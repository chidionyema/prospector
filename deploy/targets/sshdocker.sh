#!/usr/bin/env bash
# Any Linux box with Docker and an SSH login. Hetzner, EC2, a Mac mini, a Pi in a cupboard.
#
# This is the escape hatch from Fly, and it is written NOW so that leaving Fly is a command we
# have already run rather than a project we have to start. Same eleven verbs as deploy/targets/fly.sh;
# the contract is written out in deploy/PORTABILITY.md.
#
#   PROSPECTOR_SSH_HOST=engine@1.2.3.4 deploy/cutover.sh --from fly --to sshdocker

set -euo pipefail

HOST="${PROSPECTOR_SSH_HOST:?set PROSPECTOR_SSH_HOST=user@host}"
NAME="${PROSPECTOR_DOCKER_NAME:-prospector-engine}"
DATA="${PROSPECTOR_DOCKER_DATA:-/srv/prospector/data}"
IMAGE="${PROSPECTOR_DOCKER_IMAGE:-prospector-engine:latest}"
ENGINE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../engine" && pwd)"
REPO_DIR="$(cd "$ENGINE_DIR/../.." && pwd)"

_ssh() { ssh -o BatchMode=yes "$HOST" "$@"; }

t_name() { echo "sshdocker:${HOST}"; }

t_preflight() {
  command -v docker >/dev/null || { echo "docker not installed locally (needed to build)" >&2; return 1; }
  _ssh "docker version >/dev/null" || { echo "no docker over ssh at $HOST" >&2; return 1; }
}

t_provision() { _ssh "mkdir -p $DATA/store $DATA/state"; }

# $1 = KEY=VALUE file. Kept 0600 on the box; docker reads it with --env-file.
t_secrets() {
  _ssh "install -m 600 /dev/null $DATA/engine.env"
  # shellcheck disable=SC2002
  cat "$1" | _ssh "cat > $DATA/engine.env"
}

t_release() {
  docker build -f "$ENGINE_DIR/Dockerfile" -t "$IMAGE" "$REPO_DIR"
  docker save "$IMAGE" | gzip | _ssh "gunzip | docker load"
}

t_start() {
  # --restart unless-stopped is how this platform keeps its one-container promise.
  _ssh "docker rm -f $NAME >/dev/null 2>&1 || true;
        docker run -d --name $NAME --restart unless-stopped \
          --env-file $DATA/engine.env -v $DATA:/data \
          -p 127.0.0.1:8601:8601 -p 127.0.0.1:8611:8611 $IMAGE"
}

t_stop() { _ssh "docker rm -f $NAME >/dev/null 2>&1 || true"; }

t_exec() { _ssh "docker exec $NAME /bin/sh -lc $(printf '%q' "$*")"; }

t_put() { _ssh "cat > $2" < "$1"; }

t_pack() {
  t_exec "python /app/scripts/store_migrate.py pack /data/handover.tar.gz --store /data/store"
  _ssh "cat $DATA/handover.tar.gz" > "$1"
  t_exec "rm -f /data/handover.tar.gz"
}

t_logs() { _ssh "docker logs -f $NAME"; }

# Is this box actually carrying the load right now? deploy/decommission.sh asks before it turns
# the other platform off for good. A running container is not enough on its own: a container that
# came up against an empty volume is running and serving nothing, so the ledger is checked too.
t_health() {
  local state
  state="$(_ssh "docker inspect -f '{{.State.Running}}' $NAME 2>/dev/null" || echo false)"
  [ "$state" = "true" ] || { echo "sshdocker:$HOST container $NAME is not running" >&2; return 1; }
  _ssh "test -f $DATA/store/prospector.jsonl" \
    || { echo "sshdocker:$HOST is up but has no ledger at $DATA/store/prospector.jsonl" >&2; return 1; }
  echo "sshdocker:$HOST running, ledger present"
}

# Run a verb directly: `bash deploy/targets/<name>.sh t_release`.
#
# Without this, running the file instead of sourcing it defines every function, reaches the end
# and exits 0 - a silent success that deploys nothing. Measured 2026-08-18: three consecutive
# `bash fly.sh t_release` calls each exited 0 with no output while `fly releases` never moved off
# v3. The guard means `source`ing it, which deploy/cutover.sh does, still runs nothing.
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
  verb="${1:?usage: $(basename "${BASH_SOURCE[0]}") <verb> [args...]}"
  case "$verb" in
    t_*) ;;
    *) echo "unknown verb: $verb (verbs start with t_)" >&2; exit 2 ;;
  esac
  declare -F "$verb" >/dev/null || { echo "no such verb: $verb" >&2; exit 2; }
  shift
  "$verb" "$@"
fi
