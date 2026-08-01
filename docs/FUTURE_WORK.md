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

## 4. Two settings that decode but cannot be written

`echoStatus` (the command-confirmation beeper, where set = silent) and `selfCleaningStatus` both
decode cleanly and are marked user-facing by the device model, but neither has been seen written.
They are deliberately absent from the write map rather than added on inference — a group-set applies
the whole word block, so a wrong bit is not a local mistake.

Self-clean now has both halves of a state transition observed. A captured write is what is missing.

## 5. A timer, on units that publish one

Some units declare `timingPowerOn` / `timingPowerOff` (minute counts, 0–1440) and a `timingStatus` of
cancel / set / keep. Others declare no timer attribute at all and merely hold a handset-set countdown
internally. Where the attributes exist, a timer entity is straightforward and would be the first in
this ecosystem; where they do not, it cannot be offered. Needs hardware that declares them.

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


## 8. The attributes a device declares are read, but not yet offered as entities

A unit declares three or four times the attributes any family map carries — on the reference units,
42 declared against 14 mapped — and every one of them sits where the published map already says.
Those extra readings are now decoded and reported in diagnostics (`model_declared_fields`), because
membership comes from the device's own model and position from the map, and the two are arrived at
independently. On a real 125-byte report they read sensibly, and the screen-display flag agrees with
what that unit published through the cloud.

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
