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
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import streamlit as st

from prospector import paths
from prospector.config import load_config

logger = logging.getLogger(__name__)

# Every reader below degrades to an empty value so a broken artifact cannot take the page
# down (app.py:99 would render a traceback where a panel should be).  That is only honest
# while the failure leaves a trace: a silent `{}` is how the cockpit once reported a KPI of
# 0 that was really "the read threw".  So every degraded return logs at ERROR, and the
# decision surfaces (config, provider health, Overview KPIs) also expose a companion
# `*_error()` reader so a panel can render "unavailable" instead of a confident zero.

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
    d = paths.store_path("control_center")
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@st.cache_data(ttl=10)
def load_config_typed():
    """Load the engine Config object. ``None`` means it could not be loaded.

    The except stays broad: `load_config` parses YAML, coerces types and validates, so the
    failure modes are open-ended.  `config_load_error()` carries the reason, because "no
    config" and "config unreadable" look identical to a caller that only sees ``None``.
    """
    try:
        return load_config()
    except Exception:
        logger.exception("control_center: load_config() failed — engine config unreadable")
        return None


@st.cache_data(ttl=10)
def config_load_error() -> str:
    """Why the config readers came back empty — "" when config.yaml loaded both ways.

    Covers `load_config_dict` (raw YAML) and `load_config_typed` (the Config object): both
    degrade to a falsy value, and a page cannot otherwise tell that from a config that
    genuinely says nothing.
    """
    import yaml
    try:
        with open("config.yaml", encoding="utf-8") as f:
            yaml.safe_load(f)
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        return f"config.yaml unreadable — {type(exc).__name__}: {exc}"
    try:
        load_config()
        return ""
    except Exception as exc:  # reported, never raised: pages render a banner, not a crash
        return f"{type(exc).__name__}: {exc}"


@st.cache_data(ttl=10)
def load_config_dict() -> dict[str, Any]:
    """Load config.yaml as a raw dict (for the editor).

    ``{}`` is a legitimate answer (an empty config.yaml), so a swallowed read error here is
    indistinguishable from one — it silently empties the Launch form's operator/lane/profile
    choices.  Narrowed to the conditions actually expected and logged at ERROR;
    `config_load_error()` is what a page shows the operator.
    """
    import yaml
    try:
        with open("config.yaml", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        logger.exception("control_center: config.yaml unreadable — returning empty config")
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
    db_path = paths.store_path("prospector.db")
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
        # "the catalogue is empty" and "the index is locked/corrupt" render identically.
        # The page cannot act on it, so the trace is the audit trail.
        logger.exception("control_center: catalogue_index query failed (decision=%r)", decision)
        rows = []
    finally:
        conn.close()
    return rows


@st.cache_data(ttl=15)
def catalogue_stats() -> dict[str, Any]:
    """Aggregate counts via SQL — do not load every dossier row into Python."""
    empty = {
        "total": 0, "n_pass": 0, "n_kill": 0, "n_defer": 0, "n_provisional": 0,
        "n_pass_non_prov": 0, "n_pass_provisional": 0, "n_listed": 0,
        "pass": 0, "kill": 0, "defer": 0,
    }
    db_path = paths.store_path("prospector.db")
    if not db_path.exists():
        empty["n_listed"] = _count_listings()
        return empty
    conn = sqlite3.connect(str(db_path), timeout=5.0)
    try:
        cur = conn.execute(
            "SELECT lower(coalesce(decision,'')) AS d, COUNT(*), "
            "SUM(CASE WHEN provisional THEN 1 ELSE 0 END) FROM dossiers GROUP BY d"
        )
        dec = {"pass": 0, "kill": 0, "defer": 0}
        prov = 0
        total = 0
        pass_prov = 0
        for d, n, p in cur.fetchall():
            n = int(n or 0)
            p = int(p or 0)
            total += n
            prov += p
            if d in dec:
                dec[d] = n
            if d == "pass":
                pass_prov = p
        n_pass = dec["pass"]
        return {
            **dec,
            "n_pass": n_pass,
            "n_kill": dec["kill"],
            "n_defer": dec["defer"],
            "n_provisional": prov,
            "n_pass_non_prov": max(0, n_pass - pass_prov),
            "n_pass_provisional": pass_prov,
            "n_listed": _count_listings(),
            "total": total,
        }
    except sqlite3.Error:
        empty["n_listed"] = _count_listings()
        return empty
    finally:
        conn.close()


def _count_listings() -> int:
    """Local listing receipts under store/listings/ (CC Pub badge source)."""
    listings = paths.store_path("listings")
    if not listings.is_dir():
        return 0
    try:
        return sum(1 for p in listings.glob("*.json") if p.is_file())
    except OSError:
        logger.exception("control_center: could not count store/listings — reporting 0")
        return 0


@st.cache_data(ttl=15)
def catalogue_has_rows() -> bool:
    """Cheap emptiness check — avoids loading the full index on Overview boot."""
    db_path = paths.store_path("prospector.db")
    if not db_path.exists():
        return False
    conn = sqlite3.connect(str(db_path), timeout=5.0)
    try:
        row = conn.execute("SELECT 1 FROM dossiers LIMIT 1").fetchone()
        return row is not None
    except sqlite3.Error:
        return False
    finally:
        conn.close()


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
        # The file exists (checked above), so this is corruption, not absence — and the
        # caller reads ``None`` as "no dossier". Log it; the page cannot repair a dossier.
        logger.exception("control_center: dossier %s.%s unreadable", candidate_id, decision)
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
        # Exists but unreadable — "unlisted" is the wrong story to tell about a listing.
        logger.exception("control_center: listing %s unreadable", candidate_id)
        return None


# ---------------------------------------------------------------------------
# Pending signals
# ---------------------------------------------------------------------------

@st.cache_data(ttl=5)
def load_pending_signals() -> list[dict[str, Any]]:
    """Load all pending signals from signals/pending/*.json."""
    pending_dir = paths.repo_path("signals", "pending")
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
    """Load job history from store/control_center/jobs.json.

    Filters ephemeral pytest/tmp jobs so the cockpit never treats them as live.
    """
    path = _control_center_dir() / "jobs.json"
    if not path.exists():
        return []
    try:
        jobs = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(jobs, list):
            logger.error("control_center: %s is not a JSON list — reporting no jobs", path)
            return []
    except (json.JSONDecodeError, OSError):
        logger.exception("control_center: %s unreadable — reporting no jobs", path)
        return []
    try:
        from prospector.control_center.runner import filter_production_jobs
    except ImportError:
        # Returning the UNFILTERED list is how a pytest job gets rendered as a live run.
        # Only an import failure may take that path, and it must not be silent.
        logger.exception("control_center: filter_production_jobs unimportable — jobs unfiltered")
        return jobs
    return filter_production_jobs(jobs)


def summarize_job_command(argv: list[str] | None) -> str:
    """Human-readable command summary, e.g. ``generate k=20``."""
    import re

    argv = list(argv or [])
    if not argv:
        return "—"

    # Drop interpreter / -u / -m prospector.run prefix when present.
    parts = argv[:]
    if parts and (parts[0].endswith("python") or parts[0].endswith("python3")
                  or "Python" in parts[0] or parts[0].endswith("python3.14")
                  or parts[0].endswith("/python") or "/bin/python" in parts[0]):
        parts = parts[1:]
    while parts and parts[0] in ("-u", "-B"):
        parts = parts[1:]
    # Bare ``python -c '…'`` test argv — never pretend this is a CC command.
    if parts and parts[0] == "-c":
        return "— (test/ephemeral)"
    if len(parts) >= 2 and parts[0] == "-m" and parts[1].startswith("prospector"):
        parts = parts[2:]
    if parts and parts[0].endswith("prospector.run"):
        parts = parts[1:]

    cmd = parts[0] if parts else " ".join(argv[-3:])
    joined = " ".join(parts)

    k = None
    for flag in ("--candidates", "--count"):
        m = re.search(rf"{re.escape(flag)}\s+(\d+)", joined)
        if m:
            k = m.group(1)
            break
    if k is not None:
        return f"{cmd} k={k}"
    if "--resume" in parts:
        return f"{cmd} --resume"
    return cmd


def argv_lane(argv: list[str] | None) -> str | None:
    """Return ``--lane`` value from a job argv, if present."""
    argv = list(argv or [])
    for i, tok in enumerate(argv):
        if tok == "--lane" and i + 1 < len(argv):
            return str(argv[i + 1])
    return None


def parse_job_progress(log_text: str) -> tuple[int, int] | None:
    """Latest ``[n/m]`` progress from a run log, or None."""
    import re

    if not log_text:
        return None
    clean = re.sub(r"\x1b\[[0-9;]*m", "", log_text)
    hits = re.findall(r"\[(\d+)/(\d+)\]", clean)
    if not hits:
        return None
    n, m = hits[-1]
    return int(n), int(m)


def _log_in_vetting_phase(log_text: str) -> bool:
    """True when a generate run log has entered candidate vetting.

    Generation finishes in seconds; almost all wall-clock is vetting. Glance must
    not keep saying "Generating N/M" once the vet loop has started.
    """
    import re

    if not log_text:
        return False
    clean = re.sub(r"\x1b\[[0-9;]*m", "", log_text)
    if re.search(r"vetting\s+\d+\s+candidate", clean, re.IGNORECASE):
        return True
    if re.search(r"▸\s*vetting started", clean, re.IGNORECASE):
        return True
    # Per-candidate result lines only appear after vetting begins.
    if re.search(r"\[\d+/\d+\].*(?:KILL|PASS|DEFER)", clean):
        return True
    return False


def read_job_log_tail(job: dict[str, Any], n: int = 80) -> str:
    """Last N lines of a job log (disk). Empty string if missing."""
    path = job.get("log_file") or ""
    if not path:
        jid = job.get("job_id")
        if jid:
            path = f"store/control_center/runs/{jid}.log"
    if not path:
        return ""
    p = Path(path)
    try:
        if not p.exists():
            return ""
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-n:])
    except OSError:
        # "" also means "log not written yet", so an unreadable log reads as a quiet run.
        logger.exception("control_center: job log %s unreadable", p)
        return ""


def glance_status(
    active: dict[str, Any] | None,
    latest: dict[str, Any] | None,
    *,
    now: float | None = None,
) -> str:
    """One-sentence cockpit status for the Overview hero."""
    import time as _time

    now = _time.time() if now is None else now

    if active is not None:
        cmd = summarize_job_command(active.get("argv"))
        verb = cmd.split()[0] if cmd and not cmd.startswith("—") else "Running"
        # Present continuous for common verbs
        pretty = {
            "generate": "Generating",
            "vet": "Vetting",
            "signal": "Signalling",
            "discover": "Discovering",
        }.get(verb, verb.capitalize() if verb else "Running")
        tail = read_job_log_tail(active, n=120)
        # generate spends most wall-clock in vetting; don't label that as "Generating".
        if verb == "generate" and _log_in_vetting_phase(tail):
            pretty = "Vetting"
        prog = parse_job_progress(tail)
        lane = argv_lane(active.get("argv"))
        parts = [pretty]
        if prog:
            parts[0] = f"{pretty} {prog[0]}/{prog[1]}"
        elif cmd and cmd != "—":
            parts[0] = f"{pretty} ({cmd})"
        if lane:
            parts.append(f"lane {lane}")
        start = active.get("start_ts") or 0
        if start:
            parts.append(f"{int(now - float(start))}s")
        return " · ".join(parts)

    if latest is None:
        return "No manual job yet · see Engine for the daemon"

    cmd = summarize_job_command(latest.get("argv"))
    status = (latest.get("status") or "?").lower()
    elapsed = latest.get("elapsed_s")
    if elapsed is None and latest.get("start_ts"):
        elapsed = max(0, int(now - float(latest["start_ts"])))
    elapsed_s = f"{int(elapsed)}s" if elapsed is not None else "?"
    label = {
        "succeeded": "succeeded",
        "failed": "failed",
        "cancelled": "cancelled",
        "deferred": "deferred",
        "unknown": "unknown",
    }.get(status, status)
    # NOT "Engine idle". This sentence is built from the last MANUAL launcher job and knows
    # nothing about the daemon: on 2026-08-16 it read "Engine idle · last generate k=5 failed"
    # over a job dated 2026-07-31 while the consumer was live and ruling (3 PASS that run).
    # Name the surface it actually measures, and date it so a stale job cannot read as current.
    age = ""
    started = latest.get("start_ts")
    if started:
        secs = max(0.0, now - float(started))
        if secs < 5400:
            age = f", {int(secs / 60)}m ago"
        elif secs < 172800:
            age = f", {secs / 3600:.0f}h ago"
        else:
            age = f", {secs / 86400:.0f}d ago"
    return f"No manual job running · last {cmd} {label} ({elapsed_s}{age})"


def watched_operators(cfg: dict[str, Any] | None = None) -> list[str]:
    """Deduped operator names for the Overview health strip."""
    cfg = cfg if cfg is not None else load_config_dict()
    watched: list[str] = []
    for key in ("operator", "artifact_operator"):
        val = (cfg or {}).get(key)
        if isinstance(val, list):
            watched.extend(str(x) for x in val)
        elif isinstance(val, str) and val:
            watched.append(val)
    for extra in ("claude_cli", "claude", "deepseek", "minimax"):
        watched.append(extra)
    seen: set[str] = set()
    out: list[str] = []
    for op in watched:
        if op and op not in seen:
            seen.add(op)
            out.append(op)
    return out


def parse_job_outcome_counts(log_text: str) -> dict[str, int] | None:
    """Extract PASS/KILL/DEFER counts from a run log, or None if unfinished/unknown.

    Prefers the progress summary line (``PASS N / KILL M / DEFER K``). Falls back
    to counting per-candidate result lines from ``progress.result``.
    """
    import re

    if not log_text:
        return None

    # Strip ANSI so bold summary lines match.
    clean = re.sub(r"\x1b\[[0-9;]*m", "", log_text)

    summaries = re.findall(
        r"PASS\s+(\d+)\s*/\s*KILL\s+(\d+)(?:\s*/\s*DEFER\s+(\d+))?",
        clean,
    )
    if summaries:
        p, k, d = summaries[-1]
        return {"n_pass": int(p), "n_kill": int(k), "n_defer": int(d or 0)}

    # Signal-pipeline style (if ever echoed to the CC log).
    pipe = re.findall(
        r"pass_count['\":\s]+(\d+).*?kill_count['\":\s]+(\d+).*?defer_count['\":\s]+(\d+)",
        clean,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if pipe:
        p, k, d = pipe[-1]
        return {"n_pass": int(p), "n_kill": int(k), "n_defer": int(d)}

    # Per-candidate lines: "[1/20] ✓ PASS  title…"
    results = re.findall(
        r"\[\d+/\d+\]\s+\S+\s+(PASS|KILL|DEFER)\b",
        clean,
        flags=re.IGNORECASE,
    )
    if results:
        n_pass = sum(1 for r in results if r.upper() == "PASS")
        n_kill = sum(1 for r in results if r.upper() == "KILL")
        n_defer = sum(1 for r in results if r.upper() == "DEFER")
        return {"n_pass": n_pass, "n_kill": n_kill, "n_defer": n_defer}

    return None


def job_outcome_summary(job: dict[str, Any]) -> str:
    """One-line outcome for Overview/Launch: counts, or still-running hint."""
    status = (job.get("status") or "").lower()
    if status in ("running", "queued"):
        return "still running — see log"

    log_path = job.get("log_file") or ""
    text = ""
    if log_path:
        p = Path(log_path)
        if not p.is_absolute():
            p = Path(log_path)
        try:
            if p.exists():
                text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""

    counts = parse_job_outcome_counts(text)
    if counts is not None:
        return (
            f"PASS {counts['n_pass']} / KILL {counts['n_kill']} / "
            f"DEFER {counts['n_defer']}"
        )

    if status == "succeeded":
        return "finished — no PASS/KILL summary in log"
    if status == "failed":
        return "failed — see log"
    if status == "cancelled":
        return "cancelled"
    if status == "deferred":
        return "deferred — see log"
    if status == "unknown":
        return "unknown (process gone) — see log"
    return "—"


def scheduler_paused() -> bool:
    """True when the filesystem kill switch ``store/scheduler/PAUSE`` exists."""
    return paths.store_path("scheduler", "PAUSE").exists()


def launch_operator_choices() -> list[str]:
    """Operator choices for Launch forms — config default first, then known brains."""
    known = ["claude_cli", "claude", "deepseek", "minimax", "mock"]
    cfg = load_config_dict()
    op = cfg.get("operator")
    preferred: list[str] = []
    if isinstance(op, list) and op:
        preferred = [str(op[0])]
    elif isinstance(op, str) and op:
        preferred = [op]
    # "(config)" means omit --operator and use config.yaml chain.
    ordered = ["(config)"] + preferred + [k for k in known if k not in preferred]
    # de-dupe preserving order
    seen: set[str] = set()
    out: list[str] = []
    for x in ordered:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def launch_lane_choices() -> list[str]:
    """Ambition lanes for Launch forms.

    Catalogue default is ``side_hustle`` first. Empty string = multi-lane MIX job
    (explicit, not the catalogue default) — kept at the end of the list.
    """
    cfg = load_config_dict()
    lanes = cfg.get("lanes") or {}
    active = cfg.get("active_lanes") or []
    names = [str(x) for x in active if x] if active else sorted(lanes)
    # Keep canonical order when present; append any defined-but-inactive lanes.
    for name in sorted(lanes):
        if name not in names:
            names.append(name)
    preferred = "side_hustle"
    if preferred in names:
        names = [preferred] + [n for n in names if n != preferred]
    # "" (multi-lane mix) is last — catalogue Launch must not default into a grind.
    return names + [""]


def launch_market_choices() -> list[str]:
    """Markets for Launch — open markets selectable; closed shown but disabled via help.

    Returns codes only for markets with status open (plus empty = config default).
    Closed markets remain launchable only via CLI `markets probe`.
    """
    cfg = load_config_dict()
    markets = cfg.get("markets") or {}
    default = str(markets.get("default") or "")
    open_codes = sorted(
        k for k, v in markets.items()
        if k != "default" and isinstance(v, dict)
        and str(v.get("status", "open") or "open") == "open"
    )
    # Prefer default first when open.
    if default in open_codes:
        open_codes = [default] + [c for c in open_codes if c != default]
    return [""] + open_codes


def launch_archetype_choices() -> list[str]:
    """Founder archetypes for Launch — empty = lane default / config pin."""
    cfg = load_config_dict()
    archetypes = ((cfg.get("generation") or {}).get("archetypes") or {})
    names = sorted(archetypes) if isinstance(archetypes, dict) else []
    # Prefer the configured default first when present.
    default = str((cfg.get("generation") or {}).get("operator_archetype") or "")
    if default in names:
        names = [default] + [n for n in names if n != default]
    return [""] + names


def launch_profile_choices() -> list[str]:
    """Generation profiles for Launch — catalogue default first.

    Profiles are generation-only (forms + focus); they never touch the moat.
    ``statutory_compliance_pack`` is the UK catalogue preset; empty (no profile)
    is available at the end for research / unsteered runs.
    """
    cfg = load_config_dict()
    profiles = cfg.get("profiles") or {}
    names = sorted(profiles) if isinstance(profiles, dict) else []
    preferred = "statutory_compliance_pack"
    if preferred in names:
        names = [preferred] + [n for n in names if n != preferred]
    return names + [""]


@st.cache_data(ttl=15)
def recent_dossier_rows(limit: int = 8) -> list[dict[str, Any]]:
    """Newest catalogue rows for the Overview inventory strip (SQL LIMIT)."""
    limit = max(0, int(limit))
    db_path = paths.store_path("prospector.db")
    if not db_path.exists() or limit == 0:
        return []
    conn = sqlite3.connect(str(db_path), timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            "SELECT candidate_id, title, decision, gate_fired, composite, "
            "created_at, ambition_tier, market, provisional "
            "FROM dossiers ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]
    except sqlite3.Error:
        logger.exception("control_center: recent_dossier_rows query failed")
        return []
    finally:
        conn.close()


def stuck_paths() -> dict[str, str]:
    """Canonical paths an operator should open when debugging."""
    return {
        "jobs": "store/control_center/jobs.json",
        "run_logs": "store/control_center/runs/",
        "audit": "store/prospector.jsonl",
        "pause": "store/scheduler/PAUSE",
        "provider_health": "store/provider_health.json",
        "batch_diagnostics": "store/scheduler/batch_diagnostics.jsonl",
    }


# ---------------------------------------------------------------------------
# Provider health
# ---------------------------------------------------------------------------

def _read_provider_health() -> tuple[dict[str, Any], str]:
    """(health, error). ``error`` is non-empty only when the file exists and broke."""
    path = paths.store_path("provider_health.json")
    if not path.exists():
        return {}, ""  # absence = no breaker ever tripped; a real answer, not a failure
    try:
        return json.loads(path.read_text(encoding="utf-8")), ""
    except (json.JSONDecodeError, OSError) as exc:
        logger.exception("control_center: %s unreadable — operator health unknown", path)
        return {}, f"{type(exc).__name__}: {exc}"


@st.cache_data(ttl=5)
def load_provider_health() -> dict[str, Any]:
    """Load circuit-breaker state from store/provider_health.json.

    An empty dict is read downstream as "no breaker rows ⇒ every operator healthy"
    (pages/_diagnostics.py:85, pages/_overview.py:280).  A corrupt health file therefore
    paints the whole moat green — the loudest possible lie from the quietest failure.
    Pair this with `provider_health_error()` before drawing anything reassuring.
    """
    return _read_provider_health()[0]


@st.cache_data(ttl=5)
def provider_health_error() -> str:
    """Why `load_provider_health()` is empty — "" when the file is absent or fine."""
    return _read_provider_health()[1]


def moat_down(health: dict[str, Any]) -> bool:
    """Return True if ALL configured moat operators are dead (dead_until > now).

    The moat is down when Claude is exhausted.
    """
    now = datetime.now(timezone.utc).timestamp()
    # Moat operators: Claude (anthropic)
    moat_ops = {"claude", "claude_cli"}

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

@st.cache_data(ttl=60)
def load_audit_log() -> list[dict[str, Any]]:
    """Load ALL audit entries — expensive (~15s / 70MB+). Prefer today_spend().

    Kept for Reports. Overview must never call this on the hot path.
    """
    return _jsonl_lines(paths.store_path("prospector.jsonl"))


def _spend_ts(ev: dict[str, Any]) -> str:
    return str(ev.get("ts") or ev.get("timestamp") or ev.get("asctime") or "")


def _today_spend_from_events(audit: list[dict[str, Any]], today: str) -> dict[str, Any]:
    total = 0.0
    by_phase: dict[str, float] = {}
    for ev in audit:
        if ev.get("event") != "spend":
            continue
        ts = _spend_ts(ev)
        if not ts.startswith(today):
            continue
        try:
            amt = float(ev.get("amount_usd", 0) or 0)
        except (TypeError, ValueError):
            continue
        total += amt
        phase = ev.get("phase", "main")
        by_phase[phase] = by_phase.get(phase, 0.0) + amt
    return {"total_usd": round(total, 4), "by_phase": by_phase}


@st.cache_data(ttl=30)
def _today_spend_from_ledger(_mtime: float) -> dict[str, Any]:
    """Today's spend THROUGH THE RAIL'S OWN READER (R23). ``_mtime`` busts the cache.

    This used to be a bespoke reverse-tail parse of `store/prospector.jsonl` living right here —
    a SECOND derivation of the one number the daemon stops itself on. Two parsers of one ledger
    is not redundancy: it is two answers, and the console's was the one nobody could reconcile.
    Concretely it summed `event: "spend"` + `amount_usd` and therefore reported the METERED leg
    only, while calling it "today's spend" — on 2026-08-16 that is $0.69 against $19.53 of
    subscription burn, so the Overview under-reported consumption by 28x with no warning
    (memory: `never-hand-parse-the-spend-ledger`).

    Now it is `SchedulerGuard.scan_today()` via `prospector.ops.spend`, the same call
    `guard.evaluate()` gates on, and BOTH legs come back. `total_usd` keeps its meaning — the
    billed leg the cap enforces — and `subscription_usd` is no longer silently dropped.
    """
    from prospector.ops import spend as _ops_spend
    from prospector.ops.readmodel import load_cfg

    try:
        view = _ops_spend.spend_view(load_cfg())
    except Exception as exc:  # noqa: BLE001 — a KPI must not take the Overview down
        logger.error("control_center: spend view unavailable (%s: %s)", type(exc).__name__, exc)
        return {"total_usd": 0.0, "subscription_usd": 0.0, "by_phase": {},
                "source": "unavailable", "warnings": [f"spend read failed: {exc}"]}

    return {
        "total_usd": round(float(view["legs"]["metered"]["usd"]), 4),
        "subscription_usd": round(float(view["legs"]["subscription"]["usd"]), 4),
        # The guard's single pass accumulates per-DAY, not per-phase; the phase split belonged to
        # the deleted parser. `pages/_spend.py` carries the per-tier and per-role split instead.
        "by_phase": {},
        "source": view["source"],
        "warnings": view.get("warnings", []),
    }


def today_spend(audit: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    """Today's spend. Prefer ledger tail-scan; optional in-memory ``audit`` for tests."""
    today = datetime.now(timezone.utc).date().isoformat()
    if audit is not None:
        # Never put ``audit`` through st.cache_data — hashing 100k+ dicts is multi-second.
        return _today_spend_from_events(audit, today)
    return today_spend_cached()


def today_spend_cached() -> dict[str, Any]:
    """Overview-safe spend helper — keyed by ledger mtime, never loads full jsonl."""
    path = paths.store_path("prospector.jsonl")
    mtime = 0.0
    try:
        if path.exists():
            mtime = path.stat().st_mtime
    except OSError:
        pass
    return _today_spend_from_ledger(mtime)



# ---------------------------------------------------------------------------
# Golden runs
# ---------------------------------------------------------------------------

@st.cache_data(ttl=30)
def load_golden_runs() -> list[dict[str, Any]]:
    """Load all golden run files from store/golden_runs/, newest first.

    Sorted by MTIME, not by filename.  Filenames are `<operator>_<ISO8601>.json`, so a
    reverse lexical sort orders by OPERATOR first and only then by time — it agreed with
    "newest first" for as long as every file shared one prefix, and stopped the moment a
    second brain was benchmarked.  Measured 2026-08-15: `mock_20260814T2149…` (a CI
    artefact, discrimination 1.0) sorted above `minimax_20260815T0046…` (the real gate
    run, 0.667), so the cockpit's headline gate score was a mock's green.
    """
    golden_dir = paths.store_path("golden_runs")
    if not golden_dir.exists():
        return []
    results = []
    for p in golden_dir.glob("*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            d["_filename"] = p.name
            d["_mtime"] = p.stat().st_mtime
            results.append(d)
        except (json.JSONDecodeError, OSError):
            pass
    # Filename breaks mtime ties so the order is deterministic within one second —
    # `--runs 3` writes three records in well under that.
    results.sort(key=lambda d: (d["_mtime"], d["_filename"]), reverse=True)
    return results


@st.cache_data(ttl=30)
def latest_golden() -> Optional[dict[str, Any]]:
    """The most recent REAL golden run — a mock run is never the estate's score.

    `--operator mock` exercises the harness, not a brain: it returns canned verdicts and
    reaches 1.0 by construction.  Displaying one as "latest golden" states that the moat
    passed its gate when nothing was measured.  History keeps them (`load_golden_runs`
    returns everything); the live number may not be one.
    """
    for run in load_golden_runs():
        if str(run.get("operator", "")).lower() != "mock":
            return run
    return None


# ---------------------------------------------------------------------------
# Overview KPIs
# ---------------------------------------------------------------------------

def _compute_overview_kpis() -> tuple[dict[str, Any], str]:
    """(kpis, error). Every consumer reads a missing key as 0 — see the docstring below."""
    try:
        cfg = load_config_typed()
        stats = catalogue_stats()
        health = load_provider_health()
        today_spend_data = today_spend_cached()
        latest = latest_golden()
        pending = load_pending_signals()

        daily_cap = 50.0
        if cfg is not None:
            if hasattr(cfg, "spend_guard") and cfg.spend_guard:
                daily_cap = float(cfg.spend_guard.daily_cap_usd)
            elif hasattr(cfg, "spend") and cfg.spend:
                daily_cap = float(cfg.spend.daily_cap_usd)

        return {
            "pass_count": stats.get("n_pass", 0),
            "kill_count": stats.get("n_kill", 0),
            "defer_count": stats.get("n_defer", 0),
            "n_provisional": stats.get("n_provisional", 0),
            "n_pass_non_prov": stats.get("n_pass_non_prov", 0),
            "n_pass_provisional": stats.get("n_pass_provisional", 0),
            "n_listed": stats.get("n_listed", 0),
            "total": stats.get("total", 0),
            "today_spend": today_spend_data.get("total_usd", 0.0),
            "daily_cap": daily_cap,
            "golden_score": latest.get("discrimination_score") if latest else None,
            "golden_passed": latest.get("passed", False) if latest else False,
            "pending_count": len(pending),
            "moat_down": moat_down(health),
            "paused": scheduler_paused(),
            "health": health,
        }, ""
    except Exception as exc:
        # Broad on purpose: this fans out over sqlite, the spend ledger, golden runs and
        # the config, so anything can surface here. What may NOT happen is the page
        # reading the resulting {} as a quiet estate.
        logger.exception("control_center: Overview KPIs failed to compute")
        return {}, f"{type(exc).__name__}: {exc}"


@st.cache_data(ttl=15)
def load_overview_kpis() -> dict[str, Any]:
    """Lightweight Overview KPIs — never loads the full audit jsonl.

    ``{}`` on failure is kept deliberately (pages/_overview.py:218 hides the KPI strip on a
    falsy value), but ``{}`` is ALSO what a brand-new store returns, and every consumer
    defaults a missing key to 0: `pages/_reports.py:11` would print
    "Today $0.00 · PASS 0 · KILL 0 · 0 dossiers" from a read that threw.  A panel must call
    `overview_kpis_error()` before showing any of these numbers.
    """
    return _compute_overview_kpis()[0]


@st.cache_data(ttl=15)
def overview_kpis_error() -> str:
    """Why `load_overview_kpis()` is empty — "" when the numbers are real."""
    return _compute_overview_kpis()[1]


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
