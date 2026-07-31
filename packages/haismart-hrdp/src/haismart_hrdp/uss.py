"""uSS local transport (TCP :56800) — the on-LAN protocol these ACs speak for reads and control.

Layers
------
1. **uSS message**: a 16-byte header + payload::

     [0:4]   info_code BE32 = 0xEA60 + info_type   (hello=0, hello_resp=1, hello_done=2, done_resp=3)
     [4:6]   payload_len + 0x0a (BE16)
     [6]     type byte   (pro_ver 2 -> 0x01, pro_ver 3 -> 0x6E)
     [7]     flag        (0 plaintext / 1 encrypted biz-data)
     [8:12]  sn BE32     (client counter from 1; the AC echoes it)
     [12:14] code2 BE16  (0 for hello)
     [14:16] session BE16 (0 in the client hello; the AC ASSIGNS one in HELLO_RESP)

2. **Handshake** (plaintext): client HELLO → AC HELLO_RESP(+session) → client HELLO_DONE →
   AC HELLO_DONE_RESP. Then the AC push-notifies status as ``0xEAC4`` messages.

3. **biz-data payload**: AES-128-CBC, IV = 16 zero bytes, key = ``MD5(localKey-as-ascii-hex)``. The
   plaintext carries an ``sn`` and an MD5 integrity checksum (verified on decrypt).
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import socket
import struct
import time
from collections.abc import Callable, Collection
from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .wire_models import select_wire_model, vane_h_sweeping, vane_v_sweeping

_LOGGER = logging.getLogger(__name__)

USS_PORT = 56800
_ZERO_IV = b"\x00" * 16
# After a control op the AC replies with its updated status burst, then goes silent on the still-open
# socket. Once the burst has begun we linger only this long (seconds) for trailing frames before
# returning — so the caller can update state promptly instead of blocking for the full op timeout.
_COLLECT_IDLE = 0.6

# info_type -> info_code is (0xEA60 + info_type) for the handshake range.
INFO_HELLO = 0
INFO_HELLO_RESP = 1
INFO_HELLO_DONE = 2
INFO_HELLO_DONE_RESP = 3

TYPE_BYTE = {2: 0x01, 3: 0x6E}  # pro_ver -> header type byte


# --- key derivation -----------------------------------------------------------

def localkey_aes_key(local_key: str | bytes) -> bytes:
    """AES-128 key = MD5 of the localKey's 32-char hex string used as ASCII (keylen 0x20 in the lib)."""
    if isinstance(local_key, bytes):
        local_key = local_key.decode("ascii")
    return hashlib.md5(local_key.encode("ascii")).digest()


# --- uSS message codec --------------------------------------------------------

@dataclass(frozen=True)
class Message:
    info_type: int
    info_code: int
    type_byte: int
    flag: int
    sn: int
    session: int
    payload: bytes


def encode_message(info_type: int, sn: int, payload: bytes = b"", *,
                   type_byte: int = 0x01, flag: int = 0, session: int = 0) -> bytes:
    hdr = struct.pack(">IHBBIHH",
                      0xEA60 + info_type, len(payload) + 0x0A,
                      type_byte & 0xFF, flag & 0xFF, sn & 0xFFFFFFFF, 0, session & 0xFFFF)
    return hdr + payload


def decode_message(buf: bytes) -> Message:
    if len(buf) < 16:
        raise ValueError("short uSS message")
    info_code, length, type_byte, flag, sn, _code2, session = struct.unpack(">IHBBIHH", buf[:16])
    return Message(info_code - 0xEA60, info_code, type_byte, flag, sn, session,
                   buf[16:6 + length] if 6 + length <= len(buf) else buf[16:])


def split_messages(buf: bytes):
    """Yield complete uSS messages from a byte stream (the AC may batch several).

    A declared length below 0x0A cannot be a real frame (the header alone is 16 bytes, i.e. a
    ``6 + length`` total of 16). Rather than hand ``decode_message`` a truncated slice — which raises
    ``ValueError`` from inside a collect loop the caller does not guard, turning a corrupt packet into
    an unhandled traceback every poll — stop and log. A desynchronised stream cannot be resynced
    safely, and advancing by a bogus total risks looping forever on ``total == 0``.
    """
    off = 0
    while off + 6 <= len(buf):
        length = struct.unpack(">H", buf[off + 4:off + 6])[0]
        total = 6 + length
        if total < 16:
            _LOGGER.warning(
                "uSS stream desynchronised at offset %d: declared frame length %d is too short to be "
                "a message; discarding the rest of this read", off, length,
            )
            return
        if off + total > len(buf):
            break
        yield buf[off:off + total]
        off += total


def _message_complete(buf: bytes) -> bool:
    """True once ``buf`` holds at least one full uSS message (6-byte prefix + declared length)."""
    return len(buf) >= 6 and len(buf) >= 6 + struct.unpack(">H", buf[4:6])[0]


def _recv_message(sock) -> Message:
    """Read exactly one complete uSS message, tolerating TCP fragmentation of the reply."""
    buf = b""
    while not _message_complete(buf):
        chunk = sock.recv(4096)
        if not chunk:
            raise RuntimeError("connection closed before a complete reply")
        buf += chunk
    return decode_message(buf)


# --- handshake messages -------------------------------------------------------

def hello_message(device_id: str, sn: int = 1, pro_ver: int = 2,
                  arg8: int = 0, arg7: int = 0) -> bytes:
    if pro_ver not in TYPE_BYTE:
        raise ValueError(f"pro_ver must be 2 or 3, got {pro_ver}")
    dev = device_id.encode("ascii").ljust(32, b"\x00")[:32]
    payload = dev if pro_ver == 2 else dev + struct.pack(">II", arg8, arg7)
    return encode_message(INFO_HELLO, sn, payload, type_byte=TYPE_BYTE[pro_ver])


def hello_done_message(sn: int, session: int, pro_ver: int = 2) -> bytes:
    return encode_message(INFO_HELLO_DONE, sn, b"", type_byte=TYPE_BYTE[pro_ver], session=session)


@dataclass(frozen=True)
class HelloResp:
    session: int
    sn: int
    status: int             # 1 = ok
    localkey_version: int   # the AC's CURRENT localKey version (payload[4:8])


def check_hello_resp(msg: Message) -> HelloResp:
    """Validate a HELLO_RESP and return it, raising if the AC refused the session.

    ``status != 1`` means the AC answered but declined — the session is dead. Every call site used to
    check only ``info_type``, so a refusal sailed through ``hello_done``, produced no status push, and
    surfaced as the same "no decodable status" a stale key or a dead network gives. On the write path
    it was worse: an op was sent into a session the AC had already refused.
    """
    if msg.info_type != INFO_HELLO_RESP:
        raise RuntimeError(f"unexpected reply {msg.info_code:#x}")
    resp = parse_hello_resp(msg)
    if resp.status != 1:
        raise RuntimeError(
            f"AC rejected the handshake (status={resp.status}) - check the deviceId is this unit's "
            f"Wi-Fi MAC"
        )
    return resp


def parse_hello_resp(msg: Message) -> HelloResp:
    """HELLO_RESP payload is ``status(BE32) || localkey_version(BE32)`` (e.g. ``00000001 00000004``)."""
    status, ver = (struct.unpack(">II", msg.payload[:8]) if len(msg.payload) >= 8 else (0, 0))
    return HelloResp(msg.session, msg.sn, status, ver)


def probe_localkey_version(ip: str, device_id: str, *, pro_ver: int = 2, timeout: float = 4.0) -> int:
    """Handshake-only (NO localKey required): return the AC's current localKey version.

    The localKey rotates server-side and a stale cached key is otherwise SILENT (the handshake still
    succeeds; only biz-data decryption fails the MD5 check). Compare this against the cached key's
    version to know when to re-pull — before ever attempting to decrypt.
    """
    s = socket.create_connection((ip, USS_PORT), timeout=timeout)
    try:
        s.sendall(hello_message(device_id, sn=1, pro_ver=pro_ver))
        msg = _recv_message(s)
    finally:
        s.close()
    return check_hello_resp(msg).localkey_version


# --- biz-data payload crypto --------------------------------------------------

def _cbc(key: bytes, data: bytes, *, decrypt: bool) -> bytes:
    op = Cipher(algorithms.AES(key), modes.CBC(_ZERO_IV))
    op = op.decryptor() if decrypt else op.encryptor()
    return op.update(data) + op.finalize()


def biz_decrypt(ciphertext: bytes, local_key: str) -> tuple[int, bytes]:
    """Decrypt an encrypted biz-data payload -> (sn, data). Raises if the MD5 check fails.

    The ciphertext is the message payload truncated to a 16-byte multiple; a wrong localKey (or a
    stale key version) fails the MD5 check on every block — that is the signal to re-pull the key.
    """
    n = (len(ciphertext) // 16) * 16
    if n < 48:
        raise ValueError("biz ciphertext too short")
    pt = _cbc(localkey_aes_key(local_key), ciphertext[:n], decrypt=True)
    rawlen = struct.unpack(">H", pt[0:2])[0]
    sn = struct.unpack(">I", pt[2:6])[0]
    datalen = rawlen - 0x28
    if datalen < 0 or 0x2A + datalen > len(pt):
        raise ValueError("bad rawlen")
    if hashlib.md5(pt[0x26:0x26 + datalen + 4]).digest() != pt[6:22]:
        raise ValueError("biz integrity (MD5) check failed — wrong/stale localKey?")
    # Unescape here, not at each call site: every caller wants canonical fixed-length blobs, and a
    # single missed site reappears as a rare, state-dependent decode failure. See `destuff_epp`.
    return sn, destuff_epp(pt[0x2A:0x2A + datalen])


def biz_encrypt(sn: int, data: bytes, local_key: str, *,
                fields22: bytes = b"\x00" * 16, pre4: bytes | None = None) -> bytes:
    """Inverse of :func:`biz_decrypt`, matching the AC's framing: AES-CBC(plaintext)
    followed by a **5-digit ASCII transport nonce trailer**. The plaintext's ``pt[38:42]`` field is the
    trailer's first 4 digits (``pre4``); the full 5-digit nonce is appended after the ciphertext. Both
    directions carry this trailer on real frames — and the AC **rejects an outbound op without it**
    (:func:`biz_decrypt` ignores it by truncating to a 16-byte multiple, so reads never needed it).

    ``pre4``: pass a 5-byte nonce for the exact frame, or a 4-byte value to
    fix the plaintext digits while the trailer's 5th digit is random. ``fields22`` is ``pt[22:38]``."""
    if pre4 is None:
        nonce5 = f"{random.randint(10000, 99999)}".encode("ascii")
    elif len(pre4) >= 5:
        nonce5 = pre4[:5]
    else:
        nonce5 = pre4 + f"{random.randint(0, 9)}".encode("ascii")
    pre4b = nonce5[:4]
    rawlen = 0x28 + len(data)
    pt = (struct.pack(">HI", rawlen, sn) + hashlib.md5(pre4b + data).digest()
          + fields22 + pre4b + data)
    if len(pt) % 16:
        pt += b"\x00" * (16 - len(pt) % 16)
    return _cbc(localkey_aes_key(local_key), pt, decrypt=False) + nonce5


# --- write/op path builders ---
# The outbound control op: the FF FF frame + checksum, the grSetDAC field map
# (build_epp_frame / set_grsetdac_field),
# the CAE request envelope (build_cae_op_request, type 0x2714), the biz crypto (incl. the 5-digit trailer),
# the uSS framing, and the send flow (async_send_op). ``build_cae_op_envelope`` / ``build_op_message``
# below build the report-style envelope, used for the report round-trip.

FLAG_BIZ_ENCRYPTED = 1  # header[7] for an encrypted biz-data message (op / push)

EPP_FRAME_HEAD = b"\xff\xff"

# --- transport byte stuffing -------------------------------------------------
# 0xFF is the frame separator, so any 0xFF *inside* a frame is escaped on the wire as `FF 55`. The
# two leading separators are the delimiter itself and are never escaped; escaping starts after them.
#
# This is not theoretical. A report whose checksum happens to be 0xFF arrives one byte longer than
# its family's fixed length (128 instead of 127 on the classic family), so a small fraction of
# otherwise ordinary reports are escaped. Every length-keyed lookup then misses, and because the write path gates on the blob length
# (`status_layout`), control fails with "control is unavailable for this model" while reads carry on
# working. Worse, an 0xFF in the *payload* would shift every following offset.
#
# So unescape once, as close to decryption as possible, and let everything downstream see canonical
# fixed-length blobs.
_SEPARATOR_BYTE = 0xFF
_SEPARATOR_POST_BYTE = 0x55


def destuff_epp(blob: bytes) -> bytes:
    """Undo `FF 55` -> `FF` escaping inside the EPP frame of a decrypted blob.

    Returns ``blob`` unchanged when it carries no frame or no escapes, so this is safe to apply
    unconditionally. `FF 55` is unambiguous: a real 0xFF is always escaped, so the pair can only ever
    mean "one escaped 0xFF".
    """
    at = blob.find(EPP_FRAME_HEAD)
    if at < 0:
        return blob
    body = blob[at + 2:]
    if bytes([_SEPARATOR_BYTE, _SEPARATOR_POST_BYTE]) not in body:
        return blob
    out = bytearray()
    i = 0
    while i < len(body):
        byte = body[i]
        out.append(byte)
        i += 1
        if byte == _SEPARATOR_BYTE and i < len(body) and body[i] == _SEPARATOR_POST_BYTE:
            i += 1  # drop the escape byte
    return blob[:at + 2] + bytes(out)


def stuff_epp(frame: bytes) -> bytes:
    """Apply `FF` -> `FF 55` escaping to an EPP frame for transmission.

    The inverse of :func:`destuff_epp`, over a bare frame (leading separators preserved). Outbound
    frames we build today never contain an 0xFF body byte, but a group-set word block is seeded from
    live device state, so one can appear — `energySavePeriod` and `targetHumidity` are both full-range
    bytes.
    """
    if not frame.startswith(EPP_FRAME_HEAD):
        return frame
    out = bytearray(EPP_FRAME_HEAD)
    for byte in frame[2:]:
        out.append(byte)
        if byte == _SEPARATOR_BYTE:
            out.append(_SEPARATOR_POST_BYTE)
    return bytes(out)
# EPP control commands (frameType=1 for all):
EPP_CMD_GETALLPROPERTY = b"\x4d\x01"  # read-only status query — the SAFE probe (changes nothing)
EPP_CMD_GRSETDAC = b"\x60\x01"        # group set (words 1-5)
# Read-only query for the unit's EXTENDED status. Units that support it answer with an additional
# report (see `parse_extended_status`) carrying the running power/current/compressor figures on top of
# the ordinary status; units that don't simply refuse this one frame and still send normal status, so
# asking is safe either way.
EPP_CMD_EXTENDED_STATUS = b"\x4d\xfe"
# Report kinds the unit sends back, identified by the command word inside the returned frame. A single
# session can carry all three, so `parse_full_status` uses these to tell them apart.
_EPP_RPT_STATUS = b"\x6d\x01"    # the ordinary full-status report
_EPP_RPT_ALARM = b"\x0f\x5a"     # fault bitmap
_EPP_RPT_EXTENDED = b"\x7d\x01"  # extended status (running power / compressor figures)


def build_epp_frame(frame_type: int, epp_cmd: bytes, data: bytes = b"") -> bytes:
    """Build a positional OLD-EPP ``FF FF`` frame. The checksum rule reproduces the real report
    checksums (0xAE/0xF9).

    Layout ``FF FF | len | 00*6 | frameType | eppCmd(2) | data | checksum`` where ``len`` counts the
    bytes after it (the 00*6, frameType, eppCmd, data and the checksum) and
    ``checksum = (len + all those payload bytes excluding the checksum) & 0xFF``.
    """
    if len(epp_cmd) != 2:
        raise ValueError("epp_cmd must be exactly 2 bytes")
    payload = b"\x00" * 6 + bytes([frame_type & 0xFF]) + epp_cmd + data
    length = len(payload) + 1  # +1 accounts for the trailing checksum byte
    body = bytes([length]) + payload
    # Escaped bytes count toward the checksum: each 0xFF travels as `FF 55`, and the 0x55 is summed
    # too. No frame we have ever sent contains an 0xFF body byte, so this term is 0 today and cannot
    # change any currently-working frame — but a group-set is seeded from live device state, where a
    # full-range byte (`energySavePeriod`, `targetHumidity`) could produce one.
    checksum = (sum(body) + _SEPARATOR_POST_BYTE * body.count(_SEPARATOR_BYTE)) & 0xFF
    return EPP_FRAME_HEAD + body + bytes([checksum])


def getallproperty_epp_frame() -> bytes:
    """The read-only getAllProperty query frame ``ff ff 0a 00*6 01 4d 01 59`` — a status request that
    changes nothing. This is the frame the safe first probe sends."""
    return build_epp_frame(0x01, EPP_CMD_GETALLPROPERTY)


def extended_status_epp_frame() -> bytes:
    """The read-only extended-status query ``ff ff 0a 00*6 01 4d fe 56``.

    Also changes nothing. Units that support it answer with an extra report carrying the live
    power/current/compressor figures (:func:`parse_extended_status`) *in addition to* the ordinary
    status report, so one request returns both. Units that don't support it answer this frame with a
    short refusal and still send normal status — hence it is safe to ask unconditionally.
    """
    return build_epp_frame(0x01, EPP_CMD_EXTENDED_STATUS)


# CONFIRMED inbound report-envelope prefix: bytes [0:78] of the decrypted status blob, byte-identical
# across both physical ACs. [0:13] = CAE container header, [13:78] = STD-attr region (03 02 00 00 04 01
# then 59 zeros — all-zero on this sensor-less unit). The read path decodes the full blob by offset.
CAE_REPORT_PREFIX = bytes.fromhex("00002715000000004e56010000030200000401" + "00" * 59)
CAE_CONTAINER_HEADER = CAE_REPORT_PREFIX[:13]  # the 13-byte header alone (STD-region-dropped variant)


def build_cae_op_envelope(epp_frame: bytes, *, prefix: bytes = CAE_REPORT_PREFIX) -> bytes:
    """Reconstruct the INBOUND report CAE envelope: ``prefix | frameLen(BE16) | epp_frame``.

    With ``prefix=CAE_REPORT_PREFIX`` this reproduces a status blob when fed the report frame. For the
    OUTBOUND op envelope (a different layout: type 0x2714, embeds the deviceId, BE32 frameLen) use
    :func:`build_cae_op_request` instead.
    """
    return prefix + struct.pack(">H", len(epp_frame)) + epp_frame


def build_op_message(sn: int, epp_frame: bytes, local_key: str, session: int, *,
                     info_type: int, prefix: bytes = CAE_REPORT_PREFIX,
                     pro_ver: int = 2) -> bytes:
    """Build a biz-encrypted op message using the report-style envelope. For a real write use
    :func:`build_op_request_message` (the outbound op layout the AC expects).
    """
    envelope = build_cae_op_envelope(epp_frame, prefix=prefix)
    ciphertext = biz_encrypt(sn, envelope, local_key)
    return encode_message(info_type, sn, ciphertext, type_byte=TYPE_BYTE[pro_ver],
                          flag=FLAG_BIZ_ENCRYPTED, session=session)


# --- outbound op (write path) ---
# The C2S control op rides the SAME uSS message envelope as an inbound report (info_type 0x64 -> code
# 0xEAC4, flag=1, biz-encrypted with the device localKey). But the CAE envelope INSIDE differs from a
# report: type 0x2714 (reports are 0x2715), it carries the deviceId, and length-prefixes the EPP frame
# with a BE32 (not the report's BE16).
CAE_OP_TYPE_REQUEST = 0x2714   # outbound op (C2S); inbound reports are 0x2715


def build_cae_op_request(epp_frame: bytes, device_id: str, counter: int) -> bytes:
    """Wrap an EPP frame in the outbound CAE op envelope (C2S control request).

    Layout::

        00 00 27 14 | 36 zero bytes | deviceId ASCII right-padded to 32 bytes
                    | counter(BE32) | len(epp_frame)(BE32) | epp_frame

    ``counter`` is the app's per-op sequence (observed 1, 3, 5 — the app steps it by 2 per session).

    The frame is escaped on the way out (:func:`stuff_epp`) and the declared length is the escaped
    length, matching how the device sends its own frames. This is a no-op for every frame we have
    ever built — none contains an 0xFF body byte — so it cannot alter a currently-working op.
    """
    did = device_id.encode("ascii")
    if len(did) > 32:
        raise ValueError("device_id too long for the 32-byte field")
    field = did + b"\x00" * (32 - len(did))
    wire = stuff_epp(epp_frame)
    return (struct.pack(">I", CAE_OP_TYPE_REQUEST) + b"\x00" * 36 + field
            + struct.pack(">II", counter, len(wire)) + wire)


def build_op_request_message(sn: int, epp_frame: bytes, local_key: str, session: int,
                             device_id: str, counter: int, *, info_type: int = 0x64,
                             pro_ver: int = 2, pre4: bytes | None = None) -> bytes:
    """Assemble a full CONFIRMED outbound uSS control op: CAE request -> biz_encrypt -> uSS message.

    Produces the op — the CAE envelope, EPP frame and checksum match the wire
    bytes exactly; only the biz-layer ``pre4`` nonce is random (pass it to reproduce a recorded op).
    Building is always safe; SENDING a crafted frame to a real AC is a gated, approval-only action.
    """
    envelope = build_cae_op_request(epp_frame, device_id, counter)
    ciphertext = biz_encrypt(sn, envelope, local_key, pre4=pre4)
    return encode_message(info_type, sn, ciphertext, type_byte=TYPE_BYTE[pro_ver],
                          flag=FLAG_BIZ_ENCRYPTED, session=session)


# --- grSetDAC field map (group-set word packing) --------------------------------------------------
# Bit positions come from the device's EPP model. word0 is the
# eppCmd word; word N (1-based) = grSetDAC data bytes[2*(N-1) : +2], 16-bit big-endian, bit0 = LSB.
# Each entry is (word_index, bit_shift, bit_width). The `targetTemperature` value is absolute
# (epp = degC - 16).
GRSETDAC_FIELDS = {
    # Every field maps 1:1 to the app's own control list.
    # word index is 1-based; each value is (word, bit_shift, bit_width). App label noted.
    "targetTemperature": (1, 8, 8),    # epp = degC - 16 ; range 16..30
    "operationMode":     (2, 13, 3),   # 0=auto/comfort 1=cool 2=dry 6=fanOnly
    "windSpeed":         (2, 8, 3),    # 1=high 2=med 3=low 5=auto
    "onOffStatus":       (3, 0, 1),    # power 0=off 1=on
    "healthMode":          (3, 1, 1),  # app: "health"
    "rapidMode":           (3, 3, 1),  # app: "strong"
    "muteStatus":          (3, 4, 1),  # app: "quiet"
    "silentSleepStatus":   (3, 5, 1),  # app: "sleep"
    "screenDisplayStatus": (3, 9, 1),  # app: "lamp" (the unit's front light/display)
    "windDirectionVertical": (1, 0, 4),  # app: "up and down" — a TOGGLE on this unit: 0=off, 0x0c=on
    "windDirectionHorizontal": (4, 0, 3),  # app: "left and right" — 0=fixed, 7=auto
    # ^ confirmed by a single-attribute app sweep: toggling ONLY left-right swing moved word4 bits
    #   0-2 between 7 and 0 and nothing else — ecoMode (same word, bits 3-5) stayed 0 and the
    #   vertical nibble stayed put. Unlike windDirectionVertical the raw EPP value equals the STD
    #   code the digital model lists (0 = 左右摆位置一(固定), 7 = 左右摆位置八(自动)).
    "ecoMode":               (4, 3, 3),  # app: "eco" — device-specific MULTI-LEVEL: 0=off, 5/6/7 = 3 levels
    # ^ ecoMode is NOT the digital model's energySavingStatus bool (word5 b6, which never moves here); this
    #   unit repurposes word4 b3-5 into a 3-bit eco level. Confirmed by an eco-only sweep (values 0/5/6/7).
}

# Allowed raw EPP values per field — the encoder REFUSES anything else, so we never fire a code the app
# was not observed to send (temperature is range-checked instead). Bools accept {0,1} implicitly.
# Values our own units don't have (e.g. heat, absent on a cooling-only AC) can additionally be
# authorized per device by that device's own digital model — see :data:`GRSETDAC_MODEL_AUTHORIZED`.
GRSETDAC_ALLOWED_VALUES = {
    "operationMode": {0, 1, 2, 4, 6},   # 4 = heat; see GRSETDAC_ENUMS
    "windSpeed":     {1, 2, 3, 5},
    "windDirectionVertical": {0x00, 0x0c},   # off / on (the app's exact on-nibble)
    "windDirectionHorizontal": {0x00, 0x07}, # fixed / auto (the model's only two codes)
    "ecoMode":               {0, 5, 6, 7},   # off / three levels (5/6/7)
}

# Fields whose value space the DEVICE'S OWN digital model may extend beyond the observed set above
# (pass the model's codes as ``model_values``). Both are plain STD enums that the model describes
# attribute-for-attribute (``valueRange`` LIST) and whose STD code IS the raw EPP value — the wire
# model maps stdValue -> eppValue 1:1 for them — so a mode a heat-pump unit has and ours doesn't is
# taken from that unit's model rather than guessed. The device-specific fields are deliberately NOT
# here: no model attribute describes ``windDirectionVertical``'s 0x0c toggle or this unit's
# repurposed 3-bit ``ecoMode``, so those stay pinned to the observed values alone.
GRSETDAC_MODEL_AUTHORIZED = frozenset({"operationMode", "windSpeed"})

GRSETDAC_ENUMS = {  # semantic token -> raw EPP value, for the multi-value fields
    # operationMode 4 = heat. Absent originally because the reference unit (AAC1UKZ01 /
    # HSU-24VRRA03TF) is cooling-only, so a heat-capable model advertised HVACMode.HEAT from its
    # digital model and then raised on the write. The code matches the app's own mode table
    # (0 smart / 1 cool / 2 dry / 4 heat / 6 fan) and is now HARDWARE-CONFIRMED on a heat-capable
    # unit (AACRL2E00, @darkdiamond): the AC echoed operationMode=4, a fresh read agreed, the revert
    # was clean and no other attribute drifted — hence it sits in the allowlist above. Codes we have
    # NO such evidence for still need the device's own model to authorise them (``model_values``).
    "operationMode": {"auto": 0, "cool": 1, "dry": 2, "heat": 4, "fan_only": 6},
    "windSpeed":     {"high": 1, "medium": 2, "low": 3, "auto": 5},
    "windDirectionVertical": {"off": 0x00, "on": 0x0c},
    "windDirectionHorizontal": {"off": 0x00, "on": 0x07},
    # confirmed on this family: a higher level caps the compressor current harder
    "ecoMode":               {"off": 0, "level1": 5, "level2": 6, "level3": 7},
}


def set_grsetdac_field(
    words: bytes, name: str, epp_value: int, *, model_values: Collection[int] | None = None
) -> bytes:
    """Return the grSetDAC data-word bytes ``words`` with packed field ``name`` set to ``epp_value``
    (the raw EPP value — e.g. targetTemperature is degC-16). Only CONFIRMED, fire-safe fields in
    :data:`GRSETDAC_FIELDS` are accepted, and only observed-valid values (:data:`GRSETDAC_ALLOWED_VALUES`
    / the 16..30 temp range / 0..1 for bools) — anything else raises (per "don't fire what you can't map").
    The op is a group-set, so ``words`` should be a real current-state baseline (from a read) so every
    other packed attribute is preserved — this flips just the one field.

    ``model_values``: the raw codes this specific device's digital model declares for ``name``
    (``valueRange`` LIST). For the fields in :data:`GRSETDAC_MODEL_AUTHORIZED` they widen the
    allowlist, so a capability our own units lack — heat mode being the case in point — is authorized
    by the device's own published model instead of a guessed constant. Ignored for every other field.
    """
    if name not in GRSETDAC_FIELDS:
        raise KeyError(f"{name!r} is not a confirmed grSetDAC field — refusing to encode (unmapped)")
    wi, shift, width = GRSETDAC_FIELDS[name]
    if not 0 <= epp_value < (1 << width):
        # would silently truncate into the neighbouring attributes' bits
        raise ValueError(f"{name}={epp_value} does not fit its {width}-bit field")
    allowed = GRSETDAC_ALLOWED_VALUES.get(name)
    if allowed is not None:
        if model_values and name in GRSETDAC_MODEL_AUTHORIZED:
            allowed = set(allowed) | {int(v) for v in model_values}
        if epp_value not in allowed:
            raise ValueError(
                f"{name}={epp_value} is neither an observed-valid value {sorted(allowed)} "
                "nor declared by the device's digital model"
            )
    elif name == "targetTemperature":
        if not 0 <= epp_value <= 14:               # 16..30 degC
            raise ValueError("targetTemperature epp must be 0..14 (16..30 degC)")
    elif width == 1 and epp_value not in (0, 1):
        raise ValueError(f"{name} is a bool — value must be 0 or 1")
    off = (wi - 1) * 2
    if off + 1 >= len(words):
        raise ValueError("words too short for this field")
    b = bytearray(words)
    word = (b[off] << 8) | b[off + 1]
    mask = ((1 << width) - 1) << shift
    word = (word & ~mask) | ((epp_value << shift) & mask)
    b[off], b[off + 1] = (word >> 8) & 0xFF, word & 0xFF
    return bytes(b)


# --- structural status (EPP container) parse ----------------------------------

@dataclass(frozen=True)
class StatusContainer:
    """Structural split of a decrypted status blob into its container header + raw attribute region.

    The core climate fields inside the attribute region are decoded by :func:`parse_full_status` (see
    its confirmed offsets); the remaining packed attributes map via the device digital model / the
    per-model ``AttributeProfile``. (Note: the open-source haier-esphome/smartair2 stack is a *different*
    protocol — ``FF FF`` UART — and does NOT decode this uSDK-EPP payload.)"""

    header: bytes          # the fixed 13-byte container header
    attr_region: bytes     # everything after the header (the packed STD attribute bytes)
    raw: bytes


def parse_status_container(data: bytes) -> StatusContainer:
    """Split a decrypted status blob into its container header + attribute region.

    Observed header (typeId AAC1UKZ01): ``0000 2715 00000000 4e56 01 0003 02 0004 01`` (13 bytes),
    then the packed attribute payload (see :func:`parse_full_status` for the decoded fields).
    """
    hdr_len = 13 if len(data) >= 13 else len(data)
    return StatusContainer(header=data[:hdr_len], attr_region=data[hdr_len:], raw=data)


# Confirmed byte offsets in the "full status" report, validated on real units against the uSDK's
# getAttributeMap + a single-variable app sweep.
#
# The CAE envelope (78-byte prefix + BE16 inner-frame length) and the EPP frame header are identical
# across models, so the packed attribute vector always starts at byte 92 — immediately after the
# ``6d 01`` getAllProperty response code. What DOES vary by model is how many grSetDAC control words
# the report carries before the read-only sensor block, which shifts every sensor offset after it.
# Each known report length therefore gets a :class:`StatusLayout`; an unrecognised length decodes to
# ``{}`` rather than silently misreading a neighbouring attribute.
_FULL_STATUS_LEN = 127   # AAC1UKZ01 report length — the historical default
_OFF_ATTRS = 92          # first packed attribute byte; identical on every known variant
_OFF_TARGET_TEMP = 92    # targetTemperature = byte + 16
_OFF_SWING_V = 93        # vertical vane: a 4-bit POSITION CODE, not a bitmask (see `vane_v_sweeping`)
_OFF_MODE_FAN = 94       # (operationMode << 5) | windSpeed  — both STD codes packed in one byte
_OFF_ONOFF = 97          # onOffStatus lives in bit 0 of this byte ONLY — see _ONOFF_MASK
# This byte carries EIGHT packed flags, not just the on/off bit: bit0 onOffStatus, bit1 health,
# bit2 electric-heat, bit3 boost, bit4 quiet, bit5 sleep, bit6 child-lock, bit7 buzzer. Masking is
# required — reading the whole byte reports the unit as ON whenever any of those toggles is set, and
# this integration's own switches write four of them.
_ONOFF_MASK = 0x01
_OFF_INDOOR_TEMP = 104   # indoorTemperature = byte / 2  (the /2 == the model's 0.5° step)
_OFF_OUTDOOR_TEMP = 106  # outdoorTemperature = byte - 64  (correlated across 3 states, 2 distinct pts)


@dataclass(frozen=True)
class StatusLayout:
    """The model-dependent part of a full-status report layout, keyed by report length.

    ``words`` is how many grSetDAC control words (2 bytes each, from :data:`_OFF_ATTRS`) the report
    carries — i.e. the size of the baseline a control op seeds from. The read-only sensor bytes follow
    that block, so their offsets move with it.
    """

    words: int          # grSetDAC data words 1..N present in the report
    indoor_temp: int    # byte offset of indoorTemperature (value = byte / 2)
    outdoor_temp: int   # byte offset of outdoorTemperature (value = byte - 64)
    verified: bool = True   # False when DERIVED from the length rather than a confirmed table entry

    @property
    def baseline(self) -> slice:
        """The report slice holding grSetDAC data words 1..``words``."""
        return slice(_OFF_ATTRS, _OFF_ATTRS + 2 * self.words)

    @classmethod
    def for_words(cls, words: int, *, verified: bool) -> StatusLayout:
        """Build a layout from the control-word count alone.

        Both confirmed models satisfy ``indoor = _OFF_ATTRS + 2*words`` and ``outdoor = indoor + 2``
        (127 B -> 6 words -> 104/106; 125 B -> 5 words -> 102/104), i.e. the sensor block begins
        immediately after the word block.
        """
        indoor = _OFF_ATTRS + 2 * words
        return cls(words=words, indoor_temp=indoor, outdoor_temp=indoor + 2, verified=verified)


STATUS_LAYOUTS: dict[int, StatusLayout] = {
    # typeId AAC1UKZ01 (HSU-24VRRA03TF): 6 control words, sensor block from byte 104.
    127: StatusLayout(words=6, indoor_temp=_OFF_INDOOR_TEMP, outdoor_temp=_OFF_OUTDOOR_TEMP),
    # deviceType 0201201d: the report carries 2 attribute bytes fewer — 5 control words — so every
    # sensor offset after the word block shifts by -2. Verified on a live unit: every decoded field
    # agreed with the cloud digital-model shadow read in the same second (targetTemperature,
    # operationMode, windSpeed, onOffStatus, indoorTemperature, screenDisplayStatus,
    # windDirectionVertical), and a grSetDAC op built from the 5-word baseline was ACCEPTED — the AC
    # echoed the new targetTemperature on the op's own connection and preserved every other attribute.
    125: StatusLayout(words=5, indoor_temp=102, outdoor_temp=104),
}


# Bytes that follow the control-word block: the read-only sensor region plus the EPP checksum. This
# is 23 on BOTH confirmed models (127 = 92 + 2*6 + 23, 125 = 92 + 2*5 + 23), which is what makes the
# word count derivable from the report length alone.
_SENSOR_TAIL_LEN = 23
_LAYOUT_BASE_LEN = _OFF_ATTRS + _SENSOR_TAIL_LEN   # 115; report length = base + 2*words
_MAX_WORDS = 12   # sanity bound: no observed grSetDAC block exceeds this

# Plausibility band used to veto a DERIVED layout and to reject sentinel sensor readings. A unit that
# lacks a sensor reports 0 for it, which would otherwise decode to a confident -64.0 C outdoor value.
_PLAUSIBLE_TEMP_C = (-40.0, 70.0)


def status_layout(data: bytes) -> StatusLayout | None:
    """The CONFIRMED :class:`StatusLayout` for a blob, or ``None`` if its length isn't in the table.

    Table-only on purpose. This is the gate the **write** path uses (via
    :func:`grsetdac_baseline_from_status`), where a wrong word count would send a sensor byte back to
    the AC as a control word. For reads, prefer :func:`derive_status_layout`.
    """
    if len(data) < 4 or data[2:4] != b"\x27\x15":
        return None
    return STATUS_LAYOUTS.get(len(data))


def derive_status_layout(data: bytes, digital_model: dict | None = None) -> StatusLayout | None:
    """A layout for reading ``data``: the confirmed table entry, else one derived from its length.

    Returns ``None`` only when the blob isn't a status report at all or the derivation is not
    credible. A derived layout carries ``verified=False`` and is deliberately **not** accepted by the
    write path.

    Derivation is the closed form implied by :data:`_SENSOR_TAIL_LEN`, vetoed by a plausibility check
    on the byte it would call ``indoorTemperature`` — using the device's own model bounds when a
    ``digital_model`` is supplied. The veto can only reject; it never picks between candidates.
    """
    if len(data) < 4 or data[2:4] != b"\x27\x15":
        return None
    known = STATUS_LAYOUTS.get(len(data))
    if known is not None:
        return known
    span = len(data) - _LAYOUT_BASE_LEN
    if span <= 0 or span % 2:
        return None
    words = span // 2
    if not 1 <= words <= _MAX_WORDS:
        return None
    layout = StatusLayout.for_words(words, verified=False)
    if layout.outdoor_temp >= len(data):
        return None
    lo, hi = _indoor_bounds(digital_model)
    raw = data[layout.indoor_temp]
    if raw in (0x00, 0xFF) or not lo <= raw / 2.0 <= hi:
        return None
    return layout


def _indoor_bounds(digital_model: dict | None) -> tuple[float, float]:
    """``indoorTemperature`` min/max from the device model, or a conservative room-temperature band."""
    lo, hi = 1.0, 55.0
    for attr in (digital_model or {}).get("attributes", []):
        if attr.get("name") != "indoorTemperature":
            continue
        ds = ((attr.get("valueRange") or {}).get("dataStep")) or {}
        try:
            return max(lo, float(ds["minValue"])), min(hi, float(ds["maxValue"]))
        except (KeyError, TypeError, ValueError):
            break
    return lo, hi

# The secondary app toggles + eco live in the SAME grSetDAC word block a control op seeds from
# (report[92:104]), so they decode straight back through the confirmed field map — no separate offsets to
# pin. 1-bit fields become bools; ecoMode is the multi-level value. (Both swing axes are already
# surfaced as ``swing_vertical`` / ``swing_horizontal`` above, so windDirectionVertical and
# windDirectionHorizontal are intentionally not repeated here.)
_STATUS_TOGGLE_FIELDS = {
    "healthMode": "health",
    "rapidMode": "strong",
    "muteStatus": "quiet",
    "silentSleepStatus": "sleep",
    "screenDisplayStatus": "lamp",
    "ecoMode": "eco",
}


def parse_full_status(
    data: bytes, profile=None, digital_model: dict | None = None, *, uplus_id: str | None = None
) -> dict:
    """Decode the CONFIRMED fields of a full-status report (see :data:`STATUS_LAYOUTS`).

    All offsets validated on real hardware (getAttributeMap ground truth + a one-attribute-at-a-time
    app sweep):
      - ``power``               = byte[97] & 0x01   (bit 0 — the byte packs eight flags)
      - ``target_temperature``  = byte[92] + 16
      - ``current_temperature`` = byte[104] / 2
      - ``operation_mode`` (STD code) = byte[94] >> 5   (0=auto 1=cool 2=dry 6=fan)
      - ``wind_speed``    (STD code) = byte[94] & 0x07  (1=high 2=medium 3=low 5=auto)
      - ``swing_vertical`` (bool)    = byte[93] & 0x08  (auto up-down swing; confirmed by app toggle)
      - ``swing_horizontal`` (bool)  = grSetDAC word4 bits 0-2 (auto left-right swing; app toggle)
      - ``outdoor_temperature``      = byte[106] - 64   (correlated across 3 states; 2 distinct points)

    NB the many air-quality/humidity attributes the digital model lists read 0 on this basic cooling
    unit — it has no such sensors — so they carry no data to decode from the report.

    The offsets above are the AAC1UKZ01 (127-byte) report — the "classic" split-AC family. Models
    that report fewer grSetDAC control words shift the sensor offsets that follow the word block —
    ``indoorTemperature`` / ``outdoorTemperature`` are therefore read from the blob's
    :class:`StatusLayout`, not from fixed constants. The attribute vector itself always starts at
    byte 92, so the classic control-word fields (power / target temperature / mode / fan / swing) are
    layout-independent *within that family*.

    A report whose length is NOT a classic layout is handed to the per-family **wire-model** registry
    (:mod:`haismart_hrdp.wire_models`) first — an entirely different family (e.g. the 117-byte
    "compact-12", where the sensors live inside the word array) decodes there. Such a decode carries a
    ``layout`` marker (the family name) and ``writable`` flag; the classic family sets neither. Only if
    no wire model claims the report does it fall through to the partial / unknown-layout handling.

    Pass an ``AttributeProfile`` (e.g. ``profile_for("AAC1UKZ01")``) to also get normalized ``mode``/
    ``fan_mode`` tokens. ``uplus_id`` (the device-list ``wifiType``) selects a wire model exactly when
    known, otherwise report length is used. Returns ``{}`` if ``data`` isn't a full-status report.
    """
    if len(data) < 4 or data[2:4] != b"\x27\x15":
        return {}
    # A session yields several report kinds, not just status: the fault bitmap and (when asked for)
    # the extended report share the same container. Both are long enough to pass the length checks
    # below and would decode into confident nonsense — e.g. the fault frame reads as a powered-off
    # unit with a 16 C setpoint. Reject the report kinds we can identify rather than relying on the
    # order the unit happens to send them in. Unrecognised kinds still fall through, so a family we
    # have not seen is not locked out.
    at = data.find(EPP_FRAME_HEAD)
    if at >= 0 and data[at + 10:at + 12] in (_EPP_RPT_ALARM, _EPP_RPT_EXTENDED):
        return {}
    # Non-classic families: the classic 125/127 lengths keep their hardware-verified inline decode
    # (and the write path) below; every other length consults the wire-model registry. A wire-model
    # decode that fails its own plausibility check returns None here, so we fall through to the
    # unknown-layout path rather than surfacing a mis-decode.
    if len(data) not in STATUS_LAYOUTS:
        wm = select_wire_model(len(data), uplus_id)
        if wm is not None and (decoded := wm.decode(data, profile)) is not None:
            return decoded
    layout = derive_status_layout(data, digital_model)
    if layout is None and len(data) <= _OFF_ONOFF:
        return {}   # too short even for the layout-independent fields

    # Fields at bytes 92..97 are grSetDAC words 1-3, which sit BEFORE anything the word count moves,
    # so they decode identically on every layout — confirmed byte-for-byte on both known models. That
    # is what makes a partial decode worthwhile: an unrecognised report still yields a working
    # thermostat (power / setpoint / mode / fan / vertical swing) instead of nothing at all.
    mode_code = str(data[_OFF_MODE_FAN] >> 5)
    # 3 bits, not 4: bit 3 of this byte belongs to `specialMode`, so masking 0x0F turns an odd
    # specialMode into a phantom fan code of `speed + 8` and blanks the fan dropdown.
    fan_code = str(data[_OFF_MODE_FAN] & 0x07)
    out: dict = {
        "power": bool(data[_OFF_ONOFF] & _ONOFF_MASK),
        "target_temperature": float(data[_OFF_TARGET_TEMP] + 16),
        "operation_mode": mode_code,
        "wind_speed": fan_code,
        "swing_vertical": vane_v_sweeping(data[_OFF_SWING_V] & 0x0F),
    }
    if profile is not None:
        out["mode"] = profile.normalized_mode(mode_code)
        out["fan_mode"] = profile.normalized_fan(fan_code)

    if layout is None:
        # Unknown report length. Say so explicitly so the caller can surface it as "this model needs
        # a layout" rather than the misleading "no decodable status", and omit every field whose
        # offset depends on the word count rather than guessing at it.
        out["layout"] = "unknown"
        out["partial"] = True
        return out

    out["current_temperature"] = _sensor_temp(data[layout.indoor_temp], scale=0.5, offset=0.0)
    out["outdoor_temperature"] = _sensor_temp(data[layout.outdoor_temp], scale=1.0, offset=-64.0)
    words = data[layout.baseline]
    out["swing_horizontal"] = vane_h_sweeping(_field_from_words(words, "windDirectionHorizontal"))
    # the secondary toggles + eco, read back from the report's grSetDAC word block (confirmed map)
    for field, label in _STATUS_TOGGLE_FIELDS.items():
        try:
            raw = _field_from_words(words, field)
        except ValueError:
            continue    # this layout is too short to carry the field; omit rather than fabricate
        out[label] = bool(raw) if GRSETDAC_FIELDS[field][2] == 1 else raw
    return out


def _sensor_temp(raw: int, *, scale: float, offset: float) -> float | None:
    """Decode a temperature byte, or ``None`` when the unit clearly has no such sensor.

    A model without (say) an outdoor probe reports 0 for it, which the raw formula turns into a
    confident -64.0 C. Published as a MEASUREMENT that lands in long-term statistics, one fabricated
    reading permanently skews the min/max/mean of a user's history, so an absent sensor must read as
    absent. 0x00/0xFF are the observed sentinels; the band catches the rest.
    """
    if raw in (0x00, 0xFF):
        return None
    value = raw * scale + offset
    lo, hi = _PLAUSIBLE_TEMP_C
    return value if lo <= value <= hi else None


# --- extended status (running power / compressor telemetry) -------------------

# The extended report repeats the ordinary status words and then appends an engineering block. These
# offsets are byte positions inside the decrypted blob, confirmed on a 24 000-BTU-class wall-mounted
# split (the "classic" family, whose extended report is 141 bytes).
_EXT_STATUS_LEN = 141
_EXT_OFF_POWER = 126          # BE16, watts
_EXT_OFF_COIL_DISCHARGE = 128  # high byte = indoor coil temp, low byte = compressor discharge temp
_EXT_OFF_FREQ = 133           # compressor frequency, Hz
_EXT_OFF_CURRENT = 134        # BE16, amps x 10
_EXT_OFF_ACTUATORS = 136      # BE16 of 2-bit actuator states: bits 0-1 compressor, bits 2-3 indoor fan
# A unit that is not reporting simply sends 0. Anything above these is not a real domestic reading and
# is treated as "no data" rather than published into long-term statistics.
_MAX_PLAUSIBLE_W = 20_000
_MAX_PLAUSIBLE_A = 100.0


def parse_extended_status(data: bytes) -> dict[str, Any]:
    """Decode the running power / compressor figures from an extended-status report.

    Returns ``{}`` for anything that is not the confirmed extended-report layout, so a device whose
    extended report differs simply yields no telemetry rather than fabricated numbers. Only the
    "classic" family's 141-byte report is confirmed; other families append their engineering block at
    different offsets and need their own entry before this can decode them.

    Keys (each omitted when the unit does not report it):
      ``power_w``, ``compressor_current_a``, ``compressor_frequency_hz``,
      ``coil_temperature``, ``discharge_temperature``, ``compressor_running``, ``fan_running``
    """
    if len(data) != _EXT_STATUS_LEN or data[2:4] != b"\x27\x15":
        return {}
    at = data.find(EPP_FRAME_HEAD)
    if at < 0 or data[at + 10:at + 12] != _EPP_RPT_EXTENDED:
        return {}

    out: dict[str, Any] = {}
    watts = int.from_bytes(data[_EXT_OFF_POWER:_EXT_OFF_POWER + 2], "big")
    if watts <= _MAX_PLAUSIBLE_W:
        out["power_w"] = watts
    amps = int.from_bytes(data[_EXT_OFF_CURRENT:_EXT_OFF_CURRENT + 2], "big") / 10.0
    if amps <= _MAX_PLAUSIBLE_A:
        out["compressor_current_a"] = round(amps, 1)
    out["compressor_frequency_hz"] = data[_EXT_OFF_FREQ]
    # Same absent-sensor policy as the status report's temperatures: 0 must not become a confident
    # -20/-64 C reading in a user's statistics.
    coil = _sensor_temp(data[_EXT_OFF_COIL_DISCHARGE], scale=0.5, offset=-20.0)
    if coil is not None:
        out["coil_temperature"] = coil
    discharge = _sensor_temp(data[_EXT_OFF_COIL_DISCHARGE + 1], scale=1.0, offset=-64.0)
    if discharge is not None:
        out["discharge_temperature"] = discharge
    actuators = int.from_bytes(data[_EXT_OFF_ACTUATORS:_EXT_OFF_ACTUATORS + 2], "big")
    out["compressor_running"] = bool(actuators & 0x03)
    out["fan_running"] = bool((actuators >> 2) & 0x03)
    return out


# --- fault bitmap -------------------------------------------------------------

# The unit pushes a fault frame alongside every status report, and answers a fault query with the
# same payload. It is a bitmap: after the command word come N bytes of flags, read as ONE big-endian
# integer whose least-significant bit is fault 0. So the LAST byte carries faults 0-7, the one before
# it 8-15, and so on. N comes from the frame's own length -- it is not fixed, and a unit sending
# fewer bytes shifts every position, so it must never be hardcoded.
_ALARM_MAX_BYTES = 32

# Fault labels by bit position. The service codes (E1, F4, ...) are the ones printed on the unit and
# shown by the handset, so they are the useful half of the label.
ALARM_LABELS: tuple[str, ...] = (
    "F1 - Outdoor module failure",
    "Outdoor defrost sensor failure",
    "F14 - Outdoor compressor exhaust sensor failure",
    "F11 - Outdoor EEPROM abnormality",
    "E2 - Indoor coil sensor failure",
    "E7 - Indoor-outdoor communication failure",
    "Power supply overvoltage protection",
    "Communication failure between panel and indoor unit",
    "F4 - Outdoor compressor overheat protection",
    "Outdoor environmental sensor abnormality",
    "Full water protection",
    "E4 - Indoor EEPROM failure",
    "Outdoor out air sensor failure",
    "F13 - PCB and module communication failure",
    "E14 - Indoor DC fan failure",
    "F2 - Outdoor DC fan failure",
    "Door switch failure",
    "Dust filter needs cleaning",
    "Water shortage protection",
    "Humidity sensor failure",
    "E1 - Indoor temperature sensor failure",
    "Manipulator limit failure",
    "Indoor PM2.5 sensor failure",
    "Outdoor PM2.5 sensor failure",
    "Indoor heating overload alarm",
    "Outdoor AC current protection",
    "Outdoor compressor operation abnormality",
    "Outdoor DC current protection",
    "Outdoor no-load failure",
    "CT current abnormality",
    "Indoor cooling freeze protection",
    "High and low pressure protection",
    "Compressor out air temperature too high",
    "Outdoor evaporator sensor failure",
    "Outdoor cooling overload",
    "Water pump drainage failure",
    "Three-phase power supply failure",
    "Four-way valve failure",
    "External alarm / flow switch failure",
    "E18 - Temperature cutoff protection",
    "Different mode operation failure",
    "Electronic expansion valve failure",
    "Dual heat source sensor Tw failure",
    "Communication failure with the wired controller",
    "Indoor unit address duplication failure",
    "50Hz zero crossing failure",
    "Outdoor unit failure",
    "Formaldehyde sensor failure",
    "VOC sensor failure",
    "CO2 sensor failure",
    "Firewall failure",
)


def alarm_label(code: int) -> str:
    """The label for a fault position, or a placeholder for one this model does not name."""
    return ALARM_LABELS[code] if 0 <= code < len(ALARM_LABELS) else f"Unknown fault {code}"


def parse_alarm_frame(data: bytes) -> dict[str, Any] | None:
    """Decode a fault frame into active fault positions, or ``None`` if ``data`` is not one.

    Returns ``{"alarm_count", "alarm_codes", "alarm_labels"}``; an all-clear unit yields a count of 0
    and empty lists, which is a meaningful answer and distinct from ``None`` ("no fault frame here").
    """
    at = data.find(EPP_FRAME_HEAD)
    if at < 0 or len(data) < at + 12 or data[at + 10:at + 12] != _EPP_RPT_ALARM:
        return None
    declared = data[at + 2]
    payload = data[at + 10:at + 10 + max(declared - 8, 0)]
    flags = payload[2:]
    if not flags or len(flags) > _ALARM_MAX_BYTES:
        return None
    count = len(flags)
    codes = [
        bit + ((count - 1 - index) << 3)
        for index in range(count - 1, -1, -1)
        for bit in range(8)
        if flags[index] & (1 << bit)
    ]
    return {
        "alarm_count": len(codes),
        "alarm_codes": codes,
        "alarm_labels": [alarm_label(code) for code in codes],
    }


# --- live session (sync + async), READ-ONLY -----------------------------------

def read_status(ip: str, device_id: str, local_key: str, *,
                pro_ver: int = 2, timeout: float = 4.0) -> list[bytes]:
    """READ-ONLY: full handshake then collect + decrypt the AC's status pushes. Sends no writes."""
    s = socket.create_connection((ip, USS_PORT), timeout=timeout)
    blobs: list[bytes] = []
    try:
        s.sendall(hello_message(device_id, sn=1, pro_ver=pro_ver))
        resp = _recv_message(s)
        check_hello_resp(resp)
        s.sendall(hello_done_message(sn=2, session=resp.session, pro_ver=pro_ver))
        buf = b""
        deadline = time.monotonic() + timeout
        while len(buf) < 8192 and time.monotonic() < deadline:
            try:
                chunk = s.recv(4096)
            except TimeoutError:
                break
            if not chunk:
                break
            buf += chunk
            # The AC delivers its whole status burst at once, then holds the socket open and silent,
            # so waiting the full timeout after the burst spent ~4s of wall clock on every poll for
            # data that arrived in ~50ms. Once bytes are in hand, allow only a short idle window.
            # (The write path already did this; the read paths never got the same treatment.)
            s.settimeout(min(timeout, _COLLECT_IDLE))
    finally:
        s.close()
    for raw in split_messages(buf):
        m = decode_message(raw)
        if len(m.payload) >= 48:
            try:
                blobs.append(biz_decrypt(m.payload, local_key)[1])
            except ValueError:
                pass
    return blobs


async def async_read_status(ip: str, device_id: str, local_key: str, *,
                            pro_ver: int = 2, timeout: float = 4.0,
                            extra_request: bytes | None = None) -> list[bytes]:
    """Async READ-ONLY handshake + status collect (for the HA coordinator).

    ``extra_request`` optionally sends ONE additional read-only query inside the same session, after
    the handshake completes, and collects its reply alongside the pushed status. This is how the
    extended-status query (:func:`extended_status_epp_frame`) is polled: these units accept a single
    connection at a time, so folding the extra query into the existing cycle costs no additional
    connection and no additional poll. It is still a read — nothing is written to the device.
    """
    reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, USS_PORT), timeout)
    blobs: list[bytes] = []
    try:
        writer.write(hello_message(device_id, sn=1, pro_ver=pro_ver))
        await writer.drain()
        rbuf = b""
        while not _message_complete(rbuf):
            chunk = await asyncio.wait_for(reader.read(4096), timeout)
            if not chunk:
                raise RuntimeError("connection closed before a complete reply")
            rbuf += chunk
        resp = decode_message(rbuf)
        check_hello_resp(resp)
        writer.write(hello_done_message(sn=2, session=resp.session, pro_ver=pro_ver))
        await writer.drain()
        buf = b""
        deadline = time.monotonic() + timeout
        sent_extra = extra_request is None
        while len(buf) < 8192:
            # full timeout for the first bytes, then only a short idle window for stragglers - see
            # the note in `read_status`. The deadline stops a peer that trickles bytes from holding
            # the poll open indefinitely, since each read otherwise resets its own timeout.
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            read_to = min(remaining, timeout if not buf else min(timeout, _COLLECT_IDLE))
            try:
                chunk = await asyncio.wait_for(reader.read(4096), read_to)
            except TimeoutError:
                break
            if not chunk:
                break
            buf += chunk
            if not sent_extra:
                # The session is only live once the unit has sent HELLO_DONE_RESP; its body carries
                # the sequence base this session's requests must use. Send the extra query exactly
                # once, then keep collecting (and give the reply a fresh window to arrive).
                for raw in split_messages(buf):
                    msg = decode_message(raw)
                    if msg.info_type != INFO_HELLO_DONE_RESP:
                        continue
                    try:
                        _, seq_base = biz_decrypt(msg.payload, local_key)
                    except ValueError:
                        sent_extra = True   # stale key: the status decrypt will fail too, so give up
                        break
                    envelope = build_cae_op_request(extra_request, device_id, 1)
                    writer.write(encode_message(
                        0x64, 0, biz_encrypt(int.from_bytes(seq_base, "big"), envelope, local_key),
                        type_byte=TYPE_BYTE[pro_ver], flag=FLAG_BIZ_ENCRYPTED, session=resp.session))
                    await writer.drain()
                    sent_extra = True
                    deadline = time.monotonic() + timeout
                    break
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass
    for raw in split_messages(buf):
        m = decode_message(raw)
        if len(m.payload) >= 48:
            try:
                blobs.append(biz_decrypt(m.payload, local_key)[1])
            except ValueError:
                pass
    return blobs


# --- WRITE / control session -------------------------------------------------
# grSetDAC is a GROUP set: the frame carries the full current settable-word state plus the change. The
# baseline for those words is read straight out of a full-status report — byte-for-byte, report[92:104]
# equals the grSetDAC data words 1..6 (verified against 64/66 real status reports). So the
# control flow is: read status -> take report[92:104] as the baseline -> set_grsetdac_field(...) for each
# change -> build_epp_frame(0x01, EPP_CMD_GRSETDAC, words) -> async_send_op.
GRSETDAC_BASELINE = STATUS_LAYOUTS[_FULL_STATUS_LEN].baseline  # words 1..6 (the 127-byte report)


def grsetdac_baseline_from_status(status_blob: bytes) -> bytes:
    """Extract the grSetDAC data-word bytes (words 1..N) from a full-status report to seed a control op
    — so a group-set preserves every attribute except the one(s) being changed.

    ``N`` comes from the report's :class:`StatusLayout`. Slicing a fixed 12 bytes would pull read-only
    sensor bytes into the word block on a model that carries fewer control words, and a group-set seeded
    that way would write a sensor reading back as if it were a control word.

    Only the classic family (:data:`STATUS_LAYOUTS`) has a capture-confirmed grSetDAC write path, so
    this raises for any other report — including a non-classic family that :func:`parse_full_status`
    reads fine via the wire-model registry. Writing to such a family would use the wrong field map, so
    control stays refused until that family is captured on real hardware.
    """
    layout = status_layout(status_blob)
    if layout is None:
        raise ValueError(
            f"report length {len(status_blob)} has no capture-confirmed grSetDAC write layout "
            f"(known: {sorted(STATUS_LAYOUTS)}) — control is unavailable for this model"
        )
    return status_blob[layout.baseline]


def grsetdac_op_frame(words: bytes) -> bytes:
    """Build the inner grSetDAC (0x6001) EPP frame from a full 12-byte word block."""
    return build_epp_frame(0x01, EPP_CMD_GRSETDAC, words)


def read_grsetdac_field(status_blob: bytes, name: str) -> int:
    """Read the current raw EPP value of a confirmed grSetDAC ``name`` out of a full-status report.

    The report carries the same packed words as a grSetDAC op (report[92:104]), so this lets the HA layer
    show the live state of fields the report parser doesn't already expose (the secondary toggles / eco)."""
    return _field_from_words(grsetdac_baseline_from_status(status_blob), name)


def _field_from_words(words: bytes, name: str) -> int:
    """Read a confirmed grSetDAC field out of an already-extracted word block.

    Bounds-checked, mirroring :func:`set_grsetdac_field`: a field living in a word the report does not
    carry raises a clear ``ValueError`` instead of an ``IndexError`` from deep inside a decode. That
    matters on the shorter layouts, where a word-5/6 field would otherwise kill the whole poll.
    """
    if name not in GRSETDAC_FIELDS:
        raise KeyError(f"{name!r} is not a confirmed grSetDAC field")
    wi, shift, width = GRSETDAC_FIELDS[name]
    off = (wi - 1) * 2
    if off + 1 >= len(words):
        raise ValueError(
            f"{name} lives in grSetDAC word {wi}, but this report carries only "
            f"{len(words) // 2} word(s)"
        )
    word = (words[off] << 8) | words[off + 1]
    return (word >> shift) & ((1 << width) - 1)


async def _read_pushed_status(reader, leftover: bytes, local_key: str, timeout: float) -> bytes | None:
    """Return the AC's post-handshake status push (a full-status blob) to seed a control op from, or
    ``None`` if none arrives in time. ``leftover`` is any bytes already read past HELLO_DONE_RESP. Waits
    up to ``timeout`` for the first bytes, then only a short idle window; returns on the first decodable
    full-status report."""
    buf = leftover
    first = not buf
    while len(buf) < 16384:
        for raw in split_messages(buf):
            m = decode_message(raw)
            if len(m.payload) >= 48:
                try:
                    blob = biz_decrypt(m.payload, local_key)[1]
                except ValueError:
                    continue
                # A full-status report, i.e. a blob whose length maps to a known StatusLayout — so the
                # grSetDAC baseline is a complete word block. A blob of any other size (e.g. a small ack
                # that happens to decrypt) must not seed a truncated/malformed op frame.
                if status_layout(blob) is not None:
                    return blob
        read_to = timeout if first else min(timeout, _COLLECT_IDLE)
        try:
            chunk = await asyncio.wait_for(reader.read(4096), read_to)
        except TimeoutError:
            break
        if not chunk:
            break
        buf += chunk
        first = False
    return None


async def async_send_op(ip: str, device_id: str, local_key: str, epp_frame: bytes | None = None, *,
                        counter: int, biz_sn: int | None = None, uss_sn: int = 0,
                        info_type: int = 0x64, pro_ver: int = 2, timeout: float = 4.0,
                        collect: bool = True,
                        build_frame: Callable[[bytes | None], bytes] | None = None) -> list[bytes]:
    """Handshake, then send ONE encrypted op (e.g. a grSetDAC control frame) and collect the AC's reply
    reports. **This WRITES to the AC** — only call it for a user-authorized control action.

    Op framing: hello -> hello_done -> one ``0xEAC4`` biz-encrypted op with the
    CAE request envelope (type 0x2714, deviceId, ``counter``). ``uss_sn`` defaults to 0 (as the app sent).
    The op's ``biz_sn`` MUST be the session sequence base the AC assigns in HELLO_DONE_RESP (its decrypted
    body is that base as a BE32) — the AC drops the connection on a wrong sn. By default (``biz_sn=None``)
    it is read from HELLO_DONE_RESP automatically; pass a value only to override. Returns decrypted status
    blobs pushed in reply (so the caller can confirm the new state).

    Seeding a group-set (read-modify-write): pass ``build_frame`` instead of ``epp_frame``. The AC pushes
    its current status right after the handshake (same as a read), so we hand that fresh in-session
    baseline blob (or ``None`` if none arrived) to ``build_frame`` to construct the op — no separate read
    connection, so control stays snappy and the AC isn't hit twice. Exactly one of ``epp_frame`` /
    ``build_frame`` must yield a frame."""
    reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, USS_PORT), timeout)
    blobs: list[bytes] = []
    try:
        writer.write(hello_message(device_id, sn=1, pro_ver=pro_ver))
        await writer.drain()
        rbuf = b""
        while not _message_complete(rbuf):
            chunk = await asyncio.wait_for(reader.read(4096), timeout)
            if not chunk:
                raise RuntimeError("connection closed before a complete reply")
            rbuf += chunk
        resp = decode_message(rbuf)
        check_hello_resp(resp)
        writer.write(hello_done_message(sn=2, session=resp.session, pro_ver=pro_ver))
        await writer.drain()
        # The AC only accepts an op once the session is fully established — i.e. AFTER it sends
        # HELLO_DONE_RESP (confirmed by the app's real choreography: it waits for HELLO_DONE_RESP before
        # the first op). Consume messages until we see it, then send. Carry any bytes past HELLO_RESP.
        hbuf = rbuf[6 + struct.unpack(">H", rbuf[4:6])[0]:]
        done_msg: Message | None = None
        done_end = 0  # byte offset in hbuf just past HELLO_DONE_RESP (rest is the AC's status push)
        while done_msg is None:
            off = 0
            for raw in split_messages(hbuf):
                m = decode_message(raw)
                off += len(raw)
                if m.info_type == INFO_HELLO_DONE_RESP:
                    done_msg = m
                    done_end = off
                    break
            if done_msg is not None:
                break
            chunk = await asyncio.wait_for(reader.read(4096), timeout)
            if not chunk:
                raise RuntimeError("connection closed before HELLO_DONE_RESP")
            hbuf += chunk
        # The AC assigns this session's op sequence base in HELLO_DONE_RESP (decrypted body = BE32 base).
        # The op MUST use it as biz_sn or the AC drops the connection.
        if biz_sn is None:
            _, seq_base = biz_decrypt(done_msg.payload, local_key)
            biz_sn = int.from_bytes(seq_base, "big")
        if build_frame is not None:
            # Read-modify-write in ONE session: the AC pushes its current status right after the
            # handshake (like a read), so seed the group-set from that fresh in-session baseline —
            # no second connection. ``build_frame`` gets None if no status arrived (caller falls back).
            baseline = await _read_pushed_status(reader, hbuf[done_end:], local_key, timeout)
            epp_frame = build_frame(baseline)
        if epp_frame is None:
            raise RuntimeError("async_send_op: neither epp_frame nor build_frame produced a frame")
        envelope = build_cae_op_request(epp_frame, device_id, counter)
        ciphertext = biz_encrypt(biz_sn, envelope, local_key)
        writer.write(encode_message(info_type, uss_sn, ciphertext, type_byte=TYPE_BYTE[pro_ver],
                                    flag=FLAG_BIZ_ENCRYPTED, session=resp.session))
        await writer.drain()
        if collect:
            buf = b""
            while len(buf) < 8192:
                # The AC applies the change and pushes its updated status almost immediately, then
                # holds the socket open and silent. Wait up to the full `timeout` for the FIRST reply
                # bytes, but once the reply burst has started, linger only a short idle window for any
                # trailing frames. Waiting the full `timeout` after the burst is what made the HA state
                # lag seconds behind the unit — the state was correct, just returned late.
                read_timeout = timeout if not buf else min(timeout, _COLLECT_IDLE)
                try:
                    chunk = await asyncio.wait_for(reader.read(4096), read_timeout)
                except TimeoutError:
                    break
                if not chunk:
                    break
                buf += chunk
            for raw in split_messages(buf):
                m = decode_message(raw)
                if len(m.payload) >= 48:
                    try:
                        blobs.append(biz_decrypt(m.payload, local_key)[1])
                    except ValueError:
                        pass
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass
    return blobs
