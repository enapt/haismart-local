"""Config flow tests. Requires homeassistant + pytest-homeassistant-custom-component."""
from __future__ import annotations

from ipaddress import ip_address

import pytest
from haismart_extractor.cloud import CloudError
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.haismart.const import (
    CONF_DEVICE_ID,
    CONF_HOST,
    CONF_LOCAL_KEY,
    CONF_LOCALKEY_VERSION,
    CONF_PRODUCT_CODE,
    CONF_SCAN_INTERVAL,
    CONF_ZONE_INFO,
    DOMAIN,
)

try:  # HA >= 2025.2
    from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
except ImportError:
    from homeassistant.components.zeroconf import ZeroconfServiceInfo

LOCAL_KEY = "00112233445566778899aabbccddeeff"

USER_INPUT = {
    CONF_HOST: "192.168.1.50",
    CONF_DEVICE_ID: "A1B2C3D4E5F6",
    CONF_LOCAL_KEY: LOCAL_KEY,
    "name": "Downstairs AC",
}


async def _past_model_step(hass: HomeAssistant, result):
    """Answer the "which model is this?" step with "skip" if the flow reached it.

    The manual path always asks, because it is the one place the question can be put as a
    shortlist rather than a free-text code. Tests that are not about the model itself say "skip",
    which is a first-class answer: the appliance reads and controls either way.
    """
    if result.get("type") == FlowResultType.FORM and result.get("step_id") == "model":
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"product_code": "skip"}
        )
    await hass.async_block_till_done()
    return result


async def _start_manual(hass: HomeAssistant) -> str:
    """Init the flow and pick the 'manual' menu option; return the manual form's flow_id."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] == FlowResultType.MENU
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "manual"}
    )
    assert result["type"] == FlowResultType.FORM
    return result["flow_id"]


def _entry(**overrides) -> MockConfigEntry:
    data = {
        CONF_HOST: "192.168.1.50",
        CONF_DEVICE_ID: "A1B2C3D4E5F6",
        CONF_LOCAL_KEY: LOCAL_KEY,
        CONF_PRODUCT_CODE: "AAC1UKZ01",
        CONF_LOCALKEY_VERSION: 4,
        **overrides,
    }
    return MockConfigEntry(
        domain=DOMAIN, data=data, unique_id=data[CONF_DEVICE_ID], title="Downstairs AC"
    )


async def test_user_flow_creates_entry(hass: HomeAssistant, mock_uss) -> None:
    flow_id = await _start_manual(hass)
    result2 = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)
    result2 = await _past_model_step(hass, result2)

    assert result2["type"] == FlowResultType.CREATE_ENTRY
    assert result2["title"] == "Downstairs AC"
    assert result2["data"][CONF_DEVICE_ID] == "A1B2C3D4E5F6"
    assert result2["data"][CONF_LOCAL_KEY] == LOCAL_KEY
    # the AC's current localKey version is stored for rotation detection
    assert result2["data"][CONF_LOCALKEY_VERSION] == 4
    # No product code was supplied, so none is stored. It must not default to this project's own:
    # it is the identifier a device's model, rules and real feature set are looked up by, and a
    # wrong one is indistinguishable from a right one.
    assert CONF_PRODUCT_CODE not in result2["data"]


@pytest.mark.parametrize("bad_key", ["not-hex-not-hex-not-hex-not-hex-!", "abcd12"])
async def test_user_flow_invalid_key(hass: HomeAssistant, mock_uss, bad_key: str) -> None:
    flow_id = await _start_manual(hass)
    result2 = await hass.config_entries.flow.async_configure(
        flow_id, {**USER_INPUT, CONF_LOCAL_KEY: bad_key}
    )
    assert result2["type"] == FlowResultType.FORM
    assert result2["errors"] == {"base": "invalid_key"}


async def test_user_flow_cannot_connect(hass: HomeAssistant, mock_uss) -> None:
    mock_uss.probe.side_effect = OSError("no route to host")
    flow_id = await _start_manual(hass)
    result2 = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)
    assert result2["type"] == FlowResultType.FORM
    assert result2["errors"] == {"base": "cannot_connect"}


async def test_user_flow_wrong_key_is_invalid_auth(hass: HomeAssistant, mock_uss) -> None:
    """Handshake ok but nothing decrypts (MD5 fail on every payload) -> invalid_auth."""
    mock_uss.read.return_value = []
    flow_id = await _start_manual(hass)
    result2 = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)
    assert result2["type"] == FlowResultType.FORM
    assert result2["errors"] == {"base": "invalid_auth"}


async def test_user_flow_duplicate_aborts(hass: HomeAssistant, mock_uss) -> None:
    _entry().add_to_hass(hass)
    flow_id = await _start_manual(hass)
    result2 = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)
    assert result2["type"] == FlowResultType.ABORT
    assert result2["reason"] == "already_configured"


def _zeroconf_info(host: str = "192.168.1.50") -> ZeroconfServiceInfo:
    return ZeroconfServiceInfo(
        ip_address=ip_address(host),
        ip_addresses=[ip_address(host)],
        hostname="A1B2C3D4E5F6.local.",
        name="A1B2C3D4E5F6._cae._udp.local.",
        port=56800,
        type="_cae._udp.local.",
        properties={},
    )


async def test_zeroconf_flow_prefills_and_creates(hass: HomeAssistant, mock_uss) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "zeroconf"}, data=_zeroconf_info()
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "manual"  # zeroconf skips the menu, prefilled

    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_HOST: "192.168.1.50",
            CONF_DEVICE_ID: "A1B2C3D4E5F6",
            CONF_LOCAL_KEY: LOCAL_KEY,
        },
    )
    result2 = await _past_model_step(hass, result2)
    assert result2["type"] == FlowResultType.CREATE_ENTRY
    assert result2["data"][CONF_HOST] == "192.168.1.50"
    assert result2["data"][CONF_DEVICE_ID] == "A1B2C3D4E5F6"


async def test_zeroconf_updates_host_of_configured_entry(
    hass: HomeAssistant, mock_uss
) -> None:
    """A DHCP move re-announces on mDNS -> the stored host follows, flow aborts."""
    entry = _entry()
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "zeroconf"}, data=_zeroconf_info("192.168.1.99")
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == "192.168.1.99"


async def test_dhcp_flow_prefills_host_and_device(hass: HomeAssistant, mock_uss) -> None:
    """DHCP discovery (deviceId = MAC, OUI AC:B7:22) prefills host + deviceId; user adds the key."""
    dhcp_mod = pytest.importorskip("homeassistant.components.dhcp")  # needs aiodhcpwatcher
    info = dhcp_mod.DhcpServiceInfo(
        ip="192.168.1.50", hostname="haier-ac", macaddress="acb722aabbcc"
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "dhcp"}, data=info
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "manual"   # host + deviceId prefilled from the MAC
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_HOST: "192.168.1.50", CONF_DEVICE_ID: "ACB722AABBCC", CONF_LOCAL_KEY: LOCAL_KEY},
    )
    result2 = await _past_model_step(hass, result2)
    assert result2["type"] == FlowResultType.CREATE_ENTRY
    assert result2["data"][CONF_HOST] == "192.168.1.50"
    assert result2["data"][CONF_DEVICE_ID] == "ACB722AABBCC"


async def test_resolve_host_by_mac_via_arp(hass: HomeAssistant) -> None:
    """Login resolves a picked AC's IP by matching its deviceId(=MAC) in HA's ARP/DHCP data."""
    pytest.importorskip("aiodiscover")
    from unittest.mock import AsyncMock, MagicMock, patch

    from custom_components.haismart.discovery import async_resolve_host_arp

    hosts = [
        {"ip": "192.168.1.9", "macaddress": "11:22:33:44:55:66"},
        {"ip": "192.168.1.50", "macaddress": "ac:b7:22:aa:bb:cc"},   # our AC (deviceId = MAC)
    ]

    def _fake_discover(return_value):
        # patch the class so no real DiscoverHosts() is constructed (it spawns a thread)
        inst = MagicMock()
        inst.async_discover = AsyncMock(return_value=return_value)
        return MagicMock(return_value=inst)

    with patch("aiodiscover.DiscoverHosts", _fake_discover(hosts)):
        assert await async_resolve_host_arp("ACB722AABBCC") == "192.168.1.50"
    with patch("aiodiscover.DiscoverHosts", _fake_discover([])):
        assert await async_resolve_host_arp("ACB722AABBCC") is None


async def test_reauth_flow_updates_key_and_version(hass: HomeAssistant, mock_uss) -> None:
    entry = _entry()
    entry.add_to_hass(hass)
    mock_uss.probe.return_value = 5  # the AC rotated to v5

    entry.async_start_reauth(hass)
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert len(flows) == 1

    # reauth now OFFERS to re-fetch the key rather than only demanding it, so pick the manual
    # branch explicitly -- a menu is the whole point: the automatic path is the right default for a
    # user who has no way to produce a 32-hex key by hand.
    menu = await hass.config_entries.flow.async_configure(flows[0]["flow_id"])
    assert menu["step_id"] == "reauth"
    assert set(menu["menu_options"]) == {"reauth_cloud", "reauth_confirm"}
    confirm = await hass.config_entries.flow.async_configure(
        flows[0]["flow_id"], {"next_step_id": "reauth_confirm"}
    )
    assert confirm["step_id"] == "reauth_confirm"

    new_key = "ffeeddccbbaa99887766554433221100"
    result = await hass.config_entries.flow.async_configure(
        flows[0]["flow_id"], {CONF_LOCAL_KEY: new_key}
    )
    await hass.async_block_till_done()
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_LOCAL_KEY] == new_key
    assert entry.data[CONF_LOCALKEY_VERSION] == 5


async def test_options_flow_sets_scan_interval(hass: HomeAssistant, mock_uss) -> None:
    entry = _entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 60}
    )
    await hass.async_block_till_done()
    assert result2["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_SCAN_INTERVAL] == 60


async def test_manual_flow_is_local_only(hass: HomeAssistant, mock_uss) -> None:
    """The manual path is purely local — no cloud credentials are stored on the entry."""
    from custom_components.haismart.const import CONF_REFRESH_TOKEN

    flow_id = await _start_manual(hass)
    result2 = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)
    result2 = await _past_model_step(hass, result2)
    assert result2["type"] == FlowResultType.CREATE_ENTRY
    assert CONF_REFRESH_TOKEN not in result2["data"]
    assert result2["data"][CONF_LOCAL_KEY] == LOCAL_KEY


def _cloud_consts():
    from custom_components.haismart.const import (
        CONF_ACCESS_TOKEN,
        CONF_CLOUD_CLIENT_ID,
        CONF_LOCALKEY_VERSION,
        CONF_REFRESH_TOKEN,
        CONF_ZONE_INFO,
    )

    return (CONF_ACCESS_TOKEN, CONF_CLOUD_CLIENT_ID, CONF_LOCALKEY_VERSION,
            CONF_REFRESH_TOKEN, CONF_ZONE_INFO)


async def _drive_login_to_pick(hass, mock_uss, extra_patches):
    """Menu -> email/password login -> device picker; pick Downstairs. Returns the post-pick result.

    ``extra_patches`` (list of context managers) stubs the hands-off fetch/resolve so the tests make
    no network calls."""
    from contextlib import ExitStack
    from unittest.mock import patch

    from haismart_extractor.cloud import SEA_APP_CREDENTIALS, CloudDevice, HaierCloud
    from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

    CONF_ACCESS_TOKEN, CONF_CLOUD_CLIENT_ID, _, CONF_REFRESH_TOKEN, CONF_ZONE_INFO = _cloud_consts()
    cloud_data = {
        CONF_REFRESH_TOKEN: "2_RT", CONF_ACCESS_TOKEN: "2_FRESH",
        CONF_CLOUD_CLIENT_ID: "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4", CONF_ZONE_INFO: "66",
    }
    client = HaierCloud(SEA_APP_CREDENTIALS, "2_FRESH")
    devices = [
        # prod_no is what a real device list carries and is the identifier the rules are keyed by
        CloudDevice("A1B2C3D4E5F6", "Downstairs", "0201203a", "UPLUS", True,
                    prod_no="AAC1UKZ01"),
        CloudDevice("A1B2C3D4E5F7", "Upstairs", "0201203a", "UPLUS", False,
                    prod_no="AAC1UKZ01"),
    ]

    async def fake_login(username, password, zone_info, *, transport=None):
        # the flow must hand the library HA's shared-client transport, never let it build its own
        # (constructing an httpx client loads the CA bundle from disk = blocking the event loop)
        assert transport is not None
        return client, cloud_data

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "login"}
    )
    with ExitStack() as stack:
        stack.enter_context(patch(
            "custom_components.haismart.config_flow._async_login_cloud", side_effect=fake_login))
        stack.enter_context(patch(
            "custom_components.haismart.config_flow.HaierCloud.list_devices_v2",
            return_value=devices))
        stack.enter_context(patch(
            "custom_components.haismart.config_flow.HaierCloud.get_digital_model",
            return_value={"attributes": []}))
        for p in extra_patches:
            stack.enter_context(p)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: "me@example.com", CONF_PASSWORD: "pw", CONF_ZONE_INFO: "66"},
        )
        assert result["step_id"] == "pick_device"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_DEVICE_ID: "A1B2C3D4E5F6"}
        )
        await hass.async_block_till_done()
    return result


async def test_login_flow_autofetches_key_asks_only_host(hass: HomeAssistant, mock_uss) -> None:
    """Key auto-fetched, but mDNS couldn't find the IP -> ask for ONLY the host, then create."""
    from unittest.mock import AsyncMock, patch

    result = await _drive_login_to_pick(hass, mock_uss, [
        patch("custom_components.haismart.config_flow._async_fetch_localkey",
              new=AsyncMock(return_value=(LOCAL_KEY, 13))),
        patch("custom_components.haismart.config_flow._async_resolve_host",
              new=AsyncMock(return_value=None)),   # mDNS miss
    ])
    assert result["step_id"] == "host"
    assert set(result["data_schema"].schema) == {CONF_HOST}     # ONLY the IP, no key field
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.168.1.50"}
    )
    await hass.async_block_till_done()
    assert result2["type"] == FlowResultType.CREATE_ENTRY
    assert result2["data"][CONF_LOCAL_KEY] == LOCAL_KEY         # never pasted


async def test_login_flow_falls_back_to_manual_if_gateway_fails(
    hass: HomeAssistant, mock_uss
) -> None:
    """A failed key fetch reaches a step that explains itself and offers a retry.

    It used to drop the user straight onto the manual form, which demands a 32-hex key seconds after
    the previous step promised they would not have to paste anything -- and which they have no way
    to obtain by hand. That was a dead end; the only way out was to abandon setup.
    """
    from unittest.mock import AsyncMock, patch

    from haismart_extractor import GatewayError

    result = await _drive_login_to_pick(hass, mock_uss, [
        patch("custom_components.haismart.config_flow._async_fetch_localkey",
              new=AsyncMock(side_effect=GatewayError("CONNACK rc=5"))),
        patch("custom_components.haismart.config_flow._async_resolve_host",
              new=AsyncMock(return_value=None)),
    ])
    assert result["step_id"] == "key_failed"
    assert set(result["menu_options"]) == {"key_retry", "manual"}

    manual = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "manual"}
    )
    assert manual["step_id"] == "manual"
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_HOST: "192.168.1.50", CONF_DEVICE_ID: "A1B2C3D4E5F6", CONF_LOCAL_KEY: LOCAL_KEY},
    )
    await hass.async_block_till_done()
    assert result2["type"] == FlowResultType.CREATE_ENTRY
    assert result2["data"][CONF_LOCAL_KEY] == LOCAL_KEY


async def test_login_flow_email_password_hands_off(hass: HomeAssistant, mock_uss) -> None:
    """Menu -> email/password -> picker -> key+IP auto-resolved -> entry (nothing pasted)."""
    from unittest.mock import AsyncMock, patch

    from haismart_extractor.cloud import SEA_APP_CREDENTIALS, CloudDevice, HaierCloud
    from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

    (CONF_ACCESS_TOKEN, CONF_CLOUD_CLIENT_ID, _,
     CONF_REFRESH_TOKEN, CONF_ZONE_INFO) = _cloud_consts()
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "login"}
    )
    assert result["step_id"] == "login"

    client = HaierCloud(SEA_APP_CREDENTIALS, "2_UHOME")
    cloud_data = {
        CONF_REFRESH_TOKEN: "2_RT", CONF_ACCESS_TOKEN: "2_UHOME",
        CONF_CLOUD_CLIENT_ID: "ABCDEF0123456789ABCDEF0123456789", CONF_ZONE_INFO: "0",
    }
    devices = [CloudDevice("A1B2C3D4E5F6", "Downstairs", "0201203a", "UPLUS", True,
                           prod_no="AAC1UKZ01")]

    async def fake_login(username, password, zone_info, *, transport=None):
        assert username == "me@example.com" and password == "hunter2" and zone_info == "66"
        assert transport is not None  # HA's shared httpx client, not one built on the loop
        return client, cloud_data

    with patch(
        "custom_components.haismart.config_flow._async_login_cloud", side_effect=fake_login
    ), patch(
        "custom_components.haismart.config_flow.HaierCloud.list_devices_v2", return_value=devices
    ), patch(
        "custom_components.haismart.config_flow.HaierCloud.get_digital_model",
        return_value={"attributes": []},
    ), patch(
        "custom_components.haismart.config_flow._async_fetch_localkey",
        new=AsyncMock(return_value=(LOCAL_KEY, 13)),
    ), patch(
        "custom_components.haismart.config_flow._async_resolve_host",
        new=AsyncMock(return_value="192.168.1.50"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            # the country is now an explicit choice: there is no hardcoded default to fall back on
            {CONF_USERNAME: "me@example.com", CONF_PASSWORD: "hunter2", CONF_ZONE_INFO: "66"},
        )
        assert result["step_id"] == "pick_device"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_DEVICE_ID: "A1B2C3D4E5F6"}
        )
        await hass.async_block_till_done()
    assert result["type"] == FlowResultType.CREATE_ENTRY          # hands-off, no paste
    assert result["data"][CONF_REFRESH_TOKEN] == "2_RT"          # durable token, from login
    assert result["data"][CONF_LOCAL_KEY] == LOCAL_KEY           # fetched, not pasted
    assert result["data"][CONF_CLOUD_CLIENT_ID] == "ABCDEF0123456789ABCDEF0123456789"


async def test_login_flow_auth_error_shows_form(hass: HomeAssistant, mock_uss) -> None:
    """A bad password (or captcha-gated login) re-shows the login form with an error."""
    from unittest.mock import patch

    from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

    from custom_components.haismart.config_flow import CloudAuthError

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "login"}
    )
    with patch(
        "custom_components.haismart.config_flow._async_login_cloud",
        side_effect=CloudAuthError("retCode B00002-00002: bad password"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: "x@y.com", CONF_PASSWORD: "wrong", CONF_ZONE_INFO: "66"},
        )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "login"
    assert result["errors"]["base"] == "cloud_auth"


def _picker_device_ids(result) -> set[str]:
    """The device IDs offered by a pick_device form (reads the vol.In choices)."""
    for key, val in result["data_schema"].schema.items():
        if str(key) == CONF_DEVICE_ID:
            return set(val.container)
    return set()


async def test_multiple_devices_added_one_at_a_time(hass: HomeAssistant, mock_uss) -> None:
    """Two ACs on the account: add Downstairs, then the picker offers only Upstairs, then it's
    'all configured'. Each AC is its own entry (one per device)."""
    from contextlib import ExitStack
    from unittest.mock import AsyncMock, patch

    from haismart_extractor.cloud import SEA_APP_CREDENTIALS, CloudDevice, HaierCloud
    from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

    (CONF_ACCESS_TOKEN, CONF_CLOUD_CLIENT_ID, _,
     CONF_REFRESH_TOKEN, CONF_ZONE_INFO) = _cloud_consts()
    cloud_data = {
        CONF_REFRESH_TOKEN: "2_RT", CONF_ACCESS_TOKEN: "2_FRESH",
        CONF_CLOUD_CLIENT_ID: "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4", CONF_ZONE_INFO: "66",
    }
    client = HaierCloud(SEA_APP_CREDENTIALS, "2_FRESH")
    devices = [
        CloudDevice("A1B2C3D4E5F6", "Downstairs", "0201203a", "UPLUS", True),
        CloudDevice("A1B2C3D4E5F7", "Upstairs", "0201203a", "UPLUS", False),
    ]

    def _patches():
        return [
            patch("custom_components.haismart.config_flow._async_login_cloud",
                  new=AsyncMock(return_value=(client, cloud_data))),
            patch("custom_components.haismart.config_flow.HaierCloud.list_devices_v2",
                  return_value=devices),
            patch("custom_components.haismart.config_flow.HaierCloud.get_digital_model",
                  return_value={"attributes": []}),
            patch("custom_components.haismart.config_flow._async_fetch_localkey",
                  new=AsyncMock(return_value=(LOCAL_KEY, 13))),
            patch("custom_components.haismart.config_flow._async_resolve_host",
                  new=AsyncMock(return_value="192.168.1.50")),
        ]

    async def _to_picker():
        r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        r = await hass.config_entries.flow.async_configure(r["flow_id"], {"next_step_id": "login"})
        return await hass.config_entries.flow.async_configure(
            r["flow_id"],
            {CONF_USERNAME: "me@example.com", CONF_PASSWORD: "pw", CONF_ZONE_INFO: "66"},
        )

    # 1) add Downstairs — both ACs offered
    with ExitStack() as stack:
        for p in _patches():
            stack.enter_context(p)
        r = await _to_picker()
        assert _picker_device_ids(r) == {"A1B2C3D4E5F6", "A1B2C3D4E5F7"}
        r = await hass.config_entries.flow.async_configure(
            r["flow_id"], {CONF_DEVICE_ID: "A1B2C3D4E5F6"}
        )
        await hass.async_block_till_done()
        assert r["type"] == FlowResultType.CREATE_ENTRY

    # 2) second run — picker now offers ONLY the un-added Upstairs
    with ExitStack() as stack:
        for p in _patches():
            stack.enter_context(p)
        r = await _to_picker()
        assert _picker_device_ids(r) == {"A1B2C3D4E5F7"}
        r = await hass.config_entries.flow.async_configure(
            r["flow_id"], {CONF_DEVICE_ID: "A1B2C3D4E5F7"}
        )
        await hass.async_block_till_done()
        assert r["type"] == FlowResultType.CREATE_ENTRY

    assert len(hass.config_entries.async_entries(DOMAIN)) == 2   # two AC entries

    # 3) both added -> the flow stops cleanly instead of re-offering them
    with ExitStack() as stack:
        for p in _patches():
            stack.enter_context(p)
        r = await _to_picker()
        assert r["type"] == FlowResultType.ABORT
        assert r["reason"] == "all_configured"


async def test_login_country_defaults_from_the_ha_instance(hass: HomeAssistant, mock_uss) -> None:
    """The country field pre-selects from hass.config.country instead of a hardcoded guess.

    It used to default to 66 (Thailand) for everybody, which is wrong for nearly every user, and
    a wrong region is reported by Haier as "account is not registered" - so it reads as a bad
    password. Where the country is unknown the field is left EMPTY on purpose: no default beats
    a plausible-looking wrong one.
    """
    from custom_components.haismart.countries import default_dial_code

    assert default_dial_code("PT") == "351"
    assert default_dial_code("pt") == "351"      # case-insensitive
    assert default_dial_code("TH") == "66"
    assert default_dial_code(None) is None
    assert default_dial_code("ZZ") is None

    await hass.config.async_update(country="PT")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "login"}
    )
    schema = result["data_schema"].schema
    zone_key = next(k for k in schema if str(k) == CONF_ZONE_INFO)
    assert zone_key.default() == "351", "the HA instance's own country should be pre-selected"


async def test_login_wrong_region_gets_its_own_error(hass: HomeAssistant, mock_uss) -> None:
    """retCode 30032 must not be collapsed into the generic 'check all three fields' message."""
    from custom_components.haismart.config_flow import CloudAuthError, _login_error_for

    wrong_region = CloudAuthError("login -> retCode 30032: Account is not registered")
    assert _login_error_for(wrong_region) == "account_not_in_region"
    missing = CloudAuthError("login -> retCode 10001: missing field")
    assert _login_error_for(missing) == "missing_field"
    bad_password = CloudAuthError("login -> retCode B00002: bad password")
    assert _login_error_for(bad_password) == "cloud_auth"


async def test_login_with_no_devices_aborts(hass: HomeAssistant, mock_uss) -> None:
    """Sign-in succeeded; the account is simply empty.

    Re-showing the form as an error invites an endless retype of credentials that were correct,
    and throws away the tokens just obtained.
    """
    from unittest.mock import AsyncMock, MagicMock, patch

    cloud = MagicMock()
    cloud.list_devices_v2 = AsyncMock(return_value=[])
    with patch(
        "custom_components.haismart.config_flow._async_login_cloud",
        AsyncMock(return_value=(cloud, {})),
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "login"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: "me@example.com", CONF_PASSWORD: "pw", CONF_ZONE_INFO: "351"},
        )
    assert result["type"] == "abort"
    assert result["reason"] == "no_devices"


def test_every_error_and_abort_string_exists() -> None:
    """Each errors["base"] / async_abort(reason=...) literal must resolve to a real string.

    A missing key renders in the UI as the raw slug, which is invisible in tests and only ever
    noticed by a user hitting the error path. This also catches strings left behind after the code
    that raised them is gone.
    """
    import json
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "custom_components" / "haismart"
    source = (root / "config_flow.py").read_text(encoding="utf-8")
    strings = json.loads((root / "strings.json").read_text(encoding="utf-8"))

    declared_errors = set(strings["config"]["error"])
    declared_aborts = set(strings["config"]["abort"])
    used_errors = set(re.findall(r'errors\["base"\]\s*=\s*"([a-z_]+)"', source))
    used_errors |= set(re.findall(r'return "([a-z_]+)"', source))     # _login_error_for
    used_aborts = set(re.findall(r'reason="([a-z_]+)"', source))

    # HA supplies these itself; they need no local definition
    builtin_aborts = {"already_configured", "reauth_successful", "already_in_progress"}

    assert not (used_errors - declared_errors), (
        f"config_flow raises errors with no string: {sorted(used_errors - declared_errors)}"
    )
    assert not (used_aborts - declared_aborts - builtin_aborts), (
        f"config_flow aborts with no string: {sorted(used_aborts - declared_aborts)}"
    )
    unused = declared_errors - used_errors
    assert not unused, f"strings.json declares errors nothing raises: {sorted(unused)}"


def test_strings_and_english_translation_are_in_sync() -> None:
    """en.json is the shipped copy of strings.json; drift means the UI shows stale text."""
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "custom_components" / "haismart"
    a = json.loads((root / "strings.json").read_text(encoding="utf-8"))
    b = json.loads((root / "translations" / "en.json").read_text(encoding="utf-8"))
    assert a == b, "strings.json and translations/en.json have diverged"


async def test_key_retry_succeeds_on_the_second_attempt(hass: HomeAssistant, mock_uss) -> None:
    """The retry offered by key_failed actually re-runs the fetch and completes setup."""
    from unittest.mock import AsyncMock, patch

    from haismart_extractor import GatewayError

    fetch = AsyncMock(side_effect=[GatewayError("CONNACK rc=5"), (LOCAL_KEY, 4)])
    with patch("custom_components.haismart.config_flow._async_fetch_localkey", new=fetch):
        result = await _drive_login_to_pick(hass, mock_uss, [
            patch("custom_components.haismart.config_flow._async_resolve_host",
                  new=AsyncMock(return_value="192.168.1.50")),
        ])
        assert result["step_id"] == "key_failed"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "key_retry"}
        )
        await hass.async_block_till_done()

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_LOCAL_KEY] == LOCAL_KEY
    assert fetch.await_count == 2


async def test_reconfigure_changes_the_host_only_after_validating(
    hass: HomeAssistant, mock_uss
) -> None:
    """A bad address must not be committed.

    Re-running the manual flow with the same device id also rewrites the host, but it does so
    BEFORE validating -- so a typo silently took a working entry offline while reporting nothing
    more useful than "already configured".
    """
    entry = _entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "reconfigure_host"}
    )

    mock_uss.probe.side_effect = OSError("no route to host")
    bad = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.168.1.99"}
    )
    assert bad["errors"] == {"base": "cannot_connect"}
    assert entry.data[CONF_HOST] != "192.168.1.99", "a rejected host must not be committed"

    mock_uss.probe.side_effect = None
    good = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.168.1.77"}
    )
    await hass.async_block_till_done()
    assert good["type"] == FlowResultType.ABORT
    assert entry.data[CONF_HOST] == "192.168.1.77"


def test_dhcp_discovery_covers_haier_appliance_ouis_only() -> None:
    """The DHCP matcher must cover Haier's appliance OUIs, and only those.

    This started as a single prefix, which meant most Haier units were never auto-discovered. It is
    asserted here because nothing did: an earlier attempt to widen it was silently lost when the
    script applying it aborted, and no test noticed the manifest had reverted.
    """
    import json
    from pathlib import Path

    manifest = json.loads(
        (Path(__file__).resolve().parents[1] / "custom_components" / "haismart" / "manifest.json")
        .read_text(encoding="utf-8")
    )
    prefixes = {entry["macaddress"].rstrip("*") for entry in manifest["dhcp"]}

    # confirmed in service on working air conditioners
    for oui in ("ACB722", "24E8CE", "0007A8"):
        assert oui in prefixes, f"{oui} is a known-working appliance OUI"

    # NOT appliances: phones, TVs and a silicon design house. A false positive here would offer a
    # config flow for someone's Haier phone.
    for oui, what in (
        ("C8D779", "Haier Telecom - phones"),
        ("B0A37E", "Haier Telecom - phones"),
        ("DC330D", "Haier Telecom - phones (adjacent to DC330E, which IS appliances)"),
        ("D058C0", "Haier Multimedia - TVs"),
        ("BC2B6B", "Beijing Haier IC Design"),
    ):
        assert oui not in prefixes, f"{oui} ({what}) must not be matched"

    # MA-M assignments: their 24-bit prefixes are shared with unrelated companies, and Home
    # Assistant matches on prefixes, so they cannot be expressed safely.
    for oui in ("1845B3", "1054D2"):
        assert oui not in prefixes, f"{oui} is an MA-M block with a shared 24-bit prefix"

    assert all(len(p) == 6 and p.isalnum() for p in prefixes), prefixes


async def test_manual_entry_keeps_a_supplied_product_code_verbatim(
    hass: HomeAssistant, mock_uss
) -> None:
    """A product code the user actually supplies is stored, trimmed, and not second-guessed.

    The companion case -- that an unsupplied one stays absent rather than defaulting to this
    project's own air conditioner -- is asserted in `test_user_flow_creates_entry`.
    """
    flow_id = await _start_manual(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id, USER_INPUT
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PRODUCT_CODE: "  AAD180E00  "}
    )
    await hass.async_block_till_done()

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PRODUCT_CODE] == "AAD180E00"


async def test_manual_onboarding_looks_up_the_published_model(
    hass: HomeAssistant, mock_uss
) -> None:
    """A hand-configured entry has no cloud credentials, so nothing else can tell it which
    attributes its air conditioner actually has. Where a product code is supplied, the open
    catalogue fills that gap at setup time."""
    from unittest.mock import AsyncMock, patch

    from custom_components.haismart.const import CONF_DIGITAL_MODEL

    published = {
        "attributes": [{"name": "operationMode"}, {"name": "freshAirStatus", "invisible": True}],
        "alarms": [{"name": "F1", "desc": "a fault"}],
    }
    flow_id = await _start_manual(hass)
    with patch(
        "custom_components.haismart.config_flow.get_public_device_config",
        new=AsyncMock(return_value=published),
    ) as fetch:
        result = await hass.config_entries.flow.async_configure(
            flow_id, USER_INPUT
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PRODUCT_CODE: "AAD180E00"}
        )
        await hass.async_block_till_done()

    import json as _json

    assert fetch.await_args.args[0] == "AAD180E00"
    stored = _json.loads(result["data"][CONF_DIGITAL_MODEL])
    assert stored["attributes"][0]["name"] == "operationMode"


async def test_manual_onboarding_does_not_look_up_without_a_product_code(
    hass: HomeAssistant, mock_uss
) -> None:
    """No code, no lookup -- guessing one would fetch another device's model."""
    from unittest.mock import AsyncMock, patch

    from custom_components.haismart.const import CONF_DIGITAL_MODEL

    flow_id = await _start_manual(hass)
    with patch(
        "custom_components.haismart.config_flow.get_public_device_config", new=AsyncMock()
    ) as fetch:
        result = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)
        result = await _past_model_step(hass, result)

    assert fetch.await_count == 0
    assert CONF_DIGITAL_MODEL not in result["data"]


async def test_manual_onboarding_survives_a_failed_lookup(
    hass: HomeAssistant, mock_uss
) -> None:
    """Setting up an air conditioner must not fail because a supplementary lookup did."""
    from unittest.mock import AsyncMock, patch

    from custom_components.haismart.const import CONF_DIGITAL_MODEL

    flow_id = await _start_manual(hass)
    with patch(
        "custom_components.haismart.config_flow.get_public_device_config",
        new=AsyncMock(side_effect=CloudError("no such product code")),
    ):
        result = await hass.config_entries.flow.async_configure(
            flow_id, USER_INPUT
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PRODUCT_CODE: "NOSUCHCODE"}
        )
        await hass.async_block_till_done()

    assert result["type"] == FlowResultType.CREATE_ENTRY   # the entry is still created
    assert result["data"][CONF_PRODUCT_CODE] == "NOSUCHCODE"
    assert CONF_DIGITAL_MODEL not in result["data"]


async def test_a_backed_up_local_key_is_all_an_offline_install_needs(
    hass: HomeAssistant, mock_uss
) -> None:
    """The whole point of the offline path: with the key saved, nothing else needs the network.

    Someone who has their localKey written down should be able to add the appliance with no account,
    no internet, and nothing typed that they cannot read off the unit or its label. That means the
    identity comes from the appliance itself and the rules come from what ships with the
    integration, so this asserts the entire chain in one place -- if any link starts needing the
    cloud again, this fails.
    """
    from unittest.mock import patch

    from haismart_hrdp.udiscovery import DeviceInfo

    from custom_components.haismart.const import (
        CONF_PRODUCT_CODE,
        CONF_REFRESH_TOKEN,
        CONF_UPLUS_ID,
    )

    uplus = "2008610800820324021200118012560000000000000000000000000000000040"
    reported = DeviceInfo(
        device_id="A1B2C3D4E5F6", host="192.168.1.50", uplus_id=uplus, cloud_state=1006
    )

    flow_id = await _start_manual(hass)
    with patch(
        "custom_components.haismart.config_flow.udiscovery.async_query",
        return_value=reported,
    ):
        result = await hass.config_entries.flow.async_configure(
            flow_id,
            {
                CONF_HOST: "192.168.1.50",
                CONF_LOCAL_KEY: LOCAL_KEY,  # the one thing that had to come from the cloud, once
            },
        )
    # the model number off the appliance's label -- not the opaque product code
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PRODUCT_CODE: "HSU-24VRRA03TF"}
    )
    await hass.async_block_till_done()

    assert result["type"] == FlowResultType.CREATE_ENTRY
    data = result["data"]
    assert CONF_REFRESH_TOKEN not in data, "no account credential should be stored"
    # the appliance answered for its own identity: neither of these was typed
    assert data[CONF_DEVICE_ID] == "A1B2C3D4E5F6"
    assert data[CONF_UPLUS_ID] == uplus, "the wire-model key came from the unit, not an account"
    # the label's model number resolved to the code the rules are keyed by
    assert data[CONF_PRODUCT_CODE] == "AAC1UKZ01"

    # and the rules that code unlocks are present without anything having been fetched
    from haismart_hrdp import merge_rules
    from haismart_hrdp.model_rules import rules_for_product

    merged = merge_rules({"attributes": []}, rules_for_product(data[CONF_PRODUCT_CODE]))
    assert len(merged["modifiers"]) == 6
    assert len(merged["alarms"]) == 52
    # `invisible_attributes` is what gates the optional-feature entities; without it a unit is
    # offered controls for hardware it does not have.
    assert len(merged["invisible_attributes"]) == 25


def _reports_uplus_id(uplus: str | None = None):
    """The appliance answering the identification query with a real family identifier.

    The shared fixture reports none, which is the right default (plenty of modules do not), but the
    model shortlist only exists when one is known -- so the tests about it have to say so.
    """
    from unittest.mock import patch

    from haismart_hrdp.udiscovery import DeviceInfo

    return patch(
        "custom_components.haismart.config_flow.udiscovery.async_query",
        return_value=DeviceInfo(
            device_id="A1B2C3D4E5F6",
            host="192.168.1.50",
            uplus_id=uplus
            or "2008610800820324021200118012560000000000000000000000000000000040",
        ),
    )


async def test_the_unit_narrows_the_model_list_and_skipping_is_allowed(
    hass: HomeAssistant, mock_uss
) -> None:
    """The identifier a unit announces names its family, so offer that family's models to choose.

    171 published models is not a question anyone can answer; the couple of dozen sharing this
    unit's own identifier is. And "skip" has to be a real option — without a model the appliance
    still reads and controls, whereas a wrong pick applies another model's rules.
    """
    from custom_components.haismart.const import CONF_PRODUCT_CODE

    flow_id = await _start_manual(hass)
    with _reports_uplus_id():
        result = await hass.config_entries.flow.async_configure(
            flow_id, {CONF_HOST: "192.168.1.50", CONF_LOCAL_KEY: LOCAL_KEY}
        )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "model"

    options = result["data_schema"].schema[CONF_PRODUCT_CODE].config["options"]
    assert "skip" == options[0], "skipping must be offered first, not buried"
    assert "HSU-24VRRA03TF" in options, "the shortlist should hold this family's models"
    assert 2 <= len(options) <= 40, f"a choosable shortlist, got {len(options)}"

    done = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PRODUCT_CODE: "HSU-24VRRA03TF"}
    )
    await hass.async_block_till_done()
    assert done["type"] == FlowResultType.CREATE_ENTRY
    assert done["data"][CONF_PRODUCT_CODE] == "AAC1UKZ01"


async def test_skipping_the_model_still_creates_a_working_entry(
    hass: HomeAssistant, mock_uss
) -> None:
    """No model stored, and deliberately none guessed — no rules locks nothing, which is safe."""
    from custom_components.haismart.const import CONF_PRODUCT_CODE

    flow_id = await _start_manual(hass)
    with _reports_uplus_id():
        result = await hass.config_entries.flow.async_configure(
            flow_id, {CONF_HOST: "192.168.1.50", CONF_LOCAL_KEY: LOCAL_KEY}
        )
    done = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PRODUCT_CODE: "skip"}
    )
    await hass.async_block_till_done()
    assert done["type"] == FlowResultType.CREATE_ENTRY
    assert not done["data"].get(CONF_PRODUCT_CODE)


async def test_the_account_path_stores_the_product_code_it_was_given(
    hass: HomeAssistant, mock_uss
) -> None:
    """Signing in should mean never having to be asked which model this is.

    The device list names the product outright, and this flow already forwards that name when it
    asks for the model's rules -- it just never kept it, so the entry fell back to a built-in
    default that reads exactly like a real code. Nothing downstream can tell those apart, and it is
    the identifier the rules, the fault names and the real feature set are all keyed by.
    """
    from unittest.mock import AsyncMock, patch

    from custom_components.haismart.const import CONF_PRODUCT_CODE

    result = await _drive_login_to_pick(hass, mock_uss, [
        patch("custom_components.haismart.config_flow._async_fetch_localkey",
              new=AsyncMock(return_value=(LOCAL_KEY, 13))),
        patch("custom_components.haismart.config_flow._async_resolve_host",
              new=AsyncMock(return_value="192.168.1.50")),
    ])
    await hass.async_block_till_done()
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PRODUCT_CODE] == "AAC1UKZ01"


async def test_an_appliance_added_by_hand_is_not_offered_again_after_signing_in(
    hass: HomeAssistant, mock_uss
) -> None:
    """Adding by hand and signing in later must not produce two entries for one appliance.

    A realistic order of events: someone sets a unit up from a saved key, then signs in later to get
    automatic key rotation. The picker filters on what is already configured, so the two paths have
    to agree on the identifier — and they only do if a typed MAC is normalised the way a discovered
    one is. Written with separators precisely because that is the form people type them in.
    """
    from contextlib import ExitStack

    flow_id = await _start_manual(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id,
        {
            CONF_HOST: "192.168.1.50",
            CONF_DEVICE_ID: "a1:b2:c3:d4:e5:f6",  # same unit, typed the way a label prints it
            CONF_LOCAL_KEY: LOCAL_KEY,
        },
    )
    result = await _past_model_step(hass, result)
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_DEVICE_ID] == "A1B2C3D4E5F6"

    from unittest.mock import AsyncMock, patch

    from haismart_extractor.cloud import SEA_APP_CREDENTIALS, CloudDevice, HaierCloud
    from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

    (CONF_ACCESS_TOKEN, CONF_CLOUD_CLIENT_ID, _,
     CONF_REFRESH_TOKEN, CONF_ZONE_INFO) = _cloud_consts()
    client = HaierCloud(SEA_APP_CREDENTIALS, "2_FRESH")
    devices = [
        CloudDevice("A1B2C3D4E5F6", "Downstairs", "0201203a", "UPLUS", True,
                    prod_no="AAC1UKZ01"),
        CloudDevice("A1B2C3D4E5F7", "Upstairs", "0201203a", "UPLUS", False,
                    prod_no="AAC1UKZ01"),
    ]
    with ExitStack() as stack:
        for ctx in (
            patch("custom_components.haismart.config_flow._async_login_cloud",
                  new=AsyncMock(return_value=(client, {
                      CONF_REFRESH_TOKEN: "2_RT", CONF_ACCESS_TOKEN: "2_FRESH",
                      CONF_CLOUD_CLIENT_ID: "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
                      CONF_ZONE_INFO: "66"}))),
            patch("custom_components.haismart.config_flow.HaierCloud.list_devices_v2",
                  return_value=devices),
        ):
            stack.enter_context(ctx)
        r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        r = await hass.config_entries.flow.async_configure(
            r["flow_id"], {"next_step_id": "login"}
        )
        picker = await hass.config_entries.flow.async_configure(
            r["flow_id"],
            {CONF_USERNAME: "me@example.com", CONF_PASSWORD: "pw", CONF_ZONE_INFO: "66"},
        )

    # the hand-added one is gone from the list; only the other AC on the account remains
    assert _picker_device_ids(picker) == {"A1B2C3D4E5F7"}


def test_the_scan_prefixes_match_the_manifest_matchers() -> None:
    """One list of MAC prefixes, used twice: to be discovered, and to go looking.

    Home Assistant matches these to surface an appliance on its own; the offline path matches the
    same set to find one before asking for an address. If they drift, the offline scan quietly stops
    seeing a whole product line while discovery still works, which is close to undebuggable.
    """
    import json
    from pathlib import Path

    from custom_components.haismart.const import HAIER_OUIS

    root = Path(__file__).resolve().parents[1] / "custom_components" / "haismart"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert sorted(HAIER_OUIS) == sorted(
        m["macaddress"].rstrip("*").upper() for m in manifest["dhcp"]
    )


async def test_the_offline_path_offers_what_it_finds_instead_of_asking_for_an_address(
    hass: HomeAssistant, mock_uss
) -> None:
    """Nobody should type an IP address for a device sitting on the same network.

    Home Assistant already knows every MAC on the subnet and the appliances answer a key-free
    query, so the address, the device ID and the wire-model identifier are all obtainable before
    anyone is asked anything. All that is left is the key.
    """
    from unittest.mock import AsyncMock, patch

    from haismart_hrdp.udiscovery import DeviceInfo

    from custom_components.haismart.const import CONF_UPLUS_ID

    uplus = "2008610800820324021200118012560000000000000000000000000000000040"
    found = [
        DeviceInfo(device_id="A1B2C3D4E5F6", host="192.168.1.50", uplus_id=uplus),
        DeviceInfo(device_id="A1B2C3D4E5F7", host="192.168.1.51", uplus_id=uplus),
    ]
    with patch(
        "custom_components.haismart.config_flow.async_scan_for_appliances",
        new=AsyncMock(return_value=found),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "manual"}
        )
        assert result["step_id"] == "pick_local"
        assert set(result["data_schema"].schema[CONF_HOST].container) == {
            "192.168.1.50",
            "192.168.1.51",
        }
        # picking settles address + identity; the form that follows only wants the key
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "192.168.1.50"}
        )
        assert result["step_id"] == "manual"
        assert CONF_LOCAL_KEY in result["data_schema"].schema

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "192.168.1.50", CONF_LOCAL_KEY: LOCAL_KEY}
        )
        result = await _past_model_step(hass, result)

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_DEVICE_ID] == "A1B2C3D4E5F6"   # never typed
    assert result["data"][CONF_UPLUS_ID] == uplus             # never typed


async def test_a_known_appliance_is_located_rather_than_re_offered(
    hass: HomeAssistant, mock_uss
) -> None:
    """Do not ask someone to choose an appliance they have already chosen.

    The account path lands on the manual form when it could not fetch a key, and it arrives knowing
    exactly which unit was picked. The network scan should then be used to find that unit's address
    — not to present the whole list again.
    """
    from unittest.mock import AsyncMock, patch

    from haismart_hrdp.udiscovery import DeviceInfo

    found = [
        DeviceInfo(device_id="AABBCCDDEEFF", host="192.168.1.51"),
        DeviceInfo(device_id="A1B2C3D4E5F6", host="192.168.1.50"),  # the one already chosen
    ]
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "zeroconf"}, data=_zeroconf_info()
    )
    assert result["step_id"] == "manual"  # arrives named, from discovery

    with patch(
        "custom_components.haismart.config_flow.async_scan_for_appliances",
        new=AsyncMock(return_value=found),
    ):
        again = await hass.config_entries.flow.async_configure(result["flow_id"], None)

    assert again["step_id"] == "manual", "should not bounce to a picker"
    assert again["data_schema"]({CONF_LOCAL_KEY: LOCAL_KEY})[CONF_HOST] == "192.168.1.50"


async def test_a_cut_off_appliance_explains_why_its_key_could_not_be_fetched(
    hass: HomeAssistant, mock_uss
) -> None:
    """A deliberate block should read as confirmation, not as an unexplained failure.

    Keys are issued to the appliance by the manufacturer's servers, so a unit blocked from the
    internet cannot be given one — and blocking it is the recommended end state here. The unit
    reports its own connectivity for free, so the failure can say which of the two it is.

    Note what this does *not* claim: the sign-in itself succeeded. Blocking the key gateway leaves
    the account endpoints reachable, so telling someone their internet is broken would be wrong.
    """
    from unittest.mock import AsyncMock, patch

    from haismart_extractor import GatewayError
    from haismart_hrdp.udiscovery import DeviceInfo

    cut_off = DeviceInfo(
        device_id="A1B2C3D4E5F6", host="192.168.1.50", cloud_state=1006
    )
    result = await _drive_login_to_pick(hass, mock_uss, [
        patch("custom_components.haismart.config_flow._async_fetch_localkey",
              new=AsyncMock(side_effect=GatewayError("CONNACK rc=5"))),
        patch("custom_components.haismart.config_flow._async_resolve_host",
              new=AsyncMock(return_value="192.168.1.50")),
        patch("custom_components.haismart.config_flow.udiscovery.async_query",
              new=AsyncMock(return_value=cut_off)),
    ])

    assert result["step_id"] == "key_failed"
    note = result["description_placeholders"]["note"]
    assert "cannot reach Haier's servers" in note
    assert "your sign-in worked" in note, "must not blame the account or the network"
    assert "keeps working" in note, "a blocked unit's key is frozen, so an old one is still good"


async def test_a_connected_appliance_gets_no_such_explanation(
    hass: HomeAssistant, mock_uss
) -> None:
    """The unit is online, so its connectivity is not the reason — say nothing rather than guess."""
    from unittest.mock import AsyncMock, patch

    from haismart_extractor import GatewayError

    result = await _drive_login_to_pick(hass, mock_uss, [
        patch("custom_components.haismart.config_flow._async_fetch_localkey",
              new=AsyncMock(side_effect=GatewayError("CONNACK rc=5"))),
        patch("custom_components.haismart.config_flow._async_resolve_host",
              new=AsyncMock(return_value="192.168.1.50")),
    ])
    assert result["step_id"] == "key_failed"
    assert result["description_placeholders"]["note"] == ""


async def test_attaching_an_account_to_a_hand_added_entry_stops_the_key_going_stale(
    hass: HomeAssistant, mock_uss
) -> None:
    """The remedy for "it loses its configuration every restart", and it was untested.

    An appliance still talking to the manufacturer rotates its key several times a day. An entry
    added by hand holds no account credentials, so it cannot re-fetch — the first read after a
    rotation detects the version mismatch, setup is abandoned, and the entities disappear. That
    reads to an owner as losing the configuration, and re-adding by hand only works until the next
    rotation.

    Attaching an account fixes it for good, and must do so **without disturbing what already
    works**: the same appliance, the same key, the same entry — only credentials added.
    """
    from unittest.mock import AsyncMock, patch

    from haismart_extractor.cloud import SEA_APP_CREDENTIALS, HaierCloud
    from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

    from custom_components.haismart.const import (
        CONF_ACCESS_TOKEN,
        CONF_CLOUD_CLIENT_ID,
        CONF_REFRESH_TOKEN,
        CONF_ZONE_INFO,
    )

    entry = _entry()          # a hand-added entry: host + deviceId + key, no account
    entry.add_to_hass(hass)
    assert CONF_REFRESH_TOKEN not in entry.data

    creds = {
        CONF_REFRESH_TOKEN: "2_RT", CONF_ACCESS_TOKEN: "2_FRESH",
        CONF_CLOUD_CLIENT_ID: "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4", CONF_ZONE_INFO: "92",
    }
    with patch(
        "custom_components.haismart.config_flow._async_login_cloud",
        new=AsyncMock(return_value=(HaierCloud(SEA_APP_CREDENTIALS, "2_FRESH"), creds)),
    ):
        result = await entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "reconfigure_cloud"}
        )
        assert result["step_id"] == "reconfigure_cloud"
        done = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: "me@example.com", CONF_PASSWORD: "pw", CONF_ZONE_INFO: "92"},
        )
        await hass.async_block_till_done()

    assert done["type"] == FlowResultType.ABORT
    assert done["reason"] == "reconfigure_successful"
    # the account is now attached, so a rotation can be re-fetched instead of prompting
    assert entry.data[CONF_REFRESH_TOKEN] == "2_RT"
    assert entry.data[CONF_CLOUD_CLIENT_ID] == creds[CONF_CLOUD_CLIENT_ID]
    # and nothing about the working local setup was disturbed
    assert entry.data[CONF_HOST] == "192.168.1.50"
    assert entry.data[CONF_DEVICE_ID] == "A1B2C3D4E5F6"
    assert entry.data[CONF_LOCAL_KEY] == LOCAL_KEY


async def test_the_model_shortlist_is_decompressed_off_the_event_loop(
    hass: HomeAssistant, mock_uss
) -> None:
    """The shortlist comes out of a gzipped bundle, and a first install opens it here.

    The coordinator warms that cache when an entry is set up, but on a first install there is no
    entry yet — this flow is the first thing to touch the bundle. Reading it straight from the step
    decompresses a file on the event loop, which Home Assistant reports as a blocking call against
    this integration. So the warm-up has to happen here too, in an executor.
    """
    from custom_components.haismart import config_flow

    handed_to_executor: list[object] = []
    original = hass.async_add_executor_job

    def _record(target, *args):
        handed_to_executor.append(target)
        return original(target, *args)

    hass.async_add_executor_job = _record
    try:
        flow_id = await _start_manual(hass)
        with _reports_uplus_id():
            result = await hass.config_entries.flow.async_configure(
                flow_id, {CONF_HOST: "192.168.1.50", CONF_LOCAL_KEY: LOCAL_KEY}
            )
    finally:
        hass.async_add_executor_job = original

    assert result["step_id"] == "model"
    # The claim is precisely this: the bundle read was handed to the executor rather than run on
    # the loop. Asserting only that the warm-up "happened" would pass just as well for the inline
    # call that is the bug.
    assert config_flow._preload_model_rules in handed_to_executor


async def test_a_model_number_from_another_region_resolves_through_the_account(
    hass: HomeAssistant, mock_uss
) -> None:
    """The shipped catalogue is one region's, so an owner elsewhere types a number it never knew.

    The catalogue answers according to the dialling code the account registered with, and the
    regions publish very different sets -- the number on the first 209-byte appliance reported here
    resolves to nothing under this project's own region and resolves exactly under its owner's. So a
    number the bundle cannot place is put to the account's own region before being kept verbatim.
    """
    from unittest.mock import AsyncMock, patch

    from haismart_extractor.cloud import CatalogueProduct

    from custom_components.haismart.const import (
        CONF_ACCESS_TOKEN,
        CONF_CLOUD_CLIENT_ID,
        CONF_REFRESH_TOKEN,
        CONF_ZONE_INFO,
    )

    flow_id = await _start_manual(hass)
    flow = hass.config_entries.flow._progress[flow_id]
    flow._cloud_data = {
        CONF_REFRESH_TOKEN: "2_RT",
        CONF_CLOUD_CLIENT_ID: "c" * 32,
        CONF_ACCESS_TOKEN: "T",
        CONF_ZONE_INFO: "92",
    }
    listed = AsyncMock(return_value=[
        CatalogueProduct(product_code="AACVX7E00", model="HSU-24HFAB/013WUSDC(W)-T3")
    ])
    with (
        patch("custom_components.haismart.config_flow.HaierCloud.refresh_token",
              new=AsyncMock(return_value=type("R", (), {"access_token": "T2"})())),
        patch("custom_components.haismart.config_flow.HaierCloud.list_ac_products", new=listed),
    ):
        result = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PRODUCT_CODE: "HSU-24HFAB/013WUSDC(W)-T3"}
        )
        await hass.async_block_till_done()

    assert result["data"][CONF_PRODUCT_CODE] == "AACVX7E00"
    assert listed.await_args.kwargs["model"] == "HSU-24HFAB/013WUSDC(W)-T3"


async def test_a_hand_made_entry_never_reaches_for_the_region_catalogue(
    hass: HomeAssistant, mock_uss
) -> None:
    """No account, no lookup: an offline install keeps whatever the owner typed."""
    from unittest.mock import AsyncMock, patch

    flow_id = await _start_manual(hass)
    with patch(
        "custom_components.haismart.config_flow.HaierCloud.list_ac_products", new=AsyncMock()
    ) as listed:
        result = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PRODUCT_CODE: "HSU-SOMETHING-UNKNOWN"}
        )
        await hass.async_block_till_done()

    assert listed.await_count == 0
    assert result["data"][CONF_PRODUCT_CODE] == "HSU-SOMETHING-UNKNOWN"
