"""Run Launcher — launch runs from a form without hand-typing run.py commands."""
from __future__ import annotations

import re
import time
from pathlib import Path

import streamlit as st

# Project root must be in path for prospector imports
import sys as _sys
_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

from prospector.control_center import runner as _runner


# Estimated checks per candidate (used for scope hint)
_ESTIMATED_CHECKS_PER_CANDIDATE = 6  # 6 kill-checks


def render():
    st.title("🚀 Run Launcher")

    # ── Check for active run ───────────────────────────────────────────────
    try:
        active = _get_active_job()
        if active:
            _render_run_detail(active)
            return
    except Exception:
        pass

    # ── Command tabs ────────────────────────────────────────────────────────
    tab_vet, tab_signal, tab_generate, tab_discover = st.tabs(
        ["vet", "signal", "generate", "discover"])

    with tab_vet:
        _render_vet_form()
    with tab_signal:
        _render_signal_form()
    with tab_generate:
        _render_generate_form()
    with tab_discover:
        _render_discover_form()


def _get_active_job():
    """Return the active job if one is running, else None."""
    jobs = _runner.load_jobs()
    for j in jobs:
        if j.get("status") == "running":
            return j
    return None


def _render_run_detail(job: dict):
    """Show live log streaming for a running job using st.fragment for scoped refresh."""
    job_id = job.get("job_id", "")
    argv = job.get("argv", [])

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Status", "🟡 Running")
    with col2:
        elapsed = job.get("elapsed_s", 0) or round(
            time.time() - job.get("start_ts", time.time()))
        st.metric("Elapsed", f"{elapsed}s")
    with col3:
        cost = job.get("cost_usd") or "—"
        st.metric("Cost", f"${cost:.4f}" if isinstance(cost, float) else cost)

    st.info(f"Run: `{' '.join(argv)}`")

    # ── Live log — auto-refreshes every 2s within this fragment ──────────
    @st.fragment(run_every="2s")
    def _live_log():
        log_lines = _runner.get_log_lines(job_id, n=300)
        if log_lines:
            st.text_area(
                "Log output",
                "\n".join(log_lines[-300:]),
                height=420,
                disabled=True,
                label_visibility="collapsed",
                key=f"log_{job_id}",
            )
        else:
            st.info("Collecting log output...")

    _live_log()

    # ── Completion check ───────────────────────────────────────────────────
    jobs = _runner.load_jobs()
    current = next((j for j in jobs if j.get("job_id") == job_id), None)
    if current and current.get("status") not in ("running", "queued"):
        _render_completion(current)
    else:
        if st.button("🔴 Cancel run", type="primary"):
            try:
                _runner.cancel_job(job_id)
                st.warning("Run cancelled.")
                st.rerun()
            except Exception as e:
                st.error(f"Cancel failed: {e}")


def _render_completion(job: dict):
    """Show the completion summary card and deep-link to the Catalogue."""
    status = job.get("status", "?")
    status_icon = {
        "succeeded": "✅ Succeeded",
        "failed": "❌ Failed",
        "cancelled": "⚠️ Cancelled",
        "deferred": "⏸ Deferred",
    }.get(status, status)

    st.success(f"Run {status_icon}")
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Duration", f"{job.get('elapsed_s', '?')}s")
    with col2:
        cost = job.get("cost_usd")
        st.metric("Cost", f"${cost:.4f}" if isinstance(cost, float) else cost or "—")

    # ── Deep-link to new dossier ─────────────────────────────────────────
    # Parse candidate_id from the on-disk log if this was a vet run
    job_id = job.get("job_id", "")
    log_file = Path(f"store/control_center/runs/{job_id}.log")
    candidate_ids = []
    if log_file.exists():
        for line in log_file.read_text(encoding="utf-8").splitlines():
            # Look for: "candidate_id: <id>" or "Vetting candidate: <title> (id=<id>)"
            m = re.search(r"candidate_id['\":\s]+([0-9a-f]{16})", line, re.IGNORECASE)
            if m:
                candidate_ids.append(m.group(1))
            m = re.search(r"id=([0-9a-f]{16})", line)
            if m and m.group(1) not in candidate_ids:
                candidate_ids.append(m.group(1))

    if candidate_ids:
        st.markdown("**New dossiers:**")
        for cid in candidate_ids:
            st.page_link(
                "prospector/control_center/app.py",
                label=f"📋 {cid[:8]}…",
                params={"page": "📋 Catalogue"},
            )
            st.caption(f"id: `{cid}`")

    # ── Next actions ──────────────────────────────────────────────────────
    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        if st.button("📋 View in Catalogue"):
            st.switch_page("prospector/control_center/app.py")
    with col2:
        if st.button("🚀 Launch another run", type="primary"):
            st.rerun()


# ---------------------------------------------------------------------------
# Form builders
# ---------------------------------------------------------------------------

def _render_vet_form():
    with st.form("vet_form"):
        st.markdown("**Vet a single candidate**")
        title = st.text_input("Title *", placeholder="e.g. Fuel duty rebate automation")
        one_liner = st.text_input("One-liner", placeholder="Short description")
        why_now = st.text_input("Why now", placeholder="e.g. HMRC rule change 2024")
        
        col1, col2 = st.columns(2)
        with col1:
            lane = st.selectbox("Lane",
                               ["", "venture", "operator", "founder", "scout"], index=0)
            operator = st.selectbox("Operator",
                                   ["mock", "gemini_cli", "claude", "gemini"], index=1)
        with col2:
            persona = st.selectbox("Persona",
                                  ["", "shark", "minimalist", "academic"], index=0,
                                  help="Analytical bias to 'tint' the analysis.")
            board = st.checkbox("Advisory Board mode", value=False,
                               help="Run shark, minimalist, and academic in parallel.")

        fixtures = st.checkbox("Offline mode (--fixtures)", value=True)
        publish = st.checkbox("Publish on PASS (requires golden certification)")

        _scope_hint("vet", 1, operator, fixtures)

        submitted = st.form_submit_button("🚀 Launch vet", type="primary")
        if submitted and title:
            _launch_vet(title, one_liner, why_now, lane, operator, fixtures, publish, persona, board)
        elif submitted:
            st.warning("Title is required.")


def _render_signal_form():
    with st.form("signal_form"):
        st.markdown("**Generate candidates from a signal**")
        text = st.text_area("Signal text *",
                           placeholder="e.g. Rising energy costs for SME manufacturers",
                           height=4)
        count = st.slider("Candidates to generate", 1, 10, 3)
        
        col1, col2 = st.columns(2)
        with col1:
            lane = st.selectbox("Lane",
                               ["", "venture", "operator", "founder", "scout"], index=0)
            operator = st.selectbox("Operator",
                                   ["mock", "gemini_cli", "claude", "gemini"], index=1)
        with col2:
            persona = st.selectbox("Persona",
                                  ["", "shark", "minimalist", "academic"], index=0,
                                  help="Analytical bias to 'tint' the analysis.")
            board = st.checkbox("Advisory Board mode", value=False,
                               help="Run shark, minimalist, and academic in parallel.")

        fixtures = st.checkbox("Offline mode (--fixtures)", value=True)
        publish = st.checkbox("Publish on PASS (requires golden certification)")

        _scope_hint("signal", count, operator, fixtures)

        submitted = st.form_submit_button("🚀 Launch signal", type="primary")
        if submitted and text:
            _launch_signal(text, count, lane, operator, fixtures, publish, persona, board)
        elif submitted:
            st.warning("Signal text is required.")


def _render_generate_form():
    with st.form("generate_form"):
        st.markdown("**Direct candidate generation**")
        candidates = st.slider("Candidates", 1, 20, 5)
        exploration = st.slider("Exploration level", 0.2, 0.9, 0.5, 0.1)
        
        col1, col2 = st.columns(2)
        with col1:
            lane = st.selectbox("Lane",
                               ["", "venture", "operator", "founder", "scout"], index=0)
            operator = st.selectbox("Operator",
                                   ["mock", "gemini_cli", "claude", "gemini"], index=1)
        with col2:
            persona = st.selectbox("Persona",
                                  ["", "shark", "minimalist", "academic"], index=0,
                                  help="Analytical bias to 'tint' the analysis.")
            board = st.checkbox("Advisory Board mode", value=False,
                               help="Run shark, minimalist, and academic in parallel.")

        fixtures = st.checkbox("Offline mode (--fixtures)", value=True)

        _scope_hint("generate", candidates, operator, fixtures)

        submitted = st.form_submit_button("🚀 Launch generate", type="primary")
        if submitted:
            _launch_generate(candidates, exploration, lane, operator, fixtures, persona, board)


def _render_discover_form():
    with st.form("discover_form"):
        st.markdown("**Discover opportunities from sectors**")
        count = st.slider("Discoveries", 1, 20, 5)
        
        col1, col2 = st.columns(2)
        with col1:
            dry_run = st.checkbox("Dry run", value=True)
            fixtures = st.checkbox("Offline mode (--fixtures)", value=True)
        with col2:
            persona = st.selectbox("Persona",
                                  ["", "shark", "minimalist", "academic"], index=0,
                                  help="Analytical bias to 'tint' the analysis.")
            board = st.checkbox("Advisory Board mode", value=False,
                               help="Run shark, minimalist, and academic in parallel.")

        submitted = st.form_submit_button("🚀 Launch discover", type="primary")
        if submitted:
            _launch_discover(count, dry_run, fixtures, persona, board)


# ---------------------------------------------------------------------------
# Scope estimation hint
# ---------------------------------------------------------------------------

def _scope_hint(mode: str, candidates: int, operator: str, fixtures: bool):
    """Show an estimated cost/latency hint based on form values."""
    if fixtures:
        st.caption("ℹ️ Offline mode: uses fixtures, no API cost, fast (~30s)")
        return

    checks = _ESTIMATED_CHECKS_PER_CANDIDATE
    scope_str = f"~{candidates} candidate(s) × {checks} checks = ~{candidates * checks} LLM calls"
    if mode == "vet":
        latency = "~1–5 min total"
    elif mode == "signal":
        latency = "~5–15 min"
    elif mode == "generate":
        latency = "~2–8 min"
    else:
        latency = "~1–5 min"

    # Rough cost estimate
    cost_per_call = 0.001  # rough estimate for mock/gemini
    if operator in ("claude",):
        cost_per_call = 0.003
    estimated_cost = candidates * checks * cost_per_call

    st.caption(f"ℹ️ Estimated scope: {scope_str} · latency {latency} · "
               f"est. cost ${estimated_cost:.3f} (offline = free)")


# ---------------------------------------------------------------------------
# Launch helpers
# ---------------------------------------------------------------------------

def _launch_vet(title, one_liner, why_now, lane, operator, fixtures, publish, persona, board):
    """Build argv and launch a vet run."""
    argv = ["python", "-m", "prospector.run", "vet",
            "--title", title, "--operator", operator]
    if one_liner:
        argv += ["--one-liner", one_liner]
    if why_now:
        argv += ["--why-now", why_now]
    if lane:
        argv += ["--lane", lane]
    if persona:
        argv += ["--persona", persona]
    if board:
        argv += ["--board"]
    if fixtures:
        argv += ["--fixtures"]
    if publish:
        argv += ["--publish"]
    _do_launch(argv)


def _launch_signal(text, count, lane, operator, fixtures, publish, persona, board):
    argv = ["python", "-m", "prospector.run", "signal",
            "--text", text, "--count", str(count), "--operator", operator]
    if lane:
        argv += ["--lane", lane]
    if persona:
        argv += ["--persona", persona]
    if board:
        argv += ["--board"]
    if fixtures:
        argv += ["--fixtures"]
    if publish:
        argv += ["--publish"]
    _do_launch(argv)


def _launch_generate(candidates, exploration, lane, operator, fixtures, persona, board):
    argv = ["python", "-m", "prospector.run", "generate",
            "--candidates", str(candidates),
            "--exploration", str(exploration),
            "--operator", operator]
    if lane:
        argv += ["--lane", lane]
    if persona:
        argv += ["--persona", persona]
    if board:
        argv += ["--board"]
    if fixtures:
        argv += ["--fixtures"]
    _do_launch(argv)


def _launch_discover(count, dry_run, fixtures, persona, board):
    argv = ["python", "-m", "prospector.run", "discover",
            "--count", str(count)]
    if dry_run:
        argv += ["--dry-run"]
    if persona:
        argv += ["--persona", persona]
    if board:
        argv += ["--board"]
    if fixtures:
        argv += ["--fixtures"]
    _do_launch(argv)


def _do_launch(argv: list[str]):
    """Common launch logic with publish double-gate."""
    # ── Publish double-gate ────────────────────────────────────────────────
    if "--publish" in argv:
        from prospector.control_center.readers import load_certification
        cert = load_certification()
        if not cert.get("certified"):
            st.error("🚨 Publish is blocked: the config is not certified by a passing "
                     "golden run. Run golden regression first, or remove the publish flag.")
            return

    try:
        job_id = _runner.launch(argv)
        st.success(f"Run launched: `{job_id}`. Live log will appear below.")
        st.rerun()
    except RuntimeError as e:
        st.error(f"❌ {e}")
    except Exception as e:
        st.error(f"Launch failed: {e}")
