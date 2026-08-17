"""Per-model attribute profiles — the model-specific ``AttributeProfile`` seam. Selected by the cloud
``product_code`` / ``pid`` (e.g. ``AAC1UKZ01`` / ``PID_AAC1UKZ01``).

The AAC1UKZ01 enums are **authoritative from the device digital model** (the constraintfile the app
downloads at bind time; see :func:`profile_from_device_config`) — operationMode 0=auto/1=cool/2=dry/
6=fan_only (no heat), windSpeed 1=high/2=medium/3=low/5=auto, targetTemperature 16-30 step 1. These were
independently cross-checked against a live ``getAttributeMap`` dump + a one-attribute-at-a-time app sweep
on real units, all consistent.

No prior open-source project maps this **encrypted uSS/CAE transport** — that part is original here.
⚠️ The *inner* frame is not original and must not be described as unrelated: it is the same
documented ``FF FF`` frame the public Haier implementations speak, and one of the families decoded
here is that protocol exactly, agreeing position for position with a public implementation of it.
What differs is the outer envelope and its encryption, not the frame inside.
"""
from __future__ import annotations

import logging
from collections.abc import Collection, Mapping
from typing import Any

from .device_rules import INVALID_REASONS
from .models import STD_OPERATION_MODE, STD_WIND_SPEED, AttributeProfile

_LOGGER = logging.getLogger(__name__)

# AAC1UKZ01 enums are now AUTHORITATIVE — from the device digital model (constraintfile)
# `HSU-24VRRA03TF@<uPlusId>@2.0.1.signed.json` pulled from the app (see profile_from_device_config).
# It's a cooling-only shared/rental AC (共享空调): modes auto/cool/dry/fan, no heat.
AAC1UKZ01 = AttributeProfile(
    power_attr="onOffStatus",
    mode_attr="operationMode",
    target_temp_attr="targetTemperature",
    indoor_temp_attr="indoorTemperature",
    humidity_attr="indoorHumidity",
    fan_attr="windSpeed",
    power_on_value="true",
    power_off_value="false",
    mode_values={           # numeric STD code -> normalized token (from the digital model)
        "0": "auto",        # 智能/自动/舒适
        "1": "cool",        # 制冷
        "2": "dry",         # 除湿
        "6": "fan_only",    # 送风  (no heat mode on this model)
    },
    fan_values={
        "1": "high",        # 高
        "2": "medium",      # 中
        "3": "low",         # 低
        "5": "auto",        # 自动
    },
    min_temp=16.0,
    max_temp=30.0,
    temp_step=1.0,
    modes_authoritative=True,   # hand-verified against this model's digital model + hardware
)

# Fallback only: map a model's value DESCRIPTION -> our normalized token, for a code the STD table
# doesn't know. Both Chinese and English, because the description language is not ours to control —
# `HaierCloud._headers` sends `language: en-us` on the shadow endpoint that feeds the coordinator,
# while the constraintfile CDN (no headers) serves the canonical Chinese. Matching only Chinese meant
# the entire mechanism silently produced nothing on the path that is actually used.
#
# Sorted longest-first at import so a specific description wins over a substring of it ("制热" before
# "热", "fan only" before "fan"). The old tuple claimed this ordering in its comment but never did it.
_MODE_KEYWORDS: tuple[tuple[str, str], ...] = tuple(sorted((
    ("制冷", "cool"), ("制热", "heat"), ("除湿", "dry"), ("送风", "fan_only"),
    ("通风", "fan_only"), ("智能", "auto"), ("自动", "auto"), ("舒适", "auto"),
    ("cool", "cool"), ("heat", "heat"), ("dry", "dry"), ("dehumidif", "dry"),
    ("fan only", "fan_only"), ("fan_only", "fan_only"), ("fanonly", "fan_only"),
    ("ventilat", "fan_only"), ("auto", "auto"), ("comfort", "auto"), ("smart", "auto"),
    ("intelligent", "auto"),
), key=lambda kv: -len(kv[0])))
_FAN_KEYWORDS: tuple[tuple[str, str], ...] = tuple(sorted((
    ("高", "high"), ("中", "medium"), ("低", "low"), ("自动", "auto"),
    ("high", "high"), ("medium", "medium"), ("middle", "medium"), ("low", "low"),
    ("auto", "auto"),
), key=lambda kv: -len(kv[0])))


def _enum_from_datalist(data_list, std_table, keywords, *, what: str) -> dict[str, str]:
    """Map a model's ``valueRange.dataList`` to normalized tokens.

    The STD code table is the PRIMARY mechanism — the codes are Haier-wide, so a model only tells us
    which subset it supports. Description keywords are a fallback for a code the table doesn't know.
    A code that resolves by neither is **dropped with a log line**, never guessed: an unnameable mode
    simply doesn't appear in the entity, which is strictly better than fabricating a mapping.
    """
    out: dict[str, str] = {}
    for item in data_list or []:
        code = str(item.get("data"))
        token = std_table.get(code)
        if token is None:
            desc = (item.get("desc") or "").casefold()
            token = next((tok for kw, tok in keywords if kw.casefold() in desc), None)
        if token is None:
            _LOGGER.info(
                "%s code %r (%r) is not a known STD code and its description did not match a known "
                "keyword - dropping it. Please report this model so it can be mapped.",
                what, code, item.get("desc"),
            )
            continue
        out[code] = token
    return out


def profile_from_device_config(config: dict) -> AttributeProfile:
    """Build an ``AttributeProfile`` from a Haier device digital-model / constraintfile JSON.

    This is the *queryable* path: the model config (fetched during device binding, or by
    ``getDeviceFuncNew?mode=<productCode>`` / the ``constraintfile`` resource) fully specifies each
    attribute's ``valueRange``, so any model self-maps instead of being hand-coded. Codes resolve via
    the Haier-wide STD tables first, then by description keyword, then are dropped.

    Raises ``ValueError`` if no ``operationMode`` code could be resolved. This matters: it used to
    substitute a hardcoded default map on failure, which (a) could never match the numeric codes the
    decoder emits and (b) meant the caller's fallback-to-a-known-profile path was unreachable dead
    code. Failing loudly hands control back to ``profile_for(product_code)``.
    """
    attrs = {a["name"]: a for a in config.get("attributes", [])}

    def datalist(name):
        return ((attrs.get(name) or {}).get("valueRange") or {}).get("dataList")

    def step_bounds(name, dflt_min, dflt_max, dflt_step):
        ds = ((attrs.get(name) or {}).get("valueRange") or {}).get("dataStep") or {}
        try:
            return (float(ds.get("minValue", dflt_min)), float(ds.get("maxValue", dflt_max)),
                    float(ds.get("step", dflt_step)))
        except (TypeError, ValueError):
            return dflt_min, dflt_max, dflt_step

    mn, mx, step = step_bounds("targetTemperature", 16.0, 30.0, 1.0)
    modes = _enum_from_datalist(
        datalist("operationMode"), STD_OPERATION_MODE, _MODE_KEYWORDS, what="operationMode"
    )
    if not modes:
        raise ValueError(
            "digital model yielded no usable operationMode enum "
            f"(dataList={datalist('operationMode')!r})"
        )
    fans = _enum_from_datalist(
        datalist("windSpeed"), STD_WIND_SPEED, _FAN_KEYWORDS, what="windSpeed"
    )
    if not fans:
        # Fan speeds are not essential to a working thermostat, so fall back to the STD table rather
        # than discarding an otherwise-good profile over them.
        _LOGGER.info("digital model yielded no windSpeed enum - using the STD code table")
        fans = dict(STD_WIND_SPEED)
    return AttributeProfile(
        mode_values=modes, fan_values=fans, min_temp=mn, max_temp=mx, temp_step=step,
        # the device's own model told us which codes it supports, so this IS a capability list
        modes_authoritative=True,
    )


# --- write validation against the device digital model (safety guard) ---------

def writable_attributes(config: dict) -> dict[str, dict]:
    """Map of attribute name -> its model spec, for attributes the model marks ``writable``."""
    return {a["name"]: a for a in config.get("attributes", []) if a.get("writable")}


def model_enum_codes(config: dict, name: str) -> set[int]:
    """The numeric codes attribute ``name`` declares in its model ``valueRange`` LIST.

    This is the device's OWN statement of which values it supports, so it is what authorizes a
    capability our hardware doesn't have (heat mode, an extra fan speed) instead of a guessed
    constant — it feeds ``set_grsetdac_field(..., model_values=...)``. Non-numeric enums (the
    ``'false'``/``'true'`` bools) and unlisted/absent attributes yield an empty set.
    """
    spec = next((a for a in config.get("attributes", []) if a.get("name") == name), None)
    vr = (spec or {}).get("valueRange") or {}
    if vr.get("type") != "LIST":
        return set()
    codes: set[int] = set()
    for item in vr.get("dataList") or []:
        try:
            codes.add(int(str(item.get("data"))))
        except (TypeError, ValueError):
            continue
    return codes


def validate_write(
    config: dict, name: str, value, *, require_writable: bool = True
) -> tuple[bool, str]:
    """Gate a proposed control write against the device digital model BEFORE it is ever encoded.

    Refuses anything that isn't a writable attribute with a value the model allows — so a control
    command can never carry an unknown attribute, an out-of-range temperature, or an invalid enum.
    (The user's safety point: use the product constraints to limit the input.) LIST attrs must match a
    ``valueRange.dataList`` code; STEP attrs must be numeric, within [min,max], and on the step grid.
    Returns ``(ok, reason)``.

    ``require_writable``: when True (default) an attribute the model flags read-only is rejected. The
    HA control path passes ``False`` because Haier's cloud model misclassifies several
    **confirmed** grSetDAC fields as non-writable (e.g. ``targetTemperature``, ``rapidMode`` —
    both observed in real app writes and verified on hardware). There, writability is authorized
    by the confirmed allowlist in ``set_grsetdac_field`` instead, and this function only gates
    the **valueRange** (bounds / enum membership).
    """
    attrs = {a["name"]: a for a in config.get("attributes", [])}
    spec = attrs.get(name)
    if spec is None:
        return False, f"unknown attribute {name!r} (not in device model)"
    if require_writable and not spec.get("writable"):
        return False, f"{name!r} is not writable (read-only in the model)"
    vr = spec.get("valueRange") or {}
    sval = str(value)
    if vr.get("type") == "LIST":
        allowed = {str(x.get("data")) for x in (vr.get("dataList") or [])}
        if sval not in allowed:
            return False, f"{name}={sval!r} not in allowed {sorted(allowed)}"
        return True, "ok"
    if vr.get("type") == "STEP":
        ds = vr.get("dataStep") or {}
        try:
            v = float(value)
            lo = float(ds["minValue"])
            hi = float(ds["maxValue"])
            st = float(ds["step"])
        except (KeyError, TypeError, ValueError):
            return False, f"{name}: non-numeric value or malformed range"
        if not (lo <= v <= hi):
            return False, f"{name}={v} out of range [{lo}, {hi}]"
        if st > 0 and abs(((v - lo) / st) - round((v - lo) / st)) > 1e-6:
            return False, f"{name}={v} not on step grid (step {st} from {lo})"
        return True, "ok"
    return False, f"{name}: unsupported valueRange type {vr.get('type')!r}"

# The AC's full STD attribute set (uSDKDevice.getAttributeMap, AAC1UKZ01) — reference for the HA layer.
AAC1UKZ01_ATTRIBUTES: tuple[str, ...] = (
    "onOffStatus", "operationMode", "operationModeHK", "targetTemperature", "indoorTemperature",
    "outdoorTemperature", "indoorHumidity", "targetHumidity", "windSpeed", "windDirectionVertical",
    "windDirectionHorizontal", "tempUnit", "acType", "useMode", "opSrc", "errCode", "ErrAckFlag",
    "healthMode", "rapidMode", "silentSleepStatus", "muteStatus", "lightStatus", "screenDisplayStatus",
    "echoStatus", "lockStatus", "energySavingStatus", "energySavePeriod", "electricHeatingStatus",
    "10degreeHeatingStatus", "halfDegreeSettingStatus", "selfCleaningStatus", "selfCleaning56Status",
    "sensingResult", "humanSensingStatus", "intelligenceStatus", "pmvStatus", "specialMode",
    "generatorMode", "freshAirStatus", "humidificationStatus", "localCtrValid", "localFilterChangeFlag",
    "airQuality", "pm2p5Level", "indoorPM2p5Value", "outdoorPM2p5Value", "vocValue", "ch2oValue",
    "co2Value", "totalElectricityUsed", "totalCleaningTime",
)

# AACRL2E00 ("PRO X INV-42/3PH", deviceType 0201201d) — a reverse-cycle wall-mounted split, i.e. the
# first confirmed unit here that HEATS. Its digital model lists operationMode 0/1/2/4/6 (制热 = 4) and
# windSpeed 1/2/3/5, verified against the live cloud shadow. Worth spelling out rather than leaning on
# the STD defaults, because this is the hardcoded fallback used when no digital model is stored.
AACRL2E00 = AttributeProfile(
    mode_values={"0": "auto", "1": "cool", "2": "dry", "4": "heat", "6": "fan_only"},
    fan_values={"1": "high", "2": "medium", "3": "low", "5": "auto"},
    min_temp=16.0,
    max_temp=30.0,
    temp_step=1.0,
    modes_authoritative=True,   # verified against this unit's digital model + live cloud shadow
)

# Registry keyed by cloud product_code / pid (usdk_os.db cloud_device.product_code / .pid).
PROFILES: dict[str, AttributeProfile] = {
    "AAC1UKZ01": AAC1UKZ01,
    "PID_AAC1UKZ01": AAC1UKZ01,
    "AACRL2E00": AACRL2E00,
    "PID_AACRL2E00": AACRL2E00,
}


def profile_for(type_id: str | None) -> AttributeProfile:
    """Return the AttributeProfile for a product_code/pid, or a generic STD default if unknown.

    The default is keyed by the Haier-wide STD codes (see :data:`~.models.STD_OPERATION_MODE`), so an
    unknown model still decodes its mode and fan correctly. It is deliberately permissive about which
    modes exist — a unit that cannot heat will simply never report code 4 — so the caller should
    prefer a profile derived from the device's own digital model when one is available.
    """
    if type_id and type_id in PROFILES:
        return PROFILES[type_id]
    return AttributeProfile()


# --- co-command rules ---------------------------------------------------------
# Some settings cannot be sent alone. The unit silently drops a command that conflicts with the
# state it would leave behind -- selecting fan-only while the fan is on auto is the case seen most
# often, where the mode change simply does not happen. The device model carries these rules, so they
# can be honoured for any model rather than one hard-coded case at a time.
#
# A rule reads "if the write sets X, also send Y". Values here are the model's own (STD) values, as
# strings; the caller converts to and from wire values, which keeps this free of any per-field
# encoding knowledge.


def constraint_commands(
    model: Mapping[str, Any] | None, pending: Mapping[str, str]
) -> dict[str, str]:
    """The extra commands the model requires alongside ``pending``.

    ``pending`` and the result are ``{attribute: model value}``. A rule fires when *every* attribute
    it names is being set to one of the values it lists. Anything already in ``pending`` is left
    alone -- an explicit request outranks a rule's default.
    """
    if not model:
        return {}
    extra: dict[str, str] = {}
    for rule in model.get("constraints") or ():
        condition = ((rule.get("pendingCondition") or {}).get("commands")) or {}
        if not condition:
            continue
        if not all(str(pending.get(name)) in [str(v) for v in values]
                   for name, values in condition.items()):
            continue
        for command in ((rule.get("additionalCommands") or {}).get("commands")) or ():
            name, value = command.get("name"), command.get("value")
            if name and value is not None and name not in pending:
                extra[name] = str(value)
    return extra


def alarm_names(model: Mapping[str, Any] | None, codes: Collection[int]) -> frozenset[str]:
    """The model's own names for the active fault positions in ``codes``.

    A fault frame gives positions; the rules in :func:`locked_attributes` are written against names,
    so one has to be turned into the other. The model's alarm list starts with its "fault cleared"
    entry, which is not a position at all, so position N is the model's entry **N + 1** — the same
    offset the unit's own error code uses. A position past the end of the list is dropped rather
    than guessed at.
    """
    alarms = (model or {}).get("alarms") or ()
    names: set[str] = set()
    for code in codes:
        index = code + 1
        if 0 <= index < len(alarms) and (name := alarms[index].get("name")):
            names.add(name)
    return frozenset(names)


def locked_attributes(
    model: Mapping[str, Any] | None,
    state: Mapping[str, str],
    active_alarms: Collection[str] = (),
) -> frozenset[str]:
    """Attributes the model marks non-writable while ``state`` holds (or a fault is active).

    Distinct from the per-attribute ``writable`` flag, which misclassifies several settings this
    hardware demonstrably accepts. These rules are conditional and match observed behaviour: a unit
    in fan-only really does ignore a setpoint, and one reporting a fault ignores most of the rest.
    """
    return frozenset(lock_reasons(model, state, active_alarms))


def lock_reasons(
    model: Mapping[str, Any] | None,
    state: Mapping[str, str],
    active_alarms: Collection[str] = (),
) -> dict[str, str]:
    """Which attributes are locked right now, and **why** — ``{attribute: reason}``.

    Every rule names the reason it fires as a code, and the model states what those codes mean, so a
    control that has gone unavailable can say whether it is the unit's mode, a fault, or its being
    switched off. Reasons are for display only; :func:`locked_attributes` is the same computation and
    is what decides availability.

    An attribute locked by more than one rule keeps the **first** reason, and a model lists its rules
    in descending priority, so that is the highest-priority rule's. Note what that means in practice
    rather than assuming: the fault rule does not sit at the top, so a unit that is both faulted and
    in fan-only reports the mode as the reason. Both are true and neither is more correct -- do not
    "fix" this into a fault-first ordering without a reason to prefer one.

    An attribute whose rule names no reason, or names one the model does not explain, is still
    locked but reported without one; a missing explanation must never turn into a missing lock.
    """
    if not model:
        return {}
    # A model states its reasons in its own language -- the openly fetched ones come back in
    # Chinese. The CODE is the fact and the sentence is presentation, so for codes we recognise the
    # English wording wins; anything we do not know falls back to whatever the model said, which is
    # better than nothing.
    raw = model.get("invalid_reasons") or {}
    if not isinstance(raw, Mapping):
        # A family-agreed model once shipped this section as a bare list of codes, and entries
        # merged under those releases persisted it. The code is still the fact, so recover the
        # codes and let the recognised-code table below supply the wording.
        raw = {code: "" for code in raw}
    meanings = {str(k): str(v) for k, v in raw.items()}
    meanings.update({k: v for k, v in INVALID_REASONS.items() if k in meanings})
    reasons: dict[str, str] = {}
    for rule in model.get("modifiers") or ():
        trigger = rule.get("trigger") or {}
        conditions = trigger.get("conditions") or {}
        alarms = trigger.get("alarms") or []
        matched = [str(state.get(name)) in [str(v) for v in values]
                   for name, values in conditions.items()]
        if alarms:
            matched.append(any(name in active_alarms for name in alarms))
        if not matched:
            continue
        fired = any(matched) if str(trigger.get("operator")).upper() == "OR" else all(matched)
        if not fired:
            continue
        reason = meanings.get(str(rule.get("invalid_code") or ""), "")
        for action in rule.get("actions") or ():
            if action.get("writable") is False and action.get("name"):
                reasons.setdefault(action["name"], reason)
    return reasons
