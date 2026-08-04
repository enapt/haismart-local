"""Running-state binary sensors from the AC's extended report.

Present only on units that report the extended figures; on the rest they stay unavailable rather
than showing a made-up "off". Names live in strings.json via `translation_key`.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from haismart_hrdp import OPTIONAL_BOOL_FEATURES
from haismart_hrdp.udiscovery import CLOUD_STATES
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import HaismartConfigEntry, HaismartCoordinator
from .entity import HaismartEntity


@dataclass(frozen=True, kw_only=True)
class HaismartBinarySensorDescription(BinarySensorEntityDescription):
    value_fn: Callable[[dict[str, Any]], bool | None]


BINARY_SENSORS: tuple[HaismartBinarySensorDescription, ...] = (
    HaismartBinarySensorDescription(
        key="compressor_running",
        translation_key="compressor",
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.get("compressor_running"),
    ),
    HaismartBinarySensorDescription(
        key="fan_running",
        translation_key="fan",
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.get("fan_running"),
    ),
    HaismartBinarySensorDescription(
        key="self_cleaning",
        translation_key="self_cleaning",
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
        # Reported, not controlled. The cycle runs to completion and ignores a second press, so
        # there is nothing a switch could usefully do with an "off".
        value_fn=lambda s: s.get("self_cleaning"),
    ),
    HaismartBinarySensorDescription(
        key="fault",
        translation_key="fault",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        # `alarm_count` is absent until a fault frame has been seen, which must read as unknown
        # rather than "no fault" -- a unit we have not heard from is not a healthy one.
        value_fn=lambda s: None if s.get("alarm_count") is None else s["alarm_count"] > 0,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HaismartConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    if coordinator.is_ac is False:
        # Fault frames, optional features and the UDISCOVERY cloud link are AC concepts; a washer
        # reports none of them.
        return
    entities: list[BinarySensorEntity] = [
        HaismartBinarySensor(coordinator, desc) for desc in BINARY_SENSORS
    ]
    entities.append(HaismartCloudConnectionSensor(coordinator))
    # Read-only observability for the extra features a unit's own model declares -- fresh air,
    # electric-heat, ambient light, and the rest a unit may declare. Which ones exist comes
    # from the device model; where each sits comes from the published map; the value is the bit at
    # that position. Only families with a confirmed map displacement produce any, so a device on an
    # unpinned family simply gets none. Not controls: a group-set write of one of these applies the
    # whole word block, which needs its own confirmation -- these are state, not switches.
    for name in sorted(coordinator.declared_features):
        entities.append(HaismartFeatureSensor(coordinator, name))
    async_add_entities(entities)


class HaismartCloudConnectionSensor(HaismartEntity, BinarySensorEntity):
    """Whether the AC itself can currently reach Haier's cloud.

    Answered by the appliance over the key-free UDISCOVERY query on UDP :7083 -- no account, no
    localKey, and no request to Haier -- which is what makes it usable as verification for someone
    who has deliberately firewalled the unit. `on` means the AC is talking to the cloud; `off` means
    it is cut off, which for that user is the desired state.

    Note the asymmetric latency: losing the cloud appears after about two minutes and settles a
    couple of minutes after that, while regaining it takes about ten seconds. `None` -- unknown --
    when the unit does not answer the query at all, never a fabricated `off`.
    """

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "cloud_connection"

    def __init__(self, coordinator: HaismartCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_cloud_connection"

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.cloud_connected

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        # Three codes have been observed (connected / retrying / disconnected); the label is None
        # for anything else, which is a datapoint worth reporting rather than flattening away.
        return {
            "raw_state": self.coordinator.cloud_state,
            "state_name": CLOUD_STATES.get(self.coordinator.cloud_state or -1),
        }


class HaismartFeatureSensor(HaismartEntity, BinarySensorEntity):
    """One declared boolean feature, read-only, from the device's own model + the published map.

    The attribute name (``freshAirStatus``) is the model's; the translation slug
    (``fresh_air``) is ours. Diagnostic, and ``None`` until a report carries it -- a feature a unit
    declares but has not yet reported reads unknown, never a fabricated off.
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: HaismartCoordinator, attribute: str) -> None:
        super().__init__(coordinator)
        self._attribute = attribute
        self._attr_translation_key = OPTIONAL_BOOL_FEATURES[attribute]
        self._attr_unique_id = f"{coordinator.device_id}_{OPTIONAL_BOOL_FEATURES[attribute]}"

    @property
    def is_on(self) -> bool | None:
        features = (self.coordinator.data or {}).get("features") or {}
        return features.get(self._attribute)


class HaismartBinarySensor(HaismartEntity, BinarySensorEntity):
    entity_description: HaismartBinarySensorDescription

    def __init__(
        self, coordinator: HaismartCoordinator, description: HaismartBinarySensorDescription
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.device_id}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        if not self.coordinator.data:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Name the active faults on the fault sensor, so "problem" is actionable rather than a
        bare flag. Absent on the other sensors, which have nothing to add."""
        if self.entity_description.key != "fault" or not self.coordinator.data:
            return None
        data = self.coordinator.data
        if data.get("alarm_count") is None:
            return None
        return {
            "faults": data.get("alarm_labels") or [],
            "fault_codes": data.get("alarm_codes") or [],
            # a second, independent view: the status report names one fault where the fault frame
            # carries the whole set, so a disagreement is itself worth seeing
            "error_code": data.get("error_code"),
        }
