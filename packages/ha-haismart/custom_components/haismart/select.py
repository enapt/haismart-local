"""Select entities: the multi-level ECO control, and the left-right vane's position.

ECO is a 3-bit field (word4 b3-5) with values {0=off, 5, 6, 7} = off / L1 / L2 / L3, matching the
remote's "ECO L1/L2/L3". It is NOT the digital model's energySavingStatus bool. The library refuses
any code outside {0,5,6,7}. The levels are a compressor current limit — a higher level caps harder,
so the unit draws less and cools more slowly (confirmed by measurement).

The left-right vane is a position code rather than a flag, so where a unit's model publishes the
positions between "fixed" and "auto" they can be selected. The climate entity's swing controls stay
as they are and still express the two ends; this adds the stops in between, which no climate feature
can carry. The up-down vane is a position code too but is not offered: its wire values are not the
codes its model names, so there is nothing to authorize the intermediate stops with.
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

_VANE_H = "windDirectionHorizontal"
_VANE_H_ENUM = GRSETDAC_ENUMS[_VANE_H]
_VANE_H_FIXED, _VANE_H_AUTO = _VANE_H_ENUM["off"], _VANE_H_ENUM["on"]
# The two ends have names; the stops between them are numbered as the model numbers them, which is
# one higher than the code (the model's "position four" is code 3). Nothing is offered that the
# device's own model does not list, so the tokens here are a superset of what any one unit shows.
_VANE_H_NAMED = {_VANE_H_FIXED: "fixed", _VANE_H_AUTO: "auto"}


def _vane_h_option(code: int) -> str:
    return _VANE_H_NAMED.get(code) or f"position_{code + 1}"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HaismartConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[SelectEntity] = []
    # This unit's multi-level eco is a repurposed 3-bit field that no other wire family maps, so on
    # those the select could only ever raise — leave it out rather than offer it.
    if coordinator.supports_field("ecoMode"):
        entities.append(HaismartEcoSelect(coordinator))
    # Only worth an entity where the model publishes stops the swing control cannot already reach:
    # a unit that lists nothing but fixed and auto is fully served by `swing_horizontal_mode`.
    vane_codes = coordinator.field_codes(_VANE_H)
    if vane_codes - {_VANE_H_FIXED, _VANE_H_AUTO}:
        entities.append(HaismartVaneHorizontalSelect(coordinator, vane_codes))
    async_add_entities(entities)


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


class HaismartVaneHorizontalSelect(HaismartEntity, SelectEntity):
    """Where the left-right vane points, for the units whose model publishes the positions.

    The options are built from that model rather than from a fixed list: a unit that lists six
    stops gets six, and one that lists two never reaches here at all.
    """

    _attr_translation_key = "vane_horizontal"

    def __init__(self, coordinator: HaismartCoordinator, codes: frozenset[int]) -> None:
        super().__init__(coordinator)
        self._codes = {_vane_h_option(code): code for code in sorted(codes)}
        self._attr_options = list(self._codes)
        self._attr_unique_id = f"{coordinator.device_id}_vane_horizontal"

    @property
    def current_option(self) -> str | None:
        code = self.coordinator.current_field(_VANE_H)
        if code is None:
            return None
        # A unit can report a stop its own model does not list. Report that as unknown rather than
        # as an option this entity does not offer, which Home Assistant would refuse anyway.
        option = _vane_h_option(code)
        return option if option in self._codes else None

    async def async_select_option(self, option: str) -> None:
        code = self._codes.get(option)
        if code is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unsupported_value",
                translation_placeholders={
                    "name": self.name or "this air conditioner",
                    "value": str(option),
                    "field": "left-right vane",
                },
            )
        await self.coordinator.async_send_control({_VANE_H: code})
