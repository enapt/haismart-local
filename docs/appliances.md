# Appliance support

This integration was built for air conditioners and that is where nearly all of its testing lies.
The rest of the Haier range is covered through a different mechanism — and the difference matters
when you are deciding whether to trust it, so it is set out plainly here.

## How non-air-conditioner support works

There is no per-appliance code. Nobody here wrote a washing-machine driver.

Haier publishes, per product class, the **byte-level layout of a status report**: for every field,
which word and bit it sits at, how long it is, how to scale it, what its options mean and what its
faults are called. The integration ships that map for **166 product types across 37 device classes**,
and fetches it on demand for a class it does not carry.

That map alone is not enough, because it describes what the *class* can carry, not what *your unit*
has. So a second gate applies: **your appliance's own declaration**, which it reports along with its
status. Only fields your unit declares become entities. This is why a model without a particular
feature does not get a dead control for it.

Each surviving field becomes an entity of the appropriate kind, carrying the manufacturer's own
unit, range, and option labels. See [the README](../README.md#any-other-appliance) for the mapping.

## What is actually proven, and what is not

Be aware of which tier your appliance falls into.

| Tier | What it means | Classes |
|---|---|---|
| **Confirmed on hardware** | Real units, commanded and read back | Air conditioners `0212`, `0d12` (presence and the four-way louvres provisional), `3912` (a window unit); heat-pump water heater `2001` (**setpoint only** — its other settings are decoded but have never been commanded) |
| **Decode validated against a real capture** | A real unit's traffic decoded correctly; never driven through Home Assistant, never commanded | Washing machine `0501`; twin washer + dryer `0504` (read-only, see below) |
| **By construction** | The manufacturer's map and your unit's declaration; **never seen on hardware here** | every other class below |

⚠️ **Only one non-air-conditioner setting has ever been commanded successfully** — a heat-pump
water heater's setpoint, accepted by the appliance and read back (2026-09-14). Every other write on
every other class is still *published, not proven*: they use the same single-parameter mechanism
that works on air conditioners, with the command ids Haier publishes for that class. If your
appliance refuses a command, Home Assistant shows the reason from your appliance's own model, and a
diagnostics download records the refusal.

If you own any appliance below that is not an air conditioner, **please
[open an issue](TROUBLESHOOTING.md#before-you-open-an-issue) either way** — including one that simply
works. A diagnostics download says exactly what was decoded, and is the whole of what is needed.

## The device classes carried

166 product types, 37 classes. The class is the identifier the appliance announces; it is on the
**Model ID** diagnostic sensor's `uplus_id` attribute if you want to check yours.

### Air conditioners — 28 product types

| Class | Kind |
|---|---|
| `0211` `0212` `0214` | Wall-mounted and general split units |
| `0312` | Split units |
| `0d12` `0d21` | Central / cassette cabinets |
| `3912` | Split units |

### Water heaters — 87 product types

| Class | Kind |
|---|---|
| `0612` `0616` `0618` `0619` `061a` | Electric storage water heaters (76 types) |
| `1812` `1813` `1814` `1815` `1817` | Gas water heaters (9 types) |
| `2001` | Heat-pump water heaters (2 types) |

Water heaters get a dedicated `water_heater` entity with the unit's own temperature range and
operating modes.

### Everything else — 50 product types

| Class | Kind |
|---|---|
| `0121` `0122` `0123` `0124` `0128` | Refrigerators |
| `0501` | Washing machines |
| `0504` | Twin washer + dryer (laundry centre) |
| `0901` `0902` | Cooker hoods |
| `0b11` `0b12` | Sterilising cabinets |
| `1a01` | Dishwashers |
| `1d01` | Gas hobs |
| `2101` | Air purifiers |
| `3e01` | Steam ovens |
| `0f01` | Televisions |
| `150e` | Body-composition scales |
| `2702` | Sensors |
| `3b01` | Voice assistants |

These are read and controlled through generic entities. A category gets a dedicated Home Assistant
entity type as support for it is confirmed.

## Twin washer + dryer (`0504`)

The HWD140-BD14LCGNU1 laundry centre is one appliance with two drums, and it reports them in **two
status frames every session**: the dryer in `6D01` (165 bytes) and the washer in `6D02` (225 bytes).
Each is decoded under its own command from the unit's published map and merged into one state. A
frame that stops arriving ages out after two minutes, so that drum's entities go unknown instead of
freezing.

It is identified by its class field. That matters here, because its dryer report is exactly as long
as the extended-36 air-conditioner family's: read by length alone it looks like an air conditioner.
Identified as laundry, it gets **sensors and binary sensors** by default and never a thermostat.

**Both reports are exactly as long as their maps, and every field in them agrees with Haier's own
cloud** for the same moment: all 44 of the dryer's and all 111 of the washer's, on a real capture.
Each drum also carries two programme-name text fields, the programme's identifier
(`smart_local`) and its display name; they are text, so they become no entity.

The map also files a **big-data report per drum**: `7D01` (dryer) and `7D02` (washer). None of
Haier's laundry configurations publishes the query that asks for one, so they are read only if the
machine pushes them, decoded under their own command and placed underneath the status reports. The
readings only they carry, such as motor current, valve states and the dryer's energy totals, are not
declared by this unit's own model, so they stay hidden.

### Controls (off by default)

Turn on **Configure → Enable washer and dryer controls** to get:

* **Start or resume**, **Pause** and **Cancel** buttons for each drum. Start runs the programme
  chosen at the drum's panel; the machine uses one value for start and resume. Cancel abandons the
  cycle: a running drum is paused first, then returned to standby, which is the sequence Haier's own
  app uses.
* The options the machine's configuration marks as writable **on their own** (`operationType`
  `I`): spin speed, wash temperature, dry level and temperature, the dosing and care options and
  so on, 42 in all. Settings it writes only inside a group command are not offered.

**The programme itself is chosen at the machine's panel.** Haier's app never sets a programme with
a single-parameter write: it sends one group command carrying the programme and that programme's
whole parameter set, and a washing machine's board traffic shows exactly that. A programme written
on its own would load without its parameters, and on other Haier washers writing the programme and
the start separately gave spin-only cycles. The **child lock** is not offered either: Haier's
manual says the network can neither set nor clear it.

Every command is a single-parameter `5Dxx` write; the washer drum's carry the `0x80` drum bit. Each
one is refused before anything is sent unless:

* that drum's **remote-control flag is on**. It is set at the machine's panel, and on Haier's
  washers it lapses again when a cycle ends, the programme knob is turned or the door is opened, so
  expect to enable it once per cycle;
* the **child lock is off** — Haier's app refuses every command while it is on;
* for power off, **both drums are idle** by their cycle phase (standby or finished). The running
  mode cannot tell that apart from paused mid-cycle: it reads the same either way.

Never offered: the "long-term authorisation" pair, which would keep remote control allowed with no
panel action; remote power-on; the measured load weight; and the factory resets.

A refused command says why, in Haier's own words: this unit's model publishes no refusal reasons,
so they come from Haier's laundry refusal table — "remote control is not activated", "the door was
opened", "the child lock is on", "this setting cannot be adjusted in this programme" and the rest.

⚠️ No laundry command has been seen accepted yet, and starting a cycle from standby with the single
start command has no confirmed precedent on any Haier washer — the projects that start one send
the group command. The first one sent tells: a refusal shows as an error naming the reason, and the
diagnostics file records every command and its reply. Haier's configuration also defines the group
commands the app starts a programme with (`grCommonDry` 0x60/0001, `grOnlineWash` 0x60/8006, with
every member's word and bit). The dryer's mostly mirrors its status report and could be filled from
it; the washer's carries forty motor and water parameters no report holds.

## How an appliance is identified, and what happens when it is not

Nothing asks you what your appliance is if the appliance can say so. In order:

1. **Its class field** (characters 17–20 of the uPlusId, e.g. `0504`). A class this integration
   names settles it, whatever else says otherwise.
2. **The laundry family.** Any other `05xx` class is a washer or dryer: every `05` configuration
   Haier publishes is one, and Haier's own app files its washer-and-dryer cards under that family.
3. **The cloud's category**, when the appliance was added through an account. "Roller Washer",
   "Dryer" and other laundry words make it laundry; the air-conditioner and water-heater categories
   must match exactly. Neither ever overrides a class from step 1.
4. **You.** If the appliance named a class or category and none of the above recognised it, setup
   asks what it is:
   * **Washer, dryer or washer-dryer**: read-only sensors from every status frame, like `0504`.
   * **Another appliance, not an air conditioner**: never a thermostat or the AC entity set, however
     its report looks.
   * **Decide from its reports**: what happens without an answer. It keeps a thermostat only while
     its report decodes as an air conditioner's, which keeps working an AC nobody has catalogued.

   The answer is in the integration's **Configure** options afterwards, so it can be changed. An
   air conditioner set up the usual way is never asked: it is recognised, or it said nothing, and
   the question then appears in the options once the appliance has identified itself.

A class Haier names as something other than an air conditioner (a refrigerator, a hood, a `0501`
washer) is also never read as one: report length is not identity, and the `0504` dryer's report
proved it.

## What is deliberately not supported

**Appliances with no Wi-Fi module of their own.** Bulbs, sockets, curtains, door and motion sensors
that sit behind a Haier gateway do not speak this local protocol and have no address of their own.
No byte map changes that — they are out of reach, not merely unimplemented.

**Settings written through a group command.** Some settings are not written one at a time but as a
block: a water heater's reservation times, a washing machine's programme. One capture shows one
being sent to a non-air-conditioner — a washing machine's board traffic from another project, where
a single group command starts a cycle — and none shows one sent from Home Assistant. The asymmetry
is what makes this worth waiting on: a single-parameter write names the one attribute it
changes and a wrong one is rejected, whereas a group write sends a whole block, so a wrong layout
would change several settings at once with nothing to report it. These stay read-only until one can
be verified against a real appliance.

**Classes published only in Haier's older profile format.** Of the 193 product types the
manufacturer publishes a configuration for, **166 use the current format and are carried; the other
27 use an older V2 text profile** which keys fields by a Chinese label and a base-36 id, where the
declaration gate speaks English attribute names — there is no bridge between the two. This affects
classes `0101`, `0102`, `0104`, `0202`, `0401`, `0502`, `0601`, `0602`, `0903` and `1801`, plus a few
individual products in otherwise-supported classes. These are the oldest entries in the catalogue and the
fetcher requests the current format first, so a unit sold recently is unlikely to be affected.

## If your appliance is not decoded

The integration will not invent entities it cannot justify: an appliance whose report it cannot
decode keeps working as whatever it was already recognised as, rather than being given a guessed
set of controls. Download diagnostics and
[open an issue](TROUBLESHOOTING.md#before-you-open-an-issue) — the file contains the report, the
class, and what was and was not placed, which is everything needed to add it.
