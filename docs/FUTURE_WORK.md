# Open items

Each is written to be picked up cold: what it is, why it is not done, and what would settle it.
Anything genuinely settled is collapsed to a line or two at the bottom, under **Settled** — kept so
that nobody re-opens it, and pointing at where the detail now lives (a doc, the code, or the git
history).

The numbers are **identifiers, not positions** — items refer to each other by number, so an item
keeps its own when it moves between the two sections. Expect the sequence to have gaps in both.

> **One finding frames several of the items below.** Where an item says a setting "cannot be placed"
> or "needs hardware that declares it", weigh it against this: **almost every product publishes the
> ordered attribute list of its group-set command, and that order is the wire order** — word
> ascending, then bit descending within a word. So a setting's position can often be *derived* by
> anchoring on the settings the shared map already places and fitting the unknowns between them. That
> does not place everything — a list is in wire order only up to a boundary, after which later
> additions are appended out of order — but it places some things once recorded as unplaceable, and
> brackets many more. Count coverage **per family** (compact / central-air / wall-floor describe
> themselves in different formats), never against the shared map alone, or the count understates the
> other families badly.

## Open items

### 63. Issue #13 — a heat-pump WATER HEATER, 167-byte report, and the integration models it as an AC

**Reported 2026-09-09 (issue #13), and it is the best-controlled report this project has had from a
user.** A Haier heat-pump water heater in Taiwan, `product_code GK0GXZE0J`,
`uplus_id 201c120000118674**2001**00418007574800000000000000000000000000000040`. Four diagnostics
downloads with **one variable changed per capture** and ~2 min to settle, plus the reporter's own byte
diff of `last_raw_status`.

**What is wrong today:** the unit decodes as a `climate` entity with cool / dry / fan_only, fan and
swing modes, a 16–30 °C clamp against a real 35–75 °C setpoint range, `current_temperature` null, and
**writes disabled** — the 167-byte report matches no known length (we know 125 and 127).

**The reporter's mapping** (0-indexed into the 167-byte frame), each value cross-checked against the
cloud's `reported_values_now` in the same capture:

| byte | meaning | evidence |
|---|---|---|
| 92 | current water temperature, raw °C | 49,49,49,50 ↔ `currentTemperature` |
| 93 | **target temperature − 30** | 18,25,32,18 → 48,55,62,48 ↔ `targetTemperature` |
| 97 | heat mode: 3 = eco, 4 = dual-source/instant | tracks `oddHotWater` / `dualHeaterMode` |
| 108, 111 | reserve / off-peak temps `resn1`/`resn2`, also (°C − 30) | 0x14→50, 0x2d→75 |
| 95 | clock minutes | 11/18/21/23 |
| 128 | slowly drifting (RSSI?) | — |
| 166 | checksum | varies with everything |

✅ `workStatus` (1 = keep-warm/idle, 2 = heating) is at **word 36 bit 7** — see below. The earlier
line here read *"its byte is not pinned"*; Haier's own map pins it, and it decodes 1/2/2/1 across the
four captures, matching the app.

#### ⛔⛔ CORRECTED 2026-09-13 — THE FETCH HAD ALREADY HAPPENED. WE HELD THE MAP ALL ALONG.

This section read: *"⛔ **We do not hold this one** — `catalogue/configfiles/` has 193 files, all
`201c1200…**0612**…` and friends; the reporter's class field is **`2001`**, a category we have never
fetched."* **That is wrong in both halves.** `catalogue/configfiles/` **and** `catalogue/funcmodels/`
each carry `201c120000118674200100418007574800000000000000000000000000000040` — the reporter's exact
typeid — fetched **2026-09-01** in the same sweep as everything else (211 KB and 81 KB).

⚠️ **The file's mtime no longer shows 2026-09-01 and that is not evidence against this** (checked
2026-09-13, after it briefly looked like one): the configFile was **re-fetched on 2026-09-13**, which
reset it. ★ **The control is the funcModel** — `catalogue/funcmodels/<same typeid>.json` is dated
**2026-09-03** (the funcModel sweep) and has *not* been re-fetched, so the reporter's exact typeid was
in our enumeration **six days before the issue was filed**. The configFile sweep enumerated the same
**194 catalogue typeids** (`catalogue/configfiles/README.md`), and both `2001` typeids came back.
⇒ Do not re-derive this from timestamps alone.

⚠️ **What made it wrong is worth more than the fact:** the claim was a guess at a filename pattern
that nobody enumerated (`METHOD.md` Rule 2 — enumerate a file's keys, never grep for the name you
expect). A class histogram over the directory takes one line and gives **~44 device classes**, not
"`0612` and friends": refrigerators (`0121`–`0128`), air conditioners (`0211`/`0212`/`0214`/`0312`/
`0d12`/`0d21`/`3912`), washers (`0501`), electric water heaters (`0612`/`0616`/`0618`/`0619`/`061a`,
76 files), gas water heaters (`1812`–`1817`), hoods (`0901`/`0902`), sterilisers (`0b11`/`0b12`),
hobs (`1d01`), a TV (`0f01`), an oven (`3e01`), an air purifier (`2101`), a scale (`150e`) — and
**heat-pump water heaters (`2001`, 2 files)**.

**The endpoint is also still live** (re-fetched 2026-09-13, 210,675 B), so on-demand fetch per
typeid remains available and the bundled catalogue is a floor, not a ceiling.

#### ✅ AND HAIER'S MAP DECODES THE CAPTURES — 26/26 PER CAPTURE, INCLUDING THE FIELD THE REPORTER COULD NOT PIN

A generic decoder that reads only `startWord`/`startBit`/`length`/`variants` from the configFile, at
the **same `_ATTR_BASE = 92` word geometry the AC path already uses**, reproduces **every attribute
the cloud mirror reports** — all 26 of them, on each of the four captures. Checkable:
`tools/re/configfile_decode.py --selftest` (parent tree). A sample:

| attribute | config position | capture 1–4 | cloud `reported_values_now` |
|---|---|---|---|
| `currentTemperature` | w1 b8 len8, k=1 c=0 | 49 / 49 / 49 / 50 | ✓ |
| `targetTemperature` | w1 b0 len8, k=1 **c=30** | 48 / 55 / 62 / 48 | ✓ |
| ★ `workStatus` | **w36 b7 len1** | 1 / 2 / 2 / 1 | ✓ |
| `dualHeaterMode` | w36 b6 len1 | false / false / false / **true** | ✓ |
| `oddHotWater` | w3 b0 len16 | 3 / 3 / 3 / 4 | ✓ |
| `resn1Temperature` | w9 b8 len8, c=30 | 50 / 50 / 50 / 75 | ✓ |
| `resn2Temperature` | w10 b0 len8, c=30 | 50 / 50 / 50 / 75 | ✓ |
| `onOffStatus` | w36 b0 len1 | true ×4 | ✓ |
| `runningMode` | w36 b1 len5 | 2 ×4 | ✓ |

★ The reporter's byte numbers fall straight out of the same arithmetic (`byte = 92 + 2×(w−1)`,
`+0` for bit≥8 and `+1` below): w1 b8 → 92, w1 b0 → 93, w3 → 96–97, w9 b8 → 108, w10 b0 → 111 —
the 92/93/97/108/111 of the table above. **Four captures could not establish a frame layout; the
manufacturer's map does, and the captures confirm it.**

⚠️ Scope: **one** unit of **one** `2001` family, cross-checked against the cloud mirror in the same
capture. It does not test the ~230 Properties the cloud was silent on, the `Bigdata`/`7D01` frame
(never captured from this unit), the second `2001` family, or any write.

⚠️ **And the check caught a real bug that a hand-check had passed.** Comparing nine chosen
attributes succeeded; comparing **all** the cloud reports failed on `time`, because for `caeType`
3/4/5 the `variants` list is a **composite part descriptor** (`[{startWord,startBit,length}, …]`),
not an `eppValue` table — read as an enum it silently yields `None`. ★ `caeType` is the
discriminator, and enumerating it over all **22,667** Property+Bigdata fields of the 164 V3
configFiles gives **seven rows with no residue**: 1 and 6 = `raw*k + c` · 2 = enum · 3 = time
`HH:MM` · 4 = time `HH:MM:SS` · 5 = date · 13 = opaque string. ⛔ Only caeType 3 is confirmed
against ground truth (the cloud's `"22:11"` beside parts 22 and 11); 4 and 5 are rendered the same
way by construction and **no capture in the corpus carries one with a cloud value beside it**.

#### ★★★ AND THE SAME DECODER REPRODUCES THE SHIPPED AC DECODER — THREE CLASSES, FOUR LENGTHS

This is the finding that outgrows item 63. The identical config-driven decoder was run against the
stored AC captures with no per-family code at all:

| capture | class | length | result |
|---|---|---|---|
| discord `AAD180E00` | `0212` ext-36 | 165 B | indoor 24.5 · target 24.0 · mode cool · fan high · power on · both vanes · `opSrc` network — **matches the shipped decode field for field** |
| issue #12 ×7 | `0d12` cabinet | 133 B | power / target / mode (cool, dry, fan\_only) / fan (low, medium, high) / indoor — **7/7 captures** |
| issue #13 ×4 | `2001` heat pump | 167 B | the table above — **a class the integration has never decoded** |

**144/144 attribute comparisons, 12 captures, 3 device classes, 3 report lengths.**

⇒ the `canonical_displacement` / `canonical_insert` / `length_inserts` machinery is a hand-derived
restatement of what these files state outright. The 125-vs-127 split, derived here as "one inserted
word", is simply **two different configFiles**: `挂机通用_V2D18S_0D02` puts `indoorTemperature` at
byte 102, `共享空调_V2D18S_0D07` (the rental SKU) at byte 104 — both hardware-confirmed numbers.
⚠️ Scope: three classes, three report lengths, twelve captures — **not** the 125-byte classic
(no stored capture carries one) and not any `Bigdata`/`7D01` frame. It is not a claim that every
configFile is correct for every unit, and the absent-probe rule (`outdoorTemperature` raw 0 →
−64 °C) still has to be applied on top — `_sensor_temp`'s job, which the generic reader does not do
for free.

**The larger ask, stated plainly:** #13 request 3 is *"support heat-pump water heaters, not only air
conditioners."* That is a **new platform** (`water_heater`), not a new layout — a real piece of work,
and the first appliance category outside AC this integration would carry. The owner's call whether
that is in scope. ⓘ Nothing about it is blocked: the wire is the same uSS/`:56800` path we already
speak, and the localKey already works (the reporter has a live entity).

#### ✅ SHIPPED 2026-09-13 — and it grew into support for every appliance category

⇒ **The full account is `docs/MULTI_DEVICE_PLAN_2026-09-13.md` in the development tree.** Beyond the
`water_heater` platform below, what shipped is a generic layer that gives **any** appliance its
entities from its own declaration and Haier's published byte map: 165 device classes bundled, any
other fetched on demand, and every field classified into a switch / select / number / sensor /
binary sensor with the units, ranges, options and English name the manufacturer's data supports.
Validated on a washing machine from prior art that nobody here owns, and swept across all 36 classes
with `tools/re/simulate_appliances.py`.

⛔ **Not shipped, deliberately — each is its own open item below: group-command writes (64) and the
V2 text profile (66).**

#### ✅ SWEPT 2026-09-13 — and the sweep found four defects nobody could have reported

Checked against Home Assistant's own `DEVICE_CLASS_UNITS` and `DEVICE_CLASS_STATE_CLASSES` rather
than a table copied out of them, and then by setting up a real config entry for **every one of the
36 classes** and reading what came out:

* **203 sensors** paired `device_class: volume` with `state_class: measurement`, which Home
  Assistant refuses at write time — `volume` is a meter total and a tank's contents is
  `volume_storage`. The two are now derived together, as a pair, valid by construction.
* The **same attribute carries `ug/m³` on some classes and `ug/m3` on others** (96 fields against
  52). The unit decides the device class, so the spelling silently cost **17 classes** their
  air-quality classes. Units are normalised once, before anything is classified.
* **Ambiguous units were read as semantics**: a formaldehyde probe was labelled "PM2.5" and a
  carbon-monoxide probe "CO₂", because `µg/m³` and `ppm` each cover several gases. The name now
  disambiguates, and where it cannot the reading keeps its unit and gets no class.
* **`resnMode` publishes a single value** and had become a switch — an off position `encode_write`
  refuses, i.e. a control that fails the first time it is used.

All four are now permanent tests: every spec of every class against Home Assistant's constants,
every control checked for a usable range or option set, every writable spec round-tripped through
the encoder at both ends of its range, and a real entry per class asserting no log complaints, a
serialisable diagnostics download and a clean unload/reload.

#### ✅ the `water_heater` platform itself

`water_heater.py`, plus the two layers under it that were the real work:

* **`haismart_hrdp.device_model`** — Haier's published byte map for 165 typeids across 36 device
  classes, bundled at **133 KiB gzipped**, generated by `tools/re/gen_device_models.py`. Decoding an
  appliance stops being a hand-transcription job.
* **`haismart_hrdp.appliance`** — what KIND a device is, from its typeid's class field first and the
  cloud's `appTypeName` second, and `OTHER` where neither settles it. Platforms are now forwarded
  **per entry**, so a water heater gets no thermostat.
  ⚠️ With a no-regression clause that matters: a device of an unknown class whose report really
  *does* decode as an air conditioner keeps its climate entity, because some working installs are in
  exactly that state.
* Writes go out on the `5Dxx` single-parameter channel, validated against the unit's own model
  (35–75, not the class-wide 30–80) and refused before the wire for anything the map does not name.
* The unknown-layout repair is no longer raised for an appliance the byte map decodes, and its
  wording is no longer air-conditioner-specific.

⛔ **Not confirmed on hardware: any write.** No byte has been sent to this appliance. The reporter's
control is disabled today, so the first write is theirs to make, and it must be read back.

#### ✅ BUILT AND PROVEN END TO END ON REAL HAOS (2026-09-13) — branch `feat/every-appliance-category`

All three blockers are closed: ~~(1) the configFile + funcModel~~ ✅ held and validated (above);
~~(2) the `water_heater` platform decision~~ ✅ **built**; ~~(3) a `workStatus` byte~~ ✅ **w36 b7**.

★★ **The decode is cross-checked against Haier's OWN cloud, not against our decoder.** Each of the
reporter's four downloads also carries `reported_values_now` — the live device shadow fetched from
`uws-sgp.haieriot.net/shadow/v1/devdigitalmodels` while the file was written, independent of our byte
map. **26 of 26 attributes agree on all four captures — 104/104, zero disagreements, zero unplaced.**
⚠️ Compare against `reported_values_now`, **never `reported_values`**: the latter is the model stored
at onboarding and is identical across all four files (it reads `targetTemperature 48` and
`time 21:59` even in the capture where the setpoint is 62) — using it scores a spurious 91/104.

**⟦LIVE⟧ Verified on the owner's HAOS box** by serving the reporter's own captured report back over
uSS to a fake entry: **27 entities**, `water_heater.…` = `Instant heat`, min 35.0 / max 75.0,
current 49.0, target 48.0, the 8 declared modes + off; `workStatus` = `Keep warm`;
`hot_water_remaining` = 3 L (`volume_storage`); `dual_heater_mode` switch = off. Box then restored to
its 54-entity baseline.

**The entity set this unit actually generates** — ⛔ **corrected 2026-09-13; an earlier draft of this
item predicted switches and numbers for the reservation fields and that is wrong.** The declaration
gate leaves only **5** attributes writable (below), so the reservation fields are read-only:

* `water_heater` (hero) — `currentTemperature`, `targetTemperature` (**35–75 °C from the device's own
  declaration**, not the configFile's class-wide 30–80), `onOffStatus`, `runningMode` as the
  operation list: 8 of the class's 19 modes (即热 · 动态夜电 · 预约1 / 预约2 / 预约1+2 · 中温保温 ·
  Eco除菌 · 随温而动).
* **1 switch** — `dualHeaterMode` (the only writable non-hero attribute).
* **15 sensors** — `workStatus` (保温/加热), `oddHotWater` (L, `volume_storage`), `resn1`/`resn2Temperature`
  (°C), the reservation and valley-period times, `heatModeMaxTemp`, `pumpModeMaxTemp`, `time`.
* **6 binary sensors** — `resn1`/`resn2` running, cycle and result flags.
* 32 alarms from the configFile, named from the device's own model.

**Writes are single-parameter `5Dxx`** — the mechanism `0d12` already ships. ★ **The class map
publishes 16 ids, but this unit declares only 5:** `onOffStatus 5D00` · `targetTemperature 5D01` ·
`time 5D02` (composite ⇒ stays read-only) · `runningMode 5D04` · `dualHeaterMode 5D05`. The other
eleven (`holidayLength 5D03`, `3dSetting 5D06`, `sterilizationMode 5D07`, `maxFluxMode 5D08`,
`zeroColdWaterBookMode 5D09`, `tankWaterLevel 5D0A`, `sparklingWaterStatus 5D0B`,
`smartPressurizeStatus 5D0C`, `quickWash3D 5D0D`, `zcwTimingCycleStatus 5D0E`, `fcMode 5D0F`) are
features this model does not declare and are **not offered**. ⛔ An earlier line here listed
`sterilizationMode`/`maxFluxMode` as if they applied to this unit — they do not.

⛔ **Still unverified on hardware: any write.** No byte has ever been sent to a heat-pump water
heater. The first write must be self-verifying and read back, as every other class was.

▶ **Reported to the reporter 2026-09-13** — issue #13 comment `5651939563`: what was found, the byte
positions including `workStatus`, the 104/104 cross-check, the 35–75 range, the four control ids, and
the explicit ask for a read-back on their first setpoint write. ⛔ The group-written reservation
**times** are called out there as deliberately read-only (see item 64).


### 67. The two decode paths apply DIFFERENT plausibility bands to the same reading

Surfaced 2026-09-13 while building `haismart_hrdp.ac_view` to compare the two decoders. A sensor
temperature is vetoed as implausible by a band, and there are two of them:

| path | constant | band |
|---|---|---|
| the classic family, via `uss._sensor_temp` | `uss._PLAUSIBLE_TEMP_C` | **−70 … 150 °C** |
| every `wire_models` family (ext-36, ext-46, compact-12, `0d12`) | `_PLAUSIBLE_SENSOR_C` | **−30 … 70 °C** |

⇒ **An outdoor probe reading 100 °C is published by one path and dropped by the other, on two air
conditioners, today.** Neither is wrong on its face — the wider one admits a discharge-line
temperature, the narrower one is right for ambient air — but they are applied to the *same*
attribute on different families, which nothing states and nothing tests.

⚠️ **Not fixed here, deliberately.** `ac_view` reproduces both, per family, because its job is to
show what ships; a flip that also changed a band would make any regression unattributable. Fixing it
is a behaviour change for real units and belongs on its own, with the oracle and the stored-capture
regression behind it.

**What closes it:** decide which band an ambient sensor should have, apply it in both paths, and run
the oracle plus `tools/re/decoder_equivalence.py` over every capture. ⓘ No capture on disk contains
a reading in the disputed 70…150 °C range, so nothing observed is affected — this is latent.

### 64. Group-command writes are decoded but not offered — no capture of one exists

A water heater's reservation times, a washing machine's programme settings and a fridge's zone
setpoints are not written one parameter at a time. Haier publishes them as an `Operation`: a frame
type, an EPP command and a list of `(name, startWord, startBit, length)` making up that op's own
word array — `grSetResn1` on issue #13's heater, and eleven more on it alone.

Everything needed to build one is in the map, and the integration reads those attributes today. It
does not offer them as controls, and that is a decision rather than an omission.

**Why.** The two write mechanisms are not equally forgiving. A single-parameter write names its
attribute in the command and carries the value in the payload: a wrong id is refused with a NACK we
can see, and nothing else moves. A group set packs a whole word block and the appliance acts on all
of it — so a layout that is wrong by one word sets several settings at once, silently, and the unit
has no way to tell us. On a gas water heater or a washing machine that is not a trivial mistake.

⛔ **And there is no validation available.** No capture held by this project or found in prior art
contains a group op being *sent* to a non-air-conditioner. The washing machine capture is a genuine
both-directions UART tap and the only writes in it are `4d01` status queries. The air conditioners'
`grSetDAC` was confirmed on hardware, which is exactly the evidence these lack.

**What closes it:** one capture of a group op on the wire for any non-AC appliance — a UART tap, or
a diagnostics download taken immediately after setting a reservation in the Haismart app, which
would leave the op in `lan_frames`.

### 65. A board can wipe its module's Wi-Fi configuration

*(see `CLAUDE.md`; the `FD` 清除用户信息 field — a board that sends it takes the unit off the LAN and
the integration sees the appliance vanish.)*

### 66. Ten device classes are published only in the older V2 text profile

`catalogue/configfiles/` holds 191 maps, of which 27 are not JSON but Haier's older text profile:

    [冷藏显示温度]^601001#1&1,-38@!&!,!#6d01,1,8,8$

It carries the identical four numbers — statusCmd, word, bit, length — plus the scaling, so decoding
is not the problem. **Naming is.** The format keys its fields by a Chinese label and a base-36
attribute id (`601001`), while the declaration gate speaks the digital model's English attribute
names (`refrigeratorTemperatureC`), and this project holds no bridge between the two. `ATTR_IDS` is
a different id space and was checked: none of those ids appears in it.

⚠️ Ten classes have **only** V2 members — `0101 0102 0104 0202 0401 0502 0601 0602 0903 1801` — plus
a minority of `0121` (fridges), `0501` (washers) and `0612` (water heaters). A device of one of
those gets no byte map and falls back to exactly the behaviour it had before any of this existed.

ⓘ It is probably smaller than it looks: those typeids are the 2019-era ones bundled in the app, and
the on-demand fetcher asks for V3 first, so a current device of the same category would most likely
be served a V3 map under its own typeid.

**What closes it:** a label→name mapping (the panel resources may carry one), or one live device of
those classes whose typeid does serve V3 — which would show the whole question is historical.

### 58. The end-anchored telemetry decode assumes a tail block — five published families put it elsewhere

`parse_extended_status` has two paths. A frame whose word count matches a family in `BIGDATA_MAPS`
(20, 21, 23, 43 words) is read from the manufacturer's own field map. **Anything else at least 141
bytes long is read END-ANCHORED**: the engineering block is assumed to sit at the tail, and every
offset is derived from the frame's own length (`shift = len - 141`).

That assumption is well-evidenced for everything it has met — the classic 141-byte wall units and
the `0d012` cabinets at 147 bytes carry the identical block six bytes further along, confirmed
across three captures on the issue #12 cabinet. The comment in the code says exactly that, and it is
true of every family **confirmed on hardware**.

The manufacturer's own byte map now supplies counter-examples. Five families place telemetry
**after** the engineering block:

| family | engineering block ends | frame runs to | words after the block |
|---|---|---|---|
| `…0212…1330…` 挂机通用 0D16 光伏 海外 | word 64 | 77 | **13** |
| `…0212…1774…` 挂机通用 0D16 光伏 | word 64 | 77 | **13** |
| `…0312…204042…` 柜机通用 0D17 光伏 | word 75 | 88 | **13** |
| `…0d21…189448…` 柜嵌通用 0D14 光伏 | word 61 | 74 | **13** |
| `…0212…1597…` 南亚光伏挂式空调2022 | word 23 | 30 | **7** |

What sits after it is photovoltaic telemetry — `accumulatedUseMainsPower`,
`accumulatedPhotovoltaicPower`, `pvInput`, `realTimeTotalPower`, `realTimeTotalPowerStorage` — all
carrying `statusCmd 7D01`, so they are part of the same big-data frame. For comparison, both
families the generator was built from end their engineering block one word before the frame ends
(42 of 43, 22 of 23): genuinely at the tail.

#### The declaring set is EIGHT families, not five — and the three extra ones are SAFE (swept 2026-09-08)

The five above were found by reading the families already suspected. A sweep of **all 191
configFiles** for PV/solar field names (`pv[A-Z]`, `photov`, `solar`, `光伏`, enumerated over
`Property`/`Bigdata`/`changeParas`/`Alarm`/`Event` rather than grepped for an expected name) finds
**eleven** families mentioning PV at all: eight declaring PV **telemetry**, plus the unobserved 商空
`0d12` family (`…0d122151860b57…`) which declares PV **alarms only**, and two `1d01` families whose
only hit is `pValveErr` — a proportional-valve fault, a false positive on the pattern.

The three newly-found telemetry families do **not** extend the risk set, because each ends its
`Bigdata` map **on** `expansionValveOpenDegree` and puts its PV words *before* the engineering block:

| family | `expansionValveOpenDegree` at word | last Bigdata word | words after the block |
|---|---|---|---|
| `…0212…1675…` | 29 | 29 | **0** — safe |
| `…0d21…1916…` | 31 | 31 | **0** — safe |
| `…0212…1890…` | 48 | 48 | **0** — safe |

⇒ **the at-risk set stays exactly the five in the table above**, now positively confirmed rather than
assumed complete. The 商空 `0d12` family is also safe on this axis (block ends at word 27 of 27),
though it remains divergent for the reasons in item 13.

⚠️ Scope: this is a statement about **what the configFiles declare**, not about hardware. It cannot
say whether any such unit exists in the field or would return its full declared block.

**The risk, stated no more strongly than the evidence supports.** If one of these units returns a
big-data frame carrying its full declared block, its word count is not a `BIGDATA_MAPS` key and its
length is well over 141, so it takes the end-anchored path — and `shift` would be 13 words (26
bytes) too large. Power and current have plausibility ceilings that would reject some of the
resulting nonsense, but **`compressor_frequency_hz` has no such veto** and would report whatever
byte lands there. That is the failure this decoder is otherwise careful to avoid: not missing data,
but confident wrong data.

**It is not known to fire.** No unit of these families has ever given us an extended report. There
is one capture from `…1774…` (issue #6), but it predates the frame-keeping diagnostics and carries
no `7d01`. So this is a latent risk with a named test, not an observed defect.

**What would settle it:** one diagnostics download from any 光伏 model with the compressor running —
`lan_frames["06/7d01"]` present. If its payload is 78 words, the end-anchored path is wrong for it;
if the unit sends a short block instead, the convention holds and this item closes.

**The cheap guard, if it is wanted before that arrives:** the configFile says, per family, whether
anything sits after the engineering block. Restricting the end-anchored path to lengths already
confirmed (141 and 147), or consulting that fact, both close it without inventing a layout. Neither
is done here: changing decode behaviour is a gated change (the oracle sweep and the stored-capture
regression), and no user is known to be affected yet.

⚠️ Note also that the PV telemetry itself is **not shipped and should not be shipped blind**: the
one real unit of these families whose model we hold (issue #6) declares 82 attributes and **none of
the PV names are among them**, so entities built from the byte map alone would be phantom — the same
trap the declaration gate exists to prevent.

### 57. Half-degree setpoints — the register is known, what asserting it MEANS is not

Reported by the owner of a `0d12` roof cabinet: the unit's remote sets 24.0, 24.5, 25.0, while the
integration steps in whole degrees. The step comes from the appliance's own model
(`targetTemperature` `dataStep.step`), and the climate entity rounds a requested temperature to a
whole degree before encoding it.

**There are two half-degree mechanisms, and the manufacturer's byte map says which product uses
which.** Either the setpoint field itself counts halves (`k = 0.5, c = 0`, i.e. °C × 2 — this is the
209-byte family's encoding, already shipped, and 33 catalogued products declare `step: 0.5` that
way), or the setpoint stays whole degrees (`k = 1, c = 16`) and a separate flag,
`halfDegreeSettingStatus`, carries the half. No product declares both. The `0d12` cabinets and the
classic families are the second kind.

**On `0d12` the flag has its own single-parameter command.** The manufacturer's configuration for
both `0d12` families gives `halfDegreeSettingStatus` word 3 bit 10, `eppCmd 5D08`, writable — and the
funcModel makes it `writeType: I`. That is unusual and worth stating precisely: of the 19 device
families whose funcModel carries this attribute at all, **only the two `0d12` families make it
individually settable; the other 17 are group-only**. `0d12` is the class whose firmware refuses the
group set, so the individual channel is the only one a control could use there.

The position is agreed by four independent sources — the configuration, the vendor's own `0D012`
UART document (its 附录D command table puts it at Byte5:Bit2, which is word 3 bit 10), the public
`0D012` template, and prior art's byte map, whose eight bits of that word match the configuration
8 of 8. The same UART document enumerates `targetTemperature` as fifteen whole-degree codes
(16 °C … 30 °C) while enumerating halves elsewhere (`indoorTemperature` steps 0.5 °C), so on this
class the flag is the only place a half degree can live.

**What the wire shows.** Across every hON status report in the prior-art corpus — 598 frames — the
flag is set in 7, all from one cabinet, and that cabinet is a `0d12`. The other 591, from the
residential families, read 0. Every report this project holds reads 0. And the class splits: a
second `0d12` cabinet refuses `5D08` outright, which its board reports as a command its control
handler will not accept — that cabinet will not do halves whatever the flag means.

⛔ **The blocker is semantic, not mechanical.** Every manufacturer surface documents this attribute
as on/off and nothing more. The only statement anywhere of what asserting it does is prior art's
implementation, which treats it as the setpoint's fraction: write the whole degrees and set the flag
when the remainder is half, read the setpoint back as `value + 16 + 0.5 × flag`. If instead the flag
merely enables a half-degree mode on the panel, the half never reaches the wire and no honest 0.5
setpoint is possible on this class. The provisional-control mechanism does not close that gap: it
retires an id on a refusal or an unmoved read-back, but under the mode-enable reading the flag reads
back set and the integration would show 24.5 for a unit sitting at 24. A wrong setpoint is not
something to ship.

**What settles it — one report, no code.** Set a half degree on the unit's remote, leave it, then
download diagnostics: the status frame is kept whole, and word 3 bit 10 is the answer. The flag set
while the setpoint byte still reads the whole degree is the fraction reading, and confirms that
cabinet has the function. The flag clear while the unit's own display shows the half means the half
lives in the controller. Worth asking what the unit's display shows, since a two-character display
rounds it away either way.

#### ▶ THE REPORT ARRIVED 2026-09-08 — and the test did not register. Item stays OPEN.

@nutkkc sent three diagnostics downloads from his `0d12` cabinet (`AE2C52Q00` / `HCFI-38XTR32F`,
module `e_4.6.21 / R_6.0.01`), named `24.5` / `25` / `25.5`, taken on v0.69.1. He set the values
**on the remote**, which offers 0.5 steps. They are in the parent tree as `24.5.json`, `25.json`,
`25.5.json`.

**What the wire says — the flag never moved, and neither did the setpoint.**

| download | setpoint code (w1.b8) | `halfDegreeSettingStatus` (w3.b10) | decoded |
|---|---|---|---|
| `24.5` | 9 | 0 | 25.0 °C |
| `25` | 9 | 0 | 25.0 °C |
| `25.5` | 9 | 0 | 25.0 °C |

A bit-level diff of **all four frame kinds** across the three captures shows only outdoor
temperature (100 → 99 → 99, i.e. 36 → 35 °C), two outdoor probes in the `7d01`, and the checksums.
`04/0f5a` and `02/6d01` are byte-identical. The captures are live and fresh — poll counts advance by
three between files and outdoor temperature moved — so a change that had landed would be visible.

**This is not "the half was dropped".** Under the mechanism above, 24.5 is code **8** + flag 1 and
25.5 is code 9 + flag **1**. Neither the code nor the flag moved, and no rounding rule sends 25 for
both 24.5 and 25.5 (24.5 truncates to 24; 25.5 rounds to 26). The board's setpoint simply did not
change during the exercise.

**Controls, so the conclusion is not just "nothing happened".**

* No integration write occurred: `02/6d01` (the control-session reply) sits at **35 in all three**,
  and `controls.last_control` is an earlier HA write of `targetTemperature: 9` at 06:51:56 UTC.
* He could not have used Home Assistant anyway — his resolved profile is **`temp_step: 1.0`**.
* He could not have used the app either: the app-facing model in his own diagnostics carries 12
  attributes, `targetTemperature` is `STEP {min 16, max 30, step "1"}`, and
  **`halfDegreeSettingStatus` is absent from it entirely**. (Note `indoorTemperature` *is* `step 0.5`
  there — the app shows halves for the *reading*, which is a plausible source of confusion.)
* Independent third witness: the cloud's own live mirror, `digital_model.reported_values_now`
  (a fresh fetch — it differs from the cached `reported_values` on `windDirectionHorizontal`), reads
  `targetTemperature: "25"` in all three.

⇒ three independent paths — LAN status frame, LAN telemetry frame, cloud REST mirror — agree the
unit sat at 25.0 throughout.

**Two readings survive, and this capture cannot separate them.**

1. **The handset's .5 is display-local** — it transmits only on whole-degree crossings, so stepping
   25 → 24.5 → 25 → 25.5 sends the board nothing it acts on.
2. **The remote was not registering on the board at all** during those windows.

`opSrc` reads **3 = network** in all three (`{0: other, 1: remote, 2: panel, 3: network}`), i.e. the
last change the board *recorded* was HA's earlier write. That **rules out a wall panel having set it
and the board accepting it** (that latches 2), but it does not separate 1 from 2: `opSrc` only moves
when a change is accepted, so a handset command treated as a no-op leaves it at 3 either way.

**Corroborating scope — the flag has never been observed set on this hardware.** A sweep of every
stored diagnostics file found **21 `0d12` captures** (133-byte frames, all `AE2C52Q00`), spanning
months and setpoints 20/21/22/24/25 °C: `halfDegreeSettingStatus` reads **0 in every one**. Word 3
itself is populated in those frames (`0x0201` — `screenDisplayStatus` 1, `onOffStatus` 1), so that is
a real zero in a live word, not an unread region. ⚠️ **Bounded:** one product code, one module build.
And the sweep's word origin (`byte 112 = outdoorTemperature`, hence word 0 at `len − 43`) is valid
**only for the 133-byte `0d12` frames** — it self-validates there because the decoded setpoint matches
each capture's filename, but applying it to the 117/165/175/209-byte families in the same corpus
produces garbage, and any `half=1` printed for those is a wrong-offset artefact, not evidence.

**⛔ Do not write down "the half never reaches the wire."** That is a negative stated past its
evidence: it requires the whole-degree part to have been dropped too, which nothing here explains.

**What settles it — one more download, and it is cheaper than the first.** Ask him to set a plainly
whole-degree change on the remote, **25 → 28**, wait a minute, download again.

* Code 9 → 12 ⇒ the remote does reach the board ⇒ reading 1 is confirmed, the half never leaves the
  handset, and the 0.5 step must not ship on this class.
* Code still 9 ⇒ the remote is not registering at all, and the half-degree test has to be re-run.

Worth asking alongside, since either could settle it without another download: **what is he actually
holding** — a wired wall controller, an IR handset, or both — and does the **indoor unit's own
display** show the .5, or only the handset? If only the handset shows it, that is reading 1 outright.

**If it confirms**, every piece is already positioned: the flag has a read position on the shared
frame and a write position in the published group-set order (559 of 1,451 products carry it there,
528 of them the classic wall splits, though 554 of the 559 mark it invisible), and on `0d12` the
coordinator already splits a multi-attribute change into separate single-parameter commands. The
step would become a property rather than a fixed attribute, 0.5 only where the flag is usable — and
it must fall back to whole degrees when a provisional control retires, or a user is left with a
half-degree dial whose halves round away silently.

#### ⚠️ A defect this turned up, independent of the flag

The 33 products whose model declares `targetTemperature` `step: 0.5` already get a half-degree step
in the UI, because the step is read straight from the model — while the write path rounds the value
to a whole degree. Those units offer a step the write cannot express. The fix is either to encode
the half (their setpoint field counts halves, so it can carry it) or to clamp the advertised step to
what the encoder can send; the first is correct and needs one capture from such a unit to confirm the
field is written the way it is read.

### 56. The single-parameter register is CLASS-WIDE — the funcModel is the per-family witness

The 2026-09-03 funcModel sweep (`catalogue/funcmodels/`, 164 families, 36 classes) showed the
single-parameter write mechanism the project ships on `0d12` — `CONTROL + 0x5D00|id` — is **not a
`0d12` special case**. Almost every AC class declares `writeType: I` attributes with an `eppCmd`, and
**every class's ids sit on the same `5D` command page** (checked across all configFiles). So the
addressable single-parameter surface spans most families; today we exploit it only on `0d12`.

**What is witnessed vs what is not.** Haier's funcModel states, per family (per uPlusId), which
attributes are single-parameter writable (`writeType` containing `I`). It is a **declaration, an
INPUT** (METHOD Rule 40), not a hardware outcome. Support is per-uPlusId: within one class some
families are `I`-rich and some are **G-only** (group-set only).

★★ **Live probe (2026-09-03) — CONFIRMED board-predictive PER ATTRIBUTE.** The three-way split
matters: across the 26 AC families, **12 are I-capable** (a full single-param register), **12 mark ONLY
`onOffStatus` `I&G`** (single-param power, everything else `G`), and **2 are truly G-only** (the window
units). The owner's family (`…02120011801256…`, 共空 0D07) is in the middle group: every attribute `G`
**except `onOffStatus` (`I&G`)**. TWO live no-op probes of it, on the OFF Upstairs unit, settled it
cleanly:
* `0x5D02` (**setpoint — funcModel `G`**) → **REFUSED, frame `0x03`, code `0x0000`**.
* `0x5D01` (**onOffStatus — funcModel `I&G`**, value 0=off, its current state) → **ACCEPTED, frame
  `0x02` + a status report, no refusal**; unit stayed off.
⇒ The board implements the `5D` page **SELECTIVELY, exactly as the funcModel `writeType` says**: it
accepts the `I&G` attribute and refuses the `G` one, ON THE SAME UNIT. So `writeType` predicts board
behaviour **per attribute**, not merely per family — the strongest validation yet for offering
single-param strictly by the funcModel. (The `0x0000` on `5D02` meant "no single-param for THIS
attribute", NOT "no `5D` page" — an earlier reading, now corrected.) Unit left off/23, unchanged.
⚠️ Practical caveat: the 12 middle-tier families already control power via the **group-set**, so
`5D01` single-param power is redundant THERE; the finding's value is the validated `writeType`→board
link, which raises confidence for the 12 **I-capable** families whose `I` attributes have no group-set
alternative. (Probe pattern: `async_send_op` a `build_epp_frame(0x01, 0x5D00|id, value)`, read
`epp_frame_type` — accept `0x02` vs refuse `0x03`.)

**Why not shipped for other families.** (1) `writeType: I` is unconfirmed on hardware for every non-
`0d12` family — the write is only proven on `0d12` (prior-art issue #19 + a reporter). (2) Read-back /
self-settling needs each family's report layout worked out, which is done for only a few families.
(3) The owner's units are classic G-only and cannot exercise it. Shipping unverified single-param
writes wholesale across dozens of families would violate Rule 8 ("the unit is the only authority on
writes").

**What would settle it, per target family:** a live single-param probe (tooling exists) on a unit of
that family, OR a reporter's capture of the vendor module's own single-param traffic (the issue
tracker is the capture corpus), then ship provisionally + self-settling exactly the way the
four-sided louvres do on `0d12`. Tooling: `tools/re/fetch_funcmodel.py`, `sweep_funcmodels.py`, `funcmodel_coverage.py`;
standing gate `tools/re/validate_configfile_register.py` check 6 (shipped ids must be `writeType: I`;
a declared+writable+positioned attribute left unshipped FAILS). For `0d12` itself the register is
COMPLETE against declarations — no gap but the already-deferred `ampereControl` (item unchanged).

### 1. Vane positions on a unit whose model understates it

Both axes offer their positions as `select` entities beside the swing controls, built from the stops
a unit's own model publishes.

The up-down axis needs a translation, because a model numbers its stops differently from the wire.
That table is **read from the published map**, which carries the vendor's own code table for this
attribute, rather than written out by hand — so it covers every stop the vendor defines, including
the health-airflow positions and the second auto that a wall unit does not have but a cabinet does.
The stops one unit was stepped through on hardware, capture by capture, are kept beside it and the
suite checks the map still agrees with them: taking a table from a generated source is only safe
while that source agrees with an observation.

⚠️ **Why it is read rather than written:** every consumer of this table filters against its keys, so
a stop the table omits is not written wrongly — it disappears, from the authorized set and from the
select's options alike. A hand-written copy that covered one unit's stops silently cost **86
products** the three positions their models declare and it does not.

What is left is only the case where **a model publishes less than the hardware has.** The reference
units are exactly that: their handsets step the up-down vane through six stops, but their model lists
only `0` (fixed) and `8` (auto), so nothing authorises the six, and they get no up-down select. No
map can settle this — it is not a question of where the field is or what its values mean (both
known), but of what a *particular* unit accepts, which only that unit answers: a recorded command
carrying a position on hardware whose model does not list it.

### 2. Health writes one bit where the vendor app writes three

Toggling Health moves three bits together — its own flag plus the two purification-status bits — and
they have never been observed apart. Our encoder maps `healthMode` to its own bit alone. A unit
commanded from its handset sets the other two itself, so a single-bit write most likely suffices.
That is an assumption. One write from our side, with the report watched, settles it.

### 3. Self-clean reporting on the 209-byte family

Shipped on the classic, 165/175-byte and (this round) 117-byte families; still open on the 209-byte
family alone, because that family's ten-word insert point is not pinned and the flag has two
candidate homes.

What its captures confirm: w20/w21/w22 (setpoint, mode, power) unmoved; w35/w36 (indoor, outdoor)
+10; w25 a vane and w26.b9 the fan, both inside the inserted block. So the block starts after w22 and
at or before w25 — and w23, w24 or w25 place canonical w24 at report w24 or w34, disagreeing. Indoor
temperature cannot separate them (all three predict canonical w25 → report w35) and every capture
reads w23/w24/w33/w34 as zero, because nothing was switched on.

**What settles it is cheaper than catching a self-clean cycle.** Any capture from that family with
*any* w24-block feature on — Health, ambient light, fresh air — pins the insert point, because
exactly one of w24 / w34 will be non-zero, placing the whole flag block at once.

### 5. A timer, on units that publish one

Some units declare `timingPowerOn` / `timingPowerOff` (minute counts, 0–1440) and a `timingStatus`
of cancel / set / keep; **161 products declare all three.** So the attributes are common and a
reporter carrying them is likely rather than hypothetical — a timer entity would be the first in this
ecosystem.

What is missing is their **position**, and the published order does not supply it: on every model
that declares them they sit in the appended tail of the group-set list, past the point where the
list stops being wire order. A single report from a unit with a timer set, against one with it clear,
places all three at once. (The 175-byte family was checked — issue #8 — and declares no timer at all;
its app timer is server-side scheduling, and two captures differ only in the live power/energy words.
So that family cannot get a timer entity, and this waits on hardware that declares the attributes.)

★ **Checked properly 2026-08-25, and the negative is real — with two things worth knowing.** No
`timing*` attribute of any spelling appears in **any** of the eight bundled air-conditioner
descriptions (searched whole-file, not just the sections a map is generated from), so the position
cannot be inherited from a relative either.
⚠️ **The two corpora spell it differently**, which is exactly how a search like this returns a false
negative: the product catalogue says `timingPowerOn` / `timingPowerOff` (minute counts), while the
descriptions that *do* carry a timer — none of them air conditioners — say
**`timingPowerOnHH` / `timingPowerOnMM`**, hours and minutes as **separate one-byte fields**.
★ So the prediction for the first air conditioner that reports one is **two bytes, not a minute
count**. Anyone testing this should look for the pair before concluding the attribute is absent.

### 6. The energy total on the families that are not yet trusted for it

The cumulative register counts **watt-hours**, settled on the 165/175-byte family against an owner's
own app (one 15-minute interval added 347 against ~1390 Wh measured; a whole day added 7516 against
the app's 7.52 kWh). That family ships an Energy sensor; the classic family's register is published
too on the same reasoning (it *is* the map 19 words earlier, checked field for field), and reads
zero — reported as absent — on every classic unit met so far.

Two cases stay unconfirmed:

* **Exactly one classic unit is known to keep a total, and its magnitude is unchecked** — it reads
  ≈ 3,139 kWh, and no reading off that owner's app has ever been compared against it. This shipped on
  *weaker* evidence than the 165/175-byte sensor. **Asked for on issue #1; if the answer disagrees,
  withdraw the sensor rather than defend it** — a wrong total is not recoverable once it is in
  someone's history.
* **The 209-byte family has a working register that is deliberately not published**, because that
  family has been caught departing from the shared map three times over and its counter's position is
  derived from the same inserted block. A unit is not the sort of thing to inherit on the strength of
  a map the family already disagrees with.

One reading off the owner's app, beside a diagnostics download, settles each — the same way the
165/175-byte sensor was settled.

### 7. The fault decode has not met a real fault

The bitmap decode follows the vendor's own parser and the labels match the published fault list, but
no unit here has reported a fault. `errCode` gives a free cross-check when one occurs: it names a
single fault where the frame carries the set, so the bit that is set must be `errCode - 1`. Nothing
to do but keep the diagnostic in place and check the first report that arrives.

★ **The table itself is not in question.** Every published
air-conditioner model declares **the same 51 faults at the same 51 positions**, with **zero**
disagreements about a name, so the one shared table this integration applies to every family is
justified by measurement rather than assumption.

★★ **The bit ordering has a second source too.** It was the one part of this item
resting on our own reading: which byte carries positions 0..7, and which way the bits run inside it.
An independent implementation of the same protocol decodes those frames too, and it was compared
against ours frame by frame — 8 bitmap bytes read **last byte first**, least-significant bit first
within each byte. Over every single-bit fault frame the two agree on **64 of 64 positions**, and its
fault list is **51 entries matching ours position for position**. So both halves of the decode now
have a second source.

What is left is only that no unit here has ever reported a fault, so the decode has never run on a
real one. That is a confirmation waiting to happen rather than an open question, and the first
faulted report still settles it for good.

### 8. The declared attributes that are still unreachable

A unit declares three or four times the attributes any family map carries, and every one sits where
the published map already says — so the extra readings are decoded into diagnostics
(`model_declared_fields`), membership from the device's own model, position from the map. The
user-facing ones are entities: the optional-feature sensors (item 4's gate),
the panel controls (item 36), and the air-quality suite (item 37). So have the maintenance and status
readings the vendor's own panel renders **no** control for, which is its way of saying they are a
status rather than a switch — the filter-change reminder (197 products declare it), the control-panel
lock, the two four-step air-quality ratings, what the presence sensor currently sees, the two
purification functions and the purifier's hour meter. Each takes the same three gates as the rest:
the unit declares it, its model does not mark it as hardware it lacks, and its family's relationship
to the published map is confirmed.

What is **still** unreachable is the residue with no derivable position — attributes in the appended
tail of the group-set list, which is unordered, so nothing places them. Where a run of unknowns fits
*exactly* between two placed attributes it can be laid out (five were placed that way, unanimous
across every model that declares them, and it re-derived positions already known from hardware — the
check that it works); where the fit is not exact the run is left unplaced rather than guessed, since a
wrong position decodes silently rather than failing. The remaining genuine controls (the append-region
bools and the dual-airflow read-back) are item 36's residue; everything else here reaches diagnostics
and waits on a capture of a unit with the feature switched on.

### 9. Eco, on the 209-byte family

The Eco ladder is `generatorMode`, a current limit that descends with the level (higher = more
restrictive). Two families ship it: the classic family (three level bits, established from its own
captures, at w4.b3–5) and the 165/175-byte family (two level bits at w23.b3–4, settled from issue #8
— off/L1/L2/L3 measured at 1969/1951/1798/1205 W). Both are written and read in the classic
representation so nothing above the family map knows which it is.

Open on the 209-byte family, because **the shared map carries no `generatorMode` at all** and cannot
place it. The published order *brackets* it — declared by 566 products, it falls between two placed
attributes, narrowing it to w4.b1–5, which contains the classic family's measured w4.b3–5 without
having been told it — but a bracket with spare bits is not a placement. Four captures (Eco off, then
each level, one download per state) settle it. (⚠️ Off and L1 were only 18 W apart on the 165/175
capture; worth one more reading before anyone describes what L1 *does*, though it does not affect
where the field is.)

### 13. The four-sided cassette vanes — shipped provisional, awaiting one wire confirmation

The four independent louvres of a four-way cassette (52 products declare them) ship as four selects,
offered on any cabinet that declares them and written one setting at a time: `5D0F`/`0E`/`11`/`10`,
each std stop `0..6` mapped to the config's non-linear epp code. Both halves come from the
manufacturer's own device configuration (the master byte map): the write ids sit
in the same per-attribute `eppCmd` column as the nine confirmed climate ids, and the read positions
are the config's **word 6** — four nibbles filling that word, inside the report's inserted block.

⚠️ **Provisional, for one specific reason.** The write ids are as solid as the nine, but their read
position has never been seen *populated* on the wire: the one `0d12` cabinet captured is a
single-flow cassette that leaves word 6 at zero. So each is written by id and settled by its own
read-back — a cabinet that actually moves its louvre confirms the position on first use, and one that
does not retires the control. **One report from a four-way cabinet with the louvres in four different
positions confirms all four at once**, and that is the only thing still worth asking for.

★ **Where the louvres sit.** Haier's config puts them at word 6, independent of
`windDirectionHorizontal` at word 4; the two coexist in the byte map rather than sharing bits. The
presence read-guard (item 42) rests on a separate fact: four-way cabinets do not declare presence.

**Residue, recorded not parked** (all watched by the register oracle in the maintainer's tooling, which
checks every id, read position, **value encoding** and big-data word against both config families and
that every config id is accounted for):

* **The unobserved second (商空) family diverges, and nobody has captured one.** The `…2151860b57…`
  family (23 products) numbers a few controls differently in its config — its `windSpeed` is
  non-identity (`std 6→epp 7`, `std 9→epp 6`; the shipped class-wide identity map would set the
  wrong fan speed on it), and it numbers the health-airflow louvre stop `std 10` where the observed
  candy family uses `std 7`. Its report also carries ~18 more status words than candy's, so the
  `(length−125)/2` insert heuristic would miscount on it. None of this touches the observed candy
  family that ships to real units; it is fenced off because the 商空 family is a **capture target**,
  not a shipping target. The oracle WARNs on the encoding divergence rather than failing.
* **`ampereControl`** (`5D32`, second family, ~4 products) — a compressor-current limit like the ECO
  ladder, now that the config gives it a number. Held for a focused follow-up; its value semantics
  are not yet worked out. Tracked in the oracle's `DECLARED_NOT_YET_SHIPPED`.
* **The `0d21` cassette is a SEPARATE class, not this one.** ~20 products spell the louvres
  `fourSidesWindDirection*` in their own declarations — those are class `0d21` (uPlusId `…0d21…`), a
  distinct device class with no single-parameter support here at all. Adding it is its own item (a
  `0d21` capture, its own decode), not a spelling alias on `0d12`. ⚠️ An earlier note here wrongly
  filed those 20 as a `0d12` 商空 spelling gap; they are a different class.
* **Not louvre-related but surfaced in the same sweep:** the ext-46 family reads/writes its inserted
  `windSpeed` at `w26.b9` with an identity enum, where its config puts it at `w26.b8` with a
  non-identity enum — wrong for the upper fan codes, and `b9`'s span reaches `oxygenSupplyMode`'s bit.
  Already flagged hardware-unverified in the code; a real ext-46 capture is the fix (its own item).

### 19. The still-unpositioned settings — counted per lineage, and classified by *why*

⚠️ **Count per lineage, never against one map.** Positions do not transfer between lineages, and the
compact family names its fields by Chinese label rather than by the catalogue's English name — so an
English-name membership test is structurally blind to it and reports its whole attribute set as
missing. That mistake has been made repeatedly; it is what the per-lineage table below exists to
prevent.

| lineage | products | attribute slots placed |
|---|---|---|
| compact-12 | 482 | **95.9 %** — 27 of the 28 attributes its products declare |
| shared frame (wall/floor) | 754 | 80.0 % |
| central `0d12` | 187 | 87.4 % |
| central `0d21` | 20 | 81.1 % |
| window / media | 8 | ~91 % |
| **total** | **1,451** | **83.9 %** |

⚠️ **"Placed" here means "carried by the layout this integration ships", not "position unknown".**
The two are not the same, and the gap between them is measured: of the residue, **6 attributes across
837 product-slots have a position that has been worked out and is deliberately not shipped** — three
are capability flags no product makes visible, one is contested against an attribute already placed
at those bits, one belongs to families that are read-only, and one is unanimous over four products.
Each is stored with the reason, and the test suite re-derives that reason from the shipped data, so
the day one becomes shippable the suite says so. Counting only what nothing anywhere can place, the
residue is **98 attributes over 7,118 slots**.

⚠️ **It is also a slot count across all products, and it must not be read as "any given unit is 84 %
mapped".** Most of the 1,451 are ordinary wall units declaring around twenty attributes, and they
pull the figure up. A feature-rich appliance is much further from complete: the twin-tower cabinet
this project holds diagnostics for declares **79 real attributes and 40 are positioned** — its own
description lists what the *product* supports, while the layouts published for it predate several of
those functions. That shortfall is a gap in what the manufacturer published, not one in what this
integration reads.

**The raw slot count is not the missing-control gap.** Classified, what remains is:

| why it is missing | slots | note |
|---|---|---|
| **past the last anchor** — no ordering information exists | 4,112 | only a capture places these |
| **bracketed, but the run does not close** | ~1,350 | see below — not solvable from published data |
| **derived, withheld with a stated reason** | 833 | five positions, run closed with no free parameter; each withheld on a measurement — see item 36 |
| **not in any write order** | 574 | read-only or cloud-side by construction |
| **compact-12 `echoStatus`** | 456 | its profile carries no record at all |

Much of the "not in any write order" bucket is **not a wire field in the first place**: the
manufacturer's own AC service holds per-appliance cloud records for self-learning, filter runtime,
sleep curves, countdown timers and power history. A feature computed and stored in the cloud cannot
appear in a byte map, and its absence from one is not a gap.

⚠️ **`echoStatus` is corroborated absent, not merely unfound**: the compact profile has no record for
it, the hardware silently discards a write to it on the classic family, and the vendor's own control
panel renders no widget for it anywhere. Three independent sources agree.

What settles any single one of the rest is unchanged: a report from a unit that actually has the
feature, taken with the feature in a known state — the layout prober scores against written-down
states. Nothing is waiting on this and nothing can go wrong because of it: none is surfaced, so none
can be mis-read, and a unit missing one is otherwise fully supported.

### 31. The compact family's three unproven registers

That family's 117-byte report is **decoded in full** — thirty-eight positioned fields, every one
exactly where the published description says, and **27 of the 28 attributes its products declare are
placed** (the 28th is `echoStatus`, for which the description carries no record at all).

★ **The three registers below are precisely the ones the catalogue names nothing for.** Every other
position in that description pairs with a declared attribute; these three do not, so their meaning
cannot be read off the models and has to come from a reading. They are held in the decode (visible in
diagnostics) rather than promoted to entities, checked against the three real reports from the issue
#4 unit:

* **input power** (word 3, low + high byte) — live (0 off, 15 cooling, 0 fan-only), but 15 is not
  watts while cooling, so the unit cannot be taken at face value. One reporter reading their meter or
  app beside a capture settles the scale.
* **the word-2 low byte** — an **outdoor-unit** temperature (reads ~60 cooling, stale ~59 off), *not*
  ambient outdoor air, so it is `w2_low_raw` in diagnostics rather than an "outdoor temperature"
  sensor a user would misread.
* **the word-9/10 toggles and flags** — positions published, but every capture reads them 0, so there
  is no positive confirmation of a bit until a capture exercises one.

⚠️ **Prior art does not answer these.** The independent
description of this same protocol carries **no power field at all** for this family, so it cannot
settle the scale; and its label for the word-2 byte is the *source* of the humidity-vs-temperature
disagreement recorded above, not evidence about it. Both still need one reading from a unit.

The humidity registers (word 11) read 0 — no probe — so they decode as absent and appear only on a
unit that has the sensor. No new user-facing entity ships for the 509 products this round; the
promotion bar (a reading proven and a meaning a user won't misread) is intact.

### 36. The panel control surface — the blocked residue

The panel control surface **shipped** across every group-set family, and across the compact family
via its per-attribute commands. What remains open is the residue that no source can place or read:

* **five append-region booleans** — `constDehumidificationStatus`, `preventSupercooling`,
  `pvPowerSavingMode`, `uvSterilizationSwitch`, `windAvoidance`.

  ✅ **`constDehumidificationStatus` is derived with no free parameter**, along with the four
  neighbours that share its run, at the same positions on all **159** products that publish it. The
  run is bounded by a confirmed position at each end and exactly one tiling fits it.

  The width is measured rather than inferred. The catalogue publishes only each
  setting's *standard* codes, while the wire carries the manufacturer's *internal* codes, and the
  bundled descriptions publish both — so the relationship between them can be counted rather than
  assumed. Counted: a code set beginning at zero keeps its codes in **1,082 of 1,082** cases, and of
  every setting whose codes are the pair `{1,2}`, **235 of 249 occupy one bit**. The neighbour in
  question publishes exactly that pair, so its width is settled by a population rather than by
  analogy to a single other field.

  ⛔ **All five are nevertheless withheld — and the reason is a measurement rather than caution.**
  Each was checked against the shipped model bundle, one at a time:

  | derived position | why it is not surfaced |
  |---|---|
  | balanced-wind and humidity-control capability flags, display mode | **159 products declare them and every one marks them as hardware the unit lacks.** There is no unit to show them on. Both flags are `有无` — "does this model have the function" — which is a statement about the product, not a state the appliance reports |
  | the left tower's horizontal vane | **contested**: 161 of the 165 products declaring it also declare the ordinary horizontal vane, which the shared map places at exactly those bits. A placement under this name would be reading the other setting's bits on almost every unit that has it |
  | constant dehumidification | the only **30** products that show it are the two families of item 38 — the ones whose published order refutes the shared frame, which is why they are read-only. A position derived from an order that contradicts the frame cannot be trusted against that frame |

  Those reasons are kept as data next to the positions themselves and re-measured by the suite, not
  written down and forgotten: if a catalogue re-sweep ever makes one of them visible, or moves a
  product off a read-only family, the test says so instead of the position staying withheld for a
  reason that quietly stopped being true.

  The other three stay unplaced, with a stated reason each: two sit **past the last setting the frame
  pins**, so nothing bounds them from above and no ordering information ever will; one sits in a run
  with spare bits the order cannot locate. Those need a capture, not more analysis.

  ⚠️ **Their positions are REUSED between product families** — one family keeps mould-proof, drying
  and heatstroke-prevention where another keeps humidity-control, display-mode and balanced-wind.
  Exactly one product declares both sets, and there the published order separates them and every one
  is marked as hardware the unit lacks, so nothing is mis-offered today. Anything shipped here must be
  family-gated the way the existing bit-reuse guard is.
* **dual-airflow** (`windDirectionVerticalL/R`, `windSpeedL/R`) — the twin-tower write positions are
  known (ext46, w1/w2), but **no report we hold reads a tower back**, so they would be write-only
  controls. Blocked on one capture with a tower vane parked non-zero (the same capture item 3 wants).

⚠️ **The per-attribute write channel does NOT rescue any of this, and that is measured rather
than assumed.** Item 42 writes central cabinets one setting at a time without needing a
position, so the obvious question is whether the same channel reaches these. It does not: across all
174 bundled device descriptions — 5,054 per-attribute command declarations, 596 distinct attribute
names — **no air-conditioner class publishes a per-attribute command for any climate attribute**. The
plain AC descriptions publish exactly one, `onOffStatus`; the two richest add twenty, all of them
voice-box functions. Every `targetTemperature`/`operationMode` per-attribute command in the corpus
belongs to a **different appliance category** (water heaters, sterilizer cabinets, steam ovens), at
different numbers. The attrID list the models publish alongside it does not cover these attributes
either. ⇒ For the wall/floor families a position is still required, and a capture is still the way
to get one.
* **`freshWindSpeed`** — read out of the published models, every product that declares it marks it
  **`writeType: G`** — group-written — and publishes **four** values, in two variants. Of the **16** products whose raw published model we hold: **3** publish
  `0 无 · 1 低 · 2 高 · 3 额定`, which **fits the frame's 2-bit slot exactly**; **13** publish
  `0 无 · 1 低 · 2 高 · 4 中`, and **code 4 does not fit two bits**. So the blocker is narrower than
  recorded — it is not the attribute that cannot be carried, it is *that one value on that one
  variant*. ⓘ **195 products declare the attribute**; the enum above is read from the 16 whose raw
  model we hold, so the remaining 179 are unmeasured, not known to agree. Settling it needs the value
  sets for those, or a report placing the field's real width.

### 38. Two families publish a group-set order the shared frame cannot explain (30 products)

A catalogue-wide audit — every product's published group-set order checked against the shared
frame's positions — found two families (12 + 18 products, the **AQUA `AQA-AX*` and `JAA-MX*` wall
units**) whose order has essentially **zero rank-correlation with the frame** (τ ≈ 0.06, against
1.0 for every confirmed family). That is not the frame with a few settings moved; it is some other
layout, or a list published in some other discipline. Nothing anchors it, so nothing can be derived
from it.

These products are **read-only**: every frame-position write for them would be a guess with
substantial counter-evidence, and a guessed group-set runs wrong functions silently rather than
failing (their report decode is unaffected — report
layouts are verified against the report itself, and the read frame is not the write frame). What
settles it: a diagnostics file or capture from any of these units, which would show whether their
reports resolve to a known family and give the first anchor for whatever their write layout is.
⚠️ **Checked 2026-08-25:** no report from an `AQA-*` or `JAA-*` unit exists in the public issue
trackers of the projects implementing this protocol either — the route that settled item 42 has
nothing to offer here yet.

### 39. The appended-tail settings on the other twin-tower families

The same audit showed extended-46's structure is not unique to it: **every twin-tower family** (six
families, 161 products) lists the appliance's own `windDirectionVertical`, `windDirectionHorizontal`
and `windSpeed` in the appended tail of its order, past the words the shared frame reaches. For
extended-46 the packing arithmetic plus capture-confirmed read-back settled the vane and fan at
group-set words 6/7 (item 29).

✅ **Mostly resolved — 109 of those products now have swing and fan speed.** Two of the families
publish an order that is **byte-identical to extended-46's through both anchor positions**, and every
attribute preceding them in the tail publishes an identical value set, so the packing that puts the
anchors on those bits is *the same packing*. The positions are therefore extended-46's own, copied
rather than re-derived, and they are carried in a family-keyed table
(`family_write.TAIL_POSITIONS`). Measured over the whole catalogue: **109 products gain exactly two
controls, none loses one and no position moves.**

⚠️ Two things this did **not** fix, and both are honest residue:

* **`windDirectionHorizontal` is still absent on all of them.** It is in the tail too, but
  extended-46 has no confirmed position for it either, so there was nothing to copy. Worse, it is
  now known to be *underivable*: between the two confirmed anchors the order leaves a **4-bit run**
  for `windDirectionHorizontal` (irreducibly 3 bits) and `oxgyenSupplyMode` (2 bits, because its
  published code set starts at 0 and such sets keep their codes in 1,082 of 1,082 measured cases).
  Five bits into four. The residue is a reserved bit or an attribute the frame does not carry, and
  **published data cannot tell those apart.** One capture settles it; nothing else will.
* **8 products still lose all three controls.** One family inserts `waterWindSpeed` before the
  anchors so its positions shift by that field's width, and two `0d21` families diverge earlier
  still. Each needs its own solve or one report.

⚠️ Rule 8 residue: no unit of the two newly-reached families has been commanded. The evidence is
published order agreement plus a *sibling's* capture, which is stronger than what shipped for
related layouts — but it is not this family's own hardware.
⚠️ **Checked 2026-08-25:** those same public trackers carry no report from a twin-tower cabinet
either. Worth re-checking whenever one of those projects gains a dual-airflow user — that is exactly
how item 42 was settled.

### 41. The fan speeds — named from the vendor's own wording; Boost alone is withheld

Issue #11 exposed the shape of a defect worth stating once: the wire map's mode and fan **code sets
are the identity** — on every family that is the published map at a displacement, the wire value *is*
the standard code — so their only job is to say which codes exist, and a code missing from one does
not decode wrong, it **vanishes**. Downstream that reads as "the appliance did not report a fan
speed", not as "we do not know this code", which is why nobody noticed.

Both enums are complete against the published catalogue, and — this is the part that took the
longest to get right — **named by the manufacturer, not by us.** Its app ships an offline language
bundle whose `seasia_home.AC_*` keys are exactly this vocabulary in 18 locales, so the English for
each Chinese description is the vendor's own word. See **[`VENDOR_LABELS.md`](VENDOR_LABELS.md)**.

| code | description | vendor English | our token |
|---|---|---|---|
| 4 | 微风 | Breeze | `breeze` |
| 6 | 静音风 · 快速风 | Silent · Quick | `silent` · `quick` |
| 7 | 中高风 · 快速风 | Mid-high · Quick | `mid_high` · `quick` |
| 8 | 中低风 | Mid-low | `mid_low` |
| 3 (mode) | 健康除湿 | Healthy Dry | `health_dry` |

★ **Naming them fixed three silent collisions**, which is the half that mattered: `中高风` and `高风`
both resolved to `high` on **51 products**; `中低风` and `中风` both to `medium` on **31**; and
`健康除湿` and `除湿` both to `dry` on **20**. Two codes on one token means the reverse lookup a write
resolves through returns whichever the model happened to list first.

⚠️ **Codes 6 and 7 each carry two different meanings across products**, so the code never determines
the speed — the description does, which is how `_enum_from_datalist` already worked. Nothing here is
a code table.

**What is deliberately still out, and why each:**

* ⛔ **超强风 / "Boost" (code 0, 23 products).** Its wire value is 0, and 0 is what the fan field
  reads on a real 209-byte report from a unit that is switched **off** — so it cannot be told apart
  from "no speed reported". No report from any Boost-declaring product exists to separate them.
  Withheld in **both** layers (no wire code, no keyword), because offering a speed in one layer and
  not the other is the actual hazard. **What settles it:** one report from a unit declaring 超强风,
  taken while it is running at that speed.
* **中低风 (8) and 静音风 (9) do not fit** the frame's 3-bit `windSpeed` field. They are named, so a
  unit reporting one shows it wherever the field is wide enough; the frame simply cannot carry them.
  Every product declaring either is already refused `windSpeed` control on other grounds, so nothing
  reachable is lost.
* **`medium` stays `medium`** although the vendor says "Mid" — it is in users' automations.
* **`健康除湿` is display-only**, like the window units' ECO: it shows as Dry and is not separately
  selectable, because Home Assistant has no mode for it. Reported correctly, which it was not before.

### 42. The `0d12` central cabinets — controlled, vanes included

**187 products** publish **no group command at all**. Every attribute is marked individually
settable, and their firmware **refuses the group-set frame outright** — so the group set is not
merely undeclared for these cabinets, it is unavailable. Each setting is its own command, with the
value in the payload.

**What ships:** power, setpoint, mode, fan speed, health, quiet, boost, both vane axes and the
display unit (°C/°F) — offered where the cabinet's own model declares the attribute, and each read
back from its own position in the report so it shows real state rather than an echo of the request —
plus presence-based airflow and the four-way cassette louvres, on the provisional terms described at
the end of this item and in item 13. All fifteen single-parameter ids are Haier's own, taken from
its device configuration and checked by the register oracle in the maintainer's tooling.

★ **A vane is read even where it cannot be commanded.** A vane is a position, not a switch,
and the climate entity's swing control answers only "is it sweeping" — so a vane parked at a real
stop reads exactly like one held closed. These cabinets publish as many as ten up-down stops and
eight left-right ones and report both axes in every status frame, so where an axis is readable and
not writable its position is surfaced as a reading of its own, named for the stop the unit's own
model publishes. Where the axis *is* writable the existing control already shows the stop, and the
reading is not duplicated.

⚠️ **All of that is gated on the report resolving to a layout**, which for these cabinets is not
automatic: one of them reports a block of words between its settings and its sensors that no
published description mentions, so every ordinary offset is rejected on the room temperature alone
and the appliance decodes almost nothing. That case is handled (see the 133-byte section of
[`report-layouts.md`](report-layouts.md)): the size of the report settles how big the block is, so a
cabinet resolves whether or not it can heat. ★ That last part matters — the heat-capability flag alone
answers only for a **cooling-only** unit, and two of the three such cabinets on record are heat
pumps, so the report's size is what settles the block. A cabinet reporting some *other* length with the
same shape would still need its own measurement before the same arithmetic could be trusted for it.

* **The command bytes** are the ones these appliances are observed to exchange, and the values need
  no translation: mode `0/1/2/4/6`, fan `1/2/3/5`, setpoint `°C − 16`, booleans `0`/`1` — the same
  encodings every other family here uses.
* **Several settings become several commands.** There is no word block to pack, so a change that
  touches three settings sends three ops, each separately accepted or refused by the appliance —
  which also means a refusal names the setting that was actually refused. Power leads when switching
  on and trails when switching off, so a unit is configured while it runs and stopped only after the
  rest has been applied. ⚠️ That order is a choice, not a measurement; it is fixed so it is at least
  predictable.
* **Reads are corroborated** against reports from an appliance of this exact identifier: setpoint,
  mode, fan and power all land where the published map puts them. Wrong sensor values on one of
  these means an old version — update.

★ **The two vane commands were offered on terms the appliance itself settles — and it settled them.**
This generation defines a command for each axis, and for a long time neither had been watched being
*accepted*: the reference table's other eleven were read off a real appliance's traffic while these
two were added without any capture behind them, and the one cabinet whose traffic was captured has no
vane. So they were resolved a different way, and the mechanism is worth keeping because presence
(below) uses it now.

**The up-down command is bracketed**: in the published wire order that attribute is the only one
these cabinets declare between two commands that *were* observed, and only one command number is
free in that gap — so the number is forced, and it is the number the reference table guessed. And
**both axes read back**. This channel names one attribute at a time, and the report says where each
vane is pointing, so the appliance can answer the question the moment somebody uses the control: ask
for a stop, then look at where the vane says it is.

⇒ **A provisional control is written, checked once against the appliance's own reading, and then
trusted.** If the value took, nothing more is checked. If it did not, that control is withdrawn for
good and the failure is reported, rather than leaving somebody pressing a button that quietly does
nothing. An owner then moved **both** axes on real hardware — the adjudication passed on the up-down
command it bracketed and on the left-right command that rested on the reference table alone — so
both are plain confirmed controls now, and the provisional machinery stays in place for the next
derived command.

**143 of the 187 cabinets declare an up-down vane and 91 a left-right one.**

⚠️ **One thing about these command numbers is worth stating plainly: they were watched on one
appliance kind and are sent to two.** This class covers **187 appliances in two families** — 162 of
one, which is the family every captured number came from, and **25 of another** that publishes two
and a half times as many functions. All 187 are individually written and the two families agree on
the 87 functions that matter here, so sending the same numbers to both is a reasonable expectation —
but nobody has watched the second family answer. A command is still only ever sent for a function the
appliance itself declares, and a control that does not take is withdrawn permanently, so the exposure
is one command; the point is that it is an expectation rather than an observation.

★ **That also names the most valuable single capture anyone could contribute here:** traffic from one
of those 25 appliances would place far more commands than the recording this integration was built
from, and would settle the question above at the same time.

⚠️ **`invisible` is not used as the gate** — see item 43. Membership is the attribute being declared
at all, because the parameter table is per device class while the function is per product: a cabinet
with no health module must not be offered health merely because its class defines a command for it.

#### Presence-based airflow on these cabinets — offered provisionally, on the vane terms above

One of these cabinets reports its presence mode as *on* where three identical siblings report *off*,
so the hardware is real and the reading ships. The **control** is offered too, as a select (off /
avoid / follow / on), and how it is offered matters because its command has not yet been watched
being accepted.

**Where the number comes from.** The command number is the manufacturer's own: its device
configuration for both central-cabinet families gives `humanSensingStatus` the write command
`5D23`, the same per-attribute column the nine confirmed climate ids come from. It is provisional
only because the write has not yet been exercised on a cabinet, not because the number is a guess.

**Why it is safe to offer anyway.** It is offered exactly as the vane commands were: the appliance
reports the setting's own position in every status frame, so the first use writes the command and
reads the setting back. If it took, the control is trusted from then on. If the appliance refused it
or the setting did not move, the control is **withdrawn for good** and the failure is reported — the
cost of a wrong number is one command that changes nothing. A cabinet without the sensor withdraws it
the first time anyone tries, which is the right outcome for that cabinet.

**Who gets it.** Membership is the class: every `0d12` cabinet carries the setting undeclared — the
same under-declaration that hides its outdoor probe — so the control is offered on every one except
a cabinet whose own description gives those bits to the four-way louvres (a presence control there
would be writing a vane). Whether a given cabinet has the sensor is settled by the write itself.

⚠️ **Two things are called "presence" and they are not interchangeable.** The airflow *mode* — what a
user changes — is an ordinary attribute of the main board, and that is what is commanded here. The
sensor's own enable and installation parameters are a separate conversation between the module and a
sub-board that never reaches the network, and are not something a user sets. Conflating the two once
produced the wrong conclusion that presence could not be controlled at all.

**What would settle it outright:** one use on a cabinet that has the sensor. The adjudication above
runs automatically, so nothing is asked of anyone beyond trying the control.

### 45. A multi-attribute write command exists on paper — and this generation refuses it

Item 42 sends one op per setting, because the class it serves has no group-set command. The protocol
documents a **third** shape between the two: a *set-parameters* command carrying a list of
`parameter id + value` pairs in one frame — the same per-attribute addressing item 42 uses, but
several at a time, with no packed word block and so none of the group set's whole-block hazard.
A cabinet that took it would apply "turn on, cool, fan low" in one op instead of three.

**Tested here on 2026-08-25, and refused.** Both halves were sent to a wall unit as no-ops — the
*get* form carries attribute ids and no values at all, and the *set* form carried an attribute's own
current value — and the appliance **refused both**. In between, the per-attribute command it does
publish was sent identically and **accepted**. Nothing moved on any of the three.

**Why the bracketing matters.** A refusal on its own says only that the unit declined *something*.
A refusal either side of an acceptance, from the same state, over the same connection, minutes
apart, says it declined **that command** — the difference between an appliance that is fussy today
and a command this firmware does not implement.

**The unit says the same thing out loud.** These appliances chirp when they accept a command. Re-run
as a listening test with someone standing beside it, three commands inside twenty seconds: both
refused forms were **silent** and the one it implements **beeped**. That is a second signal, owing
nothing to how we decode a reply, and it agrees.

**And the refusal of the *get* form is the one that settles it.** That form carries no value, so it
cannot be explained away by the value's width, its encoding, or which of the two number spaces a
value travels in — the three loose ends a set-only test would have left. It was refused anyway.

⚠️ **What it does not settle.** One appliance, of the wall generation — **not** the central cabinets
that item 42 actually serves, which are the ones sending several ops. They have answered nothing.
The evidence against is strong (nothing in any of the 174 published device descriptions declares
either half, the reference implementation documents the pair without using it, and hardware of a
neighbouring generation refuses both), so this is not worth a reporter's time on its own — but if a
central cabinet is ever on the other end of a probe, the same two commands cost ten seconds.

**Not a blocker for item 42.** Several ops is correct behaviour, just not the tidiest.

### 47. The lock explanations — restored and translated, with one residue

When a rule makes a control unavailable, the integration shows the reason the device's own published
model gives for it. Two faults meant most owners never saw one.

**A published model spells that record two ways**, one per serialisation — `code`/`description` on
1,423 products and **`name`/`desc`** on the 28 that arrive in the other shape. Only the first was
read, so **21 products shipped with no explanations at all** (189 sentences), and 96 more were
missing some of theirs. Twenty of the twenty-one are the compact central cabinets — `HCFI-*`,
`HCSI-*`. **477 sentences restored.**

**And 52% of the sentences that did ship were in the source language.** The English wording only ever
covered one of the two reason-code spaces, so the 700 products whose codes live in the other one
showed their owners text they could not read — worse than showing nothing, because it looks like a
fault in the integration rather than a message from the appliance. **7,261 sentences translated;
31 published wordings collapse to 20.**

Both are guarded now: a test refuses any shipped reason left in the source language, and a second
pins the fact that **a reason code is not a global key** — code `1` means "not allowed in the current
state" on 509 products and "this function is not supported" on 300, so nothing may carry a sentence
between products on the code alone.

⚠️ **What is left.** The wording is **ours**, not the manufacturer's: its own language bundle has no
text for any of these (see `VENDOR_LABELS.md`), so unlike mode and fan-speed names — which arrive in
18 locales — these twenty are English wherever they appear. They surface as free-text entity
attributes rather than through Home Assistant's string catalogue, so localising them is hand work.
**7 products still show none**, correctly: their published models declare no reasons.

### 48. The rules that locked what they only limited — fixed, and the operator with it

**Every published rule was re-read against the vendor's own bytes, and two faults came out of it.**
Both had been shipping since the rules engine existed, and both were invisible to the tests because
every fixture was written from the same understanding as the code.

**A rule that limits a setting's VALUES was making it unavailable.** A rule's action names which of
the attribute's fields it rewrites — `W` its writability, `V` its permitted values, `WV` both — and a
`V` action carries no writability at all. Read as a lock, it withdrew the control: **611 products**,
almost all of them on the up-down vane or the fan speed, triggered by an ordinary running mode. The
worst of them made **the swing control unavailable while the unit was simply cooling**, with the
explanation "not available in the unit's current state" — a sentence the model never said. The other
serialisation of the same model states the answer outright: there a `WV` action is *writable* **and**
carries the narrowed set. **1,451 attribute-state locks removed, 0 added.**

**And a rule's conditions were being combined with the wrong operator.** A trigger holds two groups —
what the write asks for, and what the unit currently reports — each with its own relation, and the
relation on the trigger combines the *groups*. It was being read as the operator over the conditions.
Calibrated against the account-scoped copy of one product's ten rules, which states the operator
plainly: it matches the inner relation on all ten and the outer on one.

**Then the engine ignored the operator anyway.** Two functions in one file evaluate a rule's trigger;
one honoured `OR` and the other, thirty lines above it, ANDed everything. An `OR` rule ANDed fires
only when both its settings travel in one command, which is to say never: **495 rules across 488
products** were parsed, valid and permanently inert — this project's own appliance among them, whose
model says switching on quiet or sleep also clears boost, and which did not.

The shipped rule bundle was built from the adapted output, so it was re-derived from the published
models for all 1,451 products; re-running that repair is a no-op. A test over the whole bundle
refuses any rule that locks a setting it only narrows, and asserts there are more than 500 such rules
to get wrong — a guard over an empty set proves nothing.

⚠️ **What is still not read, and is not a defect.** A trigger's *reported-state* term is dropped, as
the vendor's own account serialisation drops it: two rules that differ only by it arrive
indistinguishable there too, and the integration already handles the one case that matters (it
substitutes a fan speed when fan-only is selected on auto) more precisely than the rule would. And
**four products** publish two rules that set the same attribute to different values under the same
condition (`windAvoidance` and the vane positions); the model orders them by a priority nothing here
reads, so one of the two wins by list order. One report from such a unit would settle which.

### 50. The central cabinets may be several indoor units behind one address

The protocol treats a group of appliances on a shared bus behind one communication module as a
single addressable system: every frame carries a source and destination address, the module is
always address zero, and sub-units are numbered from one. There is a command to ask a system for
**how many sub-units it has and what their addresses are**, and another the appliance sends when
that set changes.

This integration sends the destination address as zero in every frame, which is correct for a
single-board appliance and is what the residential units are. For a central cabinet it may mean we
are only ever talking to the first indoor unit of a system that has several — which would explain
why a multi-unit installation appears as one device.

Nothing here can test it: it needs a central installation with more than one indoor unit on one
module. The enumeration command changes nothing if the appliance does not implement it — it is a
question, and an appliance that does not understand it simply refuses.

### 53. Presence is a MODULE-side sensor with its own pipeline — and it reports distance

The vendor's generated protocol document for `0D012`
carries a second presence pipeline beside the board's 2-bit `sensingResult`: the **Wi-Fi module's
own status frames** (§6.41 reply, §6.44 push — every 10 s in 人感模式, at once on change) include a
**`0xA0` 人感 block** — bit0 `0 无人 / 1 有人`, bit1 start/stop, bit2 antenna status, plus **the
sensed person's distance band, lower and upper bound in centimetres**. The board enables and
configures it with system-interaction frames (`0x100A` enable · `0x100B` disable · `0x100C`
parameters, sent after every handshake · `0x1011` query · `0x100F` "module asks the board to disable
its own presence logic"). `humanSensingModuleErr` on 187/187 `0d12` products is that module's fault.

Consequences:

* The board's `sensingResult` reads `0` on every `0d12` report on file — **including the issue #12
  cabinet whose presence MODE reads 3 (on) in the same reports, taken with nobody under the
  cassette.** `0` is therefore *unknown*, not "no sensor"; the state map leaves it out and the raw
  value is in diagnostics (`feature_raw`). ⛔ Do not gate anything on `sensingResult == 0`.
* Every LAN frame kind is kept with its bytes (`lan_frames`) and every uSS message of the last
  session is traced (`uss_messages`), so whether the module's `0xA0` block ever reaches `:56800`
  is answerable from a diagnostics file.
* **The experiment:** on a cabinet with presence mode on, capture with someone under it, then with
  the room empty. If the board field follows (`1`/`2`/`3` vs `0`) the vocabulary is settled; if a
  frame with the `0xA0` block appears in `lan_frames`, the module's own report — with the
  distance — is on the LAN and a presence/distance sensor can ship.
* **Outcome on the issue #12 cabinet (2026-09-01):** the reporter states the unit **has no PIR
  sensor**, and that the app's "Detecting" screen is fault detection (as read from the panel).
  Their diagnostics with the frame-keeping build: `feature_raw` `humanSensingStatus 3` (on) with
  `sensingResult 0`; `lan_frames` holds four kinds only — the 4-byte session blob, `06/6d01` 133 B,
  `04/0f5a` 103 B, `06/7d01` 147 B (item 52) — no `0xA0` block. So this cabinet cannot register the
  experiment, and it shows that the board's presence MODE field reads "on" on a unit without the
  sensor. The control was offered by the CLASS gate (`CLASS_CARRIED_ENUM_FEATURES["0d12"]`,
  `_class_carried_controls`) — the product's constraintfile lists 9 attributes and no presence,
  while the panel-embedded model fetched for this very product (the per-product panel's embedded model for `AE2C52Q00`, 39 attributes keyed by name) DOES declare `humanSensingStatus` (感人模式, writable, marked not readable). **The manufacturer's own per-model witness** (a Haier Thailand brochure the
  reporter supplied): "HUMAN SENSOR
  … *only on HCFI-36ETR32, HCFI-40ESR32, HCFI-40ETR32, HCFI-48ESR32 and HCFI-48ETR32*" — five
  models, all on the C/E-series family (`…00041410…`, shared-frame presence), none of them `0d12`;
  `HCFI-38XTR32F` is not on it. The brochure also refutes the constraintfile the other way: every
  C/E HCFI product declares `humanSensingStatus` (13CSR, 18CSR, 25ESR, 30CSR, …) while the brochure
  names five. So neither published model is a per-unit or even per-model witness for the sensor,
  and a per-product gate built from the panel would offer presence on exactly this reporter's
  cabinet. The provisional `5D23` write — the id Haier's own device configuration gives
  `humanSensingStatus` (`5D08` is `halfDegreeSettingStatus`) — offered, not yet tried on this unit —
  remains the only
  adjudicator on `0d12` (a `0001` "not supported" refusal withdraws the control); on the C/E family
  the five brochure names are the only allow-list held, scoped to one market's brochure. The
  experiment still needs a cabinet whose owner confirms the sensor is fitted — one of those five
  models is the place to ask.

### 54. Left-right vane on `0d12` — control confirmed on hardware, and the code→position map

The issue #12 reporter drove `windDirectionHorizontal` from the integration on their `AE2C52Q00`
cabinet and watched the louvre: **the `5D0C` single-parameter control works** (the vane moved), and
of the eight codes the model authorises (`0..7`), **codes 1 and 2 do nothing** while **3 = far left,
4 = near-centre left, 5 = near-centre right, 6 = far right** — four discrete stops sweeping the room
left→right. `0` and `7` were not reported (by analogy with the vertical vane, `0` fixed / `7` auto).
So the control and its adjudication (`5D0C`, per the diagnostics `single_param_ids`) are confirmed
live on a real `0d12` cabinet, and the enum's *usable* range is the middle four codes, not all eight.
This is a per-hardware observation, not a model change; it is the ground truth to check the shipped
`windDirectionHorizontal` labels against, and the first confirmation that a `0d12` L-R vane command
moves the actual louvre (the four-sided cassette sweep, `FUTURE_WORK` unchanged, is still unobserved).

### 55. What the unit is doing (`hvac_action`) is undecidable in auto on a heat pump while the compressor runs

The climate entity reports what the unit is *doing* -- cooling / idle / drying / heating / fan / off
-- from the extended report's compressor flag; Home Assistant badges the tile-card icon with it and
prints it under the temperature in the thermostat card. Two gaps, both left as honest unknowns
rather than guesses:

- **Auto on a unit that can heat, compressor running.** Nothing decoded says which way the
  compressor is pumping. The extended report carries a reversing-valve field
  (`four_way_valve_status`), but every capture to hand reads it as "not reported" (2), and its
  polarity -- whether 1 means heating -- has never been observed. So the action reads unknown
  there; idle, and the explicit modes, are still decided. On a cooling-only unit auto reads
  cooling, because nothing else is possible.
- **Units that answer no extended query.** Off and fan-only are decided from the status report;
  cool / heat / dry read unknown rather than echoing the mode, because "cooling" on an idle unit
  is precisely the wrong answer the badge exists to avoid.

**What closes the first:** one extended report from a heat-pump unit that is heating (mode heat,
compressor running) whose reversing-valve field reads 0 or 1 -- that fixes the polarity, and auto
can then be decided from it. Defrost (`defrost_status`, same actuator word) can be published as
`defrosting` the same way once one report shows it at 1.

### 59. ⓘ A THIRD presence parameter exists in the SDK: the occupied→unoccupied DELAY (2026-09-06)

Haier's own `wifibase` SDK manual (`catalogue/haigeek_refdocs/wifibase/`, §九 `uhepp.h`) declares three
radar/人感 events on the module↔board UART:

    UHEPP_RADAR_STATUS_GET       获取感知状态
    UHEPP_RADAR_STATUS_SWITCH    人感开关状态切换
    UHEPP_RADAR_SET_DELAY_TIME   ★ 设置人感有人到无人的延时时间

We ship the presence **mode** (off/avoid/follow/on) and read `sensingResult`; the **delay time** —
how long after the room empties before the appliance treats it as unoccupied — is a parameter we have
never seen, in the byte maps or on the wire.

⚠️ **Do NOT ship anything from this.** It is an SDK API surface, not a wire encoding: there is no
attribute name, no `5Dxx` id and no byte position here, and no evidence our AC's board implements these
events. It is recorded so that if a delay-like field ever turns up in a configFile or a capture, its
meaning is already known. Related: memory `presence-sensor-is-module-side-with-distance`,
`docs/LEFTOVER_UNKNOWNS_2026-08-31.md` §A2.


### 60. ⓘ The appliance announces its own key rotation on `:56800` — an unhandled message type (2026-09-08)

While a controller is connected, the appliance sends an unsolicited message with **info type 6**
(`info_code 0xEA66`) when its key version changes. It is **header-only — an empty payload** — and is
rate-limited to roughly one every five minutes. There is also a controller→appliance **type 4** that
asks the appliance to refresh its key, answered with a **type 5** whose body is encrypted under the
session key with the framing the integration already implements (`BE16 length ‖ data ‖ padding`,
AES-CBC). The handshake types we do implement are 0–3, so **types 4, 5 and 6 are all unhandled**.

Today the integration learns about a rotation only when biz-data fails to decrypt, and then re-keys.
The appliance is willing to say so directly, and because the type-6 message carries no payload it
remains readable with a stale key.

⚠️ **Do not build on this yet.** Three things are unsettled: the message does **not** carry the new
version (that arrives in the next handshake reply, which is fine — we already know how to re-key,
what we lack is the trigger); it is unconfirmed on the firmware our reference units run; and the
coordinator polls in short sessions, so a five-minute-debounced push will usually fire with nobody
connected.

▶ **The free first step, no hardware and no risk:** the frame ledger added in v0.66.0
(`coordinator.lan_frames`, `uss.collect_session_blobs`) already keeps every frame kind seen. Record
the **info type** of any inbound message that is not `1` or `3`, so one of these shows up in a
diagnostics download instead of being silently dropped. If one is ever seen, its bytes settle the
rest.

### 61. ⓘ "i-Feel" (the handset measuring room temperature) is not visible to us — a caveat on `indoorTemperature` (2026-09-08)

On many Haier remotes, a handset button makes the **remote** measure the room temperature and the
appliance follow it instead of its own sensor. Asked whether we can see it: **no**, and the search
that says so was scoped as follows.

* **All 228 distinct attributes** across the 23 air-conditioner families in the published device
  models were listed with their descriptions. The only temperature attributes are
  `targetTemperature`, `indoorTemperature`, `outdoorTemperature` and `tempUnit`, plus comfort flags
  (`autoTempCtrlStatus`, `constDehumidificationStatus`, `tempHumidDisplayMode`, `dualCtrlStatus`).
  **Nothing indicates which sensor feeds the control loop.**
* Nine Chinese HVAC terms for the concept (控温点 · 感温点 · 测温点 · 回风感温 · 温度来源 · 温度补偿
  · 温控点 · 控温方式 · 温度控制方式) appear **nowhere** in the published models, the byte maps, the
  vendor documentation set or the UART protocol specification.
* ★ **The control that makes this a real negative:** Haier *does* model "control method" where it
  wants to — **`humidityCtrMode` 湿度控制方式** exists. There is simply no temperature equivalent.
* The vendor documentation set contains **no infrared protocol material** at all; the few mentions of
  遥控器 are onboarding instructions ("set the remote to cooling mode") and a product category.
* One reference unit declares 87 attributes, of which two are temperature.
* ⛔ Not covered: the per-product panel bundles.

⚠️ **Do not mistake `opSrc` for it.** `opSrc` (控制命令来源) enumerates `0 other / 1 remote /
2 keypad / 3 network` — the source of the last **command**, not of the temperature reading.

⚠️ **The caveat that matters for us.** The handset sends its reading to the appliance over infrared,
and the appliance substitutes it for its own sensor internally. Nothing new appears on the wire —
`indoorTemperature` is reported as usual, with **no indication that its source changed**. So while
i-Feel is active our sensor may be reporting **the remote's location, not the unit's**. Worth a
README line if a user ever reports the reading moving on its own.
⛔ Nothing to implement: there is no attribute to read.

▶ **One cheap test (a hypothesis, not a claim).** If the handset transmits its reading as an infrared
*command*, `opSrc` may flip to **1 (remote)** periodically while i-Feel is on with nobody touching
the remote — an indirect indicator. It is equally possible the appliance treats those frames as
telemetry and never updates `opSrc`. The test costs nothing: enable i-Feel, leave the remote alone,
and watch `opSrc` across two diagnostics downloads.

## Reference — not open items

Kept because each looks like something to "fix" until you know why it is the way it is.

⛔ **Not on the central cabinets, and that is settled rather than untested.** The communication
standard states that a multi-appliance system *must* use the interactive conversation mode, and
those cabinets use the simpler one where the module asks and the appliance only answers — which
their own refusals confirm. So an appliance of that class is not one of these systems, however many
indoor units a building has. This needs hardware that actually talks the interactive mode.

### The layout prober is told what the captures were

The prober is the *second* thing to run: an unfamiliar report is first matched against
the offsets its nearest published relatives use (item 23), and the prober handles only what survives
that. Its output is a shortlist to verify, not a result. `probe_layout` scores against
`stated=[StatedState(...)]` — what each capture was known to be — as heavily as the device's published
values, so on two real reports where 77 of 83 candidates tie on plausibility alone, the stated states
separate them, and a reporter's "cool"/"fan-only" work without anyone knowing the model's codes. The
report form has one box per capture, `scripts/probe-diagnostics.py` takes them with `--state`, and
diagnostics dumps `digital_model.reported_values`. What is *not* solvable from here: the search inside
diagnostics runs unaided, because Home Assistant cannot know what state a unit was put in — the states
have to enter from the issue.

### The one rule we decline to honour

`locked_attributes` decides which commands a unit discards (fan-only shows no setpoint; boost and
quiet refuse in the modes that discard them; a faulted unit accepts only power and mode). It drives
*command refusal*, **not** entity availability — that was the bug item 24 fixed. Rules are fetched
per device and merged onto the shadow (which carries no rules); a device with no published rules gets
none, which locks nothing.

Two carve-outs are deliberate. A model marks nearly everything unwritable **while the unit is off** —
including `operationMode`, which is exactly what turns a unit on and which real hardware accepts — so
that rule describes an app greying its own buttons, not what the unit discards, and is skipped (the
self-clean half, which really does hold the unit, is honoured). And the preset control is evaluated
as though no comfort setting were on, because a preset write clears its siblings and a rule letting
sleep lock boost would strand the control meant to undo it. Writes are never gated on any of this;
only availability was, and that is now a refusal instead.

### 43. `invisible` marks hardware a unit lacks — but it is NOT a control gate

**Investigated and closed 2026-08-25. The fix was written, it broke a test, and the test was right.**

**The observation that started it, which stands:** `switch.py` creates the five core toggles
(strong/quiet/health/sleep/lamp) gated only by `supports_field`, which never consults `invisible` —
while the panel controls ten lines below it *do*. `button.py`, `sensor.py` and `climate.py` share the
ungated pattern. On paper that is the phantom-feature bug on the control side.

**The counter-example that closes it.** Gating `supports_field` on an explicit `invisible` mark
immediately withdrew **left-right swing** from the owner's own unit. Its product `AAC1UKZ01` marks
**`windDirectionHorizontal` invisible** (one of 25 invisible attributes of 39) — yet that control was
**shipped and live-verified on that exact hardware**, tracking the handset through
auto → position_4 → fixed.

⇒ **The vendor's `invisible` flag says the unit has no horizontal vane. The unit has one.**

★★ **So the flag is not "this hardware is absent" in the sense a control gate needs.** The asymmetry
decides it:

| | trusting `invisible` | not trusting it |
|---|---|---|
| **sensor** | may hide a real reading | a phantom sensor reading a constant zero |
| **control** | **removes a working control** — demonstrated | offers a control that may do nothing |

For a sensor the flag is worth trusting; for a control it is not, because the failure is worse and we
have a concrete case of it firing wrongly. **Leave the controls ungated.**

★ **What genuinely came out of this, and is worth keeping:**
* **`invisible` and group-set order membership are independent** — measured across the published
  models: **2,156** attribute slots are invisible *and still in their product's order*, **0** are
  invisible and absent from it. Order describes packing, `invisible` describes hardware. Never
  substitute one for the other (this is why the F6 order gate filters no absent hardware, by design).
* **`invisible` is unreliable per-attribute**, at least for `windDirectionHorizontal` on `AAC1UKZ01`.
  ⚠️ That should temper how far the optional-feature gate is trusted, though the risk there
  (a hidden sensor) is mild and no case of it is known.
* The tree was left unchanged and the suite stayed green.

# Settled

**49. A refusal names its own reason, and it is reported in the manufacturer's own words.** Done.
An appliance that declines a command answers with a code saying which rule was broken, and each
product publishes its own table of those codes — this integration ships all of them, translated, and
now reads the code off the refusal and renders that product's sentence. ⚠️ Never a global lookup: the
same number means different things on different appliances, so a code a product does not publish is
reported as "the command was not recognised" rather than borrowed from another product. The reader is
held to a refusal recorded from a real central cabinet, which carries the flag that says a checksum
is followed by a CRC — a shape no hand-written fixture had. ★ The distinction it draws is worth more
than the sentence: an appliance answers one code when it does not recognise a command at all, and
another when it recognises the command and does not have the hardware, so a probe can tell whether a
command number exists without writing anything. ⚠️ The central cabinets of item 42 publish an
**empty** reason table of their own, so every refusal they send carries the protocol's generic "not
recognised" code; a product-specific reason will only ever be seen from a family that publishes one.

**51. Presence-based airflow, on the family whose own description publishes it.** Done for the
compact lineage. Those cabinets place the setting in their published group command at a named word
and bit, with the manufacturer's own codes for the two states it has there — and the position is the
one the read map already carries, so the setting reads back where it was written. ⚠️ The attribute
has four states on the shared frame and **two** here, because this lineage gives it a single bit; a
control is therefore built from the values its own family can carry, and the other two are refused by
the encoder rather than silently truncated. Sixteen products gained a control that previously had
neither a switch nor a reading. The central cabinets, written one setting at a time, are offered it
too — provisionally, on the self-checking terms in item 42, because their number for it is derived
from the vendor's own module traffic rather than published. ⇒ **Every product that declares presence
visibly now has a control for it**: 47 on the shared frame, 16 on this lineage, and the central
cabinets on the terms above.

Not open items — collapsed to the conclusion plus a pointer. The full reasoning for each is in the
git history and, where noted, in the canonical docs and the code.

**4. `echoStatus` vs `selfCleaningStatus` — the write contract.** Settled both ways. `echoStatus`
stays read-only: a live self-verifying write is *accepted* but the bit never lands, and the app's own
control panel renders no widget for it either. `selfCleaningStatus` is honoured (a live write started
a cycle; the panel showed **CL**) and ships as a Start-self-clean button plus a
Last-self-clean timestamp. The rule this leaves: the model gives the *candidate* list of controls, a
live self-verifying write gives the *verdict*, and a panel widget predicts that verdict for free — the
four-step gate (`declares ∧ ¬invisible ∧ panel widget ∧ live write`) `panel.py` now implements.

**10. Indoor humidity.** Ships with the air-quality suite (item 37): offered where the unit declares
the probe and does not mark it invisible, zero read as absent, over-100 dropped as a sentinel. A
cross-check against a reporter's hygrometer is still welcome — withdraw rather than defend if it
disagrees.

**11. The central-air category — settled across all three of its classes.** It is **235 published
products in three architectures**, not one family: **28** compact (`8080`, a registered family that
has read and controlled since its map shipped), **20** (`0d21`) publishing the ordinary shared frame
and reachable on first report, and **187** (`0d12`) publishing no group command at all
— read, and controlled a setting at a time (item 42). Their read layout is the shared map at −19,
and it is corroborated against real reports on four anchors rather than inferred from report length.
⚠️ **Never say these units are "cloud-only".** That is a fact about the vendor's app, whose control
API picks a channel per device and falls back to the cloud for one it holds no local byte map for.
These are ordinary local appliances: they answer a status query on the LAN to anything holding their
key, and work with no internet at all. Being listed in the product catalogue means the app can
*operate* a unit, not that the unit needs the cloud.

**12. Control for the central family, a parameter at a time — shipped (item 42).** They publish no
group-set command *and* their firmware refuses that frame outright, so each setting is its own
command. The safety property is argued from that mechanism rather than copied from the group set: a
command either names an attribute the class publishes or it does not, and the appliance accepts or
refuses each one, so a command it does not implement is declined rather than misapplied. That is why
a command can be held back until it is observed and added later without disturbing anything else —
as the two vane commands were, and as presence is now.

**14. Deploy and verify the shipped rules — done.** The rules for all published products
travel with the integration and are consulted when the catalogue is unreachable (the ordinary path on
a firewalled install). Cross-checked on hardware: 19/19 comparable readings agree, the shipped and
fetched copies agree on identity, locking is unchanged and conditional. Found and fixed in passing:
diagnostics now prints the `invisible` flags (`feature_set_known`, `invisible_attributes` — empty and
absent mean different things).

**15. The compact family — see item 31.** The family's own published description carries
thirty-eight positioned fields, ten more than the derived extract it was once measured against, and
places `cloudControlStatus` / `sleepCurveStatus` at word 9. The lasting lesson: **count coverage per
family**, never against the shared map, which is generated from only one of the two published
formats.

**16. A layout that is not a displacement.** Recorded, not urgent — no model of this shape is sold in
the region served. One model elsewhere merges what the shared map spends two words on and packs the
setpoint into four bits, so a decoder assuming "every layout is the shared map at an offset" would
mis-read its setpoint/mode/fan into plausible-but-wrong numbers. The resolver's plausibility guard
(item 23) protects against it but is not a proof; a merged-first-word report is the shape to suspect.

**17. What still needs the cloud — one thing.** Checked row by row against shipped code: address,
device id, wire-model key, byte map, rules, feature set and product code all resolve offline. The
**local key** is the only cloud datum, fetched via an account sign-in and rotating several times a day
unless the unit is firewalled — which is why "fetch once, then firewall" is the working configuration.

**18. Comparison to the vendor app.** Parity with what the app can do **locally**, on every model it
supports. The app additionally displays cloud-shadow attributes it cannot decode and drives
server-side timers — deliberately declined here, because a value that did not come from the appliance
can be stale or wrong exactly when the network is. Two things this does that the app cannot: control a
firewalled unit (these modules are mDNS-silent, so the app never finds them locally), and report the
refrigeration circuit as named readings. Coverage is measured in item 35.

**20. Which model this is — why setup asks.** The appliance announces its **family** but not its
model, and nothing else recovers it: 19 of the 23 products in the reference family are byte-identical
to every observation yet carry four different rule sets. The vendor asks at pairing too, and sign-in
reads that stored answer back — which is why only a hand-made, account-less entry asks. Skipping
applies the family-agreed rules: **all** fault names and unavailability reasons survive, conditional
availability thins safely (a rule nobody disagrees on cannot make the wrong control unavailable).

**21. A reading that looked intermittent — Rule 13.** The compressor discharge line reads 80 °C
cooling hard and was discarded by a validity range chosen for room air (top 70 °C), which looked like
a failing probe for weeks. A range check on a *confirmed* field cannot prevent a decode error — it can
only hide one, as absence, which then reads as absent hardware. Temperatures are now bounded by
physics, not expectation. (`METHOD.md` Rule 13.)

**22. A command's reply must report what a poll does.** The reply after a command is a status report
with no fault frame and (once) no telemetry, so publishing it blanked those readings until the next
poll — worst on a problem sensor, where "unknown" reads as the check having stopped. Fixed three
times, once per reading; the test now guards the rule, not the three: whatever a poll publishes beyond
plain status, the reply must too, by re-reading or by holding for a bounded time.

**23. Layouts resolved from the nearest published relatives — shipped.** An unfamiliar
report is decoded at the offsets its close relatives use, keeping the one the report agrees with; the
report is the only tie-breaker (rules key on product code, declared attributes describe feature set
not layout, and both were tried and failed). Three refusals were deliberate; the read-only one was
lifted by item 30. ⚠️ Assumes item 16's stronger claim; not yet exercised against a genuinely unknown
appliance (both reference units are classic).

**24. A setting the unit ignores is not a fault — fixed.** A control discarded in the current mode
must not go *unavailable*: that means "state cannot be read" for states that read perfectly, hides
the reason, and loses the history. It stays visible and readable, and the *command* is refused with
the model's own words. The refusal lives on the entity, not in `async_send_control`
(a model marks the mode unwritable while off, and turning on *is* a mode write). The self-clean button
is the deliberate exception — an action, not a state.

**25. An outdoor reading that is not a measurement — shipped.** The outdoor probe is dormant
when the unit is off, so the board repeats its last value; published as a MEASUREMENT it dragged
long-term statistics. Now `unknown` after 30 minutes off **and** unchanged — both required. Not a
plausibility band (item 21): the value is correctly decoded and *knowably* unrefreshed, so the bound
is on age and observed stillness, never on the value looking wrong. A genuinely current reading is
never suppressed.

**26. Home Assistant's own network view is unreliable.** `aiodiscover` does not always see these units
(while the MAC sits in the host's ARP table), so the Discovered card cannot be relied on and address
resolution occasionally falls through to a UDISCOVERY broadcast. The dependable way to add a second
appliance is **Add Integration → use the account already added**, not waiting for a card. Do not widen
the manifest matcher — the matcher is correct; what feeds it is not.

**27. One family's byte map was typed, not generated — settled.** extended-46 kept a hand table (11
fields typed, 5 the map already placed omitted → dead switches and an empty declared-attribute list).
It is now derived from the map via `canonical_insert=(pivot, words)` — an insert is a *piecewise*
displacement, not the absence of one — taking its declared attributes from 0 to 54 (53 agreeing with
the manufacturer's record, none disagreeing). Two things stay explicit on purpose: the inserted
block's own tower vane/fan (from captures), and the half-degree setpoint (position from the map,
scaling from a reading — a test asserts the departure).

**28. Fan speed and the up-down vane on the 209-byte family — settled.** Both ship; w25/w26
are the **appliance's own** vane and fan (a diagnostics file's cloud record listed the towers
separately as 3/5 and 0/0, refuting the per-tower explanation they were withdrawn under). ★ Rule 14:
a fact that is overturned takes its dependents with it — a `digital_model` frozen at onboarding and a
staleness-blind agreement count cost two releases here. Open residue: `write_base_word + write_word −
1` fails for two bit-fields (listed in `_WRITE_READ_EXCEPTIONS`); only a live write settles which way,
and the readback is restored so the owner can. `windDirectionHorizontal` stays out — published like
the others but with no report position that reads it back.

**29. The 209-family group-set writes its own vane/fan, not the tower — settled from source, fixed.**
The shared frame's vane/fan slots (w1/w2.b8) are the twin **towers** on this cabinet; the appliance's
own vane and fan are group-set words 6/7 = report w25/w26 (the write↔read relation, the read map, and
the published packed order all converge). `word_count` is now 7 so the frame reaches them, and the
family obeys the write↔read relation instead of needing an exception. The only hardware residue is
confirmation that the appliance honours a 7-word frame.

**30. Control for read-only related layouts — shipped.** Control went from 590 products to **1,236 at
the time** (the current figure is **1,421** — see the table below, and do not quote 1,236).
Safe without a capture because the group-set is one frame across every published air conditioner, its
report base word is `20 + the layout's own offset` (a definition, not a fitted constant), and *which*
settings a unit has comes from its own published group-set list; families reusing a shared position
have those controls refused (item 32). A layout that publishes no list stays read-only — the safe
default. ⚠️ **Two families are read-only on positive evidence**, not for want of data: their
published order refutes the frame outright (item 38).

★ **Figures — 1,451 = 1,421 read + write · 30 read-only · 0 without a layout.** Every published
product can resolve a layout; none is refused for want of published data. The read-only 30 are the
families whose order refutes the frame (item 38). Supersedes *1,206 / 30 / 215*, *1,234 / 217 / 0*,
and "1,236 products" everywhere either appears.

| how the layout is reached | products | control |
|---|---|---|
| registered family (compact-12 · extended-46 · extended-36) | 590 | yes |
| the shared frame, corroborated by the product's own order | 644 | yes |
| no group command at all — written one parameter at a time (item 42) | 187 | yes |
| resolved, but the order refutes the frame | 30 | no |

⚠️ **"Control needs a frame, and these have no usable one" is a tempting and wrong reading.** It is
right about the frame and wrong about control: these cabinets do not use a frame at all, and the
mechanism they do use needs no order and no packing. A gate written for one
mechanism had been quietly deciding for a class that uses another.

⚠️ "Can resolve a layout" is not "will decode": the report still has to agree with exactly one
offset. What changed is that nothing is turned away before its report is even looked at.

**32. A control must not be sent to a bit a family reuses — fixed.** Eleven families keep a different
setting at a shared group-set position (self-clean↔sterilization; the twin towers at the vane/fan
slots; humidity-control↔manual-defrost; a keep-warm renamed, *not* reused). Packed by position, the
wrong function would run — the self-clean button would have started a *sterilization* cycle on 248
products. Those controls are now refused per family; everything else is untouched. Established from
the published order, every departure unanimous within its family.

**33. A whole AC category was invisible — fixed.** The product list asked the catalogue for three
categories; the app's own picker asks for none. Asked without a filter it answers 1,999 products
across 38 categories — including **window air conditioners**, which publish the ordinary command set
(30 of 33 group-set settings landing exactly where the shared frame puts them). Sixteen products
added → **1,451**. Second time a parameter *we chose* was mistaken for a property of the data (the
first was the account's region).

**34. A decode that reads nothing came back as a decode — fixed.** A uPlusId match beats report
length (deliberate — an appliance names its family key-free), which let a frame too short to reach a
family's fields read nothing, veto nothing, and return a truthy decode that poisoned the control
baseline (`report too short (93) for extended46 baseline`). `WireModel.decode` now requires both
anchors (indoor + setpoint) to have arrived. Rule 13 again — the guard existed in one caller (item
23) and now lives in `decode`, reaching every family. Found in passing: the in-session baseline gate
was classic-only, so every other family fell back to a cached blob; `is_control_baseline` asks the
registry instead.

**35. Which units are placed offline — measured.** **1,421 of 1,451** are placed from published
data alone (item 30's table). The working below is kept because it is how the remainder was resolved,
one class at a time.

The 215 that were once unplaced are **two** central-air classes plus eight others: `0d12` (187, no
group command — item 11), `0d21` (**20, which publish the ordinary shared frame**), four wall and
four window. **Twenty-eight of the 215 therefore publish a frame**, are corroborated against it, and
are reachable on first report; only the 187 are genuinely without published positions. Nor is the
*category* out of scope: 28 further central-air products are a registered family that reads and
controls. The similarity threshold must **not** be lowered to reach any of them (they differ inside
the appliance-type field) — the displacement is measured from the report instead.

★ **The 187 are read as well.** Requiring a group-set order before decoding them was evidence about
the *write* frame standing in for evidence about the *read* frame (Rule 22). They resolve from their
own report like any other appliance, and they are controlled a setting at a time (item 42). So the
current statement is: **1,451 = 1,421 read + write · 30 read-only · 0 refused** — and neither half
needed an owner to appear.

⚠️ "Placed offline" is not "will work": an unrecognised identifier falls back to report length, so
the set that works on first contact is larger; and a resolved layout still needs its report to agree
with exactly one offset.

**37. The air-quality suite — shipped.** PM2.5, CO₂, formaldehyde, a VOC index and indoor humidity are
sensors where the unit declares the probe and does not mark it invisible; zero is absent and a value
above the published maximum is a sentinel. It forced a correction: the 127-byte layout reads canonical
words 25+ **one word later** (an undescribed `targetRentTime` at report word 6), and the
declared-attribute placement now follows the layout table per report length (a test pins it to the
table's own confirmed offsets). The outdoor coil/air-intake/defrost probes stay diagnostics-only —
zero-for-life on the reference hardware, so as entities they would read `unknown` forever (a live
deploy caught and withdrew six such dead entities).

**40. A frame write must be corroborated by the product's own published order — shipped.**
The order is positional, so it can contradict the frame for a setting under its *own name* — a
departure the bit-reuse table (item 32) is structurally blind to, because that table only records
positions where a *different* attribute was placed. The audit that found it ran every one of the
1,238 published orders against the frame: every twin-tower family lists the appliance's vane, fan
**and horizontal vane** in its appended tail, and the horizontal vane — unlike the other two — was
still being offered at the frame position, where those cabinets keep tower/auxiliary bits. The
frame-path controls are now gated by `consistent_with_frame`: an order corroborates a position, or
drops the moved names (the appended-tail shape), or refutes the frame outright and offers nothing
(item 38). The audit itself ships as a test over the full bundle, so a future catalogue regeneration
that introduces a new departure fails the suite instead of quietly being offered frame positions its
own contract contradicts.

**44. A refused command was reported as SUCCESS — fixed.** Every op connection opens with
the unit's routine status push (frameType `0x06`) and alarm push (`0x04`) *before* the answer to our
own frame arrives, so a refusal always travels alongside a perfectly decodable status blob. Taking
that blob as "the unit answered with its updated state" reported the refusal as success and displayed
the **pre-command** state as the result — the setting appeared to have been accepted and the entity
did not even look stale. Detection was already right; only the precedence was wrong. The refusal is
checked first now, and the reply is still decoded so the seed baseline is refreshed either way.
Regression test `test_a_refusal_is_not_masked_by_the_routine_status_push`, confirmed to fail against
the old ordering.

**46. The co-command rules that could never fire — fixed.** Rules triggered by an on/off setting
were read in one vocabulary only, so 3,139 rules on 847 products parsed to an empty match set and
never sent their paired command (switching off did not clear self-clean, boost did not clear quiet).
The reader takes every vocabulary the settings use, the rule bundle is re-derived from the published
models, and a bundle-wide test refuses an empty condition.


### 52. The roof cabinets' big-data telemetry — SETTLED: compressor frequency and temperatures are live; power/current are not reported

⚠️ **Reworked 2026-09-01.** Three earlier readings of this were wrong in turn and are all corrected
here at the point of the claim. The truth, from the issue #12 cabinet (`AE2C52Q00`) captured with
the frame-keeping build, and from Haier's own generated UART protocol for this class:

* **The cabinet answers the telemetry query over the LAN.** `lan_frames` holds a **147-byte
  `06/7d01`** report. ⛔ Withdrawn: *"the same class of appliance answers nothing at all… what is
  missing is delivery."* The silence was the parser's, not the module's.
* **It is the documented `0D012` big-data frame, and it is DECODED (shipped).** The `7d01` payload
  is Haier's *big-data information (BIT-position format)*, whose field layout is the vendor's own
  **附录H** in `catalogue/profiles_0d12/0D012_UART通讯协议.txt`. The payload offset is confirmed the
  right one because its first eight bytes decode to the live state exactly (target 25 °C, mode cool,
  on, human-sensing 3). 附录H places `power` at Byte29, `compressorFrequency` Byte36,
  `compressorCurrent` Byte37, `compressorStatus` Byte40 — which is **word-for-word the published
  span-21 layout** one word-run past this class's extra indoor/outdoor PM2.5, CH₂O, VOC and CO₂
  readings (hence the 27-word span). That map ships as `uss._BIGDATA_VENDOR_DOC[27]`;
  `parse_extended_status` decodes the frame and the coordinator no longer writes the unit off.
  ⛔ Withdrawn: the intermediate claim that the tail was *"the classic 14-byte tail, decode with the
  classic offsets"* — the classic-offset read landed on undocumented bytes past Byte41 and only
  looked plausible while idle.
* ⛔ **The 附录H byte positions were WRONG for this product** (corrected once more, from the wire).
  The vendor appendix places `power` at Byte29 and `compressorFrequency`/`compressorCurrent` at
  Byte36/37, and those read a flat zero on the hardware. The real running block is the **classic
  engineering trailer at the END of the frame** — the identical block the 141-byte wall units carry,
  six bytes further along a 147-byte report — so it is decoded from the frame length, not from the
  appendix offsets.
* **SETTLED on three live captures** (once the build keeps polling, the reporter's downloads are
  live): the readings TRACK the compressor exactly — `compressorFrequency` **0 Hz idle → 40 cruising
  → 103 cooling hard**, evaporator coil **25 → 17 → 10.5 °C** (colder under load), discharge line
  **33 → 49 → 79 °C** (hotter), compressor **off → on → on**. These four (plus fan state) are real
  and shipped. Textbook refrigeration physics, self-consistent across the three states.
* **Power and current are NOT reported by this three-phase class.** `power` reads a flat 0;
  `compressorCurrent` is railed at its documented full-scale ceiling (`0x01FF` = 51.1 A — the vendor
  model gives it a 9-bit field, 0.0–51.1 A — unchanged whether the compressor is off or at 103 Hz,
  which no real current does). The vendor model documents **only** `power` (W) and `compressorCurrent`
  (A) here — **no voltage, no per-phase reading, no energy/kWh counter anywhere** in the 0D012 model
  (three-phase appears only as a *fault* code, `threePhaseSupplyErr`). So power cannot be
  reconstructed on-device, and a supply voltage would not help (there is no real current to multiply,
  and the compressor drive frequency does not convert to watts). Those two entities are retired for
  such a unit (`coordinator`, keyed on the decode dropping them) rather than shown as a constant that
  tracks nothing. Item closed for these cabinets; real energy needs an external meter.
* **Every path checked — the enumeration behind the negative** (so "no power" is scoped, not
  assumed): the vendor's Appendix C is the COMPLETE 0D012 command table and holds exactly **three**
  commands — `4D01` getAllProperty (→ 6D01), `4DFE` getBigDataFrame (→ 7D01), `5D01` onOff set.
  There is **no 7D02, no 4C01/5C01 per-attribute read, and no "detailed running data" query** in the
  61-page protocol. The 62-field 7D01 model's only load/electrical fields are `power` (W),
  `compressorFrequency` (Hz) and `compressorCurrent` (A) — **no voltage, per-phase current, power
  factor, reactive power, second current or kWh accumulator anywhere**, in 7D01 or the 101-field
  6D01 status. So there is no fuller frame or channel we have not read.
* **The board DOES measure current and voltage — it just never exposes the value.** The 6D01 model
  carries the electrical quantities only as PROTECTION FAULT BITS: `powerProtection` (over-voltage),
  `outdoorACProtection` / `outdoorDCProtection` (over-current), `ctCurrentErr` (CT abnormal),
  `threePhaseSupplyErr`. A unit needs a CT and voltage sensing to raise those, so the measurement
  exists internally — it reaches the protocol only as a threshold trip (a named fault we already
  surface), never as a readable analog value.
* **The two fields are real, and populated on OTHER classes.** Prior art issue #39 (a single-phase
  residential Casarte, smartAir2 family) sends live, varying `power` (0 / 256 W) and
  `compressorCurrent` (0.0 / 76.8 / 153.7 raw) on the same two fields — so they work on Haier
  hardware in general; this three-phase central class simply leaves them empty (`power` 0) and
  railed (`compressorCurrent` at its documented max `0x01FF` = 51.1 A). Why frequency but not amps:
  of the model's three load fields this class populates only the frequency.
* **Why the app shows nothing yet the cloud could:** the protocol routes 7D01 "only to the cloud
  server" by design (`user data → all endpoints; big-data → cloud only`), which is why the app's
  local view has no telemetry; the module relays 7D01 to a LAN controller anyway (that is how we get
  it), and the frame it relays is the BOARD's own — its temps and frequency track load, so the empty
  power/current are the board's own empties on this class, not a module placeholder or a richer
  copy the cloud keeps back.
* **The HARDWARE EPP was checked, not just the cloud template — they are byte-for-byte identical.**
  The board's own UART protocol document, the APK-bundled EPP wire models, the big-data
  function-model PDF and the master/slave comms spec all define the SAME 63 big-data fields at the
  SAME byte positions (`power` Byte29-30, `compressorFrequency` Byte36, `compressorCurrent`
  Byte37-38); the cloud template dropped nothing. There is **no separate diagnostic/engineering
  frame** — the "run-monitoring data area" (运行监控数据区) IS the 7D big-data set, spec'd as
  "synced to the app via the message platform, not pushed in the status loop" (the cloud routing
  above). Residential AC classes (`02011/02012/03012`) carry the **identical** three electrical
  fields and no voltage either — home units are not privileged. A `380 V` / phase scan of all four
  LAN frame types across five captures found nothing (the one 0xC0=384 candidate is a fixed
  status-structure flag, constant across every state and `0x3f` on the wall units).
* **The platform CAN model readable voltage — every AC class deliberately omits it.** Washing
  machines (`05001*`, `voltage` 0–500 V), range hoods (`0900*`, `voltage` 85–285 V), fridges (DC fan
  drive voltages) and water heaters (`dcVoltage`) expose a readable voltage on their own 7D01. That
  the fridge/washer/hood models carry it while EVERY Haier AC model (residential and the central-AC
  sibling `0D021`, which shares this template) omits it is strong evidence the omission is model
  design, not truncation. The board monitors voltage/current for outdoor-unit protection — proven by
  the errCode enum (7 power over-voltage · 26/28 AC/DC over-current · 30 CT abnormal · 37 three-phase
  supply) — and exposes that monitoring **only as the protection verdict (an alarm bit)**, never the
  measured value.
* **Honest residue (needs a capture, not more reading):** the on-disk `0D012_UART通讯协议.txt` is the
  GENERIC template-generated document, not the reporter's specific OEM outdoor board
  (`HCFI-38XTR32F`/`AE2C52Q00`). A particular OEM board could in principle define extra 7D fields —
  but the spec forbids the big-data area from duplicating anything, and every source (generic doc,
  both public templates, all residential + commercial AC EPP models) converges on the same three
  electrical fields, so it is a long shot. Confirming or refuting it needs a **UART capture** of that
  board (module↔board), which this project has never taken; prior-art issue trackers are the capture
  corpus if one surfaces. ★ **Simulator dig (2026-09-01) added actionable items** (memory
  `esphome-hon-source-is-the-decode-reference`): **compact-12/smartAir2 gains 5 controls we don't
  ship** — display, lock, ten-degree, half-degree, temp-unit (byte/bit-exact) — plus a `room_humidity`
  SENSOR; a concrete feature add for the 16 compact-12 products. The 7 hON `0d12` single-param
  candidates are double-confirmed. And `GET_DEVICE_CONFIGURATION 0x7C→0x7D` is a documented but
  uncharacterized per-unit config exchange — a live `0x7C` probe is the standing lead for the
  per-unit feature gate (likely module-blocked over :56800, untried). **RE of the vendor's E++ tool** (2026-09-01) surfaced two endpoints we do not use — a
  function-model file (`resource/funcModelFile`, parallel to the `logicLimit` we fetch) and the
  per-board PCB E++ file store — but the first needs a signed request and serves the same class
  model we already have (no voltage), and the second is behind the developer login and scoped to the
  OEM's account. So neither reaches the electrical data; the board↔module UART tap (decoded with the
  vendor's own U+串口监听工具, whose E++ crypto could be recovered from `SerialAssistant.exe`) remains
  the only avenue, and it needs physical access to a cabinet. ★ **Update — the board-direct case is already in the prior art.** esphome replaces the
  Wi-Fi module with an ESP on the board UART, so its captures ARE board-direct; prior-art issue #19
  (HaierProtocol 0.9.20, the hOn family) logs raw `7D01` frames off the board whose current field
  reads the SAME railed `01FF` we see via the module relay. So a serial tap would NOT recover the
  electrical data on an hOn unit — the board itself sends the placeholder; esphome-at-UART sees what
  we see, and reported no usable current for that unit. (The smartAir2 Casarte's live power/current
  is an older protocol on a single-phase board — not transferable.) ★ **Closed: 47/47 hON frames rail the current.** Every genuine hON `7D01` big-data
  frame in the prior-art corpus — 47, residential `U-AC` and commercial `U-BAC` (the `0d12` family's
  own device name, #115) — has `current`=`01FF` and no usable power; ZERO live. The railed field is a
  HON-PROTOCOL-WIDE property, not our unit or the module; the one live capture is smartAir2. No sliver
  remains. ★ **esphome confirms the group-set NACK too:** prior-art #115 is a `U-BAC` unit
  (commercial hON = our `0d12` family); esphome sent a group-set `60 01` and got `type 03` INVALID,
  code `00 01` — U-BAC/`0d12` REFUSES the group-set, exactly our finding. esphome has no
  single-param fallback, so it can only READ these cabinets; our `5Dxx` single-param path is the
  correct one and a genuine differentiator. (It also means esphome never requests big-data `4DFE` on
  U-BAC in that log — 0 occurrences — consistent with the group-set being rejected first.) ★ **The esphome hON SOURCE (not just its logs) is the register map we'd been reconstructing.**
  `esphome/components/haier` (`hon_packet.h`) defines the single-parameter `DataParameters` register
  (`CONTROL` + `0x5D00+id`, our exact write path); it matches our 9 confirmed 0d12 ids bit-for-bit
  and adds the standard ids `0x07 USE_FAHRENHEIT` (2nd witness for the withheld `5D07 tempUnit`),
  `0x09 DISPLAY`, `0x0A TEN_DEGREE`, `0x0D SELF_CLEANING`, `0x16 BEEPER`, `0x17 LOCK_REMOTE`,
  `0x1B SLEEP` — residential-derived CANDIDATES to probe on a 0d12 via the provisional mechanism.
  So "the 5Dxx numbering is not derivable" was true of HAIER'S PUBLISHED DATA; esphome's RE of real
  devices derives the STANDARD register (the enum GAP at 0x08 still neither confirms nor denies the
  provisional `5D23` presence, and it holds nothing for 4-sided vanes / ampereControl / powerSource).
  esphome also confirms NO voltage/energy field in hON (3rd source), and names fields we do not yet
  surface — `room_humidity` (status byte12), the expansion valve as a %, and 51 named alarm bits
  incl. the electrical/three-phase protections a 0d12 raises.

  ★ **Cross-checks done 2026-09-01 (esphome source):**
  * **Alarms — VALIDATED 51/51.** Our `ALARM_LABELS` is position-for-position identical to esphome's
    `HON_ALARM_MESSAGES` (all 51), and RICHER — we carry the service codes (`F1`/`E2`/`E14`/`E18`)
    esphome lacks; the only nit is esphome's "CBD" typo at idx13 where we correctly say "PCB". So
    "fault names right through position 50" is now independently confirmed for every bit.
  * ⛔ **~~Seven NEW candidate single-parameter controls for `0d12`~~ — SIX ARE PHANTOMS, and this
    bullet's attribute names were guesses the configuration later corrected.** Prior art's
    `DataParameters` ids `0x07/09/0A/0D/16/17/1B` are, per the manufacturer's own configuration for
    this class, `tempUnit` · `screenDisplayStatus` · `10degreeHeatingStatus` · `selfCleaningStatus` ·
    `echoStatus` · `lockStatus` · `electricHeatingStatus` — not the `muteStatus` / `silentSleepStatus`
    this bullet guessed for `0x16` / `0x1B` (those are `19` and `18`, and `muteStatus` was already
    shipped). **`0x07 tempUnit` ships**, because 19 products declare it. **No `0d12` product declares
    any of the other six**, so the declaration gate would never surface them and wiring them would be
    phantom controls; they are held in the register validator's byte-map-only list, which trips if a
    configuration re-sweep ever makes one declarable. The same list holds `0x08`
    `halfDegreeSettingStatus` — see item 57, and note the scope of "declared by no product" there.
    The register today is **ten settled ids plus five provisional** (presence `5D23` and the four
    cassette louvres).
  * **Per-unit feature detection — NOT in the hON handshake** (dug esphome, 2026-09-01). The
    device-version answer's `functions[1]` bitmap is PROTOCOL negotiation (CRC/interactive/multinode/
    roles), not an appliance-feature manifest; esphome gates nothing on it. Human-sensing has no
    capability marker (result field reads `00`=N/A whether or not a PIR is fitted). The only untested
    place a manifest could live is the config frames `0x7C`/`0xE9`/`0xEB` — likely module-terminated
    over `:56800` (like `0x61`/`0x70`), but `0x7C` is an untried probe on a live unit (⛔ disable an
    entry first). So the per-product presence/feature gate must stay panel-derived or class-based; the
    wire offers no per-unit capability read.

These cabinets answer a query for their detailed running data when it is asked over the wire inside
the appliance — a recording of one shows the manufacturer's own module asking nine times and the
board answering all nine, with a frame that is populated and changes between recordings.

⚠️ What is in that frame is only partly known, and it does **not** obviously include power. Its
first three quarters are the ordinary status report repeated, leaving seven readings of which two
are always empty and one is a fixed placeholder. Of the four that carry anything, one behaves like a
temperature — lowest while cooling, highest in fan-only — and none behaves like a wattage. On the
wall-mounted models the same seven readings carry power, current and compressor speed; on these they
appear not to.

Checked against the machine's own state, which each recording carries: three of the nine were taken
with the unit cooling and six were not, and **not one reading distinguishes them**. On the
wall-mounted models those same readings are the most load-dependent numbers in the protocol.

So the appliance answers, and its answer contains nothing that behaves like power or compressor
load. No description of this family's detailed-data layout exists anywhere we hold, so this is a
reading of how the numbers behave rather than a decode — and "cooling" is inferred from the setpoint
being below the room temperature rather than observed. A recording taken beside a meter reading
would settle it outright.

**What would close it:** a recording of that frame taken beside known conditions — the compressor
running, then off. That is how every other family's power reading was placed.

ⓘ ⛔ **Superseded 2026-09-01.** This said the vendor's *design template* described a 62-reading
frame that "does not line up — power lands on an empty word", concluding no description placed
anything. That was the full-function template read against the wrong offset. The class's real
big-data layout IS documented — 附录H of the generated UART protocol — and DOES line up (power at
Byte29 = word15, the span-21 position); the earlier mismatch was the analysis, not the data. What
remains open is only whether the board fills those documented fields when the compressor runs.

### 51. The cumulative energy counter is not read on a relative's layout

An air conditioner whose layout is worked out from a close relative's gets eleven readings, and the
cumulative electricity counter is not one of them. A unit whose own family map is registered does
get it.

This is not currently costing anyone: of every report attached to this project, the only appliances
decoded from a relative's layout are the central cabinets, and none of those publishes a counter at
all. It is written down because that is a fact about the reports we happen to hold rather than about
the design.

⚠️ It is deliberately not added on spec. The counter is a 32-bit value that extends *backwards* from
its stated position, so on a layout that carries extra words in the middle it lands somewhere no
report has ever confirmed — and a wrong lifetime-kWh figure in someone's energy dashboard is worse
than no figure at all.

**What closes it:** one diagnostics file from an air conditioner that is decoded from a relative's
layout *and* whose model lists the counter. The value can then be checked rather than assumed.

### 62. Replicate the technician app's local surface as a CLI or web UI, for fully offline users

> ## ✅ TIER 1 IS BUILT AND GATED (2026-09-10) — `tools/re/ble_advert.py` + `tools/re/discover.py`
>
> The discovery tier below is no longer a proposal. Two tools, both lint-clean, both self-tested,
> **neither able to write to an appliance** — they carry no code for a BLE connection, GATT,
> pairing, OTA or the factory-test channel, and `discover.py` never opens `:56800`, so it does not
> contend with Home Assistant for the single control session.
>
> * **The advertisement decode now exists as code rather than prose.** Both TLV encodings, the
>   `"U+"` header, fragment + scan-response reassembly, all 22 types, the 11 named flag bits, the
>   ExtField in memory order. Its self-test asserts **the four independent reality checks**
>   (`LocalkeyValid`, `Controllable`, `Configurable`, `isNeedAuth`) and pins `APConnected = 0`,
>   which §23 then resolved: the module **never sets that bit**, so it is an unimplemented field
>   rather than a wrong reading.
>   Mutation-tested: two deliberate corruptions each produce four failures.
> * ⟦LIVE⟧ **Run against both units 2026-09-10** — joined `LAN+BLE` on the MAC, `psk0`, `A91R6`,
>   `e_4.3.00`/`R_6.0.01`, `cloud_state 1006`. Units left as found.
>
> ★★ **AND IT MEASURED THE GAP TO TIER 2, which is the more useful output.** Against the technician
> client's own LAN property vocabulary (`cae_sr_uwt_reset_property_list`, `FW_BLE_ADVERT_DECODED.md`
> §21 §2), the key-free surfaces fill **7 of 22** properties. The **15** out of reach are
> `Protocol · ProtocolVers · ProductCode · swType · Busying · ReadyToBind · SupportPing · UDPPort ·
> OfflineReason · IsMeshGW · ComplexDevType · SupportGetDevVerInfo · SUWTLibVer · SUWTDevVer ·
> SupportAuxiliaryConfig`.
> ⇒ **the cheapest instrument for most of them is LAN `0x5DC3` device-info** (reply `0x5DC4`,
> 0x10 + 0x10 + 0x40 bytes of device/config fields) — a **read** on a channel we already speak, and
> the natural content of tier 2. ⛔ Not sent by either tool.
> ⛔⛔ **TESTED ⟦LIVE⟧ 2026-09-10 AND THE RECOMMENDATION ABOVE IS WITHDRAWN.** `0x5DC3`, `0x65BB` and
> `0x659D` each **RESET the connection after send** — **bare AND inside a fully established uSS
> session** (hello → hello_resp with `localkey_version 48` verified → hello_done → done_resp), with
> the control that the very handshake our integration uses every 30 s worked on that same socket.
> ⇒ **the whole `0x4E20+` command family is unreachable on these units**, so tier 2 has **no LAN
> instrument** and those 15 properties stay out of reach. ⚠️ **[U] why** — a role byte, or a different
> listener. `captures/module-firmware/analysis/FW_GATT_LIVE_2026-09-10.md`.
> ⓘ Counting note: §21 prints 24 strings, two of which (`UWT_DEV`, `UWT_DEV_SAFE`) are its own
> identification of the *values* of `Protocol`; hence 22 distinct properties. If that split is ever
> shown wrong the count is 24 and nothing else changes.
>
> ▶ **What tier 1 still lacks:** a scanner. This host has no Bluetooth adapter, so `discover.py`
> reads a scan **log** (the C# harness in `captures/ble-scan-2026-09-09/`) rather than driving a
> radio. A packaged tool for an offline owner needs a `bleak`-based scanner on a machine that has
> one — bounded work, no new protocol knowledge required.

**The idea (owner, 2026-09-10):** everything the uAssistant technician app can do to a unit *without
the cloud* is now enumerated, and none of it needs Haier's servers at the moment of use. Packaging
that as a command-line tool or a small local web UI would give an owner who keeps their appliances
firewalled the same diagnostic and control surface a technician has — with no account, no internet,
and nothing installed on the appliance.

**Why this is now realistic rather than speculative.** The surface is mapped, not guessed:

* **97 `cae_localc_*` local-control functions** crawled with their literals
  (`captures/module-firmware/analysis/APP_TECHNICIAN_API.md`) — security/key, bind, BLE bond and
  auth, BLE transport, OTA, network/domain, device I/O, proxy lifecycle, mesh.
* **The BLE GATT profile** — six services, 30 characteristics, every UUID from Haier's own symbols
  (`FW_BLE_GATT_SURFACE.md`), including `ff20` **EPP req/rsp**, i.e. the same appliance frames we
  already build for `:56800`.
  ⚠️ **SCOPE CORRECTION ⟦LIVE⟧ 2026-09-10:** that is the profile **as the phone library defines it**.
  The enumeration on Downstairs found **`ff00` AUTH and `ff50` STP served, and `ff10`/`ff20`/`ff30`/
  `ff40` ABSENT**. ⇒ **`ff20` is not available on this build**; EPP over BLE would ride ucom `0x22`
  over **STP** (`ff50`/`ff53`, both served and writable) instead. `FW_GATT_LIVE_2026-09-10.md`,
  `FW_BLE_GATT_SURFACE.md` §29.2.
* **The LAN command set** — all 13 commands on `:56800` decoded (`FW_LAN_SET_GATEWAY_26013.md` §10).
* **The BLE scan-result field set** — `prepare_search_dev_info` … `prepare_search_ble_dev_event`,
  58 keys, and the Java model `BleGbDeviceAddNotify` (`FW_BLE_ADVERT_DECODED.md` §17). A scan list
  showing RSSI, config mode, bind state, key validity and the ExtField versions is buildable from a
  **passive** scan plus one `SCAN_REQ`.
* **UDISCOVERY** already gives deviceId, uPlusId, firmware, SDK version and cloud state, key-free.

**What it would plausibly offer, in rising order of risk:**
1. **Read-only, zero-touch:** discovery (UDP `:7083` + BLE scan), device inventory, firmware/hardware
   versions, cloud state, bind state, the decoded ExtField, RSSI. *Nothing is written.*
2. **Read-only over an authenticated session:** the LAN reads we already speak (status, extended
   report). ⛔ **`0x5DC3` device info and `0x65BB` bind info are NOT available** — measured
   ⟦LIVE⟧ 2026-09-10: both reset the connection even inside a valid uSS session (see the correction
   in the tier-1 box above). **Tier 2 is therefore thinner than this list implied.**
3. **Control:** what this integration already does — the EPP write path — but exposed outside Home
   Assistant, and optionally **over BLE `ff20`** rather than the LAN.

⛔ **Explicitly out of scope, and the reasons are on file:** OTA (`ff3x`, the only brick-capable
action), the factory-test channel, `ff0a`/`ff09`/`ff12`/`ff15` writes, and anything that pairs or
bonds. Those stay under the standing stop rules regardless of how convenient a UI would make them.

⛔ **CORRECTED 2026-09-10 (owner: *"arent you confident in the write side?"*) — I was, and I wrote
the gate too broadly.** The caution below belongs to **the BLE transport**, not to writing.

✅ **The LAN write path is not speculative — it is the shipping product.** `packages/` writes
setpoint, mode, fan and vane to two real appliances every day; **727 tests green** (2026-09-10);
v0.69.1 is deployed and was **live-verified** (setpoint 23→24→23 on Upstairs, confirmed by the unit's
own next poll). The single-parameter `5Dxx` path is confirmed **per attribute on real hardware** —
`5D01` (`I&G`) accepted with a status report, `5D02` (`G`) refused `0x03/0x0000`, **same unit, same
session**. And writes are **self-verifying**: the reply frame type is the acceptance oracle
(`02` accept / `03` refuse), with per-product reason codes decoded. ⇒ **LAN control belongs in tier 1
beside discovery, not behind it.**

✅ **AND THE BLE TIER JUST GOT CHEAPER (2026-09-10):** EPP over BLE is wrapped with the **same uSS
cipher and the same localKey** as our `:56800` biz-data, with the sequence number pinned to **0**
(`FW_BLE_GATT_SURFACE.md` §19 — `psk0_encrpyt_data` → `safekey_2_key` → `uss_encrpyt_data` →
`uss_encrpyt_data_with_sn(sn=0)`). ⇒ **no new cryptography is needed**: `haismart_hrdp.uss.biz_encrypt`
/ `biz_decrypt` work unchanged at `sn = 0`, and the existing EPP frame builders are reusable. **Only
the transport is new.**

⚠️ **The gate that IS real, and it is narrow: the BLE transport.** **No byte has ever been sent over
BLE to these units**, `ff20`-carries-EPP is inferred from characteristic names, and whether they serve
the `ff00` family at all is `BLE_ROUTE_UNKNOWNS.md` **A1/A2**. ⇒ **BLE** is where "read-only first"
applies, and one passive GATT enumeration answers both unknowns.
ⓘ And the exclusions above (OTA, factory-test, `ff0a/09/12/15`, pairing) are **risk policy, not
uncertainty** — they stay out however confident we are.


## 64. ⟦LIVE⟧ ★★★★★ BLE control is PROVEN — scope it, and decide on disclosure

**2026-09-11.** An **unpaired, unbonded, UNAUTHENTICATED** BLE peer changed a unit's setpoint and
restored it, verified over the LAN both times. The chain is in
`captures/module-firmware/analysis/FW_BLE_FIRST_CONTACT_2026-09-11.md` §13 and the builder is
`tools/re/ble_control.py` (private tree only).

⇒ **This makes `FUTURE_WORK` 62 (a technician-style offline CLI) realistic for CONTROL** — the BLE
half needs no account, no internet and no credential. ⛔ It does **not** make takeover realistic:
installing a localKey we choose is a different operation and is unchanged.

**Open, all cheap and on the same rig:**
1. Other EPP commands over BLE — mode, fan, power, swing. Only `grSetDAC` setpoint is proven.
2. The second unit; persistence across a power cycle; a never-paired unit.
3. Whether the module will *report* state over BLE (the outbound callback table at `0x100100a0` —
   only `0x13 CFG_STATE RPT` is observed populated).

⚠️⚠️ **And a decision that is not engineering: DISCLOSURE.** Anyone in BLE range can command these
units with no credential. That is more serious than the three items already on that list (the
`*-sessionKey` API, the RNG with no hardware entropy, the `libOSDK` debug localKey). **Owner's call.**
⛔ **Nothing beyond the existing private tooling should be published**, and the builder must not go
into the public repo.

## 65. A unit can un-provision ITSELF on its mainboard's orders — `FD` 清除用户信息

**2026-09-13, from the vendor UART spec + prior-art captures** (`captures/module-firmware/analysis/`
`FW_LOCALKEY_STORE_2026-09-11.md` §70; `docs/PROTOCOL.md` §10.8).

In **master-slave mode** — which is almost certainly what the owner's units and the `0d12` cabinets
run (three independent lines agree; `docs/UART_SYSTEM_FRAMES.md` §9a) — the Wi-Fi module **polls its
own appliance mainboard** for management instructions, roughly once per cycle: frame **`FC`** out
(no payload), frame **`FD`** back (6 bytes). One of those bytes is **清除用户信息**, and the value
**`0x02`** means *"清除模块中用户配置的WIFI信息等"* — **clear the user-configured Wi-Fi settings.**
A sibling byte, **解除绑定状态 = `0x01`**, unbinds the appliance from its account, and **模式切换**
can push the module into softAP / smartlink / WPS setup.

⇒ **What this means for the integration:** an appliance can leave the network *without anything on
the network doing anything wrong*. From Home Assistant's side the failure looks like a unit that
simply **vanishes** — no error, no key rotation, no cloud event, no reachability at
`192.168.x.x:56800` — because the module has discarded its Wi-Fi credentials and gone looking for a
provisioner. A user would report it as "the integration stopped working"; the cause is on the other
side of the module, in appliance firmware we have never held.

**Why it is filed rather than fixed:** nothing here is actionable in code today.
* ⛔ **Never observed in the wild.** In every prior-art capture the field is `0x00`: a `0212` cabinet
  answers `00 00 00 00 00 00` and a `0d12` cabinet `00 00 00 01 00 00` (that `1` is 强制进设置, which
  the spec says is **ignored** unless 模式切换 selects a config mode). **93 polls, 93 answers, not one
  requesting anything.**
* ⛔ **We cannot see it happen.** It is board↔module UART traffic; it never crosses `:56800`, and this
  project has never taken a UART capture.
* ⛔ **And we could not prevent it if we did** — it is the appliance obeying its own mainboard.

**What would make it actionable, cheapest first:**
1. **A user report matching the signature** — a unit that disappears from the LAN and, on inspection,
   is back in pairing mode (Wi-Fi LED flashing rather than solid) with **no** router/DHCP change and
   **no** power event. That distinguishes it from the ordinary causes (DHCP lease moved, AP band
   steering, the unit unplugged).
2. If it ever recurs on one unit: the diagnostic is the **Wi-Fi LED** — solid = paired and connected,
   flashing = config mode — which needs no tooling at all.

**What to do with it now:** keep it in `TROUBLESHOOTING.md`'s vocabulary. If a user reports a unit
that vanished and came back needing re-pairing, this is a documented mechanism, not necessarily
something they or we did wrong. ⚠️ Do **not** put it in user-facing docs as a likely cause — it has
never been observed, and the ordinary explanations are overwhelmingly more common.
