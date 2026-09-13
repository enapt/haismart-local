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
    "canonical_unit",
    "english_name",
    "enum_label",
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
    "pm2p5", "ch2o", "tvoc",
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
    # Air quality. Haier spells PM2.5 as "PM2p5", which no mechanical split reads well, and names
    # the gases by formula -- `ch2oValue` is formaldehyde, and a label nobody recognises is a
    # reading nobody acts on. These are the readings a safety-minded owner is looking for.
    "indoorPM2p5Value": "Indoor PM2.5",
    "outdoorPM2p5Value": "Outdoor PM2.5",
    "pm2p5Level": "PM2.5 level",
    "pm2p5CleaningStatus": "PM2.5 cleaning",
    "pm2p5ExceedRemind": "PM2.5 high reminder",
    "pm2p5WindSpeed": "PM2.5 fan speed",
    "ch2oValue": "Formaldehyde",
    "ch4Value": "Methane",
    "co2Value": "Carbon dioxide",
    "coValue": "Carbon monoxide",
    "anion": "Negative ions",
    "pmvStatus": "Comfort (PMV)",
    "ffm": "Fat-free mass",
    "runFanSpd": "Fan speed",
    "curWaterFlux": "Water flow",
    "waterFlux": "Water flow",
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

# Haier spells the same unit several ways across device classes, and the differences are not
# cosmetic: they decide whether a reading gets a device class at all, and Home Assistant validates
# the unit string it is given. `ug/m³` and `ug/m3` are both in the catalogue for the SAME attribute
# on different classes -- 96 fields against 52 -- so 17 classes' air-quality sensors were silently
# losing their class. Normalised once, here, before anything is classified.
_CANONICAL_UNITS: Mapping[str, str] = MappingProxyType({
    "℃": "°C",
    "ug/m³": "µg/m³", "ug/m3": "µg/m³",
    "PPM": "ppm",
    "kwh": "kWh", "KWh": "kWh",
    "w": "W", "kw": "kW",
    "RPM": "rpm", "r/min": "rpm",
    "Kcal": "kcal",
    "分": "min",                 # a Chinese-labelled minute, on three classes
})


def canonical_unit(unit: str | None) -> str | None:
    """Haier's unit string as Home Assistant spells it, or ``None`` for no unit.

    ⚠️ An EMPTY string is not a unit. 219 fields carry one, and passed through it makes a reading
    look dimensioned when it is not.
    """
    if not unit or not unit.strip():
        return None
    return _CANONICAL_UNITS.get(unit, unit)


_CLOCK_PART = re.compile(r"(HH|MM|SS)$")
# Readings that only ever grow. `state_class` decides whether Home Assistant builds long-term
# statistics as a total or a measurement, and getting it wrong makes the energy dashboard nonsense.
_TOTAL_UNITS = frozenset({"Wh", "kWh", "MJ", "kcal"})
_TOTAL_NAMES = re.compile(
    r"(TotalTime|WorkingTime|RunTimes?|Times|Used|ActionNum|TotalNum|WaterL|GasL|Flux)$"
)
_MEASURED = "measurement"
_TOTAL = "total_increasing"


def _quantity(name: str, unit: str | None, cumulative: bool) -> tuple[str | None, str | None]:
    """``(device class, state class)`` for a numeric reading, as a PAIR.

    Derived together on purpose. Home Assistant validates the combination — `volume` accepts only a
    total, `volume_storage` only a measurement — and it validates the unit against the class too, so
    a table keyed on the unit alone produces pairs that are individually plausible and jointly
    invalid. That is not a cosmetic failure: the entity's state is refused at write time.

    ⚠️ **Several of Haier's units are ambiguous and the name disambiguates them.** `µg/m³` covers
    PM2.5, PM10 *and* formaldehyde; `ppm` covers CO₂, carbon monoxide, methane, smoke and negative
    ions; litres covers water used, hot water remaining and gas consumed. Assigning by unit alone
    labelled a formaldehyde probe "PM2.5" and a carbon-monoxide probe "CO₂" — a wrong fact about a
    safety sensor, which is the worst kind to publish. Where the name does not settle it, the
    reading keeps its unit and gets no class.
    """
    lower = name.lower()
    if unit in ("W", "kW"):
        return "power", _MEASURED
    if unit in _TOTAL_UNITS:
        return "energy", _TOTAL
    if unit == "°C":
        return "temperature", _MEASURED
    if unit == "V":
        return "voltage", _MEASURED
    if unit == "A":
        return "current", _MEASURED
    if unit == "Hz":
        return "frequency", _MEASURED
    if unit in ("Pa", "kPa"):
        return "pressure", _MEASURED
    if unit == "L/min":
        return "volume_flow_rate", _MEASURED
    if unit == "L":
        if not cumulative:
            return "volume_storage", _MEASURED      # what is in the tank now
        return ("water" if "water" in lower else "volume"), _TOTAL
    if unit == "µg/m³":
        if "pm2" in lower:
            return "pm25", _MEASURED
        if "pm10" in lower:
            return "pm10", _MEASURED
        if "ch2o" in lower or "hcho" in lower or "formaldehyde" in lower:
            return "volatile_organic_compounds", _MEASURED
        return None, _MEASURED
    if unit == "ppm":
        if "co2" in lower:
            return "carbon_dioxide", _MEASURED
        if lower.startswith("co") and not lower.startswith("col"):
            return "carbon_monoxide", _MEASURED
        return None, _MEASURED
    if unit == "%":
        return ("humidity" if "humidity" in lower else None), _MEASURED
    if unit == "m":
        return ("distance" if "distance" in lower else None), _MEASURED
    if unit in ("g", "kg"):
        return ("weight" if "weight" in lower else None), _MEASURED
    if unit in ("h", "min", "s"):
        return "duration", (_TOTAL if cumulative else _MEASURED)
    if cumulative:
        return None, _TOTAL
    return None, (_MEASURED if unit else None)


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


# --- enum labels ---------------------------------------------------------------------------------
# An enum value's human label comes from the DEVICE's own model (`valueRange.dataList[].desc`), and
# Haier publishes those in Chinese. ⚠️ Not for want of asking: the cloud client already sends
# `language: en-us` on every request and issue #13's model came back with `即热模式` regardless.
# Scope of that: one account, one product, one fetch -- it is not established that no product or
# account ever gets English.
#
# So: translate what recurs, and fall back to the manufacturer's own label rather than to a bare
# number. A Chinese label a user can paste into a search engine is more use than "Mode 19".
# ⓘ The frequency ranking behind this table was taken over the catalogue's AC models, which is the
# only corpus with enum descriptions in it -- so it is strongest on the terms every appliance
# shares (on/off, high/medium/low, auto, locked) and thinnest on category-specific programme names.
_ENUM_LABELS: Mapping[str, str] = MappingProxyType({
    # the universals -- 10,500 occurrences of the first two alone
    "开": "On", "关": "Off", "开机": "On", "关机": "Off", "开启": "On", "关闭": "Off",
    "有": "Yes", "无": "No", "有效": "Enabled", "无效": "Disabled",
    "高": "High", "中": "Medium", "低": "Low", "自动": "Auto",
    "高风": "High", "中风": "Medium", "低风": "Low",
    "锁定": "Locked", "解锁": "Unlocked", "未锁定": "Unlocked",
    "正常": "Normal", "标准": "Standard", "清零": "Reset",
    "摄氏度": "Celsius", "华氏度": "Fahrenheit",
    # modes that recur across categories
    "节能": "Energy saving", "强力": "Boost", "静音": "Quiet", "快速": "Rapid",
    "除菌": "Sterilise", "杀菌": "Sterilise", "保温": "Keep warm", "预约": "Scheduled",
    "即热": "Instant heat", "即热模式": "Instant heat", "智能": "Smart", "舒适": "Comfort",
    "睡眠": "Sleep", "假期": "Holiday", "童锁": "Child lock", "烘干": "Dry",
    "加热": "Heating", "制冷": "Cooling", "制热": "Heating", "除湿": "Dehumidify",
    "送风": "Fan only", "通风": "Ventilate", "待机": "Standby", "运行": "Running",
    "暂停": "Paused", "结束": "Finished", "故障": "Fault", "停止": "Stopped",
    "中温保温": "Mid-temperature keep warm", "动态夜电模式": "Off-peak",
    "随温而动": "Adaptive", "Eco除菌": "Eco sterilise",
    "单预约": "One schedule", "双预约": "Two schedules",
})


# Labels that are a word plus a number. A table cannot hold "预约1", "预约2", "预约1+2" and the
# eight positions of a vane separately for every appliance; the pattern does.
_LABEL_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^预约\s*([\d+\s]+)$"), r"Schedule \1"),
    (re.compile(r"^位置\s*([一二三四五六七八九十\d]+)$"), r"Position \1"),
    (re.compile(r"^(\d+)档$"), r"Level \1"),
)
_CHINESE_NUMERALS = {"一": "1", "二": "2", "三": "3", "四": "4", "五": "5",
                     "六": "6", "七": "7", "八": "8", "九": "9", "十": "10"}


def enum_label(value: Any, description: str | None) -> str:
    """A human label for one enum value.

    Order: a translation of the manufacturer's own description, then a pattern for the
    word-plus-number labels a table cannot enumerate, then that description verbatim, then the bare
    value. ⛔ Never an invented name — a value this project cannot name is shown as what the
    manufacturer calls it, not as a guess at what it does.
    """
    if not description:
        return str(value)
    text = description.strip()
    if text in _ENUM_LABELS:
        return _ENUM_LABELS[text]
    for pattern, replacement in _LABEL_PATTERNS:
        match = pattern.match(text)
        if match:
            out = pattern.sub(replacement, text).strip()
            for cn, arabic in _CHINESE_NUMERALS.items():
                out = out.replace(cn, arabic)
            return out
    return text


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
    #: For a COLLAPSED series: the attributes this one entity reads, in order. Empty for the
    #: ordinary case of one entity per attribute. See :func:`_schedule_groups`.
    sources: tuple[str, ...] = dataclass_field(default_factory=tuple)
    #: Labels for a collapsed series, parallel to :attr:`sources` (``"00"`` … ``"23"``, ``"mon"`` …).
    source_labels: tuple[str, ...] = dataclass_field(default_factory=tuple)

    @property
    def key(self) -> str:
        """Stable per-attribute suffix for a unique id. Never derived from the name, which changes."""
        return self.attribute


def _declared_options(
    field: ModelField, declared: Sequence[Mapping[str, Any]] | None
) -> tuple[tuple[Any, str], ...]:
    """The enum values to offer, as ``(value, label)``.

    The DEVICE's list wins where it has one -- issue #13's heater declares 8 of its class's 19
    running modes -- and the class map is the fallback for a device whose model lists no values.
    ⛔ A value the CLASS MAP cannot encode is dropped whatever the device says about it: offering
    an option no write could express is a control that fails when it is used.
    """
    encodable = {
        str(entry.get("stdValue"))
        for entry in (field.variants if isinstance(field.variants, list) else ())
        if entry.get("stdValue") is not None
    }
    source: Sequence[Mapping[str, Any]] = declared or [{"data": v} for v in sorted(encodable)]
    out: list[tuple[Any, str]] = []
    for entry in source:
        value = entry.get("data")
        if value is None or str(value) not in encodable:
            continue
        out.append((value, enum_label(value, entry.get("desc"))))
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


# A schedule grid: one boolean per hour of the day, or per day of the week, repeated for several
# named programmes. Haier's 786 gas water heater publishes EIGHT such groups -- 192 booleans, which
# as 192 entities is not a feature, it is a wall. Collapsed, each group is one readable line.
_SERIES = re.compile(r"^(?P<prefix>.*?)(?:Hour|Day)(?P<index>\d{1,2}|[A-Za-z]{3})$")
_WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
#: Below this, an indexed run is a handful of related settings and reads better as itself.
_SERIES_MIN = 6


def _series_key(name: str) -> tuple[str, str] | None:
    """``(group, index label)`` if ``name`` is one cell of a schedule grid, else ``None``."""
    match = _SERIES.match(name)
    if not match:
        return None
    index = match.group("index")
    if index.isdigit():
        if not 0 <= int(index) <= 31:
            return None
        return match.group("prefix") + name[len(match.group("prefix")):-len(index)], index
    if index.lower() in _WEEKDAYS:
        return (
            match.group("prefix") + name[len(match.group("prefix")):-len(index)],
            index.lower(),
        )
    return None


def _schedule_groups(
    fields: Sequence[ModelField], declared: Mapping[str, Any]
) -> dict[str, EntitySpec]:
    """One spec per schedule grid, keyed by every attribute it swallows.

    ⛔ Only where every cell is a BOOLEAN and none is writable. A writable grid is a control, and
    collapsing a control into a read-only summary would remove the ability to set it -- worse than
    the clutter it fixes.
    """
    groups: dict[str, list[ModelField]] = {}
    for field in fields:
        if field.name not in declared or field.data_type != "bool":
            continue
        key = _series_key(field.name)
        if key is not None:
            groups.setdefault(key[0], []).append(field)

    out: dict[str, EntitySpec] = {}
    for group, members in groups.items():
        if len(members) < _SERIES_MIN:
            continue
        ordered = sorted(
            members,
            key=lambda f: (
                int(_series_key(f.name)[1]) if _series_key(f.name)[1].isdigit()
                else _WEEKDAYS.index(_series_key(f.name)[1])
            ),
        )
        spec = EntitySpec(
            attribute=group,
            control=Control.SENSOR,
            name=english_name(group),
            writable=False,
            sources=tuple(f.name for f in ordered),
            source_labels=tuple(_series_key(f.name)[1] for f in ordered),
        )
        for field in ordered:
            out[field.name] = spec
    return out


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
    unit = canonical_unit(field.unit)
    cumulative = unit in _TOTAL_UNITS or bool(_TOTAL_NAMES.search(name))
    device_class, state_class = _quantity(name, unit, cumulative)

    # A composite (a clock or a date) has no numeric meaning: it is a string reading.
    if field.is_composite:
        return EntitySpec(name, Control.SENSOR, english, False, diagnostic=True)

    values = ((declared or {}).get("valueRange") or {}).get("dataList") or []

    if field.is_enum:
        options = _declared_options(field, values)
        # What the CLASS MAP can encode, which is not the same as what the device declares: a
        # control has to be able to express both of its states, and this is where that is decided.
        encodable = {
            str(entry.get("stdValue")).lower()
            for entry in field.variants
            if entry.get("stdValue") is not None
        }
        # Two-value booleans are a switch or a binary sensor, not a two-item dropdown. Haier models
        # 8,218 of them that way -- half the catalogue -- and every one would otherwise be a select.
        # ⛔ Exactly two, not "at most two": `resnMode` publishes a SINGLE value (`{1: 1}`), and as a
        # switch it rendered an off position that `encode_write` refuses -- a control that fails the
        # first time somebody uses it. A one-value field is a constant, and it reads as a sensor.
        boolean = len(encodable) == 2 and (
            field.data_type == "bool" or encodable <= {"true", "false", "0", "1"}
        )
        if boolean:
            if writable:
                return EntitySpec(name, Control.SWITCH, english, True, diagnostic=diagnostic)
            return EntitySpec(
                name, Control.BINARY_SENSOR, english, False, diagnostic=diagnostic
            )
        if writable and len(options) > 1 and len(encodable) > 1:
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
        # A setting is not a statistic: a number entity carries no state class, and a device class
        # only where the SETTING's own dimension is unambiguous.
        return EntitySpec(
            name, Control.NUMBER, english, True, unit=unit, device_class=device_class,
            minimum=minimum, maximum=maximum, step=step, diagnostic=diagnostic,
        )
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
    status_cmd: Sequence[str] = ("6D01", "7D01"),
) -> tuple[EntitySpec, ...]:
    """Every entity this device should have, from what it declares and what the map places.

    ``declared`` is the device's own model attributes (``digital_model["attributes"]``) and is the
    gate: **nothing not in it becomes an entity**. ``exclude`` is for attributes a hero platform has
    already claimed -- a water heater's setpoint belongs to its `water_heater` entity, not to a
    second `number` beside it.

    ⛔ Returns nothing at all when the device has declared nothing. That is the safe direction: a
    device whose model has not been fetched yet gets no entities rather than the whole class map,
    and picks them up on the next refresh.

    Both status frames are covered: the ordinary report (``6D01``) and the extended telemetry one
    (``7D01``, which Haier files under ``Bigdata``). The second is where a washing machine's water
    and electricity totals live, and covering only the first decoded them into state that nothing
    ever showed. A name appearing in both keeps its ``6D01`` reading, which is the one that arrives
    on every poll.
    """
    if model is None:
        return ()
    by_name = {entry.get("name"): entry for entry in (declared or ()) if entry.get("name")}
    if not by_name:
        return ()
    writable_names = frozenset(writable)
    excluded = frozenset(exclude)
    wanted = (status_cmd,) if isinstance(status_cmd, str) else tuple(status_cmd)
    candidates = [
        f for command in wanted for f in model.fields
        if f.status_cmd == command and f.name not in excluded and f.name in by_name
    ]
    collapsed = {
        name: spec
        for name, spec in _schedule_groups(candidates, by_name).items()
        if name not in writable_names
    }
    specs: list[EntitySpec] = []
    seen: set[str] = set()
    for field in candidates:
        if field.name in seen:
            continue
        seen.add(field.name)
        if (group := collapsed.get(field.name)) is not None:
            if group not in specs:
                specs.append(group)
            continue
        spec = _spec(
            field, declared=by_name[field.name], writable=field.name in writable_names
        )
        if spec is not None:
            specs.append(spec)
    return tuple(sorted(specs, key=lambda s: (s.diagnostic, s.name)))
