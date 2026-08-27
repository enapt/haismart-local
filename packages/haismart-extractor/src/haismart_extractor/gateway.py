"""Per-device localKey fetch over Haier's SE-Asia cloud **MQTT gateway**.

The per-device ``localKey`` is delivered over an MQTT 3.1.1 / TLS business channel to
``gw-sgp.haieriot.net:58702``. The gateway is authoritative — it returns the current key even when the
app's own cache is stale.

**Protocol**:

* CONNECT (MQTT 3.1.1 / TLS) to ``gw-sgp.haieriot.net:58702`` with :class:`GatewayCreds`.
* SUB ``Client/<clientId>/Business/Down``
* PUB ``Client/<clientId>/Business/Up`` (QoS 0), body :func:`localkey_request_payload`::

      {"type":"devLocalkey",
       "data": base64('{"sn":"<sn>","dev":"<deviceId>","flag":0}'),
       "tokens":["<accessToken>"]}

* RESP on ``.../Business/Down`` (:func:`parse_localkey_response`)::

      base64(data) -> {"sn":"<echoed>","errNo":0,"vers":<ver>,"key":"<localKey>"}

**Credentials.** All four CONNECT inputs are derivable:

* ``client_id`` — :func:`derive_client_id` = ``MD5(<uSDK CLIENTID> + "_" + <package>)`` (the uSDK
  ``CLIENTID`` is provisioned by the Login onboarding path). The gateway does **not** validate
  ``client_id`` at CONNECT — only the ``username``/``password`` pair — so any value connects; we derive it
  to match the app.
* ``access_token`` — an account accessToken; mint one from the reusable refreshToken via
  :meth:`haismart_extractor.cloud.HaierCloud.refresh_token`.
* ``username`` + ``password`` — :func:`derive_gateway_auth`. There is **no per-user secret** and no
  token/clientId in the pre-image — the pair is self-contained and self-verifying::

      username_body = 8 digits  (any 8 work)
      username      = "01" + username_body
      block         = BE16(len("haier_sdk")=9) + b"haier_sdk"    # zero-padded to a 16-byte boundary
      password      = hex( AES-128-CBC( key=MD5(username_body), iv=0, block ) )

  The gateway recomputes ``password`` from the sent username (stripping the ``"01"`` tag) and the global
  ``"haier_sdk"`` salt, so a freshly generated pair is accepted. Build creds with
  :meth:`GatewayCreds.derive`.

The MQTT connection is injectable (``connect=`` on :class:`GatewayClient`) so the request-build / response-
parse / sn-matching logic is unit-testable with a fake — no network. The default connection uses ``ssl``.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import socket
import ssl
import struct
import time
from collections.abc import Callable
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .cloud import LocalKey

DEFAULT_HOST = "gw-sgp.haieriot.net"
DEFAULT_PORT = 58702
DEFAULT_PACKAGE = "com.haier.uhome.uplus.seasia"

#: Global salt used by the gateway-auth credential derivation; the same for every install/account —
#: the gateway uses it to recompute the CONNECT password from the username.
GATEWAY_AUTH_SALT = b"haier_sdk"
#: Fixed 2-char tag prepended to the username body on the wire.
GATEWAY_USERNAME_TAG = "01"


# --- credential derivation -----------------------------------------------------


def derive_client_id(usdk_client_id: str, package: str = DEFAULT_PACKAGE) -> str:
    """The MQTT clientId = ``MD5(<uSDK CLIENTID> + "_" + <package>)`` (lowercase hex).

    ``usdk_client_id`` is the per-install uSDK ``CLIENTID`` (32-hex, e.g.
    ``A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4``), provisioned by the Login onboarding path. Reproduces the
    app's real clientId byte-for-byte.
    """
    return hashlib.md5(f"{usdk_client_id}_{package}".encode()).hexdigest()


def derive_gateway_password(username_body: str, salt: bytes = GATEWAY_AUTH_SALT) -> str:
    """Compute the CONNECT ``password`` from the username body (lowercase 32-hex).

    The gateway-auth password derivation: the plaintext is a
    length-prefixed salt block ``BE16(len(salt)) + salt`` zero-padded to a 16-byte boundary, encrypted
    with **AES-128-CBC, IV=0** under ``key = MD5(username_body)``; the 16-byte ciphertext is hex-encoded.

    ``username_body`` is the username WITHOUT the ``"01"`` wire tag (the app derives the password from the
    body only, and the gateway strips the tag before recomputing).
    """
    block = len(salt).to_bytes(2, "big") + salt
    block += b"\x00" * (-len(block) % 16)  # pad up to a whole 16-byte block
    key = hashlib.md5(username_body.encode()).digest()
    enc = Cipher(algorithms.AES(key), modes.CBC(b"\x00" * 16)).encryptor()
    return (enc.update(block) + enc.finalize()).hex()


def generate_username_body(rng: secrets.SystemRandom | None = None) -> str:
    """A fresh 8-character username body (8 decimal digits, matching the app's format).

    The app builds it as ``"%d%d%d%d%d%d%d%d"`` over 8 random bytes truncated to 8 chars; the gateway
    doesn't care about the internal structure, only that ``password == f(body)``. Any 8 digits work.
    """
    r = rng or secrets.SystemRandom()
    return "".join(str(r.randrange(10)) for _ in range(8))


def derive_gateway_auth(username_body: str | None = None) -> tuple[str, str]:
    """Return a valid ``(username, password)`` CONNECT pair, fully derived.

    ``username`` is the wire username (``"01" + body``); ``password`` is derived from the body. If
    ``username_body`` is omitted a fresh random one is generated. Verified live (CONNACK rc=0).
    """
    body = username_body if username_body is not None else generate_username_body()
    return GATEWAY_USERNAME_TAG + body, derive_gateway_password(body)


# --- request / response codec ------------------------------------------------


def localkey_request_payload(
    device_id: str, access_token: str, *, sn: str | int, flag: int = 0
) -> str:
    """Build the exact ``Business/Up`` publish body (compact JSON, cJSON key order).

    The localKey request body: an inner ``{"sn","dev","flag"}`` object (``sn`` a
    STRING, ``flag`` a NUMBER) is base64-encoded into ``data``; ``sn`` is echoed in the response so it
    doubles as a request id.
    """
    inner = json.dumps({"sn": str(sn), "dev": device_id, "flag": flag}, separators=(",", ":"))
    data = base64.b64encode(inner.encode()).decode()
    body = {"type": "devLocalkey", "data": data, "tokens": [access_token]}
    return json.dumps(body, separators=(",", ":"))


def parse_localkey_response(payload: bytes | str) -> dict:
    """Decode a ``Business/Down`` message to its inner ``{"sn","errNo","vers","key"}`` dict.

    Returns ``{}`` for a message that is not a decodable localKey response (so a reader can skip
    unrelated pushes without raising)."""
    try:
        outer = json.loads(payload)
        if outer.get("type") != "devLocalkey" or "data" not in outer:
            return {}
        inner = json.loads(base64.b64decode(outer["data"]))
    except (ValueError, KeyError, TypeError):
        return {}
    return inner if isinstance(inner, dict) else {}


# --- credentials + result ------------------------------------------------------


@dataclass(frozen=True)
class GatewayCreds:
    """MQTT CONNECT credentials for the localKey gateway.

    Every field is derivable without (see module docstring): ``client_id`` via
    :func:`derive_client_id`, ``username``/``password`` via :func:`derive_gateway_auth`, and
    ``access_token`` minted from the reusable refreshToken. Use :meth:`derive` to build a fully-derived
    instance; the raw constructor stays available for supplying values directly.
    """

    client_id: str
    username: str
    password: str
    access_token: str
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT

    @classmethod
    def derive(
        cls,
        *,
        usdk_client_id: str,
        access_token: str,
        package: str = DEFAULT_PACKAGE,
        username_body: str | None = None,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
    ) -> GatewayCreds:
        """Build fully-derived creds — no stored username/password needed.

        ``client_id = MD5(usdk_client_id + "_" + package)`` and the ``username``/``password`` pair is
        generated by :func:`derive_gateway_auth` (fresh random body unless ``username_body`` is pinned).
        """
        username, password = derive_gateway_auth(username_body)
        return cls(
            client_id=derive_client_id(usdk_client_id, package),
            username=username,
            password=password,
            access_token=access_token,
            host=host,
            port=port,
        )

    @property
    def pub_topic(self) -> str:
        return f"Client/{self.client_id}/Business/Up"

    @property
    def sub_topic(self) -> str:
        return f"Client/{self.client_id}/Business/Down"


# --- MQTT connection abstraction (injectable for tests) ------------------------


class MqttConnection:
    """Minimal MQTT connection contract used by :class:`GatewayClient`.

    Tests inject a fake; :class:`_TlsMqttConnection` is the real one.
    """

    def subscribe(self, topic: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def publish(self, topic: str, payload: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def poll(self, timeout: float) -> list[tuple[str, bytes]]:  # pragma: no cover - interface
        """Return any PUBLISH messages received within ``timeout`` as ``(topic, payload)``."""
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError


ConnectionFactory = Callable[[GatewayCreds], MqttConnection]


_LOGGER = logging.getLogger(__name__)


class GatewayError(Exception):
    pass


class GatewayClient:
    """Fetch per-device localKeys over the MQTT gateway.

    ``connect`` is a factory returning a live :class:`MqttConnection` for the given creds; it defaults to
    the real TLS connection but tests pass a fake. ``clock`` is the source of the collection deadline
    and is injectable for the same reason: a test that asserts "one shared deadline, not one per
    device" must not do so by measuring the wall clock.
    """

    def __init__(
        self,
        creds: GatewayCreds,
        *,
        connect: ConnectionFactory | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.creds = creds
        self._connect = connect or _tls_connect
        # A timeout is an ELAPSED-time question, so it takes the monotonic clock. This used to read
        # `time.time()`, which the system may step (NTP, suspend/resume, a WSL host clock jump) — and a
        # stepped wall clock either abandons the collection early or holds the connection open far past
        # the caller's timeout. `MqttPahoConnection.subscribe` in this same file already deadlined on
        # `time.monotonic`; the two disagreed.
        self._clock = clock or time.monotonic
        # Monotonic request counter. This used to be `time_ms + len(out)`, where `len(out)` only
        # advanced on SUCCESS — so two devices requested in the same millisecond after a failure got
        # the SAME sn, and a late reply for one could be stored against the other. A device holding
        # another device's key fails its MD5 check forever, presenting as an unfixable stale key.
        self._sn = int(time.time() * 1000)

    def _next_sn(self) -> str:
        self._sn += 1
        return str(self._sn % 1_000_000_000)

    def _request_keys(
        self, conn: MqttConnection, device_ids: list[str], timeout: float
    ) -> tuple[dict[str, LocalKey], dict[str, str]]:
        """Publish one request per device, then collect replies against a SINGLE deadline.

        Returns ``(keys, failures)``. Both public methods share this, so they can no longer disagree
        about what a valid response looks like — the batch path previously omitted the ``errNo`` check
        entirely and used a per-device deadline, making a bad token take ``N * timeout`` seconds.
        """
        pending: dict[str, str] = {}
        for device_id in device_ids:
            sn = self._next_sn()
            pending[sn] = device_id
            conn.publish(
                self.creds.pub_topic,
                localkey_request_payload(device_id, self.creds.access_token, sn=sn),
            )
        keys: dict[str, LocalKey] = {}
        failures: dict[str, str] = {}
        deadline = self._clock() + timeout
        while pending and self._clock() < deadline:
            for _topic, pay in conn.poll(0.5):
                inner = parse_localkey_response(pay)
                sn = str(inner.get("sn"))
                device_id = pending.get(sn)
                if device_id is None:
                    continue        # not ours, or already answered
                # Check errNo BEFORE the key. It used to be nested INSIDE `if inner.get("key")`, but a
                # real error response carries no key at all - so every genuine failure (expired token,
                # device not bound, wrong terminal) fell through to a bare "no response within Ns",
                # discarding the reason the gateway had just given us.
                err = _as_int(inner.get("errNo")) or 0
                if err:
                    failures[device_id] = f"gateway errNo={err}"
                elif inner.get("key"):
                    keys[device_id] = LocalKey(
                        key=str(inner["key"]), version=_as_int(inner.get("vers"))
                    )
                else:
                    failures[device_id] = "gateway returned neither a key nor an errNo"
                pending.pop(sn, None)
        for sn, device_id in pending.items():
            failures.setdefault(device_id, f"no localKey response within {timeout}s")
        return keys, failures

    def get_localkey(self, device_id: str, *, timeout: float = 8.0) -> LocalKey:
        """Fetch ``device_id``'s current localKey. Raises :class:`GatewayError` on no/failed response."""
        conn = self._connect(self.creds)
        try:
            conn.subscribe(self.creds.sub_topic)
            keys, failures = self._request_keys(conn, [device_id], timeout)
        finally:
            conn.close()
        if device_id in keys:
            return keys[device_id]
        raise GatewayError(f"{failures.get(device_id, 'no localKey response')} for {device_id}")

    def get_localkeys(self, device_ids: list[str], *, timeout: float = 8.0) -> dict[str, LocalKey]:
        """Fetch several devices' localKeys over one connection.

        Devices that fail are omitted, but the reason is logged rather than silently swallowed, so a
        short result set can be explained (offline vs not bound vs token rejected).
        """
        conn = self._connect(self.creds)
        try:
            conn.subscribe(self.creds.sub_topic)
            keys, failures = self._request_keys(conn, list(device_ids), timeout)
        finally:
            conn.close()
        for device_id, reason in failures.items():
            _LOGGER.warning("localKey fetch failed for %s: %s", device_id, reason)
        return keys


def get_localkey_via_gateway(
    creds: GatewayCreds,
    device_id: str,
    *,
    timeout: float = 8.0,
    connect: ConnectionFactory | None = None,
) -> LocalKey:
    """One-shot convenience: connect, fetch ``device_id``'s localKey, disconnect."""
    return GatewayClient(creds, connect=connect).get_localkey(device_id, timeout=timeout)


def _as_int(v: object) -> int | None:
    try:
        return int(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


# --- default TLS MQTT connection (raw MQTT 3.1.1; no external deps) -------------


def _encode_len(n: int) -> bytes:
    out = b""
    while True:
        d = n % 128
        n //= 128
        out += bytes([d | 0x80]) if n > 0 else bytes([d])
        if n == 0:
            return out


def _mqtt_field(s: bytes | str) -> bytes:
    b = s.encode() if isinstance(s, str) else s
    return struct.pack(">H", len(b)) + b


class _TlsMqttConnection(MqttConnection):  # pragma: no cover - needs network
    """Raw MQTT 3.1.1 over TLS. Deliberately dependency-free (stdlib ``ssl`` only)."""

    def __init__(self, creds: GatewayCreds) -> None:
        # Verified TLS. This channel carries the account accessToken (in the publish body) and the
        # device localKey (in the reply), so `CERT_NONE` handed both to anyone able to intercept the
        # connection - silently, with no warning. The host presents a valid public DigiCert
        # certificate for its own name, so verification simply works; there is nothing to trade off.
        # A caller that genuinely needs different behaviour can inject its own ConnectionFactory.
        ctx = ssl.create_default_context()
        self.ss: ssl.SSLSocket | None = None
        self._pid = 0
        self._buf = b""
        self._subacked: set[int] = set()
        self._publishes: list[tuple[str, bytes]] = []
        raw = socket.create_connection((creds.host, creds.port), timeout=10)
        try:
            self.ss = ctx.wrap_socket(raw, server_hostname=creds.host)
        except Exception:
            raw.close()     # wrap_socket does not own `raw` until it succeeds
            raise
        try:
            vh = b"\x00\x04MQTT\x04" + bytes([0x02 | 0x80 | 0x40]) + struct.pack(">H", 60)
            body = (vh + _mqtt_field(creds.client_id) + _mqtt_field(creds.username)
                    + _mqtt_field(creds.password))
            self.ss.sendall(b"\x10" + _encode_len(len(body)) + body)
            # Read until a whole CONNACK is in hand. Taking `r[3]` off a single recv reported
            # "rc=-1 (creds rejected/stale)" for a merely fragmented packet, sending users to
            # re-authenticate when their credentials were fine.
            ack = b""
            while len(ack) < 4:
                chunk = self.ss.recv(4 - len(ack))
                if not chunk:
                    raise GatewayError("gateway closed the connection before CONNACK")
                ack += chunk
            if ack[0] != 0x20:
                raise GatewayError(f"expected CONNACK, got packet type {ack[0] >> 4}")
            if ack[3] != 0:
                raise GatewayError(f"CONNACK rc={ack[3]} (creds rejected/stale)")
        except Exception:
            self.close()    # otherwise every failed attempt leaks an fd until "too many open files"
            raise

    def subscribe(self, topic: str, *, timeout: float = 5.0) -> None:
        """Subscribe and WAIT for the SUBACK before returning.

        The caller publishes immediately after subscribing. Without this wait the broker could process
        the publish's response before the subscription existed, so the reply went nowhere and the
        result was an intermittent, unreproducible "no localKey response within 8s".
        """
        self._pid += 1
        pid = self._pid
        body = struct.pack(">H", pid) + _mqtt_field(topic) + b"\x00"
        self.ss.sendall(b"\x82" + _encode_len(len(body)) + body)
        deadline = time.monotonic() + timeout
        while pid not in self._subacked and time.monotonic() < deadline:
            # any PUBLISH arriving early is buffered by _drain, not dropped
            self._drain(min(0.5, max(0.05, deadline - time.monotonic())))
        if pid not in self._subacked:
            raise GatewayError(f"no SUBACK for {topic!r} within {timeout}s")

    def publish(self, topic: str, payload: str) -> None:
        body = _mqtt_field(topic) + payload.encode()
        self.ss.sendall(b"\x30" + _encode_len(len(body)) + body)

    def poll(self, timeout: float) -> list[tuple[str, bytes]]:
        """Return PUBLISH payloads, including any buffered while waiting for a SUBACK."""
        return self._drain(timeout)

    def _drain(self, timeout: float) -> list[tuple[str, bytes]]:
        out: list[tuple[str, bytes]] = self._publishes
        self._publishes = []
        self.ss.settimeout(timeout)
        try:
            d = self.ss.recv(8192)
            if d:
                self._buf += d
        except TimeoutError:
            return out
        while len(self._buf) >= 2:
            mult = 1
            val = 0
            i = 1
            done = False
            while i < len(self._buf):
                b = self._buf[i]
                val += (b & 0x7F) * mult
                mult *= 128
                i += 1
                if not (b & 0x80):
                    done = True
                    break
            if not done:
                break
            total = i + val
            if len(self._buf) < total:
                break
            t = self._buf[0]
            pkt = self._buf[i:total]
            self._buf = self._buf[total:]
            if (t >> 4) == 9 and len(pkt) >= 2:  # SUBACK
                self._subacked.add((pkt[0] << 8) | pkt[1])
            elif (t >> 4) == 3:  # PUBLISH
                tl = (pkt[0] << 8) | pkt[1]
                topic = pkt[2 : 2 + tl].decode("latin1")
                qos = (t >> 1) & 3
                payload = pkt[2 + tl + (2 if qos > 0 else 0):]
                out.append((topic, payload))
        return out

    def close(self) -> None:
        if self.ss is None:
            return
        try:
            self.ss.close()
        except OSError:
            pass


def _tls_connect(creds: GatewayCreds) -> MqttConnection:  # pragma: no cover - needs network
    return _TlsMqttConnection(creds)
