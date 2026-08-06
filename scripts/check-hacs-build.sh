#!/usr/bin/env bash
# Verify that custom_components/ matches what scripts/build-hacs.sh would generate from packages/.
#
# custom_components/ is a generated, committed tree (HACS installs from the repo root, so it has to
# be committed). Two ways it drifts:
#   * someone edits packages/ and forgets to re-run the build, so the shipped component is stale;
#   * someone edits custom_components/ directly, and the next build silently reverts it.
# Both leave the test suites green, because the suites import the packages/ copy. CI fails on this;
# this script exists so you find out before pushing.
#
# It is a CHECK: it leaves your working tree exactly as it found it, and never commits anything.
#
#   scripts/check-hacs-build.sh          # exit 0 in sync, 1 if it drifted
set -uo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
dest="$root/custom_components"
[ -d "$dest" ] || { echo "no custom_components/ to check"; exit 0; }

# Compiled bytecode is gitignored and is created just by running the tests, so it must not
# count as drift - otherwise this fails for anyone who ran the suite first.
DIFF_SKIP="-x __pycache__ -x *.pyc"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
cp -r "$dest" "$tmp/actual"

# QUIET_BUILD keeps the build's own "discarded local changes" advice out of a check that is about to
# put those same changes back.
QUIET_BUILD=1 "$root/scripts/build-hacs.sh" >/dev/null 2>&1
cp -r "$dest" "$tmp/expected"

# Restore what was there before, whatever the verdict — a check must not mutate the tree.
rm -rf "$dest"
cp -r "$tmp/actual" "$dest"

# hacs.json is NOT generated -- it is committed at the repo root, because that is the only copy
# HACS reads. The package keeps its own copy for the monorepo layout, so the two can drift with
# nothing to catch it: a declaration added to the package copy alone is simply never applied, which
# is exactly how the supported-Home-Assistant floor sat unread for several releases.
if ! diff -q "$root/hacs.json" "$root/packages/ha-haismart/hacs.json" >/dev/null 2>&1; then
  {
    echo "hacs.json differs between the repo root and packages/ha-haismart/:"
    diff "$root/hacs.json" "$root/packages/ha-haismart/hacs.json" | sed "s/^/  /"
    echo
    echo "HACS only ever reads the ROOT copy. Make them identical."
  } >&2
  exit 1
fi

if diff -rq $DIFF_SKIP "$tmp/actual" "$tmp/expected" >/dev/null 2>&1; then
  echo "custom_components/ is in sync with packages/"
  exit 0
fi

{
  echo "custom_components/ is NOT in sync with packages/:"
  diff -rq $DIFF_SKIP "$tmp/actual" "$tmp/expected" 2>&1 | sed "s|$tmp/actual|committed|; s|$tmp/expected|generated|; s/^/  /"
  echo
  echo "Fix: run scripts/build-hacs.sh and commit the result."
  echo
  echo "If you were changing the component, edit the SOURCE, never the generated tree:"
  echo "    the component  -> packages/ha-haismart/custom_components/haismart/"
  echo "    the helper libs -> packages/haismart-hrdp/src, packages/haismart-extractor/src"
} >&2
exit 1
