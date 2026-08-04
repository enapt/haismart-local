# Supported devices

Model number alone is **not** a sufficient compatibility key — the Wi-Fi module and its firmware
matter at least as much. Two units with the same model sticker can behave differently if one shipped
with a newer module.

**You do not need to write any of that down.** The integration knows it, and a diagnostics download
carries it under `device_identity`: the `model_number` off the sticker, the `product_code` it is
keyed on, the `uplus_id`, and the module's `module_firmware` and `module_sdk_version` as the
appliance itself reports them. **Settings → Devices & Services → Haismart → ⋮ → Download
diagnostics**, and attach the file.

(If your unit is not yet added, or will not connect at all, then the model number off the sticker is
the useful thing to quote.)

The integration builds itself from the model description your AC's own cloud profile provides, so a
model missing from this table will very likely still work. The table records what has actually been
**observed**, not the limit of what is supported.

Since **v0.35.0** that holds even for a report layout nobody has ever sent in: a unit whose Model ID
resembles published models close to it is read using the offsets those relatives use, provided the
report agrees with the result. Such a unit **reads but does not command** — control still needs a
layout confirmed on real hardware, which is what the capture procedure in
[`docs/new-model.md`](docs/new-model.md) provides. So an absence from this table increasingly means
"nobody has told us", not "it will not work".

A diagnostics download from a unit on a recognised layout now reads **every attribute that unit
declares** and prints it beside the values the unit publishes through its cloud profile — two
independent sources for the same readings. That is usually enough to confirm a model belongs in this
table without anyone here owning one.

## Confirmed working

| Product code | Model | Report | Heat | Notes |
|---|---|---|---|---|
| `AACRL2E00` | PRO X INV-42/3PH | 125-byte classic | ✅ | `deviceType 0201201d`, OUI `24:E8:CE`. Reverse-cycle wall-mounted split; the reference unit for heat support. |
| `AAC1UKZ01` | HSU-24VRRA03TF | 127-byte classic | ❌ | `deviceType 0201203a`, OUI `AC:B7:22`. Cooling-only. The original unit this project was written for. |
| `AAC1UKZ01` | HSU-12HFMF/013WUSDC(W) | 117-byte compact-12 | ✅ | OUI `04:E2:29`. A **different wire family** — all attributes (sensors included) are packed into one word array. Reading and control both confirmed on real hardware. |
| `AAD180E00` | HSU-12KCROC(IN)-R32 | 165-byte extended-36 | ✅ | `deviceType 02012036`. The classic bit map **displaced by 19 words**: the report carries a voice/media block first, so the climate attributes start at word 20. **Confirmed on hardware by the reporter** (2026-07-29): reading and full control — temperature, modes, fan speed, health, display light. |
| `AAC1UKZ01` | HS-25VRB03 | 175-byte extended-36 | ❌ | Module `MK-QTWiFi3.1S`, firmware `e.4.3.00` / `R_6.0.01`, Malaysia. The extended-36 map with five further words of counters on the end. **Confirmed on hardware by the reporter** (2026-07-31): reading and full control — power, mode, temperature, fan speed, both swings, no snap-back. Its report carries **live power in watts**, which no other family here reports directly, plus a working **cumulative energy total in watt-hours** — the only unit here with both, so it feeds the Energy dashboard with no helper — and it publishes both vanes' positions. |
| `AAC1UKZ01` | HSU-24HFAB/013WUSDC(W)-T3 | 209-byte extended-46 | ✅ | OUI `5C:24:1F`. Extended-36 with a further ten-word block inserted at word 25, and a **half-degree setpoint**. Reading confirmed against three captured states, fan speed included — it answers from the inserted block rather than the usual word. Control covers power, mode and temperature; fan speed is read-only here and the swings are not settled. |

> **"Report" is the status layout, not just a length.** Most models share the *classic* family (the
> setpoint/mode/fan/power in a leading control-word block, sensors after it); the length only varies
> with how many control words the model carries. A few models use a genuinely different packing
> (**compact-12**) or the classic packing at a different offset (**extended-36**, **extended-46**),
> which the integration recognises and decodes automatically. Full inventory:
> [`docs/report-layouts.md`](docs/report-layouts.md).

## What the Eco levels actually do

On units with a multi-level Eco control (the remote shows **L1 / L2 / L3**), the levels are **current
limits on the compressor**, not comfort tweaks — and a **higher number is more restrictive**, which is
the opposite of what most people assume.

Measured on an `HSU-24VRRA03TF` (23 200 BTU, 220 V) cooling a room from 28 °C with the setpoint held
at 22 °C, so the unit was working hard and each level had something to cap:

| Eco | Power | Current | Compressor |
|---|---|---|---|
| L1 | ≈ 1350 W | 6.0 A | 66 Hz |
| L2 | ≈ 1130 W | 5.0 A | 55 Hz |
| L3 | ≈ 800 W | 3.5 A | 40 Hz |
| Off | ≥ 1350 W | ≥ 6.0 A | ≥ 66 Hz |

So **L3 draws about 41 % less than L1** — and cools correspondingly more slowly. If a room is not
getting cool enough, an Eco level is worth checking before anything else. The caps are round current
values, which is a hint at the feature's origin: it is designed for running an air conditioner off a
generator or a limited supply, and doubles as an energy saver.

Two caveats on the numbers: they are one unit at one ambient, so treat the ratios rather than the
absolute watts as the useful part; and the "Off" row is a lower bound, because the compressor was
still ramping when it was measured.

If your unit's Eco behaves differently, please say so in an issue — levels may well be scaled per
model or per capacity.

## Known NOT to work

These pair with the **hOn** app. Their Wi-Fi modules refuse the connection outright
(`ECONNREFUSED` on port 56800) — there is no local listener at all, so this is not something that can
be fixed here. Use [Andre0512/hon](https://github.com/Andre0512/hon) instead.

`AS35TAMHRA-C` · `AS50S2SF1FA-BH` · `AS25S2SF1FA-BH` · `AS352SF1FA-WH` ·
`adh125h1erg` (module `HI-WB101DEI`) · `1U71RACFRA` (SmartHQ)

## Older SmartAir2 units

Units pairing with **SmartAir2 / Smart Clima** use the same port with an older, unencrypted variant
that has no local key. They are not supported here; see
[oxystin/homebridge-haier-air-conditioner](https://github.com/oxystin/homebridge-haier-air-conditioner),
which lists `AS09QS2ERA-W`, `AD35S2SS1FA`, `HSU-07HT103/R2`, `AS50S2SD1FA-CL` and others as working.

Worth noting from that project: module `KZW-W002` firmware `e_2.3.12` works while `2.5.14` does not
— a concrete example of firmware mattering more than the model number.

## Report yours

Whether it works or not, please tell us — use the
[new model report](https://github.com/enapt/haismart-local/issues/new?template=new_model.yml)
issue template, or follow [`docs/new-model.md`](docs/new-model.md).
