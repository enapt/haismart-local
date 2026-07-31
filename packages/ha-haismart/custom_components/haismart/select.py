"""Select entity for the AC's multi-level ECO control.

This unit's ECO is a 3-bit field (word4 b3-5) with values {0=off, 5, 6, 7} = off / L1 / L2 / L3,
matching the remote's "ECO L1/L2/L3". It is NOT the digital model's energySavingStatus bool. The
library refuses any code outside {0,5,6,7}. The levels are a compressor current limit — a higher
level caps harder, so the unit draws less and cools more slowly (confirmed by measurement).
"""
from __future__ import annotations

from haismart_hrdp import GRSETDAC_ENUMS
from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import HaismartConfigEntry, HaismartCoordinator
from .entity import HaismartEntity

_ECO = GRSETDAC_ENUMS["ecoMode"]              # token -> raw EPP code (off/level1/level2/level3)
_ECO_REVERSE = {v: k for k, v in _ECO.items()}  # raw EPP code -> token


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HaismartConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    # This unit's multi-level eco is a repurposed 3-bit field that no other wire family maps, so on
    # those the select could only ever raise — leave it out rather than offer it.
    if coordinator.supports_field("ecoMode"):
        async_add_entities([HaismartEcoSelect(coordinator)])


class HaismartEcoSelect(HaismartEntity, SelectEntity):
    _attr_translation_key = "eco"
    _attr_options = list(_ECO)

    def __init__(self, coordinator: HaismartCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_eco"

    @property
    def current_option(self) -> str | None:
        value = self.coordinator.current_field("ecoMode")
        return None if value is None else _ECO_REVERSE.get(value)

    async def async_select_option(self, option: str) -> None:
        code = _ECO.get(option)
        if code is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unsupported_value",
                translation_placeholders={
                    "name": self.name or "this air conditioner",
                    "value": str(option),
                    "field": "eco",
                },
            )
        await self.coordinator.async_send_control({"ecoMode": code})
