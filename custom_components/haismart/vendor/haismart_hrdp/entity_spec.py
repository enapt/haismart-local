"""What ENTITY an attribute should become — so an appliance nobody here owns works out of the box.

The integration cannot wait for a reporter per appliance category. It does not have to: for any
device we hold three things already, and between them they decide every entity.

* **Where the attribute sits** and how its bits scale — Haier's own byte map
  (:mod:`haismart_hrdp.device_model`).
* **Which attributes THIS unit has**, with its own narrowed ranges and enum values — the device's
  digital model, fetched once at onboarding. ⛔ This is the gate that stops the class map becoming
  phantom entities: the map lists what the *platform* can carry, and a device declares a subset.
* **Whether a write id is published** for it.

This module turns those into a neutral :class:`EntitySpec` — neutral so it can be tested without
Home Assistant, and so the mapping from "a writable two-value enum" to "a switch" is stated once
rather than in five platform modules.

⛔ **What it deliberately does not do.** It never invents an attribute, never guesses a value an
enum does not publish, and never promotes something to a control because it looks like one: a
control exists only where the manufacturer publishes a single-parameter write id for it. The
appliance is still the only authority on whether that id works — see
:meth:`haismart_hrdp.device_model.DeviceModel.encode_write`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from .device_model import DeviceModel, ModelField

__all__ = [
    "Control",
    "EntitySpec",
    "english_name",
    "specs_for",
]


class Control(StrEnum):
    """The kind of entity an attribute becomes. Values are Home Assistant platform names."""

    SWITCH = "switch"
    SELECT = "select"
    NUMBER = "number"
    SENSOR = "sensor"
    BINARY_SENSOR = "binary_sensor"


# --- naming -------------------------------------------------------------------------------------
# Haier's attribute names are English camelCase, so a mechanical split reads correctly for most of
# the 1,676 distinct names in the catalogue ("heatingRodWorkingTime" -> "Heating rod working time").
# What follows is the curation on top of that, and it is patterns first because a pattern covers a
# family: `resn` alone names 30-odd attributes across every water heater.

_ACRONYMS = frozenset({
    "tds", "hh", "mm", "ss", "pm25", "pm10", "co2", "eev", "led", "uv", "ph", "rpm", "ppm",
    "3d", "ai", "tv", "usb", "wifi", "ec", "io", "cl", "id", "eco", "hepa", "utc",
    "msa", "voc", "hcho", "uvc",
})

# Applied to the NAME before splitting. Ordered: first match wins.
_REWRITES: tuple[tuple[re.Pattern[str], str], ...] = (
    # "resn" is Haier's abbreviation for 预约 -- a reservation/schedule slot. It is the single most
    # common unexplained prefix in the catalogue and reads as noise untranslated.
    (re.compile(r"^resn(\d+)"), r"reservation\1 "),
    (re.compile(r"^resn"), "reservation "),
    (re.compile(r"^valley"), "offPeak "),
    # A typo in Haier's own model, in two attributes across 60 device classes.
    (re.compile(r"Satus$"), "Status"),
)

# Applied to the SPLIT words, last word first: a suffix names the quantity, which is what a user
# reads. "reservation1TimeHH" -> "Reservation 1 hour" rather than "Reservation 1 time HH".
_SUFFIXES: Mapping[str, str] = MappingProxyType({
    "hh": "hour",
    "mm": "minute",
    "ss": "second",
    "num": "count",
})

# Exact names where neither the split nor a pattern gets it right.
_NAMES: Mapping[str, str] = MappingProxyType({
    "onOffStatus": "Power",
    "operationSrc": "Changed by",
    "opSrc": "Changed by",
    "runningMode": "Mode",
    "operationMode": "Mode",
    "targetTemperature": "Target temperature",
    "currentTemperature": "Current temperature",
    "indoorTemperature": "Indoor temperature",
    "outdoorTemperature": "Outdoor temperature",
    "inWaterTemperature": "Inlet water temperature",
    "outWaterTemperature": "Outlet water temperature",
    "tds": "TDS",
    "mgTestModuleExist": "Magnesium test module fitted",
    "leakageTestExist": "Leakage test fitted",
    "remainingHotWater": "Hot water remaining",
    "oddHotWater": "Hot water remaining",
    "oddHeatTime": "Heating time remaining",
    "currentWaterFlux": "Water flow",
    "powerOnTotalTime": "Total powered-on time",
    "totalElectricityUsed": "Total electricity used",
    "runPower": "Power draw",
    "actualPower": "Power draw",
    "vastMode": "Large-capacity mode",
    "scene": "Scene",
    "volume": "Volume",
})

# Never become entities. Each is a reason, not a preference:
#   forceDelete          a factory-reset command Haier models as an attribute -- 118 device classes
#   getAll*/stop*        operations, not state
#   uniqueId/token/...   opaque identifiers (caeType 13), and two of them are credentials
_SKIP: frozenset[str] = frozenset({
    "forceDelete", "getAllProperty", "getAllAlarm", "stopCurrentAlarm",
    "uniqueId", "token", "clientId", "location", "machineId", "deviceId",
})

# Diagnostics rather than controls: counters, run-times, fault codes, presence-of-hardware flags.
# A user does not want thirty of these on the dashboard, and Home Assistant has a shelf for them.
_DIAGNOSTIC = re.compile(
    r"(Err|ErrCode|Error|Fault|Times|TotalTime|WorkingTime|RunTime|ActionNum|Num|Exist|Version"
    r"|MaintenanceStatus|Result|Src)$"
)

_UNIT_DEVICE_CLASS: Mapping[str, str] = MappingProxyType({
    "℃": "temperature",
    "W": "power",
    "kW": "power",
    "Wh": "energy",
    "kwh": "energy",
    "kWh": "energy",
    "V": "voltage",
    "A": "current",
    "Hz": "frequency",
    "Pa": "pressure",
    "kPa": "pressure",
    "h": "duration",
    "min": "duration",
    "s": "duration",
    "L": "volume",
    "ug/m³": "pm25",
    "PPM": "carbon_dioxide",
})

# Units whose reading only ever grows. `state_class` decides whether Home Assistant builds long-term
# statistics as a total or a measurement, and getting it wrong makes the energy dashboard nonsense.
_CLOCK_PART = re.compile(r"(HH|MM|SS)$")
_TOTAL_UNITS = frozenset({"Wh", "kwh", "kWh", "MJ"})
_TOTAL_NAMES = re.compile(r"(TotalTime|WorkingTime|RunTimes?|Times|Used|ActionNum|TotalNum)$")


def _split(name: str) -> list[str]:
    text = name
    for pattern, replacement in _REWRITES:
        new = pattern.sub(replacement, text)
        if new != text:
            text = new
            break
    # Not every class uses camelCase: the air purifier's model is Snake_Case throughout
    # (`Child_Security_Lock`, `LED_Air_Quality`), and splitting only on case leaves those unreadable.
    text = text.replace("_", " ")
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    text = re.sub(r"(?<=[A-Za-z])(?=\d)", " ", text)
    text = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", text)
    return text.split()


def english_name(attribute: str) -> str:
    """A readable English name for a Haier attribute.

    Curated where the mechanical answer is wrong, mechanical everywhere else — which is most of
    them, because Haier's names are already English. ⛔ Never returns the raw identifier: an entity
    called ``heatingRodWorkingTime`` is worse than a slightly clumsy sentence.
    """
    if attribute in _NAMES:
        return _NAMES[attribute]
    words = _split(attribute)
    if not words:
        return attribute
    if words[-1].lower() in _SUFFIXES:
        words[-1] = _SUFFIXES[words[-1].lower()]
        # "reservation 1 time hour" -> "reservation 1 hour": the unit already says it is a time.
        if len(words) > 1 and words[-2].lower() == "time":
            del words[-2]
    out: list[str] = []
    for index, word in enumerate(words):
        lower = word.lower()
        if lower in _ACRONYMS:
            out.append(word.upper())
        elif index == 0:
            out.append(word[:1].upper() + word[1:])
        else:
            out.append(lower)
    return " ".join(out)


@dataclass(frozen=True)
class EntitySpec:
    """One attribute, as the entity it should become.

    Neutral by design: ``control``, ``device_class`` and ``state_class`` are Home Assistant's public
    slugs as plain strings, so this whole layer is testable without importing Home Assistant.
    """

    attribute: str
    control: Control
    name: str
    writable: bool
    unit: str | None = None
    device_class: str | None = None
    state_class: str | None = None
    diagnostic: bool = False
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    #: For a select: the values this DEVICE declares, as ``(published value, label)``. Ordered as
    #: the device's own model orders them.
    options: tuple[tuple[Any, str], ...] = dataclass_field(default_factory=tuple)

    @property
    def key(self) -> str:
        """Stable per-attribute suffix for a unique id. Never derived from the name, which changes."""
        return self.attribute


def _declared_options(
    field: ModelField, declared_values: Sequence[Any] | None
) -> tuple[tuple[Any, str], ...]:
    """The enum values to offer, as ``(value, label)``.

    The DEVICE's list wins where it has one -- issue #13's heater declares 8 of its class's 19
    running modes -- and the class map is the fallback for a device whose model lists no values.
    """
    labels: dict[Any, str] = {}
    for entry in field.variants if isinstance(field.variants, list) else ():
        std = entry.get("stdValue")
        if std is not None:
            labels[str(std)] = f"{std}"
    source = declared_values if declared_values else list(labels)
    out: list[tuple[Any, str]] = []
    for value in source:
        if str(value) not in labels:
            continue            # a value the class map cannot encode is not offerable
        out.append((value, str(value)))
    return tuple(out)


def _numeric_bounds(
    field: ModelField, declared: Mapping[str, Any] | None
) -> tuple[float | None, float | None, float | None]:
    """``(min, max, step)`` — the DEVICE's own range first, the class map's second.

    The device's is narrower and is the one a user recognises: issue #13's heater declares 35-75
    where its class says 30-80.
    """
    step_spec = ((declared or {}).get("valueRange") or {}).get("dataStep") or {}
    try:
        return (
            float(step_spec["minValue"]),
            float(step_spec["maxValue"]),
            float(step_spec.get("step") or 1),
        )
    except (KeyError, TypeError, ValueError):
        pass
    bounds = field.bounds()
    if bounds is None:
        return None, None, None
    step = 1.0
    if isinstance(field.variants, dict):
        step = float(field.variants.get("step") or 1)
    return bounds[0], bounds[1], step


def _spec(
    field: ModelField,
    *,
    declared: Mapping[str, Any] | None,
    writable: bool,
) -> EntitySpec | None:
    """Classify one field, or ``None`` where it should not become an entity at all."""
    name = field.name
    if name in _SKIP or field.cae_type == 13:
        return None
    english = english_name(name)
    diagnostic = bool(_DIAGNOSTIC.search(name)) or field.is_composite
    unit = field.unit
    device_class = _UNIT_DEVICE_CLASS.get(unit or "")

    # A composite (a clock or a date) has no numeric meaning: it is a string reading.
    if field.is_composite:
        return EntitySpec(name, Control.SENSOR, english, False, diagnostic=True)

    values = ((declared or {}).get("valueRange") or {}).get("dataList") or []
    declared_values = [entry.get("data") for entry in values if entry.get("data") is not None]

    if field.is_enum:
        options = _declared_options(field, declared_values)
        # Two-value booleans are a switch or a binary sensor, not a two-item dropdown. Haier models
        # 8,218 of them that way -- half the catalogue -- and every one would otherwise be a select.
        boolean = field.data_type == "bool" or (
            len(options) <= 2
            and {str(v).lower() for v, _ in options} <= {"true", "false", "0", "1"}
        )
        if boolean:
            if writable:
                return EntitySpec(name, Control.SWITCH, english, True, diagnostic=diagnostic)
            return EntitySpec(
                name, Control.BINARY_SENSOR, english, False, diagnostic=diagnostic
            )
        if writable and len(options) > 1:
            return EntitySpec(
                name, Control.SELECT, english, True, options=options, diagnostic=diagnostic
            )
        return EntitySpec(
            name, Control.SENSOR, english, False, options=options, diagnostic=diagnostic
        )

    # A clock COMPONENT is not a quantity. Haier declares `resn1TimeHH` with unit "h" and
    # `valleyStartTimeMM` with "min", which are the field's meaning, not its dimension: rendered as
    # a duration Home Assistant shows "6 h" for six o'clock. They keep their name ("Reservation 1
    # hour") and lose the unit, rather than being given a device class that is false.
    if _CLOCK_PART.search(name):
        return EntitySpec(name, Control.SENSOR, english, False, diagnostic=diagnostic)

    minimum, maximum, step = _numeric_bounds(field, declared)
    if writable and minimum is not None and maximum is not None:
        return EntitySpec(
            name, Control.NUMBER, english, True, unit=unit, device_class=device_class,
            minimum=minimum, maximum=maximum, step=step, diagnostic=diagnostic,
        )
    state_class = None
    if unit in _TOTAL_UNITS or _TOTAL_NAMES.search(name):
        state_class = "total_increasing"
    elif device_class is not None:
        state_class = "measurement"
    return EntitySpec(
        name, Control.SENSOR, english, False, unit=unit, device_class=device_class,
        state_class=state_class, diagnostic=diagnostic,
    )


def specs_for(
    model: DeviceModel | None,
    declared: Iterable[Mapping[str, Any]] | None,
    *,
    writable: Iterable[str] = (),
    exclude: Iterable[str] = (),
    status_cmd: str = "6D01",
) -> tuple[EntitySpec, ...]:
    """Every entity this device should have, from what it declares and what the map places.

    ``declared`` is the device's own model attributes (``digital_model["attributes"]``) and is the
    gate: **nothing not in it becomes an entity**. ``exclude`` is for attributes a hero platform has
    already claimed -- a water heater's setpoint belongs to its `water_heater` entity, not to a
    second `number` beside it.

    ⛔ Returns nothing at all when the device has declared nothing. That is the safe direction: a
    device whose model has not been fetched yet gets no entities rather than the whole class map,
    and picks them up on the next refresh.
    """
    if model is None:
        return ()
    by_name = {entry.get("name"): entry for entry in (declared or ()) if entry.get("name")}
    if not by_name:
        return ()
    writable_names = frozenset(writable)
    excluded = frozenset(exclude)
    specs: list[EntitySpec] = []
    seen: set[str] = set()
    for field in model.fields:
        if field.status_cmd != status_cmd or field.name in seen or field.name in excluded:
            continue
        if field.name not in by_name:
            continue
        seen.add(field.name)
        spec = _spec(
            field, declared=by_name[field.name], writable=field.name in writable_names
        )
        if spec is not None:
            specs.append(spec)
    return tuple(sorted(specs, key=lambda s: (s.diagnostic, s.name)))
