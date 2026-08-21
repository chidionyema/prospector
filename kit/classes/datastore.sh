#!/usr/bin/env bash
# The datastore class: get the service's state onto the target BEFORE the cutover window.
#
# The runner calls this as `datastore.sh <verb>` with the step's variables in the environment:
#
#   RESOURCE         what is being moved, as the declaration names it
#   FROM, TO         the two substrates, as `deploy/targets/<name>.sh` names them
#   VERB             move | rollback
#   STEP_ID          the id the console shows, and the id `--from-step` resumes at
#   OPT_REMOTE_PATH  required. Where the state lands on the target.
#   OPT_VERIFY_CMD   optional. Run on the target against the seeded copy; non-zero fails the step.
#
# THIS SEEDS. IT DOES NOT TAKE THE AUTHORITATIVE COPY, AND THE DIFFERENCE IS THE WHOLE FILE.
#
# `kit/projects/schema.py:46` orders datastore BEFORE compute, which is right -- the state has
# to be there before the service lands on it. But the service is still RUNNING at that point,
# still writing. A copy taken here and treated as final is a copy that is stale by every write
# the source made afterwards, and the loss is silent: the new side comes up healthy, serving
# yesterday's rows. So this step takes a copy that is ALLOWED to be inconsistent, and the
# consistent one is taken inside `deploy/cutover.sh` phases 5-6, after the source is stopped.
#
# THAT IS ALSO WHY IT IS WORTH RUNNING AT ALL. The seed carries the bulk of the bytes outside
# the downtime window, so the copy taken while the service is stopped is a delta rather than
# the whole store. Clause A3 budgets that window in seconds; a cold full copy does not fit in it.
#
# The overlap with the cutover is therefore deliberate and safe in one direction only: the
# later copy overwrites this one. Never the reverse. Nothing here may run after the source stops.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO="$(git -C "$HERE" rev-parse --show-toplevel)"
# Neutral by clause A5: no product name may appear anywhere under kit/, and a default
# work directory named after one business is exactly the kind of hardcoding that makes
# the second business need a code change.
WORK="${MIGRATE_WORK_DIR:-${TMPDIR:-/tmp}/migrate-seed}"

die() { echo "datastore: $*" >&2; exit 1; }

# The target adapters. `MIGRATE_TARGETS_DIR` is not a test hook: clause A7 says a second
# business costs a declaration and no code, and a business on a substrate this repo has no
# adapter for would otherwise need one committed here. It also lets a run be exercised against
# a substrate made of directories, which is how the wire is graded without a cloud account.
TARGETS="${MIGRATE_TARGETS_DIR:-$REPO/deploy/targets}"

# Each adapter is sourced in a subshell so the two ends cannot collide on function names.
call() { local side="$1"; shift; ( set -euo pipefail; . "$TARGETS/$side.sh"; "$@" ); }

seed() {
  local tarball="$WORK/${RESOURCE:-datastore}.seed.tar.gz"
  local remote="$OPT_REMOTE_PATH"

  for side in "$FROM" "$TO"; do
    [ -f "$TARGETS/$side.sh" ] || die "no target adapter $side.sh in $TARGETS"
  done

  if [ "${DRY_RUN:-}" != "" ]; then
    echo "  DRY: pack $FROM -> $tarball; put on $TO; unpack at $remote${OPT_VERIFY_CMD:+; verify}"
    return 0
  fi

  mkdir -p "$WORK"
  call "$FROM" t_pack "$tarball"
  # t_pack is contracted to produce the file, but a target adapter that fails silently and
  # exits 0 would otherwise be discovered by tar, on the far side, as a corrupt archive.
  [ -s "$tarball" ] || die "$FROM t_pack produced nothing at $tarball"
  echo "datastore: packed $(du -h "$tarball" | cut -f1) from $FROM"

  call "$TO" t_put "$tarball" "$remote.seed.tar.gz"
  # Unpack beside the destination and move into place, never straight over it. An interrupted
  # untar directly onto $remote leaves a half-written store that looks present to everything
  # that checks for a directory, and the cutover's own verify would then grade the wreckage.
  call "$TO" t_exec "rm -rf '$remote.incoming' && mkdir -p '$remote.incoming' && tar xzf '$remote.seed.tar.gz' -C '$remote.incoming'"
  if [ -n "${OPT_VERIFY_CMD:-}" ]; then
    call "$TO" t_exec "$OPT_VERIFY_CMD '$remote.incoming'"
  fi
  call "$TO" t_exec "rm -rf '$remote' && mv '$remote.incoming' '$remote' && rm -f '$remote.seed.tar.gz'"
  echo "datastore: seeded $remote on $TO -- NOT authoritative; the cutover recopies after the source stops"
}

case "${1:-}" in
  move)
    [ -n "${FROM:-}" ] || die "no FROM -- the runner must name the substrate this resource is on"
    [ -n "${TO:-}" ]   || die "no TO -- the runner must name the substrate it is moving to"
    [ -n "${OPT_REMOTE_PATH:-}" ] || die "no remote_path option -- the declaration must say where the state lands"
    [ "$FROM" = "$TO" ] && { echo "datastore: both ends are $FROM -- nothing to seed"; exit 0; }
    seed
    ;;
  rollback)
    # NOTHING TO UNDO ON THE SOURCE. `t_pack` reads; the source was never modified, so the side
    # being returned to still holds the only copy that was ever authoritative. Undoing the seed
    # would mean deleting a directory on the target, and this class will not do that on a
    # failure path: the one time a delete here is wrong -- the plan resumed, or the operator
    # already re-pointed at the target -- it destroys the live store, which is the single
    # unrecoverable outcome in the whole run. Left behind, named, is the correct trade.
    echo "datastore: ${FROM:-the source} was only read, so it is intact and authoritative."
    echo "datastore: the seed at ${OPT_REMOTE_PATH:-the target path} on ${TO:-the target} is left in place -- deleting a datastore on a failure path is not a risk this class takes." >&2
    ;;
  "")
    die "no verb -- expected: datastore.sh move | datastore.sh rollback"
    ;;
  *)
    # Exit 78 is EX_CONFIG: a problem in the plan, not in the world. The runner reports it
    # differently from a step that tried and failed, because nothing was touched.
    echo "datastore: no such verb '$1' -- this class does move and rollback" >&2
    exit 78
    ;;
esac
