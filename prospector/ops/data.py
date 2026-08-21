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
    corpus = _corpus(store)
    return {
        "copy": copy,
        "drill": _drill(store),
        "versioning": _versioning(root),
        "rpo": _rpo(copy),
        "corpus": corpus,
        "warnings": _warnings(copy) + _corpus_warnings(corpus),
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


#: A verdict dossier and a pack-lint receipt live in the SAME directory and are NOT the same
#: population. Measured 2026-08-21: this repo's `store/dossiers/` held 14 files and all fourteen
#: were `*.lint.json` receipts — a plain directory count reports a 14-dossier corpus that does
#: not exist. Count the two separately or do not count at all.
_LINT_SUFFIX = ".lint.json"


def _corpus(store: Path) -> dict:
    """CORPUS — where the verdict dossiers live, and how many this process can actually see.

    Registered 2026-08-21 on the founder's instruction, after a measurement found every
    catalogue on the laptop empty: 18 checkouts inspected, 0 dossiers in all of them. That is
    not a fault. The corpus is on the Fly volume `prospector_store`, mounted at `/data`
    (`deploy/engine/fly.toml:65-67`) with `PROSPECTOR_STORE_DIR=/data/store`, so a developer
    checkout genuinely cannot see it.

    What IS a fault is a screen that prints 0 and lets an operator read it as "the engine has
    produced nothing". So this reports the PATH it read and whether that path is the production
    one, next to every count. A number with no location is what made this invisible.

    The catalogue is opened `mode=ro`. A plain `sqlite3.connect` CREATES the file when it is
    missing, which would leave a phantom empty catalogue behind every time an operator opened
    this screen — and the store is single-writer, so the read must also never block the daemon.
    """
    import os
    import sqlite3

    declared = os.environ.get("PROSPECTOR_STORE_DIR")
    out: dict = {
        "store": str(store),
        "declared_by_env": declared,
        "is_production_path": str(store) == "/data/store",
        "catalogue": {"status": "unknown", "reason": "not read"},
        "files": {"status": "unknown", "reason": "not read"},
    }

    db = store / "prospector.db"
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2.0)
        try:
            rows = con.execute("SELECT COUNT(*) FROM dossiers").fetchone()[0]
            # Bound to the enum, never to a literal. `store.py:303` writes
            # `dossier.decision.value`, which is lowercase "pass"; a hardcoded 'PASS' here
            # returns 0 on a fully populated catalogue and reads as "we have sold nothing".
            from prospector.models import Decision
            passes = con.execute(
                "SELECT COUNT(*) FROM dossiers WHERE decision = ?",
                (Decision.PASS.value,)).fetchone()[0]
            out["catalogue"] = {"status": "ok", "dossiers": int(rows), "passes": int(passes),
                                "path": str(db)}
        finally:
            con.close()
    except sqlite3.Error as exc:
        # Missing file, missing table and a locked store all land here, and every one of them
        # means "no answer", never "zero".
        out["catalogue"] = {"status": "unknown", "path": str(db),
                            "reason": f"{type(exc).__name__}: {exc}"}

    ddir = store / "dossiers"
    try:
        names = [f.name for f in ddir.iterdir() if f.is_file() and f.name.endswith(".json")]
        out["files"] = {
            "status": "ok",
            "path": str(ddir),
            "dossiers": sum(1 for n in names if not n.endswith(_LINT_SUFFIX)),
            "lint_receipts": sum(1 for n in names if n.endswith(_LINT_SUFFIX)),
        }
    except OSError as exc:
        out["files"] = {"status": "unknown", "path": str(ddir),
                        "reason": f"{type(exc).__name__}: {exc}"}
    return out


def _corpus_warnings(corpus: dict) -> list[str]:
    """An empty corpus on a non-production path is EXPECTED and must not read as an incident;
    an empty corpus on the production path is the incident. The two look identical as a count,
    which is exactly why the path is carried alongside it."""
    out: list[str] = []
    cat = corpus.get("catalogue") or {}
    where = corpus.get("store")
    if cat.get("status") != "ok":
        out.append(f"The catalogue at {cat.get('path')} could not be read: {cat.get('reason')}. "
                   "That is a failed measurement, not an empty corpus.")
        return out
    if cat.get("dossiers") == 0:
        if corpus.get("is_production_path"):
            out.append(f"The production catalogue at {where} holds 0 dossiers. The engine has "
                       "published nothing, or the store this process reads is not the store the "
                       "daemon writes.")
        else:
            out.append(f"This process reads {where}, which is NOT the production store. The "
                       "corpus lives on the Fly volume `prospector_store` at /data/store; 0 "
                       "here means out of reach, not empty.")
    return out


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
