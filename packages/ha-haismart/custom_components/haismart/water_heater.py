"""Water heaters — the first appliance category this integration carries that is not an AC.

Issue #13: a Haier heat-pump water heater paired through the Haismart app arrived as a `climate`
entity with cool / dry / fan_only modes and a 16-30 °C clamp against a real 35-75 °C setpoint, and
control was disabled because its 167-byte report matched no hand-written layout.

Nothing here decodes anything. The state comes from Haier's own published byte map for the device's
typeid (:mod:`haismart_hrdp.device_model`), gated by the attributes the unit's own model declares,
and writes go out on the single-parameter `5Dxx` channel the same map publishes — the mechanism the
`0d12` cabinets already ship. This module is the Home Assistant shape on top of that.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.water_heater import (
    STATE_OFF,
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import HaismartConfigEntry, HaismartCoordinator
from .entity import HaismartEntity

# The attribute names this platform reads, all published by the manufacturer's map.
_CURRENT_TEMPERATURE = "currentTemperature"
_TARGET_TEMPERATURE = "targetTemperature"
_POWER = "onOffStatus"
_RUNNING_MODE = "runningMode"

# Haier publishes each running mode as a std code with a Chinese description; these are the English
# names for the ones its water heaters declare. A code with no entry falls back to a readable name
# built from the code itself rather than being hidden -- a mode the appliance is actually in must
# always be displayable, or `current_operation` reports None while the unit is plainly running.
#
# ⚠️ Translations of the manufacturer's own labels, not guesses at behaviour: 即热 = instant heat,
# 动态夜电 = dynamic off-peak electricity, 预约 = reservation/schedule, 中温保温 = mid-temperature
# keep-warm, 随温而动 = follow-the-temperature. What each mode DOES on a given unit is the
# appliance's business; the name only has to identify it.
OPERATION_NAMES: dict[int, str] = {
    2: "Instant heat",
    3: "Off-peak",
    4: "Schedule 1",
    5: "Schedule 2",
    6: "Schedule 1 + 2",
    19: "Keep warm",
    20: "Eco sterilise",
    22: "Adaptive",
}


def _operation_name(code: int) -> str:
    return OPERATION_NAMES.get(code, f"Mode {code}")


async def async_setup_entry(
    hass: Any,
    entry: HaismartConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([HaismartWaterHeater(entry.runtime_data)])


class HaismartWaterHeater(HaismartEntity, WaterHeaterEntity):
    """A Haier water heater, driven entirely by what its own model declares."""

    _attr_name = None                    # the device name is the entity name
    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator: HaismartCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_water_heater"

        # The range comes from the DEVICE's own model where it has one, which is narrower than the
        # class map: the reporter's unit declares 35-75 where its class says 30-80. Falling back to
        # the AC profile's 16-30 is the defect this platform exists to fix, so there is no fallback
        # to it here -- an appliance that declares no range simply offers no setpoint.
        bounds = coordinator.model_attribute_range(_TARGET_TEMPERATURE)
        features = WaterHeaterEntityFeature(0)
        if bounds is not None:
            self._attr_min_temp, self._attr_max_temp, self._attr_target_temperature_step = bounds
            features |= WaterHeaterEntityFeature.TARGET_TEMPERATURE

        writable = coordinator.model_write_fields()
        self._can_set_temperature = _TARGET_TEMPERATURE in writable
        self._can_set_mode = _RUNNING_MODE in writable
        self._can_switch = _POWER in writable
        if not self._can_set_temperature:
            features &= ~WaterHeaterEntityFeature.TARGET_TEMPERATURE

        # Only the modes THIS unit declares. Its class defines nineteen; the reporter's heater
        # declares eight, and offering the other eleven would put controls on a device that
        # discards them.
        self._modes: dict[str, int] = {}
        for value in coordinator.model_attribute_options(_RUNNING_MODE):
            try:
                code = int(value)
            except (TypeError, ValueError):
                continue
            self._modes[_operation_name(code)] = code
        if self._modes and self._can_set_mode:
            features |= WaterHeaterEntityFeature.OPERATION_MODE
        if self._can_switch:
            features |= WaterHeaterEntityFeature.ON_OFF
        self._attr_supported_features = features

    @property
    def _state(self) -> dict[str, Any]:
        """What the manufacturer's byte map read out of the last report."""
        return (self.coordinator.data or {}).get("model_state") or {}

    @property
    def available(self) -> bool:
        # The coordinator's own availability, plus: a report we could not decode leaves every
        # reading stale, and a water heater showing yesterday's tank temperature is worse than one
        # showing none.
        return super().available and bool(self._state)

    @property
    def current_temperature(self) -> float | None:
        value = self._state.get(_CURRENT_TEMPERATURE)
        return float(value) if isinstance(value, (int, float)) else None

    @property
    def target_temperature(self) -> float | None:
        value = self._state.get(_TARGET_TEMPERATURE)
        return float(value) if isinstance(value, (int, float)) else None

    @property
    def operation_list(self) -> list[str] | None:
        if not self._modes:
            return None
        # `off` is a mode in Home Assistant's vocabulary for this platform, and the unit's power is
        # a separate attribute -- so it is offered alongside the running modes rather than instead
        # of them, and selecting it turns the appliance off.
        return [*self._modes, STATE_OFF] if self._can_switch else list(self._modes)

    @property
    def current_operation(self) -> str | None:
        if self._state.get(_POWER) is False:
            return STATE_OFF
        code = self._state.get(_RUNNING_MODE)
        if not isinstance(code, int):
            return None
        # Named even when it is not in `operation_list`: a unit reporting a mode it never declared
        # must still say which one, or the entity shows nothing while the appliance is running.
        return _operation_name(code)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """The rest of what the report says, under the manufacturer's own attribute names.

        Deliberately raw and deliberately unpromoted: these are real readings this platform has no
        first-class home for yet (`workStatus`, `oddHotWater`, the reservation fields). Exposing
        them as attributes makes the appliance usable in automations now, without shipping a dozen
        entities whose names and device classes have not been thought through.
        """
        extra = {k: v for k, v in self._state.items()
                 if k not in (_CURRENT_TEMPERATURE, _TARGET_TEMPERATURE, _POWER, _RUNNING_MODE)}
        return extra or None

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        self.raise_if_locked(_TARGET_TEMPERATURE)
        # The published value, not a raw wire value: the byte map does its own scaling, and the
        # device's model states its range in the same units a user sets.
        await self.coordinator.async_send_control({_TARGET_TEMPERATURE: float(temperature)})

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        if operation_mode == STATE_OFF:
            await self.async_turn_off()
            return
        code = self._modes.get(operation_mode)
        if code is None:
            self.raise_unsupported_value(operation_mode, _RUNNING_MODE)
        self.raise_if_locked(_RUNNING_MODE)
        await self.coordinator.async_send_control({_RUNNING_MODE: code})

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.raise_if_locked(_POWER)
        await self.coordinator.async_send_control({_POWER: True})

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.raise_if_locked(_POWER)
        await self.coordinator.async_send_control({_POWER: False})
