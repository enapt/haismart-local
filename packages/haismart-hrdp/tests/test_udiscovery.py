"""Tests for the UDISCOVERY_UWT LAN protocol (udiscovery.py).

The vectors below are real 309-byte device-info datagrams, with the deviceId and LAN address
replaced by the illustrative placeholders used throughout this suite (per SECURITY.md). Everything
else — the uPlusId, ports, firmware strings and the TLV area — is left as it appears on the wire, so
these tests pin the decoder against real frames rather than against itself.

The two vectors differ in exactly one byte, offset 0x70: the low byte of the cloud-state TLV, in its
connected and cut-off values.
"""

import struct

import pytest

from haismart_hrdp import udiscovery as ud

DEV = "A1B2C3D4E5F6"  # illustrative deviceId (real ones are the module's MAC)

# Real device-info reply, cloud CONNECTED (state 1000).
REPLY_ONLINE = bytes.fromhex(
    "48616965720000684d020a00000000000000000120" + DEV.encode().hex() + "00000000"
    "2008610800820324021200118012560000000000000000000000000000000040"
    "0000000201" + "20" + DEV.encode().hex() + "00" * 20 +
    "0304000003e8" + "00" * 116 +
    "3139322e3136382e312e353000000000"  # "192.168.1.50"
    "dde0" "000000000000" "322e313800" "000600"
    "655f342e332e3030" "525f362e302e3031"  # firmware "e_4.3.00" / "R_6.0.01"
    "55444953434f564552595f555754" + "00" * 18
)

# Same unit while firewalled off from Haier's cloud: cloud-state TLV reads 1006.
REPLY_OFFLINE = REPLY_ONLINE[:0x70] + b"\xee" + REPLY_ONLINE[0x71:]


def test_reply_vector_is_the_real_shape():
    """Guard the vectors themselves: 309 bytes, and the two differ only in the cloud-state byte."""
    assert len(REPLY_ONLINE) == 309
    differing = [i for i in range(309) if REPLY_ONLINE[i] != REPLY_OFFLINE[i]]
    assert differing == [0x70]


def test_build_query_matches_the_wire_format():
    q = ud.build_query()
    assert q[:5] == b"Haier"
    assert struct.unpack_from(">I", q, 5)[0] == ud.CMD_SEARCH
    assert struct.unpack_from(">I", q, 0x11)[0] == len(q) - ud.HEADER_LEN == 56
    # both literals are validated by the device -- zeroing either gets no answer at all
    assert q[ud.HEADER_LEN + 0x10 :].startswith(b"2.0.0")
    assert q[ud.HEADER_LEN + 0x18 :].startswith(b"UDISCOVERY_SDK")


def test_parse_reply_decodes_every_identity_field():
    info = ud.parse_reply(REPLY_ONLINE)
    assert info is not None
    assert info.device_id == DEV
    assert info.host == "192.168.1.50"
    assert info.port == 56800  # the uSS control port, self-reported
    assert info.sdk_version == "2.18"
    assert info.firmware == ("e_4.3.00", "R_6.0.01")


def test_uplus_id_is_bcd_and_matches_the_cloud_device_list():
    """The uPlusId is BCD-packed binary, not text.

    Decoding it as ASCII yields garbage; hex-encoding reproduces the cloud device list's `wifiType`
    exactly, which is what makes offline wire-model selection possible.
    """
    info = ud.parse_reply(REPLY_ONLINE)
    assert info is not None
    assert info.uplus_id == (
        "2008610800820324021200118012560000000000000000000000000000000040"
    )


def test_cloud_state_reflects_reachability():
    online = ud.parse_reply(REPLY_ONLINE)
    offline = ud.parse_reply(REPLY_OFFLINE)
    assert online is not None and offline is not None
    assert online.cloud_state == ud.CLOUD_STATE_CONNECTED == 1000
    assert online.cloud_connected is True
    assert offline.cloud_state == 1006
    assert offline.cloud_connected is False


def test_unknown_cloud_state_is_not_reported_as_connected():
    """Only 1000 means connected. The rest of the code space is undocumented, so an unrecognised
    value must not be optimistically read as "online"."""
    mutated = REPLY_ONLINE[:0x6D] + struct.pack(">I", 4242) + REPLY_ONLINE[0x71:]
    info = ud.parse_reply(mutated)
    assert info is not None
    assert info.cloud_state == 4242
    assert info.cloud_connected is False


def test_missing_cloud_state_tlv_reads_unknown_not_false():
    """A device that reports no state TLV is unknown, not disconnected -- the entity must go
    unavailable rather than claim the cloud is down."""
    without = REPLY_ONLINE[:0x6B] + b"\x00" * 6 + REPLY_ONLINE[0x71:]
    info = ud.parse_reply(without)
    assert info is not None
    assert info.cloud_state is None
    assert info.cloud_connected is None


def test_tlvs_are_walked_by_type_not_fixed_offset():
    """The TLV area is a fixed-size region whose populated part varies by device, so the decoder
    walks records. Swapping the record order must not move the answer."""
    state_tlv = REPLY_ONLINE[0x6B:0x71]
    id_tlv = REPLY_ONLINE[0x49:0x6B]
    reordered = REPLY_ONLINE[:0x49] + state_tlv + id_tlv + REPLY_ONLINE[0x71:]
    info = ud.parse_reply(reordered)
    assert info is not None
    assert info.cloud_state == 1000


@pytest.mark.parametrize(
    "bad",
    [
        b"",
        b"Haier",
        b"Xaier" + REPLY_ONLINE[5:],  # wrong magic
        REPLY_ONLINE[:0x40],  # truncated inside the identity block
        b"Haier" + struct.pack(">I", 0x6915) + REPLY_ONLINE[9:],  # a query, not a reply
    ],
)
def test_parse_reply_rejects_non_replies(bad):
    assert ud.parse_reply(bad) is None


def test_short_reply_still_yields_identity():
    """An unfamiliar appliance whose reply stops after the TLV area should still be identified --
    the tail fields are optional, so we degrade to a partial answer instead of nothing."""
    info = ud.parse_reply(REPLY_ONLINE[:0x71])
    assert info is not None
    assert info.device_id == DEV
    assert info.cloud_connected is True
    assert info.host == ""
    assert info.port == 0


def test_tlv_count_cannot_run_away():
    """The count field is device-supplied; a silly value must not spin or over-read."""
    huge = REPLY_ONLINE[:0x45] + struct.pack(">I", 0xFFFFFFFF) + REPLY_ONLINE[0x49:]
    info = ud.parse_reply(huge)
    assert info is not None
    assert info.device_id == DEV


def test_retrying_state_is_not_connected():
    """1010 is what a module reports for the first couple of minutes of an outage — before it
    settles on 1006. A decoder that treated "not 1006" as connected would call an AC online for
    that whole window."""
    retrying = REPLY_ONLINE[:0x6D] + struct.pack(">I", 1010) + REPLY_ONLINE[0x71:]
    info = ud.parse_reply(retrying)
    assert info is not None
    assert info.cloud_state == 1010
    assert info.cloud_connected is False
    assert info.cloud_state_name == "retrying"


def test_state_names_cover_only_what_was_observed():
    assert ud.CLOUD_STATES == {1000: "connected", 1010: "retrying", 1006: "disconnected"}
    unknown = REPLY_ONLINE[:0x6D] + struct.pack(">I", 4242) + REPLY_ONLINE[0x71:]
    info = ud.parse_reply(unknown)
    assert info.cloud_state_name is None      # unnamed, but still...
    assert info.cloud_connected is False      # ...not connected


def test_the_reply_tail_names_a_protocol():
    """The last 32 bytes of a reply were never parsed, and an appliance names a protocol there.

    The manufacturer's library carries three local adapters — `adapter_uss_pro` (what this library
    implements), `adapter_local_dev_user_uwt` and `adapter_local_dev_user_coap` — and this tail is
    the only place an appliance names one at all.

    ⚠️ It does NOT select the adapter, and must not be treated as if it did: real appliances
    announce `UDISCOVERY_UWT` here and are driven with `uss_pro` successfully. It is parsed so that
    one announcing something different can be seen, not acted upon.
    """
    from haismart_hrdp.udiscovery import parse_reply

    reply = bytearray(0x135)
    reply[0:5] = b"Haier"
    struct.pack_into(">I", reply, 5, 0x684D)
    reply[0x15:0x15 + 12] = b"ACB722AABBCC"
    reply[0x115:0x115 + 14] = b"UDISCOVERY_UWT"
    info = parse_reply(bytes(reply))
    assert info is not None
    assert info.protocol_tag == "UDISCOVERY_UWT"

    # a reply that stops before the tail is not an appliance without a protocol, it is a shorter
    # reply -- so the field is empty rather than the parse failing
    short = parse_reply(bytes(reply[:0x110]))
    assert short is not None and short.protocol_tag == ""
