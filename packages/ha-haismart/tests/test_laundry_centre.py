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
