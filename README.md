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
> is where releases are cut and where issues get answered. Copies exist elsewhere — that is what the
> MIT licence is for — but they are not tracked here, may be based on much older code, and their
> version numbers are their own. If you arrived from one, check the release you are running against
> [the list here](https://github.com/enapt/haismart-local/releases).

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
- [Troubleshooting](#troubleshooting)
- [Why it keeps asking for a key](#why-it-keeps-asking-for-a-key)
  - ["This air conditioner is already being set up"](#this-air-conditioner-is-already-being-set-up)
  - [Getting the key by hand](#getting-the-key-by-hand)
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
likely still work, and not by luck: the integration carries the published description of **every air
conditioner in the manufacturer's catalogue — 1,451 product codes, covering 1,416 model numbers** —
which settings each has, what its faults are called, and which controls it ignores in which state, so
it configures itself for a unit nobody here has ever seen. Where your own account can describe your
appliance, that is used too, and the two are combined rather than one being preferred. If something
decodes oddly, that's a [great issue to open](#before-you-open-an-issue), and usually a quick fix.

Those figures are entries in a catalogue rather than distinct appliances, and it is worth being
straight about the difference: many are the same unit in another colour or for another market
(`…(W)-T3` and `…(GREY)-T3` are one air conditioner), and the 1,451 products collapse to just
**26 hardware families**. 21 model names are even shared by more than one product — 56 products
between them — which is why setup asks which product yours is rather than trusting the label alone.
What the count means is that no published air conditioner is unknown to the integration — not that
Haier sells 1,451 different machines.

### Every region, not just one

**The catalogue answers according to the country your account registered with**, and the regions
publish very different lists — one 171 entries, another 242, Japan's 30, six countries none at all.
Before **v0.38.0** what shipped here was a single region's 171, so an air conditioner published
anywhere else could not be named, could not be offered by the number on its label, and could reach
its own fault names only while Home Assistant had internet.

All of them now ship. The listing also turned out to be filtered by product **category**, which had
hidden the window air conditioners — the complete catalogue is 1,999 products across 38 appliance
categories, and every air-conditioner category among them now ships, window units included. Your
country is also used at setup — to shorten the model list to what is sold where you are, and to look
up a model number the shipped list has not heard of. If an older version could not identify your
unit, this one very likely can.

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
| **Energy** | A running kWh total, on the units that keep one themselves. Goes straight on the Energy dashboard — no helper needed. Most units carry the register but never fill it in, and there the sensor reads *unknown*; see [Energy monitoring](#energy-monitoring) |
| **Compressor current / frequency** *(diagnostic)* | What the outdoor unit is actually doing |
| **Coil / discharge temperature** *(diagnostic)* | Evaporator and compressor-discharge temperatures |
| **Air quality** | Indoor and outdoor PM2.5, CO₂, formaldehyde, a VOC index, and indoor humidity — on units that carry the probes. A unit without a given probe gets no entity for it, and a probe reading nothing shows *unknown* rather than a fake zero |
| **Compressor / Fan** *(diagnostic, on/off)* | Whether the compressor and indoor fan are actually running |
| **Self-clean** | Start a cycle with the **Start self-clean** button — a one-shot trigger: it runs to completion and can't be cancelled, so it's a button, not a switch. A binary sensor shows whether a cycle is running, and a **Last self-clean** timestamp records when the last one finished, so a "days since"-style reminder is a one-line automation. Only on units whose model has it, and the button greys out when a clean can't be started — off, auto mode, sleep, or a fault |
| **Extra controls** | The optional functions the vendor app itself offers a control for — fresh air, electric heating, ambient light, energy saving, mould prevention, dry-out, heatstroke prevention, presence-based airflow — each a real switch or select, and only on units that *actually* have the function |
| **Optional features** *(diagnostic, on/off)* | The remaining extra functions a unit reports having but the app offers no control for — a 10 °C keep-warm, an intelligent mode, humidification, the buzzer, and others — each read-only, and only the ones your unit *actually* has (a model over-declares; the ones it lacks are hidden) |
| **Presence airflow** *(diagnostic, enum)* | Where a presence-sensing unit is directing air: off / avoid / follow. Only on units with the sensor |
| **Fault** *(diagnostic, problem)* | Whether the unit is reporting a fault. Its attributes name the active faults with the service code the unit shows (E1, F4, …) — that is what an engineer will ask for |
| **Last changed by** *(diagnostic)* | Whether the last change came from the handset, the unit's own panel, or the network. Useful as an automation trigger when someone picks up the remote |
| **Model ID** *(diagnostic)* | The identifier that selects your unit's report layout. Shown shortened (it's 64 characters); the exact value is on the entity's `uplus_id` attribute — quote that in a bug report about a model that isn't decoded |
| **Cloud connection** *(diagnostic, on/off)* | Whether the AC itself can still reach Haier's servers — see [going fully cloud-independent](#going-fully-cloud-independent) |
| **Local key** *(diagnostic, off by default)* | Your unit's key, so it rides along in HA backups |

Which of these appear depends on your model — the integration only exposes controls it can actually
drive on your unit, and only reports the features your unit genuinely has, rather than showing
buttons or sensors that do nothing. A model tends to describe every function its product line might
have; the ones your particular unit lacks are recognised and left out.

**Your air conditioner describes itself, and the integration listens.** When you sign in it fetches
your unit's own model: the modes and fan speeds it really has, the setpoint range it accepts, the
positions its vanes can hold, and the rules saying which settings it ignores in which state. That is
why a heat pump gets Heat and a cooling-only unit does not, without anyone maintaining a list.

**Some settings only apply in some modes, and the integration knows which.** Air conditioners ignore
certain settings in certain states — a unit in fan-only discards the temperature you set, and most
of them ignore boost while dehumidifying. Your unit's own model says which.

Those controls **stay visible and keep showing their real state**; what changes is that the command
is refused, naming the reason — *"Eco does not accept that setting: not available in fan-only
mode"*. They are not marked unavailable, because a setting your AC ignores in its current mode is
normal operation, not a fault: flagging it made a working system look broken, and took the reading
and its history away for as long as the mode lasted. The one thing that does disappear is the
temperature on the thermostat card, which is the mechanism Home Assistant provides for exactly this
— better than a box that accepts numbers the unit throws away. A unit reporting a fault refuses its
settings the same way. Nothing is restricted while the AC is merely switched off — that is when you
are most likely to be setting it up.

The climate entity also carries **presets** for the three comfort modes — eco, sleep and boost — so
they work from the thermostat card, from a voice assistant and from `climate.set_preset_mode`, not
only from the switches. A preset is exclusive: choosing one clears the others in a single write to
the AC. The switches and the Eco select are still there for the individual fields and for choosing
which eco level you want.

**Swing** comes as both controls Home Assistant offers. The four-way one (off / up-down / left-right
/ both) moves the two vanes together and is unchanged; alongside it, `climate.set_swing_horizontal_mode`
moves the left-right vane on its own, without touching the up-down one. Units whose left-right
position we haven't confirmed get only the four-way control.

Swinging and pointing are different things, though, and a climate entity can only express the first.
Where your unit publishes the stops a vane can hold, a **Left-right vane** or **Up-down vane** select
appears with those positions on it, so you can aim the airflow at one part of the room rather than
sweeping it across the whole. Fixed and Auto are the same two states the swing control covers; the
positions in between are the ones it cannot reach. Positions are numbered as your unit numbers
them — "Position 1" is the first stop it offers. A unit that publishes only fixed and auto for an
axis gets no select for it, since the swing control already says everything there is to say.

Not everything the air conditioner reports becomes an entity — its **firmware version**, for
instance, is a property of the unit rather than a reading that changes, so it appears on the device
page and in a diagnostics download instead of as a sensor that would never move.

### Energy monitoring

Units that report their power draw get a **Power** sensor in watts. That is a live reading, so it
records into Home Assistant's history and long-term statistics on its own — but the **Energy
dashboard** needs a running total in kWh, which is a different thing.

**Some units keep that total themselves**, and those get an **Energy** sensor you can add straight
to the Energy dashboard under **Settings → Dashboards → Energy → Individual devices**. It is the
figure the air conditioner's own meter keeps, so it survives restarts and outages and does not
depend on how often Home Assistant polls. If your unit has one, use it and skip the rest of this
section. If your Energy sensor reads *unknown*, your unit is one of the many that carries the
register and never fills it in — read on.

To build a total from the power reading instead, add a Riemann-sum integral helper over it:

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

The integration never invents a kWh total. Where a unit keeps one, you get it as it is counted;
where it does not, the helper above is the honest way to build one.

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

Then pick one of the paths offered:

**Sign in (recommended).** Enter your Haier account email (or phone) and password, and the country
your **account** was registered in. The integration lists your air conditioners, fetches the chosen
one's key automatically, finds it on your network, and reads which model it is — you won't paste or
choose anything.

> The country field is the **phone dialling code of the country your Haier account was created in**
> — not where the AC is installed, and not necessarily where you live now. Getting it wrong is the
> single most common setup failure, because Haier's server reports it as "account not registered",
> which reads like a wrong password.

**I already have this unit's local key.** The offline route, and it now asks for almost nothing.
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

Once one unit is set up through an account, that account is stored — so the next one costs you
nothing. **Add Integration → Haismart** now offers a third choice, first in the list:

**Use the Haier account already added.** No password, no key, no address. It lists the appliances on
the account that are not set up yet; pick one and it is added. The same thing happens if your air
conditioner appears in Home Assistant's **Discovered** box — the card leads to a confirmation rather
than to a key prompt, because the key can simply be fetched.

Signing in a second time also works, but there is no reason to: each sign-in registers a new
terminal with Haier, and the credentials your first air conditioner is holding are the ones that get
superseded. If you do sign in again, every appliance already set up on that account is updated with
the new credentials, so none of them is left behind.

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

**The local key is the only thing that has to come from Haier — everything else ships with the
integration or comes from the appliance.** That is worth stating plainly, because it is what makes
the rest of this section work rather than being a compromise:

| what setting up an appliance needs | where it comes from |
|---|---|
| its address on your network | your network |
| its device ID | the appliance |
| how to read its reports | ships with the integration |
| its faults, rules and real feature list | ships with the integration — every published product |
| which model it is | the number on its label, matched offline |
| its temperatures, modes and telemetry | read from the appliance |
| **its local key** | **Haier — once** |

So the one remaining cloud dependency is that Haier's server can **rotate** the key, which the
integration then re-fetches.

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
   the unit later through the offline path with no cloud involved at all — and because the key is
   frozen, the copy you archived in step 1 is still the right one however long has passed.
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

- **Stale local key** — keys rotate server-side. If another air conditioner on the same account is
  set up here, its credentials are tried first and the key is re-fetched with nothing shown to you
  at all. Otherwise, if you signed in with your account, it re-fetches
  automatically; otherwise you'll be prompted to re-authenticate. The integration tells you which
  situation you are in rather than making you guess — see
  [Why it keeps asking for a key](#why-it-keeps-asking-for-a-key).
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

A control your AC ignores in its current mode is **not** shown as unavailable — it stays readable and
refuses the command instead — so an unavailable entity here really does mean the unit is out of
reach, rather than a setting that does not apply right now.

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

## Why it keeps asking for a key

An air conditioner that can still reach Haier is issued a **new local key several times a day**.
That is the single most common cause of an installation that seems to lose its configuration: the
key changes, the stored one no longer works, and the next restart shows an error and no entities.
Re-adding the unit fixes it only until the next change.

**Signing in makes it invisible.** With your account stored, a key change is fetched automatically
and you are never asked. This is the main reason sign-in is the recommended route.

The integration will tell you, in Settings → Repairs, which of three situations you are in:

| What you see | What it means | What to do |
|---|---|---|
| *"its key will change and this setup cannot follow"* | The unit is still online and this entry has no account, so it cannot follow. Raised **before** anything breaks. | Add your account, or block the unit from the internet — either one ends it |
| *"localKey rotated — manual re-key needed"* | The key changed and there is no account to fetch a new one with | Reconfigure → *Add your Haier account*, then it never asks again |
| *"its key changed and the automatic re-fetch did not work"* | Your account **is** stored and the automatic fetch failed | Sign in again from the prompt. If it recurs, something is blocking Haier's key service — or blocking the unit permanently is the cleaner fix |

**Adding your account to an existing unit** takes a minute and does not disturb anything: Settings →
Devices & Services → Haismart → the device → **Reconfigure** → *Add your Haier account*. Same
appliance, same key, same history — credentials added.

**Or stop the key changing at all.** A unit blocked from the internet is never issued a new one, so
the key you have stays valid indefinitely — see
[going fully cloud-independent](#going-fully-cloud-independent). Local control is unaffected either
way, and this is the configuration the integration is built for.

### "This air conditioner is already being set up"

Fixed in **v0.40.2** — if you are on an older version, this is what you are seeing.

Your air conditioner announces itself on the network, so Home Assistant raises a **Discovered** card
for it on its own. That card is a setup already in progress, and it used to block you from starting
another one for the same unit — so signing in got as far as listing your air conditioners and was
then turned away, and the only thing you could finish was the card itself, which asks for a local
key you have no way to obtain.

Nothing was wrong with your account, and nothing appears in the log, because sign-in succeeded and
the refusal happens before a key is ever requested.

On v0.40.2 and later, adding an appliance deliberately takes precedence and the card clears itself.
If you are stuck on an older version, **restart Home Assistant** and then go straight to
**Add Integration → Haismart → sign in** before the unit announces itself again.

> Do **not** press *Ignore* on the Discovered card to get rid of it. That records the appliance as
> one you have chosen not to add, and setup will then refuse with *"already configured"* instead,
> which is harder to undo.

### Getting the key by hand

If setup will not complete no matter what, you can ask Haier for the key directly.

**It runs on any computer with Python** — your laptop is fine. The tool only talks to Haier's
servers, never to the air conditioner, so it does not need to be on the same network as the unit,
or on your Home Assistant machine at all:

```bash
pip install 'haismart-extractor[cloud] @ git+https://github.com/enapt/haismart-local#subdirectory=packages/haismart-extractor'

haismart-keys --username you@example.com --region 66
```

It signs in, lists every air conditioner on the account, and prints each one's device ID, model,
product code and **local key** — everything the *"I already have this unit's local key"* route asks
for.

> The copy bundled inside an installed integration is *not* runnable from the **Terminal & SSH**
> add-on — that container has no `cryptography`, and `docker exec` into the core container is
> refused while protection mode is on. Install it on a computer instead; it is the same tool and it
> needs nothing from your network.

`--region` is the dialling code of the country the **account** was registered in, the same value
setup asks for. The password is prompted for, never passed as an argument. Add `--json` for
machine-readable output.

> ⚠️ **A local key is a secret** — it is what lets anything on your network control the appliance.
> Do not paste the output into a bug report or a forum post. Use `--no-keys`, which prints
> everything except the keys and is safe to share.

### If it still cannot fetch the key

Since **v0.40.3** the screen tells you why, instead of leaving the reason in the log. When the fetch
fails you get the exact response — a timeout, a refusal from Haier's key service, a reply that
carried no key — printed on the page, along with whether the air conditioner itself says it can
still reach Haier.

That is deliberate: setup has not finished at that point, so there is no device and no diagnostics
download to attach to a report. Quote what the screen shows and it names the cause.

## Before you open an issue

For a quick question — "is my model likely to work?", "does this log line mean what I think?" — there
is a channel for this project on [Discord](https://discord.gg/EFfknne8Bm). Bug reports and new-model
captures still belong in an issue, where they can be found again.

This protocol is not publicly documented and behaviour varies between models, so a good report is
worth a great deal:

1. Check the [Logs page](https://my.home-assistant.io/redirect/logs/) for warnings from `haismart`.
1. Enable debug logging (above) and reproduce the problem.
1. Search [existing issues](https://github.com/enapt/haismart-local/issues?q=is%3Aissue),
   including closed ones.
1. Download diagnostics: **Settings → [Devices & Services](https://my.home-assistant.io/redirect/integrations/)
   → Haismart → ⋮ → Download diagnostics**. Secrets are redacted; the raw status bytes it contains
   are exactly what's needed to diagnose a decode problem.
1. Say what you expected and what happened. **You don't need to look anything up** — see below.

A diagnostics download is close to self-contained. It already knows what you would otherwise be asked
to transcribe: under `device_identity` it carries your **model number** and the product code it is
keyed on, the **Model ID**, and the Wi-Fi module's **firmware and SDK version** exactly as the
appliance reports them. Besides the raw report it carries **every attribute your unit declares, read
off its own report** — the settings that have no entity as well as the ones that do — alongside the
values your air conditioner publishes through its cloud profile, so the two can be compared without
asking you for anything further. On the reference unit those two independent sources agree on all 21
comparable readings.

The one thing worth typing is the model number **if your unit will not connect at all**, since none
of the above exists until it does.

**A model we have never seen usually reads — and commands — anyway.** Every published air conditioner
is the same attribute map at one of a few offsets, and a unit's Model ID names its closest relatives —
so when no known layout claims a report, the integration tries the offsets those relatives use and
keeps whichever one the report itself agrees with. Control is offered through four gates, each
removing a different way of being wrong: the group-set command is packed identically across the
published air-conditioner descriptions; **which** of its settings your product carries comes from the
product's own published attribute list, shipped for every product that publishes one; the handful
of families that keep a *different* setting at one of those positions have exactly those controls
refused; and a setting the product's own list places somewhere the shared packing cannot explain is
refused too — including, for two families, the whole write path, when the list as a whole cannot be
reconciled with the shared packing. A product that publishes no list is **read** all the same, and
simply not commanded: reading and commanding are gated separately, because a group-set list
describes how a unit is *written*, which says nothing about where its report puts things.

Of the 1,451 published air conditioners, **1,234 read and control, 217 read and report only, and
none is turned away before its report is looked at.**

**A capture is still the most valuable contribution** for such a unit, and it doesn't require writing
any code — see [`docs/new-model.md`](docs/new-model.md) for the short procedure. It is what promotes
the layout to a confirmed family and unlocks the readings beyond the core climate block. When nothing
fits at all, the diagnostics file proposes candidate layouts itself;
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
