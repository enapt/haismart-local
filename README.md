# Haismart Local — Haier air conditioners in Home Assistant, with no cloud

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Release](https://img.shields.io/github/v/release/enapt/haismart-local?color=green)](https://github.com/enapt/haismart-local/releases/latest)
[![Validate](https://img.shields.io/github/actions/workflow/status/enapt/haismart-local/validate.yml?branch=main&label=validate)](https://github.com/enapt/haismart-local/actions/workflows/validate.yml)
[![License](https://img.shields.io/github/license/enapt/haismart-local)](LICENSE)
[![Discord](https://img.shields.io/badge/Discord-join%20the%20chat-5865F2?logo=discord&logoColor=white)](https://discord.gg/EFfknne8Bm)

_Control your Haier air conditioner from Home Assistant entirely over your own network. You sign in
once so the integration can fetch your unit's key — after that it talks only to the AC, on your LAN.
Everything else it needs, including the published details of **every air conditioner in the range**,
ships with it: keep a copy of that key and setup works with no internet at all._

> **This is the home of the project.** [`enapt/haismart-local`](https://github.com/enapt/haismart-local)
> is where releases are cut and issues answered. Copies exist elsewhere — that is what the MIT licence
> is for — but they are not tracked here and their version numbers are their own; if you arrived from
> one, check what you are running against
> [the releases](https://github.com/enapt/haismart-local/releases).

**🌐 Getting started in your language:** [Bahasa Indonesia](docs/i18n/README.id.md) ·
[ไทย](docs/i18n/README.th.md) · [Tiếng Việt](docs/i18n/README.vi.md) ·
[Bahasa Melayu](docs/i18n/README.ms.md) · [Filipino](docs/i18n/README.fil.md)\
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
- [Something not working?](#something-not-working)
  - [Full troubleshooting guide](docs/TROUBLESHOOTING.md) — every known failure, and what to
    include when you open an issue
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
likely still work, and not by luck: the integration carries the published description of **every air
conditioner in the manufacturer's catalogue — 1,451 product codes covering 1,416 model numbers**, in
every region and every air-conditioner category, window units included. Which settings each has, what
its faults are called, which controls it ignores in which state — so it configures itself for a unit
nobody here has ever seen. Where your own account can describe your appliance, that is used as well,
and the two are combined. If something decodes oddly, that's a
[great issue to open](docs/TROUBLESHOOTING.md#before-you-open-an-issue).

Those are catalogue entries, not distinct appliances: many are the same unit in another colour or for
another market (`…(W)-T3` and `…(GREY)-T3` are one air conditioner), and the 1,451 collapse to **26
hardware families**. 21 model names are shared by more than one product, which is why setup asks
which product yours is rather than trusting the label. Your country is used at setup too, to shorten
the model list to what is sold where you are.

**Quick check:** if `nc -z <your-ac-ip> 56800` succeeds, the local protocol is listening.

## What you get

One device per air conditioner, with:

| Entity | What it does |
|---|---|
| **Climate** | Temperature setpoint, mode (cool / heat / dry / fan-only / auto), fan speed, swing, preset (eco / sleep / boost), on/off. Heat is offered only when the unit itself reports it can heat |
| **Indoor temperature** | The AC's own room-temperature reading |
| **Outdoor temperature** | Outdoor probe, on units that have one |
| **Switches** | Strong, Quiet, Health, Sleep, Display light |
| **Eco** | Eco level, on models where it's confirmed |
| **Left-right vane** / **Up-down vane** | Where each vane points, on units that publish its positions |
| **Power** *(diagnostic)* | Live power draw in watts, on units that report it |
| **Energy** | A running kWh total, on the units that keep one themselves — straight onto the Energy dashboard, no helper needed. Most carry the register and never fill it in; there it reads *unknown*. See [Energy monitoring](docs/behaviour.md#energy-monitoring) |
| **Compressor current / frequency** *(diagnostic)* | What the outdoor unit is actually doing |
| **Coil / discharge temperature** *(diagnostic)* | Evaporator and compressor-discharge temperatures |
| **Air quality** | Indoor and outdoor PM2.5, CO₂, formaldehyde, a VOC index and indoor humidity, on units carrying the probes. No probe, no entity; a probe reading nothing shows *unknown* rather than a fake zero |
| **Air quality rating** / **PM2.5 level** *(diagnostic, enum)* | The unit's own verdict on the air: excellent / good / moderate / poor |
| **Compressor / Fan** *(diagnostic, on/off)* | Whether the compressor and indoor fan are actually running |
| **Self-clean** | A **Start self-clean** button (a cycle runs to completion and can't be cancelled, so a button rather than a switch), a sensor for whether one is running, and a **Last self-clean** timestamp for "days since" reminders. The button greys out when a cycle can't be started — off, auto mode, sleep, or a fault |
| **Filter** *(diagnostic, problem)* | The AC's own filter-change reminder: on when it decides the filter is due. Units that meter their purifier board also get **Purifier runtime** in hours |
| **Extra controls** | The optional functions the vendor app offers a control for — fresh air, electric heating, ambient light, energy saving, mould prevention, dry-out, heatstroke prevention, presence-based airflow — as switches and selects, on units that have them |
| **Optional features** *(diagnostic, on/off)* | Read-only for the functions the app offers no control for: 10 °C keep-warm, intelligent mode, humidification, the buzzer, the control-panel lock, PM2.5 and formaldehyde purification, and others your unit has |
| **Presence airflow** *(diagnostic, enum)* | Where a presence-sensing unit is directing air: off / avoid / follow / on. Only on units with the sensor; where the unit can be commanded it is a select under *Extra controls* instead, and the reading is not duplicated |
| **Occupancy** *(diagnostic, enum)* | What the presence sensor sees: nobody, one person, or several. A unit without the sensor says so in its report, and gets no entity |
| **Fault** *(diagnostic, problem)* | Whether the unit reports a fault. Its attributes name the active faults with the service code the unit shows (E1, F4, …) — what an engineer will ask for |
| **Last changed by** *(diagnostic)* | Handset, the unit's own panel, or the network — an automation trigger for when someone picks up the remote |
| **Model ID** *(diagnostic)* | The identifier that selects your unit's report layout, shown shortened; the exact 64-character value is on its `uplus_id` attribute. Quote it in a bug report about a model that isn't decoded |
| **Cloud connection** *(diagnostic, on/off)* | Whether the AC itself can still reach Haier's servers — see [going fully cloud-independent](#going-fully-cloud-independent) |
| **Local key** *(diagnostic, off by default)* | Your unit's key, so it rides along in HA backups |

Which appear depends on your model. The integration reads your unit's own model and offers only
what that unit has, so a heat pump gets Heat and a cooling-only unit does not. A setting your AC
ignores in its current mode keeps its control visible and showing the real state; the command is
refused with the reason rather than the control being greyed out.

➡️ **[How the controls behave](docs/behaviour.md)** — mode-dependent settings, presets, vane
positions, **energy monitoring** and **polling**, in detail.

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

Then pick one of the paths offered:

**Sign in (recommended).** Enter your Haier account email (or phone) and password, and the country
your **account** was registered in. The integration lists your air conditioners, fetches the chosen
one's key automatically, finds it on your network, and reads which model it is — you won't paste or
choose anything.

> The country field is the **phone dialling code of the country your Haier account was created in**
> — not where the AC is installed, and not necessarily where you live now. Getting it wrong is the
> single most common setup failure, because Haier's server reports it as "account not registered",
> which reads like a wrong password.

**I already have this unit's local key.** The offline route, which asks for almost nothing.
Home Assistant looks for Haier appliances on your network, asks each one to identify itself, and
lists what answered — you pick yours and paste the key. The address and the device ID come from the
appliance.

It then asks **which model** you have, as a short list of the models sharing your unit's product
family, by the number printed on its label. That is worth answering: it unlocks the fault names, the
availability rules and your unit's real feature list. **Skipping is fine** — the rules every model in
that family agrees on are used instead, which still covers every fault name.

> The key is the one thing an appliance will never hand over. If you do not have one saved — from
> the *Local key* diagnostic sensor of a previous install, or a backup — sign in instead; that
> fetches it for you.

### Adding a second air conditioner

The account from your first unit is stored, so the next one costs nothing. **Add Integration →
Haismart** offers a third choice, first in the list: **use the Haier account already added** — no
password, no key, no address. It lists the appliances on that account that are not set up yet; pick
one. Your air conditioner appearing in Home Assistant's **Discovered** box leads to the same
confirmation rather than a key prompt.

Signing in a second time works but gains nothing: each sign-in registers a new terminal with Haier
and supersedes the credentials your first air conditioner holds. Every appliance already set up on
that account is updated with the new credentials, so none is left behind.

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

**The local key is the only thing that has to come from Haier.** Everything else ships with the
integration or comes from the appliance:

| what setting up an appliance needs | where it comes from |
|---|---|
| its address on your network | your network |
| its device ID | the appliance |
| how to read its reports | ships with the integration |
| its faults, rules and real feature list | ships with the integration — every published product |
| which model it is | the number on its label, matched offline |
| its temperatures, modes and telemetry | read from the appliance |
| **its local key** | **Haier — once** |

The one remaining cloud dependency is that Haier's server can **rotate** the key, which the
integration re-fetches. If you'd rather your AC never phoned home at all:

1. **Archive the key first.** Enable the *Local key* diagnostic sensor on the device page — its state
   is the key, and its attributes carry the host, device ID and version. It then rides along in your
   Home Assistant backups automatically.
2. **Block the AC's internet access** at your router — the simplest rule that works is denying traffic
   to `43.156.75.60`, Haier's gateway. Keep the LAN open: Home Assistant still needs port 56800.
   DNS blocking is *not* reliable here (the units connect by a cached address), and beware router
   features called "MAC filtering" or "IP filtering" — they often cut the device off your LAN entirely
   rather than just from the internet.
3. The key can no longer rotate, so your stored key stays valid indefinitely. You can always re-add
   the unit later through the offline path with no cloud involved at all — and because the key is
   frozen, the copy you archived in step 1 is still the right one however long has passed.
4. **Check that it worked.** Each AC has a **Cloud connection** diagnostic sensor. It asks the AC
   itself — over a local, unauthenticated query that never contacts Haier — whether it can still
   reach the cloud. Once your block is in place the sensor turns **off**, and off is the state you
   want. Allow a couple of minutes: the AC only notices the loss when a keepalive expires. Local
   control is unaffected the whole time.

Full details, including the domain list: [`INSTALL.md`](INSTALL.md).

## Something not working?

Three things cover most of it:

* **Sign-in fails** — it is almost always the **country code**. It is the dialling code of the
  country your Haier account was registered in, which may not be where you live.
* **It keeps asking for the key** — the key rotates, and a firewalled AC cannot be re-keyed
  automatically. [Going fully cloud-independent](#going-fully-cloud-independent) explains the
  trade-off; the troubleshooting guide explains how to get a fresh key by hand.
* **The AC changed IP** — handled for you. The integration follows it by MAC, usually within the
  same poll.

➡️ **[Full troubleshooting guide](docs/TROUBLESHOOTING.md)** — every known failure, its cause and its
fix, plus **what to include when you open an issue** so it can be answered in one round trip.


## Documentation

| | |
|---|---|
| [`INSTALL.md`](INSTALL.md) | Installing, the cloud-independent setup, and the domains involved |
| [`docs/behaviour.md`](docs/behaviour.md) | How the controls behave: mode-dependent settings, presets, vanes, energy, polling |
| [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) | Every known failure and its fix, and what to include in an issue |
| [`docs/new-model.md`](docs/new-model.md) | Getting an unsupported model working — what to send and why |
| [`docs/report-layouts.md`](docs/report-layouts.md) | The report layouts, per family, and how a new one is identified |
| [`docs/VENDOR_LABELS.md`](docs/VENDOR_LABELS.md) | Where the fan-speed and mode names come from |
| [`docs/FUTURE_WORK.md`](docs/FUTURE_WORK.md) | Open items, with what each would take |

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

Large parts of the multi-device support come from [**@darkdiamond**](https://github.com/darkdiamond),
developed in a fork and merged back here with history intact: a second report layout and graceful
degradation on an unknown one, the digital-model enum derivation that makes any model self-describe,
the real product code, heat mode confirmed on heat-capable hardware, the horizontal-swing axis, the
sign-in country picker and recovery flows, localisation, and this repo's CI. Thank you.

Earlier independent work on Haier's local protocols:

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

Setup uses the app's own sign-in flow with your own account: you enter your Haier credentials, the
integration signs a normal API request with the app-level identifiers shared by every install of the
Haismart app, and Haier returns your AC's local key. Nothing is bypassed, and no per-user secret of
anyone else's is involved — the same interoperability model
[`banto6/haier`](https://github.com/banto6/haier) uses for Haier's mainland app and
[pyhOn](https://github.com/Andre0512/pyhOn) for the hOn platform.

Those identifiers ship as defaults so sign-in works out of the box, and each is overridable by
environment variable: `HAISMART_APP_ID`, `HAISMART_APP_KEY`, `HAISMART_CLIENT_ID`,
`HAISMART_APP_VERSION`. Everything after setup is local, on port 56800.

## Disclaimer

An independent community project, **not affiliated with, authorised, or endorsed by Haier**. "Haier",
"Haismart" and "Haier U+" are trademarks of their respective owners, used here only to identify the
hardware this software interoperates with.

Setup signs in to Haier's account API with **your own** credentials; nothing is bypassed. Sharing a
device to a secondary account may be governed by the app's terms of service, and compliance is your
responsibility. Provided as-is, without warranty, for use with hardware you own on your own network.

Licensed under [MIT](LICENSE).
