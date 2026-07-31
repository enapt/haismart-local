# Open items

Each is written to be picked up cold: what it is, why it is not done, and what would settle it.

## 1. Vane positioning, up-down axis

The vane fields are position codes, so pointing a louver somewhere specific is expressible on the
wire. The **left-right** axis now offers it: a `select` beside the swing controls, its options taken
from whatever positions the unit's own model publishes. The **up-down** axis still does not, and the
two are not symmetric — which is the whole of what is left here.

The codes a unit reports, stepping its louver controls through every stop:

| axis | positions | auto |
|---|---|---|
| vertical | 1, 2, 3, 4, 6, 8 | 12 |
| horizontal | 0, 3, 4, 5, 6 | 7 |

Physically, horizontal runs far-left, left, centre, right, far-right; vertical steps down from the
top, and 1 and 3 are the two positions a "health airflow" button cycles through.

**Why the up-down axis is still not done.** The encoder's allowlist permits only `{0, 0x0c}` there,
and a field only enters that list once a *write* of it has been seen. Every position above was
observed being *reported*, which is weaker evidence: it establishes the code, not that the unit
accepts it as a command.

What let the left-right axis through was its device model: it lists all eight codes (`0` fixed …
`7` auto) and its wire value **equals** the model's code, so `GRSETDAC_MODEL_AUTHORIZED` — the
mechanism that already lets a device's own model widen mode and fan speed — carries it, with the
existing `valueRange` gate doing the work. The up-down axis fails exactly that test: the same model
lists **only** `0` (fixed) and `8` (auto) while the handset visibly steps the vane through wire codes
1, 2, 3, 4, 6 and 8, and the wire values are not the model's codes anyway (its "on" nibble is
`0x0c`, its model's auto is `8`). The model both understates the hardware and speaks a different
language, so it cannot authorize anything.

That leaves two ways forward: a captured write of a position, or a deliberate decision to trust the
bundled translation table (`5→6, 6→8, 7→10, 8→12`) over the device's own published range.

Home Assistant's climate entity has no vane-position concept, so this wants a `select` — the shape
the left-right axis and the eco level already use. Note this is not a presentation gap: the entity
advertises `swing_modes` of off/vertical/horizontal/both and `swing_horizontal_modes` of off/on, so
there is nothing for any card to render. Adding positions means adding entities.

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
