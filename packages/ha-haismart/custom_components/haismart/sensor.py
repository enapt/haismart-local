"""Sensors decoded from the AC's status reports.

Only fields the read path actually decodes become entities (a basic cooling unit reports no
humidity/air-quality hardware — those attributes read 0 in the report and are skipped).

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

from haismart_hrdp import OPTIONAL_ENUM_FEATURES
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .const import CONF_HOST, CONF_LOCALKEY_VERSION, CONF_PRODUCT_CODE, CONF_UPLUS_ID
from .coordinator import HaismartConfigEntry, HaismartCoordinator
from .entity import HaismartEntity


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
)


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
    # Read-only enum state for the multi-state optional features a unit declares (presence-based
    # airflow and the like). Membership from the model, position from the map -- same safe basis as
    # the feature binary sensors, and read-only for the same reason.
    for name in sorted(coordinator.declared_enum_features):
        entities.append(HaismartFeatureEnumSensor(coordinator, name))
    # "Last self-clean" — only where self-clean is a real control (same gate as the button).
    if coordinator.supports_field("selfCleaningStatus"):
        entities.append(HaismartLastSelfCleanSensor(coordinator))
    async_add_entities(entities)


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
