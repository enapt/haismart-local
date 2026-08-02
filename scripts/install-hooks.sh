#!/usr/bin/env bash
# Install the repo's git hooks.
#
# Just the one for now: a pre-commit check that refuses a commit editing the generated
# custom_components/ tree with no matching source change (see scripts/check-staged-tree.sh for why
# that case is invisible to every other check we have).
#
#   scripts/install-hooks.sh
#
# Hooks are not versioned by git, so this has to be run once per clone. It never overwrites an
# existing hook without saying so.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
hooks="$(git -C "$root" rev-parse --git-path hooks)"
hook="$hooks/pre-commit"

mkdir -p "$hooks"
if [ -e "$hook" ] && ! grep -q 'check-staged-tree.sh' "$hook" 2>/dev/null; then
  echo "==> $hook already exists and is not ours; leaving it alone." >&2
  echo "    Add this line to it yourself:" >&2
  echo "        \"\$(git rev-parse --show-toplevel)/scripts/check-staged-tree.sh\" || exit 1" >&2
  exit 1
fi

cat > "$hook" <<'HOOK'
#!/usr/bin/env bash
# Installed by scripts/install-hooks.sh
"$(git rev-parse --show-toplevel)/scripts/check-staged-tree.sh" || exit 1
HOOK
chmod +x "$hook"
echo "==> installed $hook"
