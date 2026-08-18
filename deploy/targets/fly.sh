#!/usr/bin/env bash
# Fly.io adapter. Everything in this repo that knows the word "fly" is in this file.
#
# Read deploy/PORTABILITY.md first. This implements the eight-verb contract described there.
# A second platform is a copy of this file with different commands in the same eight functions.

set -euo pipefail

APP="${PROSPECTOR_FLY_APP:-prospector-engine}"
REGION="${PROSPECTOR_FLY_REGION:-lhr}"
VOLUME="${PROSPECTOR_FLY_VOLUME:-prospector_store}"
VOLUME_GB="${PROSPECTOR_FLY_VOLUME_GB:-20}"
ENGINE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../engine" && pwd)"
# The build CONTEXT is the repository root, not the directory the Dockerfile sits in. Every
# COPY in deploy/engine/Dockerfile is written repo-root-relative - `COPY requirements.txt`,
# `COPY store_platform/src/Ops.Console` - because that is the only way one Dockerfile can pull
# in both the engine and the Next.js console. Anything narrower fails at build time with
# `failed to calculate checksum ... "/requirements.txt": not found`, which reads like a missing
# file rather than a wrong context. It cost one cutover attempt at 02:27 on 2026-08-18.
REPO_ROOT="$(cd "$ENGINE_DIR/../.." && pwd)"

t_name() { echo "fly:${APP}"; }

t_preflight() {
  command -v fly >/dev/null || { echo "fly CLI not installed: brew install flyctl" >&2; return 1; }
  fly auth whoami >/dev/null 2>&1 || { echo "fly CLI not logged in: fly auth login" >&2; return 1; }
  # `fly auth whoami` passes on a dead token in some versions, so make one real API call.
  fly apps list >/dev/null || { echo "fly token is dead; run: fly auth login" >&2; return 1; }
}

t_provision() {
  fly apps list 2>/dev/null | awk '{print $1}' | grep -qx "$APP" \
    || fly apps create "$APP" --org personal
  # No public IP on purpose. The dashboards are reached over `fly proxy`, never the internet.
  fly ips list -a "$APP" 2>/dev/null | grep -q . && {
    echo "NOTE: $APP has a public IP. Remove it with: fly ips release <addr> -a $APP" >&2; }
  fly volumes list -a "$APP" --json 2>/dev/null | grep -q "\"$VOLUME\"" \
    || fly volumes create "$VOLUME" -a "$APP" -r "$REGION" -s "$VOLUME_GB" --yes
}

# $1 = path to a KEY=VALUE file
t_secrets() {
  fly secrets import -a "$APP" --stage < "$1"
}

t_release() {
  fly deploy "$REPO_ROOT" --config "$ENGINE_DIR/fly.toml" -a "$APP" \
    --dockerfile "$ENGINE_DIR/Dockerfile" --strategy immediate --yes
}

# `fly scale count 1` returns as soon as the machine is CREATED, not when it is running. The very
# next command in the cutover is `fly ssh console`, which fails with "app X has no started VMs" -
# a message that reads like the image is broken when the machine is simply still booting. It cost
# cutover attempt 4 at 02:40 on 2026-08-18, inside the downtime window. So start means started.
t_start() {
  fly scale count 1 -a "$APP" --yes
  local i state
  for i in $(seq 1 60); do
    state="$(fly machines list -a "$APP" --json 2>/dev/null \
             | python3 -c 'import sys,json;m=json.load(sys.stdin);print(m[0]["state"] if m else "none")' 2>/dev/null || echo none)"
    [ "$state" = "started" ] && { echo "fly: machine started after ${i}0s"; return 0; }
    sleep 10
  done
  echo "fly: machine never reached state=started (last: ${state:-unknown})" >&2
  fly logs -a "$APP" --no-tail 2>&1 | tail -30 >&2
  return 1
}
t_stop()  { fly scale count 0 -a "$APP" --yes; }

t_exec() {
  fly ssh console -a "$APP" -C "/bin/sh -lc $(printf '%q' "$*")"
}

# $1 = local file, $2 = absolute path inside the container
#
# `fly ssh sftp shell` exits 0 whatever happens inside it. On cutover attempt 6 the upload
# printed "put ...: file exists on VM" and the script carried on and verified the tarball left
# behind by attempt 5 - so a good pack failed with attempt 5's numbers
# ("ledger_lines 906950 -> 906967"), which sent the diagnosis back to a bug that was already
# fixed. A transfer that cannot fail is not a transfer, so: clear the destination first, then
# prove the byte count from inside the container.
t_put() {
  local want got
  want="$(wc -c < "$1" | tr -d ' ')"
  t_exec "rm -f $2" >/dev/null 2>&1 || true
  fly ssh sftp shell -a "$APP" <<EOF
put $1 $2
EOF
  # The marker matters: t_exec's output carries `Connecting to fdaa:73:...` on stderr and that
  # line is full of digits. Grepping for a bare number would read the IPv6 address.
  got="$(t_exec "echo PUTSIZE=\$(wc -c < $2)" 2>/dev/null | grep -o 'PUTSIZE=[0-9]*' | head -1 | cut -d= -f2)"
  [ "$got" = "$want" ] \
    || { echo "fly: $2 is ${got:-absent} bytes on the VM, expected $want" >&2; return 1; }
  echo "fly: uploaded $2 ($want bytes, confirmed on the VM)"
}

# $1 = local .tar.gz to write. Used when Fly is the SOURCE, i.e. when we leave.
t_pack() {
  t_exec "python /app/scripts/store_migrate.py pack /data/handover.tar.gz --store /data/store"
  fly ssh sftp get -a "$APP" /data/handover.tar.gz "$1"
  t_exec "rm -f /data/handover.tar.gz"
}

t_logs() { fly logs -a "$APP"; }

# Is this platform actually carrying the load right now? Used by deploy/decommission.sh before
# it turns the OTHER side off for good. `fly status` is not enough: an app with a machine in
# state=stopped still reports an app.
t_health() {
  local state
  state="$(fly machines list -a "$APP" --json 2>/dev/null \
           | python3 -c 'import sys,json;m=json.load(sys.stdin);print(m[0]["state"] if m else "none")' 2>/dev/null || echo none)"
  [ "$state" = "started" ] || { echo "fly:$APP machine state=$state" >&2; return 1; }
  t_exec "test -f /data/store/prospector.jsonl" >/dev/null 2>&1 \
    || { echo "fly:$APP is up but has no ledger at /data/store/prospector.jsonl" >&2; return 1; }
  echo "fly:$APP started, ledger present"
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
