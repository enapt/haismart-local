"""Diagnostics: a redacted snapshot for bug reports."""
from __future__ import annotations

from functools import partial
from typing import Any

from haismart_hrdp import (
    STATUS_LAYOUTS,
    declared_order,
    derive_status_layout,
    probe_layout,
    select_wire_model,
)
from haismart_hrdp.udiscovery import CLOUD_STATES
from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ACCESS_TOKEN,
    CONF_CLOUD_CLIENT_ID,
    CONF_DEVICE_ID,
    CONF_GATEWAY_PASSWORD,
    CONF_GATEWAY_USERNAME,
    CONF_LOCAL_KEY,
    CONF_REFRESH_TOKEN,
)
from .coordinator import HaismartConfigEntry

# Diagnostics is the artefact users are told to attach to GitHub issues, so this list has to cover
# EVERY credential in `entry.data`. It once redacted only the localKey and the deviceId while
# leaving the account tokens in the clear — and `refresh_token` is durable and reusable, so
# publishing one grants indefinite access to the whole Haier account and every AC on it.
# The deviceId stays redacted even though it is only the Wi-Fi MAC and not a credential: it is a
# stable device identifier, and nothing here needs it — the report bytes a maintainer works offsets
# out from are dumped separately under `last_raw_status` / `report`.
TO_REDACT = {
    CONF_LOCAL_KEY,
    CONF_REFRESH_TOKEN,
    CONF_ACCESS_TOKEN,
    CONF_CLOUD_CLIENT_ID,
    CONF_GATEWAY_USERNAME,
    CONF_GATEWAY_PASSWORD,
    CONF_DEVICE_ID,
    "unique_id",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: HaismartConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    profile = coordinator.profile
    layout = await _async_layout_summary(hass, coordinator)
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "localkey_version": coordinator.localkey_version,
        "last_update_success": coordinator.last_update_success,
        "state": coordinator.data,
        # raw report bytes (post-decrypt) — carries no secrets, invaluable for offset bugs
        "last_raw_status": (
            coordinator.last_raw_status.hex() if coordinator.last_raw_status else None
        ),
        # enum codes the device's OWN digital model authorizes for the write path — this is what
        # decides whether e.g. heat is usable on this unit (coordinator._model_authorized_codes)
        "model_authorized_codes": {
            name: sorted(codes) for name, codes in coordinator.model_codes.items()
        },
        # Settings the unit is ignoring in the state it is in, per its own model's rules — the
        # answer to "why is this switch unavailable", which otherwise reads as a broken integration.
        "locked_fields": sorted(coordinator.locked_fields),
        # Everything a maintainer needs to add a layout, without a second round-trip.
        "report": {
            "length": len(coordinator.last_raw_status or b"") or None,
            "unknown_layout": coordinator.unknown_layout,
            "read_only_layout": coordinator.read_only_layout,
            "known_lengths": sorted(STATUS_LAYOUTS),
            "uplus_id": coordinator.uplus_id,
            "layout": layout,
        },
        # Whether the AC itself can reach Haier's cloud (key-free UDISCOVERY query). Worth having
        # in a bug report: a unit that is cut off cannot be re-keyed, which explains a stale
        # localKey failure that would otherwise look like a protocol bug.
        "cloud": {
            "connected": coordinator.cloud_connected,
            "raw_state": coordinator.cloud_state,
            "state_name": CLOUD_STATES.get(coordinator.cloud_state or -1),
            "supported": coordinator.supports_udiscovery,
            # Where the AC says it is, and whether that still agrees with the address this entry
            # uses. `host_matches: false` means the unit moved on DHCP and the entry is stale --
            # worth stating outright, because it presents as "the AC stopped responding" and is
            # otherwise indistinguishable from a dead unit or a bad key.
            "reported_host": coordinator.reported_host,
            "reported_port": coordinator.reported_port,
            "host_matches": (
                None
                if coordinator.reported_host is None
                else coordinator.reported_host == coordinator.host
            ),
        },
        "digital_model": _model_summary(coordinator.digital_model),
        # Attributes this device declares that its family map does not carry, read off the published
        # map at the family's confirmed displacement. Every unit declares three or four times what
        # any hand-written map holds, so this is most of what a report actually says -- surfaced
        # here first, where a wrong value costs nothing, rather than straight into entities.
        "model_declared_fields": _declared_readings(coordinator),
        "profile": {
            "product_code": coordinator.product_code,
            "modes": dict(profile.mode_values),
            "fan_modes": dict(profile.fan_values),
            "min_temp": profile.min_temp,
            "max_temp": profile.max_temp,
            "temp_step": profile.temp_step,
        },
    }


async def _async_layout_summary(hass: HomeAssistant, coordinator) -> dict[str, Any] | None:
    """Which layout was used for the stored blob, and whether it was confirmed or derived."""
    blob = coordinator.last_raw_status
    if not blob:
        return None
    # A non-classic family decoded by the wire-model registry (e.g. compact-12) — report which one.
    if len(blob) not in STATUS_LAYOUTS:
        wm = select_wire_model(len(blob), coordinator.uplus_id)
        if wm is not None:
            return {"resolved": True, "family": wm.family, "writable": wm.writable}
    layout = derive_status_layout(blob, coordinator.digital_model)
    if layout is None:
        # No known layout claims this report. Rather than leaving a maintainer to work the word
        # array out by hand, propose the layouts that fit: every model met so far has been a known
        # family whose fields are displaced from some word onward, and the device's own reported
        # attribute values decide between the candidates. This makes a diagnostics download
        # self-sufficient for adding the model — no second round-trip to the reporter.
        return {
            "resolved": False,
            "candidates": await _async_layout_candidates(hass, coordinator),
        }
    return {
        "resolved": True,
        "verified": layout.verified,      # False == derived from the length, not a confirmed entry
        "words": layout.words,
        "indoor_temp_offset": layout.indoor_temp,
        "outdoor_temp_offset": layout.outdoor_temp,
    }


async def _async_layout_candidates(
    hass: HomeAssistant, coordinator
) -> list[dict[str, Any]]:
    """Ranked layout proposals for a report nothing recognises (see :func:`probe_layout`).

    Every report the coordinator has kept is offered, because a candidate has to explain all of them
    and the reports were captured in different states. The device's own attribute values from its
    digital model are passed as the tie-breaker, and so is the order its model declares its settings
    in -- which is what actually settles a pivot, where the device states one.

    The search itself runs in an executor: it builds and decodes on the order of a thousand
    candidate models per report, which is pure CPU and has no business on the event loop — least of
    all here, since this path only runs for the user whose model is not decoding properly yet.
    """
    reports: list[bytes] = []
    for blob in (coordinator.last_raw_status, *coordinator.recent_reports):
        if blob and blob not in reports:
            reports.append(blob)
    if not reports:
        return []
    shadow = _shadow_values(coordinator.digital_model)
    order = declared_order(coordinator.digital_model)
    return await hass.async_add_executor_job(
        partial(probe_layout, reports, shadow=shadow, order=order)
    )


def _declared_readings(coordinator) -> dict[str, Any] | None:
    """What this unit's own declared attributes read, beyond the fields its family map carries.

    ``None`` when there is no report, no model, or the family has no confirmed displacement -- the
    last of which is deliberate rather than a shortfall: extended-46 carries an insert whose start
    is not pinned, so placing its attributes from the map would be guesswork wearing a decode.
    """
    blob = coordinator.last_raw_status
    model = coordinator.digital_model
    if not blob or not model:
        return None
    wm = select_wire_model(len(blob), coordinator.uplus_id) or _classic_probe_for(len(blob))
    if wm is None:
        return None
    declared = [a.get("name") for a in model.get("attributes") or [] if a.get("name")]
    fields = wm.model_fields(declared, len(blob))
    if not fields:
        return None
    return {name: wf.read(blob) for name, wf in sorted(fields.items())}


def _classic_probe_for(length: int):
    """The classic family's map, for the report lengths ``select_wire_model`` leaves to ``uss``."""
    from haismart_hrdp.wire_models import _CLASSIC_PROBE

    return _CLASSIC_PROBE if length in STATUS_LAYOUTS else None


def _shadow_values(model: dict[str, Any] | None) -> dict[str, Any]:
    """The values the device itself publishes for its attributes, keyed by attribute name.

    This is the tie-breaker for a layout proposal: a candidate that reproduces values the device
    reported through a different channel is almost certainly right. It is dumped into diagnostics
    as well as passed to the prober, so that re-running the search over the attached files reaches
    the same ranking the file already carries -- otherwise the candidates in the file can only be
    taken on trust, and any variation tried by hand is scored on plausibility alone.
    """
    return {
        attr["name"]: attr["value"]
        for attr in (model or {}).get("attributes") or []
        if isinstance(attr, dict) and attr.get("name") and attr.get("value") is not None
    }


def _model_summary(model: dict[str, Any] | None) -> dict[str, Any] | None:
    """The parts of the digital model that describe CAPABILITIES.

    The full model is large and contains device-identifying ids, so only the attribute value ranges,
    the values the device currently reports for them, and the grSetDAC attribute order are included
    -- which is all that is needed to work out a layout, and carries no credential. The reported
    values are the same settings the remote shows, alongside raw bytes that already say the same.
    """
    if not model:
        return None
    attributes = {
        a.get("name"): (a.get("valueRange") or {})
        for a in model.get("attributes", [])
        if a.get("name")
    }
    group_commands = {
        g.get("name"): g.get("attrNameList")
        for g in model.get("groupCommands", [])
        if g.get("name")
    }
    return {
        "attributes": attributes,
        "groupCommands": group_commands,
        "reported_values": _shadow_values(model),
    }
