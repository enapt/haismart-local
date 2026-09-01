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
        # Offered on the appliance's own terms -- see the provisional test below.
        "windDirectionVertical", "windDirectionHorizontal",
        # Display unit (°C/°F). Confirmed like the nine above from Haier's own device config
        # (eppCmd 5D07); reads back in the climate block, so it is placed by displacement, not
        # provisionally.
        "tempUnit",
        # Presence airflow. Id `5D23` from Haier's own device config; ships provisional only because
        # the write has not been exercised on a cabinet -- read back from w23.b6/2, withdrawn if it
        # does not take.
        "humanSensingStatus",
        # The four-way cassette louvres live INSIDE the report's inserted block, so they are offered
        # only when the model is built with an insert (a real 133-byte report). This model is built
        # with none, which is exactly why they are absent here -- see the inserted-block test below.
    }
    # And it is the provisional one, so the appliance settles it.
    assert wm.value_param_fields["humanSensingStatus"].provisional is True
    assert wm.value_param_fields["humanSensingStatus"].param_id == 0x23


CENTRAL_INSERT = (25, 4)  # a real 133-byte report: (length - 125) / 2 = 4 words inserted at w25


def _central_with_block() -> object:
    return related_wire_model(
        CENTRAL_LENGTH, CENTRAL_DISPLACEMENT,
        order=None, uplus_id=CENTRAL_UPLUS_ID, insert=CENTRAL_INSERT,
    )


def test_temp_unit_is_a_settled_control_translated_between_std_and_epp() -> None:
    """°C/°F. Confirmed like the nine climate ids from Haier's own config (eppCmd 5D07), and unlike
    them it is NOT identity: std 1/2 (the model's codes) map to epp 0/1 on the wire, so the encode
    must translate and the read-back must translate the other way, or the control would set °F when
    asked for °C and show the wrong unit."""
    wm = _central_with_block()
    tu = wm.value_param_fields["tempUnit"]
    assert tu.provisional is False and tu.param_id == 0x07
    # write: std -> command 0x5D07 and the config's epp payload
    assert wm.encode_value_param("tempUnit", 1) == (b"\x5d\x07", b"\x00\x00")  # °C  -> epp 0
    assert wm.encode_value_param("tempUnit", 2) == (b"\x5d\x07", b"\x00\x01")  # °F  -> epp 1
    with pytest.raises(ValueError):
        wm.encode_value_param("tempUnit", 5)                                   # not a unit code
    # read: the report's raw epp comes back as the model's std code (climate block, report w3.b13)
    rep = bytearray(CENTRAL_LENGTH)
    rep[92 + (3 - 1) * 2 + 1] = 0x00               # bit 13 clear -> epp 0
    assert wm.value_param_value(bytes(rep), "tempUnit") == 1                   # °C
    rep[92 + (3 - 1) * 2] = 0x20                    # word 3 high byte bit 13 set -> epp 1
    assert wm.value_param_value(bytes(rep), "tempUnit") == 2                   # °F


def test_four_sided_louvres_are_provisional_inside_the_inserted_block() -> None:
    """The four-way cassette louvres. Their write ids are as solid as the nine (Haier's config gives
    each one), but they read back from word 6 -- inside the report's inserted block -- which no wire
    capture has shown populated, so they ship provisional: written by id, settled by their own
    read-back. They exist only where the report carries the block."""
    wm = _central_with_block()
    for i, (pid, bit) in {1: (0x0F, 8), 2: (0x0E, 12), 3: (0x11, 0), 4: (0x10, 4)}.items():
        vp = wm.value_param_fields[f"4SidesWindDirection{i}"]
        assert vp.provisional is True and vp.param_id == pid
        assert (vp.read.word, vp.read.bit, vp.read.length) == (6, bit, 4)
    # write: the config's non-linear std->epp (stop 3 -> epp 6, stop 6/"auto" -> epp 12)
    assert wm.encode_value_param("4SidesWindDirection1", 3) == (b"\x5d\x0f", b"\x00\x06")
    assert wm.encode_value_param("4SidesWindDirection1", 6) == (b"\x5d\x0f", b"\x00\x0c")
    # read: epp in the inserted block decodes back to the model's stop number
    rep = bytearray(CENTRAL_LENGTH)
    off = 92 + (6 - 1) * 2                          # report word 6
    rep[off] = (6 << 0) | (2 << 4)                  # high byte: b8-11 = epp 6, b12-15 = epp 2
    assert wm.value_param_value(bytes(rep), "4SidesWindDirection1") == 3       # epp 6 -> stop 3
    assert wm.value_param_value(bytes(rep), "4SidesWindDirection2") == 1       # epp 2 -> stop 1

    # ...and NOT offered on a model built without the block: the inserted word would not exist.
    no_block = _central()
    assert "4SidesWindDirection1" not in no_block.value_param_fields
    assert "tempUnit" in no_block.value_param_fields                           # climate block stays


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


def test_the_vane_commands_are_settled() -> None:
    """Both axes are ordinary controls now: an owner of a cabinet of this class moved each of them.

    They were the last two ids nobody had watched an appliance accept -- the cabinet whose traffic
    was recorded has no vane -- so they shipped able to retire themselves if the number turned out
    to address something else. It did not, on either axis, so they are settled on the same footing
    as the other seven: observed, on hardware of this class.
    """
    wm = _central()
    for vane in ("windDirectionVertical", "windDirectionHorizontal"):
        param = wm.value_param_fields[vane]
        assert param.provisional is False, "observed on hardware -- no longer self-adjudicating"
        assert wm.value_param_value(REPORT_28C_OFF, vane) is not None, "and still read back"
    assert wm.value_param_fields["windDirectionVertical"].param_id == 0x03
    assert wm.value_param_fields["windDirectionHorizontal"].param_id == 0x0C


def test_presence_is_a_provisional_control_written_via_5d23() -> None:
    """Presence airflow (off/avoid/follow/on) is a main-board attribute -- reported at w23.b6/2 --
    set by single-parameter id ``0x23``. The id is Haier's own: the manufacturer's device config for
    both central-cabinet families gives ``humanSensingStatus`` the write command ``5D23`` (and the
    nine ids confirmed on hardware match the same config). Provisional only because the write has not
    yet been exercised on a cabinet: written as ``0x5D00 | 0x23``, a big-endian value, read back from
    w23.b6/2. (``0x08`` was a wrong earlier guess -- the config shows it is ``halfDegreeSettingStatus``.)
    """
    from haismart_hrdp.uss import build_epp_frame

    wm = _central()
    param = wm.value_param_fields["humanSensingStatus"]
    assert param.param_id == 0x23
    assert param.provisional is True
    assert param.read.word == 4  # canonical w23 at this class's -19 displacement
    for code in (0, 1, 2, 3):    # off / avoid / follow / on all encode
        cmd, payload = wm.encode_value_param("humanSensingStatus", code)
        assert cmd == b"\x5d\x23"
        assert payload == code.to_bytes(2, "big")
    # the whole frame, the vendor's own shape
    cmd, payload = wm.encode_value_param("humanSensingStatus", 2)
    assert build_epp_frame(0x01, cmd, payload).hex() == "ffff0c000000000000015d2300028f"


def test_the_vane_frame_is_the_shape_the_vendors_own_encoder_emits() -> None:
    """The half of a write the id does not decide. Recorded byte for byte from the vendor's
    `epp_parser_attr_write_v2` on a published profile: frame type 1, `0x5D00 | id`, a big-endian
    16-bit value, and the checksum over the lot. If our framing were wrong every id would fail and
    the read-back gate would retire perfectly good ones."""
    from haismart_hrdp.uss import build_epp_frame

    wm = _central()
    cmd, payload = wm.encode_value_param("onOffStatus", 1)
    assert build_epp_frame(0x01, cmd, payload) == bytes.fromhex("ffff0c000000000000015d0100016c")
    cmd, payload = wm.encode_value_param("windDirectionVertical", 2)
    assert build_epp_frame(0x01, cmd, payload).hex() == "ffff0c000000000000015d0300026f"


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
