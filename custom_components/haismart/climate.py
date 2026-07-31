"""Climate entity — generated from the per-model AttributeProfile, with local control.

Control is the grSetDAC group-set write path. Every command is seeded from the latest full-status
report so it preserves all other attributes, and the library refuses any field/value not in its
allowlist.
"""
from __future__ import annotations

from typing import Any

from haismart_hrdp import GRSETDAC_ENUMS
from homeassistant.components.climate import (
    PRESET_BOOST,
    PRESET_ECO,
    PRESET_NONE,
    PRESET_SLEEP,
    SWING_BOTH,
    SWING_HORIZONTAL,
    SWING_OFF,
    SWING_VERTICAL,
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.components.climate.const import (
    SWING_HORIZONTAL_OFF,
    SWING_HORIZONTAL_ON,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import HaismartConfigEntry, HaismartCoordinator
from .entity import HaismartEntity

# normalized profile token <-> HA HVACMode (power/off handled separately)
_MODE_TO_HVAC = {
    "cool": HVACMode.COOL,
    "heat": HVACMode.HEAT,
    "dry": HVACMode.DRY,
    "fan_only": HVACMode.FAN_ONLY,
    "auto": HVACMode.AUTO,
}
_HVAC_TO_MODE = {v: k for k, v in _MODE_TO_HVAC.items()}

# Fan-only mode on this unit won't accept fan=auto; when entering it (or if the user picks auto
# while in it) we fall back to this concrete speed. "medium" is a neutral default airflow.
_FAN_ONLY_DEFAULT_SPEED = "medium"

# The comfort modes as Home Assistant's standard presets, in the order they are offered. Each is one
# CONFIRMED grSetDAC field, already in the encoder's allowlist — nothing new reaches the wire; what
# is new is that they are reachable from the thermostat card, a voice assistant and
# `climate.set_preset_mode` rather than only from the switches and the eco select.
#
# ECO maps to the first of this unit's three levels; the select entity still chooses between them,
# and the two agree because both read the same field. The unit's "quiet" (muteStatus) is
# deliberately not a preset: it is a fan-noise setting that composes with any of these, and folding
# it in would mean turning it off whenever a preset changes.
_PRESET_FIELDS: dict[str, tuple[str, int]] = {
    PRESET_ECO: ("ecoMode", GRSETDAC_ENUMS["ecoMode"]["level1"]),
    PRESET_SLEEP: ("silentSleepStatus", 1),
    PRESET_BOOST: ("rapidMode", 1),
}
# Read-back order. These fields are independent on the wire and the switches/select write them one
# at a time, so a unit can genuinely have two of them on; Home Assistant needs a single answer, so
# the most assertive setting wins — boost is doing the most to the unit, eco the least.
_PRESET_PRECEDENCE = (PRESET_BOOST, PRESET_SLEEP, PRESET_ECO)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HaismartConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([HaismartClimate(entry.runtime_data)])


class HaismartClimate(HaismartEntity, ClimateEntity):
    _attr_name = None  # the device name is the entity name
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.SWING_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    # The two axes are independent fields on the wire (vertical = word1 low nibble, horizontal =
    # word4 bits 0-2). This four-way control is the conventional way to expose swing and stays
    # exactly as it was — dashboards and automations use `swing_mode: both|vertical|horizontal|off`
    # — while `swing_horizontal_mode` below adds the axis-at-a-time control Home Assistant has had
    # since 2024.12. Both read the same decoded state, so they cannot disagree.
    _attr_swing_modes = [SWING_OFF, SWING_VERTICAL, SWING_HORIZONTAL, SWING_BOTH]
    _attr_swing_horizontal_modes = [SWING_HORIZONTAL_OFF, SWING_HORIZONTAL_ON]
    _enable_turn_on_off_backwards_compatibility = False

    def __init__(self, coordinator: HaismartCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = coordinator.device_id
        profile = coordinator.profile
        # dict order of the profile's STD maps is the model's own enum order
        seen: list[HVACMode] = [HVACMode.OFF]
        for token in profile.mode_values.values():
            hvac = _MODE_TO_HVAC.get(token)
            if hvac is None or hvac in seen:
                continue
            # `mode_values` doubles as the DECODE table, so the generic fallback lists every
            # mode the protocol defines in order to name whatever the unit reports. That is not
            # a capability
            # list: offering Heat on a cooling-only unit gives the user a button that does nothing.
            # Only advertise the full set when the profile came from this device's own digital model
            # (or a hand-verified per-model profile).
            if token == "heat" and not profile.modes_authoritative:
                continue
            seen.append(hvac)
        self._attr_hvac_modes = seen
        fans: list[str] = []
        for token in profile.fan_values.values():
            if token not in fans:
                fans.append(token)
        self._attr_fan_modes = fans
        self._attr_min_temp = profile.min_temp
        self._attr_max_temp = profile.max_temp
        self._attr_target_temperature_step = profile.temp_step
        # Only offer the presets whose field this unit's report family can actually write: a family
        # without the secondary toggles would otherwise get a control that always raises.
        presets = [
            preset
            for preset, (field, _) in _PRESET_FIELDS.items()
            if coordinator.supports_field(field)
        ]
        if presets:
            self._attr_preset_modes = [PRESET_NONE, *presets]
            self._attr_supported_features |= ClimateEntityFeature.PRESET_MODE
        # Same gate for the horizontal axis: extended-46 deliberately leaves windDirectionHorizontal
        # out of its write map because the position isn't settled, and the encoder must never be
        # handed a field it cannot place.
        if coordinator.supports_field("windDirectionHorizontal"):
            self._attr_supported_features |= ClimateEntityFeature.SWING_HORIZONTAL_MODE

    @property
    def _state(self) -> dict[str, Any]:
        """The last decoded status, or an empty dict before the first successful read."""
        return self.coordinator.data or {}

    @property
    def hvac_mode(self) -> HVACMode | None:
        state = self._state
        if not state:
            return None
        if state.get("power") is False:
            return HVACMode.OFF
        return _MODE_TO_HVAC.get(state.get("mode"))

    @property
    def current_temperature(self) -> float | None:
        return self._state.get("current_temperature")

    @property
    def target_temperature(self) -> float | None:
        return self._state.get("target_temperature")

    @property
    def fan_mode(self) -> str | None:
        return self._state.get("fan_mode")

    @property
    def swing_mode(self) -> str | None:
        vertical = self._state.get("swing_vertical")
        horizontal = self._state.get("swing_horizontal")
        if vertical is None and horizontal is None:
            return None
        if vertical and horizontal:
            return SWING_BOTH
        if vertical:
            return SWING_VERTICAL
        if horizontal:
            return SWING_HORIZONTAL
        return SWING_OFF

    @property
    def preset_mode(self) -> str | None:
        """The active comfort preset, or ``None`` until a status report has been read.

        Two of these can be on at the same time — the switches and the eco select write the fields
        independently — so the answer is the most assertive one that is on (_PRESET_PRECEDENCE).
        """
        known = False
        for preset in _PRESET_PRECEDENCE:
            if preset not in (self._attr_preset_modes or ()):
                continue
            value = self.coordinator.current_field(_PRESET_FIELDS[preset][0])
            if value:
                return preset
            known = known or value is not None
        return PRESET_NONE if known else None

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Select one preset and clear the rest, in a single group-set.

        Exclusivity is what a preset means, and a group-set is one atomic write of the whole
        attribute vector — so this cannot leave two of them on, and it costs one session where
        setting the switches by hand costs one each.
        """
        offered = self._attr_preset_modes or ()
        if preset_mode not in offered:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unsupported_value",
                translation_placeholders={
                    "name": self.name or "this air conditioner",
                    "value": str(preset_mode),
                    "field": "preset",
                },
            )
        await self.coordinator.async_send_control({
            field: (on if preset == preset_mode else 0)
            for preset, (field, on) in _PRESET_FIELDS.items()
            if preset in offered
        })

    @property
    def swing_horizontal_mode(self) -> str | None:
        """The left-right vane on its own, as Home Assistant models it since 2024.12.

        The four-way ``swing_mode`` above still works and still moves both axes together; this is
        for the cases that control could not express — "turn on left-right swing" had to be spelled
        `swing_mode: both`, which also starts the up-down vane.
        """
        horizontal = self._state.get("swing_horizontal")
        if horizontal is None:
            return None
        return SWING_HORIZONTAL_ON if horizontal else SWING_HORIZONTAL_OFF

    async def async_set_swing_horizontal_mode(self, swing_horizontal_mode: str) -> None:
        """Move the left-right vane only, leaving the up-down one where the user put it."""
        h_enum = GRSETDAC_ENUMS["windDirectionHorizontal"]
        await self.coordinator.async_send_control({
            "windDirectionHorizontal": h_enum[
                "on" if swing_horizontal_mode == SWING_HORIZONTAL_ON else "off"
            ]
        })

    def _mode_code(self, token: str | None) -> int | None:
        """Raw operationMode code for a normalized token, from the DEVICE'S own profile first.

        The profile is built from the device's digital model, so its code is authoritative for
        this unit — that is what makes modes our reference hardware lacks (heat) work: the code
        comes from the model, not from a constant. The static map is only the fallback for a device
        with no model (manual onboarding), where the profile's keys aren't numeric.
        """
        if token is None:
            return None
        code = self.coordinator.profile.std_mode(token)
        if code is not None and code.lstrip("-").isdigit():
            return int(code)
        return GRSETDAC_ENUMS["operationMode"].get(token)

    def _fan_code(self, token: str | None) -> int | None:
        """Raw windSpeed code for a normalized token — model-declared first, as ``_mode_code``."""
        if token is None:
            return None
        code = self.coordinator.profile.std_fan(token)
        if code is not None and code.lstrip("-").isdigit():
            return int(code)
        return GRSETDAC_ENUMS["windSpeed"].get(token)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self.coordinator.async_send_control({"onOffStatus": 0})
            return
        token = _HVAC_TO_MODE.get(hvac_mode)
        mode_val = self._mode_code(token)
        if mode_val is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unsupported_value",
                translation_placeholders={
                    "name": self.name or "this air conditioner",
                    "value": str(hvac_mode),
                    "field": "mode",
                },
            )
        # turning on and selecting the mode in one group-set
        changes: dict[str, int] = {"onOffStatus": 1, "operationMode": mode_val}
        # This unit SILENTLY REJECTS fan-only mode combined with fan=auto (verified on hardware: the
        # whole group-set is dropped and the unit stays on the previous mode). Fan-only needs a
        # concrete speed, so substitute one when the current fan is auto/unknown. The digital model
        # doesn't express this cross-attribute rule — it's observed device behaviour.
        if hvac_mode == HVACMode.FAN_ONLY and self.fan_mode in (None, "auto"):
            fallback = self._fan_code(_FAN_ONLY_DEFAULT_SPEED)
            if fallback is not None:
                changes["windSpeed"] = fallback
        await self.coordinator.async_send_control(changes)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temp = kwargs.get("temperature")
        if temp is None:
            return
        await self.coordinator.async_send_control(
            {"targetTemperature": int(round(temp)) - 16}
        )

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        # In fan-only mode the unit rejects fan=auto (see async_set_hvac_mode), so coerce it to a
        # concrete speed rather than send a write the AC will silently drop.
        if fan_mode == "auto" and self.hvac_mode == HVACMode.FAN_ONLY:
            fan_mode = _FAN_ONLY_DEFAULT_SPEED
        fan_val = self._fan_code(fan_mode)
        if fan_val is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unsupported_value",
                translation_placeholders={
                    "name": self.name or "this air conditioner",
                    "value": str(fan_mode),
                    "field": "fan speed",
                },
            )
        await self.coordinator.async_send_control({"windSpeed": fan_val})

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        # Both axes travel in ONE grSetDAC group-set, so off -> both can never land as a
        # half-applied state, and picking one axis explicitly turns the other off.
        vertical = swing_mode in (SWING_VERTICAL, SWING_BOTH)
        horizontal = swing_mode in (SWING_HORIZONTAL, SWING_BOTH)
        v_enum = GRSETDAC_ENUMS["windDirectionVertical"]
        h_enum = GRSETDAC_ENUMS["windDirectionHorizontal"]
        await self.coordinator.async_send_control(
            {
                "windDirectionVertical": v_enum["on" if vertical else "off"],
                "windDirectionHorizontal": h_enum["on" if horizontal else "off"],
            }
        )

    async def async_turn_on(self) -> None:
        await self.coordinator.async_send_control({"onOffStatus": 1})

    async def async_turn_off(self) -> None:
        await self.coordinator.async_send_control({"onOffStatus": 0})
