#!/usr/bin/env bash
#
# Make a fresh `git worktree` actually usable in this repo.
#
# WHY THIS EXISTS
# ---------------
# `git worktree add` gives you a tree that looks complete and is not. Three things are
# missing or wrong, and each one fails in a way that points at the wrong culprit — which
# is what makes them expensive. Measured on 2026-08-06, they cost a shipping session
# roughly forty minutes between them:
#
#   1. node_modules is absent, and you CANNOT fix it with a symlink.
#      Turbopack rejects any node_modules symlink that leaves the project root:
#        TurbopackInternalError: Symlink [project]/node_modules is invalid,
#        it points out of the filesystem root
#      This is not a same-filesystem problem — pointing the link at another directory on
#      /Users fails identically. It must be a real directory. `cp -Rc` uses APFS
#      copy-on-write, so the 665M costs seconds and almost no disk.
#      Worse, `npm run build 2>&1 | tail` reports exit 0 through the pipe while the build
#      has actually failed, so this trap can be mistaken for a passing gate.
#
#   2. .lux/keys/agent.pem is UNTRACKED, so a worktree has no POPDD signing key and the
#      pre-commit gate cannot pass. The hook itself is shared (git resolves hooks via the
#      common dir), so the gate runs — it just cannot sign.
#
#   3. .venv is absent, and the POPDD hook pins the interpreter RELATIVE to the cwd:
#        .lux/hooks/pre-commit:67
#        VERIFY_CMD="${POPDD_VERIFY_CMD:-.venv/bin/python scripts/popdd_verify.py --staged}"
#      so every commit in a worktree dies with `sh: .venv/bin/python: No such file or
#      directory` followed by "POPDD gate BLOCKED this commit" — which reads as a failed
#      proof, not a missing interpreter. Unlike node_modules, a symlink is fine here.
#
#   4. store/ and storage/ are tracked runtime state. Running pytest in a worktree dirties
#      them. That is harmless HERE (it is a copy, not production) but it means you must
#      never `git add -A` in a worktree — you will commit test pollution. This script
#      does not fix that; it just tells you, because there is nothing to fix.
#
#   5. .env and the ENGINE'S OWN STATE are gitignored, so a worktree gets neither — and both
#      fail as something else. Measured 2026-08-14, two dead publish runs:
#        .gitignore:34  .env             -> "ERROR: PROSPECTOR_ENTITLEMENTS_API_KEY unset
#                                           after .env load; EngineBridge will refuse publish."
#                                           which reads as a revoked/missing credential, not
#                                           as an absent file.
#        .gitignore:43  store/dossiers/  -> the pass exists in the main checkout and the
#                                           worktree finds nothing, so a republish reads as
#                                           "that pack is not a PASS" rather than "wrong tree".
#      .env is SYMLINKED (one source of truth; a rotated key must propagate, and secrets
#      should not be copied around the disk). The store dirs are CoW CLONES, not links, so a
#      pytest run in the worktree cannot write into production state — which is the whole
#      reason trap 4 exists.
#
#      That said: a PRODUCTION publish belongs in the main checkout. A cloned store diverges
#      the moment either tree writes, so the worktree's copy is for tests and dry runs.
#
# USAGE
#   git worktree add --detach ../my-worktree <ref>
#   ./scripts/setup_worktree.sh ../my-worktree
#
# Idempotent: safe to re-run. Does nothing to the main checkout.

set -euo pipefail

TARGET="${1:-$PWD}"
cd "$TARGET"
TARGET="$PWD"

# The main checkout is the one holding the real .git directory and the untracked key.
COMMON_DIR="$(git rev-parse --path-format=absolute --git-common-dir)"
MAIN_CHECKOUT="$(dirname "$COMMON_DIR")"

if [ "$MAIN_CHECKOUT" = "$TARGET" ]; then
  echo "==> $TARGET is the main checkout, not a worktree. Nothing to set up."
  exit 0
fi

echo "==> worktree:      $TARGET"
echo "==> main checkout: $MAIN_CHECKOUT"

# ---------------------------------------------------------------- 1. POPDD signing key
KEY_REL=".lux/keys/agent.pem"
if [ -f "$TARGET/$KEY_REL" ]; then
  echo "[key]  already present"
elif [ -f "$MAIN_CHECKOUT/$KEY_REL" ]; then
  mkdir -p "$TARGET/.lux/keys"
  cp "$MAIN_CHECKOUT/$KEY_REL" "$TARGET/$KEY_REL"
  chmod 600 "$TARGET/$KEY_REL"
  echo "[key]  copied from main checkout (it is untracked, so worktrees never get it)"
else
  echo "[key]  WARNING: no $KEY_REL in the main checkout either; the POPDD gate will fail"
fi

# ------------------------------------------------------------------- 2. node_modules
# EVERY npm project the POPDD gate has a lane for, not just the storefront. On 2026-08-17
# this block copied Store.Web only, so the gate refused a commit with
# "missing store_platform/src/Ops.Console/node_modules — cannot prove this lane" —
# a FAIL on a lane it never actually inspected. Add a project here when you add a lane.
for REL in store_platform/src/Store.Web store_platform/src/Ops.Console; do
  WEB="$TARGET/$REL"
  SRC_MODULES="$MAIN_CHECKOUT/$REL/node_modules"
  [ -d "$WEB" ] || continue
  if [ -L "$WEB/node_modules" ]; then
    echo "[deps] $REL: removing a SYMLINKED node_modules — Turbopack rejects it (see header)"
    rm -f "$WEB/node_modules"
  fi
  if [ -d "$WEB/node_modules" ]; then
    echo "[deps] $REL: already a real directory ($(ls "$WEB/node_modules" | wc -l | tr -d ' ') entries)"
  elif [ -d "$SRC_MODULES" ]; then
    echo "[deps] $REL: cloning node_modules from the main checkout (APFS copy-on-write)..."
    cp -Rc "$SRC_MODULES" "$WEB/node_modules"
    echo "[deps] $REL: done ($(ls "$WEB/node_modules" | wc -l | tr -d ' ') entries)"
  else
    echo "[deps] $REL: no node_modules in the main checkout; run 'npm ci' in $WEB"
  fi
done

# ------------------------------------------------------------------- 3. python venv
# A symlink IS fine here: python resolves sys.executable through it, so the worktree gets
# the main checkout's interpreter and packages. (node_modules is the odd one out.)
if [ -e "$TARGET/.venv" ]; then
  echo "[venv] already present"
elif [ -d "$MAIN_CHECKOUT/.venv" ]; then
  ln -sfn "$MAIN_CHECKOUT/.venv" "$TARGET/.venv"
  echo "[venv] symlinked to the main checkout (the POPDD hook pins .venv/bin/python)"
else
  echo "[venv] WARNING: no .venv in the main checkout; every commit here will be BLOCKED"
fi

# ------------------------------------------------------------------- 4. .env
# Symlinked, never copied: it is the only place the API keys live, and a copy silently
# outlives a rotation. Every loader in the repo reads ./.env relative to cwd.
if [ -e "$TARGET/.env" ]; then
  echo "[env]  already present"
elif [ -f "$MAIN_CHECKOUT/.env" ]; then
  ln -sfn "$MAIN_CHECKOUT/.env" "$TARGET/.env"
  echo "[env]  symlinked to the main checkout (.env is gitignored, so worktrees never get it)"
else
  echo "[env]  WARNING: no .env in the main checkout; anything touching the store API will"
  echo "[env]           die with 'PROSPECTOR_ENTITLEMENTS_API_KEY unset after .env load'"
fi

# ------------------------------------------------------------------- 5. engine state
# CoW clones, NOT symlinks: a worktree pytest run must not be able to write into production
# dossiers/listings. Cheap on APFS (115M of dossiers costs seconds and almost no disk).
# store/_cache/ is deliberately excluded — 22k files, and a cold cache costs latency and
# provider quota, not correctness. Clone it by hand if a run would otherwise re-fetch:
#   cp -Rc <main>/store/_cache <worktree>/store/_cache
for REL in store/dossiers store/listings store/runs store/golden_runs; do
  if [ -d "$TARGET/$REL" ] && [ -n "$(ls -A "$TARGET/$REL" 2>/dev/null)" ]; then
    echo "[state] $REL already populated ($(ls "$TARGET/$REL" | wc -l | tr -d ' ') entries)"
  elif [ -d "$MAIN_CHECKOUT/$REL" ]; then
    mkdir -p "$(dirname "$TARGET/$REL")"
    rm -rf "$TARGET/$REL"
    cp -Rc "$MAIN_CHECKOUT/$REL" "$TARGET/$REL"
    echo "[state] cloned $REL ($(ls "$TARGET/$REL" | wc -l | tr -d ' ') entries, copy-on-write)"
  else
    echo "[state] no $REL in the main checkout; skipping"
  fi
done

# ------------------------------------------------------------------- 6. the warnings
cat <<'NOTE'

[note] Things this script deliberately does NOT do, because they are not fixable here:

  * A PRODUCTION publish belongs in the MAIN checkout. store/ here is a clone taken at
    setup time; it diverges the moment either tree writes, and a publish run from a
    worktree writes the catalogue row somewhere the daemon will never read.


  * NEVER `git add -A` in a worktree. store/ and storage/ are tracked runtime state and
    pytest writes to them. Stage explicit paths, and check `git status` before committing.

  * `npm run build | tail` reports the exit code of `tail`, not of the build. Capture the
    build's own status first:  npm run build > /tmp/build.log 2>&1; echo "exit=$?"

  * If you `git worktree move` a tree you have already run pytest in, DELETE the bytecode
    caches afterwards. .pyc files bake the absolute path into co_filename, so anything
    using inspect.getsource fails with
    "OSError: could not get source code" — pointing at auth, not at the move:
      find . -name __pycache__ -type d -not -path '*/node_modules/*' -exec rm -rf {} +

NOTE
echo "==> worktree ready."
