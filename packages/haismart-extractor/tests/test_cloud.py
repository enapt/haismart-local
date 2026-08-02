import hashlib
import json

import pytest

from haismart_extractor.cloud import (
    DEVICE_LIST_PATH,
    DEVICE_MODEL_PATH,
    LOGIN_PATH,
    PUBLIC_CONFIG_URL,
    AppCredentials,
    CloudError,
    Domains,
    HaierCloud,
    LoginResult,
    Request,
    Response,
    device_center_sign,
    device_center_sign_payload,
    encrypt_login_password,
    get_public_device_config,
    normalize_public_config,
)


class Capture:
    """Fake transport: records the request, returns a canned response. No network."""

    def __init__(self, response: Response) -> None:
        self.response = response
        self.request: Request | None = None

    async def __call__(self, req: Request) -> Response:
        self.request = req
        return self.response


# --- signing (golden: locks the recovered algorithm) --------------------------


def test_sign_payload_exact_order() -> None:
    # sign = path + stripWs(body) + appId + appKey + timestamp
    payload = device_center_sign_payload(
        "MB-UZHSH", "appkey123", "1700000000000", '{"deviceId":"D1"}', "/rcs/device/7d/query"
    )
    assert payload == "/rcs/device/7d/query" + '{"deviceId":"D1"}' + "MB-UZHSH" + "appkey123" + "1700000000000"


def test_sign_is_lowercase_sha256_hex() -> None:
    s = device_center_sign(
        "MB-UZHSH", "appkey123", "1700000000000", '{"deviceId":"D1"}', "/rcs/device/7d/query"
    )
    expected = hashlib.sha256(
        ("/rcs/device/7d/query" + '{"deviceId":"D1"}' + "MB-UZHSH" + "appkey123" + "1700000000000").encode()
    ).hexdigest()
    assert s == expected
    assert len(s) == 64 and s == s.lower()


def test_body_whitespace_stripped_for_sign() -> None:
    assert device_center_sign_payload("a", "k", "1", '{ "x": 1 }', "/p") == "/p" + '{"x":1}' + "a" + "k" + "1"


def test_appkey_trimmed_and_dequoted() -> None:
    # appKey is .trim()'d and has '"' removed before hashing.
    assert device_center_sign_payload("a", ' "k" ', "1", "{}", "/p") == "/p{}ak1"


# --- request pipeline ---------------------------------------------------------


async def test_device_center_request_pipeline() -> None:
    creds = AppCredentials(app_id="MB-UZHSH", app_key="secretKey!!", client_id="CID123")
    cap = Capture(Response(200, json.dumps({"retCode": "00000", "data": {}})))
    cloud = HaierCloud(creds, access_token="TOKEN", transport=cap)

    out = await cloud.get_device_7d("DEV1")

    req = cap.request
    assert req is not None
    assert req.method == "POST"
    assert req.url == "https://uws-sgp.haieriot.net/rcs/device/7d/query"
    assert req.body == '{"deviceId":"DEV1"}'  # compact JSON
    h = req.headers
    assert h["appId"] == "MB-UZHSH"
    assert h["appVersion"] == "5.5.0"
    assert h["apiVersion"] == "v1"
    assert h["clientId"] == "CID123"
    assert h["accessToken"] == "TOKEN"
    assert h["sequenceId"] == h["timestamp"] + "000010"
    assert h["language"] == "en-us" and h["timezone"] == "8"
    assert h["zoneInfo"] == "0"  # default; account/refreshToken needs a real value
    assert h["Content-Type"] == "application/json;charset=UTF-8"
    # sign is internally consistent with the recovered formula
    assert h["sign"] == device_center_sign(
        "MB-UZHSH", "secretKey!!", h["timestamp"], req.body, "/rcs/device/7d/query"
    )
    assert out["retCode"] == "00000"


async def test_non_200_raises_cloud_error() -> None:
    cloud = HaierCloud(AppCredentials("a", "k", "c"), "T", transport=Capture(Response(401, "denied")))
    with pytest.raises(CloudError):
        await cloud.get_device_7d("D")


async def test_refresh_token_pipeline_and_parse() -> None:
    # canned response mirrors the live  shape (accountToken rotates; refreshToken reused)
    resp_json = json.dumps({
        "retCode": "00000", "retInfo": "Operation succeeded",
        "data": {"accountToken": "2_NEWACCESS", "refreshToken": "2_RT", "expiresIn": "863999",
                 "uhomeUserId": "375071370301804544", "scope": "users.admin", "tokenType": "bearer"},
    })
    cap = Capture(Response(200, resp_json))
    creds = AppCredentials(app_id="MB-UZHSH", app_key="secretKey!!", client_id="8E57TERMINAL")
    cloud = HaierCloud(creds, access_token="OLD", zone_info="66", transport=cap)

    result = await cloud.refresh_token("2_RT")

    req = cap.request
    assert req.method == "POST"
    assert req.url == "https://uhome-sgp.haieriot.net/uplussea/accounts/v1/user/refreshToken"
    assert req.body == '{"refreshToken":"2_RT"}'          # compact, single field
    assert req.headers["zoneInfo"] == "66"                 # the piece that fixes retCode 30003
    assert req.headers["clientId"] == "8E57TERMINAL"       # per-install terminal id
    assert req.headers["sign"] == device_center_sign(
        "MB-UZHSH", "secretKey!!", req.headers["timestamp"], req.body,
        "/uplussea/accounts/v1/user/refreshToken",
    )
    # parsed result + the client's access token is refreshed in place
    assert result.access_token == "2_NEWACCESS"
    assert result.refresh_token == "2_RT" and result.expires_in == 863999
    assert cloud.access_token == "2_NEWACCESS"


async def test_refresh_token_bad_retcode_raises() -> None:
    cap = Capture(Response(200, json.dumps({"retCode": "30003", "retInfo": "Authorization exception"})))
    cloud = HaierCloud(AppCredentials("a", "k", "c"), "T", transport=cap)
    with pytest.raises(CloudError):
        await cloud.refresh_token("2_RT")


async def test_get_digital_model_parses_stringified_detailinfo() -> None:
    # the model comes back as a stringified JSON under detailInfo[deviceId]
    import json as _json
    model = {"attributes": [{"name": "operationMode", "valueRange": {"type": "LIST"}}]}
    resp = _json.dumps({"retCode": "00000", "detailInfo": {"DEV1": _json.dumps(model)}})
    cap = Capture(Response(200, resp))
    cloud = HaierCloud(AppCredentials("a", "k", "CID"), "TOKEN", transport=cap)

    out = await cloud.get_digital_model("DEV1")

    assert cap.request.method == "POST"
    assert cap.request.url == "https://uws-sgp.haieriot.net/shadow/v1/devdigitalmodels"
    assert cap.request.body == '{"deviceInfoList":[{"deviceId":"DEV1"}]}'
    assert out == model  # parsed dict, ready for profile_from_device_config


async def test_list_devices_v2_parses_account_devices() -> None:
    # mirrors the live device-list shape: baseInfo.{deviceId,deviceName,deviceType,wifiType,isOnline}
    resp = json.dumps({"retCode": "00000", "data": {"deviceInfos": [
        {"baseInfo": {"deviceId": "ACB722AABBCC", "deviceName": "Downstairs",
                      "deviceType": "0201203a", "wifiType": "200861UPLUS", "isOnline": True}},
        {"baseInfo": {"deviceId": "ACB722DDEEFF", "deviceName": "Upstairs",
                      "deviceType": "0201203a", "wifiType": "200861UPLUS", "isOnline": False}},
    ]}})
    cap = Capture(Response(200, resp))
    cloud = HaierCloud(AppCredentials("a", "k", "CID"), "TOKEN", transport=cap)

    devices = await cloud.list_devices_v2()

    assert cap.request.method == "GET"
    assert cap.request.url == "https://uhome-sgp.haieriot.net/uplussea/devices/v2/user/devices"
    assert [d.device_id for d in devices] == ["ACB722AABBCC", "ACB722DDEEFF"]
    assert devices[0].name == "Downstairs" and devices[0].online is True
    assert devices[0].device_type == "0201203a" and devices[0].uplus_id == "200861UPLUS"
    assert devices[1].online is False


def test_strip_signed_config() -> None:
    from haismart_extractor.cloud import strip_signed_config
    body = '{"attributes":[{"name":"onOffStatus"}]}'
    assert strip_signed_config("a" * 64 + body) == {"attributes": [{"name": "onOffStatus"}]}  # signed
    assert strip_signed_config(body) == {"attributes": [{"name": "onOffStatus"}]}              # bare


async def test_get_device_config_looks_the_file_up_then_downloads_it() -> None:
    """A device model is not fetched by name: the resource service is asked for it and answers with
    a URL carrying a build stamp no caller could construct, plus the file's MD5."""
    signed = "a" * 64 + json.dumps({
        "attributes": [{"name": "operationMode", "writable": True}],
        "modifiers": [{"trigger": {}, "actions": []}],
    })
    listing = json.dumps({"retCode": "00000", "data": {"resources": [{
        "name": "HSU-24VRRA03TF@2008610",
        "resUrl": "https://cdn/constraintfile/HSU-24VRRA03TF@2008610_20231016061617347.signed.json",
        "resVersion": "2.0.1",
        "md5": hashlib.md5(signed.encode()).hexdigest(),
    }]}})

    seen: list[Request] = []

    async def transport(request: Request) -> Response:
        seen.append(request)
        return Response(200, listing if request.method == "POST" else signed)

    cloud = HaierCloud(AppCredentials("a", "k", "c"), "T", transport=transport)
    cfg = await cloud.get_device_config("HSU-24VRRA03TF", "2008610", prod_no="AAC1UKZ01")

    assert seen[0].method == "POST"
    assert seen[0].url.endswith("/uplussea/resources/v1/conf/list")
    # model and typeId are both required -- the lookup returns nothing for either on its own
    assert json.loads(seen[0].body)["model"] == "HSU-24VRRA03TF"
    assert json.loads(seen[0].body)["typeId"] == "2008610"
    assert seen[1].method == "GET" and seen[1].url.endswith("_20231016061617347.signed.json")
    # and it returns the sections the device shadow does not carry
    assert cfg["modifiers"] and cfg["attributes"][0]["name"] == "operationMode"


async def test_get_device_config_picks_the_right_device_out_of_the_listing() -> None:
    """The listing is scoped to the account, not to the request.

    It answers with the configs published for the caller's own devices and reports success whatever
    model and typeId are sent, so an account with two air conditioners gets both back. Taking the
    first would hand one device the other's rulebook -- its modifiers would make the wrong entities
    unavailable and its alarms would name the wrong faults. The uPlusId decides, and the model
    number is not required to match: a sticker may read `HSU-24HFAB/013WUSDC(W)-T3` where the
    service says `HSU-24HFAB`.
    """
    signed = "a" * 64 + json.dumps({"attributes": [{"name": "wanted"}]})
    other = "a" * 64 + json.dumps({"attributes": [{"name": "the other AC"}]})
    listing = json.dumps({"retCode": "00000", "data": {"resources": [
        {"name": "SOME-OTHER-AC@1111", "resUrl": "https://cdn/other.signed.json",
         "md5": hashlib.md5(other.encode()).hexdigest()},
        {"name": "HSU-24HFAB@2222", "resUrl": "https://cdn/wanted.signed.json",
         "md5": hashlib.md5(signed.encode()).hexdigest()},
    ]}})

    async def transport(request: Request) -> Response:
        if request.method == "POST":
            return Response(200, listing)
        return Response(200, signed if "wanted" in request.url else other)

    cloud = HaierCloud(AppCredentials("a", "k", "c"), "T", transport=transport)
    cfg = await cloud.get_device_config("HSU-24HFAB/013WUSDC(W)-T3", "2222")
    assert cfg["attributes"][0]["name"] == "wanted"


async def test_get_device_config_refuses_a_model_the_account_does_not_have() -> None:
    """A device not in the listing must raise, not return whatever the account does have.

    Success is reported for any arguments, so a served-looking answer is not evidence the requested
    model was found. No rules at all locks nothing, which is the safe direction; another device's
    rules are not recoverable from once they are stored against this one.
    """
    listing = json.dumps({"retCode": "00000", "data": {"resources": [
        {"name": "SOME-OTHER-AC@1111", "resUrl": "https://cdn/other.signed.json"},
    ]}})

    async def transport(request: Request) -> Response:
        return Response(200, listing)

    cloud = HaierCloud(AppCredentials("a", "k", "c"), "T", transport=transport)
    with pytest.raises(CloudError, match="SOME-OTHER-AC@1111"):
        await cloud.get_device_config("HS-25VRB03", "9999")


async def test_get_device_config_refuses_a_download_that_fails_its_md5() -> None:
    """The listing publishes the file's MD5, so a truncated or swapped download is caught here
    rather than surfacing later as a model that parses but is not this device's."""
    listing = json.dumps({"retCode": "00000", "data": {"resources": [{
        "name": "M@U", "resUrl": "https://cdn/x.signed.json", "md5": "0" * 32,
    }]}})

    async def transport(request: Request) -> Response:
        return Response(200, listing if request.method == "POST" else "a" * 64 + "{}")

    cloud = HaierCloud(AppCredentials("a", "k", "c"), "T", transport=transport)
    with pytest.raises(CloudError, match="MD5"):
        await cloud.get_device_config("M", "U")


async def test_list_user_devices_uses_confirmed_path() -> None:
    cap = Capture(Response(200, json.dumps({"retCode": "00000", "data": []})))
    cloud = HaierCloud(AppCredentials("MB-UZHSH", "k", "c"), "T", transport=cap)
    await cloud.list_user_devices()
    assert cap.request is not None
    assert cap.request.url == f"https://uhome-sgp.haieriot.net{DEVICE_LIST_PATH}"
    assert cap.request.body == "{}"
    assert cap.request.headers["accessToken"] == "T"


async def test_get_device_model_posts_deviceid_and_signs() -> None:
    cap = Capture(Response(200, json.dumps({"retCode": "00000", "data": {}})))
    cloud = HaierCloud(AppCredentials("MB-UZHSH", "secret", "c"), "T", transport=cap)
    await cloud.get_device_model("DEV9")
    req = cap.request
    assert req is not None
    assert req.url == f"https://uhome-sgp.haieriot.net{DEVICE_MODEL_PATH}"
    assert req.body == '{"deviceId":"DEV9"}'
    assert req.headers["sign"] == device_center_sign(
        "MB-UZHSH", "secret", req.headers["timestamp"], req.body, DEVICE_MODEL_PATH
    )


# The refresh contract is covered by `test_refresh_token_pipeline_and_parse` above:
# uhome host, device-center-signed, body = {refreshToken}.


# --- email/password login ----
# The real SE-Asia H5 login: hybrid AES+RSA. A 16-digit key encrypts the password (AES-128-CBC, key==iv),
# and the key is RSA-wrapped into `sesame`. Endpoint uhome-sea.haieriot.net/uplussea/accounts/v2/login.


def test_encrypt_login_password_hybrid_scheme() -> None:
    import base64

    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.padding import PKCS7

    key = "1234567890123456"  # 16 digits; pinned for determinism
    pw_field, sesame = encrypt_login_password("password123", key=key)
    # password = AES-128-CBC/PKCS7 with key == iv == the 16 digit bytes
    kb = key.encode()
    ct = base64.b64decode(pw_field)
    dec = Cipher(algorithms.AES(kb), modes.CBC(kb)).decryptor()
    unp = PKCS7(128).unpadder()
    assert unp.update(dec.update(ct) + dec.finalize()) + unp.finalize() == b"password123"
    # sesame = RSA-1024 ciphertext of the key -> 128 bytes, base64
    assert len(base64.b64decode(sesame)) == 128
    # random key each call (non-deterministic) when key is not pinned
    assert encrypt_login_password("x")[0] != encrypt_login_password("x")[0]


async def test_login_request_shape_and_parse() -> None:
    creds = AppCredentials(app_id="MB-SHEYJDNYB-0001", app_key="appkey", client_id="ignored")
    # real SEA response shape: tokens under data.tokenInfo
    resp = {
        "retCode": "00000",
        "data": {"tokenInfo": {
            "accountToken": "2_uhomeAccess", "uhomeAccessToken": "2_uhomeAccess",
            "refreshToken": "2_refreshDurable", "uhomeUserId": "100000000000000001",
            "expiresIn": "863849", "zoneInfo": "66",
        }},
    }
    cap = Capture(Response(200, json.dumps(resp)))
    client, result = await HaierCloud.login(
        creds, "me@example.com", "hunter2", client_id="ABC123", zone_info="66", transport=cap
    )
    req = cap.request
    assert req is not None
    assert req.url == "https://uhome-sea.haieriot.net" + LOGIN_PATH  # the SEA login host
    body = json.loads(req.body)
    assert body["username"] == "me@example.com"     # username field carries the email
    assert "hunter2" not in req.body                # password is encrypted
    assert len(__import__("base64").b64decode(body["sesame"])) == 128  # RSA-wrapped key
    assert req.headers["zoneInfo"] == "66"          # the country/region zone that routes account lookup
    ts = req.headers["timestamp"]
    assert req.headers["sign"] == device_center_sign(
        "MB-SHEYJDNYB-0001", "appkey", ts, req.body, LOGIN_PATH
    )
    assert req.headers["clientId"] == "ABC123"      # we chose the terminal the token is bound to
    assert isinstance(result, LoginResult)
    assert result.access_token == "2_uhomeAccess"
    assert result.refresh_token == "2_refreshDurable"
    assert result.uhome_user_id == "100000000000000001"
    assert client.access_token == "2_uhomeAccess"


async def test_login_generates_uppercase_clientid_when_unset() -> None:
    resp = {"data": {"tokenInfo": {"uhomeAccessToken": "2_x", "refreshToken": "2_y"}}}
    cap = Capture(Response(200, json.dumps(resp)))
    _client, result = await HaierCloud.login(
        AppCredentials("a", "k", "c"), "u@e.com", "pw", transport=cap
    )
    assert len(result.client_id) == 32 and result.client_id == result.client_id.upper()
    assert all(ch in "0123456789ABCDEF" for ch in result.client_id)


async def test_login_bad_retcode_raises() -> None:
    cap = Capture(Response(200, json.dumps({"retCode": "30032", "retInfo": "Account is not registered"})))
    with pytest.raises(CloudError, match="30032"):
        await HaierCloud.login(AppCredentials("a", "k", "c"), "u@e.com", "pw", transport=cap)


async def test_login_no_tokens_raises() -> None:
    cap = Capture(Response(200, json.dumps({"retCode": "00000", "data": {"tokenInfo": {}}})))
    with pytest.raises(CloudError, match="no tokens"):
        await HaierCloud.login(AppCredentials("a", "k", "c"), "u@e.com", "pw", transport=cap)


async def test_login_custom_login_host() -> None:
    resp = {"data": {"tokenInfo": {"uhomeAccessToken": "2_A", "refreshToken": "2_R"}}}
    cap = Capture(Response(200, json.dumps(resp)))
    await HaierCloud.login(
        AppCredentials("a", "k", "c"), "u@e.com", "pw",
        domains=Domains(login="uhome-sea-yanshou.haieriot.net"), transport=cap,
    )
    assert cap.request is not None
    assert cap.request.url.startswith("https://uhome-sea-yanshou.haieriot.net/")


# --- HTTP transport plumbing (the event-loop-safety contract) ------------------


async def test_httpx_transport_wraps_a_caller_supplied_client() -> None:
    """A host with its own httpx client (Home Assistant) plugs it in here, so this library never
    constructs one — building a client loads the CA bundle from disk, which blocks the event loop."""
    from haismart_extractor.cloud import HTTP_TIMEOUT, httpx_transport

    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def request(self, method, url, *, headers, content, timeout):
            self.calls.append(
                {"method": method, "url": url, "headers": headers,
                 "content": content, "timeout": timeout}
            )
            return type("R", (), {"status_code": 207, "text": '{"ok":1}'})

    client = FakeClient()
    resp = await httpx_transport(client)(
        Request("POST", "https://example.test/p", {"h": "v"}, '{"a":1}')
    )
    assert (resp.status, resp.json()) == (207, {"ok": 1})
    assert client.calls == [{
        "method": "POST", "url": "https://example.test/p", "headers": {"h": "v"},
        "content": b'{"a":1}', "timeout": HTTP_TIMEOUT,
    }]


async def test_default_client_is_built_off_the_event_loop_and_reused() -> None:
    """Regression: the default transport must not construct its httpx client on the event loop
    (HA reports that as a blocking `load_verify_locations` call). It builds it in an executor
    thread, once per loop."""
    import threading
    from unittest.mock import patch

    import haismart_extractor.cloud as cloud_mod

    built_on: list[str] = []

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            built_on.append(threading.current_thread().name)

    cloud_mod._CLIENTS.clear()
    with patch("httpx.AsyncClient", FakeAsyncClient):
        first = await cloud_mod._async_default_client()
        second = await cloud_mod._async_default_client()

    assert first is second                      # one shared client per loop, not one per request
    assert len(built_on) == 1
    assert built_on[0] != threading.current_thread().name   # i.e. a worker thread, not the loop
    cloud_mod._CLIENTS.clear()


async def test_public_device_config_needs_no_account_and_renames_its_sections() -> None:
    """The same model, published a second way: a catalogue keyed on product code and open to anyone.

    `get_device_config` can only answer for the caller's own devices, so an install with no cloud
    credentials -- and a bug report about hardware nobody here owns -- gets nothing from it. This
    route answers for any product code with no token at all. It publishes an older spelling of the
    same sections, which is renamed on the way in so nothing downstream has to know there are two.
    """
    signed = "b" * 64 + json.dumps({
        "basicInfo": {"uPlusId": "2008610800820324"},
        "property": [{"name": "operationMode", "invisible": False}],
        "logicLimit": [{"trigger": {}, "actions": []}],
        "logicPatch": [{"name": "co-command"}],
        "alarm": [{"name": "F1", "description": "a fault"}],
    })
    listing = json.dumps({"retCode": "00000", "retInfo": "ok", "data": {
        "version": "3.0.1",
        "url": "https://resource/constraintfile/AAD180E00_20250217172728982.json",
        "md5": hashlib.md5(signed.encode()).hexdigest(),
    }})
    seen: list[Request] = []

    async def transport(request: Request) -> Response:
        seen.append(request)
        return Response(200, listing if request.method == "POST" else signed)

    cfg = await get_public_device_config("AAD180E00", transport=transport)

    # the whole request is the product code -- no token, no appId, nothing account-shaped
    assert seen[0].method == "POST" and seen[0].url == PUBLIC_CONFIG_URL
    assert json.loads(seen[0].body) == {"productCode": "AAD180E00"}
    assert "accessToken" not in seen[0].headers and "sign" not in seen[0].headers
    assert seen[1].method == "GET"
    # the sections that ARE carried arrive under the names every consumer here already speaks
    assert cfg["attributes"][0]["name"] == "operationMode"
    assert cfg["baseInfo"]["uPlusId"] == "2008610800820324"
    assert cfg["alarms"][0]["desc"] == "a fault"      # description -> desc, renamed in place
    # ...and the old spellings are gone, so nothing reads both
    for gone in ("property", "alarm", "basicInfo"):
        assert gone not in cfg

    # ⚠️ The rule sections are DROPPED, not renamed. Their inner schema differs from the
    # account-scoped model's, so carrying them across would yield rules that parse to nothing and
    # silently stop locking anything. No rules locks nothing, which is the safe direction.
    for unadapted in ("modifiers", "constraints", "logicLimit", "logicPatch"):
        assert unadapted not in cfg


async def test_public_device_config_refuses_an_unknown_product_code() -> None:
    """The catalogue reports success with an empty URL for a code it has never heard of, so a
    successful call is not enough to go on."""
    async def transport(request: Request) -> Response:
        return Response(200, json.dumps({"retCode": "00000", "data": {"url": ""}}))

    with pytest.raises(CloudError, match="no published model"):
        await get_public_device_config("NOSUCHCODE", transport=transport)


async def test_public_device_config_checks_the_published_md5() -> None:
    """The catalogue publishes the file's MD5, so a truncated or swapped download is caught here."""
    listing = json.dumps({"retCode": "00000", "data": {"url": "https://x/f.json", "md5": "0" * 32}})

    async def transport(request: Request) -> Response:
        return Response(200, listing if request.method == "POST" else "c" * 64 + "{}")

    with pytest.raises(CloudError, match="MD5"):
        await get_public_device_config("AAD180E00", transport=transport)


def test_public_config_carries_no_wire_positions() -> None:
    """It is the semantic model, never the byte map -- worth asserting, because the two are easy to
    conflate and a position taken from the wrong place decodes plausibly and wrongly."""
    cfg = normalize_public_config({
        "property": [{"name": "operationMode", "valueRange": {}}],
        "alarm": [], "logicLimit": [], "logicPatch": [],
    })
    for attr in cfg["attributes"]:
        assert not {"startWord", "startBit", "length"} & set(attr)
