# Open items

Each is written to be picked up cold: what it is, why it is not done, and what would settle it.
Anything genuinely settled is collapsed to a line or two at the bottom, under **Settled** — kept so
that nobody re-opens it, and pointing at where the detail now lives (a doc, the code, or the git
history).

The numbers are **identifiers, not positions** — items refer to each other by number, so an item
keeps its own when it moves between the two sections. Expect the sequence to have gaps in both.

> **One finding frames several of the items below.** Where an item says a setting "cannot be placed"
> or "needs hardware that declares it", weigh it against this: **almost every product publishes the
> ordered attribute list of its group-set command, and that order is the wire order** — word
> ascending, then bit descending within a word. So a setting's position can often be *derived* by
> anchoring on the settings the shared map already places and fitting the unknowns between them. That
> does not place everything — a list is in wire order only up to a boundary, after which later
> additions are appended out of order — but it places some things once recorded as unplaceable, and
> brackets many more. Count coverage **per family** (compact / central-air / wall-floor describe
> themselves in different formats), never against the shared map alone, or the count understates the
> other families badly.

## Open items

### 1. Vane positions on a unit whose model understates it

Both axes offer their positions as `select` entities beside the swing controls, built from the stops
a unit's own model publishes.

The up-down axis needs a translation, because a model numbers its stops differently from the wire.
That table is **read from the published map**, which carries the vendor's own code table for this
attribute, rather than written out by hand — so it covers every stop the vendor defines, including
the health-airflow positions and the second auto that a wall unit does not have but a cabinet does.
The stops one unit was stepped through on hardware, capture by capture, are kept beside it and the
suite checks the map still agrees with them: taking a table from a generated source is only safe
while that source agrees with an observation.

⚠️ **Why it is read rather than written:** every consumer of this table filters against its keys, so
a stop the table omits is not written wrongly — it disappears, from the authorized set and from the
select's options alike. A hand-written copy that covered one unit's stops silently cost **86
products** the three positions their models declare and it does not.

What is left is only the case where **a model publishes less than the hardware has.** The reference
units are exactly that: their handsets step the up-down vane through six stops, but their model lists
only `0` (fixed) and `8` (auto), so nothing authorises the six, and they get no up-down select. No
map can settle this — it is not a question of where the field is or what its values mean (both
known), but of what a *particular* unit accepts, which only that unit answers: a recorded command
carrying a position on hardware whose model does not list it.

### 2. Health writes one bit where the vendor app writes three

Toggling Health moves three bits together — its own flag plus the two purification-status bits — and
they have never been observed apart. Our encoder maps `healthMode` to its own bit alone. A unit
commanded from its handset sets the other two itself, so a single-bit write most likely suffices.
That is an assumption. One write from our side, with the report watched, settles it.

### 3. Self-clean reporting on the 209-byte family

Shipped on the classic, 165/175-byte and (this round) 117-byte families; still open on the 209-byte
family alone, because that family's ten-word insert point is not pinned and the flag has two
candidate homes.

What its captures confirm: w20/w21/w22 (setpoint, mode, power) unmoved; w35/w36 (indoor, outdoor)
+10; w25 a vane and w26.b9 the fan, both inside the inserted block. So the block starts after w22 and
at or before w25 — and w23, w24 or w25 place canonical w24 at report w24 or w34, disagreeing. Indoor
temperature cannot separate them (all three predict canonical w25 → report w35) and every capture
reads w23/w24/w33/w34 as zero, because nothing was switched on.

**What settles it is cheaper than catching a self-clean cycle.** Any capture from that family with
*any* w24-block feature on — Health, ambient light, fresh air — pins the insert point, because
exactly one of w24 / w34 will be non-zero, placing the whole flag block at once.

### 5. A timer, on units that publish one

Some units declare `timingPowerOn` / `timingPowerOff` (minute counts, 0–1440) and a `timingStatus`
of cancel / set / keep; **161 products declare all three.** So the attributes are common and a
reporter carrying them is likely rather than hypothetical — a timer entity would be the first in this
ecosystem.

What is missing is their **position**, and the published order does not supply it: on every model
that declares them they sit in the appended tail of the group-set list, past the point where the
list stops being wire order. A single report from a unit with a timer set, against one with it clear,
places all three at once. (The 175-byte family was checked — issue #8 — and declares no timer at all;
its app timer is server-side scheduling, and two captures differ only in the live power/energy words.
So that family cannot get a timer entity, and this waits on hardware that declares the attributes.)

★ **Checked properly 2026-08-25, and the negative is real — with two things worth knowing.** No
`timing*` attribute of any spelling appears in **any** of the eight bundled air-conditioner
descriptions (searched whole-file, not just the sections a map is generated from), so the position
cannot be inherited from a relative either.
⚠️ **The two corpora spell it differently**, which is exactly how a search like this returns a false
negative: the product catalogue says `timingPowerOn` / `timingPowerOff` (minute counts), while the
descriptions that *do* carry a timer — none of them air conditioners — say
**`timingPowerOnHH` / `timingPowerOnMM`**, hours and minutes as **separate one-byte fields**.
★ So the prediction for the first air conditioner that reports one is **two bytes, not a minute
count**. Anyone testing this should look for the pair before concluding the attribute is absent.

### 6. The energy total on the families that are not yet trusted for it

The cumulative register counts **watt-hours**, settled on the 165/175-byte family against an owner's
own app (one 15-minute interval added 347 against ~1390 Wh measured; a whole day added 7516 against
the app's 7.52 kWh). That family ships an Energy sensor; the classic family's register is published
too on the same reasoning (it *is* the map 19 words earlier, checked field for field), and reads
zero — reported as absent — on every classic unit met so far.

Two cases stay unconfirmed:

* **Exactly one classic unit is known to keep a total, and its magnitude is unchecked** — it reads
  ≈ 3,139 kWh, and no reading off that owner's app has ever been compared against it. This shipped on
  *weaker* evidence than the 165/175-byte sensor. **Asked for on issue #1; if the answer disagrees,
  withdraw the sensor rather than defend it** — a wrong total is not recoverable once it is in
  someone's history.
* **The 209-byte family has a working register that is deliberately not published**, because that
  family has been caught departing from the shared map three times over and its counter's position is
  derived from the same inserted block. A unit is not the sort of thing to inherit on the strength of
  a map the family already disagrees with.

One reading off the owner's app, beside a diagnostics download, settles each — the same way the
165/175-byte sensor was settled.

### 7. The fault decode has not met a real fault

The bitmap decode follows the vendor's own parser and the labels match the published fault list, but
no unit here has reported a fault. `errCode` gives a free cross-check when one occurs: it names a
single fault where the frame carries the set, so the bit that is set must be `errCode - 1`. Nothing
to do but keep the diagnostic in place and check the first report that arrives.

★ **The table itself is not in question.** Every published
air-conditioner model declares **the same 51 faults at the same 51 positions**, with **zero**
disagreements about a name, so the one shared table this integration applies to every family is
justified by measurement rather than assumption.

★★ **The bit ordering has a second source too.** It was the one part of this item
resting on our own reading: which byte carries positions 0..7, and which way the bits run inside it.
An independent implementation of the same protocol decodes those frames too, and it was compared
against ours frame by frame — 8 bitmap bytes read **last byte first**, least-significant bit first
within each byte. Over every single-bit fault frame the two agree on **64 of 64 positions**, and its
fault list is **51 entries matching ours position for position**. So both halves of the decode now
have a second source.

What is left is only that no unit here has ever reported a fault, so the decode has never run on a
real one. That is a confirmation waiting to happen rather than an open question, and the first
faulted report still settles it for good.

### 8. The declared attributes that are still unreachable

A unit declares three or four times the attributes any family map carries, and every one sits where
the published map already says — so the extra readings are decoded into diagnostics
(`model_declared_fields`), membership from the device's own model, position from the map. The
user-facing ones are entities: the optional-feature sensors (item 4's gate),
the panel controls (item 36), and the air-quality suite (item 37). So have the maintenance and status
readings the vendor's own panel renders **no** control for, which is its way of saying they are a
status rather than a switch — the filter-change reminder (197 products declare it), the control-panel
lock, the two four-step air-quality ratings, what the presence sensor currently sees, the two
purification functions and the purifier's hour meter. Each takes the same three gates as the rest:
the unit declares it, its model does not mark it as hardware it lacks, and its family's relationship
to the published map is confirmed.

What is **still** unreachable is the residue with no derivable position — attributes in the appended
tail of the group-set list, which is unordered, so nothing places them. Where a run of unknowns fits
*exactly* between two placed attributes it can be laid out (five were placed that way, unanimous
across every model that declares them, and it re-derived positions already known from hardware — the
check that it works); where the fit is not exact the run is left unplaced rather than guessed, since a
wrong position decodes silently rather than failing. The remaining genuine controls (the append-region
bools and the dual-airflow read-back) are item 36's residue; everything else here reaches diagnostics
and waits on a capture of a unit with the feature switched on.

### 9. Eco, on the 209-byte family

The Eco ladder is `generatorMode`, a current limit that descends with the level (higher = more
restrictive). Two families ship it: the classic family (three level bits, established from its own
captures, at w4.b3–5) and the 165/175-byte family (two level bits at w23.b3–4, settled from issue #8
— off/L1/L2/L3 measured at 1969/1951/1798/1205 W). Both are written and read in the classic
representation so nothing above the family map knows which it is.

Open on the 209-byte family, because **the shared map carries no `generatorMode` at all** and cannot
place it. The published order *brackets* it — declared by 566 products, it falls between two placed
attributes, narrowing it to w4.b1–5, which contains the classic family's measured w4.b3–5 without
having been told it — but a bracket with spare bits is not a placement. Four captures (Eco off, then
each level, one download per state) settle it. (⚠️ Off and L1 were only 18 W apart on the 165/175
capture; worth one more reading before anyone describes what L1 *does*, though it does not affect
where the field is.)

### 13. The four-sided cassette vanes — shipped provisional, awaiting one wire confirmation

The four independent louvres of a four-way cassette (52 products declare them) ship as four selects,
offered on any cabinet that declares them and written one setting at a time: `5D0F`/`0E`/`11`/`10`,
each std stop `0..6` mapped to the config's non-linear epp code. Both halves come from the
manufacturer's own device configuration (the master byte map): the write ids sit
in the same per-attribute `eppCmd` column as the nine confirmed climate ids, and the read positions
are the config's **word 6** — four nibbles filling that word, inside the report's inserted block.

⚠️ **Provisional, for one specific reason.** The write ids are as solid as the nine, but their read
position has never been seen *populated* on the wire: the one `0d12` cabinet captured is a
single-flow cassette that leaves word 6 at zero. So each is written by id and settled by its own
read-back — a cabinet that actually moves its louvre confirms the position on first use, and one that
does not retires the control. **One report from a four-way cabinet with the louvres in four different
positions confirms all four at once**, and that is the only thing still worth asking for.

★ **Where the louvres sit.** Haier's config puts them at word 6, independent of
`windDirectionHorizontal` at word 4; the two coexist in the byte map rather than sharing bits. The
presence read-guard (item 42) rests on a separate fact: four-way cabinets do not declare presence.

**Residue, recorded not parked** (all watched by the register oracle in the maintainer's tooling, which
checks every id, read position, **value encoding** and big-data word against both config families and
that every config id is accounted for):

* **The unobserved second (商空) family diverges, and nobody has captured one.** The `…2151860b57…`
  family (23 products) numbers a few controls differently in its config — its `windSpeed` is
  non-identity (`std 6→epp 7`, `std 9→epp 6`; the shipped class-wide identity map would set the
  wrong fan speed on it), and it numbers the health-airflow louvre stop `std 10` where the observed
  candy family uses `std 7`. Its report also carries ~18 more status words than candy's, so the
  `(length−125)/2` insert heuristic would miscount on it. None of this touches the observed candy
  family that ships to real units; it is fenced off because the 商空 family is a **capture target**,
  not a shipping target. The oracle WARNs on the encoding divergence rather than failing.
* **`ampereControl`** (`5D32`, second family, ~4 products) — a compressor-current limit like the ECO
  ladder, now that the config gives it a number. Held for a focused follow-up; its value semantics
  are not yet worked out. Tracked in the oracle's `DECLARED_NOT_YET_SHIPPED`.
* **The `0d21` cassette is a SEPARATE class, not this one.** ~20 products spell the louvres
  `fourSidesWindDirection*` in their own declarations — those are class `0d21` (uPlusId `…0d21…`), a
  distinct device class with no single-parameter support here at all. Adding it is its own item (a
  `0d21` capture, its own decode), not a spelling alias on `0d12`. ⚠️ An earlier note here wrongly
  filed those 20 as a `0d12` 商空 spelling gap; they are a different class.
* **Not louvre-related but surfaced in the same sweep:** the ext-46 family reads/writes its inserted
  `windSpeed` at `w26.b9` with an identity enum, where its config puts it at `w26.b8` with a
  non-identity enum — wrong for the upper fan codes, and `b9`'s span reaches `oxygenSupplyMode`'s bit.
  Already flagged hardware-unverified in the code; a real ext-46 capture is the fix (its own item).

### 19. The still-unpositioned settings — counted per lineage, and classified by *why*

⚠️ **Count per lineage, never against one map.** Positions do not transfer between lineages, and the
compact family names its fields by Chinese label rather than by the catalogue's English name — so an
English-name membership test is structurally blind to it and reports its whole attribute set as
missing. That mistake has been made repeatedly; it is what the per-lineage table below exists to
prevent.

| lineage | products | attribute slots placed |
|---|---|---|
| compact-12 | 482 | **95.9 %** — 27 of the 28 attributes its products declare |
| shared frame (wall/floor) | 754 | 80.0 % |
| central `0d12` | 187 | 87.4 % |
| central `0d21` | 20 | 81.1 % |
| window / media | 8 | ~91 % |
| **total** | **1,451** | **83.9 %** |

⚠️ **"Placed" here means "carried by the layout this integration ships", not "position unknown".**
The two are not the same, and the gap between them is measured: of the residue, **6 attributes across
837 product-slots have a position that has been worked out and is deliberately not shipped** — three
are capability flags no product makes visible, one is contested against an attribute already placed
at those bits, one belongs to families that are read-only, and one is unanimous over four products.
Each is stored with the reason, and the test suite re-derives that reason from the shipped data, so
the day one becomes shippable the suite says so. Counting only what nothing anywhere can place, the
residue is **98 attributes over 7,118 slots**.

⚠️ **It is also a slot count across all products, and it must not be read as "any given unit is 84 %
mapped".** Most of the 1,451 are ordinary wall units declaring around twenty attributes, and they
pull the figure up. A feature-rich appliance is much further from complete: the twin-tower cabinet
this project holds diagnostics for declares **79 real attributes and 40 are positioned** — its own
description lists what the *product* supports, while the layouts published for it predate several of
those functions. That shortfall is a gap in what the manufacturer published, not one in what this
integration reads.

**The raw slot count is not the missing-control gap.** Classified, what remains is:

| why it is missing | slots | note |
|---|---|---|
| **past the last anchor** — no ordering information exists | 4,112 | only a capture places these |
| **bracketed, but the run does not close** | ~1,350 | see below — not solvable from published data |
| **derived, withheld with a stated reason** | 833 | five positions, run closed with no free parameter; each withheld on a measurement — see item 36 |
| **not in any write order** | 574 | read-only or cloud-side by construction |
| **compact-12 `echoStatus`** | 456 | its profile carries no record at all |

Much of the "not in any write order" bucket is **not a wire field in the first place**: the
manufacturer's own AC service holds per-appliance cloud records for self-learning, filter runtime,
sleep curves, countdown timers and power history. A feature computed and stored in the cloud cannot
appear in a byte map, and its absence from one is not a gap.

⚠️ **`echoStatus` is corroborated absent, not merely unfound**: the compact profile has no record for
it, the hardware silently discards a write to it on the classic family, and the vendor's own control
panel renders no widget for it anywhere. Three independent sources agree.

What settles any single one of the rest is unchanged: a report from a unit that actually has the
feature, taken with the feature in a known state — the layout prober scores against written-down
states. Nothing is waiting on this and nothing can go wrong because of it: none is surfaced, so none
can be mis-read, and a unit missing one is otherwise fully supported.

### 31. The compact family's three unproven registers

That family's 117-byte report is **decoded in full** — thirty-eight positioned fields, every one
exactly where the published description says, and **27 of the 28 attributes its products declare are
placed** (the 28th is `echoStatus`, for which the description carries no record at all).

★ **The three registers below are precisely the ones the catalogue names nothing for.** Every other
position in that description pairs with a declared attribute; these three do not, so their meaning
cannot be read off the models and has to come from a reading. They are held in the decode (visible in
diagnostics) rather than promoted to entities, checked against the three real reports from the issue
#4 unit:

* **input power** (word 3, low + high byte) — live (0 off, 15 cooling, 0 fan-only), but 15 is not
  watts while cooling, so the unit cannot be taken at face value. One reporter reading their meter or
  app beside a capture settles the scale.
* **the word-2 low byte** — an **outdoor-unit** temperature (reads ~60 cooling, stale ~59 off), *not*
  ambient outdoor air, so it is `w2_low_raw` in diagnostics rather than an "outdoor temperature"
  sensor a user would misread.
* **the word-9/10 toggles and flags** — positions published, but every capture reads them 0, so there
  is no positive confirmation of a bit until a capture exercises one.

⚠️ **Prior art does not answer these.** The independent
description of this same protocol carries **no power field at all** for this family, so it cannot
settle the scale; and its label for the word-2 byte is the *source* of the humidity-vs-temperature
disagreement recorded above, not evidence about it. Both still need one reading from a unit.

The humidity registers (word 11) read 0 — no probe — so they decode as absent and appear only on a
unit that has the sensor. No new user-facing entity ships for the 509 products this round; the
promotion bar (a reading proven and a meaning a user won't misread) is intact.

### 36. The panel control surface — the blocked residue

The panel control surface **shipped** across every group-set family, and across the compact family
via its per-attribute commands. What remains open is the residue that no source can place or read:

* **five append-region booleans** — `constDehumidificationStatus`, `preventSupercooling`,
  `pvPowerSavingMode`, `uvSterilizationSwitch`, `windAvoidance`.

  ✅ **`constDehumidificationStatus` is derived with no free parameter**, along with the four
  neighbours that share its run, at the same positions on all **159** products that publish it. The
  run is bounded by a confirmed position at each end and exactly one tiling fits it.

  The width is measured rather than inferred. The catalogue publishes only each
  setting's *standard* codes, while the wire carries the manufacturer's *internal* codes, and the
  bundled descriptions publish both — so the relationship between them can be counted rather than
  assumed. Counted: a code set beginning at zero keeps its codes in **1,082 of 1,082** cases, and of
  every setting whose codes are the pair `{1,2}`, **235 of 249 occupy one bit**. The neighbour in
  question publishes exactly that pair, so its width is settled by a population rather than by
  analogy to a single other field.

  ⛔ **All five are nevertheless withheld — and the reason is a measurement rather than caution.**
  Each was checked against the shipped model bundle, one at a time:

  | derived position | why it is not surfaced |
  |---|---|
  | balanced-wind and humidity-control capability flags, display mode | **159 products declare them and every one marks them as hardware the unit lacks.** There is no unit to show them on. Both flags are `有无` — "does this model have the function" — which is a statement about the product, not a state the appliance reports |
  | the left tower's horizontal vane | **contested**: 161 of the 165 products declaring it also declare the ordinary horizontal vane, which the shared map places at exactly those bits. A placement under this name would be reading the other setting's bits on almost every unit that has it |
  | constant dehumidification | the only **30** products that show it are the two families of item 38 — the ones whose published order refutes the shared frame, which is why they are read-only. A position derived from an order that contradicts the frame cannot be trusted against that frame |

  Those reasons are kept as data next to the positions themselves and re-measured by the suite, not
  written down and forgotten: if a catalogue re-sweep ever makes one of them visible, or moves a
  product off a read-only family, the test says so instead of the position staying withheld for a
  reason that quietly stopped being true.

  The other three stay unplaced, with a stated reason each: two sit **past the last setting the frame
  pins**, so nothing bounds them from above and no ordering information ever will; one sits in a run
  with spare bits the order cannot locate. Those need a capture, not more analysis.

  ⚠️ **Their positions are REUSED between product families** — one family keeps mould-proof, drying
  and heatstroke-prevention where another keeps humidity-control, display-mode and balanced-wind.
  Exactly one product declares both sets, and there the published order separates them and every one
  is marked as hardware the unit lacks, so nothing is mis-offered today. Anything shipped here must be
  family-gated the way the existing bit-reuse guard is.
* **dual-airflow** (`windDirectionVerticalL/R`, `windSpeedL/R`) — the twin-tower write positions are
  known (ext46, w1/w2), but **no report we hold reads a tower back**, so they would be write-only
  controls. Blocked on one capture with a tower vane parked non-zero (the same capture item 3 wants).

⚠️ **The per-attribute write channel does NOT rescue any of this, and that is measured rather
than assumed.** Item 42 writes central cabinets one setting at a time without needing a
position, so the obvious question is whether the same channel reaches these. It does not: across all
174 bundled device descriptions — 5,054 per-attribute command declarations, 596 distinct attribute
names — **no air-conditioner class publishes a per-attribute command for any climate attribute**. The
plain AC descriptions publish exactly one, `onOffStatus`; the two richest add twenty, all of them
voice-box functions. Every `targetTemperature`/`operationMode` per-attribute command in the corpus
belongs to a **different appliance category** (water heaters, sterilizer cabinets, steam ovens), at
different numbers. The attrID list the models publish alongside it does not cover these attributes
either. ⇒ For the wall/floor families a position is still required, and a capture is still the way
to get one.
* **`freshWindSpeed`** — read out of the published models, every product that declares it marks it
  **`writeType: G`** — group-written — and publishes **four** values, in two variants. Of the **16** products whose raw published model we hold: **3** publish
  `0 无 · 1 低 · 2 高 · 3 额定`, which **fits the frame's 2-bit slot exactly**; **13** publish
  `0 无 · 1 低 · 2 高 · 4 中`, and **code 4 does not fit two bits**. So the blocker is narrower than
  recorded — it is not the attribute that cannot be carried, it is *that one value on that one
  variant*. ⓘ **195 products declare the attribute**; the enum above is read from the 16 whose raw
  model we hold, so the remaining 179 are unmeasured, not known to agree. Settling it needs the value
  sets for those, or a report placing the field's real width.

### 38. Two families publish a group-set order the shared frame cannot explain (30 products)

A catalogue-wide audit — every product's published group-set order checked against the shared
frame's positions — found two families (12 + 18 products, the **AQUA `AQA-AX*` and `JAA-MX*` wall
units**) whose order has essentially **zero rank-correlation with the frame** (τ ≈ 0.06, against
1.0 for every confirmed family). That is not the frame with a few settings moved; it is some other
layout, or a list published in some other discipline. Nothing anchors it, so nothing can be derived
from it.

These products are **read-only**: every frame-position write for them would be a guess with
substantial counter-evidence, and a guessed group-set runs wrong functions silently rather than
failing (their report decode is unaffected — report
layouts are verified against the report itself, and the read frame is not the write frame). What
settles it: a diagnostics file or capture from any of these units, which would show whether their
reports resolve to a known family and give the first anchor for whatever their write layout is.
⚠️ **Checked 2026-08-25:** no report from an `AQA-*` or `JAA-*` unit exists in the public issue
trackers of the projects implementing this protocol either — the route that settled item 42 has
nothing to offer here yet.

### 39. The appended-tail settings on the other twin-tower families

The same audit showed extended-46's structure is not unique to it: **every twin-tower family** (six
families, 161 products) lists the appliance's own `windDirectionVertical`, `windDirectionHorizontal`
and `windSpeed` in the appended tail of its order, past the words the shared frame reaches. For
extended-46 the packing arithmetic plus capture-confirmed read-back settled the vane and fan at
group-set words 6/7 (item 29).

✅ **Mostly resolved — 109 of those products now have swing and fan speed.** Two of the families
publish an order that is **byte-identical to extended-46's through both anchor positions**, and every
attribute preceding them in the tail publishes an identical value set, so the packing that puts the
anchors on those bits is *the same packing*. The positions are therefore extended-46's own, copied
rather than re-derived, and they are carried in a family-keyed table
(`family_write.TAIL_POSITIONS`). Measured over the whole catalogue: **109 products gain exactly two
controls, none loses one and no position moves.**

⚠️ Two things this did **not** fix, and both are honest residue:

* **`windDirectionHorizontal` is still absent on all of them.** It is in the tail too, but
  extended-46 has no confirmed position for it either, so there was nothing to copy. Worse, it is
  now known to be *underivable*: between the two confirmed anchors the order leaves a **4-bit run**
  for `windDirectionHorizontal` (irreducibly 3 bits) and `oxgyenSupplyMode` (2 bits, because its
  published code set starts at 0 and such sets keep their codes in 1,082 of 1,082 measured cases).
  Five bits into four. The residue is a reserved bit or an attribute the frame does not carry, and
  **published data cannot tell those apart.** One capture settles it; nothing else will.
* **8 products still lose all three controls.** One family inserts `waterWindSpeed` before the
  anchors so its positions shift by that field's width, and two `0d21` families diverge earlier
  still. Each needs its own solve or one report.

⚠️ Rule 8 residue: no unit of the two newly-reached families has been commanded. The evidence is
published order agreement plus a *sibling's* capture, which is stronger than what shipped for
related layouts — but it is not this family's own hardware.
⚠️ **Checked 2026-08-25:** those same public trackers carry no report from a twin-tower cabinet
either. Worth re-checking whenever one of those projects gains a dual-airflow user — that is exactly
how item 42 was settled.

### 41. The fan speeds — named from the vendor's own wording; Boost alone is withheld

Issue #11 exposed the shape of a defect worth stating once: the wire map's mode and fan **code sets
are the identity** — on every family that is the published map at a displacement, the wire value *is*
the standard code — so their only job is to say which codes exist, and a code missing from one does
not decode wrong, it **vanishes**. Downstream that reads as "the appliance did not report a fan
speed", not as "we do not know this code", which is why nobody noticed.

Both enums are complete against the published catalogue, and — this is the part that took the
longest to get right — **named by the manufacturer, not by us.** Its app ships an offline language
bundle whose `seasia_home.AC_*` keys are exactly this vocabulary in 18 locales, so the English for
each Chinese description is the vendor's own word. See **[`VENDOR_LABELS.md`](VENDOR_LABELS.md)**.

| code | description | vendor English | our token |
|---|---|---|---|
| 4 | 微风 | Breeze | `breeze` |
| 6 | 静音风 · 快速风 | Silent · Quick | `silent` · `quick` |
| 7 | 中高风 · 快速风 | Mid-high · Quick | `mid_high` · `quick` |
| 8 | 中低风 | Mid-low | `mid_low` |
| 3 (mode) | 健康除湿 | Healthy Dry | `health_dry` |

★ **Naming them fixed three silent collisions**, which is the half that mattered: `中高风` and `高风`
both resolved to `high` on **51 products**; `中低风` and `中风` both to `medium` on **31**; and
`健康除湿` and `除湿` both to `dry` on **20**. Two codes on one token means the reverse lookup a write
resolves through returns whichever the model happened to list first.

⚠️ **Codes 6 and 7 each carry two different meanings across products**, so the code never determines
the speed — the description does, which is how `_enum_from_datalist` already worked. Nothing here is
a code table.

**What is deliberately still out, and why each:**

* ⛔ **超强风 / "Boost" (code 0, 23 products).** Its wire value is 0, and 0 is what the fan field
  reads on a real 209-byte report from a unit that is switched **off** — so it cannot be told apart
  from "no speed reported". No report from any Boost-declaring product exists to separate them.
  Withheld in **both** layers (no wire code, no keyword), because offering a speed in one layer and
  not the other is the actual hazard. **What settles it:** one report from a unit declaring 超强风,
  taken while it is running at that speed.
* **中低风 (8) and 静音风 (9) do not fit** the frame's 3-bit `windSpeed` field. They are named, so a
  unit reporting one shows it wherever the field is wide enough; the frame simply cannot carry them.
  Every product declaring either is already refused `windSpeed` control on other grounds, so nothing
  reachable is lost.
* **`medium` stays `medium`** although the vendor says "Mid" — it is in users' automations.
* **`健康除湿` is display-only**, like the window units' ECO: it shows as Dry and is not separately
  selectable, because Home Assistant has no mode for it. Reported correctly, which it was not before.

### 42. The `0d12` central cabinets — controlled, vanes included

**187 products** publish **no group command at all**. Every attribute is marked individually
settable, and their firmware **refuses the group-set frame outright** — so the group set is not
merely undeclared for these cabinets, it is unavailable. Each setting is its own command, with the
value in the payload.

**What ships:** power, setpoint, mode, fan speed, health, quiet, boost, both vane axes and the
display unit (°C/°F) — offered where the cabinet's own model declares the attribute, and each read
back from its own position in the report so it shows real state rather than an echo of the request —
plus presence-based airflow and the four-way cassette louvres, on the provisional terms described at
the end of this item and in item 13. All fifteen single-parameter ids are Haier's own, taken from
its device configuration and checked by the register oracle in the maintainer's tooling.

★ **A vane is read even where it cannot be commanded.** A vane is a position, not a switch,
and the climate entity's swing control answers only "is it sweeping" — so a vane parked at a real
stop reads exactly like one held closed. These cabinets publish as many as ten up-down stops and
eight left-right ones and report both axes in every status frame, so where an axis is readable and
not writable its position is surfaced as a reading of its own, named for the stop the unit's own
model publishes. Where the axis *is* writable the existing control already shows the stop, and the
reading is not duplicated.

⚠️ **All of that is gated on the report resolving to a layout**, which for these cabinets is not
automatic: one of them reports a block of words between its settings and its sensors that no
published description mentions, so every ordinary offset is rejected on the room temperature alone
and the appliance decodes almost nothing. That case is handled (see the 133-byte section of
[`report-layouts.md`](report-layouts.md)): the size of the report settles how big the block is, so a
cabinet resolves whether or not it can heat. ★ That last part matters — the heat-capability flag alone
answers only for a **cooling-only** unit, and two of the three such cabinets on record are heat
pumps, so the report's size is what settles the block. A cabinet reporting some *other* length with the
same shape would still need its own measurement before the same arithmetic could be trusted for it.

* **The command bytes** are the ones these appliances are observed to exchange, and the values need
  no translation: mode `0/1/2/4/6`, fan `1/2/3/5`, setpoint `°C − 16`, booleans `0`/`1` — the same
  encodings every other family here uses.
* **Several settings become several commands.** There is no word block to pack, so a change that
  touches three settings sends three ops, each separately accepted or refused by the appliance —
  which also means a refusal names the setting that was actually refused. Power leads when switching
  on and trails when switching off, so a unit is configured while it runs and stopped only after the
  rest has been applied. ⚠️ That order is a choice, not a measurement; it is fixed so it is at least
  predictable.
* **Reads are corroborated** against reports from an appliance of this exact identifier: setpoint,
  mode, fan and power all land where the published map puts them. Wrong sensor values on one of
  these means an old version — update.

★ **The two vane commands were offered on terms the appliance itself settles — and it settled them.**
This generation defines a command for each axis, and for a long time neither had been watched being
*accepted*: the reference table's other eleven were read off a real appliance's traffic while these
two were added without any capture behind them, and the one cabinet whose traffic was captured has no
vane. So they were resolved a different way, and the mechanism is worth keeping because presence
(below) uses it now.

**The up-down command is bracketed**: in the published wire order that attribute is the only one
these cabinets declare between two commands that *were* observed, and only one command number is
free in that gap — so the number is forced, and it is the number the reference table guessed. And
**both axes read back**. This channel names one attribute at a time, and the report says where each
vane is pointing, so the appliance can answer the question the moment somebody uses the control: ask
for a stop, then look at where the vane says it is.

⇒ **A provisional control is written, checked once against the appliance's own reading, and then
trusted.** If the value took, nothing more is checked. If it did not, that control is withdrawn for
good and the failure is reported, rather than leaving somebody pressing a button that quietly does
nothing. An owner then moved **both** axes on real hardware — the adjudication passed on the up-down
command it bracketed and on the left-right command that rested on the reference table alone — so
both are plain confirmed controls now, and the provisional machinery stays in place for the next
derived command.

**143 of the 187 cabinets declare an up-down vane and 91 a left-right one.**

⚠️ **One thing about these command numbers is worth stating plainly: they were watched on one
appliance kind and are sent to two.** This class covers **187 appliances in two families** — 162 of
one, which is the family every captured number came from, and **25 of another** that publishes two
and a half times as many functions. All 187 are individually written and the two families agree on
the 87 functions that matter here, so sending the same numbers to both is a reasonable expectation —
but nobody has watched the second family answer. A command is still only ever sent for a function the
appliance itself declares, and a control that does not take is withdrawn permanently, so the exposure
is one command; the point is that it is an expectation rather than an observation.

★ **That also names the most valuable single capture anyone could contribute here:** traffic from one
of those 25 appliances would place far more commands than the recording this integration was built
from, and would settle the question above at the same time.

⚠️ **`invisible` is not used as the gate** — see item 43. Membership is the attribute being declared
at all, because the parameter table is per device class while the function is per product: a cabinet
with no health module must not be offered health merely because its class defines a command for it.

#### Presence-based airflow on these cabinets — offered provisionally, on the vane terms above

One of these cabinets reports its presence mode as *on* where three identical siblings report *off*,
so the hardware is real and the reading ships. The **control** is offered too, as a select (off /
avoid / follow / on), and how it is offered matters because its command has not yet been watched
being accepted.

**Where the number comes from.** The command number is the manufacturer's own: its device
configuration for both central-cabinet families gives `humanSensingStatus` the write command
`5D23`, the same per-attribute column the nine confirmed climate ids come from. It is provisional
only because the write has not yet been exercised on a cabinet, not because the number is a guess.

**Why it is safe to offer anyway.** It is offered exactly as the vane commands were: the appliance
reports the setting's own position in every status frame, so the first use writes the command and
reads the setting back. If it took, the control is trusted from then on. If the appliance refused it
or the setting did not move, the control is **withdrawn for good** and the failure is reported — the
cost of a wrong number is one command that changes nothing. A cabinet without the sensor withdraws it
the first time anyone tries, which is the right outcome for that cabinet.

**Who gets it.** Membership is the class: every `0d12` cabinet carries the setting undeclared — the
same under-declaration that hides its outdoor probe — so the control is offered on every one except
a cabinet whose own description gives those bits to the four-way louvres (a presence control there
would be writing a vane). Whether a given cabinet has the sensor is settled by the write itself.

⚠️ **Two things are called "presence" and they are not interchangeable.** The airflow *mode* — what a
user changes — is an ordinary attribute of the main board, and that is what is commanded here. The
sensor's own enable and installation parameters are a separate conversation between the module and a
sub-board that never reaches the network, and are not something a user sets. Conflating the two once
produced the wrong conclusion that presence could not be controlled at all.

**What would settle it outright:** one use on a cabinet that has the sensor. The adjudication above
runs automatically, so nothing is asked of anyone beyond trying the control.

### 45. A multi-attribute write command exists on paper — and this generation refuses it

Item 42 sends one op per setting, because the class it serves has no group-set command. The protocol
documents a **third** shape between the two: a *set-parameters* command carrying a list of
`parameter id + value` pairs in one frame — the same per-attribute addressing item 42 uses, but
several at a time, with no packed word block and so none of the group set's whole-block hazard.
A cabinet that took it would apply "turn on, cool, fan low" in one op instead of three.

**Tested here on 2026-08-25, and refused.** Both halves were sent to a wall unit as no-ops — the
*get* form carries attribute ids and no values at all, and the *set* form carried an attribute's own
current value — and the appliance **refused both**. In between, the per-attribute command it does
publish was sent identically and **accepted**. Nothing moved on any of the three.

**Why the bracketing matters.** A refusal on its own says only that the unit declined *something*.
A refusal either side of an acceptance, from the same state, over the same connection, minutes
apart, says it declined **that command** — the difference between an appliance that is fussy today
and a command this firmware does not implement.

**The unit says the same thing out loud.** These appliances chirp when they accept a command. Re-run
as a listening test with someone standing beside it, three commands inside twenty seconds: both
refused forms were **silent** and the one it implements **beeped**. That is a second signal, owing
nothing to how we decode a reply, and it agrees.

**And the refusal of the *get* form is the one that settles it.** That form carries no value, so it
cannot be explained away by the value's width, its encoding, or which of the two number spaces a
value travels in — the three loose ends a set-only test would have left. It was refused anyway.

⚠️ **What it does not settle.** One appliance, of the wall generation — **not** the central cabinets
that item 42 actually serves, which are the ones sending several ops. They have answered nothing.
The evidence against is strong (nothing in any of the 174 published device descriptions declares
either half, the reference implementation documents the pair without using it, and hardware of a
neighbouring generation refuses both), so this is not worth a reporter's time on its own — but if a
central cabinet is ever on the other end of a probe, the same two commands cost ten seconds.

**Not a blocker for item 42.** Several ops is correct behaviour, just not the tidiest.

### 47. The lock explanations — restored and translated, with one residue

When a rule makes a control unavailable, the integration shows the reason the device's own published
model gives for it. Two faults meant most owners never saw one.

**A published model spells that record two ways**, one per serialisation — `code`/`description` on
1,423 products and **`name`/`desc`** on the 28 that arrive in the other shape. Only the first was
read, so **21 products shipped with no explanations at all** (189 sentences), and 96 more were
missing some of theirs. Twenty of the twenty-one are the compact central cabinets — `HCFI-*`,
`HCSI-*`. **477 sentences restored.**

**And 52% of the sentences that did ship were in the source language.** The English wording only ever
covered one of the two reason-code spaces, so the 700 products whose codes live in the other one
showed their owners text they could not read — worse than showing nothing, because it looks like a
fault in the integration rather than a message from the appliance. **7,261 sentences translated;
31 published wordings collapse to 20.**

Both are guarded now: a test refuses any shipped reason left in the source language, and a second
pins the fact that **a reason code is not a global key** — code `1` means "not allowed in the current
state" on 509 products and "this function is not supported" on 300, so nothing may carry a sentence
between products on the code alone.

⚠️ **What is left.** The wording is **ours**, not the manufacturer's: its own language bundle has no
text for any of these (see `VENDOR_LABELS.md`), so unlike mode and fan-speed names — which arrive in
18 locales — these twenty are English wherever they appear. They surface as free-text entity
attributes rather than through Home Assistant's string catalogue, so localising them is hand work.
**7 products still show none**, correctly: their published models declare no reasons.

### 48. The rules that locked what they only limited — fixed, and the operator with it

**Every published rule was re-read against the vendor's own bytes, and two faults came out of it.**
Both had been shipping since the rules engine existed, and both were invisible to the tests because
every fixture was written from the same understanding as the code.

**A rule that limits a setting's VALUES was making it unavailable.** A rule's action names which of
the attribute's fields it rewrites — `W` its writability, `V` its permitted values, `WV` both — and a
`V` action carries no writability at all. Read as a lock, it withdrew the control: **611 products**,
almost all of them on the up-down vane or the fan speed, triggered by an ordinary running mode. The
worst of them made **the swing control unavailable while the unit was simply cooling**, with the
explanation "not available in the unit's current state" — a sentence the model never said. The other
serialisation of the same model states the answer outright: there a `WV` action is *writable* **and**
carries the narrowed set. **1,451 attribute-state locks removed, 0 added.**

**And a rule's conditions were being combined with the wrong operator.** A trigger holds two groups —
what the write asks for, and what the unit currently reports — each with its own relation, and the
relation on the trigger combines the *groups*. It was being read as the operator over the conditions.
Calibrated against the account-scoped copy of one product's ten rules, which states the operator
plainly: it matches the inner relation on all ten and the outer on one.

**Then the engine ignored the operator anyway.** Two functions in one file evaluate a rule's trigger;
one honoured `OR` and the other, thirty lines above it, ANDed everything. An `OR` rule ANDed fires
only when both its settings travel in one command, which is to say never: **495 rules across 488
products** were parsed, valid and permanently inert — this project's own appliance among them, whose
model says switching on quiet or sleep also clears boost, and which did not.

The shipped rule bundle was built from the adapted output, so it was re-derived from the published
models for all 1,451 products; re-running that repair is a no-op. A test over the whole bundle
refuses any rule that locks a setting it only narrows, and asserts there are more than 500 such rules
to get wrong — a guard over an empty set proves nothing.

⚠️ **What is still not read, and is not a defect.** A trigger's *reported-state* term is dropped, as
the vendor's own account serialisation drops it: two rules that differ only by it arrive
indistinguishable there too, and the integration already handles the one case that matters (it
substitutes a fan speed when fan-only is selected on auto) more precisely than the rule would. And
**four products** publish two rules that set the same attribute to different values under the same
condition (`windAvoidance` and the vane positions); the model orders them by a priority nothing here
reads, so one of the two wins by list order. One report from such a unit would settle which.

### 50. The central cabinets may be several indoor units behind one address

The protocol treats a group of appliances on a shared bus behind one communication module as a
single addressable system: every frame carries a source and destination address, the module is
always address zero, and sub-units are numbered from one. There is a command to ask a system for
**how many sub-units it has and what their addresses are**, and another the appliance sends when
that set changes.

This integration sends the destination address as zero in every frame, which is correct for a
single-board appliance and is what the residential units are. For a central cabinet it may mean we
are only ever talking to the first indoor unit of a system that has several — which would explain
why a multi-unit installation appears as one device.

Nothing here can test it: it needs a central installation with more than one indoor unit on one
module. The enumeration command changes nothing if the appliance does not implement it — it is a
question, and an appliance that does not understand it simply refuses.

### 53. Presence is a MODULE-side sensor with its own pipeline — and it reports distance

The vendor's generated protocol document for `0D012`
carries a second presence pipeline beside the board's 2-bit `sensingResult`: the **Wi-Fi module's
own status frames** (§6.41 reply, §6.44 push — every 10 s in 人感模式, at once on change) include a
**`0xA0` 人感 block** — bit0 `0 无人 / 1 有人`, bit1 start/stop, bit2 antenna status, plus **the
sensed person's distance band, lower and upper bound in centimetres**. The board enables and
configures it with system-interaction frames (`0x100A` enable · `0x100B` disable · `0x100C`
parameters, sent after every handshake · `0x1011` query · `0x100F` "module asks the board to disable
its own presence logic"). `humanSensingModuleErr` on 187/187 `0d12` products is that module's fault.

Consequences:

* The board's `sensingResult` reads `0` on every `0d12` report on file — **including the issue #12
  cabinet whose presence MODE reads 3 (on) in the same reports, taken with nobody under the
  cassette.** `0` is therefore *unknown*, not "no sensor"; the state map leaves it out and the raw
  value is in diagnostics (`feature_raw`). ⛔ Do not gate anything on `sensingResult == 0`.
* Every LAN frame kind is kept with its bytes (`lan_frames`) and every uSS message of the last
  session is traced (`uss_messages`), so whether the module's `0xA0` block ever reaches `:56800`
  is answerable from a diagnostics file.
* **The experiment:** on a cabinet with presence mode on, capture with someone under it, then with
  the room empty. If the board field follows (`1`/`2`/`3` vs `0`) the vocabulary is settled; if a
  frame with the `0xA0` block appears in `lan_frames`, the module's own report — with the
  distance — is on the LAN and a presence/distance sensor can ship.
* **Outcome on the issue #12 cabinet (2026-09-01):** the reporter states the unit **has no PIR
  sensor**, and that the app's "Detecting" screen is fault detection (as read from the panel).
  Their diagnostics with the frame-keeping build: `feature_raw` `humanSensingStatus 3` (on) with
  `sensingResult 0`; `lan_frames` holds four kinds only — the 4-byte session blob, `06/6d01` 133 B,
  `04/0f5a` 103 B, `06/7d01` 147 B (item 52) — no `0xA0` block. So this cabinet cannot register the
  experiment, and it shows that the board's presence MODE field reads "on" on a unit without the
  sensor. The control was offered by the CLASS gate (`CLASS_CARRIED_ENUM_FEATURES["0d12"]`,
  `_class_carried_controls`) — the product's constraintfile lists 9 attributes and no presence,
  while the panel-embedded model fetched for this very product (the per-product panel's embedded model for `AE2C52Q00`, 39 attributes keyed by name) DOES declare `humanSensingStatus` (感人模式, writable, marked not readable). **The manufacturer's own per-model witness** (a Haier Thailand brochure the
  reporter supplied): "HUMAN SENSOR
  … *only on HCFI-36ETR32, HCFI-40ESR32, HCFI-40ETR32, HCFI-48ESR32 and HCFI-48ETR32*" — five
  models, all on the C/E-series family (`…00041410…`, shared-frame presence), none of them `0d12`;
  `HCFI-38XTR32F` is not on it. The brochure also refutes the constraintfile the other way: every
  C/E HCFI product declares `humanSensingStatus` (13CSR, 18CSR, 25ESR, 30CSR, …) while the brochure
  names five. So neither published model is a per-unit or even per-model witness for the sensor,
  and a per-product gate built from the panel would offer presence on exactly this reporter's
  cabinet. The provisional `5D23` write — the id Haier's own device configuration gives
  `humanSensingStatus` (`5D08` is `halfDegreeSettingStatus`) — offered, not yet tried on this unit —
  remains the only
  adjudicator on `0d12` (a `0001` "not supported" refusal withdraws the control); on the C/E family
  the five brochure names are the only allow-list held, scoped to one market's brochure. The
  experiment still needs a cabinet whose owner confirms the sensor is fitted — one of those five
  models is the place to ask.

### 54. Left-right vane on `0d12` — control confirmed on hardware, and the code→position map

The issue #12 reporter drove `windDirectionHorizontal` from the integration on their `AE2C52Q00`
cabinet and watched the louvre: **the `5D0C` single-parameter control works** (the vane moved), and
of the eight codes the model authorises (`0..7`), **codes 1 and 2 do nothing** while **3 = far left,
4 = near-centre left, 5 = near-centre right, 6 = far right** — four discrete stops sweeping the room
left→right. `0` and `7` were not reported (by analogy with the vertical vane, `0` fixed / `7` auto).
So the control and its adjudication (`5D0C`, per the diagnostics `single_param_ids`) are confirmed
live on a real `0d12` cabinet, and the enum's *usable* range is the middle four codes, not all eight.
This is a per-hardware observation, not a model change; it is the ground truth to check the shipped
`windDirectionHorizontal` labels against, and the first confirmation that a `0d12` L-R vane command
moves the actual louvre (the four-sided cassette sweep, `FUTURE_WORK` unchanged, is still unobserved).

### 55. What the unit is doing (`hvac_action`) is undecidable in auto on a heat pump while the compressor runs

The climate entity reports what the unit is *doing* -- cooling / idle / drying / heating / fan / off
-- from the extended report's compressor flag; Home Assistant badges the tile-card icon with it and
prints it under the temperature in the thermostat card. Two gaps, both left as honest unknowns
rather than guesses:

- **Auto on a unit that can heat, compressor running.** Nothing decoded says which way the
  compressor is pumping. The extended report carries a reversing-valve field
  (`four_way_valve_status`), but every capture to hand reads it as "not reported" (2), and its
  polarity -- whether 1 means heating -- has never been observed. So the action reads unknown
  there; idle, and the explicit modes, are still decided. On a cooling-only unit auto reads
  cooling, because nothing else is possible.
- **Units that answer no extended query.** Off and fan-only are decided from the status report;
  cool / heat / dry read unknown rather than echoing the mode, because "cooling" on an idle unit
  is precisely the wrong answer the badge exists to avoid.

**What closes the first:** one extended report from a heat-pump unit that is heating (mode heat,
compressor running) whose reversing-valve field reads 0 or 1 -- that fixes the polarity, and auto
can then be decided from it. Defrost (`defrost_status`, same actuator word) can be published as
`defrosting` the same way once one report shows it at 1.

## Reference — not open items

Kept because each looks like something to "fix" until you know why it is the way it is.

⛔ **Not on the central cabinets, and that is settled rather than untested.** The communication
standard states that a multi-appliance system *must* use the interactive conversation mode, and
those cabinets use the simpler one where the module asks and the appliance only answers — which
their own refusals confirm. So an appliance of that class is not one of these systems, however many
indoor units a building has. This needs hardware that actually talks the interactive mode.

### The layout prober is told what the captures were

The prober is the *second* thing to run: an unfamiliar report is first matched against
the offsets its nearest published relatives use (item 23), and the prober handles only what survives
that. Its output is a shortlist to verify, not a result. `probe_layout` scores against
`stated=[StatedState(...)]` — what each capture was known to be — as heavily as the device's published
values, so on two real reports where 77 of 83 candidates tie on plausibility alone, the stated states
separate them, and a reporter's "cool"/"fan-only" work without anyone knowing the model's codes. The
report form has one box per capture, `scripts/probe-diagnostics.py` takes them with `--state`, and
diagnostics dumps `digital_model.reported_values`. What is *not* solvable from here: the search inside
diagnostics runs unaided, because Home Assistant cannot know what state a unit was put in — the states
have to enter from the issue.

### The one rule we decline to honour

`locked_attributes` decides which commands a unit discards (fan-only shows no setpoint; boost and
quiet refuse in the modes that discard them; a faulted unit accepts only power and mode). It drives
*command refusal*, **not** entity availability — that was the bug item 24 fixed. Rules are fetched
per device and merged onto the shadow (which carries no rules); a device with no published rules gets
none, which locks nothing.

Two carve-outs are deliberate. A model marks nearly everything unwritable **while the unit is off** —
including `operationMode`, which is exactly what turns a unit on and which real hardware accepts — so
that rule describes an app greying its own buttons, not what the unit discards, and is skipped (the
self-clean half, which really does hold the unit, is honoured). And the preset control is evaluated
as though no comfort setting were on, because a preset write clears its siblings and a rule letting
sleep lock boost would strand the control meant to undo it. Writes are never gated on any of this;
only availability was, and that is now a refusal instead.

### 43. `invisible` marks hardware a unit lacks — but it is NOT a control gate

**Investigated and closed 2026-08-25. The fix was written, it broke a test, and the test was right.**

**The observation that started it, which stands:** `switch.py` creates the five core toggles
(strong/quiet/health/sleep/lamp) gated only by `supports_field`, which never consults `invisible` —
while the panel controls ten lines below it *do*. `button.py`, `sensor.py` and `climate.py` share the
ungated pattern. On paper that is the phantom-feature bug on the control side.

**The counter-example that closes it.** Gating `supports_field` on an explicit `invisible` mark
immediately withdrew **left-right swing** from the owner's own unit. Its product `AAC1UKZ01` marks
**`windDirectionHorizontal` invisible** (one of 25 invisible attributes of 39) — yet that control was
**shipped and live-verified on that exact hardware**, tracking the handset through
auto → position_4 → fixed.

⇒ **The vendor's `invisible` flag says the unit has no horizontal vane. The unit has one.**

★★ **So the flag is not "this hardware is absent" in the sense a control gate needs.** The asymmetry
decides it:

| | trusting `invisible` | not trusting it |
|---|---|---|
| **sensor** | may hide a real reading | a phantom sensor reading a constant zero |
| **control** | **removes a working control** — demonstrated | offers a control that may do nothing |

For a sensor the flag is worth trusting; for a control it is not, because the failure is worse and we
have a concrete case of it firing wrongly. **Leave the controls ungated.**

★ **What genuinely came out of this, and is worth keeping:**
* **`invisible` and group-set order membership are independent** — measured across the published
  models: **2,156** attribute slots are invisible *and still in their product's order*, **0** are
  invisible and absent from it. Order describes packing, `invisible` describes hardware. Never
  substitute one for the other (this is why the F6 order gate filters no absent hardware, by design).
* **`invisible` is unreliable per-attribute**, at least for `windDirectionHorizontal` on `AAC1UKZ01`.
  ⚠️ That should temper how far the optional-feature gate is trusted, though the risk there
  (a hidden sensor) is mild and no case of it is known.
* The tree was left unchanged and the suite stayed green.

# Settled

**49. A refusal names its own reason, and it is reported in the manufacturer's own words.** Done.
An appliance that declines a command answers with a code saying which rule was broken, and each
product publishes its own table of those codes — this integration ships all of them, translated, and
now reads the code off the refusal and renders that product's sentence. ⚠️ Never a global lookup: the
same number means different things on different appliances, so a code a product does not publish is
reported as "the command was not recognised" rather than borrowed from another product. The reader is
held to a refusal recorded from a real central cabinet, which carries the flag that says a checksum
is followed by a CRC — a shape no hand-written fixture had. ★ The distinction it draws is worth more
than the sentence: an appliance answers one code when it does not recognise a command at all, and
another when it recognises the command and does not have the hardware, so a probe can tell whether a
command number exists without writing anything. ⚠️ The central cabinets of item 42 publish an
**empty** reason table of their own, so every refusal they send carries the protocol's generic "not
recognised" code; a product-specific reason will only ever be seen from a family that publishes one.

**51. Presence-based airflow, on the family whose own description publishes it.** Done for the
compact lineage. Those cabinets place the setting in their published group command at a named word
and bit, with the manufacturer's own codes for the two states it has there — and the position is the
one the read map already carries, so the setting reads back where it was written. ⚠️ The attribute
has four states on the shared frame and **two** here, because this lineage gives it a single bit; a
control is therefore built from the values its own family can carry, and the other two are refused by
the encoder rather than silently truncated. Sixteen products gained a control that previously had
neither a switch nor a reading. The central cabinets, written one setting at a time, are offered it
too — provisionally, on the self-checking terms in item 42, because their number for it is derived
from the vendor's own module traffic rather than published. ⇒ **Every product that declares presence
visibly now has a control for it**: 47 on the shared frame, 16 on this lineage, and the central
cabinets on the terms above.

Not open items — collapsed to the conclusion plus a pointer. The full reasoning for each is in the
git history and, where noted, in the canonical docs and the code.

**4. `echoStatus` vs `selfCleaningStatus` — the write contract.** Settled both ways. `echoStatus`
stays read-only: a live self-verifying write is *accepted* but the bit never lands, and the app's own
control panel renders no widget for it either. `selfCleaningStatus` is honoured (a live write started
a cycle; the panel showed **CL**) and ships as a Start-self-clean button plus a
Last-self-clean timestamp. The rule this leaves: the model gives the *candidate* list of controls, a
live self-verifying write gives the *verdict*, and a panel widget predicts that verdict for free — the
four-step gate (`declares ∧ ¬invisible ∧ panel widget ∧ live write`) `panel.py` now implements.

**10. Indoor humidity.** Ships with the air-quality suite (item 37): offered where the unit declares
the probe and does not mark it invisible, zero read as absent, over-100 dropped as a sentinel. A
cross-check against a reporter's hygrometer is still welcome — withdraw rather than defend if it
disagrees.

**11. The central-air category — settled across all three of its classes.** It is **235 published
products in three architectures**, not one family: **28** compact (`8080`, a registered family that
has read and controlled since its map shipped), **20** (`0d21`) publishing the ordinary shared frame
and reachable on first report, and **187** (`0d12`) publishing no group command at all
— read, and controlled a setting at a time (item 42). Their read layout is the shared map at −19,
and it is corroborated against real reports on four anchors rather than inferred from report length.
⚠️ **Never say these units are "cloud-only".** That is a fact about the vendor's app, whose control
API picks a channel per device and falls back to the cloud for one it holds no local byte map for.
These are ordinary local appliances: they answer a status query on the LAN to anything holding their
key, and work with no internet at all. Being listed in the product catalogue means the app can
*operate* a unit, not that the unit needs the cloud.

**12. Control for the central family, a parameter at a time — shipped (item 42).** They publish no
group-set command *and* their firmware refuses that frame outright, so each setting is its own
command. The safety property is argued from that mechanism rather than copied from the group set: a
command either names an attribute the class publishes or it does not, and the appliance accepts or
refuses each one, so a command it does not implement is declined rather than misapplied. That is why
a command can be held back until it is observed and added later without disturbing anything else —
as the two vane commands were, and as presence is now.

**14. Deploy and verify the shipped rules — done.** The rules for all published products
travel with the integration and are consulted when the catalogue is unreachable (the ordinary path on
a firewalled install). Cross-checked on hardware: 19/19 comparable readings agree, the shipped and
fetched copies agree on identity, locking is unchanged and conditional. Found and fixed in passing:
diagnostics now prints the `invisible` flags (`feature_set_known`, `invisible_attributes` — empty and
absent mean different things).

**15. The compact family — see item 31.** The family's own published description carries
thirty-eight positioned fields, ten more than the derived extract it was once measured against, and
places `cloudControlStatus` / `sleepCurveStatus` at word 9. The lasting lesson: **count coverage per
family**, never against the shared map, which is generated from only one of the two published
formats.

**16. A layout that is not a displacement.** Recorded, not urgent — no model of this shape is sold in
the region served. One model elsewhere merges what the shared map spends two words on and packs the
setpoint into four bits, so a decoder assuming "every layout is the shared map at an offset" would
mis-read its setpoint/mode/fan into plausible-but-wrong numbers. The resolver's plausibility guard
(item 23) protects against it but is not a proof; a merged-first-word report is the shape to suspect.

**17. What still needs the cloud — one thing.** Checked row by row against shipped code: address,
device id, wire-model key, byte map, rules, feature set and product code all resolve offline. The
**local key** is the only cloud datum, fetched via an account sign-in and rotating several times a day
unless the unit is firewalled — which is why "fetch once, then firewall" is the working configuration.

**18. Comparison to the vendor app.** Parity with what the app can do **locally**, on every model it
supports. The app additionally displays cloud-shadow attributes it cannot decode and drives
server-side timers — deliberately declined here, because a value that did not come from the appliance
can be stale or wrong exactly when the network is. Two things this does that the app cannot: control a
firewalled unit (these modules are mDNS-silent, so the app never finds them locally), and report the
refrigeration circuit as named readings. Coverage is measured in item 35.

**20. Which model this is — why setup asks.** The appliance announces its **family** but not its
model, and nothing else recovers it: 19 of the 23 products in the reference family are byte-identical
to every observation yet carry four different rule sets. The vendor asks at pairing too, and sign-in
reads that stored answer back — which is why only a hand-made, account-less entry asks. Skipping
applies the family-agreed rules: **all** fault names and unavailability reasons survive, conditional
availability thins safely (a rule nobody disagrees on cannot make the wrong control unavailable).

**21. A reading that looked intermittent — Rule 13.** The compressor discharge line reads 80 °C
cooling hard and was discarded by a validity range chosen for room air (top 70 °C), which looked like
a failing probe for weeks. A range check on a *confirmed* field cannot prevent a decode error — it can
only hide one, as absence, which then reads as absent hardware. Temperatures are now bounded by
physics, not expectation. (`METHOD.md` Rule 13.)

**22. A command's reply must report what a poll does.** The reply after a command is a status report
with no fault frame and (once) no telemetry, so publishing it blanked those readings until the next
poll — worst on a problem sensor, where "unknown" reads as the check having stopped. Fixed three
times, once per reading; the test now guards the rule, not the three: whatever a poll publishes beyond
plain status, the reply must too, by re-reading or by holding for a bounded time.

**23. Layouts resolved from the nearest published relatives — shipped.** An unfamiliar
report is decoded at the offsets its close relatives use, keeping the one the report agrees with; the
report is the only tie-breaker (rules key on product code, declared attributes describe feature set
not layout, and both were tried and failed). Three refusals were deliberate; the read-only one was
lifted by item 30. ⚠️ Assumes item 16's stronger claim; not yet exercised against a genuinely unknown
appliance (both reference units are classic).

**24. A setting the unit ignores is not a fault — fixed.** A control discarded in the current mode
must not go *unavailable*: that means "state cannot be read" for states that read perfectly, hides
the reason, and loses the history. It stays visible and readable, and the *command* is refused with
the model's own words. The refusal lives on the entity, not in `async_send_control`
(a model marks the mode unwritable while off, and turning on *is* a mode write). The self-clean button
is the deliberate exception — an action, not a state.

**25. An outdoor reading that is not a measurement — shipped.** The outdoor probe is dormant
when the unit is off, so the board repeats its last value; published as a MEASUREMENT it dragged
long-term statistics. Now `unknown` after 30 minutes off **and** unchanged — both required. Not a
plausibility band (item 21): the value is correctly decoded and *knowably* unrefreshed, so the bound
is on age and observed stillness, never on the value looking wrong. A genuinely current reading is
never suppressed.

**26. Home Assistant's own network view is unreliable.** `aiodiscover` does not always see these units
(while the MAC sits in the host's ARP table), so the Discovered card cannot be relied on and address
resolution occasionally falls through to a UDISCOVERY broadcast. The dependable way to add a second
appliance is **Add Integration → use the account already added**, not waiting for a card. Do not widen
the manifest matcher — the matcher is correct; what feeds it is not.

**27. One family's byte map was typed, not generated — settled.** extended-46 kept a hand table (11
fields typed, 5 the map already placed omitted → dead switches and an empty declared-attribute list).
It is now derived from the map via `canonical_insert=(pivot, words)` — an insert is a *piecewise*
displacement, not the absence of one — taking its declared attributes from 0 to 54 (53 agreeing with
the manufacturer's record, none disagreeing). Two things stay explicit on purpose: the inserted
block's own tower vane/fan (from captures), and the half-degree setpoint (position from the map,
scaling from a reading — a test asserts the departure).

**28. Fan speed and the up-down vane on the 209-byte family — settled.** Both ship; w25/w26
are the **appliance's own** vane and fan (a diagnostics file's cloud record listed the towers
separately as 3/5 and 0/0, refuting the per-tower explanation they were withdrawn under). ★ Rule 14:
a fact that is overturned takes its dependents with it — a `digital_model` frozen at onboarding and a
staleness-blind agreement count cost two releases here. Open residue: `write_base_word + write_word −
1` fails for two bit-fields (listed in `_WRITE_READ_EXCEPTIONS`); only a live write settles which way,
and the readback is restored so the owner can. `windDirectionHorizontal` stays out — published like
the others but with no report position that reads it back.

**29. The 209-family group-set writes its own vane/fan, not the tower — settled from source, fixed.**
The shared frame's vane/fan slots (w1/w2.b8) are the twin **towers** on this cabinet; the appliance's
own vane and fan are group-set words 6/7 = report w25/w26 (the write↔read relation, the read map, and
the published packed order all converge). `word_count` is now 7 so the frame reaches them, and the
family obeys the write↔read relation instead of needing an exception. The only hardware residue is
confirmation that the appliance honours a 7-word frame.

**30. Control for read-only related layouts — shipped.** Control went from 590 products to **1,236 at
the time** (the current figure is **1,421** — see the table below, and do not quote 1,236).
Safe without a capture because the group-set is one frame across every published air conditioner, its
report base word is `20 + the layout's own offset` (a definition, not a fitted constant), and *which*
settings a unit has comes from its own published group-set list; families reusing a shared position
have those controls refused (item 32). A layout that publishes no list stays read-only — the safe
default. ⚠️ **Two families are read-only on positive evidence**, not for want of data: their
published order refutes the frame outright (item 38).

★ **Figures — 1,451 = 1,421 read + write · 30 read-only · 0 without a layout.** Every published
product can resolve a layout; none is refused for want of published data. The read-only 30 are the
families whose order refutes the frame (item 38). Supersedes *1,206 / 30 / 215*, *1,234 / 217 / 0*,
and "1,236 products" everywhere either appears.

| how the layout is reached | products | control |
|---|---|---|
| registered family (compact-12 · extended-46 · extended-36) | 590 | yes |
| the shared frame, corroborated by the product's own order | 644 | yes |
| no group command at all — written one parameter at a time (item 42) | 187 | yes |
| resolved, but the order refutes the frame | 30 | no |

⚠️ **"Control needs a frame, and these have no usable one" is a tempting and wrong reading.** It is
right about the frame and wrong about control: these cabinets do not use a frame at all, and the
mechanism they do use needs no order and no packing. A gate written for one
mechanism had been quietly deciding for a class that uses another.

⚠️ "Can resolve a layout" is not "will decode": the report still has to agree with exactly one
offset. What changed is that nothing is turned away before its report is even looked at.

**32. A control must not be sent to a bit a family reuses — fixed.** Eleven families keep a different
setting at a shared group-set position (self-clean↔sterilization; the twin towers at the vane/fan
slots; humidity-control↔manual-defrost; a keep-warm renamed, *not* reused). Packed by position, the
wrong function would run — the self-clean button would have started a *sterilization* cycle on 248
products. Those controls are now refused per family; everything else is untouched. Established from
the published order, every departure unanimous within its family.

**33. A whole AC category was invisible — fixed.** The product list asked the catalogue for three
categories; the app's own picker asks for none. Asked without a filter it answers 1,999 products
across 38 categories — including **window air conditioners**, which publish the ordinary command set
(30 of 33 group-set settings landing exactly where the shared frame puts them). Sixteen products
added → **1,451**. Second time a parameter *we chose* was mistaken for a property of the data (the
first was the account's region).

**34. A decode that reads nothing came back as a decode — fixed.** A uPlusId match beats report
length (deliberate — an appliance names its family key-free), which let a frame too short to reach a
family's fields read nothing, veto nothing, and return a truthy decode that poisoned the control
baseline (`report too short (93) for extended46 baseline`). `WireModel.decode` now requires both
anchors (indoor + setpoint) to have arrived. Rule 13 again — the guard existed in one caller (item
23) and now lives in `decode`, reaching every family. Found in passing: the in-session baseline gate
was classic-only, so every other family fell back to a cached blob; `is_control_baseline` asks the
registry instead.

**35. Which units are placed offline — measured.** **1,421 of 1,451** are placed from published
data alone (item 30's table). The working below is kept because it is how the remainder was resolved,
one class at a time.

The 215 that were once unplaced are **two** central-air classes plus eight others: `0d12` (187, no
group command — item 11), `0d21` (**20, which publish the ordinary shared frame**), four wall and
four window. **Twenty-eight of the 215 therefore publish a frame**, are corroborated against it, and
are reachable on first report; only the 187 are genuinely without published positions. Nor is the
*category* out of scope: 28 further central-air products are a registered family that reads and
controls. The similarity threshold must **not** be lowered to reach any of them (they differ inside
the appliance-type field) — the displacement is measured from the report instead.

★ **The 187 are read as well.** Requiring a group-set order before decoding them was evidence about
the *write* frame standing in for evidence about the *read* frame (Rule 22). They resolve from their
own report like any other appliance, and they are controlled a setting at a time (item 42). So the
current statement is: **1,451 = 1,421 read + write · 30 read-only · 0 refused** — and neither half
needed an owner to appear.

⚠️ "Placed offline" is not "will work": an unrecognised identifier falls back to report length, so
the set that works on first contact is larger; and a resolved layout still needs its report to agree
with exactly one offset.

**37. The air-quality suite — shipped.** PM2.5, CO₂, formaldehyde, a VOC index and indoor humidity are
sensors where the unit declares the probe and does not mark it invisible; zero is absent and a value
above the published maximum is a sentinel. It forced a correction: the 127-byte layout reads canonical
words 25+ **one word later** (an undescribed `targetRentTime` at report word 6), and the
declared-attribute placement now follows the layout table per report length (a test pins it to the
table's own confirmed offsets). The outdoor coil/air-intake/defrost probes stay diagnostics-only —
zero-for-life on the reference hardware, so as entities they would read `unknown` forever (a live
deploy caught and withdrew six such dead entities).

**40. A frame write must be corroborated by the product's own published order — shipped.**
The order is positional, so it can contradict the frame for a setting under its *own name* — a
departure the bit-reuse table (item 32) is structurally blind to, because that table only records
positions where a *different* attribute was placed. The audit that found it ran every one of the
1,238 published orders against the frame: every twin-tower family lists the appliance's vane, fan
**and horizontal vane** in its appended tail, and the horizontal vane — unlike the other two — was
still being offered at the frame position, where those cabinets keep tower/auxiliary bits. The
frame-path controls are now gated by `consistent_with_frame`: an order corroborates a position, or
drops the moved names (the appended-tail shape), or refutes the frame outright and offers nothing
(item 38). The audit itself ships as a test over the full bundle, so a future catalogue regeneration
that introduces a new departure fails the suite instead of quietly being offered frame positions its
own contract contradicts.

**44. A refused command was reported as SUCCESS — fixed.** Every op connection opens with
the unit's routine status push (frameType `0x06`) and alarm push (`0x04`) *before* the answer to our
own frame arrives, so a refusal always travels alongside a perfectly decodable status blob. Taking
that blob as "the unit answered with its updated state" reported the refusal as success and displayed
the **pre-command** state as the result — the setting appeared to have been accepted and the entity
did not even look stale. Detection was already right; only the precedence was wrong. The refusal is
checked first now, and the reply is still decoded so the seed baseline is refreshed either way.
Regression test `test_a_refusal_is_not_masked_by_the_routine_status_push`, confirmed to fail against
the old ordering.

**46. The co-command rules that could never fire — fixed.** Rules triggered by an on/off setting
were read in one vocabulary only, so 3,139 rules on 847 products parsed to an empty match set and
never sent their paired command (switching off did not clear self-clean, boost did not clear quiet).
The reader takes every vocabulary the settings use, the rule bundle is re-derived from the published
models, and a bundle-wide test refuses an empty condition.


### 52. The roof cabinets' big-data telemetry — SETTLED: compressor frequency and temperatures are live; power/current are not reported

⚠️ **Reworked 2026-09-01.** Three earlier readings of this were wrong in turn and are all corrected
here at the point of the claim. The truth, from the issue #12 cabinet (`AE2C52Q00`) captured with
the frame-keeping build, and from Haier's own generated UART protocol for this class:

* **The cabinet answers the telemetry query over the LAN.** `lan_frames` holds a **147-byte
  `06/7d01`** report. ⛔ Withdrawn: *"the same class of appliance answers nothing at all… what is
  missing is delivery."* The silence was the parser's, not the module's.
* **It is the documented `0D012` big-data frame, and it is DECODED (shipped).** The `7d01` payload
  is Haier's *big-data information (BIT-position format)*, whose field layout is the vendor's own
  **附录H** in `catalogue/profiles_0d12/0D012_UART通讯协议.txt`. The payload offset is confirmed the
  right one because its first eight bytes decode to the live state exactly (target 25 °C, mode cool,
  on, human-sensing 3). 附录H places `power` at Byte29, `compressorFrequency` Byte36,
  `compressorCurrent` Byte37, `compressorStatus` Byte40 — which is **word-for-word the published
  span-21 layout** one word-run past this class's extra indoor/outdoor PM2.5, CH₂O, VOC and CO₂
  readings (hence the 27-word span). That map ships as `uss._BIGDATA_VENDOR_DOC[27]`;
  `parse_extended_status` decodes the frame and the coordinator no longer writes the unit off.
  ⛔ Withdrawn: the intermediate claim that the tail was *"the classic 14-byte tail, decode with the
  classic offsets"* — the classic-offset read landed on undocumented bytes past Byte41 and only
  looked plausible while idle.
* ⛔ **The 附录H byte positions were WRONG for this product** (corrected once more, from the wire).
  The vendor appendix places `power` at Byte29 and `compressorFrequency`/`compressorCurrent` at
  Byte36/37, and those read a flat zero on the hardware. The real running block is the **classic
  engineering trailer at the END of the frame** — the identical block the 141-byte wall units carry,
  six bytes further along a 147-byte report — so it is decoded from the frame length, not from the
  appendix offsets.
* **SETTLED on three live captures** (once the build keeps polling, the reporter's downloads are
  live): the readings TRACK the compressor exactly — `compressorFrequency` **0 Hz idle → 40 cruising
  → 103 cooling hard**, evaporator coil **25 → 17 → 10.5 °C** (colder under load), discharge line
  **33 → 49 → 79 °C** (hotter), compressor **off → on → on**. These four (plus fan state) are real
  and shipped. Textbook refrigeration physics, self-consistent across the three states.
* **Power and current are NOT reported by this three-phase class.** `power` reads a flat 0;
  `compressorCurrent` is railed at its documented full-scale ceiling (`0x01FF` = 51.1 A — the vendor
  model gives it a 9-bit field, 0.0–51.1 A — unchanged whether the compressor is off or at 103 Hz,
  which no real current does). The vendor model documents **only** `power` (W) and `compressorCurrent`
  (A) here — **no voltage, no per-phase reading, no energy/kWh counter anywhere** in the 0D012 model
  (three-phase appears only as a *fault* code, `threePhaseSupplyErr`). So power cannot be
  reconstructed on-device, and a supply voltage would not help (there is no real current to multiply,
  and the compressor drive frequency does not convert to watts). Those two entities are retired for
  such a unit (`coordinator`, keyed on the decode dropping them) rather than shown as a constant that
  tracks nothing. Item closed for these cabinets; real energy needs an external meter.
* **Every path checked — the enumeration behind the negative** (so "no power" is scoped, not
  assumed): the vendor's Appendix C is the COMPLETE 0D012 command table and holds exactly **three**
  commands — `4D01` getAllProperty (→ 6D01), `4DFE` getBigDataFrame (→ 7D01), `5D01` onOff set.
  There is **no 7D02, no 4C01/5C01 per-attribute read, and no "detailed running data" query** in the
  61-page protocol. The 62-field 7D01 model's only load/electrical fields are `power` (W),
  `compressorFrequency` (Hz) and `compressorCurrent` (A) — **no voltage, per-phase current, power
  factor, reactive power, second current or kWh accumulator anywhere**, in 7D01 or the 101-field
  6D01 status. So there is no fuller frame or channel we have not read.
* **The board DOES measure current and voltage — it just never exposes the value.** The 6D01 model
  carries the electrical quantities only as PROTECTION FAULT BITS: `powerProtection` (over-voltage),
  `outdoorACProtection` / `outdoorDCProtection` (over-current), `ctCurrentErr` (CT abnormal),
  `threePhaseSupplyErr`. A unit needs a CT and voltage sensing to raise those, so the measurement
  exists internally — it reaches the protocol only as a threshold trip (a named fault we already
  surface), never as a readable analog value.
* **The two fields are real, and populated on OTHER classes.** Prior art issue #39 (a single-phase
  residential Casarte, smartAir2 family) sends live, varying `power` (0 / 256 W) and
  `compressorCurrent` (0.0 / 76.8 / 153.7 raw) on the same two fields — so they work on Haier
  hardware in general; this three-phase central class simply leaves them empty (`power` 0) and
  railed (`compressorCurrent` at its documented max `0x01FF` = 51.1 A). Why frequency but not amps:
  of the model's three load fields this class populates only the frequency.
* **Why the app shows nothing yet the cloud could:** the protocol routes 7D01 "only to the cloud
  server" by design (`user data → all endpoints; big-data → cloud only`), which is why the app's
  local view has no telemetry; the module relays 7D01 to a LAN controller anyway (that is how we get
  it), and the frame it relays is the BOARD's own — its temps and frequency track load, so the empty
  power/current are the board's own empties on this class, not a module placeholder or a richer
  copy the cloud keeps back.
* **The HARDWARE EPP was checked, not just the cloud template — they are byte-for-byte identical.**
  The board's own UART protocol document, the APK-bundled EPP wire models, the big-data
  function-model PDF and the master/slave comms spec all define the SAME 63 big-data fields at the
  SAME byte positions (`power` Byte29-30, `compressorFrequency` Byte36, `compressorCurrent`
  Byte37-38); the cloud template dropped nothing. There is **no separate diagnostic/engineering
  frame** — the "run-monitoring data area" (运行监控数据区) IS the 7D big-data set, spec'd as
  "synced to the app via the message platform, not pushed in the status loop" (the cloud routing
  above). Residential AC classes (`02011/02012/03012`) carry the **identical** three electrical
  fields and no voltage either — home units are not privileged. A `380 V` / phase scan of all four
  LAN frame types across five captures found nothing (the one 0xC0=384 candidate is a fixed
  status-structure flag, constant across every state and `0x3f` on the wall units).
* **The platform CAN model readable voltage — every AC class deliberately omits it.** Washing
  machines (`05001*`, `voltage` 0–500 V), range hoods (`0900*`, `voltage` 85–285 V), fridges (DC fan
  drive voltages) and water heaters (`dcVoltage`) expose a readable voltage on their own 7D01. That
  the fridge/washer/hood models carry it while EVERY Haier AC model (residential and the central-AC
  sibling `0D021`, which shares this template) omits it is strong evidence the omission is model
  design, not truncation. The board monitors voltage/current for outdoor-unit protection — proven by
  the errCode enum (7 power over-voltage · 26/28 AC/DC over-current · 30 CT abnormal · 37 three-phase
  supply) — and exposes that monitoring **only as the protection verdict (an alarm bit)**, never the
  measured value.
* **Honest residue (needs a capture, not more reading):** the on-disk `0D012_UART通讯协议.txt` is the
  GENERIC template-generated document, not the reporter's specific OEM outdoor board
  (`HCFI-38XTR32F`/`AE2C52Q00`). A particular OEM board could in principle define extra 7D fields —
  but the spec forbids the big-data area from duplicating anything, and every source (generic doc,
  both public templates, all residential + commercial AC EPP models) converges on the same three
  electrical fields, so it is a long shot. Confirming or refuting it needs a **UART capture** of that
  board (module↔board), which this project has never taken; prior-art issue trackers are the capture
  corpus if one surfaces. ★ **Simulator dig (2026-09-01) added actionable items** (memory
  `esphome-hon-source-is-the-decode-reference`): **compact-12/smartAir2 gains 5 controls we don't
  ship** — display, lock, ten-degree, half-degree, temp-unit (byte/bit-exact) — plus a `room_humidity`
  SENSOR; a concrete feature add for the 16 compact-12 products. The 7 hON `0d12` single-param
  candidates are double-confirmed. And `GET_DEVICE_CONFIGURATION 0x7C→0x7D` is a documented but
  uncharacterized per-unit config exchange — a live `0x7C` probe is the standing lead for the
  per-unit feature gate (likely module-blocked over :56800, untried). **RE of the vendor's E++ tool** (2026-09-01) surfaced two endpoints we do not use — a
  function-model file (`resource/funcModelFile`, parallel to the `logicLimit` we fetch) and the
  per-board PCB E++ file store — but the first needs a signed request and serves the same class
  model we already have (no voltage), and the second is behind the developer login and scoped to the
  OEM's account. So neither reaches the electrical data; the board↔module UART tap (decoded with the
  vendor's own U+串口监听工具, whose E++ crypto could be recovered from `SerialAssistant.exe`) remains
  the only avenue, and it needs physical access to a cabinet. ★ **Update — the board-direct case is already in the prior art.** esphome replaces the
  Wi-Fi module with an ESP on the board UART, so its captures ARE board-direct; prior-art issue #19
  (HaierProtocol 0.9.20, the hOn family) logs raw `7D01` frames off the board whose current field
  reads the SAME railed `01FF` we see via the module relay. So a serial tap would NOT recover the
  electrical data on an hOn unit — the board itself sends the placeholder; esphome-at-UART sees what
  we see, and reported no usable current for that unit. (The smartAir2 Casarte's live power/current
  is an older protocol on a single-phase board — not transferable.) ★ **Closed: 47/47 hON frames rail the current.** Every genuine hON `7D01` big-data
  frame in the prior-art corpus — 47, residential `U-AC` and commercial `U-BAC` (the `0d12` family's
  own device name, #115) — has `current`=`01FF` and no usable power; ZERO live. The railed field is a
  HON-PROTOCOL-WIDE property, not our unit or the module; the one live capture is smartAir2. No sliver
  remains. ★ **esphome confirms the group-set NACK too:** prior-art #115 is a `U-BAC` unit
  (commercial hON = our `0d12` family); esphome sent a group-set `60 01` and got `type 03` INVALID,
  code `00 01` — U-BAC/`0d12` REFUSES the group-set, exactly our finding. esphome has no
  single-param fallback, so it can only READ these cabinets; our `5Dxx` single-param path is the
  correct one and a genuine differentiator. (It also means esphome never requests big-data `4DFE` on
  U-BAC in that log — 0 occurrences — consistent with the group-set being rejected first.) ★ **The esphome hON SOURCE (not just its logs) is the register map we'd been reconstructing.**
  `esphome/components/haier` (`hon_packet.h`) defines the single-parameter `DataParameters` register
  (`CONTROL` + `0x5D00+id`, our exact write path); it matches our 9 confirmed 0d12 ids bit-for-bit
  and adds the standard ids `0x07 USE_FAHRENHEIT` (2nd witness for the withheld `5D07 tempUnit`),
  `0x09 DISPLAY`, `0x0A TEN_DEGREE`, `0x0D SELF_CLEANING`, `0x16 BEEPER`, `0x17 LOCK_REMOTE`,
  `0x1B SLEEP` — residential-derived CANDIDATES to probe on a 0d12 via the provisional mechanism.
  So "the 5Dxx numbering is not derivable" was true of HAIER'S PUBLISHED DATA; esphome's RE of real
  devices derives the STANDARD register (the enum GAP at 0x08 still neither confirms nor denies the
  provisional `5D23` presence, and it holds nothing for 4-sided vanes / ampereControl / powerSource).
  esphome also confirms NO voltage/energy field in hON (3rd source), and names fields we do not yet
  surface — `room_humidity` (status byte12), the expansion valve as a %, and 51 named alarm bits
  incl. the electrical/three-phase protections a 0d12 raises.

  ★ **Cross-checks done 2026-09-01 (esphome source):**
  * **Alarms — VALIDATED 51/51.** Our `ALARM_LABELS` is position-for-position identical to esphome's
    `HON_ALARM_MESSAGES` (all 51), and RICHER — we carry the service codes (`F1`/`E2`/`E14`/`E18`)
    esphome lacks; the only nit is esphome's "CBD" typo at idx13 where we correctly say "PCB". So
    "fault names right through position 50" is now independently confirmed for every bit.
  * **★ Seven NEW candidate single-parameter controls for `0d12`.** esphome's `DataParameters` ids
    `0x07/09/0A/0D/16/17/1B` each map to an attribute the `0D012` class DECLARES (附录H): `tempUnit`,
    `screenDisplayStatus`(/`lightStatus`), `10degreeHeatingStatus`, `selfCleaningStatus`, `muteStatus`,
    `lockStatus`, `silentSleepStatus`. We ship 9 confirmed `0d12` single-param ids + provisional
    `5D08`; these are candidates (the CANONICAL ids are now in each family's config — `catalogue/configfiles/`; id from esphome's 9/9-matching register, attribute
    from the class model). Add them as PROVISIONAL single-param controls (self-adjudicating —
    a refusal/unmoved field withdraws) the same way `5D23` presence ships; `0x09` is ambiguous between
    `screenDisplayStatus` and `lightStatus` — resolve on hardware. Needs a reporter's `0d12` to
    confirm, but no capture — the provisional mechanism adjudicates on first use.
  * **Per-unit feature detection — NOT in the hON handshake** (dug esphome, 2026-09-01). The
    device-version answer's `functions[1]` bitmap is PROTOCOL negotiation (CRC/interactive/multinode/
    roles), not an appliance-feature manifest; esphome gates nothing on it. Human-sensing has no
    capability marker (result field reads `00`=N/A whether or not a PIR is fitted). The only untested
    place a manifest could live is the config frames `0x7C`/`0xE9`/`0xEB` — likely module-terminated
    over `:56800` (like `0x61`/`0x70`), but `0x7C` is an untried probe on a live unit (⛔ disable an
    entry first). So the per-product presence/feature gate must stay panel-derived or class-based; the
    wire offers no per-unit capability read.

These cabinets answer a query for their detailed running data when it is asked over the wire inside
the appliance — a recording of one shows the manufacturer's own module asking nine times and the
board answering all nine, with a frame that is populated and changes between recordings.

⚠️ What is in that frame is only partly known, and it does **not** obviously include power. Its
first three quarters are the ordinary status report repeated, leaving seven readings of which two
are always empty and one is a fixed placeholder. Of the four that carry anything, one behaves like a
temperature — lowest while cooling, highest in fan-only — and none behaves like a wattage. On the
wall-mounted models the same seven readings carry power, current and compressor speed; on these they
appear not to.

Checked against the machine's own state, which each recording carries: three of the nine were taken
with the unit cooling and six were not, and **not one reading distinguishes them**. On the
wall-mounted models those same readings are the most load-dependent numbers in the protocol.

So the appliance answers, and its answer contains nothing that behaves like power or compressor
load. No description of this family's detailed-data layout exists anywhere we hold, so this is a
reading of how the numbers behave rather than a decode — and "cooling" is inferred from the setpoint
being below the room temperature rather than observed. A recording taken beside a meter reading
would settle it outright.

**What would close it:** a recording of that frame taken beside known conditions — the compressor
running, then off. That is how every other family's power reading was placed.

ⓘ ⛔ **Superseded 2026-09-01.** This said the vendor's *design template* described a 62-reading
frame that "does not line up — power lands on an empty word", concluding no description placed
anything. That was the full-function template read against the wrong offset. The class's real
big-data layout IS documented — 附录H of the generated UART protocol — and DOES line up (power at
Byte29 = word15, the span-21 position); the earlier mismatch was the analysis, not the data. What
remains open is only whether the board fills those documented fields when the compressor runs.

### 51. The cumulative energy counter is not read on a relative's layout

An air conditioner whose layout is worked out from a close relative's gets eleven readings, and the
cumulative electricity counter is not one of them. A unit whose own family map is registered does
get it.

This is not currently costing anyone: of every report attached to this project, the only appliances
decoded from a relative's layout are the central cabinets, and none of those publishes a counter at
all. It is written down because that is a fact about the reports we happen to hold rather than about
the design.

⚠️ It is deliberately not added on spec. The counter is a 32-bit value that extends *backwards* from
its stated position, so on a layout that carries extra words in the middle it lands somewhere no
report has ever confirmed — and a wrong lifetime-kWh figure in someone's energy dashboard is worse
than no figure at all.

**What closes it:** one diagnostics file from an air conditioner that is decoded from a relative's
layout *and* whose model lists the counter. The value can then be checked rather than assumed.
