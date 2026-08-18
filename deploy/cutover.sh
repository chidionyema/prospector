#!/usr/bin/env bash
# Move the engine from one platform to another. Neither end is hardcoded.
#
#   deploy/cutover.sh --from laptop --to fly          # tonight
#   deploy/cutover.sh --from fly    --to sshdocker    # the day we leave Fly
#   deploy/cutover.sh --from fly    --to laptop       # rollback, same command, ends swapped
#
# Read deploy/PORTABILITY.md for the contract each adapter implements.
#
# THE ONE RULE THIS SCRIPT ENFORCES: the engine is stopped on the source before the state is
# packed, and it is not started on the target until the copy is proved. Two engines running at
# once keep two spend ledgers and can spend twice the daily cap. That is why every phase is
# ordered the way it is, and why the failure path restarts the SOURCE rather than pressing on.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
FROM=""; TO=""; DRY=0; START_AT=1

# The secrets live in the MAIN checkout, and this script is usually run from a worktree, which
# never has a `.env` of its own. Falling straight through to "no env file" would make the
# cutover need a flag that only ever has one correct value. So: this tree if it has one,
# otherwise the main checkout, found through git rather than guessed.
_default_env() {
  [ -f "$REPO/.env" ] && { echo "$REPO/.env"; return; }
  local common main
  common="$(cd "$(git -C "$REPO" rev-parse --git-common-dir 2>/dev/null || echo .)" && pwd -P)"
  main="$(dirname "$common")"
  [ -f "$main/.env" ] && { echo "$main/.env"; return; }
  echo "$REPO/.env"
}
ENV_FILE="${PROSPECTOR_ENV_FILE:-$(_default_env)}"
WORK="${PROSPECTOR_CUTOVER_WORK:-${TMPDIR:-/tmp}/prospector-cutover}"

while [ $# -gt 0 ]; do
  case "$1" in
    --from) FROM="$2"; shift 2 ;;
    --to) TO="$2"; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    --from-phase) START_AT="$2"; shift 2 ;;
    --env-file) ENV_FILE="$2"; shift 2 ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[ -n "$FROM" ] && [ -n "$TO" ] || { echo "usage: cutover.sh --from <adapter> --to <adapter>" >&2; exit 2; }
for side in "$FROM" "$TO"; do
  [ -f "$HERE/targets/$side.sh" ] || { echo "no adapter deploy/targets/$side.sh" >&2; exit 2; }
done

# Each adapter is sourced in a subshell so the two ends cannot collide on function names.
call() { local side="$1"; shift; ( set -euo pipefail; . "$HERE/targets/$side.sh"; "$@" ); }
say()  { printf '\n\033[1m[%s] %s\033[0m\n' "$(date +%H:%M:%S)" "$*"; }
run()  { if [ "$DRY" = 1 ]; then echo "  DRY: $*"; else "$@"; fi; }

phase() { # phase <n> <title>; returns 1 when this phase should be skipped
  [ "$1" -ge "$START_AT" ] || { echo "  skip phase $1 ($2)"; return 1; }
  say "PHASE $1 — $2"; return 0
}

SOURCE_STOPPED=0
rollback() {
  local rc=$?
  [ "$rc" = 0 ] && return 0
  say "FAILED (exit $rc) — rolling back"
  # A dry run has changed nothing, so it must undo nothing. Calling t_stop here would make
  # --dry-run stop a real machine, which is the one thing the flag promises it will not do.
  if [ "$DRY" = 1 ]; then
    echo "  dry run — nothing was changed, so nothing is being rolled back"
    exit "$rc"
  fi
  call "$TO" t_stop 2>/dev/null || true
  if [ "$SOURCE_STOPPED" = 1 ]; then
    echo "  restarting the engine on $FROM"
    call "$FROM" t_start || echo "  !! COULD NOT RESTART $FROM — start it by hand NOW" >&2
  fi
  echo "  the packed state is kept at $WORK — nothing was deleted"
  exit "$rc"
}
trap rollback EXIT

mkdir -p "$WORK"
TARBALL="$WORK/store.tar.gz"

say "engine cutover: $(call "$FROM" t_name) -> $(call "$TO" t_name)"
[ "$DRY" = 1 ] && echo "  (dry run — nothing will change)"

if phase 1 "preflight both ends"; then
  call "$FROM" t_preflight
  call "$TO"   t_preflight
  [ -f "$ENV_FILE" ] || { echo "no env file at $ENV_FILE" >&2; exit 1; }
  git -C "$REPO" diff --quiet HEAD -- deploy scripts prospector \
    || echo "  NOTE: uncommitted changes in deploy/ scripts/ prospector/ — the image builds from the working tree"
fi

if phase 2 "provision the target and push its secrets"; then
  run call "$TO" t_provision
  # Only the keys the engine actually needs travel. Dead keys are not carried to a new platform.
  KEEP='^(MINIMAX_API_KEY|EXA_API_KEY|STORE_INTERNAL_API_KEY|STORE_API_URL|STRIPE_LIVE_API_KEY|PROSPECTOR_ENTITLEMENTS_API_KEY|R2_ACCOUNT_ID|R2_ACCESS_KEY_ID|R2_SECRET_ACCESS_KEY|R2_BUCKET|CONTROL_CENTER_PASSWORD|FLY_API_TOKEN|TELEGRAM_[A-Z_]+)='
  grep -E "$KEEP" "$ENV_FILE" > "$WORK/engine.env" || true
  # Exactly one copy of this image may write to the backup bucket. The target is it from
  # the moment the source stops, which is phase 4.
  echo 'ENGINE_BACKUPS_ENABLED=true' >> "$WORK/engine.env"
  grep -q '^CONTROL_CENTER_PASSWORD=' "$WORK/engine.env" \
    || echo "  WARNING: no CONTROL_CENTER_PASSWORD — the ops console will be unauthenticated" >&2
  grep -q '^FLY_API_TOKEN=' "$WORK/engine.env" \
    || echo "  WARNING: no FLY_API_TOKEN — the MONEY DATABASE backup will not run from the target" >&2
  echo "  carrying $(wc -l < "$WORK/engine.env" | tr -d ' ') secrets"
  chmod 600 "$WORK/engine.env"
  run call "$TO" t_secrets "$WORK/engine.env"
fi

if phase 3 "build and deploy the image, but do NOT start it"; then
  run call "$TO" t_release
  run call "$TO" t_stop      # deployed and dormant; the source is still the only writer
fi

if phase 4 "STOP the engine on $FROM (this is the downtime window opening)"; then
  run call "$FROM" t_stop
  SOURCE_STOPPED=1
fi

if phase 5 "pack the state and prove it here"; then
  run call "$FROM" t_pack "$TARBALL"
  [ "$DRY" = 1 ] || ls -lh "$TARBALL"
fi

if phase 6 "ship the state to $TO and prove it there"; then
  run call "$TO" t_start                       # up, but the engine is paused by PAUSE below
  run call "$TO" t_exec "mkdir -p /data && touch /data/store/scheduler/PAUSE 2>/dev/null || true"
  run call "$TO" t_put "$TARBALL" /data/store.tar.gz
  run call "$TO" t_exec "cd /data && rm -rf store.incoming && mkdir store.incoming && tar xzf store.tar.gz -C store.incoming"
  # The manifest of per-file sha256 rides inside the tarball, so the same command proves both ends.
  run call "$TO" t_exec "python /app/scripts/store_migrate.py verify /data/store.incoming"
  run call "$TO" t_exec "rm -rf /data/store.old && mv /data/store /data/store.old 2>/dev/null; mv /data/store.incoming /data/store && rm -f /data/store.tar.gz"
fi

if phase 7 "release the brake and watch one tick"; then
  run call "$TO" t_exec "rm -f /data/store/scheduler/PAUSE"
  run call "$TO" t_exec "python /app/scripts/store_migrate.py plan --store /data/store"
  echo "  engine live on $(call "$TO" t_name). Downtime window closed."
  echo "  watch it:      deploy/cutover.sh --from $FROM --to $TO --from-phase 99  # no-op, use t_logs"
  echo "  dashboard:     fly proxy 8611:8611 -a prospector-engine   (fly target)"
fi

if phase 8 "leave $FROM as a cold backup, stopped but intact"; then
  echo "  $FROM keeps its state at $WORK and its own store directory, untouched and NOT running."
  echo "  Delete nothing for 7 days. Turn it off for good with: deploy/decommission.sh --side $FROM"
fi

trap - EXIT
say "DONE — $(call "$FROM" t_name) -> $(call "$TO" t_name)"
