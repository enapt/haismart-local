"""Switch entities for the AC's boolean features (all confirmed).

Each switch flips one grSetDAC bit via the coordinator's group-set control path; the library refuses
any field that wasn't confirmed, so only these fire. App labels: strong=rapidMode,
quiet=muteStatus, health=healthMode, sleep=silentSleepStatus, lamp=screenDisplayStatus (the light).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import HaismartConfigEntry, HaismartCoordinator
from .entity import HaismartEntity


@dataclass(frozen=True, kw_only=True)
class HaismartSwitchDescription(SwitchEntityDescription):
    """A boolean grSetDAC field exposed as a switch."""

    field: str


# Names live in strings.json via `translation_key`, and icons in icons.json, which is what makes
# them translatable at all -- hardcoded `name=` strings can only ever be English. The `key` values
# are unchanged, so `unique_id` and therefore existing entity ids survive.
SWITCHES: tuple[HaismartSwitchDescription, ...] = (
    HaismartSwitchDescription(key="strong", field="rapidMode", translation_key="strong"),
    HaismartSwitchDescription(key="quiet", field="muteStatus", translation_key="quiet"),
    HaismartSwitchDescription(key="health", field="healthMode", translation_key="health"),
    HaismartSwitchDescription(key="sleep", field="silentSleepStatus", translation_key="sleep"),
    HaismartSwitchDescription(
        key="lamp", field="screenDisplayStatus", translation_key="lamp"
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HaismartConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    # Only the toggles this unit's report family can actually write. The classic family has all
    # five; compact-12 has none of them, and creating a switch there produced a control that read
    # `unknown` forever and raised the moment it was touched. Same rule the readings follow: expose
    # what the unit really has, not a button that does nothing.
    async_add_entities(
        HaismartSwitch(coordinator, desc)
        for desc in SWITCHES
        if coordinator.supports_field(desc.field)
    )


class HaismartSwitch(HaismartEntity, SwitchEntity):
    entity_description: HaismartSwitchDescription

    def __init__(
        self, coordinator: HaismartCoordinator, description: HaismartSwitchDescription
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.device_id}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        value = self.coordinator.current_field(self.entity_description.field)
        return None if value is None else bool(value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_control({self.entity_description.field: 1})

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_control({self.entity_description.field: 0})
