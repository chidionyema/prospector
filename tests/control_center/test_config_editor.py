"""Behavioral tests for control_center.config_editor.

Tests schema validation, moat-affecting detection, diff, mtime conflict,
write/backup, and certification state.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import pytest

import prospector.control_center.config_editor as ce


class TestValidateConfig:
    """validate_config() must accept valid configs and reject invalid ones."""

    def test_valid_real_config_passes(self):
        raw = ce.load_config_raw()
        valid, errs = ce.validate_config(raw)
        assert valid, f"Real config should be valid: {errs}"
        assert errs == []

    def test_rejects_confidence_floor_out_of_range(self):
        invalid = {
            "thresholds": {"confidence_floor": 1.5},
            "weights": {},
        }
        valid, errs = ce.validate_config(invalid)
        assert not valid
        assert any("confidence_floor" in e for e in errs)

    def test_rejects_negative_confidence_floor(self):
        invalid = {
            "thresholds": {"confidence_floor": -0.1},
            "weights": {},
        }
        valid, errs = ce.validate_config(invalid)
        assert not valid

    def test_rejects_weights_not_summing_to_one(self):
        invalid = {
            "thresholds": {},
            "weights": {
                "pain_acuity": 0.5,
                "money_provability": 0.2,
                # total = 0.7, not 1.0
            },
        }
        valid, errs = ce.validate_config(invalid)
        assert not valid
        assert any("sum" in e.lower() for e in errs)

    def test_rejects_negative_weight(self):
        invalid = {
            "thresholds": {},
            "weights": {"pain_acuity": -0.1},
        }
        valid, errs = ce.validate_config(invalid)
        assert not valid

    def test_rejects_negative_spend_cap(self):
        invalid = {
            "thresholds": {},
            "weights": {},
            "spend": {"daily_cap_usd": -5.0},
        }
        valid, errs = ce.validate_config(invalid)
        assert not valid
        assert any("daily_cap" in e for e in errs)

    def test_accepts_zero_queries_per_check(self):
        """0 means 'use provider default' — valid."""
        invalid = {
            "thresholds": {},
            "weights": {},
            "retrieval": {"queries_per_check": 0},
        }
        valid, errs = ce.validate_config(invalid)
        assert valid, f"0 should be valid (provider default): {errs}"


class TestMoatAffecting:
    """is_moat_affecting() must detect changes to hard gates, thresholds, operator routing."""

    def test_same_config_is_not_moat_affecting(self):
        cfg = {"hard_gates": [], "thresholds": {"confidence_floor": 0.6}}
        assert not ce.is_moat_affecting(cfg, cfg)

    def test_changing_confidence_floor_is_moat_affecting(self):
        old = {"thresholds": {"confidence_floor": 0.6}}
        new = {"thresholds": {"confidence_floor": 0.8}}
        assert ce.is_moat_affecting(old, new)

    def test_changing_hard_gates_is_moat_affecting(self):
        old = {"hard_gates": [{"pain_reality": ["refuted"]}]}
        new = {"hard_gates": [{"value_durability": ["refuted"]}]}
        assert ce.is_moat_affecting(old, new)

    def test_changing_operator_is_moat_affecting(self):
        old = {"operator": "gemini_cli"}
        new = {"operator": "claude"}
        assert ce.is_moat_affecting(old, new)

    def test_changing_spend_guard_is_not_moat_affecting(self):
        old = {"spend": {"daily_cap_usd": 50.0}}
        new = {"spend": {"daily_cap_usd": 100.0}}
        assert not ce.is_moat_affecting(old, new)

    def test_changing_weights_is_not_moat_affecting(self):
        old = {"weights": {"pain_acuity": 0.2, "distribution": 0.15}}
        new = {"weights": {"pain_acuity": 0.5, "distribution": 0.1}}
        assert not ce.is_moat_affecting(old, new)


class TestDiff:
    """diff_configs() must show changes between old and new configs."""

    def test_no_diff_for_identical_configs(self):
        cfg = {"thresholds": {"confidence_floor": 0.6}}
        assert ce.diff_configs(cfg, cfg) == ""

    def test_detects_threshold_change(self):
        old = {"thresholds": {"confidence_floor": 0.6}}
        new = {"thresholds": {"confidence_floor": 0.8}}
        diff = ce.diff_configs(old, new)
        assert "confidence_floor" in diff
        assert "0.6" in diff
        assert "0.8" in diff

    def test_detects_nested_change(self):
        old = {"spend": {"daily_cap_usd": 50.0}}
        new = {"spend": {"daily_cap_usd": 100.0}}
        diff = ce.diff_configs(old, new)
        assert "daily_cap_usd" in diff
        assert "50.0" in diff or "50" in diff

    def test_unchanged_keys_are_not_in_diff(self):
        old = {"thresholds": {"confidence_floor": 0.6}, "operator": "gemini"}
        new = {"thresholds": {"confidence_floor": 0.6}, "operator": "claude"}
        diff = ce.diff_configs(old, new)
        assert "confidence_floor" not in diff
        assert "operator" in diff


class TestMtimeConflict:
    """mtime_conflict() must detect external edits while editing."""

    def test_no_conflict_when_file_hasnt_changed(self):
        raw = ce.load_config_raw()
        current_mtime = ce.get_config_mtime()
        assert not ce.mtime_conflict(current_mtime)

    def test_detects_conflict_when_file_modified_since_load(self, tmp_path):
        # Touch a temp file to simulate the scenario
        fake = tmp_path / "config.yaml"
        fake.write_text("thresholds:\n  confidence_floor: 0.6\n")
        old_mtime = fake.stat().st_mtime
        # Modify the file after the "load"
        time.sleep(0.05)
        fake.write_text("thresholds:\n  confidence_floor: 0.8\n")
        new_mtime = fake.stat().st_mtime
        assert new_mtime > old_mtime
        # Monkeypatch get_config_mtime for this test
        import prospector.control_center.config_editor as _ce
        import prospector.control_center.config_editor as _ce_module
        orig_path = _ce_module.CONFIG_PATH
        try:
            _ce_module.CONFIG_PATH = fake
            assert _ce.mtime_conflict(old_mtime)
        finally:
            _ce_module.CONFIG_PATH = orig_path


class TestWriteConfig:
    """write_config() must create a backup before overwriting and validate first."""

    def test_write_config_refuses_on_mtime_conflict(self, tmp_path):
        fake = tmp_path / "config.yaml"
        fake.write_text("key: value\n")
        import prospector.control_center.config_editor as _ce_module
        orig_path = _ce_module.CONFIG_PATH
        try:
            _ce_module.CONFIG_PATH = fake
            # Write something, then modify underneath, then try to save
            _ce_module.CONFIG_PATH.write_text("key: value\n")
            first_mtime = _ce_module.CONFIG_PATH.stat().st_mtime
            time.sleep(0.05)
            # External edit happens
            _ce_module.CONFIG_PATH.write_text("key: externally_modified\n")
            ok, msg = _ce_module.write_config(
                {"key": "new_value"}, moat_affecting=False, orig_mtime=first_mtime
            )
            assert not ok
            assert "externally" in msg.lower() or "modified" in msg.lower()
        finally:
            _ce_module.CONFIG_PATH = orig_path

    def test_write_config_refuses_on_validation_failure(self, tmp_path):
        fake_cfg = tmp_path / "config.yaml"
        fake_cfg.write_text("key: value\n")
        fake_cc = tmp_path / "cc"
        fake_cc.mkdir()
        fake_backup = tmp_path / "backups"
        fake_backup.mkdir()
        import prospector.control_center.config_editor as _ce_module
        orig_path = _ce_module.CONFIG_PATH
        orig_cc = _ce_module._CC_DIR
        orig_backup = _ce_module._BACKUP_DIR
        try:
            _ce_module.CONFIG_PATH = fake_cfg
            _ce_module._CC_DIR = fake_cc
            _ce_module._BACKUP_DIR = fake_backup
            # Pass the actual mtime so no conflict is detected
            ok, msg = _ce_module.write_config(
                {"thresholds": {}, "weights": {"x": -1.0}},
                moat_affecting=False,
                orig_mtime=fake_cfg.stat().st_mtime,
            )
            assert not ok
            assert "validation" in msg.lower(), f"Expected validation error, got: {msg}"
        finally:
            _ce_module.CONFIG_PATH = orig_path
            _ce_module._CC_DIR = orig_cc
            _ce_module._BACKUP_DIR = orig_backup

    def test_write_config_creates_backup(self, tmp_path):
        fake_cfg = tmp_path / "config.yaml"
        fake_cfg.write_text("key: original\n")
        fake_cc = tmp_path / "cc"
        fake_cc.mkdir()
        fake_backup = tmp_path / "backups"
        fake_backup.mkdir()
        import prospector.control_center.config_editor as _ce_module
        orig_path = _ce_module.CONFIG_PATH
        orig_cc = _ce_module._CC_DIR
        orig_backup = _ce_module._BACKUP_DIR
        try:
            _ce_module.CONFIG_PATH = fake_cfg
            _ce_module._CC_DIR = fake_cc
            _ce_module._BACKUP_DIR = fake_backup
            ok, msg = _ce_module.write_config(
                {"key": "modified"}, moat_affecting=False,
                orig_mtime=fake_cfg.stat().st_mtime,
            )
            assert ok, f"write_config should succeed: {msg}"
            backups = list(fake_backup.glob("config.yaml.bak.*"))
            assert len(backups) >= 1, f"Expected at least 1 backup, got {len(backups)}"
        finally:
            _ce_module.CONFIG_PATH = orig_path
            _ce_module._CC_DIR = orig_cc
            _ce_module._BACKUP_DIR = orig_backup


class TestCertification:
    """Certification state is written/read correctly."""

    def test_load_certification_returns_certified_false_when_no_file(self, tmp_path):
        fake_cert = tmp_path / "nonexistent.json"
        import prospector.control_center.config_editor as _ce_module
        orig = _ce_module._CERT_PATH
        try:
            _ce_module._CERT_PATH = fake_cert
            cert = _ce_module.load_certification()
            assert cert == {"certified": False}
        finally:
            _ce_module._CERT_PATH = orig

    def test_certify_from_golden_marks_certified(self, tmp_path):
        cert_file = tmp_path / "cert.json"
        import prospector.control_center.config_editor as _ce_module
        orig_cert = _ce_module._CERT_PATH
        orig_cc = _ce_module._CC_DIR
        try:
            _ce_module._CERT_PATH = cert_file
            _ce_module._CC_DIR = tmp_path
            _ce_module.certify_from_golden(
                golden_run_id="run_001",
                operator="mock",
                discrimination=0.85,
                floor=0.75,
                passed=True,
            )
            cert = _ce_module.load_certification()
            assert cert.get("certified") is True
            assert cert.get("golden_run") == "run_001"
        finally:
            _ce_module._CERT_PATH = orig_cert
            _ce_module._CC_DIR = orig_cc

    def test_certify_from_golden_does_not_certify_on_failure(self, tmp_path):
        cert_file = tmp_path / "cert2.json"
        import prospector.control_center.config_editor as _ce_module
        orig_cert = _ce_module._CERT_PATH
        orig_cc = _ce_module._CC_DIR
        try:
            _ce_module._CERT_PATH = cert_file
            _ce_module._CC_DIR = tmp_path
            _ce_module.certify_from_golden(
                golden_run_id="run_002",
                operator="mock",
                discrimination=0.5,
                floor=0.75,
                passed=False,
            )
            cert = _ce_module.load_certification()
            # Should NOT create a certified=true entry on failure
            assert cert.get("certified") is not True
        finally:
            _ce_module._CERT_PATH = orig_cert
            _ce_module._CC_DIR = orig_cc


class TestBackups:
    """Backup listing and restore."""

    def test_list_backups_empty_when_no_backups(self, tmp_path):
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        import prospector.control_center.config_editor as _ce_module
        orig = _ce_module._BACKUP_DIR
        try:
            _ce_module._BACKUP_DIR = backup_dir
            backups = _ce_module.list_backups()
            assert backups == []
        finally:
            _ce_module._BACKUP_DIR = orig

    def test_restore_backup_roundtrips_config(self, tmp_path):
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        fake_cfg = tmp_path / "config.yaml"
        fake_cfg.write_text("key: original\n")
        import prospector.control_center.config_editor as _ce_module
        orig_cfg = _ce_module.CONFIG_PATH
        orig_backup = _ce_module._BACKUP_DIR
        try:
            _ce_module.CONFIG_PATH = fake_cfg
            _ce_module._BACKUP_DIR = backup_dir
            bak = backup_dir / "config.yaml.bak.test001"
            bak.write_text("key: backup_value\n")
            ok, msg = _ce_module.restore_backup("config.yaml.bak.test001")
            assert ok
            assert fake_cfg.read_text() == "key: backup_value\n"
        finally:
            _ce_module.CONFIG_PATH = orig_cfg
            _ce_module._BACKUP_DIR = orig_backup
