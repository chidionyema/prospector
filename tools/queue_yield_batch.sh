#!/usr/bin/env bash
# Wait until TARGET_JOB is no longer running (succeeded / failed / cancelled /
# PID dead), then publish recent non-provisional PASSes and launch a yield-
# focused UK batch with --publish via Control Center runner.launch.
#
# Catalogue preset (not multi-lane MIX):
#   k=5 · --lane side_hustle · --profile statutory_compliance_pack · --publish
#
# Safe to stop the target job early: cancelled/failed still triggers backfill
# + the faster k=5 launch (operator time > grinding remaining KILLs).
#
# Usage (from repo root):
#   nohup bash tools/queue_yield_batch.sh >> store/control_center/runs/queue_yield_batch.log 2>&1 &
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${ROOT}/.venv/bin/python"
LOG="${ROOT}/store/control_center/runs/queue_yield_batch.log"
TARGET_JOB="${TARGET_JOB:-20260730T192006215}"
POLL_S="${POLL_S:-15}"
# No CLI-slot pin here. `PROSPECTOR_CURSOR_CONCURRENCY` was removed 2026-08-06 with the
# cursor_cli adapter; prospector/cli_governor.py caps claude CLI fan-out machine-wide via
# flock, so config.yaml retrieval.claude_concurrency is the single source of truth.
mkdir -p "$(dirname "$LOG")"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] queue_yield_batch: waiting for job ${TARGET_JOB} (status!=running or PID dead); poll=${POLL_S}s"

while true; do
  state="$("$PY" - "$TARGET_JOB" <<'PY'
import json, os, sys
from pathlib import Path

def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True

target = sys.argv[1]
p = Path("store/control_center/jobs.json")
if not p.exists():
    print("gone")
    raise SystemExit
jobs = json.loads(p.read_text())
j = next((x for x in jobs if x.get("job_id") == target), None)
if j is None:
    print("gone")
    raise SystemExit
status = str(j.get("status") or "")
pid = int(j.get("pid") or 0)
alive = pid_alive(pid)
# Any terminal status (succeeded/failed/cancelled/…) or a dead PID unblocks.
if status != "running" or not alive:
    print(f"clear status={status} pid={pid} alive={alive}")
else:
    print(f"wait status={status} pid={pid} alive={alive}")
PY
)"
  case "$state" in
    clear*|gone)
      echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ${state}"
      break
      ;;
  esac
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] still waiting (${state}); sleep ${POLL_S}"
  sleep "$POLL_S"
done

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] clear — backfill listings for any non-provisional PASSes that lack them (recent)"
# k=20 (and early stops) may run without --publish; mint sellable packs now.
"$PY" - <<'PY'
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
cutoff = datetime.now(timezone.utc) - timedelta(hours=12)
paths = []
for f in Path("store/dossiers").glob("*.pass.json"):
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        continue
    if str(d.get("decision", "")).lower() != "pass":
        continue
    if d.get("provisional"):
        continue
    cid = (d.get("candidate") or {}).get("candidate_id") or f.stem.split(".")[0]
    title = ((d.get("candidate") or {}).get("title") or "")
    title_key = title.lower().replace(" ", "").replace("-", "")
    # Always include known k=20 survivors if listing-less (even if older than cutoff).
    named = any(k in title_key or k in cid.lower() for k in (
        "sparkcert", "petshift",
    ))
    if Path(f"store/listings/{cid}.json").exists():
        continue
    created = d.get("created_at") or ""
    try:
        ts = datetime.fromisoformat(created.replace("Z", "+00:00"))
    except Exception:
        ts = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
    if named or ts >= cutoff:
        paths.append(str(f))
print(f"backfill candidates: {len(paths)}")
for p in paths:
    print(" ", p)
if paths:
    import subprocess, sys
    r = subprocess.run([sys.executable, "-m", "tools.publish_passes", *paths], cwd=".")
    print("publish_passes exit", r.returncode)
else:
    print("no recent PASS without listing — skip backfill")
PY

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] launching focused yield batch with --publish (k=5, vet_workers from config)"
# Prefer CC runner.launch so the job shows in the UI.
"$PY" - <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, str(Path(".").resolve()))
from prospector.control_center.runner import launch

argv = [
    str(Path(".venv/bin/python").resolve()),
    "-u", "-m", "prospector.run", "generate",
    "--candidates", "5",
    "--lane", "side_hustle",
    "--market", "uk",
    "--archetype", "solo_agent",
    "--profile", "statutory_compliance_pack",
    "--publish",
]
try:
    job_id = launch(argv)
    print(f"launched_via=runner.launch job_id={job_id}")
except Exception as e:
    # Fallback: CLI with file log (still durable).
    import subprocess, time
    log = Path("store/control_center/runs") / f"yield_uk_cli_{int(time.time())}.log"
    print(f"runner.launch failed ({e!r}); falling back to CLI log={log}")
    with open(log, "ab", buffering=0) as fh:
        subprocess.Popen(
            argv,
            cwd=".",
            stdin=subprocess.DEVNULL,
            stdout=fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    print(f"launched_via=cli log={log}")
PY

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] done"
