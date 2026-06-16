"""Read-only data loaders for the Control Center.

All functions are cached (st.cache_data) and gracefully degrade on missing/corrupt
artifacts. No model calls, no side effects.

Sources of truth (never recomputed):
  - store/prospector.db        (SQLite index of dossiers)
  - store/dossiers/<id>.<dec>.json  (full dossier JSON)
  - store/prospector.jsonl      (audit log)
  - store/provider_health.json  (circuit state)
  - store/golden_runs/*.json    (discrimination trend)
  - store/control_center/jobs.json  (job history)
  - store/control_center/certification.json (config certification state)
  - signals/pending/*.json       (generation backlog)
  - config.yaml                 (engine parameters)
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import streamlit as st

from prospector.config import load_config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _jsonl_lines(path: Path) -> list[dict]:
    """Parse a JSONL file, returning a list of parsed dicts (empty on error)."""
    if not path.exists():
        return []
    results = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                results.append(json.loads(line))
            except (json.JSONDecodeError, ValueError):
                pass
    except (OSError, UnicodeDecodeError):
        pass
    return results


def _control_center_dir() -> Path:
    """Get or create the control_center store dir."""
    d = Path("store/control_center")
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@st.cache_data(ttl=10)
def load_config_typed():
    """Load the engine Config object."""
    try:
        return load_config()
    except Exception:
        return None


@st.cache_data(ttl=10)
def load_config_dict() -> dict[str, Any]:
    """Load config.yaml as a raw dict (for the editor)."""
    import yaml
    try:
        with open("config.yaml", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Catalogue (SQLite index)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=10)
def catalogue_index(decision: Optional[str] = None) -> list[dict[str, Any]]:
    """All dossier rows from the SQLite index.

    Returns list of dicts with keys: candidate_id, title, one_liner, decision,
    gate_fired, composite, created_at, reverify_due_at, path, ambition_tier,
    structural_form, provisional, dense_reward, adversarial_confidence.
    """
    db_path = Path("store/prospector.db")
    if not db_path.exists():
        return []

    conn = sqlite3.connect(str(db_path), timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            "SELECT * FROM dossiers" +
            (" WHERE decision = ?" if decision else "") +
            " ORDER BY created_at DESC",
            (decision,) if decision else (),
        )
        rows = [dict(r) for r in cur.fetchall()]
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    return rows


@st.cache_data(ttl=10)
def catalogue_stats() -> dict[str, Any]:
    """Aggregate counts for the Overview KPI strip."""
    rows = catalogue_index()
    if not rows:
        return {"total": 0, "n_pass": 0, "n_kill": 0, "n_defer": 0, "n_provisional": 0}
    n = len(rows)
    dec = {k: sum(1 for r in rows if (r.get("decision") or "").lower() == k)
           for k in ("pass", "kill", "defer")}
    prov = sum(1 for r in rows if r.get("provisional"))
    return {**dec, "n_pass": dec["pass"], "n_kill": dec["kill"],
            "n_defer": dec["defer"], "n_provisional": prov, "total": n}


# ---------------------------------------------------------------------------
# Dossier JSON
# ---------------------------------------------------------------------------

@st.cache_data(ttl=10)
def load_dossier(candidate_id: str, decision: str) -> Optional[dict[str, Any]]:
    """Load a full dossier JSON from store/dossiers/<id>.<decision>.json."""
    path = Path(f"store/dossiers/{candidate_id}.{decision.lower()}.json")
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


@st.cache_data(ttl=10)
def load_listing(candidate_id: str) -> Optional[dict[str, Any]]:
    """Load a listing JSON if one exists for this candidate."""
    path = Path(f"store/listings/{candidate_id}.json")
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


# ---------------------------------------------------------------------------
# Pending signals
# ---------------------------------------------------------------------------

@st.cache_data(ttl=5)
def load_pending_signals() -> list[dict[str, Any]]:
    """Load all pending signals from signals/pending/*.json."""
    pending_dir = Path("signals/pending")
    if not pending_dir.exists():
        return []
    results = []
    for p in sorted(pending_dir.glob("*.json")):
        try:
            results.append({**json.loads(p.read_text(encoding="utf-8")),
                           "_path": str(p), "_filename": p.name})
        except (json.JSONDecodeError, OSError):
            pass
    return results


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

@st.cache_data(ttl=5)
def load_jobs() -> list[dict[str, Any]]:
    """Load job history from store/control_center/jobs.json."""
    path = _control_center_dir() / "jobs.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


# ---------------------------------------------------------------------------
# Provider health
# ---------------------------------------------------------------------------

@st.cache_data(ttl=5)
def load_provider_health() -> dict[str, Any]:
    """Load circuit-breaker state from store/provider_health.json."""
    path = Path("store/provider_health.json")
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def moat_down(health: dict[str, Any]) -> bool:
    """Return True if ALL configured moat operators are dead (dead_until > now).

    The moat is down when both Claude AND Gemini are exhausted. If even one is
    healthy, the moat can still run.
    """
    now = datetime.now(timezone.utc).timestamp()
    # Moat operators: Claude (anthropic) and Gemini (google) — both must be dead
    # for the moat to be down.
    moat_ops = {"claude", "gemini", "claude_cli", "gemini_cli",
                "anthropic", "google"}

    # Collect moat operators found in the health file
    moat_dead = []
    for op, state in health.items():
        if not op or not isinstance(state, dict):
            continue
        op_root = op.lower().split("/")[0]
        if op_root not in moat_ops:
            continue
        dead_until = state.get("dead_until", 0)
        moat_dead.append(dead_until and dead_until > now)


    # Moat is down only when ALL moat operators are dead.
    # If no moat operators are tracked, we don't know — assume healthy.
    if not moat_dead:
        return False
    return all(moat_dead)


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

@st.cache_data(ttl=5)
@st.cache_data(ttl=5)
def load_audit_log() -> list[dict[str, Any]]:
    """Load all audit log entries from store/prospector.jsonl."""
    return _jsonl_lines(Path("store/prospector.jsonl"))


# NOT cached: this is a cheap pure loop over `audit`. Decorating it with st.cache_data
# would force Streamlit to hash the (potentially 30k+ entry) audit list to build a cache
# key — ~20s on the real log. The expensive I/O it depends on is cached in load_audit_log.
def today_spend(audit: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    """Compute today's spend from the audit log.

    Returns: {total_usd, n_events, by_phase: {phase: amount}}.
    """
    if audit is None:
        audit = load_audit_log()
    today = datetime.now(timezone.utc).date().isoformat()
    total = 0.0
    by_phase: dict[str, float] = {}
    for ev in audit:
        if ev.get("event") != "spend":
            continue
        ts = ev.get("ts", "")
        if not ts.startswith(today):
            continue
        amt = float(ev.get("amount_usd", 0) or 0)
        total += amt
        phase = ev.get("phase", "main")
        by_phase[phase] = by_phase.get(phase, 0.0) + amt
    return {"total_usd": round(total, 4), "by_phase": by_phase}


# ---------------------------------------------------------------------------
# Golden runs
# ---------------------------------------------------------------------------

@st.cache_data(ttl=30)
def load_golden_runs() -> list[dict[str, Any]]:
    """Load all golden run files from store/golden_runs/, newest first."""
    golden_dir = Path("store/golden_runs")
    if not golden_dir.exists():
        return []
    results = []
    for p in sorted(golden_dir.glob("*.json"), reverse=True):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            d["_filename"] = p.name
            d["_mtime"] = p.stat().st_mtime
            results.append(d)
        except (json.JSONDecodeError, OSError):
            pass
    return results


@st.cache_data(ttl=30)
def latest_golden() -> Optional[dict[str, Any]]:
    """The most recent golden run result."""
    runs = load_golden_runs()
    return runs[0] if runs else None


# ---------------------------------------------------------------------------
# Overview KPIs
# ---------------------------------------------------------------------------

@st.cache_data(ttl=10)
def load_overview_kpis() -> dict[str, Any]:
    """Compute KPI metrics for the Overview page."""
    try:
        cfg = load_config_typed()
        stats = catalogue_stats()
        health = load_provider_health()
        audit = load_audit_log()
        today_spend_data = today_spend(audit)
        latest = latest_golden()
        pending = load_pending_signals()
        
        pass_count = stats.get("n_pass", 0)
        kill_count = stats.get("n_kill", 0)
        defer_count = stats.get("n_defer", 0)
        
        spend_today = today_spend_data.get("total_usd", 0.0)
        daily_cap = cfg.spend_guard.daily_cap_usd if cfg.spend_guard else float("inf")
        
        golden_score = latest.get("discrimination_score", 0) if latest else 0
        golden_passed = latest.get("passed", False) if latest else False
        
        pending_count = len(pending)
        
        moat_down = (
            health.get("claude", {}).get("dead_until", 0) > 0
            and health.get("gemini", {}).get("dead_until", 0) > 0
        )
        
        return {
            "pass_count": pass_count,
            "kill_count": kill_count,
            "defer_count": defer_count,
            "today_spend": spend_today,
            "daily_cap": daily_cap,
            "golden_score": golden_score,
            "golden_passed": golden_passed,
            "pending_count": pending_count,
            "moat_down": moat_down,
            "health": health,
        }
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Certification
# ---------------------------------------------------------------------------

@st.cache_data(ttl=30)
def load_certification() -> dict[str, Any]:
    """Load the config certification state."""
    path = _control_center_dir() / "certification.json"
    if not path.exists():
        return {"certified": False}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"certified": False}
