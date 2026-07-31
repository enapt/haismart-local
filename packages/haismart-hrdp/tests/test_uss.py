"""Tests for the uSS local protocol (uss.py).

The status/handshake byte vectors are real wire structures, so these tests pin behaviour against
ground truth, not just internal self-consistency. The deviceId and localKey below are illustrative
placeholders — no real device credential is committed; the status blobs carry no secret (they are the
decrypted sensor readings).
"""

import pytest

from haismart_hrdp import uss

DEV = "A1B2C3D4E5F6"  # illustrative deviceId (real ones are the module's MAC)
LOCALKEY = "0123456789abcdef0123456789abcdef"  # illustrative — not a real device key

# HELLO the client sends (real 48-byte structure), and the AC's HELLO_RESP
REAL_HELLO = bytes.fromhex(
    "0000ea60002a01000000000100000000" + DEV.encode().hex() + "00" * 20
)
REAL_HELLO_RESP = bytes.fromhex("0000ea610012010000000001000089fc0000000100000004")
# The HELLO_RESP payload a real AC sends: status=1 (session accepted) + its localKey version. The
# fakes below used an EMPTY payload, which parses as status=0 -> a refusal. That unrealistic fixture
# is why nothing noticed that no call site ever checked the status field.
HELLO_RESP_OK = bytes.fromhex("0000000100000004")
# real decrypted status blob (127B), typeId AAC1UKZ01
REAL_STATUS = bytes.fromhex(
    "00002715000000004e56010000030200000401" + "00" * 66
    + "2fffff2c000000000000066d010808c30002010007080000003c005e80000f" + "00" * 15 + "ae"
)


def test_hello_message_matches_hardware():
    assert uss.hello_message(DEV, sn=1, pro_ver=2) == REAL_HELLO
    assert len(REAL_HELLO) == 48


def test_decode_real_hello_resp():
    m = uss.decode_message(REAL_HELLO_RESP)
    assert m.info_code == 0xEA61
    assert m.info_type == uss.INFO_HELLO_RESP
    assert m.sn == 1               # AC echoes our sn
    assert m.session == 0x89FC     # AC-assigned session
    assert m.payload == bytes.fromhex("0000000100000004")  # status=1, localkey_ver=4


def test_hello_done_message():
    b = uss.hello_done_message(sn=2, session=0x89FC, pro_ver=2)
    m = uss.decode_message(b)
    assert m.info_type == uss.INFO_HELLO_DONE and m.info_code == 0xEA62
    assert m.sn == 2 and m.session == 0x89FC and m.payload == b""
    assert b == bytes.fromhex("0000ea62000a0100000000020000" "89fc")


def test_message_roundtrip():
    b = uss.encode_message(7, 42, b"hello-body", type_byte=0x6E, flag=1, session=0x1234)
    m = uss.decode_message(b)
    assert (m.info_type, m.sn, m.flag, m.session, m.payload) == (7, 42, 1, 0x1234, b"hello-body")


def test_split_messages():
    buf = uss.hello_message(DEV) + REAL_HELLO_RESP + uss.hello_done_message(2, 0x1)
    parts = list(uss.split_messages(buf))
    assert len(parts) == 3
    assert uss.decode_message(parts[1]).info_code == 0xEA61


def test_localkey_aes_key():
    assert uss.localkey_aes_key(LOCALKEY).hex() == \
        __import__("hashlib").md5(LOCALKEY.encode()).hexdigest()
    assert len(uss.localkey_aes_key(LOCALKEY)) == 16


def test_biz_roundtrip_and_integrity():
    data = b'\x00\x00\x27\x15\x00\x00\x00\x00status-bytes-here'
    ct = uss.biz_encrypt(0x11223344, data, LOCALKEY)
    # real biz payloads are AES-CBC ciphertext (16-multiple) + a 5-digit ASCII transport nonce trailer
    assert len(ct) % 16 == 5
    assert ct[-5:].isdigit()
    sn, out = uss.biz_decrypt(ct, LOCALKEY)
    assert sn == 0x11223344 and out == data


def test_biz_encrypt_reproduces_real_frame_byte_exact():
    # A biz-data frame (trailer nonce = "24225"): given the same nonce + fields, the
    # encoder must reproduce the ENTIRE payload incl. the 5-digit trailer the AC requires.
    inner = b'\x00\x00\x27\x14control-op-bytes'
    nonce = b"24225"
    ct = uss.biz_encrypt(7, inner, LOCALKEY, pre4=nonce)
    assert ct[-5:] == nonce                        # trailer appended
    # the plaintext pre4 is the trailer's first 4 digits
    pt = uss._cbc(uss.localkey_aes_key(LOCALKEY), ct[: (len(ct) // 16) * 16], decrypt=True)
    assert pt[38:42] == nonce[:4]
    sn, out = uss.biz_decrypt(ct, LOCALKEY)
    assert sn == 7 and out == inner


def test_biz_decrypt_wrong_key_raises():
    ct = uss.biz_encrypt(1, b"payload-data-1234", LOCALKEY)
    with pytest.raises(ValueError):  # MD5 check fails on a wrong/stale key — the re-pull signal
        uss.biz_decrypt(ct, "00" * 16)


def test_parse_status_container():
    c = uss.parse_status_container(REAL_STATUS)
    assert c.header == REAL_STATUS[:13]
    assert c.attr_region == REAL_STATUS[13:]
    assert c.raw == REAL_STATUS


# 127B full-status blobs (two units)
REAL_STATUS_DOWN = bytes.fromhex(
    "00002715000000004e560100000302000004010000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000002fffff2c000000000000066d010808c30002010007080000003c005e80000f00000000000000000000000000000000ae")
REAL_STATUS_UP = bytes.fromhex(
    "00002715000000004e560100000302000004010000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000002fffff2c000000000000066d010700220002000007080000003e005e80000300000000000000000000000000000000f9")


def test_parse_full_status_confirmed_fields():
    from haismart_hrdp import profile_for
    prof = profile_for("AAC1UKZ01")
    # Downstairs: ON, target 24, indoor 30.0, mode 6=fan_only, fan 3=low (byte[94]=0xc3),
    #   vertical vane byte[93]=0x08 -> position four, PARKED. The vane field is a position code and
    #   only 0x0C/0x0E are auto; this previously asserted True via a single-bit test that also
    #   matched the parked-low codes 8 and 10.
    # secondary toggles read back from the same grSetDAC word block: both units have only the display
    # light on (lamp=True); health/strong/quiet/sleep off and eco=0 (computed from the real blobs)
    _toggles = {"health": False, "strong": False, "quiet": False, "sleep": False, "lamp": True, "eco": 0,
                "swing_horizontal": True,
                # both reference units are cooling-only and say so: the flag after the outdoor
                # reading is set. A reverse-cycle unit clears it.
                "heat_capable": False, "error_code": 0, "last_changed_by": "network",
                "self_cleaning": False}  # both units report word4 bits0-2 == 7 (left-right auto)
    d = uss.parse_full_status(REAL_STATUS_DOWN, prof)
    assert d == {"power": True, "target_temperature": 24.0, "current_temperature": 30.0,
                 "operation_mode": "6", "wind_speed": "3", "swing_vertical": False,
                 "outdoor_temperature": 30.0, **_toggles, "mode": "fan_only", "fan_mode": "low"}
    # Upstairs: OFF, target 23, indoor 31.0, mode 1=cool, fan 2=medium, swing off, outdoor 30
    u = uss.parse_full_status(REAL_STATUS_UP, prof)
    assert u == {"power": False, "target_temperature": 23.0, "current_temperature": 31.0,
                 "operation_mode": "1", "wind_speed": "2", "swing_vertical": False,
                 "outdoor_temperature": 30.0, **_toggles, "mode": "cool", "fan_mode": "medium"}
    # without a profile: raw STD codes only (still includes the secondary toggles)
    assert uss.parse_full_status(REAL_STATUS_UP) == {
        "power": False, "target_temperature": 23.0, "current_temperature": 31.0,
        "operation_mode": "1", "wind_speed": "2", "swing_vertical": False,
        "outdoor_temperature": 30.0, **_toggles}
    # non-full-status blob -> empty (no fabrication)
    assert uss.parse_full_status(b"\x00\x00\x27\x15short") == {}


def test_hello_v3_shape():
    b = uss.hello_message(DEV, sn=1, pro_ver=3, arg8=0, arg7=0)
    m = uss.decode_message(b)
    assert m.type_byte == 0x6E and len(m.payload) == 40  # deviceId[32] + arg8 + arg7


def test_hello_message_rejects_bad_pro_ver():
    with pytest.raises(ValueError):
        uss.hello_message(DEV, pro_ver=5)


class _FragSock:
    """A socket stub that hands back the buffer in small chunks, to exercise reassembly."""
    def __init__(self, data, chunk=5):
        self.data, self.chunk, self.i = data, chunk, 0

    def recv(self, _n):
        c = self.data[self.i:self.i + self.chunk]
        self.i += len(c)
        return c


def test_recv_message_reassembles_tcp_fragments():
    full = REAL_HELLO_RESP  # a real 24-byte HELLO_RESP, delivered 5 bytes at a time
    m = uss._recv_message(_FragSock(full, chunk=5))
    assert m.info_type == uss.INFO_HELLO_RESP and m.session == 0x89FC and len(m.payload) == 8


def test_recv_message_raises_on_early_close():
    with pytest.raises(RuntimeError):
        uss._recv_message(_FragSock(REAL_HELLO_RESP[:10], chunk=5))  # closes mid-message


# --- write/op path builders ---

def test_getallproperty_frame_matches_re():
    # The exact bytes from the wire model (the read-only probe frame). eppCmd 4D01, frameType 1.
    assert uss.getallproperty_epp_frame() == bytes.fromhex("ffff0a000000000000014d0159")
    assert uss.getallproperty_epp_frame()[10:12] == uss.EPP_CMD_GETALLPROPERTY  # 4D01, read-only


def test_epp_frame_checksum_reproduces_real_report():
    # Rebuild the real DOWN report frame (frameType 06, cmd 6D01, 34 data bytes) from its own data and
    # assert the builder reproduces it byte-exact — proving structure + the (len+payload)&0xFF checksum.
    real_frame = REAL_STATUS_DOWN[80:]                       # ff ff .. ae, 47 bytes
    data = real_frame[12:-1]                                 # after 00*6|06|6d01, before checksum
    assert uss.build_epp_frame(0x06, b"\x6d\x01", data) == real_frame
    assert real_frame[-1] == 0xAE                            # the real checksum
    # UP frame too (checksum 0xF9)
    up = REAL_STATUS_UP[80:]
    assert uss.build_epp_frame(0x06, b"\x6d\x01", up[12:-1]) == up and up[-1] == 0xF9


def test_grsetdac_set_to_current_matches_re():
    # grSetDAC (6001) with DOWN's live words1-5 -> the exact candidate frame in the wire model.
    words1_5 = REAL_STATUS_DOWN[80:][12:12 + 10]  # the 5 BE16 words after 06 6d01 in the real report
    assert words1_5 == bytes.fromhex("0808c300020100070800")
    assert uss.build_epp_frame(0x01, uss.EPP_CMD_GRSETDAC, words1_5) == \
        bytes.fromhex("ffff140000000000000160010808c3000201000708005b")


def test_epp_frame_rejects_bad_cmd_length():
    with pytest.raises(ValueError):
        uss.build_epp_frame(0x01, b"\x4d")  # eppCmd must be exactly 2 bytes


def test_cae_prefix_is_the_real_report_prefix():
    # CAE_REPORT_PREFIX must be byte-identical to bytes [0:78] of a real status blob (both units share it).
    assert uss.CAE_REPORT_PREFIX == REAL_STATUS_DOWN[:78] == REAL_STATUS_UP[:78]
    assert len(uss.CAE_REPORT_PREFIX) == 78
    assert uss.CAE_CONTAINER_HEADER == REAL_STATUS_DOWN[:13]


def test_cae_envelope_reproduces_real_status_blob():
    # Feeding the real report frame back through the envelope builder must reproduce the real blob.
    assert uss.build_cae_op_envelope(REAL_STATUS_DOWN[80:]) == REAL_STATUS_DOWN
    assert uss.build_cae_op_envelope(REAL_STATUS_UP[80:]) == REAL_STATUS_UP


def test_outbound_getallproperty_envelope_matches_findings():
    # The candidate outbound biz-data from the wire model §4b: prefix | 000d | getAllProperty.
    env = uss.build_cae_op_envelope(uss.getallproperty_epp_frame())
    assert env == uss.CAE_REPORT_PREFIX + bytes.fromhex("000d") + \
        bytes.fromhex("ffff0a000000000000014d0159")
    assert env[78:80] == bytes.fromhex("000d")  # frameLen BE16 = 13


def test_build_op_message_roundtrips_through_biz_and_framing():
    sn, session, info_type = 0x00000005, 0x1234, 0x64  # 0x64 -> info_code 0xEAC4 (a candidate)
    msg = uss.build_op_message(sn, uss.getallproperty_epp_frame(), LOCALKEY, session,
                               info_type=info_type)
    m = uss.decode_message(msg)
    assert m.info_type == info_type and m.info_code == 0xEA60 + info_type
    assert m.flag == uss.FLAG_BIZ_ENCRYPTED and m.session == session and m.sn == sn
    dec_sn, envelope = uss.biz_decrypt(m.payload, LOCALKEY)
    assert dec_sn == sn
    assert envelope == uss.build_cae_op_envelope(uss.getallproperty_epp_frame())


# --- outbound op — pinned to a real control frame ---------------------------------------
# A "set temperature +1" (grSetDAC) op. The inner EPP frame
# below is the exact on-wire command (no secret — it is the AC's own control bytes); the CAE envelope
# structure is pinned via a placeholder deviceId so no real device MAC is committed. This is the ground
# truth that unblocked the write path (the protocol).
REAL_GRSETDAC_EPP = bytes.fromhex("ffff160000000000000160010c0422000201000708000000bc")
REAL_GRSETDAC_WORDS = bytes.fromhex("0c0422000201000708000000")  # word[0]=0x0c = setpoint (was 0x0b)


def test_build_epp_frame_reproduces_real_grsetdac():
    # The positional frame + checksum rule reproduces a SET command exactly.
    frame = uss.build_epp_frame(0x01, uss.EPP_CMD_GRSETDAC, REAL_GRSETDAC_WORDS)
    assert frame == REAL_GRSETDAC_EPP
    assert frame[-1] == 0xBC                      # checksum (len + sum(payload)) & 0xFF
    assert frame[10:12] == uss.EPP_CMD_GRSETDAC   # eppCmd 0x6001 = grSetDAC


def test_build_cae_op_request_matches_real_envelope_structure():
    # Reconstruct the confirmed outbound CAE envelope for a placeholder device and pin its layout.
    env = uss.build_cae_op_request(REAL_GRSETDAC_EPP, DEV, counter=5)
    assert env[0:4] == bytes.fromhex("00002714")              # op type (reports are 0x2715)
    assert env[4:40] == b"\x00" * 36                          # reserved
    assert env[40:52] == DEV.encode() and env[52:72] == b"\x00" * 20  # 32-byte deviceId field
    assert env[72:76] == bytes.fromhex("00000005")            # counter BE32
    assert env[76:80] == bytes.fromhex("00000019")            # epplen BE32 = 25
    assert env[80:] == REAL_GRSETDAC_EPP


def test_build_op_request_message_roundtrips_and_pins_envelope():
    sn, session, counter = 0x00000223, 0x9C10, 5
    msg = uss.build_op_request_message(sn, REAL_GRSETDAC_EPP, LOCALKEY, session,
                                       device_id=DEV, counter=counter)
    m = uss.decode_message(msg)
    assert m.info_code == 0xEAC4 and m.flag == uss.FLAG_BIZ_ENCRYPTED
    assert m.session == session and m.sn == sn
    dec_sn, envelope = uss.biz_decrypt(m.payload, LOCALKEY)
    assert dec_sn == sn
    assert envelope == uss.build_cae_op_request(REAL_GRSETDAC_EPP, DEV, counter)


# grSetDAC field encoder — each (before, field, epp_value) -> after exercises one single-field
# transition across a temp/mode/fan/power/toggle sweep, so these exercise the bit map end to end.
@pytest.mark.parametrize("before,name,value,after", [
    ("0c0422000200000708000000", "onOffStatus",       1,    "0c0422000201000708000000"),  # power on
    ("0c0422000201000708000000", "windSpeed",         1,    "0c0421000201000708000000"),  # fan -> high
    ("0c0421000201000708000000", "targetTemperature", 11,   "0b0421000201000708000000"),  # 28 -> 27C
    ("0800050002030007080c0000", "operationMode",     2,    "0800450002030007080c0000"),  # auto -> dry
    ("090025000211000708000000", "healthMode",        1,    "090025000213000708000000"),  # health on
    ("090023000201000708000000", "rapidMode",         1,    "090023000209000708000000"),  # rapid on
    # eco-only + up/down-only transitions:
    ("0800230002030007080c0000", "ecoMode",           5,    "080023000203002f080c0000"),  # eco off -> L5
    ("0800230002030007080c0000", "ecoMode",           6,    "0800230002030037080c0000"),  # eco off -> L6
    ("080023000203002f080c0000", "ecoMode",           0,    "0800230002030007080c0000"),  # eco -> off
    ("0800230002030007080c0000", "windDirectionVertical", 0x0c, "080c230002030007080c0000"),  # up/down on
    ("080c230002030007080c0000", "windDirectionVertical", 0,    "0800230002030007080c0000"),  # up/down off
])
def test_set_grsetdac_field_reproduces_real_transitions(before, name, value, after):
    assert uss.set_grsetdac_field(bytes.fromhex(before), name, value) == bytes.fromhex(after)


def test_set_grsetdac_field_refuses_unmapped_fields():
    words = bytes.fromhex("0c0422000201000708000000")
    # NB windDirectionHorizontal used to be listed here; it is now a confirmed field (word4 bits
    # 0-2), so an invalid VALUE for it raises ValueError instead — see the test below.
    for unmapped in ("energySavingStatus", "lightStatus", "notARealAttr"):
        with pytest.raises(KeyError):
            uss.set_grsetdac_field(words, unmapped, 1)


def test_set_grsetdac_field_refuses_unobserved_values():
    # Values the app was never seen to send must be refused, even for mapped fields.
    words = bytes.fromhex("0800230002030007080c0000")
    with pytest.raises(ValueError):
        uss.set_grsetdac_field(words, "ecoMode", 3)             # 3 is not one of {0,5,6,7}
    with pytest.raises(ValueError):
        uss.set_grsetdac_field(words, "windDirectionVertical", 8)   # model's 8, but app uses 0x0c
    with pytest.raises(ValueError):
        uss.set_grsetdac_field(words, "operationMode", 3)       # 3 is not a valid mode
    with pytest.raises(ValueError):
        uss.set_grsetdac_field(words, "targetTemperature", 20)  # 20 -> 36 degC, out of 16..30 range


# --- values authorized by the DEVICE's own digital model (heat on a heat-pump unit) ---------------
# Our reference units are cooling-only, so heat (operationMode 4) is not in the observed allowlist.
# A device whose model declares the code may use it; a device that doesn't, may not.
def test_model_declared_mode_is_encodable_but_not_by_default():
    """A code with no evidence behind it needs the device's own model to authorize it.

    (Heat, 4, is no longer such a code — it is hardware-confirmed and sits in the base allowlist.
    Mode 3 is: it is a valid 3-bit value that no unit we have seen uses, which is exactly the shape
    of an unverified code, so it stands in for "a capability only this model claims".)
    """
    auto = bytes.fromhex("0800050002030007080c0000")            # operationMode = 0 (auto)
    with pytest.raises(ValueError):
        uss.set_grsetdac_field(auto, "operationMode", 3)        # unauthorized: no model says so
    mode3 = uss.set_grsetdac_field(auto, "operationMode", 3, model_values={0, 1, 2, 3, 6})
    assert mode3 == bytes.fromhex("0800650002030007080c0000")    # mode bits (word2 b13) = 3
    # everything else in the group-set is untouched
    assert uss.set_grsetdac_field(mode3, "operationMode", 0, model_values={0, 3}) == auto
    # heat needs no model to authorize it any more: confirmed on real heat-capable hardware
    assert uss.set_grsetdac_field(auto, "operationMode", 4) == bytes.fromhex(
        "0800850002030007080c0000"
    )


def test_model_values_cannot_widen_device_specific_fields_or_overflow():
    words = bytes.fromhex("0800230002030007080c0000")
    # windDirectionVertical/ecoMode have no matching model attribute (this unit repurposes them), so
    # the model is not allowed to authorize values for them — the observed set stays the authority.
    with pytest.raises(ValueError):
        uss.set_grsetdac_field(words, "windDirectionVertical", 8, model_values={0, 8})
    with pytest.raises(ValueError):
        uss.set_grsetdac_field(words, "ecoMode", 1, model_values={0, 1})
    # a code that doesn't fit the field would silently corrupt neighbouring attributes
    with pytest.raises(ValueError):
        uss.set_grsetdac_field(words, "operationMode", 8, model_values={8})


# --- control (grSetDAC) baseline + field read/write pipeline (HA layer building blocks) -------------
def test_grsetdac_baseline_extracted_from_real_report():
    base = uss.grsetdac_baseline_from_status(REAL_STATUS_DOWN)
    assert len(base) == 12 and base == REAL_STATUS_DOWN[92:104]
    with pytest.raises(ValueError):
        uss.grsetdac_baseline_from_status(b"\x00\x00\x99\x99" + b"\x00" * 200)  # not a 0x2715 report


def test_read_grsetdac_field_agrees_with_parse_full_status():
    from haismart_hrdp import profile_for
    prof = profile_for("AAC1UKZ01")
    st = uss.parse_full_status(REAL_STATUS_DOWN, prof)
    assert uss.read_grsetdac_field(REAL_STATUS_DOWN, "targetTemperature") == st["target_temperature"] - 16
    assert uss.read_grsetdac_field(REAL_STATUS_DOWN, "operationMode") == int(st["operation_mode"])
    assert uss.read_grsetdac_field(REAL_STATUS_DOWN, "windSpeed") == int(st["wind_speed"])
    assert uss.read_grsetdac_field(REAL_STATUS_DOWN, "onOffStatus") == int(st["power"])


def test_control_pipeline_baseline_to_frame_preserves_other_fields():
    # Change ONLY the setpoint; every other read-back field must be unchanged (group-set safety).
    base = uss.grsetdac_baseline_from_status(REAL_STATUS_DOWN)
    before = {f: uss.read_grsetdac_field(REAL_STATUS_DOWN, f)
              for f in ("operationMode", "windSpeed", "onOffStatus")}
    new_words = uss.set_grsetdac_field(base, "targetTemperature", 26 - 16)  # -> 26 degC
    frame = uss.grsetdac_op_frame(new_words)
    assert frame[:2] == b"\xff\xff" and frame[10:12] == uss.EPP_CMD_GRSETDAC
    assert frame[-1] == (frame[2] + sum(frame[3:-1])) & 0xFF   # checksum holds
    # rebuild a report-shaped blob to read the fields back
    rebuilt = REAL_STATUS_DOWN[:92] + new_words + REAL_STATUS_DOWN[104:]
    assert uss.read_grsetdac_field(rebuilt, "targetTemperature") == 10
    for f, v in before.items():
        assert uss.read_grsetdac_field(rebuilt, f) == v


# --- async_send_op returns promptly after the reply burst (no full-timeout drain) -------------------
async def test_send_op_returns_promptly_after_reply_burst(monkeypatch):
    """The AC pushes its updated status right after the op, then holds the socket open and silent.
    async_send_op must return shortly after that burst (a short idle window), NOT block for the whole
    op ``timeout`` — the bug that made HA's state lag seconds behind the unit. It must still return the
    status blob so the caller can confirm the new state."""
    import asyncio
    import time

    SESSION = 0x1234
    hello_resp = uss.encode_message(uss.INFO_HELLO_RESP, 1, HELLO_RESP_OK, session=SESSION)
    done_resp = uss.encode_message(
        uss.INFO_HELLO_DONE_RESP, 2, uss.biz_encrypt(0, (547).to_bytes(4, "big"), LOCALKEY),
        flag=uss.FLAG_BIZ_ENCRYPTED, session=SESSION,
    )
    status = uss.encode_message(
        0x64, 3, uss.biz_encrypt(547, REAL_STATUS_DOWN, LOCALKEY),
        flag=uss.FLAG_BIZ_ENCRYPTED, session=SESSION,
    )

    reader = asyncio.StreamReader()
    reader.feed_data(hello_resp + done_resp)  # handshake available up front

    class FakeWriter:
        def __init__(self) -> None:
            self.writes = 0

        def write(self, data: bytes) -> None:
            self.writes += 1
            if self.writes == 3:  # the op write -> the AC now emits its updated status, then falls silent
                reader.feed_data(status)

        async def drain(self) -> None:
            pass

        def close(self) -> None:
            pass

        async def wait_closed(self) -> None:
            pass

    async def fake_open(ip, port):
        return reader, FakeWriter()

    monkeypatch.setattr(asyncio, "open_connection", fake_open)

    t0 = time.monotonic()
    blobs = await uss.async_send_op(
        "1.2.3.4", DEV, LOCALKEY, REAL_GRSETDAC_EPP, counter=1, timeout=5.0
    )
    elapsed = time.monotonic() - t0

    assert REAL_STATUS_DOWN in blobs           # the updated state was captured
    assert elapsed < 2.5                        # returned ~_COLLECT_IDLE after the burst, not ~5s


async def test_send_op_build_frame_seeds_from_in_session_push(monkeypatch):
    """Single-session read-modify-write: build_frame is handed the AC's post-handshake status push as
    the baseline, so a control op seeds from live state without a separate read connection."""
    import asyncio

    SESSION = 0x1234
    hello_resp = uss.encode_message(uss.INFO_HELLO_RESP, 1, HELLO_RESP_OK, session=SESSION)
    done_resp = uss.encode_message(
        uss.INFO_HELLO_DONE_RESP, 2, uss.biz_encrypt(0, (547).to_bytes(4, "big"), LOCALKEY),
        flag=uss.FLAG_BIZ_ENCRYPTED, session=SESSION,
    )
    push = uss.encode_message(  # the status the AC pushes right after the handshake
        0x64, 3, uss.biz_encrypt(547, REAL_STATUS_DOWN, LOCALKEY),
        flag=uss.FLAG_BIZ_ENCRYPTED, session=SESSION,
    )
    reader = asyncio.StreamReader()
    reader.feed_data(hello_resp + done_resp + push)

    class FakeWriter:
        def write(self, data: bytes) -> None: ...
        async def drain(self) -> None: ...
        def close(self) -> None: ...
        async def wait_closed(self) -> None: ...

    async def fake_open(ip, port):
        return reader, FakeWriter()

    monkeypatch.setattr(asyncio, "open_connection", fake_open)

    seen: dict = {}

    def build(baseline):
        seen["baseline"] = baseline
        return REAL_GRSETDAC_EPP

    await uss.async_send_op("1.2.3.4", DEV, LOCALKEY, build_frame=build, counter=1, timeout=1.0)
    assert seen["baseline"] == REAL_STATUS_DOWN   # the in-session push became the seed baseline


# --- 125-byte report variant (deviceType 0201201d) ----------------------------
# A real decrypted full-status report from a unit whose report carries 2 attribute bytes fewer than the
# AAC1UKZ01 one: 5 grSetDAC control words instead of 6, so every sensor offset after the word block
# shifts by -2. Captured live and cross-checked field-by-field against the cloud digital-model shadow
# (targetTemperature=24, operationMode=1, windSpeed=5, onOffStatus=false, indoorTemperature=25.0,
# screenDisplayStatus=true, windDirectionVertical=8 -> swing on). Carries no secret: the canonical
# all-zero CAE report prefix, no deviceId embedded.
STATUS_125 = bytes.fromhex(
    "00002715000000004e5601000003020000040100000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000002dffff2a000000000000066d01080c250f"
    "020000070000323760100003000000000000000000000000002fe4c19f"
)

# --- 117-byte "compact-12" family (haismart-local issue #4, HSU-12HFMF) --------
# A DIFFERENT wire family: 12 words where the sensors live INSIDE the word array (indoor@w1,
# outdoor@w2), not in a separate trailing block like the classic family. Three real decrypted status
# reports supplied in the reporter's diagnostics, decoded via the APK preset wire model and each
# matching the state they reported. No secret: the all-zero CAE report prefix, no deviceId in a report.
#   OFF: power off, last setpoint 27, room 29, mode fan_only, fan high, swings off
STATUS_117_OFF = bytes.fromhex(
    "00002715000000004e5601000003020000040100000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "00000000000000000000000000000025ffff22000000000000066d01001d003b"
    "000000000000000300000000000000000000000bfc"
)
#   COOL 22, fan (decodes auto — see note), room 27
STATUS_117_COOL22 = bytes.fromhex(
    "00002715000000004e5601000003020000040100000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "00000000000000000000000000000025ffff22000000000001066d01001b003c"
    "000f00000000000100030000000100000000000608"
)
#   FAN ONLY, speed high, both swings on, room 27
STATUS_117_FANHI_SWING = bytes.fromhex(
    "00002715000000004e5601000003020000040100000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "00000000000000000000000000000025ffff22000000000000066d01001b003c"
    "0000000000000003000000030001000000000006fa"
)

# --- 165-byte "extended-36" family (haismart-local issue #5, HSU-12KCROC(IN)-R32) --------
# The CLASSIC climate block displaced by 19 words: a voice/media module occupies report words 1..19
# (inert on a plain split AC, but it is why the classic partial decode reads byte 92 as a 48 C
# setpoint — that byte is the module's `volume`), then targetTemperature@w20.b8, mode@w21.b13,
# fan@w21.b8, the boolean word@w22, horizontal swing@w23, indoor@w25.b8, outdoor@w26.b8. Two real
# decrypted reports from the reporter's diagnostics. No secret: the all-zero CAE report prefix.
#   OFF: power off, last setpoint 22, room 30.0, mode cool, fan high, vertical swing off
STATUS_165_OFF = bytes.fromhex(
    "00002715000000004e5601000003020000040100000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "00000000000000000000000000000055ffff52000000000000066d0120640000"
    "0000000000000000000000000000000000000000000000000000000000000100"
    "00000600210002020007000c3c00000000020000000000000000000000000000"
    "00000000c7"
)
#   ON: power on, setpoint 20, room 27.5, mode cool, fan high, vertical swing on
STATUS_165_ON = bytes.fromhex(
    "00002715000000004e5601000003020000040100000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "00000000000000000000000000000055ffff52000000000000066d0120640000"
    "0000000000000000000000000000000000000000000000000000000000000100"
    "00000408210002030007000c3700000000020000000000000000000000000000"
    "00000000c9"
)


def test_status_layout_recognises_both_report_lengths():
    assert len(STATUS_125) == 125
    assert uss.status_layout(REAL_STATUS_DOWN) == uss.StatusLayout(
        words=6, indoor_temp=104, outdoor_temp=106
    )
    assert uss.status_layout(STATUS_125) == uss.StatusLayout(
        words=5, indoor_temp=102, outdoor_temp=104
    )
    # the 78-byte CAE envelope is identical across variants; only the inner EPP frame length differs
    assert STATUS_125[:78] == uss.CAE_REPORT_PREFIX
    assert int.from_bytes(STATUS_125[78:80], "big") == len(STATUS_125) - 80


def test_status_layout_rejects_non_status_blobs():
    assert uss.status_layout(b"") is None
    assert uss.status_layout(bytes(126)) is None            # unknown length
    assert uss.status_layout(bytes(4)) is None              # right length field, wrong magic
    # a blob of a known length but the wrong container type is not a status report
    assert uss.status_layout(b"\x00\x00\x99\x99" + bytes(121)) is None


def test_parse_full_status_decodes_the_125_byte_variant():
    from haismart_hrdp import profile_for

    prof = profile_for("AAC1UKZ01")
    d = uss.parse_full_status(STATUS_125, prof)
    assert d == {
        "power": False, "target_temperature": 24.0, "current_temperature": 25.0,
        "operation_mode": "1", "wind_speed": "5", "swing_vertical": True,
        "swing_horizontal": True, "outdoor_temperature": 32.0,
        "health": False, "strong": False, "quiet": False, "sleep": False, "lamp": True, "eco": 0,
        "heat_capable": True, "error_code": 0, "last_changed_by": "network",
        "self_cleaning": False, "mode": "cool", "fan_mode": "auto",
    }


def test_compact12_decodes_the_three_real_reports():
    """The 117-byte family decodes via the wire-model registry (issue #4), matching the reporter's
    stated state on all three captures. Sensors live in the word array, so mode/fan use the STD codes
    the wire model maps from raw EPP indices (epp 2 -> STD "4" = heat, etc.)."""
    from haismart_hrdp import profile_for

    prof = profile_for("AAC1UKZ01")
    off = uss.parse_full_status(STATUS_117_OFF, prof)
    assert off == {
        "power": False, "target_temperature": 27.0, "current_temperature": 29.0,
        "operation_mode": "6", "wind_speed": "1", "swing_vertical": False,
        "swing_horizontal": False, "mode": "fan_only", "fan_mode": "high",
        "layout": "compact12", "writable": True,
    }
    cool = uss.parse_full_status(STATUS_117_COOL22, prof)
    assert cool["power"] is True and cool["target_temperature"] == 22.0
    assert cool["current_temperature"] == 27.0 and cool["mode"] == "cool"
    fan = uss.parse_full_status(STATUS_117_FANHI_SWING, prof)
    assert fan["mode"] == "fan_only" and fan["fan_mode"] == "high"
    assert fan["swing_vertical"] is True and fan["swing_horizontal"] is True
    # a compact-12 decode never fabricates the fields we deliberately left out
    for absent in ("outdoor_temperature", "health", "strong", "quiet", "sleep", "lamp", "eco"):
        assert absent not in off


def test_compact12_maps_heat_via_the_profile():
    """A model that HEATS names EPP mode index 2 as heat. The wire model emits STD code "4"; the
    device's own profile turns that into the ``heat`` token — a cooling-only profile would just omit
    it. Built by setting mode word 6 to raw 2 on a real report."""
    from haismart_hrdp import profile_for

    b = bytearray(STATUS_117_COOL22)
    b[92 + (6 - 1) * 2 + 1] = 2   # operationMode word 6 low byte -> EPP index 2
    heat_capable = profile_for("AACRL2E00")            # has mode "4" -> heat
    cooling_only = profile_for("AAC1UKZ01")            # no heat in its map
    assert uss.parse_full_status(bytes(b), heat_capable)["operation_mode"] == "4"
    assert uss.parse_full_status(bytes(b), heat_capable)["mode"] == "heat"
    assert uss.parse_full_status(bytes(b), cooling_only)["mode"] is None


def test_compact12_control_encodes_a_4d5f_group_set():
    """The 117 family's control path: read-modify-write over its 12-word array with group command
    4d5f (spec from the APK, std->EPP maps applied), packing only the requested field and preserving
    the rest. Round-trips: encode a change, wrap in the FF FF frame, and decode the words back."""
    wm = uss.select_wire_model(117)
    assert wm is not None and wm.group_cmd == b"\x4d\x5f"
    base = wm.baseline_words(STATUS_117_COOL22)          # words 1..12 (24 bytes)
    assert len(base) == 24

    # set heat (STD 4 -> EPP 2 @ word6) and 25 C (EPP 9 @ word12) in one group-set
    words = wm.encode_control(base, {"operationMode": 4, "targetTemperature": 25 - 16})
    frame = uss.build_epp_frame(0x01, wm.group_cmd, words)
    assert frame[:2] == b"\xff\xff" and frame[10:12] == b"\x4d\x5f"     # a 4d5f group-set frame
    assert (frame[2] + sum(frame[3:-1])) & 0xFF == frame[-1]            # checksum reproduces
    # word6 (mode) now EPP 2, word12 (temp) now EPP 9, everything else preserved from the baseline
    assert words[(6 - 1) * 2 + 1] == 2
    assert words[(12 - 1) * 2 + 1] == 9
    assert words[(7 - 1) * 2 + 1] == base[(7 - 1) * 2 + 1]              # windSpeed untouched

    # the encoder refuses an unmapped field and an unsupported enum value
    with pytest.raises(KeyError):
        wm.encode_control(base, {"healthMode": 1})
    with pytest.raises(ValueError, match="not a supported code"):
        wm.encode_control(base, {"operationMode": 9})


def test_extended36_decodes_the_real_reports():
    """The 165-byte family (issue #5). Its climate block sits 19 words into the report — the classic
    partial decode reads that leading media block instead and reports a 48 C setpoint on a unit that
    is off, which is the bug this family fixes."""
    from haismart_hrdp import profile_for

    prof = profile_for("AAD180E00")
    off = uss.parse_full_status(STATUS_165_OFF, prof)
    assert off == {
        "power": False, "target_temperature": 22.0, "current_temperature": 30.0,
        "operation_mode": "1", "wind_speed": "1", "swing_vertical": False,
        "swing_horizontal": True, "mode": "cool", "fan_mode": "high",
        "heat_capable": True, "error_code": 0, "last_changed_by": "panel",
        "layout": "extended36", "writable": True,
    }
    on = uss.parse_full_status(STATUS_165_ON, prof)
    assert on["power"] is True and on["target_temperature"] == 20.0
    # This is the reported "Cool, 22 C, Fan Low, FIXED louver position" state, and its vane code is
    # 8 -- position four, parked. It must not read as sweeping; only 0x0C/0x0E do. The old
    # single-bit test called this True, contradicting the stated louver position.
    assert on["current_temperature"] == 27.5 and on["swing_vertical"] is False
    # outdoorTemperature IS mapped, but both units report the 0 "no probe" sentinel, which must read
    # as absent rather than a confident -64 C that would poison long-term statistics
    assert "outdoor_temperature" not in off and "outdoor_temperature" not in on
    # the classic decode's wrong answer, for the record: byte 92 is the media module's `volume`
    assert STATUS_165_OFF[92] + 16 == 48


def test_extended36_reads_the_secondary_toggles_through_its_write_map():
    """The w22 boolean block is exposed via the write map (what the switch entities read back), not
    the read fields. Both captures have health + display light on and the rest off."""
    wm = uss.select_wire_model(165)
    assert wm is not None and wm.family == "extended36"
    got = {
        f: wm.current_write_value(STATUS_165_OFF, f)
        for f in ("healthMode", "rapidMode", "muteStatus", "silentSleepStatus",
                  "screenDisplayStatus", "onOffStatus")
    }
    assert got == {"healthMode": 1, "rapidMode": 0, "muteStatus": 0, "silentSleepStatus": 0,
                   "screenDisplayStatus": 1, "onOffStatus": 0}
    assert wm.current_write_value(STATUS_165_ON, "onOffStatus") == 1
    # a std_enum reads back as the STD code the caller passes in, not the raw wire value
    assert wm.current_write_value(STATUS_165_ON, "operationMode") == 1     # cool
    assert wm.current_write_value(STATUS_165_ON, "windSpeed") == 1         # high
    assert wm.current_write_value(STATUS_165_ON, "ecoMode") is None        # not mapped on this family


def test_extended36_control_encodes_a_6001_group_set_from_word_20():
    """Control on the 165 family: the same `6001` group-set the classic path sends, with the same
    five-word bit map — only the *baseline* comes from report word 20 (byte 130) rather than word 1,
    because that is where this family keeps the climate block."""
    wm = uss.select_wire_model(165)
    assert wm is not None and wm.group_cmd == b"\x60\x01" and wm.write_base_word == 20
    base = wm.baseline_words(STATUS_165_ON)
    assert len(base) == 10                                   # words 1..5
    assert bytes(base) == STATUS_165_ON[130:140]             # sliced past the media block

    words = wm.encode_control(base, {"targetTemperature": 24 - 16, "operationMode": 6})
    frame = uss.build_epp_frame(0x01, wm.group_cmd, words)
    assert frame[:2] == b"\xff\xff" and frame[10:12] == b"\x60\x01"
    assert (frame[2] + sum(frame[3:-1])) & 0xFF == frame[-1]  # checksum reproduces
    assert words[0] == 24 - 16                               # targetTemperature word1 b8
    assert (words[2] << 8 | words[3]) >> 13 == 6             # operationMode word2 b13 -> fan_only
    assert words[4:] == base[4:]                             # words 3..5 preserved untouched

    # the encoder refuses what it cannot map: an unknown field, an unnamed enum code, and a setpoint
    # outside 16..30 that would otherwise fit the 8-bit field
    with pytest.raises(KeyError):
        wm.encode_control(base, {"ecoMode": 5})
    with pytest.raises(ValueError, match="not a supported code"):
        wm.encode_control(base, {"operationMode": 3})
    with pytest.raises(ValueError, match="outside the 0..14"):
        wm.encode_control(base, {"targetTemperature": 99})


# --- 209-byte "extended-46" family (haismart-local issue #6, HSU-24HFAB) ------------------
# The extended-36 layout with a TEN-word block inserted at word 25: words 1..24 sit exactly where
# extended-36 puts them (the same media module in 1..19, then targetTemperature@w20.b8,
# mode@w21.b13, the boolean word@w22), and everything from extended-36's word 25 upward moves ten
# words later — indoor@w35.b8, outdoor@w36.b8, errCode@w37.b8, the energy counter@w44+w45. The
# setpoint counts HALF degrees from zero here, not whole degrees offset by 16. Three real decrypted
# reports. No secret: the all-zero CAE report prefix.
#   OFF: power off, retained setpoint 24, room 25.5, outdoor 37, mode cool, vertical swing off
STATUS_209_OFF = bytes.fromhex(
    "00002715000000004e5601000003020000040100000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "00000000000000000000000000000081ffff7e000000000000066d0120640000"
    "0000000000000000000000000000000000000000000000000000000000000100"
    "00003000260f0200000000000000000000000000000000000000000000000000"
    "333c65100043000000000000000000000000000b794000000000000000000000"
    "00000000000000000000000000000000c9"
)
#   COOL: power on, setpoint 22, room 25.5, outdoor 37, mode cool, vertical swing off
STATUS_209_COOL = bytes.fromhex(
    "00002715000000004e5601000003020000040100000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "00000000000000000000000000000081ffff7e000000000000066d0120640000"
    "0000000000000000000000000000000000000000000000000000000000000100"
    "00002c00260f0201000000000000060000000000000000000000000000000000"
    "333c65100003000000000000000000000000000b794000000000000000000000"
    "000000000000000000000000000000008c"
)
#   FAN: power on, setpoint 22, room 26.0, outdoor 36, mode fan_only, vertical swing ON
STATUS_209_FAN = bytes.fromhex(
    "00002715000000004e5601000003020000040100000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "00000000000000000000000000000081ffff7e000000000000066d0120640000"
    "0000000000000000000000000000000000000000000000000000000000000100"
    "00002c00c60f020100000000000c020000000000000000000000000000000000"
    "343c6410000f000000000000000000000000000b794000000000000000000000"
    "0000000000000000000000000000000040"
)


def test_extended46_decodes_the_real_reports():
    """The 209-byte family (issue #6). Same climate block as extended-36 for words 20..22, sensors
    ten words further on, and a half-degree setpoint."""
    from haismart_hrdp import profile_for

    prof = profile_for("AAC1UKZ01")
    assert len(STATUS_209_OFF) == len(STATUS_209_COOL) == len(STATUS_209_FAN) == 209

    off = uss.parse_full_status(STATUS_209_OFF, prof)
    assert off == {
        "power": False, "target_temperature": 24.0, "current_temperature": 25.5,
        "outdoor_temperature": 37.0, "operation_mode": "1", "swing_vertical": False,
        "heat_capable": True, "error_code": 0, "last_changed_by": "network",
        "mode": "cool", "layout": "extended46", "writable": True,
    }
    cool = uss.parse_full_status(STATUS_209_COOL, prof)
    assert cool["power"] is True and cool["target_temperature"] == 22.0 and cool["mode"] == "cool"
    fan = uss.parse_full_status(STATUS_209_FAN, prof)
    assert fan["mode"] == "fan_only" and fan["swing_vertical"] is True
    assert fan["current_temperature"] == 26.0 and fan["outdoor_temperature"] == 36.0

    # The classic partial decode is what this family REPLACES: byte 92 is the media module's
    # `volume` (100), which reads as a 48 C setpoint, and the classic power bit lands elsewhere so
    # the unit looks permanently off. Both are the symptoms the family was added to fix.
    assert STATUS_209_COOL[92] + 16 == 48
    assert not STATUS_209_COOL[97] & 0x01


def test_extended46_setpoint_is_half_degrees_both_ways():
    """The setpoint encoding is what separates this family from extended-36 at the same positions:
    the wire counts half degrees from zero, so a report reading 44 is 22 C, not 60 C."""
    wm = uss.select_wire_model(209)
    assert wm is not None and wm.family == "extended46"
    # read back in the classic representation the coordinator/climate hand around (degC - 16)
    assert wm.current_write_value(STATUS_209_COOL, "targetTemperature") == 22 - 16
    assert wm.current_write_value(STATUS_209_OFF, "targetTemperature") == 24 - 16

    base = wm.baseline_words(STATUS_209_COOL)
    words = wm.encode_control(base, {"targetTemperature": 25 - 16})
    assert words[0] == 50                       # 25 C on the wire == 50 half-degrees
    # a value that fits the 8-bit field but is not a temperature this family accepts
    with pytest.raises(ValueError, match="outside the 32..60"):
        wm.encode_control(base, {"targetTemperature": 99 - 16})


def test_extended46_control_reuses_the_extended36_group_set():
    """Words 20..24 — the whole settable block — sit where extended-36 puts them, so control is that
    family's `6001` group-set seeded from report word 20."""
    wm = uss.select_wire_model(209)
    assert wm.group_cmd == b"\x60\x01" and wm.write_base_word == 20 and wm.word_count == 5
    base = wm.baseline_words(STATUS_209_COOL)
    assert bytes(base) == STATUS_209_COOL[130:140]

    words = wm.encode_control(base, {"operationMode": 6, "onOffStatus": 0})
    frame = uss.build_epp_frame(0x01, wm.group_cmd, words)
    assert frame[:2] == b"\xff\xff" and frame[10:12] == b"\x60\x01"
    assert (frame[2] + sum(frame[3:-1])) & 0xFF == frame[-1]
    assert (words[2] << 8 | words[3]) >> 13 == 6      # operationMode word2 b13 -> fan_only
    assert words[5] & 0x01 == 0                       # onOffStatus word3 b0 cleared
    assert words[0] == base[0]                        # setpoint untouched

    # Fan speed and the swings are NOT settable on this family: their positions are not settled, and
    # the encoder must refuse a field it cannot place rather than write to a guessed word.
    for unsupported in ("windSpeed", "windDirectionVertical", "windDirectionHorizontal"):
        with pytest.raises(KeyError):
            wm.encode_control(base, {unsupported: 1})


def test_probe_layout_proposes_the_209_family_unaided():
    """The prober is what should keep an unknown report from needing hand analysis: given the three
    reports and the device's own attribute values, it proposes the right map without the family
    being registered. Run here with extended-46 removed from the candidate list so the search has to
    find it."""
    from haismart_hrdp import wire_models

    reports = [STATUS_209_OFF, STATUS_209_COOL, STATUS_209_FAN]
    shadow = {"targetTemperature": "24", "operationMode": "1", "onOffStatus": "true"}
    families = tuple(f for f in wire_models.PROBE_FAMILIES if f.family != "extended46")
    original = wire_models.PROBE_FAMILIES
    wire_models.PROBE_FAMILIES = families
    try:
        candidates = wire_models.probe_layout(reports, shadow=shadow)
    finally:
        wire_models.PROBE_FAMILIES = original

    assert candidates, "the prober found no layout for a report it should explain"
    best = candidates[0]
    assert best["family"] == "extended36"
    assert best["shift"] == 10 and best["setpoint"] == "half"
    # and the proposal decodes the reports the way the shipped family does
    assert [d["target_temperature"] for d in best["decoded"]] == [24.0, 22.0, 22.0]
    assert [d["current_temperature"] for d in best["decoded"]] == [25.5, 25.5, 26.0]


def test_probe_layout_rejects_a_report_it_cannot_explain():
    """An empty word array has no plausible room temperature, so nothing is proposed — the prober
    must say "no idea" rather than rank a map that reads a powered-off 16 C unit out of zeros."""
    from haismart_hrdp import wire_models

    blank = bytes(STATUS_209_OFF[:92]) + bytes(len(STATUS_209_OFF) - 92)
    assert wire_models.probe_layout(blank) == []


def test_grsetdac_baseline_still_classic_only():
    """The classic grSetDAC baseline helper stays classic-only — a non-classic length raises (that
    path uses its own wire-model encoder, not this one)."""
    assert uss.select_wire_model(len(REAL_STATUS_DOWN)) is None   # classic length isn't in the registry
    with pytest.raises(ValueError, match="no capture-confirmed grSetDAC write layout"):
        uss.grsetdac_baseline_from_status(STATUS_117_OFF)


def test_wire_model_selection_prefers_uplus_id_then_length():
    from haismart_hrdp import select_wire_model

    compact12 = select_wire_model(117)
    assert compact12 is not None and compact12.family == "compact12"
    assert select_wire_model(999) is None                        # unknown length, no match
    # an implausible decode is rejected so a length collision can't surface a mis-decode
    bogus = bytearray(STATUS_117_OFF)
    bogus[92] = 0xFF   # indoor word 1 high byte -> ~16000 degC, fails the plausibility guard
    bogus[93] = 0xFF
    assert compact12.decode(bytes(bogus)) is None


def test_parse_full_status_partially_decodes_an_unknown_report_length():
    """An unrecognised length yields the layout-INDEPENDENT fields, flagged, never a silent {}.

    Bytes 92-97 are grSetDAC words 1-3, which sit before anything the word count shifts, so a brand
    new model still gets a working thermostat. Everything whose offset depends on the word count is
    omitted rather than guessed.
    """
    for blob in (STATUS_125 + b"\x00", STATUS_125[:-1]):   # odd span -> not derivable
        assert uss.derive_status_layout(blob) is None
        state = uss.parse_full_status(blob)
        assert state["partial"] is True and state["layout"] == "unknown"
        # layout-independent fields still decode, and agree with the real 125-byte report
        assert state["power"] is False
        assert state["target_temperature"] == 24.0
        assert state["operation_mode"] == "1"
        assert state["wind_speed"] == "5"
        assert state["swing_vertical"] is True
        # ...and nothing that depends on the word count is invented
        for absent in ("current_temperature", "outdoor_temperature", "swing_horizontal", "eco"):
            assert absent not in state


def test_parse_full_status_rejects_blobs_that_are_not_status_reports():
    assert uss.parse_full_status(b"") == {}
    assert uss.parse_full_status(b"\x00\x00\x99\x99" + bytes(121)) == {}   # wrong container type
    # right magic but too short to hold even the layout-independent fields
    assert uss.parse_full_status(b"\x00\x00\x27\x15" + bytes(90)) == {}


def test_grsetdac_baseline_tracks_the_report_layout():
    """The baseline is words 1..N for the blob's layout — never a fixed 12 bytes.

    On the 125-byte variant byte 102 is the read-only indoorTemperature. A hardcoded ``[92:104]``
    slice would pull it (and byte 103) into the word block, so a group-set would write a sensor
    reading back to the AC as if it were control word 6.
    """
    assert uss.grsetdac_baseline_from_status(REAL_STATUS_DOWN) == REAL_STATUS_DOWN[92:104]
    base = uss.grsetdac_baseline_from_status(STATUS_125)
    assert base == STATUS_125[92:102]
    assert len(base) == 10
    # the invariant that matters: the word block must end at or before the first sensor byte
    for blob in (REAL_STATUS_DOWN, STATUS_125):
        layout = uss.status_layout(blob)
        assert layout.baseline.stop <= layout.indoor_temp
    assert STATUS_125[uss.status_layout(STATUS_125).indoor_temp] == 50   # 50 / 2 == 25.0 degC


def test_grsetdac_baseline_rejects_an_unknown_length():
    with pytest.raises(ValueError, match="no capture-confirmed grSetDAC write layout"):
        uss.grsetdac_baseline_from_status(STATUS_125[:-1])


def test_read_grsetdac_field_on_the_125_variant():
    # words 1..5 sit at the same offsets on both variants, so the confirmed field map applies as-is
    assert uss.read_grsetdac_field(STATUS_125, "targetTemperature") == 24 - 16
    assert uss.read_grsetdac_field(STATUS_125, "operationMode") == 1
    assert uss.read_grsetdac_field(STATUS_125, "windSpeed") == 5
    assert uss.read_grsetdac_field(STATUS_125, "onOffStatus") == 0
    assert uss.read_grsetdac_field(STATUS_125, "screenDisplayStatus") == 1
    assert uss.read_grsetdac_field(STATUS_125, "windDirectionVertical") == 0x0C
    assert uss.read_grsetdac_field(STATUS_125, "ecoMode") == 0


def test_set_grsetdac_field_round_trips_on_a_125_baseline():
    base = uss.grsetdac_baseline_from_status(STATUS_125)
    words = uss.set_grsetdac_field(base, "targetTemperature", 26 - 16)
    assert len(words) == len(base)                     # group-set keeps the word count
    assert words[2:] == base[2:]                       # only word 1's high byte moved
    # re-reading through a synthetic report confirms the encode/decode agree
    patched = STATUS_125[:92] + words + STATUS_125[92 + len(words):]
    assert uss.read_grsetdac_field(patched, "targetTemperature") == 26 - 16
    assert uss.parse_full_status(patched)["target_temperature"] == 26.0
    # ...and the untouched fields are preserved by the group-set
    assert uss.parse_full_status(patched)["operation_mode"] == "1"
    assert uss.parse_full_status(patched)["lamp"] is True


# --- independent horizontal swing axis (windDirectionHorizontal) ---------------
def test_horizontal_swing_reads_on_both_report_variants():
    """word4 bits 0-2 carry left-right swing on both the 127- and 125-byte reports."""
    for blob in (REAL_STATUS_DOWN, REAL_STATUS_UP, STATUS_125):
        assert uss.read_grsetdac_field(blob, "windDirectionHorizontal") == 7
        assert uss.parse_full_status(blob)["swing_horizontal"] is True
        # the axis must not be confused with ecoMode, which shares word 4 (bits 3-5)
        assert uss.read_grsetdac_field(blob, "ecoMode") == 0


def test_horizontal_swing_is_independent_of_vertical_and_eco():
    """Confirmed by a single-attribute app sweep: only word4 bits 0-2 move.

    Ground truth captured live — toggling ONLY left-right swing in the vendor app took word4 from
    0x0007 to 0x0000 while byte 93 (vertical) stayed 0x0c and ecoMode stayed 0.
    """
    base = uss.grsetdac_baseline_from_status(STATUS_125)
    off = uss.set_grsetdac_field(base, "windDirectionHorizontal", 0x00)
    assert (off[6] << 8) | off[7] == 0x0000
    assert off[:6] == base[:6] and off[8:] == base[8:]      # nothing outside word 4 moved

    fixed = STATUS_125[:92] + off + STATUS_125[92 + len(off):]
    state = uss.parse_full_status(fixed)
    assert state["swing_horizontal"] is False
    assert state["swing_vertical"] is True                  # vertical axis untouched
    assert state["eco"] == 0                                # eco untouched
    assert state["target_temperature"] == 24.0

    back = uss.set_grsetdac_field(off, "windDirectionHorizontal", 0x07)
    assert back == base                                     # round-trips exactly


def test_horizontal_swing_refuses_unobserved_values():
    base = uss.grsetdac_baseline_from_status(STATUS_125)
    for bad in (1, 3, 8, 12, 15):
        # refused either as an unobserved value or (for 8/12/15) by the 3-bit width check
        with pytest.raises(ValueError, match="observed-valid|does not fit"):
            uss.set_grsetdac_field(base, "windDirectionHorizontal", bad)


def test_horizontal_swing_enum_matches_the_digital_model_codes():
    # the model lists exactly two codes: 0 = fixed, 7 = auto. Unlike windDirectionVertical, the raw
    # EPP value equals the STD code, which is why the coordinator can gate it against valueRange.
    assert uss.GRSETDAC_ENUMS["windDirectionHorizontal"] == {"off": 0x00, "on": 0x07}
    assert uss.GRSETDAC_ALLOWED_VALUES["windDirectionHorizontal"] == {0x00, 0x07}
    assert uss.GRSETDAC_FIELDS["windDirectionHorizontal"] == (4, 0, 3)


def test_check_hello_resp_rejects_a_refused_session():
    """status != 1 must raise, not sail on into hello_done and an empty status collect.

    A refused session used to be indistinguishable from a stale localKey or a dead network, because
    only `info_type` was checked; worse, the write path would send a control op into it.
    """
    refused = uss.decode_message(
        uss.encode_message(uss.INFO_HELLO_RESP, 1, bytes.fromhex("0000000000000004"), session=0x1234)
    )
    with pytest.raises(RuntimeError, match="rejected the handshake"):
        uss.check_hello_resp(refused)

    wrong_type = uss.decode_message(uss.encode_message(uss.INFO_HELLO_DONE_RESP, 1, HELLO_RESP_OK))
    with pytest.raises(RuntimeError, match="unexpected reply"):
        uss.check_hello_resp(wrong_type)

    ok = uss.decode_message(uss.encode_message(uss.INFO_HELLO_RESP, 1, HELLO_RESP_OK, session=0x1234))
    assert uss.check_hello_resp(ok).localkey_version == 4


def test_split_messages_stops_on_a_desynchronised_frame():
    """A declared length under 0x0A cannot be a frame; yielding it would raise inside a collect loop."""
    good = uss.encode_message(uss.INFO_HELLO_RESP, 1, HELLO_RESP_OK, session=1)
    assert len(list(uss.split_messages(good))) == 1
    bad = good + b"\x00\x00\xea\x61\x00\x03rubbish"
    assert list(uss.split_messages(bad)) == [good]     # the good frame survives, the junk is dropped
    assert list(uss.split_messages(b"\x00\x00\xea\x61\x00\x00")) == []   # total==0, must not loop


# --- extended status (running power / compressor figures) ----------------------------------------

# Verbatim extended-status reports from two real units in opposite states: one cooling under an ECO
# current cap, one idle. 141 bytes, inner report command 7d01.
EXT_COOLING = bytes.fromhex(
    "00002715000000004e560100c0030200c004010000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000010000003dffff3a000000000000067d010b0c22000201003f0800000038005f8000010000000000000000000000000000000002b2407900000023001e022500002e")
EXT_IDLE = bytes.fromhex(
    "00002715000000004e560100bb030200bb04010000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000010000003dffff3a000000000000067d01070022000200000708000000420059800001000000000000000000000000000000000000606800000000000002200000fe")


def test_extended_status_frame_is_a_read_only_query():
    """The query changes nothing and matches the checksum rule the unit enforces."""
    frame = uss.extended_status_epp_frame()
    assert frame == bytes.fromhex("ffff0a000000000000014dfe56")
    body = frame[2:-1]
    assert frame[-1] == sum(body) & 0xFF
    assert frame[9] == 0x01                     # a plain request, not a set
    assert frame[10:12] == uss.EPP_CMD_EXTENDED_STATUS


def test_parse_extended_status_decodes_a_running_unit():
    got = uss.parse_extended_status(EXT_COOLING)
    assert got["power_w"] == 690
    assert got["compressor_current_a"] == 3.0
    assert got["compressor_frequency_hz"] == 35
    assert got["compressor_running"] is True
    assert got["fan_running"] is True
    # a cold evaporator while cooling, and a hot discharge line
    assert got["coil_temperature"] == 12.0
    assert got["discharge_temperature"] == 57.0


def test_parse_extended_status_decodes_an_idle_unit():
    got = uss.parse_extended_status(EXT_IDLE)
    assert got["power_w"] == 0
    assert got["compressor_current_a"] == 0.0
    assert got["compressor_frequency_hz"] == 0
    assert got["compressor_running"] is False
    assert got["fan_running"] is False
    assert got["coil_temperature"] == 28.0      # coil sits at room temperature


def test_parse_extended_status_rejects_anything_else():
    """Only the confirmed extended layout decodes — never a guess at another report's bytes."""
    assert uss.parse_extended_status(b"") == {}
    assert uss.parse_extended_status(REAL_STATUS_DOWN) == {}          # ordinary status report
    assert uss.parse_extended_status(EXT_COOLING[:-1]) == {}          # wrong length
    # right length, but the report command says it is something else
    other = bytearray(EXT_COOLING)
    at = other.index(b"\xff\xff")
    other[at + 10:at + 12] = b"\x6d\x01"
    assert uss.parse_extended_status(bytes(other)) == {}


def test_status_parser_ignores_the_other_report_kinds():
    """A session carries status, faults and (when asked) extended status in the same container.

    The fault frame is long enough to pass the status length checks and decodes into a confident
    powered-off unit with a 16 degC setpoint, so it must be rejected by report kind rather than by
    the order the unit happens to send frames in.
    """
    assert uss.parse_full_status(EXT_COOLING) == {}
    alarm = bytes.fromhex(
        "00002715000000004e5601000003020000040100000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000015ffff12000000000000040f5a00000000000000007f")
    assert len(alarm) == 101
    assert uss.parse_full_status(alarm) == {}


def test_power_reads_only_the_on_off_bit():
    """byte 97 packs eight flags; only bit 0 is on/off.

    Reading the whole byte reported the unit as ON whenever health / boost / quiet / sleep / lock /
    buzzer was set — and this integration's own switches write four of them, so turning on Quiet
    while the unit was off flipped the thermostat to "on".
    """
    assert uss.parse_full_status(REAL_STATUS_UP)["power"] is False
    w3 = int.from_bytes(REAL_STATUS_UP[96:98], "big")
    assert w3 & 0x01 == 0, "fixture precondition: this unit is off"
    for bit in range(1, 8):
        blob = bytearray(REAL_STATUS_UP)
        blob[96:98] = (w3 | (1 << bit)).to_bytes(2, "big")
        at = blob.index(b"\xff\xff")
        blob[-1] = sum(blob[at + 2:-1]) & 0xFF          # keep the frame checksum valid
        got = uss.parse_full_status(bytes(blob))
        assert got["power"] is False, f"bit {bit} of byte 97 leaked into power"
    blob = bytearray(REAL_STATUS_UP)
    blob[96:98] = (w3 | 0x01).to_bytes(2, "big")
    at = blob.index(b"\xff\xff")
    blob[-1] = sum(blob[at + 2:-1]) & 0xFF
    assert uss.parse_full_status(bytes(blob))["power"] is True


def test_vertical_vane_position_codes_are_not_a_bitmask():
    """The vane field is a position code: only the auto codes count as sweeping.

    Device model: 0 = fixed, 2/4/5/6/7 = positions one..five, 8 = auto -> wire 0/2/4/6/8/10 and 12.
    Wire 8 and 10 are the vane parked low; a single-bit `& 0x08` test reported both as sweeping.
    """
    sweeping = {0x0C, 0x0E}
    for code in (0x00, 0x02, 0x04, 0x06, 0x08, 0x0A, 0x0C, 0x0E):
        assert uss.vane_v_sweeping(code) is (code in sweeping), f"wire code {code:#04x}"


def test_horizontal_vane_only_auto_counts_as_swinging():
    """Horizontal: 0 = fixed, 3..6 = positions, 7 = auto. `bool()` called every position swinging."""
    blob = bytearray(REAL_STATUS_DOWN)
    words = uss.STATUS_LAYOUTS[len(blob)].baseline
    for code, expected in ((0, False), (3, False), (4, False), (6, False), (7, True)):
        block = bytearray(blob[words])
        block[7] = (block[7] & ~0x07) | code
        blob[words] = block
        assert uss.parse_full_status(bytes(blob))["swing_horizontal"] is expected, f"code {code}"


def test_destuff_recovers_a_report_whose_checksum_is_ff():
    """The real 128-byte case: a report whose frame checksum lands on 0xFF travels as `FF 55`.

    Confirmed on hardware. Left escaped, every length-keyed lookup misses and the write path
    refuses control on a perfectly good report.
    """
    canonical = REAL_STATUS_DOWN
    at = canonical.find(uss.EPP_FRAME_HEAD)
    frame_len = canonical[at + 2]
    checksum_at = at + 10 + (frame_len - 8)
    stuffed = bytearray(canonical)
    stuffed[checksum_at] = 0xFF                      # force the checksum onto the separator value
    stuffed.insert(checksum_at + 1, 0x55)            # ...so the wire escapes it

    assert len(stuffed) == len(canonical) + 1
    assert uss.status_layout(bytes(stuffed)) is None, "escaped blob must not match a length table"

    recovered = uss.destuff_epp(bytes(stuffed))
    assert len(recovered) == len(canonical)
    assert uss.status_layout(recovered) is not None
    assert uss.grsetdac_baseline_from_status(recovered) == canonical[
        uss.STATUS_LAYOUTS[len(canonical)].baseline
    ]


def test_destuff_is_a_no_op_on_unescaped_blobs():
    for blob in (REAL_STATUS_DOWN, REAL_STATUS_UP, b"", b"\x00\x01\x02"):
        assert uss.destuff_epp(blob) == blob


def test_stuff_destuff_round_trip():
    frame = uss.build_epp_frame(0x01, uss.EPP_CMD_GRSETDAC, bytes([0xFF, 0x00, 0xFF, 0x55, 0x12]))
    wire = uss.stuff_epp(frame)
    assert wire.count(bytes([0xFF, 0x55])) >= 2      # both body 0xFFs escaped
    assert wire.startswith(uss.EPP_FRAME_HEAD)        # the delimiter itself is never escaped
    assert uss.destuff_epp(wire) == frame


def test_checksum_counts_escape_bytes():
    """Each escaped 0xFF contributes its 0x55 to the checksum; frames without one are unchanged."""
    plain = uss.build_epp_frame(0x01, uss.EPP_CMD_GRSETDAC, bytes(12))
    body = plain[2:-1]
    assert plain[-1] == sum(body) & 0xFF              # no 0xFF present -> plain sum, as before

    withff = uss.build_epp_frame(0x01, uss.EPP_CMD_GRSETDAC, bytes([0xFF]) + bytes(11))
    body2 = withff[2:-1]
    assert withff[-1] == (sum(body2) + 0x55) & 0xFF


def _alarm_frame(flags: bytes) -> bytes:
    """A fault frame carrying ``flags``, wrapped exactly as the unit sends one."""
    frame = uss.build_epp_frame(0x04, b"\x0f\x5a", flags)
    return b"\x00\x00\x27\x15" + bytes(76) + frame


def test_alarm_bitmap_is_one_big_endian_integer():
    """Fault 0 is the LOW bit of the LAST flag byte, so the bytes read as one big-endian value."""
    clear = uss.parse_alarm_frame(_alarm_frame(bytes(8)))
    assert clear == {"alarm_count": 0, "alarm_codes": [], "alarm_labels": []}

    # fault 0 lives in the last byte, not the first
    first = uss.parse_alarm_frame(_alarm_frame(bytes(7) + b"\x01"))
    assert first["alarm_codes"] == [0]
    assert first["alarm_labels"] == ["F1 - Outdoor module failure"]

    # ...and the first byte carries the HIGH positions
    high = uss.parse_alarm_frame(_alarm_frame(b"\x01" + bytes(7)))
    assert high["alarm_codes"] == [56]

    # a mid-range one: E1, indoor temperature sensor, is position 20
    e1 = uss.parse_alarm_frame(_alarm_frame(bytes(5) + b"\x10" + bytes(2)))
    assert e1["alarm_codes"] == [20]
    assert e1["alarm_labels"] == ["E1 - Indoor temperature sensor failure"]


def test_alarm_positions_track_the_frame_length():
    """The byte count comes from the frame, so a shorter frame shifts every position."""
    assert uss.parse_alarm_frame(_alarm_frame(bytes(3) + b"\x01"))["alarm_codes"] == [0]
    assert uss.parse_alarm_frame(_alarm_frame(b"\x01" + bytes(3)))["alarm_codes"] == [24]


def test_parse_alarm_frame_ignores_other_reports():
    assert uss.parse_alarm_frame(REAL_STATUS_DOWN) is None
    assert uss.parse_alarm_frame(b"") is None


def test_heat_capability_is_reported_by_the_unit():
    """Bit 7 after the outdoor reading is set on a cooling-only unit.

    Checked against real reports from both kinds of hardware rather than a synthesised bit: the
    reference units are cooling-only, while the 165- and 209-byte reporters run reverse-cycle models
    whose published mode list includes heat. The flag agrees with the hardware in every case, on
    three different report layouts.
    """
    cooling_only = (REAL_STATUS_DOWN, REAL_STATUS_UP)
    reverse_cycle = (STATUS_165_OFF, STATUS_165_ON, STATUS_209_OFF, STATUS_209_COOL, STATUS_209_FAN)

    for report in cooling_only:
        assert uss.parse_full_status(report)["heat_capable"] is False, len(report)
    for report in reverse_cycle:
        assert uss.parse_full_status(report)["heat_capable"] is True, len(report)


def test_self_clean_is_reported_from_the_flag_word():
    """A self-clean cycle sets one bit in the flag word and clears it when the cycle ends.

    Confirmed on hardware across a full cycle: the bit set when the cycle was started at the handset
    and cleared when the unit finished, and no other control bit moved in between.
    """
    assert uss.parse_full_status(REAL_STATUS_DOWN)["self_cleaning"] is False

    cleaning = bytearray(REAL_STATUS_DOWN)
    flag_at = 92 + (uss._FLAG_WORD - 1) * 2
    cleaning[flag_at + 1] |= 1 << uss._SELF_CLEAN_BIT
    decoded = uss.parse_full_status(bytes(cleaning))
    assert decoded["self_cleaning"] is True
    # ...and nothing else moved with it
    baseline = uss.parse_full_status(REAL_STATUS_DOWN)
    assert {k: v for k, v in decoded.items() if k != "self_cleaning"} == {
        k: v for k, v in baseline.items() if k != "self_cleaning"
    }
