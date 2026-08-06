#!/usr/bin/env bash
# Commit exactly the paths named on the command line, and nothing else.
#
# WHY THIS EXISTS
# ---------------
# Committing in this repo has five separate traps, all of them recorded, all of them still
# fired repeatedly — because the command was hand-authored from memory every single time, and
# knowing a trap exists does not help if you are re-typing the quoting at 1am. This script is
# the mechanical fix: the traps are handled once, here, and the caller has no quoting decisions
# left to make.
#
#   1. zsh does not word-split unquoted variables. `git commit --only $PATHS` passes every path
#      as ONE argument and dies with "pathspec 'a.py b.py c.py' did not match any file(s)".
#      Here paths arrive as "$@" — separate argv from the shell that invoked us — so there is no
#      variable to split and no way to get it wrong.
#   2. A bare `git commit` takes the WHOLE shared index, sweeping a concurrent session's staged
#      files into your commit. `--only` is not optional and is not left to the caller.
#   3. `git commit --only` cannot create a blob for an untracked path. New files are `git add`ed
#      first, automatically.
#   4. `.git/index.lock` races with concurrent sessions and with the POPDD gate's ~9-minute HEAD
#      window. We wait for the lock instead of failing.
#   5. `git commit ... | tail` reports the exit code of TAIL, so a failed commit looks like exit
#      0. Nothing here is piped, and the result is verified by reading `git log`/`git show`, not
#      by trusting a status code.
#
# USAGE
#   tools/commit_mine.sh -F <message-file> [-n] <path> [<path> ...]
#   tools/commit_mine.sh -m "<message>"    [-n] <path> [<path> ...]
#     -n   dry run: validate and report, change nothing.
set -uo pipefail

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
  echo "commit_mine: not inside a git repository" >&2; exit 2; }
cd "$REPO_ROOT" || exit 2

MSG_FILE=""; MSG_TEXT=""; DRY=0; PATHS=()
while [ $# -gt 0 ]; do
  case "$1" in
    -F) MSG_FILE="${2-}"; shift 2 ;;
    -m) MSG_TEXT="${2-}"; shift 2 ;;
    -n|--dry-run) DRY=1; shift ;;
    --) shift; while [ $# -gt 0 ]; do PATHS+=("$1"); shift; done ;;
    -*) echo "commit_mine: unknown flag $1" >&2; exit 2 ;;
    *) PATHS+=("$1"); shift ;;
  esac
done

[ -n "$MSG_FILE" ] || [ -n "$MSG_TEXT" ] || { echo "commit_mine: need -F file or -m text" >&2; exit 2; }
[ -z "$MSG_FILE" ] || [ -f "$MSG_FILE" ] || { echo "commit_mine: no such message file: $MSG_FILE" >&2; exit 2; }
[ "${#PATHS[@]}" -gt 0 ] || { echo "commit_mine: name at least one path" >&2; exit 2; }

# Every path must exist. A typo caught here is a 2-second error; a typo passed to git is a
# pathspec failure after the lock wait, and sometimes after a multi-minute pre-commit gate.
MISSING=0
for p in "${PATHS[@]}"; do
  [ -e "$p" ] || { echo "commit_mine: path does not exist: $p" >&2; MISSING=1; }
done
[ "$MISSING" -eq 0 ] || exit 2

echo "commit_mine: ${#PATHS[@]} path(s):"
for p in "${PATHS[@]}"; do printf '    %s\n' "$p"; done

# Trap 3: --only cannot mint a blob for an untracked path, so stage those (and only those).
UNTRACKED=()
for p in "${PATHS[@]}"; do
  git ls-files --error-unmatch -- "$p" >/dev/null 2>&1 || UNTRACKED+=("$p")
done
if [ "${#UNTRACKED[@]}" -gt 0 ]; then
  echo "commit_mine: untracked, will be staged first: ${UNTRACKED[*]}"
fi

if [ "$DRY" -eq 1 ]; then
  echo "commit_mine: dry run — nothing changed."
  exit 0
fi

# Trap 4: wait out a concurrent session's index.lock rather than failing on it.
for i in $(seq 1 120); do
  [ -e .git/index.lock ] || break
  [ "$i" -eq 1 ] && echo "commit_mine: .git/index.lock held by another process; waiting..."
  sleep 5
done
if [ -e .git/index.lock ]; then
  echo "commit_mine: .git/index.lock still held after 10 min; refusing to commit" >&2
  exit 3
fi

if [ "${#UNTRACKED[@]}" -gt 0 ]; then
  git add -- "${UNTRACKED[@]}" || { echo "commit_mine: git add failed" >&2; exit 4; }
fi

BEFORE=$(git rev-parse HEAD)

# Traps 1, 2 and 5: separate argv, always --only, never piped.
# `-F`/`-m` MUST come before the `--`: everything after `--` is a pathspec, so the message flag
# placed there is read as a filename to commit and git dies with "is outside repository". Caught
# by this script's own post-commit check on its first real run, which is the point of having one.
if [ -n "$MSG_FILE" ]; then
  git commit --only -F "$MSG_FILE" -- "${PATHS[@]}"
else
  git commit --only -m "$MSG_TEXT" -- "${PATHS[@]}"
fi
STATUS=$?

AFTER=$(git rev-parse HEAD)
echo "================ verify by reading git, not by the exit code ================"
if [ "$BEFORE" = "$AFTER" ]; then
  echo "commit_mine: HEAD did not move ($BEFORE) — NOTHING WAS COMMITTED (git exit $STATUS)" >&2
  exit "${STATUS:-5}"
fi
git show --stat --format='%H %s' HEAD

# Trap 2, verified rather than assumed: the commit must contain exactly the named paths.
LANDED=$(git show --name-only --format= HEAD | sed '/^$/d' | sort)
WANTED=$(printf '%s\n' "${PATHS[@]}" | sed 's#^\./##' | sort)
if [ "$LANDED" != "$WANTED" ]; then
  echo "commit_mine: WARNING — the commit's file list is not the list you named." >&2
  echo "  named but not in commit: $(comm -13 <(echo "$LANDED") <(echo "$WANTED") | tr '\n' ' ')" >&2
  echo "  in commit but not named: $(comm -23 <(echo "$LANDED") <(echo "$WANTED") | tr '\n' ' ')" >&2
  echo "  (a directory argument expands to its files, which is benign; anything else is a sweep)" >&2
  exit 6
fi
echo "commit_mine: OK — exactly the ${#PATHS[@]} named path(s) landed in $AFTER"
