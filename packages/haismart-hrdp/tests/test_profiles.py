"""Tests for the AAC1UKZ01 attribute profile (from the device digital model + app-UI correlation)."""
import json
import pathlib

from haismart_hrdp import AttributeProfile, profile_for, profile_from_device_config
from haismart_hrdp.profiles import AAC1UKZ01, AAC1UKZ01_ATTRIBUTES

_DEVCONFIG = pathlib.Path(__file__).parent / "fixtures" / "AAC1UKZ01_devconfig.json"


def test_profile_lookup_by_product_code():
    assert profile_for("AAC1UKZ01") is AAC1UKZ01
    assert profile_for("PID_AAC1UKZ01") is AAC1UKZ01
    # unknown -> generic default, never a crash
    assert isinstance(profile_for("SOMETHING_ELSE"), AttributeProfile)
    assert isinstance(profile_for(None), AttributeProfile)


def test_mode_enum_confirmed_values():
    # CONFIRMED against the app UI on real hardware
    assert AAC1UKZ01.normalized_mode("1") == "cool"
    assert AAC1UKZ01.normalized_mode("6") == "fan_only"
    assert AAC1UKZ01.std_mode("cool") == "1"
    assert AAC1UKZ01.std_mode("fan_only") == "6"


def test_fan_enum_confirmed_values():
    assert AAC1UKZ01.normalized_fan("2") == "medium"
    assert AAC1UKZ01.normalized_fan("3") == "low"
    assert AAC1UKZ01.std_fan("low") == "3"


def test_power_and_attr_names():
    assert AAC1UKZ01.power_attr == "onOffStatus"
    assert AAC1UKZ01.power_on_value == "true" and AAC1UKZ01.power_off_value == "false"
    assert AAC1UKZ01.target_temp_attr == "targetTemperature"
    assert AAC1UKZ01.fan_attr == "windSpeed"
    assert AAC1UKZ01.mode_attr == "operationMode"


def test_full_attribute_list_present():
    for core in ("onOffStatus", "operationMode", "targetTemperature", "indoorTemperature", "windSpeed"):
        assert core in AAC1UKZ01_ATTRIBUTES
    assert len(AAC1UKZ01_ATTRIBUTES) > 40  # the AC exposes a large STD attribute set


def test_validate_write_against_model():
    from haismart_hrdp import validate_write, writable_attributes
    cfg = json.loads(_DEVCONFIG.read_text())
    # valid writes
    assert validate_write(cfg, "operationMode", "1")[0] is True   # cool (enum member)
    assert validate_write(cfg, "operationMode", 6)[0] is True      # fan (int coerced)
    assert validate_write(cfg, "targetTemperature", 24)[0] is True
    assert validate_write(cfg, "targetTemperature", "16")[0] is True
    # rejected writes — the safety guard
    assert validate_write(cfg, "operationMode", "4")[0] is False   # heat: not on this model
    assert validate_write(cfg, "targetTemperature", 40)[0] is False  # out of range
    assert validate_write(cfg, "targetTemperature", 24.5)[0] is False  # off the step grid (step 1)
    assert validate_write(cfg, "indoorTemperature", 20)[0] is False  # read-only sensor
    assert validate_write(cfg, "notARealAttribute", "1")[0] is False
    # writable set excludes read-only sensors
    w = writable_attributes(cfg)
    assert "operationMode" in w and "targetTemperature" in w
    assert "indoorTemperature" not in w and "outdoorTemperature" not in w


def _with_heat(config: dict) -> dict:
    """The real cooling-only model, plus operationMode 4 (heat) — i.e. a heat-pump unit's model."""
    for attr in config["attributes"]:
        if attr["name"] == "operationMode":
            attr["valueRange"]["dataList"].insert(3, {"data": "4", "desc": "制热"})
    return config


def test_model_enum_codes_reports_declared_values():
    from haismart_hrdp import model_enum_codes
    cfg = json.loads(_DEVCONFIG.read_text())
    assert model_enum_codes(cfg, "operationMode") == {0, 1, 2, 6}   # cooling-only: no heat
    assert model_enum_codes(cfg, "windSpeed") == {1, 2, 3, 5}
    assert model_enum_codes(_with_heat(cfg), "operationMode") == {0, 1, 2, 4, 6}
    # bools (LIST of 'false'/'true') and unknown/read-only-range attrs carry no numeric codes
    assert model_enum_codes(cfg, "screenDisplayStatus") == set()
    assert model_enum_codes(cfg, "targetTemperature") == set()
    assert model_enum_codes(cfg, "notARealAttribute") == set()


def test_heat_mode_self_maps_from_a_heat_capable_model():
    # A heat-pump unit's own model is what teaches the profile its heat code (nothing hardcoded).
    p = profile_from_device_config(_with_heat(json.loads(_DEVCONFIG.read_text())))
    assert p.mode_values == {"0": "auto", "1": "cool", "2": "dry", "4": "heat", "6": "fan_only"}
    assert p.std_mode("heat") == "4" and p.normalized_mode("4") == "heat"


def test_mode_enum_falls_back_to_std_codes_for_unrecognised_descriptions():
    # Descriptions are Haier's and not guaranteed to be Chinese; English wording still maps...
    english = {"attributes": [{"name": "operationMode", "valueRange": {"type": "LIST", "dataList": [
        {"data": "1", "desc": "Cooling"}, {"data": "4", "desc": "Heating"},
        {"data": "6", "desc": "Fan"}]}}]}
    assert profile_from_device_config(english).mode_values == {
        "1": "cool", "4": "heat", "6": "fan_only"}
    # ...and a description that matches nothing falls back to the standard split-AC code table.
    blank = {"attributes": [{"name": "operationMode", "valueRange": {"type": "LIST", "dataList": [
        {"data": "1", "desc": ""}, {"data": "4"}, {"data": "9", "desc": "???"}]}}]}
    assert profile_from_device_config(blank).mode_values == {"1": "cool", "4": "heat"}


def test_profile_from_real_device_config():
    # the queryable digital model (constraintfile) should self-derive the same authoritative enums
    config = json.loads(_DEVCONFIG.read_text())
    p = profile_from_device_config(config)
    assert p.mode_values == {"0": "auto", "1": "cool", "2": "dry", "6": "fan_only"}  # no heat
    assert p.fan_values == {"1": "high", "2": "medium", "3": "low", "5": "auto"}
    assert (p.min_temp, p.max_temp, p.temp_step) == (16.0, 30.0, 1.0)
    # matches the hand-verified hardcoded profile
    assert p.mode_values == AAC1UKZ01.mode_values and p.fan_values == AAC1UKZ01.fan_values


# The rules a real device model carries, verbatim in shape.
_RULES = {
    "constraints": [
        {"pendingCondition": {"operator": "AND", "commands": {"operationMode": ["6"]}},
         "additionalCommands": {"mergeType": "PREPEND", "commands": [
             {"name": "windSpeed", "value": "3"},
             {"name": "muteStatus", "value": "false"},
             {"name": "generatorMode", "value": "0"}]}},
        {"pendingCondition": {"operator": "AND", "commands": {"rapidMode": ["true"]}},
         "additionalCommands": {"commands": [{"name": "muteStatus", "value": "false"}]}},
        {"pendingCondition": {"operator": "AND", "commands": {"windSpeed": ["1", "2", "3"]}},
         "additionalCommands": {"commands": [
             {"name": "rapidMode", "value": "false"},
             {"name": "muteStatus", "value": "false"}]}},
    ],
    "modifiers": [
        {"priority": 4, "trigger": {"operator": "AND", "conditions": {"operationMode": ["6"]}},
         "actions": [{"name": "targetTemperature", "writable": False},
                     {"name": "muteStatus", "writable": False}]},
        {"priority": 1, "trigger": {"operator": "OR", "conditions": {},
                                    "alarms": ["indoorTempSensorErr", "outdoorFanErr"]},
         "actions": [{"name": "operationMode", "writable": False}]},
    ],
}


def test_constraint_commands_adds_what_the_unit_requires():
    from haismart_hrdp import constraint_commands

    # fan-only will not take an auto wind speed, and the model says which speed to send with it
    assert constraint_commands(_RULES, {"operationMode": "6"}) == {
        "windSpeed": "3", "muteStatus": "false", "generatorMode": "0"
    }
    # strong and quiet are mutually exclusive
    assert constraint_commands(_RULES, {"rapidMode": "true"}) == {"muteStatus": "false"}
    # ...and choosing a concrete speed cancels both
    assert constraint_commands(_RULES, {"windSpeed": "2"}) == {
        "rapidMode": "false", "muteStatus": "false"
    }


def test_an_explicit_request_outranks_a_rule():
    """A rule supplies a default, so it must not overwrite what the caller actually asked for."""
    from haismart_hrdp import constraint_commands

    extra = constraint_commands(_RULES, {"operationMode": "6", "windSpeed": "1"})
    assert "windSpeed" not in extra, "the caller's own choice of speed was overwritten"
    # setting a concrete speed is itself a trigger, so that rule's commands come along too
    assert extra == {"muteStatus": "false", "generatorMode": "0", "rapidMode": "false"}


def test_constraint_commands_is_quiet_without_rules():
    from haismart_hrdp import constraint_commands

    assert constraint_commands(None, {"operationMode": "6"}) == {}
    assert constraint_commands({}, {"operationMode": "6"}) == {}
    assert constraint_commands(_RULES, {"operationMode": "1"}) == {}


def test_locked_attributes_covers_state_and_faults():
    from haismart_hrdp import locked_attributes

    assert locked_attributes(_RULES, {"operationMode": "6"}) == frozenset(
        {"targetTemperature", "muteStatus"}
    )
    assert locked_attributes(_RULES, {"operationMode": "1"}) == frozenset()
    # a fault locks the rule's attributes whatever the state is
    assert locked_attributes(_RULES, {"operationMode": "1"}, ["outdoorFanErr"]) == frozenset(
        {"operationMode"}
    )
    assert locked_attributes(None, {"operationMode": "6"}) == frozenset()
