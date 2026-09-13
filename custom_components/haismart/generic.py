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
    """The spec's unit, which is already canonical.

    ⚠️ It is normalised in :func:`haismart_hrdp.entity_spec.canonical_unit`, at the ONE place the
    field's unit is read -- not here. That matters because the unit decides the device class, and a
    table on this side of the boundary would have the classifier reasoning about `ug/m3` while the
    entity published `µg/m³`. It did, and 17 classes' air-quality sensors lost their device class
    to the difference.
    """
    return spec.unit


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
    def _model_state(self) -> dict[str, Any]:
        return (self.coordinator.data or {}).get("model_state") or {}

    @property
    def native_value_raw(self) -> Any:
        """The attribute's published value from the last report, or ``None``.

        For a COLLAPSED series this is the summary line instead — see :attr:`EntitySpec.sources`.
        """
        if self.spec.sources:
            return self._series_summary()
        return self._model_state.get(self.spec.attribute)

    def _series_summary(self) -> str | None:
        """A schedule grid as one readable line: ``"06-09, 18-22"``, or ``"none"``.

        Haier publishes a timer as one boolean per hour of the day (or per weekday), and the 786 gas
        water heater has eight such grids -- 192 booleans. As 192 entities that is a wall; as eight
        lines it is a schedule somebody can read. Contiguous runs are joined, because "06, 07, 08"
        is the same fact written three times.
        """
        state = self._model_state
        active = [
            label
            for source, label in zip(self.spec.sources, self.spec.source_labels, strict=False)
            if state.get(source)
        ]
        if not any(source in state for source in self.spec.sources):
            return None                       # nothing decoded yet: unknown, not "none"
        if not active:
            return "none"
        if not all(label.isdigit() for label in active):
            return ", ".join(active)          # weekdays: no runs to join
        runs: list[tuple[int, int]] = []
        for hour in (int(label) for label in active):
            if runs and hour == runs[-1][1] + 1:
                runs[-1] = (runs[-1][0], hour)
            else:
                runs.append((hour, hour))
        return ", ".join(
            f"{lo:02d}" if lo == hi else f"{lo:02d}-{hi:02d}" for lo, hi in runs
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """The manufacturer's own identifier and description for this attribute.

        Worth carrying: these entities are generated, so a bug report about one is unreadable
        without the identifier it was generated from.
        """
        extra: dict[str, Any] = {"haier_attribute": self.spec.attribute}
        if self.spec.description:
            # The manufacturer's own words, verbatim. 83% of the catalogue's attributes have one and
            # all but four are Chinese, so it cannot BE the name for an English-speaking user — but
            # it is what Haier's own app shows, and it is what somebody searching their
            # documentation, or improving one of these names, actually needs.
            extra["haier_description"] = self.spec.description
        if self.spec.sources:
            extra["haier_attributes"] = list(self.spec.sources)
        return extra

    async def async_write(self, value: Any) -> None:
        """Send a value, refusing first anything the unit's own rules say it would discard."""
        self.raise_if_locked(self.spec.attribute)
        await self.coordinator.async_send_control({self.spec.attribute: value})


def description(spec: EntitySpec) -> EntityDescription:
    """A minimal description, for platforms that want one. Names are set on the entity."""
    return EntityDescription(key=spec.key, name=spec.name)
