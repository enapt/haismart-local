"""Issue #21 — a wall unit whose sessions carry no status report, end to end.

An HS-18VRSA05W (Haier's SE-Asia 2024 family) opened every session with two copies of its big-data
report and nothing else, so no status decoded and setup failed on every retry. Its sibling with the
same product id worked. The family's byte map repeats the whole status report at the head of the
big-data one, so the status is read from there; and a session that carries no status at all, in
either form, is answered by asking the appliance (`getAllProperty`), which Haier's serial standard
requires every appliance to answer.
"""
from __future__ import annotations

import pytest
from ha_compat import MockConfigEntry
from haismart_hrdp import build_epp_frame, getallproperty_epp_frame
from homeassistant.components.climate import DOMAIN as CLIMATE_DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, ATTR_TEMPERATURE
from homeassistant.core import HomeAssistant

from custom_components.haismart.const import (
    CONF_DEVICE_ID,
    CONF_HOST,
    CONF_LOCAL_KEY,
    CONF_LOCALKEY_VERSION,
    CONF_PRODUCT_CODE,
    CONF_UPLUS_ID,
    DOMAIN,
)

CLIMATE = "climate.office"
SEA_2024 = "2008610800820324021200118018900000000000000000000000000000000040"
_GET_ALL = getallproperty_epp_frame()

#: The session's sequence base: the one payload every healthy session decrypts.
SEQUENCE = bytes.fromhex("8b913520")

#: Issue #21's big-data report as the unit sent it (the envelope's device id replaced with an
#: illustrative one): on, cooling to 29 C in a 29 C room, fan auto, outdoors 28 C, 155 W.
BIGDATA = bytes.fromhex(
    "00002715000000004e560100000302000005080000000000000000060a413142324333443445350000000000000000"
    "00000000000000000000000000000000000000000000000000000000000000006effff6a000000000000067d012064"
    "0000000000000000000000000000000000000000000000000000000000000000010000000d06250002031600000c3a"
    "005c8000000000000000000000000000000003dd160000000000000003dd16009b009b60610000000001ff022401e0"
    "27"
)
_AT = 80
_WORDS = BIGDATA[_AT + 12:-1]


def _status(frame_type: int, *, setpoint: int | None = None) -> bytes:
    """The family's 175-byte status report under ``frame_type``, built from the unit's own words.

    ``setpoint`` replaces word 20's setpoint byte (whole degrees above 16), to tell reports apart.
    """
    words = bytearray(_WORDS[:82])
    if setpoint is not None:
        words[38] = setpoint - 16
    return BIGDATA[:_AT] + build_epp_frame(frame_type, b"\x6d\x01", bytes(words))


def _reads(poll: list[bytes], answer: list[bytes] | None = None):
    """``poll`` for an ordinary cycle, ``answer`` for a session that asks ``4D01``."""
    asked: list[bytes | None] = []

    async def read(*args, extra_request=None, **kwargs):
        asked.append(extra_request)
        return list(answer or []) if extra_request == _GET_ALL else list(poll)

    return read, asked


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Office",
        unique_id="A1B2C3D4E5",
        data={
            CONF_HOST: "192.168.1.50",
            CONF_DEVICE_ID: "A1B2C3D4E5",
            CONF_LOCAL_KEY: "00112233445566778899aabbccddeeff",
            CONF_PRODUCT_CODE: "AAD378Z00",
            CONF_LOCALKEY_VERSION: 4,
            CONF_UPLUS_ID: SEA_2024,
        },
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def test_the_fixture_builds_the_familys_status_report() -> None:
    assert len(_status(0x06)) == 175


async def test_a_unit_that_sends_only_its_big_data_report_sets_up(
    hass: HomeAssistant, mock_uss
) -> None:
    """The reporter's sessions, exactly: the sequence base and two copies of the big-data report."""
    mock_uss.read.side_effect, asked = _reads([SEQUENCE, BIGDATA, BIGDATA])
    entry = await _setup(hass)

    assert entry.state is ConfigEntryState.LOADED
    state = hass.states.get(CLIMATE)
    assert state.state == "cool"
    assert state.attributes["temperature"] == 29.0
    assert state.attributes["current_temperature"] == 29.0
    assert state.attributes["fan_mode"] == "auto"
    # read from what the session carried: no extra session was needed
    assert _GET_ALL not in asked
    assert len(entry.runtime_data.last_raw_status) == 175
    assert float(hass.states.get("sensor.office_power").state) == 155


async def test_a_command_is_seeded_from_the_status_the_report_carries(
    hass: HomeAssistant, mock_uss
) -> None:
    """The group set starts from the unit's own words, so nothing but the setpoint changes."""
    mock_uss.read.side_effect, _ = _reads([SEQUENCE, BIGDATA, BIGDATA])
    mock_uss.send.baseline = None          # its command sessions carry no status push either
    await _setup(hass)
    await hass.services.async_call(
        CLIMATE_DOMAIN, "set_temperature",
        {ATTR_ENTITY_ID: CLIMATE, ATTR_TEMPERATURE: 27}, blocking=True,
    )
    frame = mock_uss.send.last_frame
    assert frame is not None
    at = frame.find(b"\xff\xff")
    assert frame[at + 10:at + 12] == b"\x60\x01"
    sent = frame[at + 12:-1]
    # report word 20 is group-set word 1: the setpoint byte moved, every other byte is the unit's
    assert sent[0] == 27 - 16
    assert sent[1:] == _WORDS[2 * 19 + 1:2 * 19 + len(sent)]


async def test_a_real_status_report_wins_over_the_copy_in_the_big_data_report(
    hass: HomeAssistant, mock_uss
) -> None:
    push = _status(0x06, setpoint=24)
    mock_uss.read.side_effect, _ = _reads([SEQUENCE, push, BIGDATA])
    entry = await _setup(hass)

    assert entry.runtime_data.last_raw_status == push


async def test_a_session_with_no_status_at_all_asks_the_appliance(
    hass: HomeAssistant, mock_uss
) -> None:
    """The session decrypted, so the key is good -- it simply carried no status. Ask for one, and
    take the appliance's own answer (frame type 02) over anything that session pushed."""
    answer = _status(0x02, setpoint=26)
    mock_uss.read.side_effect, asked = _reads(
        [SEQUENCE], [SEQUENCE, _status(0x06, setpoint=22), answer]
    )
    entry = await _setup(hass)

    assert entry.state is ConfigEntryState.LOADED
    assert _GET_ALL in asked
    assert entry.runtime_data.last_raw_status == answer
    assert hass.states.get(CLIMATE).attributes["temperature"] == 26.0
    assert "status-query" in entry.runtime_data.lan_frames["02/6d01"]["sessions"]


@pytest.mark.parametrize("answer", [None, [SEQUENCE]])
async def test_an_unanswered_question_still_fails_the_cycle(
    hass: HomeAssistant, mock_uss, answer
) -> None:
    mock_uss.read.side_effect, asked = _reads([SEQUENCE], answer)
    entry = await _setup(hass)

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert asked.count(_GET_ALL) == 1, "one question per cycle"


async def test_a_session_that_decrypted_nothing_is_not_asked_again(
    hass: HomeAssistant, mock_uss
) -> None:
    """Nothing decrypted means the key is wrong, and a second session with the same key would only
    fail the same way; the rotation check owns that case."""
    mock_uss.read.side_effect, asked = _reads([])
    entry = await _setup(hass)

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert _GET_ALL not in asked
