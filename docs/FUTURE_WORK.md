# Open items

Each is written to be picked up cold: what it is, why it is not done, and what would settle it.

## 1. Vane positions on a unit whose model understates it

Both axes now offer their positions, as `select` entities beside the swing controls, built from the
stops the unit's own model publishes. The up-down axis needs its model codes translated to reach the
wire — a model numbers its stops `0, 2, 4, 5, 6, 8` while the unit works in `0, 2, 4, 6, 8, 12` —
and that table is confirmed on hardware: a unit was stepped through every stop its app offers, one
capture per stop, and reported the table's value each time. The left-right axis needs no table; its
model code is its wire value.

What is left is the case where **a model publishes less than the hardware has.** The reference units
here are exactly that: their handsets step the up-down vane through six stops, but their model lists
only `0` (fixed) and `8` (auto), so nothing authorises the six. They get no up-down entity, which is
correct — an option nothing declares is a guess, and a group-set applies the whole word block, so a
wrong value there is not a local mistake.

Settling it needs evidence from those units specifically: a recorded command carrying a position, or
the same stepping exercise on hardware whose model does list the stops, enough times to establish
that the translation table holds across models rather than on the one that confirmed it.

## 2. Health writes one bit where the vendor app writes three

Toggling Health moves three bits together — its own flag plus the two purification-status bits — and
they have never been observed apart. Our encoder maps `healthMode` to its own bit alone. A unit
commanded from its handset sets the other two itself, so a single-bit write most likely suffices.
That is an assumption. One write from our side, with the report watched, settles it.

## 3. Self-clean reporting on two more families

Offered on the classic and 165-byte families. Not on the 209-byte or 117-byte ones, because the flag
word's position there is not supported by evidence: the 209-byte family places its vane outside the
displacement its control block otherwise follows, so it does not share the same shape, and the
117-byte family has a different map entirely.

One report from either, taken while a self-clean cycle is running, settles it — the bit that changes
is the answer.

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

## 7. The one rule we decline to honour

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

## 8. The fault decode has not met a real fault

The bitmap decode follows the vendor's own parser and the labels match the published fault list, but
no unit here has reported a fault. `errCode` gives a free cross-check when one occurs: it names a
single fault where the frame carries the set, so the bit that is set must be `errCode - 1`.

Nothing to do but keep the diagnostic in place and check the first report that arrives.
