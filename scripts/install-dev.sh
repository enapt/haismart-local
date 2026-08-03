#!/usr/bin/env bash
# Install the Haismart integration into a Home Assistant config directory for testing.
#
# It does the two things a manual copy misses:
#   1. pip-installs the two helper libs (haismart-hrdp, haismart-extractor) INTO HA's Python env,
#      because they are not on PyPI â€” so HA sees the manifest requirements already satisfied instead
#      of trying (and failing) to fetch them at startup.
#   2. copies (or symlinks) custom_components/haismart into <config>/custom_components/.
#
# cryptography + httpx are already shipped with Home Assistant, so nothing else is needed.
#
# Usage:
#   scripts/install-dev.sh --config <HA config dir> [--python <ha python>] [--symlink] [--copy-only]
#
#   --config DIR    HA config directory (the one holding configuration.yaml). REQUIRED.
#   --python EXE    Python interpreter of the HA environment (default: python3). For a venv install
#                   point it at <venv>/bin/python; for Docker run this script INSIDE the container.
#   --symlink       Symlink the component instead of copying (handy for dev: edits apply on restart).
#   --copy-only     Skip the pip step (only copy/symlink the component). Use if the libs are already
#                   importable in HA's env.
#
# Env: PYTHON=<exe> works too (same as --python). Examples in INSTALL.md.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
py="${PYTHON:-python3}"
config=""
mode="copy"        # copy | symlink
do_pip=1

usage() { sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --config)   config="${2:-}"; shift 2 ;;
    --python)   py="${2:-}"; shift 2 ;;
    --symlink)  mode="symlink"; shift ;;
    --copy-only) do_pip=0; shift ;;
    -h|--help)  usage 0 ;;
    *) echo "unknown arg: $1" >&2; usage 1 ;;
  esac
done

[ -n "$config" ] || { echo "error: --config <HA config dir> is required" >&2; usage 1; }
[ -d "$config" ] || { echo "error: config dir not found: $config" >&2; exit 1; }

src="$root/packages/ha-haismart/custom_components/haismart"
[ -d "$src" ] || { echo "error: component not found at $src (run from the repo)" >&2; exit 1; }

if [ "$do_pip" -eq 1 ]; then
  echo "==> installing helper libs into: $("$py" -c 'import sys; print(sys.prefix)')"
  "$py" -m pip install --upgrade \
      "$root/packages/haismart-hrdp" \
      "$root/packages/haismart-extractor"
  # sanity: both must import in THIS interpreter (= HA's, if you passed the right --python)
  "$py" - <<'PY'
import haismart_hrdp, haismart_extractor  # noqa: F401
print("==> import check OK (haismart_hrdp + haismart_extractor available)")
PY
else
  echo "==> --copy-only: skipping pip (assuming the libs are already in HA's env)"
fi

dest_dir="$config/custom_components"
dest="$dest_dir/haismart"
mkdir -p "$dest_dir"
rm -rf "$dest"                      # clean any previous install (only the haismart/ subdir)
if [ "$mode" = "symlink" ]; then
  ln -sfn "$src" "$dest"
  echo "==> symlinked $dest -> $src"
else
  cp -r "$src" "$dest"
  find "$dest" -name __pycache__ -type d -prune -exec rm -rf {} +   # drop dev bytecode
  echo "==> copied component to $dest"
fi

cat <<EOF

Done. Next:
  1. Restart Home Assistant.
  2. Settings -> Devices & Services -> Add Integration -> "Haismart".
  3. Pick an onboarding path (see INSTALL.md): 'login' (email/password + region) is easiest.

If HA logs "Requirements for haismart not found", the libs landed in a DIFFERENT Python than HA's â€”
re-run with --python pointing at HA's interpreter (venv: <venv>/bin/python; Docker: run inside the
container). See INSTALL.md "Troubleshooting".
EOF
