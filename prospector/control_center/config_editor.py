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
import json
import logging
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from prospector import models as _models
from prospector import paths
from prospector.control_center import yaml_surgery as _surgery

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


def read_history(limit: int = 100) -> list[dict[str, Any]]:
    """Every recorded save, newest last — JSON lines AND the legacy four-line YAML blocks.

    233 of the existing records were written as YAML into a file named `.jsonl` (T0-5). They are
    real history and are not being rewritten, so the reader accepts both: a line that parses as
    JSON is a record; anything else accumulates until it parses as a YAML mapping. A reader that
    only handled the new format would report the estate's own change log as empty.
    """
    path = _config_history()
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    block: list[str] = []

    def _flush() -> None:
        if not block:
            return
        try:
            parsed = yaml.safe_load("".join(block))
            if isinstance(parsed, dict):
                out.append(parsed)
        except yaml.YAMLError:
            pass
        block.clear()

    try:
        for line in path.read_text(encoding="utf-8").splitlines(keepends=True):
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
                _flush()
                if isinstance(parsed, dict):
                    out.append(parsed)
                continue
            except json.JSONDecodeError:
                pass
            if block and re.match(r"^\S", line) and line.split(":", 1)[0] in {
                    k.split(":", 1)[0] for k in block}:
                _flush()      # a repeated top-level key means the previous block ended
            block.append(line)
        _flush()
    except OSError:
        return out
    return out[-limit:]


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

# KEYED TO KEYS THAT EXIST (T0-6). The previous set named `moat_order`, `adversarial_decisive`
# and `adversarial` as TOP-LEVEL paths; none of the three is a top-level key in config.yaml, so
# the fence was pointed at nothing and fired 0 times in 233 recorded saves. Meanwhile the keys
# that actually decide what may be SOLD were uncovered. Every entry below was verified present
# on disk before being added — a fence keyed to an absent path reads as protection and is inert.
MOAT_AFFECTING_KEYS: set[tuple[str, ...]] = {
    ("hard_gates",),                 # config.yaml:474 — the kill filter itself
    ("moat_primary",),               # :81  — which brains may rule FINALLY, i.e. what publishes
    ("operator",),                   # :58  — the verdict chain
    ("noncritical_operator",),       # :70  — never rules, but generates what gets ruled on
    ("thresholds",),                 # :460 — confidence_floor / min_composite_to_pass
    ("weights",),                    # :504 — the composite every PASS is scored against
    ("lanes",),                      # per-lane gate and threshold overrides
    ("admissibility",),              # what is allowed to be generated at all
    ("retrieval", "provider"),       # the grounding chain a verdict is retrieved through
    ("listing", "pricing"),          # :1555 — every price the buyer sees
    ("schedule",),                   # cadence, batch size, backlog cap, market rotation
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
    # THE KEYS ARE THE POINT (T0-1). "list, of dicts" waved through
    # `[{"k": True}, {"k": True}, ...]` — six gates whose names had been replaced by the literal
    # string "k", so not one of them matched a check name and the kill filter that decides what
    # may be sold silently stopped firing. A shape check that cannot tell that from the real
    # value is not validating the thing that matters.
    gates = cfg.get("hard_gates", [])
    known = set(_models.DEFAULT_CHECKS) | {"adversarial_decisive"}
    if not isinstance(gates, list):
        errors.append("hard_gates must be a list")
    else:
        for g in gates:
            if not isinstance(g, dict) or len(g) != 1:
                errors.append("Each hard_gate entry must be a single-key dict "
                              "(e.g. {legality: [refuted]})")
                continue
            (name, verdicts), = g.items()
            if name not in known:
                errors.append(
                    f"hard_gate '{name}' is not a check name — the gate would never fire. "
                    f"Known: {', '.join(sorted(known))}")
            elif name != "adversarial_decisive" and not (
                    isinstance(verdicts, list) and verdicts):
                errors.append(f"hard_gate '{name}' must list the verdicts that fail it, "
                              f"e.g. [refuted] — got {verdicts!r}")

    # ── Operator chains (T0-2) ─────────────────────────────────────────────
    # An empty or unbuildable chain is not a configuration; it is what a broken widget stages.
    # The engine fails LOUDLY on it at startup (`_build_operator` raises), which means the
    # damage lands on the daemon's next re-exec rather than on the person who clicked Save.
    from prospector.operator import BUILDABLE_TIERS
    for field in ("operator", "noncritical_operator", "artifact_operator", "moat_primary"):
        if field not in cfg:
            continue
        raw = cfg[field]
        chain = [raw] if isinstance(raw, str) else list(raw or [])
        if not chain or any(not str(t).strip() for t in chain):
            errors.append(f"{field} must name at least one operator tier (got {raw!r}) — "
                          "an empty chain is what a broken save looks like, not a setting")
            continue
        unknown = [t for t in chain if t not in BUILDABLE_TIERS]
        if unknown:
            errors.append(f"{field} names {unknown}, which no adapter can build. "
                          f"Buildable: {', '.join(BUILDABLE_TIERS)}")

    # ── The verdict roster (R20) ───────────────────────────────────────────
    # ONE fence, called from here and from `prospector.ops.routing.set_moat_primary`, so the
    # Streamlit save, the CLI and the Telegram tap refuse the same rosters. Imported inside the
    # function because `ops.routing` imports this module for the writer.
    if "moat_primary" in cfg or "operator" in cfg:
        from prospector.ops.routing import routing_problems

        problems = routing_problems(cfg.get("operator"), cfg.get("moat_primary"))
        # A FENCE CATCHES WHAT THE WRITE INTRODUCES. Judged against the whole incoming config,
        # a roster gap that was ALREADY on disk blocks every unrelated edit — an operator could
        # not move `confidence_floor` until they had first fixed a roster this write does not
        # touch, and the pause/threshold controls go down with it. So subtract the problems the
        # config on disk already has: a write that leaves the roster no worse is not the write
        # that broke it. `set_moat_primary` still applies the UNFILTERED fence (routing.py:198),
        # which is the path that actually changes the roster.
        try:
            current = load_config_raw()
        except Exception:  # noqa: BLE001
            # swallow-ok: unreadable on-disk config means we subtract NOTHING and the full fence
            # applies — the strict direction. The read itself is diagnosed by the mtime/parse
            # fences in `write_config`, which refuse the write outright.
            current = {}
        if current:
            already = set(routing_problems(current.get("operator"),
                                           current.get("moat_primary")))
            problems = [p for p in problems if p not in already]
        errors.extend(problems)

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

    # ── Write, SURGICALLY (T0-3) ───────────────────────────────────────────
    # `yaml.safe_dump` used to write this file. Measured: 2034 lines in, 981 out, 1173 comment
    # lines destroyed — the estate's entire calibration record, including a revenue decision
    # parked in a comment. The console re-serialising a hand-annotated config is the defect;
    # editing only the lines whose values changed is the fix. Anything the surgeon cannot place
    # is REFUSED here rather than serialised, because a save an operator can retry beats a write
    # that silently eats 1,173 lines of why.
    try:
        original_text = _config_path().read_text(encoding="utf-8")
    except OSError as e:
        return False, f"Could not read config.yaml before writing: {e}"

    edited, problems = _surgery.rewrite(original_text, _read_config_raw()[0], new_cfg)
    if problems:
        return False, ("Refusing to save — these changes cannot be made without re-serialising "
                       "config.yaml, which would destroy its comments:\n"
                       + "\n".join(f"  - {p}" for p in problems)
                       + "\nEdit config.yaml directly for these, or narrow the change.")
    try:
        _config_path().write_text(edited, encoding="utf-8")
    except OSError as e:
        return False, f"Could not write config.yaml: {e}"

    # ── Log history ─────────────────────────────────────────────────────────
    _cc_dir().mkdir(parents=True, exist_ok=True)
    # CACHE INVALIDATION MUST NOT DECIDE WHETHER THE WRITE SUCCEEDED. `readers` imports
    # streamlit; this writer is now also reached headlessly (`python -m prospector.ops.routing`,
    # and through it the Telegram surface). A hard import here would raise AFTER config.yaml had
    # already been rewritten, reporting failure for a write that happened — the worst possible
    # answer for an actuator. There is no Streamlit cache to clear in that process anyway.
    try:
        from prospector.control_center import readers as _r
        _r.load_config_dict.clear()
        _r.load_config_typed.clear()
        _r.config_load_error.clear()
    except (ImportError, AttributeError):
        # Exactly the two conditions the comment above describes: no streamlit in this
        # process, or a reader without a cache to clear. Neither is a failed write.
        _r = None

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "hash": config_hash(new_cfg),
        "moat_affecting": moat_affecting,
        "backup": str(bak),
    }
    # ONE JSON OBJECT PER LINE (T0-5). This file is named `.jsonl` and was written as four-line
    # YAML blocks — 932 lines / 233 records, every one of which fails a JSONL reader on line 1.
    # A recon pass this session read it and reported the file "malformed", which is what an audit
    # surface would do too. Legacy YAML records stay on disk; `read_history` tolerates both.
    try:
        with open(_config_history(), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, sort_keys=True) + "\n")
    except OSError:
        pass

    # ── Certification ────────────────────────────────────────────────────────
    if moat_affecting:
        _write_certification(certified=False,
                           reason="moat-affecting change",
                           config_hash=config_hash(new_cfg))
        # Invalidate cert cache (absent in a headless caller — see the import above)
        if _r is not None:
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
        if _r is not None:
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
