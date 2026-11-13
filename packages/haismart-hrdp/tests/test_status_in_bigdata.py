"""The status report a family's big-data report carries (issue #21).

A wall unit of Haier's SE-Asia 2024 family opened every session with its big-data report (`7d01`)
and no status report at all, so nothing decoded and setup failed. Haier's own byte map for that
family repeats every status attribute in the big-data report at the same word and bit with the same
value table, and the report's leading words are the status report's words -- so the status is read
from there. The rule comes from the map, not from the identifier: it applies to any family whose
map has that shape, and to no other.
"""
from __future__ import annotations

import pytest

from haismart_hrdp.uss import (
    EPP_FRAME_HEAD,
    is_extended_status_frame,
    parse_extended_status,
    parse_full_status,
    status_from_bigdata,
)

SEA_2024 = "2008610800820324021200118018900000000000000000000000000000000040"
JP_2024 = "2008610800820324021200118018500000000000000000000000000000000040"
#: Two families whose big-data report repeats the status at the same positions but NOT with the same
#: value tables -- the 0d12 cabinets (the four-sided vanes count 0/2/4/6/8 in one, 0/1/2/3/4 in the
#: other) and the classic shared wall units -- so neither reads its status from there.
CABINET = "201c10c7088081000d1205464544850000009cd68e692c104e2a333eab95d140"
CLASSIC = "2008610800820324021200118012560000000000000000000000000000000040"

#: Issue #21's report, as the unit sent it in every session -- only the envelope's device id is
#: replaced with an illustrative one. On, cooling to 29 C in a 29 C room, fan auto, outdoors 28 C,
#: 155 W with the compressor stopped, 253,206 Wh so far. The envelope is the one tag set seen only
#: on this unit (`05 08 …`, then `06 0a` and a ten-character id); the frame still starts at byte 80.
ISSUE21_BIGDATA = bytes.fromhex(
    "00002715000000004e560100000302000005080000000000000000060a413142324333443445350000000000000000"
    "00000000000000000000000000000000000000000000000000000000000000006effff6a000000000000067d012064"
    "0000000000000000000000000000000000000000000000000000000000000000010000000d06250002031600000c3a"
    "005c8000000000000000000000000000000003dd160000000000000003dd16009b009b60610000000001ff022401e0"
    "27"
)

#: Issue #19 (a second japan-wall unit, switched off): one session's status push and the big-data
#: report from the same session, exactly as its diagnostics kept them.
JP_PUSH = bytes.fromhex(
    "00002715000000004e5601000003020000040100000000000000000000000000000000000000000000000000000000"
    "00000000000000000000000000000000000000000000000000000000000000001fffff1c000000000000066d013604"
    "00040000020000000000000046306700ad"
)
JP_BIGDATA = bytes.fromhex(
    "00002715000000004e5601007a0302007a040100000000000000000000000000000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000000000000100000031ffff2e000000000000067d013604"
    "00040000020000000000000046306700007066630063000000000001e03600001acb67"
)


def _words(blob: bytes) -> bytes:
    at = blob.find(EPP_FRAME_HEAD)
    return blob[at + 12:-1]


def test_the_fixture_is_the_frame_the_unit_sent() -> None:
    assert len(ISSUE21_BIGDATA) == 189
    assert ISSUE21_BIGDATA.find(EPP_FRAME_HEAD) == 80
    assert is_extended_status_frame(ISSUE21_BIGDATA)
    # the frame's own checksum, which counts the 0x55 that follows its one stuffed 0xFF on the wire
    body = ISSUE21_BIGDATA[82:-1]
    assert (sum(body) + 0x55 * body.count(0xFF)) & 0xFF == ISSUE21_BIGDATA[-1]


def test_nothing_decodes_the_report_as_it_arrives() -> None:
    """The failure: a session that carried only this report gave Home Assistant no status."""
    assert parse_full_status(ISSUE21_BIGDATA, uplus_id=SEA_2024) == {}


def test_the_report_carries_the_familys_status() -> None:
    status = status_from_bigdata(ISSUE21_BIGDATA, SEA_2024)
    assert status is not None
    # the family's own status report: 41 words, which is the 175-byte report issue #8's unit sends
    assert len(status) == 175
    assert _words(status) == _words(ISSUE21_BIGDATA)[:82]
    state = parse_full_status(status, uplus_id=SEA_2024)
    assert state["power"] is True
    assert state["operation_mode"] == "1"        # cool
    assert state["target_temperature"] == 29.0
    assert state["current_temperature"] == 29.0
    assert state["wind_speed"] == "5"            # auto
    assert state["outdoor_temperature"] == 28.0
    assert state["power_w"] == 155
    assert state["energy_wh"] == 253206
    assert state["writable"] is True


def test_the_status_keeps_the_reports_kind_and_a_valid_checksum() -> None:
    """Still a REPORT (frame type 06), never mistaken for the appliance answering a query."""
    status = status_from_bigdata(ISSUE21_BIGDATA, SEA_2024)
    at = status.find(EPP_FRAME_HEAD)
    assert status[at + 9] == 0x06
    assert status[at + 10:at + 12] == b"\x6d\x01"
    assert status[at + 2] == len(status) - at - 3
    body = status[at + 2:-1]
    assert (sum(body) + 0x55 * body.count(0xFF)) & 0xFF == status[-1]
    assert status[:at] == ISSUE21_BIGDATA[:at]


def test_on_a_second_family_it_reproduces_the_sessions_own_push() -> None:
    """Ground truth the rule was not built from: where a session carried both reports, the status
    taken from the big-data report is the push, word for word."""
    status = status_from_bigdata(JP_BIGDATA, JP_2024)
    assert status is not None
    assert len(status) == len(JP_PUSH)
    assert _words(status) == _words(JP_PUSH)
    assert parse_full_status(status, uplus_id=JP_2024) == parse_full_status(
        JP_PUSH, uplus_id=JP_2024
    )


@pytest.mark.parametrize("uplus_id", [None, CABINET, CLASSIC, "f" * 64])
def test_a_family_whose_map_does_not_say_so_gets_nothing(uplus_id) -> None:
    assert status_from_bigdata(ISSUE21_BIGDATA, uplus_id) is None


def test_only_a_big_data_report_is_read() -> None:
    assert status_from_bigdata(JP_PUSH, JP_2024) is None


def test_a_report_shorter_than_the_status_is_not_read() -> None:
    at = ISSUE21_BIGDATA.find(EPP_FRAME_HEAD)
    payload = _words(ISSUE21_BIGDATA)[:80]                 # one word short of the status
    body = bytes([len(payload) + 10]) + bytes(6) + b"\x06\x7d\x01" + payload
    short = ISSUE21_BIGDATA[:at] + EPP_FRAME_HEAD + body + bytes([sum(body) & 0xFF])
    assert status_from_bigdata(short, SEA_2024) is None


def test_a_truncated_report_is_not_read() -> None:
    assert status_from_bigdata(ISSUE21_BIGDATA[:-3], SEA_2024) is None


def test_the_telemetry_it_carries_still_decodes() -> None:
    telemetry = parse_extended_status(ISSUE21_BIGDATA, uplus_id=SEA_2024)
    assert telemetry["power_w"] == 155
    assert telemetry["compressor_frequency_hz"] == 0
    assert telemetry["coil_temperature"] == 28.0
    assert telemetry["expansion_valve_opening"] == 480


def test_a_current_pinned_at_its_ceiling_beside_real_power_is_not_published() -> None:
    """The frame reads 155 W (its input-power register agrees) and a current of `0x01FF`: the
    51.1 A Haier's own maps give as the field's maximum, in every one that carries it. Fifty amps
    at 155 W is not a reading -- 155 W is under one amp at any mains voltage. The current is
    dropped and the power, which the unit does measure, is kept."""
    telemetry = parse_extended_status(ISSUE21_BIGDATA, uplus_id=SEA_2024)
    assert "compressor_current_a" not in telemetry
    assert telemetry["power_w"] == 155
