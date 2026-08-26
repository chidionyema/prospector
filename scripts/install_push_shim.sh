#!/usr/bin/env bash
# Install the pre-push shim into this repo's hooks directory.
#
# crew#326: three times (2026-08-23, 2026-08-26 17:06, 2026-08-26 20:55) this write clobbered
# ~/.estate/guards/hooks/_router. `git rev-parse --git-path hooks` honours core.hooksPath, so
# when the estate router is installed the "hooks dir" is the shared router directory and
# pre-push there is a symlink to _router; `cat >` follows the symlink and every commit and push
# on the machine is refused. The router already dispatches to $top/.githooks/<name>, so the
# shim has nothing to add there. Rule: never write a hook when core.hooksPath is set.
set -euo pipefail
if hp="$(git config --get core.hooksPath 2>/dev/null)" && [ -n "$hp" ]; then
  echo "[hooks] core.hooksPath=$hp dispatches to .githooks/pre-push already; not writing a shim"
  exit 0
fi
hooks_dir="$(git rev-parse --path-format=absolute --git-path hooks)"
mkdir -p "$hooks_dir"
if [ -L "$hooks_dir/pre-push" ]; then
  echo "[hooks] $hooks_dir/pre-push is a symlink; refusing to write through it" >&2
  exit 1
fi
cat > "$hooks_dir/pre-push" <<'HOOK'
#!/usr/bin/env bash
set -euo pipefail
top="$(git rev-parse --show-toplevel)"
hook="$top/.githooks/pre-push"
if [ ! -x "$hook" ]; then
  echo "pre-push: $hook missing or not executable; refusing rather than skipping."
  [ "${ALLOW_BRANCH_RECREATE:-}" = "1" ] || exit 1
  exit 0
fi
exec "$hook" "$@"
HOOK
chmod +x "$hooks_dir/pre-push"
echo "[hooks] pre-push installed at $hooks_dir/pre-push (per-tree, shared by every worktree)"
