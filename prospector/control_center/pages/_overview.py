"""Overview — operator cockpit.

Layout (top → bottom):
  1. One-glance status sentence + primary Launch CTA
  2. Active / last job outcome + log peek (always one click)
  3. Inventory metrics + compact operator health
  4. Expandable: recent runs, when stuck, calibration alarms

Never load full audit jsonl. Auto-refresh only while a job is running.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import streamlit as st

from prospector.control_center import readers
from prospector.control_center.components.chrome import (
    go_page,
    job_log_path,
    log_panel,
    page_hero,
    resolve_log_text,
    tone_from_job_status,
)


def render():
    jobs = _jobs_for_ui()
    active, latest = _active_and_latest(jobs)
    focus = active or latest

    glance = readers.glance_status(active, latest)
    tone = tone_from_job_status((focus or {}).get("status") if focus else None)
    if active is None and latest is None:
        tone = "idle"

    page_hero("Overview", glance, tone=tone)
    _render_pause_banner()
    _render_cta_row(busy=active is not None)

    if not readers.catalogue_has_rows() and not focus:
        st.caption("No dossiers yet — launch generate with safe defaults.")
    else:
        _render_job_panel(active, latest)
        _render_kpi_cards()
        _render_moat_pills()

    with st.expander("Recent runs", expanded=False):
        _render_recent_runs()
    with st.expander("When stuck", expanded=False):
        _render_stuck_help()
    with st.expander("Calibration alarms (slow — on demand)", expanded=False):
        _render_alarm_cards()


# ---------------------------------------------------------------------------
# Jobs helpers (kept for tests)
# ---------------------------------------------------------------------------

def _jobs_for_ui() -> list[dict]:
    try:
        from prospector.control_center import runner as _runner
        jobs = _runner.load_jobs()
    except Exception:
        jobs = readers.load_jobs()
    try:
        from prospector.control_center.runner import filter_production_jobs
        return filter_production_jobs(jobs)
    except Exception:
        return jobs


def _active_and_latest(jobs: list[dict]) -> tuple[dict | None, dict | None]:
    if not jobs:
        return None, None
    active = next((j for j in jobs if j.get("status") == "running"), None)
    finishedish = [j for j in jobs if j.get("status") not in ("running", "queued")]
    pool = finishedish or jobs
    latest = max(pool, key=lambda j: j.get("start_ts", 0))
    return active, latest


def _status_label(status: str) -> str:
    return {
        "running": "Running",
        "succeeded": "Succeeded",
        "failed": "Failed",
        "cancelled": "Cancelled",
        "deferred": "Deferred",
        "queued": "Queued",
        "unknown": "Unknown",
    }.get(status, status or "?")


def _fmt_ts(ts: float | int | None) -> str:
    if not ts:
        return "—"
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return "—"


# ---------------------------------------------------------------------------
# CTA / pause
# ---------------------------------------------------------------------------

def _render_pause_banner():
    if readers.scheduler_paused():
        st.error("PAUSE kill switch ON — `store/scheduler/PAUSE` exists. Delete it to resume.")


def _render_cta_row(*, busy: bool):
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        label = "Launch generate" if not busy else "Open live run"
        if st.button(label, type="primary", use_container_width=True, key="ov_launch"):
            go_page("launcher")
    with c2:
        if st.button("Refresh", use_container_width=True, key="overview_refresh"):
            for fn in (
                readers.load_overview_kpis,
                readers.catalogue_stats,
                readers.catalogue_has_rows,
                readers.recent_dossier_rows,
                readers.load_jobs,
                readers.load_provider_health,
                readers._today_spend_from_ledger,
            ):
                try:
                    fn.clear()
                except Exception:
                    pass
            st.rerun()
    with c3:
        if st.button("Resume / DEFER", use_container_width=True, key="ov_resume"):
            go_page("resume")


# ---------------------------------------------------------------------------
# Job panel + log (running AND finished)
# ---------------------------------------------------------------------------

def _render_job_panel(active: dict | None, latest: dict | None):
    job = active or latest
    if job is None:
        return

    if active is not None:
        _render_now_live(active)
        return

    st.markdown("**Last job**")
    _render_job_meta(latest)
    path = job_log_path(latest)
    log_panel(
        resolve_log_text(latest, n=80),
        path=path,
        height=240,
        key=f"last_log_{latest.get('job_id')}",
        empty_hint="Log empty or missing — path above.",
    )


def _render_now_live(job: dict):
    @st.fragment(run_every="15s")
    def _tick():
        jobs = _jobs_for_ui()
        current = next(
            (j for j in jobs if j.get("job_id") == job.get("job_id")),
            job,
        )
        st.markdown("**Live run**")
        _render_job_meta(current)
        path = job_log_path(current)
        log_panel(
            resolve_log_text(current, n=100),
            path=path,
            height=280,
            key=f"now_log_{current.get('job_id')}_{current.get('status')}",
            empty_hint="Log empty or not flushed yet.",
        )
        if current.get("status") not in ("running", "queued"):
            st.info("Job finished — click Refresh to update the cockpit.")

    _tick()


def _render_job_meta(job: dict):
    job_id = job.get("job_id", "—")
    status = job.get("status", "?")
    cmd = readers.summarize_job_command(job.get("argv"))
    outcome = readers.job_outcome_summary(job)
    start_ts = job.get("start_ts") or 0
    if status == "running" and start_ts:
        elapsed = f"{int(time.time() - float(start_ts))}s"
    elif job.get("elapsed_s") is not None:
        elapsed = f"{job['elapsed_s']}s"
    else:
        elapsed = "—"

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Job", str(job_id)[-12:])
    c2.metric("Command", cmd)
    c3.metric("Status", _status_label(status))
    c4.metric("Elapsed", elapsed)
    st.caption(f"Outcome: {outcome} · started {_fmt_ts(start_ts)}")


# ---------------------------------------------------------------------------
# Inventory + health (test-exported names)
# ---------------------------------------------------------------------------

def _render_kpi_cards():
    kpis = readers.load_overview_kpis()
    if not kpis:
        return
    spend = float(kpis.get("today_spend") or 0.0)
    cap = float(kpis.get("daily_cap") or 50.0)
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric(
        "PASS (sellable)",
        kpis.get("n_pass_non_prov", kpis.get("pass_count", 0)),
        help="Non-provisional PASSes (may publish).",
    )
    c2.metric(
        "Provisional",
        kpis.get("n_pass_provisional", kpis.get("n_provisional", 0)),
        help="PASS ruled by emergency fallback — never publish until re-vet.",
    )
    c3.metric(
        "Listed",
        kpis.get("n_listed", 0),
        help="Local store/listings receipts (Pub=Y). Store Catalog is sellable SoT.",
    )
    c4.metric("KILL", kpis.get("kill_count", 0))
    c5.metric("Spend", f"${spend:.2f}")
    c6.metric("Cap", f"${cap:.0f}")
    st.caption(
        f"All PASS={kpis.get('pass_count', 0)} · DEFER={kpis.get('defer_count', 0)} · "
        f"Pending signals={kpis.get('pending_count', 0)}"
    )

    rows = readers.recent_dossier_rows(6)
    if rows:
        st.caption("Newest dossiers")
        display = [{
            "id": (r.get("candidate_id") or "")[:8],
            "title": (r.get("title") or "")[:50],
            "decision": (r.get("decision") or "").upper(),
            "lane": r.get("ambition_tier") or "—",
            "created": (r.get("created_at") or "")[:19],
        } for r in rows]
        st.dataframe(display, use_container_width=True, hide_index=True, height=200)


def _render_moat_pills():
    kpis = readers.load_overview_kpis()
    health = kpis.get("health") or readers.load_provider_health()
    watched = readers.watched_operators()
    now = datetime.now(timezone.utc).timestamp()

    paused = "PAUSE" if kpis.get("paused") else ""
    moat = "MOAT DOWN" if kpis.get("moat_down") else ""
    flags = " · ".join(x for x in (paused, moat) if x)
    if flags:
        st.caption(flags)

    pills = []
    for op in watched:
        state = health.get(op) if isinstance(health, dict) else None
        if not isinstance(state, dict):
            for k, v in (health or {}).items():
                if isinstance(v, dict) and k.lower().split("/")[0] == op.lower():
                    state = v
                    break
        if not isinstance(state, dict):
            # Absence = breaker never tripped — healthy, no "no row" spam.
            pills.append(f'<span class="cc-pill cc-pill--healthy">{op}</span>')
            continue
        du = state.get("dead_until", 0) or 0
        remaining = max(0, du - now) if du else 0
        if remaining > 0:
            pills.append(
                f'<span class="cc-pill cc-pill--dead">{op} {round(remaining)}s</span>'
            )
        elif du > 0:
            pills.append(
                f'<span class="cc-pill cc-pill--recovering">{op} recovering</span>'
            )
        else:
            pills.append(f'<span class="cc-pill cc-pill--healthy">{op}</span>')

    if pills:
        st.markdown(
            '<div style="display:flex;flex-wrap:wrap;gap:0.4rem;padding:0.35rem 0">'
            + "".join(pills) + "</div>",
            unsafe_allow_html=True,
        )


def _render_stuck_help():
    paths = readers.stuck_paths()
    st.markdown(
        f"- Job logs: `{paths['run_logs']}`\n"
        f"- Jobs registry: `{paths['jobs']}`\n"
        f"- Audit ledger: `{paths['audit']}`\n"
        f"- Provider health: `{paths['provider_health']}`\n"
        f"- Batch diagnostics: `{paths['batch_diagnostics']}`\n"
        f"- PAUSE switch: `{paths['pause']}`\n"
    )


def _render_recent_runs():
    jobs = _jobs_for_ui()
    if not jobs:
        st.caption("No production runs recorded.")
        return
    recent = sorted(jobs, key=lambda j: j.get("start_ts", 0), reverse=True)[:10]
    rows = []
    for j in recent:
        status = j.get("status", "?")
        start = j.get("start_ts", 0) or 0
        if status == "running" and start:
            elapsed = round(time.time() - start)
        else:
            elapsed = j.get("elapsed_s") or "—"
        rows.append({
            "job_id": j.get("job_id", ""),
            "status": _status_label(status),
            "command": readers.summarize_job_command(j.get("argv")),
            "started": _fmt_ts(start),
            "elapsed_s": elapsed,
            "outcome": readers.job_outcome_summary(j),
            "log": j.get("log_file") or "",
        })
    st.dataframe(rows, use_container_width=True, hide_index=True, height=260)


def _render_alarm_cards():
    data = _diagnostics_cached()
    if data.get("error"):
        st.warning(f"Could not load diagnostics: {data['error']}")
        return
    alarms = data.get("alarms", [])
    if not alarms:
        st.success("No calibration pathologies detected.")
        return
    for a in alarms[:8]:
        st.warning(f"**{a.get('code', '?')}** ({a.get('level', 'warn')}): {a.get('message', '')}")


@st.cache_data(ttl=60)
def _diagnostics_cached() -> dict:
    cfg = readers.load_config_typed()
    if cfg is None:
        return {"alarms": [], "error": "no config"}
    from prospector.diagnostics import diagnostics_data
    from prospector.store import Store
    try:
        return diagnostics_data(Store(cfg), cfg)
    except Exception as e:
        return {"alarms": [], "error": str(e)}
