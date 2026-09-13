# Appliance support

This integration was built for air conditioners and that is where nearly all of its testing lies.
It now covers the rest of the Haier range as well, through a different mechanism — and the
difference matters when you are deciding whether to trust it, so it is set out plainly here.

## How non-air-conditioner support works

There is no per-appliance code. Nobody here wrote a washing-machine driver.

Haier publishes, per product class, the **byte-level layout of a status report**: for every field,
which word and bit it sits at, how long it is, how to scale it, what its options mean and what its
faults are called. The integration ships that map for **165 product types across 36 device classes**,
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
| **Confirmed on hardware** | Real units, commanded and read back | Air conditioners `0212`, `0d12` |
| **Confirmed end to end from a real report** | A real unit's captured report, decoded and driven through Home Assistant; cross-checked against Haier's own cloud | Heat-pump water heater `2001` |
| **Decode validated against a real capture** | A real unit's traffic decoded correctly; never driven through Home Assistant, never commanded | Washing machine `0501` |
| **By construction** | The manufacturer's map and your unit's declaration; **never seen on hardware here** | every other class below |

⚠️ **No command has ever been sent to a non-air-conditioner appliance by this project.** Writes for
those classes use exactly the same single-parameter mechanism that is proven on air conditioners,
with the command ids Haier publishes for that class — but *published is not the same as proven*. If
your appliance refuses a command, the integration records the refusal and retires that control
rather than continuing to offer something that does not work.

If you own any appliance below that is not an air conditioner, **please
[open an issue](TROUBLESHOOTING.md#before-you-open-an-issue) either way** — including one that simply
works. A diagnostics download says exactly what was decoded, and is the whole of what is needed.

## The device classes carried

165 product types, 36 classes. The class is the identifier the appliance announces; it is on the
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

## What is deliberately not supported

**Appliances with no Wi-Fi module of their own.** Bulbs, sockets, curtains, door and motion sensors
that sit behind a Haier gateway do not speak this local protocol and have no address of their own.
No byte map changes that — they are out of reach, not merely unimplemented.

**Settings written through a group command.** Some settings are not written one at a time but as a
block: a water heater's reservation times, a washing machine's programme. No capture anywhere —
this project's or anyone else's — shows one of these being sent to a non-air-conditioner. The
asymmetry is what makes this worth waiting on: a single-parameter write names the one attribute it
changes and a wrong one is rejected, whereas a group write sends a whole block, so a wrong layout
would change several settings at once with nothing to report it. These stay read-only until one can
be verified against a real appliance.

**Classes published only in Haier's older profile format.** 28 of the 193 catalogue entries use a
V2 text profile which keys fields by a Chinese label and a base-36 id, where the declaration gate
speaks English attribute names — there is no bridge between the two. This affects classes `0101`,
`0102`, `0104`, `0202`, `0401`, `0502`, `0601`, `0602`, `0903` and `1801`, plus a few individual
products in otherwise-supported classes. These are the oldest entries in the catalogue and the
fetcher requests the current format first, so a unit sold recently is unlikely to be affected.

## If your appliance is not decoded

The integration will not invent entities it cannot justify: an appliance whose report it cannot
decode keeps working as whatever it was already recognised as, rather than being given a guessed
set of controls. Download diagnostics and
[open an issue](TROUBLESHOOTING.md#before-you-open-an-issue) — the file contains the report, the
class, and what was and was not placed, which is everything needed to add it.
