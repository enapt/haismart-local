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
from homeassistant.components.climate import DOMAIN as CLIMATE_DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, SERVICE_TURN_OFF
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.haismart.const import (
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


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
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
