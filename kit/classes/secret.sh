#!/usr/bin/env bash
# The secret class: put the keys the service needs on the substrate it is moving to.
#
# The runner calls this as `secret.sh <verb>` with the step's variables in the environment:
#
#   RESOURCE          what is being moved, as the declaration names it
#   FROM, TO          the two substrates, as `deploy/targets/<name>.sh` names them
#   VERB              move | rollback
#   STEP_ID           the id the console shows, and the id `--from-step` resumes at
#   OPT_KEEP_PATTERN  required. An extended regex matching the `KEY=` lines that travel.
#   OPT_ENV_FILE      optional. Where the keys are read from; discovered when absent.
#
# WHICH KEYS TRAVEL IS THE PROJECT'S FACT, NOT THE KIT'S. A list of key names compiled into
# this file would be one business's private inventory sitting in shared code, and the second
# business would need a code change to add its own -- the two things clauses A5 and A7 exist
# to stop. So the pattern arrives as an option, this script never contains a key name, and a
# new project's answer is a line in its declaration.
#
# NO VALUE IS EVER PRINTED, AND NO VALUE IS EVER AN ARGUMENT. The filtered file is written
# with a private umask and handed to the target adapter BY PATH. A value passed on a command
# line is visible to every other process on the box for as long as the call runs, and lands
# in the shell history of whoever is watching.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO="$(git -C "$HERE" rev-parse --show-toplevel)"

die() { echo "secret: $*" >&2; exit 1; }

# The target adapters. `MIGRATE_TARGETS_DIR` is not a test hook: clause A7 says a second
# business costs a declaration and no code, and a business on a substrate this repo has no
# adapter for would otherwise need one committed here. It also lets a run be exercised against
# a substrate made of directories, which is how the wire is graded without a cloud account.
TARGETS="${MIGRATE_TARGETS_DIR:-$REPO/deploy/targets}"

# Each adapter is sourced in a subshell so the two ends cannot collide on function names.
# Same rule, and the same one line, as `deploy/cutover.sh`.
call() { local side="$1"; shift; ( set -euo pipefail; . "$TARGETS/$side.sh"; "$@" ); }

# The secrets live in the MAIN checkout, and a migration usually runs from a worktree, which
# never has a `.env` of its own. Found through git rather than guessed, exactly as
# `deploy/cutover.sh::_default_env` finds it -- if the two ever disagree, a cutover pushes one
# set of keys and this class pushes another, and the failure surfaces as an authentication
# error from a provider rather than as a missing file.
_default_env() {
  [ -f "$REPO/.env" ] && { echo "$REPO/.env"; return; }
  local common main
  common="$(cd "$(git -C "$REPO" rev-parse --git-common-dir 2>/dev/null || echo .)" && pwd -P)"
  main="$(dirname "$common")"
  [ -f "$main/.env" ] && { echo "$main/.env"; return; }
  echo "$REPO/.env"
}

push() {
  local side="$1" env_file work kept
  env_file="${OPT_ENV_FILE:-$(_default_env)}"
  [ -f "$env_file" ] || die "no env file at $env_file -- there is nothing to push"
  [ -n "${OPT_KEEP_PATTERN:-}" ] || die "no keep_pattern option -- the declaration must say which keys travel"
  [ -f "$TARGETS/$side.sh" ] || die "no target adapter $side.sh in $TARGETS"

  # 077 before the file exists, not chmod after: between creation and chmod the keys are
  # world-readable, and that window is long enough on a shared box.
  work="$(umask 077 && mktemp "${TMPDIR:-/tmp}/secret-XXXXXX.env")"
  # EXIT, not RETURN: `die` exits the shell, and a RETURN trap does not fire on that path --
  # which is the path that leaves a file full of live credentials in a world-writable /tmp.
  WORKFILE="$work"; trap 'rm -f "$WORKFILE"' EXIT
  grep -E "$OPT_KEEP_PATTERN" "$env_file" > "$work" || true

  # An empty file is the dangerous case, because `t_secrets` accepts it and the service then
  # starts with no credentials at all -- which fails later, on the far side, as a provider
  # outage. A pattern that matches nothing is a defect in the declaration, so say so here.
  kept="$(wc -l < "$work" | tr -d ' ')"
  [ "$kept" -gt 0 ] || die "keep_pattern matched no key in $env_file -- refusing to push an empty secret set"
  echo "secret: pushing $kept key(s) to $side"     # the COUNT. Never a name, never a value.

  if [ "${DRY_RUN:-}" = "" ]; then
    call "$side" t_secrets "$work"
  else
    echo "  DRY: call $side t_secrets <$kept keys>"
  fi
}

case "${1:-}" in
  move)
    [ -n "${TO:-}" ] || die "no TO -- the runner must name the substrate it is moving to"
    push "$TO"
    ;;
  rollback)
    # NOTHING TO UNDO ON THE SOURCE, AND THAT IS NOT A GAP. `t_secrets` COPIES: the keys were
    # never removed from FROM, so the side being returned to already holds them and pushing
    # again would change nothing.
    #
    # What IS left behind is the copy on TO, and the target contract has no verb that removes
    # one -- twelve functions, `deploy/PORTABILITY.md:44`, and none of them is a purge. So an
    # abandoned target keeps a live credential set until someone deletes it by hand. That is a
    # real hole in clause A2 (0 resources left behind) and it is reported rather than hidden,
    # because a rollback that prints "done" over an unrevoked key is worse than one that does
    # not run: the operator stops looking.
    echo "secret: the keys on ${TO:-the target} were copied, not moved -- ${FROM:-the source} still has its own set."
    echo "secret: THE COPY ON ${TO:-the target} IS STILL LIVE. The target contract has no purge verb, so revoke it by hand." >&2
    ;;
  "")
    die "no verb -- expected: secret.sh move | secret.sh rollback"
    ;;
  *)
    # Exit 78 is EX_CONFIG: a problem in the plan, not in the world. The runner reports it
    # differently from a step that tried and failed, because nothing was touched.
    echo "secret: no such verb '$1' -- this class does move and rollback" >&2
    exit 78
    ;;
esac
