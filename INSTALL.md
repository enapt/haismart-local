# Installing the Haismart integration on your Home Assistant

Fully-local control of Haier ACs that pair with the **Haismart** (Haier U+/uHome SE‑Asia) app — no cloud at
runtime after setup. This guide gets the integration onto a running Home Assistant for real use/testing.

> **Not on HACS yet.** The integration depends on two helper libraries (`haismart-hrdp`, `haismart-extractor`)
> that aren't published to PyPI, so HA can't auto-install them. `scripts/install-dev.sh` handles that by
> pip-installing them into HA's Python env; then HA sees the `manifest.json` requirements already satisfied.

## Prerequisites

- **Home Assistant** running, **on the same LAN as the ACs** (they answer on TCP `:56800`). Runtime is local;
  the cloud is touched only at setup and on key rotation.
- **A Haismart account.** Easiest is an **email/phone + password** account. If you sign in with **Google/
  Facebook** (no password), create a throwaway email/password Haier account, **share your AC(s) to it** in
  the app, and log in with that account — sharing grants the same local access as ownership.
- `cryptography` and `httpx` are already shipped with HA — nothing else to install.

## 1. Install

### HACS (recommended)

In **HACS → ⋮ → Custom repositories**, add `https://github.com/cantruchd/haismart` with category
**Integration**. Install **Haismart (Haier local)**, then **restart Home Assistant**. The component is
self-contained (the two helper libraries are vendored into it), so there is **no pip step**.

### Manual copy

Copy the repo's root [`custom_components/haismart/`](custom_components/haismart) folder into your
`<config>/custom_components/` and restart Home Assistant. It's self-contained — nothing to pip-install.
(This is the same vendored drop-in HACS installs.)

### From source (development)

Run from a checkout of this repo. The script pip-installs the two libs **into HA's Python env** and copies the
component into `<config>/custom_components/`.

### Home Assistant Core / venv
```bash
scripts/install-dev.sh --config ~/.homeassistant --python /srv/homeassistant/bin/python
```
Point `--python` at the interpreter of the venv where `homeassistant` is installed (so the libs land where HA
imports from). `--config` is the directory holding `configuration.yaml`.

### Home Assistant Container (Docker)
Run it **inside** the container so the libs go into the container's Python:
```bash
docker cp . homeassistant:/tmp/haismart          # or bind-mount the repo
docker exec -it homeassistant bash -lc \
  'cd /tmp/haismart && scripts/install-dev.sh --config /config --python python3'
```

### Home Assistant OS / Supervised
You can't easily pip-install into the core container here — this is the one awkward case. For testing,
use a **Core/venv or Container** instance (even a spare one on the same LAN). Vendoring the two pure-Python
libs into the component is the eventual HAOS fix, but that's packaging work, not covered by this script.

### Options
- `--symlink` — symlink the component instead of copying (edits apply on the next HA restart; handy for dev).
- `--copy-only` — skip the pip step (only if the two libs are already importable in HA's env).
- `PYTHON=<exe>` — same as `--python`.

Then **restart Home Assistant.**

## 2. Add the integration

**Settings → Devices & Services → Add Integration → "Haismart (Haier local)"** (it may also appear on its own
via zeroconf, since it listens for `_cae._udp`). Pick one path:

- **Login (recommended) — no key to paste:** email/phone + password + the **country your Haier
  account was registered in**, picked from a list (it is the phone dialling code underneath, and it
  defaults to your Home Assistant instance's own country). It then **lists your ACs to pick from**, and for the one you
  choose it **fetches the localKey from the cloud automatically** — you never paste a key — and **finds the
  AC's IP via DHCP** (the deviceId is the AC's MAC). You only enter the IP if HA hasn't seen the AC on the
  network yet (then find it in your router's client list).
  **Google/Facebook owners** (no password): create a throwaway email/password Haier account, **share your
  AC(s) to it** in the app, and log in with that account here.
- **Manual:** host + device ID + `localKey` directly (no cloud; fully offline, but a key rotation then needs a
  manual re-enter instead of self-healing).

The flow validates by doing a live read, then creates the entities.

**Multiple ACs (e.g. Upstairs + Downstairs):** each AC is its own HA device, added one at a time. After you
add the first, run **Add Integration → Haismart** again — the picker now shows only the AC(s) you haven't
added yet (and says so once they're all in). Each AC is also **DHCP-discovered** (Haier's Wi-Fi
modules use a number of MAC prefixes; the integration matches all the appliance ones it knows),
so both will appear as "Discovered" cards you can add directly.

## 3. Verify

You should get, per AC: a **climate** card (temperature, mode, fan, swing, on/off), five **switches**
(strong / quiet / health / sleep / display light), an **eco** select, and indoor/outdoor **temperature**
sensors. Change the setpoint — the AC applies it and the card confirms from the AC's own reply immediately.

## 4. Optional: go fully cloud-independent (block Haier's servers)

**Everything already runs locally after setup** — reads and control never touch Haier. The *only* runtime
cloud dependency is that Haier's server can **rotate the per-device `localKey`** (which the integration then
re-fetches). If you'd rather the units never phone home at all, you can block Haier's cloud — then the key
can't rotate and your stored key stays valid indefinitely. This is **optional** and for advanced users.

**The key fact:** a key rotation is *pushed to the AC over the AC's own cloud connection*. So you must block
**the AC's** internet access, not just Home Assistant's. Keep the AC's **LAN** open (HA still needs `:56800`).

> ⚠️ **The most common way this goes wrong:** reaching for a router feature called *MAC filtering* or
> *IP/port filtering*. Those usually remove the device from the **network altogether** — it disappears
> from your LAN, Home Assistant loses it, and local control stops. You want to block a *destination*
> (Option A), not a device. If everything for that AC goes **unavailable** rather than the Cloud
> connection sensor going **off**, that is what has happened.

> **Before blocking:** note each AC's current key/version — from HA go **Settings → Devices & Services →
> Haismart → the device → Diagnostics** (redacted), or run `probe_localkey_version(ip, deviceId)`. Keep a
> copy as your escape hatch; you can always re-add via the **manual** path (host + deviceId + key), no cloud.

### Option A — block the gateway address (recommended)

Add a firewall rule denying traffic **to `43.156.75.60`** — Haier's MQTT gateway
(`gw-sgp.haieriot.net:58702`). Source can be the air conditioners, or everything on your LAN if your
router only does destination rules.

This is the recommended method for two reasons. It is **proven sufficient**: that single address
carries both the app's gateway *and* the air conditioners' own uplink, and blocking it takes a unit
offline (confirmed against Haier's own device list, which reported the units as offline for the
duration). And because the rule is scoped to a **destination**, it cannot accidentally cut the units
off your LAN — which is the failure mode below.

If you apply it LAN-wide, note that Home Assistant also loses its ability to fetch a fresh key. That
is harmless here — a blocked AC never rotates its key, so there is nothing to fetch — but it does mean
you should lift the rule before deliberately re-keying anything.

### Option B — per-device WAN block (only if your router really separates WAN from LAN)

Deny **internet** for each AC by MAC or reserved IP, while allowing LAN. This catches any hardcoded
address, so it is airtight in principle.

> ⚠️ **Check what your router's feature actually blocks.** Router options named *MAC filtering*,
> *IP filtering* or *IP/port filtering* frequently block the device from the **network entirely**, not
> just from the internet — the AC drops off your LAN, Home Assistant loses it, and local control stops.
> That looks exactly like the integration breaking. If the `Cloud connection` sensor goes *unavailable*
> rather than *off*, and your other entities go unavailable too, that is what has happened: the rule is
> too broad. Use Option A instead, or a rule that explicitly permits your LAN subnet **before** denying
> everything else — order matters.

Blocking by **MAC** is worth preferring over IP where your router offers both: these modules move on
DHCP, and an IP-based rule silently stops applying when they do, leaving you thinking a unit is
blocked when it isn't.

### Not recommended — DNS blocking

Blocking `*.haieriot.net`, `*.haier.net` and `*.haigeek.com` on Pi-hole or AdGuard **will not reliably
stop the air conditioners.** The modules connect to the gateway by a cached IP address and do not
appear to resolve it at connection time, so a DNS blackhole can leave the unit connected while
convincing you it is cut off. It still has some value for stopping the *phone app* from reaching
Haier, but do not use it as your isolation mechanism — and if you do use it, verify with the sensor
below rather than assuming.

### Verify it holds
1. **Watch the AC's own `Cloud connection` sensor** (diagnostic, one per device). This is the direct
   answer: the integration asks the *air conditioner* whether it can still reach Haier, over a local
   unauthenticated query on UDP `:7083` that never contacts Haier itself. When your block is working the
   sensor reads **off**. Give it ~2 minutes — the AC only notices once a keepalive expires, and its
   `raw_state` attribute passes through `retrying` before settling on `disconnected`. (Coming back is
   faster: about 10 seconds.) If it stays **on**, the AC is still getting out → use Option B.
2. Confirm local read/control still works right after blocking (some IoT gear sulks without cloud — these
   don't, but check): change the setpoint in HA.
3. Confirm the key stops rotating. A cut-off unit does **not** rotate at all. So a `Local key` version
   that hasn't moved in a day is corroboration — but the sensor in step 1 is the signal, since a quiet
   period proves nothing on its own (a connected but idle unit can also go a week without rotating).

### What you keep, and what you give up

Confirmed on hardware, with the block sustained:

| | |
|---|---|
| Reading and control over `:56800` | **unaffected** — setpoint, mode, fan, switches all work normally |
| The stored local key | stays valid; a cut-off unit does not rotate it |
| The `Cloud connection` sensor | reports `off` — this is the state you want |
| The vendor phone app | stops working for that unit; it is cloud-only |
| Automatic re-keying | unavailable, and unnecessary while the unit stays blocked |
| Adding a *new* or factory-reset AC | needs the cloud, so lift the rule first |

Blocking and unblocking is **not destructive**: units recover on their own within about ten seconds of
the rule being removed, with no re-pairing.

## 5. Optional: survive a Haier shutdown (future-proofing)

"What if Haier discontinues the service?" — a device you **already control keeps working**. The localKey is
stored on the AC; with no server to push a rotation, your key stays valid, and the integration drives the AC
locally forever. To be fully immune:

1. **Archive every AC's localKey now** (while the cloud is alive). Each AC has a **Local key** diagnostic
   sensor (disabled by default). Enable it on the device page → its state is the key and its attributes
   carry host + deviceId + version + model ID. It then rides along in your HA backups automatically. Keep
   those safe — the key grants ongoing local control. (The **Model ID** sensor shows the same identifier
   without exposing the key, and is on by default; both are in your backups either way, since the values
   are stored with the integration's settings.)
2. **Onboard each AC via the config-flow `manual` path** (host + deviceId + key from the backup). Manual needs
   **zero cloud** — no login, no gateway — so nothing depends on Haier being up. The model ID it needs to
   decode your unit correctly is read from the air conditioner itself, so a manual setup is now as accurate
   as one done through an account.
3. **Firewall the ACs** (§4) so the key never rotates.

That's it — those ACs are now Haier-independent. **The one thing this doesn't cover** is *factory-resetting* or
adding a *brand-new* AC after Haier is gone (a wiped device has no key and normally fetches one from the cloud).
Workarounds for that narrow case: run your **own** key-issuing server (a large, hardware-gated project) or,
as the guaranteed floor, flash **ESPHome** onto the module.

## Troubleshooting

- **HA log: "Requirements for haismart not found" / import errors.** The two libs landed in a different Python
  than HA's. Re-run `install-dev.sh` with `--python` pointing at HA's interpreter (Core/venv: the venv's
  `bin/python`; Docker: run inside the container).
- **"No decodable status" / entities unavailable right after adding.** Two different causes, and
  recent versions tell them apart for you. If the climate entity works but the temperatures are
  missing and a repair notification has appeared, the AC's **report layout is not one we know yet**
  — the key is fine; please report the model (see [`docs/new-model.md`](docs/new-model.md)).
  Otherwise it is a **stale `localKey`** — it
  rotates server-side. The login/cloud paths auto-refetch it; the manual path will prompt a reauth (and raise
  a repair suggesting you add account creds so it self-heals next time).

  If it persists, turn on debug logging for the integration:

  ```yaml
  # configuration.yaml
  logger:
    logs:
      custom_components.haismart: debug
  ```

  Each failed cycle then logs which cause it is — the wording tells them apart:

  | Log says | Means |
  |---|---|
  | `nothing decrypted this cycle` | the key is wrong/stale, **or** the AC pushed no status at all |
  | `localKey is good … unrecognised frame` | the key is fine, but what the AC pushed isn't a status report (no `2715` signature, or too short) |

  Note an unrecognised report **length** does not appear here at all: that case decodes partially and
  raises the repair notification described above, so it is already named for you. Either way the log
  line includes the frame — please open an issue with it if the entity stays unavailable. It carries
  device state only, no key.
- **The AC changed IP address.** Handled automatically: after a failed read the integration
  broadcasts a local discovery query, recognises the unit by its device ID wherever it has landed,
  and updates the entry to follow it — usually within the same poll, so you see nothing at all. A
  DHCP reservation is still worth setting, but is no longer required.
- **Can't reach the AC.** Confirm HA and the AC are on the same subnet and `:56800` is open:
  `nc -z <ac-ip> 56800`. The integration finds the AC by **DHCP** (matching Haier's appliance MAC
  prefixes) or the host you
  provide; if you blocked the AC's WAN (§4), make sure you left its **LAN** open.
- **Login rejected.** The integration now names the likely cause rather than listing all three
  fields. "No Haier account … in the country you selected" (retCode 30032) means the **country** is
  almost certainly wrong: it is the one the account was *registered* in, which need not be where you
  live or where the AC is. A missing-field error is retCode 10001. If sign-in succeeds but no devices
  appear, the account has none bound — share the AC to it in the app first.

## Uninstall

Remove the integration in the UI, then delete `<config>/custom_components/haismart/`. (The helper libs pip-
installed into HA's env are harmless to leave; `pip uninstall haismart-hrdp haismart-extractor` removes them.)
