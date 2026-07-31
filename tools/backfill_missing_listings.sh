#!/usr/bin/env bash
# Publish all non-provisional PASSes that lack store/listings receipts.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${ROOT}/.venv/bin/python"
# Do NOT pin concurrency here. This used to default to 2, and the env var WINS over config
# (cursor_cli.configure_concurrency returns early when it is set), so this line silently
# overrode retrieval.cursor_concurrency and kept the backfill at 2 slots forever. Oversubscription
# was the real reason a low number looked necessary, and prospector/cli_governor.py now enforces
# the cap machine-wide via flock — every pipeline draws from ONE shared pool of slot files, so
# config can be the single source of truth again. An explicit env var still overrides for debugging.
if [ -n "${PROSPECTOR_CURSOR_CONCURRENCY:-}" ]; then
  export PROSPECTOR_CURSOR_CONCURRENCY
fi
LOG="${ROOT}/store/control_center/runs/backfill_all_listings.log"
mkdir -p "$(dirname "$LOG")"
exec >>"$LOG" 2>&1
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] backfill_missing_listings start"
"$PY" -u - <<'PY'
import json, subprocess, sys
from pathlib import Path
paths = []
for f in sorted(Path("store/dossiers").glob("*.pass.json")):
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        continue
    if str(d.get("decision", "")).lower() != "pass" or d.get("provisional"):
        continue
    cid = (d.get("candidate") or {}).get("candidate_id") or f.stem.split(".")[0]
    if Path(f"store/listings/{cid}.json").exists():
        continue
    paths.append(str(f))
print(f"missing={len(paths)}", flush=True)
# Raised from 2 on 2026-07-31. Each batch is a fresh `tools.publish_passes` subprocess, so a
# small batch pays full interpreter + config + store startup per 2 dossiers and cannot overlap
# CLI work across the boundary. The per-dossier work is unchanged — this only widens the window
# in which the 8 shared CLI slots can stay busy. Restart-safety is preserved: the existence
# check below re-runs per batch, so anything already carrying a listing is still skipped.
batch_size = 5
for i in range(0, len(paths), batch_size):
    batch = [p for p in paths[i:i+batch_size]
             if not Path(f"store/listings/{Path(p).name.replace('.pass.json','')}.json").exists()]
    if not batch:
        continue
    print(f"batch {i//batch_size+1}/{ (len(paths)+batch_size-1)//batch_size }: {batch}", flush=True)
    r = subprocess.run([sys.executable, "-u", "-m", "tools.publish_passes", *batch], cwd=".")
    print(f"exit={r.returncode} listings_now={len(list(Path('store/listings').glob('*.json')))}", flush=True)
print("backfill_missing_listings done", flush=True)
PY
