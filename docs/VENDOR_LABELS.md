# What the manufacturer calls things

Every user-visible name for a mode or a fan speed in this integration is the **manufacturer's own**,
not a translation of ours. This page records where they come from and what was decided where the
vendor's vocabulary and Home Assistant's do not line up.

## Where they come from

The vendor's app ships its interface strings offline, as a language bundle inside the APK
(`assets/PresetResPkg/mPaaS@uplanguage@<version>.zip`). Inside it is one JSON per locale — **18 of
them** — each keyed by module, and the air-conditioner vocabulary is the `seasia_home.AC_*` block.
Reading the Chinese value of a key and then the same key's English value gives the manufacturer's own
English for the exact label its models publish.

That matters because the published device models describe an enum value only in **Chinese**
(`超强风`, `微风`, `静音风`…). Translating those ourselves would be a guess dressed as a fact — and this
project has already paid for one of those, when a fan-speed enum was mapped from a plausible reading
rather than from the model's own descriptions. The language bundle removes the guess entirely.

## The air-conditioner vocabulary

| model description | vendor key | vendor English | our token |
|---|---|---|---|
| `超强风` | `AC_super_high` | **Boost** | ⛔ *not shipped — see below* |
| `高风` | `AC_high` | High | `high` |
| `中高风` | `AC_mid_high` | **Mid-high** | `mid_high` |
| `中风` | `AC_mid` | Mid | `medium` ⚠️ |
| `中低风` | `AC_mid_low` | **Mid-low** | `mid_low` |
| `低风` | `AC_low` | Low | `low` |
| `微风` | `AC_small` | **Breeze** | `breeze` |
| `静音风` | `AC_quite` | **Silent** | `silent` |
| `快速风` | `AC_quick` | **Quick** | `quick` |
| `自动` | `AC_Auto` | Auto | `auto` |
| `制冷` | `AC_cool` | Cool | `cool` |
| `制热` | `AC_heat` | Heat | `heat` |
| `除湿` | `AC_dry` | Dry | `dry` |
| `健康除湿` | `AC_health_dry` | **Healthy Dry** | `health_dry` |
| `送风` | `AC_fan` | Fan | `fan_only` |
| `节能` | `AC_ECO` | **ECO** | `eco` |
| `智能` | `AC_smart` | Smart | `auto` |

⚠️ **`medium` is the one deliberate divergence.** The vendor says "Mid"; we have shipped `medium`
for a long time and it is in users' automations. One word is not worth breaking them for.

⛔ **Boost is the one label we know and do not use.** Its wire code is **0** — and 0 is what the fan
field reads on a real report from a 209-byte unit that is switched **off**. So at the wire it cannot
be told apart from "no speed reported", and 23 products declare it while none of them has ever sent
us a report. Naming it would put a speed in the list that the appliance can never be seen to be in,
which is the one thing a control must not do. It is withheld in *both* layers — no wire code, no
keyword — because offering it in one and not the other is the actual hazard.

★ `AC_quite` is the vendor's own spelling of the key. Its *value* is "Silent" in every locale, which
is what we follow.

## Why naming them mattered

It is not cosmetic. Before these names existed, two different speeds were silently sharing one
token, and a token is what a write is resolved through:

- `中高风` (code 7) and `高风` (code 1) both became `high` — on **51 products**;
- `中低风` (code 8) and `中风` (code 2) both became `medium` — on **31**;
- `健康除湿` (code 3) and `除湿` (code 2) both became `dry` — on **20**.

With two codes on one token, the reverse lookup returns whichever the model happened to list first.
And four further speeds — Boost, Breeze, Silent, Quick — resolved to *nothing*, so a unit switched to
one of them reported **no fan speed at all**: not a wrong reading, an absent one, which is the harder
kind to notice.

## Where the vendor's vocabulary and Home Assistant's do not meet

Home Assistant's `HVACMode` has five members and no room for a vendor variant of one. Two modes are
therefore **display-only** — they show as the standard mode they are a variant of, and selecting that
standard mode writes the plain code, never the variant:

| mode | shows as | how it is reached |
|---|---|---|
| `ECO` (窗机) | Cool | the **eco preset** |
| `Healthy Dry` | Dry | not selectable — reported only |

Fan speeds have no such constraint: Home Assistant takes the fan list from the appliance, so every
speed a unit publishes is offered under the manufacturer's own name for it.

⚠️ On the handful of products that publish both, the fan speed **Boost** and the **boost preset** are
different things — the first is a fan speed, the second is the appliance's rapid mode. The names
collide because both are the vendor's own; three published products carry both.

## Reproducing this

```bash
unzip -p <app>.apk 'assets/PresetResPkg/mPaaS@uplanguage@*.zip' > /tmp/lang.zip
unzip -o /tmp/lang.zip -d /tmp/lang        # -> uplanguage/<locale>.json, 18 locales
python3 -c "import json;d=json.load(open('/tmp/lang/uplanguage/en.json'))['seasia_home'];\
print({k:v for k,v in d.items() if k.startswith('AC_')})"
```
