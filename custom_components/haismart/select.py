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

from haismart_hrdp import GRSETDAC_ENUMS, PANEL_ENUM_CONTROLS
from haismart_hrdp.wire_models import VANE_V_EPP_TO_MODEL, vane_position_name
from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

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
    # The panel's multi-state controls (presence-based airflow, fresh-air fan level): functions the
    # app renders a select for and this unit declares. Offered the way the app offers them.
    for field in coordinator.panel_select_fields():
        entities.append(HaismartPanelSelect(coordinator, field))
    async_add_entities(entities)


class HaismartEcoSelect(HaismartEntity, SelectEntity):
    _attr_translation_key = "eco"
    _attr_options = list(_ECO)

    def __init__(self, coordinator: HaismartCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_eco"

    # No `available` override. The model states when a unit ignores its economy setting -- fan-only
    # and auto both do -- but that is a normal operating state, not a fault, and it is what the
    # setting still reads as. Going unavailable said "broken" and lost the reading; the command is
    # refused instead, with the model's own reason.

    @property
    def current_option(self) -> str | None:
        value = self.coordinator.current_field("ecoMode")
        return None if value is None else _ECO_REVERSE.get(value)

    async def async_select_option(self, option: str) -> None:
        self.raise_if_locked("ecoMode")
        code = _ECO.get(option)
        if code is None:
            self.raise_unsupported_value(option, "eco")
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
        """Name one stop. Shared with the read-only position sensor, so a writable axis and a
        read-only one can never name the same stop differently.

        ⚠️ **This entity works in WIRE codes and the naming is done in the MODEL's.** The two spaces
        part company above the second stop on the up-down axis, so the stop the vendor calls its
        second automatic sweep is wire ``14`` here and ``9`` in the manual. Naming it from the wire
        number would rank it as an ordinary position while the sensor, which already works in the
        model's codes, named it correctly -- the same stop under two names, which is exactly what
        sharing this function is meant to make impossible.
        """
        std = self._to_model(code)
        return vane_position_name(
            std, {self._to_model(c) for c in codes},
            self._to_model(self._vane.fixed), self._to_model(self._vane.auto), self._vane.field,
        )

    def _to_model(self, code: int) -> int:
        """A wire code in the space this device's own model publishes. Identity on left-right."""
        if self._vane.field != "windDirectionVertical":
            return code
        return VANE_V_EPP_TO_MODEL.get(code, code)

    # No `available` override, for the same reason as the economy setting above: a faulted unit, or
    # one running a self-clean cycle, will not move its vanes -- but it still reports where they
    # are, and that reading is worth keeping. The command is refused instead.

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
        self.raise_if_locked(self._vane.field)
        code = self._codes.get(option)
        if code is None:
            self.raise_unsupported_value(option, self._vane.key)
        await self.coordinator.async_send_control({self._vane.field: code})


class HaismartPanelSelect(HaismartEntity, SelectEntity):
    """A multi-state panel control (presence-based airflow, fresh-air fan level).

    Options are the vendor's own state tokens for the attribute (:data:`PANEL_ENUM_CONTROLS`); the
    raw wire value maps to and from them. Read back from the same position it writes (the
    write<->read relation), so it shows the unit's real state and the command can be checked.
    """

    def __init__(self, coordinator: HaismartCoordinator, field: str) -> None:
        super().__init__(coordinator)
        self._field = field
        slug, states = PANEL_ENUM_CONTROLS[field]
        self._to_token = dict(states)               # wire value -> token
        # Only the values this family can actually carry are offered; the rest would be a control
        # that refuses whenever they are chosen (compact-12 has one bit here, not two). Reading is
        # unrestricted — the appliance may report a state its own controller set that no command of
        # ours could ask for, and showing that is the point of reading it back.
        offered = coordinator.panel_select_codes(field) or frozenset(states)
        self._to_value = {states[v]: v for v in sorted(offered) if v in states}
        self._attr_translation_key = slug
        self._attr_unique_id = f"{coordinator.device_id}_{slug}"
        self._attr_options = [states[v] for v in sorted(offered) if v in states]

    # No `available` override: a setting the unit currently ignores is not a fault (see the vane
    # select above); the command is refused with the model's reason instead.

    @property
    def current_option(self) -> str | None:
        value = self.coordinator.current_field(self._field)
        return None if value is None else self._to_token.get(value)

    async def async_select_option(self, option: str) -> None:
        self.raise_if_locked(self._field)
        value = self._to_value.get(option)
        if value is None:
            self.raise_unsupported_value(option, self._attr_translation_key or self._field)
        await self.coordinator.async_send_control({self._field: value})
