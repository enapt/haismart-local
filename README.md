# Haismart Local — Haier air conditioners in Home Assistant, with no cloud

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Release](https://img.shields.io/github/v/release/enapt/haismart-local?color=green)](https://github.com/enapt/haismart-local/releases/latest)
[![Validate](https://img.shields.io/github/actions/workflow/status/enapt/haismart-local/validate.yml?branch=main&label=validate)](https://github.com/enapt/haismart-local/actions/workflows/validate.yml)
[![License](https://img.shields.io/github/license/enapt/haismart-local)](LICENSE)

_Control your Haier air conditioner from Home Assistant entirely over your own network. You sign in
once so the integration can fetch your unit's key — after that it talks only to the AC, on your LAN._

**🌐 Getting started in your language:** [Bahasa Indonesia](docs/i18n/README.id.md) ·
[ไทย](docs/i18n/README.th.md) · [Tiếng Việt](docs/i18n/README.vi.md) ·
[Bahasa Melayu](docs/i18n/README.ms.md)\
_The integration's own screens are translated into 30 languages — including Urdu, Hindi, Bengali,
Tamil, Arabic and Persian — and follow whatever language you've set in Home Assistant. These docs are
English-only; the pages above cover install and setup._

<details>
<summary><b>Table of contents</b></summary>

- [Is my air conditioner supported?](#is-my-air-conditioner-supported)
- [What you get](#what-you-get)
- [Before you install](#before-you-install)
- [Installation](#installation)
- [Set up your air conditioner](#set-up-your-air-conditioner)
- [Automation examples](#automation-examples)
- [Going fully cloud-independent](#going-fully-cloud-independent)
- [Troubleshooting](#troubleshooting)
- [Before you open an issue](#before-you-open-an-issue)
- [Contributing](#contributing)
- [Credits](#credits)
- [How sign-in works](#how-sign-in-works)
- [Disclaimer](#disclaimer)

</details>

> [!IMPORTANT]
> Your Haier account is used **once**, during setup, to fetch your AC's local encryption key. From
> then on Home Assistant talks directly to the air conditioner over TCP port 56800 on your LAN.
> Reading state and sending commands never leave your network — and keep working if your internet
> does not.

## Is my air conditioner supported?

**The app you use is what matters, not the country you're in.** If your AC pairs with the
**Haier / Haismart** app (also branded *Haier U+* or *uHome*), you're in the right place. Despite
the "SE-Asia" label the platform carries internally, accounts registered well outside that region
work fine — this is used daily on an account registered outside South-East Asia.

| Your app | Supported here? | Use instead |
|---|---|---|
| **Haier / Haismart / Haier U+ / uHome** | ✅ **Yes** | — |
| hOn (mostly Europe) | ❌ No — these modules don't open port 56800 at all | [Andre0512/hon](https://github.com/Andre0512/hon) |
| Haier 智家 (mainland China) | ❌ No — different cloud | [banto6/haier](https://github.com/banto6/haier) |
| SmartHQ (US / GE Appliances) | ❌ No — different platform entirely | — |
| SmartAir2 / Smart Clima (older units) | ❌ No — same port, older unencrypted protocol | [oxystin/homebridge-haier-air-conditioner](https://github.com/oxystin/homebridge-haier-air-conditioner) |

**Confirmed working units** are listed in [`DEVICES.md`](DEVICES.md). Yours not there? It will very
likely still work — the integration builds itself from the model description your AC's own cloud
profile provides, rather than from hard-coded per-model tables. If something decodes oddly, that's a
[great issue to open](#before-you-open-an-issue), and usually a quick fix.

**Quick check:** if `nc -z <your-ac-ip> 56800` succeeds, the local protocol is listening.

## What you get

One device per air conditioner, with:

| Entity | What it does |
|---|---|
| **Climate** | Temperature setpoint, mode (cool / heat / dry / fan-only / auto), fan speed, swing, preset (eco / sleep / boost), on/off |
| **Indoor temperature** | The AC's own room-temperature reading |
| **Outdoor temperature** | Outdoor probe, on units that have one |
| **Switches** | Strong, Quiet, Health, Sleep, Display light |
| **Eco** | Eco level, on models where it's confirmed |
| **Power** *(diagnostic)* | Live power draw in watts, on units that report it |
| **Compressor current / frequency** *(diagnostic)* | What the outdoor unit is actually doing |
| **Coil / discharge temperature** *(diagnostic)* | Evaporator and compressor-discharge temperatures |
| **Compressor / Fan** *(diagnostic, on/off)* | Whether the compressor and indoor fan are actually running |
| **Model ID** *(diagnostic)* | The identifier that selects your unit's report layout. Shown shortened (it's 64 characters); the exact value is on the entity's `uplus_id` attribute — quote that in a bug report about a model that isn't decoded |
| **Cloud connection** *(diagnostic, on/off)* | Whether the AC itself can still reach Haier's servers — see [going fully cloud-independent](#going-fully-cloud-independent) |
| **Local key** *(diagnostic, off by default)* | Your unit's key, so it rides along in HA backups |

Which of these appear depends on your model — the integration only exposes controls it can actually
drive on your unit, rather than showing buttons that do nothing.

The climate entity also carries **presets** for the three comfort modes — eco, sleep and boost — so
they work from the thermostat card, from a voice assistant and from `climate.set_preset_mode`, not
only from the switches. A preset is exclusive: choosing one clears the others in a single write to
the AC. The switches and the Eco select are still there for the individual fields and for choosing
which eco level you want.

**Swing** comes as both controls Home Assistant offers. The four-way one (off / up-down / left-right
/ both) moves the two vanes together and is unchanged; alongside it, `climate.set_swing_horizontal_mode`
moves the left-right vane on its own, without touching the up-down one. Units whose left-right
position we haven't confirmed get only the four-way control.

Not everything the air conditioner reports becomes an entity — its **firmware version**, for
instance, is a property of the unit rather than a reading that changes, so it appears on the device
page and in a diagnostics download instead of as a sensor that would never move.

### Energy monitoring

Units that report their power draw get a **Power** sensor in watts. That is a live reading, so it
records into Home Assistant's history and long-term statistics on its own — but the **Energy
dashboard** needs a running total in kWh, which is a different thing.

To get one, add a Riemann-sum integral helper over the power sensor:

1. **Settings → Devices & services → Helpers → Create helper → Integral sensor**
2. Pick your AC's **Power** sensor as the input
3. Metric prefix **k** (kilo), time unit **hours** — that gives you kWh
4. Method: **Trapezoidal** is the sensible default for a value that ramps

Then add the resulting kWh sensor under **Settings → Dashboards → Energy → Individual devices**.

Two things worth knowing before you trust the numbers:

- **Check the helper's state class is `total_increasing`.** If the Energy dashboard will not offer
  your new sensor, this is almost always why — a helper left on `total` can also produce spikes in
  long-term statistics after a restart.
- **It is an estimate, and so is the manufacturer's.** The figure comes from the unit's own current
  measurement, and integrating a value sampled every 30 seconds cannot capture everything in between.
  The vendor app's energy screens are estimates too — by their own wording they are "based on the
  operation status data of devices", and they stop counting entirely while the unit is offline. If you
  need billing-grade numbers, use a clamp meter or a metering plug.

These units keep no running energy total of their own, which is why the integration does not offer a
kWh sensor directly — there is nothing to read, so it would have to be invented.

### How often it polls

The integration polls every **30 seconds** by default (minimum 10), and you can change it under the
integration's **Configure** menu. One poll fetches everything in a single connection — status,
faults and the power figures — because these units accept only one connection at a time.

If you want a different rhythm than a fixed interval, Home Assistant has a documented way that works
for any integration: open the integration's **⋮ → System options** and turn off *Enable polling for
updates*, then drive it from an automation calling `homeassistant.update_entity` on whatever schedule
or trigger you like. That is useful if, say, you only want frequent readings while the AC is running.

Polling faster than 10 seconds is not offered on purpose: each cycle is a full connection to the
unit, and the readings simply do not change fast enough to be worth it.

The **Cloud connection** sensor is refreshed on its own slower cadence (about once a minute) inside
the same cycle. It costs one small UDP exchange rather than a connection, and the underlying state
only moves on a scale of minutes, so there is nothing to gain from asking more often.

When you change a setting, the air conditioner confirms it on that same connection, so the thermostat
card reflects the change at once instead of waiting for the next poll. The engineering readings —
power, current, frequency, the coil and discharge temperatures, compressor and fan — are not part of
that confirmation, so they keep the values from the most recent poll until the next one arrives. They
are held for at most two minutes, and cleared immediately if you switch the unit on or off, because
the figures for a running unit say nothing about one that has just stopped.

## Before you install

Worth knowing up front, so nothing surprises you:

- Home Assistant and the AC must be on the **same subnet**. There's no cloud relay to fall back on.
- The AC accepts **one local session at a time**, and each session is capped at about 17 seconds.
  Running another Haier local integration against the same unit will cause both to misbehave.
- Installing this **does not stop your AC talking to Haier**. It keeps its own cloud connection
  unless you firewall it — see [going fully cloud-independent](#going-fully-cloud-independent).
- A **DHCP reservation** for the AC is tidy but optional: if its address moves, the integration
  finds the unit again by its device ID and follows it.
- Social logins (Google / Facebook) have no password to sign in with. Create a throwaway
  email/password Haier account, **share the AC to it** in the app, and use that here — sharing grants
  the same local access as ownership.

## Installation

### Option 1 — HACS (recommended)

1. Make sure [HACS](https://hacs.xyz/) is installed.
1. Open this repository in HACS:\
   [![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=enapt&repository=haismart-local&category=integration)
1. Click **Download**, then **Download** again in the version dialog.
1. **Restart Home Assistant.** A custom integration's code is only loaded at startup — reloading the
   entry is not enough.

<details>
<summary>The button didn't work — add it by hand</summary>

1. Open **HACS** from the sidebar.
1. Three-dot menu, top right → **Custom repositories**.
1. Repository: `https://github.com/enapt/haismart-local`, type **Integration** → **Add**.
1. Search HACS for **Haismart** → **Download**.
1. Restart Home Assistant.

</details>

<details>
<summary>Option 2 — manual installation</summary>

1. Download the source of the [latest release](https://github.com/enapt/haismart-local/releases/latest).
1. Copy the `custom_components/haismart/` folder into your Home Assistant `config/custom_components/`.
1. Restart Home Assistant.

It's fully self-contained — no `pip install` step, the helper libraries are bundled.

</details>

## Set up your air conditioner

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=haismart)

Or: **Settings → Devices & Services → + Add Integration → Haismart**. If it isn't listed, hard-refresh
your browser (<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>R</kbd>).

Then pick one of two paths:

**Sign in (recommended).** Enter your Haier account email (or phone) and password, and the country
your **account** was registered in. The integration lists your air conditioners, fetches the chosen
one's key automatically, and finds it on your network — you won't paste anything.

> The country field is the **phone dialling code of the country your Haier account was created in**
> — not where the AC is installed, and not necessarily where you live now. Getting it wrong is the
> single most common setup failure, because Haier's server reports it as "account not registered",
> which reads like a wrong password.

**Manual.** Host + device ID + local key, entered directly. Completely offline — no account needed.
Use this if you already have a key (from the *Local key* diagnostic sensor, or a backup).

## Automation examples

```yaml
# Pre-cool the living room before you get home
automation:
  - alias: "Pre-cool before arrival"
    triggers:
      - trigger: zone
        entity_id: person.me
        zone: zone.home
        event: enter
    actions:
      - action: climate.set_temperature
        target: { entity_id: climate.living_room_ac }
        data: { temperature: 23, hvac_mode: cool }
```

```yaml
# Quiet mode overnight
automation:
  - alias: "AC quiet at night"
    triggers:
      - trigger: time
        at: "22:30:00"
    actions:
      - action: switch.turn_on
        target: { entity_id: switch.living_room_ac_quiet }
```

## Going fully cloud-independent

Everything already runs locally after setup. The one remaining cloud dependency is that Haier's
server can **rotate** your unit's local key, which the integration then re-fetches.

If you'd rather your AC never phoned home at all:

1. **Archive the key first.** Enable the *Local key* diagnostic sensor on the device page — its state
   is the key, and its attributes carry the host, device ID and version. It then rides along in your
   Home Assistant backups automatically.
2. **Block the AC's internet access** at your router — the simplest rule that works is denying traffic
   to `43.156.75.60`, Haier's gateway. Keep the LAN open: Home Assistant still needs port 56800.
   DNS blocking is *not* reliable here (the units connect by a cached address), and beware router
   features called "MAC filtering" or "IP filtering" — they often cut the device off your LAN entirely
   rather than just from the internet.
3. The key can no longer rotate, so your stored key stays valid indefinitely. You can always re-add
   the unit later through the **Manual** path, with no cloud involved at all.
4. **Check that it worked.** Each AC has a **Cloud connection** diagnostic sensor. It asks the AC
   itself — over a local, unauthenticated query that never contacts Haier — whether it can still
   reach the cloud. Once your block is in place the sensor turns **off**, and off is the state you
   want. Allow a couple of minutes: the AC only notices the loss when a keepalive expires. Local
   control is unaffected the whole time.

Full details, including the domain list: [`INSTALL.md`](INSTALL.md).

## Troubleshooting

<details>
<summary><b>My AC changed IP address</b></summary>

Handled for you. If a poll fails, the integration looks the unit up by its device ID — which is the
Wi-Fi module's MAC — finds where it has moved to, and updates itself to follow, usually within the
same poll. A DHCP reservation is still tidy, but it is no longer something you have to set up.

</details>

<details>
<summary><b>"Sign-in failed" / "account not registered"</b></summary>

Almost always the **country code**. It's the phone dialling code of the country your Haier *account*
was registered in, which may not be where you live now or where the AC is. If you're certain it's
right, check whether your account is actually a Haier / Haismart one — hOn and Haier China accounts
live on entirely different servers and no country code will work.

</details>

<details>
<summary><b>"No decodable status from &lt;ip&gt;"</b></summary>

The AC answered and the connection is fine, but Home Assistant couldn't read the reply. Two causes:

- **Stale local key** — keys rotate server-side. If you signed in with your account, it re-fetches
  automatically; otherwise you'll be prompted to re-authenticate.
- **A report layout we don't know yet** — your model packs its status differently. The integration
  recognises several layouts automatically and, for anything else, decodes what it can and says so
  explicitly instead of failing outright. Please [open an issue](#before-you-open-an-issue) with
  diagnostics; adding a new layout is usually a small change, and the diagnostics file works out
  the likely answer for you — it carries a ranked list of candidate layouts with the values each
  one decodes. See [`docs/report-layouts.md`](docs/report-layouts.md).

</details>

<details>
<summary><b>Temperatures show the wrong unit (°F instead of °C, or vice versa)</b></summary>

This happens when Home Assistant's unit system was **changed after** the integration was first set
up. Home Assistant pins each sensor's display unit to whatever the system used **when the sensor was
first created**, on purpose, so that later changing the system unit doesn't silently rewrite your
history. So sensors added before the change keep the old unit while newer ones use the new one — it
applies to any integration's temperature sensors, not just this one.

Two ways to fix it, per sensor:

- **Keep history (recommended):** open the sensor → its settings (cog) → **Unit of Measurement** →
  pick the unit you want. Home Assistant converts the stored history to match.
- **Clean slate:** delete the sensor entity; the integration recreates it on the next update, and the
  new one follows your current system unit. This clears the pinned unit but starts its history over
  (and the entity id may change if you've since renamed the device).

</details>

<details>
<summary><b>Entities are unavailable, or the AC dropped off</b></summary>

An address change is not usually the cause — the integration follows a unit that moves. Check that
nothing else is holding a local session to the same air conditioner (these modules accept one
connection at a time), and that `nc -z <ac-ip> 56800` still succeeds.

</details>

<details>
<summary><b>Turn on debug logging</b></summary>

```yaml
# configuration.yaml
logger:
  default: info
  logs:
    custom_components.haismart: debug
    haismart_hrdp: debug
    haismart_extractor: debug
```

</details>

## Before you open an issue

This protocol is not publicly documented and behaviour varies between models, so a good report is
worth a great deal:

1. Check the [Logs page](https://my.home-assistant.io/redirect/logs/) for warnings from `haismart`.
1. Enable debug logging (above) and reproduce the problem.
1. Search [existing issues](https://github.com/enapt/haismart-local/issues?q=is%3Aissue),
   including closed ones.
1. Download diagnostics: **Settings → [Devices & Services](https://my.home-assistant.io/redirect/integrations/)
   → Haismart → ⋮ → Download diagnostics**. Secrets are redacted; the raw status bytes it contains
   are exactly what's needed to diagnose a decode problem.
1. Include your **AC model number**, the Wi-Fi module if you know it, and the app you pair with.

**Adding support for a new model** is the most valuable contribution here, and it doesn't require
writing any code — see [`docs/new-model.md`](docs/new-model.md) for a short capture procedure. When a
report's layout isn't recognised, the diagnostics file proposes candidate layouts itself;
[`docs/report-layouts.md`](docs/report-layouts.md) is the inventory of every known one.

## Contributing

Pull requests are genuinely welcome, whether or not you write Python:

- **Report a new model** — the capture procedure in [`docs/new-model.md`](docs/new-model.md) turns
  adding a model into a desk job. No hardware access needed on our side.
- **Translations** — the UI strings live in
  [`translations/`](packages/ha-haismart/custom_components/haismart/translations). Adding a language
  is a single JSON file.
- **Code** — see [`CONTRIBUTING.md`](CONTRIBUTING.md). It's a three-package monorepo; tests run with
  no hardware and no network.
- **Just using it and saying it worked** on a model not in [`DEVICES.md`](DEVICES.md) is a real
  contribution too.

Protocol details, if you want to dig in: [`PROTOCOL.md`](PROTOCOL.md).

## Credits

The local uSS/HRDP protocol support here — the handshake, the AES/localKey biz-data layer, the status
decode and the grSetDAC control path — was worked out from scratch for this project, for
interoperability with air conditioners we own.

Large parts of the multi-device support come from [**@darkdiamond**](https://github.com/darkdiamond),
developed in a fork and merged back here with history intact: support for a second report layout
(and graceful degradation on an unknown one), the digital-model enum derivation that makes any model
self-describe, the real product code, **heat mode confirmed on heat-capable hardware**, the
horizontal-swing axis, the sign-in country picker and recovery flows, localisation, and this repo's
CI. Thank you.

Standing on the shoulders of earlier independent work on Haier's local protocols:

- [bstuff/haier-ac-remote](https://github.com/bstuff/haier-ac-remote) and
  [roeij/py-haier-ac-remote](https://github.com/roeij/py-haier-ac-remote) — early port-56800 work
- [KoalaBear84/HaierAC](https://github.com/KoalaBear84/HaierAC) — protocol logging, session behaviour
- [oxystin/homebridge-haier-air-conditioner](https://github.com/oxystin/homebridge-haier-air-conditioner)
  — SmartAir2 units and a valuable compatibility list
- [paveldn/haier-esphome](https://github.com/paveldn/haier-esphome) — the e++ frame layer
- [banto6/haier](https://github.com/banto6/haier) — the mainland-China cloud
- [Andre0512/hon](https://github.com/Andre0512/hon) / [pyhOn](https://github.com/Andre0512/pyhOn) —
  the hOn platform

And to everyone who opens an issue, reports a model, or stars the repo. ⭐

## How sign-in works

Setup uses **the app's own sign-in flow with your own account**: you enter your Haier credentials,
the integration signs a normal API request with the app-level identifiers (an `appId`/`appKey` pair
that is the same for every install of the Haismart app), and Haier returns your AC's local key. There
is no authentication bypass, no defeated protection and no per-user secret of anyone else's involved —
the same interoperability model that [`banto6/haier`](https://github.com/banto6/haier) uses for
Haier's mainland app and [pyhOn](https://github.com/Andre0512/pyhOn) /
[`hon`](https://github.com/Andre0512/hon) use for the hOn platform.

Those app-level identifiers ship as defaults so sign-in works out of the box. If you would rather
supply your own, every one of them is overridable by environment variable —
`HAISMART_APP_ID`, `HAISMART_APP_KEY`, `HAISMART_CLIENT_ID`, `HAISMART_APP_VERSION`.

Everything after setup is local: the protocol the AC speaks on port 56800 was worked out for this
project so a unit you own can be driven from your own network. That is the point of the exercise —
interoperability with your own hardware, not access to anything that isn't yours.

## Disclaimer

An independent community project, **not affiliated with, authorised, or endorsed by Haier**. "Haier",
"Haismart" and "Haier U+" are trademarks of their respective owners, used here only to identify the
hardware this software interoperates with.

Setup signs in to Haier's account API with **your own** credentials; nothing is bypassed. Sharing a
device to a secondary account may be governed by the app's terms of service, and compliance is your
responsibility. Provided as-is, without warranty, for use with hardware you own on your own network.

Licensed under [MIT](LICENSE).
