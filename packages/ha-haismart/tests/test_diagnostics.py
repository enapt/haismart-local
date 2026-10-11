"""What the diagnostics file must NOT carry.

It is the artefact users are told to attach to public GitHub issues, so all of it is published.
The credentials are covered in test_init; these are the identifying values that slipped past them.
"""
from __future__ import annotations

import json

from homeassistant.core import HomeAssistant
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
from custom_components.haismart.diagnostics import async_get_config_entry_diagnostics

HOST = "192.168.1.50"
# A marker planted inside the model JSON: `async_redact_data` walks dicts, not the strings the
# entry stores them in, so a key-based rule on the inner field could never have caught it.
MODEL_MARKER = "DEVICE-IDENTIFYING-0123456789"


def _model() -> dict:
    from conftest import heat_capable_digital_model

    return {**heat_capable_digital_model(), "deviceId": MODEL_MARKER}


async def _diag(hass: HomeAssistant) -> dict:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Downstairs AC",
        unique_id="A1B2C3D4E5F6",
        data={
            CONF_HOST: HOST,
            CONF_DEVICE_ID: "A1B2C3D4E5F6",
            CONF_LOCAL_KEY: "00112233445566778899aabbccddeeff",
            CONF_PRODUCT_CODE: "AAC1UKZ01",
            CONF_LOCALKEY_VERSION: 4,
            CONF_DIGITAL_MODEL: json.dumps(_model()),
        },
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return await async_get_config_entry_diagnostics(hass, entry)


async def test_the_lan_address_is_redacted_everywhere(hass: HomeAssistant, mock_uss) -> None:
    """The entry's host and the address the AC reports for itself are the same fact: where on the
    owner's network the unit sits. Neither helps a maintainer; `host_matches` carries the only thing
    the reported one was there to show."""
    diag = await _diag(hass)
    assert diag["entry"][CONF_HOST] == "**REDACTED**"
    assert diag["cloud"]["reported_host"] == "**REDACTED**"
    assert diag["cloud"]["host_matches"] is True, "the comparison must survive the redaction"
    assert HOST not in json.dumps(diag)


async def test_a_moved_unit_is_still_flagged_after_redaction(
    hass: HomeAssistant, mock_uss
) -> None:
    from haismart_hrdp.udiscovery import DeviceInfo

    mock_uss.cloud.return_value = DeviceInfo(
        device_id="A1B2C3D4E5F6", host="192.168.1.77", port=56800, cloud_state=1000
    )
    diag = await _diag(hass)
    assert diag["cloud"]["host_matches"] is False
    assert "192.168.1.77" not in json.dumps(diag)


async def test_the_stored_model_json_is_redacted_but_summarised(
    hass: HomeAssistant, mock_uss
) -> None:
    diag = await _diag(hass)
    assert diag["entry"][CONF_DIGITAL_MODEL] == "**REDACTED**"
    assert MODEL_MARKER not in json.dumps(diag)
    assert diag["digital_model"], "the summary is what maintainers read, and it must remain"
