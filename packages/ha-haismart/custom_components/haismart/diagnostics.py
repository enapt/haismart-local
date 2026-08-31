"""Diagnostics: a redacted snapshot for bug reports."""
from __future__ import annotations

import logging
from functools import partial
from typing import Any

from haismart_hrdp import (
    STATUS_LAYOUTS,
    declared_attribute_names,
    declared_order,
    derive_status_layout,
    device_type_class,
    probe_handshake_reply,
    probe_layout,
    rules_for_product,
    select_wire_model,
    uplus_class,
)
from haismart_hrdp.udiscovery import CLOUD_STATES
from haismart_hrdp.uss import EXTENDED_STATUS_FRAME_TYPES
from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ACCESS_TOKEN,
    CONF_CLOUD_CLIENT_ID,
    CONF_DEVICE_ID,
    CONF_GATEWAY_PASSWORD,
    CONF_GATEWAY_USERNAME,
    CONF_LOCAL_KEY,
    CONF_PRODUCT_CODE,
    CONF_REFRESH_TOKEN,
    DEFAULT_PRODUCT_CODE,
    EXTENDED_MISSES,
    READ_TIMEOUT,
)
from .coordinator import HaismartConfigEntry

_LOGGER = logging.getLogger(__name__)

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


async def _async_handshake_reply(hass: HomeAssistant, coordinator) -> dict[str, Any] | None:
    """The appliance's handshake reply, as it arrives, without decrypting it.

    The frame that decides whether a command can be sent, and the one nobody could ever supply when
    it went wrong: when it will not decrypt there is nothing to inspect, because the failure IS the
    decryption. Recording it here -- key-free, so it works precisely when the key does not -- means
    the file answers the question instead of somebody being asked to reproduce a fault with debug
    logging enabled.

    ``version`` is what the appliance says its key is; ``flag`` is its header flag, which reads 0 on
    every appliance seen even though the body is encrypted; ``head`` is the start of the payload, so
    a body that is NOT encrypted is recognisable on sight rather than by inference.
    """
    if not coordinator.host:
        return None
    try:
        version, flag, payload = await hass.async_add_executor_job(
            partial(probe_handshake_reply, coordinator.host, coordinator.device_id,
                    timeout=READ_TIMEOUT)
        )
    except Exception as err:  # noqa: BLE001 - diagnostics must never fail to download
        _LOGGER.debug("could not collect a handshake reply from %s: %s", coordinator.host, err)
        return None
    return {
        "localkey_version": version,
        "flag": flag,
        "payload_len": len(payload),
        "head": payload[:48].hex(),
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: HaismartConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    profile = coordinator.profile
    layout = await _async_layout_summary(hass, coordinator)
    # The cloud's CURRENT decoded value for every declared attribute, fetched now rather than read
    # out of the model stored at onboarding. Paired with the raw report below it turns an unplaced
    # attribute into arithmetic -- find the bits already equal to this known value -- for any
    # family,
    # with nothing asked of the owner. Falls back to nothing when there are no credentials or the
    # cloud is unreachable, which must not stop the rest of the report being produced.
    fresh_shadow = await coordinator.async_fresh_shadow()
    # ⚠️ Under the coordinator's session lock. These appliances accept ONE connection at a time, so
    # a probe fired while a poll or a command is in flight makes one of them fail -- and a
    # diagnostics download taken *because* something is wrong must not manufacture a second fault
    # for the file to record.
    async with coordinator._session:  # noqa: SLF001 - no public accessor, and the lock is the point
        handshake = await _async_handshake_reply(hass, coordinator)
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        # ⚠️ Two numbers, and the pair is the point. This one is the version of the key this entry
        # HOLDS; `localkey_version_reported` below is the version the appliance says it is using
        # right now. Everything the appliance sends is encrypted with the latter, so if they differ
        # the key is stale and nothing will decrypt -- a state that otherwise presents as a refused
        # command, an empty reading, or a protocol bug, depending on which path hits it first.
        # Reporting only the stored one made a bug report unable to answer its own first question.
        "localkey_version": coordinator.localkey_version,
        "localkey_version_reported": (handshake or {}).get("localkey_version"),
        "handshake_reply": handshake,
        "last_update_success": coordinator.last_update_success,
        "state": coordinator.data,
        # raw report bytes (post-decrypt) — carries no secrets, invaluable for offset bugs
        "last_raw_status": (
            coordinator.last_raw_status.hex() if coordinator.last_raw_status else None
        ),
        # The telemetry frame, for the same reason as the status one above: the compressor and
        # refrigeration readings are the least settled part of the map, and without the bytes a
        # disagreement about one of them cannot be checked from a report.
        "last_raw_extended": (
            coordinator.last_raw_extended.hex() if coordinator.last_raw_extended else None
        ),
        # Whether this unit answers the telemetry query at all, and how the answer was reached.
        # Without it, `last_raw_extended: null` has two very different causes that read alike: an
        # appliance that does not carry those sensors, and one we stopped asking. A report of
        # "the power and compressor sensors are empty" cannot be answered from the bytes, because
        # the point is that there are none -- so it has to be stated here.
        #   supported  true  -- it has answered, so the entities are real and the frame is simply
        #                       absent from the most recent session
        #              false -- written off after repeated silence; the entities will not appear
        #              null  -- still being tried, or nothing asked yet
        "extended_status": {
            "supported": coordinator.supports_extended,
            "consecutive_misses": coordinator._extended_misses,
            "misses_before_giving_up": EXTENDED_MISSES,
            "query_form": coordinator._extended_form,
            "query_forms_available": len(EXTENDED_STATUS_FRAME_TYPES),
        },
        # enum codes the device's OWN digital model authorizes for the write path — this is what
        # decides whether e.g. heat is usable on this unit (coordinator._model_authorized_codes)
        "model_authorized_codes": {
            name: sorted(codes) for name, codes in coordinator.model_codes.items()
        },
        # Settings the unit is ignoring in the state it is in, per its own model's rules — the
        # answer to "why is this switch unavailable", which otherwise reads as a broken integration.
        "locked_fields": sorted(coordinator.locked_fields),
        # each locked field with the reason its own model gives, so a report of "the control is
        # missing" carries why without another round trip
        "locked_reasons": dict(sorted(coordinator.locked_reasons.items())),
        # Which commands this appliance is written with, which of them are on trial, and what
        # the last one drew. See _controls_summary.
        "controls": _controls_summary(coordinator),
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
            # The protocol the appliance names in its discovery reply. The manufacturer's library
            # carries three local adapters -- uss_pro (implemented here), uwt and coap -- and this
            # is the only place an appliance names one at all. It selects nothing: every appliance
            # seen announces UWT and is driven with uss_pro regardless. Recorded so that one
            # announcing something different is visible instead of silently unusual.
            "reported_protocol": coordinator.reported_protocol,
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
        "digital_model": _model_summary(coordinator.digital_model, fresh_shadow),
        # Attributes this device declares that its family map does not carry, read off the published
        # map at the family's confirmed displacement. Every unit declares three or four times what
        # any hand-written map holds, so this is most of what a report actually says -- surfaced
        # here first, where a wrong value costs nothing, rather than straight into entities.
        "model_declared_fields": _declared_readings(coordinator),
        # What this particular device IS, kept apart from the profile chosen for it. A report is
        # only useful for adding a new model if it says which device it came from, and
        # `product_code` alone does not: an entry that never learned one falls back to a built-in
        # default, which then reads exactly like a device genuinely carrying that code. Saying
        # which it is separates a usable report from a misleading one.
        "device_identity": {
            "uplus_id": coordinator.uplus_id,
            "product_code": coordinator.product_code,
            "product_code_is_fallback": (
                not entry.data.get(CONF_PRODUCT_CODE)
                and coordinator.product_code == DEFAULT_PRODUCT_CODE
            ),
            # The product class the uPlusId encodes -- an identifier for lookup only. Devices in one
            # class are known to report in different wire families, so it never picks a decoder.
            "device_type_class": device_type_class(coordinator.uplus_id),
            # The device's own deviceType, when onboarding captured it: the same class plus the
            # variant digits, which cannot be derived from the uPlusId. Names unfamiliar hardware
            # exactly in a bug report. Also lookup only, for the same reason as the class above.
            "device_type": coordinator.device_type,
            # Whether the shipped rules and any fetched ones describe the same product.
            # "identity-mismatch" means the stored product code and uPlusId disagree.
            "model_rules_agreement": coordinator.model_rules_agreement,
            # The number printed on the unit, looked up from the product code in the shipped
            # catalogue. Reporters were being asked to transcribe this by hand; it is derivable
            # from something already stored, so ask the catalogue instead of the person.
            "model_number": _model_number(coordinator.product_code),
            # What the Wi-Fi module runs. Two units with the same model sticker behave differently
            # if one shipped with a newer module, so this belongs beside the model rather than only
            # on the device page -- which is NOT part of this file, the one people attach to issues.
            "module_firmware": coordinator.firmware,
            "module_sdk_version": coordinator.sdk_version,
        },
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


def _controls_summary(coordinator) -> dict[str, Any]:
    """Which commands this appliance is written with, which are on trial, and what the last drew.

    The per-attribute command numbers are a per-board registry nothing publishes, so which numbers
    an appliance is being sent cannot be read off anything else in this file -- and one of them may
    be DERIVED rather than observed (``provisional``), in which case the appliance's own answer to
    it is the finding. ``last_control`` is that answer as it arrived: the reply frame types, the
    refusal code, the product's own sentence for it, and whether the control was withdrawn.
    ``class_carried`` is the read/control gate for attributes a device class carries without
    declaring them, with the declared attributes that blocked one where its bits belong to something
    else on this product.
    """
    from haismart_hrdp.features import CARRIED_BLOCKED_BY, CLASS_CARRIED_ENUM_FEATURES

    wm = coordinator._wire_model  # noqa: SLF001 - no public accessor; the registry entry is the fact
    single = {
        name: {"command": f"0x{0x5D00 | p.param_id:04X}", "provisional": p.provisional}
        for name, p in sorted((wm.value_param_fields if wm is not None else {}).items())
    }
    paired = {
        name: {"on": p.on.hex(), "off": None if p.off is None else p.off.hex()}
        for name, p in sorted((wm.single_param_fields if wm is not None else {}).items())
    }
    carried = CLASS_CARRIED_ENUM_FEATURES.get(uplus_class(coordinator.uplus_id), frozenset())
    declared = declared_attribute_names(coordinator.digital_model)
    offered = coordinator._class_carried_controls()  # noqa: SLF001 - the gate itself is the fact
    blocked = {
        n: sorted(CARRIED_BLOCKED_BY.get(n, frozenset()) & declared)
        for n in sorted(carried - offered)
    }
    return {
        "single_param_ids": single,
        "paired_commands": paired,
        "class_carried": {"offered": sorted(offered), "blocked_by_declared": blocked},
        "unusable_params": sorted(coordinator.unusable_params),
        "last_control": coordinator.last_control,
    }


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


def _model_summary(
    model: dict[str, Any] | None, fresh_shadow: dict[str, str] | None = None
) -> dict[str, Any] | None:
    """The parts of the digital model that describe CAPABILITIES.

    The full model is large and contains device-identifying ids, so only the attribute value ranges,
    the values the device currently reports for them, and the grSetDAC attribute order are included
    -- which is all that is needed to work out a layout, and carries no credential. The reported
    values are the same settings the remote shows, alongside raw bytes that already say the same.

    Also which attributes this unit does NOT have. A generic model lists everything the product line
    might carry and marks the rest ``invisible``; that flag is what stops optional features being
    offered for hardware the unit lacks, so whether it is known decides whether those entities can
    be trusted. Summarising the model without it left that unanswerable from a diagnostics file --
    the only evidence was whether the resulting entities happened to look sane.
    """
    # ⚠️ A fresh shadow is worth reporting even when NO model is stored -- a hand-configured entry
    # has none, and that is precisely the install where the cloud's values are the only statement of
    # what this appliance's attributes currently read. Bailing on `not model` threw them away.
    if not model:
        if fresh_shadow is None:
            return None
        return {"reported_values_now": fresh_shadow, "reported_values_now_available": True}
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
    # Present-but-empty and absent mean different things and must not collapse to the same output:
    # empty is "we know, and this unit lacks nothing", absent is "we do not know, so nothing
    # optional is offered". Hence the separate flag rather than an empty list standing for both.
    known = "invisible_attributes" in model
    return {
        "attributes": attributes,
        "groupCommands": group_commands,
        # ⚠️ TWO sets of values, and the difference is load-bearing. `reported_values` is the model
        # STORED AT ONBOARDING and never refreshed since, so it may describe the appliance as it was
        # months ago -- one attachment states `onOffStatus: false` beside a report that decodes the
        # unit as running. `reported_values_now` was fetched while this file was written, so it is
        # the only one that may be compared against `last_raw_status`: pairing a value with the
        # bytes
        # printed next to it is what places an attribute no byte map carries.
        "reported_values": _shadow_values(model),
        "reported_values_now": fresh_shadow,
        "reported_values_now_available": fresh_shadow is not None,
        "feature_set_known": known,
        "invisible_attributes": list(model.get("invisible_attributes") or ()) if known else None,
    }


def _model_number(product_code: str | None) -> str | None:
    """The model number printed on the unit, for a product code the shipped catalogue covers.

    The two are different things and the difference matters in a bug report: `AAC1UKZ01` is the
    product code the integration keys its rules on, `HSU-24VRRA03TF` is what is on the sticker and
    what an owner recognises. The catalogue holds both for every published air conditioner, so a
    report can carry the readable one without anyone typing it.
    """
    if not product_code:
        return None
    rules = rules_for_product(product_code)
    return (rules or {}).get("model") or None
