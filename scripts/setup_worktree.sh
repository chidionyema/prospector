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
# PRESENT IS NOT ENOUGH — IT MUST BE THE SAME KEY. This block used to stop at
# `[ -f "$TARGET/$KEY_REL" ] && echo "already present"`, which accepts a key the estate has
# never seen. Measured 2026-08-20 in the wt-redesign worktree: it held a key generated at
# 14:37 that afternoon, so setup reported "[key] already present" and every commit there
# failed with `Chain valid: False` / "signature invalid at 0" AFTER running the whole
# suite — 6772 tests passed and the gate still refused. The chain's head is
# .lux/receipts/2026-06-17.jsonl, which IS TRACKED and was signed by the main checkout's
# key, so a worktree with any other key can never verify receipt 0 and no diff can fix it.
# The failure names the receipt chain, which reads as a POPDD bug rather than a wrong key.
KEY_REL=".lux/keys/agent.pem"
if [ ! -f "$MAIN_CHECKOUT/$KEY_REL" ]; then
  echo "[key]  WARNING: no $KEY_REL in the main checkout; the POPDD gate will fail"
elif [ -f "$TARGET/$KEY_REL" ] && cmp -s "$MAIN_CHECKOUT/$KEY_REL" "$TARGET/$KEY_REL"; then
  echo "[key]  already present and identical to the main checkout"
else
  # Keep the odd one rather than deleting it: it signed whatever receipts this tree already
  # wrote, and a key is the one file here that cannot be regenerated from git.
  if [ -f "$TARGET/$KEY_REL" ]; then
    mv "$TARGET/$KEY_REL" "$TARGET/$KEY_REL.does-not-match-main.bak"
    echo "[key]  the key here was NOT the main checkout's — moved aside as"
    echo "[key]  $KEY_REL.does-not-match-main.bak. Every commit in this tree was failing"
    echo "[key]  at receipt 0 of the tracked chain. Replacing it with the main checkout's."
  fi
  mkdir -p "$TARGET/.lux/keys"
  cp "$MAIN_CHECKOUT/$KEY_REL" "$TARGET/$KEY_REL"
  chmod 600 "$TARGET/$KEY_REL"
  echo "[key]  copied from main checkout (it is untracked, so worktrees never get it)"
fi


# `deps_missing <project-dir>` prints the declared packages that are NOT on disk, space
# separated, and prints nothing when the install is complete.
#
# GRADED AGAINST package.json, NEVER AGAINST AN ENTRIES COUNT. A count answers "is there
# something here", and the question that decides whether the gate can run is "is the thing
# THIS BRANCH declares here". The two differ exactly when a branch adds a dependency, which
# is the case the old check was blind to.
#
# optionalDependencies are deliberately not graded: npm may legitimately skip one for this
# platform and the install is still complete. Grading them would make a correct tree fail.
#
# The size of the hole this closes, measured 2026-08-20 in one worktree that the old check
# had called ready: Ops.Console was missing 4 declared packages (react-markdown, remark-gfm,
# @axe-core/playwright, eslint-plugin-tailwindcss, all added by f7eeab3a) and Store.Web was
# missing 16, including @testing-library/react, storybook and stylelint. The POPDD console
# lane failed typecheck with TS2307 "Cannot find module", vitest never ran, and the verdict
# printed "(0 passed, 0 failed)" — which reads as a broken import in the author's own diff.
deps_missing() {
  python3 - "$1" <<'PY'
import json, os, sys
root = sys.argv[1]
pkg = os.path.join(root, "package.json")
if not os.path.isfile(pkg):
    raise SystemExit(0)
with open(pkg, encoding="utf8") as fh:
    declared = json.load(fh)
want = list(declared.get("dependencies", {})) + list(declared.get("devDependencies", {}))
nm = os.path.join(root, "node_modules")
# A scoped name is a nested path on disk: @scope/pkg -> node_modules/@scope/pkg
missing = [n for n in want if not os.path.exists(os.path.join(nm, *n.split("/")))]
print(" ".join(sorted(missing)))
PY
}

DEPS_INCOMPLETE=0

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
    echo "[deps] $REL: node_modules is a real directory; checking what package.json declares"
  elif [ -d "$SRC_MODULES" ]; then
    echo "[deps] $REL: cloning node_modules from the main checkout (APFS copy-on-write)..."
    cp -Rc "$SRC_MODULES" "$WEB/node_modules"
  else
    echo "[deps] $REL: no node_modules in the main checkout"
  fi

  # The clone above is a starting point, not an answer: it copies the MAIN checkout's
  # install, which is as old as whenever someone last ran npm there. The branch in this
  # worktree may declare more.
  MISSING="$(deps_missing "$WEB")"
  if [ -n "$MISSING" ]; then
    echo "[deps] $REL: $(echo $MISSING | wc -w | tr -d ' ') declared package(s) absent: $(echo $MISSING | cut -c1-140)"
    echo "[deps] $REL: running npm install to fetch them..."
    ( cd "$WEB" && npm install --no-audit --no-fund ) || true
    MISSING="$(deps_missing "$WEB")"
  fi
  if [ -n "$MISSING" ]; then
    echo "[deps] $REL: STILL ABSENT after npm install: $(echo $MISSING | cut -c1-200)"
    DEPS_INCOMPLETE=1
  else
    echo "[deps] $REL: every declared dependency is on disk"
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

# ------------------------------------------------- 3a. the receipt chain (AFTER the venv)
# A daily receipt file signed by a key this tree no longer holds wedges the gate the same way,
# and it is not covered by the key check above: the key can be correct now and the file still
# hold receipts written under the old one. Move it aside so a fresh chain starts under the key
# that is actually here. It is gitignored scratch, so nothing tracked is lost.
#
# THIS BLOCK MUST STAY BELOW THE VENV STEP. It ran above it until 2026-08-21, and .venv does
# not exist in a fresh worktree until the step above creates it — so `.venv/bin/python` was
# always "No such file or directory", the check always failed, and EVERY fresh worktree was
# told "the receipt chain does not verify / Every commit in this tree will be BLOCKED at
# 'Chain valid: False'" while the chain was fine. Measured that day in ../prospector-rust:
# the warning printed, and re-running the identical check after setup returned
# {'valid': True, 'total': 2}. The noisy branch was the lucky one — on any day this tree
# already had a receipt file, the other branch would silently rename a PERFECTLY GOOD chain.
#
# And it grades on a PRINTED TOKEN, not on the exit status, because that is the class of
# mistake rather than the instance: exit 1 is what python returns for an invalid chain AND
# for an ImportError, and 127 is what the shell returns for a missing interpreter. Only an
# explicit CHAIN_INVALID may move a file. Anything else is "could not measure", which is a
# different fact and must never destroy anything.
if [ -f "$TARGET/$KEY_REL" ] && [ -d "$TARGET/.lux/receipts" ]; then
  CHAIN_OUT="$( cd "$TARGET" && .venv/bin/python -c "
import sys, pathlib
sys.path.insert(0, '.')
from popdd_agent import PopddAgent
print('CHAIN_VALID' if PopddAgent.at_path(pathlib.Path('.').resolve()).verify_chain()['valid'] else 'CHAIN_INVALID')
" 2>/dev/null || true )"
  case "$CHAIN_OUT" in
    *CHAIN_VALID*)
      echo "[key]  receipt chain verifies under this tree's key"
      ;;
    *CHAIN_INVALID*)
      today="$(date -u +%Y-%m-%d)"
      if [ -f "$TARGET/.lux/receipts/$today.jsonl" ]; then
        mv "$TARGET/.lux/receipts/$today.jsonl" "$TARGET/.lux/receipts/$today.jsonl.unverifiable.bak"
        echo "[key]  today's receipt chain did not verify — moved aside; a fresh one starts now"
      else
        echo "[key]  WARNING: the receipt chain does not verify and it is not today's file."
        echo "[key]           Every commit in this tree will be BLOCKED at 'Chain valid: False'."
      fi
      ;;
    *)
      echo "[key]  WARNING: could not run the receipt-chain check (no interpreter, or"
      echo "[key]           popdd_agent did not import). This is NOT a verdict on the chain,"
      echo "[key]           so nothing was moved. Check by hand before you rely on the gate."
      ;;
  esac
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

# ------------------------------------------------------------------- 5b. the push fences
# One hooks directory serves every worktree (it lives in the common git dir), so this installs
# once and covers all of them. The shim resolves the CALLING tree's own .githooks/pre-push, so a
# new tree never runs an old tree's fences.
#
# It is a file in .git/hooks rather than `core.hooksPath=.githooks`, deliberately: hooksPath
# replaces the directory outright, which would make the graphify post-commit and post-checkout
# hooks inert without a word.
hooks_dir="$(git rev-parse --path-format=absolute --git-path hooks)"
mkdir -p "$hooks_dir"
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

# ---------------------------------------------------------------- 6. the warnings
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
if [ "$DEPS_INCOMPLETE" = "1" ]; then
  # SAY IT IS NOT READY. The whole cost of the old version was that it reported a tree
  # ready and the gate refused the first commit minutes later, naming a TypeScript error
  # in a file the author had never opened. Failing here spends the same minutes with the
  # right label on them.
  echo "==> worktree NOT ready: declared npm packages are still absent (see [deps] above)."
  echo "    The POPDD gate will refuse a commit here with 'Cannot find module ...' errors."
  exit 1
fi

echo "==> worktree ready."
