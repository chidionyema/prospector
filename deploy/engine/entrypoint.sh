#!/usr/bin/env bash
# Container entrypoint. Prepares the volume, then hands off.
#
# Three jobs, in order: make the directories the store expects, normalise the two
# environment variables supervisor parses strictly, and refuse to start if the machine
# was handed a store it cannot write. The last one matters most. A container that starts
# with an unwritable or absent volume runs a full tick, spends money on verdicts and then
# loses every row — which reads in the logs as a quiet, successful run.
set -euo pipefail

STORE_DIR="${PROSPECTOR_STORE_DIR:-/data/store}"
STATE_DIR="$(dirname "${PROSPECTOR_USAGE_WALL_MARKER:-/data/state/x}")"

mkdir -p "$STORE_DIR" "$STATE_DIR" "${CLAUDE_CONFIG_DIR:-/data/state/claude}"
mkdir -p "$STORE_DIR/scheduler" "$STORE_DIR/inflight" "$STORE_DIR/dossiers"

# The write probe. `mkdir -p` on a read-only mount succeeds when the directory already
# exists, so the existence of the path proves nothing about being able to append to the
# ledger.
probe="$STORE_DIR/.write_probe"
if ! : > "$probe" 2>/dev/null; then
    echo "FATAL: $STORE_DIR is not writable. The volume is missing or mounted read-only." >&2
    echo "       Refusing to start: a tick here would spend money and drop every row." >&2
    exit 1
fi
rm -f "$probe"

# supervisor parses autostart as a boolean and rejects `1`/`0`/`yes`. Accept the usual
# spellings from an operator or a fly secret and hand supervisor the two it takes.
case "$(printf '%s' "${ENGINE_BACKUPS_ENABLED:-false}" | tr '[:upper:]' '[:lower:]')" in
    1|true|yes|on) export ENGINE_BACKUPS_ENABLED=true ;;
    *)             export ENGINE_BACKUPS_ENABLED=false ;;
esac

case "${1:-supervisor}" in
    supervisor)
        echo "[entrypoint] store=$STORE_DIR backups=$ENGINE_BACKUPS_ENABLED"
        exec supervisord -c /etc/supervisord.conf
        ;;
    tick)
        # One scheduled tick, in the foreground, then exit. This is the abort gate: it is
        # how the image is proven on a laptop before a Fly volume exists, and how the
        # shadow run is done against a copy of the store.
        shift
        exec python -m prospector.scheduler.run_scheduled --once --config /app/config.yaml "$@"
        ;;
    shell)
        exec /bin/bash
        ;;
    *)
        exec "$@"
        ;;
esac
