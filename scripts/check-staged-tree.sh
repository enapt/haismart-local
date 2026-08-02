#!/usr/bin/env bash
# Refuse a commit that edits the GENERATED component tree directly.
#
# custom_components/ is generated from packages/ and committed (HACS installs from the repo root).
# Editing it directly looks like it works: the file changes, the app picks it up, and the tests still
# pass — because the suites import the packages/ copy. Then the next scripts/build-hacs.sh silently
# overwrites the edit, and the change is simply gone.
#
# scripts/check-hacs-build.sh already detects a tree that has drifted, but it CANNOT catch this case:
# to compare, it runs the build — which destroys the evidence. Once the build has run, the direct
# edit is gone and the tree is genuinely in sync, so the check passes and reports nothing. This runs
# at commit time instead, while the edit is still there to see.
#
# The rule: staged changes under custom_components/ are legitimate only as the product of a build,
# and a build follows a source change. So staged generated files with NO staged source files means
# someone edited the generated tree.
#
#   scripts/check-staged-tree.sh          # exit 0 if fine, 1 to refuse the commit
#
# Install as a hook with scripts/install-hooks.sh. To commit anyway (a deliberate generated-only
# change, e.g. re-running the build after a dependency bump): git commit --no-verify.
set -uo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root" || exit 0

staged="$(git diff --cached --name-only 2>/dev/null)" || exit 0
[ -n "$staged" ] || exit 0

generated="$(echo "$staged" | grep '^custom_components/' || true)"
[ -n "$generated" ] || exit 0

source_changed="$(echo "$staged" | grep '^packages/' || true)"
[ -n "$source_changed" ] && exit 0

{
  echo "Refusing: this commit changes the GENERATED tree with no source change."
  echo
  echo "  staged under custom_components/:"
  echo "$generated" | sed 's/^/    /'
  echo
  echo "custom_components/ is generated from packages/. An edit there survives until the next"
  echo "scripts/build-hacs.sh, which overwrites it without saying so — and the test suites keep"
  echo "passing throughout, because they import the packages/ copy."
  echo
  echo "Edit the SOURCE instead, then re-run scripts/build-hacs.sh:"
  echo "    the component   -> packages/ha-haismart/custom_components/haismart/"
  echo "    the helper libs -> packages/haismart-hrdp/src, packages/haismart-extractor/src"
  echo
  echo "If this really is a generated-only commit, re-run with: git commit --no-verify"
} >&2
exit 1
