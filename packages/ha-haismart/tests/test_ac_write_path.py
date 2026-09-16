"""Issue #15 — an air conditioner must keep its own write path when a byte map is also loaded.

v0.70.0 gave every appliance a decoder built from Haier's published byte map. Air conditioners
already had a hand-built one, and `entity_specs` / `uses_curated_ac_entities` keep them on it for
READS. The WRITE gate (`model_write_fields`) was keyed on `model_decoded` alone, so an air
conditioner whose byte map also decodes had single-field changes diverted to the byte-map path --
which speaks a different representation (published values, not raw EPP) and builds a different
frame (a `5Dxx` single-parameter write, not the group set).

The visible half is the reporter's 500: `onOffStatus='0' not in allowed ['false', 'true']`. The
silent half is worse and is asserted here too -- with no digital model to validate against, the
same change would have gone out as the wrong frame.

⚠️ Every test here sets `CONF_UPLUS_ID`. That is the whole reason the suite stayed green: no other
air-conditioner test carries one, so `model_for(None)` returned None, `model_decoded` stayed False
and this gate was never reached.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import heat_capable_digital_model, make_status_frame
from homeassistant.components.climate import DOMAIN as CLIMATE_DOMAIN
from homeassistant.components.climate import HVACMode
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, SERVICE_TURN_OFF, SERVICE_TURN_ON
from homeassistant.core import HomeAssistant
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
)

CLIMATE = "climate.downstairs_ac"

# The owner's own two units. Class 0212 is an air conditioner, and this typeid's byte map marks
# exactly one attribute writable -- `onOffStatus` -- which is why turning the unit OFF is the one
# thing that broke on the hardware this project develops against.
OWNER_UPLUS_ID = "2008610800820324021200118012560000000000000000000000000000000040"


def _ac_model() -> dict:
    """The AC fixture model plus the one key that makes it a REAL one.

    `declared_attribute_names` returns nothing unless the model carries `invisible_attributes`,
    because a model without it does not tell us which attributes this unit really has. Every
    digital model the cloud actually serves has the key; the shared test fixture does not, which
    is the second reason this regression was invisible to the suite -- even an air-conditioner test
    that DID set a uplus_id would have decoded nothing.
    """
    return {**heat_capable_digital_model(), "invisible_attributes": []}


def _entry(**overrides) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Downstairs AC",
        unique_id="A1B2C3D4E5F6",
        data={
            CONF_HOST: "192.168.1.50",
            CONF_DEVICE_ID: "A1B2C3D4E5F6",
            CONF_LOCAL_KEY: "00112233445566778899aabbccddeeff",
            CONF_PRODUCT_CODE: "AAC1UKZ01",
            CONF_LOCALKEY_VERSION: 4,
            CONF_UPLUS_ID: OWNER_UPLUS_ID,
            CONF_DIGITAL_MODEL: json.dumps(_ac_model()),
            **overrides,
        },
    )


async def _setup(hass: HomeAssistant, **overrides) -> MockConfigEntry:
    entry = _entry(**overrides)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


async def test_the_byte_map_does_decode_this_air_conditioner(
    hass: HomeAssistant, mock_uss
) -> None:
    """The precondition, asserted rather than assumed: this is not a vacuous regression test.

    If the byte map ever stopped decoding the owner's units, every other test in this file would
    pass for the wrong reason.
    """
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    assert coordinator.model_decoded is True
    assert coordinator.uses_curated_ac_entities is True


async def test_turning_an_air_conditioner_off_is_not_gated_by_the_byte_map(
    hass: HomeAssistant, mock_uss
) -> None:
    """The reported failure: `onOffStatus='0' not in allowed ['false', 'true']`, HTTP 500.

    `climate.turn_off` sends the raw EPP `0`; the byte-map validator wants the model's published
    `"false"`. The fix is not to translate between them -- it is that an air conditioner must not
    reach that validator at all.
    """
    await _setup(hass)
    await hass.services.async_call(
        CLIMATE_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: CLIMATE}, blocking=True
    )


async def test_setting_hvac_mode_off_is_not_gated_either(
    hass: HomeAssistant, mock_uss
) -> None:
    """The second route to the same single-field change, and the one the reporter hit first."""
    await _setup(hass)
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_hvac_mode",
        {ATTR_ENTITY_ID: CLIMATE, "hvac_mode": HVACMode.OFF},
        blocking=True,
    )


async def test_turning_it_on_is_not_gated_either(hass: HomeAssistant, mock_uss) -> None:
    """`climate.turn_on` is also a single-field change, so it was broken too.

    The reporter saw turn-on work because they reached it through `set_hvac_mode` with a real
    mode, which carries `operationMode` as well -- a field this family's byte map does not mark
    writable, so the whole change fell back to the air-conditioner path by luck.
    """
    await _setup(hass)
    await hass.services.async_call(
        CLIMATE_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: CLIMATE}, blocking=True
    )


async def test_power_goes_out_as_a_group_set_not_a_single_parameter_write(
    hass: HomeAssistant, mock_uss
) -> None:
    """The other half of the bug, and the reason translating the value would not have fixed it.

    Refusing the write was only the visible symptom. Had the validator merely been taught to
    convert `0` to `"false"`, the change would have gone out as `5D00` + payload -- a
    single-parameter write this project has never confirmed on a classic air-conditioner family,
    and one the owner's own unit refuses for every attribute but power (probed live 2026-09-03).

    `60 01` is grSetDAC, asserted positively so this cannot pass merely because the frame stopped
    being a `5Dxx` one.
    """
    mock_uss.read.return_value = [make_status_frame(power=True)]
    mock_uss.send.baseline = make_status_frame(power=True)
    await _setup(hass)
    await hass.services.async_call(
        CLIMATE_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: CLIMATE}, blocking=True
    )
    frame = mock_uss.send.last_frame
    assert frame is not None
    assert b"\x60\x01" in frame, "power must ride in the air conditioner's group set"
    assert b"\x5d\x00" not in frame, "and must not go out as a byte-map single-parameter write"


async def test_a_fan_change_also_keeps_the_group_set(hass: HomeAssistant, mock_uss) -> None:
    """A second single-field control, so the group-set shape is held by more than power alone.

    ⚠️ This one passes with or without the fix, and that is the point worth recording: this
    family's byte map marks ONLY `onOffStatus` writable, which is why power was the single thing
    that broke on the owner's own units. The cabinet below is where a family that marks eight
    attributes writable loses eight controls.
    """
    await _setup(hass)
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_fan_mode",
        {ATTR_ENTITY_ID: CLIMATE, "fan_mode": "low"},
        blocking=True,
    )
    frame = mock_uss.send.last_frame
    assert frame is not None
    assert b"\x60\x01" in frame
    assert b"\x5d" not in frame


async def test_a_water_heater_still_uses_the_byte_map_for_writes(
    hass: HomeAssistant, mock_uss
) -> None:
    """The no-over-correction clause: this fix must not take the byte-map write path away from the
    appliances it was built for.

    Issue #13's heat-pump water heater is the one appliance whose non-AC write is confirmed on real
    hardware, so it is the right guard. Asserted through `model_write_fields` rather than by sending
    a frame -- `test_water_heater.py` already owns the end-to-end assertion, and duplicating it here
    would give two tests one reason to fail.
    """

    entry = await _setup(
        hass,
        **{
            CONF_UPLUS_ID: (
                "201c120000118674200100418007574800000000000000000000000000000040"
            ),
            CONF_DIGITAL_MODEL: json.dumps(
                {
                    "attributes": [{"name": "targetTemperature", "writable": True}],
                    "invisible_attributes": [],
                }
            ),
        },
    )
    coordinator = entry.runtime_data
    assert coordinator.uses_curated_ac_entities is False
    assert "targetTemperature" in coordinator.model_write_fields()


# --- Issue #12's commercial cabinet: the widest blast radius --------------------------------
#
# A `0d12` roof cabinet, from the reporter's own diagnostics
# (`captures/issue12/capture-cool22.json` in the development tree): the 133-byte report it sent and
# the 12-attribute digital model its account holds. This class has no group set at all -- it is
# written one setting at a time through its own hand-built `5Dxx` register -- and its byte map marks
# 42 attributes writable, eight of which this unit declares. So eight of its controls, essentially
# its whole surface, were diverted.
CABINET_UPLUS_ID = "201c10c7088081000d1205464544850000009cd68e692c104e2a333eab95d140"
CABINET_REPORT = bytes.fromhex(
    "00002715000000004e5601000003020000040100000000000000000000000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000000000000000000000000035ffff320000000000"
    "00066d0106002300020114000000000000000003020332325f80000300000000000000000000000000000000"
    "34"
)
# ⓘ The reporter's own model, restored to the shape an entry stores. Diagnostics reshape
# `attributes` into a name-keyed dict of value ranges; this is that reshape undone, not a synthesis
# -- every attribute name and every value range is theirs.
CABINET_MODEL = json.loads(
    (Path(__file__).parent / "fixtures" / "issue12_cabinet_model.json").read_text("utf-8")
)
CABINET_CLIMATE = "climate.roof_cabinet"


@pytest.fixture
def cabinet(mock_uss):
    mock_uss.read.return_value = [CABINET_REPORT]
    mock_uss.send.baseline = CABINET_REPORT
    return mock_uss


async def _setup_cabinet(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Roof cabinet",
        unique_id="B1B2C3D4E5F6",
        data={
            CONF_HOST: "192.168.1.51",
            CONF_DEVICE_ID: "B1B2C3D4E5F6",
            CONF_LOCAL_KEY: "00112233445566778899aabbccddeeff",
            CONF_PRODUCT_CODE: "AE2C52Q00",
            CONF_LOCALKEY_VERSION: 4,
            CONF_UPLUS_ID: CABINET_UPLUS_ID,
            CONF_DIGITAL_MODEL: json.dumps(CABINET_MODEL),
        },
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


async def test_the_cabinets_controls_are_not_gated_by_the_byte_map(
    hass: HomeAssistant, cabinet
) -> None:
    """Power and setpoint on issue #12's hardware.

    The setpoint is the sharper of the two: 22 C is EPP 6, and the model declares 16-30, so the
    byte-map validator rejected a perfectly ordinary temperature as out of range. Power and
    setpoint are asserted together because they fail for different reasons -- an enum the EPP value
    is not a member of, and a number the EPP value is below.
    """
    await _setup_cabinet(hass)
    await hass.services.async_call(
        CLIMATE_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: CABINET_CLIMATE}, blocking=True
    )
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_temperature",
        {ATTR_ENTITY_ID: CABINET_CLIMATE, "temperature": 22},
        blocking=True,
    )


async def test_the_cabinet_still_writes_through_its_own_register(
    hass: HomeAssistant, cabinet
) -> None:
    """And it keeps the hand-built `5Dxx` id, not the byte map's.

    This class NACKs the group set, so "not the byte-map path" is not enough on its own -- the
    frame has to be its own single-parameter write. `5D02` is the setpoint id, confirmed on this
    reporter's hardware.
    """
    await _setup_cabinet(hass)
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_temperature",
        {ATTR_ENTITY_ID: CABINET_CLIMATE, "temperature": 22},
        blocking=True,
    )
    frame = cabinet.send.last_frame
    assert frame is not None
    assert b"\x5d\x02" in frame, "the setpoint keeps this class's confirmed single-parameter id"
