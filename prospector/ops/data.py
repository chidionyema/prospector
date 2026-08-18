"""The Data screen's reader.

One question: if the Fly volume went away in the next minute, what would we get back and how
much would we have lost.

Every number here comes from a control that already exists. This module runs those controls and
reports them; it computes nothing of its own.

  * DAT-1 — `ops/automations/offsite_backup.py` already answers "is there a fresh copy" as a
    measurement with an exit code. It is called read-only here (`fix=False`), so opening this
    screen never takes a backup.
  * DAT-2 — `scripts/restore_drill.py` proves a copy restores. Its receipt is
    `store/ops/restore_drill.json`. No receipt means the drill has never been run, which is the
    honest answer and the one the risk register carries.
  * DAT-4 — the recovery point is the age of the newest copy. How many orders sit inside that
    window is NOT computed here: the orders live in SQLite on Fly, and guessing at the count
    from local files would be a number the database disagrees with.
  * AST-1 — bucket versioning, asked of the same storage client the backup uses. Without it, an
    overwrite or a delete is final even though a copy exists.

Anything that cannot be measured is reported as `unknown` with the reason. A screen about
recovery must never render "no answer" as "fine".
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from prospector.config import store_root

#: Where `restore_drill.py` leaves its receipt, RELATIVE TO THE STORE. It used to be relative to
#: the repo (`store/ops/restore_drill.json`) and was read from `_repo_root()`, which is a store
#: path derived from `__file__` — it follows the CODE, not the store. On Fly the code is /app and
#: the store is /data/store, so this screen read a path nothing writes and reported "the restore
#: has never been proven" no matter how many drills passed.
DRILL_RECEIPT = Path("ops") / "restore_drill.json"

#: A drill older than this is not evidence any more. Quarterly is the weakest defensible cadence
#: for a restore nobody has automated; it is here as a number so the screen can go amber rather
#: than reading green forever off one run in August.
DRILL_STALE_DAYS = 90


def data_view(cfg: Any, *, root: Optional[Path] = None,
              store: Optional[Path] = None) -> dict:
    """`root` locates the REPO (declarations, .env); `store` locates the STATE. Two arguments
    because they are two different directories in production and were conflated here."""
    root = Path(root) if root else _repo_root()
    store = Path(store) if store else store_root()
    copy = _offsite(root)
    return {
        "copy": copy,
        "drill": _drill(store),
        "versioning": _versioning(root),
        "rpo": _rpo(copy),
        "warnings": _warnings(copy),
    }


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _offsite(root: Path) -> dict:
    """DAT-1, read-only. The automation's own answer, not a re-implementation of it."""
    cfg_path = root / "ops" / "config" / "offsite_backup.yaml"
    if not cfg_path.exists():
        return {"status": "unknown", "reason": f"no declaration at {cfg_path}", "sources": []}
    try:
        import sys
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from ops.automations import offsite_backup

        return offsite_backup.run(cfg_path, fix=False)
    except Exception as exc:  # noqa: BLE001 — credentials, network, import: all are "unknown"
        return {"status": "unknown", "reason": f"{type(exc).__name__}: {exc}", "sources": []}


def _drill(store: Path) -> dict:
    """DAT-2. Absent receipt means never proven, and that is what the screen says."""
    path = store / DRILL_RECEIPT
    if not path.exists():
        return {"state": "never", "path": str(DRILL_RECEIPT), "ran_at": None, "ok": None,
                "what": "the restore has never been proven end to end"}
    try:
        rec = json.loads(path.read_text())
    except Exception as exc:  # noqa: BLE001
        return {"state": "unreadable", "path": str(DRILL_RECEIPT), "ran_at": None, "ok": None,
                "what": f"receipt is not readable: {exc}"}

    age_days = _age_days(rec.get("ran_at"))
    ok = bool(rec.get("ok"))
    if not ok:
        state = "failed"
    elif age_days is not None and age_days > DRILL_STALE_DAYS:
        state = "stale"
    else:
        state = "ok"
    return {"state": state, "path": str(DRILL_RECEIPT), "ran_at": rec.get("ran_at"), "ok": ok,
            "age_days": age_days, "took_s": rec.get("took_s"),
            "restored": rec.get("restored"), "what": rec.get("what") or ""}


def _versioning(root: Path) -> dict:
    """AST-1. Without versioning, one bad sync overwrites the copy that was the safety net."""
    cfg_path = root / "ops" / "config" / "offsite_backup.yaml"
    if not cfg_path.exists():
        return {"state": "unknown", "reason": f"no declaration at {cfg_path}"}
    try:
        import sys
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from ops.automations import offsite_backup

        decl = offsite_backup.load_declaration(cfg_path)
        offsite_backup.load_dotenv(root / ".env")
        client, bucket, _prefix = offsite_backup.storage_client(decl.storage)
        got = client.get_bucket_versioning(Bucket=bucket) or {}
        status = got.get("Status")
        return {"state": "on" if status == "Enabled" else "off", "bucket": bucket,
                "raw": status, "reason": None}
    except Exception as exc:  # noqa: BLE001
        return {"state": "unknown", "reason": f"{type(exc).__name__}: {exc}"}


def _rpo(copy: dict) -> dict:
    """DAT-4. The window, stated as the thing it actually is: the age of the newest copy."""
    ages = [s.get("age_hours") for s in copy.get("sources", [])
            if isinstance(s, dict) and s.get("age_hours") is not None]
    if not ages:
        return {"hours": None,
                "what": "no copy age is known, so the recovery point cannot be stated"}
    worst = max(ages)
    return {
        "hours": worst,
        "what": (f"up to {worst:.1f}h of writes would be lost. How many orders that is cannot "
                 "be counted from here — they live in SQLite on Fly, and no route reports them."),
    }


def _warnings(copy: dict) -> list[str]:
    out: list[str] = []
    if copy.get("status") == "unknown":
        out.append(f"The backup check could not run: {copy.get('reason')}. "
                   "This is a failed measurement, not a fresh copy.")
    for finding in copy.get("findings", []) or []:
        out.append(str(finding.get("what") or finding))
    return out


def _age_days(stamp: Any) -> Optional[float]:
    if not stamp:
        return None
    from datetime import datetime, timezone
    try:
        when = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return round((datetime.now(timezone.utc) - when).total_seconds() / 86400.0, 2)
