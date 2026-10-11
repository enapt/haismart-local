"""Issue #19 — a Japanese wall unit (`JAA-MX225AK`), end to end.

Its 111-byte report matched no hand-built family, so the classic fallback read it: the thermostat
showed a 58 C setpoint (133 F at the 20 C it was set to when added) on a unit it called off while it
ran, and every command was refused as an unrecognised layout. The family publishes its own frame,
and these tests drive the reporter's own report and the reporter's own digital model through the
integration to the frame each command puts on the wire.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from haismart_hrdp import getallproperty_epp_frame
from homeassistant.components.climate import DOMAIN as CLIMATE_DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, SERVICE_TURN_OFF
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.haismart.const import (
    CONF_ABSENT_READINGS,
    CONF_DEVICE_ID,
    CONF_DIGITAL_MODEL,
    CONF_HOST,
    CONF_LOCAL_KEY,
    CONF_LOCALKEY_VERSION,
    CONF_PRODUCT_CODE,
    CONF_UPLUS_ID,
    DOMAIN,
    ISSUE_UNKNOWN_LAYOUT,
)

CLIMATE = "climate.wall_mounted"
JP_2024 = "2008610800820324021200118018500000000000000000000000000000000040"

#: The reporter's status report: cool, 21 C, fan auto, on; room 20 C, 60 %, outdoors 14 C.
REPORT = bytes.fromhex(
    "00002715000000004e5601000003020000040100000000000000000000000000000000000000000000000000000000"
    "00000000000000000000000000000000000000000000000000000000000000001fffff1c000000000000066d012a08"
    "210400000200000000000000283c4e009b"
)
#: The reporter's own digital model, exactly as the entry stores it.
MODEL = json.loads(
    (Path(__file__).parent / "fixtures" / "issue19_japan_wall_model.json").read_text("utf-8")
)

#: `FF FF len 00*6 01 60 01` -- the head of every group set this family is sent.
_HEAD = bytes.fromhex("ffff12000000000000016001")


@pytest.fixture
def japan_wall(mock_uss):
    mock_uss.read.return_value = [REPORT]
    mock_uss.send.baseline = REPORT
    return mock_uss


async def _setup(hass: HomeAssistant, **extra) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Wall Mounted",
        unique_id="A1B2C3D4E5F6",
        data={
            CONF_HOST: "192.168.1.50",
            CONF_DEVICE_ID: "A1B2C3D4E5F6",
            CONF_LOCAL_KEY: "00112233445566778899aabbccddeeff",
            CONF_PRODUCT_CODE: "AACWS2E00",
            CONF_LOCALKEY_VERSION: 4,
            CONF_UPLUS_ID: JP_2024,
            CONF_DIGITAL_MODEL: json.dumps(MODEL),
            **extra,
        },
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


def _words(frame: bytes) -> bytes:
    """The four group-set words of a sent frame, after checking it is this family's group set."""
    assert frame[: len(_HEAD)] == _HEAD, frame.hex()
    words = frame[len(_HEAD):-1]
    assert len(words) == 8, frame.hex()
    assert (sum(frame[2:-1]) & 0xFF) == frame[-1], "checksum"
    return words


async def test_the_thermostat_shows_what_the_unit_is_doing(hass: HomeAssistant, japan_wall) -> None:
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    assert coordinator.unknown_layout is None
    assert coordinator.read_only_layout is None
    raised = {i.translation_key for i in ir.async_get(hass).issues.values()}
    assert ISSUE_UNKNOWN_LAYOUT not in raised, "no unknown-layout repair for a family we decode"

    state = hass.states.get(CLIMATE)
    assert state is not None
    assert state.state == "cool"
    assert state.attributes["temperature"] == 21.0
    assert state.attributes["current_temperature"] == 20.0
    assert state.attributes["fan_mode"] == "auto"
    assert state.attributes["swing_mode"] == "off"
    assert state.attributes["swing_horizontal_mode"] == "off"


async def test_turning_it_off_clears_exactly_the_power_bit(hass: HomeAssistant, japan_wall) -> None:
    await _setup(hass)
    await hass.services.async_call(
        CLIMATE_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: CLIMATE}, blocking=True
    )
    # `2104` -> `0104`: word 2 bit 13 is power. The other three words are the unit's own, echoed.
    assert _words(japan_wall.send.last_frame) == bytes.fromhex("2a08010400000200")


async def test_a_setpoint_goes_out_in_half_degrees(hass: HomeAssistant, japan_wall) -> None:
    await _setup(hass)
    await hass.services.async_call(
        CLIMATE_DOMAIN, "set_temperature",
        {ATTR_ENTITY_ID: CLIMATE, "temperature": 24}, blocking=True,
    )
    assert _words(japan_wall.send.last_frame) == bytes.fromhex("3008210400000200")


async def test_a_fan_speed_goes_out_in_this_familys_own_codes(
    hass: HomeAssistant, japan_wall
) -> None:
    """High is wire 2 here, not the 1 every shared-frame family uses."""
    await _setup(hass)
    await hass.services.async_call(
        CLIMATE_DOMAIN, "set_fan_mode",
        {ATTR_ENTITY_ID: CLIMATE, "fan_mode": "high"}, blocking=True,
    )
    assert _words(japan_wall.send.last_frame) == bytes.fromhex("2a08210400002200")


async def test_left_right_swing_writes_the_auto_end(hass: HomeAssistant, japan_wall) -> None:
    await _setup(hass)
    await hass.services.async_call(
        CLIMATE_DOMAIN, "set_swing_horizontal_mode",
        {ATTR_ENTITY_ID: CLIMATE, "swing_horizontal_mode": "on"}, blocking=True,
    )
    # Word 1 bits 5-7 = 7: `2a08` -> `2ae8`.
    assert _words(japan_wall.send.last_frame) == bytes.fromhex("2ae8210400000200")


async def test_the_entities_follow_what_this_family_can_place(
    hass: HomeAssistant, japan_wall
) -> None:
    """Offered: the up-down stops (the same wire codes as the shared table) and the humidity probe.
    Not offered: a left-right stop select -- its codes are not the shared identity, so a stop chosen
    through the shared rule would land on a different one."""
    entry = await _setup(hass)
    registry = er.async_get(hass)
    suffixes = {
        e.unique_id.removeprefix("A1B2C3D4E5F6_")
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    assert "vane_vertical" in suffixes
    assert "vane_horizontal" not in suffixes

    humidity = [
        e for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.unique_id.endswith("_humidity")
    ]
    assert len(humidity) == 1
    assert hass.states.get(humidity[0].entity_id).state == "60"


def _suffixes(hass: HomeAssistant, entry) -> set[str]:
    registry = er.async_get(hass)
    return {
        e.unique_id.removeprefix("A1B2C3D4E5F6_")
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    }


def _state(hass: HomeAssistant, entry, suffix: str) -> str:
    registry = er.async_get(hass)
    (entity,) = [
        e for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.unique_id == f"A1B2C3D4E5F6_{suffix}"
    ]
    return hass.states.get(entity.entity_id).state


async def test_who_made_the_last_change_is_not_offered(hass: HomeAssistant, japan_wall) -> None:
    """The product's own model does not declare `opSrc`, so the sensor would read "Other" after a
    change Home Assistant made. Not created -- and one left by an earlier build is removed."""
    names = {a.get("name") for a in MODEL["attributes"]}
    assert "opSrc" not in names, "the reason for withholding it: the product does not declare it"
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "sensor", DOMAIN, "A1B2C3D4E5F6_last_changed_by", suggested_object_id="old_last_changed_by"
    )
    entry = await _setup(hass)
    assert "last_changed_by" not in _suffixes(hass, entry)
    assert registry.async_get_entity_id("sensor", DOMAIN, "A1B2C3D4E5F6_last_changed_by") is None


#: A second unit's telemetry report (issue #19), unit off: 18 words, read from the family's own map.
TELEMETRY = bytes.fromhex(
    "00002715000000004e5601007a0302007a040100000000000000000000000000000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000000000000100000031ffff2e000000000000067d013604"
    "00040000020000000000000046306700007066630063000000000001e03600001acb67"
)


async def test_the_telemetry_report_fills_the_running_sensors(
    hass: HomeAssistant, japan_wall
) -> None:
    japan_wall.read.return_value = [REPORT, TELEMETRY]
    entry = await _setup(hass)
    assert _state(hass, entry, "compressor_frequency_hz") == "0"
    assert float(_state(hass, entry, "coil_temperature")) == 36.0


async def test_sensors_written_off_before_the_map_existed_come_back(
    hass: HomeAssistant, japan_wall
) -> None:
    """The reporter's entry had already retired these, because the frame could not be read. The
    first poll that decodes it restores them -- no reinstall."""
    japan_wall.read.return_value = [REPORT, TELEMETRY]
    entry = await _setup(
        hass, **{CONF_ABSENT_READINGS: ["coil_temperature", "compressor_frequency_hz", "power_w"]}
    )
    await hass.async_block_till_done()
    assert not set(entry.data.get(CONF_ABSENT_READINGS) or ()) & {
        "coil_temperature", "compressor_frequency_hz", "power_w"
    }
    assert {"coil_temperature", "compressor_frequency_hz", "power_w"} <= _suffixes(hass, entry)


# --- issue #19's first unit, after its owner's commands: a poll whose two reports disagreed -----
# Real frames from the owner's diagnostics download. The status push and the extended report came
# from the SAME poll, and disagree on power, setpoint and up-down vane. Haier's cloud, fetched as
# the file was written, agreed with the extended report on 34 of 35 attributes, as did the owner.

#: The poll's status push: on, cool, 19 C, vane wire 2, room 22 C.
PUSH_ON = bytes.fromhex(
    "00002715000000004e5601000003020000040100000000000000000000000000000000000000000000000000000000"
    "00000000000000000000000000000000000000000000000000000000000000001fffff1c000000000000066d012602"
    "2104000002000000000000002c395c00a0"
)
#: The same poll's alarm push (no fault).
ALARM = bytes.fromhex(
    "00002715000000004e5601000003020000040100000000000000000000000000000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000000000000000000015ffff12000000000000040f5a0000"
    "0000000000007f"
)
#: The same poll's extended report: off, cool, 20 C, vane wire 8 (published 6), room 21 C.
EXTENDED_OFF = bytes.fromhex(
    "00002715000000004e5601007a03020079040100000000000000000000000000000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000000000000100000031ffff2e000000000000067d012808"
    "0104000002000000000000002a395c00004c7c530053000000000001e028000039cb23"
)
#: The unit's accepted reply (frame type 02) to the owner's turn-on: on, cool, 19 C, vane wire 2.
ECHO_ON = bytes.fromhex(
    "00002715000000004e5601006e0302006d040100000000000000000000000000000000000000000000000000000000"
    "00000000000000000000000000000000000000000000000000000000010000001fffff1c000000000000026d012602"
    "21040000020000000000000027395b0096"
)
#: Rad1ally's unit (same Model ID): a poll whose push and extended report agree -- off, auto, 27 C.
AGREEING_PUSH = bytes.fromhex(
    "00002715000000004e5601000003020000040100000000000000000000000000000000000000000000000000000000"
    "00000000000000000000000000000000000000000000000000000000000000001fffff1c000000000000066d013604"
    "00040000020000000000000046306700ad"
)

_GET_ALL = getallproperty_epp_frame()


def _with_words_of(frame: bytes, source: bytes, words: int = 9) -> bytes:
    """``frame`` carrying ``source``'s first ``words`` report words, checksum recomputed.

    The unit's own answer to ``4D01`` is not in the owner's file, so the tests build it from the
    unit's own bytes: its real accepted reply, carrying the settings its own extended report gave in
    that poll -- the same nine words in the same layout (the family's byte map places them alike).
    """
    at, src = frame.find(b"\xff\xff"), source.find(b"\xff\xff")
    body = bytearray(frame[:-1])
    body[at + 12:at + 12 + 2 * words] = source[src + 12:src + 12 + 2 * words]
    return bytes(body) + bytes([sum(body[at + 2:]) & 0xFF])


def test_the_built_answer_keeps_the_frames_own_checksum_rule() -> None:
    assert _with_words_of(ECHO_ON, ECHO_ON) == ECHO_ON


def _reads(answer: list[bytes] | None, poll: list[bytes]):
    """A read mock: ``poll`` for an ordinary cycle, ``answer`` for a session that asks ``4D01``."""
    asked: list[bytes | None] = []

    async def read(*args, extra_request=None, **kwargs):
        asked.append(extra_request)
        return list(answer or []) if extra_request == _GET_ALL else list(poll)

    return read, asked


async def test_when_a_polls_two_reports_disagree_the_unit_is_asked(
    hass: HomeAssistant, japan_wall
) -> None:
    """Home Assistant showed this unit on at 19 C while it was off at 20 C. The appliance's own
    answer to `getAllProperty` decides, and is what the thermostat shows."""
    answer = _with_words_of(ECHO_ON, EXTENDED_OFF)
    japan_wall.read.side_effect, asked = _reads(
        [PUSH_ON, ALARM, answer], [PUSH_ON, ALARM, EXTENDED_OFF]
    )
    entry = await _setup(hass)

    assert _GET_ALL in asked
    state = hass.states.get(CLIMATE)
    assert state.state == "off"
    assert state.attributes["temperature"] == 20.0
    checks = entry.runtime_data.status_checks
    assert checks["count"] >= 1
    assert checks["last"]["pushed"] == {
        "onOffStatus": True, "targetTemperature": 19.0, "windDirectionVertical": 2,
    }
    assert checks["last"]["extended"] == {
        "onOffStatus": False, "targetTemperature": 20.0, "windDirectionVertical": 6,
    }
    assert checks["last"]["answer"] == checks["last"]["extended"]
    assert entry.runtime_data.last_raw_status == answer


async def test_a_poll_whose_reports_agree_asks_nothing_more(
    hass: HomeAssistant, japan_wall
) -> None:
    japan_wall.read.side_effect, asked = _reads(None, [AGREEING_PUSH, ALARM, TELEMETRY])
    entry = await _setup(hass)
    await entry.runtime_data.async_refresh()

    assert _GET_ALL not in asked
    assert entry.runtime_data.status_checks["count"] == 0
    assert hass.states.get(CLIMATE).attributes["temperature"] == 27.0


async def test_a_difference_the_unit_confirms_is_not_checked_again(
    hass: HomeAssistant, japan_wall
) -> None:
    """When the appliance's answer sides with the push, its extended report differs there by
    design: believe the answer, and do not pay an extra session for it on every poll."""
    japan_wall.read.side_effect, asked = _reads(
        [PUSH_ON, ALARM, ECHO_ON], [PUSH_ON, ALARM, EXTENDED_OFF]
    )
    entry = await _setup(hass)
    assert hass.states.get(CLIMATE).attributes["temperature"] == 19.0
    asked_before = asked.count(_GET_ALL)
    assert asked_before == 1

    await entry.runtime_data.async_refresh()
    assert asked.count(_GET_ALL) == asked_before


async def test_a_unit_that_does_not_answer_the_question_stops_being_asked(
    hass: HomeAssistant, japan_wall
) -> None:
    japan_wall.read.side_effect, asked = _reads(
        [PUSH_ON, ALARM], [PUSH_ON, ALARM, EXTENDED_OFF]
    )
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    for _ in range(4):
        await coordinator.async_refresh()

    assert asked.count(_GET_ALL) == 3
    assert coordinator.status_checks["off"]
    # Nothing to go on but the push, so the push stands, as it did before the check existed.
    assert hass.states.get(CLIMATE).attributes["temperature"] == 19.0


async def test_the_byte_map_state_after_a_command_is_the_replys(
    hass: HomeAssistant, japan_wall
) -> None:
    """A command's reply carries a status report and no extended one, so the extended report on
    hand is the one from before the command. Laid over the reply, it put the old values back --
    issue #19's diagnostics read off at 20 C there, beside a decode reading on at 19 C."""
    answer = _with_words_of(ECHO_ON, EXTENDED_OFF)
    japan_wall.read.side_effect, _ = _reads(
        [PUSH_ON, ALARM, answer], [PUSH_ON, ALARM, EXTENDED_OFF]
    )
    japan_wall.send.baseline = answer
    japan_wall.send.return_value = [ALARM, ECHO_ON]
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    assert coordinator.last_raw_extended == EXTENDED_OFF

    await hass.services.async_call(
        CLIMATE_DOMAIN, "set_hvac_mode", {ATTR_ENTITY_ID: CLIMATE, "hvac_mode": "cool"},
        blocking=True,
    )
    model_state = coordinator.data["model_state"]
    assert model_state["onOffStatus"] is True
    assert model_state["targetTemperature"] == 19.0
    assert model_state["windDirectionVertical"] == 2
    assert hass.states.get(CLIMATE).state == "cool"


async def test_a_command_after_a_stale_push_is_built_from_the_units_answer(
    hass: HomeAssistant, japan_wall
) -> None:
    """A group set is seeded from the status its own session opens with -- the same push the last
    poll caught contradicting the appliance. Seeded from it, a setpoint change would have sent
    "on, vane 2" back and switched on a unit its owner had just switched off."""
    answer = _with_words_of(ECHO_ON, EXTENDED_OFF)
    japan_wall.read.side_effect, _ = _reads(
        [PUSH_ON, ALARM, answer], [PUSH_ON, ALARM, EXTENDED_OFF]
    )
    japan_wall.send.baseline = PUSH_ON
    await _setup(hass)

    await hass.services.async_call(
        CLIMATE_DOMAIN, "set_temperature", {ATTR_ENTITY_ID: CLIMATE, "temperature": 21},
        blocking=True,
    )
    # 21 C with the answer's vane (wire 8); power stays off (`0104`), not the push's `2104`.
    assert _words(japan_wall.send.last_frame) == bytes.fromhex("2a08010400000200")
