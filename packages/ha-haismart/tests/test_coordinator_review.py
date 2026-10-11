"""Coordinator edge cases: what a write publishes, and how a failed cycle is classified.

Each of these is a path where the coordinator used to tell Home Assistant something wrong -- an
entity blanked after a write, a hold that never reset, a reauth demanded for a network outage.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from conftest import make_status_frame
from haismart_extractor import GatewayConnectionError, GatewayError, LocalKey
from haismart_extractor.cloud import CloudConnectionError
from haismart_hrdp import LocalKeyRotated
from homeassistant.components.water_heater import DOMAIN as WATER_HEATER_DOMAIN
from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.const import ATTR_ENTITY_ID, ATTR_TEMPERATURE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from test_init import _entry, _setup
from test_water_heater import (
    DUAL_SOURCE,
    ENTITY,
    water_heater,  # noqa: F401 - fixture
)
from test_water_heater import _setup as _setup_water_heater

from custom_components.haismart import discovery
from custom_components.haismart.const import (
    CONF_LOCALKEY_VERSION,
    DOMAIN,
    ROTATION_OUTAGE_GRACE,
)

GATEWAY = "custom_components.haismart.coordinator.get_localkey_via_gateway"
REFRESH = "custom_components.haismart.coordinator.HaierCloud.refresh_token"


def _gateway_entry(**extra):
    return _entry(
        cloud_client_id="A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
        access_token="tok-abc",
        **extra,
    )


async def _setup_entry(hass: HomeAssistant, entry):
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


# --- what a write publishes -------------------------------------------------------------------


async def test_a_byte_map_write_keeps_the_model_state(
    hass: HomeAssistant, water_heater  # noqa: F811
) -> None:
    """The echo is published as the new state, so it must carry what the poll does.

    Every water-heater and generic entity reads `model_state`; an echo without it took all of them
    to `unknown` after each command, until the next poll.
    """
    entry = await _setup_water_heater(hass)
    water_heater.send.return_value = [DUAL_SOURCE]
    await hass.services.async_call(
        WATER_HEATER_DOMAIN, "set_temperature",
        {ATTR_ENTITY_ID: ENTITY, ATTR_TEMPERATURE: 55}, blocking=True,
    )
    await hass.async_block_till_done()
    assert entry.runtime_data.data.get("model_state"), "the echo dropped the byte-map decode"
    state = hass.states.get(ENTITY)
    # the echo's own reading (DUAL_SOURCE's tank is 50), not the poll's 49 and not unknown
    assert state.attributes["current_temperature"] == 50.0


async def test_a_published_write_ends_the_hold(hass: HomeAssistant, mock_uss) -> None:
    """Fresh data from the unit is the end of a failure run, whichever path brought it."""
    coordinator = (await _setup(hass)).runtime_data
    coordinator._held_cycles, coordinator._held_since = 2, hass.loop.time() - 100
    mock_uss.send.return_value = [make_status_frame()]
    await coordinator.async_send_control({"onOffStatus": 1})
    assert coordinator._held_cycles == 0


# --- a rotated key on the read path -----------------------------------------------------------


async def test_a_rotation_during_a_cloud_outage_retries_rather_than_reauths(
    hass: HomeAssistant, mock_uss
) -> None:
    """A key service that is merely unreachable is not a credential problem.

    It used to be fetched twice (once here, once more by the probe) and then answered with a reauth
    flow -- asking someone to sign in again because their internet blinked.
    """
    coordinator = await _setup_entry(hass, _gateway_entry())
    mock_uss.read.side_effect = LocalKeyRotated(device_version=5, held_version=4)
    with patch(GATEWAY, side_effect=OSError("network unreachable")) as gw:
        with pytest.raises(UpdateFailed):
            await coordinator._async_read_cycle()
    assert gw.call_count == 1, "one fetch per cycle, not a second through the probe"
    assert mock_uss.probe.call_count == 0, "the handshake already said which version it holds"
    assert not hass.config_entries.flow.async_progress_by_handler(DOMAIN)


async def test_a_broker_that_hangs_up_retries_rather_than_reauths(
    hass: HomeAssistant, mock_uss
) -> None:
    """A dropped MQTT connection is the network, not the account -- same rule as an OSError."""
    coordinator = await _setup_entry(hass, _gateway_entry())
    mock_uss.read.side_effect = LocalKeyRotated(device_version=5, held_version=4)
    with patch(GATEWAY, side_effect=GatewayConnectionError("gateway closed the connection")):
        with pytest.raises(UpdateFailed):
            await coordinator._async_read_cycle()
    assert not hass.config_entries.flow.async_progress_by_handler(DOMAIN)


async def test_a_rejected_account_still_reauths_after_a_single_fetch(
    hass: HomeAssistant, mock_uss
) -> None:
    coordinator = await _setup_entry(hass, _gateway_entry())
    mock_uss.read.side_effect = LocalKeyRotated(device_version=5, held_version=4)
    with patch(GATEWAY, side_effect=GatewayError("CONNACK rc=4")) as gw:
        with pytest.raises(ConfigEntryAuthFailed):
            await coordinator._async_read_cycle()
    assert gw.call_count == 1


async def test_a_rotation_with_no_account_reauths(hass: HomeAssistant, mock_uss) -> None:
    coordinator = (await _setup(hass)).runtime_data
    mock_uss.read.side_effect = LocalKeyRotated(device_version=5, held_version=4)
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_read_cycle()


async def test_the_probe_path_also_retries_during_a_cloud_outage(
    hass: HomeAssistant, mock_uss, freezer
) -> None:
    """Same rule when the rotation is found by the probe after empty cycles."""
    coordinator = await _setup_entry(hass, _gateway_entry())
    mock_uss.probe.return_value = 5
    with patch(GATEWAY, side_effect=TimeoutError("timed out")):
        with pytest.raises(UpdateFailed):
            await coordinator._check_localkey_rotation()
    assert not hass.config_entries.flow.async_progress_by_handler(DOMAIN)


async def test_the_probe_path_reauths_a_rejected_account(hass: HomeAssistant, mock_uss) -> None:
    coordinator = await _setup_entry(hass, _gateway_entry())
    mock_uss.probe.return_value = 5
    with patch(GATEWAY, side_effect=GatewayError("CONNACK rc=4")):
        with pytest.raises(ConfigEntryAuthFailed):
            await coordinator._check_localkey_rotation()
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert not flows or flows[0]["context"]["source"] == SOURCE_REAUTH


async def test_an_unreachable_token_refresh_is_not_blamed_on_the_stale_token(
    hass: HomeAssistant, mock_uss
) -> None:
    """The refresh could not reach Haier, so the gateway was handed yesterday's (expired) token and
    refused it. That refusal is about the token nobody could renew, not the account: retry."""
    coordinator = await _setup_entry(hass, _gateway_entry(refresh_token="rt-durable"))
    mock_uss.read.side_effect = LocalKeyRotated(device_version=5, held_version=4)
    with (
        patch(REFRESH, side_effect=CloudConnectionError("POST uhome: ConnectError")),
        patch(GATEWAY, side_effect=GatewayError("gateway errNo=110001 for dev")),
    ):
        with pytest.raises(UpdateFailed):
            await coordinator._async_read_cycle()
    assert not hass.config_entries.flow.async_progress_by_handler(DOMAIN)


async def test_an_outage_that_outlasts_the_grace_period_escalates(
    hass: HomeAssistant, mock_uss
) -> None:
    """Retrying quietly forever hid a DNS/firewall block -- or a broker refusing by hanging up --
    behind an AC that was simply unavailable. Past the grace period it escalates."""
    coordinator = await _setup_entry(hass, _gateway_entry())
    mock_uss.read.side_effect = LocalKeyRotated(device_version=5, held_version=4)
    with patch(GATEWAY, side_effect=OSError("network unreachable")):
        with pytest.raises(UpdateFailed):
            await coordinator._async_read_cycle()
        coordinator._outage_since = hass.loop.time() - ROTATION_OUTAGE_GRACE - 1
        with pytest.raises(ConfigEntryAuthFailed):
            await coordinator._async_read_cycle()


async def test_a_healed_refresh_ends_the_outage_run(hass: HomeAssistant, mock_uss) -> None:
    coordinator = await _setup_entry(hass, _gateway_entry())
    coordinator._outage_since = hass.loop.time() - ROTATION_OUTAGE_GRACE - 1
    with patch(GATEWAY, return_value=LocalKey(key="0123456789abcdef0123456789abcdef", version=5)):
        assert await coordinator._async_gateway_refresh()
    assert coordinator._outage_since is None


async def test_no_probe_without_a_held_version(hass: HomeAssistant, mock_uss) -> None:
    """With no version to compare against, the probe's answer decides nothing: skip the session."""
    coordinator = await _setup_entry(hass, _entry(**{CONF_LOCALKEY_VERSION: None}))
    coordinator.localkey_version = None
    mock_uss.probe.reset_mock()
    await coordinator._check_localkey_rotation()
    assert mock_uss.probe.call_count == 0


# --- a garbled read ---------------------------------------------------------------------------


async def test_a_decode_error_is_a_missed_cycle_not_a_crash(
    hass: HomeAssistant, mock_uss
) -> None:
    """uSS decoding raises ValueError (a failed MD5, a short message). A miss like any other:
    held, counted, a reason to look for the unit elsewhere -- not an unexpected-error traceback."""
    coordinator = (await _setup(hass)).runtime_data
    mock_uss.read.side_effect = ValueError("biz integrity (MD5) check failed")
    await coordinator.async_refresh()
    assert coordinator.last_update_success, "the previous reading stands in"
    assert coordinator._held_cycles == 1
    assert mock_uss.rediscover.await_count == 1


# --- bounded network sweeps -------------------------------------------------------------------


async def test_a_hung_arp_scan_is_no_answer(monkeypatch) -> None:
    class _Hangs:
        async def async_discover(self):
            await asyncio.sleep(3600)

    import sys
    from types import SimpleNamespace

    # aiodiscover ships with HA's `dhcp` component and need not be installed here.
    monkeypatch.setitem(sys.modules, "aiodiscover", SimpleNamespace(DiscoverHosts=_Hangs))
    monkeypatch.setattr(discovery, "ARP_TIMEOUT", 0.01)
    async with asyncio.timeout(5):          # the bound is under test, so fail rather than hang
        assert await discovery.async_resolve_host_arp("A1B2C3D4E5F6") is None


async def test_a_slow_rules_fetch_does_not_hold_up_setup(hass: HomeAssistant, mock_uss) -> None:
    """The awaited top-up is an improvement; an unreachable cloud must not stall startup for it."""
    import custom_components.haismart as integration
    from custom_components.haismart.coordinator import HaismartCoordinator

    async def _hangs(self):
        await asyncio.sleep(3600)

    entry = _entry()
    entry.add_to_hass(hass)
    with (
        patch.object(integration, "MODEL_RULES_TIMEOUT", 0.01),
        patch.object(HaismartCoordinator, "needs_invisible_topup", True),
        patch.object(HaismartCoordinator, "async_fetch_model_rules", _hangs),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
