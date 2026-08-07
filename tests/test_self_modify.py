"""Tests for SelfModificationLog and ConfigSnapshot."""

import tempfile
from pathlib import Path

from prospector.self_modify import (
    STATUS_ACTIVE,
    STATUS_ROLLED_BACK,
    STATUS_SUPERSEDED,
    ConfigSnapshot,
    SelfModificationLog,
)


def test_record_and_retrieve():
    """Record a change and retrieve it."""
    with tempfile.TemporaryDirectory() as tmp:
        log = SelfModificationLog(Path(tmp) / "test_mod.db")

        cid = log.record(
            component="generation",
            field="temperature",
            old_value="0.7",
            new_value="0.9",
            trigger_signal="low_yield_kill_rate_0.88",
            expected_effect="Increase creativity to reduce kill rate",
        )

        assert cid is not None
        assert cid.startswith("change-")

        entry = log.get(cid)
        assert entry is not None
        assert entry["component"] == "generation"
        assert entry["field"] == "temperature"
        assert entry["old_value"] == "0.7"
        assert entry["new_value"] == "0.9"
        assert entry["trigger_signal"] == "low_yield_kill_rate_0.88"
        assert entry["status"] == STATUS_ACTIVE


def test_rollback():
    """Rollback should mark change as rolled back."""
    with tempfile.TemporaryDirectory() as tmp:
        log = SelfModificationLog(Path(tmp) / "test_rollback.db")

        cid = log.record("generation", "steer", "old", "new", "test", "test")
        assert log.rollback(cid) is True

        entry = log.get(cid)
        assert entry["status"] == STATUS_ROLLED_BACK
        assert entry["rolled_back_at"] is not None


def test_rollback_nonexistent():
    """Rollback of nonexistent change returns False."""
    with tempfile.TemporaryDirectory() as tmp:
        log = SelfModificationLog(Path(tmp) / "test_rollback_miss.db")
        assert log.rollback("nonexistent") is False


def test_rollback_already_rolled_back():
    """Double rollback should return False (idempotent guard)."""
    with tempfile.TemporaryDirectory() as tmp:
        log = SelfModificationLog(Path(tmp) / "test_double.db")
        cid = log.record("test", "x", "a", "b")
        assert log.rollback(cid) is True
        assert log.rollback(cid) is False


def test_list_recent():
    """List recent returns ordered by timestamp descending."""
    with tempfile.TemporaryDirectory() as tmp:
        log = SelfModificationLog(Path(tmp) / "test_list.db")

        log.record("gen", "temp", "0.5", "0.6", "t1", "e1")
        log.record("gen", "temp", "0.6", "0.7", "t2", "e2")
        log.record("gen", "temp", "0.7", "0.8", "t3", "e3")

        recent = log.list_recent(n=2)
        assert len(recent) == 2
        # Most recent first
        assert recent[0]["new_value"] == "0.8"
        assert recent[1]["new_value"] == "0.7"


def test_supersede_previous_active():
    """New change to same component+field supersedes old active one."""
    with tempfile.TemporaryDirectory() as tmp:
        log = SelfModificationLog(Path(tmp) / "test_supersede.db")

        cid1 = log.record("gen", "prompt", "v1", "v2")
        cid2 = log.record("gen", "prompt", "v2", "v3")

        assert log.get(cid1)["status"] == STATUS_SUPERSEDED
        assert log.get(cid2)["status"] == STATUS_ACTIVE


def test_list_active():
    """Only active changes should appear in list_active."""
    with tempfile.TemporaryDirectory() as tmp:
        log = SelfModificationLog(Path(tmp) / "test_active.db")

        cid1 = log.record("a", "x", "old", "new")
        cid2 = log.record("b", "y", "old", "new")
        log.rollback(cid2)

        active = log.list_active()
        active_ids = [a["change_id"] for a in active]
        assert cid1 in active_ids
        assert cid2 not in active_ids


def test_record_effect():
    """Recording a measured effect should persist."""
    with tempfile.TemporaryDirectory() as tmp:
        log = SelfModificationLog(Path(tmp) / "test_effect.db")

        cid = log.record("gen", "steer", "old", "new")
        effect = {
            "direction": "positive",
            "magnitude": 0.15,
            "confidence": 0.92,
            "sample_size": 20,
        }
        assert log.record_effect(cid, effect) is True

        entry = log.get(cid)
        import json

        measured = json.loads(entry["measured_effect"])
        assert measured["direction"] == "positive"
        assert measured["magnitude"] == 0.15


def test_get_active_change_ids():
    """Should return only active change IDs."""
    with tempfile.TemporaryDirectory() as tmp:
        log = SelfModificationLog(Path(tmp) / "test_ids.db")

        cid1 = log.record("a", "x", "old", "new")
        cid2 = log.record("b", "y", "old", "new")
        log.rollback(cid1)

        ids = log.get_active_change_ids()
        assert cid1 not in ids
        assert cid2 in ids


def test_diff():
    """Diff should show before/after."""
    with tempfile.TemporaryDirectory() as tmp:
        log = SelfModificationLog(Path(tmp) / "test_diff.db")
        cid = log.record("prompts", "gate_moat", "old prompt text", "new prompt text", "test", "improve moat")

        diff = log.diff(cid)
        assert diff is not None
        assert "old prompt text" in diff
        assert "new prompt text" in diff
        assert "improve moat" in diff


def test_config_snapshot_roundtrip():
    """Snapshot and restore should be a clean roundtrip."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        config_path = tmp_path / "config.yaml"
        snapshots_dir = tmp_path / "snapshots"

        # Write original config
        original = "temperature: 0.7\nmodel: claude-sonnet\n"
        config_path.write_text(original)

        cs = ConfigSnapshot(config_path, snapshots_dir)

        # Snapshot
        snap_path = cs.snapshot("test-change-001")
        assert snap_path.is_file()
        assert snap_path.read_text() == original

        # Modify config
        config_path.write_text("temperature: 0.9\nmodel: claude-sonnet\n")
        assert config_path.read_text() != original

        # Restore
        assert cs.restore("test-change-001") is True
        assert config_path.read_text() == original


def test_config_snapshot_list():
    """List should return snapshots sorted by mtime."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        config_path = tmp_path / "config.yaml"
        config_path.write_text("key: value\n")
        cs = ConfigSnapshot(config_path, tmp_path / "snaps")

        cs.snapshot("change-001")
        cs.snapshot("change-002")

        snapshots = cs.list_snapshots()
        assert len(snapshots) == 2


def test_config_snapshot_latest():
    """Latest should return most recent snapshot."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        config_path = tmp_path / "config.yaml"
        config_path.write_text("key: value\n")
        cs = ConfigSnapshot(config_path, tmp_path / "snaps")

        cs.snapshot("change-001")
        cs.snapshot("change-002")

        latest = cs.latest()
        assert latest is not None
        assert "change-002" in str(latest)
