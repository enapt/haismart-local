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

**The 209-byte family is ready to take.** The reason recorded here previously — that it places its
vane outside the displacement its control block otherwise follows, so it does not share the same
shape — was overtaken by the published map. `selfCleaningStatus` sits at word 24, and this family's
insert begins at word 25: the flag is *below* the insert, inside the range words 1..24 that this
family is known to place exactly where the 165-byte one does. That is the same standard the
165-byte family's own self-clean ships on, so the field can be added on the same authority.

What keeps it a judgement rather than a certainty is only that all three captures from that family
read 0 there, which is consistent with the position being right and equally consistent with any
other quiet bit. One report taken while a cycle is running turns it into a certainty; adding it
without one is defensible but is a decision, not a deduction.

**The 117-byte family is genuinely open.** It is the one family that is not a displacement of the
published map at all, so nothing carries over to it. It needs its own evidence: a report taken
while a self-clean cycle runs, where the bit that changes is the answer.

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

## 6. The layout prober's ground truth is not collected automatically

`probe_layout` now scores against `stated=[StatedState(...)]` — what each capture was known to be in
— as heavily as it scores the cloud shadow, and a contradiction costs more than a match earns. That
takes the cloud off the critical path: on two real reports, 77 of 83 candidates tie at the top score
on plausibility alone, and the stated states separate them. `mode_group`/`fan_group` carry the
relational half, so a reporter's "cool" and "fan-only" work without anyone knowing the model's codes.

What is left is plumbing rather than method. The states live in the issue form as prose, so a
maintainer types them into the call; nothing associates capture two with "cool, 22 °C, fan low". The
diagnostics prober therefore still runs unaided, on plausibility plus whatever shadow is stored. A
structured field in the issue form — or naming the three downloads — would let the proposal arrive
already scored against them.

## 7. The energy total, on the family whose map already has exceptions

The cumulative register counts **watt-hours**, settled on the 165/175-byte family against an owner's
own app: one 15-minute accumulation interval spent cooling added 347 against ~1390 Wh of measured
draw, a 26-minute session added 478 against ~494 expected, and a whole day added 7516 against the
app's 7.52 kWh. That unit now has an Energy sensor.

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

## 8. The fault decode has not met a real fault

The bitmap decode follows the vendor's own parser and the labels match the published fault list, but
no unit here has reported a fault. `errCode` gives a free cross-check when one occurs: it names a
single fault where the frame carries the set, so the bit that is set must be `errCode - 1`.

Nothing to do but keep the diagnostic in place and check the first report that arrives.


# Settled

Not open items. They are here because each looks like something to "fix" until you know why it is
the way it is.

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
