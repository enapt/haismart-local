"""Running-state binary sensors from the AC's extended report.

Present only on units that report the extended figures; on the rest they stay unavailable rather
than showing a made-up "off". Names live in strings.json via `translation_key`.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

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
    entities: list[BinarySensorEntity] = [
        HaismartBinarySensor(coordinator, desc) for desc in BINARY_SENSORS
    ]
    entities.append(HaismartCloudConnectionSensor(coordinator))
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
