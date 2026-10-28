"""A twin washer + dryer (class 0504), and the air conditioner it must NOT be given.

The reports are a real unit's -- an HWD140-BD14LCGNU1 laundry centre, captured by this integration's
own diagnostics while its dryer ran and its washer sat idle after a finished cycle -- together with
Haier's cloud shadow read at the same moment (`fixtures/laundry_0504.json`). Nothing is synthesised.

Two things went wrong on the unit before this, and each is pinned below:

* its dryer report is 165 bytes, the length of the extended-36 air-conditioner family, so it was
  read as an AC: a thermostat, Quiet/Sleep/Strong/Health switches and a 50.5 °C "room";
* its washer reports separately, in a second status frame (``6D02``), which nothing read at all.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.haismart.const import (
    CONF_APP_TYPE,
    CONF_DEVICE_ID,
    CONF_DIGITAL_MODEL,
    CONF_HOST,
    CONF_LOCAL_KEY,
    CONF_LOCALKEY_VERSION,
    CONF_PRODUCT_CODE,
    CONF_UPLUS_ID,
    DOMAIN,
)

CAPTURE = json.loads((Path(__file__).parent / "fixtures" / "laundry_0504.json").read_text("utf-8"))
DRYER_RUNNING = bytes.fromhex(CAPTURE["frames"]["6d01_dryer_running"])
WASHER_IDLE = bytes.fromhex(CAPTURE["frames"]["6d02_washer_idle"])
CLOUD = CAPTURE["reported_values_now"]


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Laundry",
        unique_id="A1B2C3D4E5F6",
        data={
            CONF_HOST: "192.168.1.50",
            CONF_DEVICE_ID: "A1B2C3D4E5F6",
            CONF_LOCAL_KEY: "00112233445566778899aabbccddeeff",
            # The code the unit was really stored under -- an AC's, which is part of the trap.
            CONF_PRODUCT_CODE: "CEACSAE00",
            CONF_LOCALKEY_VERSION: 4,
            CONF_UPLUS_ID: CAPTURE["typeid"],
            CONF_APP_TYPE: CAPTURE["app_type"],
            CONF_DIGITAL_MODEL: json.dumps(CAPTURE["digital_model"]),
        },
    )


@pytest.fixture
def laundry(mock_uss):
    """The unit as it really answers: the dryer's report first, then the washer's, every session."""
    mock_uss.read.return_value = [DRYER_RUNNING, WASHER_IDLE]
    mock_uss.send.baseline = DRYER_RUNNING
    return mock_uss


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = _entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _entities(hass: HomeAssistant, entry: MockConfigEntry) -> dict[str, er.RegistryEntry]:
    """The entry's entities, keyed on the ATTRIBUTE they read (the unique id's suffix)."""
    registry = er.async_get(hass)
    return {
        e.unique_id.rsplit("_", 1)[-1]: e
        for e in registry.entities.values()
        if e.config_entry_id == entry.entry_id
    }


def _state(hass: HomeAssistant, entry: MockConfigEntry, attribute: str) -> str:
    entity = _entities(hass, entry)[attribute]
    state = hass.states.get(entity.entity_id)
    assert state is not None, attribute
    return state.state


async def test_a_laundry_centre_is_not_given_an_air_conditioner(
    hass: HomeAssistant, laundry
) -> None:
    """No thermostat and no AC switch -- and nothing that writes at all: it is read-only."""
    entry = await _setup(hass)
    assert entry.state is ConfigEntryState.LOADED
    domains = {e.domain for e in _entities(hass, entry).values()}
    assert domains <= {"sensor", "binary_sensor"}, domains


async def test_it_reads_the_dryer_from_6d01(hass: HomeAssistant, laundry) -> None:
    """The dryer was running Ai Dry, still sensing its load -- the app showed the same."""
    entry = await _setup(hass)
    assert CLOUD["dryerRunningMode"] == "1" and CLOUD["dryerCyclePhase"] == "8"
    assert _state(hass, entry, "dryerRunningMode") == "Running"
    assert _state(hass, entry, "dryerCyclePhase") == "Sensing load"
    assert _state(hass, entry, "dryerRemainingDryTime") == CLOUD["dryerRemainingDryTime"] == "470"
    assert _state(hass, entry, "dryerDoorLockStatus") == "on"


async def test_it_reads_the_washer_from_6d02(hass: HomeAssistant, laundry) -> None:
    """The second status frame, which nothing read before -- every value as the cloud had it."""
    entry = await _setup(hass)
    assert _state(hass, entry, "laundryCyclePhase") == "Standby"
    assert _state(hass, entry, "laundryCycleStatus") == "off"
    assert _state(hass, entry, "remainingTimeHH") == CLOUD["remainingTimeHH"] == "1"
    assert _state(hass, entry, "remainingTimeMM") == CLOUD["remainingTimeMM"] == "8"
    assert _state(hass, entry, "washerDoorLockStatus") == "off"
    assert _state(hass, entry, "washerMessage") == "Softener empty"
    assert float(_state(hass, entry, "totalWaterUsed")) == float(CLOUD["totalWaterUsed"])


async def test_a_session_with_only_the_washer_frame_reads_it_as_the_washer(
    hass: HomeAssistant, mock_uss
) -> None:
    """⛔ Read with the dryer's positions, a lone 6D02 put dryer values on the washer's words."""
    mock_uss.read.return_value = [WASHER_IDLE]
    mock_uss.send.baseline = WASHER_IDLE
    entry = await _setup(hass)
    assert _state(hass, entry, "laundryCyclePhase") == "Standby"
    assert _state(hass, entry, "remainingTimeMM") == "8"


# --- controls: off by default, gated on the machine's own remote flag ---------------------------

from homeassistant.exceptions import HomeAssistantError  # noqa: E402

from custom_components.haismart.const import CONF_LAUNDRY_CONTROLS  # noqa: E402

BASE = 92   # where the word array starts in a LAN status message


def _with_bit(blob: bytes, word: int, bit: int, on: bool) -> bytes:
    """``blob`` with one report bit set or cleared (word 1-based, bit within the 16-bit word)."""
    at = BASE + 2 * (word - 1)
    value = int.from_bytes(blob[at:at + 2], "big")
    value = value | (1 << bit) if on else value & ~(1 << bit)
    return blob[:at] + value.to_bytes(2, "big") + blob[at + 2:]


# Positions from the class's configFile: 6D02 word 3 bit 1 / 6D01 word 1 bit 3 (remote valid),
# 6D02 word 3 bit 7 (washer running).
def _washer(remote: bool, running: bool = False) -> bytes:
    return _with_bit(_with_bit(WASHER_IDLE, 3, 1, remote), 3, 7, running)


def _dryer(remote: bool) -> bytes:
    return _with_bit(DRYER_RUNNING, 1, 3, remote)


async def _setup_controls(hass: HomeAssistant, mock_uss, *, remote: bool, running=False):
    mock_uss.read.return_value = [_dryer(remote), _washer(remote, running)]
    mock_uss.send.baseline = _dryer(remote)
    entry = _entry()
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={CONF_LAUNDRY_CONTROLS: True})
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _entity(hass: HomeAssistant, entry, unique_suffix: str) -> str:
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        unique_suffix.split(":")[0], "haismart", f"A1B2C3D4E5F6_{unique_suffix.split(':')[1]}"
    )
    assert entity_id, unique_suffix
    return entity_id


async def test_controls_appear_only_when_turned_on(hass: HomeAssistant, mock_uss) -> None:
    entry = await _setup_controls(hass, mock_uss, remote=False)
    domains = {e.domain for e in _entities(hass, entry).values()}
    assert {"button", "switch", "select", "number"} <= domains
    assert "climate" not in domains
    for drum in ("washer", "dryer"):
        for action in ("start", "pause", "cancel"):
            _entity(hass, entry, f"button:{drum}_{action}")
    # Start/pause are buttons, never a "running mode" dropdown that starts a cycle when changed.
    assert "washerRunningMode" not in {
        k for k, e in _entities(hass, entry).items() if e.domain == "select"
    }


async def test_nothing_is_sent_while_the_panel_has_remote_control_off(
    hass: HomeAssistant, mock_uss
) -> None:
    entry = await _setup_controls(hass, mock_uss, remote=False)
    mock_uss.send.reset_mock()
    with pytest.raises(HomeAssistantError, match="remote control is not enabled for the washer"):
        await hass.services.async_call(
            "button", "press", {"entity_id": _entity(hass, entry, "button:washer_start")},
            blocking=True,
        )
    mock_uss.send.assert_not_called()


@pytest.mark.parametrize(
    ("button", "frame_cmd", "payload"),
    [
        ("washer_start", "5da1", "0001"),
        ("washer_pause", "5da1", "0000"),
        ("washer_cancel", "5da4", "0001"),
        ("dryer_start", "5d21", "0001"),
        ("dryer_pause", "5d21", "0000"),
        ("dryer_cancel", "5d23", "0001"),
    ],
)
async def test_each_drum_button_sends_its_own_single_command(
    hass: HomeAssistant, mock_uss, button: str, frame_cmd: str, payload: str
) -> None:
    """The ids are the class's own: the washer's carry the 0x80 drum bit, the dryer's do not."""
    entry = await _setup_controls(hass, mock_uss, remote=True)
    await hass.services.async_call(
        "button", "press", {"entity_id": _entity(hass, entry, f"button:{button}")}, blocking=True
    )
    frame = mock_uss.send.last_frame
    assert frame is not None and frame[:2] == b"\xff\xff"
    assert frame[9] == 0x01, "a single-parameter write, never a group set"
    assert frame[10:12].hex() == frame_cmd and frame[12:14].hex() == payload


async def test_a_programme_is_not_changed_under_a_running_drum(
    hass: HomeAssistant, mock_uss
) -> None:
    entry = await _setup_controls(hass, mock_uss, remote=True, running=True)
    coordinator = entry.runtime_data
    mock_uss.send.reset_mock()
    with pytest.raises(HomeAssistantError, match="the washer is running"):
        await coordinator.async_send_control({"washerUnifiedProgramSettings": 3})
    mock_uss.send.assert_not_called()


async def test_a_laundry_write_never_reaches_the_air_conditioner_paths(
    hass: HomeAssistant, mock_uss
) -> None:
    entry = await _setup_controls(hass, mock_uss, remote=True)
    mock_uss.send.reset_mock()
    with pytest.raises(HomeAssistantError, match="not a laundry control"):
        await entry.runtime_data.async_send_control({"targetTemperature": 24})
    mock_uss.send.assert_not_called()


async def test_turning_controls_off_again_removes_them(hass: HomeAssistant, mock_uss) -> None:
    entry = await _setup_controls(hass, mock_uss, remote=True)
    hass.config_entries.async_update_entry(entry, options={CONF_LAUNDRY_CONTROLS: False})
    await hass.async_block_till_done()
    assert {e.domain for e in _entities(hass, entry).values()} <= {"sensor", "binary_sensor"}


async def test_a_big_data_report_never_overrides_the_status_reports(
    hass: HomeAssistant, mock_uss
) -> None:
    """7D02 repeats 81 of 6D02's names; the status report is the fresher and must win."""
    from haismart_hrdp.device_model import model_for

    model = model_for(CAPTURE["typeid"])
    big = bytearray(WASHER_IDLE)
    at = big.find(bytes.fromhex("6d02"))
    big[at:at + 2] = bytes.fromhex("7d02")
    # Make the big-data report DISAGREE: the remaining minutes it carries differ from 6D02's.
    minutes = next(f for f in model.fields_for("7D02") if f.name == "remainingTimeMM")
    big = bytearray(_with_bit(bytes(big), minutes.word, minutes.bit + 5, True))
    assert model.decode(bytes(big), status_cmd="7D02")["remainingTimeMM"] != int(
        CLOUD["remainingTimeMM"]
    )
    mock_uss.read.return_value = [DRYER_RUNNING, WASHER_IDLE, bytes(big)]
    entry = _entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    state = entry.runtime_data.data["model_state"]
    assert state["remainingTimeMM"] == int(CLOUD["remainingTimeMM"])
    washer = model.decode(WASHER_IDLE, status_cmd="6D02")
    shared = {f.name for f in model.fields_for("7D02")} & set(washer)
    assert shared
    assert all(state[name] == washer[name] for name in shared if name in state)


# --- the gate reads only each drum's own fresh status report (review findings) ------------------


def _as(blob: bytes, command: str, frm: str) -> bytes:
    """``blob`` re-filed under another command (the bytes after it are left as they are)."""
    out = bytearray(blob)
    at = out.find(bytes.fromhex(frm))
    out[at:at + 2] = bytes.fromhex(command)
    return bytes(out)


async def _controls(hass: HomeAssistant, mock_uss, frames: list[bytes]):
    mock_uss.read.return_value = frames
    mock_uss.send.baseline = frames[0]
    entry = _entry()
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={CONF_LAUNDRY_CONTROLS: True})
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    mock_uss.send.reset_mock()
    mock_uss.send.last_frame = None
    return entry


async def test_a_big_data_report_cannot_open_the_gate(hass: HomeAssistant, mock_uss) -> None:
    """7D01 carries the dryer's remote flag at the same place; only 6D01 may answer for it."""
    dryer_off = _dryer(False)
    big_on = _with_bit(_as(DRYER_RUNNING, "7d01", "6d01"), 1, 3, True)
    entry = await _controls(hass, mock_uss, [dryer_off, _washer(True), big_on])
    with pytest.raises(HomeAssistantError, match="remote control is not enabled for the dryer"):
        await entry.runtime_data.async_send_control({"dryerRunningMode": 1})
    mock_uss.send.assert_not_called()


async def test_without_the_drum_s_own_report_nothing_is_sent(hass: HomeAssistant, mock_uss) -> None:
    big_on = _with_bit(_as(DRYER_RUNNING, "7d01", "6d01"), 1, 3, True)
    entry = await _controls(hass, mock_uss, [_washer(True), big_on])
    with pytest.raises(HomeAssistantError, match="no fresh report from the dryer"):
        await entry.runtime_data.async_send_control({"dryerRunningMode": 1})
    mock_uss.send.assert_not_called()


async def test_a_change_report_is_not_read_as_the_dryer(hass: HomeAssistant, mock_uss) -> None:
    """A 6C01 delta read at 6D01's positions would overwrite the dryer's state and the gate's."""
    change_on = _with_bit(_as(DRYER_RUNNING, "6c01", "6d01"), 1, 3, True)
    entry = await _controls(hass, mock_uss, [change_on, _dryer(False), _washer(True)])
    assert entry.runtime_data.data["model_state"]["dryerRemoteCtrValid"] is False
    with pytest.raises(HomeAssistantError, match="remote control is not enabled for the dryer"):
        await entry.runtime_data.async_send_control({"dryerRunningMode": 1})


async def test_machine_wide_settings_need_both_drums(hass: HomeAssistant, mock_uss) -> None:
    entry = await _controls(hass, mock_uss, [_dryer(True), _washer(False)])
    with pytest.raises(HomeAssistantError, match="not enabled for the washer"):
        await entry.runtime_data.async_send_control({"childLockStatus": False})
    mock_uss.send.assert_not_called()


async def test_power_off_fails_closed_when_a_drum_is_unknown(hass: HomeAssistant, mock_uss) -> None:
    entry = await _controls(hass, mock_uss, [_dryer(True)])
    with pytest.raises(HomeAssistantError):
        await entry.runtime_data.async_send_control({"onOffStatus": False})
    mock_uss.send.assert_not_called()


async def test_the_command_s_own_session_is_checked_again(hass: HomeAssistant, mock_uss) -> None:
    """The poll said yes; the push in the command's own session says remote is now off."""
    entry = await _controls(hass, mock_uss, [_dryer(True), _washer(True)])
    mock_uss.send.baseline = _dryer(False)
    with pytest.raises(HomeAssistantError, match="switched off for the dryer; nothing was sent"):
        await entry.runtime_data.async_send_control({"dryerRunningMode": 1})
    assert mock_uss.send.last_frame is None


async def test_every_command_is_kept_with_its_frame_for_diagnostics(
    hass: HomeAssistant, mock_uss
) -> None:
    entry = await _controls(hass, mock_uss, [_dryer(True), _washer(True)])
    coordinator = entry.runtime_data
    await coordinator.async_send_control({"dryerRunningMode": 2})
    await coordinator.async_send_control({"washerRunningMode": 1})
    log = list(coordinator.control_log)
    assert [c["frame"][20:28] for c in log] == ["5d210000", "5da10001"]
