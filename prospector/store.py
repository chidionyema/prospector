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
    path            TEXT,
    ambition_tier   TEXT,
    structural_form TEXT,
    provisional     INTEGER DEFAULT 0,
    dense_reward    REAL,
    adversarial_confidence REAL,
    persona         TEXT
);
"""

_CREATE_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_decision ON dossiers(decision);
CREATE INDEX IF NOT EXISTS idx_reverify ON dossiers(reverify_due_at);
CREATE INDEX IF NOT EXISTS idx_ambition_tier ON dossiers(ambition_tier);
CREATE INDEX IF NOT EXISTS idx_structural_form ON dossiers(structural_form);
CREATE INDEX IF NOT EXISTS idx_dense_reward ON dossiers(dense_reward);
CREATE INDEX IF NOT EXISTS idx_persona ON dossiers(persona);
"""

_UPSERT = """
INSERT OR REPLACE INTO dossiers
    (candidate_id, title, one_liner, decision, gate_fired, composite,
     created_at, reverify_due_at, path, ambition_tier, structural_form, 
     provisional, dense_reward, adversarial_confidence, persona)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
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
            conn.execute(_CREATE_TABLE)
            # Migration: add any new columns that an old DB is missing.
            cols = {r[1] for r in conn.execute("PRAGMA table_info(dossiers)")}
            for col, typ in [("one_liner", "TEXT"),
                               ("ambition_tier", "TEXT"),
                               ("structural_form", "TEXT"),
                               ("provisional", "INTEGER DEFAULT 0"),
                               ("dense_reward", "REAL"),
                               ("adversarial_confidence", "REAL"),
                               ("persona", "TEXT")]:
                if col not in cols:
                    conn.execute(f"ALTER TABLE dossiers ADD COLUMN {col} {typ}")
            
            # Create indexes AFTER columns are guaranteed to exist
            conn.executescript(_CREATE_INDEXES)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save(self, dossier: Dossier) -> Path:
        """Persist dossier JSON and upsert the index row. Returns the JSON path.

        The write is atomic (write-temp-then-rename) so a mid-write kill or crash
        never leaves a partial/corrupt dossier JSON — the prior version or nothing
        is visible at the target path. This is the cancel-safety guarantee. (CC #1)
        """
        cid = dossier.candidate.candidate_id
        dec = dossier.decision.value  # "pass" | "kill" | "defer"
        path = self._dossier_dir / f"{cid}.{dec}.json"
        # Atomic write: temp → rename. A SIGKILL mid-write leaves the temp file
        # orphaned (never at the target path); only a completed write lands.
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(dossier.to_json(), encoding="utf-8")
        tmp.rename(path)

        # A re-vet can change a candidate's decision (e.g. defer -> kill). The DB row is
        # upserted by candidate_id, but the JSON filename encodes the decision, so an old
        # verdict's file would linger and be double-counted. Remove any stale-decision
        # files for this candidate (keep only the one we just wrote).
        for stale in self._dossier_dir.glob(f"{cid}.*.json"):
            if stale != path:
                stale.unlink(missing_ok=True)

        composite = dossier.score.composite if dossier.score else None
        # Extract ambition_tier and structural_form for per-lane indexing.
        tier = getattr(dossier.candidate, "ambition_tier", "") or ""
        form = getattr(dossier.candidate, "structural_form", "") or ""
        adv_conf = dossier.adversarial.confidence if dossier.adversarial else 0.0

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
                tier,
                form,
                int(bool(getattr(dossier, "provisional", False))),
                dossier.dense_reward,
                adv_conf,
                getattr(dossier, "persona", "") or ""
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

    def all(self, decision: Optional[str] = None,
             ambition_tier: Optional[str] = None) -> list[dict]:
        """Return all index rows as dicts, optionally filtered.

        Args:
            decision: filter to pass/kill/defer only.
            ambition_tier: filter to a specific lane (e.g. 'venture', 'side_hustle')."""
        with self._connect() as conn:
            if decision is not None and ambition_tier is not None:
                rows = conn.execute(
                    "SELECT * FROM dossiers WHERE decision = ? AND ambition_tier = ?",
                    (decision, ambition_tier)).fetchall()
            elif decision is not None:
                rows = conn.execute(
                    "SELECT * FROM dossiers WHERE decision = ?", (decision,)
                ).fetchall()
            elif ambition_tier is not None:
                rows = conn.execute(
                    "SELECT * FROM dossiers WHERE ambition_tier = ?",
                    (ambition_tier,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM dossiers").fetchall()
        return [dict(row) for row in rows]

    def provisional(self) -> list[dict]:
        """Return rows ruled by the emergency fallback tail (moat exhausted).

        These are real-but-untrusted decisions (PASS or KILL) awaiting a moat re-vet.
        `vet --resume` re-runs them so the trusted moat overwrites the cheap verdict."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM dossiers WHERE provisional = 1").fetchall()
        return [dict(row) for row in rows]
