"""haismart-hrdp — standalone async client for Haier's local uSS/HRDP protocol.

Home-Assistant-agnostic. The local protocol lives in ``uss.py``:

    import haismart_hrdp as h

    profile = h.profile_for("AAC1UKZ01")
    blobs = await h.async_read_status("192.168.1.50", "A1B2C3D4E5F6", localkey)
    state = next(h.parse_full_status(b, profile) for b in blobs if h.parse_full_status(b, profile))

    # control: group-set seeded from a live status blob; the encoder refuses non-confirmed field/values
    raw = next(b for b in blobs if h.status_layout(b) is not None)
    words = h.set_grsetdac_field(h.grsetdac_baseline_from_status(raw), "targetTemperature", 25 - 16)
    await h.async_send_op("192.168.1.50", "A1B2C3D4E5F6", localkey, h.grsetdac_op_frame(words), counter=1)
"""
from __future__ import annotations

from .canonical_map import CANONICAL, DISPLACEMENTS, CanonicalField
from .device_rules import DEVICE_RULES, RULE_SECTIONS, merge_rules, rules_for, with_rules
from .models import AttributeProfile
from .profiles import (
    AAC1UKZ01,
    AAC1UKZ01_ATTRIBUTES,
    PROFILES,
    alarm_names,
    constraint_commands,
    locked_attributes,
    model_enum_codes,
    profile_for,
    profile_from_device_config,
    validate_write,
    writable_attributes,
)
from .udiscovery import (
    CLOUD_STATE_CONNECTED,
    CLOUD_STATES,
    DeviceInfo,
    async_query,
    build_query,
    discover,
    parse_reply,
    query,
)
from .uss import (
    EPP_CMD_GRSETDAC,
    GRSETDAC_ALLOWED_VALUES,
    GRSETDAC_ENUMS,
    GRSETDAC_FIELDS,
    GRSETDAC_MODEL_AUTHORIZED,
    STATUS_LAYOUTS,
    HelloResp,
    Message,
    StatusContainer,
    StatusLayout,
    alarm_label,
    async_read_status,
    async_send_op,
    biz_decrypt,
    biz_encrypt,
    build_cae_op_envelope,
    build_cae_op_request,
    build_epp_frame,
    build_op_message,
    build_op_request_message,
    check_hello_resp,
    decode_message,
    derive_status_layout,
    encode_message,
    extended_status_epp_frame,
    getallproperty_epp_frame,
    grsetdac_baseline_from_status,
    grsetdac_op_frame,
    hello_done_message,
    hello_message,
    localkey_aes_key,
    parse_alarm_frame,
    parse_extended_status,
    parse_full_status,
    parse_hello_resp,
    parse_status_container,
    probe_localkey_version,
    read_grsetdac_field,
    read_status,
    set_grsetdac_field,
    status_layout,
)
from .wire_models import (
    VANE_V_EPP_TO_MODEL,
    VANE_V_MODEL_TO_EPP,
    WIRE_MODELS,
    StatedState,
    WireField,
    WireModel,
    WriteField,
    probe_layout,
    select_wire_model,
)

__version__ = "0.1.0"

__all__ = [
    # READ
    "read_status",
    "async_read_status",
    "hello_message",
    "hello_done_message",
    "encode_message",
    "decode_message",
    "Message",
    "biz_encrypt",
    "biz_decrypt",
    "localkey_aes_key",
    "parse_status_container",
    "alarm_label",
    "parse_alarm_frame",
    "parse_extended_status",
    "parse_full_status",
    "status_layout",
    "derive_status_layout",
    "StatusLayout",
    "STATUS_LAYOUTS",
    # per-family wire models (non-classic report layouts)
    "WireModel",
    "WireField",
    "WriteField",
    "WIRE_MODELS",
    "select_wire_model",
    "probe_layout",
    "StatedState",
    "VANE_V_MODEL_TO_EPP",
    "CANONICAL",
    "CanonicalField",
    "DISPLACEMENTS",
    "VANE_V_EPP_TO_MODEL",
    "StatusContainer",
    "parse_hello_resp",
    "check_hello_resp",
    "HelloResp",
    "probe_localkey_version",
    # CONTROL / write
    "build_epp_frame",
    "extended_status_epp_frame",
    "getallproperty_epp_frame",
    "build_cae_op_request",         # outbound CAE op envelope
    "build_op_request_message",     # full outbound op message
    "set_grsetdac_field",           # grSetDAC field encoder (fire-safe allowlist)
    "GRSETDAC_FIELDS",
    "GRSETDAC_ENUMS",
    "GRSETDAC_ALLOWED_VALUES",
    "GRSETDAC_MODEL_AUTHORIZED",
    "grsetdac_baseline_from_status",
    "grsetdac_op_frame",
    "read_grsetdac_field",
    "async_send_op",                # WRITE session (user-authorized control only)
    "EPP_CMD_GRSETDAC",
    "build_cae_op_envelope",        # inbound report-envelope reconstruction
    "build_op_message",             # low-level op message; prefer build_op_request_message
    # UDISCOVERY (UDP :7083) — key-free LAN discovery + cloud-connectivity state
    "DeviceInfo",
    "query",
    "async_query",
    "discover",
    "build_query",
    "parse_reply",
    "CLOUD_STATE_CONNECTED",
    "CLOUD_STATES",
    # per-model attribute profiles
    "AttributeProfile",
    "profile_for",
    "profile_from_device_config",
    "validate_write",
    "writable_attributes",
    "model_enum_codes",
    "constraint_commands",
    "locked_attributes",
    "alarm_names",
    "DEVICE_RULES",
    "rules_for",
    "merge_rules",
    "RULE_SECTIONS",
    "with_rules",
    "AAC1UKZ01",
    "AAC1UKZ01_ATTRIBUTES",
    "PROFILES",
    "__version__",
]
