# Adding support for a new model

Many models are recognised automatically from their factory layout, so most air conditioners just
work. If yours connects but some values look wrong — or Home Assistant reports `no decodable status`
— its status report packs fields in a layout we haven't mapped yet. Working that out needs **no code
and no protocol knowledge**, just three captures from you.

## First: check whether it already reads

Since **v0.35.0** an air conditioner whose exact layout we have never seen can often still be read,
by matching it to the published models closest to it and checking the result against what the unit
actually sent. Since **v0.52.0** that no longer needs a close match at all: a unit that resembles
nothing published is tried against every layout offset in use, and its own report decides which one
fits. Since **v0.53.0** it does not need to publish a group-set list either — without one it is read
and simply not commanded.

So before capturing anything, look at what you have:

- **Readings look right, and you can control it.** Nothing to do — your model is recognised. (Since
  v0.48.0 this includes most units on the matched-relatives path: the core controls come from your
  product's own published list of group-set settings, no capture required.)
- **Readings look right, but the thermostat and switches won't change anything.** Your product is one
  of the few that publishes no group-set list, so commands stay withheld — the safe default, since a
  command writes a whole block of settings at once. **The captures below are exactly what turns your
  model into a controllable one** — and because the readings already work, they are easy to take.
- **Only power, setpoint, mode and fan appear, or values are clearly wrong.** Either your unit did not
  tell us which model it is, or no offset agreed with its report. The captures below are the way
  forward, and they are the whole job.

Captures are also what unlock the **readings beyond the core climate block** (power telemetry,
per-model extras) on a matched-relatives layout, and — on twin-airflow tower units — what verifies
which airflow the fan and vane commands address. So even a unit that reads *and* controls is worth
capturing.

In every case, please open an issue either way — a model that now works without any capture is worth
recording just as much as one that doesn't.

## Why three captures

The report is a fixed prefix followed by a block of control words and then read-only sensor bytes.
Where the sensors start depends on how many control words your model carries. Changing one setting at
a time and diffing the results pins that boundary exactly: only the bytes that changed can belong to
the setting you changed, and the rest fall out by elimination.

## What to send

For each of the three states below: set it **on the AC's own remote or the Haier app** (not from Home
Assistant), wait about 30 seconds so Home Assistant polls at least once, then download diagnostics —
**Settings → Devices & Services → Haismart → ⋮ → Download diagnostics**.

| # | State to set | Also note |
|---|---|---|
| 1 | **Off** | — |
| 2 | **Cool, 22 °C, fan low, swing off** | the room temperature the remote displays |
| 3 | **Fan-only, fan high, swing on** | — |

The report form has a **separate box for each capture**, so attach each file in the box naming the
state it was taken in. That pairing is what makes three captures worth more than three times one: a
candidate layout has to explain all three, and knowing which file is which is what separates a real
match from a coincidence.

**If your unit cannot manage one of these states, set the nearest thing it can and say what you
actually set.** A state that is written down is useful whatever it was — some units have no fan-only
mode, some no swing control, some no 22 °C. The one file nobody can use is the one nobody can place.

It also helps to quote your unit's **Model ID** — the diagnostic sensor of that name on the device page.
That identifier is what selects the report layout, so it tells us immediately whether your unit is a family
we already know or a genuinely new one. The sensor shows a shortened form; the exact 64-character value is
its `uplus_id` attribute (and it is in the diagnostics file too, so attaching that covers it).

Then open a [new model report](https://github.com/enapt/haismart-local/issues/new?template=new_model.yml)
and attach each file in its own box, plus:

- the **model number** from the sticker on the indoor unit
- the **Wi-Fi module** model, if it is printed on the unit or shown in the app
- which **app** you pair with (Haier / Haismart / Haier U+ / uHome)
- the room temperature the remote showed in state 2

## Is anything secret in there?

No. Diagnostics redacts your account tokens and your device's local key. It does include the raw
status bytes, which are just the sensor and setting values — the same numbers your remote shows — and
the device ID, which is the Wi-Fi module's MAC address. That is not a credential, and it is needed to
make sense of the capture.

## What happens next

The three captures are diffed to locate the control-word block and the sensor bytes. The room
temperature you noted confirms the indoor-temperature byte immediately — most families store it as
twice the reading, so it stands out at once (a few store whole degrees, which the same check finds).
Adding the layout is then usually a single table entry, and you will be asked to confirm the result
on your unit before it ships.

Much of that is now done for you inside the diagnostics file itself. When a report's layout isn't
recognised, the file carries a **ranked list of candidate layouts** — each naming a known model
family, how far its fields are displaced, and the values it decodes from *your* captures. That is why
three states are worth the trouble: one report is mostly zeros, so many candidate layouts explain it
equally well, and only a change of state tells them apart. A candidate has to explain all three.

The candidates are a starting point, not the answer — they are checked against the states you
describe and against your unit's own published settings before anything ships.

The file also now says **which device it came from** — the identifier your unit reports, the product
class that identifier encodes, and the product code. That last one is worth a glance before you
attach the file: if it is flagged as a fallback, it is a built-in default rather than your unit's own,
and saying so in the report saves a round-trip. With a real product code the rest of your model's
published description — its rules, its fault list, and which of its features your particular unit
actually has — can be looked up directly.

**A product code an older release could not look up was not necessarily unknown to the
manufacturer.** Its catalogue answers per **region**, scoped by the country code your account signed
in with, and the regions publish very different sets — one lists 171 air conditioners, another 242,
Japan's lists 30 — while a region it does not recognise gets the complete set. Every product list
shipped here before **v0.38.0** was one region's 171, so an appliance published elsewhere could not
be named at all.

The shipped catalogue now covers **every published air conditioner: 1,451 product codes covering
1,416 model numbers**, collapsing to 26 hardware families — so the count is catalogue entries rather
than distinct machines. (The v0.38.0 listing was later found to be filtered by product category as
well as by region, which had hidden the window air conditioners; every air-conditioner category now
ships. 21 model numbers are carried by more than one product, and where those disagree about their
rules the integration declines to guess between them and falls back to what their family agrees on.) Of the 100 countries the setup
form offers, 94 publish at least one air conditioner and six publish none — Myanmar, Nigeria, Kenya,
Cambodia, Laos and Nepal — where the model shortlist simply is not narrowed by region.

So if an older release could not name your appliance, retry on a current one before assuming the
model is undocumented.

The file carries one more thing that saves a round-trip. Once your unit's layout **is** recognised,
diagnostics reads **every attribute your air conditioner declares** — the settings with no entity as
well as the ones with — and prints them beside the values your unit publishes through its cloud
profile. Two independent sources for the same readings, which is usually enough to confirm a layout
outright, or to show exactly which field is off.
