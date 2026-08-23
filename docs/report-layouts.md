# Status report layouts

Every Haier AC answers a status query with the same envelope, and packs its attributes into an array
of 16-bit big-endian words that starts at **byte 92** of the decrypted report. Word `N` (1-based)
begins at byte `92 + 2*(N-1)`; bit 0 is the least-significant bit of the word. What differs between
models is **where each attribute sits in that array** — the *layout*.

This page is the inventory: which layouts exist, which the integration decodes, and what to do when a
unit reports one that is not here. It is the maintainer's companion to
[`new-model.md`](new-model.md), which is the user-facing "my model isn't decoded" guide.

## A layout is a family, not a length

A **family** is a distinct field map. One family spans several report lengths, because the length only
reflects how many words a particular unit carries — units append words for options they have and stop
where they run out. So the classic split-AC family shows up at 109, 121, 125 and 127 bytes with the
same field map throughout.

Length is therefore a *good but imperfect* key. The integration prefers an exact **Model ID**
(`uplus_id`) match, falls back to length, and in both cases only accepts the result if the decode is
plausible — a candidate that reads an impossible room temperature or setpoint is rejected in favour
of the partial "unknown layout" path, so a wrong family is never published as fact.

## When no family claims the report

Since **v0.35.0** there is a step between "no family matches" and the partial decode.

Every published model is the same attribute map at one of a small number of whole-word offsets, and a
Model ID shares its leading characters with its close relatives. So the published models most like an
unfamiliar unit name the offsets its report is likely to use. The integration shortlists those and
tries each against the report the unit actually sent, keeping whichever one agrees with it.

The shortlist never decides on its own, and is not built to. Most Model IDs match two published
models rather than one, and **those pairs disagree about the offset every time** — one carries the
leading media block and one does not. Nothing else separates them: the rule sections are keyed by
product code rather than by Model ID, and the attributes a device declares describe its feature set,
not its layout, so a lean unit may sit on a rich map. Both were tried against the models that state
an answer and both got it wrong. Only the report settles it, which is why the candidates are decoded
rather than ranked.

Three limits, all deliberate:

- **Control is gated on the product's own published list.** A control command writes a whole block of
  words at once, so a layout arrived at this way commands only through three gates: the group-set
  command's packing (identical across the published air-conditioner descriptions), the product's own
  published list of which settings its group-set carries, and the per-family refusals for positions a
  family gives to a different attribute. A product publishing no list stays read-only — the safe
  default.
- **Core readings only.** Power, setpoint, room and outdoor temperature, mode, fan, vertical swing,
  fault code and who last changed the unit. The further attributes a device declares stay unplaced
  until the offset has been checked field by field against a real report.
- **It refuses rather than guesses.** A candidate that "fits" only because it read past the end of a
  shorter report — every field absent, nothing implausible because nothing is there — is rejected
  rather than believed.

### When the unit resembles nothing published (v0.52.0)

Until v0.52.0, a Model ID resembling nothing published produced **no candidates at all**, and the
unit fell through to the partial decode. That is what the window air conditioners hit (issue #11):
their identifiers diverge at character 16, *inside* the device type, which is exactly the boundary
the relatedness threshold exists to refuse — so they had no relative to inherit an offset from and
reported "no decodable status" despite being an ordinary grSetDAC appliance.

They do not need a relative. The offsets are only two, and the shortlist was never the evidence —
the report was. So a unit with no relative is now tried against **every offset a published model
reports at**, on two conditions:

- **the unit must have named itself** (it announces its Model ID on the discovery channel, key-free);
  and
- **its product must publish a group-set list.** That list is the product's own statement that it is
  a grSetDAC appliance packed by the shared frame, so it is independent evidence that the published
  map describes this appliance at all.

and with one extra rule: because the shortlist now carries no ranking, **the report has to single one
offset out**. Two that both fit is an unresolved question, not a coin toss, and falls back to the
partial decode. In practice they rarely both fit — the offsets are nineteen words apart, so on a
short report the wrong one reads past the end and places nothing. A window unit's 109-byte report is
eight words long and the climate block starts at map word 20, so only one offset places anything at
all.

This is deliberately **not** a new assumption. The partial decode already reads the head of *any*
unrecognised report at fixed byte positions — which is this map at −19 — and publishes power,
setpoint, mode, fan and vane from it with no check at all. What the fallback adds is the rest of the
block and, unlike that path, a verdict.

Units with no group-set list keep exactly their previous behaviour, including their `layout:
unknown` flag — and that flag is how an unsupported model gets reported and then supported, so it is
not spent on a guess. In the published catalogue that is the difference between 28 products that
state a frame and the 187 central-air models that state none.

A resolved layout is reported as `related-19` / `related+0` (the offset it used) rather than a family
name, so diagnostics distinguish it from a family confirmed on hardware.

## Known families

| Report | Family | Setpoint | Sensors | Status |
|---|---|---|---|---|
| 109 / 121 / 125 / 127 B | **classic** | `°C − 16` @ w1.b8 | indoor w6.b8, outdoor w7.b8 | ✅ read + control |
| 109 B (window units) | classic map, resolved as `related-19` | as above | indoor w6.b8; **no outdoor probe** | ✅ read + control since v0.52.0 |
| 117 B | **compact-12** | whole °C @ w12 | indoor w1; w2 low byte is the outdoor-UNIT temp (hot, ~60 °C cooling; not ambient) — diagnostics only | ✅ read + control |
| 165 / 175 B | **extended-36** | `°C − 16` @ w20.b8 | indoor w25.b8, outdoor w26.b8 | ✅ read + control |
| 209 B | **extended-46** | **half-degrees** @ w20.b8 | indoor w35.b8, outdoor w36.b8 | ✅ read + control (no left-right vane) |
| 133 B | *unclaimed* — map below | `°C − 16` @ w1.b12 (4 bits) | indoor w5.b8, outdoor w6.b8 | ⏳ documented, not shipped |
| 149 / 155 B | *unclaimed* — floor/heat-pump class | @ w25.b8 | — | ⏳ two conflicting maps at 149 B |

### Secondary readings, by family

Beyond the climate block, families differ in what else is placed. A field is offered only where its
position is supported by the reports themselves — absent beats wrong, since a misplaced offset shows
a confident but invented value.

| | classic | compact-12 | extended-36 | extended-46 |
|---|---|---|---|---|
| heat capability | ✅ | — | ✅ | ✅ |
| fault code + last-changed-by | ✅ | — | ✅ | ✅ |
| fault bitmap | ✅ (its own frame, family-independent) | ✅ | ✅ | ✅ |
| self-clean | ✅ | ❌ | ✅ | ❌ |
| vane positions (both axes) | ✅ | ❌ | ✅ | ❌ |
| live power, from the report itself | ❌ | ⚠️ (decoded at w3, diagnostics only — unit unproven, so no sensor) | ✅ (175 B only) | ❌ |
| cumulative energy total | ❌ (register present, never populated) | ❌ | ✅ (where populated) | ❌ (works, unit unsettled) |

Heat capability, the fault code and last-changed-by all sit in the sensor block, one and two words
past the outdoor reading, so they follow wherever that lands. The fault bitmap arrives in a separate
frame and needs no layout at all.

**Self-clean** comes from the flag word, four words into the control block. That holds on classic and
extended-36 — on the latter the reports corroborate it, with the two purification bits set together
there and the self-clean bit clear on units that were not cleaning.

★ **And on extended-36 it is now observed, not inferred** (a 175-byte unit, 2026-08-05): the control
shipped for that family on the strength of the command being shared across layouts, which is exactly
the kind of inference the write gate says not to trust. Its owner pressed the button and the unit
started a cycle with `CL` on its panel. So a write confirmed on one family does carry to another
unmodified — the first direct evidence for that, which until then rested on the published write
frame alone. It does not license skipping the check: the gate exists because a field can decode,
be declared, validate, and still be discarded by the hardware.

It is **not offered** on the other two, for different reasons.

On **compact-12** the shared map does not carry over — its packing differs throughout — but the
family's own published description places self-clean, in word 9 alongside its other toggles, and that
whole description is now decoded (all 38 fields; the decode grew from seven to the full set). Self-clean
is read from word 9 **into diagnostics, not the self-clean sensor**: every capture reads the bit 0, so
there is no positive confirmation to promote it on, and a report taken while a cycle runs would both
confirm the bit and license the entity in one step. (Two other newly-decoded registers — a live
input-power figure at w3 and the outdoor byte at w2 — are held back the same way, on unit/meaning
rather than the bit; see `FUTURE_WORK.md` item 31.)

On **extended-46** the flag has two candidate homes and the captures cannot choose between them.
That family confirms w20/w21/w22 unmoved, w35/w36 at +10, and a vane at w25 with fan speed at
w26.b9 inside the inserted block — so the ten-word block starts after w22 and at or before w25.
If it starts at w25 the flag is at report w24; if it starts at w23 or w24 the flag is at report
w34. Every reading predicts indoor temperature at w35, so that cannot separate them, and w23, w24,
w33 and w34 all read zero in all three captures. Any capture with a w24-block feature switched on
(Health, the ambient light, fresh air) pins the insert point and places the whole block at once.

**Vane positions** — a `select` offering the stops a vane can hold, rather than just sweeping or
not — need a family that packs the vane as the multi-bit code it is. Classic and extended-36 do;
compact-12 collapses each vane to a single bit, so a position sent there would arrive as "sweep".
Extended-46 packs its up-down vane as a code and both reads and writes it as of v0.47.0, but is
still left out here: no write to that field has been *observed* landing on the family yet, and the
four-way swing already exercises the same field at its two ends, which is the cheaper way to find
out. Its left-right vane is not written at all — nothing in its report reads one back. The positions
themselves come from the device's own model, so even on a family that can place them the entity
appears only for a unit that publishes more than the two ends.

The up-down axis needs one translation on the way out: a model numbers its stops `0, 2, 4, 5, 6, 8`
while the wire counts `0, 2, 4, 6, 8, 12`. `VANE_V_MODEL_TO_EPP` holds it, and it is confirmed on
hardware — a unit was stepped through every stop its app offers, one capture per stop, and reported
the table's value each time, ending on the same `0x0c` the classic family has always used for auto.
The left-right axis needs no table: its model code is its wire value.

### classic

The baseline: a leading block of settable control words, then the read-only sensors. Setpoint at
w1.b8, mode at w2.b13, fan at w2.b8, the boolean block (power, health, rapid, mute, sleep, screen) in
w3, horizontal swing at w4.b0, then indoor and outdoor temperature.

### compact-12

A genuinely different packing: *every* attribute, sensors included, lives in the word array, one
attribute per whole word. Indoor temperature is word 1 — which is why a classic decode of this family
reads the room temperature as a setpoint.

### extended-36

The classic map **displaced 19 words**. Words 1..19 are a voice/media module (volume, playback,
dialect); the climate block starts at word 20. This is the family where a classic decode is not just
incomplete but actively wrong: byte 92 is the module's `volume`, typically 100, which reads as a
48 °C setpoint, and the classic power bit lands in an unrelated word so the unit looks permanently
off.

Two report lengths belong to this family. **175 B is the same map with five words on the end** — no
displacement, every climate field at the same word — carrying a cumulative counter at words 34+35
and again at 39+40, and **live input power at word 41**.

Word 41 is published as the Power sensor: captures across a session read 0 W with the unit off,
1432 W at full cooling and a thousand-odd while it held a room, and the unit publishes an `acInput`
of its own that agrees. That makes this the only family whose power figure is a measurement rather
than one derived from a current reading — and it arrives in the status report, so a unit that never
answers the extended-status query still gets it.

The counter is published too, as the Energy sensor, and **it counts watt-hours**. It is the
published map's `totalElectricityUsed`, whose 32 bits put their low half at word 35 and their high
half in the word before it; the unit reports the same total again at words 39+40, and its own
`accumulatedUseMainsPower` and `totalElectricityUsed` agree with both.

The unit was settled by an owner who captured the register in known states while reading the vendor
app's energy page, and three measurements on three timescales agree:

| what | counter | expected |
|---|---|---|
| one accumulation interval spent cooling | +347 | 15 min at the 1224–1432 W its own power register read = ~1390 Wh |
| a 26-minute session at ~1190 W average | +478 | ~494 Wh |
| a whole day, 00:53 to 12:07 | +7516 | the app's 7.52 kWh for that day |

The register accumulates in fixed steps rather than continuously, which is why a reading taken
minutes apart can show no change at all: the model publishes the interval as `energySavePeriod`,
15 minutes on that unit and settable up to 270.

A register reading exactly **zero** is treated as absent, not as a unit that has consumed nothing.
Whole classes of these air conditioners carry the register and never populate it — every 165-byte
report seen reaches the word and reads zero there, as do our own units — and a permanent 0 kWh in
the Energy dashboard is worse than no sensor at all.

### extended-46

Extended-36 with a further **ten-word block inserted at word 25**. Words 1..24 are exactly where
extended-36 puts them; everything from extended-36's word 25 upward moves ten words later. The
inserted block was taken for a dual-airflow cabinet's second, per-tower set of fan and vane
attributes — these units do describe one — and a single-flow unit leaves most of it at zero.

⚠️ **That reading is wrong for the two words we read from it.** Word 25 and word 26 carry the
**appliance's** vane and fan, not a tower's: see the fan entry below.

Three things about it differ in kind rather than position, and each was fixed by values the reports
carry directly:

- the **setpoint counts half degrees from zero** (wire 44 = 22 °C), not whole degrees offset by 16;
- the vertical vane answers at word 25, inside the inserted block, with the classic vane encoding
  (the "swinging" flag is bit 3 of the nibble);
- the cumulative **energy register at words 44+45 works** on this family — a 32-bit counter that
  reads a real total, where the classic family reports zero. It is the same published attribute
  that counts watt-hours on extended-36, but it is **not** published here: this is the one family
  already caught departing from the published map in three places, and the counter's position is
  itself derived from the inserted block, so inheriting an unverified unit into someone's energy
  history is not warranted. One reading off that owner's app against a capture settles it;
- ★ **fan speed is placed at word 26 bit 9**, and this has now been decided three times, so the
  evidence on every side is in the tests. Word 21 bit 8, where every other family keeps it, reads a
  **constant 6** in all seven captures held from two different appliances — including between one
  owner's stated *high* and stated *low*. Word 26 bit 9 reads 1 on high, 3 on low, 0 with the unit
  off, and 1 where a fresh cloud record for that same report says `windSpeed` is 1. It is decoded as
  an **enum**, so a code the model does not declare — the idle 0, the constant 6 — surfaces as *no
  reading* rather than an invented speed.

So this family reads its fan speed and its up-down vane, and **writes both** — at the appliance's own
positions, settled from the published data (`FUTURE_WORK.md` item 29).

★ **The write positions are settled — the appliance's own vane/fan are in the inserted block.**
This family's **own** published group-set list assigns the shared-frame vane/fan slots — w1.b0–3,
w1.b4–7 and w2.b8–10 — to the **per-tower** vanes and fan (`…VerticalL` / `…VerticalR` / `windSpeedL`),
not to the appliance. The appliance's own vane and fan sit in the appended tail of the list, at
group-set **words 6 and 7**, which map (by `write_base_word + write_word − 1`) to report **w25 and
w26** — exactly where the read map reads them back. So the controls now write group-set word 6
(report w25.b0) for the vane and word 7 (report w26.b9) for the fan, with the frame extended to seven
words to reach them. Three independent lines agree (the published order, the captures, and the
write↔read relation), so no reporter test is needed to place them; the only thing a live write would
add is confirmation the appliance honours a seven-word frame (Rule 8). Until v0.47.x the controls
wrote the shared slots — i.e. the **left tower** — and could not reach the appliance's own fields at
all.

### How the read positions were settled, and why they had been withdrawn

One diagnostics file carries a report **and** a cloud record taken close enough together to check
against each other — setpoint 22.0, indoor 28.0, power on and all six word-22 toggles agreeing bit
for bit. Against that record:

| the report | the same file's cloud record |
|---|---|
| w20.b0 (the map's vane) = **0** | `windDirectionVertical` = **2** |
| w25 (inserted block) = **2** | `windDirectionVerticalL` / `R` = 0 / 0 |
| w21.b8 (the map's fan) = **6** | `windSpeed` = **1** |
| w26.b9 (inserted block) = **1** | `windSpeedL` / `R` = 3 / 5 |

The per-tower explanation the fan had been withdrawn under is refuted by that same document: a tower
register cannot read the appliance's value when the towers are published beside it as 3 / 5 and 0 / 0.

⚠️ **The retirement rested on a stale document, and on a freshness check that could not fail.** The
capture that retired word 26 read 0 there "while the appliance's own cloud record said 1", from "a
document that agreed with 53 other attributes and disagreed with none". That record was the **same
frozen shadow** as the file before it — a diagnostics `digital_model` is fetched once, at
onboarding — and its own setpoint disagreed with the report it was compared against, 22.0 against
24.0. The 53 agreements run over `model_declared_fields`, which holds only attributes no field map
reads (the voice module, probes these units lack, `tempUnit`), so none of them can change.

⚠️ **`write_base_word + write_word - 1` is a heuristic, not a law.** On this family it holds for
words 1..3 as *words* — setpoint, mode and the entire boolean block — and fails for exactly two
bit-fields inside the first two. Which way that failure runs is unsettled: the appliance may ignore
those bits in the group-set, or accept them and report the result only in the inserted block. Only a
write observes it, and the readback now makes that something an owner can check.

`windDirectionHorizontal` stays unwritten: its position is published like the others, but nothing in
this family's report reads it back. See item 28 in `FUTURE_WORK.md`.

### 133 B — documented, not shipped

One factory preset implies a 133-byte report, and it is a real AC family, but no unit has been seen
reporting one. The map is recorded here so that adding it is a ten-minute job rather than an
investigation. Note the **4-bit setpoint** and that this family carries running power and compressor
telemetry *inline* in the status report, where other families put it in a separate frame.

| attribute | word.bit/len |
|---|---|
| targetTemperature | w1.b12/4 |
| windDirectionVertical | w1.b8/4 |
| operationMode | w1.b5/3 |
| windSpeed | w1.b0/3 |
| onOffStatus | w2.b0/1 |
| windDirectionHorizontal | w3.b0/3 |
| indoorTemperature | w5.b8/8 |
| outdoorTemperature | w6.b8/8 |
| power (W) | w8.b0/16 |
| errCode | w9.b8/8 |
| compressor discharge / suction temp | w10.b8/8, w11.b8/8 |
| running frequency | w12.b9/7 |
| compressor status | w13.b0/2 |

### 149 / 155 B — a genuine collision

Two different maps both imply a 149-byte report (`operationMode` at w9.b7 in one, w16.b0 in the
other), and neither declares a wind speed — this is a floor-standing / heat-pump class rather than a
split AC. Length alone cannot pick between them, so a report of this size must be resolved by Model
ID, not by size.

## When a unit reports a layout that is not here

**The diagnostics file proposes the answer itself.** When no known layout claims a report, the
`report.layout` section carries a `candidates` list: ranked layout proposals, each naming a known
family, the word from which its fields are displaced, how far, and which setpoint encoding fits —
with the decoded values for every report the integration kept.

It works because every layout met so far has been a known family displaced from some word onward, so
the search is over `(family, pivot, shift, setpoint encoding)`. Two things keep it honest:

- **Several reports, in different states.** A status report is mostly zeros, so a map whose fields
  all land on empty words "decodes" perfectly into a cold, powered-off unit at its minimum setpoint.
  A candidate must explain *every* report kept, and its score is the weakest one's. This is exactly
  why [`new-model.md`](new-model.md) asks for three states rather than one.
- **The device's own attribute values.** The profile the unit publishes carries current values for
  many attributes. A candidate that reproduces values the device reported through a different
  channel is almost certainly right — this is what settles a proposal from "plausible" to
  "confident", and it is the strongest single signal available.
- **The states the captures were taken in**, which a new-model report already collects and which
  cost nothing: off, then cool at 22 °C, then fan-only, plus the room temperature off the handset.
  This is as strong as the published values and needs no cloud, so a model can be added from the
  captures alone.

The same search is callable directly:

```python
from haismart_hrdp import StatedState, probe_layout

probe_layout([report1, report2, report3], shadow={"targetTemperature": "24", ...})
# -> [{"family": "extended36", "pivot": 25, "shift": 10, "setpoint": "half", "score": 8,
#      "decoded": [...]}, ...]

# ...or, with no cloud profile at all, the states the reporter described:
probe_layout(
    [report1, report2, report3],
    stated=[
        StatedState(power=False),
        StatedState(power=True, target_temperature=22, current_temperature=27.0,
                    swing_vertical=False, mode_group="cool", fan_group="low"),
        StatedState(power=True, swing_vertical=True, mode_group="fan_only", fan_group="high"),
    ],
)
```

`mode_group` and `fan_group` are how a stated state is used without knowing the model's codes — a
reporter says "cool" and "fan-only", not "1" and "6". Captures with different labels must decode to
different codes, and captures sharing a label to the same one. A map whose mode field lands on a word
that never changes reads one code in every state and fails that at once.

The effect is large. On two real reports, 77 of 83 candidates tie at the top score on plausibility
alone, and the ranking rests entirely on the tie-break; scoring the stated states pushes every
candidate that reads a wrong setpoint far down. Contradicting a stated value costs more than matching
one earns, because a report that is mostly zeros can agree by accident but rarely disagrees by
accident.

Beware invariants that do not discriminate. "The error code reads zero" sounds useful and is not: it
rewards a candidate whose fields land on empty words, which is the exact failure this guards against.

An empty result is itself informative: the report is not a displaced known family, and needs a map of
its own.

A proposal is a starting point, not a decision. Before a family ships it is checked against the
reporter's stated states, against the value ranges the device's own profile declares, and — where the
device publishes them — against its own reported values.

### Scoring a report's attachments

The search that runs inside diagnostics runs unaided: the states live in the issue as prose, so
nothing in Home Assistant can know that capture two was cool at 22 °C. `scripts/probe-diagnostics.py`
is where they are supplied. Give it the attached files in capture order and say what each one was:

```console
$ scripts/probe-diagnostics.py off.json cool.json fan.json \
    --state off \
    --state 'on,mode=cool,temp=22,fan=low,swing=off,room=27' \
    --state 'on,mode=fan_only,fan=high,swing=on'
```

The state syntax is the `StatedState` fields under reporter-friendly names — `on`/`off`, `temp=`,
`room=`, `swing=`, and the opaque `mode=`/`fan=` labels — and `-` stands for a capture nobody
described. It reads the reports and the device's reported values straight out of the files, so the
ranking it prints is the one the diagnostics file already carries, plus the states.

## These families are one map

They were each worked out separately, from captured reports, and they turn out to be the same
published attribute map at different displacements. `haismart_hrdp.canonical_map` carries it: 84
attributes with their word, bit, width and scaling, agreed on by the bundled air-conditioner
descriptions — same widths, same bits, same order, one whole-word displacement each. (Across the
full published catalogue, eleven families keep a *different* attribute at a handful of the shared
positions — the twin-tower vane/fan and the sterilization-for-self-clean swap — which is why those
specific controls are refused per family rather than assumed universal. A family can also move a
setting under its *own name*: every twin-tower family lists the appliance's vane, fan and horizontal
vane in the appended tail of its group-set order, past the shared frame's words, so the frame-path
controls are additionally gated on the product's own order corroborating each position — and two
families, the AQUA/JAA wall units, publish an order the frame cannot be reconciled with at all and
are kept read-only.)

| family | is |
|---|---|
| classic | the canonical map 19 words earlier |
| extended-36 | the canonical map exactly (its "media block" is the part classic units do not carry) |
| extended-46 | the canonical map with a ten-word block inserted at word 25 |
| compact-12 | genuinely different — one attribute per whole word, not this lineage |

Two of them are now *built* from it — the classic probe candidate and extended-36 read their
positions and scaling straight out of the map, and only state what the map does not: how each field
should be decoded (that a temperature sensor's zero means "no probe", that a vane nibble is a
position code, which table names an enum). Extended-46 keeps an explicit table on purpose: its vane
sits five words past where the map puts it, its setpoint counts half degrees, and its fan speed
answers from the inserted block, so a displacement plus three overrides would read as a rule with
more exceptions than rule. A test asserts the correspondence for all of them field by field, so a
change that drifts from it fails rather than diverging quietly. The practical consequence is for **new** models: a layout is the canonical map at
some displacement, so what has to be discovered is one integer rather than a whole field table.

The map also independently confirmed the up-down vane translation that was settled on hardware,
including an entry no unit here has ever exercised.

### Reading what a device declares, not just what a family maps

The map carries 85 attributes where a family map carries a dozen, and a *device* routinely declares
three or four times what its family map holds — 42 against 14 on the reference units. Those extra
attributes are read now, from the map at the family's displacement. It needs no capture per
attribute, because membership comes from the device's own model and position from the map, and the
two are arrived at independently: `WireModel.model_fields(declared, report_length)`.

The displacement has to be earned, and `WireModel.canonical_displacement` records where it has been:

| family | displacement | evidence |
|---|---|---|
| classic | −19 | all 9 mapped positions reproduced; decodes a real 125-byte report in agreement with the classic decoder on every shared field |
| extended-36 | 0 | all 12 mapped positions reproduced |
| extended-46 | — | 6 of its 9 disagree with any single offset (the ten-word insert), so it declines |
| compact-12 | — | not this lineage |

Two things it will not do, both for the same reason — a value that may not mean what it says is
worse than no value:

- **A family with no confirmed displacement returns nothing.** Placing three dozen attributes from a
  guessed offset would put every one of them somewhere plausible and wrong.
- **A code is translated where the map says it must be.** Booleans and scaled readings are kept as
  they stand, because the wire value *is* the value. An unscaled number is a code, and a few
  attributes number themselves one way in their published values and another on the wire — so the
  map carries that correspondence for the two attributes that need it, and carries none for the rest
  because they need none. An absent correspondence is the map answering, not the map staying silent.
  Checked against a live unit, all 21 booleans and scaled readings matched the values the device
  publishes through its cloud profile, and the one code that did not — reading 0 where the device
  published 1 — is one of the two, behaving exactly as its entry describes.

The readings land in a diagnostics download (`model_declared_fields`), beside the device's own
published values (`digital_model.reported_values`) so the two can be compared directly. Most are not
entities: their placement rests on the published map rather than on a capture apiece, and a wrong
value in a diagnostics file costs nothing where the same value on a dashboard is a fault report.
The exception is the numeric environment suite — PM2.5, CO₂, formaldehyde, VOC, indoor humidity —
which does become sensors on units that declare the probe, because those values carry their own
guards: zero is "no probe" rather than a state, and every one of them is bounded by the published
models, with anything outside the bound dropped as a sentinel (`FUTURE_WORK` item 37).

One placement detail matters here and is easy to get wrong: the reference hardware's 127-byte
report keeps one extra word ahead of its sensor block, so the map's words 25 and up sit one word
later there than on the 125-byte member of the same family. The layout table always encoded this
(its per-length sensor offsets differ by one word); the declared-attribute placement now follows it
per report length as well, pinned by a test to the layout table's own confirmed offsets.

## Why the registry still exists

It is a fair question whether the search could simply replace the hand-written families. Three of the
four *are* the same map displaced — classic → extended-36 is +19 words from word 1, extended-36 →
extended-46 is +10 from word 25, and the reference hardware is the classic map +1 from word 5 — so
the family list is partly an artefact of writing each one out separately. Expressing a family as
`(base map, displacements, setpoint encoding)` instead of a fresh field table would collapse most of
that duplication, and is the obvious next simplification. Only compact-12 is a genuinely different
packing.

Choosing a layout at runtime is a different proposition, and the registry stays for reasons that do
not go away:

- **The ranking is a heuristic, and ties are common.** Candidates that score identically can read
  mode and fan from different words. Publishing the winner of a close call as fact is precisely the
  failure this page exists to prevent.
- **Control needs more than a read map.** A proposal says nothing about *which* settings a unit will
  honour, and writing to a guessed layout is not a risk worth taking, so a probe could only ever
  replace the reading half. The window itself is no longer a mystery, though: the group-set frame is
  the report's own words 20 to 24 in shared-map terms — identical bit for bit through the first four,
  differing only in word five's filter flags, and stopping there because word 25 is where the
  unwritable sensor readings begin. So a family's write window follows from its displacement. What
  does *not* follow is permission: a unit can accept a group set and silently discard one bit of it,
  which is why every control is confirmed on hardware before it ships.
- **Determinism.** A registry entry behaves identically for everyone with that model, forever. A
  runtime search could resolve differently depending on which states a unit happened to be in, so two
  users with the same air conditioner could see different readings and a bug would not reproduce.

So the search does the derivation; the registry keeps the decision.
