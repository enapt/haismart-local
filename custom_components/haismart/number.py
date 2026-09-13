"""Numeric settings an appliance declares — a new platform, for the appliances that have them.

Air conditioners have one numeric control and it is the thermostat's. Everything else has several:
a water heater's reservation temperatures and off-peak windows, a washing machine's spin speed and
temperature, a fridge's compartment setpoints. Each is a published attribute with a published range
and a published write id, so none of it is hand-written per appliance.
"""
from __future__ import annotations

from haismart_hrdp.entity_spec import Control
from homeassistant.components.number import NumberEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import HaismartConfigEntry, HaismartCoordinator
from .generic import GenericEntity, device_class_for, specs_of, unit_for


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HaismartConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        HaismartNumber(coordinator, spec) for spec in specs_of(coordinator, Control.NUMBER)
    )


class HaismartNumber(GenericEntity, NumberEntity):
    """One numeric setting, written on the single-parameter channel."""

    def __init__(self, coordinator: HaismartCoordinator, spec) -> None:
        super().__init__(coordinator, spec)
        self._attr_native_min_value = spec.minimum
        self._attr_native_max_value = spec.maximum
        self._attr_native_step = spec.step
        self._attr_native_unit_of_measurement = unit_for(spec)
        if (device_class := device_class_for(spec)) is not None:
            # NumberDeviceClass and SensorDeviceClass share their member names, so the slug carries
            # across; where a release has one and not the other, the entity keeps its unit and
            # loses only the class.
            try:
                from homeassistant.components.number import NumberDeviceClass

                self._attr_device_class = NumberDeviceClass(device_class.value)
            except (ImportError, ValueError):  # pragma: no cover - older Home Assistant
                pass

    @property
    def native_value(self) -> float | None:
        value = self.native_value_raw
        return float(value) if isinstance(value, (int, float)) else None

    async def async_set_native_value(self, value: float) -> None:
        # Sent as the PUBLISHED value: the byte map does its own scaling, and the device's model
        # states its range in the same units the user set.
        await self.async_write(int(value) if float(value).is_integer() else value)
