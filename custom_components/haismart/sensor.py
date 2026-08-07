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
from typing import Any

from haismart_hrdp import OPTIONAL_ENUM_FEATURES
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_BRAND,
    CONF_DEVICE_TYPE,
    CONF_HOST,
    CONF_LOCALKEY_VERSION,
    CONF_MODEL_NAME,
    CONF_PRODUCT_CODE,
    CONF_UPLUS_ID,
    DOMAIN,
    MANUFACTURER,
)
from .coordinator import HaismartConfigEntry, HaismartCoordinator
from .entity import HaismartEntity
from .zh_translations import ZH_EN


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


# Readings specific to non-AC appliances (washers). These are the only status sensors created for a
# unit whose digital model has no `operationMode` -- the AC-shape list above stays absent there.
WASHER_SENSORS: tuple[HaismartSensorDescription, ...] = (
    HaismartSensorDescription(
        key="doorLockStatus",
        translation_key="door_lock_status",
        device_class=SensorDeviceClass.ENUM,
        options=["true", "false"],
        value_fn=lambda s: s.get("doorLockStatus"),
    ),
    HaismartSensorDescription(
        key="targetLaundryProcedure",
        translation_key="laundry_procedure",
        device_class=SensorDeviceClass.ENUM,
        options=["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"],
        value_fn=lambda s: s.get("targetLaundryProcedure"),
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
    if coordinator.is_ac is False:
        # A washer: only the washer-shape sensors (door lock, laundry procedure) plus the metadata
        # below. The AC-shape temperature/power/compressor sensors do not exist for it.
        entities: list[SensorEntity] = [
            HaismartSensor(coordinator, desc) for desc in WASHER_SENSORS
        ]
    else:
        entities: list[SensorEntity] = [
            HaismartSensor(coordinator, desc) for desc in SENSORS + WASHER_SENSORS
        ]
    # opt-in backup entity: exposes the localKey so it rides along in HA backups / can be copied.
    # It's a secret, so it's diagnostic + DISABLED by default (enable it, back it up, done).
    entities.append(HaismartModelIdSensor(coordinator))
    entities.append(HaismartLocalKeySensor(coordinator))
    # Cloud-sourced metadata: works while the device is offline (the device list + digital model
    # are served by the cloud server, not the unit).
    entities.append(HaismartCloudOnlineSensor(coordinator))
    entities.append(HaismartMetaSensor(coordinator, "device_type", CONF_DEVICE_TYPE))
    entities.append(HaismartMetaSensor(coordinator, "product_code", CONF_PRODUCT_CODE))
    entities.append(HaismartSupportedAttributesSensor(coordinator))
    # One sensor per digital-model attribute, on their own "Supported attributes" devices so the
    # main device page keeps only the built-in sensors. The sensors split across two devices --
    # one for the attributes the cloud reports a value for, one for those without one (unit
    # offline); each attribute belongs to exactly one of them, decided at creation. The state is
    # the last-known value -- for a LIST attribute ``ValueDescription(option:description, ...)``,
    # translated to English -- with an em dash when the unit never reported one; LIST options and
    # STEP ranges also live on extra_state_attributes. The ``0``/``1`` flag in the unique id
    # sorts value-having attributes before the others on the device page (which orders by entity
    # id), each group then alphabetically by attribute name.
    model = coordinator.digital_model or {}
    attrs = [a for a in model.get("attributes") or () if a.get("name")]
    attrs.sort(key=lambda a: (a.get("value") in (None, ""), (a.get("name") or "").lower()))
    for attr in attrs:
        entities.append(HaismartAttributeSensor(coordinator, attr))
    # Read-only enum state for the multi-state optional features a unit declares (presence-based
    # airflow and the like). Membership from the model, position from the map -- same safe basis as
    # the feature binary sensors, and read-only for the same reason.
    for name in sorted(coordinator.declared_enum_features):
        entities.append(HaismartFeatureEnumSensor(coordinator, name))
    async_add_entities(entities)


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


class HaismartStaticSensor(HaismartEntity, SensorEntity):
    """A sensor sourced from the cloud device list / config entry, not the live status.

    A coordinator whose refresh is failing (a device offline for the cloud) marks every
    CoordinatorEntity unavailable; these read metadata that is available anyway -- the digital
    model, the device list and entry data -- so they stay usable.
    """

    @property
    def available(self) -> bool:
        return True


class HaismartCloudOnlineSensor(HaismartStaticSensor):
    """Whether the unit is currently online for the Haier cloud, per the cloud device list.

    Sourced from the cloud SERVER, not the unit, so it is meaningful even while the device is
    offline -- and it is exactly what distinguishes 'offline for the cloud' from 'unreachable'.
    """

    _attr_translation_key = "cloud_online"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["online", "offline"]
    _attr_icon = "mdi:cloud-question"

    def __init__(self, coordinator: HaismartCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_cloud_online"

    @property
    def native_value(self) -> str | None:
        if self.coordinator.cloud_online is None:
            return None
        return "online" if self.coordinator.cloud_online else "offline"


class HaismartMetaSensor(HaismartStaticSensor):
    """Static device metadata from the cloud device list (works while the unit is offline)."""

    def __init__(self, coordinator: HaismartCoordinator, key: str, conf_key: str) -> None:
        super().__init__(coordinator)
        self._key = key
        self._conf_key = conf_key
        self._attr_translation_key = key
        self._attr_unique_id = f"{coordinator.device_id}_{key}"

    @property
    def native_value(self) -> str | None:
        return self.coordinator.config_entry.data.get(self._conf_key) or None


def _split_list(options: list[str], limit: int = 255) -> list[str]:
    """Chunk option tokens so each piece fits HA's 255-char cap without dropping any.

    Splits only between options -- an option is never cut in half and nothing is elided with
    an ellipsis; a long list simply spans several ``option_list_N`` attributes.
    """
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for option in options:
        sep_len = 2 if current else 0  # ", " between options
        if current and current_len + sep_len + len(option) > limit:
            chunks.append(", ".join(current))
            current = [option]
            current_len = len(option)
        else:
            current.append(option)
            current_len += sep_len + len(option)
    if current:
        chunks.append(", ".join(current))
    return chunks


class HaismartSupportedAttributesSensor(HaismartStaticSensor):
    """The attributes this unit's digital model declares (names, not values).

    The digital model is served by the cloud server, so the list is available even while the
    device is offline. Values require the unit to be online.

    Each attribute also gets a sensor of its own (``HaismartAttributeSensor``); this one just
    reports the total count and how many have a last-known value.
    """

    _attr_translation_key = "supported_attributes"
    _attr_icon = "mdi:format-list-checkbox"

    def __init__(self, coordinator: HaismartCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_supported_attributes"

    def _attrs(self) -> list[dict[str, Any]]:
        model = self.coordinator.digital_model or {}
        return [a for a in model.get("attributes") or () if a.get("name")]

    @property
    def native_value(self) -> int | None:
        return len(self._attrs()) or None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = self._attrs()
        return {
            "count": len(attrs),
            "with_values": sum(1 for a in attrs if a.get("value") not in (None, "")),
        }


class HaismartAttributeSensor(HaismartStaticSensor):
    """One digital-model attribute, as a sensor of its own.

    The cloud-served digital model can declare hundreds of attributes; each becomes a sensor so
    the rows stay readable. The sensors split across two "Supported attributes" devices: one for
    the attributes the cloud currently reports a value for, one for the ones it does not (the unit
    is offline more often than not, so a live read is not always possible). An attribute belongs
    to exactly one of the two, decided at creation time from whether the model carries a value.

    The state is the last-known value the cloud reported for that attribute with its translated
    description first -- a LIST attribute reads ``ValueDescription(option:description, ...)`` so
    the current setting is immediately visible -- and an em dash when the unit never reported
    one. The translated description, raw attribute name, LIST options and STEP range also live on
    extra_state_attributes. The ``0``/``1`` flag in the unique id orders value-having
    attributes before the others on the device page, each group alphabetically by name.
    """

    _attr_icon = "mdi:format-list-checkbox"

    def __init__(self, coordinator: HaismartCoordinator, attr: dict[str, Any]) -> None:
        super().__init__(coordinator)
        self._attr = attr
        name = attr.get("name") or ""
        desc = ZH_EN.get(attr.get("desc") or "", attr.get("desc") or "")
        self._attr_name = f"{name}|{desc}" if desc else name
        value_flag = "0" if attr.get("value") not in (None, "") else "1"
        self._attr_unique_id = f"{coordinator.device_id}_attribute_{value_flag}_{name}"
        entry_data = coordinator.config_entry.data
        offline = attr.get("value") in (None, "")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.device_id, "supported_attributes_offline" if offline else "supported_attributes")},
            manufacturer=entry_data.get(CONF_BRAND) or MANUFACTURER,
            model=entry_data.get(CONF_MODEL_NAME) or coordinator.product_code,
            model_id=coordinator.product_code,
            name=f"{coordinator.config_entry.title} Supported attributes"
            + (" (offline)" if offline else ""),
        )

    @property
    def native_value(self) -> str:
        # Only the washer's supported-attribute sensors lead with name|description;
        # AC attribute sensors keep the plain value.
        heading = ""
        if self.coordinator.is_ac is False:
            name = self._attr.get("name") or ""
            desc = ZH_EN.get(self._attr.get("desc") or "", self._attr.get("desc") or "")
            heading = f"{name} | {desc}\n" if desc else f"{name}\n"
        value = self._attr.get("value")
        vr = self._attr.get("valueRange") or {}
        options: list[str] = []
        head = ""
        if vr.get("type") == "LIST":
            options, value_desc = self._list_options()
            if value not in (None, ""):
                head = value_desc or str(value)
        if value in (None, ""):
            return f"{heading}\u2014"
        text = f"{head}({', '.join(options)})" if vr.get("type") == "LIST" else str(value)
        if len(heading) + len(text) <= 255:
            return heading + text
        # A few LIST attributes carry hundreds of options; keep the current value's
        # description plus as many options as fit, the full list is on
        # extra_state_attributes.
        budget = 255 - len(heading) - 3
        kept: list[str] = []
        used = 0
        for opt in options:
            sep = 2 if kept else 0
            if used + sep + len(opt) > budget:
                break
            kept.append(opt)
            used += sep + len(opt)
        return f"{heading}{head}({', '.join(kept)}…)"

    def _list_options(self) -> tuple[list[str], str | None]:
        """The LIST options as ``data:description`` tokens (fully translated), plus the
        description of the option matching the current value, if any."""
        value = self._attr.get("value")
        options: list[str] = []
        value_desc: str | None = None
        for item in (self._attr.get("valueRange") or {}).get("dataList") or ():
            data = item.get("data")
            if data is None:
                continue
            desc = ZH_EN.get(item.get("desc") or "", item.get("desc") or "")
            options.append(f"{data}:{desc}" if desc else str(data))
            if value not in (None, "") and str(data) == str(value):
                value_desc = desc or str(data)
        return options, value_desc

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attr = self._attr
        vr = attr.get("valueRange") or {}
        attrs: dict[str, Any] = {"attribute_name": attr.get("name") or None}
        desc = attr.get("desc") or ""
        if desc:
            attrs["description"] = ZH_EN.get(desc, desc)
        if vr.get("type") == "STEP":
            step = vr.get("dataStep") or {}
            if step.get("minValue") is not None and step.get("maxValue") is not None:
                attrs["range"] = f"{step.get('minValue')}..{step.get('maxValue')}"
        if vr.get("type") == "LIST":
            # The complete list, every option translated and none elided: a single
            # option_list when it fits the 255-char cap, otherwise option_list_01..NN each
            # holding as many options as fit. Only the (capped) state is ever shortened.
            options, _ = self._list_options()
            chunks = _split_list(options)
            for i, chunk in enumerate(chunks, 1):
                key = "option_list" if len(chunks) == 1 else f"option_list_{i:02d}"
                attrs[key] = chunk
        return attrs


class HaismartModelIdSensor(HaismartStaticSensor):
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


class HaismartLocalKeySensor(HaismartStaticSensor):
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
