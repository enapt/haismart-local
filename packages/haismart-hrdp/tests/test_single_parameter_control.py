"""Control for a device class whose firmware has no group set at all.

Almost every air conditioner here is commanded with one packed word block. A whole class of central
cabinets is not: they declare every attribute individually settable, they publish no group command
under any name, and their firmware **refuses** the group-set frame outright. Each setting is its own
command, with the value in the payload.

These tests pin the three things that makes safe: which attributes are offered, the exact bytes each
one sends, and that every one of them can still be read back out of the report.
"""
from __future__ import annotations

import pytest

from haismart_hrdp.wire_models import (
    SINGLE_PARAM_IDS,
    related_wire_model,
    value_param_write_fields,
)

#: What a central cabinet of this class announces. Both ends matter: the four characters at 16..20
#: name the device class the parameter registry is keyed on.
CENTRAL_UPLUS_ID = "201c10c7088081000d1205464544850000009cd68e692c104e2a333eab95d140"

#: A wall unit of the ordinary group-set generation, for the negative.
WALL_UPLUS_ID = "2008610800820324021200118012560000000000000000000000000000000040"

CENTRAL_DISPLACEMENT = -19
CENTRAL_LENGTH = 133


def _report(payload: str) -> bytes:
    """A report carrying ``payload`` as its attribute area (report word 1 = byte 92)."""
    body = bytes.fromhex(payload.replace(" ", ""))
    blob = bytearray(CENTRAL_LENGTH)
    blob[92:92 + len(body)] = body
    return bytes(blob)


# Attribute areas observed on an appliance of this identifier, with the states recorded alongside
# them: 28 C / cool / fan low / switched OFF, and 16 C / cool / fan low / switched ON.
REPORT_28C_OFF = _report("0C 00 23 00 02 00 14 00 00 00 00 00 01 00 00 03 09 03 2E 32 58")
REPORT_16C_ON = _report("00 00 23 00 02 01 14 00 00 00 00 00 01 00 00 03 09 03 30 32 58")


def _central() -> object:
    return related_wire_model(
        CENTRAL_LENGTH, CENTRAL_DISPLACEMENT, order=None, uplus_id=CENTRAL_UPLUS_ID
    )


def test_a_central_cabinet_is_commandable_although_it_publishes_no_group_set() -> None:
    """The old rule made control depend on a published group-set order, so this class -- which has
    none, and never will -- was monitoring-only. The mechanism it does have is enough."""
    wm = _central()
    assert wm.writable is True
    # ...and still no group set: the group-set encoder must keep refusing it, because the appliance
    # does. Offering both would let a caller reach the frame this firmware rejects.
    assert wm.group_cmd is None
    assert dict(wm.write_fields) == {}
    assert set(wm.value_param_fields) == {
        "onOffStatus", "targetTemperature", "operationMode",
        "windSpeed", "healthMode", "muteStatus", "rapidMode",
    }


@pytest.mark.parametrize(
    ("name", "value", "command", "payload"),
    [
        ("onOffStatus", 1, b"\x5d\x01", b"\x00\x01"),
        ("onOffStatus", 0, b"\x5d\x01", b"\x00\x00"),
        ("targetTemperature", 9, b"\x5d\x02", b"\x00\x09"),   # 25 C, sent as C - 16
        ("operationMode", 1, b"\x5d\x04", b"\x00\x01"),       # cool
        ("operationMode", 4, b"\x5d\x04", b"\x00\x04"),       # heat
        ("windSpeed", 3, b"\x5d\x05", b"\x00\x03"),           # low
        ("windSpeed", 5, b"\x5d\x05", b"\x00\x05"),           # auto
        ("healthMode", 1, b"\x5d\x0b", b"\x00\x01"),
        ("muteStatus", 1, b"\x5d\x19", b"\x00\x01"),
        ("rapidMode", 1, b"\x5d\x1a", b"\x00\x01"),
    ],
)
def test_the_command_bytes_are_the_published_parameter_ids(
    name: str, value: int, command: bytes, payload: bytes
) -> None:
    """One command per attribute, the value big-endian in two bytes. The caller hands values in the
    same representation every other family takes -- the setpoint as ``C - 16``, enums as their
    standard codes -- so nothing above the wire model needs to know which mechanism ran."""
    assert _central().encode_value_param(name, value) == (command, payload)


def test_the_vane_commands_are_withheld() -> None:
    """This generation defines an id for each vane, but no appliance of THIS class has been seen to
    accept one -- the one they were read from has no vane at all. An id that is unimplemented is
    refused and harmless; one that is implemented and means something else would move a setting
    nobody asked for, which is the failure this project does not ship."""
    wm = _central()
    for vane in ("windDirectionVertical", "windDirectionHorizontal"):
        assert vane not in wm.value_param_fields
        with pytest.raises(KeyError):
            wm.encode_value_param(vane, 0)


def test_a_control_is_read_back_from_the_report_not_from_what_was_sent() -> None:
    """A control written this way still shows real state, so a command the appliance declined shows
    as unchanged rather than as an echo of the request."""
    wm = _central()
    assert wm.value_param_value(REPORT_28C_OFF, "targetTemperature") == 12   # 28 C
    assert wm.value_param_value(REPORT_28C_OFF, "onOffStatus") == 0
    assert wm.value_param_value(REPORT_28C_OFF, "operationMode") == 1        # cool
    assert wm.value_param_value(REPORT_28C_OFF, "windSpeed") == 3            # low

    assert wm.value_param_value(REPORT_16C_ON, "targetTemperature") == 0     # 16 C
    assert wm.value_param_value(REPORT_16C_ON, "onOffStatus") == 1


def test_every_offered_control_can_also_be_read() -> None:
    """The standing rule: a family that writes a field must read it back. A control that cannot be
    read is worse than a missing one, so nothing may be offered without a position."""
    wm = _central()
    for name in wm.value_param_fields:
        assert wm.value_param_value(REPORT_28C_OFF, name) is not None, name


def test_the_report_places_its_climate_block_where_the_published_map_says() -> None:
    """The read side, pinned against a real report. These four are the anchors the layout rests on;
    if any of them moves, the offset this class is decoded at is wrong and control would be too."""
    wm = _central()
    assert wm.value_param_fields["targetTemperature"].read.word == 1
    assert wm.value_param_fields["operationMode"].read.word == 2
    assert wm.value_param_fields["windSpeed"].read.word == 2
    assert wm.value_param_fields["onOffStatus"].read.word == 3


def test_a_class_with_no_published_registry_gets_no_single_parameter_control() -> None:
    """Membership is per device class and nothing is inherited across classes: an id means different
    attributes in different classes, so a wall unit must not pick these up."""
    assert value_param_write_fields(CENTRAL_DISPLACEMENT, WALL_UPLUS_ID) == {}
    assert value_param_write_fields(CENTRAL_DISPLACEMENT, None) == {}
    # ...and a wall unit with no group-set order stays monitoring-only, exactly as before.
    assert related_wire_model(127, -19, order=None, uplus_id=WALL_UPLUS_ID).writable is False


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("targetTemperature", 99),   # past the range the setpoint accepts
        ("operationMode", 9),        # not a published mode code
        ("windSpeed", 9),            # not a published speed code
        ("onOffStatus", 2),          # a boolean is 0 or 1
    ],
)
def test_the_encoder_refuses_a_value_the_attribute_does_not_accept(
    name: str, value: int
) -> None:
    """The same guard the group-set encoder applies: control may only ever emit a mapped attribute
    with a supported value. A payload is 16 bits wide, so the bound has to come from the attribute
    rather than from the width of a packed field."""
    with pytest.raises(ValueError):
        _central().encode_value_param(name, value)


def test_the_registry_is_keyed_on_the_device_class_alone() -> None:
    assert set(SINGLE_PARAM_IDS) == {"0d12"}
    assert SINGLE_PARAM_IDS["0d12"]["onOffStatus"] == 0x01
    assert SINGLE_PARAM_IDS["0d12"]["targetTemperature"] == 0x02
