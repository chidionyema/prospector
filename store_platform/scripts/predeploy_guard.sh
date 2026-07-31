#!/usr/bin/env bash
# Refuse to deploy from a dirty store_platform/ tree.
#
# Why this exists: `fly deploy` builds the WORKING TREE, not HEAD. Any half-finished edit
# sitting in store_platform/ — including one made by a different session or agent that you
# never saw — ships to production silently and is not recoverable from git, because it was
# never committed. This happened on 2026-07-30.
#
# Read-only. Exit 0 = safe to deploy. Exit 1 = commit or stash first.
#
#   bash scripts/predeploy_guard.sh && fly deploy . --config deploy/fly/api.fly.toml
#
set -euo pipefail

repo_root=$(git rev-parse --show-toplevel 2>/dev/null) || {
  echo "FAIL  not inside a git repository — cannot prove what would ship" >&2
  exit 1
}
cd "$repo_root"

dirty=$(git status --porcelain -- store_platform)

if [ -n "$dirty" ]; then
  echo "FAIL  store_platform/ is dirty — $(printf '%s\n' "$dirty" | wc -l | tr -d ' ') path(s) would ship uncommitted:" >&2
  printf '%s\n' "$dirty" >&2
  cat >&2 <<'EOF'

`fly deploy` ships the working tree. Everything listed above would go to production
without existing in git, so the deployed code could not be rebuilt or rolled back.

Fix: commit what you intend to ship, or `git stash` what you do not, then re-run.
EOF
  exit 1
fi

echo "PASS  store_platform/ is clean at $(git rev-parse --short HEAD) — deploy would ship exactly this commit"
