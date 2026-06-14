"""SQLite + JSON-on-disk catalogue (Part 8).

Store persists every Dossier (PASS and KILL are both first-class) as:
  - A JSON file at cfg.store_dir/dossiers/<candidate_id>.<decision>.json
  - A lightweight SQLite index at cfg.store_dir/prospector.db for fast queries.

All SQL uses parameterised queries. Schema creation is idempotent
(CREATE TABLE IF NOT EXISTS / INSERT OR REPLACE).
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional

from .config import Config
from .models import Decision, Dossier

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS dossiers (
    candidate_id    TEXT PRIMARY KEY,
    title           TEXT,
    one_liner       TEXT,
    decision        TEXT,
    gate_fired      TEXT,
    composite       REAL,
    created_at      TEXT,
    reverify_due_at TEXT,
    path            TEXT
);
CREATE INDEX IF NOT EXISTS idx_decision ON dossiers(decision);
CREATE INDEX IF NOT EXISTS idx_reverify ON dossiers(reverify_due_at);
"""

_UPSERT = """
INSERT OR REPLACE INTO dossiers
    (candidate_id, title, one_liner, decision, gate_fired, composite,
     created_at, reverify_due_at, path)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
"""


class Store:
    """Persistent catalogue backed by SQLite index + per-dossier JSON files."""

    def __init__(self, cfg: Config) -> None:
        self._root: Path = cfg.store_dir
        self._root.mkdir(parents=True, exist_ok=True)
        self._dossier_dir: Path = self._root / "dossiers"
        self._dossier_dir.mkdir(parents=True, exist_ok=True)
        self.db: Path = self._root / "prospector.db"
        self._init_db()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_CREATE_TABLE)
            # Migrate DBs created before the one_liner column existed: CREATE TABLE
            # IF NOT EXISTS leaves an old table untouched, so add the column in place.
            cols = {r[1] for r in conn.execute("PRAGMA table_info(dossiers)")}
            if "one_liner" not in cols:
                conn.execute("ALTER TABLE dossiers ADD COLUMN one_liner TEXT")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save(self, dossier: Dossier) -> Path:
        """Persist dossier JSON and upsert the index row. Returns the JSON path."""
        cid = dossier.candidate.candidate_id
        dec = dossier.decision.value  # "pass" | "kill" | "defer"
        path = self._dossier_dir / f"{cid}.{dec}.json"
        path.write_text(dossier.to_json(), encoding="utf-8")

        # A re-vet can change a candidate's decision (e.g. defer -> kill). The DB row is
        # upserted by candidate_id, but the JSON filename encodes the decision, so an old
        # verdict's file would linger and be double-counted. Remove any stale-decision
        # files for this candidate (keep only the one we just wrote).
        for stale in self._dossier_dir.glob(f"{cid}.*.json"):
            if stale != path:
                stale.unlink(missing_ok=True)

        composite = dossier.score.composite if dossier.score else None
        with self._connect() as conn:
            conn.execute(_UPSERT, (
                cid,
                dossier.candidate.title,
                dossier.candidate.one_liner,
                dec,
                dossier.gate_fired,
                composite,
                dossier.created_at,
                dossier.reverify_due_at,
                str(path),
            ))
        return path

    def catalogue_titles(self) -> list[str]:
        """Return fingerprints of all PASS dossiers (used by dedup)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT title, one_liner FROM dossiers WHERE decision = ?",
                (Decision.PASS.value,),
            ).fetchall()
        return [f"{row['title']} {row['one_liner']}".strip() for row in rows]

    def get(self, candidate_id: str) -> Optional[dict]:
        """Load and return the stored dossier dict, or None if not found."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT path FROM dossiers WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
        if row is None:
            return None
        p = Path(row["path"])
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def all(self, decision: Optional[str] = None) -> list[dict]:
        """Return all index rows as dicts, optionally filtered by decision string."""
        if decision is not None:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM dossiers WHERE decision = ?", (decision,)
                ).fetchall()
        else:
            with self._connect() as conn:
                rows = conn.execute("SELECT * FROM dossiers").fetchall()
        return [dict(row) for row in rows]
