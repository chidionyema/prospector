#!/usr/bin/env bash
# The compute class: move the running service from one substrate to another.
#
# The runner calls this as `compute.sh <verb>` with the step's variables in the environment:
#
#   RESOURCE   what is being moved, as the declaration names it
#   FROM, TO   the two substrates, as `deploy/targets/<name>.sh` names them
#   VERB       move | rollback
#   STEP_ID    the id the console shows, and the id `--from-step` resumes at
#
# THIS SCRIPT ADDS NO LOGIC OF ITS OWN. `deploy/cutover.sh` already orders the phases so the
# source is stopped before the state is packed and the target is not started until the copy is
# proved -- two engines running at once keep two spend ledgers and can spend twice the daily
# cap. Re-implementing any of that here would be a second copy of a rule that is already
# written down and already tested. This script's whole job is to turn a verb and two
# environment variables into that command, and to translate its exit code.

set -euo pipefail

REPO="$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
CUTOVER="$REPO/deploy/cutover.sh"

die() { echo "compute: $*" >&2; exit 1; }

[ -x "$CUTOVER" ] || die "no cutover script at $CUTOVER"
[ -n "${FROM:-}" ] || die "no FROM -- the runner must name the substrate this resource is on"
[ -n "${TO:-}" ]   || die "no TO -- the runner must name the substrate it is moving to"

case "${1:-}" in
  move)
    exec "$CUTOVER" --from "$FROM" --to "$TO" ${DRY_RUN:+--dry-run}
    ;;
  rollback)
    # A rollback is the same move with the ends swapped, which is why the cutover script takes
    # both as arguments rather than baking either in. Note it also unwinds ITSELF on failure --
    # its own trap restarts the source. This verb is the outer net for a step the runner failed
    # for a reason the cutover never saw, and running it when the source is already back is a
    # no-op move from FROM to FROM, not a second stop.
    [ "$FROM" = "$TO" ] && { echo "compute: both ends are $FROM -- nothing to put back"; exit 0; }
    exec "$CUTOVER" --from "$TO" --to "$FROM" ${DRY_RUN:+--dry-run}
    ;;
  "")
    die "no verb -- expected: compute.sh move | compute.sh rollback"
    ;;
  *)
    # Exit 78 is EX_CONFIG: a problem in the plan, not in the world. The runner reports it
    # differently from a step that tried and failed, because nothing was touched.
    echo "compute: no such verb '$1' -- this class does move and rollback" >&2
    exit 78
    ;;
esac
