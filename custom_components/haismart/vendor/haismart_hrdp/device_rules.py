"""Conditional writability rules, for the models whose rules are known.

An air conditioner ignores certain settings in certain states — a unit in fan-only discards the
setpoint it is sent, one dehumidifying discards boost, one reporting a fault discards nearly
everything. A device model states these per device, as ``modifiers``, and
:func:`~haismart_hrdp.profiles.locked_attributes` reads them.

**The copy of the model a device hands out through the cloud carries its attributes and their values,
but not these rules.** Every model fetched during onboarding so far has arrived with no ``modifiers``
and no ``alarms``, which leaves the rules unreadable however carefully they are interpreted. So where
a model's rules are known they are recorded here, keyed by the identifier a unit reports for itself,
and merged into its model when what arrived carries none. A model that does carry its own rules is
never overridden — its own are always better.

The rules are otherwise ordinary model data: a trigger (a state, a fault, or either) and the
attributes that stop being writable while it holds.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _lock(name: str) -> dict[str, Any]:
    return {"name": name, "writable": False}


# Every lock rule names the reason it fires, as a code. A model publishes the codes and their
# meanings separately, so a locked control can say *why* rather than only going unavailable.
#
# Only one of the two forms a published model arrives in carries these: the openly fetchable one
# states a code on each condition and lists the meanings, while the account-fetched form states
# neither. So the meanings are recorded here as well, and a model that does carry its own always
# wins -- same rule as the lock rules themselves.
INVALID_REASONS: Mapping[str, str] = {
    "50001": "not available while the unit reports a fault",
    "50002": "not available in the unit's current state",
    "50003": "the temperature cannot be adjusted in the unit's current state",
    "50004": "the fan speed cannot be adjusted in the unit's current state",
    "50005": "not available in intelligent mode",
    "50006": "not available in cooling mode",
    "50007": "not available in heating mode",
    "50008": "not available in dry mode",
    "50009": "not available in fan-only mode",
}


_ALARM_NAMES = (
    "alarmCancel",
    "outdoorModuleErr",
    "outdoorDeforstSensorErr",
    "outdoorExhaustSensorErr",
    "outdoorEEPROMErr",
    "indoorCoilerSensorErr",
    "indoorOutdoorCommErr",
    "powerProtection",
    "panelCommErr",
    "outdoorCompressorOverheatProtection",
    "outdoorEnviSensorErr",
    "fullWaterProtection",
    "indoorEEPROMErr",
    "outdoorReturnAirSensorErr",
    "cbdCommErr",
    "indoorFanErr",
    "outdoorFanErr",
    "doorErr",
    "filterCleaningAlarm",
    "waterLackProtection",
    "humiditySensorErr",
    "indoorTempSensorErr",
    "mechanicalArmLimitErr",
    "indoorPM2p5SensorErr",
    "outdoorPM2p5SensorErr",
    "indoorHeatingOverloadAlarm",
    "outdoorACProtection",
    "outdoorCompressorRunningErr",
    "outdoorDCProtection",
    "outdoorUnloadedErr",
    "ctCurrentErr",
    "indoorFreezingProtection",
    "pressureProtection",
    "returnAirOverheatAlarm",
    "outdoorEvaporationSensorErr",
    "outdoorCoolingOverloadAlarm",
    "waterPumpErr",
    "threePhaseSupplyErr",
    "fourWayValveErr",
    "externalAlarmSwitchErr",
    "tempCuttingOffProtection",
    "differentModeRunningErr",
    "expansionValveErr",
    "twErr",
    "wireCtrCommErr",
    "indoorUnitIdConflictErr",
    "zeroPassageErr",
    "outdoorUnitErr",
    "ch2oSensorErr",
    "vocSensorErr",
    "co2SensorErr",
    "firewallErr",
)

_FAULTS = [
    "outdoorModuleErr",
    "outdoorDeforstSensorErr",
    "outdoorExhaustSensorErr",
    "outdoorEEPROMErr",
    "indoorCoilerSensorErr",
    "indoorOutdoorCommErr",
    "powerProtection",
    "panelCommErr",
    "outdoorCompressorOverheatProtection",
    "outdoorEnviSensorErr",
    "fullWaterProtection",
    "indoorEEPROMErr",
    "outdoorReturnAirSensorErr",
    "cbdCommErr",
    "indoorFanErr",
    "outdoorFanErr",
    "doorErr",
    "filterCleaningAlarm",
    "waterLackProtection",
    "humiditySensorErr",
    "indoorTempSensorErr",
    "mechanicalArmLimitErr",
    "indoorPM2p5SensorErr",
    "outdoorPM2p5SensorErr",
    "indoorHeatingOverloadAlarm",
    "outdoorACProtection",
    "outdoorCompressorRunningErr",
    "outdoorDCProtection",
    "outdoorUnloadedErr",
    "ctCurrentErr",
    "indoorFreezingProtection",
    "pressureProtection",
    "returnAirOverheatAlarm",
    "outdoorEvaporationSensorErr",
    "outdoorCoolingOverloadAlarm",
    "waterPumpErr",
    "threePhaseSupplyErr",
    "fourWayValveErr",
    "externalAlarmSwitchErr",
    "tempCuttingOffProtection",
    "differentModeRunningErr",
    "expansionValveErr",
    "twErr",
    "wireCtrCommErr",
    "indoorUnitIdConflictErr",
    "zeroPassageErr",
    "outdoorUnitErr",
    "ch2oSensorErr",
    "vocSensorErr",
    "co2SensorErr",
    "firewallErr",
]

_MODIFIERS = [
    {
        "trigger": {"operator": "AND", "conditions": {"silentSleepStatus": ['true']}},
        "invalid_code": "50002",
        "actions": [_lock("rapidMode"), _lock("selfCleaningStatus")],
    },
    {
        "trigger": {"operator": "AND", "conditions": {"operationMode": ['6']}},
        "invalid_code": "50009",
        "actions": [
            _lock("targetTemperature"), _lock("silentSleepStatus"), _lock("muteStatus"),
            _lock("rapidMode"), _lock("generatorMode")
        ],
    },
    {
        "trigger": {"operator": "AND", "conditions": {"operationMode": ['2']}},
        "invalid_code": "50008",
        "actions": [_lock("muteStatus"), _lock("rapidMode")],
    },
    {
        "trigger": {"operator": "AND", "conditions": {"operationMode": ['0']}},
        "invalid_code": "50005",
        "actions": [
            _lock("muteStatus"), _lock("rapidMode"), _lock("selfCleaningStatus"), _lock("generatorMode")
        ],
    },
    {
        "trigger": {"operator": "OR", "alarms": _FAULTS},
        "invalid_code": "50001",
        "actions": [
            _lock("targetTemperature"), _lock("windDirectionVertical"), _lock("operationMode"),
            _lock("windSpeed"), _lock("screenDisplayStatus"), _lock("echoStatus"),
            _lock("silentSleepStatus"), _lock("muteStatus"), _lock("rapidMode"), _lock("healthMode"),
            _lock("selfCleaningStatus"), _lock("generatorMode")
        ],
    },
    {
        "trigger": {"operator": "OR", "conditions": {
            "onOffStatus": ["false"], "selfCleaningStatus": ["true"],
        }},
        "invalid_code": "50002",
        "actions": [
            _lock("targetTemperature"), _lock("windDirectionVertical"), _lock("operationMode"),
            _lock("windSpeed"), _lock("screenDisplayStatus"), _lock("echoStatus"),
            _lock("silentSleepStatus"), _lock("muteStatus"), _lock("rapidMode"), _lock("healthMode"),
            _lock("generatorMode")
        ],
    },
]

# The settings that must travel together. A write that changes one of these also has to carry the
# others, or the unit applies the change and silently drops the rest: selecting fan-only while the
# fan is on auto is the case this project first met on real hardware, and the rule below is the
# device's own statement of it -- down to which concrete speed to substitute.
#
# ``mergeType`` says whether the extra settings go before or after the requested one.
_CONSTRAINTS = [{'pendingCondition': {'operator': 'AND', 'commands': {'operationMode': ['2']}},
  'additionalCommands': {'mergeType': 'APPEND',
                         'commands': [{'name': 'muteStatus', 'value': 'false'},
                                      {'name': 'rapidMode', 'value': 'false'},
                                      {'name': 'generatorMode', 'value': '0'}]}},
 {'pendingCondition': {'operator': 'AND', 'commands': {'operationMode': ['6']}},
  'additionalCommands': {'mergeType': 'PREPEND',
                         'commands': [{'name': 'windSpeed', 'value': '3'},
                                      {'name': 'silentSleepStatus', 'value': 'false'},
                                      {'name': 'muteStatus', 'value': 'false'},
                                      {'name': 'rapidMode', 'value': 'false'},
                                      {'name': 'generatorMode', 'value': '0'}]}},
 {'pendingCondition': {'operator': 'AND', 'commands': {'operationMode': ['0']}},
  'additionalCommands': {'mergeType': 'APPEND',
                         'commands': [{'name': 'targetTemperature', 'value': '24.00'},
                                      {'name': 'windSpeed', 'value': '5'},
                                      {'name': 'muteStatus', 'value': 'false'},
                                      {'name': 'rapidMode', 'value': 'false'},
                                      {'name': 'generatorMode', 'value': '0'}]}},
 {'pendingCondition': {'operator': 'AND', 'commands': {'onOffStatus': ['false']}},
  'additionalCommands': {'mergeType': 'PREPEND',
                         'commands': [{'name': 'selfCleaningStatus', 'value': 'false'},
                                      {'name': 'silentSleepStatus', 'value': 'false'}]}},
 {'pendingCondition': {'operator': 'AND', 'commands': {'onOffStatus': ['true']}},
  'additionalCommands': {'mergeType': 'APPEND',
                         'commands': [{'name': 'selfCleaningStatus', 'value': 'false'}]}},
 {'pendingCondition': {'operator': 'OR',
                       'commands': {'silentSleepStatus': ['true'], 'muteStatus': ['true']}},
  'additionalCommands': {'mergeType': 'APPEND',
                         'commands': [{'name': 'rapidMode', 'value': 'false'}]}},
 {'pendingCondition': {'operator': 'AND', 'commands': {'rapidMode': ['true']}},
  'additionalCommands': {'mergeType': 'APPEND',
                         'commands': [{'name': 'muteStatus', 'value': 'false'},
                                      {'name': 'generatorMode', 'value': '0'}]}},
 {'pendingCondition': {'operator': 'AND', 'commands': {'windSpeed': ['1', '2', '3']}},
  'additionalCommands': {'mergeType': 'PREPEND',
                         'commands': [{'name': 'rapidMode', 'value': 'false'},
                                      {'name': 'muteStatus', 'value': 'false'}]}},
 {'pendingCondition': {'operator': 'AND', 'commands': {'operationMode': ['6']}},
  'additionalCommands': {'mergeType': 'APPEND',
                         'commands': [{'name': 'silentSleepStatus', 'value': 'false'},
                                      {'name': 'muteStatus', 'value': 'false'},
                                      {'name': 'rapidMode', 'value': 'false'},
                                      {'name': 'generatorMode', 'value': '0'}]}},
 {'pendingCondition': {'operator': 'AND', 'commands': {'generatorMode': ['1', '2', '3']}},
  'additionalCommands': {'mergeType': 'PREPEND',
                         'commands': [{'name': 'rapidMode', 'value': 'false'}]}}]


# Keyed by the model identifier a unit reports for itself (the same one that selects its report
# layout). One family so far: the cooling-only shared-AC model these rules were read from.
DEVICE_RULES: Mapping[str, Mapping[str, Any]] = {
    "2008610800820324021200118012560000000000000000000000000000000040": {
        "modifiers": _MODIFIERS,
        "alarms": [{"name": name} for name in _ALARM_NAMES],
        "constraints": _CONSTRAINTS,
        "invalid_reasons": dict(INVALID_REASONS),
    },
}


# The sections a published model carries that a device's shadow does not: which settings it ignores
# in which state, the faults those rules name, and which settings must travel together.
RULE_SECTIONS = ("modifiers", "alarms", "constraints", "invalid_reasons")

# Not a rule, but it arrives in the same place and a shadow leaves it empty: the group commands, one
# of which lists the settings it carries IN WIRE ORDER. See :func:`declared_order`.
ORDER_SECTION = "groupCommands"

MERGED_SECTIONS = (*RULE_SECTIONS, ORDER_SECTION)


def merge_rules(model: dict[str, Any], published: Mapping[str, Any]) -> dict[str, Any]:
    """``model`` (a device's shadow: attributes and their live values) with the extra sections of its
    ``published`` model laid over it. Returns a new dict; sections the published model does not
    carry are left as they were."""
    merged = dict(model)
    for section in MERGED_SECTIONS:
        if published.get(section):
            merged[section] = published[section]
    if published.get("attributes"):
        # Always record the invisible set (even empty) once a real published model is in hand: its
        # PRESENCE is the signal that we know which of a device's attributes it actually has, which
        # is what the optional-feature entities gate on. A model without the key is one we cannot
        # yet tell real features from over-declared ones for, and gets no such entities.
        merged["invisible_attributes"] = sorted(invisible_attributes(published))
    return merged


def invisible_attributes(published: Mapping[str, Any] | None) -> frozenset[str]:
    """The attributes a published model marks ``invisible`` -- ones a generic model declares but this
    particular unit does not actually have, so the device reports them as a constant zero. The
    device shadow does not carry the flag; only the published constraintfile does. Empty when the
    model carries no such flags (e.g. one that was never topped up from its published form)."""
    out: set[str] = set()
    for attr in (published or {}).get("attributes") or []:
        if isinstance(attr, Mapping) and attr.get("name") and (
            attr.get("invisible") or attr.get("invisiable")
        ):
            out.add(str(attr["name"]))
    return frozenset(out)


def declared_order(model: Mapping[str, Any] | None) -> tuple[str, ...]:
    """The settings a device's group-set command carries, **in wire order**, or ``()``.

    A published model lists them word by word and, within a word, from the highest bit down. That
    ordering is the only thing any model says about attributes the shared position map does not
    carry: it cannot place one on its own, but it brackets each between the two mapped attributes
    either side of it, which turns "somewhere in this report" into a word and a few bits.

    Returns ``()`` for a shadow that was never topped up from its published model, which is what an
    un-merged one looks like — the section is present but empty.
    """
    section = (model or {}).get(ORDER_SECTION)
    groups = section.values() if isinstance(section, Mapping) else (section or ())
    for group in groups:
        names = (group or {}).get("attrNameList") if isinstance(group, Mapping) else None
        if names:
            return tuple(str(n) for n in names)
    return ()


def rules_for(uplus_id: str | None) -> Mapping[str, Any] | None:
    """The recorded rules for a model identifier, or ``None`` when none are known."""
    return DEVICE_RULES.get(uplus_id) if uplus_id else None


def with_rules(model: dict[str, Any] | None, uplus_id: str | None) -> dict[str, Any] | None:
    """``model`` with recorded rules filled in, if it arrived without any and any are known.

    Returns the model unchanged whenever it already states its own rules, when none are recorded for
    this identifier, or when there is no model at all — so this is safe to apply unconditionally.
    """
    if not model or model.get("modifiers"):
        return model
    known = rules_for(uplus_id)
    if not known:
        return model
    merged = dict(model)
    merged["modifiers"] = list(known["modifiers"])
    if not merged.get("alarms"):
        merged["alarms"] = list(known["alarms"])
    return merged
