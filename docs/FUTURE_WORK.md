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
a unit's own model publishes. That half is closed and settled two ways: the up-down translation
(`0, 2, 4, 5, 6, 8` in a model vs `0, 2, 4, 6, 8, 12` on the wire) was hardware-confirmed stop by
stop and then reproduced independently by the published map across every model, including a `7 → 10`
entry no unit here has exercised. A test asserts it field by field.

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

### 8. The declared attributes that are still unreachable

A unit declares three or four times the attributes any family map carries, and every one sits where
the published map already says — so the extra readings are decoded into diagnostics
(`model_declared_fields`), membership from the device's own model, position from the map. The
user-facing ones have since been promoted to entities: the optional-feature sensors (item 4's gate),
the panel controls (item 36), and the air-quality suite (item 37).

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

### 13. The four-sided cassette vanes — parked, not a request

Seventeen central models expose four independent vanes instead of one left-right field. Established
without hardware: they **replace** the left-right field (the only difference between the nine- and
twelve-attribute variants of one family), are **three bits each** on the same code range, and no
model declares both. But their **position** is not determined (the models list them in the appended,
unordered region), and four identical fields with identical encodings are symmetric — no published
description can separate them; it would take a reading in which they differ, and nothing published
contains one. So this is parked.
⚠️ **Its old reason no longer holds and is withdrawn (2026-08-25):** it used to end "the central-air
family these belong to is now in the shipped list with identities and rules, but **none has a placed
layout** (item 11), so leaving it parked still costs nothing". Those cabinets now read *and* command
(items 11 and 42), so the cost is real, if small — a unit with four-sided vanes gets every other
control and no vane control. It stays parked only because the four fields are genuinely
indistinguishable in published data; **one report from a unit with the four vanes in four different
positions separates them at once**, and that is now worth asking for.

### 19. The still-unpositioned settings — recounted, and mostly not controls

Counted per family against the description each actually uses, the compact family is complete and the
central-air family has six unplaced (item 13 plus two supply readings). The wall/floor family shows
~101 unplaced attributes, but **that number is not the missing-control gap.** About 49 are not
controls at all — rental/shared-AC management, energy/power telemetry (mostly already surfaced as the
power and energy sensors; only niche solar/storage registers are genuinely unsurfaced), query-command
pseudo-attributes, system/config/identity fields, and RGB scenario-lighting effects on a single
product. That leaves **~52 genuine AC control/feature attributes**, and most of *those* are already
handled (`generatorMode` is eco; the dual-airflow set is blocked on read-back; the timer trio on
position; `mouldProof`/`drying`/`preventHeatstroke` shipped). **Quote the filtered figure, not 101.**

What settles any single one is unchanged: a report from a unit that actually has the feature, taken
with the feature in a known state — the layout prober already scores against written-down states.
Nothing is waiting on this and nothing can go wrong because of it: none is surfaced, so none can be
mis-read, and a unit missing one is otherwise fully supported.

### 31. The compact family's three unproven registers

That family's 117-byte report is **decoded in full** — thirty-eight positioned fields, up from the
seven once read, every original field still exactly where the published description says. Three of the
additions are held in the decode (visible in diagnostics) rather than promoted to entities, because
position is settled and *meaning* is not, checked against the three real reports from the issue #4
unit:

* **input power** (word 3, low + high byte) — live (0 off, 15 cooling, 0 fan-only), but 15 is not
  watts while cooling, so the unit cannot be taken at face value. One reporter reading their meter or
  app beside a capture settles the scale.
* **the word-2 low byte** — an **outdoor-unit** temperature (reads ~60 cooling, stale ~59 off), *not*
  ambient outdoor air, so it is `w2_low_raw` in diagnostics rather than an "outdoor temperature"
  sensor a user would misread.
* **the word-9/10 toggles and flags** — positions published, but every capture reads them 0, so there
  is no positive confirmation of a bit until a capture exercises one.

⚠️ **Prior art was checked for these and does not answer them (2026-08-25).** The independent
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
  `pvPowerSavingMode`, `uvSterilizationSwitch`, `windAvoidance` — place NOWHERE even against the full
  frame (they fall in the append region the order does not order). One capture per family settles them.
* **dual-airflow** (`windDirectionVerticalL/R`, `windSpeedL/R`) — the twin-tower write positions are
  known (ext46, w1/w2), but **no report we hold reads a tower back**, so they would be write-only
  controls. Blocked on one capture with a tower vane parked non-zero (the same capture item 3 wants).

⚠️ **The per-attribute write channel does NOT rescue any of this, and that is now measured rather
than assumed (2026-08-25).** Item 42 writes central cabinets one setting at a time without needing a
position, so the obvious question is whether the same channel reaches these. It does not: across all
174 bundled device descriptions — 5,054 per-attribute command declarations, 596 distinct attribute
names — **no air-conditioner class publishes a per-attribute command for any climate attribute**. The
plain AC descriptions publish exactly one, `onOffStatus`; the two richest add twenty, all of them
voice-box functions. Every `targetTemperature`/`operationMode` per-attribute command in the corpus
belongs to a **different appliance category** (water heaters, sterilizer cabinets, steam ovens), at
different numbers. The attrID list the models publish alongside it does not cover these attributes
either. ⇒ For the wall/floor families a position is still required, and a capture is still the way
to get one.
* **`freshWindSpeed`** — ⚠️ **this bullet was wrong twice over and is corrected (2026-08-25).** It is
  **not** "five values written by named attribute": read out of the published models, every product
  that declares it marks it **`writeType: G`** — group-written — and publishes **four** values, in two
  variants. Of the **16** products whose raw published model we hold: **3** publish
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

Until v0.51.0 these products were offered the full frame-position control set; every one of those
writes was a guess with substantial counter-evidence, and a guessed group-set runs wrong functions
silently rather than failing. They are now **read-only** (their report decode is unaffected — report
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
group-set words 6/7 (item 29). The same derivation could in principle restore fan and swing on the
other five families' ~117 products — but each family's tail packs differently and **no report from
any of them has ever been seen**, so there is no read-back and no verification. Blocked on a first
report per family; until then those controls are correctly absent (and the horizontal vane, which
the frame position would have written into tower/auxiliary bits, is refused by the order gate —
item 40 below).
⚠️ **Checked 2026-08-25:** those same public trackers carry no report from a twin-tower cabinet
either. Worth re-checking whenever one of those projects gains a dual-airflow user — that is exactly
how item 42 was settled.

### 41. The fan speeds — shipped v0.54.0; Boost alone is still withheld

Issue #11 exposed the shape of a defect worth stating once: the wire map's mode and fan **code sets
are the identity** — on every family that is the published map at a displacement, the wire value *is*
the standard code — so their only job is to say which codes exist, and a code missing from one does
not decode wrong, it **vanishes**. Downstream that reads as "the appliance did not report a fan
speed", not as "we do not know this code", which is why nobody noticed.

Both enums are now complete against the published catalogue, and — this is the part that took the
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

### 42. The `0d12` central cabinets — shipped v0.55.0; the two vane commands are still withheld

**187 products** publish **no group command at all**. Every attribute is marked individually
settable, and their firmware **refuses the group-set frame outright** — so the group set is not
merely undeclared for these cabinets, it is unavailable. Each setting is its own command, with the
value in the payload.

**What ships:** seven controls — power, setpoint, mode, fan speed, health, quiet and boost — offered
where the cabinet's own model declares the attribute, and each read back from its own position in
the report so it shows real state rather than an echo of the request.

* **The command bytes** are the ones these appliances are observed to exchange, and the values need
  no translation: mode `0/1/2/4/6`, fan `1/2/3/5`, setpoint `°C − 16`, booleans `0`/`1` — the same
  encodings every other family here uses.
* **Several settings become several commands.** There is no word block to pack, so a change that
  touches three settings sends three ops, each separately accepted or refused by the appliance —
  which also means a refusal names the setting that was actually refused. Power leads when switching
  on and trails when switching off, so a unit is configured while it runs and stopped only after the
  rest has been applied. ⚠️ That order is a choice, not a measurement; it is fixed so it is at least
  predictable.
* **Reads were already right** from v0.53.0, and are now corroborated against reports from an
  appliance of this exact identifier: setpoint, mode, fan and power all land where the published map
  puts them. Anyone seeing wrong sensor values on one of these is on ≤ v0.52.x and needs to update.

⚠️ **The two vane commands are deliberately withheld.** This generation defines one for each axis,
but no cabinet of this class has been seen to accept either — the appliance the rest were read from
has no vane at all. A command that is simply unimplemented is refused and harmless; one that is
implemented and means something else would move a setting nobody asked for. They wait for a single
observation, on the same bar as every other control here. **One report from a cabinet with a working
vane closes it.**

⚠️ **`invisible` is not used as the gate** — see item 43. Membership is the attribute being declared
at all, because the parameter table is per device class while the function is per product: a cabinet
with no health module must not be offered health merely because its class defines a command for it.

### 45. A multi-attribute write command exists on paper — it would collapse item 42's several ops into one

Item 42 sends one op per setting, because the class it serves has no group-set command. The protocol
documents a **third** shape between the two: a *set-parameters* command carrying a list of
`parameter id + value` pairs in one frame — the same per-attribute addressing item 42 uses, but
several at a time, with no packed word block and so none of the group set's whole-block hazard.

**Why it is not shipped:** nothing we hold says any appliance implements it. It appears in the
published command enumeration and in prior art's reference, and in **zero** of the 174 bundled
device descriptions — where the read-side counterpart (*get specific parameters*) is equally absent.
Prior art documents it without using it.

**What would settle it, cheaply and safely:** send one carrying an attribute's **current** value.
That is a no-op by construction, and the appliance answers every command with an accept or a refuse,
so the reply says whether the command is implemented without anything moving. It needs no reporter —
any unit here will answer.

**Why it is worth the ten minutes:** a cabinet that takes it would apply "turn on, cool, fan low" in
one op instead of three, which is fewer connections, no partial application if one op fails, and no
question about the order settings are applied in (item 42 currently fixes that order by choice).

⚠️ Not a blocker for item 42 — several ops is correct behaviour, just not the tidiest. And a refusal
here costs nothing: an unimplemented command is declined, which is the answer.

## Reference — not open items

Kept because each looks like something to "fix" until you know why it is the way it is.

### The layout prober is told what the captures were

Since v0.35.0 the prober is the *second* thing to run: an unfamiliar report is first matched against
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
ungated pattern. On paper that is the v0.32.0 phantom-feature bug on the control side.

**The counter-example that closes it.** Gating `supports_field` on an explicit `invisible` mark
immediately withdrew **left-right swing** from the owner's own unit. Its product `AAC1UKZ01` marks
**`windDirectionHorizontal` invisible** (one of 25 invisible attributes of 39) — yet that control was
**shipped in v0.24.0 and live-verified on that exact hardware**, tracking the handset through
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
  ⚠️ That should temper how far the v0.32.0 optional-feature gate is trusted, though the risk there
  (a hidden sensor) is mild and no case of it is known.
* The tree was left unchanged and the suite stayed green.

# Settled

Not open items — collapsed to the conclusion plus a pointer. The full reasoning for each is in the
git history and, where noted, in the canonical docs and the code.

**4. `echoStatus` vs `selfCleaningStatus` — the write contract.** Settled both ways. `echoStatus`
stays read-only: a live self-verifying write is *accepted* but the bit never lands, and the app's own
control panel renders no widget for it either. `selfCleaningStatus` is honoured (a live write started
a cycle; the panel showed **CL**) and ships since v0.34.0 as a Start-self-clean button plus a
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
and reachable on first report since v0.52.0, and **187** (`0d12`) publishing no group command at all
— read since v0.53.0, controlled since v0.55.0 (item 42). Their read layout is the shared map at −19,
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
the two vane commands can be withheld now and added later without disturbing anything else.

**14. Deploy and verify the shipped rules — done (2026-08-04).** The rules for all published products
travel with the integration and are consulted when the catalogue is unreachable (the ordinary path on
a firewalled install). Cross-checked on hardware: 19/19 comparable readings agree, the shipped and
fetched copies agree on identity, locking is unchanged and conditional. Found and fixed in passing:
diagnostics now prints the `invisible` flags (`feature_set_known`, `invisible_attributes` — empty and
absent mean different things).

**15. The compact family — superseded by item 31.** Its central "nothing more is obtainable" verdict
did not survive a fuller reading: the family's own published description has thirty-eight positioned
fields where the derived extract measured against had thirty, and `cloudControlStatus` /
`sleepCurveStatus` are placed at word 9. The lasting lesson: **count coverage per family**, never
against the shared map (which is generated from only one of the two published formats).

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

**23. Layouts resolved from the nearest published relatives — shipped (v0.35.0).** An unfamiliar
report is decoded at the offsets its close relatives use, keeping the one the report agrees with; the
report is the only tie-breaker (rules key on product code, declared attributes describe feature set
not layout, and both were tried and failed). Three refusals were deliberate; the read-only one was
lifted by item 30. ⚠️ Assumes item 16's stronger claim; not yet exercised against a genuinely unknown
appliance (both reference units are classic).

**24. A setting the unit ignores is not a fault — fixed (v0.36.0).** A control discarded in the
current mode used to go *unavailable*, which meant "state cannot be read" for states that read
perfectly, hid the reason, and lost the history. It now stays visible and readable, and the *command*
is refused with the model's own words. The refusal lives on the entity, not in `async_send_control`
(a model marks the mode unwritable while off, and turning on *is* a mode write). The self-clean button
is the deliberate exception — an action, not a state.

**25. An outdoor reading that is not a measurement — shipped (v0.39.0).** The outdoor probe is dormant
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

**28. Fan speed and the up-down vane on the 209-byte family — settled (v0.47.0).** Both ship; w25/w26
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
default. ⚠️ *"Nothing left read-only" was true as shipped and is no longer:* the v0.51.0 audit found
two families whose published order refutes the frame outright, and they went back to read-only on
that evidence.

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

⚠️ **The 187 were read-only until v0.55.0**, on the reasoning that "control needs a frame and neither
has a usable one". That was right about the frame and wrong about control: these cabinets do not use
a frame at all, and the mechanism they do use needs no order and no packing. A gate written for one
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
was classic-only, so every other family fell back to a cached blob; `is_control_baseline` now asks the
registry.

**35. Which units are placed offline — measured.** 1,236 of 1,451 (85 %) placed from published data
alone **as first measured**; the current figure is **1,421 of 1,451** (item 30's table). The reasoning
below is kept because it is the record of how the remainder was worked through, one class at a time. ⚠️ **The original wording of this item — "the 215 unplaced are almost exactly one central-air
class that the app publishes no panel for either — out of scope, not a hole" — was too broad, and is
withdrawn (2026-08-23).** The 215 are **two** central-air classes plus eight others: `0d12` (187, no
group command — item 11), `0d21` (**20, which publish the ordinary shared frame**), four wall and
four window. **Twenty-eight of the 215 therefore publish a frame**, are corroborated against it, and
became reachable on first report in **v0.52.0**; only the 187 are genuinely without published
positions. Nor is the *category* out of scope: 28 further central-air products are a registered
family that has read and controlled since the compact map shipped. The similarity threshold still
must not be lowered to reach any of them (they differ inside the appliance-type field) — v0.52.0
measures the displacement from the report instead.

★ **And in v0.53.0 the 187 are read too.** They were still being refused a decode because they
publish no group-set order — a gate that turned out to be evidence about the *write* frame standing
in for evidence about the *read* frame (Rule 22). They now resolve from their own report like any
other appliance and are **read-only**, control being the thing that actually needs a frame. So the
honest current statement is: **1,451 = 1,421 read + write · 30 read-only · 0 refused**.
⚠️ *Superseded here:* this used to end "the open question for the 187 is no longer *will we read
them* but *will one of their owners appear*". Both halves are answered — they read correctly from
v0.53.0 and they are controllable from v0.55.0 (item 42), neither of which needed an owner to
appear.

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

**40. A frame write must be corroborated by the product's own published order — shipped (v0.51.0).**
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

**44. A refused command was reported as SUCCESS — fixed in v0.54.1.** Every op connection opens with
the unit's routine status push (frameType `0x06`) and alarm push (`0x04`) *before* the answer to our
own frame arrives, so a refusal always travels alongside a perfectly decodable status blob. Taking
that blob as "the unit answered with its updated state" reported the refusal as success and displayed
the **pre-command** state as the result — the setting appeared to have been accepted and the entity
did not even look stale. Detection was already right; only the precedence was wrong. The refusal is
checked first now, and the reply is still decoded so the seed baseline is refreshed either way.
Regression test `test_a_refusal_is_not_masked_by_the_routine_status_push`, confirmed to fail against
the old ordering.
