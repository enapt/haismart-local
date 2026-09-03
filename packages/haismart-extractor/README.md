# haismart-extractor

Cloud client for the Haismart (Haier SE-Asia) platform. Used by the Home Assistant integration to sign
in and to fetch each AC's per-device `localKey`.

## Modules

| Module | What it is |
|---|---|
| `src/haismart_extractor/cloud.py` | Account **email/password login** + token refresh, device list, digital model, and a device's **published model** (`get_device_config`). Device-center request signing: `SHA-256(path + strippedBody + appId + appKey + timestamp)`. |
| `src/haismart_extractor/gateway.py` | Per-device **`localKey`** fetch over the cloud MQTT gateway (`gw-sgp.haieriot.net:58702`). All CONNECT credentials are derived (`derive_client_id`, `derive_gateway_auth`). |

**A device hands out two descriptions of itself, and both are needed.** `get_digital_model` returns
its *shadow* — attributes, value ranges, enums and current values — and carries **no rules at all**.
The rules that say which settings a unit ignores in which state, what its faults are called, and which
commands imply others live in its **published model**, fetched separately by `get_device_config` and
merged onto the shadow. Its URL cannot be constructed: the resource service is asked for a listing and
answers with one, the file is downloaded and checked against the MD5 it gives.

The CONNECT `username`/`password` are derived, not stored (`derive_gateway_auth`):
`username = "01" + 8 digits`, `password = hex(AES-128-CBC(MD5(body), iv=0, BE16(9)+"haier_sdk" padded))`.
The gateway recomputes the password from the username, so a freshly generated pair connects.

## Example

```python
import asyncio
from haismart_extractor import HaierCloud, SEA_APP_CREDENTIALS, GatewayCreds, get_localkey_via_gateway

async def main():
    # zone_info is the dialling code of the country the account was registered in
    cloud, login = await HaierCloud.login(
        SEA_APP_CREDENTIALS, "you@example.com", "password", zone_info="66"
    )
    creds = GatewayCreds.derive(usdk_client_id=login.client_id, access_token=login.access_token)
    key = get_localkey_via_gateway(creds, "A1B2C3D4E5F6")
    print(key)

asyncio.run(main())
```

## Tests

```bash
python -m pytest
```
