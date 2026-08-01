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
        "actions": [_lock("rapidMode"), _lock("selfCleaningStatus")],
    },
    {
        "trigger": {"operator": "AND", "conditions": {"operationMode": ['6']}},
        "actions": [
            _lock("targetTemperature"), _lock("silentSleepStatus"), _lock("muteStatus"),
            _lock("rapidMode"), _lock("generatorMode")
        ],
    },
    {
        "trigger": {"operator": "AND", "conditions": {"operationMode": ['2']}},
        "actions": [_lock("muteStatus"), _lock("rapidMode")],
    },
    {
        "trigger": {"operator": "AND", "conditions": {"operationMode": ['0']}},
        "actions": [
            _lock("muteStatus"), _lock("rapidMode"), _lock("selfCleaningStatus"), _lock("generatorMode")
        ],
    },
    {
        "trigger": {"operator": "OR", "alarms": _FAULTS},
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
        "actions": [
            _lock("targetTemperature"), _lock("windDirectionVertical"), _lock("operationMode"),
            _lock("windSpeed"), _lock("screenDisplayStatus"), _lock("echoStatus"),
            _lock("silentSleepStatus"), _lock("muteStatus"), _lock("rapidMode"), _lock("healthMode"),
            _lock("generatorMode")
        ],
    },
]


# Keyed by the model identifier a unit reports for itself (the same one that selects its report
# layout). One family so far: the cooling-only shared-AC model these rules were read from.
DEVICE_RULES: Mapping[str, Mapping[str, Any]] = {
    "2008610800820324021200118012560000000000000000000000000000000040": {
        "modifiers": _MODIFIERS,
        "alarms": [{"name": name} for name in _ALARM_NAMES],
    },
}


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
