"""The air conditioner's state, built from Haier's published byte map rather than a hand map.

⛔ **Nothing uses this to decode yet, and that is deliberate.** It exists so the question "could one
decoder serve everything" can be ANSWERED rather than argued: it produces the same dictionary
:func:`haismart_hrdp.uss.parse_full_status` does, from the byte map alone, so the two can be compared
field for field on every capture and on frames nobody has seen.

What it separates, and why that is the whole point
--------------------------------------------------
Comparing the two decoders showed that on 38 stored air-conditioner captures the byte map reproduces
**449 wire fields with none disagreeing**. The differences were never about bytes — they were about
presentation. This module is that presentation layer, written down on its own:

* a vane's POSITION code collapsed to "is it sweeping" (:func:`wire_models.vane_v_sweeping`);
* an operation-source CODE named (`3` → ``"network"``);
* ``mode``/``fan_mode`` tokens derived through the device's own
  :class:`~haismart_hrdp.models.AttributeProfile`;
* the absent-probe rule for a sensor reading (``uss._sensor_temp``'s job).

⇒ Which makes the size of the actual duplication visible: it is the per-family POSITION tables in
:mod:`haismart_hrdp.wire_models` and :mod:`haismart_hrdp.canonical_map`, not the semantics above and
not the write path.

⚠️ It does NOT reproduce what the shipped decoder derives from something other than this frame —
alarms (a different frame), ``layout``/``writable`` (properties of the family, not the report), or
``heat_capable`` (the device's model). Those are the caller's, as they are today.
"""

from __future__ import annotations

from typing import Any

from .device_model import ATTR_BASE, STATUS_ALL, DeviceModel, absent_probe, read_field
from .wire_models import OPERATION_SOURCE, vane_h_sweeping, vane_v_sweeping

__all__ = ["AC_WIRE_FIELDS", "ac_state"]

#: Output key -> the Haier attribute it is read from, unchanged.
AC_WIRE_FIELDS: dict[str, str] = {
    "power": "onOffStatus",
    "target_temperature": "targetTemperature",
    "current_temperature": "indoorTemperature",
    "outdoor_temperature": "outdoorTemperature",
    "operation_mode": "operationMode",
    "wind_speed": "windSpeed",
    "health": "healthMode",
    "strong": "rapidMode",
    "quiet": "muteStatus",
    "sleep": "silentSleepStatus",
    "lamp": "screenDisplayStatus",
    "self_cleaning": "selfCleaningStatus",
}

#: Output key -> (attribute, how the air-conditioner layer presents it, read the RAW wire value?).
#:
#: ⚠️ The vanes are read RAW. ``DeviceModel.decode`` applies the map's ``variants``, which turns a
#: vane's EPP code into the STD code the model publishes — and the sweep test is written against the
#: EPP code (`wire_models.VANE_V_MODEL_TO_EPP` exists precisely because they differ). Handing it the
#: translated value reported "not sweeping" for three captures that were.
_PRESENTED: dict[str, tuple[str, Any, bool]] = {
    "swing_vertical": ("windDirectionVertical", vane_v_sweeping, True),
    "swing_horizontal": ("windDirectionHorizontal", vane_h_sweeping, True),
    "last_changed_by": ("opSrc", lambda raw: OPERATION_SOURCE.get(int(raw)), False),
}

#: Attributes the shipped decoder publishes as a STD code string rather than a number, because the
#: profile's enum maps are keyed that way (``profile.normalized_mode("1")``).
_AS_STD_STRING = frozenset({"operation_mode", "wind_speed"})

#: ⛔⛔ THE TWO EXISTING PATHS APPLY DIFFERENT BANDS TO THE SAME READING, and this reproduces that
#: rather than quietly picking one — an inconsistency the equivalence work surfaced:
#:
#:   * the classic family goes through ``uss._sensor_temp`` → **(−70, 150) °C**
#:   * every :mod:`haismart_hrdp.wire_models` family → ``_PLAUSIBLE_SENSOR_C`` → **(−30, 70) °C**
#:
#: So an outdoor probe reading 100 °C is published by one path and dropped by the other, on two air
#: conditioners, today. ⚠️ Worth fixing — but not silently and not here: this module's job is to
#: reproduce what ships, and a flip that also changed a band would make any regression unattributable.
#:
#: ⓘ And the band belongs on THIS side of the boundary whatever its value. It is hardware-confirmed
#: for air conditioners and nothing else: the published map's own range for ``outdoorTemperature`` is
#: −64…191, the span of the byte, so a garbage byte reads as a confident 167 °C without one. But a
#: water heater's reserve goes to 80 °C and an oven far higher — borrowing an AC's band for every
#: appliance is what dropped a real 75 °C reading (`docs/MULTI_DEVICE_PLAN` §7).

#: The readings the absent-probe rule applies to, named rather than inferred.
#:
#: ⛔ It must NOT be inferred from ``writable``: the classic family publishes its own setpoint as
#: read-only, and the generic rule's bounds check then dropped a 38 °C setpoint as "no such probe"
#: — a SETTING silently vanishing. This module knows each key's role, so it says so.
_SENSOR_READINGS = frozenset({"current_temperature", "outdoor_temperature"})


def _band(report_length: int) -> tuple[float, float]:
    """The plausibility band the SHIPPED decoder would apply to a report of this length."""
    from .uss import _PLAUSIBLE_TEMP_C, STATUS_LAYOUTS
    from .wire_models import _PLAUSIBLE_SENSOR_C

    return _PLAUSIBLE_TEMP_C if report_length in STATUS_LAYOUTS else _PLAUSIBLE_SENSOR_C


def ac_state(
    model: DeviceModel,
    data: bytes,
    profile: Any = None,
    *,
    base: int = ATTR_BASE,
) -> dict[str, Any]:
    """An air conditioner's state from the byte map, shaped like ``parse_full_status``'s output.

    ``profile`` is the device's own :class:`~haismart_hrdp.models.AttributeProfile`; without one the
    ``mode``/``fan_mode`` tokens are omitted rather than guessed, exactly as the classic path does.
    """
    decoded = model.decode(data, status_cmd=STATUS_ALL, drop_absent_probes=False, base=base)
    out: dict[str, Any] = {}

    for key, attribute in AC_WIRE_FIELDS.items():
        if attribute not in decoded:
            continue
        field = model.field(attribute)
        # A sensor reading a probe the unit does not have must read as absent, not as a confident
        # -64 C. The map alone cannot say that -- it is the rule `uss._sensor_temp` carries.
        value = decoded[attribute]
        if key in _SENSOR_READINGS and field is not None:
            if absent_probe(field, data, base=base):
                continue
            low, high = _band(len(data))
            if isinstance(value, (int, float)) and not low <= value <= high:
                continue
        out[key] = str(int(value)) if key in _AS_STD_STRING else value

    for key, (attribute, present, wants_raw) in _PRESENTED.items():
        field = model.field(attribute)
        if field is None or attribute not in decoded:
            continue
        value = decoded[attribute]
        if wants_raw:
            value = read_field(data, field.word, field.bit, field.length, base=base)
            if value is None:
                continue
        shown = present(value)
        if shown is not None:
            out[key] = shown

    if profile is not None:
        if "operation_mode" in out:
            out["mode"] = profile.normalized_mode(out["operation_mode"])
        if "wind_speed" in out:
            out["fan_mode"] = profile.normalized_fan(out["wind_speed"])
    return out
