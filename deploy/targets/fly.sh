#!/usr/bin/env bash
# Fly.io adapter. Everything in this repo that knows the word "fly" is in this file.
#
# Read deploy/PORTABILITY.md first. This implements the twelve-function contract described
# there. A second platform is a copy of this file with different commands in the same twelve
# functions. It said "eight" until 2026-08-20, when there had been twelve for weeks.

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

# The CLI answers to two names and the environment decides which one exists. Homebrew's
# `flyctl` formula installs both `flyctl` and a `fly` symlink; the `superfly/flyctl-actions/
# setup-flyctl` action used by .github/workflows/escape-hatch-drill.yml and deploy-engine.yml
# puts only `flyctl` on PATH. Every call below says `fly`, so on 2026-08-19 the weekly escape
# hatch drill died at its first step with `deploy/targets/fly.sh: line 106: fly: command not
# found`, exit 127 — the portability drill could not run because of the name of a binary.
#
# One shim rather than renaming twenty-five call sites: if `fly` is missing and `flyctl` is
# present, define `fly` as a function that forwards. It is defined before any function that
# calls it, and bash resolves functions at call time, so every `fly ...` below is covered.
if ! command -v fly >/dev/null 2>&1 && command -v flyctl >/dev/null 2>&1; then
  fly() { flyctl "$@"; }
fi

t_name() { echo "fly:${APP}"; }

t_preflight() {
  # `command -v` is true for the shim above as well as for a real binary, which is the point:
  # preflight asks whether the CLI is REACHABLE, not what it is called.
  command -v fly >/dev/null || { echo "fly CLI not installed: brew install flyctl" >&2; return 1; }
  fly auth whoami >/dev/null 2>&1 || { echo "fly CLI not logged in: fly auth login" >&2; return 1; }
  # `fly auth whoami` passes on a dead token in some versions, so make one real API call.
  fly apps list >/dev/null || { echo "fly token is dead; run: fly auth login" >&2; return 1; }
}

t_provision() {
  fly apps list 2>/dev/null | awk '{print $1}' | grep -qx "$APP" \
    || fly apps create "$APP" --org personal
  # The ops console needs a public address, and this is where it gets one — not in a command
  # someone has to remember. Founder, 2026-08-18: "remember everything has to be automated",
  # right after "relying on a tunnel on this macbook to run operations is not smart".
  #
  # Until 2026-08-18 this block did the opposite: it printed a NOTE if the app had an IP,
  # because the console was reached over `fly proxy` from the laptop. That left the laptop as
  # the only door to the dashboard of an engine that had already moved off it.
  #
  # Both address families, because either alone is a gap. v6 is what Fly hands out at no cost
  # and what most networks now have; a shared v4 is what a network without v6 needs. Shared
  # rather than dedicated, because a dedicated v4 is billed and nothing here needs its own
  # address. Both lines are idempotent: allocate only when that family is absent.
  if [ "${PROSPECTOR_FLY_PUBLIC:-1}" = "1" ]; then
    local ips
    ips="$(fly ips list -a "$APP" 2>/dev/null || true)"
    echo "$ips" | grep -q 'v6' || fly ips allocate-v6 -a "$APP" >/dev/null
    echo "$ips" | grep -q 'v4' || fly ips allocate-v4 --shared -a "$APP" >/dev/null

    # A custom hostname is optional. With none set the app answers on <app>.fly.dev, which Fly
    # already holds a certificate for, so the console is reachable either way and a DNS record
    # is the only step that can ever be left outstanding.
    if [ -n "${PROSPECTOR_OPS_HOSTNAME:-}" ]; then
      fly certs list -a "$APP" 2>/dev/null | grep -q "$PROSPECTOR_OPS_HOSTNAME" \
        || fly certs add "$PROSPECTOR_OPS_HOSTNAME" -a "$APP" >/dev/null
    fi
  fi

  fly volumes list -a "$APP" --json 2>/dev/null | grep -q "\"$VOLUME\"" \
    || fly volumes create "$VOLUME" -a "$APP" -r "$REGION" -s "$VOLUME_GB" --yes
}

# $1 = path to a KEY=VALUE file
t_secrets() {
  fly secrets import -a "$APP" --stage < "$1"
}

t_release() {
  # Stamp the commit into the image. Without it `fly releases` gives a version number that maps
  # to nothing, so "which commit is production running?" has no answer on this platform.
  local sha dirty
  sha="$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"
  # Tracked runtime state under store/ and storage/ is rewritten by every run, so a working
  # checkout is never clean. Only modified CODE means the image is not the commit it names.
  dirty="$(git -C "$REPO_ROOT" status --porcelain 2>/dev/null | grep -v '^??' \
           | awk '{print $NF}' | grep -vE '^(store|storage)/' | head -1 || true)"
  if [ -n "$dirty" ]; then sha="$sha-dirty"; fi
  echo "fly: building from $sha"
  fly deploy "$REPO_ROOT" --config "$ENGINE_DIR/fly.toml" -a "$APP" \
    --dockerfile "$ENGINE_DIR/Dockerfile" --build-arg "GIT_SHA=$sha" \
    --strategy immediate --yes
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

# Portable sha256 of a local file. GitHub runners have sha256sum; macOS has shasum only.
_sha256_local() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
  else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

# $1 = local .tar.gz to write. Used when Fly is the SOURCE, i.e. when we leave.
#
# WHY THIS IS CHUNKED AND CHECKSUMMED RATHER THAN ONE `get` WITH A RETRY.
#
# `fly ssh sftp get` truncates and exits 0. Measured 2026-08-23: 112,474,776 bytes packed on
# the VM, 12,779,520 bytes received (11.4%), flyctl printed "12779520 bytes written" and
# returned success. Two 100 MB control transfers the same day came back byte-exact, so the
# truncation is intermittent, not a size ceiling.
#
# An intermittent silent truncation cannot be handled by retrying the whole file: each attempt
# is unbounded, nothing proves which attempt was honest, and a run that happens to succeed says
# nothing about the next one. The export is the one path we take when we leave the platform, so
# it does not get to be probabilistic.
#
# So the transfer is split into fixed 16 MB parts. Every part carries its own sha256 taken on
# the VM, is verified on arrival, and is re-fetched on its own if it does not match. The
# reassembled file is then checked against the whole-file sha256 taken on the VM before
# anything downstream is allowed to read it, and `tar -tzf` proves it opens. Failure is loud
# and the target file is removed, so a partial export can never be mistaken for a good one.
#
# t_put already confirmed its byte count on the VM. t_pack did not confirm anything, and that
# asymmetry was the defect: the direction we depend on in order to LEAVE was the unchecked one.
t_pack() {
  local want sum parts part got attempt ok tmpdir
  # Remove any previous export FIRST. Every abort path below returns non-zero, but a caller
  # that ignores the status must not find last week's archive sitting at the target path and
  # read it as this run's output. Absent is the honest result of a failed export.
  rm -f "$1"
  # PROSPECTOR_PACK_FORCE=1 is for the weekly drill, and only for the drill.
  #
  # store_migrate.py's pack refuses to run while the scheduler or the consumer is up, which is
  # right for a cutover: at cutover, phase 4 has already stopped the engine, so a live writer
  # there means something is wrong and stopping is the correct answer. It is wrong for a drill.
  # The drill rehearses leaving without taking production down, so the engine is up by design and
  # the refusal fires every time. Three drills, three failures, all `exit 2` from that check,
  # never once a real defect in the exit path.
  #
  # Forcing it is safe here because the manifest hashes the bytes as they enter the tar rather
  # than stat-ing the tree beforehand (scripts/store_migrate.py, cmd_pack). The payload proves
  # itself even when the store is being appended to underneath it. Measured 2026-08-23 against a
  # copy of the store with a writer appending to prospector.jsonl every 20ms: pack PASS 34 files,
  # verify PASS 34/34 hashed, db_integrity=ok.
  local force=""
  [ "${PROSPECTOR_PACK_FORCE:-0}" = "1" ] && force=" --force"
  t_exec "python /app/scripts/store_migrate.py pack /data/handover.tar.gz --store /data/store$force"

  # The marker matters: t_exec's output carries `Connecting to fdaa:73:...` on stderr and that
  # line is full of digits and hex. Grepping for a bare number would read the IPv6 address.
  want="$(t_exec "echo PACKSIZE=\$(wc -c < /data/handover.tar.gz | tr -d ' ')" 2>/dev/null \
          | grep -o 'PACKSIZE=[0-9]*' | head -1 | cut -d= -f2)"
  sum="$(t_exec "echo PACKSHA=\$(sha256sum /data/handover.tar.gz | cut -d' ' -f1)" 2>/dev/null \
          | grep -o 'PACKSHA=[0-9a-f]\{64\}' | head -1 | cut -d= -f2)"
  { [ -n "$want" ] && [ "$want" -gt 0 ] 2>/dev/null && [ -n "$sum" ]; } \
    || { echo "fly: cannot read the packed size and sha256 on the VM; refusing to claim an export" >&2
         t_pack_cleanup; return 1; }
  echo "fly: packed on the VM — $want bytes, sha256 $sum"

  # 16 MB parts. Small enough that a truncation is bounded and cheap to refetch, large enough
  # that a 112 MB store is 8 transfers rather than hundreds of round trips. The size is a
  # variable only so tests/unit/test_fly_pack_refuses_a_truncated_export.py can drive the
  # split with a small archive; nothing in production sets it.
  local partbytes="${PROSPECTOR_PACK_PART_BYTES:-16777216}"
  t_exec "rm -f /data/handover.part.* && split -b $partbytes -d -a 3 /data/handover.tar.gz /data/handover.part." >/dev/null
  parts="$(t_exec "ls -1 /data/handover.part.* | sed 's#.*/##'" 2>/dev/null | grep -o 'handover\.part\.[0-9]\{3\}' | sort -u)"
  [ -n "$parts" ] || { echo "fly: the VM produced no parts to transfer" >&2; t_pack_cleanup; return 1; }
  echo "fly: $(echo "$parts" | wc -l | tr -d ' ') parts to fetch"

  tmpdir="$(mktemp -d)"
  for part in $parts; do
    local psum
    psum="$(t_exec "echo PARTSHA=\$(sha256sum /data/$part | cut -d' ' -f1)" 2>/dev/null \
            | grep -o 'PARTSHA=[0-9a-f]\{64\}' | head -1 | cut -d= -f2)"
      [ -n "$psum" ] || { echo "fly: no sha256 for $part on the VM" >&2
                        rm -f "$1"; rm -rf "$tmpdir"; t_pack_cleanup; return 1; }

    ok=0
    for attempt in 1 2 3; do
      rm -f "$tmpdir/$part"
      fly ssh sftp get -a "$APP" "/data/$part" "$tmpdir/$part" >/dev/null 2>&1 || true
      got="$(_sha256_local "$tmpdir/$part" 2>/dev/null)"
      if [ "$got" = "$psum" ]; then ok=1; break; fi
      echo "fly: $part sha mismatch on attempt $attempt ($(wc -c < "$tmpdir/$part" 2>/dev/null | tr -d ' ') bytes) — refetching" >&2
    done
    [ "$ok" = "1" ] || { echo "fly: $part failed 3 attempts; EXPORT ABORTED" >&2
                         rm -f "$1"; rm -rf "$tmpdir"; t_pack_cleanup; return 1; }
  done

  # Reassemble in the order split produced, never in shell glob order on a different locale.
  rm -f "$1"
  for part in $parts; do cat "$tmpdir/$part" >> "$1"; done
  rm -rf "$tmpdir"

  got="$(wc -c < "$1" | tr -d ' ')"
  [ "$got" = "$want" ] || { echo "fly: reassembled $got bytes, VM had $want; EXPORT ABORTED" >&2
                            rm -f "$1"; t_pack_cleanup; return 1; }
  got="$(_sha256_local "$1")"
  [ "$got" = "$sum" ] || { echo "fly: reassembled sha256 $got, VM had $sum; EXPORT ABORTED" >&2
                           rm -f "$1"; t_pack_cleanup; return 1; }
  # A file can match its checksum and still be an archive nobody can open if the VM packed it
  # wrong. This is the cheapest structural proof, and it is the check that caught the 11% payload.
  tar -tzf "$1" >/dev/null 2>&1 || { echo "fly: the archive does not open; EXPORT ABORTED" >&2
                                     rm -f "$1"; t_pack_cleanup; return 1; }

  echo "fly: exported $1 — $want bytes, sha256 $sum, byte-exact against the VM, archive opens"
  t_pack_cleanup
  return 0
}

# Always runs, on every exit path, so a failed export never leaves the Fly volume filling up.
t_pack_cleanup() {
  t_exec "rm -f /data/handover.tar.gz /data/handover.part.*" >/dev/null 2>&1 || true
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
