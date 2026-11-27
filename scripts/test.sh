#!/usr/bin/env bash
# Run every package's test suite. No hardware, no network.
# The ha-haismart suite leaves out every test that needs Home Assistant unless Home Assistant and
# its matching test package are installed, so a green run here does not prove it ran. Locally,
# install them if you are touching the integration:
#   pip install homeassistant pytest-homeassistant                  # Home Assistant 2026.11+
#   pip install homeassistant pytest-homeassistant-custom-component # earlier cores
# The integration suite runs twice: against the source copy, then against the generated copy users
# install (below). CI tests several cores and sets HA_JUNIT, which writes a JUnit report for each
# run (the second beside the first, `-generated.xml`); scripts/check-junit.py then fails the job on
# any skip in either.
set -u
root="$(cd "$(dirname "$0")/.." && pwd)"
py="${PYTHON:-python3}"
fail=0
for pkg in haismart-hrdp haismart-extractor ha-haismart; do
  echo "=== $pkg ==="
  junit=()
  if [ "$pkg" = ha-haismart ] && [ -n "${HA_JUNIT:-}" ]; then
    junit=(--junitxml="$HA_JUNIT")
  fi
  # ${junit[@]+...}: an empty array is "unbound" under set -u in bash before 4.4 (macOS /bin/bash).
  ( cd "$root/packages/$pkg" && "$py" -m pytest -q -p no:cacheprovider ${junit[@]+"${junit[@]}"} ) || fail=1
  echo
done
# The suites above test the SOURCE copy of the integration. What users install is the generated copy
# at the repo root, which imports the two bundled libraries differently (relatively, from vendor/),
# so the integration suite runs again against that copy. It runs from the repo root with the repo
# root as its only pythonpath, so the source copy is not importable; tests/conftest.py refuses to
# start if it finds the wrong one. With HA_JUNIT set, its report goes beside the first.
echo "=== ha-haismart, against the generated copy users install ==="
junit=()
if [ -n "${HA_JUNIT:-}" ]; then
  junit=(--junitxml="${HA_JUNIT%.xml}-generated.xml")
fi
( cd "$root" && HAISMART_TEST_TREE=generated "$py" -m pytest -q -p no:cacheprovider \
    -c packages/ha-haismart/pyproject.toml --rootdir packages/ha-haismart -o pythonpath=../.. \
    ${junit[@]+"${junit[@]}"} packages/ha-haismart/tests ) || fail=1
echo
# custom_components/ is generated from packages/ and committed for HACS. The suites above import
# the packages/ copy, so a stale or hand-edited generated tree passes them all. Check it here too,
# rather than letting CI be the first thing that notices.
echo "=== HACS build in sync ==="
"$root/scripts/check-hacs-build.sh" || fail=1
# The deprecation gate (tests/conftest.py) against a known answer: one report logged while the
# conftest loads -- before anything imports the integration, which is when Home Assistant reports a
# deprecated name -- must fail the run. A gate attached too late passes it, and would pass a real one.
# Only where Home Assistant is installed: without it the gate does not exist and nothing runs.
if ( cd "$root/packages/ha-haismart" && "$py" -c "import homeassistant" ) 2>/dev/null; then
  echo "=== deprecation gate catches a report raised at import ==="
  if ( cd "$root/packages/ha-haismart" && HAISMART_DEPRECATION_GATE_SELFTEST=1 \
      "$py" -m pytest -q -p no:cacheprovider tests/test_entities.py >/dev/null 2>&1 ); then
    echo "FAIL: a deprecation report logged at conftest import did not fail the run"
    fail=1
  else
    echo "deprecation gate selftest: the planted report failed the run, as it must"
  fi
fi
# The skip gate CI runs on the Home Assistant suite's report, checked against known answers: a gate
# that accepted everything would look exactly like a suite that ran.
echo "=== skip gate ==="
"$py" "$root/scripts/check-junit.py" --selftest || fail=1

exit $fail
