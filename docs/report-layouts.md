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

## Known families

| Report | Family | Setpoint | Sensors | Status |
|---|---|---|---|---|
| 109 / 121 / 125 / 127 B | **classic** | `°C − 16` @ w1.b8 | indoor w6.b8, outdoor w7.b8 | ✅ read + control |
| 117 B | **compact-12** | whole °C @ w12 | indoor w1, outdoor w2 (not published) | ✅ read + control |
| 165 / 175 B | **extended-36** | `°C − 16` @ w20.b8 | indoor w25.b8, outdoor w26.b8 | ✅ read + control |
| 209 B | **extended-46** | **half-degrees** @ w20.b8 | indoor w35.b8, outdoor w36.b8 | ✅ read + control (no fan/swing yet) |
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
| live power, from the report itself | ❌ | ❌ | ✅ (175 B only) | ❌ |
| cumulative energy total | ❌ (register present, never populated) | ❌ | ✅ (where populated) | ❌ (works, unit unsettled) |

Heat capability, the fault code and last-changed-by all sit in the sensor block, one and two words
past the outdoor reading, so they follow wherever that lands. The fault bitmap arrives in a separate
frame and needs no layout at all.

**Self-clean** comes from the flag word, four words into the control block. That holds on classic and
extended-36 — on the latter the reports corroborate it, with the two purification bits set together
there and the self-clean bit clear on units that were not cleaning.

It is **not offered** on the other two, for different reasons.

On **compact-12** nothing carries over: its map differs throughout, so the flag needs its own
evidence — a report taken while a cycle runs, where the bit that changes is the answer.

On **extended-46** the flag has two candidate homes and the captures cannot choose between them.
That family confirms w20/w21/w22 unmoved, w35/w36 at +10, and a vane at w25 with fan speed at
w26.b9 inside the inserted block — so the ten-word block starts after w22 and at or before w25.
If it starts at w25 the flag is at report w24; if it starts at w23 or w24 the flag is at report
w34. Every reading predicts indoor temperature at w35, so that cannot separate them, and w23, w24,
w33 and w34 all read zero in all three captures. Any capture with a w24-block feature switched on
(Health, the ambient light, fresh air) pins the insert point and places the whole block at once.

**Vane positions** — a `select` offering the stops a vane can hold, rather than just sweeping or
not — need a family that packs the vane as the multi-bit code it is. Classic and extended-36 do;
compact-12 collapses each vane to a single bit, so a position sent there would arrive as "sweep",
and extended-46 keeps its vane outside the block the rest of its control map follows. The positions
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
inserted block belongs to a dual-airflow cabinet — these units describe a second, per-tower set of
fan and vane attributes — and a single-flow unit leaves most of it at zero.

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
- **fan speed answers at word 26 bit 9**, inside the inserted block and beside the vane at word 25 —
  not at word 21 bit 8, where every other family keeps it and where these units read a constant 6
  that their own model does not define. The three captures were taken in stated states, and word 26
  reads that model's codes for exactly those: low in the capture set to low, high in the one set to
  high, nothing with the unit off.

Fan speed is **read only** here. The settable word array runs 20..24, so word 26 is outside anything
the group-set can reach on this family; a longer array may exist but nothing has shown one. The
swings are still unsettled in both directions, so the encoder refuses them rather than writing to a
guessed word.

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
attributes with their word, bit, width and scaling, agreed on by every published air-conditioner
model — same widths, same bits, same order, one whole-word displacement each.

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

The map also carries more than the decoder currently reads — 84 attributes against about a dozen —
and it independently confirmed the up-down vane translation that was settled on hardware, including
an entry no unit here has ever exercised.

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
- **Control needs more than a read map.** A proposal says nothing about the group-set command or the
  word array it writes. Writing to a guessed layout is not a risk worth taking, so a probe could only
  ever replace the reading half.
- **Determinism.** A registry entry behaves identically for everyone with that model, forever. A
  runtime search could resolve differently depending on which states a unit happened to be in, so two
  users with the same air conditioner could see different readings and a bug would not reproduce.

So the search does the derivation; the registry keeps the decision.
