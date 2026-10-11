"""Entity details that are easy to get quietly wrong: device identity, select options, recorder."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from haismart_hrdp.entity_spec import Control, EntitySpec
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.haismart.const import (
    CONF_DEVICE_ID,
    CONF_HOST,
    CONF_LOCAL_KEY,
    CONF_LOCALKEY_VERSION,
    CONF_PRODUCT_CODE,
    DOMAIN,
)


async def _device(hass: HomeAssistant, **extra) -> dr.DeviceEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Downstairs AC",
        unique_id="A1B2C3D4E5F6",
        data={
            CONF_HOST: "192.168.1.50",
            CONF_DEVICE_ID: "A1B2C3D4E5F6",
            CONF_LOCAL_KEY: "00112233445566778899aabbccddeeff",
            CONF_LOCALKEY_VERSION: 4,
            **extra,
        },
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, "A1B2C3D4E5F6")})
    assert device is not None
    return device


async def test_an_unknown_model_is_not_shown_as_the_fallback_code(
    hass: HomeAssistant, mock_uss
) -> None:
    """With no product code stored the coordinator decodes with a built-in default -- and the device
    page then named that default as this unit's model, which reads exactly like a real one."""
    device = await _device(hass)
    assert device.model is None
    assert device.model_id is None


async def test_a_stored_product_code_is_still_the_model(hass: HomeAssistant, mock_uss) -> None:
    device = await _device(hass, **{CONF_PRODUCT_CODE: "AACRL2E00"})
    assert device.model == "AACRL2E00"
    assert device.model_id == "AACRL2E00"


def _select(options):
    from custom_components.haismart.select import HaismartGenericSelect

    coordinator = MagicMock()
    coordinator.device_id = "A1B2C3D4E5F6"
    coordinator.config_entry.data = {}
    coordinator.locked_fields = frozenset()
    coordinator.async_send_control = AsyncMock()
    spec = EntitySpec("fanLevel", Control.SELECT, "Fan level", True, options=options)
    return HaismartGenericSelect(coordinator, spec), coordinator


async def test_a_select_with_duplicate_labels_offers_every_value() -> None:
    """Keyed on the label, two values sharing one kept only the last: the first could never be
    chosen, and choosing the label wrote the other value. Clashing labels are told apart instead."""
    select, coordinator = _select(((1, "Low"), (2, "Low"), (3, "High")))
    assert len(select.options) == 3
    assert "High" in select.options                  # an unambiguous label is left alone
    for value, option in zip((1, 2, 3), select.options, strict=True):
        await select.async_select_option(option)
        assert coordinator.async_send_control.await_args.args[0] == {"fanLevel": value}
    coordinator.data = {"model_state": {"fanLevel": 2}}
    assert select.current_option == select.options[1]


def test_the_key_sensor_keeps_addresses_out_of_history() -> None:
    """Its attributes are a manual-onboarding backup; the recorder has no use for where the unit
    sits on the LAN or its MAC, and would keep every change of either forever."""
    from custom_components.haismart.sensor import HaismartLocalKeySensor

    unrecorded = HaismartLocalKeySensor._Entity__combined_unrecorded_attributes  # noqa: SLF001
    assert {CONF_HOST, "device_id"} <= unrecorded
