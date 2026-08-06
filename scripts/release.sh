#!/usr/bin/env bash
# Cut a release: bump the version, verify everything, commit and tag.
#
#   scripts/release.sh 0.40.0            # bump, check, commit, tag (does NOT push)
#   scripts/release.sh 0.40.0 --push     # ...and push the branch and the tag
#
# WHY THIS EXISTS. HACS installs this integration from the repository tree at the tag -- there is no
# release zip -- so the manifest.json committed at that tag is literally what lands in someone's
# config directory. A tag whose manifest still says the previous version is therefore not a
# cosmetic slip: Home Assistant reads that field to decide whether an update is available, so the
# new release is offered forever, or never. Bumping it by hand is one step in a list, and it is the
# step that gets forgotten.
#
# So the version is not typed into a file: it is derived from the release being cut, in one place,
# and the tag is created from the same argument in the same run. They cannot disagree. CI asserts
# the same equality on the pushed tag, for tags made any other way.
#
# The version lives in packages/ha-haismart/custom_components/haismart/manifest.json ONLY. The copy
# at the repo root is generated (scripts/build-hacs.sh) and is rebuilt here. The two library
# pyproject.toml versions are deliberately untouched -- those version the libraries, not the release.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

version="${1:-}"
push="${2:-}"
[ -n "$version" ] || { echo "usage: scripts/release.sh <version> [--push]   e.g. 0.40.0" >&2; exit 1; }
# Accept "v0.40.0" and normalise: the manifest wants a bare version, the tag wants the v.
version="${version#v}"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
  echo "error: '$version' is not X.Y.Z" >&2; exit 1
}
tag="v$version"
manifest="packages/ha-haismart/custom_components/haismart/manifest.json"

# --- refuse to release from a state nobody can reproduce ----------------------------------------
[ "$(git rev-parse --abbrev-ref HEAD)" = "main" ] || {
  echo "error: releases are cut from main (on $(git rev-parse --abbrev-ref HEAD))" >&2; exit 1
}
# --porcelain, not `git diff`: this commits with `git add -A`, so an UNTRACKED file would be swept
# into the release commit as surely as a modified one, and `git diff` cannot see untracked files.
[ -z "$(git status --porcelain)" ] || {
  echo "error: working tree is not clean -- commit or stash first, then release" >&2
  git status --short >&2
  exit 1
}

# Fail on a missing tool now, with an explanation, rather than half way through leaving the version
# bumped. These live in the venv described in the README; an inactive venv is the usual cause.
for tool in ruff pytest; do
  python3 -c "import $tool" 2>/dev/null || {
    echo "error: $tool is not importable -- activate the venv first:" >&2
    echo "    . .venv/bin/activate" >&2
    exit 1
  }
done
git rev-parse -q --verify "refs/tags/$tag" >/dev/null && {
  echo "error: tag $tag already exists" >&2; exit 1
}

current="$(python3 -c "import json;print(json.load(open('$manifest'))['version'])")"
[ "$current" != "$version" ] || {
  echo "error: the manifest already says $version -- nothing to bump" >&2; exit 1
}
echo "releasing $current -> $version"

# --- bump, regenerate, and verify BEFORE anything is committed ----------------------------------
# Any failure from here until the commit puts the version back. A half-applied release that leaves
# the tree claiming a version nobody shipped is worse than no release: the next run would refuse
# ("the manifest already says ..."), and the bump would be silently included in whatever is
# committed next. Cleared once the tag exists.
restore() {
  git checkout -- "$manifest" custom_components/haismart/manifest.json 2>/dev/null || true
  echo "release aborted; the version was put back to $current" >&2
}
trap restore ERR

python3 - "$manifest" "$version" <<'PY'
import json, sys
path, version = sys.argv[1], sys.argv[2]
with open(path) as fh:
    text = fh.read()
data = json.loads(text)
old = data["version"]
# Rewritten as text so the file keeps its own key order and formatting; json.dump would reorder
# nothing but would still reflow it, and this file is read by humans in diffs.
with open(path, "w") as fh:
    fh.write(text.replace(f'"version": "{old}"', f'"version": "{version}"', 1))
PY

./scripts/build-hacs.sh > /dev/null

echo "--- checks ---"
python3 -m ruff check packages/
./scripts/check-hacs-build.sh
python3 scripts/check-translations.py | tail -1
./scripts/test.sh

# The point of the whole script: what is about to be tagged must claim to be that version, in the
# generated copy as much as the source, since the generated one is what HACS installs.
for f in "$manifest" custom_components/haismart/manifest.json; do
  got="$(python3 -c "import json;print(json.load(open('$f'))['version'])")"
  [ "$got" = "$version" ] || { echo "error: $f says $got, expected $version" >&2; exit 1; }
done

# --- commit and tag ------------------------------------------------------------------------------
git add -A
git commit -q -m "release: $tag"
git tag -a "$tag" -m "$tag"
trap - ERR                      # committed: there is nothing left to put back
echo "committed and tagged $tag"

if [ "$push" = "--push" ]; then
  git push origin main
  git push origin "$tag"
  echo "pushed. Now publish the release notes:"
  echo "  gh release create $tag --title '$tag — <headline>' --notes '<notes>'"
else
  echo "NOT pushed. When you are happy:"
  echo "  git push origin main && git push origin $tag"
fi
