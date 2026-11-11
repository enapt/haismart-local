#!/usr/bin/env python3
"""Fail unless a JUnit report shows every collected test executed and passed.

pytest exits 0 when every test was skipped, and the Home Assistant suite skips whatever its
environment cannot run -- a missing test package leaves nothing to collect, a missing optional
dependency skips the tests that need it. Counting collected tests cannot see either. This reads
the report pytest writes with ``--junitxml`` and fails on zero tests, on any failure or error, and
on any skip, naming each skipped test and its reason so the missing piece is visible.

    scripts/check-junit.py report.xml
    scripts/check-junit.py --selftest
"""
from __future__ import annotations

import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path


def check(report: Path) -> tuple[bool, list[str]]:
    """Whether the report is a complete, passing run, and the lines that say why."""
    if not report.is_file():
        return False, [f"no JUnit report at {report}: the suite did not run"]
    root = ET.parse(report).getroot()
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    tests = failures = errors = skipped = 0
    lines: list[str] = []
    for suite in suites:
        tests += int(suite.get("tests", 0))
        failures += int(suite.get("failures", 0))
        errors += int(suite.get("errors", 0))
        skipped += int(suite.get("skipped", 0))
        for case in suite.iter("testcase"):
            skip = case.find("skipped")
            if skip is not None:
                reason = skip.get("message") or ""
                lines.append(f"  skipped: {case.get('classname')}::{case.get('name')} -- {reason}")
    executed = tests - skipped
    summary = f"{tests} collected, {executed} executed, {failures} failed, {errors} errors, " \
              f"{skipped} skipped"
    ok = tests > 0 and executed == tests and not failures and not errors
    return ok, [summary, *lines]


def _suite(tests: int, failures: int, errors: int, skipped: int, cases: str) -> str:
    counts = f'tests="{tests}" failures="{failures}" errors="{errors}" skipped="{skipped}"'
    return f"<testsuite {counts}>{cases}</testsuite>"


def _selftest() -> int:
    passed = '<testcase classname="a" name="x"/>'
    skip = '<testcase classname="a" name="y"><skipped message="could not import aiodiscover"/>' \
           "</testcase>"
    cases = {
        "passing": (f"<testsuites>{_suite(2, 0, 0, 0, passed * 2)}</testsuites>", True),
        "empty": (_suite(0, 0, 0, 0, ""), False),
        "one skip": (_suite(2, 0, 0, 1, passed + skip), False),
        "all skipped": (_suite(1, 0, 0, 1, skip), False),
        "a failure": (_suite(1, 1, 0, 0, '<testcase classname="a" name="x"><failure/></testcase>'),
                      False),
        "an error": (_suite(1, 0, 1, 0, '<testcase classname="a" name="x"><error/></testcase>'),
                     False),
    }
    bad = 0
    with tempfile.TemporaryDirectory() as tmp:
        for name, (xml, expected) in cases.items():
            path = Path(tmp) / "r.xml"
            path.write_text(xml, encoding="utf-8")
            ok, lines = check(path)
            if ok is not expected:
                bad += 1
                print(f"FAIL {name}: got {ok}, expected {expected}: {lines}")
        ok, _ = check(Path(tmp) / "missing.xml")
        if ok:
            bad += 1
            print("FAIL missing report: accepted")
    total = len(cases) + 1
    print(f"check-junit selftest: {total - bad}/{total}")
    return 1 if bad else 0


def main(argv: list[str]) -> int:
    if argv[1:] == ["--selftest"]:
        return _selftest()
    if len(argv) != 2:
        print("usage: scripts/check-junit.py <report.xml> | --selftest", file=sys.stderr)
        return 2
    ok, lines = check(Path(argv[1]))
    print("\n".join(lines))
    if not ok:
        print(f"::error::{lines[0]}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
