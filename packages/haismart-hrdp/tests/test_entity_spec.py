"""Which entity each attribute becomes — the layer that lets an unowned appliance work out of the box.

There is no reporter for most of these appliances and there is not going to be one, so the rules
have to be right from the published model alone. What is asserted here is the classification, not
any particular device: a rule that works only for the one appliance it was written against is the
thing being avoided.
"""
from __future__ import annotations

import re

import pytest

from haismart_hrdp.device_model import device_classes, known_typeids, model_for
from haismart_hrdp.entity_spec import Control, english_name, specs_for

WATER_HEATER = "201c120000118674200100418007574800000000000000000000000000000040"
WASHER = "201c51890c31c30805010021800239584d000000000000000000000000000140"

# The reporter's own declaration for issue #13's appliance (29 attributes), vendored so this test
# needs no capture file.
_DECLARED = [
    {"name": "currentTemperature", "writable": False,
     "valueRange": {"type": "STEP", "dataStep": {"minValue": "0", "maxValue": "110", "step": "1"}}},
    {"name": "targetTemperature", "writable": True,
     "valueRange": {"type": "STEP", "dataStep": {"minValue": "35", "maxValue": "75", "step": "1"}}},
    {"name": "dualHeaterMode", "writable": True,
     "valueRange": {"type": "LIST", "dataList": [{"data": "false"}, {"data": "true"}]}},
    {"name": "runningMode", "writable": True,
     "valueRange": {"type": "LIST", "dataList": [
         {"data": "2"}, {"data": "3"}, {"data": "4"}, {"data": "5"},
         {"data": "6"}, {"data": "19"}, {"data": "20"}, {"data": "22"}]}},
    {"name": "workStatus", "writable": False,
     "valueRange": {"type": "LIST", "dataList": [{"data": "1"}, {"data": "2"}]}},
    {"name": "oddHotWater", "writable": False,
     "valueRange": {"type": "STEP", "dataStep": {"minValue": "0", "maxValue": "65535", "step": "1"}}},
    {"name": "resn1TimeHH", "writable": True,
     "valueRange": {"type": "STEP", "dataStep": {"minValue": "0", "maxValue": "23", "step": "1"}}},
    {"name": "time", "writable": True, "valueRange": {"type": "TIME"}},
]


def _specs(**kwargs):
    model = model_for(WATER_HEATER)
    assert model is not None
    return {s.attribute: s for s in specs_for(model, _DECLARED, **kwargs)}


def test_nothing_becomes_an_entity_unless_the_device_declares_it() -> None:
    """The gate that stops 503 mapped fields becoming 503 entities.

    The class map lists what the PLATFORM can carry; a device declares a subset. This is the single
    rule standing between "works out of the box" and "every appliance gets hundreds of entities
    that read zero for ever".
    """
    model = model_for(WATER_HEATER)
    assert model is not None
    assert len(model.fields) > 400
    assert len(specs_for(model, _DECLARED)) <= len(_DECLARED)
    # ...and a device that has declared nothing yet gets nothing, rather than the whole class map.
    assert specs_for(model, []) == ()
    assert specs_for(model, None) == ()
    assert specs_for(None, _DECLARED) == ()


def test_a_writable_two_value_enum_is_a_switch_and_a_read_only_one_is_a_binary_sensor() -> None:
    """Half the catalogue -- 8,218 fields -- is a two-value enum. A dropdown for each would be absurd."""
    writable = _specs(writable=["dualHeaterMode"])
    readonly = _specs()
    assert writable["dualHeaterMode"].control is Control.SWITCH
    assert readonly["dualHeaterMode"].control is Control.BINARY_SENSOR


def test_a_multi_value_enum_is_a_select_only_where_a_write_id_exists() -> None:
    """A control the appliance publishes no way to write is a control that would silently fail."""
    assert _specs(writable=["runningMode"])["runningMode"].control is Control.SELECT
    assert _specs()["runningMode"].control is Control.SENSOR


def test_a_select_offers_only_what_this_device_declares() -> None:
    """Its class defines 19 running modes; this unit declares 8. The other 11 would be discarded."""
    spec = _specs(writable=["runningMode"])["runningMode"]
    assert [value for value, _ in spec.options] == ["2", "3", "4", "5", "6", "19", "20", "22"]


def test_a_number_carries_the_devices_own_range_not_the_classs() -> None:
    """35-75 from the unit, not 30-80 from the class map. The narrower one is what a user has."""
    spec = _specs(writable=["targetTemperature"])["targetTemperature"]
    assert spec.control is Control.NUMBER
    assert (spec.minimum, spec.maximum, spec.step) == (35.0, 75.0, 1.0)
    assert spec.device_class == "temperature"


def test_a_read_only_number_is_a_sensor_with_its_unit_and_state_class() -> None:
    spec = _specs()["oddHotWater"]
    assert spec.control is Control.SENSOR
    assert spec.unit == "L" and spec.device_class == "volume"
    assert spec.state_class == "measurement"


def test_a_clock_component_is_not_given_a_duration_device_class() -> None:
    """Haier declares `resn1TimeHH` with unit "h" -- its meaning, not its dimension.

    Rendered as a duration, Home Assistant shows "6 h" for six o'clock. The name carries the
    meaning instead, and no false semantics are attached.
    """
    spec = _specs(writable=["resn1TimeHH"])["resn1TimeHH"]
    assert spec.name == "Reservation 1 hour"
    assert spec.device_class is None and spec.unit is None and spec.state_class is None


def test_a_hero_platform_can_claim_an_attribute_so_it_is_not_duplicated() -> None:
    """A water heater's setpoint belongs to its water_heater entity, not a second number beside it."""
    claimed = {s.attribute for s in specs_for(
        model_for(WATER_HEATER), _DECLARED,
        writable=["targetTemperature"], exclude=["targetTemperature"],
    )}
    assert "targetTemperature" not in claimed


def test_opaque_identifiers_and_reset_commands_never_become_entities() -> None:
    """`forceDelete` is a factory reset Haier models as an attribute, on 118 device classes.

    `token` and `clientId` are credentials. Neither is a thing to put on a dashboard, and the first
    is a thing to put there least of all.
    """
    declared = [{"name": n} for n in ("forceDelete", "token", "clientId", "uniqueId", "machineId")]
    assert specs_for(model_for(WASHER), declared) == ()


@pytest.mark.parametrize(
    ("attribute", "expected"),
    [
        ("onOffStatus", "Power"),
        ("heatingRodWorkingTime", "Heating rod working time"),
        ("resn2Temperature", "Reservation 2 temperature"),
        ("resn1TimeMM", "Reservation 1 minute"),
        ("valleyStartTimeHH", "Off peak start hour"),
        ("tds", "TDS"),
        ("3dRunningStatus", "3D running status"),
        ("totalElectricityUsed", "Total electricity used"),
        ("heatingCruiseSatus", "Heating cruise status"),   # a typo in Haier's own model
        ("relay3ActionNum", "Relay 3 action count"),
        ("operationSrc", "Changed by"),
        ("Child_Security_Lock", "Child security lock"),   # a class that uses Snake_Case throughout
        ("LED_Air_Quality", "LED air quality"),
    ],
)
def test_names_read_as_english(attribute: str, expected: str) -> None:
    """Haier's names are English camelCase, so the mechanical split is right for most of the 1,676.

    Curation is for the rest. What must never happen is an entity called `heatingRodWorkingTime`.
    """
    assert english_name(attribute) == expected


def test_every_name_in_the_whole_catalogue_comes_out_readable() -> None:
    """A property over all 1,676 distinct attribute names, because 1,676 cannot be reviewed by eye.

    Not a claim that each reads WELL -- only that none comes back as a raw identifier or empty,
    which is the failure that would actually reach a user's dashboard.
    """
    unsplit = re.compile(r"[a-z][A-Z]|_")
    bad: list[str] = []
    for typeid in known_typeids():
        model = model_for(typeid)
        assert model is not None
        for field in model.fields:
            name = english_name(field.name)
            # An all-caps acronym coming back unchanged is correct ("MSA", "TDS"). What is not is a
            # name that still carries a camelCase hump or an underscore -- that is a split that did
            # not happen, and it reaches the dashboard verbatim.
            if not name or unsplit.search(name):
                bad.append(field.name)
    assert not bad, f"unreadable: {sorted(set(bad))[:20]}"


def test_the_classifier_produces_something_for_every_device_class_we_carry() -> None:
    """Out of the box means every class, so this asserts over all 36 rather than the two tested.

    Each map is fed its own fields as though the device declared all of them, which is the upper
    bound rather than what a real unit gets -- the point is that no class classifies to nothing,
    which would be an appliance that pairs and then shows no entities at all.
    """
    empty: list[str] = []
    for device_class in sorted(device_classes()):
        typeid = next(
            t for t in sorted(known_typeids()) if model_for(t).device_class == device_class
        )
        model = model_for(typeid)
        assert model is not None
        declared = [{"name": f.name} for f in model.fields_for()]
        specs = specs_for(model, declared, writable=[f.name for f in model.writable_fields()])
        if not specs:
            empty.append(f"{device_class} ({typeid})")
    assert not empty, f"device classes that produce no entities at all: {empty}"
