"""Select entities: the multi-level ECO control, and where each vane points.

ECO is off / L1 / L2 / L3, matching the remote's "ECO L1/L2/L3". It is NOT the digital model's
energySavingStatus bool. The levels are a compressor current limit — a higher level caps harder, so
the unit draws less and cools more slowly, which has been measured on two unrelated families: one
steps 1350 → 1130 → 800 W across the three levels, the other 1951 → 1798 → 1205 W.

This entity speaks one representation, {0=off, 5, 6, 7}, whatever the unit packs on the wire; the
family's own map translates, and refuses any code outside the four. Which is worth knowing before
reading a capture: the classic family really does use 5/6/7, while another spends two bits on the
same setting and counts them 1/2/3.

Both vanes are position codes rather than flags, so where a unit's model publishes the stops between
"fixed" and "auto" they can be selected. The climate entity's swing controls stay as they are and
still express the two ends; these add the stops in between, which no climate feature can carry.

The options are built per device from its own model, and named for the position's place in that
model's list — its "position one" is the first stop it offers, whatever code that stop happens to
use. The up-down axis needs one more step, because its model codes are not its wire values; the
coordinator translates before anything here sees them, so both axes are wire values by the time they
arrive.
"""
from __future__ import annotations

from dataclasses import dataclass

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


@dataclass(frozen=True)
class _Vane:
    """One vane axis: the field it writes, and the two wire values that are not positions."""

    field: str
    key: str            # entity translation key / unique-id suffix
    fixed: int
    auto: int


_VANES = (
    _Vane(
        field="windDirectionVertical",
        key="vane_vertical",
        fixed=GRSETDAC_ENUMS["windDirectionVertical"]["off"],
        auto=GRSETDAC_ENUMS["windDirectionVertical"]["on"],     # 0x0c, the long-known auto nibble
    ),
    _Vane(
        field="windDirectionHorizontal",
        key="vane_horizontal",
        fixed=GRSETDAC_ENUMS["windDirectionHorizontal"]["off"],
        auto=GRSETDAC_ENUMS["windDirectionHorizontal"]["on"],
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HaismartConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    if coordinator.is_ac is False:
        # Non-AC appliances (washers) have no eco/vane controls.
        return
    entities: list[SelectEntity] = []
    # Not every family places the economy setting, and on the ones that reach it through the
    # published map it is offered only where the device itself declares it — see `supports_eco`.
    if coordinator.supports_eco:
        entities.append(HaismartEcoSelect(coordinator))
    for vane in _VANES:
        # Only worth an entity where the model publishes stops the swing control cannot already
        # reach: a unit listing nothing but fixed and auto is fully served by the climate entity.
        codes = coordinator.field_codes(vane.field)
        if codes - {vane.fixed, vane.auto}:
            entities.append(HaismartVaneSelect(coordinator, vane, codes))
    async_add_entities(entities)


class HaismartEcoSelect(HaismartEntity, SelectEntity):
    _attr_translation_key = "eco"
    _attr_options = list(_ECO)

    def __init__(self, coordinator: HaismartCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_eco"

    @property
    def available(self) -> bool:
        # The model states when a unit ignores its economy setting -- fan-only and auto both do.
        return super().available and "ecoMode" not in self.coordinator.locked_fields

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


class HaismartVaneSelect(HaismartEntity, SelectEntity):
    """Where one vane points, on the units whose model publishes its positions.

    The options are built from that model rather than from a fixed list: a unit that lists six stops
    gets six, and one that lists only fixed and auto never reaches here at all. Positions are
    numbered by their place in the model's list, which is what the vendor app shows for them — the
    codes themselves are not a sequence and would make a poor label.
    """

    def __init__(
        self, coordinator: HaismartCoordinator, vane: _Vane, codes: frozenset[int]
    ) -> None:
        super().__init__(coordinator)
        self._vane = vane
        self._attr_translation_key = vane.key
        self._attr_unique_id = f"{coordinator.device_id}_{vane.key}"
        self._codes = {
            self._option(code, codes): code for code in sorted(codes)
        }
        self._attr_options = list(self._codes)

    def _option(self, code: int, codes: frozenset[int]) -> str:
        if code == self._vane.fixed:
            return "fixed"
        if code == self._vane.auto:
            return "auto"
        positions = sorted(codes - {self._vane.fixed, self._vane.auto})
        return f"position_{positions.index(code) + 1}"

    @property
    def available(self) -> bool:
        # A faulted unit, or one running a self-clean cycle, will not move its vanes.
        return super().available and self._vane.field not in self.coordinator.locked_fields

    @property
    def current_option(self) -> str | None:
        code = self.coordinator.current_field(self._vane.field)
        if code is None:
            return None
        # A unit can report a stop its own model does not list — the special modes park the vane
        # at codes no model names. Report that as unknown rather than as an option this entity does
        # not offer, which Home Assistant would refuse anyway.
        option = self._option(code, frozenset(self._codes.values()))
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
                    "field": self._vane.key,
                },
            )
        await self.coordinator.async_send_control({self._vane.field: code})
