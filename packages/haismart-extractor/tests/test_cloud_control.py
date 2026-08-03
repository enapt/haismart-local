"""Tests for cloud device control (set/read/op over the MQTT user channel).

No network: the MQTT connection is faked. The wire shapes mirror the live probes
(CONNECT username blob, ``Req/Attr/W|R``/``Req/Op`` bodies, ``Resp`` errNo semantics)."""
import json
import time

import pytest

from haismart_extractor.cloud_control import (
    CloudControlClient,
    CloudControlCreds,
    CloudControlError,
    ERR_DEVICE_NOT_FOUND,
    ERR_DEVICE_OFFLINE,
    cloud_control_request_payload,
    derive_cloud_control_auth,
    generate_cloud_username_body,
    parse_cloud_control_response,
)
from haismart_extractor.gateway import GatewayCreds, MqttConnection, derive_gateway_password

USDK_CLIENTID = "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4"
CLIENT_ID = "397a1e2e07cbf0391eaa95067dfba026"
USER_ID = "348544202731458560"
TOKEN = "2_378649363670413313rdnz24zt"
DEV = "94224C865A11"

# username blob for the fixed inputs above (cJSON key order from the app's strings)
GOLDEN_USERNAME = (
    '01{"protocolVers":"1.0.0","clientId":"397a1e2e07cbf0391eaa95067dfba026",'
    '"connType":"MqttUsdk","svcVers":"1.2.3","libVers":"UCP-MQTT-UACP","userAGpType":"1",'
    '"appId":"MB-SHEYJDNYB-0001","appVers":"5.5.0","userId":"348544202731458560",'
    '"token":"2_378649363670413313rdnz24zt"}'
)


def _resp(sn: str, err_no: int = 0) -> bytes:
    return json.dumps({"sn": str(sn), "errNo": err_no}, separators=(",", ":")).encode()


class FakeMqtt(MqttConnection):
    """Records subscribe/publish; auto-answers each publish echoing its ``sn``."""

    def __init__(self, *, err_no=0, echo_sn=True, answer=True, topic=None) -> None:
        self.err_no, self.echo_sn, self.answer = err_no, echo_sn, answer
        self.topic = topic or f"User/{TOKEN}/Resp/Attr/W/{DEV}"
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
        sn = json.loads(payload)["sn"] if self.echo_sn else "999999"
        self._queue.append((self.topic, _resp(sn, self.err_no)))

    def poll(self, timeout: float) -> list[tuple[str, bytes]]:
        out, self._queue = self._queue, []
        return out

    def close(self) -> None:
        self.closed = True


def _creds() -> CloudControlCreds:
    return CloudControlCreds.derive(
        usdk_client_id=USDK_CLIENTID, user_id=USER_ID, access_token=TOKEN
    )


# --- CONNECT username/password derivation ---


def test_username_blob_shape_and_order() -> None:
    body = generate_cloud_username_body(
        client_id=CLIENT_ID, user_id=USER_ID, access_token=TOKEN
    )
    assert body == GOLDEN_USERNAME[2:]  # blob without the "01" tag
    assert list(json.loads(body)) == [
        "protocolVers", "clientId", "connType", "svcVers", "libVers",
        "userAGpType", "appId", "appVers", "userId", "token",
    ]
    assert json.loads(body)["userId"] == USER_ID
    assert json.loads(body)["token"] == TOKEN


def test_derive_cloud_control_auth_uses_blob_without_tag() -> None:
    username, password = derive_cloud_control_auth(
        client_id=CLIENT_ID, user_id=USER_ID, access_token=TOKEN
    )
    assert username == GOLDEN_USERNAME
    assert username.startswith("01")
    # password pre-image is the blob WITHOUT the tag — this is the rc=0 finding
    assert password == derive_gateway_password(GOLDEN_USERNAME[2:])


def test_derive_cloud_control_auth_tagged_preimage_differs() -> None:
    # regression guard: deriving from "01"+blob yields a different (rejected, rc=4) password
    username, password = derive_cloud_control_auth(
        client_id=CLIENT_ID, user_id=USER_ID, access_token=TOKEN
    )
    assert password != derive_gateway_password(username)


def test_creds_derive_is_fully_derived() -> None:
    creds = CloudControlCreds.derive(
        usdk_client_id=USDK_CLIENTID, user_id=USER_ID, access_token=TOKEN
    )
    assert creds.client_id == CLIENT_ID
    assert creds.user_id == USER_ID
    assert creds.access_token == TOKEN
    assert creds.username == GOLDEN_USERNAME
    assert creds.password == derive_gateway_password(GOLDEN_USERNAME[2:])
    assert creds.req_topic("Attr/W", DEV) == f"User/{TOKEN}/Req/Attr/W/{DEV}"
    assert creds.sub_topic == f"User/{TOKEN}/#"


def test_creds_gateway_creds_roundtrip() -> None:
    gw = _creds().gateway_creds()
    assert isinstance(gw, GatewayCreds)
    assert gw.host == "gw-sgp.haieriot.net" and gw.port == 58702


# --- request/response codec ---


def test_write_payload_shape() -> None:
    body = json.loads(cloud_control_request_payload("Attr/W", DEV, sn=7, name="power", value=1))
    assert body == {"sn": "7", "devId": DEV, "name": "power", "value": 1}
    assert isinstance(body["sn"], str)


def test_read_payload_omits_value() -> None:
    body = json.loads(cloud_control_request_payload("Attr/R", DEV, sn=7, name="power"))
    assert body == {"sn": "7", "devId": DEV, "name": "power"}


def test_read_all_omits_name() -> None:
    body = json.loads(cloud_control_request_payload("Attr/R", DEV, sn=7))
    assert body == {"sn": "7", "devId": DEV}


def test_op_payload_shape() -> None:
    body = json.loads(
        cloud_control_request_payload("Op", DEV, sn=7, op="startProgram", args=[1, 2])
    )
    assert body == {"sn": "7", "devId": DEV, "op": "startProgram", "args": [1, 2]}


def test_parse_response_ok() -> None:
    assert parse_cloud_control_response(b'{"sn":"7","errNo":0}') == {"sn": "7", "errNo": 0}


@pytest.mark.parametrize("junk", [b"not json", "{}", b'\x00\x01', '{"event":"invalidToken"}'])
def test_parse_response_ignores_junk(junk) -> None:
    assert parse_cloud_control_response(junk) == {}


# --- client flow ---


def test_set_attribute_returns_result_and_cleans_up() -> None:
    fake = FakeMqtt()
    res = CloudControlClient(_creds(), connect=lambda c: fake).set_attribute(DEV, "power", 1)
    assert res.err_no == 0 and res.device_id == DEV and res.operation == "Attr/W"
    assert fake.subs == [f"User/{TOKEN}/#"]
    assert fake.pubs[0][0] == f"User/{TOKEN}/Req/Attr/W/{DEV}"
    assert json.loads(fake.pubs[0][1])["value"] == 1
    assert fake.closed


def test_get_attribute_publishes_read_topic() -> None:
    fake = FakeMqtt(topic=f"User/{TOKEN}/Resp/Attr/R/{DEV}")
    CloudControlClient(_creds(), connect=lambda c: fake).get_attribute(DEV, "power")
    assert fake.pubs[0][0] == f"User/{TOKEN}/Req/Attr/R/{DEV}"
    assert json.loads(fake.pubs[0][1])["name"] == "power"


def test_operate_publishes_op_topic() -> None:
    fake = FakeMqtt(topic=f"User/{TOKEN}/Resp/Op/{DEV}")
    CloudControlClient(_creds(), connect=lambda c: fake).operate(DEV, "startProgram", [1])
    assert fake.pubs[0][0] == f"User/{TOKEN}/Req/Op/{DEV}"
    body = json.loads(fake.pubs[0][1])
    assert body["op"] == "startProgram" and body["args"] == [1]


def test_errno_raises_with_code() -> None:
    fake = FakeMqtt(err_no=ERR_DEVICE_OFFLINE)
    with pytest.raises(CloudControlError) as ei:
        CloudControlClient(_creds(), connect=lambda c: fake).set_attribute(DEV, "power", 1)
    assert ei.value.err_no == ERR_DEVICE_OFFLINE
    assert "errNo=16" in str(ei.value)
    assert fake.closed


def test_errno_device_not_found() -> None:
    fake = FakeMqtt(err_no=ERR_DEVICE_NOT_FOUND)
    with pytest.raises(CloudControlError) as ei:
        CloudControlClient(_creds(), connect=lambda c: fake).set_attribute(DEV, "power", 1)
    assert ei.value.err_no == ERR_DEVICE_NOT_FOUND


def test_times_out_on_wrong_sn() -> None:
    fake = FakeMqtt(echo_sn=False)
    with pytest.raises(CloudControlError, match="no cloud Attr/W response"):
        CloudControlClient(_creds(), connect=lambda c: fake).set_attribute(DEV, "power", 1, timeout=0.2)
    assert fake.closed


def test_times_out_on_silence() -> None:
    fake = FakeMqtt(answer=False)
    with pytest.raises(CloudControlError, match="within"):
        CloudControlClient(_creds(), connect=lambda c: fake).set_attribute(DEV, "power", 1, timeout=0.2)


def test_sns_never_repeat() -> None:
    sns = []

    class Recorder(FakeMqtt):
        def publish(self, topic, payload):
            self.pubs.append((topic, payload))
            sns.append(json.loads(payload)["sn"])

    client = CloudControlClient(_creds(), connect=lambda _c: Recorder())
    for _ in range(3):
        with pytest.raises(CloudControlError):
            client.set_attribute(DEV, "power", 1, timeout=0.1)  # silence -> raise
    assert len(sns) == 3 and len(set(sns)) == 3, f"sn collision: {sns}"


def test_ignores_unrelated_push_then_answers() -> None:
    class PushFirst(FakeMqtt):
        def publish(self, topic, payload):
            self.pubs.append((topic, payload))
            sn = json.loads(payload)["sn"]
            self._queue.append((f"User/{TOKEN}/Push/Event", b'{"event":"invalidToken","info":null}'))
            self._queue.append((self.topic, _resp(sn, 0)))

    res = CloudControlClient(_creds(), connect=lambda _c: PushFirst()).set_attribute(DEV, "power", 1)
    assert res.err_no == 0


def test_elapsed_one_shared_deadline() -> None:
    fake = FakeMqtt(answer=False)
    t0 = time.monotonic()
    with pytest.raises(CloudControlError):
        CloudControlClient(_creds(), connect=lambda _c: fake).set_attribute(DEV, "power", 1, timeout=0.3)
    assert time.monotonic() - t0 < 0.3 * 2.5
