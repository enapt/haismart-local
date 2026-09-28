"""`climate.set_temperature`: the mode it may carry, and the values the wire cannot hold."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from conftest import heat_capable_digital_model
from homeassistant.components.climate import DOMAIN as CLIMATE_DOMAIN
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.haismart.const import (
    CONF_DEVICE_ID,
    CONF_DIGITAL_MODEL,
    CONF_HOST,
    CONF_LOCAL_KEY,
    CONF_LOCALKEY_VERSION,
    CONF_PRODUCT_CODE,
    DOMAIN,
)

CLIMATE = "climate.downstairs_ac"


def _model(**temp_range) -> dict:
    model = heat_capable_digital_model()
    if temp_range:
        for attr in model["attributes"]:
            if attr["name"] == "targetTemperature":
                attr["valueRange"] = {"type": "STEP", "dataStep": temp_range}
    return model


async def _setup(hass: HomeAssistant, model: dict | None = None):
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
            CONF_DIGITAL_MODEL: json.dumps(model or _model()),
        },
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


async def _set_temperature(hass: HomeAssistant, coordinator, **data) -> AsyncMock:
    with patch.object(coordinator, "async_send_control", AsyncMock()) as send:
        await hass.services.async_call(
            CLIMATE_DOMAIN, "set_temperature", {ATTR_ENTITY_ID: CLIMATE, **data}, blocking=True
        )
    return send


async def test_a_mode_given_with_the_temperature_rides_in_the_same_write(
    hass: HomeAssistant, mock_uss
) -> None:
    """`hvac_mode` is part of the set_temperature schema, and was dropped: an automation asking for
    "heat at 24" got 24 in whatever mode the unit was already in. One group-set carries both."""
    coordinator = await _setup(hass)
    send = await _set_temperature(hass, coordinator, temperature=24, hvac_mode="heat")
    send.assert_awaited_once()
    changes = send.await_args.args[0]
    assert changes["targetTemperature"] == 24 - 16
    assert changes["operationMode"] == 4          # the model's heat code
    assert changes["onOffStatus"] == 1


async def test_off_with_a_temperature_turns_it_off(hass: HomeAssistant, mock_uss) -> None:
    coordinator = await _setup(hass)
    send = await _set_temperature(hass, coordinator, temperature=24, hvac_mode="off")
    assert send.await_args.args[0] == {"onOffStatus": 0, "targetTemperature": 24 - 16}


async def test_a_plain_temperature_leaves_the_mode_alone(hass: HomeAssistant, mock_uss) -> None:
    coordinator = await _setup(hass)
    send = await _set_temperature(hass, coordinator, temperature=22)
    assert send.await_args.args[0] == {"targetTemperature": 22 - 16}


async def test_the_advertised_range_is_what_the_wire_can_carry(
    hass: HomeAssistant, mock_uss
) -> None:
    """A model declaring a floor of 8 and half-degree steps must not get a UI offering 12 or 22.5:
    the setpoint travels as whole degrees above 16, so those could only ever be refused."""
    await _setup(hass, _model(minValue="8", maxValue="30", step="0.5"))
    attrs = hass.states.get(CLIMATE).attributes
    assert attrs["min_temp"] == 16
    assert attrs["target_temp_step"] == 1.0


async def test_a_temperature_below_the_wire_floor_is_refused(
    hass: HomeAssistant, mock_uss
) -> None:
    """The raw value is °C − 16, so 12 °C would be a negative code. Refused, with nothing sent."""
    coordinator = await _setup(hass, _model(minValue="8", maxValue="30", step="1"))
    with pytest.raises(ServiceValidationError):
        await _set_temperature(hass, coordinator, temperature=12)
    send = await _set_temperature(hass, coordinator, temperature=16)
    assert send.await_args.args[0] == {"targetTemperature": 0}


async def test_a_fahrenheit_conversion_is_rounded_even_on_a_half_step_model(
    hass: HomeAssistant, mock_uss
) -> None:
    """72 °F arrives as 22.2 °C. Refusing it because the model once declared half-degree steps left
    every imperial install unable to set a temperature."""
    coordinator = await _setup(hass, _model(minValue="16", maxValue="30", step="0.5"))
    send = await _set_temperature(hass, coordinator, temperature=22.2222)
    assert send.await_args.args[0] == {"targetTemperature": 6}
