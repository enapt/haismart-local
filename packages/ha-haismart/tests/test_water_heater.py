"""Issue #13 — a heat-pump water heater, and the entities it must NOT be given.

The report and the device model are the reporter's own, from
`captures/issue13/diag-1-baseline.json` and `diag-4-dualsource.json` in the development tree: one
baseline, one after they switched the unit to dual-source heat in the app. Nothing here is
synthesised, because the point being tested is that a real appliance of a class this integration
had never decoded comes up correctly.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from homeassistant.components.water_heater import (
    ATTR_OPERATION_LIST,
    ATTR_OPERATION_MODE,
    SERVICE_SET_OPERATION_MODE,
)
from homeassistant.components.water_heater import (
    DOMAIN as WATER_HEATER_DOMAIN,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, ATTR_TEMPERATURE, SERVICE_TURN_OFF
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

# 201c1200 0000118674 **2001** ... -- class 2001 is 热泵热水器, a heat-pump water heater.
UPLUS_ID = "201c120000118674200100418007574800000000000000000000000000000040"
PRODUCT_CODE = "GK0GXZE0J"
ENTITY = "water_heater.hot_water"
CLIMATE = "climate.hot_water"

BASELINE = bytes.fromhex(
    "00002715000000004e560100000302000004010000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000057ffff54000000000000066d013112160b"
    "000303e800c8000000000000140000140000000000002222000006000000000052c55900000000000c2a030000000000"
    "0000000000000000000000000000000000000003000000"
)

DUAL_SOURCE = bytes.fromhex(
    "00002715000000004e560100000302000004010000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000057ffff54000000000000066d0132121617"
    "000403e800c80000000000002d00002d0000000000002222000006000000000050c55900000000000c2a030000000000"
    "000000000000000000000000000000000000004300007e"
)

DIGITAL_MODEL = json.loads(
    (Path(__file__).parent / "fixtures" / "issue13_water_heater_model.json").read_text("utf-8")
)


def _entry(**overrides) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Hot water",
        unique_id="A1B2C3D4E5F6",
        data={
            CONF_HOST: "192.168.1.50",
            CONF_DEVICE_ID: "A1B2C3D4E5F6",
            CONF_LOCAL_KEY: "00112233445566778899aabbccddeeff",
            CONF_PRODUCT_CODE: PRODUCT_CODE,
            CONF_LOCALKEY_VERSION: 4,
            CONF_UPLUS_ID: UPLUS_ID,
            CONF_DIGITAL_MODEL: json.dumps(DIGITAL_MODEL),
            **overrides,
        },
    )


@pytest.fixture
def water_heater(mock_uss):
    """The reporter's appliance, answering with its real baseline report."""
    mock_uss.read.return_value = [BASELINE]
    mock_uss.send.baseline = BASELINE
    return mock_uss


async def _setup(hass: HomeAssistant, **overrides) -> MockConfigEntry:
    entry = _entry(**overrides)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_a_water_heater_is_not_given_an_air_conditioner(
    hass: HomeAssistant, water_heater
) -> None:
    """The report in one line: it came up as a climate entity, and it must not.

    Not merely cosmetic -- the climate entity advertised cool / dry / fan_only and clamped the
    setpoint to 16-30 against a real 35-75, so every control on it was wrong.
    """
    entry = await _setup(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get(CLIMATE) is None
    assert hass.states.get(ENTITY) is not None


async def test_it_reads_its_own_temperatures_and_mode(hass: HomeAssistant, water_heater) -> None:
    """Decoded from Haier's published byte map, and checked against what the cloud reported.

    These are the numbers the reporter's own app showed for this capture: tank at 49, set to 48,
    keeping warm rather than heating.
    """
    await _setup(hass)
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.attributes["current_temperature"] == 49.0
    assert state.attributes[ATTR_TEMPERATURE] == 48.0
    # The unit's OWN declared range, not the class-wide 30-80 and emphatically not the AC 16-30.
    assert state.attributes["min_temp"] == 35.0
    assert state.attributes["max_temp"] == 75.0
    # `workStatus` 1 = keep-warm: the field the reporter could not pin, now read from the map.
    assert state.attributes["workStatus"] == 1


async def test_it_offers_only_the_modes_this_unit_declares(
    hass: HomeAssistant, water_heater
) -> None:
    """Eight of its class's nineteen. Offering the other eleven would be phantom controls."""
    await _setup(hass)
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.attributes[ATTR_OPERATION_LIST] == [
        "Instant heat", "Off-peak", "Schedule 1", "Schedule 2", "Schedule 1 + 2",
        "Keep warm", "Eco sterilise", "Adaptive", "off",
    ]
    assert state.state == "Instant heat"


async def test_a_second_capture_reads_its_own_state(hass: HomeAssistant, mock_uss) -> None:
    """The reporter's fourth capture: dual-source heat on, reserve temperatures at 75.

    A decoder that returns the same answer whatever the bytes passes a single-capture test, so the
    second state is asserted rather than assumed.
    """
    mock_uss.read.return_value = [DUAL_SOURCE]
    mock_uss.send.baseline = DUAL_SOURCE
    await _setup(hass)
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.attributes["current_temperature"] == 50.0
    assert state.attributes["dualHeaterMode"] is True
    # 75 C is a real reserve temperature and lands outside the air conditioners' plausibility band.
    assert state.attributes["resn1Temperature"] == 75


async def test_setting_a_temperature_sends_the_published_command(
    hass: HomeAssistant, water_heater
) -> None:
    """`5D01` + the value scaled the way the map says: 55 C goes out as 25, because c = 30.

    Sending 55 would be accepted by the appliance and set something else entirely, and nothing
    would report it.
    """
    await _setup(hass)
    await hass.services.async_call(
        WATER_HEATER_DOMAIN,
        "set_temperature",
        {ATTR_ENTITY_ID: ENTITY, ATTR_TEMPERATURE: 55},
        blocking=True,
    )
    frame = water_heater.send.last_frame
    assert frame is not None
    assert b"\x5d\x01" in frame and b"\x00\x19" in frame


async def test_setting_an_operation_mode_sends_the_epp_value_not_the_std_code(
    hass: HomeAssistant, water_heater
) -> None:
    """中温保温 is std 19 and EPP 6. Sending 19 would select a different mode."""
    await _setup(hass)
    await hass.services.async_call(
        WATER_HEATER_DOMAIN,
        SERVICE_SET_OPERATION_MODE,
        {ATTR_ENTITY_ID: ENTITY, ATTR_OPERATION_MODE: "Keep warm"},
        blocking=True,
    )
    frame = water_heater.send.last_frame
    assert frame is not None
    assert b"\x5d\x04" in frame and b"\x00\x06" in frame


async def test_turning_it_off_sends_the_power_command(
    hass: HomeAssistant, water_heater
) -> None:
    await _setup(hass)
    await hass.services.async_call(
        WATER_HEATER_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: ENTITY}, blocking=True
    )
    frame = water_heater.send.last_frame
    assert frame is not None
    assert b"\x5d\x00" in frame and b"\x00\x00" in frame


async def test_an_out_of_range_temperature_is_refused_before_it_is_sent(
    hass: HomeAssistant, water_heater
) -> None:
    """The unit declares 35-75. 90 must not reach the appliance at all.

    Home Assistant clamps to min/max itself for this service, so what is asserted is that nothing
    out of range goes out on the wire -- by either route.
    """
    await _setup(hass)
    water_heater.send.last_frame = None
    with pytest.raises(Exception):  # noqa: B017 - HA clamps or the coordinator refuses; either is fine
        await hass.services.async_call(
            WATER_HEATER_DOMAIN,
            "set_temperature",
            {ATTR_ENTITY_ID: ENTITY, ATTR_TEMPERATURE: 900},
            blocking=True,
        )
    assert water_heater.send.last_frame is None


async def test_no_unknown_layout_repair_is_raised_for_a_decoded_appliance(
    hass: HomeAssistant, water_heater
) -> None:
    """Its 167-byte report matches no AC layout, and it is not unknown to the user.

    The repair says "this air conditioner's status format is not recognised" and asks for captures.
    Raising it for an appliance we decode completely would be asking a user to report a solved
    problem -- and it is what they saw.
    """
    from homeassistant.helpers import issue_registry as ir

    entry = await _setup(hass)
    registry = ir.async_get(hass)
    unknown = [
        issue for (domain, _key), issue in registry.issues.items()
        if domain == DOMAIN and "layout" in issue.issue_id
    ]
    assert not unknown
    assert entry.runtime_data.model_decoded is True


# --- which platforms an entry gets, and the clause that stops this being a regression -----------

def test_platform_selection_is_explicit_about_what_it_does_not_know() -> None:
    """A unit table, because the rule has three cases and only one of them is obvious."""
    from haismart_hrdp.appliance import ApplianceKind
    from homeassistant.const import Platform

    from custom_components.haismart.const import PLATFORMS, platforms_for

    # Identified: the kind decides, and the no-regression clause is not consulted at all.
    for decodes in (True, False):
        assert platforms_for(
            ApplianceKind.AIR_CONDITIONER, decodes_as_air_conditioner=decodes
        ) == PLATFORMS
        water = platforms_for(ApplianceKind.WATER_HEATER, decodes_as_air_conditioner=decodes)
        assert Platform.WATER_HEATER in water
        assert Platform.CLIMATE not in water

    # Unidentified: a device whose class we have never catalogued but whose report really does read
    # as an air conditioner KEEPS its thermostat. Some working installs are in exactly this state --
    # a family added to the wire maps by capture without its class ever being named -- and breaking
    # them to fix a classification would be the wrong trade.
    unknown_ac = platforms_for(ApplianceKind.OTHER, decodes_as_air_conditioner=True)
    assert Platform.CLIMATE in unknown_ac
    # ...and one that does not decode as an air conditioner gets every model-driven platform and no
    # thermostat. Nothing is lost by not knowing what it is; what is withheld is a confident lie.
    unknown_other = platforms_for(ApplianceKind.OTHER, decodes_as_air_conditioner=False)
    assert Platform.CLIMATE not in unknown_other
    assert Platform.SENSOR in unknown_other and Platform.SWITCH in unknown_other


async def test_an_air_conditioner_still_gets_its_climate_entity(
    hass: HomeAssistant, mock_uss
) -> None:
    """The whole existing user base. Asserted here rather than assumed from the AC suite passing,
    because what changed is which platforms are forwarded, not what the climate entity does."""
    from conftest import make_status_frame

    mock_uss.read.return_value = [make_status_frame()]
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Downstairs AC",
        unique_id="A1B2C3D4E5F6",
        data={
            CONF_HOST: "192.168.1.50",
            CONF_DEVICE_ID: "A1B2C3D4E5F6",
            CONF_LOCAL_KEY: "00112233445566778899aabbccddeeff",
            CONF_PRODUCT_CODE: "AAC1UKZ01",
            CONF_LOCALKEY_VERSION: 4,
        },
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("climate.downstairs_ac") is not None
    assert hass.states.get("water_heater.downstairs_ac") is None


async def test_unloading_uses_the_platforms_that_were_set_up(
    hass: HomeAssistant, water_heater
) -> None:
    """Unloading a platform that was never forwarded leaves entities behind on every reload."""
    entry = await _setup(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert hass.states.get(ENTITY).state == "unavailable"


async def test_an_existing_unknown_layout_repair_is_cleared_once_the_map_decodes(
    hass: HomeAssistant, water_heater
) -> None:
    """The reporter's own entry is in this state: the repair was raised for days.

    Not raising a new one is not enough — the old notification would sit there for ever, telling
    somebody to send captures for a device that now works.
    """
    from homeassistant.helpers import issue_registry as ir

    from custom_components.haismart.const import ISSUE_UNKNOWN_LAYOUT

    entry = _entry()
    entry.add_to_hass(hass)
    registry = ir.async_get(hass)
    issue_id = f"{ISSUE_UNKNOWN_LAYOUT}_{entry.entry_id}"
    ir.async_create_issue(
        hass, DOMAIN, issue_id, is_fixable=False,
        severity=ir.IssueSeverity.WARNING, translation_key=ISSUE_UNKNOWN_LAYOUT,
    )
    assert registry.async_get_issue(DOMAIN, issue_id) is not None

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert registry.async_get_issue(DOMAIN, issue_id) is None
