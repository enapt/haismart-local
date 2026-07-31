"""Polling coordinator built on the uSS read cycle.

Each refresh is one short-lived uSS session (hello handshake -> the AC pushes its status ->
close), exactly the flow verified live on the real ACs. Polling is the RIGHT fit, not a fallback:
the AC has a fixed ~17s session cap anchored to the handshake (not an idle timer — a keepalive
does not extend it), so it is built for short request/response sessions, not held-open ones. And a
write self-confirms — the AC returns its updated state on the op's own connection (the protocol
§2.1). So polling only exists to catch out-of-band changes (physical remote / the app).

A stale localKey is SILENT at the transport level — the handshake still succeeds and only the
biz-data MD5 check fails, so a read cycle just yields no decodable status. To tell rotation
apart from a transient miss, after consecutive empty cycles we probe the AC's current localKey
version (key-free) and compare it with the version recorded at config time; a mismatch raises
ConfigEntryAuthFailed so HA starts a reauth flow for the new key.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from functools import partial
from typing import Any

from haismart_extractor import (
    GatewayCreds,
    GatewayError,
    HaierCloud,
    get_localkey_via_gateway,
)
from haismart_extractor.cloud import SEA_APP_CREDENTIALS, CloudError
from haismart_hrdp import (
    GRSETDAC_FIELDS,
    GRSETDAC_MODEL_AUTHORIZED,
    STATUS_LAYOUTS,
    AttributeProfile,
    WireModel,
    async_read_status,
    async_send_op,
    build_epp_frame,
    extended_status_epp_frame,
    grsetdac_baseline_from_status,
    grsetdac_op_frame,
    model_enum_codes,
    parse_extended_status,
    parse_full_status,
    probe_localkey_version,
    profile_for,
    profile_from_device_config,
    read_grsetdac_field,
    select_wire_model,
    set_grsetdac_field,
    udiscovery,
    validate_write,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .cloud_transport import async_cloud_transport
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_CLOUD_CLIENT_ID,
    CONF_DEVICE_ID,
    CONF_DIGITAL_MODEL,
    CONF_GATEWAY_USERNAME,
    CONF_HOST,
    CONF_LOCAL_KEY,
    CONF_LOCALKEY_VERSION,
    CONF_PRODUCT_CODE,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    CONF_UPLUS_ID,
    CONF_ZONE_INFO,
    DEFAULT_PRODUCT_CODE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EXTENDED_MISSES,
    ISSUE_STALE_LOCALKEY,
    ISSUE_UNKNOWN_LAYOUT,
    READ_TIMEOUT,
    REDISCOVER_COOLDOWN,
    TELEMETRY_MAX_AGE,
    UDISCOVERY_INTERVAL,
    UDISCOVERY_MISSES,
    UDISCOVERY_RETIRE_INTERVAL,
    UDISCOVERY_TIMEOUT,
    WRITE_TIMEOUT,
)
from .discovery import async_find_host

# Socket timeout for the cloud MQTT-gateway localKey fetch (TLS connect + one round-trip).
GATEWAY_TIMEOUT = 8.0

_LOGGER = logging.getLogger(__name__)

type HaismartConfigEntry = ConfigEntry["HaismartCoordinator"]

# Empty read cycles tolerated before probing the AC's localKey version for rotation.
_MISSES_BEFORE_PROBE = 2

# Caps on the undecodable-frame debug log (the known reports are 125/127 bytes, so this keeps whole
# frames while bounding the damage if some other device pushes something large).
_LOG_FRAME_BYTES = 192
_LOG_FRAME_MAX = 3

# Distinct status reports kept while a layout is unrecognised, for the layout proposals in
# diagnostics. Three states is what it takes to tell candidate maps apart; more adds little.
_RECENT_REPORTS = 3


# A control op carries raw EPP values; the digital model describes each attribute in STD values.
# For fields that map 1:1 to a model attribute (same STD name), this converts the EPP value so
# ``validate_write`` can gate it against the model's ``valueRange``:
#   - temperature is absolute degC (EPP + 16), matched against the STEP range;
#   - enums are the STD code directly (grSetDAC uses the model's numeric codes: operationMode
#     ``0/1/2/6``, windSpeed ``1/2/3/5``), matched by string against the LIST codes;
#   - booleans map the grSetDAC bit 0/1 to the model's LIST codes ``'false'``/``'true'`` — the model
#     describes these as string enums, NOT 0/1, so a raw-int passthrough was rejected as e.g.
#     ``screenDisplayStatus='1' not in ['false','true']``.
# Device-specific fields (the vertical-swing toggle 0x0c and this unit's repurposed 3-bit
# ``ecoMode``) have no standard model attribute, so they are absent here and stay gated by the
# encoder allowlist in ``set_grsetdac_field`` alone.
def _bool_code(epp: int) -> str:
    return "true" if epp else "false"


_MODEL_VALUE_FROM_EPP: dict[str, Callable[[int], object]] = {
    "targetTemperature": lambda epp: epp + 16,
    "operationMode": lambda epp: epp,
    "windSpeed": lambda epp: epp,
    "onOffStatus": _bool_code,
    "healthMode": _bool_code,
    "rapidMode": _bool_code,
    "muteStatus": _bool_code,
    "silentSleepStatus": _bool_code,
    "screenDisplayStatus": _bool_code,
    # raw EPP value == the STD code the model lists (0 / 7), so the valueRange gate applies
    # directly. windDirectionVertical is deliberately absent: its EPP nibble (0x0c) is NOT its
    # STD code (8), so it cannot be validated against the model's valueRange.
    "windDirectionHorizontal": lambda epp: epp,
}


def _load_digital_model(entry: HaismartConfigEntry) -> dict[str, Any] | None:
    """The cloud-fetched digital model (device constraints) as a dict, or None if absent/bad."""
    raw = entry.data.get(CONF_DIGITAL_MODEL)
    if not raw:
        return None
    try:
        model = json.loads(raw)
    except (ValueError, TypeError):
        _LOGGER.warning("stored digital model is not valid JSON; model write-validation disabled")
        return None
    return model if isinstance(model, dict) and model.get("attributes") else None


def _model_authorized_codes(model: dict[str, Any] | None) -> dict[str, set[int]]:
    """Per-field raw codes this device's own digital model declares, for the enum fields the encoder
    lets the model authorize (``operationMode``/``windSpeed``).

    This is how a capability the reference unit doesn't have reaches the wire: heat mode is absent
    from the encoder's observed-value allowlist (our hardware is cooling-only), so a heat-pump AC's
    own published model is what authorizes its heat code — not a guessed constant. Empty when no
    model is stored (manual onboarding), which leaves the observed allowlist as the only authority.
    """
    if model is None:
        return {}
    codes = {name: model_enum_codes(model, name) for name in GRSETDAC_MODEL_AUTHORIZED}
    return {name: values for name, values in codes.items() if values}


def _telemetry_from(blobs: list[bytes]) -> dict[str, Any]:
    """The running-power/compressor figures out of a session's blobs, or ``{}`` if it carried no
    extended report (the usual case for a control session, which does not query for one)."""
    for blob in blobs:
        if ext := parse_extended_status(blob):
            return ext
    return {}


def _build_profile(
    entry: HaismartConfigEntry, product_code: str, model: dict[str, Any] | None
) -> AttributeProfile:
    """Prefer the cloud-fetched digital model (correct for ANY model); otherwise fall back to the
    hardcoded per-model profile keyed by product_code."""
    if model is not None:
        try:
            return profile_from_device_config(model)
        except (ValueError, KeyError, TypeError):
            _LOGGER.warning("stored digital model is unusable; using the hardcoded profile")
    return profile_for(product_code)


class HaismartCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls one AC over uSS and exposes the parsed full-status report."""

    config_entry: HaismartConfigEntry

    def __init__(self, hass: HomeAssistant, entry: HaismartConfigEntry) -> None:
        self.host: str = entry.data[CONF_HOST]
        self.device_id: str = entry.data[CONF_DEVICE_ID]
        self._local_key: str = entry.data[CONF_LOCAL_KEY]
        self.product_code: str = entry.data.get(CONF_PRODUCT_CODE) or DEFAULT_PRODUCT_CODE
        # uPlusId (device-list wifiType) — the precise wire-model key when the cloud onboarding
        # stored it; None for manual onboarding, where the decoder keys on report length instead.
        self.uplus_id: str | None = entry.data.get(CONF_UPLUS_ID) or None
        self.digital_model: dict[str, Any] | None = _load_digital_model(entry)
        self.profile: AttributeProfile = _build_profile(
            entry, self.product_code, self.digital_model
        )
        self.model_codes: dict[str, set[int]] = _model_authorized_codes(self.digital_model)
        self.localkey_version: int | None = entry.data.get(CONF_LOCALKEY_VERSION)
        self.last_raw_status: bytes | None = None
        # Whether this unit answers the extended-status query (running power / compressor figures).
        # None = not yet known; settled on the first cycle that produces a status report.
        self.supports_extended: bool | None = None
        self._ask_extended = True
        # consecutive cycles that carried status but no extended report (see EXTENDED_MISSES)
        self._extended_misses = 0
        # The last extended reading actually reported, with when it arrived and the on/off state it
        # described. A cycle that carries no extended report re-publishes it (see
        # `_apply_telemetry`) so a control op does not blank the telemetry entities.
        self._telemetry: dict[str, Any] = {}
        self._telemetry_at = 0.0
        self._telemetry_power: bool | None = None
        self._misses = 0
        # Cloud reachability, from the key-free UDISCOVERY query (see const.py). `None` = not known
        # (never answered, or the unit does not implement it) -- deliberately NOT False, so a device
        # that cannot tell us reads "unknown" rather than being reported as cut off.
        self.cloud_connected: bool | None = None
        self.cloud_state: int | None = None
        # Module firmware, reported by the same query. Surfaced as the HA device's software
        # version, so it lands on the device page and in a diagnostics report without an entity.
        self.firmware: str | None = None
        # Where the AC says it is. Only used in diagnostics: if this stops matching the configured
        # host the unit has moved on DHCP, which is the commonest way a working setup breaks and
        # otherwise presents as an AC that simply stopped answering.
        self.reported_host: str | None = None
        self.reported_port: int | None = None
        self._rediscover_next = 0.0
        # Snapshot of the options this coordinator was built with, so the entry's update listener
        # can tell an options change (reload) from the runtime data writes below (do not reload).
        self.options: dict[str, Any] = dict(entry.options)
        self.supports_udiscovery: bool | None = None
        self._udiscovery_next = 0.0
        self._udiscovery_misses = 0
        # length of a status report we could only partially decode, or None. Drives the repair.
        self.unknown_layout: int | None = None
        # distinct status reports kept while the layout is unrecognised (see _remember_report)
        self._recent_reports: list[bytes] = []
        # length of a report that decoded fully via a KNOWN non-classic wire model that is not yet
        # write-capable (read-only family), or None. Blocks control with a clear message — unlike
        # unknown_layout it raises no repair, because monitoring works.
        self.read_only_layout: int | None = None
        # the non-classic wire model in use (set on decode), or None for the classic family. Drives
        # the family-specific control encoder.
        self._wire_model: WireModel | None = None
        # These units accept ONE connection at a time (§2.1), and nothing in Home Assistant
        # serializes a command against a poll — or against another command: applying a scene fires
        # its entities concurrently, so one carrying the thermostat and a switch sends two ops at
        # once. Every uSS session therefore goes through this lock. It is not only about the refused
        # second connection: a control op seeds its group-set from the status the AC pushes on the
        # op's OWN connection, so two overlapping ops each seed from a baseline taken before the
        # other applied, and a group-set writes the WHOLE attribute vector — so the later reply
        # silently reverts the earlier change instead of half-applying it.
        self._session = asyncio.Lock()
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {self.device_id}",
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        # One connection per cycle: these units accept a single session at a time, so the
        # extended-status query rides along inside the ordinary read rather than costing a second
        # connection or its own poll interval. `_ask_extended` latches off if a unit turns out not
        # to cope with it, so an unfamiliar model degrades to plain status instead of failing.
        try:
            blobs = await self._async_read()
        except (TimeoutError, OSError, RuntimeError) as err:
            # Before giving up: the AC may simply have moved. Ask the LAN who is out there, and if
            # this unit answers from a new address, follow it and retry in the same cycle -- the
            # user sees nothing at all rather than an AC that went unavailable until they noticed.
            if not await self._async_rediscover_host():
                raise UpdateFailed(f"uSS read from {self.host} failed: {err}") from err
            try:
                blobs = await self._async_read()
            except (TimeoutError, OSError, RuntimeError) as retry_err:
                raise UpdateFailed(
                    f"uSS read from {self.host} failed: {retry_err}"
                ) from retry_err

        # The read succeeded, so the unit is reachable: a silent UDISCOVERY query now means the
        # module does not implement it, not that the network is down. That distinction is why this
        # sits here rather than at the top of the cycle.
        await self._async_poll_cloud_state()

        telemetry = _telemetry_from(blobs)

        for blob in blobs:
            if state := parse_full_status(
                blob, self.profile, self.digital_model, uplus_id=self.uplus_id
            ):
                self._misses = 0
                self.last_raw_status = blob
                if state.get("partial"):
                    # Decoded, but only the layout-independent fields: this model's report
                    # length has no confirmed layout. Keeping the blob matters -- it is exactly
                    # what a maintainer needs, and diagnostics used to report `null` for this case.
                    self._note_unknown_layout(blob)
                else:
                    self._clear_unknown_layout()
                # A known non-classic family decodes fully. Track its wire model (drives the
                # family-specific control encoder) and, if it has no confirmed write path, flag it
                # read-only so control returns a clear message instead of a wrong-family group-set.
                self._wire_model = (
                    None if len(blob) in STATUS_LAYOUTS
                    else select_wire_model(len(blob), self.uplus_id)
                )
                self.read_only_layout = (
                    len(blob) if state.get("writable") is False else None
                )
                if telemetry:
                    self.supports_extended = True
                    self._extended_misses = 0
                elif self.supports_extended is True and not self._ask_extended:
                    # The query was paused by an empty cycle (see below), and reads are working
                    # again — so ask for the extended report again rather than leaving a unit that
                    # has already answered one without its telemetry for the rest of the run.
                    self._ask_extended = True
                elif self._ask_extended and self.supports_extended is None:
                    # Status arrived but no extended report, which usually means this unit does not
                    # offer one -- so stop appending a frame it ignores on every poll from now on.
                    # But not on the first cycle: a single reply can simply be dropped, and writing
                    # the capability off costs the unit seven entities until the entry is reloaded.
                    # Same reasoning (and the same threshold) as UDISCOVERY_MISSES.
                    self._extended_misses += 1
                    if self._extended_misses >= EXTENDED_MISSES:
                        self.supports_extended = False
                        self._ask_extended = False
                        _LOGGER.debug(
                            "%s did not answer the extended-status query in %d cycles; the power "
                            "and compressor sensors will stay unavailable for this unit",
                            self.host, EXTENDED_MISSES,
                        )
                self._apply_telemetry(state, telemetry)
                return state

        # Connected fine but nothing decoded — either the AC pushed no full report this
        # cycle (transient) or every biz payload failed the MD5 check (stale localKey).
        # If we appended the extended query, stop asking for now so the next cycle retries with a
        # plain read: a unit that cannot cope with the extra frame must not lose its status over it.
        if self._ask_extended:
            self._ask_extended = False
            if self.supports_extended is True:
                # This unit HAS answered the extended query, so the extra frame is not what broke
                # this cycle — a stale key or a dropped push is. Pause it for one cycle to be sure,
                # then re-arm above once a status decodes again. Concluding "unsupported" here used
                # to be permanent, so one empty cycle took the telemetry entities out for good.
                _LOGGER.debug(
                    "no decodable status from %s; pausing the extended-status query for one cycle "
                    "(this unit has answered it before)", self.host,
                )
            else:
                self.supports_extended = False
                _LOGGER.debug(
                    "no decodable status from %s while asking for extended status; dropping the "
                    "extra query and retrying with a plain read", self.host,
                )
        self._log_undecodable(blobs)
        self._misses += 1
        # capture BEFORE the probe below resets it, or the message always reports 0
        misses = self._misses
        if self._misses >= _MISSES_BEFORE_PROBE:
            # probe once at the threshold; if the key still matches it's a transient miss, so
            # reset the counter rather than re-probe (an extra handshake) on every later cycle.
            await self._check_localkey_rotation()
            self._misses = 0
        raise UpdateFailed(
            f"no decodable status from {self.host} ({misses} consecutive misses)"
        )

    async def _async_read(self) -> list[bytes]:
        """One read cycle against the current host, holding the single-session lock."""
        async with self._session:
            return await async_read_status(
                self.host, self.device_id, self._local_key, timeout=READ_TIMEOUT,
                extra_request=extended_status_epp_frame() if self._ask_extended else None,
            )

    async def _async_rediscover_host(self) -> bool:
        """Find this AC at a new address after a failed read. ``True`` if the host changed.

        These modules move on DHCP, and until now that presented as an AC that simply stopped
        responding -- indistinguishable from a dead unit or a stale key, and fixable only by hand.
        Since the deviceId is the module's MAC, an ARP/DHCP lookup recognises the unit wherever it
        landed and the entry is corrected without the user doing anything (see `discovery.py` for
        why that is preferred over the protocol's own broadcast).

        Never raises: this runs on a failure path and must not replace the real error.
        """
        now = self.hass.loop.time()
        if now < self._rediscover_next:
            return False
        self._rediscover_next = now + REDISCOVER_COOLDOWN
        host = await async_find_host(self.hass, self.device_id)
        if host is None or host == self.host:
            return False
        _LOGGER.info(
            "%s moved from %s to %s; updating the entry to follow it",
            self.device_id, self.host, host,
        )
        self.host = host
        self.hass.config_entries.async_update_entry(
            self.config_entry, data={**self.config_entry.data, CONF_HOST: host}
        )
        self._sync_device_registry()
        return True

    def _sync_device_registry(self) -> None:
        """Keep the HA device's firmware version and configuration link in step with what we learn.

        `entity.py` builds its DeviceInfo once per entity, so both values freeze at the moment the
        entities are created. Firmware that arrives on a later UDISCOVERY reply -- because the
        first query went unanswered, or the module was slow -- then never shows up at all, and
        after the AC moves on DHCP the configuration link still points at the address it left, on
        the very page someone opens to work out why it stopped answering.

        Never raises, and a no-op once both agree: this runs on every successful discovery query.
        """
        registry = dr.async_get(self.hass)
        device = registry.async_get_device(identifiers={(DOMAIN, self.device_id)})
        if device is None:
            return      # the first refresh runs before the platforms create the device
        updates: dict[str, Any] = {}
        if self.firmware and device.sw_version != self.firmware:
            updates["sw_version"] = self.firmware
        url = f"http://{self.host}"
        if device.configuration_url != url:
            updates["configuration_url"] = url
        if updates:
            registry.async_update_device(device.id, **updates)

    async def _async_poll_cloud_state(self) -> None:
        """Refresh whether the AC can reach Haier's cloud, on its own slow cadence.

        One UDP round trip on :7083, no localKey and no account involved -- which is the point: it
        lets someone who has firewalled their AC confirm the block holds without asking Haier
        anything. Never raises: this is a diagnostic signal and must not be able to fail a poll.

        A unit that stays silent is backed off to UDISCOVERY_RETIRE_INTERVAL rather than abandoned:
        the answer can come back (a firmware update, or simply an access point that stopped eating
        the datagrams), and one query an hour costs nothing against what giving up loses.
        """
        now = self.hass.loop.time()
        if now < self._udiscovery_next:
            return
        self._udiscovery_next = now + UDISCOVERY_INTERVAL
        try:
            info = await udiscovery.async_query(self.host, timeout=UDISCOVERY_TIMEOUT)
        except OSError as err:
            _LOGGER.debug("UDISCOVERY query to %s failed: %s", self.host, err)
            info = None
        if info is None:
            self.cloud_state = None
            self.cloud_connected = None
            self._udiscovery_misses += 1
            if self._udiscovery_misses >= UDISCOVERY_MISSES:
                self._udiscovery_next = now + UDISCOVERY_RETIRE_INTERVAL
                if self.supports_udiscovery is not False:
                    self.supports_udiscovery = False
                    _LOGGER.debug(
                        "%s does not answer the UDISCOVERY query; the cloud-connection sensor will "
                        "stay unavailable for this unit, and the query drops to one attempt every "
                        "%.0f s in case that changes", self.host, UDISCOVERY_RETIRE_INTERVAL,
                    )
            return
        self._udiscovery_misses = 0
        self.supports_udiscovery = True
        self._learn_identity(info)
        if info.cloud_connected is not self.cloud_connected:
            _LOGGER.debug(
                "%s cloud connectivity: %s (state %s)",
                self.host, info.cloud_connected, info.cloud_state,
            )
        self.cloud_state = info.cloud_state
        self.cloud_connected = info.cloud_connected

    def _learn_identity(self, info: udiscovery.DeviceInfo) -> None:
        """Record what the AC says about itself: firmware, and the uPlusId if we lack it.

        The uPlusId is the precise wire-model key. Until now it arrived only from the cloud device
        list, so a `manual` (fully offline) install had to fall back to keying the decoder on report
        length -- which is what makes an unfamiliar model decode partially or not at all. The AC
        hands it over for free, so an offline install can now be exactly as accurate as a cloud one.

        It is written into the config entry rather than kept in memory: entry data lives in
        `.storage`, so it rides along in Home Assistant backups the same way the localKey does, and
        survives a restart without re-querying.
        """
        if info.firmware:
            self.firmware = " / ".join(info.firmware)
        self.reported_host = info.host or None
        self.reported_port = info.port or None
        self._sync_device_registry()
        uplus_id = info.uplus_id.strip("0")  # an all-zero field means "not reported"
        if not uplus_id or info.uplus_id == self.uplus_id:
            return
        if self.uplus_id:
            # Trust the cloud value we already have; a mismatch is worth knowing about but is not
            # ours to resolve silently.
            _LOGGER.debug(
                "%s reports uPlusId %s but the entry stores %s; keeping the stored one",
                self.device_id, info.uplus_id, self.uplus_id,
            )
            return
        self.uplus_id = info.uplus_id
        _LOGGER.info(
            "learned uPlusId %s for %s from the device itself; the report layout can now be "
            "selected without cloud credentials", info.uplus_id, self.device_id,
        )
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            data={**self.config_entry.data, CONF_UPLUS_ID: info.uplus_id},
        )

    @property
    def recent_reports(self) -> tuple[bytes, ...]:
        """Distinct status reports seen while the layout was unrecognised (diagnostics)."""
        return tuple(self._recent_reports)

    def _remember_report(self, blob: bytes) -> None:
        """Keep a few *distinct* status reports while the layout is unrecognised.

        Working out an unknown layout needs reports taken in different states — one report is mostly
        zeros, so many candidate maps explain it equally well, and only a change of state tells them
        apart. Identical reports are dropped so an idle unit cannot fill the store with copies of
        one state, and the store is cleared as soon as a layout is recognised.
        """
        if blob in self._recent_reports:
            return
        self._recent_reports.append(blob)
        del self._recent_reports[:-_RECENT_REPORTS]

    def _note_unknown_layout(self, blob: bytes) -> None:
        """Record an unrecognised report length: log once, raise a repair, remember the blob."""
        self._remember_report(blob)
        if self.unknown_layout == len(blob):
            return      # already reported; do not repeat every poll
        self.unknown_layout = len(blob)
        _LOGGER.warning(
            "Unrecognised Haier status report from %s: %d bytes (known: %s). Power, setpoint, "
            "mode, fan and vertical swing were decoded; indoor/outdoor temperature and the "
            "secondary toggles are unavailable. product_code=%s. Please report this model so the "
            "layout can be added - see docs/new-model.md.",
            self.host, len(blob), ", ".join(str(n) for n in sorted(STATUS_LAYOUTS)),
            self.product_code,
        )
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            f"{ISSUE_UNKNOWN_LAYOUT}_{self.device_id}",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_UNKNOWN_LAYOUT,
            translation_placeholders={
                "name": self.config_entry.title,
                "length": str(len(blob)),
                "product_code": self.product_code or "unknown",
            },
            learn_more_url=(
                "https://github.com/enapt/haismart-local/blob/main/docs/new-model.md"
            ),
        )

    def _clear_unknown_layout(self) -> None:
        self._recent_reports.clear()
        if self.unknown_layout is None:
            return
        self.unknown_layout = None
        ir.async_delete_issue(self.hass, DOMAIN, f"{ISSUE_UNKNOWN_LAYOUT}_{self.device_id}")

    def _log_undecodable(self, blobs: list[bytes]) -> None:
        """Debug-log what the AC actually sent when no status decoded — the report discriminator.

        ``async_read_status`` returns only payloads that decrypted (a failed biz MD5 check is
        dropped silently), so the two cases look identical from the outside but mean opposite
        things:

        * **no payloads** — the AC pushed nothing this cycle, OR every payload failed the MD5 check,
          i.e. the localKey is wrong/stale (the consecutive-miss probe below checks for rotation);
        * **payloads present** — the localKey is GOOD and nothing the AC sent was a full-status
          report at all: a frame without the ``2715`` signature, or one too short for even the
          layout-independent fields.

        Note an unrecognised report *length* does NOT reach here: ``parse_full_status`` decodes
        those partially and :meth:`_note_unknown_layout` raises a repair, so a new model is already
        diagnosed by name. What lands here is whatever else the AC is pushing, hence logging the
        frames in full — they are the only way to identify it.

        Report bytes carry device state only, no key material (the same bytes diagnostics exports).
        """
        if not blobs:
            _LOGGER.debug(
                "%s: handshake OK but nothing decrypted this cycle (stored localKey v%s) — either "
                "the AC pushed no status, or every payload failed the biz MD5 check "
                "(wrong/stale key)",
                self.device_id,
                self.localkey_version,
            )
            return
        _LOGGER.debug(
            "%s: localKey is good (%d payload(s) decrypted) but no full-status report decoded — "
            "unrecognised frame (no 2715 signature, or shorter than the attribute vector). "
            "Frames: %s",
            self.device_id,
            len(blobs),
            "; ".join(
                f"len={len(b)} {b[:_LOG_FRAME_BYTES].hex()}"
                f"{'…' if len(b) > _LOG_FRAME_BYTES else ''}"
                for b in blobs[:_LOG_FRAME_MAX]
            ),
        )

    async def async_send_control(self, changes: dict[str, int]) -> None:
        """Apply ``{field_name: raw_epp_value}`` to the state and send it as one grSetDAC op.

        grSetDAC is a group-set: it must be seeded from the AC's TRUE current state so every
        attribute except the changed one(s) is preserved, then the requested fields flipped. We
        seed from the status the AC pushes on the op's OWN connection right after the handshake
        (``build_frame``), so the baseline is live — no separate read connection (keeps control
        snappy, halves the AC load) and no staleness: seeding from a cached ``last_raw_status``
        that lags an IR change or a prior command could re-send an old power/mode bit and silently
        turn the unit back off. If the AC pushes nothing that session we fall back to the cached
        status. The library gates each field + value (confirmed only). WRITES to the AC.
        """
        # Per-model lockdown: gate every change against the device's digital model (valueRange)
        # BEFORE it is sent, on top of the library's confirmed allowlist — so the pulled
        # product constraints reject an out-of-range temperature or an unsupported enum. Only
        # fields mapping 1:1 to a model attribute are checked; device-specific ones (swing/eco) stay
        # gated by the encoder allowlist alone.
        self._validate_against_model(changes)

        if self.read_only_layout is not None:
            # A recognised family, but its wire model (word map + group-set command) isn't
            # capture-confirmed for writes yet. Reads work; control would use the wrong field map,
            # so refuse cleanly rather than send a malformed op.
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="control_rejected",
                translation_placeholders={
                    "name": self.config_entry.title,
                    "error": (
                        "this AC model is supported for monitoring only; control is not enabled "
                        "yet for its report layout"
                    ),
                },
            )

        if self.unknown_layout is not None:
            # Reads degrade gracefully on an unrecognised report; writes must not. The size of the
            # control-word block is exactly what could not be determined, so a group-set built from
            # it could send a read-only sensor byte back to the AC as a setting.
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="layout_unknown",
                translation_placeholders={
                    "name": self.config_entry.title,
                    "length": str(self.unknown_layout),
                },
            )

        def _build(baseline: bytes | None) -> bytes:
            base = baseline if baseline is not None else self.last_raw_status
            if base is None:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="no_status",
                    translation_placeholders={"name": self.config_entry.title},
                )
            if baseline is not None:  # refresh the cache from the fresh in-session baseline
                self._misses = 0
                self.last_raw_status = baseline
            wm = self._wire_model
            if wm is not None and wm.group_cmd is not None:
                # Non-classic family: pack via its own wire model + group-set command. The encoder
                # translates the classic-shaped change values (STD codes / setpoint) to this
                # family's raw values and refuses anything unmapped.
                words = wm.encode_control(wm.baseline_words(base), changes)
                return build_epp_frame(0x01, wm.group_cmd, words)
            words = grsetdac_baseline_from_status(base)
            for name, value in changes.items():
                words = set_grsetdac_field(
                    words, name, value, model_values=self.model_codes.get(name)
                )
            return grsetdac_op_frame(words)

        try:
            # One short session: the CAE counter starts at 1 and the biz sequence base is
            # auto-derived from HELLO_DONE_RESP (a wrong sn drops the connection). build_frame
            # seeds from the AC's in-session status push.
            # Under the session lock, so this op cannot overlap a poll or a second command: the
            # baseline `_build` seeds from must be the state left by whatever ran before it. Waiting
            # costs at most one read (READ_TIMEOUT), against an op that would otherwise be refused
            # by the AC or quietly undone by the other one.
            async with self._session:
                reply = await async_send_op(
                    self.host, self.device_id, self._local_key,
                    build_frame=_build, counter=1, timeout=WRITE_TIMEOUT,
                )
        except HomeAssistantError:
            raise
        except (ValueError, KeyError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="control_rejected",
                translation_placeholders={"name": self.config_entry.title, "error": str(err)},
            ) from err
        except (OSError, RuntimeError, TimeoutError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="control_failed",
                translation_placeholders={"name": self.config_entry.title, "error": str(err)},
            ) from err
        # The AC echoes its UPDATED state on the op's own connection (the protocol), so confirm
        # from that reply directly — instant, one fewer connection. Fall back to a read cycle only
        # if the reply carried no decodable full-status report.
        if (state := self._state_from_reply(reply)) is not None:
            self.async_set_updated_data(state)
        else:
            await self.async_request_refresh()

    def _state_from_reply(self, reply: list[bytes]) -> dict[str, Any] | None:
        """The newest decodable full-status report in a control op's reply blobs, or None if none
        decoded. The AC echoes updated state on the op connection (the protocol). Also updates
        the seed baseline + miss counter so the next op/poll starts from the confirmed state."""
        telemetry = _telemetry_from(reply)
        for blob in reversed(reply):
            if state := parse_full_status(
                blob, self.profile, self.digital_model, uplus_id=self.uplus_id
            ):
                self.last_raw_status = blob
                self._misses = 0
                self._apply_telemetry(state, telemetry)
                return state
        return None

    def _apply_telemetry(self, state: dict[str, Any], telemetry: dict[str, Any]) -> None:
        """Attach the running-power/compressor figures to a decoded state, standing in the previous
        reading when this cycle produced none.

        A control session collects the AC's own status echo but no extended report — that query
        belongs to a read cycle — so publishing the echo alone used to blank every telemetry entity:
        power, current, frequency, the coil/discharge temperatures and the compressor/fan sensors
        all went `unknown` after each command until the next poll (which a command also pushes a
        full interval away). The same gap opens on a read cycle whose extended reply simply does not
        arrive. These are slow-moving measurements, so the reading from moments ago stands in far
        better than a hole in the history, for up to `TELEMETRY_MAX_AGE`.

        It is dropped at once when the unit's on/off state changed, because that invalidates the
        figures outright — an AC that was drawing 800 W draws none once it is off — and a
        plausible-looking wrong number is worse than a gap.
        """
        if telemetry:
            state.update(telemetry)
            self._telemetry = telemetry
            self._telemetry_at = self.hass.loop.time()
            self._telemetry_power = state.get("power")
            return
        if not self._telemetry or self.supports_extended is not True:
            return
        if state.get("power") != self._telemetry_power:
            return
        if self.hass.loop.time() - self._telemetry_at > TELEMETRY_MAX_AGE:
            # Too old to speak for the unit any more: forget it, so the entities read unknown
            # instead of holding a stale number indefinitely.
            self._telemetry = {}
            return
        state.update(self._telemetry)

    def _validate_against_model(self, changes: dict[str, int]) -> None:
        """Reject a control change the device's digital model forbids (out-of-range temperature, an
        enum the unit doesn't support, a non-writable attribute). No-op when no digital model is
        stored (e.g. the manual onboarding path) or for device-specific fields the model doesn't
        describe — those stay gated by the library's encoder allowlist. Raises HomeAssistantError.
        """
        model = self.digital_model
        if model is None:
            return
        described = {a.get("name") for a in model.get("attributes", [])}
        for name, epp in changes.items():
            to_model = _MODEL_VALUE_FROM_EPP.get(name)
            # skip device-specific fields, and fields the model doesn't describe (can't constrain
            # what it doesn't list — the encoder allowlist still gates those). Enforce the rest.
            if to_model is None or name not in described:
                continue
            # Gate the valueRange only. The model's own ``writable`` flag misclassifies several
            # confirmed grSetDAC fields (targetTemperature, rapidMode, muteStatus,
            # silentSleepStatus) as read-only; writability here is authorized by the capture
            # allowlist in ``set_grsetdac_field``, which is proven against real hardware.
            ok, reason = validate_write(model, name, to_model(epp), require_writable=False)
            if not ok:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="control_rejected",
                    translation_placeholders={
                        "name": self.config_entry.title,
                        "error": reason,
                    },
                )

    @property
    def local_key(self) -> str:
        """The AC's current localKey (kept fresh across gateway auto-refresh). For the opt-in backup
        sensor — it's a secret, so that entity is diagnostic + disabled by default."""
        return self._local_key

    def supports_field(self, name: str) -> bool:
        """Whether a control field can be written on the family this unit actually reports.

        The classic family's write map is :data:`GRSETDAC_FIELDS`; a non-classic family carries its
        own, which is generally smaller — compact-12 has none of the secondary toggles, extended-46
        no swing, and neither has this unit's multi-level ``ecoMode``. A control that advertises a
        field its family cannot place could only ever raise, so the entities that group several
        fields into one control ask here before offering themselves.
        """
        if (wm := self._wire_model) is not None:
            return name in wm.write_fields
        return name in GRSETDAC_FIELDS

    def current_field(self, name: str) -> int | None:
        """The live raw EPP value of a grSetDAC field (for the toggle/select entities), or None.

        A non-classic family keeps its control block wherever its own wire model says, so the value
        is read back through that model — otherwise the classic reader would slice the wrong bytes,
        and a switch would show a state the AC never reported. ``None`` (state unknown) whenever the
        field isn't mapped on this family, which is how a monitoring-only model behaves.
        """
        if self.last_raw_status is None:
            return None
        if (wm := self._wire_model) is not None:
            return wm.current_write_value(self.last_raw_status, name)
        try:
            return read_grsetdac_field(self.last_raw_status, name)
        except (ValueError, KeyError):
            return None

    async def _check_localkey_rotation(self) -> None:
        """Probe the AC's current localKey version (key-free). On rotation, try to auto-refresh the
        localKey from the Haier cloud MQTT gateway; only fall back to a manual reauth flow if the
        gateway refresh isn't configured or fails."""
        try:
            # Also a uSS session (a handshake, key-free), so it takes the same lock.
            async with self._session:
                current = await self.hass.async_add_executor_job(
                    partial(
                        probe_localkey_version, self.host, self.device_id, timeout=READ_TIMEOUT
                    )
                )
        except (OSError, RuntimeError) as err:
            raise UpdateFailed(f"localKey version probe failed: {err}") from err
        if self.localkey_version is None or current == self.localkey_version:
            return
        old = self.localkey_version
        if await self._async_gateway_refresh():
            _LOGGER.info(
                "localKey auto-refreshed via the cloud gateway (v%s -> v%s) for %s",
                old, self.localkey_version, self.device_id,
            )
            self.clear_stale_localkey_issue()  # healed itself — no manual step needed
            return
        # No cloud creds to self-heal: a person must reauth by hand. Surface an actionable repair
        # advising them to add account credentials so future rotations auto-refresh.
        self._raise_stale_localkey_issue(old, current)
        raise ConfigEntryAuthFailed(
            f"localKey rotated on the AC (v{old} -> v{current}) and no cloud auto-refresh "
            "succeeded; a fresh key is needed"
        )

    def _raise_stale_localkey_issue(self, old: int | None, current: int) -> None:
        """Create the actionable repair for a manual re-key (no cloud auto-refresh configured)."""
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            f"{ISSUE_STALE_LOCALKEY}_{self.device_id}",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_STALE_LOCALKEY,
            translation_placeholders={
                "name": self.config_entry.title,
                "old": str(old),
                "new": str(current),
            },
        )

    def clear_stale_localkey_issue(self) -> None:
        """Delete the manual-re-key repair once rotation self-heals via the cloud gateway."""
        ir.async_delete_issue(
            self.hass, DOMAIN, f"{ISSUE_STALE_LOCALKEY}_{self.device_id}"
        )

    async def _async_gateway_refresh(self) -> bool:
        """Fetch the current localKey from the cloud MQTT gateway and update it in place.

        Returns ``True`` on success (key + version updated on ``self`` and persisted to the config
        entry, so the next read cycle uses it); ``False`` if the gateway credentials aren't
        configured or any step fails — the caller then falls back to a manual reauth flow. Every
        CONNECT credential is now DERIVED (nothing stored): the clientId from the stored uSDK
        CLIENTID, the accessToken minted from the reusable refreshToken, and the MQTT
        username/password by ``haismart_extractor.gateway.derive_gateway_auth`` — so the only
        per-entry input needed is the uSDK CLIENTID + a token. (``CONF_GATEWAY_USERNAME`` /
        ``CONF_GATEWAY_PASSWORD`` are honored if present, for pinning, but no longer required.)
        """
        data = self.config_entry.data
        usdk_client_id = data.get(CONF_CLOUD_CLIENT_ID)
        if not usdk_client_id:
            return False  # gateway auto-refresh not configured for this entry
        # Optional pin: if an explicit username was stored, reuse its body so the pair is
        # reproducible; otherwise a fresh valid pair is generated per refresh.
        pinned_username = data.get(CONF_GATEWAY_USERNAME)
        username_body = (
            pinned_username[2:]
            if pinned_username and pinned_username.startswith("01") and len(pinned_username) == 10
            else None
        )

        access_token = data.get(CONF_ACCESS_TOKEN)
        refresh_token = data.get(CONF_REFRESH_TOKEN)
        if refresh_token:
            # mint a fresh accessToken from the durable refreshToken (accessTokens expire ~daily)
            try:
                cloud = HaierCloud(
                    replace(SEA_APP_CREDENTIALS, client_id=usdk_client_id),
                    access_token or "",
                    zone_info=data.get(CONF_ZONE_INFO, "0"),
                    # HA's shared httpx client: building one here would block the loop (CA bundle)
                    transport=async_cloud_transport(self.hass),
                )
                access_token = (await cloud.refresh_token(refresh_token)).access_token
            except (CloudError, OSError, RuntimeError) as err:
                _LOGGER.warning("token refresh failed (%s); trying the stored access token", err)
        if not access_token:
            return False

        creds = GatewayCreds.derive(
            usdk_client_id=usdk_client_id,
            access_token=access_token,
            username_body=username_body,
        )
        try:
            local_key = await self.hass.async_add_executor_job(
                partial(get_localkey_via_gateway, creds, self.device_id, timeout=GATEWAY_TIMEOUT)
            )
        except (GatewayError, OSError, RuntimeError) as err:
            _LOGGER.warning("gateway localKey refresh failed for %s: %s", self.device_id, err)
            return False

        self._local_key = local_key.key
        self.localkey_version = local_key.version
        updates: dict[str, Any] = {
            CONF_LOCAL_KEY: local_key.key,
            CONF_LOCALKEY_VERSION: local_key.version,
        }
        if access_token and access_token != data.get(CONF_ACCESS_TOKEN):
            updates[CONF_ACCESS_TOKEN] = access_token
        self.hass.config_entries.async_update_entry(
            self.config_entry, data={**data, **updates}
        )
        return True
