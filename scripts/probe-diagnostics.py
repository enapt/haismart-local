#!/usr/bin/env python3
"""Rank layout candidates for the diagnostics files attached to a new-model report.

A new-model report arrives as one diagnostics file per capture, each taken in a state the reporter
wrote down. Diagnostics already proposes candidates on its own, but it does so unaided: the states
live in the issue as prose, so nothing inside Home Assistant can know that capture two was "cool,
22 C, fan low". Those states are worth as much as the device's own published values and are the
difference between a shortlist and a ranking -- on real reports most candidates tie at the top score
without them.

This is where they get supplied. Give it the attached files in capture order and say what each one
was, in the same order:

    scripts/probe-diagnostics.py off.json cool.json fan.json \\
        --state off \\
        --state 'on,mode=cool,temp=22,fan=low,swing=off,room=27' \\
        --state 'on,mode=fan_only,fan=high,swing=on'

A state is a comma-separated list of:

    on | off          the unit was running / was switched off
    temp=22           the setpoint, in degrees C
    room=27           the room temperature the handset displayed
    swing=on | off    the up-down vane was sweeping / was parked
    mode=<label>      an OPAQUE label for the mode -- "cool", "fan_only", "whatever"
    fan=<label>       an OPAQUE label for the fan speed -- "low", "high"

`mode` and `fan` are labels, not codes, and are never compared against the model's numbering: what
they assert is only that captures labelled differently must decode to different codes and captures
sharing a label to the same one. That is what makes them usable from a reporter's own words. Use
`-` for a capture nobody described.

The output is a shortlist to verify, not a result. Close scores are common, and the registry -- not
this search -- decides what ships.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packages/haismart-hrdp/src"))

from haismart_hrdp import StatedState, probe_layout  # noqa: E402

_TRUTHY = {"on", "true", "yes", "1"}
_FALSY = {"off", "false", "no", "0"}


def parse_state(text: str) -> StatedState | None:
    """One `--state` argument as a :class:`StatedState`, or ``None`` for an undescribed capture."""
    text = text.strip()
    if text in ("", "-", "?"):
        return None
    fields: dict[str, Any] = {}
    for token in (t.strip() for t in text.split(",") if t.strip()):
        if token.lower() in _TRUTHY | _FALSY:
            fields["power"] = token.lower() in _TRUTHY
            continue
        key, sep, value = (part.strip() for part in token.partition("="))
        if not sep:
            raise SystemExit(f"cannot read {token!r} in state {text!r} -- expected key=value")
        key, value_lower = key.lower(), value.lower()
        if key in ("temp", "target", "setpoint"):
            fields["target_temperature"] = float(value)
        elif key in ("room", "indoor", "current"):
            fields["current_temperature"] = float(value)
        elif key in ("swing", "swing_vertical"):
            if value_lower not in _TRUTHY | _FALSY:
                raise SystemExit(f"swing must be on or off, not {value!r}")
            fields["swing_vertical"] = value_lower in _TRUTHY
        elif key == "mode":
            fields["mode_group"] = value
        elif key == "fan":
            fields["fan_group"] = value
        else:
            raise SystemExit(f"unknown state key {key!r} in {text!r}")
    return StatedState(**fields)


def load_capture(path: Path) -> tuple[bytes, dict[str, Any]]:
    """The raw report and the device's published values out of one diagnostics file."""
    try:
        diag = json.loads(path.read_text())
    except (OSError, ValueError) as err:
        raise SystemExit(f"{path}: {err}") from err
    # A diagnostics download from Home Assistant nests the payload under "data"; a file that has
    # already been unwrapped is accepted too, since both turn up on issues.
    diag = diag.get("data", diag)
    blob = diag.get("last_raw_status")
    if not blob:
        raise SystemExit(
            f"{path}: no last_raw_status -- this download caught the unit with no report decoded, "
            "so there is nothing to work a layout out from. Ask for another."
        )
    try:
        report = bytes.fromhex(blob)
    except ValueError as err:
        raise SystemExit(f"{path}: last_raw_status is not hex ({err})") from err
    model = diag.get("digital_model") or {}
    return report, model.get("reported_values") or {}


def describe(path: Path, report: bytes, state: StatedState | None) -> str:
    stated = "state not given" if state is None else ", ".join(
        f"{k}={v}" for k, v in vars(state).items() if v is not None
    )
    return f"  {path.name}: {len(report)} bytes, {stated}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("files", nargs="+", type=Path, help="diagnostics files, in capture order")
    parser.add_argument(
        "--state", action="append", default=[], metavar="STATE",
        help="what the matching capture was in; repeat once per file, same order",
    )
    parser.add_argument("--limit", type=int, default=5, help="candidates to print (default 5)")
    parser.add_argument(
        "--max-shift", type=int, default=24, help="largest displacement to try (default 24)"
    )
    args = parser.parse_args()

    if args.state and len(args.state) != len(args.files):
        raise SystemExit(
            f"{len(args.files)} files but {len(args.state)} --state arguments. Give one per file in "
            "the same order, using '-' for a capture nobody described."
        )
    stated = [parse_state(s) for s in args.state] or None

    reports, shadows = [], []
    for path in args.files:
        report, shadow = load_capture(path)
        reports.append(report)
        shadows.append(shadow)

    # Every file from one config entry carries the same published values -- they are stored when the
    # device is added, not re-read per download -- so the first non-empty set is the whole of it.
    shadow = next((s for s in shadows if s), {})

    print(f"{len(reports)} capture(s):")
    for path, report, state in zip(args.files, reports, stated or [None] * len(reports)):
        print(describe(path, report, state))
    if shadow:
        print(f"  published values: {len(shadow)} attributes")
    else:
        print(
            "  published values: none in these files -- either the device was added without cloud\n"
            "  credentials, or the files predate diagnostics carrying them. The stated states above\n"
            "  are then the only ground truth, so it is worth having all three."
        )
    if not stated:
        print(
            "\nNo --state given, so this ranks on plausibility and published values alone, which is\n"
            "what the diagnostics file already did. The states are in the issue -- pass them."
        )

    candidates = probe_layout(
        reports, shadow=shadow or None, stated=stated, max_shift=args.max_shift, limit=args.limit
    )
    if not candidates:
        print(
            "\nNothing fits. That is an answer rather than a failure: this report is not a known\n"
            "family displaced from some word onward, so it needs a layout of its own."
        )
        return 1

    print(f"\n{len(candidates)} candidate(s), best first:\n")
    for rank, candidate in enumerate(candidates, 1):
        shift, pivot = candidate["shift"], candidate["pivot"]
        moved = f"+{shift} words from w{pivot}" if shift else "unmoved"
        print(
            f"{rank}. {candidate['family']}, {moved}, {candidate['setpoint']} setpoint"
            f"  (score {candidate['score']})"
        )
        for path, decoded in zip(args.files, candidate["decoded"]):
            values = ", ".join(f"{k}={v}" for k, v in sorted(decoded.items()) if v is not None)
            print(f"     {path.name}: {values}")
        print()
    print(
        "Check the best candidate against what the reporter described before it goes anywhere near\n"
        "the registry, and confirm it on their unit before it ships."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
