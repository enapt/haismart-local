"""UDISCOVERY_UWT — Haier's key-free LAN discovery protocol on UDP ``:7083``.

A second local protocol alongside the uSS control path in :mod:`uss`, and the only one that needs
**no localKey, no account and no cloud**. One UDP round trip answers three questions:

* which Haier appliances are on this LAN, and at which IP (these modules do **not** answer mDNS, and
  they move on DHCP, so this is the reliable way to find them);
* what each one's ``uPlusId`` is — the wire-model key that otherwise only comes from the cloud device
  list, so an offline install can still pick the right report layout;
* whether each one currently has a working connection to Haier's cloud.

That last field is the reason this module exists: it lets a user who has firewalled their AC verify
the block actually holds, locally, without asking Haier anything.

Frame layout (21-byte header, both directions)::

    [0x00] 5  magic "Haier"        -- validated by the device; wrong magic gets silence
    [0x05] 4  BE32 command
    [0x09] 2  BE16 flags           -- device sends 0x020a; ignored in requests
    [0x0b] 6  zeros
    [0x11] 4  BE32 payload length  -- NOT validated by the device
    [0x15] n  payload

The device answers ``CMD_SEARCH`` with a ``CMD_DEVICE_INFO`` reply carrying fixed identity fields
plus a counted TLV area. Cloud state is TLV type ``0x03``: ``1000`` = connected, anything else = not.
These are module-firmware values with no published documentation, and only three have ever been
observed (:data:`CLOUD_STATES`) — so treat only ``1000`` as a positive and keep the raw value for
diagnostics, because an unrecognised code is not a known one.

Timing: losing the cloud shows up in about **2 minutes** (``1010``), settling to ``1006`` a further
**~2 minutes** later; regaining it takes about **10 seconds**, during which the module goes briefly
silent rather than reporting an intermediate code. Polling faster than once a minute buys nothing.
"""
from __future__ import annotations

import asyncio
import socket
import struct
from dataclasses import dataclass

PORT = 7083
MAGIC = b"Haier"
HEADER_LEN = 0x15

# The only request THIS CLIENT sends. Two other codes in the family were probed and got no reply,
# and that negative is now BOUNDED (2026-09-10): the payload shape matters. `0x6853` is a
# transparent-transmission channel whose payload is `[kind:1][...]`, and the module implements
# **kind 7** in BOTH directions -- it builds such datagrams and parses them (receiver 0x9b01e6fe,
# sender 0x9b01e844). The receiver is CALLED BY the search handler itself, at 0x9b02ddb8, BEFORE
# its 0x6915 compare -- so this port serves two commands, not one.
# The vendor's app sends **kind 1** = "list the unprovisioned devices you can see" -- the LAN face
# of Haier's device-to-device 改密回连. `0x6851` (diagnose) still looks genuinely absent: zero code
# sites against one each for 0x6915/0x684D. Neither is implemented here because neither is needed
# to find an appliance -- not because the module ignores them.
# Detail: captures/module-firmware/analysis/FW_UDISCOVERY_BIZ_0x6853.md
CMD_SEARCH = 0x6915
CMD_DEVICE_INFO = 0x684D

# Both literals are checked by the device — zeroing either gets silence. The 16-byte client
# identifier ahead of them is not checked, so it is sent as zeros.
CLIENT_VERSION = b"2.0.0"
CLIENT_TAG = b"UDISCOVERY_SDK"

# The module emits at most four, in this order (builder `0x9b02d5fc`):
#   0x01  len 0x20  the deviceId               -- always
#   0x03  len 4     cloud state, htonl'd       -- only when the value is non-zero
#   0x04  len 1     the literal 5              -- only when an identity flag is set
#   0x05  len 1     the literal 2              -- same condition
# Our units emit exactly the first two, which the flags word at 0x09 (`0x020a`) independently
# predicts: its 0x100 bit is clear, and that bit is the very condition gating TLVs 4 and 5.
TLV_DEVICE_ID = 0x01
TLV_CLOUD_STATE = 0x03

#: Cloud-state TLV value meaning "the module has a live connection to Haier's cloud".
CLOUD_STATE_CONNECTED = 1000

#: The confirmed values, observed across a full disconnect/reconnect cycle sampled at 1 Hz. Losing
#: the cloud is not a single step: the module reports ``1010`` for a couple of minutes before
#: settling on ``1006``. Anything absent from this map is unknown and must still count as "not
#: connected" -- these three are what has been SEEN.
#:
#: ★ But the namespace now has a RULE, read from the firmware (2026-09-10,
#: ``captures/module-firmware/analysis/FW_LAN_SET_GATEWAY_26013.md`` §12.6). The producer adds a
#: constant to an internal code before reporting it, and WHICH constant is a flag:
#:
#:     if (code in 0..999):  code += (psk_len == 0) ? 4000 : 1000
#:     else:                 report code unchanged
#:
#: where ``psk_len`` is the module's stored pre-shared-key length (``config+0x3CB``, capped at 64).
#: ⇒ a ``1xxx`` value means the module HOLDS a PSK; a ``4xxx`` value means its PSK store is EMPTY.
#: ⇒ the owner's two units report ``1006``, so both hold a non-empty PSK -- a fact that was
#: previously unknown and is readable with no key, no account and no session.
#: ⚠️ The decode is read from instructions; the attribution of that field to THIS TLV is a strong
#: inference, not proven -- every value ever observed lies in the 1000-range, which is what makes it
#: strong, and a unit reporting 4xxx would confirm it. Treating unrecognised values as
#: "not connected" (below) is correct either way, so nothing here changes behaviour.
CLOUD_STATES = {
    1000: "connected",
    1010: "retrying",      # connection lost, module still trying
    1006: "disconnected",  # settled; held indefinitely while cut off
}

# Fixed field offsets in the reply, from the start of the datagram.
_OFF_DEVICE_ID = 0x15
_OFF_UPLUS_ID = 0x25
# ⚠️⚠️ NOT ACTUALLY A BE32 COUNT -- corrected 2026-09-10 by reading the module's own reply builder
# (`0x9b02d5fc`; `FW_LAN_SET_GATEWAY_26013.md` §12.7). Bytes 0x45..0x48 are THREE separate fields,
# written by different arms of a block the module skips entirely when its bind-window latch is 0:
#     0x45  u16   0, or htons(x) in one mode
#     0x47  byte  0, or [cfg+0x555] in two other modes
#     0x48  byte  the literal 2, when an internal device-type byte == 3
# Reading a BE32 here therefore yields a HUGE number on a unit in those modes. We keep doing it --
# and it is safe -- only because `_walk_tlvs` caps at min(count, 32) and stops on kind == 0. Both
# guards predate this finding; either alone makes the mis-read harmless. The comment is corrected,
# the code deliberately is not.
# ⛔ [U] whether 0x48 is semantically "the count": it is a literal, not computed from how many TLVs
# get emitted, so its agreement with the two our units send may be structural or coincidence.
_OFF_TLV_COUNT = 0x45
# ✅ Every offset in this layout was confirmed against the module's builder on 2026-09-10:
# 0x25 uPlusId, 0x49 TLV area, 0xE5 IP, 0xF5 port (htons(0xdde0) = 56800), 0xFD SDK, 0x105/0x10D
# firmware, 0x115 protocol tag. ⓘ One field we do NOT read: a htons(0x600) at 0x103.
_OFF_TLV_AREA = 0x49
_OFF_IP = 0xE5
_OFF_PORT = 0xF5
_OFF_SDK_VERSION = 0xFD
_OFF_FIRMWARE = 0x105
# The tail nobody had read. Our appliances put ``UDISCOVERY_UWT`` here, null-padded to the end of
# the datagram. The library carries THREE local protocol adapters -- `adapter_uss_pro` (the one
# implemented here), `adapter_local_dev_user_uwt` and `adapter_local_dev_user_coap` -- so a name
# announced by the appliance is worth keeping even though it does not, on its own, say which one
# applies: ours announce UWT and speak uss_pro regardless. Recorded so that an appliance announcing
# something else is visible rather than invisible.
_OFF_PROTOCOL_TAG = 0x115
_MIN_REPLY = _OFF_TLV_AREA  # everything past the TLV area is optional (other families may differ)


@dataclass(frozen=True)
class DeviceInfo:
    """One appliance's answer to a UDISCOVERY search."""

    device_id: str
    """The module's MAC without separators — the same identifier the uSS handshake uses."""
    host: str
    """The IP the device reports for itself (may differ from the address that answered)."""
    uplus_id: str = ""
    """64-digit model identifier; matches the cloud device list's ``wifiType`` byte for byte."""
    port: int = 0
    """The uSS control port to use for this device (56800 on every unit seen so far)."""
    sdk_version: str = ""
    firmware: tuple[str, ...] = ()
    cloud_state: int | None = None
    """Raw TLV value; ``None`` when the device did not report one."""
    protocol_tag: str = ""
    """The protocol name in the reply's tail (``UDISCOVERY_UWT`` on every appliance seen).

    ⚠️ NOT an adapter selector on the evidence available: appliances that announce it are driven
    with ``adapter_uss_pro`` successfully. Carried because the library has three adapters and this
    is the only place an appliance names a protocol at all."""

    @property
    def cloud_state_name(self) -> str | None:
        """A label for :attr:`cloud_state`, or ``None`` for a value never observed."""
        if self.cloud_state is None:
            return None
        return CLOUD_STATES.get(self.cloud_state)

    @property
    def cloud_connected(self) -> bool | None:
        """Whether the device can currently reach Haier's cloud, or ``None`` if it didn't say.

        Only :data:`CLOUD_STATE_CONNECTED` counts as connected: the rest of the code space is
        undocumented, so an unknown value must not be reported as "online".
        """
        if self.cloud_state is None:
            return None
        return self.cloud_state == CLOUD_STATE_CONNECTED


def _encode(cmd: int, payload: bytes) -> bytes:
    return (
        MAGIC
        + struct.pack(">I", cmd)
        + b"\x00" * 8
        + struct.pack(">I", len(payload))
        + payload
    )


def build_query() -> bytes:
    """The search datagram. Payload is 56 bytes: 16 unused, then the two required literals."""
    payload = bytearray(56)
    payload[0x10 : 0x10 + len(CLIENT_VERSION)] = CLIENT_VERSION
    payload[0x18 : 0x18 + len(CLIENT_TAG)] = CLIENT_TAG
    return _encode(CMD_SEARCH, bytes(payload))


def _text(data: bytes) -> str:
    return data.split(b"\x00")[0].decode("ascii", "replace").strip()


def _walk_tlvs(data: bytes) -> dict[int, bytes]:
    """Records in the counted TLV area: ``type(1) | length(1) | value``.

    Walked by type rather than read at fixed offsets, because the area is a fixed-size region whose
    populated length varies (a gateway with sub-devices fills more of it than a lone AC).
    """
    out: dict[int, bytes] = {}
    if len(data) < _OFF_TLV_AREA:
        return out
    count = struct.unpack_from(">I", data, _OFF_TLV_COUNT)[0]
    pos = _OFF_TLV_AREA
    for _ in range(min(count, 32)):  # bounded: the field is attacker-adjacent, the area is not huge
        if pos + 2 > len(data):
            break
        kind, length = data[pos], data[pos + 1]
        if kind == 0:
            break
        value = data[pos + 2 : pos + 2 + length]
        if len(value) < length:
            break
        out.setdefault(kind, value)
        pos += 2 + length
    return out


def parse_reply(data: bytes) -> DeviceInfo | None:
    """Decode a device-info reply, or ``None`` if this datagram isn't one.

    Everything past the TLV area is treated as optional so an unfamiliar appliance still yields its
    identity rather than nothing.
    """
    if len(data) < _MIN_REPLY or not data.startswith(MAGIC):
        return None
    if struct.unpack_from(">I", data, 5)[0] != CMD_DEVICE_INFO:
        return None

    tlvs = _walk_tlvs(data)
    cloud_state: int | None = None
    if (raw := tlvs.get(TLV_CLOUD_STATE)) is not None and len(raw) >= 4:
        cloud_state = struct.unpack_from(">I", raw, 0)[0]

    device_id = _text(data[_OFF_DEVICE_ID:_OFF_UPLUS_ID])
    if not device_id and (raw := tlvs.get(TLV_DEVICE_ID)) is not None:
        device_id = _text(raw)
    if not device_id:
        return None

    def field(start: int, end: int) -> str:
        return _text(data[start:end]) if len(data) >= end else ""

    firmware = tuple(
        fw
        for fw in (
            field(_OFF_FIRMWARE, _OFF_FIRMWARE + 8),
            field(_OFF_FIRMWARE + 8, _OFF_FIRMWARE + 16),
        )
        if fw
    )
    port = (
        struct.unpack_from(">H", data, _OFF_PORT)[0]
        if len(data) >= _OFF_PORT + 2
        else 0
    )
    # The uPlusId is BCD-packed binary, not text: each byte is two digits. Hex-encoding it
    # reproduces the cloud device list's `wifiType` string exactly.
    return DeviceInfo(
        device_id=device_id,
        host=field(_OFF_IP, _OFF_PORT),
        uplus_id=data[_OFF_UPLUS_ID:_OFF_TLV_COUNT].hex(),
        port=port,
        sdk_version=field(_OFF_SDK_VERSION, _OFF_SDK_VERSION + 5),
        protocol_tag=field(_OFF_PROTOCOL_TAG, _OFF_PROTOCOL_TAG + 32),
        firmware=firmware,
        cloud_state=cloud_state,
    )


def query(host: str, *, timeout: float = 2.0) -> DeviceInfo | None:
    """Ask one appliance for its device info. READ-ONLY; returns ``None`` on no answer.

    Unicast is answered from any source port, so this needs no privileged or fixed local port.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(build_query(), (host, PORT))
        while True:
            try:
                data, _ = sock.recvfrom(4096)
            except TimeoutError:
                return None
            if (info := parse_reply(data)) is not None:
                return info
    finally:
        sock.close()


def discover(
    *, broadcast: str = "255.255.255.255", timeout: float = 3.0
) -> list[DeviceInfo]:
    """Broadcast a search and collect every appliance that answers within ``timeout``.

    .. important::
       The local socket **must** be bound to :data:`PORT`. Broadcast queries sent from an ephemeral
       source port are silently ignored by the devices (unicast ones are not) — the single
       non-obvious requirement of the protocol. If some other process holds the port, fall back to
       :func:`query` per candidate address.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    found: dict[str, DeviceInfo] = {}
    try:
        sock.bind(("", PORT))
        sock.settimeout(timeout)
        sock.sendto(build_query(), (broadcast, PORT))
        while True:
            try:
                data, _ = sock.recvfrom(4096)
            except TimeoutError:
                break
            if (info := parse_reply(data)) is not None:
                found.setdefault(info.device_id, info)
    finally:
        sock.close()
    return list(found.values())


class _QueryProtocol(asyncio.DatagramProtocol):
    def __init__(self, future: asyncio.Future[DeviceInfo]) -> None:
        self._future = future

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if self._future.done():
            return
        if (info := parse_reply(data)) is not None:
            self._future.set_result(info)

    def error_received(self, exc: Exception) -> None:
        if not self._future.done():
            self._future.set_exception(exc)


async def async_query(host: str, *, timeout: float = 2.0) -> DeviceInfo | None:
    """Async :func:`query`, for event-loop hosts. READ-ONLY; ``None`` on no answer."""
    loop = asyncio.get_running_loop()
    future: asyncio.Future[DeviceInfo] = loop.create_future()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: _QueryProtocol(future), remote_addr=(host, PORT)
    )
    try:
        transport.sendto(build_query())
        return await asyncio.wait_for(future, timeout)
    except TimeoutError:
        return None
    finally:
        transport.close()
