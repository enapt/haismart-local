"""Tests for the MQTT-gateway localKey fetch. No network: the MQTT connection is faked.

Golden vectors are the real  live capture (both keys byte-matched the getLocalKey
and decrypted the live ACs)."""
import base64
import json

import pytest

from haismart_extractor.cloud import LocalKey
from haismart_extractor.gateway import (
    GATEWAY_AUTH_SALT,
    GatewayClient,
    GatewayCreds,
    GatewayError,
    MqttConnection,
    derive_client_id,
    derive_gateway_auth,
    derive_gateway_password,
    generate_username_body,
    get_localkey_via_gateway,
    localkey_request_payload,
    parse_localkey_response,
)

# --- test vectors (all values are placeholders; the shapes match the live wire format) ---
USDK_CLIENTID = "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4"  # a per-install uSDK CLIENTID; login() generates one
CLIENT_ID = "397a1e2e07cbf0391eaa95067dfba026"  # = derive_client_id(USDK_CLIENTID), pinned below
TOKEN = "2_exampletokenexampletoken00000"
UP_DEV = "ACB722DDEEFF"
UP_KEY = "ffeeddccbbaa99887766554433221100"
UP_VER = 13
# the Business/Up body shape the app publishes for (dev=UP_DEV, sn="1", flag=0)
GOLDEN_REQUEST = (
    '{"type":"devLocalkey",'
    '"data":"eyJzbiI6IjEiLCJkZXYiOiJBQ0I3MjJEREVFRkYiLCJmbGFnIjowfQ==",'
    '"tokens":["2_exampletokenexampletoken00000"]}'
)
# the exact Business/Down response for Upstairs v13
GOLDEN_RESPONSE = (
    '{"type":"devLocalkey",'
    '"data":"eyJzbiI6IjEiLCJlcnJObyI6MCwidmVycyI6MTMsImtleSI6ImZmZWVkZGNjYmJhYTk5ODg3NzY2NTU0NDMzMjIxMTAwIn0=",'
    '"tokens":["2_exampletokenexampletoken00000"]}'
)


def _make_response(sn: str, key: str, vers: int, err_no: int = 0) -> bytes:
    inner = json.dumps(
        {"sn": str(sn), "errNo": err_no, "vers": vers, "key": key}, separators=(",", ":")
    )
    outer = {"type": "devLocalkey", "data": base64.b64encode(inner.encode()).decode(), "tokens": []}
    return json.dumps(outer, separators=(",", ":")).encode()


class FakeMqtt(MqttConnection):
    """Records subscribe/publish; auto-answers each publish echoing the request's ``sn``."""

    def __init__(self, *, key=UP_KEY, vers=UP_VER, err_no=0, echo_sn=True, answer=True) -> None:
        self.key, self.vers, self.err_no = key, vers, err_no
        self.echo_sn, self.answer = echo_sn, answer
        self.subs: list[str] = []
        self.pubs: list[tuple[str, str]] = []
        self.closed = False
        self._queue: list[tuple[str, bytes]] = []

    def subscribe(self, topic: str) -> None:
        self.subs.append(topic)

    def publish(self, topic: str, payload: str) -> None:
        self.pubs.append((topic, payload))
        if not self.answer:
            return
        req_inner = json.loads(base64.b64decode(json.loads(payload)["data"]))
        sn = req_inner["sn"] if self.echo_sn else "999999"
        self._queue.append(
            ("Client/x/Business/Down", _make_response(sn, self.key, self.vers, self.err_no))
        )

    def poll(self, timeout: float) -> list[tuple[str, bytes]]:
        out, self._queue = self._queue, []
        return out

    def close(self) -> None:
        self.closed = True


def _creds() -> GatewayCreds:
    return GatewayCreds(client_id=CLIENT_ID, username="0172114171", password="deadbeef", access_token=TOKEN)


# --- credential derivation ---


def test_derive_client_id_matches_live() -> None:
    assert derive_client_id(USDK_CLIENTID) == CLIENT_ID


def test_derive_client_id_custom_package() -> None:
    import hashlib

    assert derive_client_id("ABC", "com.x") == hashlib.md5(b"ABC_com.x").hexdigest()


# --- CONNECT username/password derivation ---

# Golden vector: username body "72114171" (wire "0172114171") derives this password — a regression
# guard so the CONNECT-password derivation stays byte-stable.
GOLDEN_USERNAME_BODY = "72114171"
GOLDEN_PASSWORD = "43dc259405f8b4471e4f29d85c6e63ee"


def test_gateway_salt_is_haier_sdk() -> None:
    # the salt the gateway-auth derivation uses (NOT the sibling salt "haier_uplug")
    assert GATEWAY_AUTH_SALT == b"haier_sdk"


def test_derive_gateway_password_matches_live_capture() -> None:
    # reproduction of the gateway password
    assert derive_gateway_password(GOLDEN_USERNAME_BODY) == GOLDEN_PASSWORD


def test_derive_gateway_password_algorithm_explicit() -> None:
    # spell the algorithm out independently: AES-128-CBC/IV0, key=MD5(body), pt=BE16(len)+salt+zero-pad
    import hashlib

    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    salt = b"haier_sdk"
    block = len(salt).to_bytes(2, "big") + salt
    block += b"\x00" * (-len(block) % 16)
    assert block.hex() == "000968616965725f73646b0000000000"
    key = hashlib.md5(GOLDEN_USERNAME_BODY.encode()).digest()
    enc = Cipher(algorithms.AES(key), modes.CBC(b"\x00" * 16)).encryptor()
    assert (enc.update(block) + enc.finalize()).hex() == GOLDEN_PASSWORD


def test_derive_gateway_auth_pins_body() -> None:
    username, password = derive_gateway_auth(GOLDEN_USERNAME_BODY)
    assert username == "01" + GOLDEN_USERNAME_BODY  # "01" wire tag prepended
    assert password == GOLDEN_PASSWORD


def test_derive_gateway_auth_is_self_consistent() -> None:
    # a freshly generated pair must satisfy password == f(body) where body = username without "01"
    username, password = derive_gateway_auth()
    assert username.startswith("01") and len(username) == 10
    assert password == derive_gateway_password(username[2:])


def test_generate_username_body_shape() -> None:
    body = generate_username_body()
    assert len(body) == 8 and body.isdigit()


def test_gatewaycreds_derive_is_fully_derived() -> None:
    creds = GatewayCreds.derive(usdk_client_id=USDK_CLIENTID, access_token=TOKEN)
    assert creds.client_id == CLIENT_ID
    assert creds.access_token == TOKEN
    assert creds.username.startswith("01") and len(creds.username) == 10
    assert creds.password == derive_gateway_password(creds.username[2:])


def test_gatewaycreds_derive_pinned_body_matches_live() -> None:
    creds = GatewayCreds.derive(
        usdk_client_id=USDK_CLIENTID, access_token=TOKEN, username_body=GOLDEN_USERNAME_BODY
    )
    assert creds.username == "0172114171"
    assert creds.password == GOLDEN_PASSWORD


# --- request/response codec (golden) ---


def test_localkey_request_payload_is_byte_exact() -> None:
    assert localkey_request_payload(UP_DEV, TOKEN, sn=1, flag=0) == GOLDEN_REQUEST


def test_request_payload_inner_structure() -> None:
    body = json.loads(localkey_request_payload(UP_DEV, TOKEN, sn=7, flag=0))
    assert list(body) == ["type", "data", "tokens"]  # cJSON insertion order
    inner = json.loads(base64.b64decode(body["data"]))
    assert inner == {"sn": "7", "dev": UP_DEV, "flag": 0}  # sn STRING, flag NUMBER
    assert isinstance(inner["sn"], str) and isinstance(inner["flag"], int)


def test_parse_localkey_response_golden() -> None:
    inner = parse_localkey_response(GOLDEN_RESPONSE)
    assert inner == {"sn": "1", "errNo": 0, "vers": 13, "key": UP_KEY}


def test_parse_localkey_response_accepts_bytes() -> None:
    assert parse_localkey_response(GOLDEN_RESPONSE.encode())["key"] == UP_KEY


@pytest.mark.parametrize("junk", [b"not json", "{}", '{"type":"other","data":"x"}', b"\x00\x01"])
def test_parse_localkey_response_ignores_junk(junk) -> None:
    assert parse_localkey_response(junk) == {}


# --- client flow ---


def test_get_localkey_returns_key_and_version() -> None:
    fake = FakeMqtt()
    lk = GatewayClient(_creds(), connect=lambda c: fake).get_localkey(UP_DEV)
    assert lk == LocalKey(key=UP_KEY, version=UP_VER)
    assert fake.subs == [f"Client/{CLIENT_ID}/Business/Down"]
    assert fake.pubs[0][0] == f"Client/{CLIENT_ID}/Business/Up"
    assert fake.closed  # connection cleaned up


def test_get_localkey_publishes_correct_device() -> None:
    fake = FakeMqtt()
    GatewayClient(_creds(), connect=lambda c: fake).get_localkey(UP_DEV)
    inner = json.loads(base64.b64decode(json.loads(fake.pubs[0][1])["data"]))
    assert inner["dev"] == UP_DEV
    assert json.loads(fake.pubs[0][1])["tokens"] == [TOKEN]


def test_get_localkey_times_out_on_wrong_sn() -> None:
    fake = FakeMqtt(echo_sn=False)  # answers with a non-matching sn
    with pytest.raises(GatewayError, match="no localKey response"):
        GatewayClient(_creds(), connect=lambda c: fake).get_localkey(UP_DEV, timeout=0.2)
    assert fake.closed


def test_get_localkey_times_out_on_silence() -> None:
    fake = FakeMqtt(answer=False)
    with pytest.raises(GatewayError, match="no localKey response"):
        GatewayClient(_creds(), connect=lambda c: fake).get_localkey(UP_DEV, timeout=0.2)


def test_get_localkey_raises_on_errno() -> None:
    fake = FakeMqtt(err_no=5)
    with pytest.raises(GatewayError, match="errNo=5"):
        GatewayClient(_creds(), connect=lambda c: fake).get_localkey(UP_DEV, timeout=1.0)


def test_get_localkeys_multiple_devices() -> None:
    keys = {"ACB722AABBCC": "00112233445566778899aabbccddeeff", UP_DEV: UP_KEY}

    class MultiFake(FakeMqtt):
        def publish(self, topic, payload):
            self.pubs.append((topic, payload))
            req = json.loads(base64.b64decode(json.loads(payload)["data"]))
            self._queue.append(
                ("d", _make_response(req["sn"], keys[req["dev"]], 13))
            )

    fake = MultiFake()
    out = GatewayClient(_creds(), connect=lambda c: fake).get_localkeys(list(keys))
    assert {d: lk.key for d, lk in out.items()} == keys


def test_convenience_wrapper() -> None:
    fake = FakeMqtt()
    lk = get_localkey_via_gateway(_creds(), UP_DEV, connect=lambda c: fake)
    assert lk.key == UP_KEY


def test_creds_topic_helpers() -> None:
    c = _creds()
    assert c.pub_topic == f"Client/{CLIENT_ID}/Business/Up"
    assert c.sub_topic == f"Client/{CLIENT_ID}/Business/Down"


# --- regressions for the errNo/sn/deadline bugs -------------------------------

def _make_error_response(sn: str, err_no: int) -> bytes:
    """A REAL gateway error response: it carries errNo and NO key at all."""
    inner = json.dumps({"sn": str(sn), "errNo": err_no}, separators=(",", ":"))
    outer = {"type": "devLocalkey", "data": base64.b64encode(inner.encode()).decode(), "tokens": []}
    return json.dumps(outer, separators=(",", ":")).encode()


class KeylessErrorMqtt(FakeMqtt):
    """Answers every request with a keyless errNo response."""

    def __init__(self, err_no: int = 21016) -> None:
        super().__init__(answer=False)
        self.err_no_only = err_no

    def publish(self, topic: str, payload: str) -> None:
        self.pubs.append((topic, payload))
        sn = json.loads(base64.b64decode(json.loads(payload)["data"]))["sn"]
        self._queue.append(("Client/x/Business/Down", _make_error_response(sn, self.err_no_only)))


def test_get_localkey_surfaces_a_keyless_error_response() -> None:
    """The gateway's own reason must reach the caller.

    The errNo check used to sit INSIDE ``if inner.get("key")``, and a real error response has no key -
    so every genuine failure (expired token, device not bound, wrong terminal) fell through to a bare
    "no response within Ns" and the user went debugging TLS and firewalls. Every pre-existing fixture
    included a key, which is exactly why a passing suite never caught it.
    """
    conn = KeylessErrorMqtt(21016)
    with pytest.raises(GatewayError, match="errNo=21016"):
        GatewayClient(_creds(), connect=lambda _c: conn).get_localkey(UP_DEV, timeout=0.5)
    assert conn.closed is True          # the connection is still released on the error path


def test_get_localkeys_shares_one_deadline_and_never_reuses_an_sn() -> None:
    """Batch fetch must not cost N*timeout, and two devices must never collide on one sn.

    The sn used to be ``time_ms + len(out)`` where ``len(out)`` only advanced on SUCCESS, so devices
    requested in the same millisecond after a failure shared an sn - and a late reply for one could be
    stored against the other, leaving a device holding another's key (an unfixable stale-key loop).

    The deadline is asserted against an INJECTED clock, never a measurement of the wall clock. The
    earlier form timed the call and allowed ``0.3 * 2.5`` seconds, which was both weak (a per-device
    deadline costs 3x the timeout, so the bound only just separated pass from fail) and flaky -- one
    run on a host whose clock stepped reported a NEGATIVE duration. With the clock injected the
    assertion is exact: however many devices are asked for, the collection spans ONE timeout.
    """
    sns: list[str] = []

    class Recorder(FakeMqtt):
        def __init__(self) -> None:
            super().__init__(answer=False)

        def publish(self, topic: str, payload: str) -> None:
            sns.append(json.loads(base64.b64decode(json.loads(payload)["data"]))["sn"])

    reads: list[float] = []

    def fake_clock() -> float:
        reads.append(len(reads) * 0.05)     # every read advances the clock one fixed step
        return reads[-1]

    out = GatewayClient(_creds(), connect=lambda _c: Recorder(), clock=fake_clock).get_localkeys(
        [UP_DEV, "ACB722AABBCC", "ACB722001122"], timeout=0.3
    )
    assert out == {}
    assert len(sns) == 3 and len(set(sns)) == 3, f"sn collision: {sns}"
    # One shared deadline: the whole collection spans one timeout. A per-device deadline would span 3.
    assert reads[-1] - reads[0] == pytest.approx(0.3, abs=0.05)


def test_get_localkeys_still_returns_the_devices_that_did_answer() -> None:
    keys = GatewayClient(_creds(), connect=lambda _c: FakeMqtt()).get_localkeys([UP_DEV])
    assert keys == {UP_DEV: LocalKey(key=UP_KEY, version=UP_VER)}
