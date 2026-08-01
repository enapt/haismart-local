# The uSS local protocol

Reference notes for the LAN protocol these air conditioners speak on **TCP port 56800**. Useful if
you are adding a model, debugging a decode, or driving a unit without Home Assistant.

This protocol is not publicly documented; the description here was worked out independently by
[@enapt](https://github.com/enapt) for interoperability with hardware we own. The document mostly
records what the code already encodes, plus what has been learned since.

## Layers

1. **uSS message** — a 16-byte header plus payload:

   ```
   [0:4]   info_code BE32 = 0xEA60 + info_type  (hello=0, hello_resp=1, hello_done=2, done_resp=3)
   [4:6]   payload_len + 0x0A (BE16)
   [6]     type byte      (pro_ver 2 -> 0x01, pro_ver 3 -> 0x6E)
   [7]     flag           (0 plaintext, 1 encrypted biz-data)
   [8:12]  sn BE32        (client counter from 1; the AC echoes it)
   [12:14] code2 BE16
   [14:16] session BE16   (0 in the client hello; the AC ASSIGNS one in HELLO_RESP)
   ```

   A declared length below `0x0A` cannot be a real frame — the header alone is 16 bytes.

2. **Handshake** (plaintext): client `HELLO` → AC `HELLO_RESP` → client `HELLO_DONE` → AC
   `HELLO_DONE_RESP`, after which the AC pushes status as `0xEAC4` messages.

   `HELLO_RESP`'s payload is `status(BE32) || localkey_version(BE32)`. **`status` must be 1.** A unit
   that answers with a different status has refused the session: it will accept `HELLO_DONE`, push
   nothing, and look exactly like a dead network. The version field is free rotation detection — no
   separate probe connection is needed.

3. **biz-data payload**: AES-128-CBC, IV = 16 zero bytes, key = `MD5(localKey-as-ascii-hex)`. The
   plaintext carries an `sn` and an MD5 integrity check. A wrong or rotated key fails that MD5 on
   every payload — silently, which is why a stale key and an unreadable layout used to be
   indistinguishable.

Sessions are capped at roughly **17 seconds** from the handshake (not an idle timer — a keepalive
does not extend it), and the AC accepts **one local session at a time**. It delivers its whole status
burst immediately and then holds the socket open and silent, so a collector should return on a short
idle window rather than waiting out the full timeout.

## The status report

A decrypted full-status blob is:

```
[0:78]    CAE report prefix   (identical across models; [2:4] == 27 15 identifies it)
[78:80]   inner frame length  (BE16)
[80:]     EPP frame:  ff ff | len | flags | 5 reserved | type | data | checksum
```

The packed attribute vector always begins at **byte 92**, immediately after the `6d 01`
getAllProperty response code. What varies by model is how many grSetDAC **control words** (2 bytes
each) precede the read-only sensor block:

| Report length | Control words | indoorTemperature | outdoorTemperature |
|---|---|---|---|
| 127 bytes | 6 | byte 104 | byte 106 |
| 125 bytes | 5 | byte 102 | byte 104 |

Both satisfy `indoor = 92 + 2 * words` and `outdoor = indoor + 2`, and the trailing block (sensors
plus checksum) is 23 bytes on both — so `words = (length - 115) / 2`. The library uses that closed
form to *read* an unknown layout, vetoed by a plausibility check on the byte it would call
indoorTemperature, but keeps the confirmed table as the allowlist for *writes*: a wrong word count
would send a sensor byte back to the AC as a control word.

Fields at bytes 92–97 are control words 1–3 and therefore sit before anything the word count shifts,
which is why an unrecognised report can still be partially decoded.

### Other wire families (per-model layouts)

The table above is the *classic* family. Some models pack their attributes into an entirely
different layout — not just a different word count, but different words for each attribute, and the
sensors interleaved into the same array rather than in a trailing block. Each such family is a
**wire model**: a per-attribute map of `word` / `bit` / `length` plus the value transforms, kept in
[`wire_models.py`](packages/haismart-hrdp/src/haismart_hrdp/wire_models.py) and selected by uPlusId
(the cloud device-list `wifiType`) or, failing that, by report length — with a plausibility check so
an ambiguous length falls back to the unknown-layout path instead of mis-decoding.

The first such family is **compact-12** (117-byte report, e.g. HSU-12HFMF): a 12-word array with
`indoorTemperature` at word 1, `operationMode` at word 6, `windSpeed` at word 7, swings at word 8,
`onOffStatus` at word 9 and `targetTemperature` at word 12. Its enum values are true EPP indices
(unlike the classic family, whose stored codes equal the Haier STD codes), so the wire model maps
each back to its STD code for the profile to name. Control uses the model's own group-set command
(`4d5f`, vs the classic `6001`), a read-modify-write over the same 12-word array.

The second is **extended-36** (165-byte report, e.g. HSU-12KCROC(IN)-R32, `deviceType 02012036`).
This one is not a different bit map at all: it is the *classic* map **displaced by 19 words**. The
report begins with a voice/media module block (volume, playback, dialect …) that the model's generic
preset describes but a plain split AC leaves inert, and the climate attributes follow it —
`targetTemperature` at word 20 bit 8, `operationMode` at word 21 bit 13, `windSpeed` at word 21
bit 8, the boolean block at word 22, `windDirectionHorizontal` at word 23, `indoorTemperature` at
word 25 bit 8 and `outdoorTemperature` at word 26 bit 8. That displacement is exactly why the classic
*partial* decode misfires on this model rather than simply falling short: byte 92 is the media
block's `volume`, which reads as a 48 °C setpoint.

Its control path is the classic `6001` group-set with the classic five-word bit map — the op is
unchanged; only the *baseline* is sliced from report word 20 instead of word 1. That displacement is
what `WireModel.write_base_word` expresses: where a family keeps its control block in the report is
independent of where that block sits in the op.

> **Future consolidation.** The classic family is currently a bespoke decoder/encoder while the newer
> families are data-driven wire models — two paradigms for the same idea. The plan, once the wire-model
> path has more confirmed models behind it, is to fold the classic family into the registry as one more
> entry (extending `WireModel` to cover its byte-offset sensors, variable 125/127 length, and
> device-specific values such as the swing toggle and the eco level), collapsing to a single
> path. A smaller first step is to extract the shared bit pack/unpack helpers the two paths currently
> duplicate. Both are deliberately deferred so the hardware-verified classic path stays untouched until
> then.

### Confirmed field offsets

| Field | Where | Decode |
|---|---|---|
| `targetTemperature` | byte 92 | `byte + 16` |
| `windDirectionVertical` | byte 93 | bit 3 (`0x08`) = auto up-down swing |
| `operationMode` / `windSpeed` | byte 94 | `byte >> 5` and `byte & 0x07` |
| `onOffStatus` | byte 97 | **bit 0 only** (`byte & 0x01`) |
| `windDirectionHorizontal` | word 4, bits 0–2 | `0` fixed, `7` auto |
| `indoorTemperature` | per layout | `byte / 2` |
| `outdoorTemperature` | per layout | `byte - 64` |

`windSpeed` is masked with `0x07`, not `0x0F`: bit 3 of byte 94 belongs to `specialMode`, so a wider
mask invents a fan code of `speed + 8`.

Byte 97 needs the same care for the opposite reason: it packs **eight** flags, of which on/off is only
bit 0. The rest are health (1), electric heat (2), boost (3), quiet (4), sleep (5), child lock (6) and
buzzer (7). Reading the whole byte reports the unit as on whenever any of those is set.

A unit without a given sensor reports `0`, which the raw outdoor formula turns into a confident
−64 °C. Absent sensors must decode to *absent*, not to a fabricated reading.

## Extended status (running power / compressor figures)

Besides the ordinary status query, units can be asked for an **extended status** report:

```
request   ff ff 0a 00*6 01 4d fe 56          (read-only; changes nothing)
reply     a second report, command word 7d01 — 141 bytes on the classic family
```

The reply repeats the ordinary status words and appends an engineering block. One request therefore
returns *both* reports plus the fault bitmap in a single session, which matters because these units
accept only one connection at a time — the integration folds this into its normal poll rather than
opening a second one.

Confirmed offsets (classic family, 141-byte reply):

| Field | Where | Decode |
|---|---|---|
| power | bytes 126–127 | BE16, watts |
| indoor coil temperature | byte 128 | `byte * 0.5 - 20` |
| compressor discharge temperature | byte 129 | `byte - 64` |
| compressor frequency | byte 133 | Hz |
| compressor current | bytes 134–135 | BE16, `/ 10` amps |
| compressor running | byte 137 | bits 0–1 non-zero |

Two things to know before relying on these:

- **Power is not an independent measurement.** Across every reading observed on one unit it tracked
  the reported current exactly, as `220 x amps + 30` — i.e. it is computed from the current sensor at
  a nominal mains voltage, with a small fixed baseline. Current is the real sensor, quantised to
  0.5 A. Do not treat watts and amps as two independent readings, and do not hard-code the 220: a
  unit on a different nominal supply may well use a different constant.
- **The energy counter in *this* frame is dead.** It has a field for a cumulative watt-hour total,
  and it reads zero on every unit that answers this query and in every reading taken from them — the
  firmware never populates it. So on these units a kWh figure has to be integrated from the power
  sensor host-side rather than read.

  That is a property of this frame, not of the protocol. Another report family carries a counter in
  its **ordinary status report** that does work, and it counts watt-hours — see
  [`docs/report-layouts.md`](docs/report-layouts.md). A counter reading exactly zero is therefore
  best treated as *absent* rather than as a real total: it is the signal that this firmware does not
  keep one.

Not every unit answers the query. One that does not simply refuses this one frame — with a short
reply carrying no data — and still sends normal status, so it is safe to ask unconditionally. The
integration asks once, notes the answer, and stops asking if the unit does not support it.

A session can therefore return three different report kinds sharing the same container: status
(`6d01`), the fault bitmap (`0f5a`, 101 bytes) and extended status (`7d01`). **Tell them apart by the
command word, not by length or arrival order** — the fault frame is long enough to pass a status
parser's length checks and decodes into a plausible-looking powered-off unit with a 16 °C setpoint.

### Escaped bytes

`0xFF` starts a frame, so an `0xFF` occurring *inside* one is escaped as `FF 55`. The two leading
separators are the delimiter and are never escaped; escaping begins after them, and the inserted
`0x55` counts toward the frame checksum.

This shows up in ordinary use: a report whose checksum happens to be `0xFF` arrives one byte longer
than its family's fixed length. Unescape before anything looks at a length, or that report misses
every length-keyed lookup — reads still work, but the write path refuses control on a perfectly good
report and recovers on the next one.

### Fault bitmap

The `0f5a` frame is a bitmap. After the command word come N flag bytes, read as **one big-endian
integer** whose least-significant bit is fault 0 — so the *last* byte carries faults 0–7, the byte
before it 8–15, and so on. N comes from the frame's own length: a unit sending fewer bytes shifts
every position, so it must never be hardcoded.

### Vane positions

Both vane fields are position codes, not bitmasks. Vertical: 0 = fixed, 2/4/5/6/7 = positions one to
five, 8 = auto — reaching the wire as 0/2/4/6/8/10 and 12. Horizontal: 0 = fixed, 3–6 = positions,
7 = auto. Only the auto codes mean the vane is sweeping; testing a single bit also matches the vane
parked low.

Some handset buttons are vane positions rather than separate settings. A "health airflow" button, for
instance, cycles the vertical vane between wire codes 1, 3 and 12 — there is no flag for it anywhere
else in the report. Note it also locks out the ordinary louver control until the cycle returns to
auto, so a unit can appear unresponsive to the position button while it is engaged.

Stepping a unit through every position gives, on the wire: vertical **1, 2, 3, 4, 6, 8** and auto
**12**; horizontal **0, 3, 4, 5, 6** and auto **7**. Vertical **8** is the vane parked pointing down
and horizontal **3–6** are ordinary parked positions — none of them sweeping. Both are worth spelling
out because they are exactly the values a bit test gets wrong: `& 0x08` calls vertical 8 a sweep, and
a plain truthiness test calls all four horizontal positions one.

Watching the louver while stepping the horizontal control gives the physical order — auto, far left,
left, centre, right, far right, back to auto — which matches the published naming of those codes
(3 = far left, 4 = left, 5 = right, 6 = far right, 0 = centre, 7 = auto). The observed wire order is
`7 -> 0 -> 3 -> 4 -> 5 -> 6 -> 7`, so the code set and the naming agree even though the stop the
cycle starts from is not worth relying on.

### One control, several bits

A setting is not always one bit. Health moves **three** together — its own flag plus the two
purification-status bits in the flag word — and they have never been observed apart. The vendor app
sets all three in a single group-set; a unit commanded from its handset sets the other two itself.

Worth knowing before reading a control as a single bit, or writing one: a group-set carries the whole
word block, so a partial write leaves the rest of a multi-bit setting at whatever the seed held.

### Controls that are handset-side only

Not every button on a handset reaches the unit, and the ones that do need not land in the words a
group-set carries. Stepping through a handset's full set shows an **"I feel"** button and the
**timer** leaving the *control block* untouched.

Watching **every** word of the report, not just the control block, neither moves anything.

For **"I feel"** that is structural. The handset has its own temperature sensor and re-transmits its
reading every few minutes so the unit regulates to the temperature where the handset is — but that
exchange is infrared and never enters this protocol. It cannot be read here and cannot be driven from
here; feeding a room sensor to a unit this way needs an infrared transmitter, not a network command.

Worth being precise about what that does and does not mean. It is not that the feature is
undocumented — the manufacturer describes it plainly — but that the infrared side of it has not been
decoded for these units. The equivalent is well understood for several other makes, whose remotes are
known to carry a temperature field; the published descriptions of this one carry no such field for
any of its infrared variants. So this is an open question on a different transport, not a dead end.

The **timer** is different, and worth checking per model rather than assuming. Some units publish it:
`timingPowerOn` and `timingPowerOff` as minute counts (0–1440) alongside a `timingStatus` of
cancel / set / keep. Others, including this one, declare no timer attribute at all — the unit accepts
a timer from the handset and holds the countdown internally, but never reports it. So a timer set at
the handset is invisible here, while a unit whose model declares those attributes could support one.

Both light an icon on the handset, so an owner will reasonably expect them. "I feel" is never
available; a timer depends on the model.

The vendor app does not offer either for a unit like this one, which is worth knowing before hunting
for a command that would expose them: its control surface names neither, and the attribute set it is
driven by contains neither. If an app build ever does show them for a given unit, that would be the
thing to chase — its control surface is served as a resource bundle and can change.

### Turbo and quiet are one control

They occupy separate bits but the unit treats them as mutually exclusive: engaging turbo clears quiet
in the same report, and a handset typically cycles turbo -> quiet -> off through a single button.
Engaging turbo **also parks the vertical vane at centre**, and the vane stays there when turbo is
cancelled.

Both are worth knowing before writing either: a group-set carries the whole word block, so a change
that looks like one bit can leave the unit in a state the owner did not ask for.

### Heat capability

Bit 7 of the byte after the outdoor reading is set on a cooling-only unit. The unit states this
itself on every report, which is a better answer than any model: it is right for hardware nobody has
catalogued and cannot disagree with itself.

## grSetDAC control words

Writes are a **group-set**: the whole word block is sent at once, so it must be seeded from the AC's
own current status or unrelated settings get clobbered. The library seeds from the status the AC
pushes on the op's own connection, so the baseline is always live.

| Field | Word | Shift | Width |
|---|---|---|---|
| `targetTemperature` | 1 | 8 | 8 |
| `windDirectionVertical` | 1 | 0 | 4 |
| `operationMode` | 2 | 13 | 3 |
| `windSpeed` | 2 | 8 | 3 |
| `onOffStatus` | 3 | 0 | 1 |
| `healthMode` | 3 | 1 | 1 |
| `rapidMode` | 3 | 3 | 1 |
| `muteStatus` | 3 | 4 | 1 |
| `silentSleepStatus` | 3 | 5 | 1 |
| `screenDisplayStatus` | 3 | 9 | 1 |
| `windDirectionHorizontal` | 4 | 0 | 3 |
| `ecoMode` | 4 | 3 | 3 |

STD operation-mode codes are drawn from a Haier-wide space, not allocated per model — the tell is the
gaps: a cooling-only unit lists 0/1/2 then jumps to 6, skipping 3/4/5. Known codes: `0` auto, `1`
cool, `2` dry, `4` heat, `6` fan-only. Wind speed: `1` high, `2` medium, `3` low, `5` auto.

**`ecoMode` — confirmed on this model.** Word 4 bits 3–5 are a 3-bit eco/power-limit level with
values `0` off, `5`/`6`/`7` = levels 1/2/3 (the remote labels these **ECO L1/L2/L3**). The encoding
is an enable bit (bit 5) plus a 2-bit level (bits 3–4). It corresponds to the digital model's
`generatorMode`, and it acts as a **compressor current limit** — a higher level caps harder, so the
unit draws less and cools more slowly. This was confirmed live by stepping through the levels and
watching the power and compressor-current readings; see [DEVICES.md](DEVICES.md) for the measured
figures. The codes are confirmed for **this family only** — another model may map the levels
differently, so don't widen the allowlist for a new model without a fresh single-attribute sweep.

## Cross-attribute rules

Some combinations are silently rejected — the AC drops the entire group-set and stays as it was. The
known case is **fan-only combined with fan=auto**; the digital model's `constraints[]` block expresses
this (and, on the reference unit, asks for `windSpeed=3` when entering fan-only). Heat needs no such
rule, confirmed on hardware.

## The families are one map

Every air conditioner packs the same attributes into the same words, at the same bits, with the same
widths and scaling. What differs is only **where the block starts**. The published device models
agree on it completely — same widths, same bits, same order, one whole-word displacement each — and
[`canonical_map.py`](packages/haismart-hrdp/src/haismart_hrdp/canonical_map.py) carries that map,
84 attributes of it.

| family | is |
|---|---|
| classic | the map 19 words earlier |
| extended-36 | the map exactly — its "media block" is the part classic units do not carry |
| extended-46 | the map with a ten-word block inserted at word 25 |
| compact-12 | genuinely different: one attribute per whole word |

So a **new** model's layout is this map at some displacement, which makes the unknown one integer
rather than a field table. See [`docs/new-model.md`](docs/new-model.md): three status captures in
known states are enough to pin it, and the layout prober scores candidates against those states.

## What the device's own model supplies

Onboarding fetches two things about a device and uses both:

* its **shadow** — every attribute with its value range, enums and current value. This is what makes
  the integration self-configuring: which modes and fan speeds a unit really has, what setpoint
  range it accepts, and (for four fields) which extra codes it authorises.
* its **published model** — the same attributes plus the parts the shadow leaves out: `modifiers`
  (which settings the unit ignores in which state, which drives entity availability), `alarms` (the
  fault names those rules refer to) and `constraints` (which settings must travel together).

The second is not fetched by name — the model is looked up in the account's resource service, which
answers with a download URL carrying a build stamp, the file's version and its MD5.

## A second local protocol: UDISCOVERY on UDP `:7083`

Alongside the uSS control path there is a **key-free** LAN protocol. It needs no `localKey`, no
account and no cloud, and one UDP round trip answers three things: which appliances are on the LAN
and at what address, each one's `uPlusId`, and **whether the appliance can currently reach Haier's
cloud**. `packages/haismart-hrdp/src/haismart_hrdp/udiscovery.py` implements it.

### Framing

A 21-byte header in both directions:

| off | size | field | notes |
|---|---|---|---|
| `0x00` | 5 | magic `"Haier"` | validated by the device — a wrong magic gets silence |
| `0x05` | 4 | BE32 command | |
| `0x09` | 2 | BE16 flags | device sends `0x020a`; ignored in requests |
| `0x0b` | 6 | zeros | |
| `0x11` | 4 | BE32 payload length | **not** validated by the device |
| `0x15` | n | payload | |

The only command an appliance answers is **`0x6915`** (search) → **`0x684d`** (device info). Two
other request codes exist in this protocol family — `0x6851` (diagnose) and `0x6853` (biz
transparent-transmission) — but the appliances here are **silent to both**, at every payload shape
tried, unicast and broadcast. They appear to address sub-devices behind a gateway (a class of
hardware this integration does not cover), so they are deliberately not implemented.

The request payload is 56 bytes and the device checks exactly two things in it: the literal `2.0.0`
at `+0x10` and `UDISCOVERY_SDK` at `+0x18`. Zeroing either gets no reply. The 16-byte client
identifier before them is not checked.

> ⚠️ **Broadcast requires source port 7083** — and even then, do not depend on it. Sent from an
> ephemeral port a unicast query is answered but a broadcast one is silently ignored, so `discover()`
> binds `:7083`. But broadcast is unreliable in the field regardless: plenty of access points filter
> or rate-limit it, and units that answer unicast every time can stay silent to a broadcast. Unicast
> (`query()`) is the dependable call, which is why the integration finds a moved unit by ARP/DHCP
> first and treats broadcast as a fallback.

### The `0x684d` reply (309 bytes on the reference family)

| off | size | field |
|---|---|---|
| `0x15` | 16 | deviceId (MAC, ASCII, NUL-padded) |
| `0x25` | 32 | `uPlusId`, **BCD-packed** — hex-encoding reproduces the cloud device list's `wifiType` exactly |
| `0x45` | 4 | BE32 TLV count |
| `0x49` | … | TLV area, records of `type(1) | length(1) | value` |
| `0xe5` | 16 | the device's own IP, ASCII |
| `0xf5` | 2 | BE16 uSS control port (`56800`) |
| `0xfd` | 5 | SDK version |
| `0x105` | 16 | two 8-byte firmware strings |
| `0x115` | 16 | protocol tag `UDISCOVERY_UWT` |

Two TLV types are known: `0x01` deviceId, and **`0x03` cloud state**. Decode by walking the records,
not by fixed offset — the area is a fixed-size region whose populated part varies by device class.

### Cloud state (TLV `0x03`)

Three values have been observed, across a full disconnect/reconnect cycle sampled at 1 Hz:

| value | meaning |
|---|---|
| `1000` | connected |
| `1010` | connection lost, module retrying |
| `1006` | disconnected; held indefinitely while cut off |

**The rest of the code space is unknown.** These are module-firmware values and Haier publishes no
documentation for them, so those three are what has been confirmed — and `1010` is the reason a
decoder must not assume the complement of "disconnected" means connected: for the first two minutes
of every outage the code is neither of the two values originally observed.

Decode defensively as a result: walk the TLVs by type, treat **only** `1000` as connected, and keep
the raw number in an attribute so an unrecognised code arrives as a bug report instead of being
silently flattened into "offline". Enumerating the rest needs sampling a unit at ~1 Hz across a
block/unblock cycle and a power cycle, to catch whatever transient states exist between the two
known ones.

Confirmed on hardware in both directions, and **losing the cloud is not a single step**:

```
1000  --~2 min-->  1010  --~2 min-->  1006        (blocked)
1006  -->  [module silent ~3-6 s]  -->  1000      (restored, ~10 s end to end)
```

Recovery has **no intermediate code**: the module stops answering the discovery query altogether for
a few seconds while its stack re-establishes, then replies `1000` directly. A query landing in that
window gets no reply, which is why "no answer" must read as *unknown* rather than as disconnected.
No byte other than the state TLV changes at any point.

**Latency is asymmetric**: a cut is visible after about **2 minutes** and settles about **2 minutes**
later; a restore takes about **10 seconds**. Poll no faster than once a minute.

Two units on the same LAN moved **3.0 s apart at both disconnect transitions** — the same offset
twice, i.e. a fixed phase difference between their timers rather than jitter.

Two related behaviours are worth knowing: the localKey **does not rotate while a unit is cut off**
(reconnecting is itself a rotation trigger), and the `:56800` read and control path is **completely
unaffected** by cloud loss.
