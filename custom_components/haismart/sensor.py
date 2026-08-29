"""Sensors decoded from the AC's status reports.

Only fields the read path actually decodes become entities. The air-quality/humidity suite exists
only on units whose own model declares the probe (a basic cooling unit reports no such hardware —
those attributes read a constant 0 in its report, and it gets no entity for them).

Units that answer the extended-status query also expose the running power draw, compressor current
and compressor frequency. `power` is published as a MEASUREMENT in watts.

A few units additionally keep a cumulative energy total of their own, and those get an Energy
sensor that the Energy dashboard can use directly. Most do not: their register exists but stays at
zero for the unit's whole life, and for those the way to get a kWh total is still a Riemann-sum
integral helper over the power sensor — see the README.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from haismart_hrdp import OPTIONAL_ENUM_FEATURES, vane_position_name
from homeassistant.components.sensor import (
    DOMAIN as SENSOR_DOMAIN,
)
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .const import (
    CONF_HOST,
    CONF_LOCALKEY_VERSION,
    CONF_PRODUCT_CODE,
    CONF_UPLUS_ID,
    DOMAIN,
)
from .coordinator import _VANE_ENDS, HaismartConfigEntry, HaismartCoordinator
from .entity import HaismartEntity

# Newer Home Assistant renamed these two air-quality units. The old flat constants still work but
# log a deprecation warning, while the new UnitOf* names do not exist on the version this
# integration still supports (see hacs.json) -- so prefer the new, fall back to the old, both quiet.
try:
    from homeassistant.const import UnitOfDensity, UnitOfRatio

    _UG_PER_M3 = UnitOfDensity.MICROGRAMS_PER_CUBIC_METER
    _PPM = UnitOfRatio.PARTS_PER_MILLION
except ImportError:
    from homeassistant.const import (  # noqa: I001
        CONCENTRATION_MICROGRAMS_PER_CUBIC_METER as _UG_PER_M3,
        CONCENTRATION_PARTS_PER_MILLION as _PPM,
    )


@dataclass(frozen=True, kw_only=True)
class HaismartSensorDescription(SensorEntityDescription):
    value_fn: Callable[[dict[str, Any]], float | None]


SENSORS: tuple[HaismartSensorDescription, ...] = (
    HaismartSensorDescription(
        key="current_temperature",
        translation_key="indoor_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda s: s.get("current_temperature"),
    ),
    HaismartSensorDescription(
        key="outdoor_temperature",
        translation_key="outdoor_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda s: s.get("outdoor_temperature"),
    ),
    HaismartSensorDescription(
        key="last_changed_by",
        translation_key="last_changed_by",
        device_class=SensorDeviceClass.ENUM,
        options=["other", "remote", "panel", "network"],
        entity_category=EntityCategory.DIAGNOSTIC,
        # The unit says who made the last change, which lets an automation react to someone
        # picking up the handset rather than to the change itself.
        value_fn=lambda s: s.get("last_changed_by"),
    ),
    # --- running power / compressor figures, from the extended-status report ---------------------
    # Present only on units that answer the extended query; `native_value` returns None on the rest,
    # so these exist but stay unavailable rather than appearing and vanishing between polls.
    #
    # They deliberately carry no name or translation_key: with `has_entity_name`, an unnamed entity
    # takes its name from its device class, which Home Assistant already translates into every
    # language it ships. Naming them here would mean 30 new translation files for no gain.
    HaismartSensorDescription(
        key="power_w",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        # Read from the unit's own register, which the published map states is in watts -- not a
        # figure computed here. On the units measured so far the register tracks the current sensor
        # closely enough to look calculated, but that is the firmware's business: what reaches this
        # entity is what the air conditioner reports.
        #
        # Diagnostic, which groups it with the rest of the engineering telemetry. MEASUREMENT, so it
        # records into long-term statistics and a Riemann-sum helper can turn it into the kWh the
        # Energy dashboard needs on the units that keep no total of their own.
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.get("power_w"),
    ),
    # Cumulative energy, from the unit's own register — on the units that keep one. It is a running
    # total the air conditioner maintains across restarts and outages, so it is exactly what the
    # Energy dashboard wants, and TOTAL_INCREASING lets Home Assistant handle the reset if the unit
    # is ever replaced or the register wraps.
    #
    # Not diagnostic: this one is a headline reading rather than an engineering aid, and the Energy
    # dashboard is where it belongs. It is stated in watt-hours because that is what the register
    # counts, and displayed in kWh because that is what anyone reading it wants.
    #
    # The register is absent (rather than zero) on every unit whose firmware does not populate it,
    # so this sensor exists everywhere and stays unavailable on the units that keep no total.
    HaismartSensorDescription(
        key="energy_wh",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda s: s.get("energy_wh"),
    ),
    HaismartSensorDescription(
        key="compressor_current_a",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.get("compressor_current_a"),
    ),
    HaismartSensorDescription(
        key="compressor_frequency_hz",
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.get("compressor_frequency_hz"),
    ),
    # Refrigeration-circuit temperatures, also from the extended report. Diagnostic: useful for
    # spotting a unit that is running but not actually cooling (a cold coil while cooling, a hot
    # discharge line). They carry a translation_key because "temperature" alone is ambiguous once
    # there are several — the device-class name would make three identical "Temperature" entities.
    HaismartSensorDescription(
        key="coil_temperature",
        translation_key="coil_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.get("coil_temperature"),
    ),
    HaismartSensorDescription(
        key="discharge_temperature",
        translation_key="discharge_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.get("discharge_temperature"),
    ),
    # NB the outdoor unit's own coil / air-intake / defrost probes are decoded from this same report
    # (see `parse_extended_status`) and reach a diagnostics download, but are deliberately NOT
    # entities: they read a constant zero (absent) on the reference hardware, so as sensors they
    # would sit at `unknown` for the life of the install -- worse than not existing. A unit that
    # genuinely reports one is the evidence that would promote it, the bar every reading here meets.
)


def _reading(attribute: str) -> Callable[[dict[str, Any]], float | None]:
    return lambda s: (s.get("readings") or {}).get(attribute)


# The air-quality/humidity readings a unit's own model may declare (PM2.5 probes, CO2, formaldehyde,
# VOC, the humidity probe), decoded from the status report at the published-map positions. Created
# only for the attributes the device declares and does not mark invisible — most units carry none of
# these, and an entity for a probe the hardware lacks would read a permanent unknown.
#
# CO2 and humidity carry no name on purpose: with `has_entity_name`, an unnamed entity takes its
# name from its device class, which Home Assistant already translates. The rest are named because
# their device-class name alone would be wrong (two PM2.5 sensors would collide) or does not exist
# (formaldehyde, a unitless VOC index).
# The optional numeric readings that become sensors, by the attribute name the device declares.
# Air quality and humidity, plus the purifier's hour meter -- everything `OPTIONAL_NUMERIC_READINGS`
# can place. A declared reading with no entry here is simply not surfaced.
OPTIONAL_READING_SENSORS: dict[str, HaismartSensorDescription] = {
    "indoorPM2p5Value": HaismartSensorDescription(
        key="indoor_pm25",
        translation_key="indoor_pm25",
        device_class=SensorDeviceClass.PM25,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=_UG_PER_M3,
        value_fn=_reading("indoorPM2p5Value"),
    ),
    "outdoorPM2p5Value": HaismartSensorDescription(
        key="outdoor_pm25",
        translation_key="outdoor_pm25",
        device_class=SensorDeviceClass.PM25,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=_UG_PER_M3,
        value_fn=_reading("outdoorPM2p5Value"),
    ),
    "co2Value": HaismartSensorDescription(
        key="co2",
        device_class=SensorDeviceClass.CO2,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=_PPM,
        value_fn=_reading("co2Value"),
    ),
    "ch2oValue": HaismartSensorDescription(
        key="formaldehyde",
        translation_key="formaldehyde",
        # No formaldehyde device class exists; the unit is the published one (ug/m3).
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=_UG_PER_M3,
        value_fn=_reading("ch2oValue"),
    ),
    "vocValue": HaismartSensorDescription(
        key="voc_level",
        translation_key="voc_level",
        # A unitless 0..1023 index — the models publish no unit for it, so neither VOC device class
        # (both of which prescribe a concentration unit) may be claimed for it.
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_reading("vocValue"),
    ),
    "indoorHumidity": HaismartSensorDescription(
        key="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=_reading("indoorHumidity"),
    ),
    "totalCleaningTime": HaismartSensorDescription(
        key="purifier_hours",
        translation_key="purifier_hours",
        device_class=SensorDeviceClass.DURATION,
        # It only ever counts up, so it is a total rather than a measurement -- which is what lets
        # a dashboard show hours-since as well as hours-total. The unit is the model's own (`h`).
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfTime.HOURS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_reading("totalCleaningTime"),
    ),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HaismartConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    # Create every sensor unconditionally and let `native_value` return None when a reading is
    # absent.
    # Gating creation on the FIRST poll's values meant a sensor missing at setup (a failed first
    # refresh, or a report whose layout we can only partially decode) never appeared until the entry
    # was reloaded.
    # ...with one exception: a reading the appliance has already told us it does not produce. That
    # verdict is remembered on the entry, so those entities are not created here at all rather than
    # being created and removed again on every restart. Absence is never enough for this -- only a
    # refusal, which is what `absent_readings` records.
    absent = coordinator.absent_readings
    entities: list[SensorEntity] = [
        HaismartSensor(coordinator, desc) for desc in SENSORS if desc.key not in absent
    ]
    # opt-in backup entity: exposes the localKey so it rides along in HA backups / can be copied.
    # It's a secret, so it's diagnostic + DISABLED by default (enable it, back it up, done).
    entities.append(HaismartModelIdSensor(coordinator))
    entities.append(HaismartLocalKeySensor(coordinator))
    # Read-only enum state for the multi-state optional features a unit declares that the app shows
    # no control for. The ones it renders a select for (and this unit can write) become select
    # entities instead, so they are excluded here to avoid a select and a sensor for the same thing.
    promoted = set(coordinator.panel_select_fields())
    for name in sorted(coordinator.declared_enum_features - promoted):
        entities.append(HaismartFeatureEnumSensor(coordinator, name))
    # Air-quality/humidity readings, for the probes this unit's own model declares (and its family
    # can place). Not read-backed: zero means "absent" for these values, so existence comes from the
    # declaration and the value handles its own absence.
    for name in sorted(coordinator.declared_numeric_readings):
        if desc := OPTIONAL_READING_SENSORS.get(name):
            entities.append(HaismartSensor(coordinator, desc))
    # Where each vane points, for an axis this unit reports but cannot be commanded to move — the
    # writable ones are selects instead, so the two never both appear for one axis.
    reporting = {key for key, _, _ in coordinator.vane_position_axes()}
    for key, attribute, codes in coordinator.vane_position_axes():
        entities.append(HaismartVanePositionSensor(coordinator, key, attribute, codes))
    _drop_superseded_vane_sensors(hass, coordinator, reporting)
    # "Last self-clean" — only where self-clean is a real control (same gate as the button).
    if coordinator.supports_field("selfCleaningStatus"):
        entities.append(HaismartLastSelfCleanSensor(coordinator))
    async_add_entities(entities)


def _drop_superseded_vane_sensors(
    hass: HomeAssistant, coordinator: HaismartCoordinator, reporting: set[str]
) -> None:
    """Remove the read-only position sensor for an axis that has since become a control.

    An axis starts read-only and can become writable -- that is what happened to the central
    cabinets, whose vane commands were settled by the appliances themselves. Home Assistant does not
    forget an entity just because a platform stops creating it: the registry row survives, and the
    entity lingers holding whatever it last read. So the owner would be left with a position sensor
    frozen at some old stop, sitting beside a select showing where the vane actually is -- two
    entities for one vane, disagreeing, and the stale one is the one an automation might already
    reference.

    Only rows this integration owns are touched, and only for an axis that is no longer reported
    this way. An axis that is still read-only keeps its sensor, which is the whole point of it.
    """
    registry = er.async_get(hass)
    for key, slug in _VANE_SLUGS.items():
        if key in reporting:
            continue
        unique_id = f"{coordinator.device_id}_{slug}"
        if entity_id := registry.async_get_entity_id(SENSOR_DOMAIN, DOMAIN, unique_id):
            registry.async_remove(entity_id)


class HaismartLastSelfCleanSensor(HaismartEntity, RestoreEntity, SensorEntity):
    """When the most recent self-clean cycle finished — the app's "days since last clean".

    A timestamp sensor renders as relative time ("3 days ago") on the dashboard, which *is* the
    days-since display, and an automation can compare it to ``now()`` to remind when a clean is
    overdue. It updates when the self-clean status goes from on to off — a cycle *completing* —
    whether it was started from this button, the handset, or a schedule, and is restored across
    restarts so a reminder survives one. Anchoring on completion rather than the start also catches
    a cycle that was already running when the sensor came up (it records when that one ends).
    """

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "last_self_clean"

    def __init__(self, coordinator: HaismartCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_last_self_clean"
        self._last_clean: datetime | None = None
        self._was_cleaning: bool | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None and last.state not in (
            STATE_UNKNOWN,
            STATE_UNAVAILABLE,
        ):
            self._last_clean = dt_util.parse_datetime(last.state)

    @callback
    def _handle_coordinator_update(self) -> None:
        running = (self.coordinator.data or {}).get("self_cleaning")
        if running is not None:
            # Record the moment a cycle *finishes* (on -> off). Anchoring on completion means a
            # cycle already running when this sensor came up is still dated (when it ends), which
            # anchoring on the start would miss.
            if not running and self._was_cleaning:
                self._last_clean = dt_util.utcnow()
            self._was_cleaning = bool(running)
        super()._handle_coordinator_update()

    @property
    def native_value(self) -> datetime | None:
        return self._last_clean


class HaismartFeatureEnumSensor(HaismartEntity, SensorEntity):
    """One declared multi-state optional feature, read-only, as a labelled enum sensor."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: HaismartCoordinator, attribute: str) -> None:
        super().__init__(coordinator)
        slug, states = OPTIONAL_ENUM_FEATURES[attribute]
        self._attribute = attribute
        self._attr_translation_key = slug
        self._attr_unique_id = f"{coordinator.device_id}_{slug}"
        self._attr_options = sorted(set(states.values()))

    @property
    def native_value(self) -> str | None:
        return ((self.coordinator.data or {}).get("features_enum") or {}).get(self._attribute)


#: The decode key of each vane axis -> its entity slug, which reuses the select's own vocabulary
#: (they are mutually exclusive, so the same wording serves both).
_VANE_SLUGS = {"swing_vertical": "vane_vertical_position",
               "swing_horizontal": "vane_horizontal_position"}


class HaismartVanePositionSensor(HaismartEntity, SensorEntity):
    """Where one vane points, on a unit whose vane can be READ but not commanded.

    The climate entity reduces a vane to "is it sweeping", which is the right answer for a swing
    control and throws the stop away -- a vane parked at a real position reads exactly like one held
    closed. Where the axis is writable a select shows the stop and this does not exist; where it is
    not (a cabinet written one setting at a time, whose vane commands are withheld for want of an
    observed acceptance) the appliance still reports its vanes in every status frame, and this says
    so rather than leaving the reading on the floor.
    """

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coordinator: HaismartCoordinator, key: str, attribute: str, codes: frozenset[int]
    ) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attribute = attribute
        self._codes = codes
        self._ends = _VANE_ENDS[key]
        slug = _VANE_SLUGS[key]
        self._attr_translation_key = slug
        self._attr_unique_id = f"{coordinator.device_id}_{slug}"
        self._attr_options = sorted(
            {vane_position_name(c, codes, *self._ends, attribute) for c in codes},
            key=lambda o: (o != "fixed", o == "auto", o),
        )

    @property
    def native_value(self) -> str | None:
        code = self.coordinator.vane_position_code(self._key)
        if code is None or code not in self._codes:
            # A unit can park a vane at a stop its own model does not list (the special modes do
            # exactly that). Unknown beats naming an option this entity never offered.
            return None
        return vane_position_name(code, self._codes, *self._ends, self._attribute)


class HaismartSensor(HaismartEntity, SensorEntity):
    entity_description: HaismartSensorDescription

    def __init__(
        self, coordinator: HaismartCoordinator, description: HaismartSensorDescription
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.device_id}_{description.key}"

    @property
    def native_value(self) -> float | None:
        if not self.coordinator.data:
            return None
        return self.entity_description.value_fn(self.coordinator.data)


class HaismartModelIdSensor(HaismartEntity, SensorEntity):
    """The AC's uPlusId — the identifier that selects its report layout.

    Enabled by default, unlike the localKey sensor it used to be an attribute of. The two were
    coupled only because they are both wanted for a manual re-add, but they are not alike: the
    localKey is a secret, whereas the uPlusId is a model identifier shared by every unit of that
    model. Reading your model ID should not require enabling an entity whose state is your key.

    It is what a bug report about an undecoded model needs, and it is now obtainable with no cloud
    account at all -- the air conditioner reports it over the key-free discovery query.
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "uplus_id"
    _attr_icon = "mdi:identifier"

    def __init__(self, coordinator: HaismartCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_uplus_id"

    @property
    def native_value(self) -> str | None:
        """A shortened form, because the identifier is 64 characters and overflows the UI.

        Home Assistant caps a state at 255 characters but offers nothing like the numeric
        `suggested_display_precision` for strings, so a long identifier simply runs past the edge of
        an entity row. The full value is on the `uplus_id` attribute (and in diagnostics, and in the
        config entry), which is where anything machine-readable should read it from anyway.

        The elided middle is the run of padding zeros; the head identifies the family and the tail
        keeps the two ends distinguishable.
        """
        uplus = self.coordinator.uplus_id
        if not uplus:
            # None (unknown) rather than "" on a unit we have never learned it for -- e.g. a manual
            # entry whose AC does not answer the discovery query.
            return None
        return f"{uplus[:16]}\u2026{uplus[-4:]}" if len(uplus) > 24 else uplus

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            CONF_PRODUCT_CODE: self.coordinator.product_code,
            # the exact identifier -- quote THIS in a report, not the shortened state
            CONF_UPLUS_ID: self.coordinator.uplus_id or None,
        }


class HaismartLocalKeySensor(HaismartEntity, SensorEntity):
    """The AC's current localKey, for backup/export. Diagnostic + disabled by default (a secret).

    Enable it to see/copy the key (it rides along in HA backups); the attributes carry all the
    `manual` onboarding path needs (host + deviceId + version + uPlusId), a one-stop
    cloud-independent backup.
    Stays current across localKey rotation (the coordinator updates it in place)."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_translation_key = "local_key"
    _attr_icon = "mdi:key-variant"

    def __init__(self, coordinator: HaismartCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_local_key"

    @property
    def native_value(self) -> str:
        return self.coordinator.local_key

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self.coordinator
        return {
            CONF_HOST: c.host,
            "device_id": c.device_id,
            CONF_LOCALKEY_VERSION: c.localkey_version,
            CONF_PRODUCT_CODE: c.product_code,
            # The wire-model key. Worth backing up alongside the localKey: with both, a manual
            # re-add decodes the AC exactly as a cloud-onboarded one would, with no account.
            CONF_UPLUS_ID: c.uplus_id,
        }
