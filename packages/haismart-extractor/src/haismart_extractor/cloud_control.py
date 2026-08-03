"""Device control (set/read attributes, run ops) over Haier's SE-Asia cloud MQTT channel.

Unlike :mod:`~haismart_extractor.gateway` (which only fetches localKeys), this speaks the **user**
channel of the same broker (``gw-sgp.haieriot.net:58702``) — the one the app uses to control devices
that are online through the cloud but not (yet) reachable on the LAN, and to run operations the local
protocol does not expose.

**Protocol** (reversed from ``liball-in-one.so`` + live probing; CONNECT verified rc=0, responses
verified against real devices):

* CONNECT (MQTT 3.1.1 / TLS) with :class:`CloudControlCreds`.
* SUB ``User/<accessToken>/#`` — **mandatory before any publish** (the app logs "dont pub, befor
  user sub"; without the subscription the response is routed nowhere).
* PUB ``User/<accessToken>/Req/Attr/W/<deviceId>`` for a write, ``.../Req/Attr/R/<deviceId>`` for a
  read, ``.../Req/Op/<deviceId>`` for an op. Bodies (compact JSON, ``sn`` a STRING echoed back)::

      W:  {"sn":"<sn>","devId":"<deviceId>","name":"<attr>","value":<value>}
      R:  {"sn":"<sn>","devId":"<deviceId>","name":"<attr>"}          # omit name to read all
      Op: {"sn":"<sn>","devId":"<deviceId>","op":"<op>","args":[<args>]}

* RESP on ``User/<accessToken>/Resp/Attr/W/<deviceId>`` etc::

      {"sn":"<echoed>","errNo":0}                                     # 0 = success

  ``errNo`` semantics observed live: ``14`` = invalid user (wrong token on the topic/userId),
  ``15`` = device not found, ``16`` = device offline. Any other reply (e.g. a ``Push/Event``
  ``invalidToken`` heartbeat) is ignored.

**Credentials.** Everything is derivable (see module docstring of :mod:`gateway` for the shared parts):

* ``client_id`` — same ``MD5(<uSDK CLIENTID> + "_" + <package>)`` as the localKey channel.
* ``username`` — ``"01"`` + a compact JSON identity blob, byte-ordered as the app builds it::

      {"protocolVers":"1.0.0","clientId":"<clientId>","connType":"MqttUsdk","svcVers":"1.2.3",
       "libVers":"UCP-MQTT-UACP","userAGpType":"1","appId":"<appId>","appVers":"<appVersion>",
       "userId":"<uhomeUserId>","token":"<accessToken>"}

* ``password`` — the SAME derivation as the localKey channel (:func:`derive_gateway_password`), but
  the pre-image is the JSON body WITHOUT the ``"01"`` tag. Deriving from the tagged string, or sending
  any other password, gets CONNACK rc=4.

The MQTT connection is injectable (``connect=`` on :class:`CloudControlClient`) so the request-build /
response-parse / sn-matching logic is unit-testable with a fake — no network.
"""
from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .cloud import LocalKey  # noqa: F401  (re-exported convenience, mirrors gateway.py)
from .gateway import (
    DEFAULT_HOST,
    DEFAULT_PACKAGE,
    DEFAULT_PORT,
    GATEWAY_USERNAME_TAG,
    GatewayCreds,
    MqttConnection,
    _tls_connect,
    derive_client_id,
    derive_gateway_password,
)

#: The uHome app identity used for the CONNECT username blob. Same for every user.
DEFAULT_APP_ID = "MB-SHEYJDNYB-0001"
DEFAULT_APP_VERSION = "5.5.0"

#: errNo values observed live on the user channel.
ERR_OK = 0
ERR_INVALID_USER = 14       # wrong user token / topic prefix
ERR_DEVICE_NOT_FOUND = 15   # device id not bound to the account
ERR_DEVICE_OFFLINE = 16     # device exists but is not connected to the cloud

_LOGGER = logging.getLogger(__name__)

# --- CONNECT username blob -----------------------------------------------------


def generate_cloud_username_body(
    *,
    client_id: str,
    user_id: str,
    access_token: str,
    app_id: str = DEFAULT_APP_ID,
    app_version: str = DEFAULT_APP_VERSION,
) -> str:
    """The compact JSON identity blob used as the CONNECT username (without the ``"01"`` tag).

    Key order is fixed (cJSON insertion order from the app). The gateway routes this connection's
    topics by the ``token``/``userId`` fields, so both must be the uHome values.
    """
    return json.dumps(
        {
            "protocolVers": "1.0.0",
            "clientId": client_id,
            "connType": "MqttUsdk",
            "svcVers": "1.2.3",
            "libVers": "UCP-MQTT-UACP",
            "userAGpType": "1",
            "appId": app_id,
            "appVers": app_version,
            "userId": user_id,
            "token": access_token,
        },
        separators=(",", ":"),
    )


def derive_cloud_control_auth(
    *,
    client_id: str,
    user_id: str,
    access_token: str,
    app_id: str = DEFAULT_APP_ID,
    app_version: str = DEFAULT_APP_VERSION,
) -> tuple[str, str]:
    """Return a valid ``(username, password)`` CONNECT pair for the user channel.

    ``username`` = ``"01"`` + the JSON blob; ``password`` = the standard gateway derivation applied to
    the blob WITHOUT the tag (verified live: tagged pre-image or any other password → CONNACK rc=4).
    """
    body = generate_cloud_username_body(
        client_id=client_id,
        user_id=user_id,
        access_token=access_token,
        app_id=app_id,
        app_version=app_version,
    )
    return GATEWAY_USERNAME_TAG + body, derive_gateway_password(body)


# --- request / response codec --------------------------------------------------


def cloud_control_request_payload(
    operation: str, device_id: str, *, sn: str | int, name: str | None = None,
    value: object = None, args: list | None = None, op: str | None = None,
) -> str:
    """Build the ``Req/.../<deviceId>`` publish body (compact JSON; ``sn`` a STRING).

    ``operation`` is the topic segment between ``Req/`` and ``<deviceId>`` — ``Attr/W``, ``Attr/R``
    or ``Op``. Reads omit ``value``/``args``; passing ``name=None`` reads all attributes.
    """
    body: dict = {"sn": str(sn), "devId": device_id}
    if operation == "Op":
        body["op"] = op or ""
        body["args"] = args or []
    else:
        if name is not None:
            body["name"] = name
        if operation == "Attr/W":
            body["value"] = value
    return json.dumps(body, separators=(",", ":"))


def parse_cloud_control_response(payload: bytes | str) -> dict:
    """Decode a ``Resp/...`` message to its inner ``{"sn","errNo"}`` dict.

    Returns ``{}`` for anything that is not a control response (unrelated pushes, junk), so a reader
    can skip messages without raising.
    """
    try:
        d = json.loads(payload)
    except (ValueError, TypeError):
        return {}
    if not isinstance(d, dict) or ("errNo" not in d and "sn" not in d):
        return {}
    return d


# --- credentials + result ------------------------------------------------------


@dataclass(frozen=True)
class CloudControlCreds:
    """MQTT CONNECT credentials for the cloud user channel.

    Every field is derivable (see module docstring): ``client_id`` via
    :func:`derive_client_id`, ``username``/``password`` via :func:`derive_cloud_control_auth`, and
    ``access_token`` minted from the reusable refreshToken. Use :meth:`derive` to build a fully-derived
    instance.
    """

    client_id: str
    username: str
    password: str
    user_id: str
    access_token: str
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT

    @classmethod
    def derive(
        cls,
        *,
        usdk_client_id: str,
        user_id: str,
        access_token: str,
        package: str = DEFAULT_PACKAGE,
        app_id: str = DEFAULT_APP_ID,
        app_version: str = DEFAULT_APP_VERSION,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
    ) -> CloudControlCreds:
        """Build fully-derived creds — no stored username/password needed."""
        client_id = derive_client_id(usdk_client_id, package)
        username, password = derive_cloud_control_auth(
            client_id=client_id,
            user_id=user_id,
            access_token=access_token,
            app_id=app_id,
            app_version=app_version,
        )
        return cls(
            client_id=client_id,
            username=username,
            password=password,
            user_id=user_id,
            access_token=access_token,
            host=host,
            port=port,
        )

    def gateway_creds(self) -> GatewayCreds:
        """The equivalent localKey-channel creds, for the shared TLS connection."""
        return GatewayCreds(
            client_id=self.client_id,
            username=self.username,
            password=self.password,
            access_token=self.access_token,
            host=self.host,
            port=self.port,
        )

    @property
    def sub_topic(self) -> str:
        return f"User/{self.access_token}/#"

    def req_topic(self, operation: str, device_id: str) -> str:
        return f"User/{self.access_token}/Req/{operation}/{device_id}"


@dataclass(frozen=True)
class CloudControlResult:
    """A successful control response (``err_no == 0``)."""

    device_id: str
    operation: str
    sn: str
    err_no: int = ERR_OK
    raw: dict = field(default_factory=dict)


class CloudControlError(Exception):
    """Control failed: connection error, timeout, or a non-zero gateway ``errNo``.

    ``err_no`` carries the gateway's code when known (14 invalid user, 15 device not found,
    16 device offline) so callers can render a precise message.
    """

    def __init__(self, message: str, err_no: int | None = None) -> None:
        super().__init__(message)
        self.err_no = err_no


# --- client --------------------------------------------------------------------


ConnectionFactory = Callable[[GatewayCreds], MqttConnection]


class CloudControlClient:
    """Set/read device attributes and run ops over the cloud MQTT user channel.

    ``connect`` is a factory returning a live :class:`MqttConnection` for the given creds; it defaults
    to the real TLS connection but tests pass a fake.
    """

    def __init__(
        self, creds: CloudControlCreds, *, connect: ConnectionFactory | None = None
    ) -> None:
        self.creds = creds
        self._connect = connect or _tls_connect
        self._sn = int(time.time() * 1000)

    def _next_sn(self) -> str:
        self._sn += 1
        return str(self._sn % 1_000_000_000)

    def set_attribute(self, device_id: str, name: str, value: object, *, timeout: float = 8.0) -> CloudControlResult:
        return self._request("Attr/W", device_id, name=name, value=value, timeout=timeout)

    def get_attribute(self, device_id: str, name: str | None = None, *, timeout: float = 8.0) -> CloudControlResult:
        return self._request("Attr/R", device_id, name=name, timeout=timeout)

    def operate(self, device_id: str, op: str, args: list | None = None, *, timeout: float = 8.0) -> CloudControlResult:
        return self._request("Op", device_id, op=op, args=args, timeout=timeout)

    def _request(self, operation: str, device_id: str, *, timeout: float,
                 name: str | None = None, value: object = None, args: list | None = None,
                 op: str | None = None) -> CloudControlResult:
        sn = self._next_sn()
        conn = self._connect(self.creds.gateway_creds())
        try:
            conn.subscribe(self.creds.sub_topic)
            conn.publish(
                self.creds.req_topic(operation, device_id),
                cloud_control_request_payload(
                    operation, device_id, sn=sn, name=name, value=value, args=args, op=op
                ),
            )
            deadline = time.time() + timeout
            while time.time() < deadline:
                for _topic, pay in conn.poll(0.5):
                    inner = parse_cloud_control_response(pay)
                    if not inner or str(inner.get("sn")) != sn:
                        continue  # unrelated push or another request's reply
                    err = _as_int(inner.get("errNo"))
                    if err is None or err == ERR_OK:
                        return CloudControlResult(
                            device_id=device_id, operation=operation,
                            sn=sn, err_no=ERR_OK, raw=inner,
                        )
                    raise CloudControlError(
                        f"cloud {operation} errNo={err} for {device_id}", err_no=err
                    )
            raise CloudControlError(f"no cloud {operation} response for {device_id} within {timeout}s")
        finally:
            conn.close()


def _as_int(v: object) -> int | None:
    try:
        return int(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
