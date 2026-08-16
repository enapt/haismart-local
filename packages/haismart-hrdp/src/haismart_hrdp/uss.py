"""uSS local transport (TCP :56800) — the on-LAN protocol these ACs speak for reads and control.

Layers
------
1. **uSS message**: a 16-byte header + payload::

     [0:4]   info_code BE32 = 0xEA60 + info_type   (hello=0, hello_resp=1, hello_done=2, done_resp=3)
     [4:6]   payload_len + 0x0a (BE16)
     [6]     protocol version (pro_ver 2 -> 0x01, pro_ver 3 -> 0x6E)
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
from collections.abc import Callable, Collection, Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .canonical_map import CANONICAL_WRITE
from .panel import PANEL_BOOL_CONTROLS, PANEL_ENUM_CONTROLS, PANEL_EXTRA_POSITIONS
from .wire_models import (
    OPERATION_SOURCE,
    decode_related,
    select_wire_model,
    vane_h_sweeping,
    vane_v_sweeping,
)

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

TYPE_BYTE = {2: 0x01, 3: 0x6E}  # pro_ver -> header byte 6


def negotiated_type_byte(resp: Message, *, requested: int = TYPE_BYTE[2]) -> int:
    """The header version byte to speak for the rest of the session: the appliance's own.

    Header byte 6 is the uSS protocol version, and the appliance's reader compares it against the
    version it is running. On a mismatch it DISCARDS the packet -- no reply, no error, nothing to
    observe from this side. Opening with a fixed value therefore risks a session that handshakes
    perfectly and then swallows every command, which is the hardest kind of fault to diagnose and
    exactly the shape of one already seen (see the flag note below).

    Every appliance measured answers ``0x01``, which is what was always sent, so this changes
    nothing observed and removes an assumption. A reply of ``0`` is treated as no answer and leaves
    ``requested`` in place: a value known to work beats a value known to be empty.
    """
    return resp.type_byte or requested


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


class LocalKeyRotated(RuntimeError):
    """The appliance is using a newer localKey than the one we hold.

    Raised BEFORE anything is decrypted, which is the whole point. The appliance states its current
    key version in its handshake reply, and everything after that reply -- the reply itself included
    -- is encrypted with that key. Decrypting it with an older one yields noise, and noise fails a
    structural check with a message about lengths, so a rotated key used to surface as
    "does not accept that setting: bad rawlen" on a command the appliance never received.

    The vendor's own client does exactly this comparison and fetches a fresh key when it fails.
    """

    def __init__(self, device_version: int, held_version: int) -> None:
        super().__init__(
            f"the appliance has rotated its local key to v{device_version} and this one is "
            f"v{held_version}; a new key is needed before it will accept anything"
        )
        self.device_version = device_version
        self.held_version = held_version


def check_hello_resp(msg: Message, expect_localkey_version: int | None = None) -> HelloResp:
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
    # The version the appliance reports is the version everything after this point is encrypted
    # with. Checking it here is what `probe_localkey_version` has always said to do -- "compare
    # this against the cached key's version ... BEFORE ever attempting to decrypt" -- and the op
    # path was the one place that read the number and dropped it.
    if (
        expect_localkey_version is not None
        and resp.localkey_version
        and resp.localkey_version != expect_localkey_version
    ):
        raise LocalKeyRotated(resp.localkey_version, expect_localkey_version)
    return resp


def parse_hello_resp(msg: Message) -> HelloResp:
    """HELLO_RESP payload is ``status(BE32) || localkey_version(BE32)`` (e.g. ``00000001 00000004``)."""
    status, ver = (struct.unpack(">II", msg.payload[:8]) if len(msg.payload) >= 8 else (0, 0))
    return HelloResp(msg.session, msg.sn, status, ver)


def probe_handshake_reply(
    ip: str, device_id: str, *, pro_ver: int = 2, timeout: float = 4.0
) -> tuple[int, int, bytes]:
    """Complete a handshake and hand back HELLO_DONE_RESP **as it arrived**, without decrypting it.

    Returns ``(localkey_version, flag, payload)``.

    This exists because the one frame nobody could ever produce on request is the one that decides
    whether a command can be sent at all. Everything the appliance says afterwards is encrypted with
    a key that may or may not be the one being held, and when it cannot be read there is nothing to
    look at -- no capture, no bytes, only a complaint about a length. Asking the appliance directly,
    needing no key to do it, means a diagnostics file carries the evidence instead of a person being
    asked to reproduce a fault with debug logging on.

    Read-only and key-free: the handshake is plaintext, and this stops before anything is decoded.
    """
    s = socket.create_connection((ip, USS_PORT), timeout=timeout)
    try:
        s.sendall(hello_message(device_id, sn=1, pro_ver=pro_ver))
        resp = _recv_message(s)
        version = check_hello_resp(resp).localkey_version
        s.sendall(encode_message(INFO_HELLO_DONE, 2, b"",
                                 type_byte=negotiated_type_byte(resp, requested=TYPE_BYTE[pro_ver]),
                                 session=resp.session))
        done = _recv_message(s)
        if done.info_type != INFO_HELLO_DONE_RESP:
            raise RuntimeError(f"expected HELLO_DONE_RESP, got {done.info_code:#x}")
        return version, done.flag, done.payload
    finally:
        s.close()


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
    # The manufacturer's own decoder checks `rawlen > 0x28`, `rawlen <= payload_len - 2` and
    # `rawlen <= 0xE028`, bounding against the payload **as it arrived** -- these are its numbers,
    # not ours. Two differences mattered enough to close: it rejects `rawlen == 0x28` (a frame
    # carrying no data at all) where we accepted one, and it bounds against the whole payload where
    # we used the 16-byte-aligned slice, which is up to fifteen bytes shorter. A well-formed frame
    # satisfies both, so neither difference is a fault we have observed -- they are simply places
    # our reader was stricter than the client the appliance is built to talk to.
    #
    # ⚠️ The message carries its numbers deliberately. This complaint is what a reporter sees when
    # a command fails, and bare "bad rawlen" says nothing: a wrong key decrypts to noise whose
    # first two bytes are a random 16-bit number, which looks exactly like a structural fault. A
    # rawlen in the tens of thousands against a 200-byte payload is a key problem; one that misses
    # by a few bytes is a framing problem. Same words, opposite causes, and only the figures separate
    # them.
    if not 0x28 < rawlen <= min(len(ciphertext) - 2, 0xE028) or 0x2A + datalen > len(pt):
        raise ValueError(
            f"bad rawlen {rawlen} (payload {len(ciphertext)} B, decrypted {len(pt)} B)"
        )
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
# otherwise ordinary reports are escaped. Every length-keyed lookup then misses, and because the
# write path gates on the blob length
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
#
# The status constant names the report a *query* draws. A unit also answers a group-set with `6d5f`,
# which carries the identical payload, and both arrive on the same connection during a control op.
# `parse_full_status` therefore identifies a status report by *exclusion* -- anything that is not an
# alarm or an extended report -- and that is deliberate. Tightening it to an equality test against
# `_EPP_RPT_STATUS` would drop every control confirmation while still passing the tests, since those
# are built from query responses.
_EPP_RPT_STATUS = b"\x6d\x01"    # the ordinary full-status report (a group-set is answered `6d5f`)
_EPP_RPT_ALARM = b"\x0f\x5a"     # fault bitmap
_EPP_RPT_EXTENDED = b"\x7d\x01"  # extended status (running power / compressor figures)

# The byte before the command word says what KIND of frame this is, and one value means the unit is
# refusing rather than answering: it will not carry a command word we recognise, so every check that
# keys on the command word reads a refusal as silence.
#
# That distinction is worth making. A control op that draws a refusal and a control op that draws
# nothing are the same event to a caller who only asks "did a status report come back?", and the
# difference is exactly the one a user needs: a setting the unit declined, versus a connection that
# missed. A refusal is also the only direct evidence that a unit rejects a particular write -- every
# such verdict here otherwise rests on writing a bit and observing it did not change.
_EPP_FRAME_TYPE_OFFSET = 9       # FF FF | len | flags | 5 reserved | frameType | cmd(2) | ...
EPP_FRAME_TYPE_REFUSED = 0x03


def epp_command(blob: bytes) -> bytes | None:
    """The two-byte EPP command a frame carries, or ``None`` if it holds no EPP frame.

    Frame types that take no command -- the alarm query and the alarm stop -- have no meaningful
    two bytes here, so read this together with :func:`epp_frame_type` rather than on its own.
    """
    at = blob.find(EPP_FRAME_HEAD)
    if at < 0 or len(blob) < at + 12:
        return None
    return bytes(blob[at + 10:at + 12])


def describe_epp_frame(blob: bytes) -> str | None:
    """A short name for a frame we recognise but do not decode, or ``None`` if it is unfamiliar.

    Used when nothing decoded, to separate "the unit sent something we know about and ignore" from
    "the unit sent something nobody here has seen". The first is not a fault and should not read
    like one in a log; the second is the interesting case and is what an unfamiliar model looks
    like.
    """
    frame_type = epp_frame_type(blob)
    if frame_type is None:
        return None
    if frame_type == EPP_FRAME_TYPE_REFUSED:
        return "a refusal"
    if frame_type == EPP_FRAME_TYPE_STOP_ALARM:
        return "an alarm-stop frame"
    command = epp_command(blob)
    if command == EPP_CMD_CHANGED_PARAMS:
        return "a changed-parameters report (6c01), which this integration does not read"
    return None


def epp_frame_type(blob: bytes) -> int | None:
    """The frame-type byte of the EPP frame inside ``blob``, or ``None`` if it carries no frame."""
    at = blob.find(EPP_FRAME_HEAD)
    if at < 0 or len(blob) <= at + _EPP_FRAME_TYPE_OFFSET:
        return None
    return blob[at + _EPP_FRAME_TYPE_OFFSET]


def reply_refused(blobs: Iterable[bytes]) -> bool:
    """Whether any reply in ``blobs`` is the unit refusing the command it was sent.

    Only ever consulted when a control op produced no usable status report — a unit that answers
    with its updated state has accepted the write, whatever else arrived alongside.
    """
    return any(epp_frame_type(blob) == EPP_FRAME_TYPE_REFUSED for blob in blobs)


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


# The frame types under which the extended-status query is published, in the order to try them.
# Most models ask for it the way every other command is sent, under the control frame type. One
# generation -- the metering inverters -- publishes the same command under 0x60 instead, and a unit
# of that generation simply says nothing to the usual form. Nothing distinguishes "not supported"
# from "asked the wrong way" on the wire, so both are tried before a unit is written off as having
# no telemetry.
EXTENDED_STATUS_FRAME_TYPES: tuple[int, ...] = (0x01, 0x60)

# Declared by every published model and deliberately not sent: it clears the unit's current fault
# rather than reading anything, and nothing here has a reason to.
EPP_FRAME_TYPE_STOP_ALARM = 0x09

# A changed-parameters report. Models that publish it list, per attribute, which of its fields the
# frame carries; a device sends one when something changes instead of a whole status report. No unit
# met so far sends it, and it is named here so that a frame arriving under it is recognised as a
# known kind rather than logged as undecodable.
EPP_CMD_CHANGED_PARAMS = b"\x6c\x01"


def extended_status_epp_frame(frame_type: int = EXTENDED_STATUS_FRAME_TYPES[0]) -> bytes:
    """The read-only extended-status query ``ff ff 0a 00*6 <frameType> 4d fe <sum>``.

    Changes nothing. Units that support it answer with an extra report carrying the live
    power/current/compressor figures (:func:`parse_extended_status`) *in addition to* the ordinary
    status report, so one request returns both. Units that don't support it answer with a short
    refusal and still send normal status — hence it is safe to ask unconditionally.

    ``frame_type`` selects between the forms in :data:`EXTENDED_STATUS_FRAME_TYPES`. A caller that
    gets no extended report should try the next one before concluding the unit has no telemetry:
    the difference is between generations of the same product line, not between capable and
    incapable units, and asking the wrong way looks exactly like asking a unit that cannot answer.
    """
    return build_epp_frame(frame_type, EPP_CMD_EXTENDED_STATUS)


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
# The fields the encoder may write. **Membership is deliberate and hand-held; positions are not.**
#
# A name appears below only once a real write of it has been observed, and that rule is the whole
# reason this encoder can be trusted: a group-set applies the entire word block, so a field added on
# inference would ride along with every command. The published map describes far more fields than
# these, and listing a field there is emphatically NOT grounds to add it here.
#
# Where a field sits, on the other hand, is taken from the published map rather than transcribed by
# hand. The two were arrived at independently and agree field for field, so taking positions from one
# place removes the only thing a second copy could contribute: a typo in the table that decides which
# bit a command lands on. `test_grsetdac_fields_match_their_confirmed_positions` pins the
# resulting values, so a change in the map cannot quietly move a live control.
#
# App labels: health / strong / quiet / sleep / lamp (front display) / up-and-down / left-and-right.
_CONFIRMED_WRITE_FIELDS = (
    "targetTemperature",        # epp = degC - 16 ; range 16..30
    "operationMode",            # 0=auto/comfort 1=cool 2=dry 6=fanOnly
    "windSpeed",                # 1=high 2=med 3=low 5=auto
    "onOffStatus",              # power 0=off 1=on
    "healthMode",
    "rapidMode",
    "muteStatus",
    "silentSleepStatus",
    "screenDisplayStatus",
    "windDirectionVertical",    # a TOGGLE on this unit: 0=off, 0x0c=on
    "windDirectionHorizontal",  # 0=fixed, 7=auto
    # ^ confirmed one attribute at a time: setting ONLY left-right swing moves word4 bits
    #   0-2 between 7 and 0 and nothing else — ecoMode (same word, bits 3-5) stayed 0 and the
    #   vertical nibble stayed put. Unlike windDirectionVertical the raw EPP value equals the STD
    #   code the digital model lists (0 = 左右摆位置一(固定), 7 = 左右摆位置八(自动)).
    "selfCleaningStatus",       # the flag word, bit 4 — START-only trigger; see the note below
    # ^ live-confirmed 2026-08-04: with the unit on, in a non-auto mode and not sleeping, setting
    #   ONLY this bit read back set on the next poll and the unit's panel showed "CL" — a cycle
    #   started. It is a one-shot: there is no OFF command (the model declares it), so the value is
    #   restricted to the start (1). Its writability is gated by the model's own modifiers — off,
    #   auto mode, sleep, or a fault all lock it — which `locked_fields` already enforces.
)

# Fields the shared map does not describe, so they cannot be looked up and are stated here.
# `ecoMode` is NOT the digital model's energySavingStatus bool (word5 b6, which never moves here):
# this unit repurposes word4 b3-5 into a 3-bit eco level, 0=off and 5/6/7 the three levels. Confirmed
# by setting economy alone. The shared map assigns those bits to other attributes, which is why
# it cannot supply this one.
_DEVICE_SPECIFIC_WRITES = {
    "ecoMode": (4, 3, 3),
}

# NB `echoStatus` (word 3, bit 7 — the command-confirmation beeper, where set = silent) is the one
# field that decodes cleanly and is marked user-facing by the device model yet stays deliberately
# absent: a live write of it was accepted while the bit never landed, and the manufacturer's own
# control panel does not offer it. `selfCleaningStatus` looked identical on paper (both in the
# published write frame, both model-writable, both "managed" by a writability modifier) but is NOT
# the same case — the panel *does* offer self-clean, and a live write of it DID land (the panel
# showed "CL"). So it is confirmed above. The lesson stands: presence in the map is not grounds to
# add a field — an observed write is; the panel reference predicts the outcome but the write settles it.
# The panel's own control set (`haismart_hrdp.panel`), positioned by the invariant frame. These are
# authorised the way the vendor app authorises them — the device declares the attribute, it is not
# invisible, and the panel renders a widget for it — not by a capture apiece. The app controls these
# without probing hardware, and the frame positions them identically on every device type, so they
# are as safe to encode as the confirmed set. Only the ones the frame actually places are taken here;
# the caller still gates on the device declaring the attribute (see `coordinator.panel_*_fields`).
_PANEL_FRAME_WRITES = {
    **{
        name: (CANONICAL_WRITE[name].word, CANONICAL_WRITE[name].bit, CANONICAL_WRITE[name].length)
        for name in (*PANEL_BOOL_CONTROLS, *PANEL_ENUM_CONTROLS)
        if name in CANONICAL_WRITE
    },
    # order-derived controls the invariant frame does not carry (unanimous, see PANEL_EXTRA_POSITIONS)
    **PANEL_EXTRA_POSITIONS,
}

GRSETDAC_FIELDS = {
    **{
        name: (
            CANONICAL_WRITE[name].word,
            CANONICAL_WRITE[name].bit,
            CANONICAL_WRITE[name].length,
        )
        for name in _CONFIRMED_WRITE_FIELDS
    },
    **_DEVICE_SPECIFIC_WRITES,
    **_PANEL_FRAME_WRITES,
}

# Allowed raw EPP values per field — the encoder REFUSES anything else, so we never fire a code the app
# was not observed to send (temperature is range-checked instead). Bools accept {0,1} implicitly.
# Values our own units don't have (e.g. heat, absent on a cooling-only AC) can additionally be
# authorized per device by that device's own digital model — see :data:`GRSETDAC_MODEL_AUTHORIZED`.
GRSETDAC_ALLOWED_VALUES = {
    "operationMode": {0, 1, 2, 4, 6},   # 4 = heat; see GRSETDAC_ENUMS
    "windSpeed":     {1, 2, 3, 5},
    "windDirectionVertical": {0x00, 0x0c},   # off / on (the app's exact on-nibble)
    "windDirectionHorizontal": {0x00, 0x07}, # the two codes ever seen written: fixed / auto. The
                                             # positions between them come from the device's own
                                             # model — see GRSETDAC_MODEL_AUTHORIZED.
    "ecoMode":               {0, 5, 6, 7},   # off / three levels (5/6/7)
    "selfCleaningStatus":    {1},            # START only — the cycle runs to completion, no OFF command
    # panel enum controls (bools are handled by the width==1 path): the wire values their state maps use
    "humanSensingStatus":    {0, 1, 2, 3},   # off / avoid / follow / on
}

# Fields whose value space the DEVICE'S OWN digital model may extend beyond the observed set above
# (pass the model's codes as ``model_values``). All three are plain STD enums that the model
# describes attribute-for-attribute (``valueRange`` LIST) and whose STD code IS the raw EPP value —
# the wire model maps stdValue -> eppValue 1:1 for them — so a mode a heat-pump unit has and ours
# doesn't is taken from that unit's model rather than guessed.
#
# ``windDirectionHorizontal`` qualifies on the same terms: the model lists eight codes (0 = position
# one/fixed .. 7 = position eight/auto) and the field's raw wire value IS that code — a unit reports
# the vane parked at position five as the same 4 the model names. So a unit that publishes
# intermediate vane positions can be pointed at one, authorized by its own model rather than by
# inference.
#
# ``windDirectionVertical`` qualifies too, but with a catch the caller must honour: its model codes
# are NOT its wire values (a model names auto 8; the wire has always used 0x0C). Pass the model's
# codes through :data:`~haismart_hrdp.wire_models.VANE_V_MODEL_TO_EPP` first — ``model_values`` here
# means wire values, as everything else in this module does. The translation is confirmed on
# hardware, on the commanded path: a unit stepped through every stop its app offers reported the
# table's value each time.
#
# ``ecoMode`` does not qualify: no model attribute describes this unit's repurposed 3-bit field, so
# it stays pinned to the observed values alone.
GRSETDAC_MODEL_AUTHORIZED = frozenset(
    {"operationMode", "windSpeed", "windDirectionHorizontal", "windDirectionVertical"}
)

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
# The flag word: fresh air, humidification, the cleaning modes, the display light and the
# self-clean cycle, one bit each. Word 5 of the control block on this family.
_FLAG_WORD = 5
_SELF_CLEAN_BIT = 4
_OFF_INDOOR_TEMP = 104   # indoorTemperature = byte / 2  (the /2 == the model's 0.5° step)
_OFF_OUTDOOR_TEMP = 106  # outdoorTemperature = byte - 64  (correlated across 3 states, 2 distinct pts)
# How far past the indoor reading the cumulative total's low word sits. The published map puts the
# two ten words apart, and this family is that map at a fixed displacement -- checked field for
# field against a real report, where the displaced map reproduces the decode below on every field
# the two share. On both known control-word counts it lands on the report's final two words.
_ENERGY_WORDS_PAST_SENSORS = 10


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
    # Byte offset of the LOW word of the 32-bit cumulative watt-hour total. The attribute's
    # significance runs backwards from there, so the reading spans this word and the one before it,
    # i.e. the last two words of the report. ``None`` where the report is too short to hold it.
    energy: int | None = None

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

        The cumulative total sits ten words past the sensor block by the same arithmetic, which on
        both models is the last two words of the report (125 B -> 120..123, 127 B -> 122..125).
        """
        indoor = _OFF_ATTRS + 2 * words
        return cls(
            words=words, indoor_temp=indoor, outdoor_temp=indoor + 2, verified=verified,
            energy=indoor + 2 * _ENERGY_WORDS_PAST_SENSORS,
        )


STATUS_LAYOUTS: dict[int, StatusLayout] = {
    # typeId AAC1UKZ01 (HSU-24VRRA03TF): 6 control words, sensor block from byte 104.
    127: StatusLayout(words=6, indoor_temp=_OFF_INDOOR_TEMP, outdoor_temp=_OFF_OUTDOOR_TEMP,
                      energy=_OFF_INDOOR_TEMP + 2 * _ENERGY_WORDS_PAST_SENSORS),
    # deviceType 0201201d: the report carries 2 attribute bytes fewer — 5 control words — so every
    # sensor offset after the word block shifts by -2. Verified on a live unit: every decoded field
    # agreed with the cloud digital-model shadow read in the same second (targetTemperature,
    # operationMode, windSpeed, onOffStatus, indoorTemperature, screenDisplayStatus,
    # windDirectionVertical), and a grSetDAC op built from the 5-word baseline was ACCEPTED — the AC
    # echoed the new targetTemperature on the op's own connection and preserved every other attribute.
    125: StatusLayout(words=5, indoor_temp=102, outdoor_temp=104,
                      energy=102 + 2 * _ENERGY_WORDS_PAST_SENSORS),
}


# Bytes that follow the control-word block: the read-only sensor region plus the EPP checksum. This
# is 23 on BOTH confirmed models (127 = 92 + 2*6 + 23, 125 = 92 + 2*5 + 23), which is what makes the
# word count derivable from the report length alone.
_SENSOR_TAIL_LEN = 23
_LAYOUT_BASE_LEN = _OFF_ATTRS + _SENSOR_TAIL_LEN   # 115; report length = base + 2*words
_MAX_WORDS = 12   # sanity bound: no observed grSetDAC block exceeds this

# Plausibility band used to veto a DERIVED layout and to reject sentinel sensor readings. A unit that
# lacks a sensor reports 0 for it, which would otherwise decode to a confident -64.0 C outdoor value.
# The only bound a CONFIRMED field gets: physically impossible, not merely unusual.
#
# This started as a comfort band (-40..70) doing two jobs -- vetoing a candidate offset during
# layout derivation, and rejecting an absent sensor's zero. The first job now lives where it
# belongs, in `wire_models` (`_PLAUSIBLE_INDOOR_C` and friends), where the question really is "does
# this offset look right". The second is done by the sentinels below.
#
# What was left did neither, and did harm: it silently discarded a compressor discharge line at
# 80 C -- a correct reading from a unit pulling 78 Hz -- because 80 exceeded a range chosen for
# room air. Worse than the lost reading is the shape of the failure: a masked decode looks exactly
# like absent hardware, so it gets ignored, whereas an implausible *number* gets reported and
# fixed. A narrow band on a confirmed field buys nothing and hides the bugs worth finding.
_PLAUSIBLE_TEMP_C = (-70.0, 150.0)


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
    data: bytes,
    profile=None,
    digital_model: dict | None = None,
    *,
    uplus_id: str | None = None,
    order: Sequence[str] | None = None,
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
        # No registered family claims this report. The appliance still names itself, and the
        # published models sharing that name's leading characters are its nearest relatives -- each
        # naming a whole-word offset its report may use. Try them and keep whichever one the report
        # agrees with; relatives normally disagree by exactly one offset, so this is the step that
        # decides between them. Anything that fails falls through to the partial decode below,
        # exactly as before.
        if wm is None and (
            decoded := decode_related(data, uplus_id, profile, order=order)
        ) is not None:
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
    # The unit states its own heat capability: bit 7 of the byte after the outdoor reading is set on
    # a cooling-only unit. Worth having because it needs no model of any kind -- it is the one signal
    # that distinguishes a reverse-cycle unit from a cooling-only one without asking anything else.
    out["heat_capable"] = not (data[layout.outdoor_temp + 1] >> 7) & 1
    # The word after the sensors carries the fault code and who made the last change. `error_code`
    # is a single code (0 = healthy) and is a different view of the fault frame, not a duplicate:
    # it names one fault where the frame carries the full set.
    # Whether a self-clean cycle is running. The unit frosts the coil with the indoor fan stopped,
    # then stops the compressor and lets the ice melt off; it runs to completion and ignores a second
    # press. Read-only -- see the note beside GRSETDAC_FIELDS.
    if layout.words >= _FLAG_WORD:
        flag_word = int.from_bytes(
            data[_OFF_ATTRS + (_FLAG_WORD - 1) * 2:_OFF_ATTRS + _FLAG_WORD * 2], "big"
        )
        out["self_cleaning"] = bool(flag_word >> _SELF_CLEAN_BIT & 1)
    # The cumulative watt-hour total, where the unit keeps one. Most of this family carries the
    # register and never populates it, and a permanent 0 kWh in someone's Energy dashboard is worse
    # than no sensor at all -- so zero is reported as ABSENT rather than as a total of nothing.
    # 32 bits, and its significance runs backwards from its own word, so it spans the two words
    # ending at `layout.energy`.
    if layout.energy is not None and len(data) >= layout.energy + 2:
        total = int.from_bytes(data[layout.energy - 2:layout.energy + 2], "big")
        if total:
            out["energy_wh"] = total
    out["error_code"] = data[layout.outdoor_temp + 2]
    out["last_changed_by"] = OPERATION_SOURCE.get(data[layout.outdoor_temp + 3] & 0x03)
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
# Audited in full against the published telemetry layout of the nearest relative model: all ten
# offsets below are stated there, nine agree by name, and the actuator word agrees on all six of its
# two-bit fields. The exception is noted at _EXT_OFF_DISCHARGE.
_EXT_OFF_POWER = 126          # BE16, watts -- a register the unit keeps, not a figure we compute
_EXT_OFF_COIL = 128           # indoor coil temp, x0.5 - 20
_EXT_OFF_DISCHARGE = 129      # compressor discharge line, -64. See the note above the parser.
                              # The published layout names this position for outdoor outlet air. It
                              # reads ~69 C while the unit's own outdoor sensor reads ~28 C, which is
                              # ordinary for a compressor discharge line and impossible for outdoor
                              # air. Position agreed, name not: the reading decides.
_EXT_OFF_OUTDOOR_COIL = 130      # outdoor coil temp, -64
_EXT_OFF_OUTDOOR_IN_AIR = 131    # outdoor unit air-inlet temp, -64
_EXT_OFF_OUTDOOR_DEFROST = 132   # outdoor defrost sensor, -64
_EXT_OFF_FREQ = 133           # compressor frequency, Hz
_EXT_OFF_CURRENT = 134        # BE16, amps x 10
_EXT_OFF_ACTUATORS = 136      # BE16 of six 2-bit actuator states, see _EXT_ACTUATORS
_EXT_OFF_EXPANSION_VALVE = 138   # BE16, electronic expansion valve opening

# The actuator word packs six two-bit states, each **0 = off, 1 = on, 2 = not reported**. That third
# value is the important one: a unit says "I do not have this reading" in-band rather than by leaving
# the field out, so a state has to be read as three-valued and not as a flag.
#
# Reading it as a flag is wrong in the direction that matters. `bool(value)` turns "not reported" into
# "running" and pins the sensor on for as long as the unit keeps saying it cannot tell you -- the same
# shape of defect as testing a byte that packs eight attributes for truthiness. The reference units
# here report 2 for their reversing valve and outdoor fan whether cooling hard or idle at 0 W, which
# is what first showed the value could not be a flag.
#
# So: 1 is on, 0 is off, and anything else omits the key entirely, leaving it unknown rather than
# inventing a state. Same rule as a temperature probe the unit does not carry.
_EXT_ACTUATOR_STATES: tuple[tuple[str, int], ...] = (
    ("compressor_running", 0),
    ("fan_running", 2),                  # indoor fan
    ("four_way_valve_status", 4),
    ("indoor_electric_heating_status", 6),
    ("outdoor_fan_status", 8),
    ("defrost_status", 10),
)
_ACTUATOR_ON = 1
_ACTUATOR_OFF = 0
# A unit that is not reporting simply sends 0. Anything above these is not a real domestic reading and
# is treated as "no data" rather than published into long-term statistics.
_MAX_PLAUSIBLE_W = 20_000
_MAX_PLAUSIBLE_A = 100.0


def parse_extended_status(data: bytes) -> dict[str, Any]:
    """Decode the running power / compressor figures from an extended-status report.

    ⚠️ One name here deliberately departs from the published map. The map calls the reading at byte
    129 the outdoor unit's *air-outlet* temperature, and its position is not in doubt -- five
    neighbouring fields on both sides of it land exactly where the same offset puts them. But a live
    unit reports **69 °C there while its own outdoor sensor reads 28 °C**, with the compressor at
    52 Hz drawing 1020 W. Air leaving a condenser runs some ten to twenty degrees above ambient, not
    forty; a discharge line at that frequency runs exactly this hot. The same section of the map
    also gives the expansion valve's opening the unit "Hz", so its labels are not authoritative
    where they conflict with the reading. Position from the map, name from the thermometer.

    Returns ``{}`` for anything that is not the confirmed extended-report layout, so a device whose
    extended report differs simply yields no telemetry rather than fabricated numbers. Only the
    "classic" family's 141-byte report is confirmed; other families append their engineering block at
    different offsets and need their own entry before this can decode them.

    Keys (each temperature omitted when the unit does not carry that probe):
      ``power_w``, ``compressor_current_a``, ``compressor_frequency_hz``,
      ``expansion_valve_opening``, the refrigeration-circuit temperatures ``coil_temperature``,
      ``discharge_temperature``, ``outdoor_coil_temperature``, ``outdoor_in_air_temperature``
      and ``outdoor_defrost_temperature``, and the actuator states named in
      :data:`_EXT_ACTUATOR_FLAGS` and :data:`_EXT_ACTUATOR_CODES`.

    Only some of these are surfaced as entities; the rest are decoded because the published map
    states where they are, and they reach a diagnostics download rather than a dashboard.
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
    # -20/-64 C reading in a user's statistics. Most units carry only some of these probes.
    for key, off, scale, offset in (
        ("coil_temperature", _EXT_OFF_COIL, 0.5, -20.0),
        ("discharge_temperature", _EXT_OFF_DISCHARGE, 1.0, -64.0),
        ("outdoor_coil_temperature", _EXT_OFF_OUTDOOR_COIL, 1.0, -64.0),
        ("outdoor_in_air_temperature", _EXT_OFF_OUTDOOR_IN_AIR, 1.0, -64.0),
        ("outdoor_defrost_temperature", _EXT_OFF_OUTDOOR_DEFROST, 1.0, -64.0),
    ):
        value = _sensor_temp(data[off], scale=scale, offset=offset)
        if value is not None:
            out[key] = value
    actuators = int.from_bytes(data[_EXT_OFF_ACTUATORS:_EXT_OFF_ACTUATORS + 2], "big")
    for key, bit in _EXT_ACTUATOR_STATES:
        state = (actuators >> bit) & 0x03
        if state in (_ACTUATOR_ON, _ACTUATOR_OFF):
            out[key] = state == _ACTUATOR_ON
    out["expansion_valve_opening"] = int.from_bytes(
        data[_EXT_OFF_EXPANSION_VALVE:_EXT_OFF_EXPANSION_VALVE + 2], "big"
    )
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
        s.sendall(encode_message(INFO_HELLO_DONE, 2, b"",
                                 type_byte=negotiated_type_byte(resp, requested=TYPE_BYTE[pro_ver]),
                                 session=resp.session))
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
                            extra_request: bytes | None = None,
    expect_localkey_version: int | None = None,
) -> list[bytes]:
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
        check_hello_resp(resp, expect_localkey_version)
        speak = negotiated_type_byte(resp, requested=TYPE_BYTE[pro_ver])
        writer.write(encode_message(INFO_HELLO_DONE, 2, b"", type_byte=speak, session=resp.session))
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
                        type_byte=speak, flag=FLAG_BIZ_ENCRYPTED, session=resp.session))
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


def is_control_baseline(blob: bytes, uplus_id: str | None = None) -> bool:
    """Whether ``blob`` is a full-status report whose control-word block can seed a group-set.

    The classic family answers from the confirmed :data:`STATUS_LAYOUTS` table. Every other family
    answers from its own wire model, which is the part this used to miss: the gate was written
    before the registry existed and stayed table-only, so a 209-byte report was not recognised as a
    seed and control on those families ALWAYS fell back to the caller's cached blob -- the stale
    baseline the single-session read-modify-write exists to avoid. A wire model's ``decode``
    returning a value is the same guarantee the table gives: it only does so when the family's own
    readings are actually present, so the word block is whole.

    ``writable`` is required as well, since a family with no confirmed group-set has nothing to seed.
    """
    if status_layout(blob) is not None:
        return True
    wm = select_wire_model(len(blob), uplus_id)
    return wm is not None and wm.writable and wm.decode(blob) is not None


async def _read_pushed_status(reader, leftover: bytes, local_key: str, timeout: float,
                              uplus_id: str | None = None) -> bytes | None:
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
                # A full-status report of a family with a confirmed word block — so the group-set
                # baseline is complete. A blob of any other size (e.g. a small ack that happens to
                # decrypt) must not seed a truncated/malformed op frame.
                if is_control_baseline(blob, uplus_id):
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


def session_sequence_base(done: Message, local_key: str) -> int:
    """The op sequence base the AC assigns in HELLO_DONE_RESP. The op MUST use it as ``biz_sn``, or
    the appliance ignores the command.

    ⚠️ **The payload is biz-encrypted even though the header flag says it is not.** Real appliances
    send this message with ``flag=0`` and an encrypted 53-byte body; the flag is simply not set on
    it. Deciding whether to decrypt by reading the flag -- which sounds obviously right, and which
    every other message on this connection does honour -- takes four bytes of ciphertext as the
    sequence number instead. The appliance then discards the command **silently**: no error, no
    reply, the setting simply never changes. Shipped once, caught on hardware within the hour, and
    the reason this decrypts unconditionally.

    ⚠️ Raises ``RuntimeError``, deliberately not ``ValueError``. The layer above maps ``ValueError``
    to "does not accept that setting", which was said to somebody whose appliance never received
    the setting. A handshake that cannot be read is a session problem and has to read as one.
    """
    try:
        _, body = biz_decrypt(done.payload, local_key)
    except ValueError as err:
        _LOGGER.debug(
            "HELLO_DONE_RESP would not decrypt (flag=%d, %d bytes): %s -- first bytes %s",
            done.flag, len(done.payload), err, done.payload[:48].hex(),
        )
        raise RuntimeError(
            f"the appliance's handshake reply could not be read ({err}), so the command was "
            "never sent"
        ) from err
    if len(body) < 4:
        _LOGGER.debug("HELLO_DONE_RESP body is %d bytes, too short for a sequence base", len(body))
        raise RuntimeError(
            "the appliance's handshake reply carried no session sequence number, so the command "
            "was never sent"
        )
    return int.from_bytes(body[:4], "big")


async def async_send_op(ip: str, device_id: str, local_key: str, epp_frame: bytes | None = None, *,
                        counter: int, biz_sn: int | None = None, uss_sn: int = 0,
                        info_type: int = 0x64, pro_ver: int = 2, timeout: float = 4.0,
                        collect: bool = True,
                        build_frame: Callable[[bytes | None], bytes] | None = None,
    expect_localkey_version: int | None = None,
    uplus_id: str | None = None,
) -> list[bytes]:
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
    ``build_frame`` must yield a frame. Pass ``uplus_id`` so a non-classic family's push is recognised
    as a baseline (:func:`is_control_baseline`); without it only the classic lengths are, and those
    families silently fall back to whatever the caller cached."""
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
        check_hello_resp(resp, expect_localkey_version)
        speak = negotiated_type_byte(resp, requested=TYPE_BYTE[pro_ver])
        writer.write(encode_message(INFO_HELLO_DONE, 2, b"", type_byte=speak, session=resp.session))
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
        if biz_sn is None:
            biz_sn = session_sequence_base(done_msg, local_key)
        if build_frame is not None:
            # Read-modify-write in ONE session: the AC pushes its current status right after the
            # handshake (like a read), so seed the group-set from that fresh in-session baseline —
            # no second connection. ``build_frame`` gets None if no status arrived (caller falls back).
            baseline = await _read_pushed_status(reader, hbuf[done_end:], local_key, timeout,
                                                 uplus_id)
            epp_frame = build_frame(baseline)
        if epp_frame is None:
            raise RuntimeError("async_send_op: neither epp_frame nor build_frame produced a frame")
        envelope = build_cae_op_request(epp_frame, device_id, counter)
        ciphertext = biz_encrypt(biz_sn, envelope, local_key)
        writer.write(encode_message(info_type, uss_sn, ciphertext, type_byte=speak,
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
