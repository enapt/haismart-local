# Open items

Each is written to be picked up cold: what it is, why it is not done, and what would settle it.
Anything genuinely settled belongs at the bottom, under **Settled**, not here.

> ## ★★★ 2026-08-15 — a published field this list assumed did not exist
>
> Several items below say a thing "cannot be placed", "is not derivable", or "needs hardware that
> declares it". Those were written against a **published model set one region wide**, and against a
> reading of the published data that omitted one section.
>
> **Every product publishes the ordered attribute list of its group-set command**, and the order is
> the wire order — word ascending, then bit descending within a word. Two published serialisations
> carry the same list under different names, and only one of them was being read. Checked against a
> unit whose list is available both ways: 38 entries, same order, no differences in either direction.
> Across the whole published set, better than nine in ten products carry such a list; the ones that
> do not are the central-air family, which has no group-set command at all.
>
> That does not place everything — a list is in wire order only up to a boundary, after which later
> additions are appended out of order — but it places some things this file records as unplaceable,
> and it brackets many more. Three positions it derives were already known from hardware and were not
> used to derive them, which is the check that it works: the economy setting, the cloud-control flag,
> and the rental timer.
>
> **Recount before trusting any figure here — and count per lineage.** These appliances fall into
> three families that describe themselves in different ways, and a coverage figure computed against
> one family's map understates the others badly. Counted against the map each actually uses:
>
> | lineage | products | attributes it declares | placed | unplaced |
> |---|---|---|---|---|
> | the compact 12-word family | 509 | 31 | **28** | 3 — and all three are the query commands, not readings, so this family is **complete** |
> | the central-air family | 175 | 17 | 11 | 6 — the four cassette vanes, and two supply readings |
> | the wall/floor family | 751 | 185 | 77 | **101** unplaced — but ~49 are NOT controls (rental, telemetry, commands, RGB lighting); only **~52 genuine AC controls**, most already handled (see below) |
>
> ★ The compact family's own published description places four of the most widely declared settings
> that the shared map cannot see at all — a sleep curve, a cloud-adaptive flag, and two healthy-airflow
> settings — because that family is described in a different format the shared map is not built from.
> Its description also carries a **live input-power register**, humidity readings, and roughly twenty
> other positioned fields this integration does not read. See item 31.
>
> Items 5, 8 and 9 are revised below; items 29–31 are new. Item 30 has since shipped; item 31 is
> the largest piece of work remaining.

The numbers are **identifiers, not positions** — items refer to each other by number, so an item
keeps its own when it moves between the two sections. Expect the sequence to have gaps in both.

## 1. Vane positions on a unit whose model understates it

Both axes now offer their positions, as `select` entities beside the swing controls, built from the
stops the unit's own model publishes. The left-right axis needs no translation; its model code is
its wire value. The up-down axis does — a model numbers its stops `0, 2, 4, 5, 6, 8` while the unit
works in `0, 2, 4, 6, 8, 12`.

**That table is no longer resting on the one unit that confirmed it.** It was hardware-confirmed by
stepping a unit through every stop its app offers, one capture per stop; the published map then
reproduced it independently, across every air conditioner model published, including the `7 → 10`
entry no unit here has ever exercised. Two unrelated sources, the same table. That half of this item
is closed, and a test asserts the correspondence field by field.

What is left is only the case where **a model publishes less than the hardware has.** The reference
units here are exactly that: their handsets step the up-down vane through six stops, but their model
lists only `0` (fixed) and `8` (auto), so nothing authorises the six. They get no up-down entity,
which is correct — an option nothing declares is a guess, and a group-set applies the whole word
block, so a wrong value there is not a local mistake.

No map can settle this, because it is not a question about where the field is or what its values
mean; both are known. It is a question of what a *particular* unit will accept, and only that unit
can answer it: a recorded command carrying a position on hardware whose model does not list it.

## 2. Health writes one bit where the vendor app writes three

Toggling Health moves three bits together — its own flag plus the two purification-status bits — and
they have never been observed apart. Our encoder maps `healthMode` to its own bit alone. A unit
commanded from its handset sets the other two itself, so a single-bit write most likely suffices.
That is an assumption. One write from our side, with the report watched, settles it.

## 3. Self-clean reporting on the compact family

Offered on the classic and 165/175-byte families **and now the 117-byte one** (see the end of this
item); still not on the 209-byte family. The two cases were never the same case, and the difference
is worth stating before anyone picks up the one that remains.

**The 209-byte family: the insert point is not pinned, so the flag has two candidate homes.** An
earlier revision of this entry claimed the position was known and only confirmation was missing.
That was wrong, and the arithmetic is worth writing out so nobody repeats it.

What the captures confirm on that family: w20/w21/w22 (setpoint, mode, power) sit unmoved; w35/w36
(indoor, outdoor) sit +10; w25 carries a vane and w26.b9 the fan speed, both inside the inserted
block. So the ten-word block starts **after w22 and at or before w25** — w23, w24 or w25. Each fits
every observation, and they disagree about where the flag lands:

| block starts at | canonical w24 lands at |
|---|---|
| w25 | report **w24** |
| w24 | report **w34** |
| w23 | report **w34** |

Indoor temperature cannot separate them: all three predict canonical w25 → report w35, which is why
it looked settled. Nor can the vane or fan speed — both are inside the block under every reading.
And the frames are silent: **w23, w24, w33 and w34 all read zero in all three captures**, because
nothing on that unit was switched on.

So the flag is at w24 under one reading of three. Shipping it would be a guess wearing the clothes
of a deduction.

**What settles it is cheaper than catching a self-clean cycle.** Any capture from that family with
*any* w24-block feature switched on — Health (which drives the two purification bits), the ambient
light, fresh air — pins the insert point, because exactly one of w24 / w34 will be non-zero. That
places the whole flag block at once, self-clean included.

**The 117-byte family: ✅ shipped.** It is not a displacement of the published map, so nothing
carries over from the shared frame — but that family's own published description places its
self-clean bit (report word 9, alongside the rest of that block; see item 31), and its own paired
command starts a cycle. Both now ship: the running indicator and the last-clean timestamp read the
bit, and the start button sends the family's own start command — offered only to units whose model
declares the function (item 36's declaration gate).

## 5. A timer, on units that publish one

Some units declare `timingPowerOn` / `timingPowerOff` (minute counts, 0–1440) and a `timingStatus` of
cancel / set / keep. Others declare no timer attribute at all and merely hold a handset-set countdown
internally. Where the attributes exist, a timer entity is straightforward and would be the first in
this ecosystem; where they do not, it cannot be offered. Needs hardware that declares them.

⚠️ **The 175-byte family was checked (issue #8) and is the second case: it declares no timer
attribute at all.** Its app timer is app/cloud-side scheduling, and two captures (timer on vs
off) differ only in the live power/energy words. So this family cannot get a timer entity; the
item still waits on hardware that declares `timingPowerOn`/`timingPowerOff`.

The published map cannot answer this one either way, and its silence is not evidence: it carries no
timer attribute, but it is built from the single richest model and keeps only that model's
attributes, so anything another model declares alone never appears in it.

★ **REVISED 2026-08-15 — "needs hardware that declares them" is no longer the blocker.** Counted
across every published air conditioner rather than one region's share of them, **161 products declare
`timingPowerOn`, `timingPowerOff` and `timingStatus`.** So the attributes are common, and a reporter
carrying them is likely rather than hypothetical.

⚠️ What *is* still missing is their position, and the published order does not supply it: on every
model that declares them they sit in the appended tail of the group-set list, past the point where
the list stops being in wire order. So this item stays open, but for a different and narrower
reason — not "no such hardware" but "the order does not reach them". A single report from a unit with
a timer set, against one with it clear, places all three at once.

## 6. The energy total, on the family whose map already has exceptions

The cumulative register counts **watt-hours**, settled on the 165/175-byte family against an owner's
own app: one 15-minute accumulation interval spent cooling added 347 against ~1390 Wh of measured
draw, a 26-minute session added 478 against ~494 expected, and a whole day added 7516 against the
app's 7.52 kWh. That unit now has an Energy sensor.

The classic family's register is published too, on the same reasoning: that family **is** the
published map 19 words earlier, checked against a real report field for field, so the attribute's
unit and position are inherited rather than assumed, and it lands on the report's last two words.
Every classic unit met so far carries the register and leaves it at zero, and zero is reported as
absent — so this changes nothing for almost everyone.

⚠️ **Exactly one unit is known to keep a total, and its magnitude is unconfirmed.** It reads
3,138,753, i.e. ≈ 3,139 kWh, and no reading off that owner's own app has ever been compared against
it. This shipped on *weaker* evidence than the 165/175-byte sensor did: that one had three
measurements on three timescales, this one has a single static capture from hardware nobody here
owns. The justification is that a different question is being asked — there the unit of measure was
unknown, here only the instance is — and that the two candidate readings are far enough apart to
argue for the one taken (a fortnight of use against a few years, on a large reverse-cycle unit long
in service). **Asked for on issue #1. If the answer disagrees, withdraw the sensor rather than
defend it** — a wrong total is not recoverable from once it is in someone's history.

The 209-byte family has a register that works too — the same published attribute, reading a real
total where the classic family reports zero — and it is **not** published. That family is the one
that has been caught departing from the published map three times over (its setpoint counts half
degrees, its vane sits five words on, its fan speed answers from the inserted block), and its
counter's position is derived from the same inserted block. A unit is not the sort of thing to
inherit on the strength of a map the family already disagrees with, because a wrong one settles
permanently into someone's energy history.

One reading off that owner's app, taken beside a diagnostics download, settles it exactly as it was
settled on the other family. The same goes for any new family whose register turns out to be
populated.

## 7. The fault decode has not met a real fault

The bitmap decode follows the vendor's own parser and the labels match the published fault list, but
no unit here has reported a fault. `errCode` gives a free cross-check when one occurs: it names a
single fault where the frame carries the set, so the bit that is set must be `errCode - 1`.

Nothing to do but keep the diagnostic in place and check the first report that arrives.


## 8. The attributes a device declares — read, and the user-facing ones now surfaced

A unit declares three or four times the attributes any family map carries — on the reference units,
42 declared against 14 mapped — and every one of them sits where the published map already says.
Those extra readings are decoded and reported in diagnostics (`model_declared_fields`), because
membership comes from the device's own model and position from the map, and the two are arrived at
independently. On a real 125-byte report they read sensibly, and the screen-display flag agrees with
what that unit published through the cloud.

**The optional ones are now entities** (read-only, diagnostic): the user-facing comfort and
air-treatment functions — fresh air, electric heating, a 10 °C keep-warm, ambient light, an
intelligent mode, humidification, the buzzer, presence-based airflow — appear as sensors on any unit
that *actually has* them. Two gates make that safe: the family must have a confirmed map displacement
(classic and extended-36; the others place nothing), and the model must be known well enough to tell
a real feature from one the generic model over-declares. **A generic model lists every attribute the
product line might have and marks the ones a given unit lacks `invisible`** (they read a permanent
zero); those are dropped, and where that flag is not yet known the unit gets no such entities at all
rather than a guess. Confirmed on a live unit: of 42 declared attributes exactly one is a
non-invisible optional feature, and that one alone appears.

**Still read-only, deliberately.** A group-set write applies the whole word block, so making these
*controls* needs a confirmed write per field — see the write-contract note below. And the ones the
canonical map does not yet place (`mouldProof`, `drying`, `uvSterilizationSwitch`, `pvPowerSavingMode`,
the dual-airflow `*L`/`*R` set, ...) wait on a position; they are declared but cannot be read off any
report.

★ **REVISED 2026-08-15 — four of those now have positions, from the published order.** Where a run of
unknown attributes sits between two attributes the shared map already places, and their widths add up
to exactly the room between them, there is only one way to lay them out. Booleans are the easy case,
because a boolean is one bit and needs no assumption. Unanimous across every model that declares
them, with no conflicts:

| attribute | position | declared by |
|---|---|---|
| `preventHeatstroke` | word 5, bit 15 | 113 products |
| `mouldProof` | word 5, bit 14 | 114 products |
| `drying` | word 5, bit 13 | 113 products |
| `manualDefrosting` | word 5, bit 12 | 83 products |
| `sterilizationSwitch` | word 5, bit 4 | alternates with `selfCleaningStatus` |

(positions in the group-set frame; the report word follows from the family's own base word.)

Those four bits alternate with `humidityCtrlStatus`: of every published air conditioner, exactly
**one** declares both, so a model declares either that attribute or this block, never both. The
dual-airflow `*L`/`*R` set is a separate case and is now item 29 below.

⚠️ Where the fit is *not* exact the run is left unplaced rather than guessed at — a wrong position
does not fail loudly, it decodes. Attributes in the appended tail of a list (see the banner at the
top) get no position this way at all.

**Codes are included, and were not always.** An unscaled number is a code, and for a while every one
of them was dropped on the grounds that the wire numbering need not be the published numbering.
That is true of exactly two attributes in the whole map, and the map carries the correspondence for
both — so the rest were being withheld for want of an answer already given. They are now read: a
code the map translates is translated, and one it does not is already the published value. This is
also what finally made the indoor-humidity reading in item 10 appear.

Most of them stop at diagnostics on purpose. A wrong value there costs nothing; the same value wired
into someone's dashboard is a fault report. What would move one further is the ordinary evidence: a
capture of a unit with it switched on. **The numeric environment readings are the exception as of
item 37** — PM2.5, CO₂, formaldehyde, VOC and indoor humidity are surfaced as sensors on units that
declare the probe (and do not mark it invisible), because for those a zero is "no probe" rather than
a state, the published models bound every one of them, and a value outside the bound is dropped as a
sentinel rather than shown.

**compact-12** cannot have them at all, and that is correct rather than missing — it is not this
lineage, and its own published description is what item 31 covers. **extended-46** was once the
second exclusion, when no single whole-word displacement fit; the piecewise insert (item 27) reads
its declared attributes now, with item 3's caveat about where the flag block lands still standing.


## 9. Eco, on the families that publish the setting but not its place

The Eco ladder is `generatorMode`, and on the classic family it is a three-level current limit whose
position was established from captures: enable plus two level bits, in a word the control block
already covers.

Other families publish the attribute and get no Eco control, because **the published map does not
carry `generatorMode` at all** — it is one of the attributes that exists in a device's own model but
not in the shared map, so the trick that placed two dozen others (item 8) cannot place this one.
Nothing short of captures will do it: Eco off, then each level in turn, one download per state.

**★ The captures arrived (issue #8), and the 165/175-byte family now has the control.** Four
reports, one per state, taken minutes apart on a unit held in cool:

| | w23 bits 3–4 | live input power (w41) |
|---|---|---|
| Eco off | 0 | 1969 W |
| Eco L1 | 1 | 1951 W |
| Eco L2 | 2 | 1798 W |
| Eco L3 | 3 | 1205 W |

Nothing else in the report moved but the outdoor temperature and the energy counters. The ladder
descends with the level, as it does on the classic family, so higher is more restrictive here too.

The field is **word 23 bits 3–4 counting 0/1/2/3**, where the classic family puts it at the same bit
of the same word but spends three bits on it, with an enable bit above two level bits (0/5/6/7).
Both are written and read in the classic representation, so nothing above the family's own map has
to know which it is talking to; the encoder seeded from the report taken with economy off reproduces
each of the other three control words byte for byte.

**Bit 4 is one the shared map assigns to `freshWindSpeed`.** So this is a model-specific attribute
overlapping a shared one, and the control is offered only where the device's own model declares the
setting — a unit without it would otherwise have something else written over. The classic family is
exempt: its field was established from its own captures, in a place no shared map describes.

**Still open on the 209-byte family.** The published map carries no `generatorMode` at all, so
nothing places it there; that family needs the same four captures this one got. The 117-byte family
is no longer in that position: its own published description carries its energy-saving field at word
9 (item 31), so it waits on the reads work, not on a capture.

★ **REVISED 2026-08-15 — the published order brackets it, and agrees with the hardware answer.**
`generatorMode` is declared by **564 products**, and on every model that lists it in the group-set it
falls between two attributes the shared map places — narrowing it to **word 4, bits 1–5**. The
classic family's position, established from captures, is word 4 bits 3–5. So the bracket contains the
measured answer without having been told it, which is the check that the method is sound.

That is a bracket, not a placement: bits 1 and 2 are unaccounted for, and a run with spare bits can
be packed against either end. It is enough to make the captures cheaper — a reporter now needs to
distinguish five candidate bit positions rather than search a word — and not enough to ship. The
four-state capture set remains what settles it.

⚠️ **Off and L1 are only 18 W apart**, which is not the separation the other steps show. Either L1
caps above what the unit was drawing, or it had not finished ramping. Worth one more reading before
anyone describes what L1 *does*; it does not affect where the field is.

## 10. ✅ SHIPPED — indoor humidity, on the units that have the probe

The published map gives the position — the low byte of the word carrying indoor temperature — and it
was long read as zero on every unit here, which is why no sensor was offered.

**That reason stopped being true, and the sensor now ships** (with the air-quality suite, item 37).
A real 125-byte capture reads **55** there, a thoroughly plausible humidity, and the map that places
it is the same one verified field for field against that very report. The gates that make offering
it safe are the ones the optional features already use, plus two of its own: the unit's model must
declare the attribute and not mark it invisible (a probe the hardware lacks gets no entity), a zero
reads as *absent* rather than 0 % (no unit's statistics gain a fabricated bone-dry reading), and
anything above 100 is dropped as a sentinel.

What would still be welcome is the cross-check this item originally asked for: a diagnostics
download from a unit with the probe, taken with the room's actual humidity noted. If a reporter's
reading disagrees with their hygrometer, the sensor comes back out rather than being defended.


## 11. Reads for the central-air-conditioner family — one report unlocks 175 products

**Status: open, and the cheapest high-value item on this list.**

Counted across every region, **175** of the published air conditioners are central/ducted units —
they are 207 of the 215 products no published data places in advance (item 35). Between them they
declare seventeen attributes, and **eleven already have positions** in the shared map —
`onOffStatus`, `operationMode`, `targetTemperature`, `windSpeed`, both vane fields, `muteStatus`,
`rapidMode`, `indoorTemperature`, `tempUnit` among them. Nothing about their layout is unknown
except **which displacement applies**, and that is what the layout prober scores from a report
length plus a few stated states.

**The displacement is derived, not awaited.** A model omits the leading media block or it does not,
and the offset is exactly the span it omits. The regional seventy-nine first swept declare no media
attribute at all — checked against every attribute the shared map places below the climate block —
which is the same thing the classic family does, and the classic family reads nineteen words
earlier. Their attributes occupy the shared map's words twenty through twenty-five, so they occupy
their own report's first six.

Nothing further is needed to read them. What has not happened is a unit of that shape being seen,
which would confirm the derivation rather than produce it.

**⚠️ Re-scoped 2026-08-03 — expect no reporter, and do not treat this as a coverage gap.** The
manufacturer ships **no phone-app interface for this device class in this region**: the app carries
panels for refrigeration, air conditioning (wall and cabinet) and laundry, and none for the class
these products belong to. So an owner here has no vendor app to pair or control them with, and
is correspondingly unlikely to arrive with a report. Two consequences worth stating plainly:

* These products should **not** sit in a coverage denominator for this integration. Quoting "175
  products unsupported" overstates the gap — they are outside what the vendor supports here too.
* The derivation above still stands and costs nothing to keep. If a unit ever does appear, it is
  one report away. **Also useful** (measured on the regional seventy-nine; not yet recounted over
  all 175): **thirty-six publish their attribute list in wire order** (word ascending, bit
  descending — verified against the shared map's anchors with zero violations), so their positions
  can be solved without a capture at all. The other forty-three show one consistent disagreement,
  which means either their list is not ordered or their layout genuinely differs — untestable
  without hardware.

## 12. Control for the central family — a parameter at a time, not a group

**Status: open. Depends on 11 for reads, but is independent work.**

Those models publish **no group-set command** at all — their operations are `getAllProperty`,
`getAllAlarm`, `stopCurrentAlarm`, `getBigDataFrame`. They are written one parameter at a time, a
method the vendor ships and prior art documents.

⚠️ **Do not reuse the group-set safety argument here.** The encoder refuses any field it has not
seen written because a group-set applies a whole word block, so a mistake changes a neighbour rather
than failing. A single-parameter write cannot do that. The family deserves a safety property argued
from its own mechanics — probably narrower than the current allowlist, and certainly not the same
rule copied across without examination.

## 29. ✅ SETTLED FROM SOURCE, AND FIXED — the 209-byte family's group-set writes its own vane/fan, not the tower

**Status: settled without a reporter, and corrected in code.** Three independent lines converge, so
the ten-second reporter test that used to headline this item is now confirmation, not the gate.

Every published model in that family — all of them, identically — lists its group-set attributes in
this order:

    targetTemperature, windDirectionVerticalR, windDirectionVerticalL,
    operationMode, specialMode, windSpeedL, energySavePeriod, … (74 in all)

Packed by the vendor's own rule (word ascending, bit descending), the first 43 entries fill the first
five words **exactly** — eighty bits, nothing spare — which forces the positions:

| position | what the shared single-flow frame puts there | what THIS family publishes there |
|---|---|---|
| word 1, bits 0–3 | `windDirectionVertical` | **`windDirectionVerticalL`** (left tower) |
| word 1, bits 4–7 | *(nothing)* | **`windDirectionVerticalR`** (right tower) |
| word 2, bits 8–10 | `windSpeed` | **`windSpeedL`** (left tower) |

So the shared-frame vane/fan slots are the **towers** on this twin-tower cabinet. The appliance's own
vane and fan fall in the appended tail — group-set **words 6 and 7** — and those map, by the
`write_base_word + write_word − 1` relation, to report words **25 and 26**: exactly where the read map
(established independently from captures) reads `swing_vertical` (w25.b0) and `wind_speed` (w26.b9).
The same shape appears on a second, larger family, so **152 products** are affected.

**Three independent lines, all pointing at the same answer, none needing hardware:**
1. the vendor's published order + packing rule → towers at w1/w2.b8, appliance vane/fan at word 6/7;
2. the captures → appliance vane/fan read back at report w25/w26;
3. the universal write↔read relation → group-set word 6 → report w25, word 7 → report w26.

★ **The fix:** `windDirectionVertical` now writes group-set word 6 (report w25.b0), `windSpeed`
group-set word 7 (report w26.b9), and `word_count` is **7** so the frame reaches them (it was 5,
stopping at w24 — the appliance's own fields were unreachable *and* the code was writing the left
tower at w1/w2.b8). This makes the family OBEY the write↔read relation instead of needing an
exception for it. Read-modify-write seeds words 6–7 from the live report, so nothing else in the
inserted block is disturbed.

⚠️ **The one thing source cannot supply (Rule 8):** confirmation that the appliance *honours* a
7-word frame. The read side is capture-confirmed at these positions and the relation holds, so this
is strictly more correct than the previous behaviour (which wrote the wrong field, the left tower,
and could not reach the appliance's own). A live setpoint/fan change-and-hold would be the final tick;
it is no longer the blocker.

## 30. ✅ SHIPPED — control for the families that were read-only only because nothing confirmed a capture

**Status: SHIPPED.** Control went from 590 products to **1,236** — every appliance whose layout
resolves now commands as well as reads, and nothing is left read-only.

**What made it safe, and none of it needed a capture:**

* the group-set command is **one frame** across every published air conditioner — same settings, same
  words, same bits, and no shift between families;
* the report word that frame starts at is **20 + the layout's own offset**, which is the definition
  restated rather than a constant anyone fitted, and it matches all three families that were
  confirmed on hardware;
* **which** of the frame's settings a given appliance actually has comes from its own published
  group-set list, now shipped for every product that publishes one;
* and where a family keeps a *different* setting at one of those positions, those controls are
  refused (item 32).

**Three gates, each removing a different way of being wrong.** A layout whose appliance has published
no list stays read-only — the frame says where a setting goes, only the appliance says whether it has
one. Two properties carried over unchanged: the seed for every command still comes from a report the
same layout decoded, and whether the appliance honours the write is still only the appliance's to
answer — that bar has not moved. Values are still gated by the model's own declared ranges. What
each unit gets: 502 products all twelve controls, 30 eleven, 114 nine (the twin-tower cabinets,
correctly minus the three they reuse).

Those per-unit counts describe the **646** products reached through published relatives. The 1,236
total is that 646, plus **81** whose family carries its own registered layout, plus **509** of the
compact family — which resolve by report length on first contact and carry their own write command.

⚠️ The old reasoning — *"no capture has confirmed these positions on that appliance"* — was written
before the frame was known to be published and unshifted. It stayed in place after that stopped being
true, which is why one flag held back 44 % of the product line. The read half — resolving an
unfamiliar appliance's layout from its nearest published relatives — had shipped back in v0.35.0
(item 23); this item is what let those layouts command as well.

## 31. ★★ The 117-byte family is described in full — now decoded in full, and awaiting evidence to promote three registers

**Status: the decode is DONE; three fields are held back from becoming entities until a reporter
supplies the evidence that fixes their meaning. Control is unchanged and correctly sourced.**

That family — the largest of the three by product count, **509 products** — has a **complete
published description**: thirty-eight positioned fields, each with its word, bit, width, scaling, the
report it appears in, and the command that writes it. The integration used to read **seven**; it now
reads **all thirty-eight**. Every one of the original seven still sits exactly where the description
says, so the additions are unused capacity taken up, not a correction to what was there.

**But reading a field is not the same as surfacing it as an entity**, and three of the additions are
held in the decode (visible in diagnostics) rather than promoted to a sensor, because position is
settled and *meaning* is not — checked against the three real reports from the issue #4 unit:

| field | where | why it is not an entity yet |
|---|---|---|
| **input power** | word 3, low + high byte | LIVE — it moves with the compressor (0 off, 15 cooling, 0 fan-only) — but 15 is not watts while cooling, so the description's unit cannot be taken at face value. Same bar as the 209-family's counter: no confirmed unit, no sensor. One reporter reading their meter or app beside a capture settles the scale. |
| **word 2 low byte** — outdoor-UNIT temp (not ambient) | word 2, low byte | the description labels it outdoor temperature (`外温`) and that is right: it reads 59/60/60 across off/cool/fan, which is a temperature of the **outdoor unit** (coil/condenser/discharge side), not ambient. ~60 °C off the condenser while cooling is ordinary — the telemetry family's outdoor-air byte runs 60–85 °C for the same reason — and it holds ~59 when off because the outdoor probe is dormant/stale then (the parked-outdoor-temperature behaviour). ⚠️ It is NOT surfaced as an "outdoor temperature" sensor: a user reads that as ambient, and it is stale-when-off besides. Stays `w2_low_raw`, diagnostics-only. (An earlier note here called it humidity — that was a convenient fit not checked against the fact that 60 °C outdoor-unit air is normal; retracted.) |
| the toggles & flags | words 9–10 | positions published; every capture reads them 0, so there is no positive confirmation of the bit. They read back for diagnostics and for the day a capture exercises one. |

The humidity registers (word 11) read 0 on the issue #4 unit — no probe — so they decode as **absent**
rather than a fabricated 0 %, and appear only on a unit that actually has the sensor.

The description also names a per-attribute write command against most fields, alongside the group
command this integration already uses. Both are published; the per-attribute mechanism is what item
12 describes for the central-air family, and this family marks **thirteen of sixteen** settings as
individually writable where ours marks one. The control path stays the group command — it works — so
this is not needed; recorded so the option is known.

★ **So the reads are taken up in full and cost nothing, and the promotion bar is intact:** no new
user-facing entity ships for the 509 products this round. The w2 low byte is an **outdoor-unit**
temperature (hot, stale-when-off) — real, but wrong to surface as an "outdoor temperature" a user
would read as ambient. The power register is live but its **scale** is unproven (only a meter settles
it). That is the v0.32.0 phantom-feature rule holding: a decoded position is not a sensor until its
reading is proven and its meaning is one a user won't misread, and a stale hot-side 60 °C labelled
"outdoor" or a unit-less 15 in someone's dashboard is worse than
its absence.

## 36. ★ The full panel control surface — the panel's controls added across every grSetDAC family

**Status: shipped for every group-set family; what remains is blocked on captures or a second write
mechanism, not on more analysis.**

The app renders a control for a function iff `the device declares the attribute ∧ it is not
invisible ∧ the panel has a widget for it` — a documentary rule, no per-unit probing. So the whole
set of controls the app offers is computable from data we already hold (the device model, the
invisible flags, the panel widget table). The integration used to surface ~12 controls and hold the
rest as read-only sensors, on a per-attribute live-write bar the app never applied. This lifts that.

**Shipped, on EVERY grSetDAC family** (classic, extended-36, extended-46, related layouts):
`haismart_hrdp/panel.py` (the widget table as data) + `coordinator.panel_switch_fields` /
`panel_select_fields` (the app's gate) promote **nine** functions from read-only sensors to real
controls — six positioned by the invariant frame (**electric-heat, fresh air, 10 °C keep-warm,
ambient light, energy saving** switches — the last being the boolean energy-save toggle, distinct
from the multi-level eco ladder, at w5.b6, a position no family reuses; **presence-based airflow**
select, values read from the model enum), and
three by the published order, each unanimous across the 83 products that declare it (**mould
prevention** w5.b14,
**dry-out** w5.b13, **heatstroke prevention** w5.b15 — item 5's positions, re-derived). Each is
offered only where the device declares it and does not mark it invisible, dropped from the read-only
platforms so nothing duplicates. A function the app shows no widget for (`echoStatus`) is still not
offered; that exclusion is the panel's, not a live write's.

**What remains, and why each is BLOCKED rather than merely undone:**
* **five of the eight order booleans** — `constDehumidificationStatus`, `preventSupercooling`,
  `pvPowerSavingMode`, `uvSterilizationSwitch`, `windAvoidance` — place NOWHERE even against the full
  frame (they fall in the append region, which the order does not order). No derivable position, so
  not shipped: a wrong write position decodes silently. One capture per family settles them.
* **dual-airflow** (`windDirectionVerticalL/R`, `windSpeedL/R`) — the twin-tower write positions are
  known (ext46, w1/w2), but **no report we hold reads a tower back**, so they would be write-only
  controls. Blocked on one capture with a tower vane parked non-zero (the same capture item 29 wants).
* **compact-12** — ✅ DONE. Its panel controls (electric-heat, fresh air) are written **one parameter
  at a time** (`4d05`/`4d04`, `4d1f`/`4d1e`) — the paired on/off command carries the value, no
  baseline — and read back from the toggle's own bit. `WireModel.single_param_fields` / `SingleParam`.
  **Health (`4d09`/`4d08`) and the self-clean trigger (`4d26`, start-only) followed**: a
  single-parameter control is now offered by DECLARATION (the unit's model must carry the attribute,
  not invisible), which is the gate that was missing — the health switch and self-clean button reach
  this family without over-offering on the products that lack the function. The remaining published
  pairs (child lock, humidify) stay out on the documentary rule, not the gate: the app's panel
  renders no widget for either.
* **central-air (`0d`)** — the vendor publishes no panel for these, so the app renders no controls
  either; not in scope.
* **`freshWindSpeed`** (fresh-air fan speed) is **withdrawn**, not shipped: its model enum has six
  values (off / low / high / rated / medium / strong, read from the enum descriptions) but the frame
  gives it a **2-bit** slot (holds 0..3), so medium/strong do not fit and it cannot be written
  faithfully. Needs its real width, or the group-set's supported subset, established first. (All
  shipped controls now carry real translations — this was the last piece of English-interim debt.)

⚠️ Rule 8 unchanged: these ship the way the app ships — documentary — and are verified on hardware
the way any control change is (deploy, change-and-hold), never by a per-attribute capture in advance.

## 37. ✅ SHIPPED — the air-quality suite, and the one-word correction it forced

**The environment readings a unit's own model declares are now sensors**: indoor and outdoor PM2.5,
CO₂, formaldehyde, a VOC index, and indoor humidity (item 10). They sit in the ordinary status
report — the published map has carried their positions all along (PM2.5 at map words 29–30, CH₂O/VOC/
CO₂ at 31–33, the level codes at 26) — so no new query, no new frame, and no per-family work beyond
the placement rule each family already has. The gates are the optional-feature ones plus two of
their own: the unit must **declare** the attribute and not mark it `invisible` (a probe the hardware
lacks gets no entity at all); a **zero is absent**, not a reading (a unit without the probe leaves
the register at 0 for its whole service life, and none of these quantities rests at exactly zero in
habitable air — CO₂ never reads below ~400 ppm anywhere near a building); and a value **above the
published maximum** (4095 µg/m³ for PM2.5, 10 000 for CH₂O and CO₂, 1023 for the VOC index, 100 %
for humidity — every published model agrees on each) is a sentinel and is dropped. PM2.5 and CO₂
carry their native Home Assistant device classes; the two level codes (`pm2p5Level`, `airQuality`)
stay in diagnostics, because no published model states what their four values mean and a guessed
label is how the fresh-air fan speed went wrong (item 36).

★ **The correction: the 127-byte layout reads canonical words 25+ one word later, and the declared-
attribute reads were not doing so.** The 127-byte member of the classic family carries one word the
published map does not describe (`targetRentTime`, its report word 6), so everything from the map's
word 25 up sits one further along than the flat displacement says. The confirmed layout table always
knew this — its indoor-temperature offset for the 127-byte report is two bytes past the 125-byte
one — but the declared-attribute placement used the flat rule for both lengths, which put every
declared reading above the flag word (humidity, this whole suite) **one word early on 127-byte
reports: plausible garbage, not zeros.** Nothing user-facing ever showed those values (they reached
diagnostics only, and the reference units carry none of these probes), which is why it survived.
The placement is now per-length where a family's members differ by an inserted word, and the test
pins it to the layout table's own hardware-confirmed offsets rather than to constants: the map's
humidity word must land on the byte the layout table says holds indoor temperature, per length.

The **outdoor unit's three probe temperatures** (outdoor coil, air intake, defrost sensor) also
became sensors — they were already decoded from the engineering report, reaching diagnostics only.
Like the coil and discharge readings they are diagnostic-category, absent rather than −64 °C on
units without the probe, and they join the set that is removed when an appliance refuses the
engineering query in every published form.

What would confirm the suite end to end is one diagnostics download from a unit that actually has
the probes, read beside the vendor app's own air-quality page. If a reporter's readings disagree,
the sensors come back out rather than being defended.

## 32. ✅ SHIPPED — a control must not be sent to a bit this family uses for something else

**Status: fixed. This was a live hazard on 248 published products, one of them a cycle nobody would
want started by accident.**

The group-set command is packed by **position**, and across every published air conditioner it is
otherwise identical: the same 39 settings at the same word, bit and width, with no shift between
families. Eleven families nonetheless keep a **different setting** at one of those positions:

| position | what the shared frame puts there | what these families put there |
|---|---|---|
| word 5, bit 4 | self-clean | **sterilization** |
| word 1, bits 0–3 | the up-down vane | the **left tower's** up-down vane |
| word 1, bits 4–7 | *(nothing)* | the **right tower's** up-down vane |
| word 2, bits 8–10 | fan speed | the **left tower's** fan speed |
| word 5, bit 12 | humidity control | manual defrost |
| word 3, bit 8 | 10 °C keep-warm | the same setting under a newer name — *not* a reuse |

So on those appliances the self-clean button would have started a **sterilization cycle**, and the
swing and fan controls would have moved one tower. Neither fails — a group-set is accepted whole and
the wrong function runs, which is precisely what a write gate exists to prevent.

**The fix:** a control whose position this family gives to a different setting is **not offered**.
Everything else is untouched, so this is a gate and not a retreat — setpoint, mode, on/off and the
comfort settings stay available on every affected unit. A family that has not published such a
departure loses nothing, which is almost all of them.

**How it was established, and why it can be trusted without a capture:** every product that publishes
a group-set command also publishes the ordered list of settings that command carries, and that order
is the wire order. Anchoring on the shared frame and solving the gaps by exact fit — never by
guessing, and refusing wherever the fit is not exact — places those settings. **Every departure is
unanimous across every member of its family**, with no family disagreeing with itself; and the same
method independently rediscovered a position that was already known from hardware, which is the check
that it works.

⚠️ It does **not** follow that these appliances cannot swing or change fan speed — only that the
shared position is the wrong way to ask. Reaching the appliance-level setting means writing both
towers, and only the up-down vane publishes both; the right tower's fan speed is in the unordered
tail of the list and has no position yet. That is item 29's remaining half.

## 33. ✅ SHIPPED — a whole category of air conditioner was invisible

**Status: fixed. Window air conditioners were never in the product list at all.**

The shipped product list is built by asking the manufacturer's catalogue for air conditioners. It
asked for **three** appliance categories — central, wall mounted and floor standing — because those
are the three someone wrote down. The app's own model picker asks for **no category** and lets the
owner narrow afterwards.

Asked without a category filter, the catalogue answers with **1,999 products across 38 categories**,
and among them is a fourth air-conditioner category: **window air conditioners**. Those four
products publish the ordinary air-conditioner command set — including the group-set command, with
**thirty of its thirty-three settings landing exactly where the shared frame puts them and no
ordering contradictions at all** — so they were fully supportable and simply absent. Twelve central
units from one brand were missing for the same reason.

**Sixteen products added.** The list now holds **1,451**.

★ **The general lesson, and it is the second time:** an earlier release found this list was scoped by
the *country* an account signs in with, and swept every region. This one was scoped by *category*
as well. Both times a parameter **we chose** was mistaken for a property of the data. The list is now
built by asking with no category and no recognised region, which returns everything in one pass —
verified by re-asking region by region and getting nothing new.

⚠️ Two neighbouring categories were checked and deliberately left out: **dehumidifiers** publish a
*different* group command, and **air purifiers** publish none at all. Same transport, different
contract — they would need their own work, not an entry in this list.

# Settled

Not open items. They are here because each looks like something to "fix" until you know why it is
the way it is.

## The layout prober is told what the captures were

Since v0.35.0 the prober is the *second* thing to run, not the first: an unfamiliar report is
matched against the offsets its nearest published relatives use, and the prober is what remains for
the reports that survive that — a layout no relative explains. Its output is still a shortlist to verify
rather than a result.

`probe_layout` scores against `stated=[StatedState(...)]` — what each capture was known to be in — as
heavily as it scores the device's published values, and a contradiction costs more than a match
earns. That takes the cloud off the critical path: on two real reports, 77 of 83 candidates tie at
the top score on plausibility alone, and the stated states separate them. `mode_group`/`fan_group`
carry the relational half, so a reporter's "cool" and "fan-only" work without anyone knowing the
model's codes.

The plumbing that was missing is now there. The report form has **one box per capture**, so a file
arrives paired with the state it was taken in instead of three files landing beside a paragraph, and
`scripts/probe-diagnostics.py` takes those files with `--state` arguments and prints the ranking.
Diagnostics also dumps the device's reported values now (`digital_model.reported_values`), so a
search re-run over the attachments scores on exactly what the in-file candidates were scored on
rather than on plausibility alone.

What is *not* solved, and cannot be from this direction: the search inside diagnostics still runs
unaided, because Home Assistant has no way to know what state a unit was put in. The states have to
enter from the issue, which is why they are collected there.

## The one rule we decline to honour

`locked_attributes` decides which commands a unit will discard: a unit in fan-only shows no setpoint,
boost and quiet refuse in the modes that discard them, and a faulted unit accepts only power and
mode.

⚠️ It used to drive entity **availability** as well, and that was wrong — see item 24. A setting the
unit ignores in its current mode is normal operation, so the entity stays and the *command* is
refused. The setpoint is still dropped from the thermostat, because a climate entity has a real
mechanism for that.

The rules are fetched per device, from the model its own maker publishes. A device's shadow — what
onboarding used to store on its own — carries attributes and their values but no rules at all, so
they are looked up separately and merged in: the account's resource service answers with a URL, the
file is downloaded and its `modifiers`, `alarms` and `constraints` kept. Entries created before that
existed top themselves up once on startup. A unit whose model publishes no rules simply gets none,
which locks nothing — the safe direction — and `haismart_hrdp.device_rules` still records them for
one family as a fallback for an install with no cloud credentials at all.

One rule is deliberately skipped, and it is worth knowing why before anyone "fixes" it. A model marks
nearly everything unwritable **while the unit is off** — including `operationMode`, which is exactly
what this integration writes to turn a unit on, and which real hardware accepts. So that rule
describes an app greying out its own buttons, not what the unit discards, and honouring it would take
away the controls someone reaches for while setting up an air conditioner that is off. The self-clean
half of the same rule is honoured; a cycle really does hold the unit.

The second carve-out is the preset control, which is evaluated as though no comfort setting were on.
A preset write clears its siblings, so a rule that lets sleep lock boost would strand the control
that is meant to undo it.

Writes are **not** gated on any of this — only availability is. Turning a unit on means writing its
mode while it is off.

---

## 4. One setting that decodes and reads but cannot be *written* — tested, not assumed

**Status: settled both ways. `echoStatus` stays read-only; `selfCleaningStatus` turned out to be
writable and ships as a control since v0.34.0.** They are kept together because the pair is the whole
argument: two attributes the model describes identically, one honoured and one silently discarded,
and a free test that told them apart in advance.

`echoStatus` (the command-confirmation beeper, where set = silent) and `selfCleaningStatus` both
decode cleanly and are marked `writeType=G`/writable by the device model. On paper both belonged in
the write map. One of them did not, and this is no longer an assumption.

**A live write settled `echoStatus`: the hardware silently ignores it.** On a real unit, a
self-verifying write — seed from the unit's own status, flip exactly one bit, read back, revert —
was run against two bits of the same word: `screenDisplayStatus` (the display light, a control we
already ship) flipped and reverted cleanly, while `echoStatus`, byte-identical treatment, left the
word **unchanged**. The op is accepted and the bit never lands. So `writeType=G` is necessary but not
sufficient; the unit is the only authority on whether a group-set write takes. As a control it would
silently do nothing, which is worse than absent — so it stays a **read-only sensor**, which is
exactly how it now ships.

⚠️ **Corrected 2026-08-02 — an earlier revision said the manufacturer's own app offers this control.
It does not.** That claim came from the device model marking the attribute visible and writable, which
is not the same thing. The app's air-conditioner control panel — the bundle the app actually renders,
fetched for this exact unit — **never mentions `echoStatus` anywhere**, while every other control it
offers appears 7 to 88 times. There is no beeper control in the app, and none on the handset either.

That makes the panel a **free predictor of what a unit will honour, and on the evidence a perfect
one.** Of this unit's fourteen attributes that the model marks visible, thirteen are referenced by
the panel and one is not — and the one that is not is exactly the one the hardware discards. So the
sequence to follow before offering any new control is four steps, not two:

1. the device's model **declares** the attribute (it exists on this product line),
2. the model does **not** mark it `invisible` (this particular unit has it),
3. the **panel references it** (the manufacturer renders a control for it), and only then
4. a **live self-verifying write** confirms the unit honours it.

Step 3 costs nothing and would have predicted the `echoStatus` result without touching hardware.
Step 4 is still required — it is the only one that observes the unit itself.

`selfCleaningStatus` was not tested the same way because writing it starts a self-clean cycle that
runs to completion and cannot be called back — not a thing to trigger on a whim on someone's unit.
It had both halves of its *state transition* observed but no confirmed *write*.

**✅ RESOLVED 2026-08-04 — confirmed on hardware and shipped.** A live self-verifying write on the
classic family, with the unit on and not in auto/sleep, set exactly word 5 bit 4: it read back set on
the next poll and the unit's panel showed **CL** — a cycle started. So unlike `echoStatus` (published
and model-writable but silently dropped), self-clean is honoured. It now ships as a **"Start
self-clean" button** (a one-shot trigger — the cycle can't be called back, so it is a button, not a
switch), plus a **"Last self-clean" timestamp sensor** for "days since"-style automations. Its
writability is gated by the model's own modifiers (off / auto / sleep / fault) via `locked_fields`.
The panel reference predicted the outcome; the write settled it.

⚠️ **A prediction this file made, which the test then disproved — left standing because being wrong
about it is instructive.** Before the write was attempted, this section argued that one bit would not
be enough: other implementations of this protocol start a cleaning cycle by setting the flag
**together with the machine state the cycle needs** — powered on, dry mode, a 22 °C set point, both
vanes centred, the display off, and the other cleaning flag explicitly cleared — so a test that
flipped the flag alone and saw nothing was expected to prove nothing.

**One bit was enough.** Word 5 bit 4, on a unit that was merely on and not in auto or sleep, read
back set and started a cycle. What another implementation *chooses* to send is evidence about that
implementation, not about what the appliance requires — the reason it sets the surrounding state is
plausibly that it wants the cycle to run under known conditions, not that the firmware demands it.
Prior art narrows the search; only the unit answers the question.

Worth separating from the above: the **56 °C sterilising** flag lives in a different word from the
ordinary self-clean flag, and there is reason to think it behaves as a *trigger* rather than a stored
setting — an implementation that re-sends a status-derived baseline has to clear that word explicitly
or it re-starts the cycle it just read back. Our control path carries the baseline forward untouched,
which is the safe default for a setting and the wrong one for a trigger. Neither has been observed
here, and the two should not be tested as if they were the same field.

The general rule this leaves: **the model gives the candidate list of controls; a live self-verifying
write gives the verdict.** Any control added beyond the confirmed set must pass that live write on
real hardware first.

## 13. The four-sided cassette vanes — what is known, and why it stops there

**Status: as far as published material goes. Not a request.**

Seventeen central models expose four independent vanes instead of one left-right field. Established
without hardware: they **replace** the left-right field, being the only difference between the nine-
and twelve-attribute variants of one family; they are **three bits each** on the same code range as
the field they replace; and no model anywhere declares both, so the two never coexist.

Two things do not follow and were once written here as though they did. Their **position** is not
determined — the models that list them meaningfully put them after everything else they describe, in
a region that provably does not follow the wire, and replacing a field in an attribute set is not
occupying its bits. Their **order among themselves** is consistent — every one of the eleven
meaningful listings gives second, first, fourth, third, never numerically — which is a convention
rather than an accident, but says nothing about which word they live in.

Four identical fields with identical encodings are symmetric, and no amount of published description
separates them: it would take a reading in which they differ. Nothing published contains one. This is
therefore a closed item rather than an open one. ⚠️ It is no longer true that no model of this shape
is carried at all — the shipped list now includes the central-air family these belong to, the
AQUA-branded units among them, with identities and rules; but none has a placed layout yet (item
11), so the cost of leaving this closed is still nothing.

## 14. Deploy and verify the shipped rules — done

**Status: closed 2026-08-04. Deployed and cross-checked on hardware.**

The rules for every published air conditioner travel with the integration — all 1,451 products in
26 families as of the full-catalogue sweep; the bundle held the regional 171 when this check was
run — and the coordinator consults them when the catalogue cannot be reached. On a firewalled
installation — which is the configuration this integration is for — that is the ordinary path
rather than the fallback.

It changes startup behaviour, and this project has twice shipped decode work that passed every test
and was only caught by deploying, so the check asked for here was: deploy, diff
`model_declared_fields` against `digital_model.reported_values`, and confirm entity availability is
unchanged on a unit whose rules previously came from the cloud. All three were run:

- **19 comparable readings, 19 agreeing.** The only two differences are how the numbers are written
  — `15.0` against `"15"`, `30.0` against `"30"` — the wire giving a number and the cloud a string of
  the same value.
- **The shipped copy and the fetched copy agree** on the device's identity
  (`model_rules_agreement: agree`), which is the check that exists because a fetched copy is matched
  on the very code that would be wrong if it were wrong.
- **Locking is unchanged and correctly conditional**: in fan-only the unit locks
  `targetTemperature`, `ecoMode`, `muteStatus`, `rapidMode` and `silentSleepStatus`, and exactly
  those commands are refused. (At the time this was checked those entities went *unavailable*; item
  24 changed that to a refusal, without changing which fields lock.)

⚠️ **Verified on one unit of one family.** The shipped rules now cover 1,451 products (171 when
this check ran); this exercises the path, not the table.

✅ **Found while running that check, and fixed: diagnostics did not print the `invisible` flags.**
The model summary kept value ranges only, so "does this install know the unit's real feature set?"
— the thing that decides whether the optional-feature entities can be trusted at all — could not be
answered from the file. It had to be inferred from whether those entities happened to look sane,
which is indirect evidence for something the file can simply state.

It now carries `feature_set_known` and `invisible_attributes`. The two are separate on purpose:
**present-but-empty and absent mean different things** — empty is "we know, and this unit lacks
nothing", absent is "we do not know, so nothing optional is offered" — and an empty list alone would
collapse them. Confirmed on hardware: `feature_set_known: true`, **28 of 42 attributes invisible**,
which is why exactly one optional feature (`buzzer_silent`) appears and no phantoms do.

## 15. The compact family, resolved as far as it can be — superseded; see item 31

**Status: superseded on its central claim.** This item closed on "what remains is not obtainable
from anything published", and that verdict did not survive a fuller reading: the family's **own raw
description** states thirty-eight positioned fields — word, bit, width, scaling, and the command
that writes each — where the derived extract this item was measured against keeps thirty. Item 31
carries the current state. What follows is kept for the naming work, which stands, and for the
lesson in how the gap was mis-measured.

Its twelve-word report is fully described. Every position this project already decoded agrees with
that description, and two separate published descriptions of the family agree with each other on
every position and identifier they share. Of the thirty positions in the extract, twenty-five carry
a standard attribute name: eighteen joined through the identifiers the catalogue publishes, seven
more read directly from their labels onto names the family declares.

The slots that stayed unnamed here describe an air quality figure, a two-byte power reading, a
particulate value and a room humidity. This item read them as hardware the product line has and
these particular products lack — every one reads zero in every report available here — and that
remains the right reading of a zero on *these* units. What it is not is grounds to close the
layout: the positions are published, item 31 names them, and a unit that has one of those probes is
one report away from being read.

This item then recorded — corrected once already on 2026-08-03 — that `cloudControlStatus` and
`sleepCurveStatus` had no stated position anywhere. ✅ **Both are placed: word 9 of the family's own
raw description**, beside its lock, electric-heat, self-clean and energy-saving bits (item 31). The
enumeration that reported them absent was run over the **derived extract**, which keeps the
per-attribute records and drops other lines — an adapter mistaken for its source, the same shape of
error the banner at the top of this file records for the group-set order.

★ **Why it was missed is the more useful part.** Every coverage figure this project has quoted was
computed against the shared map, and that map is generated from **one of the two published formats
only** — so this family's description contributes nothing to it, and this family's attributes were
never counted against anything at all. **Coverage must be counted per family, never against the
shared map alone.** A companion false positive to expect in the other direction: an attribute can
read as "unplaced" merely because it is published nowhere while being perfectly well known from
hardware, which is the case for the eco setting.

This item last recorded two readings as unresolvable, "neither settleable from published material".
The published description **positions** both, and both are now decoded (item 31):

* the **word 2 low byte** is a single byte, not half of a 16-bit word — reading the two bytes together
  is what put the reading near sixty as one number. As a byte it is ~60, and that IS a sensible
  reading: the vendor's `外温` is a temperature of the **outdoor unit** (coil/condenser/discharge
  side), which runs ~60 °C while cooling — the same reason the telemetry family's outdoor-air byte
  reads 60–85 °C — and holds stale ~59 when off. It is not ambient outdoor air (that would be
  impossible at 60), so it is diagnostics-only (`w2_low_raw`), never an "outdoor temperature" sensor.
  ⚠️ An earlier revision of this line called it humidity; that was a convenient fit not checked
  against the outdoor-unit-air fact already in the corpus. Retracted (see item 31).
* the power reading is a **live input-power register** — word 3, low and high bytes — now decoded, but
  it reads 15 while cooling, so its unit is unproven and it stays in diagnostics until a known draw
  fixes the scale. Item 31.

Neither is surfaced yet; item 31 is where that happens.

## 16. A layout that is not a displacement

**Status: recorded, not urgent — no model of this shape is sold in the region this integration
serves.**

Every layout supported here is the shared map read at a whole-word offset, and everything published
for this region is exactly that. One published model elsewhere is not: from its second word on it is
the shared map, matching on word, bit and width for every attribute compared — but its **first word
merges what the map spends two words on**, and squeezes the setpoint into four bits instead of eight.

Nothing needs doing. It is written down because the shape of the claim matters: "every layout is the
shared map at an offset" is true of what this integration meets and false of the wider published set,
and a decoder that assumed the stronger version would mis-read such a unit's setpoint, mode and fan
in a way that still produces plausible numbers. If a report arrives that decodes sensibly from the
second word and nonsensically in the first, this is the shape to suspect.

⚠️ **v0.35.0 makes this worth re-reading.** Resolving an unfamiliar report against the offsets its
nearest published relatives use assumes exactly the stronger claim — that the only difference is
where the block starts. A unit of the shape above would be shortlisted like any other. What stops it
being mis-read is the same thing that stops any wrong candidate: the decode has to produce the core
readings *and* find them plausible, and a merged first word puts the setpoint in four bits, which
does not survive that. That is a guard, not a proof. A model of this shape appearing in-region is the
case where the resolver should be checked before it is trusted.

## 17. What still needs the cloud — settled, and it is one thing

**Status: closed. Recorded so it is not re-opened.**

Checked row by row against shipped code rather than estimated. Everything a device needs to be
discovered, decoded, gated and controlled now resolves without any per-model cloud request:

| needed | where it comes from | cloud? |
|---|---|---|
| address | DHCP, ARP, or the key-free LAN discovery query | no |
| device id | it is the MAC | no |
| the wire-model key | the LAN discovery reply, no key and no account | no |
| the byte map | ships with the integration | no |
| rules — locks, faults, co-commands | ship with the integration, all 1,451 published products | no |
| which features a unit actually has | derived from those same shipped rules | no |
| the product code that keys them | the model number printed on the unit — 1,416 of 1,451 name exactly one product; the 21 shared names (56 products) fall back to the rules their whole family agrees on | no |
| live readings | read from the unit | no |
| **the local key** | the manufacturer's gateway | **yes — the only one** |

Two caveats worth keeping visible rather than buried:

* Fetching the key still needs an **account sign-in**. "No cloud" here means no per-model cloud
  data, not no account has ever been used.
* The key **rotates several times a day** — unless the unit is firewalled, which freezes it. That is
  precisely why "fetch once, then firewall" is the working configuration rather than a workaround.

One ordering detail that already behaves correctly and should stay that way: the wire-model key is
learned from the discovery query **before** the first report is decoded, in the same first poll. A
device is therefore never decoded by report length before its own identifier is known, and moving
the discovery call later would silently reintroduce that window.

## 18. How this compares to the vendor app — and the one thing it deliberately will not do

**Status: settled. Recorded because "does it do everything the app does?" keeps being asked, and the
honest answer is neither yes nor no.**

**On which units are supported, it is exact parity — measured on the regional catalogue as it then
stood.** Of those 171 air conditioners, this integration reached a byte map for 92 — precisely the
ones the manufacturer publishes a phone-app interface for. The 79 it could not map are the
central/ducted family, for which the app carries no interface either. The same product-lineage split
drives both, which is why the two sets coincide rather than merely being the same size. ★ The
full-catalogue recount is in the section below ("Why the coverage is as wide as it is"): **1,236 of
1,451 placed**, and the unplaced remainder is still almost exactly that same central-air class
(item 35).

**Three things the app does that this does not:**

* **It can display an attribute it cannot decode.** Where the app has no usable layout for a unit it
  falls back to values reported by the manufacturer's servers. That is how it can show settings this
  integration cannot place — including the settings still unpositioned, 108 of them on the
  wall/floor family alone (item 19). This integration reads only
  what it can decode from the unit itself, so an attribute it cannot place is simply absent rather
  than filled in from elsewhere. **That is a deliberate choice, not a defect**: a value that did not
  come from the appliance is a value that can be stale, wrong, or unavailable exactly when the
  network is.

  ⚠️ **This is not the app having a better description of these appliances — it reads the same
  published descriptions this does.** Wherever a setting is unplaced here it is unplaced for the app
  too. Of the models declaring one of the still-unpositioned settings (measured when that set was
  the regional nine; the full-catalogue recount widens the set, not the argument), **six have an
  exact published description for their own model and the setting is still not in it**; the rest
  reach one only through a close relative, or not at all. A description that fits a model exactly
  and still omits a setting means the setting was **added after that description was published** —
  these are recent features on recent hardware, not omissions. So the difference is not the map; it
  is that the app has a server to ask when the map runs out, and this integration deliberately does
  not.
* **Timers are family-dependent, and no entity ships yet either way.** The one family checked (a
  reporter's) declares no timer attribute at all — its app timer is server-side scheduling, and for
  that family there is genuinely nothing local to drive an entity with. But **161 products do
  declare the local timer attributes**; nothing ships for them either, because their position is
  past the point where the published order stops being wire order (item 5). Home Assistant's own
  automations are the dependable answer in both cases, and depend on nobody's cloud.
* Pairing, firmware updates, sharing and push notifications are all server functions and out of
  scope.

**Two things this does that the app cannot:**

* **Control an appliance with no internet access.** These modules do not announce themselves over
  mDNS, so the app's local discovery never finds them, and its session depends on the manufacturer's
  servers regardless. An appliance firewalled off the internet is fully controllable here and not
  from the app. That is the entire purpose of this integration, and why "fetch the key once, then
  firewall the unit" is the recommended configuration rather than a workaround.
* **Report the refrigeration circuit** — live input power, compressor current and frequency, coil
  temperatures, and faults as named service codes — none of which the app surfaces as such.

So the accurate claim is **parity with what the app can do locally, on every model it supports**, and
a deliberate decline of what it does through the cloud.

### ★ Why the coverage is as wide as it is — a close relative counts

**Added 2026-08-15.** The manufacturer publishes only a **handful** of byte-level descriptions for
air conditioners — eight, across a line of 1,451 products. An approach that required each appliance
to have a description bearing *its own* identifier would reach **518 of them**.

This integration does not require that. Identifiers in this line are **hierarchical**: an appliance
shares a long leading run with its close relatives — the same specification a revision or two apart —
and every published air conditioner is the *same map at a whole-word offset* (§27, §23). So a model
with no description of its own is matched to its nearest published relative, which takes coverage to
**1,236 of 1,451 (85 %)** from the very same eight descriptions.

★ **The similarity threshold is not a tuning knob.** Sorted by how much each family shares with the
nearest published description, the ones that match share **26–32 characters** and the ones that do
not share **19 or fewer**. **Nothing falls in between.** The cut-off sits in an empty gap, so it is
not trading false matches against missed ones — anywhere in that gap gives the identical answer.
That is also why it is **not** loosened to reach the last handful (§35): they differ *inside* the
appliance-type field, which is a real boundary rather than a near miss.

⚠️ **Your own appliance is very likely a sub-variant, not an unknown.** "There is no description
published under this exact model" and "this model cannot be decoded" are different statements, and
only the first is usually true.

## 19. The settings nobody's hardware has reported yet — recounted, and no longer nine

**Status: open on the wall/floor family, parked elsewhere. Nothing is waiting on it and nothing can
go wrong because of it — none of these is surfaced, so none can be mis-read.**

This item used to say **nine** settings lacked a position, that they **could not be derived**, and
that the map should be treated as complete for everything locally derivable. All three were measured
against one region's catalogue and one family's map, and the 2026-08-15 recount (the banner at the
top) replaces them. Counted per family, against the description each family actually uses:

* the **compact family is complete** — its three unplaced entries are query commands, not readings
  (item 31);
* the **central-air family** has six unplaced: the four cassette vanes (item 13) and two supply
  readings;
* the **wall/floor family has ~101 unplaced attributes — but that number is not the missing-control
  gap.** Filtered by what the attribute actually is: **~49 are not controls at all** — rental /
  shared-AC management (`useMode`, `localCtrValid`, `rentTimingStatus`, `targetRentTime`), energy and
  power **telemetry** — sensors, never controls, and mostly **already surfaced** (`acInput` reads as
  the power sensor, `totalElectricityUsed`/`accumulatedUseMainsPower` as the energy sensor; they only
  look "unplaced" because that was measured against the shared map, which does not carry the
  family-specific energy reads — only the solar/storage registers `pvInput` / photovoltaic /
  storage-supply are genuinely unsurfaced, and those are niche PV telemetry), **query-command
  pseudo-attributes** (`getAllAlarm`,
  `getAllProperty`, `stopCurrentAlarm`), **system / config / identity** (`irCode`, `vboxId`,
  `languageTypes`, `securityStatus`, `privateDataTransStatus`, `installationPosition`, …) and **RGB
  scenario-lighting** effects (twenty `scenarioLight*` keys, on a single product). That leaves **~52
  genuine AC control/feature attributes**, and most of THOSE are already handled — `generatorMode`
  is eco (placed), the dual-airflow `*L`/`*R` set is blocked on read-back, the timer trio on
  position, and `mouldProof`/`drying`/`preventHeatstroke` shipped this session. **Quote the filtered
  figure, not 101** — counting rental fields, sensors, commands and lighting effects as "missing AC
  controls" is what inflates it.

"They cannot be derived" also fell. The published group-set order places settings wherever a run of
unknowns fits exactly between two known positions — five were placed that way in one pass (item 8)
— and brackets more (item 9). What derivation genuinely cannot reach is the **appended tail**: a
list is in wire order only up to a boundary, and later additions land past it, unordered. The
handful of genuine controls that remain are open-but-blocked on exactly that — not nonexistent, and
not beyond evidence. The vendor app is in the same position locally and covers it by asking a server,
which this integration deliberately does not do.

What settles any single one of them is unchanged: **a report from a unit that actually has the
feature, taken with the feature in a known state.** The layout prober already scores against
written-down states, so one report with the feature on and one with it off places it. Until then,
everything else about those models decodes normally — a unit missing one of these is otherwise
fully supported.

## 20. Which model this is — why it is asked, and what happens if you skip

**Status: settled. Recorded because "why does it ask?" is a fair question with a non-obvious answer.**

An appliance announces which product **family** it belongs to, and that is as far as the wire goes.
It does not announce which model it is, and — this is the part worth knowing — **neither does
anything else about it**. Of the twenty-three products sharing our reference units' family, nineteen
are indistinguishable from the appliance itself: identical declared settings, identical real feature
sets. Those nineteen still carry **four different rule sets** between them. Two units can be
byte-for-byte the same to every observation available and still be governed by different rules, so
no amount of probing can recover the difference. The information is not in the appliance.

**The manufacturer does not derive it either — it asks.** Adding an appliance to the vendor app
requires choosing the product from a list, and what the account reports afterwards is the stored
record of that answer. Signing in here reads that same answer back, which is why the account path
never asks. Only a hand-made entry, set up from a saved key with no account, has nobody to ask —
so it asks you, from the shortlist that appliance's own family implies, in model numbers off the
label rather than internal codes.

**Skipping costs less than it sounds.** Where the model is unknown, the rules every member of the
family agrees on are applied instead, which is safe whichever model it turns out to be. The
agreement is lopsided in the useful direction — across every published family:

| what | how much survives without knowing the model |
|---|---|
| fault names | **all of them** |
| explanations for why a control is unavailable | **all of them** |
| settings that must be written together | about half |
| rules for when a control is unavailable | about a quarter |

So the part anyone actually sees — a fault reported as a named service code rather than a number —
arrives complete with nothing chosen. What thins out is conditional availability, and it thins out
safely: a rule nobody disagrees about cannot make the wrong control unavailable, and a missing rule
makes nothing unavailable at all.

One deliberate asymmetry: a setting that **any** member of the family lacks is treated as absent for
all of them. Offering a control for hardware a unit does not have is the failure this layer exists
to prevent, so where the family disagrees, the conservative reading wins.

## 21. A reading that looked intermittent, and the rule that came out of it — settled

**Status: fixed and verified on hardware. Recorded because the mistake is easy to repeat.**

The compressor discharge reading appeared once and was absent afterwards, which looked like a
failing probe and kept an argument about what that byte means alive for weeks. The appliance had
been reporting it correctly the whole time.

With the unit cooling hard — 78 Hz, 8 A, 1790 W — the discharge line reads **80 °C**, which is
ordinary for a discharge line and impossible for room air. The decoder discarded it, because every
temperature was checked against one range chosen for air temperatures, topping out at 70. The single
earlier sighting was the same reading at lighter load, one degree inside that range.

**The lesson generalises past this reading.** A range check on a position that is already confirmed
cannot prevent a wrong decode — it can only hide one, and it hides it in the worst possible form:

* an implausible **number** is visible, gets reported, and gets fixed;
* **nothing at all** is indistinguishable from an appliance that has no such sensor, so it is never
  reported by anyone.

That second case is exactly what happened, and it is self-reinforcing, because "a zero means the
hardware is absent" is a sound rule here — so a filter that manufactures absence produces a
conclusion that looks correct.

Temperatures are now bounded by what is physically possible rather than by what was expected. The
absent-sensor markers stay, because those are values the appliance actually sends rather than an
opinion about what is reasonable.

Two related changes came out of the same investigation:

* the telemetry frame is now included in diagnostics alongside the status frame, so a question about
  a compressor or coil reading can be answered from a bug report rather than needing the appliance;
* when a guard is moved or duplicated, the original must go. This one had been written to do two
  jobs, both of which moved elsewhere, and it kept running with neither reason still attached.

## 22. Whatever a poll reports, a command's reply must report too — settled

**Status: fixed, and written down as a rule because it has now happened three times.**

The reply an appliance sends after a command is a status report and nothing else. It carries no
fault frame, and for a while it carried no compressor telemetry either. Publishing that reply
unchanged therefore blanked every reading that was not in it — and a command also pushes the next
poll a full interval away, so those readings stayed blank for a while rather than flickering.

On a **problem** sensor that is worse than it sounds: "unknown" reads as the check having stopped
working, not as "nothing to report".

It has been fixed three times now, once per reading that hit it — the compressor figures, then the
fault sensor, then the optional-feature sensors. So the test no longer guards those three; it
guards the rule:

> Whatever a poll publishes beyond the plain status, a command's reply has to publish too — either
> by re-reading it from the reply, or by holding the last value for a bounded time.

Which of the two depends on where the reading comes from. The optional-feature states are in the
status words, so they are re-read from the reply itself. The fault frame is not in it at all, so the
last reading stands in — for the same span as the telemetry, and for the same reason: past that it
no longer speaks for the appliance, and honest silence beats a stale answer.

⚠️ **The first attempt at this fix did nothing**, and passed its tests. It was placed on the polling
path, while a command's reply is handled somewhere else entirely. A correct function on a path that
never runs looks exactly like no fix at all from the outside — worth remembering for anything in
this area, since reads and commands take genuinely different routes through the code.

## 23. Layouts resolved from the nearest published relatives — shipped

**Status: shipped in v0.35.0, verified on hardware. Recorded because of what it assumes and what it
deliberately declines to do.**

An air conditioner whose exact layout nobody has reported used to fall back to the handful of
readings that are identical on every model. It is now usually read in full instead: every published
model is the shared map at one of a few whole-word offsets, a Model ID shares its leading characters
with its close relatives, so the models nearest an unfamiliar unit name the offsets its report is
likely to use. Those are shortlisted, decoded, and the one the report agrees with is kept.

**The shortlist cannot decide alone, and two obvious ways to make it decide were tried and failed.**
Most Model IDs match two published models rather than one, and those pairs disagree about the offset
*every time* — one carries the leading media block and one does not. Neither the rule sections nor
the declared attributes break that tie:

- the rules are keyed by **product code**, while the ambiguity is on the **Model ID** side, so
  nothing keyed on the product varies with the choice;
- the attributes a device declares describe its **feature set**, not its layout. A boundary test
  built on that agreed with the one unit it was developed against and then got **both** independent
  checks wrong — two products that link exactly to a media-carrying model declare none of its
  leading attributes. A lean unit can sit on a rich map.

So the report is the only thing that settles it, and it costs nothing: it arrives on the first
successful read, with no capture and nobody asked for anything.

**Three refusals as shipped in v0.35.0, all deliberate — and the first has since been lifted.** It
reported and never commanded, on the grounds that a control writes a whole block of words at once
and no capture had confirmed these positions on that appliance; item 30 retired that reasoning, and
these layouts now command wherever the appliance's own published group-set list is known. The other
two stand: it places only the core readings, leaving the rest unplaced until an offset is confirmed
field by field, and it declines rather than guesses — a Model ID resembling nothing published
yields no candidates at all.

⚠️ **The failure this nearly shipped is worth keeping.** The candidate that is wrong by nineteen
words reads *past the end* of a shorter report, so every field comes back absent — and a decode
holding no readings passes a plausibility check on the readings it does not have. It returned an
empty result that would have hidden the partial decode a unit was entitled to. The core readings must
now be **present**, not merely not-implausible. Same shape as the validity band in item 21: a check
that can only see what is there cannot speak for what is missing.

⚠️ **This assumes the stronger claim that item 16 records as false of the wider published set** —
that the only difference between layouts is where the block starts. What protects a merged-first-word
model from being mis-read is the ordinary guard, not a proof; see item 16.

⚠️ **Not yet exercised against a genuinely unknown appliance.** Both units here are the classic
family, so the path stays dormant on them by design. It is proven on real captured data — resolving
the offset from the identifier alone reproduces the confirmed decoder on every shared field — not
against hardware nobody has mapped. The first reporter whose diagnostics show a resolved layout
instead of a partial decode is the real test.

## 24. A setting the unit ignores is not a fault — settled

**Status: fixed in v0.36.0, confirmed on hardware in both modes. Recorded because the wrong
behaviour was deliberate, defensible, and still wrong.**

A control the unit discards in its current mode used to be marked **unavailable**. The reasoning was
sound as far as it went: a switch that reports "on" and changes nothing is worse than one that says
it cannot be used. But `available` in Home Assistant means *the state cannot be read* — and these
states read perfectly. Using it for "cannot be set right now" produced three problems at once:

- the dashboard showed a warning, so a working system looked broken, every time the unit sat in
  fan-only;
- the reading and its history vanished for as long as the mode lasted;
- **no reason could be shown**, because Home Assistant has nowhere to attach one to an unavailable
  entity — so the explanation the model publishes could never reach the person looking at it.

The controls now stay, showing the truth, and the *command* is refused with the model's own words:
*"Eco does not accept that setting: not available in fan-only mode"*. Nothing silently does nothing,
which is the thing the original design was right to avoid.

**Where the refusal lives matters.** It is on the entity, not in `async_send_control`. Commands are
deliberately not gated centrally: a model marks almost everything unwritable while a unit is off,
including the mode, and turning a unit on *is* a write of the mode — which real hardware accepts. An
entity knows which field it is and refuses only for itself.

**The self-clean button is deliberately different** and still goes unavailable. A button has no
reading and no history to lose — it is an action, not a state — and a disabled button is already how
Home Assistant says "not now". The switches went unavailable while still perfectly readable, which
is what made them look like a fault.

⚠️ **This was only half the bug.** The reason text did not exist either. The sentences were being
merged from the catalogue, but the *code* selecting one lives on each rule, and gap-filling only
fills empty sections — a signed-in install has rules, so nothing was filled, and a device's own
account states no code on any rule. Every signed-in install shipped the phrasebook with no phrases.
Rules now adopt the code from their catalogue twin, matched on trigger. That cannot change what is
locked: a code labels a rule that has already fired.

**Verified on hardware, both directions.** In fan-only: 26 entities, none flagged, `locked_fields`
naming five, and setting Eco or Quiet refused with the reason. In cool: same 26 entities, no locks,
and Eco set to `level1` and back to `off` on the real unit. No entity changes state between modes,
so switching modes leaves no history gap and no automation sees an entity blink out.

## 25. An outdoor reading that is not a measurement — settled

**Status: shipped in v0.39.0, deployed and verified on hardware. Reported as a bug by the owner of
a 175-byte unit; the diagnosis is that it was never our bug, and the fix is about how we present
what the appliance says rather than about what we read.**

The outdoor temperature stops changing when the air conditioner is switched off. The probe is in the
**outdoor** unit, which is dormant then, so the indoor board carries on reporting the last value it
managed to take. The indoor probe is on the indoor board, which stays awake — which is exactly the
asymmetry that was reported: one reading kept moving, the other stood still.

Nothing was cached on our side. The decode is stateless, and neither of the two hold-overs that do
exist (telemetry, faults) can reach this field — the extended report names `outdoor_coil`,
`outdoor_in_air` and `outdoor_defrost`, and no `outdoor_temperature`. The behaviour is documented
independently for this protocol: the value *"remains unchanged, reflecting the last measured value"*.

**Why it still needed fixing.** The reading is published as a `MEASUREMENT`, so it lands in
long-term statistics. A unit switched off overnight therefore wrote a value that was true at dusk
into eight hours of history and dragged the day's minimum with it. Presenting a parked number as a
current measurement is the thing that was wrong, not the number itself.

**What ships:** after the unit has been off for 30 minutes *with the reading unchanged*, the sensor
reports `unknown`. Both conditions are required, and the second is the important one — staleness
while off is documented behaviour, not a law, so a unit that keeps refreshing its probe resets the
clock simply by sending a different value and never blanks.

⚠️ **This is deliberately NOT the same shape as a plausibility band**, which
[Rule 13](#21-a-reading-that-looked-intermittent-and-the-rule-that-came-out-of-it--settled) exists to
warn against. A band on a confirmed field cannot prevent a decode error, only hide one, and it hides
it as absence. Here the value is correctly decoded and *knowably* unrefreshed, which is why the bound
is on age and on observed stillness rather than on the value looking wrong. A reading that is
genuinely current is never suppressed — that direction is the one that matters, and it is the one
verified live.

**A switched-off air conditioner is ordinary**, so this raises no repair and logs at debug, once per
transition. The sensor reads `unknown` rather than `unavailable`: the entity works, the value is
simply not known.

**Verified on hardware (2026-08-06):** 26 entities, none unavailable, no exceptions, and the unit
running in fan-only with its outdoor reading present — i.e. a live measurement is not suppressed.
⚠️ The 30-minute drop itself is covered by tests rather than by the deploy, since observing it live
means leaving the appliance switched off for half an hour.

## 26. Home Assistant's own network view does not see these appliances reliably

`aiodiscover` is the library Home Assistant's `dhcp` component uses to learn what is on the subnet,
and it is also what this integration used to turn a device ID into an address. On at least one
network it does not see these units — while the very same MAC is sitting in the host's ARP table.

Two consequences, one cause:

* **The Discovered card cannot be relied on.** With an appliance removed and Home Assistant
  restarted, no discovery flow appeared for it inside two minutes, despite its OUI being in the
  manifest's matcher list. When discovery *does* fire the card behaves correctly and leads to a
  confirmation rather than a key prompt — that path is covered by tests but has not been seen
  happen by itself on hardware.
* **Address resolution occasionally falls through to asking.** Host lookup now ends in a
  UDISCOVERY broadcast, which is not ARP-dependent, and with it in place an address was found
  without asking in every run but one — the exception being a run seconds after a restart. Not
  diagnosed. It is recoverable (one field, and the answer is discoverable) rather than a dead end.

**What would settle it:** instrument which of the three steps answers, across restarts and on more
than one network. If the broadcast proves dependable and ARP does not, the order should change
rather than the fallback merely existing. Do not "fix" this by widening the manifest matcher — the
matcher is correct; what feeds it is not.

⇒ Because of this, **the dependable way to add a second appliance is
Add Integration → use the account already added**, not waiting for a card to appear. That route
asks for nothing and does not depend on ARP at all.

## 27. One family's byte map is typed rather than generated — settled

`_CLASSIC_PROBE` and `EXTENDED36` are built from `canonical_map`; extended-46 was not, and kept a
hand-written table. Eleven fields were typed into it, five the map already placed were left out, and
the switches for those five were offered and then sat unavailable for want of anything to read. The
same exemption emptied the family's declared-attribute list and withheld its optional-feature
entities — three symptoms reported as separate faults, one cause.

**The mistake was in how the family was described, not in what was known about it.** It was recorded
as having no displacement, on the grounds that no single offset fits. That is true and it is not the
same as unplaceable: an insert is a **piecewise** displacement. `WireModel` now carries
`canonical_insert=(pivot, words)` beside the offset, and `canonical_word()` applies both, so the map
places everything either side of the inserted block and the block itself stays explicit.

Outcome on the 209-byte family:

* its fields are **derived from the map** and reproduce every capture-verified position exactly,
  field for field, asserted by a test;
* its devices' declared attributes went from **0 to 54**, of which **53 agree with the
  manufacturer's own record and none disagree**;
* optional-feature entities work there for the first time.

Two things stay explicit, and both are the point rather than an exception:

* **The inserted block's own two fields** (per-tower vane and fan) are not in the published map,
  because no bundled model has dual airflow. They came from captures and still do.
* ⚠️ **The half-degree setpoint.** The map encodes a setpoint as degrees above 16; this family sends
  half-degrees from zero. Taking the scaling from the map — on a field whose *position* the map gets
  right — would read 24 °C as 40 °C. Position from the map, scaling from a reading. A test asserts
  the departure so nobody restores it, and fails if the map ever agrees.

Also settled in passing: `CANONICAL_WIRE_MAP` flagged that `write_base_word=20` for this family was
inherited and never verified on it. It is now, from the other end — the five toggles derived through
that base agree bit for bit with the manufacturer's record of the same attributes.

## 34. A decode that reads nothing came back as a successful decode — settled

An appliance names its own family on the discovery channel, key-free, so a uPlusId match beats the
report length when a wire model is selected. That is deliberate and it stays. What it also did was
let a frame of **any** length be claimed by that family — and a frame too short to reach the
family's fields read nothing, vetoed nothing, and came back as a decode carrying only its `layout`
and `writable` markers.

A truthy decode is a full status report everywhere downstream. So one short frame — an ack, a reply
to a query the unit does not implement — replaced the cached report, and the next command seeded its
group-set from 93 bytes and failed with

> `report too short (93) for extended46 baseline`

until a later poll happened to overwrite the cache. Reported from a live 209-byte unit, alongside
item 28's swing error; the two arrived together and were one report of two unrelated faults.

**This is Rule 13 in its plainest form** — a plausibility check on a value that was never read
passes — and the striking part is that it had already been found and fixed *once*, for the
related-layout path (item 23), where the wrong relative reads past the end of a shorter report and
comes back empty. The guard was put in that caller. Every registered family went on without it for
another release. **Where a lesson gets written down decides how far it reaches:** in the caller it
protected one path, in `WireModel.decode` it protects all of them.

`decode` now requires both anchors — the indoor reading and the setpoint — to have actually arrived,
for any family that declares them. A test asserts the anchor requirement is the stricter of the two
bounds, so anything that decodes at all carries a complete settable word block and can seed its own
group-set.

**Found in passing, and worth as much:** the in-session baseline gate was table-only. It recognised
the classic lengths and nothing else, having been written before the wire-model registry existed —
so on every other family the appliance's own post-handshake push was not recognised as a baseline
and control **always** fell back to the caller's cached blob. That is the stale seed the
single-session read-modify-write exists to avoid, and it is why one poisoned cache entry could keep
breaking commands rather than being corrected by the next one. `is_control_baseline` now asks the
registry, and `async_send_op` takes the uPlusId so it can.

## 28. Fan speed and the up-down vane on the 209-byte family — settled

**Both ship, as of v0.47.0.** The reading was restored and the controls with it, on evidence that
had been sitting in a diagnostics file for a day. Reported as a *regression* by the owner of the
first 209-byte appliance (issue #6): after v0.46.2 his climate entity dropped from `supported_features`
441 to 401 — no fan dropdown, no swing — while his remote worked the fan and the vane perfectly well.

★ **The write positions were never in doubt — across the byte-level descriptions.** The published
write frame is ONE frame across every air-conditioner device type that carries such a description
(`02011`, `02012`, `0201201G`, `02012036`, `03012`, `0301200L`, `0301200n`): 39 attributes, eppCmd
`6001`, frameType 1, the same words and bits, with no disagreement among those seven. It places
`windDirectionVertical` at w1.b0/4 and `windSpeed` at w2.b8/3, and this family's three
hardware-confirmed positions reproduce it exactly. ⚠️ What that must **not** be read as saying is
that every *family* keeps those positions — this very family's published group-set list assigns w1
and w2.b8–10 to the per-tower vane and fan (item 29, now settled from source and the controls
retargeted to the appliance's own positions at group-set words 6/7), and eleven families keep some
other setting at a shared position (item 32). Both are handled; this item is only about the
seven bundled profiles agreeing among themselves.

### What settled it

One diagnostics file carrying a report **and** a cloud record taken close enough together to be
checked against each other. Its volatile attributes agree — setpoint 22.0, indoor 28.0, power on,
and all six word-22 toggles bit for bit — so the record belongs beside that report:

| the report | that same file's cloud record |
|---|---|
| w20.b0 (the map's vane) = **0** | `windDirectionVertical` = **2** |
| w25 (inserted block) = **2** | `windDirectionVerticalL` / `R` = 0 / 0 |
| w21.b8 (the map's fan) = **6** | `windSpeed` = **1** |
| w26.b9 (inserted block) = **1** | `windSpeedL` / `R` = 3 / 5 |

The inserted block holds the **appliance's** vane and fan. And the per-tower explanation the fan was
withdrawn under is refuted by the very document that withdrew it: a tower register cannot read the
appliance's value when the towers are published in the same record as 3 / 5 and 0 / 0.

### Why it was wrong for two releases, which is the part worth keeping

v0.43.2 retired `w26.b9` — a position that fitted three captures taken in stated states — on a
fourth capture that read 0 there "while the appliance's own cloud record said 1", from "a document
that agreed with 53 other attributes and disagreed with none, **so it was not stale**". Both halves
of that fail, and both were checkable at the time:

* **The document was the same frozen record as the file before it** — diagnostics carry the cloud
  model as fetched at onboarding — and in that very file its setpoint said 22.0 while the report it
  was being compared against said 24.0. It was stale by at least one setpoint change.
* **The agreement count cannot detect staleness.** It runs over `model_declared_fields`, which by
  construction holds only the attributes no field map reads: the voice module, air-quality probes
  these units do not have, `tempUnit`, `volume`. Not one of them can change. It agrees whatever the
  document's age, so "53 agreed" was measuring nothing.

v0.46.1 then withdrew the **controls**, reasoning from that withdrawn reading plus the read-map
conflict — a fact about the *report* spent on the *group-set*, which is the conflation this item
already warned against in its previous form. One invalid retraction cascaded into a larger one.

★ **The general lesson is Rule 14** (`METHOD.md` §10): a fact that is overturned takes its
dependents with it, and nothing walks back to collect them. "A diagnostics `digital_model` is frozen
at onboarding" was written down the day *after* v0.43.2 shipped and never applied to it.

### What is still open, and it is small

`write_base_word + write_word - 1` — the report word a written bit reads back at — **holds on this
family for words 1..3 as words** (setpoint, mode and the whole boolean block, the last confirmed 6/6
against that fresh record) and **fails for exactly two bit-fields inside the first two of them**.
The relation is a heuristic, not a law; the two exceptions are listed in `_WRITE_READ_EXCEPTIONS`
with their evidence.

Which way the failure runs is not established: the appliance may ignore those bits in the group-set,
or accept them and report the result only in the inserted block. **Only a write observes that**, and
it is now the owner's to observe — the readback is restored, so setting the fan from Home Assistant
and watching it follow is the whole test.

`windDirectionHorizontal` stays out. Its write position is published like the others; nothing in
this family's report reads it back, and a control that writes what it cannot read is the defect
v0.31.0 already fixed once.

---

## 35. Which air conditioners this integration can place before it has seen one — measured

A model is placed **offline** when the published data alone says where its readings sit. Across
every air conditioner published in every region:

| | products | share |
|---|---|---|
| placed offline | **1,236** | 85 % |
| not placed offline | 215 | 15 % |

★ **The 215 are almost exactly one product class.** Grouping by the class digits every appliance
announces, one class accounts for **207 of the 215, and not one of its members is placed** — and it
is the same class the manufacturer's own phone app publishes no control panel for. Those are units
this product line does not cover, rather than a hole in the map.

★ **That leaves eight**, in four families: four wall/floor units and four window air conditioners.
All eight **publish their group-set order**, so the settings and the order they are written in are
known; what is missing is where their *reports* sit. They fall just below the similarity threshold
that decides whether one published model may stand in for another — ⚠️ and **the threshold should
not be lowered to reach them**: they differ inside the appliance-type field itself, which is the
boundary that check exists to respect.

**A single report settles all eight**, because the report's own length identifies the layout. So
this is not blocked on analysis; it is waiting for one of these units to appear.

### ⚠️ "Placed offline" is not "will not work"

Layout selection has a second chance the table above cannot count: when an appliance's identifier is
unrecognised, its **report length** is tried, and each known length belongs to exactly one layout.
An appliance nobody has ever seen therefore still decodes if it reports a familiar length. **1,236
is what the published data settles in advance** — the set that works on first contact is larger, and
how much larger is genuinely unknown until such a unit connects.

If you own one of the unplaced models, a diagnostics download is the entire contribution needed.
