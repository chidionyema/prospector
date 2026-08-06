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
WEB="$TARGET/store_platform/src/Store.Web"
SRC_MODULES="$MAIN_CHECKOUT/store_platform/src/Store.Web/node_modules"
if [ -d "$WEB" ]; then
  if [ -L "$WEB/node_modules" ]; then
    echo "[deps] removing a SYMLINKED node_modules — Turbopack rejects it (see header)"
    rm -f "$WEB/node_modules"
  fi
  if [ -d "$WEB/node_modules" ]; then
    echo "[deps] already a real directory ($(ls "$WEB/node_modules" | wc -l | tr -d ' ') entries)"
  elif [ -d "$SRC_MODULES" ]; then
    echo "[deps] cloning node_modules from the main checkout (APFS copy-on-write)..."
    cp -Rc "$SRC_MODULES" "$WEB/node_modules"
    echo "[deps] done: $(ls "$WEB/node_modules" | wc -l | tr -d ' ') entries"
  else
    echo "[deps] no node_modules in the main checkout; run 'npm ci' in $WEB"
  fi
fi

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

# ------------------------------------------------------------------- 4. the warnings
cat <<'NOTE'

[note] Two things this script deliberately does NOT do, because they are not fixable here:

  * NEVER `git add -A` in a worktree. store/ and storage/ are tracked runtime state and
    pytest writes to them. Stage explicit paths, and check `git status` before committing.

  * `npm run build | tail` reports the exit code of `tail`, not of the build. Capture the
    build's own status first:  npm run build > /tmp/build.log 2>&1; echo "exit=$?"

  * If you `git worktree move` a tree you have already run pytest in, DELETE the bytecode
    caches afterwards. .pyc files bake the absolute path into co_filename, so anything
    using inspect.getsource (the control_center auth tests do) fails with
    "OSError: could not get source code" — pointing at auth, not at the move:
      find . -name __pycache__ -type d -not -path '*/node_modules/*' -exec rm -rf {} +

NOTE
echo "==> worktree ready."
