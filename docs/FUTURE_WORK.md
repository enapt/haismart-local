# Open items

Each is written to be picked up cold: what it is, why it is not done, and what would settle it.
Anything genuinely settled belongs at the bottom, under **Settled**, not here.

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

Offered on the classic and 165/175-byte families, not on the 209-byte or 117-byte ones. The two
remaining cases are no longer the same case, and the difference is worth stating before anyone
picks this up.

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

**The 117-byte family is separately open.** It is not a displacement of the published map at all, so
nothing carries over: it needs its own report taken while a cycle runs.

## 4. Two settings that decode and read but cannot be *written* — now tested, not just assumed

`echoStatus` (the command-confirmation beeper, where set = silent) and `selfCleaningStatus` both
decode cleanly and are marked `writeType=G`/writable by the device model. On paper they belong in the
write map. They are still deliberately kept out of it, and this is no longer an assumption.

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
It has both halves of its *state transition* observed but no confirmed *write*, and on the evidence
of `echoStatus` the assumption that `writeType=G` implies a working write is not one to make. It also
stays read-only.

⚠️ **When it is tested, one bit will not be enough.** Other implementations of this protocol start a
cleaning cycle by setting the flag **together with the machine state the cycle needs** — powered on,
dry mode, a 22 °C set point, both vanes centred, the display off, and the other cleaning flag
explicitly cleared. That is the same shape as the co-command rules a device's own model publishes, so
a test that flips the flag alone and sees nothing happen would prove nothing. It is one group-set
either way; it just has to carry the whole state.

Worth separating from the above: the **56 °C sterilising** flag lives in a different word from the
ordinary self-clean flag, and there is reason to think it behaves as a *trigger* rather than a stored
setting — an implementation that re-sends a status-derived baseline has to clear that word explicitly
or it re-starts the cycle it just read back. Our control path carries the baseline forward untouched,
which is the safe default for a setting and the wrong one for a trigger. Neither has been observed
here, and the two should not be tested as if they were the same field.

The general rule this leaves: **the model gives the candidate list of controls; a live self-verifying
write gives the verdict.** Any control added beyond the confirmed set must pass that live write on
real hardware first.

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

**Codes are included, and were not always.** An unscaled number is a code, and for a while every one
of them was dropped on the grounds that the wire numbering need not be the published numbering.
That is true of exactly two attributes in the whole map, and the map carries the correspondence for
both — so the rest were being withheld for want of an answer already given. They are now read: a
code the map translates is translated, and one it does not is already the published value. This is
also what finally made the indoor-humidity reading in item 10 appear.

They stop at diagnostics on purpose. A wrong value there costs nothing; the same value wired into
someone's dashboard is a fault report. What would move them further is the ordinary evidence: a
capture of a unit with one of them switched on.

Two families cannot have them at all, and that is correct rather than missing. **extended-46** has
no single whole-word displacement — 6 of its 9 mapped positions disagree with any offset, because of
the ten-word insert whose start is still not pinned (item 3) — and **compact-12** is not this
lineage. Both decline rather than place attributes plausibly and wrongly.


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

**Still open on other families.** The published map carries no `generatorMode` at all, so nothing
places it on the 209- or 117-byte families; they need the same four captures this one got.

⚠️ **Off and L1 are only 18 W apart**, which is not the separation the other steps show. Either L1
caps above what the unit was drawing, or it had not finished ramping. Worth one more reading before
anyone describes what L1 *does*; it does not affect where the field is.

## 10. Indoor humidity, on the units that have the probe

The published map gives the position — the low byte of the word carrying indoor temperature — and it
has been read as zero on every unit here, which is why no sensor is offered.

**That reason is no longer quite true.** A real 125-byte capture reads **55** there, a thoroughly
plausible humidity, and the map that places it is the same one verified field for field against that
very report. So the honest statement is not "every unit reads zero" but "every unit *here* reads
zero, and one unit elsewhere does not".

What is missing is the same thing item 6 is missing for the same capture: nothing has compared it
against what that unit reports through any other channel. A diagnostics download from a unit with a
humidity probe, taken with the room's actual humidity noted, settles it. The reading already appears
in `model_declared_fields` on any unit that declares the attribute, so the evidence may well arrive
on its own.


# Settled

Not open items. They are here because each looks like something to "fix" until you know why it is
the way it is.

## The layout prober is told what the captures were

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

`locked_attributes` drives entity availability: a unit in fan-only shows no setpoint, boost and quiet
go unavailable in the modes that discard them, and a faulted unit keeps only its power and mode
controls.

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

## 11. Reads for the central-air-conditioner family — one report unlocks 79 products

**Status: open, and the cheapest high-value item on this list.**

Seventy-nine of the published air conditioners are central/ducted units. Between them they declare
fourteen attributes, and **ten already have positions** in the shared map — `onOffStatus`,
`operationMode`, `targetTemperature`, `windSpeed`, both vane fields, `muteStatus`, `rapidMode`,
`indoorTemperature`, `tempUnit`. Nothing about their layout is unknown except **which displacement
applies**, and that is what the layout prober scores from a report length plus a few stated states.

**The displacement is derived, not awaited.** A model omits the leading media block or it does not,
and the offset is exactly the span it omits. These seventy-nine declare no media attribute at all —
checked against every attribute the shared map places below the climate block — which is the same
thing the classic family does, and the classic family reads nineteen words earlier. Their attributes
occupy the shared map's words twenty through twenty-five, so they occupy their own report's first six.

Nothing further is needed to read them. What has not happened is a unit of that shape being seen,
which would confirm the derivation rather than produce it.

**⚠️ Re-scoped 2026-08-03 — expect no reporter, and do not treat this as a coverage gap.** The
manufacturer ships **no phone-app interface for this device class in this region**: the app carries
panels for refrigeration, air conditioning (wall and cabinet) and laundry, and none for the class
these seventy-nine belong to. So an owner here has no vendor app to pair or control them with, and
is correspondingly unlikely to arrive with a report. Two consequences worth stating plainly:

* These products should **not** sit in a coverage denominator for this integration. Quoting "79
  products unsupported" overstates the gap — they are outside what the vendor supports here too.
* The derivation above still stands and costs nothing to keep. If a unit ever does appear, it is
  one report away. **Also useful:** of the seventy-nine, **thirty-six publish their attribute list
  in wire order** (word ascending, bit descending — verified against the shared map's anchors with
  zero violations), so their positions can be solved without a capture at all. The other
  forty-three show one consistent disagreement, which means either their list is not ordered or
  their layout genuinely differs — untestable without hardware.

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
therefore a closed item rather than an open one, and it costs nothing, because no model of this shape
is served by this integration.

## 14. Deploy and verify the shipped rules

**Status: built, tested, not yet run on hardware.**

The rules for all 171 published air conditioners now travel with the integration, and the coordinator
consults them when the catalogue cannot be reached. On a firewalled installation — which is the
configuration this integration is for — that is now the ordinary path rather than the fallback.

It changes startup behaviour, and this project has twice shipped decode work that passed every test
and was only caught by deploying. Before calling it good: deploy, then diff `model_declared_fields`
against `digital_model.reported_values`, and confirm entity availability is unchanged on a unit whose
rules previously came from the cloud.

## 15. The compact family, resolved as far as it can be

**Status: closed on layout and naming. What remains is not obtainable from anything published.**

Its twelve-word report is fully described. Every position this project already decoded agrees with
that description, and two separate published descriptions of the family agree with each other on
every position and identifier they share. Of the thirty positions stated, twenty-five now carry a
standard attribute name: eighteen joined through the identifiers the catalogue publishes, seven more
read directly from their labels onto names the family declares.

The five that stay unnamed are the interesting part, because they are not a gap. They describe an air
quality figure, a two-byte power reading, a particulate value and a room humidity — and **the family
declares none of those attributes**. These products do not have that hardware, which is exactly why
every one of them reads zero in every report available. A position stated for a sensor a product
lacks is not a mystery; it is the shared description of a product line being wider than any one
member of it.

One attribute the family does declare, `cloudControlStatus`, has no stated position anywhere.

⚠️ **Corrected 2026-08-03 — that is not the whole remaining gap; there are two.** A second declared
attribute, **`sleepCurveStatus`**, is likewise stated nowhere: it is real (not marked absent) on six
of this family's models, is a writable boolean, and appears in no published position — neither in
the shared map nor in this family's own description, whose unnamed slots were enumerated one by one
and contain nothing resembling it.

★ **Why it was missed is the more useful part.** Every coverage figure this project has quoted was
computed against the shared map, and that map is generated from **one of the two published formats
only** — so this family's description contributes nothing to it, and this family's attributes were
never counted against anything at all. **Coverage must be counted per family, never against the
shared map alone.** A companion false positive to expect in the other direction: an attribute can
read as "unplaced" merely because it is published nowhere while being perfectly well known from
hardware, which is the case for the eco setting.

What is still unresolved is not the layout but two readings within it, and neither can be settled from
published material:

* one byte is an outdoor temperature — the catalogue decides that, since these products declare an
  outdoor sensor and declare no room humidity sensor at all — but read as its own description states
  it puts the outdoors near sixty degrees while the room is at twenty-seven with cooling running. Two
  encodings survive, and they agree to within half a degree in mild weather and diverge sharply in
  cold. Nothing published distinguishes them.
* the power reading is a byte, extended to two on richer models, and shows fifteen while cooling. No
  published material states its unit.

Neither prevents anything shipping, because neither field is surfaced. They are recorded so that a
future reading is recognised for what it settles rather than re-derived.

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
| rules — locks, faults, co-commands | ship with the integration, all 171 published models | no |
| which features a unit actually has | derived from those same shipped rules | no |
| the product code that keys them | the model number printed on the unit — 171/171 are unique | no |
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

**On which units are supported, it is exact parity.** Of the 171 published air conditioners, this
integration reaches a byte map for 92 — and those 92 are precisely the ones the manufacturer
publishes a phone-app interface for. The 79 it cannot map are the central/ducted family, for which
the app carries no interface either. The same product-lineage split drives both, which is why the
two sets coincide rather than merely being the same size.

**Three things the app does that this does not:**

* **It can display an attribute it cannot decode.** Where the app has no usable layout for a unit it
  falls back to values reported by the manufacturer's servers. That is how it can show settings this
  integration cannot place — including the handful still unpositioned. This integration reads only
  what it can decode from the unit itself, so an attribute it cannot place is simply absent rather
  than filled in from elsewhere. **That is a deliberate choice, not a defect**: a value that did not
  come from the appliance is a value that can be stale, wrong, or unavailable exactly when the
  network is.

  ⚠️ **This is not the app having a better description of these appliances — it reads the same
  published descriptions this does.** Wherever a setting is unplaced here it is unplaced for the app
  too. Of the models declaring one of the still-unpositioned settings, **six have an exact published
  description for their own model and the setting is still not in it**; the rest reach one only
  through a close relative, or not at all. A description that fits a model exactly and still omits a
  setting means the setting was **added after that description was published** — these are recent
  features on recent hardware, not omissions. So the difference is not the map; it is that the app
  has a server to ask when the map runs out, and this integration deliberately does not.
* **Timers and scheduling are server-side.** A reporter's app timer turned out not to be a local
  setting at all. No timer entity ships here because there is nothing local to drive one — use Home
  Assistant's own automations, which do not depend on anyone's cloud.
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

## 19. The settings nobody's hardware has reported yet — parked

**Status: parked, not open. Nothing is waiting on it and nothing can go wrong because of it.**

Nine settings across the published air conditioners have no position in any description this project
can reach: the four vane fields on four-sided cassettes, mains and solar input metering, a cleaning
mode, a language list, and a sleep-curve flag.

They are parked rather than open because **they cannot be derived**. Every one of them postdates the
published descriptions that carry positions — for six of the affected models the description matches
their model exactly and still omits the setting — so no amount of reading published material will
place them. The vendor app is in the same position and covers it by asking a server, which this
integration deliberately does not do.

What would settle any of them is one thing only: **a report from a unit that actually has the
feature, taken with the feature in a known state**. Until then:

* None is surfaced, so none can be mis-read. There is no wrong value to show, only an absent one.
* Everything else about those models decodes normally — a unit missing one of these is otherwise
  fully supported.
* If a capture does arrive, the layout prober already scores against written-down states, so a
  single report with the feature on and off is enough to place it.

Treat the map as complete for everything locally derivable. This item exists so that a capture, if
one ever turns up, is recognised for what it settles rather than re-investigated from scratch.

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
