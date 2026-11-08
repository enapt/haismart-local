#!/usr/bin/env python3
"""Check every translations/<lang>.json against strings.json.

Home Assistant silently ignores a translation key it does not recognise and silently falls back to
English for one that is missing, so a drifted translation file fails invisibly -- you only find out
when a user reports a half-English dialog. This makes the drift loud instead.

A placeholder mismatch is the one that actually breaks: HA formats these strings with `.format()`,
so a translator who drops `{name}` or renames it to `{nombre}` turns a dialog into a KeyError at
runtime. Both are checked here.

And the VALUES, not only the keys: `translation-sources.json` records a fingerprint of the English
each string was translated from, and of every language's translation of it. When the English
changes, the check fails and names each language still carrying the text it had before -- so a
reworded English string can no longer leave thirty languages silently saying the old thing. Once
they are translated, record the new state:

    scripts/check-translations.py
    scripts/check-translations.py --record     # after translating every key the check names
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

COMPONENT = Path(__file__).resolve().parent.parent / "packages/ha-haismart/custom_components/haismart"
PLACEHOLDER = re.compile(r"\{[^{}]*\}")
SOURCES = Path(__file__).resolve().parent / "translation-sources.json"


def flatten(obj: dict, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in obj.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.update(flatten(value, path))
        else:
            out[path] = value
    return out


def fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def _locales() -> dict[str, dict[str, str]]:
    return {
        path.stem: flatten(json.loads(path.read_text(encoding="utf-8")))
        for path in sorted((COMPONENT / "translations").glob("*.json"))
        if path.stem != "en"            # en.json mirrors strings.json; it is not a translation
    }


def record(reference: dict[str, str]) -> int:
    """Write the fingerprints: one line per key, the English first, then each language in order."""
    locales = _locales()
    languages = sorted(locales)
    lines = [
        f"  {json.dumps(key)}: "
        + json.dumps([fingerprint(reference[key])]
                     + [fingerprint(str(locales[lang].get(key, ""))) for lang in languages])
        for key in sorted(reference)
    ]
    SOURCES.write_text(
        '{"languages": ' + json.dumps(languages) + ', "keys": {\n' + ",\n".join(lines) + "\n}}\n",
        encoding="utf-8",
    )
    print(f"recorded {len(lines)} keys x {len(languages)} languages -> {SOURCES.name}")
    return 0


def check_values(reference: dict[str, str]) -> list[str]:
    """Keys whose English moved since the languages were translated, naming the stale languages."""
    if not SOURCES.exists():
        return [f"{SOURCES.name} is missing -- run with --record"]
    recorded = json.loads(SOURCES.read_text(encoding="utf-8"))
    sources = recorded["keys"]
    languages = recorded["languages"]
    locales = _locales()
    problems: list[str] = []
    if sorted(locales) != languages:
        changed = ", ".join(sorted(set(locales) ^ set(languages)))
        problems.append(f"the languages changed ({changed}) -- run --record")
    for key in sorted(reference):
        seen = sources.get(key)
        if seen is None:
            problems.append(f"{key}: new key not recorded -- translate it, then run --record")
            continue
        if fingerprint(reference[key]) == seen[0]:
            continue
        before = dict(zip(languages, seen[1:], strict=False))
        stale = sorted(
            lang for lang, data in locales.items()
            if fingerprint(str(data.get(key, ""))) == before.get(lang)
        )
        if stale:
            problems.append(
                f"{key}: the English changed, and {len(stale)} language(s) still carry the text "
                f"translated from the old one: {', '.join(stale)}"
            )
        else:
            problems.append(f"{key}: the English and every language changed -- run --record")
    if gone := sorted(set(sources) - set(reference)):
        problems.append(f"{len(gone)} recorded key(s) no longer exist: {', '.join(gone[:5])} "
                        "-- run --record")
    return problems


def main() -> int:
    # strings.json is the source of truth; translations/en.json must mirror it exactly.
    reference = flatten(json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8")))
    if "--record" in sys.argv[1:]:
        return record(reference)
    failures = 0

    for path in sorted((COMPONENT / "translations").glob("*.json")):
        problems: list[str] = []
        try:
            data = flatten(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError as exc:
            print(f"FAIL {path.name}: invalid JSON: {exc}")
            failures += 1
            continue

        if missing := sorted(set(reference) - set(data)):
            problems.append(f"missing {len(missing)} key(s): {', '.join(missing[:5])}")
        if extra := sorted(set(data) - set(reference)):
            problems.append(f"unknown {len(extra)} key(s): {', '.join(extra[:5])}")

        for key in sorted(set(reference) & set(data)):
            want = sorted(PLACEHOLDER.findall(reference[key]))
            got = sorted(PLACEHOLDER.findall(data[key]))
            if want != got:
                problems.append(f"{key}: placeholders {want} became {got}")
            if not str(data[key]).strip():
                problems.append(f"{key}: empty")

        if problems:
            failures += 1
            print(f"FAIL {path.name}")
            for problem in problems:
                print(f"     {problem}")
        else:
            print(f"ok   {path.name}")

    drift = check_values(reference)
    if drift:
        failures += 1
        print("FAIL values: the English moved under its translations")
        for problem in drift:
            print(f"     {problem}")
    else:
        print("ok   values: every translation was made from the English it sits under")

    print(f"\n{len(reference)} keys; {failures} file(s) failing")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
