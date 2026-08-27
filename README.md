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
conditioner in the manufacturer's catalogue — 1,451 product codes, covering 1,416 model numbers** —
which settings each has, what its faults are called, and which controls it ignores in which state, so
it configures itself for a unit nobody here has ever seen. Where your own account can describe your
appliance, that is used too, and the two are combined rather than one being preferred. If something
decodes oddly, that's a [great issue to open](docs/TROUBLESHOOTING.md#before-you-open-an-issue), and usually a quick fix.

Those figures are entries in a catalogue rather than distinct appliances, and it is worth being
straight about the difference: many are the same unit in another colour or for another market
(`…(W)-T3` and `…(GREY)-T3` are one air conditioner), and the 1,451 products collapse to just
**26 hardware families**. 21 model names are even shared by more than one product — 56 products
between them — which is why setup asks which product yours is rather than trusting the label alone.
What the count means is that no published air conditioner is unknown to the integration — not that
Haier sells 1,451 different machines.

### Every region, not just one

**The manufacturer's catalogue answers according to the country your account registered with**, and
the regions publish very different lists — one 171 entries, another 242, Japan's 30, six countries
none at all. It is filtered by product **category** as well as by region, which is what hides window
air conditioners from a naive listing.

**All of them ship here.** The complete catalogue is 1,999 products across 38 appliance categories,
and every air-conditioner category among them is included, window units included. Your country is
also used at setup — to shorten the model list to what is sold where you are, and to look up a model
number the shipped list has not heard of.

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
| **Air quality rating** / **PM2.5 level** *(diagnostic, enum)* | The unit's own four-step verdict on the air — excellent / good / moderate / poor — rather than a number to interpret. On units that rate it |
| **Compressor / Fan** *(diagnostic, on/off)* | Whether the compressor and indoor fan are actually running |
| **Self-clean** | Start a cycle with the **Start self-clean** button — a one-shot trigger: it runs to completion and can't be cancelled, so it's a button, not a switch. A binary sensor shows whether a cycle is running, and a **Last self-clean** timestamp records when the last one finished, so a "days since"-style reminder is a one-line automation. Only on units whose model has it, and the button greys out when a clean can't be started — off, auto mode, sleep, or a fault |
| **Filter** *(diagnostic, problem)* | The unit's own filter-change reminder, on the models that keep one — it turns on when the AC decides the filter is due, so a notification is a one-line automation. Units that also meter their purifier board get a **Purifier runtime** total in hours beside it |
| **Extra controls** | The optional functions the vendor app itself offers a control for — fresh air, electric heating, ambient light, energy saving, mould prevention, dry-out, heatstroke prevention, presence-based airflow — each a real switch or select, and only on units that *actually* have the function |
| **Optional features** *(diagnostic, on/off)* | The remaining extra functions a unit reports having but the app offers no control for — a 10 °C keep-warm, an intelligent mode, humidification, the buzzer, the control-panel lock, PM2.5 and formaldehyde purification, and others — each read-only, and only the ones your unit *actually* has (a model over-declares; the ones it lacks are hidden) |
| **Presence airflow** *(diagnostic, enum)* | Where a presence-sensing unit is directing air: off / avoid / follow. Only on units with the sensor |
| **Occupancy** *(diagnostic, enum)* | What the presence sensor currently sees: nobody, one person, or several. A unit whose sensor is absent says so in the report itself, and gets no entity |
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
