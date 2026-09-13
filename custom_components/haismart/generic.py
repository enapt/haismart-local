"""Entities built from what the appliance's own model declares — so an unowned device just works.

Air conditioners keep their hand-built entity set: it is mature, curated, and carries behaviour
(vane positions, swing axes, presets, co-commands) that no generic rule would reproduce. Everything
else gets its entities from here — one per attribute the device declares and Haier's byte map
places, classified by :mod:`haismart_hrdp.entity_spec`.

⛔ **Nothing here is speculative.** An attribute becomes an entity only where the device's own
digital model declares it, and a *control* only where the manufacturer publishes a single-parameter
write id for it. The appliance remains the only authority on whether that write is accepted — a
refusal retires the control exactly as it does on the air-conditioner path.
"""
from __future__ import annotations

from typing import Any

from haismart_hrdp.entity_spec import Control, EntitySpec
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity import EntityDescription

from .coordinator import HaismartCoordinator
from .entity import HaismartEntity

# Haier's unit strings, as Home Assistant spells them. Anything not here is passed through as the
# manufacturer wrote it: a unit we do not recognise is still a true unit, and dropping it would
# make the reading less informative rather than more correct.
UNITS: dict[str, str] = {
    "℃": "°C",
    "kwh": "kWh",
    "ug/m³": "µg/m³",
    "PPM": "ppm",
    "RPM": "rpm",
}


def device_class_for(spec: EntitySpec) -> SensorDeviceClass | None:
    """The Home Assistant device class, or ``None`` where this release has no such member.

    Home Assistant adds device classes over time and this integration supports several releases, so
    a slug the byte map produces may not exist in the running one. An unknown class becomes a plain
    reading rather than a setup failure.
    """
    if spec.device_class is None:
        return None
    try:
        return SensorDeviceClass(spec.device_class)
    except ValueError:
        return None


def state_class_for(spec: EntitySpec) -> SensorStateClass | None:
    if spec.state_class is None:
        return None
    try:
        return SensorStateClass(spec.state_class)
    except ValueError:
        return None


def unit_for(spec: EntitySpec) -> str | None:
    return UNITS.get(spec.unit or "", spec.unit) or None


def category_for(spec: EntitySpec) -> EntityCategory | None:
    return EntityCategory.DIAGNOSTIC if spec.diagnostic else None


def specs_of(coordinator: HaismartCoordinator, control: Control) -> list[EntitySpec]:
    """This device's specs for one platform, or nothing at all for an air conditioner."""
    return [spec for spec in coordinator.entity_specs if spec.control is control]


class GenericEntity(HaismartEntity):
    """Common wiring for a model-declared entity: identity, naming and reading its value."""

    def __init__(self, coordinator: HaismartCoordinator, spec: EntitySpec) -> None:
        super().__init__(coordinator)
        self.spec = spec
        # Keyed on the ATTRIBUTE, never on the name: names are curated and will improve, and an
        # entity id that moved when a label was reworded would break every automation using it.
        self._attr_unique_id = f"{coordinator.device_id}_{spec.key}"
        self._attr_name = spec.name
        self._attr_entity_category = category_for(spec)
        self._attr_entity_registry_enabled_default = not spec.diagnostic

    @property
    def native_value_raw(self) -> Any:
        """The attribute's published value from the last report, or ``None``."""
        return (self.coordinator.data or {}).get("model_state", {}).get(self.spec.attribute)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """The manufacturer's own name for this attribute.

        Worth carrying: these entities are generated, so a bug report about one is unreadable
        without the identifier it was generated from, and a user searching Haier's own
        documentation needs the same string.
        """
        return {"haier_attribute": self.spec.attribute}

    async def async_write(self, value: Any) -> None:
        """Send a value, refusing first anything the unit's own rules say it would discard."""
        self.raise_if_locked(self.spec.attribute)
        await self.coordinator.async_send_control({self.spec.attribute: value})


def description(spec: EntitySpec) -> EntityDescription:
    """A minimal description, for platforms that want one. Names are set on the entity."""
    return EntityDescription(key=spec.key, name=spec.name)
