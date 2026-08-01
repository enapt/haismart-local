# ha-haismart

Native Home Assistant integration for Haier ACs, built on [`haismart-hrdp`](../haismart-hrdp). No
MQTT, no YAML.

**Full local control.** The integration handshakes each AC over uSS `:56800`, decrypts its status
pushes, and both reads AND controls it locally (`iot_class: local_polling`) via the grSetDAC group-set
write path. No cloud at runtime.

## What it provides

- **Config Flow** (`config_flow.py`): a menu offers two onboarding paths — **login** or **manual**.
  - *Login* (**email/phone + password + region**): signs in with your Haismart account directly —
    `HaierCloud.login`, the SE-Asia H5 login (hybrid AES+RSA, `zoneInfo`=region code). This is the "just
    sign in like the app" path. **Google/Facebook accounts** have no password: create a throwaway
    email/password account, **share your AC(s) to it** in the app, and sign in with that account.
  - After sign-in the flow **lists your devices to pick from**, and for the picked AC it **fetches the
    `localKey` from the cloud gateway** (all CONNECT creds derived) — no key to paste — and **resolves the
    AC's LAN IP from HA's DHCP/ARP data** (`aiodiscover`), so typically nothing is entered at all. It asks
    for the IP only if HA hasn't seen the AC yet, and falls back to the manual key form if the gateway fetch
    fails. (Same "cloud fetches the key" model as LocalTuya's cloud-assisted onboarding.)
  - *Manual*: host + device ID + `localKey` directly — the fully-offline path (no account).
  - Every path validates by a **live uSS read** (handshake proves reachability, biz-data MD5 proves the key
    decrypts). **Discovery is by DHCP**: the deviceId **is** the AC's MAC, so a `dhcp`
    manifest matcher + `async_step_dhcp` surface each AC as a discovered device (host + device ID prefilled).
    (These units do **not** announce `_cae._udp` mDNS — so zeroconf discovery is
    kept only as a dormant future-proof.) The AC's `localKey` **version** is stored so the coordinator detects
    rotation and re-fetches the fresh key automatically. Options flow sets the poll interval. Unique-ID = MAC.
- **Polling coordinator** (`coordinator.py`): one `DataUpdateCoordinator` per AC. Each refresh is one
  short-lived uSS session (`async_read_status`); control ops (`async_send_control`) are seeded from the
  latest status so a group-set preserves every unchanged attribute. A stale `localKey` is silent at the
  transport layer, so after consecutive empty cycles the coordinator probes the AC's `localKey` version
  key-free; on a mismatch it **auto-refreshes the localKey from the cloud MQTT gateway**
  (`_async_gateway_refresh` — mints a fresh token, derives the gateway clientId, fetches via
  `haismart_extractor.gateway.get_localkey_via_gateway`, updates the key in place). Only if that isn't
  configured or fails does it raise `ConfigEntryAuthFailed` (→ manual reauth) **and surface a repair**
  advising the user to add account credentials so future rotations self-heal.
- **Profile-based entities**, generated from the model's `AttributeProfile` (not hardcoded per model):
  - `climate` — target temperature, HVAC mode (off / auto / cool / dry / fan-only, plus **heat** where
    the unit reports it can), fan speed, swing on both axes, **presets** (eco / sleep / boost), on/off.
    Controls go *unavailable* in the states the unit's own model says it discards them in.
  - `switch` ×5 — **strong** (rapid), **quiet** (mute), **health**, **sleep**, **lamp** (front display).
  - `select` ×3 — **eco** (off / level 1..3), and **up-down** / **left-right vane**, each offering the
    stops that unit's model publishes, on the families that pack a vane as a position rather than a flag.
  - `sensor` — indoor + outdoor temperature, and **who last changed it** (handset / panel / network).
  - `sensor` — **Energy** (kWh), on the units that keep a running total themselves. Most carry the
    register and never populate it; there it reads *unavailable* rather than a permanent zero.
  - `sensor` ×5 + `binary_sensor` ×2 (diagnostic) — running **power**, compressor **current** and
    **frequency**, the **coil** and **outdoor air-outlet** temperatures, and whether the
    **compressor** / indoor
    **fan** are running. From a second frame that only some units answer; absent on the rest.
  - `binary_sensor` — **Self-clean** (is a cycle running) and **Fault**, whose attributes name the
    active faults with the service code the unit displays.
  - `sensor` — **Model ID** (diagnostic): the `uPlusId` that selects the report layout. Its own entity
    rather than an attribute of the localKey sensor, because it is a model identifier and not a secret —
    reading it should not require enabling an entity whose state is your key. The state is shortened
    (the identifier is 64 characters and overflows an entity row; HA has no string equivalent of
    `suggested_display_precision`), with the exact value on the `uplus_id` attribute.
  - `binary_sensor` — **Cloud connection**: whether the AC itself can still reach Haier, asked over a
    key-free local query (UDP `:7083`) that never contacts Haier. Verifies a firewall block; reads
    *unknown*, never a fabricated "disconnected", on a unit that doesn't answer it.
  - `sensor` — **Local key** (backup/export): the AC's current localKey, **diagnostic + disabled by
    default** (it's a secret). Enable it to see/copy the key — it then rides along in HA backups, and its
    attributes carry everything the **manual** onboarding path needs (host + deviceId + version +
    `uPlusId`, also its own **Model ID** sensor), so you stay Haier-independent even if the account/cloud ever disappears. Stays current
    across key rotation.
- **Finds a unit that moved**: these modules change address on DHCP, which otherwise looks exactly like
  an AC that died. After a failed read the coordinator looks the unit up by its deviceId (= MAC) via
  ARP/DHCP, falling back to a `:7083` broadcast, and updates the entry to follow it — normally within
  the same poll, so nothing goes unavailable.
- **Learns its own model ID**: the `uPlusId` that selects the report layout is read from the device, so
  a fully offline (manual) install decodes exactly as accurately as a cloud-onboarded one.
- **Write safety** (two gates): every field/value is gated by the library's confirmed encoder (it
  raises rather than send anything not in its allowlist), **and** the coordinator
  validates every change against the device's pulled **digital model** (`validate_write` — writable + temp
  range + allowed enums) before encoding. No path sends a guessed or out-of-spec frame.
- **Repairs** (`homeassistant.helpers.issue_registry`): an actionable issue is raised when a `localKey`
  rotation forces a manual re-key (no cloud creds to auto-heal); it self-clears once a gateway refresh or a
  successful reauth restores a working key.
- **Diagnostics** (`diagnostics.py`): redacted snapshot (keeps the decrypted status bytes for offset
  debugging; redacts the key + device ID).

## Install

The integration lives at `custom_components/haismart/` in this package and requires `haismart-hrdp`
and `haismart-extractor` (declared in `manifest.json` `requirements` — the extractor provides the cloud
login/token refresh + gateway localKey fetch). Neither is on PyPI yet, so they must be installed into
HA's Python env (HA can't auto-fetch them).

**One command:** from a repo checkout, [`scripts/install-dev.sh`](../../scripts/install-dev.sh) pip-installs
both libs into HA's env and copies the component — full guide + per-install-type notes in
[`INSTALL.md`](../../INSTALL.md):

```bash
scripts/install-dev.sh --config ~/.homeassistant --python /srv/homeassistant/bin/python
```

**Manual:** copy `custom_components/haismart/` into `config/custom_components/`, `pip install` **both**
`haismart-hrdp` and `haismart-extractor` into HA's Python env, restart HA, then add **Haismart (Haier
local)** from the UI.

**HACS:** HACS custom repositories require the integration at the *repository root* (root-level
`custom_components/` + `hacs.json`). This package is the source of truth; the repo root carries a
generated, ready-to-install copy with the helper libraries vendored inside it (produced by
[`scripts/build-hacs.sh`](../../scripts/build-hacs.sh) — re-run it after changing anything here). Install
from the repo root via HACS as a custom repository, or use the manual copy above.

## Develop / test

```bash
pip install homeassistant pytest-homeassistant-custom-component
python -m pytest -q     # skip cleanly if the HA plugin isn't installed
```

Installing the HA plugin into the shared `.venv` also pulls in `pytest-socket`, which disables
sockets globally; the `haismart-hrdp` conftest re-enables loopback so all three suites still run in
one venv.
