"""Climate entity — generated from the per-model AttributeProfile, with local control.

Control is the grSetDAC group-set write path. Every command is seeded from the latest full-status
report so it preserves all other attributes, and the library refuses any field/value not in its
allowlist.
"""
from __future__ import annotations

from dataclasses import dataclass
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
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import HaismartConfigEntry, HaismartCoordinator
from .entity import HaismartEntity

# normalized profile token <-> HA HVACMode (power/off handled separately)
_MODE_TO_HVAC = {
    "cool": HVACMode.COOL,
    "heat": HVACMode.HEAT,
    "dry": HVACMode.DRY,
    "fan_only": HVACMode.FAN_ONLY,
    "auto": HVACMode.AUTO,
    # A published mode with no HVACMode of its own. The window air conditioners carry
    # `节能模式(窗机)` -- energy-saving -- as an operationMode beside cool and fan, and it IS
    # cooling, with the compressor cycled to save power. So it DISPLAYS as Cool and is chosen
    # through the eco preset (`_mode_eco_preset`) -- the only vocabulary Home Assistant has for it.
    "eco": HVACMode.COOL,
}
# Deliberately NOT the plain inverse: two tokens map to COOL, and picking Cool on the card must
# write plain cooling rather than the energy-saving variant. Excluding the eco token is what keeps
# that true no matter where it sits in the mapping above.
_ECO_MODE_TOKEN = "eco"
_HVAC_TO_MODE = {
    hvac: token for token, hvac in _MODE_TO_HVAC.items() if token != _ECO_MODE_TOKEN
}

# Fan-only mode on this unit won't accept fan=auto; when entering it (or if the user picks auto
# while in it) we fall back to this concrete speed. "medium" is a neutral default airflow.
# Fan-only will not accept an "auto" wind speed -- the unit drops the command and stays put -- so a
# concrete speed is substituted. Low is the value the unit's own model names for this case, and the
# one it sends itself when fan-only is selected.
_FAN_ONLY_DEFAULT_SPEED = "low"

# The comfort modes as Home Assistant's standard presets, in the order they are offered. Each is one
# CONFIRMED grSetDAC field, already in the encoder's allowlist — nothing new reaches the wire; what
# is new is that they are reachable from the thermostat card, a voice assistant and
# `climate.set_preset_mode` rather than only from the switches and the eco select.
#
# ECO maps to the first of this unit's three levels; the select entity still chooses between them,
# and the two agree because both read the same field. The unit's "quiet" (muteStatus) is
# deliberately not a preset: it is a fan-noise setting that composes with any of these, and folding
# it in would mean turning it off whenever a preset changes.
@dataclass(frozen=True)
class _Preset:
    """One comfort preset: the field it writes and the values that turn it on and off.

    ``off`` is not always zero. Most presets are a bit or a level on a field of their own, so
    clearing them means writing 0. The window units express their energy-saving setting as an
    ``operationMode`` CODE instead, and that field's zero is a different mode (auto) which those
    units do not even have -- so clearing it means selecting plain cooling.

    ``exact`` says how to read the field back. A level field is "on" at any non-zero value, because
    its other values are the same setting turned up (eco level 2 is still eco). A field whose other
    values are OTHER SETTINGS is on only at ``on`` itself -- ``operationMode`` 1 is cooling, not
    "eco, off", and treating it as truthy would report eco whenever the unit was cooling at all.
    """

    field: str
    on: int
    off: int = 0
    exact: bool = False

    def is_on(self, value: int | None) -> bool:
        return value == self.on if self.exact else bool(value)


_PRESET_FIELDS: dict[str, _Preset] = {
    PRESET_ECO: _Preset("ecoMode", GRSETDAC_ENUMS["ecoMode"]["level1"]),
    PRESET_SLEEP: _Preset("silentSleepStatus", 1),
    PRESET_BOOST: _Preset("rapidMode", 1),
}


def _mode_eco_preset(profile) -> _Preset | None:
    """The eco preset for a unit whose energy-saving setting is an ``operationMode`` code.

    The window air conditioners publish three modes -- cool, ``节能模式(窗机)`` and fan -- with no
    ``ecoMode`` ladder at all, so their energy-saving setting is reachable only by writing the mode.
    Both codes come from the device's own published enum: nothing here assumes what they are, and a
    unit whose model names no eco mode (or no plain cooling to return to) gets no preset.
    """
    eco, cool = profile.std_mode(_ECO_MODE_TOKEN), profile.std_mode("cool")
    if eco is None or cool is None:
        return None
    try:
        return _Preset("operationMode", int(eco), off=int(cool), exact=True)
    except (TypeError, ValueError):
        return None
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
        # Whether Heat can be *encoded* at all -- the profile has to name the mode. Capability is a
        # separate question, answered by the unit itself; see `hvac_modes`.
        self._heat_encodable = "heat" in profile.mode_values.values()
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
        self._presets: dict[str, _Preset] = {
            preset: spec
            for preset, spec in _PRESET_FIELDS.items()
            if coordinator.supports_field(spec.field)
        }
        # A unit with no eco LADDER may still have an energy-saving MODE -- the window air
        # conditioners do, and it is the only way to reach it. Only ever added when the ladder is
        # absent, so a unit carrying both keeps the ladder (which is the finer control of the two).
        if PRESET_ECO not in self._presets and coordinator.supports_field("operationMode"):
            if (eco := _mode_eco_preset(profile)) is not None:
                self._presets[PRESET_ECO] = eco
        presets = [preset for preset in _PRESET_FIELDS if preset in self._presets]
        # Always assign the attribute — the preset_modes property reads it directly, and HA's
        # ClimateEntity gives it no class default, so leaving it unset crashes entity setup on a
        # family with no writable presets (e.g. the 117-byte family — issue #4).
        self._attr_preset_modes = [PRESET_NONE, *presets] if presets else None
        if presets:
            self._attr_supported_features |= ClimateEntityFeature.PRESET_MODE
        # Same gate for the horizontal axis: extended-46 deliberately leaves windDirectionHorizontal
        # out of its write map because the position isn't settled, and the encoder must never be
        # handed a field it cannot place.
        if coordinator.supports_field("windDirectionHorizontal"):
            self._attr_supported_features |= ClimateEntityFeature.SWING_HORIZONTAL_MODE
        # ...and the same gate for the fan dropdown, which was never given one: a feature whose
        # field the family cannot place is a button that can only raise.
        if not coordinator.supports_field("windSpeed"):
            self._attr_supported_features &= ~ClimateEntityFeature.FAN_MODE
        # The four-way swing goes only when NEITHER axis can move -- not when either cannot, which
        # is what this gate said when it was written and is why a family that can work its up-down
        # vane was left with no swing control at all. `supported_features` below has always had it
        # the right way round for the locked case; the two now agree.
        #
        # A family that can move one axis keeps the control, offering only the positions it can
        # actually reach, because `async_set_swing_mode` sends only the fields it has.
        axes = [
            field
            for field in ("windDirectionVertical", "windDirectionHorizontal")
            if coordinator.supports_field(field)
        ]
        if not axes:
            self._attr_supported_features &= ~ClimateEntityFeature.SWING_MODE
        elif len(axes) == 1:
            self._attr_swing_modes = [
                SWING_OFF,
                SWING_VERTICAL if axes[0] == "windDirectionVertical" else SWING_HORIZONTAL,
            ]

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        """Why any control is missing right now, as ``{setting: reason}``.

        A control that vanishes from the card is otherwise indistinguishable from one this
        integration never supported. The unit's own model states the reason each of its rules fires
        with — its mode, a fault, a cleaning cycle — so say it. This entity is the right place
        because it is the one that keeps its features hidden while staying available itself; an
        unavailable switch cannot report anything.

        Omitted entirely when nothing is locked, rather than shown empty.
        """
        return self.coordinator.locked_reasons or None

    @property
    def supported_features(self) -> ClimateEntityFeature:
        """The features minus whatever this unit is currently ignoring.

        A unit in fan-only discards a setpoint; a faulted one discards nearly everything. Its own
        model states which, so the control disappears from the card rather than sitting there doing
        nothing. Two things stay put whatever the model says: turning the unit on or off, and
        choosing a mode. A model marks the mode unwritable while the unit is off, yet writing it is
        precisely how this integration turns a unit on — and hardware accepts that — so removing it
        would take away the way back.
        """
        features = self._attr_supported_features
        locked = self.coordinator.locked_fields
        if not locked:
            return features
        for field, flag in (
            ("targetTemperature", ClimateEntityFeature.TARGET_TEMPERATURE),
            ("windSpeed", ClimateEntityFeature.FAN_MODE),
            ("windDirectionHorizontal", ClimateEntityFeature.SWING_HORIZONTAL_MODE),
        ):
            if field in locked:
                features &= ~flag
        # the four-way control moves both vanes, so it only goes when neither axis will move
        if {"windDirectionVertical", "windDirectionHorizontal"} <= locked:
            features &= ~ClimateEntityFeature.SWING_MODE
        if not self.preset_modes:
            features &= ~ClimateEntityFeature.PRESET_MODE
        return features

    @property
    def preset_modes(self) -> list[str] | None:
        """The presets whose field the unit will act on right now — boost is ignored in dry mode,
        and both it and sleep are while a fault is active."""
        offered = self._attr_preset_modes
        if not offered:
            return offered
        # Evaluated as if no comfort setting were on: choosing a preset clears the others in the
        # same command, so a preset that only sleep is holding back is still reachable from here.
        # What does apply is a mode or a fault that locks the field regardless — boost stays out
        # while the unit is dehumidifying, whatever the other presets are doing.
        locked = self.coordinator.locked_fields_excluding(
            [spec.field for spec in self._presets.values()]
        )
        available = [
            preset
            for preset in offered
            if preset == PRESET_NONE or self._presets[preset].field not in locked
        ]
        return available if len(available) > 1 else None

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """The profile's modes, corrected by what the unit says about itself.

        The unit reports its own heat capability in every status frame, which is better evidence
        than any model: it needs no cloud lookup, it is right for a model we have never seen, and it
        cannot disagree with the hardware. So it may both *remove* Heat from a profile that lists it
        generically -- avoiding a button that does nothing -- and *add* it for a reverse-cycle unit
        whose profile is only the generic fallback, provided the profile can encode the mode.
        """
        modes = list(self._attr_hvac_modes)
        capable = self._state.get("heat_capable")
        if capable is None:
            return modes
        if not capable:
            return [mode for mode in modes if mode is not HVACMode.HEAT]
        if HVACMode.HEAT not in modes and self._heat_encodable:
            modes.append(HVACMode.HEAT)
        return modes

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
        offered = self.preset_modes or ()
        for preset in _PRESET_PRECEDENCE:
            if preset not in offered:
                continue
            spec = self._presets[preset]
            value = self.coordinator.current_field(spec.field)
            if spec.is_on(value):
                return preset
            known = known or value is not None
        return PRESET_NONE if known else None

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Select one preset and clear the rest, in a single group-set.

        Exclusivity is what a preset means, and a group-set is one atomic write of the whole
        attribute vector — so this cannot leave two of them on, and it costs one session where
        setting the switches by hand costs one each.
        """
        offered = self.preset_modes or ()
        if preset_mode not in offered:
            self.raise_unsupported_value(preset_mode, "preset")
        changes: dict[str, int] = {}
        for preset, spec in self._presets.items():
            if preset not in offered:
                continue
            if preset == preset_mode:
                changes[spec.field] = spec.on
            elif not spec.exact or spec.is_on(self.coordinator.current_field(spec.field)):
                # A preset that shares its field with other settings is only cleared when it is
                # actually on: writing its "off" unconditionally would drag a unit out of fan-only
                # into cooling merely because someone selected a different preset, or none.
                changes[spec.field] = spec.off
        await self.coordinator.async_send_control(changes)

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
            self.raise_unsupported_value(hvac_mode, "mode")
        # turning on and selecting the mode in one group-set
        changes: dict[str, int] = {"onOffStatus": 1, "operationMode": mode_val}
        # This unit SILENTLY REJECTS fan-only mode combined with fan=auto (verified on hardware: the
        # whole group-set is dropped and the unit stays on the previous mode). Fan-only needs a
        # concrete speed, so substitute one when the current fan is auto/unknown. The digital model
        # doesn't express this cross-attribute rule — it's observed device behaviour.
        # Only where the fan speed is settable at all: the 209-byte family reports one and has no
        # room for it in its group-set, and adding a field its encoder cannot place would fail the
        # mode change itself -- the substitution exists to make fan-only work, so it must never be
        # what stops it.
        if (
            hvac_mode == HVACMode.FAN_ONLY
            and self.fan_mode in (None, "auto")
            and self.coordinator.supports_field("windSpeed")
        ):
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
            self.raise_unsupported_value(fan_mode, "fan speed")
        await self.coordinator.async_send_control({"windSpeed": fan_val})

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        # Both axes travel in ONE grSetDAC group-set, so off -> both can never land as a
        # half-applied state, and picking one axis explicitly turns the other off.
        #
        # A family that places only one of them gets only that one sent: the other would be handed
        # to an encoder that cannot place it, and the whole command would raise rather than the
        # half of it that this appliance can do.
        wanted = {
            "windDirectionVertical": swing_mode in (SWING_VERTICAL, SWING_BOTH),
            "windDirectionHorizontal": swing_mode in (SWING_HORIZONTAL, SWING_BOTH),
        }
        await self.coordinator.async_send_control(
            {
                field: GRSETDAC_ENUMS[field]["on" if on else "off"]
                for field, on in wanted.items()
                if self.coordinator.supports_field(field)
            }
        )

    async def async_turn_on(self) -> None:
        await self.coordinator.async_send_control({"onOffStatus": 1})

    async def async_turn_off(self) -> None:
        await self.coordinator.async_send_control({"onOffStatus": 0})
