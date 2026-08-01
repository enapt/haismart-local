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

## 6. Layout probing without the cloud

`probe_layout` already treats the cloud shadow as optional, but scores only on plausibility. The
issue template collects three captures **in known states** plus the room temperature the reporter
read off the handset, and none of it is used. Scoring against that ground truth — the power bit
reading 0, 1, 1 across the three; the mode differing between captures two and three; the setpoint
reading 22 in capture two; room temperature within a degree or so — would remove the shadow from the
critical path entirely.

Beware invariants that do not discriminate. "Error code is zero" sounds useful and is not: it would
reward a candidate whose fields land on empty words, which is the exact failure the prober guards
against.

## 7. Conditional writability is implemented but not wired

`locked_attributes` reads the device model's rules for when an attribute cannot be written — a unit in
fan-only ignores a setpoint; one reporting a fault ignores most settings. It is tested and unused.
Wiring it to entity availability would stop the integration offering controls the unit will discard.

## 8. The fault decode has not met a real fault

The bitmap decode follows the vendor's own parser and the labels match the published fault list, but
no unit here has reported a fault. `errCode` gives a free cross-check when one occurs: it names a
single fault where the frame carries the set, so the bit that is set must be `errCode - 1`.

Nothing to do but keep the diagnostic in place and check the first report that arrives.
