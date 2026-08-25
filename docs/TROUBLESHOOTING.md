# Troubleshooting

Everything that can go wrong, and what to do about it. The
[README](../README.md) covers installing and setting up; this page is for when something is not
working.

If none of it helps, [**Before you open an issue**](#before-you-open-an-issue) at the end says what
to include so the answer comes back in one round trip instead of four.

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
  one decodes. See [`docs/report-layouts.md`](report-layouts.md).

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
[going fully cloud-independent](../README.md#going-fully-cloud-independent). Local control is unaffected either
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

Of the 1,451 published air conditioners, **1,421 read and control, 30 read and report only, and
none is turned away before its report is looked at.** (The read-only thirty are the two families
whose published order the shared packing cannot explain, so nothing is offered for them rather than
guessed at.)

**A capture is still the most valuable contribution** for such a unit, and it doesn't require writing
any code — see [`docs/new-model.md`](new-model.md) for the short procedure. It is what promotes
the layout to a confirmed family and unlocks the readings beyond the core climate block. When nothing
fits at all, the diagnostics file proposes candidate layouts itself;
[`docs/report-layouts.md`](report-layouts.md) is the inventory of every known one, and
[`docs/VENDOR_LABELS.md`](VENDOR_LABELS.md) records where the names of modes and fan
speeds come from — they are the manufacturer's own, read from the language bundle its app
ships, rather than translated by us.
