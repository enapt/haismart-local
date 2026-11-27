#!/usr/bin/env bash
# Regenerate the HACS-installable integration at the repo root: custom_components/haismart/, with the
# two helper libraries vendored inside it (so `requirements` can be empty — HACS/HA needs no pip step
# for the non-PyPI libs) and imported relatively from there (step 5). Run this after changing
# anything under packages/ and commit the result.
#
#   scripts/build-hacs.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC_COMPONENT="$ROOT/packages/ha-haismart/custom_components/haismart"
HRDP="$ROOT/packages/haismart-hrdp/src/haismart_hrdp"
EXTRACTOR="$ROOT/packages/haismart-extractor/src/haismart_extractor"
DEST="$ROOT/custom_components/haismart"

# custom_components/ is GENERATED. Editing it directly is a silent trap: the next build wipes the
# edit, and because the tests import the packages/ copy they keep passing while the change vanishes.
# So before destroying it, name anything the regeneration is about to discard.
if [ -z "${QUIET_BUILD:-}" ] && git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1; then
  if ! git -C "$ROOT" diff --quiet -- custom_components 2>/dev/null; then
    tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
    cp -r "$DEST" "$tmp/before"
    echo "==> note: custom_components/ has uncommitted changes; checking whether this build keeps them"
  fi
fi

echo "==> regenerating $DEST"
rm -rf "$DEST"
mkdir -p "$DEST/vendor"

# 1. the component itself
cp -r "$SRC_COMPONENT/." "$DEST/"

# 2. vendor the two libraries into ./vendor
cp -r "$HRDP" "$DEST/vendor/haismart_hrdp"
cp -r "$EXTRACTOR" "$DEST/vendor/haismart_extractor"

# 3. strip caches
find "$DEST" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
find "$DEST" -name '*.pyc' -delete 2>/dev/null || true

# 4. manifest: drop the pip requirements (libs are vendored now)
python3 - "$DEST/manifest.json" <<'PY'
import json, sys
p = sys.argv[1]
m = json.load(open(p))
m["requirements"] = []
json.dump(m, open(p, "w"), indent=2)
open(p, "a").write("\n")
PY

# 5. the integration reaches the bundled libraries RELATIVELY, as custom_components.haismart.vendor.*,
#    so they never become top-level modules of the Home Assistant process (one installed there would
#    shadow ours, and ours would shadow it) and nothing is added to sys.path. The source keeps its
#    absolute imports, which its tests and a source install (scripts/install-dev.sh) resolve against
#    the pip-installed libraries; only this generated copy is rewritten. The libraries themselves
#    import within themselves relatively already. The check below fails the build on any `import`
#    or `from` STATEMENT naming either library left anywhere in the copy, the libraries included.
#    A module path written as a string (importlib.import_module, mock.patch) is not a statement and
#    is not seen; none exists in the shipped code, and test_generated_copy.py's probe would fail on
#    one that runs at import.
#    packages/ha-haismart/tests/test_generated_copy.py tests the result.
printf '"""The two helper libraries, bundled with the integration: haismart_hrdp and haismart_extractor."""\n' \
  > "$DEST/vendor/__init__.py"
python3 - "$DEST" <<'PY'
import ast, re, sys
from pathlib import Path

dest = Path(sys.argv[1])
libs = ("haismart_hrdp", "haismart_extractor")
# `from haismart_hrdp[.sub] import ...` is the only form the integration uses. The component is one
# flat package, so `.vendor` is right for every module in it.
pattern = re.compile(r"^([ \t]*)from (haismart_hrdp|haismart_extractor)([. ])", re.M)
rewritten = 0
for path in sorted(dest.glob("*.py")):
    text = path.read_text(encoding="utf-8")
    new, n = pattern.subn(r"\1from .vendor.\2\3", text)
    if n:
        path.write_text(new, encoding="utf-8")
        rewritten += n

problems = []
for path in sorted(dest.rglob("*.py")):
    if "__pycache__" in path.parts:
        continue
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), str(path))):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        else:
            continue
        for name in names:
            if name.split(".")[0] in libs:
                problems.append(f"{path.relative_to(dest)}:{node.lineno}: {name}")
if problems:
    sys.exit(
        "build-hacs: absolute imports of a bundled library are left in the generated copy "
        "(the rewrite handles only `from haismart_hrdp[.x] import ...` in the integration's own "
        "modules; a library must import within itself relatively):\n  " + "\n  ".join(problems)
    )
print(f"==> {rewritten} imports of the bundled libraries made relative")
PY

# Report anything the regeneration threw away, so an edit made in the wrong place is caught here
# rather than going quietly missing.
if [ -n "${tmp:-}" ] && [ -d "$tmp/before" ]; then
  if ! diff -rq -x __pycache__ -x "*.pyc" "$tmp/before" "$DEST" >/dev/null 2>&1; then
    echo
    echo "!!  This build DISCARDED local changes under custom_components/:"
    # `diff` exits 1 when files differ and the script runs under `set -e -o pipefail`, so without
    # this the build would abort here - before printing the advice that makes the warning useful.
    diff -rq -x __pycache__ -x "*.pyc" "$tmp/before" "$DEST" 2>&1 \
      | sed "s|$tmp/before|your edit|g; s|$DEST|regenerated|g; s|^|!!    |" || true
    echo "!!"
    echo "!!  custom_components/ is generated. Make the change in packages/ instead:"
    echo "!!    the component      -> packages/ha-haismart/custom_components/haismart/"
    echo "!!    the helper libs     -> packages/haismart-hrdp/src, packages/haismart-extractor/src"
    echo "!!  then re-run this script."
    echo
  fi
fi

echo "==> done. Files:"
find "$DEST" -maxdepth 2 -type f | sed "s|$ROOT/||" | sort
