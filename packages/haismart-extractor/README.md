# haismart-extractor

Cloud client for the Haismart (Haier SE-Asia) platform. Used by the Home Assistant integration to sign
in and to fetch each AC's per-device `localKey`.

## Modules

| Module | What it is |
|---|---|
| `src/haismart_extractor/cloud.py` | Account **email/password login** + token refresh, device list, digital model, and a device's **published model** (`get_device_config`). Device-center request signing: `SHA-256(path + strippedBody + appId + appKey + timestamp)`. |
| `src/haismart_extractor/gateway.py` | Per-device **`localKey`** fetch over the cloud MQTT gateway (`gw-sgp.haieriot.net:58702`). All CONNECT credentials are derived (`derive_client_id`, `derive_gateway_auth`). |
| `src/haismart_extractor/cloud_control.py` | **Device control** over the MQTT **user channel** (`User/<token>/Req/Attr/W|R|Op/<deviceId>`): set/read attributes and run ops by their digital-model names, for devices online through the cloud. CONNECT identity is a `"01"`+JSON username (userId/token in the body) with the same password derivation applied to the untagged body (`derive_cloud_control_auth`). |

**A device hands out two descriptions of itself, and both are needed.** `get_digital_model` returns
its *shadow* — attributes, value ranges, enums and current values — and carries **no rules at all**.
The rules that say which settings a unit ignores in which state, what its faults are called, and which
commands imply others live in its **published model**, fetched separately by `get_device_config` and
merged onto the shadow. Its URL cannot be constructed: the resource service is asked for a listing and
answers with one, the file is downloaded and checked against the MD5 it gives.

The CONNECT `username`/`password` are derived, not stored (`derive_gateway_auth`):
`username = "01" + 8 digits`, `password = hex(AES-128-CBC(MD5(body), iv=0, BE16(9)+"haier_sdk" padded))`.
The gateway recomputes the password from the username, so a freshly generated pair connects.

The **user channel** (`cloud_control.py`) uses the same broker and password derivation, but the username
is `"01"` + a compact JSON identity blob (`{"protocolVers","clientId","connType":"MqttUsdk",
"svcVers","libVers":"UCP-MQTT-UACP","userAGpType","appId","appVers","userId","token"}`) and the
password pre-image is that blob **without** the `"01"` tag. Control: subscribe `User/<token>/#` first,
then publish to `User/<token>/Req/Attr/W|R/<deviceId>` (write/read) or `Req/Op/<deviceId>`, with the
reply on `User/<token>/Resp/...` echoing the `sn` and carrying `errNo` (`0` ok, `14` invalid user,
`15` device not found, `16` device offline).

## Example

```python
import asyncio
from haismart_extractor import (
    HaierCloud, SEA_APP_CREDENTIALS, GatewayCreds, get_localkey_via_gateway,
    CloudControlCreds, CloudControlClient,
)

async def main():
    cloud = HaierCloud(SEA_APP_CREDENTIALS)
    login = await cloud.login("you@example.com", "password", zone="66")
    creds = GatewayCreds.derive(usdk_client_id=login.client_id, access_token=login.access_token)
    key = get_localkey_via_gateway(creds, "ACB722AABBCC")
    print(key)

    ccreds = CloudControlCreds.derive(
        usdk_client_id=login.client_id, user_id=login.uhome_user_id,
        access_token=login.access_token,
    )
    client = CloudControlClient(ccreds)
    client.set_attribute("ACB722AABBCC", "onOffStatus", 1)     # errNo 16 = device offline
    print(await asyncio.to_thread(client.get_attribute, "ACB722AABBCC", "targetTemperature"))

asyncio.run(main())
```

## Tests

```bash
python -m pytest
```
