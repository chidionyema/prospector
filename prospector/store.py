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
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

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
    persona         TEXT,
    retrieval_degraded INTEGER DEFAULT 0,
    market          TEXT,
    audience         TEXT,
    seed_kind        TEXT
);
"""

_CREATE_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_decision ON dossiers(decision);
CREATE INDEX IF NOT EXISTS idx_reverify ON dossiers(reverify_due_at);
CREATE INDEX IF NOT EXISTS idx_ambition_tier ON dossiers(ambition_tier);
CREATE INDEX IF NOT EXISTS idx_structural_form ON dossiers(structural_form);
CREATE INDEX IF NOT EXISTS idx_dense_reward ON dossiers(dense_reward);
CREATE INDEX IF NOT EXISTS idx_persona ON dossiers(persona);
CREATE INDEX IF NOT EXISTS idx_market ON dossiers(market);
CREATE INDEX IF NOT EXISTS idx_audience ON dossiers(audience);
CREATE INDEX IF NOT EXISTS idx_seed_kind ON dossiers(seed_kind);
"""

_UPSERT = """
INSERT OR REPLACE INTO dossiers
    (candidate_id, title, one_liner, decision, gate_fired, composite,
     created_at, reverify_due_at, path, ambition_tier, structural_form,
     provisional, dense_reward, adversarial_confidence, persona, retrieval_degraded,
     market, audience, seed_kind)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
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

    @property
    def root(self) -> Path:
        """The store directory this catalogue lives in (`cfg.store_dir`).

        Public because the drain's attempt ledger (`prospector/drain_state.py`) is a sidecar
        under the same directory, and the two callers that must agree on the backlog — the
        drain and the scheduler's brake — reach it through the Store they already hold rather
        than each deriving a path from a Config.
        """
        return self._root

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Open a connection, commit-or-rollback the block, then CLOSE it.

        This used to `return` a bare `sqlite3.Connection`. Every one of the call sites
        below already wrote `with self._connect() as conn:` — which reads like a resource
        manager but is not one: `sqlite3.Connection.__exit__` commits or rolls back the
        transaction and deliberately leaves the connection OPEN. So each call leaked two
        descriptors (the db and its WAL) for the process's lifetime.

        Measured 2026-08-06: 200 `has_dossier()` calls leaked 201 fds, monotonic. It went
        unnoticed for as long as it did because every caller was O(1) per run; the backlog
        brake's per-row survey (`run.drain_survey`) is the first O(rows) caller, and it
        took the daemon past launchd's 256-fd default inside four seconds of starting —
        `[Errno 24] Too many open files` writing `heartbeat.json`, which then made the
        drainable count unavailable, which correctly-but-uselessly suppressed generation.
        The leak was the bug; the brake just found it.

        The inner `with conn:` preserves the exact transaction semantics every call site
        was already relying on, so this is a drop-in: commit on success, rollback on
        exception, and now close either way.
        """
        conn = sqlite3.connect(str(self.db), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

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
                               ("persona", "TEXT"),
                               ("retrieval_degraded", "INTEGER DEFAULT 0"),
                               ("market", "TEXT"),
                               # The audience persona generation wrote the candidate FOR
                               # (`candidate.tags["audience"]`, generate.py:552). NOT the same
                               # thing as `persona` above, which is the Part-16 analysis tint
                               # that colours a verdict; this one is who the idea is aimed at.
                               # Indexed because per-persona yield is the question it exists to
                               # answer, and a scan over 1.4k dossier JSONs to ask it is why the
                               # field went unread for so long.
                               ("audience", "TEXT"),
                               # Why a row must no longer be acted on, or NULL for a live row.
                               # The index and the disk can disagree: 189 rows on the live store
                               # (all created 2026-06-13..06-21) have no dossier JSON behind them,
                               # and 45 of those are DEFERs that the bounded drain re-selects and
                               # re-skips every tick forever. They are not deletable — the ruling
                               # happened and the audit trail should say so — but they are not
                               # workable either. A tombstone records both facts.
                               ("tombstone", "TEXT"),
                               # G5 seed provenance: "signal" | "blue_sky" | "". Backfill is
                               # deliberately NOT attempted — the 1789 pre-existing rows were
                               # written before generation stamped this, and inferring their
                               # provenance from created_at or from which command probably ran
                               # would manufacture data. They stay '' and the survival report
                               # counts them as an explicit `unknown` bucket rather than
                               # silently folding them into whichever kind is more convenient.
                               ("seed_kind", "TEXT")]:
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
                getattr(dossier, "persona", "") or "",
                # Audit: did ANY check rule under degraded/failed retrieval? Lets the
                # audit trail tell a clean grounded verdict from one served on thin
                # evidence, independent of the DEFER decision and provisional flag.
                int(any(getattr(c, "degraded", False) or getattr(c, "retrieval_failed", False)
                        for c in getattr(dossier, "checks", []) or [])),
                getattr(dossier.candidate, "market", "") or "",
                # Generation stamps this on 1410 of 1436 dossiers on disk and every reader
                # downstream of `save` then had to re-open the JSON to see it. Lifted into the
                # index so persona can be grouped in SQL. Empty string, never NULL, matching
                # `market` and `persona` — a mix of '' and NULL in one column silently splits
                # every GROUP BY into two buckets that mean the same thing.
                getattr(dossier.candidate, "audience", "") or "",
                # Same shape as `audience` directly above, including the ''-never-NULL rule:
                # a mix of '' and NULL in one column splits every GROUP BY into two buckets
                # that mean the same thing.
                getattr(dossier.candidate, "seed_kind", "") or "",
            ))
        return path

    def catalogue_titles(self) -> list[tuple[str, str]]:
        """Return (market, fingerprint) for all PASS dossiers (used by dedup).

        The market travels with the fingerprint because the same idea in a different
        jurisdiction is NOT a duplicate — "mobile notary bond, Texas" and the UK version
        are different opportunities with different evidence. Pre-Epic-D rows carry '' and
        are treated as the default market by dedup.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT title, one_liner, market FROM dossiers WHERE decision = ?",
                (Decision.PASS.value,),
            ).fetchall()
        return [(row["market"] or "", f"{row['title']} {row['one_liner']}".strip())
                for row in rows]

    def markets_present(self) -> dict[str, int]:
        """Dossier counts keyed by market ('' = pre-Epic-D rows). Feeds diagnostics."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT COALESCE(market, '') AS m, COUNT(*) AS n "
                "FROM dossiers GROUP BY m ORDER BY n DESC"
            ).fetchall()
        return {row["m"]: row["n"] for row in rows}

    def recent_titles(self, limit: int = 200) -> list[str]:
        """Return the most recent dossier titles across ALL decisions (PASS/KILL/DEFER).

        This is generation's CROSS-RUN MEMORY. catalogue_titles() returns PASS only, so an
        idea that keeps getting KILLed (e.g. a probate-clearance variant) is invisible to it —
        and the blue-sky daemon happily regenerates the same family every wave because the
        in-run `avoid` list is wiped between runs. Seeding generation's avoid list from this
        (kills included) stops the engine from re-spending budget on ideas it has already seen.
        Ordered newest-first so a bounded slice is the freshest memory.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT title FROM dossiers ORDER BY created_at DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [row["title"] for row in rows if (row["title"] or "").strip()]

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

    def has_dossier(self, candidate_id: str) -> bool:
        """True if this index row has a file behind it — the cheap half of `get()`.

        Same criterion `get()` uses (row present AND its path exists on disk), without reading
        or parsing the JSON. It exists because the scheduler's backlog brake surveys the WHOLE
        drainable population once per tick to decide whether generation may run: at the live
        backlog that is ~340 dossiers, and `get()` would read and json-parse every one of them
        to answer a question that is one stat call.
        """
        if not candidate_id:
            return False
        with self._connect() as conn:
            row = conn.execute(
                "SELECT path FROM dossiers WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
        if row is None:
            return False
        p = str(row["path"] or "")
        return bool(p) and Path(p).exists()

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

    def tombstone(self, candidate_id: str, reason: str, *,
                  path: Optional[str] = None, decision: Optional[str] = None) -> bool:
        """Mark a row as recorded-but-not-workable. Returns False if no such row.

        Deliberately NOT a delete: the ruling happened, and a catalogue that silently loses
        189 of its 1594 rows cannot answer "what did we decide, and when". Readers that act
        on rows (the resume drain, generation exemplars) skip tombstoned ones; readers that
        count history do not.

        `path` and `decision` are for the case where the dossier was MOVED rather than lost
        (nine PASSes were relocated to store/dossiers/quarantine_ungrounded/ without the
        index being updated), so the row can be re-pointed at the file that still exists in
        the same statement that voids it.

        NOTE: `_UPSERT` is INSERT OR REPLACE over an explicit column list that excludes
        `tombstone`, so re-saving a dossier for this candidate_id CLEARS the mark. That is
        the wanted behaviour — a fresh ruling with a file behind it supersedes a tombstone —
        but it means a tombstone is not a permanent ban, and must not be used as one.
        """
        sets = ["tombstone = ?"]
        params: list = [reason]
        if path is not None:
            sets.append("path = ?")
            params.append(path)
        if decision is not None:
            sets.append("decision = ?")
            params.append(decision)
        params.append(candidate_id)
        with self._connect() as conn:
            cur = conn.execute(
                f"UPDATE dossiers SET {', '.join(sets)} WHERE candidate_id = ?", params)
            return cur.rowcount > 0
