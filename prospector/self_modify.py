"""Self-modification log and rollback for Prospector's recursive improvement.

Every adaptation the engine makes to itself (prompt changes, config tweaks,
policy updates) is recorded with full before/after and trigger signal. Any
change can be rolled back with a single command.

Part of the production-grade self-improvement infrastructure (Priority 2).
"""

import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Status values for modifications
STATUS_PENDING = "pending"
STATUS_ACTIVE = "active"
STATUS_ROLLED_BACK = "rolled_back"
STATUS_SUPERSEDED = "superseded"


class SelfModificationLog:
    """Audit log for every self-modification the engine makes.

    Records what changed, why, and what the expected effect was. Supports
    rollback of any change and tracks measured effects.
    """

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS modifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    change_id TEXT NOT NULL UNIQUE,
                    timestamp TEXT NOT NULL,
                    component TEXT NOT NULL,
                    field TEXT NOT NULL,
                    old_value TEXT NOT NULL,
                    new_value TEXT NOT NULL,
                    trigger_signal TEXT NOT NULL DEFAULT '',
                    expected_effect TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active',
                    measured_effect TEXT DEFAULT NULL,
                    rolled_back_at TEXT DEFAULT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_modifications_ts
                ON modifications(timestamp DESC)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_modifications_status
                ON modifications(status)
            """)

    def record(
        self,
        component: str,
        field: str,
        old_value: str,
        new_value: str,
        trigger_signal: str = "",
        expected_effect: str = "",
    ) -> str:
        """Record a self-modification. Returns the change_id."""
        now = datetime.now(timezone.utc)
        # Microsecond precision + random suffix to prevent same-second collisions
        import random
        suffix = f"{random.randint(1000, 9999)}"
        change_id = f"change-{now.strftime('%Y%m%d-%H%M%S')}-{now.microsecond:06d}-{suffix}-{component}-{field}"

        # Supersede any previous active changes to the same component+field
        with self._connect() as conn:
            conn.execute(
                """UPDATE modifications SET status = ?
                   WHERE component = ? AND field = ? AND status = ?""",
                (STATUS_SUPERSEDED, component, field, STATUS_ACTIVE),
            )

            conn.execute(
                """INSERT INTO modifications
                   (change_id, timestamp, component, field, old_value, new_value,
                    trigger_signal, expected_effect, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    change_id,
                    now.isoformat(),
                    component,
                    field,
                    old_value,
                    new_value,
                    trigger_signal,
                    expected_effect,
                    STATUS_ACTIVE,
                ),
            )

        return change_id

    def rollback(self, change_id: str) -> bool:
        """Mark a change as rolled back. Returns True if found and rolled back."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """UPDATE modifications SET status = ?, rolled_back_at = ?
                   WHERE change_id = ? AND status != ?""",
                (STATUS_ROLLED_BACK, now, change_id, STATUS_ROLLED_BACK),
            )
            return cursor.rowcount > 0

    def get(self, change_id: str) -> Optional[dict]:
        """Get a single modification by change_id."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM modifications WHERE change_id = ?", (change_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_recent(self, n: int = 20) -> list[dict]:
        """List the N most recent modifications."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM modifications ORDER BY timestamp DESC LIMIT ?",
                (n,),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_active(self) -> list[dict]:
        """List all currently active modifications."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM modifications WHERE status = ? ORDER BY timestamp DESC",
                (STATUS_ACTIVE,),
            ).fetchall()
        return [dict(r) for r in rows]

    def record_effect(self, change_id: str, effect: dict) -> bool:
        """Record the measured effect of a change after evaluation.

        effect dict should have: direction (positive|negative|neutral),
        magnitude, confidence, sample_size.
        """
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE modifications SET measured_effect = ? WHERE change_id = ?",
                (json.dumps(effect), change_id),
            )
            return cursor.rowcount > 0

    def get_active_change_ids(self) -> list[str]:
        """Return change_ids of all currently active modifications."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT change_id FROM modifications WHERE status = ?",
                (STATUS_ACTIVE,),
            ).fetchall()
        return [r["change_id"] for r in rows]

    def diff(self, change_id: str) -> Optional[str]:
        """Pretty-print a before/after diff for a change."""
        entry = self.get(change_id)
        if not entry:
            return None
        return (
            f"Change: {entry['change_id']}\n"
            f"Component: {entry['component']}.{entry['field']}\n"
            f"Status: {entry['status']}\n"
            f"Trigger: {entry['trigger_signal']}\n"
            f"Expected: {entry['expected_effect']}\n"
            f"\n--- Old ({len(entry['old_value'])} chars) ---\n"
            f"{entry['old_value'][:200]}\n"
            f"\n+++ New ({len(entry['new_value'])} chars) +++\n"
            f"{entry['new_value'][:200]}"
        )


class ConfigSnapshot:
    """Snapshot and restore Prospector config.yaml around self-modifications.

    Before any self-modification touches config.yaml, take a snapshot.
    If the change proves harmful, restore the snapshot.
    """

    def __init__(self, config_path: Path, snapshots_dir: Optional[Path] = None):
        self.config_path = Path(config_path)
        self.snapshots_dir = (
            Path(snapshots_dir)
            if snapshots_dir
            else self.config_path.parent / "store" / "config_snapshots"
        )

    def snapshot(self, change_id: str) -> Path:
        """Save current config as a named snapshot. Returns snapshot path."""
        if not self.config_path.is_file():
            raise FileNotFoundError(f"Config not found: {self.config_path}")

        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = self.snapshots_dir / f"change_{change_id}_before.yaml"
        shutil.copy2(self.config_path, snapshot_path)
        return snapshot_path

    def restore(self, change_id: str) -> bool:
        """Restore a snapshot back to config.yaml. Returns True on success."""
        snapshot_path = self.snapshots_dir / f"change_{change_id}_before.yaml"
        if not snapshot_path.is_file():
            return False

        # Create backup of current before restoring
        backup_path = (
            self.snapshots_dir / f"change_{change_id}_restored_backup.yaml"
        )
        if self.config_path.is_file():
            shutil.copy2(self.config_path, backup_path)

        shutil.copy2(snapshot_path, self.config_path)
        return True

    def list_snapshots(self) -> list[Path]:
        """List all available snapshots, newest first (by filename)."""
        if not self.snapshots_dir.is_dir():
            return []
        return sorted(
            self.snapshots_dir.glob("change_*_before.yaml"),
            key=lambda p: p.name,
            reverse=True,
        )

    def latest(self) -> Optional[Path]:
        """Return the most recent snapshot path."""
        snapshots = self.list_snapshots()
        return snapshots[0] if snapshots else None
