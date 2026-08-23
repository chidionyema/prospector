#!/usr/bin/env bash
# Where is the estate running right now, and can it be flipped?
#
#   deploy/stack.sh status        # one screen: every component, on both platforms
#   deploy/stack.sh status --json # the same answer for the founder board
#   deploy/stack.sh recover       # what copies of the data exist, how old, and the command
#
# `status` answers "is it running". `recover` answers the question that only ever gets asked
# once, at the worst possible moment: "it is gone -- what do we still have, and what do I
# type". On 2026-08-23 that question took forty minutes and a wrong answer along the way
# (I told the founder the ledger could not be pulled back out; it could, and had been, by a
# command that already existed). Forty minutes is the cost of a runbook nobody can find. The
# whole point of this verb is that the restore command is printed NEXT TO the copy it
# restores, computed from what is actually in the bucket right now, so it cannot go stale.
#
# WHY THIS FILE EXISTS. deploy/cutover.sh already moves the ENGINE between platforms, and
# deploy/compose/ already brings the WHOLE stack up on a laptop. What nobody could answer on
# 2026-08-23 was the question that comes before either of them: where is each piece running
# now. The answer lived in four `fly status` calls, a `pgrep`, a `docker ps` and somebody's
# memory, which means it was never actually known, only assumed.
#
# THREE STATES, NOT TWO, and that is the whole design. A probe that can only say UP or DOWN
# reports a probe that never ran as DOWN, and a probe that cannot reach the platform as DOWN,
# and the founder then cannot tell "it is off" from "we did not look". So:
#
#   UP       the thing answered
#   DOWN     the thing was asked and did not answer
#   UNKNOWN  the thing could not be asked -- no credential, no daemon, no network
#
# UNKNOWN is not a failure of this script. It is the honest result, and it is the one that
# has to be visible, because a board that renders UNKNOWN as green is how a dead checker
# looks exactly like a healthy estate.
#
# Every probe is read-only. Nothing here starts, stops, deploys or deletes anything.

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Local addresses come from stack.env when it exists, so a laptop run is one file to edit
# (see compose/stack.env.example).
# shellcheck disable=SC1091
[ -f "$HERE/compose/stack.env" ] && . "$HERE/compose/stack.env"
API_PORT="${API_PORT:-5291}"
WEB_PORT="${WEB_PORT:-3000}"

# Production addresses are DELIBERATELY not SITE_DOMAIN/API_DOMAIN. stack.env owns those, and
# on a laptop it sets them to localhost -- which is correct for compose and catastrophic here.
# The first run of this script printed
#
#   store-api  fly  DOWN  no answer from https://localhost:5291/health
#
# and it was right to say DOWN, because it had just asked the laptop whether Fly was serving.
# One variable cannot name two platforms. These two are separate names, are never written by
# stack.env, and are what the fly rows probe.
PROD_API="${PROSPECTOR_PROD_API:-api.mumchimp.com}"
PROD_SITE="${PROSPECTOR_PROD_SITE:-mumchimp.com}"

VERB="${1:-status}"
case "$VERB" in status|recover) shift || true ;; -h|--help|help) VERB=usage ;; esac
JSON=0
[ "${1:-}" = "--json" ] && JSON=1

if [ "$VERB" = "usage" ]; then
  sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit 0
fi

# ---------------------------------------------------------------------------
# recover -- the inventory of every copy, with the command that brings each one back.
# ---------------------------------------------------------------------------
if [ "$VERB" = "recover" ]; then
  REPO="$(cd "$HERE/.." && pwd)"
  # boto3 lives in the repo venv when there is one. Falling back to bare python3 is not a
  # nicety: on a rented box restored from the git bundle there is no venv yet, and this verb
  # has to be able to say "no credentials" rather than "no module" -- those are different
  # problems and only one of them is the founder's.
  PY="python3"
  for c in "$REPO/.venv/bin/python3" "$REPO/venv/bin/python3"; do [ -x "$c" ] && PY="$c" && break; done

  # --json must emit JSON and nothing else. A banner around a machine-readable payload is
  # how a monitoring check ends up parsing a headline.
  if [ "$JSON" = 0 ]; then
    echo
    echo "WHAT WE STILL HAVE IF EVERYTHING ELSE BURNS"
    echo
  fi

  "$PY" - "$REPO" "$JSON" <<'PYEOF'
import os, sys, datetime, pathlib

repo = pathlib.Path(sys.argv[1])
as_json = sys.argv[2] == "1"

# The same .env the backup job reads. Parsed here rather than imported from backup_store.py
# because that module exits the process on a missing credential, and this verb must survive
# that case in order to report it.
env = {}
f = repo / ".env"
if f.is_file():
    for line in f.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
for k, v in env.items():
    os.environ.setdefault(k, v)

ROWS = []
def row(what, where, age, size, cmd):
    ROWS.append((what, where, age, size, cmd))

def ago(dt):
    if dt is None:
        return "-"
    h = (datetime.datetime.now(datetime.timezone.utc) - dt).total_seconds() / 3600.0
    return f"{h:.1f}h" if h < 72 else f"{h/24:.1f}d"

def human(n):
    if n is None:
        return "-"
    for u in ("B", "K", "M", "G"):
        if n < 1024 or u == "G":
            return f"{n:.0f}{u}" if u == "B" else f"{n:.1f}{u}"
        n /= 1024.0

missing = [k for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY") if not os.environ.get(k)]
if missing:
    row("R2 offsite copies", "cloudflare r2", "UNKNOWN", "-",
        "cannot look: no " + ", ".join(missing) + " in " + str(f))
else:
    try:
        import boto3
        from botocore.config import Config as BotoConfig
        s3 = boto3.client(
            "s3",
            endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
            aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
            config=BotoConfig(signature_version="s3v4", region_name="auto",
                              connect_timeout=8, read_timeout=15, retries={"max_attempts": 2}),
        )
        bucket = os.environ.get("R2_BACKUP_BUCKET") or "prospector-backup"

        # what, prefix, the command that restores it
        WANT = [
            ("money ledger",   "ledger/",   "python3 scripts/backup_store.py --restore-money ./restored"),
            ("money db",       "db/",       "python3 scripts/backup_store.py --restore-money ./restored"),
            ("dossiers",       "dossiers/", "python3 scripts/backup_store.py --restore ./restored"),
            ("this repo",      "repo/",     "git clone <the .bundle downloaded from r2> prospector"),
            ("engine logs",    "logs/",     "aws s3 cp --recursive s3://%s/logs/ ./logs" % bucket),
            ("offsite mirror", "offsite/",  "see ~/.claude/scripts/estate/estate_push.sh (it wrote these)"),
            ("hermes state",   "hermes/",   "see ~/.claude/scripts/estate/estate_push.sh (it wrote these)"),
        ]
        for what, prefix, cmd in WANT:
            newest, size, count = None, None, 0
            tok = None
            while True:
                kw = {"Bucket": bucket, "Prefix": prefix, "MaxKeys": 1000}
                if tok:
                    kw["ContinuationToken"] = tok
                page = s3.list_objects_v2(**kw)
                for o in page.get("Contents", []):
                    count += 1
                    if newest is None or o["LastModified"] > newest:
                        newest, size = o["LastModified"], o["Size"]
                if not page.get("IsTruncated"):
                    break
                tok = page.get("NextContinuationToken")
            if count == 0:
                row(what, f"r2:{prefix}", "MISSING", "-", "NOTHING IS BACKED UP HERE")
            else:
                row(f"{what} ({count} obj)", f"r2:{prefix}", ago(newest), human(size), cmd)
    except Exception as exc:  # noqa: BLE001 -- the reason is the answer, whatever it is
        row("R2 offsite copies", "cloudflare r2", "UNKNOWN", "-", f"{type(exc).__name__}: {exc}")

# Local copies. A local copy is not a backup, but on the day the provider is gone it is the
# fastest thing there is, and not printing it means somebody restores 500M they already have.
for what, path, cmd in [
    # This checkout's own store, which in a worktree is nearly empty and must not be
    # mistaken for production's. Labelled by path for that reason.
    ("live store (this checkout)", repo / "store", "already here -- nothing to restore"),
    ("age key",      pathlib.Path.home() / ".config/prospector/age-key.txt",
     "WITHOUT THIS FILE deploy/secrets.env.age CANNOT BE READ. Back it up off this laptop."),
    ("secret store", repo / "deploy/secrets.env.age", "bash deploy/secrets.sh push <target>"),
]:
    if path.exists():
        if path.is_dir():
            total = sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
            mt = max((p.stat().st_mtime for p in path.rglob("*") if p.is_file()), default=None)
        else:
            total = path.stat().st_size
            mt = path.stat().st_mtime
        dt = datetime.datetime.fromtimestamp(mt, datetime.timezone.utc) if mt else None
        row(what, "this laptop", ago(dt), human(total), cmd)
    else:
        row(what, "this laptop", "MISSING", "-", cmd)

bad = sum(1 for r in ROWS if r[2] in ("MISSING", "UNKNOWN"))

# A copy older than this is a stopped job, not a slow one. The money snapshots are written
# daily, so 26h is one missed run plus two hours of slack for a late start. Without this the
# table renders a backup that died last month in exactly the same ink as one written at dawn.
STALE_H = 26.0
stale = []
for _w, _where, _age, _s, _c in ROWS:
    if not _where.startswith("r2:"):
        continue
    if _age.endswith("d") or (_age.endswith("h") and float(_age[:-1]) > STALE_H):
        stale.append(_w)

if as_json:
    import json as _json
    print(_json.dumps({
        "rows": [{"what": a, "where": b, "age": c, "newest": d, "restore": e} for a, b, c, d, e in ROWS],
        "missing": bad,
        "stale": stale,
        "stale_after_hours": STALE_H,
    }, indent=2))
    sys.exit(1 if (bad or stale) else 0)

w = [max(len(str(r[i])) for r in ROWS + [("WHAT", "WHERE", "AGE", "NEWEST", "")]) for i in range(4)]
# AGE and NEWEST describe the most recent object under the prefix, not the whole prefix.
# A total would be a second listing pass for a number nobody restores by.
print(f"{'WHAT':<{w[0]}}  {'WHERE':<{w[1]}}  {'AGE':<{w[2]}}  {'NEWEST':<{w[3]}}  RESTORE WITH")
print(f"{'-'*w[0]}  {'-'*w[1]}  {'-'*w[2]}  {'-'*w[3]}  {'-'*12}")
for what, where, age, size, cmd in ROWS:
    print(f"{what:<{w[0]}}  {where:<{w[1]}}  {age:<{w[2]}}  {size:<{w[3]}}  {cmd}")
print()
print(f"{len(ROWS)} copies listed, {bad} missing or unreadable, {len(stale)} older than {STALE_H:.0f}h")
if stale:
    print("STALE: " + ", ".join(stale) + " -- whatever writes these has stopped")
sys.exit(1 if (bad or stale) else 0)

PYEOF
  RC=$?

  [ "$JSON" = 1 ] && exit "$RC"
  cat <<'DRILL'

prove a copy actually restores (do not wait for the outage to find out):
  python3 scripts/backup_store.py --restore-money ./restored   # money path, ~1 minute
  python3 scripts/restore_drill.py --backup ./restored --store ./store
DRILL
  exit "$RC"
fi

ROWS=()
# `row <component> <platform> <probe output>`. The probe returns one line, "STATE detail", and
# it is passed UNQUOTED on purpose so it lands in "$*" -- then split here, once, rather than
# every caller remembering to quote a command substitution. The first version did not, and
# "UP 2/2 machines started" silently became detail="2/2" with the rest dropped on the floor.
row() {
  local comp="$1" plat="$2"; shift 2
  local state="$1"; shift
  ROWS+=("$comp|$plat|$state|$*")
}

# ---------------------------------------------------------------------------
# Probes. Each returns a state on stdout as "STATE detail".
#
# `fly` answers about the PLATFORM: is a machine allocated and started. curl answers about
# the SERVICE: does it serve. They fail differently -- a started machine with a crashed
# process is UP to fly and DOWN to curl -- so both are asked and both are printed. That is
# LAW 15's two angles, built into the layout rather than remembered by whoever reads it.
# ---------------------------------------------------------------------------

have() { command -v "$1" >/dev/null 2>&1; }

# Every probe runs under a clock. Measured 2026-08-23: `fly machines list` answers in under
# 1.1s for all five apps, and `docker info` against a wedged colima VM did not answer at all
# -- one `status` run passed two minutes and was killed. A status screen that can hang is not
# a status screen, it is a wait, and the founder is looking at it on the day everything else
# is already broken.
#
# `timeout` is GNU and is not on a stock macOS. Falling back to running the command bare is
# deliberate: a box without coreutils should still get an answer, just without the guard.
if have timeout; then TMO=timeout
elif have gtimeout; then TMO=gtimeout
else TMO=""; fi
tmo() { local s="$1"; shift; if [ -n "$TMO" ]; then "$TMO" "$s" "$@"; else "$@"; fi; }

fly_machine() {   # fly_machine <app>
  have fly || { echo "UNKNOWN no fly CLI on this box"; return; }
  local out
  out="$(tmo 20 fly machines list -a "$1" --json 2>/dev/null)" || { echo "UNKNOWN fly did not answer for $1"; return; }
  [ -n "$out" ] || { echo "UNKNOWN fly returned nothing for $1"; return; }
  local n started
  n="$(printf '%s' "$out" | python3 -c 'import sys,json;m=json.load(sys.stdin);print(len(m))' 2>/dev/null)" \
    || { echo "UNKNOWN could not read fly output for $1"; return; }
  [ "$n" = "0" ] && { echo "DOWN no machines"; return; }
  started="$(printf '%s' "$out" | python3 -c 'import sys,json;m=json.load(sys.stdin);print(sum(1 for x in m if x.get("state")=="started"))' 2>/dev/null)"
  [ "${started:-0}" -gt 0 ] && echo "UP $started/$n machines started" || echo "DOWN 0/$n started"
}

http() {          # http <url>
  have curl || { echo "UNKNOWN no curl"; return; }
  local code
  # --max-time, because a hung probe is the one failure mode that makes a status screen
  # useless: it stops being a snapshot and starts being a wait.
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 6 "$1" 2>/dev/null)"
  case "$code" in
    000|"") echo "DOWN no answer from $1" ;;
    2*|3*)  echo "UP HTTP $code" ;;
    *)      echo "DOWN HTTP $code" ;;
  esac
}

local_proc() {    # local_proc <pattern> <what>
  pgrep -f "$1" >/dev/null 2>&1 && echo "UP $2 running" || echo "DOWN $2 not running"
}

local_container() { # local_container <name>
  have docker || { echo "UNKNOWN no docker CLI"; return; }
  # 8s, not "until it answers". A colima VM that is up but wedged leaves `docker info`
  # blocked indefinitely, which is how this script first came to take over two minutes.
  tmo 8 docker info >/dev/null 2>&1 || { echo "UNKNOWN docker daemon not answering in 8s"; return; }
  local s
  s="$(tmo 10 docker ps --filter "name=^${1}$" --format '{{.Status}}' 2>/dev/null)"
  [ -n "$s" ] && echo "UP $s" || echo "DOWN no container named $1"
}

# ---------------------------------------------------------------------------
# The estate, component by component.
# ---------------------------------------------------------------------------

# engine. On Fly it is a machine; on the laptop it is launchd, not Docker -- which is why
# deploy/targets/laptop.sh exists and why this row does not probe a container.
row engine    fly    $(fly_machine prospector-engine)
row engine    laptop $(local_proc 'prospector.scheduler.run_scheduled' scheduler)

# store api. The money path. Two angles on purpose: the machine, and a request.
row store-api fly    $(fly_machine prospector-store-api)
row store-api fly    $(http "https://${PROD_API}/health")
row store-api laptop $(local_container prospector-store-api)
row store-api laptop $(http "http://127.0.0.1:${API_PORT}/health")

# store web.
row store-web fly    $(fly_machine prospector-store-web)
row store-web fly    $(http "https://${PROD_SITE}/")
row store-web laptop $(local_container prospector-store-web)
row store-web laptop $(http "http://127.0.0.1:${WEB_PORT}/")

# hermes. Two apps on Fly, because hermes-v2 replaces one of prospector-hermes's eight
# services and the two run side by side until each has somewhere to land.
row hermes    fly    $(fly_machine prospector-hermes)
row hermes-v2 fly    $(fly_machine prospector-hermes-v2)
row hermes    laptop $(local_proc 'hermes.*gateway' gateway)

# ---------------------------------------------------------------------------
# Output.
# ---------------------------------------------------------------------------

if [ "$JSON" = 1 ]; then
  printf '%s\n' "${ROWS[@]}" | python3 -c '
import sys, json
out = []
for line in sys.stdin:
    line = line.rstrip("\n")
    if not line: continue
    comp, plat, state, detail = (line.split("|", 3) + ["", "", "", ""])[:4]
    out.append({"component": comp, "platform": plat, "state": state, "detail": detail})
print(json.dumps({"rows": out}, indent=2))
'
  exit 0
fi

printf '\n%-11s %-7s %-8s %s\n' COMPONENT PLATFORM STATE DETAIL
printf '%-11s %-7s %-8s %s\n' ----------- ------- -------- ------
up=0; down=0; unknown=0
for r in "${ROWS[@]}"; do
  IFS='|' read -r comp plat state detail <<<"$r"
  case "$state" in UP) up=$((up+1));; DOWN) down=$((down+1));; *) unknown=$((unknown+1));; esac
  printf '%-11s %-7s %-8s %s\n' "$comp" "$plat" "$state" "$detail"
done

echo
echo "$up up, $down down, $unknown unknown"
# Printed always, not only on failure. The founder should never have to remember the flip
# command, and a status screen that hides it makes him go and find it on the worst day.
cat <<'NEXT'

flip the engine:   deploy/cutover.sh --from fly --to laptop      (and --from laptop --to fly to come back)
bring the stack up here: deploy/compose/preflight.sh && docker compose --profile store up -d --build
NEXT

# UNKNOWN rows exit 2, distinct from DOWN's 1, because "we could not look" and "it is off"
# need different responses and a single non-zero cannot say which happened.
[ "$unknown" -gt 0 ] && exit 2
[ "$down" -gt 0 ] && exit 1
exit 0
