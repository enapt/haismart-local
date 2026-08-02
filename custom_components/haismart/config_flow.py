"""Config flow for Haismart local.

Two ways to add an AC (menu): **login** (email/phone + password) or **manual** (host + deviceId +
localKey). After sign-in, the login path **auto-fetches the localKey — no key paste**: it lists the
account's devices, and for the picked one fetches the digital model + **localKey from the gateway**
and resolves the LAN IP from HA's **DHCP/ARP** data (these units don't announce mDNS), then creates
the entry (asking only for a piece it couldn't get: the key if the gateway fetch failed, or the IP
if HA hasn't seen the AC yet). Control then runs fully local. Validation is a live uSS read, so the
user immediately learns if the AC is reachable (handshake) and whether the key decrypts (biz-data
MD5). The AC's localKey *version* (HELLO_RESP) is stored so the coordinator can detect key rotation
and trigger the `reauth` step here.

Google/Facebook accounts have no password to sign in with: create a throwaway email/password Haier
account, **share your AC(s) to it** in the app, and log in with that account (sharing grants the
same local access as ownership).

Discovery: these units do **NOT** announce `_cae._udp` mDNS, so HA finds them by **DHCP** (deviceId
IS the MAC): a `dhcp` matcher over Haier's appliance OUIs + `async_step_dhcp` surface each AC
prefilled), and the login flow resolves a picked AC's IP from HA's ARP/DHCP data (`aiodiscover`).
The zeroconf step is kept for future firmware. The **manual** menu path is the fully-offline option.
"""
from __future__ import annotations

import json
import logging
from functools import partial
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from haismart_extractor import GatewayCreds, GatewayError, get_localkey_via_gateway
from haismart_extractor.cloud import SEA_APP_CREDENTIALS, CloudError, HaierCloud
from haismart_hrdp import async_read_status, merge_rules, probe_localkey_version
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

try:  # HA >= 2025.2
    from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
except ImportError:  # pragma: no cover - HA < 2025.2
    from homeassistant.components.zeroconf import ZeroconfServiceInfo

if TYPE_CHECKING:
    from homeassistant.components.dhcp import DhcpServiceInfo

from .cloud_transport import async_cloud_transport
from .const import (
    AC_DEVICE_CLASSES,
    CONF_ACCESS_TOKEN,
    CONF_CLOUD_CLIENT_ID,
    CONF_DEVICE_ID,
    CONF_DIGITAL_MODEL,
    CONF_HOST,
    CONF_LOCAL_KEY,
    CONF_LOCALKEY_VERSION,
    CONF_NAME,
    CONF_PRODUCT_CODE,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    CONF_UPLUS_ID,
    CONF_ZONE_INFO,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
    READ_TIMEOUT,
)
from .countries import country_options, default_dial_code
from .discovery import async_resolve_host_arp


class CannotConnect(HomeAssistantError):
    """The AC did not answer the uSS handshake."""


class InvalidAuth(HomeAssistantError):
    """Handshake fine but nothing decrypted — wrong or stale localKey."""


class CloudAuthError(HomeAssistantError):
    """The cloud refreshToken/clientId did not authenticate."""


async def _async_login_cloud(
    username: str, password: str, zone_info: str, *, transport=None
) -> tuple[HaierCloud, dict[str, str]]:
    """Sign in with an email/phone + password (reproduces the app's account login); return a ready
    client + creds to store. ``zone_info`` is the account's country/region zone (the phone
    country code — e.g. 66 Thailand, 65 Singapore); it routes the account lookup, so a wrong value
    gives "account not registered". We choose the CLIENTID at login (no mismatch); the durable
    refreshToken is what we persist. Social logins (Google/Facebook) have no password — share the AC
    to a throwaway email/password account and log in with that instead.

    ``transport`` MUST be HA's shared-client transport (:func:`async_cloud_transport`): the
    library's own default would construct an httpx client, and that loads the CA bundle from disk —
    blocking I/O on the event loop, which HA reports as a bug."""
    zone = zone_info.strip() or "0"
    try:
        client, result = await HaierCloud.login(
            SEA_APP_CREDENTIALS,
            username.strip(),
            password,
            zone_info=zone,
            transport=transport,
        )
    except (CloudError, OSError, RuntimeError, TimeoutError) as err:
        raise CloudAuthError(str(err)) from err
    if not result.refresh_token:
        raise CloudAuthError("login succeeded but returned no refresh token")
    return client, {
        CONF_REFRESH_TOKEN: result.refresh_token,
        CONF_ACCESS_TOKEN: result.access_token,
        CONF_CLOUD_CLIENT_ID: result.client_id,
        # prefer the zone the server echoes back; fall back to what we sent
        CONF_ZONE_INFO: str(result.raw.get("zoneInfo") or zone),
    }


def _manual_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """The manual (fully-offline) form: host + deviceId + localKey (+ optional name / product)."""
    d = defaults or {}
    # localKey is intentionally never prefilled; everything else is retained across an error re-show
    name = {"default": d[CONF_NAME]} if d.get(CONF_NAME) else {}
    return vol.Schema({
        vol.Required(CONF_HOST, default=d.get(CONF_HOST, vol.UNDEFINED)): str,
        vol.Required(CONF_DEVICE_ID, default=d.get(CONF_DEVICE_ID, vol.UNDEFINED)): str,
        vol.Required(CONF_LOCAL_KEY): str,
        vol.Optional(CONF_NAME, **name): str,
        # Left blank unless the device's own is known. Filling in a default here would store one
        # air conditioner's product code against another's, and nothing downstream could tell the
        # difference -- it is the identifier a model, its rules and its real feature set are all
        # looked up by, so a wrong one is worse than none.
        vol.Optional(CONF_PRODUCT_CODE, default=d.get(CONF_PRODUCT_CODE, "")): str,
    })


def _clean_key(local_key: str) -> str:
    """Validate the localKey shape (32-char hex used as ASCII — case is significant)."""
    key = local_key.strip()
    if len(key) != 32:
        raise ValueError("localKey must be 32 hex chars")
    bytes.fromhex(key)  # ValueError -> not hex
    return key


async def _async_validate(hass, host: str, device_id: str, local_key: str) -> int:
    """Live-validate against the AC; return its current localKey version."""
    try:
        version = await hass.async_add_executor_job(
            partial(probe_localkey_version, host, device_id, timeout=READ_TIMEOUT)
        )
        blobs = await async_read_status(host, device_id, local_key, timeout=READ_TIMEOUT)
    except (OSError, RuntimeError, TimeoutError) as err:
        raise CannotConnect(str(err)) from err
    if not blobs:
        # handshake succeeded but every biz payload failed the MD5 integrity check
        raise InvalidAuth("localKey does not decrypt the AC's status pushes")
    return version


# Socket timeout for the cloud MQTT-gateway localKey fetch (TLS connect + one round-trip).
GATEWAY_TIMEOUT = 8.0


async def _async_fetch_localkey(
    hass, cloud_data: dict[str, str], device_id: str
) -> tuple[str, int]:
    """Fetch the device's current localKey from the cloud MQTT gateway so the user never pastes it.

    Every CONNECT credential is derived from the account tokens (clientId, username/password), like
    the coordinator's rotation path. Returns ``(key, version)``; raises on any failure so the caller
    can fall back to manual key entry. Same "cloud fetches the key" pattern LocalTuya uses."""
    creds = GatewayCreds.derive(
        usdk_client_id=cloud_data[CONF_CLOUD_CLIENT_ID],
        access_token=cloud_data[CONF_ACCESS_TOKEN],
    )
    local_key = await hass.async_add_executor_job(
        partial(get_localkey_via_gateway, creds, device_id, timeout=GATEWAY_TIMEOUT)
    )
    return local_key.key, local_key.version


async def _async_resolve_host(hass, device_id: str, timeout: float = 1.5) -> str | None:
    """Best-effort: find the AC's current LAN IP so the user needn't type it.

    These units do NOT announce ``_cae._udp`` mDNS, so we map the **deviceId (= MAC)** to an IP via
    HA's own DHCP/ARP library (``aiodiscover`` — what the ``dhcp`` component uses).
    mDNS is still tried first (cheap, harmless; a future unit/firmware may announce). Returns the IP
    or ``None`` -> the flow then asks for the host."""
    ip = await _async_resolve_host_mdns(hass, device_id, timeout)
    return ip or await async_resolve_host_arp(device_id)


async def _async_resolve_host_mdns(hass, device_id: str, timeout: float) -> str | None:
    try:
        from homeassistant.components import zeroconf as ha_zeroconf
        from zeroconf.asyncio import AsyncServiceInfo

        aiozc = await ha_zeroconf.async_get_async_instance(hass)
        info = AsyncServiceInfo("_cae._udp.local.", f"{device_id}._cae._udp.local.")
        if await info.async_request(aiozc.zeroconf, int(timeout * 1000)):
            for addr in info.parsed_addresses():
                return addr
    except Exception:  # noqa: BLE001 - best-effort convenience, never fatal
        return None
    return None


_LOGGER = logging.getLogger(__name__)


def _login_error_for(err: Exception) -> str:
    """Map a Haier sign-in failure to the error that names its ACTUAL cause.

    ``30032`` is emitted both for an account that genuinely does not exist and for one looked up in
    the wrong region, and the region is the only part of the form a user cannot simply re-read off
    their password manager -- so it gets its own message rather than a generic three-way shrug.
    """
    text = str(err)
    if "30032" in text:
        return "account_not_in_region"
    if "10001" in text:
        return "missing_field"
    return "cloud_auth"


def _device_label(device: Any) -> str:
    """Label a device for the picker, flagging anything that is not an air conditioner.

    Haier's `deviceType` encodes the appliance class in its first byte as hex, so a fridge or an air
    purifier on the same account is identifiable. Such devices are still listed rather than
    hidden --
    the class map may be incomplete, and hiding a unit the user can see in the app would be worse
    than warning about it -- but they are clearly marked so nobody picks one expecting it to work.
    """
    name = device.name or device.device_id
    label = f"{name} ({device.device_id})"
    cls = (getattr(device, "device_type", "") or "")[:2].lower()
    if cls and cls not in AC_DEVICE_CLASSES:
        return f"{label} - not an air conditioner, unsupported"
    return label


class HaismartConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._discovered: dict[str, str] = {}
        self._cloud_data: dict[str, str] = {}
        self._devices: list[Any] = []
        self._picked: Any = None
        self._cloud: HaierCloud | None = None
        self._local_key: str | None = None
        self._localkey_version: int | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose how to add the AC: email/password sign-in, or fully manual."""
        return self.async_show_menu(step_id="user", menu_options=["login", "manual"])

    async def async_step_login(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Sign in with your Haismart **email/phone + password**, then pick a device.

        Only for accounts that have a password — Google/Facebook sign-ins have none, so share the AC
        to a throwaway email/password account and log in with that instead. The country selects the
        account's dialling-code zone, which routes the account lookup. localKey is pulled locally
        after."""
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}
        if user_input is not None:
            zone = str(user_input.get(CONF_ZONE_INFO, "")).strip().lstrip("+")
            try:
                self._cloud, self._cloud_data = await _async_login_cloud(
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                    zone,
                    transport=async_cloud_transport(self.hass),
                )
            except CloudAuthError as err:
                # Do not collapse every sign-in failure into "check all three fields". The region is
                # the one the user cannot look up, and Haier reports a right-password-wrong-region
                # attempt as 30032 "account is not registered" - which reads as "wrong password".
                errors["base"] = _login_error_for(err)
                placeholders = {"username": user_input[CONF_USERNAME], "zone": zone}
            except (CloudError, OSError, RuntimeError, TimeoutError) as err:
                # Reached only from list_devices_v2 below in the original code; kept distinct
                # because
                # sign-in itself already succeeded by this point.
                _LOGGER.debug("cloud sign-in transport failure: %s", err)
                errors["base"] = "cannot_connect_cloud"
            else:
                try:
                    self._devices = await self._cloud.list_devices_v2()
                except (CloudError, OSError, RuntimeError, TimeoutError) as err:
                    # Signed in fine; the DEVICE LIST failed. Telling the user to check
                    # credentials
                    # that were just proven correct sends them in exactly the wrong direction.
                    _LOGGER.warning("signed in, but the device list failed: %s", err)
                    errors["base"] = "cannot_connect_cloud"
                    placeholders = {"error": str(err)[:120]}
                else:
                    if self._devices:
                        return await self.async_step_pick_device()
                    # Sign-in SUCCEEDED and the account simply has no devices. Re-showing the form
                    # as an error invites the user to retype credentials forever and throws away the
                    # tokens we just obtained; this is a terminal state, so abort and say why.
                    return self.async_abort(
                        reason="no_devices",
                        description_placeholders={"username": user_input[CONF_USERNAME]},
                    )
        default_zone = default_dial_code(self.hass.config.country)
        zone_field = (
            vol.Required(CONF_ZONE_INFO, default=default_zone)
            if default_zone
            else vol.Required(CONF_ZONE_INFO)
        )
        return self.async_show_form(
            step_id="login",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    zone_field: SelectSelector(
                        SelectSelectorConfig(
                            options=country_options(),
                            mode=SelectSelectorMode.DROPDOWN,
                            # a code that is not in the list can still be typed
                            custom_value=True,
                        )
                    ),
                }
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_pick_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick which of the account's devices to add; then set it up hands-off (no pasting).

        One AC = one config entry, added one at a time. Devices already configured are filtered out,
        so a second run only shows the ACs you haven't added yet (and it stops cleanly once they are
        all in). Adding several = repeat: sign in, pick the next one."""
        configured = self._async_current_ids()
        available = [d for d in self._devices if d.device_id.upper() not in configured]
        if not available:
            return self.async_abort(reason="all_configured")
        if user_input is not None:
            picked = next(
                (d for d in available if d.device_id == user_input[CONF_DEVICE_ID]), None
            )
            if picked is not None:
                # Persist the uPlusId (device-list wifiType) — the precise wire-model key, so the
                # decoder need not fall back to keying on report length. Absent on older list
                # responses, which is fine (length keying still works).
                if getattr(picked, "uplus_id", ""):
                    self._cloud_data[CONF_UPLUS_ID] = picked.uplus_id
                self._picked = picked
                return await self._async_setup_cloud_device(picked.device_id, picked.name)
        choices = {d.device_id: f"{d.name or d.device_id} ({d.device_id})" for d in available}
        return self.async_show_form(
            step_id="pick_device",
            data_schema=vol.Schema({vol.Required(CONF_DEVICE_ID): vol.In(choices)}),
        )

    async def _async_add_device_rules(self, model: dict[str, Any]) -> dict[str, Any]:
        """``model`` plus the parts the device shadow leaves out.

        What a device hands out through the shadow is its attributes and their current values. The
        rules — which settings it ignores in which state, which settings must travel together, and
        the fault list those rules refer to — are published separately, per model. Without them the
        integration offers controls a unit will discard.

        Best effort: a unit whose model is not published, or a lookup that fails, keeps the shadow
        exactly as it came, which is what every install had before this.
        """
        picked = self._picked
        if self._cloud is None or picked is None or not (
            getattr(picked, "model", "") and getattr(picked, "uplus_id", "")
        ):
            return model
        try:
            published = await self._cloud.get_device_config(
                picked.model, picked.uplus_id,
                prod_no=getattr(picked, "prod_no", "") or "",
                device_type=getattr(picked, "device_type", "") or "",
            )
        except (CloudError, OSError, RuntimeError, TimeoutError, ValueError) as err:
            _LOGGER.debug("no published model rules for %s: %s", picked.model, err)
            return model
        merged = merge_rules(model, published)
        _LOGGER.debug(
            "model rules for %s: %d modifier(s), %d constraint(s)", picked.model,
            len(merged.get("modifiers") or ()), len(merged.get("constraints") or ()),
        )
        return merged

    async def _async_setup_cloud_device(
        self, device_id: str, name: str | None
    ) -> ConfigFlowResult:
        """After sign-in, stand up a device hands-off: pull its digital model + localKey from the
        cloud and resolve its LAN IP via mDNS — so nothing is pasted. Falls back gracefully (to the
        manual key form / a host prompt) if the cloud fetch or mDNS resolve can't complete."""
        await self.async_set_unique_id(device_id.upper())
        self._abort_if_unique_id_configured()
        self._discovered[CONF_DEVICE_ID] = device_id
        if name:
            self._discovered[CONF_NAME] = name
        # digital model so the profile is correct for ANY model (best-effort)
        if self._cloud is not None:
            try:
                model = await self._cloud.get_digital_model(device_id)
                model = await self._async_add_device_rules(model)
                self._cloud_data[CONF_DIGITAL_MODEL] = json.dumps(model)
            except (CloudError, OSError, RuntimeError, TimeoutError, ValueError) as err:
                # degrades the profile and the write validation, so it should not be invisible
                _LOGGER.warning("could not fetch the digital model for %s: %s", device_id, err)
        # localKey from the cloud gateway — the whole point: no paste
        try:
            self._local_key, self._localkey_version = await _async_fetch_localkey(
                self.hass, self._cloud_data, device_id
            )
        except (GatewayError, KeyError, OSError, RuntimeError, TimeoutError) as err:
            # was silently swallowed, so neither the user nor the log knew anything had gone wrong
            _LOGGER.warning("could not fetch the localKey for %s: %s", device_id, err)
            self._local_key = None
        # resolve the LAN IP from mDNS so the user needn't type it either
        if not self._discovered.get(CONF_HOST):
            host = await _async_resolve_host(self.hass, device_id)
            if host:
                self._discovered[CONF_HOST] = host
        return await self._async_finish_or_ask_host()

    async def _async_finish_or_ask_host(self) -> ConfigFlowResult:
        """Create the entry when host + auto-fetched key are both known; otherwise ask for just the
        missing piece (the key, if the gateway fetch failed; else only the LAN IP)."""
        if self._local_key is None:
            return await self.async_step_key_failed()
        if self._discovered.get(CONF_HOST):
            try:
                return await self._async_create_from_state()
            except InvalidAuth:
                # The host answered; the KEY is what is wrong. Keep the resolved IP -- discarding it
                # made the next form come up blank and look like discovery had failed too.
                return await self.async_step_key_failed()
            except CannotConnect:
                self._discovered.pop(CONF_HOST, None)  # that IP didn't validate -> ask for one
        return await self.async_step_host()

    async def _async_create_from_state(self) -> ConfigFlowResult:
        """Validate host + the auto-fetched key live and create the entry.

        Raises ``CannotConnect`` or ``InvalidAuth`` rather than collapsing both to ``None``. They
        need opposite responses: a bad host should re-ask for the IP, while a key that does not
        decrypt means the IP was fine all along -- and reporting that on the IP form sent people off
        checking their subnet and rebooting their router.
        """
        host = self._discovered[CONF_HOST]
        device_id = self._discovered[CONF_DEVICE_ID]
        assert self._local_key is not None
        version = await _async_validate(self.hass, host, device_id, self._local_key)
        return self.async_create_entry(
            title=self._discovered.get(CONF_NAME) or f"Haier {device_id}",
            data={
                CONF_HOST: host,
                CONF_DEVICE_ID: device_id,
                CONF_LOCAL_KEY: self._local_key,
                CONF_LOCALKEY_VERSION: self._localkey_version or version,
                **self._cloud_data,
            },
        )

    async def async_step_key_failed(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The automatic key fetch failed, or the fetched key does not decrypt.

        Previously this dropped the user straight onto the manual form -- which asks for a 32-hex
        localKey, right after `pick_device` promised they would not have to paste anything, and
        which they have no way to obtain by hand. That is a dead end. Offer a retry first: the
        fetch is attempted exactly once against an 8s timeout, and transient failures are common.
        """
        return self.async_show_menu(
            step_id="key_failed", menu_options=["key_retry", "manual"]
        )

    async def async_step_key_retry(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Try the cloud key fetch once more, then continue as normal."""
        device_id = self._discovered[CONF_DEVICE_ID]
        try:
            self._local_key, self._localkey_version = await _async_fetch_localkey(
                self.hass, self._cloud_data, device_id
            )
        except (GatewayError, KeyError, OSError, RuntimeError, TimeoutError) as err:
            _LOGGER.warning("retrying the localKey fetch for %s failed: %s", device_id, err)
            self._local_key = None
            return await self.async_step_key_failed()
        return await self._async_finish_or_ask_host()

    async def async_step_host(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask only for the AC's LAN IP (when mDNS couldn't find it). The key is already fetched."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._discovered[CONF_HOST] = user_input[CONF_HOST].strip()
            try:
                return await self._async_create_from_state()
            except InvalidAuth:
                # the IP is right; the key is the problem, so do not blame this form for it
                return await self.async_step_key_failed()
            except CannotConnect:
                errors["base"] = "cannot_connect"
        return self.async_show_form(
            step_id="host",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_HOST, default=self._discovered.get(CONF_HOST, vol.UNDEFINED)
                    ): str
                }
            ),
            errors=errors,
            description_placeholders={
                "device": self._discovered.get(CONF_NAME)
                or self._discovered.get(CONF_DEVICE_ID, "")
            },
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            device_id = user_input[CONF_DEVICE_ID].strip()
            await self.async_set_unique_id(device_id.upper())
            self._abort_if_unique_id_configured(updates={CONF_HOST: host})
            try:
                local_key = _clean_key(user_input[CONF_LOCAL_KEY])
                version = await _async_validate(self.hass, host, device_id, local_key)
            except ValueError:
                errors["base"] = "invalid_key"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:
                title = user_input.get(CONF_NAME) or f"Haier {device_id}"
                return self.async_create_entry(
                    title=title,
                    data={
                        CONF_HOST: host,
                        CONF_DEVICE_ID: device_id,
                        CONF_LOCAL_KEY: local_key,
                        **(
                            {CONF_PRODUCT_CODE: product_code}
                            if (product_code := (user_input.get(CONF_PRODUCT_CODE) or "").strip())
                            else {}
                        ),
                        CONF_LOCALKEY_VERSION: version,
                        **self._cloud_data,  # from the login discovery path, if any
                    },
                )

        return self.async_show_form(
            step_id="manual",
            data_schema=_manual_schema({**self._discovered, **(user_input or {})}),
            errors=errors,
        )

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """The module announces `<deviceId>._cae._udp.local.` — prefill host + deviceId."""
        device_id = discovery_info.name.split(".")[0].upper()
        host = str(discovery_info.host)
        if not device_id:
            return self.async_abort(reason="unknown")
        await self.async_set_unique_id(device_id)
        # keep a reconfigured AC's host current when DHCP moves it
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})
        self._discovered = {CONF_HOST: host, CONF_DEVICE_ID: device_id}
        self.context["title_placeholders"] = {"device_id": device_id}
        return await self.async_step_manual()

    async def async_step_dhcp(
        self, discovery_info: DhcpServiceInfo
    ) -> ConfigFlowResult:
        """DHCP-discovered on the LAN (the deviceId **is** the module's MAC): the sanctioned
        to find units that don't announce mDNS. Prefills host + deviceId (the manual step then
        just needs the key; or use the login menu path for the key too)."""
        device_id = format_mac(discovery_info.macaddress).replace(":", "").upper()
        host = discovery_info.ip
        if not device_id:
            return self.async_abort(reason="unknown")
        await self.async_set_unique_id(device_id)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})  # follow a DHCP host move
        self._discovered = {CONF_HOST: host, CONF_DEVICE_ID: device_id}
        self.context["title_placeholders"] = {"device_id": device_id}
        return await self.async_step_manual()

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change an existing AC's settings without deleting and re-adding it.

        This did not exist, yet the stale-key repair told users to "reconfigure the device with your
        Haismart account" -- so the only actual route was delete-and-re-add, losing history, entity
        ids and every automation referencing them.
        """
        entry = self._get_reconfigure_entry()
        options = ["reconfigure_host"]
        if not entry.data.get(CONF_REFRESH_TOKEN):
            # only worth offering when it would actually change something
            options.append("reconfigure_cloud")
        return self.async_show_menu(step_id="reconfigure", menu_options=options)

    async def async_step_reconfigure_host(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Point an existing entry at a new IP, validating BEFORE committing.

        Re-running the manual flow with the same device id also updates the host, but it does so
        before validating, so a typo silently took a working entry offline while reporting only
        "already configured".
        """
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            try:
                version = await _async_validate(
                    self.hass, host, entry.data[CONF_DEVICE_ID], entry.data[CONF_LOCAL_KEY]
                )
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={CONF_HOST: host, CONF_LOCALKEY_VERSION: version},
                )
        return self.async_show_form(
            step_id="reconfigure_host",
            data_schema=vol.Schema(
                {vol.Required(CONF_HOST, default=entry.data.get(CONF_HOST)): str}
            ),
            errors=errors,
        )

    async def async_step_reconfigure_cloud(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Attach Haier account credentials to an entry added by hand.

        This is what the stale-key repair has always advised: with account credentials stored, a
        server-side key rotation is re-fetched automatically instead of prompting for a key the user
        cannot obtain.
        """
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}
        if user_input is not None:
            zone = str(user_input.get(CONF_ZONE_INFO, "")).strip().lstrip("+")
            try:
                _cloud, cloud_data = await _async_login_cloud(
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                    zone,
                    transport=async_cloud_transport(self.hass),
                )
            except CloudAuthError as err:
                errors["base"] = _login_error_for(err)
                placeholders = {"username": user_input[CONF_USERNAME], "zone": zone}
            except (CloudError, OSError, RuntimeError, TimeoutError) as err:
                _LOGGER.warning("attaching cloud credentials failed: %s", err)
                errors["base"] = "cannot_connect_cloud"
            else:
                return self.async_update_reload_and_abort(entry, data_updates=cloud_data)
        default_zone = default_dial_code(self.hass.config.country)
        zone_field = (
            vol.Required(CONF_ZONE_INFO, default=default_zone)
            if default_zone
            else vol.Required(CONF_ZONE_INFO)
        )
        return self.async_show_form(
            step_id="reconfigure_cloud",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    zone_field: SelectSelector(
                        SelectSelectorConfig(
                            options=country_options(),
                            mode=SelectSelectorMode.DROPDOWN,
                            custom_value=True,
                        )
                    ),
                }
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """The localKey rotated. Offer to re-fetch it rather than only demanding it.

        Reauth is reached only AFTER an automatic gateway refresh has already failed, and the most
        likely reason is an expired refreshToken -- which signing in again fixes instantly. Asking
        solely for a 32-hex key demands a value the user has no way to produce.
        """
        return self.async_show_menu(
            step_id="reauth", menu_options=["reauth_cloud", "reauth_confirm"]
        )

    async def async_step_reauth_cloud(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Sign in again and re-fetch this AC's key automatically."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}
        if user_input is not None:
            zone = str(user_input.get(CONF_ZONE_INFO, "")).strip().lstrip("+")
            device_id = entry.data[CONF_DEVICE_ID]
            try:
                _cloud, cloud_data = await _async_login_cloud(
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                    zone,
                    transport=async_cloud_transport(self.hass),
                )
                local_key, version = await _async_fetch_localkey(
                    self.hass, cloud_data, device_id
                )
            except CloudAuthError as err:
                errors["base"] = _login_error_for(err)
                placeholders = {"username": user_input[CONF_USERNAME], "zone": zone}
            except (CloudError, GatewayError, KeyError, OSError, RuntimeError, TimeoutError) as err:
                _LOGGER.warning("re-fetching the localKey for %s failed: %s", device_id, err)
                errors["base"] = "cannot_connect_cloud"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_LOCAL_KEY: local_key,
                        CONF_LOCALKEY_VERSION: version,
                        **cloud_data,
                    },
                )
        default_zone = default_dial_code(self.hass.config.country)
        zone_field = (
            vol.Required(CONF_ZONE_INFO, default=default_zone)
            if default_zone
            else vol.Required(CONF_ZONE_INFO)
        )
        return self.async_show_form(
            step_id="reauth_cloud",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    zone_field: SelectSelector(
                        SelectSelectorConfig(
                            options=country_options(),
                            mode=SelectSelectorMode.DROPDOWN,
                            custom_value=True,
                        )
                    ),
                }
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                local_key = _clean_key(user_input[CONF_LOCAL_KEY])
                version = await _async_validate(
                    self.hass, entry.data[CONF_HOST], entry.data[CONF_DEVICE_ID], local_key
                )
            except ValueError:
                errors["base"] = "invalid_key"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_LOCAL_KEY: local_key,
                        CONF_LOCALKEY_VERSION: version,
                    },
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_LOCAL_KEY): str}),
            description_placeholders={CONF_DEVICE_ID: entry.data[CONF_DEVICE_ID]},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> HaismartOptionsFlow:
        return HaismartOptionsFlow()


class HaismartOptionsFlow(OptionsFlow):
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SCAN_INTERVAL,
                            # a bare integer box had no ceiling and no unit affordance
                            max=600,
                            step=5,
                            unit_of_measurement="s",
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
        )
