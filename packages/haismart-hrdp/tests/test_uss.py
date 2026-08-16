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
    # NB windDirectionHorizontal (now confirmed) and lightStatus (now a panel control) used to be
    # listed here; both are mapped now. `echoStatus` is the enduring example — in the frame,
    # model-writable, but NOT a panel control (no widget), so the encoder refuses it.
    for unmapped in ("echoStatus", "energySavingStatus", "notARealAttr"):
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
    # ecoMode has no matching model attribute (this unit repurposes a 3-bit field), so the model is
    # not allowed to authorize values for it — the observed set stays the authority.
    with pytest.raises(ValueError):
        uss.set_grsetdac_field(words, "ecoMode", 1, model_values={0, 1})
    # a code that doesn't fit the field would silently corrupt neighbouring attributes
    with pytest.raises(ValueError):
        uss.set_grsetdac_field(words, "operationMode", 8, model_values={8})


def test_model_declared_vane_positions_use_wire_values_not_model_codes():
    """The up-down vane is widenable, but ``model_values`` means WIRE values, as everywhere here.

    Its model numbers the stops 0, 2, 4, 5, 6, 8 while the wire counts 0, 2, 4, 6, 8, 12 — so a
    caller hands over codes already translated (``VANE_V_MODEL_TO_EPP``). The distinction matters:
    the model's 8 is auto, and the wire's 8 is the fourth position down.
    """
    from haismart_hrdp import VANE_V_MODEL_TO_EPP

    words = bytes.fromhex("0800230002030007080c0000")
    declared = {0, 2, 4, 5, 6, 8}                       # what a model lists
    wire = {VANE_V_MODEL_TO_EPP[c] for c in declared}   # what the unit accepts
    assert wire == {0, 2, 4, 6, 8, 12}

    # nothing but the two observed values without a model to say otherwise
    with pytest.raises(ValueError):
        uss.set_grsetdac_field(words, "windDirectionVertical", 8)
    parked = uss.set_grsetdac_field(words, "windDirectionVertical", 8, model_values=wire)
    assert parked[0] & 0x0F == 8
    # auto is the same 0x0c it has always been, and the table agrees
    assert VANE_V_MODEL_TO_EPP[8] == uss.GRSETDAC_ENUMS["windDirectionVertical"]["on"]


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
# reports supplied in the reporter's diagnostics, decoded via this family's wire model and each
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


# --- 175 B: the same family with five words on the end (issue #8, HS-25VRB03) -------------
# Every climate field sits at the same word as on the 165-byte reports above; words 34..41 carry the
# cumulative energy total (twice) and an input-power register. One real report, cool 24 C, fan low,
# room 26.0, outdoor 33, screen light on, vertical vane parked at 2 and horizontal at 5.
STATUS_175 = bytes.fromhex(
    "00002715000000004e5601000003020000040100000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000005fffff5c000000000000066d0120640000"
    "0000000000000000000000000000000000000000000000000000000000000100"
    "0000080223000201160500003400618000030000000000000000000000000000"
    "6ccb00000000000000006ccb052651"
)
UPLUS_175 = "2008610800820324021200118018900000000000000000000000000000000040"

# The same unit with a comfort setting on: one report taken with boost enabled, one with sleep.
# Its owner reported both as commands that appeared to do nothing -- the air conditioner obeyed and
# the family map simply did not read the word back.
STATUS_175_BOOST = bytes.fromhex(
    "00002715000000004e5601000003020000040100000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000005fffff5c000000000000066d0120640000"
    "0000000000000000000000000000000000000000000000000000000000000100"
    "0000080225000209160500003500658000030000000000000000000000000000"
    "be6b0000000000000000be6b06e908"
)
# The same unit again, stepped through its economy levels one report at a time. Between these two
# the unit's measured input power fell from 1969 W to 1798 W.
STATUS_175_ECO_OFF = bytes.fromhex(
    "00002715000000004e5601000003020000040100000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000005fffff5c000000000000066d0120640000"
    "0000000000000000000000000000000000000000000000000000000000000100"
    "0000080222000201160500003700678000030000000000000000000000000000"
    "b8e50000000000000000b8e507b1b2"
)
STATUS_175_ECO_L2 = bytes.fromhex(
    "00002715000000004e5601000003020000040100000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000005fffff5c000000000000066d0120640000"
    "0000000000000000000000000000000000000000000000000000000000000100"
    "0000080222000201161500003700668000030000000000000000000000000000"
    "b8e50000000000000000b8e5070616"
)
STATUS_175_SLEEP = bytes.fromhex(
    "00002715000000004e5601000003020000040100000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000005fffff5c000000000000066d0120640000"
    "0000000000000000000000000000000000000000000000000000000000000100"
    "0000080225000221160500003400658000030000000000000000000000000000"
    "be6b0000000000000000be6b061f55"
)


def test_status_layout_recognises_both_report_lengths():
    assert len(STATUS_125) == 125
    assert uss.status_layout(REAL_STATUS_DOWN) == uss.StatusLayout(
        words=6, indoor_temp=104, outdoor_temp=106, energy=124
    )
    assert uss.status_layout(STATUS_125) == uss.StatusLayout(
        words=5, indoor_temp=102, outdoor_temp=104, energy=122
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
        # this unit keeps a cumulative total; the reference units carry the register and never fill
        # it in, so they report none at all
        "energy_wh": 3138753,
    }


def test_compact12_decodes_the_three_real_reports():
    """The 117-byte family decodes via the wire-model registry (issue #4), matching the reporter's
    stated state on all three captures. Sensors live in the word array, so mode/fan use the STD codes
    the wire model maps from raw EPP indices (epp 2 -> STD "4" = heat, etc.).

    Since the family's full published description was taken up, the decode also carries every other
    positioned field. On these captures the toggles all read false and the meaning-pending registers
    read their raw values — 59 in the outdoor byte against a 29 C room, which is exactly why that
    register ships raw rather than as a temperature."""
    from haismart_hrdp import profile_for

    prof = profile_for("AAC1UKZ01")
    off = uss.parse_full_status(STATUS_117_OFF, prof)
    assert off == {
        "power": False, "target_temperature": 27.0, "current_temperature": 29.0,
        "operation_mode": "6", "wind_speed": "1", "swing_vertical": False,
        "swing_horizontal": False, "mode": "fan_only", "fan_mode": "high",
        # the published description's remaining fields (meanings pending; see COMPACT12's note)
        "w2_low_raw": 59, "w2_high_raw": 0, "input_power_raw": 0, "pm_raw": 0,
        "electric_heat": False, "self_clean": False, "health": False, "humidify": False,
        "temp_unit": 0, "human_sensing": False, "cloud_adaptive": False, "sleep_curve": False,
        "lock": False, "fresh_air": False, "healthy_wind_up": False, "healthy_wind_down": False,
        "cap_strong": False, "cap_quiet": False, "cap_display": False, "cap_energy_saving": False,
        "layout": "compact12", "writable": True,
    }
    cool = uss.parse_full_status(STATUS_117_COOL22, prof)
    assert cool["power"] is True and cool["target_temperature"] == 22.0
    assert cool["current_temperature"] == 27.0 and cool["mode"] == "cool"
    fan = uss.parse_full_status(STATUS_117_FANHI_SWING, prof)
    assert fan["mode"] == "fan_only" and fan["fan_mode"] == "high"
    assert fan["swing_vertical"] is True and fan["swing_horizontal"] is True
    # the humidity registers read 0 on this unit = no probe, so the keys are ABSENT, not 0 %
    for report in (off, cool, fan):
        assert "indoor_humidity" not in report and "target_humidity" not in report


def test_compact12_power_and_outdoor_unit_temp_stay_diagnostic():
    """The two registers held out of entities on unproven SCALE/meaning, pinned to the real captures:

    * the input-power register MOVES with the compressor (0 off, 15 cooling, 0 fan-only) — the
      position is right — but 15 of anything is not watts while cooling, so its UNIT is unproven
      (~1.5 kW at 0.1 kW steps is plausible; only a meter settles it);
    * the w2 low byte (vendor `外温`) reads 59/60/60 across off/cool/fan. That is a temperature of the
      OUTDOOR UNIT, not ambient: ~60 °C off the condenser while cooling is ordinary (the telemetry
      family's outdoor-air byte runs 60-85 °C for the same reason), and it holds ~59 when off because
      the outdoor probe is dormant/stale. It is NOT surfaced as an "outdoor temperature" sensor
      because a user reads that as ambient, and it is stale-when-off besides.

    Neither ships as an entity; a meter settles the power scale, and the outdoor-unit reading is
    correctly a hot-side temperature that should not masquerade as ambient outdoor air."""
    off = uss.parse_full_status(STATUS_117_OFF, None)
    cool = uss.parse_full_status(STATUS_117_COOL22, None)
    fan = uss.parse_full_status(STATUS_117_FANHI_SWING, None)
    assert (off["input_power_raw"], cool["input_power_raw"], fan["input_power_raw"]) == (0, 15, 0)
    # ~60 while running, holding ~59 when off — consistent with a stale-when-off outdoor-unit temp
    assert (off["w2_low_raw"], cool["w2_low_raw"], fan["w2_low_raw"]) == (59, 60, 60)
    assert STATUS_117_OFF[92 + 2] == 0     # word 2 high byte (air quality): zero across all three


def test_compact12_meaning_pending_fields_reach_no_entity():
    """No key of the newly-read block may collide with a key an entity consumes. The sensors read
    `outdoor_temperature` / `power_w` / `energy_wh`, the self-clean binary sensor reads
    `self_cleaning`, and the comfort switches read their classic names — a collision would light an
    existing entity family-wide with a value whose meaning is unproven (the exact phantom-feature
    shape of v0.32.0). Promotion to those keys is a deliberate, per-key act with evidence."""
    from haismart_hrdp.wire_models import COMPACT12

    entity_keys = {"outdoor_temperature", "power_w", "energy_wh", "self_cleaning",
                   "strong", "quiet", "sleep", "lamp", "eco", "fan_running", "alarm_count"}
    assert not entity_keys & set(COMPACT12.fields)


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
    4d5f (spec from its model, std->EPP maps applied), packing only the requested field and preserving
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
        "self_cleaning": False, "layout": "extended36", "writable": True,
        # the comfort settings this family offers as switches, read from the same word as power
        "strong": False, "quiet": False, "health": True, "sleep": False, "lamp": True,
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


def test_extended36_economy_levels_round_trip_against_real_reports():
    """The multi-level economy setting, on the family that reaches it through the published map.

    It sits in the same word as the left-right vane, two bits above it, counting 0..3 -- where the
    classic family spends three bits on the same setting in the same place and counts 0/5/6/7.
    Callers keep handing the classic codes; the family translates.

    Four reports off one unit, one per level, settle it: the encoder seeded from the report taken
    with economy off reproduces each of the other three control words byte for byte, and nothing
    else in the word moves -- the vane sits at position 5 throughout."""
    wm = uss.select_wire_model(175)
    baseline = wm.baseline_words(STATUS_175_ECO_OFF)

    assert wm.current_write_value(STATUS_175_ECO_OFF, "ecoMode") == 0
    assert wm.current_write_value(STATUS_175_ECO_L2, "ecoMode") == 6      # classic code for level 2
    for report in (STATUS_175_ECO_OFF, STATUS_175_ECO_L2):
        assert wm.current_write_value(report, "windDirectionHorizontal") == 5

    # writing level 2 onto the "off" baseline reproduces the report the unit itself sent at level 2
    assert wm.encode_control(bytes(baseline), {"ecoMode": 6}) == wm.baseline_words(STATUS_175_ECO_L2)
    # and the encoder still refuses a code the setting does not have
    with pytest.raises(ValueError, match="not a supported code"):
        wm.encode_control(bytes(baseline), {"ecoMode": 4})


def test_extended36_reads_back_the_comfort_settings_it_offers():
    """This family offers boost, quiet, health, sleep and the display light as switches, and for a
    while read none of them: every switch sat at off however the unit was set.

    That is worse than a missing entity. The command reaches the air conditioner and the air
    conditioner obeys it, but the switch it was thrown from springs back at the next poll, so the
    owner sees a control that does nothing and stops trusting the rest. The settings share one word
    with the power flag, at the positions the published map states."""
    off = uss.parse_full_status(STATUS_175, uplus_id=UPLUS_175)
    boost = uss.parse_full_status(STATUS_175_BOOST, uplus_id=UPLUS_175)
    sleep = uss.parse_full_status(STATUS_175_SLEEP, uplus_id=UPLUS_175)

    for name in ("strong", "quiet", "health", "sleep"):
        assert off[name] is False, name
    assert off["lamp"] is True                      # this unit's display light was on throughout

    # each report differs from the others in exactly the setting it was taken for
    assert boost["strong"] is True and boost["sleep"] is False
    assert sleep["sleep"] is True and sleep["strong"] is False
    assert boost["power"] is sleep["power"] is True


def test_extended36_claims_the_175_byte_variant_too():
    """A 175-byte report is this family with five extra words on the end, not a new one.

    It decoded to nothing before — an unrecognised length reaching the partial path, which is what
    the reporting unit showed. The map needs no displacement: the unit's own published values agree
    with what these words say, including both vane POSITIONS, which a wrong map would not reproduce.
    """
    from haismart_hrdp import profile_for

    assert len(STATUS_175) == 175
    wm = uss.select_wire_model(175)
    assert wm is not None and wm.family == "extended36"
    # and exactly, from the identifier the unit reports on the discovery channel
    assert uss.select_wire_model(0, UPLUS_175) is wm

    state = uss.parse_full_status(STATUS_175, profile_for("AAC1UKZ01"), uplus_id=UPLUS_175)
    assert state == {
        "power": True, "target_temperature": 24.0, "current_temperature": 26.0,
        "outdoor_temperature": 33.0, "operation_mode": "1", "wind_speed": "3",
        "swing_vertical": False, "swing_horizontal": False, "mode": "cool", "fan_mode": "low",
        "heat_capable": False, "error_code": 0, "last_changed_by": "network",
        "self_cleaning": False, "layout": "extended36", "writable": True,
        "strong": False, "quiet": False, "health": False, "sleep": False, "lamp": True,
        # this variant carries its own live power reading; the shorter report has no such word
        "power_w": 1318,
        # and a cumulative energy total, in watt-hours
        "energy_wh": 27851,
    }
    assert "partial" not in state
    # the vanes are parked at positions 2 and 5, which is why neither reads as sweeping
    assert STATUS_175[131] == 2 and STATUS_175[137] & 0x07 == 5
    # screen light on, every other toggle off -- as the unit itself publishes them
    assert wm.current_write_value(STATUS_175, "screenDisplayStatus") == 1
    assert wm.current_write_value(STATUS_175, "healthMode") == 0

    # control seeds from the same five words as on a 165-byte report
    base = wm.baseline_words(STATUS_175)
    assert bytes(base) == STATUS_175[130:140]
    words = wm.encode_control(base, {"targetTemperature": 25 - 16})
    assert words[0] == 25 - 16 and words[1:] == base[1:]


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
    # the economy setting reads back in the classic representation too: this unit had it off
    assert wm.current_write_value(STATUS_165_ON, "ecoMode") == 0


def test_a_32_bit_register_runs_back_into_the_word_before_it():
    """The published map places an attribute by its LEAST significant end, so one wider than a word
    continues into the words *before* it — not after.

    The 209-byte family's report is what settles the direction: its counter's two halves are 11 and
    31040, which read backwards give 751936 and forwards give a number four orders of magnitude out.
    The map's own layout says the same thing independently — its two 24-bit stamps sit at word 7
    bit 8 and word 8 bit 0, which tile words 6..8 exactly when read backwards and overlap when read
    forwards.
    """
    from haismart_hrdp.canonical_map import CANONICAL
    from haismart_hrdp.wire_models import WireField

    assert CANONICAL["totalElectricityUsed"].length == 32
    # the counter sits ten words later on this family, the width of its inserted block
    assert WireField(45, 0, 32, kind="raw").read(STATUS_209_OFF) == 0x000B7940 == 751936
    assert (STATUS_209_OFF[92 + 43 * 2:92 + 45 * 2].hex()) == "000b7940"
    # read the other way it would be nonsense, which is the check that the direction is not arbitrary
    assert int.from_bytes(STATUS_209_OFF[92 + 44 * 2:92 + 46 * 2], "big") == 0x79400000

    # and a single-word field is unaffected: same answer as the plain two-byte read
    assert WireField(41, 0, 16, kind="raw").read(STATUS_175) == 1318


def test_the_energy_total_reads_absent_until_the_unit_populates_it():
    """A cumulative register reading exactly zero is one the firmware never fills in, not a unit
    that has consumed nothing — so it is reported absent rather than as a permanent 0 kWh.

    Both 165-byte reports reach the word (it is not off the end of the shorter report) and both
    read zero there, which is the same state our own units are in.
    """
    from haismart_hrdp import profile_for

    for report in (STATUS_165_OFF, STATUS_165_ON):
        assert len(report) > 92 + 35 * 2                       # the word is present...
        assert report[92 + 33 * 2:92 + 35 * 2] == b"\0\0\0\0"  # ...and reads zero
        assert "energy_wh" not in uss.parse_full_status(report, profile_for("AAC1UKZ01"))

    state = uss.parse_full_status(STATUS_175, profile_for("AAC1UKZ01"))
    assert state["energy_wh"] == 27851
    # the unit publishes the same total twice, at both wire positions -- they agree
    assert int.from_bytes(STATUS_175[92 + 38 * 2:92 + 40 * 2], "big") == 27851


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
        wm.encode_control(base, {"echoStatus": 1})
    # self-clean IS placed on this family now — same shared write frame (start-only), carried over
    # from the classic hardware confirmation; the flag lands in word 5 bit 4.
    assert wm.encode_control(bytearray(base), {"selfCleaningStatus": 1})[9] & 0x10
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
#   A FOURTH report, from a DIFFERENT appliance of the same family, and the one that settles the
#   vane and the fan. What makes it worth more than the three above is not the report: it is that
#   its file carries a cloud record taken close enough to it to agree on everything else --
#   setpoint 22.0, indoor 28.0, power on, and all six word-22 toggles bit for bit. Against that
#   record, the map's own positions read wrong and the inserted block reads right:
#       w20.b0 = 0  vs  windDirectionVertical = 2      w25    = 2
#       w21.b8 = 6  vs  windSpeed             = 1      w26.b9 = 1
#   ...while that same record publishes the per-tower attributes as 0 / 0 and 3 / 5.
#   Cool, setpoint 22, room 28.0, vane parked at position 2, fan high, display light on.
STATUS_209_RUNNING = bytes.fromhex(
    "00002715000000004e5601000003020000040100000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "00000000000000000000000000000081ffff7e000000000000066d0120640000"
    "0000000000000000000000000000000000000000000000000000000000000100"
    "00002c00260f0201000000000002c20000000000000001000000000000000000"
    "383c62100003000000000000000000000000000a584800000000000000000000"
    "0000000000000000000000000000000033"
)
# The cloud record from that same file, for the attributes it can be checked against.
STATUS_209_RUNNING_CLOUD = {
    "targetTemperature": "22.0", "indoorTemperature": "28.0", "onOffStatus": "true",
    "windDirectionVertical": "2", "windSpeed": "1",
    "windDirectionVerticalL": "0", "windDirectionVerticalR": "0",
    "windSpeedL": "3", "windSpeedR": "5",
    "healthMode": "false", "rapidMode": "false", "muteStatus": "false",
    "silentSleepStatus": "false", "screenDisplayStatus": "true",
}


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
        # this family populates its cumulative register, unlike most (see the delta test below)
        "energy_wh": 751936,
        # The five secondary toggles, which this family wrote and never read back until the audit
        # in test_wire_models. They read the same across all three of these captures -- everything
        # off, display lit -- which is plausible but, on its own, is also what reading the wrong
        # zeroed bits would look like. What actually places them is a report from another owner's
        # unit whose word 22 agrees bit for bit with the manufacturer's own record of the same six
        # attributes, including the two that were set.
        "health": False, "strong": False, "quiet": False, "sleep": False, "lamp": True,
    }
    cool = uss.parse_full_status(STATUS_209_COOL, prof)
    assert cool["power"] is True and cool["target_temperature"] == 22.0 and cool["mode"] == "cool"
    fan = uss.parse_full_status(STATUS_209_FAN, prof)
    assert fan["mode"] == "fan_only" and fan["swing_vertical"] is True
    assert fan["current_temperature"] == 26.0 and fan["outdoor_temperature"] == 36.0


def test_the_209_family_reads_its_fan_speed():
    """★ Restored, and this is the THIRD decision about this position, so all of it is kept here.

    For: word 26 bit 9 tracks four captures from two appliances -- low where a capture was taken on
    low, high where taken on high, nothing with the unit off, and 1 where a fresh cloud record for
    that same report said 1. Word 21 bit 8, where every other family keeps fan speed, reads a
    CONSTANT 6 in all of them, including between one owner's stated high and stated low.

    Against, and it was believed for two releases: a fourth capture read 0 here while "the
    appliance's own cloud record said 1", from "a document that agreed with 53 other attributes and
    disagreed with none, so it was not stale". Both halves of that fail:

      * The document was the SAME frozen record as the file before it -- diagnostics carry the
        cloud model as fetched at onboarding -- and in that very file its setpoint said 22.0 while
        the report it was compared against said 24.0.
      * The agreement count runs over ``model_declared_fields``, which holds only the attributes no
        field map reads: the voice module, probes these units do not have, tempUnit, volume. Not
        one of them can change. It agrees by construction and can never detect staleness.

    And the per-tower reading that explained it away is refuted by the same record, which publishes
    the towers as 0 / 0 and 3 / 5 while the wire reads 2 and 1.
    """
    from haismart_hrdp import profile_for
    from haismart_hrdp.wire_models import WireField

    prof = profile_for("AAC1UKZ01")
    speeds = {c: uss.parse_full_status(c, prof).get("fan_mode")
              for c in (STATUS_209_COOL, STATUS_209_FAN, STATUS_209_OFF, STATUS_209_RUNNING)}
    assert speeds[STATUS_209_COOL] == "low"        # capture taken on low
    assert speeds[STATUS_209_FAN] == "high"        # capture taken on high
    assert speeds[STATUS_209_RUNNING] == "high"    # cloud record for this report: windSpeed 1
    # An idle or off appliance reads 0 there, which is not a code its model declares, so it
    # surfaces as NO reading. That is the whole reason the field is an enum and not a raw int: the
    # failure this position was withdrawn for -- showing a stopped fan as a speed -- cannot occur.
    assert speeds[STATUS_209_OFF] is None
    assert WireField(26, 9, 3, kind="raw").read(STATUS_209_OFF) == 0

    # The map's own position, constant across every capture from both appliances.
    for capture in (STATUS_209_COOL, STATUS_209_FAN, STATUS_209_OFF, STATUS_209_RUNNING):
        assert WireField(21, 8, 3, kind="raw").read(capture) == 6


def test_the_209_family_reads_the_appliance_vane_not_a_tower():
    """The one file that could choose between report w20 and report w25, and does.

    Its cloud record is fresh -- checked here rather than asserted, on the attributes that would
    have moved if it were not -- so its ``windDirectionVertical`` of 2 belongs beside this report.
    Word 25 reads 2. The map's w20 reads 0. And the per-tower attributes the withdrawal invoked are
    published in the same record as 0 / 0, so they are not what w25 is showing.
    """
    from haismart_hrdp import profile_for
    from haismart_hrdp.wire_models import WireField

    cloud = STATUS_209_RUNNING_CLOUD
    decoded = uss.parse_full_status(STATUS_209_RUNNING, profile_for("AAC1UKZ01"))
    # Freshness, established from the file itself: the volatile attributes agree. This is the check
    # the withdrawal needed and did not make.
    assert decoded["target_temperature"] == float(cloud["targetTemperature"])
    assert decoded["current_temperature"] == float(cloud["indoorTemperature"])
    assert decoded["power"] is (cloud["onOffStatus"] == "true")
    assert decoded["lamp"] is (cloud["screenDisplayStatus"] == "true")
    for ours, theirs in (("health", "healthMode"), ("strong", "rapidMode"),
                         ("quiet", "muteStatus"), ("sleep", "silentSleepStatus")):
        assert decoded[ours] is (cloud[theirs] == "true")

    assert WireField(25, 0, 4, kind="raw").read(STATUS_209_RUNNING) == int(
        cloud["windDirectionVertical"]
    )
    assert WireField(20, 0, 4, kind="raw").read(STATUS_209_RUNNING) == 0
    assert cloud["windDirectionVerticalL"] == cloud["windDirectionVerticalR"] == "0"
    assert {cloud["windSpeedL"], cloud["windSpeedR"]} == {"3", "5"}  # neither is the wire's 1
    # A parked position is not a sweep, and this one is parked.
    assert decoded["swing_vertical"] is False

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


def test_extended46_control_extends_the_group_set_to_the_appliance_vane():
    """Control is the `6001` group-set seeded from report word 20 -- but SEVEN words, not five, so
    it reaches the appliance's own vane and fan in the inserted block (group-set words 6/7 = report
    w25/w26). The shared five-word frame stops at w24 and never touches them; worse, its w1/w2 slots
    are the LEFT TOWER on this family. See `test_ext46_writes_the_appliance_vane_not_the_tower`."""
    wm = uss.select_wire_model(209)
    assert wm.group_cmd == b"\x60\x01" and wm.write_base_word == 20 and wm.word_count == 7
    base = wm.baseline_words(STATUS_209_COOL)
    assert bytes(base) == STATUS_209_COOL[130:144]    # report words 20..26

    words = wm.encode_control(base, {"operationMode": 6, "onOffStatus": 0})
    frame = uss.build_epp_frame(0x01, wm.group_cmd, words)
    assert frame[:2] == b"\xff\xff" and frame[10:12] == b"\x60\x01"
    assert (frame[2] + sum(frame[3:-1])) & 0xFF == frame[-1]
    assert (words[2] << 8 | words[3]) >> 13 == 6      # operationMode word2 b13 -> fan_only
    assert words[5] & 0x01 == 0                       # onOffStatus word3 b0 cleared
    assert words[0] == base[0]                        # setpoint untouched

    # Fan speed and the up-down vane at the APPLIANCE's own positions: group-set word 7 (report
    # w26.b9) and word 6 (report w25.b0) -- where the read map reads them back, not the shared slots.
    fan = wm.encode_control(bytearray(base), {"windSpeed": 3})
    assert (fan[12] << 8 | fan[13]) >> 9 & 0x07 == 3  # windSpeed group-set word7 b9 -> low
    assert fan[2] == base[2] and fan[3] == base[3]    # word 2 (the tower fan slot) untouched
    vane = wm.encode_control(bytearray(base), {"windDirectionVertical": 0x0C})
    assert (vane[10] << 8 | vane[11]) & 0x0F == 0x0C  # windDirectionVertical group-set word6 b0
    assert vane[0] == base[0] and vane[1] == base[1]  # word 1 (setpoint + tower vane slot) untouched

    # The left-right vane is NOT settable here: nothing in this family's report reads it back, and a
    # control that writes what it cannot read shows its owner a switch that never moves.
    with pytest.raises(KeyError):
        wm.encode_control(base, {"windDirectionHorizontal": 1})


EXT46_UPLUS_ID = "2008610800820324021200118017740000000000000000000000000000000040"


def test_a_short_frame_is_not_this_family_however_it_names_itself():
    """A frame too short to carry the family's readings must NOT decode as that family's status.

    Reported from a live 209-byte unit: every command failed with `report too short (93) for
    extended46 baseline`. A uPlusId match beats the length in `WireModel.matches`, deliberately --
    the appliance names its own family on the discovery channel, key-free. So a 93-byte frame from
    that appliance was claimed by extended-46, read nothing (every field lies past its end),
    vetoed nothing (a plausibility check on a value that was never read passes), and came back as a
    successful decode holding only the `layout`/`writable` markers. The coordinator takes any
    truthy decode as the full status report, caches the blob, and seeds the next group-set from
    it -- so one short frame broke control until a later poll happened to overwrite the cache.
    """
    short = STATUS_209_COOL[:93]
    assert uss.select_wire_model(len(short), EXT46_UPLUS_ID).family == "extended46"
    assert uss.parse_full_status(short, uplus_id=EXT46_UPLUS_ID) == {}

    # It is length, not content: the same appliance's real report still decodes as it always did.
    assert uss.parse_full_status(
        STATUS_209_COOL, uplus_id=EXT46_UPLUS_ID
    )["layout"] == "extended46"


def test_a_non_classic_family_can_seed_its_own_group_set_from_the_live_push():
    """The op connection's own status push must be usable as the group-set baseline here too.

    The gate was written before the wire-model registry existed and only ever recognised the
    classic lengths, so on every other family the in-session baseline came back as "nothing
    arrived" and control fell through to the caller's CACHED blob -- the stale seed that
    single-session read-modify-write exists to avoid, and the reason one bad cache entry could
    keep breaking commands.
    """
    assert uss.is_control_baseline(STATUS_209_COOL, EXT46_UPLUS_ID)
    assert uss.is_control_baseline(STATUS_209_COOL)          # by length alone, as the poll does
    assert uss.is_control_baseline(REAL_STATUS_DOWN)         # the classic table still answers

    # what it must still refuse: a short frame, and a family with no confirmed group-set
    assert not uss.is_control_baseline(STATUS_209_COOL[:93], EXT46_UPLUS_ID)
    assert not uss.is_control_baseline(b"\x00\x00\x27\x15")


def test_a_decode_that_reads_nothing_is_never_a_decode():
    """The general form, across every registered family: a report cut short of the readings a
    thermostat is made of is refused, whatever its length says. Both anchors have to arrive --
    which is also what guarantees a decoded report can seed its own family's group-set."""
    from haismart_hrdp.wire_models import _ATTR_BASE, WIRE_MODELS

    for wm in WIRE_MODELS:
        anchors = (wm.fields[wm.indoor_key], wm.fields[wm.target_key])
        need = max(_ATTR_BASE + 2 * f.word for f in anchors)
        assert wm.decode(bytes(need - 1)) is None
        if wm.writable:
            # the anchor requirement is the stricter of the two, so anything that decodes has a
            # complete settable word block to seed from
            assert need >= _ATTR_BASE + 2 * (wm.write_base_word - 1) + 2 * wm.word_count


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


def test_probe_layout_scores_the_states_the_captures_were_taken_in():
    """The states a reporter writes down are ground truth, and they do the shadow's job for free.

    Without them almost every candidate ties: a report is mostly zeros, so a map whose fields land
    on empty words decodes a cold, off unit just as "plausibly" as the right one, and the ranking
    comes down to a tie-break. Told what the unit was actually doing, the wrong maps fall away.
    """
    from haismart_hrdp import StatedState, probe_layout

    reports = [STATUS_165_OFF, STATUS_165_ON]
    stated = [
        StatedState(power=False, target_temperature=22, current_temperature=30.0,
                    swing_vertical=False, mode_group="cool", fan_group="high"),
        StatedState(power=True, target_temperature=20, current_temperature=27.5,
                    swing_vertical=False, mode_group="cool", fan_group="high"),
    ]
    plain = probe_layout(reports, limit=500)
    assert sum(1 for c in plain if c["score"] == plain[0]["score"]) > 50   # the tie it starts from

    scored = probe_layout(reports, stated=stated, limit=500)
    best = scored[0]
    assert (best["family"], best["pivot"], best["shift"], best["setpoint"]) == (
        "extended36", 1, 0, "offset16"
    )
    assert [d["target_temperature"] for d in best["decoded"]] == [22.0, 20.0]

    # a candidate that reads the setpoint out of an empty word ties on plausibility alone and is
    # decisively behind once the stated setpoint is scored
    by_key = {(c["pivot"], c["shift"], c["setpoint"]): c for c in scored}
    wrong = by_key[(1, 22, "offset16")]
    assert wrong["decoded"][0]["target_temperature"] == 16.0
    assert wrong["score"] < best["score"]


def test_stated_states_catch_a_map_that_cannot_tell_two_modes_apart():
    """The relational half, which is what makes stated states work without knowing a model's codes.

    A reporter says "cool" and "fan-only", not "1" and "6". So captures given different labels must
    decode to different codes — and a map whose mode field lands on a word that never changes reads
    one code in both, which is precisely the failure mode the prober exists to catch.
    """
    from haismart_hrdp import StatedState, wire_models

    cool, fan = STATUS_165_ON, bytearray(STATUS_165_ON)
    fan[132] = (fan[132] & 0x1F) | (6 << 5)          # word 21 bits 13-15: mode -> fan-only
    labelled = [StatedState(mode_group="cool"), StatedState(mode_group="fan_only")]
    same = [StatedState(mode_group="cool"), StatedState(mode_group="cool")]

    def score_of(stated, pivot, shift):
        for c in wire_models.probe_layout([cool, bytes(fan)], stated=stated, limit=500):
            if c["pivot"] == pivot and c["shift"] == shift and c["setpoint"] == "offset16":
                return c["score"]
        raise AssertionError("candidate not proposed")

    # the true map reads two different codes, so it agrees with the two labels and disagrees with
    # calling them the same
    assert score_of(labelled, 1, 0) > score_of(same, 1, 0)
    # a map displaced past the mode word reads the same code in both captures, so it fails the
    # labels the true map satisfies -- and ends up behind by more than agreement alone would give
    assert score_of(labelled, 1, 0) > score_of(labelled, 1, 22)


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
    # 0 = fixed and 7 = auto are the two codes ever seen written, and the only two the encoder
    # allows on its own. Unlike windDirectionVertical, the raw EPP value equals the STD code, which
    # is why the coordinator can gate it against valueRange -- and why the model may widen it.
    assert uss.GRSETDAC_ENUMS["windDirectionHorizontal"] == {"off": 0x00, "on": 0x07}
    assert uss.GRSETDAC_ALLOWED_VALUES["windDirectionHorizontal"] == {0x00, 0x07}
    assert uss.GRSETDAC_FIELDS["windDirectionHorizontal"] == (4, 0, 3)
    assert "windDirectionHorizontal" in uss.GRSETDAC_MODEL_AUTHORIZED


def test_model_declared_vane_positions_are_encodable():
    """The stops between fixed and auto are the device model's to authorize.

    A model that lists eight codes for this vane describes eight real positions, and the field's
    raw value is the code the model names -- so a unit can be pointed at one of them without the
    encoder having ever seen that code written. A code the model does not list stays refused.
    """
    base = uss.grsetdac_baseline_from_status(STATUS_125)
    declared = {0, 1, 2, 3, 4, 5, 6, 7}
    with pytest.raises(ValueError):
        uss.set_grsetdac_field(base, "windDirectionHorizontal", 4)   # no model, no position
    parked = uss.set_grsetdac_field(base, "windDirectionHorizontal", 4, model_values=declared)
    assert (parked[6] << 8) | parked[7] == 0x0004
    assert parked[:6] == base[:6] and parked[8:] == base[8:]   # nothing outside word 4 moved

    # a vane parked at a position is NOT sweeping, and eco (same word) is untouched
    report = STATUS_125[:92] + parked + STATUS_125[92 + len(parked):]
    state = uss.parse_full_status(report)
    assert state["swing_horizontal"] is False
    assert state["eco"] == 0

    with pytest.raises(ValueError):
        uss.set_grsetdac_field(base, "windDirectionHorizontal", 5, model_values={0, 4, 7})


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
    # the outdoor probes this unit does not carry are absent rather than reported as -64 C
    assert "outdoor_coil_temperature" not in got
    assert "outdoor_in_air_temperature" not in got
    assert "outdoor_defrost_temperature" not in got


def test_parse_extended_status_decodes_an_idle_unit():
    got = uss.parse_extended_status(EXT_IDLE)
    assert got["power_w"] == 0
    assert got["compressor_current_a"] == 0.0
    assert got["compressor_frequency_hz"] == 0
    assert got["compressor_running"] is False
    assert got["fan_running"] is False
    assert got["coil_temperature"] == 28.0      # coil sits at room temperature


def test_extended_actuator_states_omit_the_ones_a_unit_will_not_report():
    """Each actuator state is 0 off, 1 on, 2 not reported -- three values, not a flag.

    A unit that cannot tell you keeps saying so, so reading the field for truthiness would pin the
    sensor on forever. The reference unit reports "not reported" for its reversing valve and outdoor
    fan whether it is cooling hard or sitting idle at 0 W; those keys must be absent, so the entity
    reads unknown rather than claiming both were running on a unit doing nothing.
    """
    cooling = uss.parse_extended_status(EXT_COOLING)
    idle = uss.parse_extended_status(EXT_IDLE)

    # the two this unit does report answer honestly, and differ between the two states
    assert cooling["compressor_running"] is True and idle["compressor_running"] is False
    assert cooling["fan_running"] is True and idle["fan_running"] is False
    # the ones it declines to report are absent in both, not False and certainly not True
    for key in ("four_way_valve_status", "outdoor_fan_status"):
        assert key not in cooling and key not in idle


def test_an_unreported_actuator_never_reads_as_running():
    """The regression this guards: `bool(state)` turns "not reported" (2) into "running"."""
    blob = bytearray(EXT_IDLE)
    off = uss._EXT_OFF_ACTUATORS
    # force every state to "not reported" -- 0b10 repeated across all six pairs
    blob[off:off + 2] = (0xAAA).to_bytes(2, "big")
    got = uss.parse_extended_status(bytes(blob))
    for key, _ in uss._EXT_ACTUATOR_STATES:
        assert key not in got, f"{key} was reported despite the unit declining to say"
    # and a unit that does answer still comes through
    blob[off:off + 2] = (0b01 | (0b01 << 2)).to_bytes(2, "big")
    got = uss.parse_extended_status(bytes(blob))
    assert got["compressor_running"] is True and got["fan_running"] is True


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
    """Only the auto codes sweep. Every other value is the vane parked somewhere.

    The codes here are the full set a unit reports while its louver control is stepped through every
    position: 1 and 3 are the two health-airflow positions, 2/4/6/8 the ordinary ones, 12 auto.
    **8 is the case that matters** -- the vane parked pointing down, which a single-bit `& 0x08` test
    reports as sweeping. 14 is auto under the special modes.
    """
    sweeping = {0x0C, 0x0E}
    observed = (1, 2, 3, 4, 6, 8, 12)
    for code in observed + (0x00, 0x0A, 0x0E):
        assert uss.vane_v_sweeping(code) is (code in sweeping), f"wire code {code:#04x}"

    # the specific regression: parked-down must not read as sweeping
    assert uss.vane_v_sweeping(0x08) is False
    assert uss.vane_v_sweeping(0x0A) is False


def test_horizontal_vane_only_auto_counts_as_swinging():
    """Horizontal: 0 = fixed, 3..6 = positions, 7 = auto.

    All six are values a unit reports as its left-right control is stepped through. A plain
    truthiness test called every one of 3, 4, 5 and 6 swinging while the vane was parked.
    """
    blob = bytearray(REAL_STATUS_DOWN)
    words = uss.STATUS_LAYOUTS[len(blob)].baseline
    for code, expected in ((0, False), (3, False), (4, False), (5, False), (6, False), (7, True)):
        block = bytearray(blob[words])
        block[7] = (block[7] & ~0x07) | code
        blob[words] = block
        assert uss.parse_full_status(bytes(blob))["swing_horizontal"] is expected, f"code {code}"


def test_extended36_reports_self_clean_from_its_flag_word():
    """The 165-byte family carries the flag word four words into its control block.

    Both reports have it reading 0x000c -- bits 2 and 3, the pair the health setting drives -- with
    bit 4 clear, which is what a unit that is not cleaning looks like.
    """
    for report in (STATUS_165_OFF, STATUS_165_ON):
        assert uss.parse_full_status(report)["self_cleaning"] is False

    cleaning = bytearray(STATUS_165_OFF)
    flag_at = 92 + (24 - 1) * 2          # report word 24
    cleaning[flag_at + 1] |= 1 << 4
    assert uss.parse_full_status(bytes(cleaning))["self_cleaning"] is True


def test_self_clean_is_absent_where_the_flag_word_is_unconfirmed():
    """Offered only where the position is supported by evidence -- absent beats wrong."""
    for report in (STATUS_209_OFF, STATUS_117_OFF):
        assert "self_cleaning" not in uss.parse_full_status(report)


# --- the canonical map ------------------------------------------------------------------------
def test_canonical_map_reproduces_every_family_we_ship():
    """One map, displaced, is what all these layouts are.

    Each family here was worked out separately, field by field, from captured reports. They are all
    the same published map at a different displacement — so this asserts the correspondence rather
    than trusting it, and a future edit that drifts from it fails here.
    """
    from haismart_hrdp.canonical_map import CANONICAL, DISPLACEMENTS

    assert set(DISPLACEMENTS) == {0, -19}

    # the classic family: the canonical map 19 words earlier
    from haismart_hrdp.panel import PANEL_EXTRA_POSITIONS
    for name, (word, bit, length) in uss.GRSETDAC_FIELDS.items():
        if name == "ecoMode" or name in PANEL_EXTRA_POSITIONS:
            continue          # not described by the read map (repurposed / order-derived)
        c = CANONICAL[name]
        assert (c.word - 19, c.bit, c.length) == (word, bit, length), name

    # the classic sensor block, from the 125-byte layout's byte offsets
    classic = uss.STATUS_LAYOUTS[125]
    for name, offset in (("indoorTemperature", classic.indoor_temp),
                         ("outdoorTemperature", classic.outdoor_temp)):
        word = (offset - 92) // 2 + 1
        assert CANONICAL[name].word - 19 == word, name
    # our own units carry ONE extra word before the sensors, which is the 127-byte layout
    assert uss.STATUS_LAYOUTS[127].indoor_temp == classic.indoor_temp + 2

    # extended-36: the same map at displacement 0, no shifting at all
    ext36 = uss.select_wire_model(165)
    for name, field in ext36.fields.items():
        canonical_name = {
            "current_temperature": "indoorTemperature", "outdoor_temperature": "outdoorTemperature",
            "target_temperature": "targetTemperature", "operation_mode": "operationMode",
            "wind_speed": "windSpeed", "power": "onOffStatus",
            "swing_vertical": "windDirectionVertical", "swing_horizontal": "windDirectionHorizontal",
            "error_code": "errCode",
        }.get(name)
        if canonical_name is None:
            continue
        c = CANONICAL[canonical_name]
        assert (c.word, c.bit) == (field.word, field.bit), name
        assert (c.k, c.c) == (field.k, field.c) or field.kind in ("enum", "vane_v", "vane_h"), name

    # the up-down vane's translation was settled by stepping a unit through every stop; the
    # published map agrees with it exactly, including the one entry no unit here ever exercised
    from haismart_hrdp import VANE_V_MODEL_TO_EPP

    published = {std: epp for epp, std in CANONICAL["windDirectionVertical"].enum.items()}
    assert all(published[std] == epp for std, epp in VANE_V_MODEL_TO_EPP.items())

    # extended-46: the same map again, with its ten-word block inserted at word 25
    ext46 = uss.select_wire_model(209)
    assert ext46.fields["current_temperature"].word == CANONICAL["indoorTemperature"].word + 10
    assert ext46.fields["outdoor_temperature"].word == CANONICAL["outdoorTemperature"].word + 10
    assert ext46.fields["power"].word == CANONICAL["onOffStatus"].word      # before the insert


def test_declared_fields_reads_what_a_device_says_it_has():
    """A device declares three or four times the attributes any family map carries, and every one
    of them sits where the published map already says. Reading them needs no capture per attribute:
    membership comes from the device's own model, position from the map, and the two are arrived at
    independently."""
    from haismart_hrdp.canonical_map import CANONICAL
    from haismart_hrdp.wire_models import _CLASSIC_PROBE

    declared = [
        "lockStatus", "targetHumidity", "freshAirStatus", "indoorHumidity",
        "onOffStatus", "healthMode",   # already in the family map -- must not be duplicated
        "someAttributeNobodyPublishes",  # not in the map -- must be ignored, not guessed at
    ]
    fields = _CLASSIC_PROBE.model_fields(declared, 125)

    for covered in ("onOffStatus", "healthMode"):
        assert covered not in fields, "re-read an attribute the family map already carries"
    assert "someAttributeNobodyPublishes" not in fields
    assert set(fields) == {"lockStatus", "targetHumidity", "freshAirStatus", "indoorHumidity"}
    # positions are the published ones, displaced by the family's confirmed offset
    for name, wf in fields.items():
        c = CANONICAL[name]
        assert (wf.word, wf.bit, wf.length) == (c.word - 19, c.bit, c.length), name

    # ...and they decode a real report. The child lock was off on the unit this capture came from,
    # and its humidity probe read 55 -- a reading nothing else in the report exposes.
    assert fields["lockStatus"].read(STATUS_125) is False
    assert fields["indoorHumidity"].read(STATUS_125) == 55


def test_declared_fields_refuse_a_family_with_no_confirmed_displacement():
    """A family with no established relationship to the published map places nothing.

    compact-12 is the genuine case: a different protocol generation packing one attribute per whole
    word, so no displacement was ever going to fit it. Reading a device's other attributes off the
    map there would place every one of them plausibly and wrongly.

    ⚠️ This used to be asserted of extended-46, which was wrong about that family rather than about
    the rule. An insert is not the absence of a relationship, it is a piecewise one -- and treating
    the two alike cost that family every attribute its devices declare. See
    ``test_an_inserted_block_no_longer_blocks_reading_declared_attributes``.
    """
    compact = uss.select_wire_model(117)
    assert compact.canonical_displacement is None
    assert compact.model_fields(["lockStatus", "freshAirStatus", "targetHumidity"], 117) == {}


def test_declared_fields_read_a_code_as_the_device_publishes_it():
    """An unscaled number is a CODE, and the published map states, for every attribute it carries,
    whether the wire numbering is the published numbering. Where the two differ it carries the
    translation; where they agree it carries none. So a code is translated or taken as it stands --
    never guessed at, and never dropped for want of an answer the map already gives."""
    from haismart_hrdp.canonical_map import CANONICAL
    from haismart_hrdp.wire_models import declared_fields

    fields = declared_fields(-19, ["tempUnit", "specialMode", "lockStatus", "targetHumidity"],
                             word_limit=17)
    assert set(fields) == {"tempUnit", "specialMode", "lockStatus", "targetHumidity"}
    # tempUnit is one of the two attributes that number themselves differently in the two places:
    # it puts 0 on the wire for the value it publishes as 1. Reporting the raw value reported
    # something the device never states, so the map's translation is applied.
    assert fields["tempUnit"].kind == "enum"
    assert fields["tempUnit"].enum == CANONICAL["tempUnit"].enum
    assert fields["tempUnit"].read(STATUS_125) == CANONICAL["tempUnit"].enum[0] == 1
    # specialMode's numbering is the same in both places, so its wire value is already the answer
    assert fields["specialMode"].kind == "raw"
    assert fields["specialMode"].read(STATUS_125) == 0
    # ...and a scaled one keeps the offset that makes it the published value
    assert fields["targetHumidity"].c == CANONICAL["targetHumidity"].c


def test_declared_fields_drop_what_the_report_cannot_hold():
    """An attribute the displacement would push past the end of a short report is dropped rather
    than read off whatever follows the array."""
    from haismart_hrdp.wire_models import declared_fields

    # ErrAckFlag is canonical w27; at -19 it needs word 8, so a 6-word report cannot carry it
    # while a 10-word one can.
    assert "ErrAckFlag" not in declared_fields(-19, ["ErrAckFlag"], word_limit=6)
    assert "ErrAckFlag" in declared_fields(-19, ["ErrAckFlag"], word_limit=10)


def test_classic_family_reads_a_cumulative_total_where_one_is_kept():
    """The classic family is the published map 19 words earlier, and that map puts a 32-bit
    watt-hour total ten words past the sensor block -- which on both known control-word counts is
    the report's last two words. The unit is the one settled on the extended-36 family against an
    owner's own app; it is the same attribute at the same place in the same map."""
    assert uss.parse_full_status(STATUS_125)["energy_wh"] == 3138753          # 5 control words
    assert uss.STATUS_LAYOUTS[125].energy == 122 and uss.STATUS_LAYOUTS[127].energy == 124


def test_classic_family_omits_a_total_it_never_populates():
    """Most of this family carries the register and leaves it at zero for its whole service life --
    both reference units do. A permanent 0 kWh sitting in someone's Energy dashboard is worse than
    no sensor, so zero is reported as absent rather than as a total of nothing."""
    for report in (REAL_STATUS_DOWN, REAL_STATUS_UP):
        decoded = uss.parse_full_status(report)
        assert "energy_wh" not in decoded
        assert decoded["current_temperature"] is not None    # ...and the rest still decodes


def test_energy_offset_follows_the_control_word_count():
    """The sensor block moves with the number of control words a model reports, and the total moves
    with it -- so a derived layout places it by the same arithmetic rather than a constant."""
    for words, expected in ((5, 122), (6, 124), (7, 126)):
        assert uss.StatusLayout.for_words(words, verified=False).energy == expected


_DECLARED_ORDER = (
    "targetTemperature", "windDirectionVertical", "operationMode", "specialMode", "windSpeed",
    "energySavePeriod", "selfCleaning56Status", "tempUnit", "screenDisplayStatus", "echoStatus",
    "lockStatus", "silentSleepStatus", "muteStatus", "rapidMode", "healthMode", "onOffStatus",
    "windDirectionHorizontal", "selfCleaningStatus",
)


def test_declared_order_is_read_from_a_model_and_empty_from_a_shadow():
    """A device's published model lists its group-set settings in wire order. A shadow that was
    never topped up from it has the section but leaves it empty, which must read as "no order
    stated" rather than as an empty order that would reject everything."""
    from haismart_hrdp import declared_order

    model = {"groupCommands": [{"name": "grSetDAC", "attrNameList": list(_DECLARED_ORDER)}]}
    assert declared_order(model) == _DECLARED_ORDER
    assert declared_order({"groupCommands": {}}) == ()
    assert declared_order({}) == ()
    assert declared_order(None) == ()


def test_declared_order_rejects_the_families_that_arrange_settings_differently():
    """The order is relative, so it cannot say WHERE a block starts. What it can do is refuse a
    family whose map arranges its settings in a different sequence.

    Two of the four do: extended-46 puts a vane five words on with its fan speed inside an inserted
    block, and compact-12 is not this lineage at all. Against a real declaration every candidate of
    both is refused and every classic and extended-36 candidate passes -- roughly half the search
    space pruned before anything is decoded.

    And the limit, asserted so nobody expects more of it: the search only ever moves fields LATER,
    so a pivot and a positive shift preserve an ascending order whatever they are. This prunes the
    family branch, never the offset."""
    from haismart_hrdp.wire_models import (
        _SETPOINT_ENCODINGS,
        EXTENDED36,
        PROBE_FAMILIES,
        _score_order,
        _shift_model,
    )

    # a displacement -- any pivot, any shift -- leaves the order exactly as it was
    base = _score_order(_shift_model(EXTENDED36, 1, 0, _SETPOINT_ENCODINGS[0]), _DECLARED_ORDER)
    assert base > 0
    for pivot, shift in ((1, 7), (22, 6), (21, 19)):
        moved = _shift_model(EXTENDED36, pivot, shift, _SETPOINT_ENCODINGS[0])
        assert _score_order(moved, _DECLARED_ORDER) == base, (pivot, shift)

    verdicts = {}
    for model in PROBE_FAMILIES:
        scores = [
            _score_order(_shift_model(model, pivot, shift, _SETPOINT_ENCODINGS[0]), _DECLARED_ORDER)
            for pivot in sorted({f.word for f in model.fields.values()} | {1})
            for shift in range(25)
        ]
        verdicts[model.family] = all(s < 0 for s in scores)
    assert verdicts == {
        "classic": False, "extended36": False,      # this lineage: every candidate passes
        "extended46": True, "compact12": True,      # a different arrangement: all refused
    }


def test_declared_bool_features_reads_from_the_model_and_the_map():
    """The optional features a device declares, read read-only from the published map. Membership is
    the device's model, position the map, value the bit -- confirmed 7/7 against the cloud on a real
    unit. Family with no confirmed displacement yields nothing (no guess)."""
    from haismart_hrdp import declared_bool_features, read_bool_features
    from haismart_hrdp.wire_models import _CLASSIC_PROBE, COMPACT12, EXTENDED46

    # `invisible_attributes` present (even empty) is the signal that the unit's real feature set is
    # known; a model without it gets no optional-feature entities at all -- never a guess.
    model = {"invisible_attributes": [], "attributes": [
        {"name": "freshAirStatus"}, {"name": "electricHeatingStatus"}, {"name": "lightStatus"},
        {"name": "onOffStatus"},               # not an optional feature -- ignored
        {"name": "somethingNobodyLists"},       # not in the map -- ignored
    ]}
    assert declared_bool_features(model) == frozenset(
        {"freshAirStatus", "electricHeatingStatus", "lightStatus"})
    # a model that does NOT yet know its invisible set offers nothing (no phantoms while unsure)
    assert declared_bool_features({"attributes": [{"name": "freshAirStatus"}]}) == frozenset()
    # a bare list of names is a caller vouching for the set directly
    assert declared_bool_features(["lightStatus", "x"]) == frozenset({"lightStatus"})
    # an entry with no name is dropped; one literally named "None" is not confused for it
    assert declared_bool_features(dict(model, attributes=[{"foo": 1}, {"name": "lightStatus"}])) \
        == frozenset({"lightStatus"})
    # an attribute the model marks invisible is one this unit does not have -- dropped, so no phantom
    # entity that reads a permanent off (the generic model over-declares; invisible is how it says so)
    model_inv = dict(model, invisible_attributes=["electricHeatingStatus"])
    assert declared_bool_features(model_inv) == frozenset({"freshAirStatus", "lightStatus"})

    got = read_bool_features(_CLASSIC_PROBE, model, STATUS_125)
    assert set(got) == {"freshAirStatus", "electricHeatingStatus", "lightStatus"}
    assert all(isinstance(v, bool) for v in got.values())
    # a family with no established relationship to the map places nothing
    assert read_bool_features(COMPACT12, model, b"\x00" * 117) == {}
    # ...while one that displaces the map piecewise does place them, which is the whole point of
    # describing an insert rather than giving up on the family
    assert set(read_bool_features(EXTENDED46, model, b"\x00" * 209)) == {
        "freshAirStatus", "electricHeatingStatus", "lightStatus"}


def test_declared_enum_features_reads_labelled_state():
    """humanSensingStatus is a multi-state optional feature -- read read-only as its labelled state,
    at its published-map position, and only where the unit's feature set is known (invisible gate)."""
    from haismart_hrdp import declared_enum_features, read_enum_features
    from haismart_hrdp.wire_models import _CLASSIC_PROBE, COMPACT12, EXTENDED46

    model = {"invisible_attributes": [], "attributes": [{"name": "humanSensingStatus"}]}
    assert declared_enum_features(model) == frozenset({"humanSensingStatus"})
    # unknown feature set -> nothing (never a guess)
    assert declared_enum_features({"attributes": [{"name": "humanSensingStatus"}]}) == frozenset()
    # invisible -> the unit does not have it -> dropped
    assert declared_enum_features(
        dict(model, invisible_attributes=["humanSensingStatus"])) == frozenset()

    got = read_enum_features(_CLASSIC_PROBE, model, STATUS_125)
    assert set(got) == {"humanSensingStatus"}
    assert got["humanSensingStatus"] in {"off", "avoid", "follow", "on"}
    # a family with no confirmed displacement places nothing
    assert read_enum_features(COMPACT12, model, b"\x00" * 117) == {}
    assert read_enum_features(EXTENDED46, model, b"\x00" * 209) == {"humanSensingStatus": "off"}


def test_the_127_byte_layout_shifts_canonical_words_25_and_up_by_one():
    """The rental SKU's 127-byte report carries one word the published map does not describe
    (`targetRentTime`, its report word 6), so canonical words 25+ sit one further along than the
    flat -19 -- exactly the difference between the two confirmed STATUS_LAYOUTS. Reading the map
    flat on a 127-byte report put every attribute above the flag word (humidity, the whole
    air-quality suite) one word early: not zeros, plausible garbage.

    Pinned against the hardware-confirmed layout table rather than magic numbers: canonical
    `indoorHumidity` shares its word with `indoorTemperature`, whose byte offset per report length
    is STATUS_LAYOUTS' own (capture-verified) `indoor_temp`.
    """
    from haismart_hrdp.canonical_map import CANONICAL
    from haismart_hrdp.wire_models import _CLASSIC_PROBE

    names = ["indoorHumidity", "indoorPM2p5Value", "co2Value", "freshAirStatus"]
    for length in (125, 127):
        placed = _CLASSIC_PROBE.model_fields(names, length)
        # indoorHumidity is the low byte of the word whose high byte is the indoor temperature,
        # and THAT byte is confirmed per length by the layout table itself.
        expected_word = (uss.STATUS_LAYOUTS[length].indoor_temp - 92) // 2 + 1
        assert placed["indoorHumidity"].word == expected_word, length
        # the air-quality block keeps its distance from the humidity word in both layouts
        assert placed["indoorPM2p5Value"].word == expected_word + (
            CANONICAL["indoorPM2p5Value"].word - CANONICAL["indoorHumidity"].word)
        assert placed["co2Value"].word == expected_word + (
            CANONICAL["co2Value"].word - CANONICAL["indoorHumidity"].word)
        # below the pivot nothing moves: the flag word is w5 on both members
        assert placed["freshAirStatus"].word == 5, length
    # and the two layouts differ by exactly the one inserted word
    assert (_CLASSIC_PROBE.model_fields(names, 127)["co2Value"].word
            == _CLASSIC_PROBE.model_fields(names, 125)["co2Value"].word + 1)


def test_declared_numeric_readings_read_the_air_quality_suite():
    """The PM2.5/CO2/formaldehyde/VOC/humidity values a unit's own model declares, read from the
    status report at the published positions. Zero is the register of a probe the unit does not
    have and a value above the published maximum is a sentinel -- both absent, never a reading."""
    from haismart_hrdp import declared_numeric_readings, read_numeric_readings
    from haismart_hrdp.wire_models import _CLASSIC_PROBE, COMPACT12

    model = {"invisible_attributes": [], "attributes": [
        {"name": "co2Value"}, {"name": "indoorPM2p5Value"}, {"name": "indoorHumidity"},
        {"name": "vocValue"},
        {"name": "onOffStatus"},           # not a numeric reading -- ignored
    ]}
    assert declared_numeric_readings(model) == frozenset(
        {"co2Value", "indoorPM2p5Value", "indoorHumidity", "vocValue"})
    # unknown feature set -> nothing; invisible -> the unit does not have the probe -> dropped
    assert declared_numeric_readings({"attributes": [{"name": "co2Value"}]}) == frozenset()
    assert declared_numeric_readings(
        dict(model, invisible_attributes=["co2Value"]))== frozenset(
        {"indoorPM2p5Value", "indoorHumidity", "vocValue"})

    # a 127-byte report with CO2 650 ppm, indoor PM2.5 23 ug/m3, humidity 55 %, VOC 0
    blob = bytearray(127)
    blob[2:4] = b"\x27\x15"
    placed = _CLASSIC_PROBE.model_fields(sorted(declared_numeric_readings(model)), 127)
    def put(name, value):
        f = placed[name]
        end = 92 + f.word * 2
        span = (f.bit + f.length + 15) // 16
        blob[end - span * 2:end] = value.to_bytes(span * 2, "big")
    put("co2Value", 650)
    put("indoorPM2p5Value", 23)
    put("indoorHumidity", 55)
    got = read_numeric_readings(_CLASSIC_PROBE, model, bytes(blob))
    # VOC reads 0 -> absent, not a reading of 0
    assert got == {"co2Value": 650, "indoorPM2p5Value": 23, "indoorHumidity": 55}
    # a raw value above the published maximum is a sentinel, not a measurement
    put("indoorPM2p5Value", 5000)          # published max is 4095
    got = read_numeric_readings(_CLASSIC_PROBE, model, bytes(blob))
    assert "indoorPM2p5Value" not in got and got["co2Value"] == 650
    # a family with no confirmed placement reads nothing
    assert read_numeric_readings(COMPACT12, model, b"\x00" * 117) == {}


def test_invisible_attributes_and_merge_records_them():
    """The published constraintfile marks attributes a generic model lists but this unit lacks
    `invisible`; merge_rules records that set (always, even empty) so the feature entities can tell a
    real feature from an over-declared one. The device shadow carries no such flag."""
    from haismart_hrdp import invisible_attributes, merge_rules

    published = {"attributes": [
        {"name": "healthMode", "invisible": False},
        {"name": "electricHeatingStatus", "invisible": True},
        {"name": "freshAirStatus", "invisiable": True},   # the other spelling seen in the wild
        {"name": "lightStatus"},                           # no flag == present
    ]}
    assert invisible_attributes(published) == frozenset(
        {"electricHeatingStatus", "freshAirStatus"})

    shadow = {"attributes": {"healthMode": {}, "electricHeatingStatus": {}}}
    merged = merge_rules(shadow, published)
    assert merged["invisible_attributes"] == ["electricHeatingStatus", "freshAirStatus"]
    # a model with no invisible flags still records the key (empty) -- presence is the "known" signal
    assert merge_rules(shadow, {"attributes": [{"name": "healthMode"}]})["invisible_attributes"] == []
    # nothing published -> the key is not added at all (we do not claim to know the set)
    assert "invisible_attributes" not in merge_rules(shadow, {})


# --- the write frame --------------------------------------------------------------------------
def test_published_write_map_reproduces_every_confirmed_field():
    """The group-set write frame is published, and it agrees with what is confirmed in use.

    `GRSETDAC_FIELDS` was built one field at a time, each confirmed on hardware. Every one of those
    positions appears in the published map at exactly the same word, bit and width. The two were
    arrived at independently, so this pins them against each other: if either moves, this fails.
    """
    from haismart_hrdp.canonical_map import CANONICAL_WRITE
    from haismart_hrdp.panel import PANEL_EXTRA_POSITIONS
    checked = 0
    for name, (word, bit, width) in uss.GRSETDAC_FIELDS.items():
        if name in PANEL_EXTRA_POSITIONS:
            continue          # order-derived panel control, not in the frame (pinned in test_panel)
        if name == "ecoMode":
            # Device-specific: this unit repurposes word 4 bits 3-5, which the shared map assigns to
            # other attributes. It is established from captures on the units that have it, and is
            # deliberately not expected in a map that describes the shared frame.
            continue
        assert name in CANONICAL_WRITE, f"{name} is confirmed in use but absent from the map"
        w = CANONICAL_WRITE[name]
        assert (w.word, w.bit, w.length) == (word, bit, width), name
        checked += 1
    assert checked >= 11, "expected every confirmed field to be checked"


def test_published_write_map_is_the_reports_writable_words():
    """The map offers far more than is confirmed in use, and it is the report's own words 20-24.

    Write word N is report word 19+N. Words 1-4 are identical bit for bit; word 5 differs only in
    the two filter flags; and there is no write word 6, because report word 25 is where the sensor
    readings begin and a thermometer cannot be written to. The offset is what a family's base word
    exists to apply -- the report is displaced per family and this frame is not, so the two are
    related exactly but must still never be used interchangeably.
    """
    from haismart_hrdp.canonical_map import CANONICAL, CANONICAL_WRITE

    # The encoder is still a subset of the published frame, plus the handful of fields the frame does
    # not carry (ecoMode + the order-derived panel controls). It is no longer "half the size" — the
    # panel surface deliberately widened it — so the check is subset-hood, not a ratio.
    from haismart_hrdp.panel import PANEL_EXTRA_POSITIONS
    off_frame = {"ecoMode", *PANEL_EXTRA_POSITIONS}
    assert set(uss.GRSETDAC_FIELDS) - off_frame <= set(CANONICAL_WRITE)
    for name, w in CANONICAL_WRITE.items():
        c = CANONICAL.get(name)
        if c is None:
            continue
        assert (c.word, c.bit, c.length) == (w.word + 19, w.bit, w.length), name
    # The one field the two sides name differently: the filter flag is asserted by the cloud on the
    # write side and reported by the unit on the read side, at one and the same bit.
    assert CANONICAL_WRITE["cloudFilterChangeFlag"].word + 19 == CANONICAL["localFilterChangeFlag"].word
    assert CANONICAL_WRITE["cloudFilterChangeFlag"].bit == CANONICAL["localFilterChangeFlag"].bit
    # ...and the cleaning-time flag now has its report position too, derived from this very
    # correspondence rather than hand-added: no model states it in `Property`, every model states it
    # in the write frame, and write word 5 bit 7 is report word 24 bit 7.
    assert (CANONICAL["cleaningTimeStatus"].word, CANONICAL["cleaningTimeStatus"].bit) == (24, 7)
    # nothing writable reaches word 25 -- that is where the readings start
    assert max(w.word for w in CANONICAL_WRITE.values()) == 5
    assert {"indoorTemperature", "indoorHumidity"} <= {
        n for n, c in CANONICAL.items() if c.word == 25
    }


def test_published_commands_match_the_ones_we_speak():
    """The commands the client sends are the ones the models publish."""
    from haismart_hrdp.canonical_map import OPERATION_ALTERNATES, OPERATIONS

    assert OPERATIONS["grSetDAC"].epp_cmd == "6001"
    assert OPERATIONS["getAllProperty"].epp_cmd == "4D01"
    assert OPERATIONS["getBigDataFrame"].epp_cmd == "4DFE"
    # The telemetry request is published two ways; the form real hardware accepts is frame type 1,
    # and the other is kept so a device that refuses it has somewhere to look.
    assert OPERATIONS["getBigDataFrame"].frame_type == 1
    assert OPERATION_ALTERNATES["getBigDataFrame"][0].frame_type == 0x60


def test_grsetdac_fields_match_their_confirmed_positions():
    """The encoder's field map, pinned to exact positions.

    Two categories: hardware-confirmed, and panel-authorised (the app renders a control for the
    attribute and the invariant frame positions it — offered per device by declaration, the way the
    app decides, not by a capture apiece). Positions are looked up in the published frame rather than
    transcribed, safe because the two agree. This freezes the values so a change in the map -- a
    regenerated file, a new model, a bad merge -- cannot quietly move the bit a live control writes.
    """
    assert uss.GRSETDAC_FIELDS == {
        # hardware-confirmed
        "targetTemperature": (1, 8, 8),
        "windDirectionVertical": (1, 0, 4),
        "operationMode": (2, 13, 3),
        "windSpeed": (2, 8, 3),
        "onOffStatus": (3, 0, 1),
        "healthMode": (3, 1, 1),
        "rapidMode": (3, 3, 1),
        "muteStatus": (3, 4, 1),
        "silentSleepStatus": (3, 5, 1),
        "screenDisplayStatus": (3, 9, 1),
        "windDirectionHorizontal": (4, 0, 3),
        "ecoMode": (4, 3, 3),
        "selfCleaningStatus": (5, 4, 1),  # start-only; live-confirmed (panel showed "CL")
        # panel-authorised (`haismart_hrdp.panel`) — the app renders these and the frame positions
        # them; offered per device by declaration, not by a capture apiece. Positions from the frame.
        "electricHeatingStatus": (3, 2, 1),
        "10degreeHeatingStatus": (3, 8, 1),
        "freshAirStatus": (5, 0, 1),
        "lightStatus": (5, 5, 1),
        "humanSensingStatus": (4, 6, 2),
        # panel controls positioned by the published ORDER, not the frame (PANEL_EXTRA_POSITIONS) —
        # each unanimous across the 83 products that declare it.
        "mouldProof": (5, 14, 1),
        "drying": (5, 13, 1),
        "preventHeatstroke": (5, 15, 1),
    }


def test_encoder_membership_is_not_widened_by_the_published_map():
    """The map describes more fields than the encoder writes, and widens ONLY by the panel.

    The encoder's membership is now hardware-confirmed ∪ panel-authorised — the second being what the
    app itself uses (the attribute is a panel control). It must NOT widen to every map field: an
    attribute in the frame but with no panel widget stays out. `echoStatus` is the standing example --
    in the write frame, model-writable, no panel widget, and silently discarded by real hardware; the
    app does not offer it and neither do we.
    """
    from haismart_hrdp.canonical_map import CANONICAL_WRITE
    from haismart_hrdp.panel import PANEL_CONTROLS

    assert len(CANONICAL_WRITE) > len(uss.GRSETDAC_FIELDS)
    # in the frame, but not a panel control -> not writable
    for withheld in ("echoStatus", "lockStatus", "targetHumidity"):
        assert withheld in CANONICAL_WRITE, "expected the map to describe it"
        assert withheld not in PANEL_CONTROLS, f"{withheld} is not a panel control"
        assert withheld not in uss.GRSETDAC_FIELDS, f"{withheld} must not be writable"
    # every panel control the frame positions IS writable (the widening, and exactly it)
    for name in PANEL_CONTROLS:
        if name in CANONICAL_WRITE:
            assert name in uss.GRSETDAC_FIELDS, f"{name} is a panel control the frame places"
    # selfCleaningStatus looked identical to echoStatus on paper (both published, both model-writable)
    # and was withheld the same way -- until a live write of it landed (the panel showed "CL") while
    # echoStatus's was silently discarded. So it, and only it, moved into the encoder.
    assert "selfCleaningStatus" in CANONICAL_WRITE
    assert "selfCleaningStatus" in uss.GRSETDAC_FIELDS
    # ecoMode is the one field the shared map cannot supply, so it stays stated locally
    assert "ecoMode" not in CANONICAL_WRITE
    assert uss.GRSETDAC_FIELDS["ecoMode"] == (4, 3, 3)


def test_device_type_class_reads_the_class_out_of_a_uplus_id():
    """A uPlusId carries the five-character product class its device belongs to."""
    from haismart_hrdp import device_type_class

    # split air conditioners -> 02012, cabinet air conditioners -> 03012
    assert device_type_class("2008610800820324021200118012560000" + "0" * 30) == "02012"
    assert device_type_class("2008610800820324031200118006114500" + "0" * 30) == "03012"
    # the three reference families all sit in one class yet report in three different wire
    # families -- which is exactly why this is an identifier and never a decoder choice
    classes = {
        device_type_class("200861080082032402120011801" + tail + "0" * 30)
        for tail in ("2560000", "7740000", "8900000")
    }
    assert classes == {"02012"}
    # absent or truncated input is not guessed at
    assert device_type_class(None) is None
    assert device_type_class("") is None
    assert device_type_class("2008610800820324") is None


# --- transport escaping, against independently published frames ---------------------------------
# 0xFF is the frame separator, so an 0xFF inside a frame travels as `FF 55`, and the checksum counts
# the inserted 0x55. Our own captures cannot reach that path: no frame this project has ever recorded
# carries an 0xFF body byte, so every checksum we have checked has a compensation term of zero. These
# four frames come from a separate implementation of the same framing, published as its own transport
# test suite, and two of them make the term load-bearing -- without it their checksums do not verify.
#
# They also use the framing's optional CRC (flag 0x40), which our units do not; that is deliberate.
# The escaping and checksum rules are what is being pinned, and those are shared.
_ESCAPED_FRAMES = {
    # every escapable position exercised at once: the frame type, the data, and the checksum itself
    "type_data_and_checksum": (
        "FF FF 0E 40 00 00 00 00 00 FF 55 FF 55 FF 55 05 FF 55 FF 55 08 FF 55 D0 8E", 5),
    # a 4D01 query carrying escapes in its data and in its checksum
    "query_with_escapes": (
        "FF FF 0D 40 00 00 00 00 00 01 4D 01 FF 55 BB FF 55 FF 55 D1 3C", 2),
    # an escape that falls inside the CRC, after the checksummed region ends
    "escape_inside_crc": (
        "FF FF 2A 40 00 00 00 00 00 02 6D 01 02 06 25 00 02 00 00 00 00 00 26 00 46 00 00 03 "
        "00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 78 FF 55 D2", 0),
    # the same report with no escapes anywhere -- the ordinary case
    "no_escapes": (
        "FF FF 2A 40 00 00 00 00 00 02 6D 01 02 06 25 00 02 00 00 00 00 00 27 00 44 00 00 03 "
        "00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 77 D1 7B", 0),
}


@pytest.mark.parametrize("name", sorted(_ESCAPED_FRAMES))
def test_escaping_and_checksum_match_an_independent_implementation(name):
    """Unescape, verify the checksum, and re-escape back to the exact bytes."""
    wire_hex, expected_escapes = _ESCAPED_FRAMES[name]
    wire = bytes.fromhex(wire_hex.replace(" ", ""))

    logical = uss.destuff_epp(wire)
    length = logical[2]
    body, sent_checksum = logical[2:2 + length], logical[2 + length]
    assert body.count(0xFF) == expected_escapes, "escaping did not resolve as expected"

    # the rule build_epp_frame uses, applied to somebody else's frames
    assert (sum(body) + 0x55 * body.count(0xFF)) & 0xFF == sent_checksum

    # and escaping is exactly invertible -- a re-encode reproduces the wire bytes
    assert uss.stuff_epp(logical) == wire


def test_checksum_compensation_is_load_bearing_not_decorative():
    """Two of those frames verify only when the inserted escape bytes are counted.

    Guards against the compensation term being 'simplified away' by someone who checks it against
    our own captures, where it is always zero and therefore always looks redundant.
    """
    needed = 0
    for wire_hex, _ in _ESCAPED_FRAMES.values():
        logical = uss.destuff_epp(bytes.fromhex(wire_hex.replace(" ", "")))
        length = logical[2]
        body, sent = logical[2:2 + length], logical[2 + length]
        if (sum(body) & 0xFF) != sent:
            needed += 1
            assert (sum(body) + 0x55 * body.count(0xFF)) & 0xFF == sent
    assert needed == 2


def test_a_refusal_is_told_apart_from_a_status_report():
    """The byte before the command word says whether the unit answered or declined.

    A refusal carries no command word we recognise, so every check that keys on the command word
    reads it as silence -- which is the wrong answer for a caller deciding whether to retry.
    """
    # a real status report: frame type 06 (report), command word 6d01
    assert uss.epp_frame_type(REAL_STATUS) == 0x06
    assert uss.reply_refused([REAL_STATUS]) is False

    # the same blob with the frame type changed to a refusal
    at = REAL_STATUS.find(uss.EPP_FRAME_HEAD)
    refusal = bytearray(REAL_STATUS)
    refusal[at + 9] = uss.EPP_FRAME_TYPE_REFUSED
    assert uss.epp_frame_type(bytes(refusal)) == uss.EPP_FRAME_TYPE_REFUSED
    assert uss.reply_refused([bytes(refusal)]) is True

    # a blob carrying no frame at all is neither -- absence is not refusal
    assert uss.epp_frame_type(b"\x00" * 40) is None
    assert uss.reply_refused([b"", b"\x00" * 40]) is False
    # and a truncated frame does not read past its end
    assert uss.epp_frame_type(uss.EPP_FRAME_HEAD + b"\x0a\x00") is None


def test_a_refusal_alongside_a_status_report_does_not_mask_it():
    """A unit that answers with its updated state has accepted the write, whatever else arrived."""
    at = REAL_STATUS.find(uss.EPP_FRAME_HEAD)
    refusal = bytearray(REAL_STATUS)
    refusal[at + 9] = uss.EPP_FRAME_TYPE_REFUSED
    # `reply_refused` reports what it sees; the caller consults it only when no status decoded,
    # which this pins by showing the status blob still parses on its own
    assert uss.parse_full_status(REAL_STATUS) is not None
    assert uss.reply_refused([REAL_STATUS, bytes(refusal)]) is True


def test_the_extended_query_has_two_published_forms() -> None:
    """The same command, sent under two frame types, because two generations publish it differently.

    Only the frame-type byte and the checksum differ -- the command itself is identical -- so a unit
    that answers neither really has no telemetry, while a unit asked only the first way may simply
    be of the generation that publishes the second.
    """
    first, second = (uss.extended_status_epp_frame(ft) for ft in uss.EXTENDED_STATUS_FRAME_TYPES)

    assert uss.EXTENDED_STATUS_FRAME_TYPES == (0x01, 0x60)
    assert first == bytes.fromhex("ffff0a000000000000014dfe56")
    assert second == bytes.fromhex("ffff0a000000000000604dfeb5")
    assert first[10:12] == second[10:12] == uss.EPP_CMD_EXTENDED_STATUS
    assert uss.epp_frame_type(first) == 0x01
    assert uss.epp_frame_type(second) == 0x60
    assert first[:9] == second[:9]              # everything before the frame type is the same


def test_the_default_form_is_the_one_our_hardware_answers() -> None:
    """Called with no argument it must still produce the frame the confirmed units reply to."""
    assert uss.extended_status_epp_frame() == uss.extended_status_epp_frame(0x01)


def test_frames_we_know_of_but_do_not_read_are_named() -> None:
    """A frame we recognise and ignore should not be logged as if nobody had ever seen it.

    The undecodable log exists to identify unfamiliar models. Three kinds are known and deliberately
    unread -- a refusal, an alarm-stop, and the changed-parameters report some models publish -- and
    naming them keeps that log about the frames that are actually a mystery.
    """
    assert "refusal" in uss.describe_epp_frame(uss.build_epp_frame(0x03, b"\x4d\x01"))
    assert "alarm-stop" in uss.describe_epp_frame(
        uss.build_epp_frame(uss.EPP_FRAME_TYPE_STOP_ALARM, b"\x00\x00")
    )
    assert "6c01" in uss.describe_epp_frame(
        uss.build_epp_frame(0x06, uss.EPP_CMD_CHANGED_PARAMS)
    )
    # an ordinary status report is not "recognised but unread" -- it is read
    assert uss.describe_epp_frame(uss.build_epp_frame(0x06, b"\x6d\x01")) is None
    assert uss.describe_epp_frame(b"not a frame at all") is None


def test_a_confirmed_field_is_bounded_only_by_physics() -> None:
    """A narrow band on a confirmed offset hides bugs; it does not prevent them.

    The band began doing two jobs: vetoing a candidate offset while a layout was being derived, and
    rejecting an absent sensor's zero. The first now lives in `wire_models`, where the question
    really is "does this offset look right". The second is the sentinels. What was left did neither
    and discarded a compressor discharge line at 80 C -- a correct reading from a unit pulling
    78 Hz -- for exceeding a range chosen for room air.

    The shape of that failure is the point: a masked decode looks exactly like absent hardware, so
    it gets ignored, whereas an implausible number gets reported and fixed.
    """
    from haismart_hrdp.uss import _PLAUSIBLE_TEMP_C, _sensor_temp

    # the live reading that used to vanish
    assert _sensor_temp(144, scale=1.0, offset=-64.0) == 80.0
    # ordinary air and coil readings are unaffected
    assert _sensor_temp(60, scale=0.5, offset=-20.0) == 10.0
    # the sentinels remain -- those are a real encoding, not a guess at what is reasonable
    for sentinel in (0x00, 0xFF):
        assert _sensor_temp(sentinel, scale=1.0, offset=-64.0) is None
    # and the bound is physical rather than comfortable
    assert _PLAUSIBLE_TEMP_C[1] >= 140.0


def test_the_209_byte_counter_is_in_watt_hours_by_its_own_two_readings():
    """Two readings of the same appliance five days apart settle the unit, on physical grounds.

    The register read 751,936 in the first report from this appliance and 777,385 in one taken five
    days later: 25,449 units. As watt-hours that is 5.1 kWh a day, which at the ~1.1 kW its owner
    measured at the breaker is about four and a half hours of running a day -- an ordinary duty cycle
    for an office. As hundredths of a kilowatt-hour it would be 51 kWh a day, which at the same
    power draw is **46 hours of running in every 24**, and there is no reading of the hardware that
    makes that possible.

    So this family's unit is established without waiting for anyone to read a figure off their app,
    and independently of the family where that measurement was made.
    """
    from haismart_hrdp.wire_models import select_wire_model

    later = 777385     # the same register, five days on
    earlier = select_wire_model(209, None).decode(STATUS_209_OFF)["energy_wh"]
    assert earlier == 751936
    hours_per_day_if_wh = (later - earlier) / 1000 / 5 / 1.1
    assert 2 < hours_per_day_if_wh < 12                      # an ordinary duty cycle
    assert hours_per_day_if_wh * 10 > 24                     # ...and ten times that is impossible


def test_a_handshake_that_cannot_be_read_is_not_reported_as_a_rejected_setting():
    """⚠️ The exception TYPE is the point, not the message.

    The layer above maps ``ValueError`` to "does not accept that setting" and ``RuntimeError`` to
    "could not send the command". An unreadable handshake reply used to raise the former, so an
    owner whose appliance never received the setting was told the appliance had refused it -- which
    sends them to check the setting, and sent us there too.
    """
    from haismart_hrdp.uss import (
        FLAG_BIZ_ENCRYPTED,
        Message,
        session_sequence_base,
    )

    good = Message(uss.INFO_HELLO_DONE_RESP, 0, 1, FLAG_BIZ_ENCRYPTED, 0, 0,
                   uss.biz_encrypt(0, (547).to_bytes(4, "big"), LOCALKEY))
    assert session_sequence_base(good, LOCALKEY) == 547

    # marked encrypted, and is not: what a wrong key or an unexpected reply looks like
    noise = Message(uss.INFO_HELLO_DONE_RESP, 0, 1, FLAG_BIZ_ENCRYPTED, 0, 0, bytes(64))
    with pytest.raises(RuntimeError, match="never sent"):
        session_sequence_base(noise, LOCALKEY)

    # a reply with nothing in it cannot carry a base either, and says so the same way
    empty = Message(uss.INFO_HELLO_DONE_RESP, 0, 1, FLAG_BIZ_ENCRYPTED, 0, 0, b"")
    with pytest.raises(RuntimeError, match="never sent"):
        session_sequence_base(empty, LOCALKEY)


def test_the_handshake_reply_is_decrypted_even_though_its_flag_says_otherwise():
    """⚠️ Real appliances send HELLO_DONE_RESP with flag=0 and an ENCRYPTED body. Do not "fix" this.

    Honouring the flag here -- which every other message on the connection does deserve -- takes
    four bytes of ciphertext as the session sequence number. The appliance then discards the command
    **silently**: no error, no reply, the setting never changes and nothing in the log says why.
    That shipped once and was caught on hardware within the hour.
    """
    from haismart_hrdp.uss import Message, session_sequence_base

    body = uss.biz_encrypt(0, (912).to_bytes(4, "big"), LOCALKEY)
    unflagged = Message(uss.INFO_HELLO_DONE_RESP, 0, 1, 0, 0, 0, body)
    assert session_sequence_base(unflagged, LOCALKEY) == 912


def test_a_rotated_key_is_named_before_anything_is_decrypted():
    """The appliance states its key version in the handshake; everything after is encrypted with it.

    Checking afterwards is too late: decrypting with an older key yields noise, and noise fails a
    structural length check, so a rotated key surfaced as "does not accept that setting: bad rawlen"
    on a command the appliance never received. `probe_localkey_version` has always documented the
    rule -- compare "BEFORE ever attempting to decrypt" -- and the op path read the number and
    dropped it.
    """
    import struct

    from haismart_hrdp.uss import LocalKeyRotated, Message, check_hello_resp

    reply = Message(uss.INFO_HELLO_RESP, 0xEA61, 1, 0, 1, 0x1234, struct.pack(">II", 1, 133))
    assert check_hello_resp(reply, 133).localkey_version == 133

    with pytest.raises(LocalKeyRotated) as caught:
        check_hello_resp(reply, 45)
    assert caught.value.device_version == 133 and caught.value.held_version == 45

    # ⚠️ It must stay a RuntimeError subclass. The layer above maps ValueError to "does not accept
    # that setting"; a key problem reported that way is what sent this whole investigation to the
    # wrong layer in the first place.
    assert isinstance(caught.value, RuntimeError)
    assert not isinstance(caught.value, ValueError)

    # No expectation supplied -> unchanged behaviour, so every existing caller is unaffected
    assert check_hello_resp(reply).localkey_version == 133
    # ...and an appliance that reports no version at all is not accused of rotating
    silent = Message(uss.INFO_HELLO_RESP, 0xEA61, 1, 0, 1, 0x1234, struct.pack(">II", 1, 0))
    assert check_hello_resp(silent, 45).localkey_version == 0


def test_the_status_refusal_still_outranks_the_version_check():
    """An appliance that declined the session is not a key problem, and says so first."""
    import struct

    from haismart_hrdp.uss import check_hello_resp

    refused = uss.Message(
        uss.INFO_HELLO_RESP, 0xEA61, 1, 0, 1, 0x1234, struct.pack(">II", 0, 133))
    with pytest.raises(RuntimeError, match="rejected the handshake"):
        check_hello_resp(refused, 45)


def test_the_session_speaks_the_version_the_appliance_answered_with():
    """Header byte 6 is the protocol version, and a mismatch is discarded SILENTLY by the appliance.

    Its reader compares the byte against the version it runs and drops the packet with no reply, so
    a session can handshake perfectly and then swallow every command -- the same failure shape as
    the flag bug, and just as invisible. Speak back what the appliance just said.
    """
    from haismart_hrdp.uss import (
        INFO_HELLO_RESP,
        TYPE_BYTE,
        decode_message,
        encode_message,
        negotiated_type_byte,
    )

    for answered in (TYPE_BYTE[2], TYPE_BYTE[3]):
        resp = decode_message(encode_message(INFO_HELLO_RESP, 1, b"\x00" * 8,
                                             type_byte=answered, session=0x4636))
        assert negotiated_type_byte(resp, requested=TYPE_BYTE[2]) == answered

    # a reply carrying no version is no answer at all -- keep the value known to work rather than
    # sending a zero no appliance has ever been observed to accept
    silent = decode_message(encode_message(INFO_HELLO_RESP, 1, b"\x00" * 8, type_byte=0))
    assert negotiated_type_byte(silent, requested=TYPE_BYTE[2]) == TYPE_BYTE[2]


def test_the_rawlen_bounds_are_the_manufacturers_own():
    """Our reader must not be stricter than the client the appliance is built to talk to.

    The vendor's decoder checks `0x28 < rawlen <= payload_len - 2` and `rawlen <= 0xE028`, bounding
    against the payload as it arrived. Ours bounded against the 16-byte-aligned slice, which is up
    to fifteen bytes shorter, and accepted `rawlen == 0x28` -- a frame carrying no data at all.
    """
    import hashlib
    import struct as _s

    from haismart_hrdp.uss import _cbc, biz_decrypt, localkey_aes_key

    key = "a" * 32

    def frame(rawlen: int, data: bytes = b"", pre4: bytes = b"1234") -> bytes:
        pt = (_s.pack(">HI", rawlen, 7) + hashlib.md5(pre4 + data).digest()
              + b"\x00" * 16 + pre4 + data)
        pt += b"\x00" * (-len(pt) % 16)
        return _cbc(localkey_aes_key(key), pt, decrypt=False) + b"12345"

    # an empty frame is refused rather than returning an empty payload that reads as a valid report
    with pytest.raises(ValueError, match="bad rawlen 40"):
        biz_decrypt(frame(0x28), key)

    # and the complaint states the figures, because a wrong key produces a random rawlen that is
    # otherwise indistinguishable from a framing fault
    with pytest.raises(ValueError, match=r"bad rawlen 60000 \(payload \d+ B, decrypted \d+ B\)"):
        biz_decrypt(frame(60000, b"\x01" * 8), key)

    # an ordinary frame still round-trips
    assert biz_decrypt(frame(0x28 + 8, b"\x01" * 8), key) == (7, b"\x01" * 8)
