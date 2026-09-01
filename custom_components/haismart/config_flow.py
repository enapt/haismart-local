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
from dataclasses import replace
from functools import partial
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from haismart_extractor import GatewayCreds, GatewayError, get_localkey_via_gateway
from haismart_extractor.cloud import (
    SEA_APP_CREDENTIALS,
    CloudConnectionError,
    CloudError,
    HaierCloud,
    get_public_device_config,
)
from haismart_hrdp import (
    async_read_status,
    invisible_attributes,
    merge_rules,
    probe_localkey_version,
    udiscovery,
)
from haismart_hrdp.model_rules import (
    known_products,
    models_for_uplus_id,
    product_for_model,
)
from haismart_hrdp.model_rules import (
    preload as _preload_model_rules,
)
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
    CONF_DEVICE_TYPE,
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
    UDISCOVERY_TIMEOUT,
)
from .countries import country_options, default_dial_code
from .discovery import async_find_host, async_scan_for_appliances


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


# Offered as the first dropdown entry so "I do not know" is a visible choice rather than a blank
# field. Without a model the unit still reads and controls; only the rule layer is missing.
_MODEL_SKIP = "skip"


def _manual_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """The manual (fully-offline) form: where the appliance is, and the key to talk to it.

    Deliberately two questions. The device ID is not one of them, because the appliance answers
    that itself -- one key-free query to the host returns it, along with the identifier that
    selects the wire map -- so it is optional, and filled in only when a module stays silent.

    The model is not asked here either. It is a real question with a real answer, but a free-text
    product code is not how to ask it: the follow-up step offers the shortlist the appliance's own
    family implies, in model numbers off the label.
    """
    d = defaults or {}
    # localKey is intentionally never prefilled; everything else is retained across an error re-show
    name = {"default": d[CONF_NAME]} if d.get(CONF_NAME) else {}
    return vol.Schema({
        vol.Required(CONF_HOST, default=d.get(CONF_HOST, vol.UNDEFINED)): str,
        # Optional, and usually left alone: the appliance answers this itself. Kept in the schema
        # rather than shown conditionally because a conditional field is not merely hidden -- the
        # form then *rejects* anyone who supplies it, including the discovery paths that prefill it.
        vol.Optional(CONF_DEVICE_ID, default=d.get(CONF_DEVICE_ID, "")): str,
        vol.Required(CONF_LOCAL_KEY): str,
        vol.Optional(CONF_NAME, **name): str,
    })


def _clean_device_id(device_id: str) -> str:
    """Normalise a device ID to the one form every path stores it in.

    It is the module's MAC, and people write MACs with colons, dashes or nothing at all. Discovery
    strips separators; a typed one used not to, so the same appliance added by hand and later found
    through an account would not be recognised as already configured -- the picker would offer it
    again and a second entry would appear for one unit, both polling it.
    """
    return "".join(c for c in device_id if c.isalnum()).upper()


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


def _describe_key_failure(err: Exception) -> str:
    """One line naming why the key could not be fetched, safe to put in front of a user.

    The type is kept as well as the message because the messages alone are thin -- "timed out" says
    nothing about which of the two hosts timed out, while the class does. Nothing here carries a
    credential: these are timeouts, connection errors, and the gateway's own refusals (a return
    code, a missing acknowledgement, a device that was not answered for).
    """
    text = str(err).strip() or err.__class__.__name__
    if isinstance(err, TimeoutError) or "timed out" in text.lower():
        return (
            f"{err.__class__.__name__}: {text} — no answer from Haier's key service. It is "
            "reachable from most networks but not all; a firewall, a DNS filter or an ISP block "
            "will all look like this."
        )
    if isinstance(err, KeyError):
        # a missing field in the reply, which reads as a bare quoted name and explains nothing
        return f"the reply was missing {text}, so no key could be read from it"
    return f"{err.__class__.__name__}: {text}"


async def _async_resolve_host(hass, device_id: str, timeout: float = 1.5) -> str | None:
    """Best-effort: find the AC's current LAN IP so the user needn't type it.

    Three ways, cheapest first, and each is tried only because the one before it came up empty:

    mDNS first -- these units do NOT announce ``_cae._udp``, so it is only for a future firmware
    that might, and it costs nothing. Then :func:`async_find_host`, which maps the **deviceId
    (= MAC)** through Home Assistant's own DHCP/ARP data and, when that comes up empty, asks the
    network directly with a UDISCOVERY broadcast.

    ⚠️ It must be ``async_find_host`` and not the appliance scan the offline form uses. That scan
    answers "which appliances are out there", and it **returns as soon as the ARP sweep yields any
    of them** -- so on a subnet where ARP knows one unit and not another, it hands back a list that
    simply does not contain the one being looked for, and never reaches its broadcast -- so an
    appliance at a perfectly reachable address still produces the "what is its IP?" form.
    ``async_find_host`` is asking about one device, so a miss falls through to the broadcast, which
    is the step that does not depend on ARP having been right.

    Returns the IP, or ``None`` -> the flow then asks for the host after all.
    """
    ip = await _async_resolve_host_mdns(hass, device_id, timeout)
    return ip or await async_find_host(hass, device_id)


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
    # A transport failure that reached here wrapped as an auth error is not a credential problem:
    # the server never answered, so "check your email and password" sends the user the wrong way.
    # `_async_login_cloud` re-raises the original as the cause, so the connection case is a type
    # test, not a string sniff -- a genuine rejection always carries a retCode instead.
    if isinstance(getattr(err, "__cause__", None), (CloudConnectionError, TimeoutError, OSError)):
        return "cannot_connect_cloud"
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
        # carried between the manual form and the model-confirmation step that follows it
        self._pending_manual: dict[str, Any] = {}
        self._model_choices: dict[str, str] = {}
        # appliances found on the LAN; None until the scan has run, [] if it found none
        self._found: list[Any] | None = None
        self._cloud_data: dict[str, str] = {}
        self._devices: list[Any] = []
        self._picked: Any = None
        self._cloud: HaierCloud | None = None
        self._local_key: str | None = None
        self._localkey_version: int | None = None
        # an account held by another entry has been tried for this appliance already (once is enough
        # -- it is a network round trip, and every path below funnels through the manual form)
        self._account_tried = False
        # set when a stored account turned out to be dead, so the sign-in form opens saying so
        self._login_error: str | None = None
        # why the key fetch failed, shown on the step that reports it. A failure here is otherwise
        # visible only in the log, and the people it happens to are the least likely to be able to
        # produce one -- setup has not finished, so there is no device, no diagnostics download and
        # nothing to point at. Two very different faults look identical without it: a setup that
        # never got as far as asking for a key, and one that asked and was refused.
        self._key_error: str | None = None

    def _stored_accounts(
        self, exclude_entry_id: str | None = None
    ) -> list[dict[str, str]]:
        """Every distinct set of account credentials the configured appliances hold.

        An account is a property of the *owner*, not of one air conditioner, but it is stored per
        entry because that is where the tokens have to live for each coordinator to refresh its own
        key. So a second appliance being added has, sitting right there, everything needed to fetch
        its key without anyone signing in again -- and until now nothing looked.

        All of them, not just the newest: two Haier accounts in one Home Assistant is unusual but
        entirely legitimate -- a household where the appliances were bought and registered
        separately -- and under a single-account assumption exactly one of them would keep being
        asked for a key that the other account could not have supplied anyway.

        Newest first, on the same reasoning as the zone default: the most recent sign-in is the one
        whose tokens are most likely still live. Deduplicated by terminal, since several appliances
        added in one sitting all carry the same pair.

        ``exclude_entry_id`` skips an entry whose own credentials have just been tried and failed,
        so that a re-key attempt reaches for a genuinely different one rather than repeating itself.
        """
        out: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for entry in reversed(self.hass.config_entries.async_entries(DOMAIN)):
            if entry.entry_id == exclude_entry_id:
                continue
            data = entry.data
            if not (data.get(CONF_REFRESH_TOKEN) and data.get(CONF_CLOUD_CLIENT_ID)):
                continue
            token = (str(data[CONF_CLOUD_CLIENT_ID]), str(data[CONF_REFRESH_TOKEN]))
            if token in seen:
                continue
            seen.add(token)
            out.append({
                CONF_REFRESH_TOKEN: token[1],
                CONF_CLOUD_CLIENT_ID: token[0],
                CONF_ACCESS_TOKEN: str(data.get(CONF_ACCESS_TOKEN) or ""),
                CONF_ZONE_INFO: str(data.get(CONF_ZONE_INFO) or "0"),
            })
        return out

    def _stored_cloud_data(self, exclude_entry_id: str | None = None) -> dict[str, str] | None:
        """The most recently stored account, for the callers that only need to know there is one."""
        accounts = self._stored_accounts(exclude_entry_id)
        return accounts[0] if accounts else None

    async def _async_cloud_from_stored(
        self, data: dict[str, str]
    ) -> HaierCloud | None:
        """A signed-in client built from stored credentials, or ``None`` if they no longer work.

        The access token is re-minted from the durable refreshToken rather than reused: access
        tokens expire in about a day, so a stored one is usually dead while the refreshToken beside
        it is fine. This is the same exchange the coordinator performs before every key refresh.
        """
        try:
            cloud = HaierCloud(
                replace(SEA_APP_CREDENTIALS, client_id=data[CONF_CLOUD_CLIENT_ID]),
                data.get(CONF_ACCESS_TOKEN) or "",
                zone_info=data.get(CONF_ZONE_INFO, "0"),
                # HA's shared httpx client: building one here would load the CA bundle from disk,
                # which is blocking I/O on the event loop
                transport=async_cloud_transport(self.hass),
            )
            cloud.access_token = (
                await cloud.refresh_token(data[CONF_REFRESH_TOKEN])
            ).access_token
        except (CloudError, KeyError, OSError, RuntimeError, TimeoutError, ValueError) as err:
            _LOGGER.debug("the stored account did not authenticate: %s", err)
            return None
        return cloud

    async def _async_adopt_stored_account(self, device_id: str) -> bool:
        """Arm this flow with an account another appliance already holds, for ``device_id``.

        This is what stops the second air conditioner being treated as though its owner had never
        signed in. Discovery hands over a device ID and an address and nothing else, so the offline
        form used to ask for a localKey -- a 32-hex secret with no way to obtain it by hand -- from
        someone whose account was already configured and could have fetched it outright. Reported as
        issue #9: one unit added through sign-in, the other clicked in the Discovered box, and only
        the second one asks.

        Returns ``True`` when the caller should continue down the account path. The appliance must
        actually be on the account: a key is issued per device, so a unit the account does not own
        would only fail slower, and taking the answer from a device list is also how the model, the
        product code and the wire-model identifier arrive. A device list that cannot be reached is
        the one case where the fetch is still attempted -- the credentials may be fine and the
        listing merely unlucky, and the key request is the authority on that.
        """
        self._account_tried = True
        wanted = _clean_device_id(device_id)
        for stored in self._stored_accounts():
            cloud = await self._async_cloud_from_stored(stored)
            if cloud is None:
                continue
            self._cloud = cloud
            self._cloud_data = {**stored, CONF_ACCESS_TOKEN: cloud.access_token}
            try:
                self._devices = await cloud.list_devices_v2()
            except (CloudError, OSError, RuntimeError, TimeoutError) as err:
                _LOGGER.debug("stored account signed in, but the device list failed: %s", err)
                return True
            picked = next(
                (d for d in self._devices if _clean_device_id(d.device_id) == wanted), None
            )
            if picked is None:
                self._cloud = None
                self._cloud_data = {}
                self._devices = []
                continue
            self._picked = picked
            self._absorb_picked(picked)
            if picked.name:
                self._discovered[CONF_NAME] = picked.name
            _LOGGER.info(
                "using the Haier account already configured to set up %s -- no key needed",
                device_id,
            )
            return True
        _LOGGER.debug(
            "%s is not on any account already configured; asking for its key instead", device_id
        )
        return False

    def _absorb_picked(self, picked: Any) -> None:
        """Keep the identifiers the device list hands over: they are not derivable from anything
        else, and each one that is dropped leaves the entry guessing at something it was told.

        * ``uplus_id`` selects the wire map, so the decoder need not key on report length;
        * ``device_type`` names the variant a uPlusId can only give the class of;
        * ``prod_no`` is the product code the rules, the fault names and the real feature set are
          all keyed by -- dropping it leaves a built-in default that looks exactly like a real one.
        """
        for attr, key in (
            ("uplus_id", CONF_UPLUS_ID),
            ("device_type", CONF_DEVICE_TYPE),
            ("prod_no", CONF_PRODUCT_CODE),
        ):
            if value := getattr(picked, attr, ""):
                self._cloud_data[key] = value

    async def _async_share_after_login(
        self, cloud: HaierCloud, creds: dict[str, str]
    ) -> None:
        """Hand the credentials a fresh sign-in just issued to the account's other appliances.

        Needs the device list to prove which entries are on this account, and that is the only
        reason it makes a request -- so it does not make one when no other entry holds an account
        to supersede, which is the ordinary single-appliance install.

        Best effort throughout, and deliberately catching everything: this runs inside a step whose
        actual job is to repair an appliance, and a courtesy update to its neighbours failing must
        never be what turns that repair into an error message.
        """
        if not any(
            e.data.get(CONF_REFRESH_TOKEN) for e in self.hass.config_entries.async_entries(DOMAIN)
        ):
            return
        try:
            devices = await cloud.list_devices_v2()
        except Exception as err:  # noqa: BLE001 - courtesy only; never fatal to the caller
            _LOGGER.debug("could not list devices to share the new credentials: %s", err)
            return
        self._async_share_account(devices, creds)

    @callback
    def _async_share_account(self, devices: list[Any], creds: dict[str, str]) -> None:
        """Give every already-configured appliance on this account the tokens just issued.

        Signing in mints a **fresh per-install CLIENTID** and binds the new token to it, so an
        account that signs in again is, to the manufacturer, a different terminal. Entries created
        before that hold the previous pair, and nothing was updating them -- so adding a second air
        conditioner by signing in again could leave the first one unable to refresh its key, which
        surfaces as it suddenly asking for one. Sharing the new credentials across the account's
        entries removes the possibility whether or not the old terminal is actually revoked.

        Membership is proven, not assumed: an entry is only updated if its appliance is on the
        device list this sign-in just returned. Nothing else identifies an entry's account, and
        writing one account's tokens into another's entry would be far worse than leaving it alone.
        """
        owned = {_clean_device_id(d.device_id) for d in devices}
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            data = entry.data
            if _clean_device_id(str(data.get(CONF_DEVICE_ID, ""))) not in owned:
                continue
            if not data.get(CONF_REFRESH_TOKEN):
                continue  # a hand-made entry: it never had an account, and gains nothing here
            if all(data.get(k) == v for k, v in creds.items()):
                continue
            _LOGGER.debug("updating %s with the credentials just issued", entry.title)
            self.hass.config_entries.async_update_entry(entry, data={**data, **creds})

    def _zone_from_signed_in_account(self) -> str | None:
        """The region a previously added appliance's account reported, if there is one.

        Stored at sign-in from the server's own answer, so on a second appliance it is known
        rather than guessed. Newest entry first.
        """
        for entry in reversed(self.hass.config_entries.async_entries(DOMAIN)):
            if entry.data.get(CONF_REFRESH_TOKEN) and (zone := entry.data.get(CONF_ZONE_INFO)):
                return str(zone)
        return None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose how to add the AC: email/password sign-in, or fully manual.

        An owner who has already signed in is offered that account first, and adding their next
        appliance costs them nothing at all -- no password, no key. Signing in again would work too,
        but it is strictly worse: it mints a second terminal identity for one account, which is the
        thing :meth:`_async_share_account` exists to contain.
        """
        options = ["login", "manual"]
        if self._stored_cloud_data() is not None:
            options.insert(0, "account")
        return self.async_show_menu(step_id="user", menu_options=options)

    async def async_step_account(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add another appliance using the account already configured, without signing in again."""
        stored = self._stored_cloud_data()
        cloud = await self._async_cloud_from_stored(stored) if stored else None
        if stored is None or cloud is None:
            # Do not dead-end and do not pretend: send them to the sign-in form with the reason.
            # The stored refreshToken is durable but not eternal, and it is also what a sign-in
            # elsewhere can invalidate.
            self._login_error = "account_expired"
            return await self.async_step_login()
        self._cloud = cloud
        self._cloud_data = {**stored, CONF_ACCESS_TOKEN: cloud.access_token}
        try:
            self._devices = await self._cloud.list_devices_v2()
        except (CloudError, OSError, RuntimeError, TimeoutError) as err:
            _LOGGER.warning("the configured account's device list failed: %s", err)
            self._login_error = "account_expired"
            return await self.async_step_login()
        if not self._devices:
            # Its own reason, not the sign-in path's: that one names the account just typed, and
            # there is no name to give here -- "Signed in as , but..." is how a placeholder that
            # has nothing to say reads to a user.
            return self.async_abort(reason="account_no_devices")
        self._async_share_account(self._devices, self._cloud_data)
        return await self.async_step_pick_device()

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
                        # This sign-in issued a new terminal identity; hand it to every appliance
                        # already configured on the same account before going on, so none of them
                        # is left holding the superseded one.
                        self._async_share_account(self._devices, self._cloud_data)
                        return await self.async_step_pick_device()
                    # Sign-in SUCCEEDED and the account simply has no devices. Re-showing the form
                    # as an error invites the user to retype credentials forever and throws away the
                    # tokens we just obtained; this is a terminal state, so abort and say why.
                    return self.async_abort(
                        reason="no_devices",
                        description_placeholders={"username": user_input[CONF_USERNAME]},
                    )
        # An account we already held turned out not to work, and this form is the fix. Say that,
        # rather than opening a blank sign-in form for no visible reason.
        if self._login_error and not errors:
            errors["base"] = self._login_error
            self._login_error = None
        # Prefer the region an account already signed in reported for itself. The server states it
        # at sign-in and it is stored, so on a second appliance the answer is known -- and it beats
        # Home Assistant's country, which says where the installation is rather than where the
        # account was registered. Nothing about the region can be discovered without it: no cloud
        # call answers, so the first sign-in has to ask.
        default_zone = self._zone_from_signed_in_account() or default_dial_code(
            self.hass.config.country
        )
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
        available = [
            d for d in self._devices if _clean_device_id(d.device_id) not in configured
        ]
        if not available:
            return self.async_abort(reason="all_configured")
        if user_input is not None:
            picked = next(
                (d for d in available if d.device_id == user_input[CONF_DEVICE_ID]), None
            )
            if picked is not None:
                self._absorb_picked(picked)
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
        # ⚠️ raise_on_progress=False, and the reason is the whole bug it fixes. These appliances are
        # announced by DHCP, so Home Assistant creates a discovery flow for one the moment it sees
        # it, and that flow sits in the Discovered box holding this very unique ID. Someone who
        # then goes Add Integration -> sign in -> pick their air conditioner would have their
        # sign-in aborted with "this air conditioner is already being set up", leaving the pending
        # card -- which asks for a local key they have no way to obtain -- as the only route they
        # can finish. The two symptoms look unrelated and are the same cause.
        #
        # A person deliberately adding this appliance outranks a card nobody has touched. Nothing
        # is lost by yielding: on success Home Assistant aborts every other in-progress flow
        # carrying the same unique ID, so the stale card clears itself. The discovery steps keep
        # the default, which is what stops two announcements of one appliance racing each other.
        await self.async_set_unique_id(_clean_device_id(device_id), raise_on_progress=False)
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
            self._key_error = _describe_key_failure(err)
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
                self._key_error = (
                    "the key fetched from your account did not decrypt this appliance's replies "
                    "(it answered, so the address is right)"
                )
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
        # Ask the appliance whether it can still reach the manufacturer, because that answers
        # "why did this fail" outright. Keys are issued by those servers *to the appliance*, so a
        # unit that is cut off cannot be given one -- and the most common reason for it to be cut
        # off is that its owner arranged it. Saying so turns an unexplained failure into a
        # confirmation that the deliberate thing worked.
        note = ""
        host = self._discovered.get(CONF_HOST)
        if host and (info := await self._async_query_device(host)) is not None:
            if info.cloud_connected is False:
                note = (
                    "\n\nThis air conditioner reports that it cannot reach Haier's servers. Keys "
                    "are issued to the unit by those servers, so one cannot be fetched while it is "
                    "cut off — your sign-in worked, and nothing else is wrong. If you blocked the "
                    "unit from the internet on purpose, that is expected: use a key you saved "
                    "earlier. A blocked unit's key stops changing, so an old one keeps working."
                )
        if self._key_error:
            note += (
                "\n\n**When the key was requested, this came back:**\n\n"
                f"```\n{self._key_error}\n```\n\n"
                "That names the cause. Please quote it if you report this — setup has not "
                "finished, so there are no diagnostics to attach, and it is the one thing that "
                "would otherwise exist only in the log."
            )
        return self.async_show_menu(
            step_id="key_failed",
            menu_options=["key_retry", "manual"],
            description_placeholders={"note": note},
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
            self._key_error = _describe_key_failure(err)
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

    async def _async_public_model(self, product_code: str) -> dict[str, Any] | None:
        """The device's published model, looked up by product code with no account. Supplemental.

        A hand-configured entry has no cloud credentials, so nothing else can tell it which
        attributes its air conditioner actually has -- and without that it gets no conditional
        availability and none of the optional-feature entities, because those must be able to tell a
        real feature from one a generic model merely lists. A catalogue keyed on product code
        answers for any device without a token, so where a code is known this fills that gap.

        Only ever additive. A code that is unknown, a catalogue that cannot be reached, or anything
        else going wrong leaves the entry exactly as it would have been -- setting up an air
        conditioner must not fail because a supplementary lookup did. And nothing is attempted
        without a code the user actually supplied: guessing one would fetch another device's model,
        which is worse than having none.
        """
        if not product_code:
            return None
        try:
            model = await get_public_device_config(
                product_code, transport=async_cloud_transport(self.hass)
            )
        except (CloudError, OSError, RuntimeError, TimeoutError, ValueError) as err:
            _LOGGER.debug("no published model for product code %s: %s", product_code, err)
            return None
        if model.get("attributes"):
            # Record which attributes this unit does not actually have. A generic model
            # over-declares -- it lists everything the product line might carry and marks the rest
            # invisible -- and the optional-feature entities refuse to appear at all unless that
            # set is known, because guessing produces sensors for hardware that is not fitted.
            # Only a published model carries the flag, and this IS one, so the offline install is
            # entitled to the same feature set an account gives it. Without this the model was
            # stored with the flags still on each attribute and nothing ever read them across.
            model["invisible_attributes"] = sorted(invisible_attributes(model))
        return model

    async def _async_region_product_code(self, model: str) -> str | None:
        """The product code for a model number, from **this account's own region catalogue**.

        The shipped catalogue is one region's. That is not a shortcoming of the sweep behind it but
        a property of the endpoint: it answers according to the dialling code the account registered
        with, and the regions publish different -- sometimes wildly different -- sets. So a model
        number that resolves to nothing here may be perfectly well published for the owner asking,
        and they are exactly the person whose account can ask.

        Needs the credentials the login path collected; returns ``None`` for a hand-made entry, an
        unreachable catalogue, or a number no region knows, in every case leaving the answer the
        owner typed to stand as it did before.
        """
        data = self._cloud_data
        if not (data.get(CONF_REFRESH_TOKEN) and data.get(CONF_CLOUD_CLIENT_ID)):
            return None
        try:
            cloud = HaierCloud(
                replace(SEA_APP_CREDENTIALS, client_id=data[CONF_CLOUD_CLIENT_ID]),
                data.get(CONF_ACCESS_TOKEN) or "",
                zone_info=data.get(CONF_ZONE_INFO, "0"),
                transport=async_cloud_transport(self.hass),
            )
            cloud.access_token = (
                await cloud.refresh_token(data[CONF_REFRESH_TOKEN])
            ).access_token
            rows = await cloud.list_ac_products(model=model)
        except (CloudError, KeyError, OSError, RuntimeError, TimeoutError, ValueError) as err:
            _LOGGER.debug("region catalogue lookup failed for %r: %s", model, err)
            return None
        wanted = model.strip().upper()
        matched = {r.product_code for r in rows if r.model.strip().upper() == wanted}
        if len(matched) > 1:
            # The same refusal the offline lookup makes, for the same reason: a model number can
            # name several products, and where it does there is nothing here to choose between
            # them. All 21 colliding numbers have their products in the same region as each other
            # -- 1408 (number, region) pairs across 70 regions -- so returning the first row would
            # be a coin toss between rule sets, which is what this layer exists to prevent.
            _LOGGER.info(
                "model %s names %d products in this account's region (%s); leaving the product "
                "unset so the rules its family agrees on are applied instead",
                model, len(matched), ", ".join(sorted(matched)),
            )
            return None
        if matched:
            code = next(iter(matched))
            _LOGGER.info(
                "model %s is published in this account's region as product %s", model, code
            )
            return code
        return None

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        # Never ask for a key we could fetch. Every route that ends at this form -- discovery, the
        # network scan's picker, the menu -- arrives knowing which appliance it is, and an owner who
        # has signed in for one air conditioner can have the key for the next one without being
        # asked anything. Tried once per flow, and skipped when this flow signed in itself: it holds
        # a better account than any stored one, and if its fetch failed, repeating it here would
        # only fail again more slowly.
        if (
            user_input is None
            and not self._account_tried
            and not self._cloud_data.get(CONF_REFRESH_TOKEN)
            and (known := self._discovered.get(CONF_DEVICE_ID))
            and await self._async_adopt_stored_account(known)
        ):
            return await self._async_setup_cloud_device(
                known, self._discovered.get(CONF_NAME)
            )
        # Before asking for an address, look for one. Home Assistant already knows every MAC on the
        # subnet, the appliance's device ID *is* its MAC, and the appliances answer a key-free query
        # -- so on the ordinary network the address, the device ID and the wire-model identifier can
        # all be had without anyone typing anything. Only ever runs once per flow, and only when
        # nothing has been prefilled by a discovery path that already knew.
        if (
            user_input is None
            and not self._discovered.get(CONF_HOST)
            and self._found is None
        ):
            self._found = await async_scan_for_appliances(self.hass)
            wanted = self._discovered.get(CONF_DEVICE_ID)
            if wanted:
                # We already know which appliance this is -- the account path lands here when it
                # could not fetch a key, and the discovery paths arrive named. Use the scan to find
                # *that* one's address rather than asking someone to choose all over again from a
                # list they have already chosen from.
                match = next(
                    (
                        d
                        for d in self._found
                        if _clean_device_id(d.device_id) == _clean_device_id(wanted)
                    ),
                    None,
                )
                if match is not None:
                    self._discovered[CONF_HOST] = match.host
                    if match.uplus_id.strip("0"):
                        self._cloud_data.setdefault(CONF_UPLUS_ID, match.uplus_id)
            elif self._found:
                return await self.async_step_pick_local()
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            device_id = _clean_device_id(user_input.get(CONF_DEVICE_ID) or "")
            # Ask the unit who it is before asking the person. One key-free UDP query returns the
            # deviceId and the uPlusId -- the identifier that selects the wire map -- so a manual
            # install ends up as precisely keyed as one set up through an account, and the owner
            # types neither. Only the localKey is genuinely secret and genuinely unavailable here.
            reported = await self._async_query_device(host)
            if reported is not None:
                device_id = device_id or _clean_device_id(reported.device_id)
                if reported.uplus_id.strip("0"):
                    self._cloud_data.setdefault(CONF_UPLUS_ID, reported.uplus_id)
            if not device_id:
                # The appliance did not answer, so the field appears now -- with the reason -- and
                # not before, when it would only have looked like a required unknown.
                errors["base"] = "device_id_required"
                return self.async_show_form(
                    step_id="manual",
                    data_schema=_manual_schema({**self._discovered, **user_input}),
                    errors=errors,
                )
            # Same reasoning as the account path: a pending Discovered card holds this unique ID,
            # and someone typing an address in deliberately must not be turned away by it.
            await self.async_set_unique_id(device_id, raise_on_progress=False)
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
                self._pending_manual = {
                    CONF_HOST: host,
                    CONF_DEVICE_ID: device_id,
                    CONF_LOCAL_KEY: local_key,
                    CONF_LOCALKEY_VERSION: version,
                    CONF_NAME: user_input.get(CONF_NAME) or f"Haier {device_id}",
                }
                # Which model this is gets its own step -- asked once, where the answer can be
                # offered as a shortlist rather than typed blind. Except when it is already known:
                # a signed-in install has been told outright by the device list, and this path is
                # also where that flow lands when it needs a key or an address from the user. Never
                # ask for something already answered better.
                if self._cloud_data.get(CONF_PRODUCT_CODE):
                    self._pending_manual[CONF_PRODUCT_CODE] = self._cloud_data[
                        CONF_PRODUCT_CODE
                    ]
                    return await self._async_finish_manual()
                # The shortlist is read out of a gzipped bundle. On a first install nothing has
                # opened it yet -- the coordinator's own warm-up only runs once an entry exists --
                # so decompressing it here would be blocking I/O on the event loop. Warm it in an
                # executor first; a no-op every time after.
                await self.hass.async_add_executor_job(_preload_model_rules)
                # Narrowed by region as well as by family. The family identifier alone no longer
                # gives a shortlist -- it reaches 186 products now that the bundle spans every
                # region -- but the products published where this owner lives are a couple of dozen
                # of those. The region comes from the account when there is one and from Home
                # Assistant's own country setting when there is not, so an offline install gets the
                # short list too; an unknown region falls back to the whole family rather than to
                # nothing.
                self._model_choices = models_for_uplus_id(
                    self._cloud_data.get(CONF_UPLUS_ID),
                    self._cloud_data.get(CONF_ZONE_INFO)
                    or default_dial_code(self.hass.config.country),
                )
                return await self.async_step_model()

        return self.async_show_form(
            step_id="manual",
            data_schema=_manual_schema({**self._discovered, **(user_input or {})}),
            errors=errors,
        )

    async def _async_finish_manual(self) -> ConfigFlowResult:
        """Create the entry from what the manual path gathered, model answered or skipped."""
        pending = self._pending_manual
        product_code = pending.get(CONF_PRODUCT_CODE) or ""
        model = await self._async_public_model(product_code)
        return self.async_create_entry(
            title=pending[CONF_NAME],
            data={
                CONF_HOST: pending[CONF_HOST],
                CONF_DEVICE_ID: pending[CONF_DEVICE_ID],
                CONF_LOCAL_KEY: pending[CONF_LOCAL_KEY],
                **({CONF_PRODUCT_CODE: product_code} if product_code else {}),
                **({CONF_DIGITAL_MODEL: json.dumps(model)} if model else {}),
                CONF_LOCALKEY_VERSION: pending[CONF_LOCALKEY_VERSION],
                **self._cloud_data,  # from the login discovery path, if any
            },
        )

    async def async_step_model(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm which model this is, from the shortlist the appliance's own identifier implies.

        The identifier a unit announces names its *family*, not its model -- ours is shared by 23
        products -- and rules are published per product, so something has to choose between them.
        Asking is the honest way, but only if the question is answerable: a shortlist of model
        numbers as printed on the label is, and a free-text product code is not.

        Skipping is a first-class answer. Without a model the unit still reads and controls
        completely; what is lost is fault names, conditional availability and the optional-feature
        list. Guessing on the owner's behalf would trade that for a real risk of applying another
        model's rules, and no rules locks nothing, which is the safe direction.
        """
        if user_input is not None:
            picked = (user_input.get(CONF_PRODUCT_CODE) or "").strip()
            if picked and picked != _MODEL_SKIP:
                # The dropdown accepts typing as well as choosing, so an answer can arrive three
                # ways: a model number from the shortlist, a model number that is not on it (the
                # family identifier was missing or the appliance is newer than the shipped list),
                # or a product code from someone who knows it. Resolve all three, and keep an
                # unrecognised answer verbatim rather than discarding it -- it is still the best
                # information anyone has about this unit, and a wrong lookup is not improved by
                # forgetting the input.
                resolved = self._model_choices.get(picked) or product_for_model(picked)
                if not resolved and picked in known_products():
                    resolved = picked
                if not resolved:
                    # ...and a fourth way: the appliance is published in a region the shipped
                    # catalogue does not cover. That catalogue is scoped by the account's own
                    # dialling code, so a signed-in install can ask *its* region -- which is where
                    # the model number of an appliance from another one actually lives. Without
                    # this, an owner types the number off their label and it resolves to nothing.
                    resolved = await self._async_region_product_code(picked)
                self._pending_manual[CONF_PRODUCT_CODE] = resolved or picked
            return await self._async_finish_manual()
        return self.async_show_form(
            step_id="model",
            data_schema=vol.Schema({
                vol.Optional(CONF_PRODUCT_CODE, default=_MODEL_SKIP): SelectSelector(
                    SelectSelectorConfig(
                        options=[_MODEL_SKIP, *sorted(self._model_choices)],
                        mode=SelectSelectorMode.DROPDOWN,
                        custom_value=True,
                    )
                ),
            }),
        )

    async def async_step_pick_local(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose from the appliances found on this network, so no address need be typed.

        Each entry here has already identified itself, so picking one settles the address, the
        device ID and the wire-model identifier at once -- everything the offline path needs except
        the key, which is the one thing no appliance will hand over.

        Units already configured are left out. If that empties the list the flow goes to the form
        rather than aborting: someone may be adding a unit this scan could not see.
        """
        configured = self._async_current_ids()
        available = [
            d
            for d in (self._found or [])
            if _clean_device_id(d.device_id) not in configured
        ]
        if not available:
            return await self.async_step_manual(None)
        if user_input is not None:
            picked = next(
                (d for d in available if d.host == user_input[CONF_HOST]), None
            )
            if picked is not None:
                self._discovered = {
                    CONF_HOST: picked.host,
                    CONF_DEVICE_ID: _clean_device_id(picked.device_id),
                }
                if picked.uplus_id.strip("0"):
                    self._cloud_data.setdefault(CONF_UPLUS_ID, picked.uplus_id)
            return await self.async_step_manual(None)
        return self.async_show_form(
            step_id="pick_local",
            data_schema=vol.Schema({
                vol.Required(CONF_HOST): vol.In(
                    {d.host: f"{d.device_id} ({d.host})" for d in available}
                ),
            }),
        )

    async def _async_query_device(self, host: str):
        """Ask a host who it is, key-free, or ``None`` if it does not answer.

        Never raises and never blocks the form: a module that stays silent, or a host that is not
        one of these appliances at all, simply leaves the person to fill the field in. The query
        needs no localKey and no account, which is the whole reason it belongs here -- it is the one
        piece of identity available before anything has been authenticated.
        """
        if not host:
            return None
        try:
            return await udiscovery.async_query(host, timeout=UDISCOVERY_TIMEOUT)
        except (OSError, RuntimeError, TimeoutError, ValueError) as err:
            _LOGGER.debug("no discovery answer from %s: %s", host, err)
            return None

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """The module announces `<deviceId>._cae._udp.local.` — prefill host + deviceId."""
        device_id = _clean_device_id(discovery_info.name.split(".")[0])
        host = str(discovery_info.host)
        if not device_id:
            return self.async_abort(reason="unknown")
        await self.async_set_unique_id(device_id)
        # keep a reconfigured AC's host current when DHCP moves it
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})
        self._discovered = {CONF_HOST: host, CONF_DEVICE_ID: device_id}
        self.context["title_placeholders"] = {"device_id": device_id}
        return await self._async_discovered(device_id)

    async def async_step_dhcp(
        self, discovery_info: DhcpServiceInfo
    ) -> ConfigFlowResult:
        """DHCP-discovered on the LAN (the deviceId **is** the module's MAC): the sanctioned way
        to find units that don't announce mDNS. Prefills host + deviceId, and fetches the key from
        an account already configured so that nothing at all is asked for."""
        device_id = _clean_device_id(format_mac(discovery_info.macaddress))
        host = discovery_info.ip
        if not device_id:
            return self.async_abort(reason="unknown")
        await self.async_set_unique_id(device_id)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})  # follow a DHCP host move
        self._discovered = {CONF_HOST: host, CONF_DEVICE_ID: device_id}
        self.context["title_placeholders"] = {"device_id": device_id}
        return await self._async_discovered(device_id)

    async def _async_discovered(self, device_id: str) -> ConfigFlowResult:
        """An appliance found on the network: ask nothing of an owner whose account can answer.

        ⚠️ Both discovery steps run on their own, the moment a matching appliance is seen -- nobody
        has clicked anything yet, and what they return is what becomes the card in Home Assistant's
        Discovered box. So this must always put a form in front of the owner. Returning the created
        entry from here instead would add every Haier appliance on the network silently, including
        ones somebody deliberately left out.

        Which form depends on what we can answer for them. Discovery knows an address and a device
        ID, which is everything except the one secret; an owner who has signed in already has that
        secret available to them, so asking for it is asking for something we could simply fetch --
        and it is unobtainable by hand, which makes the question a dead end rather than an
        inconvenience (issue #9). With an account, the card leads to a confirmation and nothing
        else. Without one, it leads to the offline form exactly as it always has.
        """
        if self._stored_cloud_data() is not None:
            return await self.async_step_discovery_confirm()
        return await self.async_step_manual()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm a discovered appliance whose key an account already configured can fetch."""
        device_id = self._discovered[CONF_DEVICE_ID]
        if user_input is None:
            return self.async_show_form(
                step_id="discovery_confirm",
                description_placeholders={
                    CONF_DEVICE_ID: device_id,
                    CONF_HOST: self._discovered.get(CONF_HOST, ""),
                },
            )
        # The account is only reached for now: it may have expired between the card appearing and
        # this click, and the offline form is the fallback then, as everywhere else.
        if await self._async_adopt_stored_account(device_id):
            return await self._async_setup_cloud_device(
                device_id, self._discovered.get(CONF_NAME)
            )
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
                # Same sign-in, same consequence for everyone else on the account.
                await self._async_share_after_login(_cloud, cloud_data)
                return self.async_update_reload_and_abort(entry, data_updates=cloud_data)
        # The region an account already reported for itself beats Home Assistant's country, which
        # says where the installation is rather than where the account was registered. Measured
        # confirmed: the server does NOT resolve this -- signing in with the wrong dialling code
        # fails as "account is not registered" -- so on a re-authentication, where an account is by
        # definition already configured, offering anything but its own zone invites the one failure
        # whose message points at the password.
        default_zone = (
            self._zone_from_signed_in_account() or default_dial_code(self.hass.config.country)
        )
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

        Before asking anything, try another appliance's account. This is not a repeat of the
        refresh that just failed: signing in mints a per-install terminal identity and binds the
        token to it, so a sibling entry holds genuinely different credentials -- and if the reason
        this entry's stopped working is that a later sign-in superseded them, the sibling is
        holding the very credentials that replaced them. That makes this the case it repairs best,
        and it repairs it without the owner seeing anything at all.
        """
        entry = self._get_reauth_entry()
        device_id = entry.data[CONF_DEVICE_ID]
        for stored in self._stored_accounts(exclude_entry_id=entry.entry_id):
            cloud = await self._async_cloud_from_stored(stored)
            if cloud is None:
                continue
            creds = {**stored, CONF_ACCESS_TOKEN: cloud.access_token}
            try:
                local_key, version = await _async_fetch_localkey(self.hass, creds, device_id)
            except (GatewayError, KeyError, OSError, RuntimeError, TimeoutError) as err:
                _LOGGER.debug(
                    "another appliance's account could not re-key %s either: %s", device_id, err
                )
                continue
            _LOGGER.info(
                "re-keyed %s from the account another appliance holds; nothing to ask", device_id
            )
            return self.async_update_reload_and_abort(
                entry,
                data_updates={
                    CONF_LOCAL_KEY: local_key,
                    CONF_LOCALKEY_VERSION: version,
                    **creds,
                },
            )
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
                # This sign-in superseded the terminal every other appliance on the account is
                # using. Repairing one air conditioner must not be what breaks the next.
                await self._async_share_after_login(_cloud, cloud_data)
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
        # The region an account already reported for itself beats Home Assistant's country, which
        # says where the installation is rather than where the account was registered. Measured
        # confirmed: the server does NOT resolve this -- signing in with the wrong dialling code
        # fails as "account is not registered" -- so on a re-authentication, where an account is by
        # definition already configured, offering anything but its own zone invites the one failure
        # whose message points at the password.
        default_zone = (
            self._zone_from_signed_in_account() or default_dial_code(self.hass.config.country)
        )
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
