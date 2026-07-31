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
| 165 B | **extended-36** | `°C − 16` @ w20.b8 | indoor w25.b8, outdoor w26.b8 | ✅ read + control |
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
| left-right vane positions | ✅ | ❌ | ❌ | ❌ |

Heat capability, the fault code and last-changed-by all sit in the sensor block, one and two words
past the outdoor reading, so they follow wherever that lands. The fault bitmap arrives in a separate
frame and needs no layout at all.

**Self-clean** comes from the flag word, four words into the control block. That holds on classic and
extended-36 — on the latter the reports corroborate it, with the two purification bits set together
there and the self-clean bit clear on units that were not cleaning. It does **not** hold on
extended-46, which places its vane outside that displacement, so its control block is not the same
shape; nor on compact-12, whose map differs throughout. One report from either family taken while a
cycle is running would settle it.

**Left-right vane positions** — a `select` offering the stops the vane can hold, rather than just
sweeping or not — are classic-only, and for a different reason: the other families pack that vane as
a plain on/off, so a position sent to one of them would be applied as its auto code. The positions
themselves come from the device's own model, so even on classic the entity appears only for a unit
that publishes more than the two ends.

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
  reads a real total, where the classic family reports zero. Its unit is not yet established, so it
  is not published as a sensor.

Not yet settled, and therefore neither read nor settable: **fan speed** and the swings. These units
report a wind-speed code their own device profile does not list, so the field's position is not
confirmed; the encoder refuses any field it cannot place rather than write to a guessed word.

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

The same search is callable directly:

```python
from haismart_hrdp import probe_layout

probe_layout([report1, report2, report3], shadow={"targetTemperature": "24", ...})
# -> [{"family": "extended36", "pivot": 25, "shift": 10, "setpoint": "half", "score": 8,
#      "decoded": [...]}, ...]
```

An empty result is itself informative: the report is not a displaced known family, and needs a map of
its own.

A proposal is a starting point, not a decision. Before a family ships it is checked against the
reporter's stated states, against the value ranges the device's own profile declares, and — where the
device publishes them — against its own reported values.

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
