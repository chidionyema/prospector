"""Safe config.yaml editing utilities for the Control Center.

Implements the three safety guarantees from CONTROL_CENTER_SPEC.md §3.5:
  1. Edits are staged in session_state, written on Save only.
  2. A diff view is shown before any write.
  3. Moat-affecting edits are flagged uncertified and require golden re-run.

Also provides mtime-conflict detection for concurrent external edits (§2.3 edge
case E6) and a formal config schema (G4).
"""
from __future__ import annotations

import hashlib
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from prospector import paths

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

# Resolved per call, never bound at import — see prospector/paths.py for why, and note this
# module is where the class did live damage. `_CONFIG_HISTORY` used to be computed at import
# from `_CC_DIR`, so a test that redirected `_CC_DIR` moved the backups and left the history
# pointing at production. It did: `store/control_center/config_history.jsonl` on this branch
# carries rows whose backup path is
#   /private/var/.../pytest-of-chidionyema/pytest-4835/test_write_config_creates_back0/backups/
# The fence was applied and the file was written anyway, because a derived constant does not
# follow the thing it was derived from. Deriving inside the accessor is what makes it follow.
#
# The module-level names survive as OVERRIDES. `None` means "resolve now"; assigning a Path
# pins it, which is the contract tests/control_center/test_config_editor.py already uses
# (`orig = _ce_module._CC_DIR` … restore in `finally`).
CONFIG_PATH: Path | None = None
_BACKUP_DIR: Path | None = None
_CC_DIR: Path | None = None
_CERT_PATH: Path | None = None
_CONFIG_HISTORY: Path | None = None


def _config_path() -> Path:
    return CONFIG_PATH or paths.repo_path("config.yaml")


def _cc_dir() -> Path:
    return _CC_DIR or paths.store_path("control_center")


def _backup_dir() -> Path:
    return _BACKUP_DIR or _cc_dir() / "backups"


def _cert_path() -> Path:
    return _CERT_PATH or _cc_dir() / "certification.json"


def _config_history() -> Path:
    return _CONFIG_HISTORY or _cc_dir() / "config_history.jsonl"


# ---------------------------------------------------------------------------
# Config loader (always reads from disk)
# ---------------------------------------------------------------------------

def _read_config_raw() -> tuple[dict[str, Any], bool]:
    """(cfg, ok). ``ok=False`` means config.yaml is on disk and could not be parsed.

    The editor stages whatever this returns and offers to SAVE it back
    (pages/_parameters.py:28 → :365), so a swallowed parse error stages an empty config and
    the next Save writes `{}` over the engine's entire configuration. `write_config` refuses
    that; this is the half that lets it tell.
    """
    if not _config_path().exists():
        return {}, True
    try:
        with open(_config_path(), encoding="utf-8") as f:
            return (yaml.safe_load(f) or {}), True
    except (yaml.YAMLError, OSError) as exc:
        logger.error("control_center: %s unparseable (%s: %s)",
                     _config_path(), type(exc).__name__, exc)
        return {}, False


def load_config_raw() -> dict[str, Any]:
    """Load config.yaml as a raw dict (never cached). ``{}`` may mean unreadable."""
    return _read_config_raw()[0]


def config_hash(cfg: dict[str, Any]) -> str:
    """Stable hash of the config dict for certification tracking."""
    return hashlib.sha1(
        yaml.safe_dump(cfg, sort_keys=True).encode()
    ).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Mtime conflict detection
# ---------------------------------------------------------------------------

def get_config_mtime() -> float:
    """Return the on-disk mtime of config.yaml."""
    return _config_path().stat().st_mtime if _config_path().exists() else 0.0


def mtime_conflict(orig_mtime: float) -> bool:
    """Return True if config.yaml has been modified since orig_mtime."""
    return _config_path().exists() and _config_path().stat().st_mtime > orig_mtime


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------

def diff_configs(old: dict[str, Any], new: dict[str, Any]) -> str:
    """Return a human-readable YAML-style diff old→new."""
    lines = []
    for key in sorted(set(old.keys()) | set(new.keys())):
        v_old = old.get(key)
        v_new = new.get(key)
        if v_old == v_new:
            continue
        if isinstance(v_old, dict) and isinstance(v_new, dict):
            sub = _diff_nested(v_old, v_new, prefix=f"  {key}.")
            if sub:
                lines.append(f"  {key}:")
                lines.append(sub)
        else:
            lines.append(f"  {key}:")
            lines.append(f"    - {repr(v_old)}")
            lines.append(f"    + {repr(v_new)}")
    return "\n".join(lines) if lines else ""


def _diff_nested(old: dict, new: dict, prefix: str = "") -> str:
    lines = []
    for k in sorted(set(old.keys()) | set(new.keys())):
        v_old, v_new = old.get(k), new.get(k)
        if v_old == v_new:
            continue
        if isinstance(v_old, dict) and isinstance(v_new, dict):
            sub = _diff_nested(v_old, v_new, prefix=f"{prefix}{k}.")
            if sub:
                lines.append(f"{prefix}{k}:")
                lines.append(sub)
        else:
            lines.append(f"{prefix}{k}:  - {repr(v_old)}  + {repr(v_new)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Moat-affecting key set
# ---------------------------------------------------------------------------

MOAT_AFFECTING_KEYS: set[tuple[str, ...]] = {
    # Top-level moat gates
    ("hard_gates",),
    ("adversarial_decisive",),
    # Thresholds
    ("thresholds", "confidence_floor"),
    ("thresholds", "min_composite_to_pass"),
    # Operator routing into the moat
    ("operator",),
    ("moat_order",),
    ("retrieval", "provider"),
    # Adversarial settings
    ("adversarial",),
    # Lane-specific moat overrides
    ("lanes",),  # any lane-level gate/threshold change
}


def is_moat_affecting(old: dict[str, Any], new: dict[str, Any]) -> bool:
    """Return True if the diff between old and new touches any moat-affecting key."""
    changed_keys = _changed_keys(old, new)
    for key_tuple in changed_keys:
        for moat_tuple in MOAT_AFFECTING_KEYS:
            if len(key_tuple) >= len(moat_tuple) and key_tuple[:len(moat_tuple)] == moat_tuple:
                return True
    return False


def _changed_keys(old: dict, new: dict, prefix: tuple = ()) -> set[tuple]:
    """Return the set of changed key paths."""
    changed: set[tuple] = set()
    all_keys = set(old.keys()) | set(new.keys())
    for k in all_keys:
        v_old, v_new = old.get(k), new.get(k)
        path = prefix + (k,)
        if v_old == v_new:
            continue
        if isinstance(v_old, dict) and isinstance(v_new, dict):
            changed |= _changed_keys(v_old, v_new, path)
        else:
            changed.add(path)
    return changed


# ---------------------------------------------------------------------------
# Schema validation (G4 — formal config schema)
# ---------------------------------------------------------------------------

def validate_config(cfg: dict[str, Any]) -> tuple[bool, list[str]]:
    """Validate a config dict against the schema.

    Returns (ok, list_of_error_messages). list is empty iff ok=True.
    """
    errors: list[str] = []

    # ── Thresholds ─────────────────────────────────────────────────────────
    thresh = cfg.get("thresholds", {})
    conf = thresh.get("confidence_floor")
    if conf is not None and not (0.0 <= conf <= 1.0):
        errors.append("thresholds.confidence_floor must be in [0.0, 1.0]")

    min_comp = thresh.get("min_composite_to_pass")
    if min_comp is not None and not (0.0 <= min_comp <= 20.0):
        errors.append("thresholds.min_composite_to_pass must be in [0.0, 20.0]")

    # ── Weights ─────────────────────────────────────────────────────────────
    weights = cfg.get("weights", {})
    weight_vals = [v for v in weights.values() if isinstance(v, (int, float))]
    if weight_vals:
        total = sum(weight_vals)
        if abs(total - 1.0) > 0.005:
            errors.append(f"Weights must sum to 1.0, got {total:.4f}")
        for k, v in weights.items():
            if not isinstance(v, (int, float)) or v < 0 or v > 1:
                errors.append(f"Weight '{k}' must be a number in [0.0, 1.0]")

    # ── Hard gates ─────────────────────────────────────────────────────────
    gates = cfg.get("hard_gates", [])
    if not isinstance(gates, list):
        errors.append("hard_gates must be a list")
    else:
        for g in gates:
            if not isinstance(g, dict):
                errors.append("Each hard_gate entry must be a dict")

    # ── Lanes ──────────────────────────────────────────────────────────────
    lanes = cfg.get("lanes", {})
    if not isinstance(lanes, dict):
        errors.append("lanes must be a dict")
    else:
        for lane_name, lane_cfg in lanes.items():
            if not isinstance(lane_cfg, dict):
                errors.append(f"lanes['{lane_name}'] must be a dict")
                continue
            lg = lane_cfg.get("hard_gates")
            if lg is not None and not isinstance(lg, list):
                errors.append(f"lanes['{lane_name}'].hard_gates must be a list")

    # ── Spend guard ─────────────────────────────────────────────────────────
    spend = cfg.get("spend", {})
    daily_cap = spend.get("daily_cap_usd")
    if daily_cap is not None and (not isinstance(daily_cap, (int, float)) or daily_cap < 0):
        errors.append("spend.daily_cap_usd must be a non-negative number")
    warn_at = spend.get("warn_at_usd")
    if warn_at is not None and (not isinstance(warn_at, (int, float)) or warn_at < 0):
        errors.append("spend.warn_at_usd must be a non-negative number")

    # ── Retrieval ──────────────────────────────────────────────────────────
    retr = cfg.get("retrieval", {})
    qpc = retr.get("queries_per_check")
    if qpc is not None and (not isinstance(qpc, int) or qpc < 0):
        errors.append("retrieval.queries_per_check must be a non-negative integer")
    rpq = retr.get("results_per_query")
    if rpq is not None and (not isinstance(rpq, int) or rpq < 1):
        errors.append("retrieval.results_per_query must be an integer ≥ 1")

    return (len(errors) == 0, errors)


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def write_config(new_cfg: dict[str, Any], moat_affecting: bool,
                orig_mtime: float = 0.0) -> tuple[bool, str]:
    """Write new config.yaml with a timestamped backup.

    Returns (success, message). On mtime conflict, refuses to overwrite.
    On mtime-OK: writes .bak.{ts}, validates, then writes config.yaml.
    If moat_affecting=True, marks the config as uncertified.
    """
    # ── Mtime conflict check ────────────────────────────────────────────────
    if mtime_conflict(orig_mtime):
        return False, ("config.yaml was modified externally while editing. "
                       "Your staged changes were based on an older version. "
                       "Reload and re-apply your changes.")

    # ── Never write a config that came from a failed read ───────────────────
    # `load_config_raw` degrades to `{}` (it must — a Streamlit page that raises is a dead
    # page), and the editor stages that `{}` as if the operator had emptied the file. Two
    # fences, because either one alone leaves the wipe reachable: nothing empty is writable,
    # and nothing is written on top of a config we could not read in the first place.
    if not isinstance(new_cfg, dict) or not new_cfg:
        return False, ("Refusing to write an empty config.yaml — this is what a failed "
                       "read looks like, not a configuration.")
    _, readable = _read_config_raw()
    if not readable:
        return False, ("config.yaml on disk cannot be parsed, so the staged config was not "
                       "built from it. Fix or restore the file before saving.")

    # ── Backup ─────────────────────────────────────────────────────────────
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    _backup_dir().mkdir(parents=True, exist_ok=True)
    bak = _backup_dir() / f"config.yaml.bak.{ts}"
    shutil.copy2(_config_path(), bak)

    # ── Validate ─────────────────────────────────────────────────────────────
    ok, errs = validate_config(new_cfg)
    if not ok:
        return False, "Config validation failed:\n" + "\n".join(f"  - {e}" for e in errs)

    # ── Write ─────────────────────────────────────────────────────────────
    try:
        with open(_config_path(), "w", encoding="utf-8") as f:
            yaml.safe_dump(new_cfg, f, default_flow_style=False, sort_keys=False)
    except OSError as e:
        return False, f"Could not write config.yaml: {e}"

    # ── Log history ─────────────────────────────────────────────────────────
    _cc_dir().mkdir(parents=True, exist_ok=True)
    from prospector.control_center import readers as _r
    _r.load_config_dict.clear()
    _r.load_config_typed.clear()
    _r.config_load_error.clear()

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "hash": config_hash(new_cfg),
        "moat_affecting": moat_affecting,
        "backup": str(bak),
    }
    try:
        with open(_config_history(), "a", encoding="utf-8") as f:
            f.write(yaml.safe_dump(entry, default_flow_style=False))
    except OSError:
        pass

    # ── Certification ────────────────────────────────────────────────────────
    if moat_affecting:
        _write_certification(certified=False,
                           reason="moat-affecting change",
                           config_hash=config_hash(new_cfg))
        # Invalidate cert cache
        _r.load_certification.clear()
    else:
        # Mark certified only if golden set has passed with this hash
        cert = load_certification()
        if cert.get("certified"):
            _write_certification(
                certified=True,
                config_hash=config_hash(new_cfg),
                certified_by=cert.get("certified_by", ""),
                golden_run=cert.get("golden_run", ""),
            )
        _r.load_certification.clear()

    return True, f"Config saved → {_config_path()} (backup: {bak.name})"


# ---------------------------------------------------------------------------
# Certification state
# ---------------------------------------------------------------------------

def load_certification() -> dict[str, Any]:
    """Load the certification state from store/control_center/certification.json."""
    if not _cert_path().exists():
        return {"certified": False}
    try:
        return yaml.safe_load(_cert_path().read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError):
        return {"certified": False}


def _write_certification(certified: bool, reason: str = "",
                        config_hash: str = "", certified_by: str = "",
                        golden_run: str = "") -> None:
    """Write the certification state file."""
    _cc_dir().mkdir(parents=True, exist_ok=True)
    cert = {
        "certified": certified,
        "config_hash": config_hash,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    if reason:
        cert["reason"] = reason
    if certified_by:
        cert["certified_by"] = certified_by
    if golden_run:
        cert["golden_run"] = golden_run

    with open(_cert_path(), "w", encoding="utf-8") as f:
        yaml.safe_dump(cert, f, default_flow_style=False)


def certify_from_golden(golden_run_id: str, operator: str,
                        discrimination: float, floor: float,
                        passed: bool) -> None:
    """Called after a golden promotion run to update certification state."""
    from prospector.control_center import readers as _r
    if passed:
        cfg = load_config_raw()
        _write_certification(
            certified=True,
            config_hash=config_hash(cfg),
            certified_by=operator,
            golden_run=golden_run_id,
        )
        _r.load_certification.clear()
    # If !passed: leave cert as-is (uncertified or the last passing state)


# ---------------------------------------------------------------------------
# Backup management
# ---------------------------------------------------------------------------

def list_backups() -> list[dict[str, Any]]:
    """List available timestamped config backups."""
    if not _backup_dir().exists():
        return []
    backups = []
    for p in sorted(_backup_dir().glob("config.yaml.bak.*"), reverse=True):
        backups.append({
            "filename": p.name,
            "mtime": p.stat().st_mtime,
            "size": p.stat().st_size,
        })
    return backups


def restore_backup(filename: str) -> tuple[bool, str]:
    """Restore config.yaml from a backup file."""
    bak = _backup_dir() / filename
    if not bak.exists():
        return False, f"Backup not found: {filename}"
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    safety_bak = _config_path().with_suffix(".yaml.bak.restore." + ts)
    shutil.copy2(_config_path(), safety_bak)
    shutil.copy2(bak, _config_path())
    from prospector.control_center import readers as _r
    _r.load_config_dict.clear()
    _r.load_config_typed.clear()
    _r.config_load_error.clear()
    return True, f"Restored from {filename} (safety backup: {safety_bak.name})"
