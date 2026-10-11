"""Session-loop robustness for the uSS transport: framing faults, deadlines and coalesced bytes.

Every exchange here is a scripted in-memory stream -- no socket, no hardware. Keys and deviceIds are
the suite's illustrative placeholders.
"""
import asyncio
import time

import pytest

from haismart_hrdp import uss

DEV = "A1B2C3D4E5F6"
LOCALKEY = "0123456789abcdef0123456789abcdef"  # illustrative — not a real device key
HELLO_RESP_OK = bytes.fromhex("0000000100000004")
SESSION = 0x1234
STATUS = b"\x00\x00\x27\x15" + bytes(123)          # stands in for a pushed report; only decrypts
EXT_REPLY = b"\x00\x00\x27\x15" + b"\x7d" * 137     # stands in for the extended-status reply
EXTRA = uss.extended_status_epp_frame()

HELLO_RESP = uss.encode_message(uss.INFO_HELLO_RESP, 1, HELLO_RESP_OK, session=SESSION)


def done_resp(body: bytes = (547).to_bytes(4, "big")) -> bytes:
    return uss.encode_message(uss.INFO_HELLO_DONE_RESP, 2, uss.biz_encrypt(0, body, LOCALKEY),
                              session=SESSION)


def pushed(blob: bytes) -> bytes:
    return uss.encode_message(0x64, 3, uss.biz_encrypt(547, blob, LOCALKEY),
                              flag=uss.FLAG_BIZ_ENCRYPTED, session=SESSION)


class FakeWriter:
    """Records writes; ``on_write[n]`` runs when the n-th write (1-based) goes out."""

    def __init__(self, on_write=None):
        self.sent: list[bytes] = []
        self.on_write = on_write or {}

    def write(self, data: bytes) -> None:
        self.sent.append(data)
        if (hook := self.on_write.get(len(self.sent))) is not None:
            hook()

    async def drain(self): ...
    def close(self): ...
    async def wait_closed(self): ...


def connect(monkeypatch, reader, writer):
    async def fake_open(ip, port):
        return reader, writer
    monkeypatch.setattr(asyncio, "open_connection", fake_open)


# --- a declared length shorter than a header is a session fault, not a refused setting ----------

def test_message_complete_rejects_a_declared_length_below_the_header():
    bad = b"\x00\x00\xea\x61\x00\x04" + bytes(10)
    with pytest.raises(RuntimeError, match="malformed"):
        uss._message_complete(bad)


async def test_send_op_bad_handshake_length_is_runtime_error(monkeypatch):
    """`ValueError` here would reach the user as "does not accept that setting"."""
    reader = asyncio.StreamReader()
    reader.feed_data(b"\x00\x00\xea\x61\x00\x04" + bytes(10))
    connect(monkeypatch, reader, FakeWriter())
    with pytest.raises(RuntimeError, match="malformed"):
        await uss.async_send_op("192.0.2.10", DEV, LOCALKEY, b"\xff", counter=1, timeout=1.0)


# --- the HELLO_DONE_RESP wait has an overall deadline and a size cap -----------------------------

async def test_send_op_handshake_wait_has_an_overall_deadline(monkeypatch):
    """A peer that keeps trickling unrelated frames must not hold the handshake open forever."""
    reader = asyncio.StreamReader()
    reader.feed_data(HELLO_RESP)
    stray = uss.encode_message(0x64, 9, b"", session=SESSION)

    async def trickle():
        for _ in range(200):
            await asyncio.sleep(0.02)
            reader.feed_data(stray)

    task = asyncio.create_task(trickle())
    connect(monkeypatch, reader, FakeWriter())
    t0 = time.monotonic()
    try:
        with pytest.raises(TimeoutError):
            await uss.async_send_op("192.0.2.10", DEV, LOCALKEY, b"\xff", counter=1, timeout=0.3)
    finally:
        task.cancel()
    assert time.monotonic() - t0 < 1.5


async def test_send_op_handshake_wait_is_size_capped(monkeypatch):
    reader = asyncio.StreamReader()
    stray = uss.encode_message(0x64, 9, bytes(500), session=SESSION)
    reader.feed_data(HELLO_RESP + stray * 40)
    connect(monkeypatch, reader, FakeWriter())
    with pytest.raises(RuntimeError, match="too much"):
        await uss.async_send_op("192.0.2.10", DEV, LOCALKEY, b"\xff", counter=1, timeout=5.0)


# --- bytes coalesced after HELLO_RESP are kept -----------------------------------------------------

async def test_read_status_keeps_bytes_coalesced_after_hello_resp(monkeypatch):
    reader = asyncio.StreamReader()
    reader.feed_data(HELLO_RESP + done_resp() + pushed(STATUS))
    connect(monkeypatch, reader, FakeWriter())
    blobs = await uss.async_read_status("192.0.2.10", DEV, LOCALKEY, timeout=1.0)
    assert STATUS in blobs


def test_sync_read_status_keeps_bytes_coalesced_after_hello_resp(monkeypatch):
    class Sock:
        def __init__(self):
            self.chunks = [HELLO_RESP + done_resp() + pushed(STATUS)]

        def sendall(self, _d): ...
        def settimeout(self, _t): ...
        def close(self): ...

        def recv(self, _n):
            if not self.chunks:
                raise TimeoutError
            return self.chunks.pop(0)

    monkeypatch.setattr(uss.socket, "create_connection", lambda *a, **k: Sock())
    assert STATUS in uss.read_status("192.0.2.10", DEV, LOCALKEY, timeout=1.0)


# --- the extended-status query inside a read session ----------------------------------------------

async def test_extra_request_reply_gets_the_full_timeout(monkeypatch):
    """The reply to the extra query may take longer than the straggler window; it must still land."""
    reader = asyncio.StreamReader()
    reader.feed_data(HELLO_RESP)
    loop = asyncio.get_running_loop()
    writer = FakeWriter({
        2: lambda: reader.feed_data(done_resp() + pushed(STATUS)),
        3: lambda: loop.call_later(uss._COLLECT_IDLE + 0.4, reader.feed_data, pushed(EXT_REPLY)),
    })
    connect(monkeypatch, reader, writer)
    blobs = await uss.async_read_status("192.0.2.10", DEV, LOCALKEY, timeout=3.0,
                                        extra_request=EXTRA)
    assert STATUS in blobs and EXT_REPLY in blobs


async def test_extra_request_uses_the_first_four_body_bytes_as_sequence_base(monkeypatch):
    reader = asyncio.StreamReader()
    reader.feed_data(HELLO_RESP + done_resp((547).to_bytes(4, "big") + b"\x00\x01") + pushed(STATUS))
    writer = FakeWriter()
    connect(monkeypatch, reader, writer)
    await uss.async_read_status("192.0.2.10", DEV, LOCALKEY, timeout=0.5, extra_request=EXTRA)
    assert len(writer.sent) == 3
    extra = uss.decode_message(writer.sent[2])
    assert uss.biz_decrypt(extra.payload, LOCALKEY)[0] == 547


async def test_extra_request_is_skipped_when_the_sequence_base_is_missing(monkeypatch):
    """A body too short for a sequence base gives up on the extra query, not on the poll."""
    reader = asyncio.StreamReader()
    reader.feed_data(HELLO_RESP + done_resp(b"\x02\x23") + pushed(STATUS))
    writer = FakeWriter()
    connect(monkeypatch, reader, writer)
    blobs = await uss.async_read_status("192.0.2.10", DEV, LOCALKEY, timeout=0.5,
                                        extra_request=EXTRA)
    assert STATUS in blobs
    assert len(writer.sent) == 2   # hello + hello_done only: no query with a bogus sequence number


# --- the pushed-status wait decrypts each message once ---------------------------------------------

async def test_read_pushed_status_decrypts_each_message_once(monkeypatch):
    calls = []
    real = uss.biz_decrypt

    def counting(payload, key):
        calls.append(payload)
        return real(payload, key)

    monkeypatch.setattr(uss, "biz_decrypt", counting)
    reader = asyncio.StreamReader()
    ack = b"\x00" * 60                              # decrypts, but is no control baseline

    async def feed():
        for _ in range(3):
            await asyncio.sleep(0.02)
            reader.feed_data(pushed(ack))           # one message per read
        reader.feed_eof()

    task = asyncio.create_task(feed())
    assert await uss._read_pushed_status(reader, pushed(ack) * 2, LOCALKEY, 1.0) is None
    await task
    assert len(calls) == 5                          # 2 leftover + 3 read, each decrypted once
