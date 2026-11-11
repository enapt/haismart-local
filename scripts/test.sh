#!/usr/bin/env bash
# Run every package's test suite. No hardware, no network.
# The ha-haismart suite leaves out every test that needs Home Assistant unless Home Assistant and
# its matching test package are installed, so a green run here does not prove it ran. Locally,
# install them if you are touching the integration:
#   pip install homeassistant pytest-homeassistant                  # Home Assistant 2026.11+
#   pip install homeassistant pytest-homeassistant-custom-component # earlier cores
# CI tests several cores and sets HA_JUNIT, which writes that suite's JUnit report;
# scripts/check-junit.py then fails the job on any skip.
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
  ( cd "$root/packages/$pkg" && "$py" -m pytest -q -p no:cacheprovider "${junit[@]}" ) || fail=1
  echo
done
# custom_components/ is generated from packages/ and committed for HACS. The suites above import
# the packages/ copy, so a stale or hand-edited generated tree passes them all. Check it here too,
# rather than letting CI be the first thing that notices.
echo "=== HACS build in sync ==="
"$root/scripts/check-hacs-build.sh" || fail=1

exit $fail
