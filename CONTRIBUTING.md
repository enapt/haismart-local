# Contributing

Thanks for helping improve haismart-local. This is a three-package monorepo (`haismart-hrdp`,
`haismart-extractor`, `ha-haismart`). `packages/haismart-hrdp/src/haismart_hrdp/uss.py` holds the local
protocol (transport, crypto, framing) — read it before changing transport, crypto, or framing code.
`udiscovery.py` alongside it is the second, key-free protocol on UDP `:7083` (discovery, model ID and
cloud-reachability); see [PROTOCOL.md](PROTOCOL.md) for both.

## Development setup

```bash
python3 -m venv --system-site-packages .venv && . .venv/bin/activate
pip install pytest pytest-asyncio cryptography ruff
# for the Home Assistant integration tests:
pip install homeassistant pytest-homeassistant-custom-component
```

## Tests & lint (must pass before a PR)

```bash
./scripts/test.sh          # all three suites: haismart-hrdp, haismart-extractor, ha-haismart
ruff check packages        # lint (each package pins its own config)
```

All suites run with **no hardware and no network**. Tests and examples must use **illustrative**
deviceIds/keys — never a real device `localKey`, MAC, or LAN address (see [SECURITY.md](SECURITY.md)).

## Ground rules

- **`uss.py` is the protocol** — the whole local read + control path.
- **No unverified frames to a real AC.** The encoder only emits fields/values in its allowlist
  (`set_grsetdac_field` raises otherwise) — keep it that way: don't widen the grSetDAC map without
  evidence for the new field/value.
- **An unknown code is not a known one.** The cloud-state value in the UDISCOVERY reply is
  module-firmware defined and undocumented: two values have been confirmed and the rest of the space
  is unknown. So the decoder treats *only* the confirmed "connected" value as connected, keeps the
  raw number in an attribute, and reports "unknown" when a device says nothing at all — never a
  fabricated "disconnected". Telling someone their firewall works when nothing was measured is worse
  than saying nothing. Hold new fields on that channel to the same bar, and walk its TLVs by type
  rather than by offset: the record area's populated length varies by device class.
- **Only surface a reading you've confirmed is real.** The status and extended reports contain more
  fields than the integration exposes. A field becomes an entity only when it's been seen to behave
  correctly on real hardware — several were left out because they didn't (e.g. an outdoor-fan state
  that reads "on" while the unit is off). And a reading a unit doesn't actually have must decode to
  *unavailable*, never a fabricated value: a missing temperature reads `0`, which naive maths turns
  into a confident −64 °C that then poisons long-term statistics. `parse_extended_status` and the
  temperature helpers already guard this; keep new fields to the same bar. The extended report's byte
  offsets are **per report family** — the ones in `parse_extended_status` are for the classic
  (141-byte) family, so another family needs its own offsets confirmed before it can decode there.
- **A cumulative register reading zero is absent, not zero.** Whole classes of these units carry a
  counter and never populate it. Publishing that as a total gives someone a permanent 0 kWh in their
  Energy dashboard, which is worse than no sensor — so a counter decodes to *unavailable* until the
  unit actually fills it in (`WireField` kind `"counter"`). The same goes for a counter whose
  **unit** is unestablished: a total with the wrong unit settles permanently into a user's history.
- **Never commit secrets.** Local keys, account tokens and anything matching `*.local.json` are
  git-ignored; keep them that way. A local key grants ongoing control of someone's appliance.
- **`custom_components/` at the repo root is generated** — the HACS-installable build with the two
  libraries vendored in. Don't edit it directly: change the source under `packages/`, then run
  `scripts/build-hacs.sh` and commit the regenerated component.

  This is easy to get wrong, so three things now catch it. `scripts/build-hacs.sh` prints what it
  discarded if you had edited the generated tree; `scripts/check-hacs-build.sh` (also run by
  `scripts/test.sh`) fails if the committed tree does not match what the build would produce; and CI
  runs the same comparison. The suites alone will not catch it — they import the `packages/` copy, so
  a stale or hand-edited generated tree keeps them green.

  **On a merge conflict inside `custom_components/`, do not hand-resolve it.** It is a generated
  file, so a hand-merge produces a tree matching neither side. Take either version
  (`git checkout --ours` / `--theirs`), then re-run `scripts/build-hacs.sh` and commit the result.
- Match existing style; keep changes focused; add tests for behaviour changes.

## Entity names and translations

A new named entity (a `translation_key` on a sensor, switch, etc.) needs a matching string in
`packages/ha-haismart/custom_components/haismart/strings.json` **and** in every file under
`translations/`. The integration ships ~30 languages and `scripts/check-translations.py` enforces
strict key parity — a key present in some files but not others fails, so adding it to `en.json`
alone will not do.

```bash
python3 scripts/check-translations.py    # key parity + placeholder integrity across every language
```

If you can't provide a real translation for a language, use the English string for now (present and
non-empty passes the check); a later PR can localise it. Diagnostic engineering entities can instead
skip `translation_key` and lean on their device class, which Home Assistant already translates — but
only when the device-class name is unambiguous (several temperatures all called "Temperature" is not,
so those carry a `translation_key`).

## Adding a new AC model

Most models need **no code at all** — the integration derives its behaviour from the device's own
digital model. When something does need a change, the work is almost always one table entry, and the
hard part is the evidence, not the patch.

Start from [`docs/new-model.md`](docs/new-model.md): three status captures in known states pin the
control-word block and identify the sensor bytes by elimination. If you have the unit in front of
you, that is the fastest path to a correct layout.

You rarely have to find the layout by hand. Since v0.35.0 an unrecognised report is first matched
against the published models nearest its Model ID, and if one of their offsets explains what the unit
sent, it is decoded with that — and commanded too, when the product publishes the attribute list of
its own group-set command (nearly all do). A unit on that path that stays read-only has a product
whose published description carries no such list; captures from it are what promote the layout to a
real family, and they also unlock the readings beyond the core climate block.

When nothing fits at all, diagnostics runs a search over the known families — see
[`docs/report-layouts.md`](docs/report-layouts.md) — and attaches ranked candidates, because every
layout met so far has been a known map displaced from some word onward. That search runs unaided,
though — it cannot know which capture was which — so re-run it over the attachments with the states
the reporter gave:

```bash
scripts/probe-diagnostics.py off.json cool.json fan.json \
    --state off --state 'on,mode=cool,temp=22,fan=low,swing=off,room=27' \
    --state 'on,mode=fan_only,fan=high,swing=on'
```

`probe_layout()` is callable directly if you want to try variations. Treat the output as a shortlist
to verify, never as a result: the ranking is a heuristic, close scores are common, and the same page
explains why the registry, not the search, remains the authority on what ships.

A diagnostics download also carries **every attribute the unit declares, read off its own report** —
far more than the family map names — beside the values the device publishes through its cloud
profile, so the two can be compared without a round-trip to the reporter. On a family whose
displacement is confirmed those two independent sources should agree; a disagreement is a finding.
Nothing there becomes an entity, and [`docs/report-layouts.md`](docs/report-layouts.md) explains what
it will and will not read.

Two rules make this safe:

- **Reads may be widened on inference; writes may not.** An unknown report length is decoded as far
  as the layout-independent fields allow and flagged `partial`. `STATUS_LAYOUTS` stays the allowlist
  for writes, because a wrong word count sends a sensor byte back to the AC as a control word.
- **A position may be inferred from the published map; a meaning may not.** Reading a device's other
  declared attributes off the map is fair — the map states where they are, the device states that it
  has them, and for a *code* the map also states whether the wire numbering is the published
  numbering. Deciding what a code means where nothing states it is not fair: the extended report
  places six two-bit actuator states whose values are declared to be 0, 1 or 2 with no meanings
  attached, so those are reported as the codes they are rather than as booleans. A live unit sends
  the same value for two of them whether it is cooling hard or idle at 0 W.
- **A new grSetDAC field or value needs an observation, not a deduction.** The way to get one is a
  single-attribute sweep: change exactly one setting in the vendor app and diff the report. That is
  how every field in the current map was established, and how horizontal swing and heat were added.

### Where the code for it lives

Per-model semantics live in `packages/haismart-hrdp/src/haismart_hrdp/profiles.py` as an
`AttributeProfile`, keyed by the cloud `product_code`. `profile_from_device_config()` can self-derive
one from Haier's digital model, so most models need no hand-coding — contribute the `product_code`
mapping and, where possible, a status vector for the test suite.

Where a model packs its status *differently*, that is a **report layout**, and it lives in
`wire_models.py` rather than in a profile. Most of a layout is not written by hand either:
`canonical_map.py` carries the attribute map these models share, so a new family is usually a
displacement plus its exceptions. [`docs/report-layouts.md`](docs/report-layouts.md) is the inventory
of every known one and the rules for adding another. Two conventions matter when you do:

- **Key on the Model ID as well as the length.** Length is a decent key but not a sound one — the
  published models contain a genuine collision at 149 bytes. The Model ID is reported by the units
  themselves on the discovery channel, so it is available even without cloud credentials.
- **Leave out what the captures did not settle.** A field whose position is unconfirmed stays off the
  read *and* out of the write map, so it reads as unavailable rather than wrong. Several shipped
  families omit fields for exactly this reason, each with the reason written next to it.
