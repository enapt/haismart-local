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


async def _diag(hass: HomeAssistant, model_json: str | None = None) -> dict:
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
            CONF_DIGITAL_MODEL: json.dumps(_model()) if model_json is None else model_json,
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


async def test_the_stored_model_keeps_its_tables_and_loses_device_ids(
    hass: HomeAssistant, mock_uss
) -> None:
    """The model's alarm, refusal-reason and constraint tables are the only copy in the file, and
    faults and refusals on appliances nobody here owns are decoded from them, so the model stays.
    A per-device id inside it is redacted. That needs the JSON string parsed:
    `async_redact_data` walks dicts, not the strings the entry stores them in."""
    diag = await _diag(hass)
    kept = json.loads(diag["entry"][CONF_DIGITAL_MODEL])
    assert kept.pop("deviceId") == "**REDACTED**"
    assert MODEL_MARKER not in json.dumps(diag)
    (entry,) = hass.config_entries.async_entries(DOMAIN)
    stored = json.loads(entry.data[CONF_DIGITAL_MODEL])
    del stored["deviceId"]
    assert kept == stored, "everything but the identifier is kept, as stored"
    assert diag["digital_model"], "the summary is what maintainers read, and it must remain"


async def test_a_model_with_no_identifier_is_published_as_stored(
    hass: HomeAssistant, mock_uss
) -> None:
    """A maintainer tool reads this field with `json.loads`: it stays a string, byte for byte."""
    from conftest import heat_capable_digital_model

    diag = await _diag(hass, json.dumps(heat_capable_digital_model()))
    (entry,) = hass.config_entries.async_entries(DOMAIN)
    assert diag["entry"][CONF_DIGITAL_MODEL] == entry.data[CONF_DIGITAL_MODEL]


async def test_a_model_that_does_not_parse_is_redacted_whole(
    hass: HomeAssistant, mock_uss
) -> None:
    diag = await _diag(hass, '{"deviceId": "' + MODEL_MARKER)
    assert diag["entry"][CONF_DIGITAL_MODEL] == "**REDACTED**"
    assert MODEL_MARKER not in json.dumps(diag)
