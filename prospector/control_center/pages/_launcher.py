"""Run Launcher — generate-first wizard with live / finished logs."""
from __future__ import annotations

import re
import sys as _sys
import time
from pathlib import Path

import streamlit as st

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

from prospector.control_center import runner as _runner
from prospector.control_center.components.chrome import (
    job_log_path,
    log_panel,
    page_hero,
    resolve_log_text,
    tone_from_job_status,
)

_ESTIMATED_CHECKS_PER_CANDIDATE = 6


def render():
    from prospector.control_center import readers as _readers

    active = None
    try:
        active = _get_active_job()
    except Exception:
        pass

    jobs = []
    try:
        from prospector.control_center.runner import filter_production_jobs
        jobs = filter_production_jobs(_runner.load_jobs())
    except Exception:
        try:
            jobs = _runner.load_jobs()
        except Exception:
            jobs = []

    latest = None
    finished = [j for j in jobs if j.get("status") not in ("running", "queued")]
    if finished:
        latest = max(finished, key=lambda j: j.get("start_ts", 0))

    if active:
        glance = _readers.glance_status(active, latest)
        page_hero("Launch", glance, tone="live")
        _render_run_detail(active)
        return

    glance = _readers.glance_status(None, latest)
    page_hero("Launch", glance, tone=tone_from_job_status((latest or {}).get("status")))

    _render_generate_form()

    with st.expander("Other commands (vet / signal / discover)", expanded=False):
        tab_vet, tab_signal, tab_discover = st.tabs(["vet", "signal", "discover"])
        with tab_vet:
            _render_vet_form()
        with tab_signal:
            _render_signal_form()
        with tab_discover:
            _render_discover_form()

    if latest:
        st.markdown("**Last finished run**")
        cmd = _readers.summarize_job_command(latest.get("argv"))
        outcome = _readers.job_outcome_summary(latest)
        st.caption(
            f"{latest.get('job_id')} · {cmd} · {_status_label(latest.get('status'))} · {outcome}"
        )
        log_panel(
            resolve_log_text(latest, n=100),
            path=job_log_path(latest),
            height=260,
            key=f"launch_last_{latest.get('job_id')}",
            empty_hint="No log for last job.",
        )


def _status_label(status: str | None) -> str:
    return {
        "running": "Running",
        "succeeded": "Succeeded",
        "failed": "Failed",
        "cancelled": "Cancelled",
        "deferred": "Deferred",
        "queued": "Queued",
        "unknown": "Unknown",
    }.get(status or "", status or "?")


def _operator_select(key: str):
    from prospector.control_center import readers as _readers
    choices = _readers.launch_operator_choices()
    return st.selectbox(
        "Operator",
        choices,
        index=0,
        key=key,
        help="(config) uses config.yaml chain. mock = offline tests only.",
    )


def _lane_select(key: str):
    from prospector.control_center import readers as _readers
    return st.selectbox(
        "Lane",
        _readers.launch_lane_choices(),
        index=0,
        key=key,
        format_func=lambda x: "(MIX multi-lane — not catalogue default)" if x == "" else x,
        help="Catalogue default: side_hustle. MIX (empty) fans across active_lanes — "
             "use only for deliberate mix jobs, not catalogue yield.",
    )


def _market_select(key: str):
    from prospector.control_center import readers as _readers
    return st.selectbox(
        "Market",
        _readers.launch_market_choices(),
        index=0,
        key=key,
        format_func=lambda x: "(config default)" if x == "" else x,
        help="Open jurisdictions only. Closed markets need `markets probe` first.",
    )


def _archetype_select(key: str):
    from prospector.control_center import readers as _readers
    return st.selectbox(
        "Archetype",
        _readers.launch_archetype_choices(),
        index=0,
        key=key,
        format_func=lambda x: "(lane default)" if x == "" else x,
        help="Founder capacity: solo_agent / small_team / startup. Generation-only.",
    )


def _profile_select(key: str):
    from prospector.control_center import readers as _readers
    return st.selectbox(
        "Profile",
        _readers.launch_profile_choices(),
        index=0,
        key=key,
        format_func=lambda x: "(none — research / unsteered)" if x == "" else x,
        help="Catalogue default: statutory_compliance_pack. "
             "Generation steering only (forms + focus); never a gate.",
    )


def _get_active_job():
    for j in _runner.load_jobs():
        if j.get("status") == "running":
            return j
    return None


def _render_run_detail(job: dict):
    from prospector.control_center import readers as _readers

    job_id = job.get("job_id", "")
    argv = job.get("argv", [])
    cmd = _readers.summarize_job_command(argv)
    log_path = job_log_path(job)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Job", str(job_id)[-12:])
    col2.metric("Status", "Running")
    elapsed = job.get("elapsed_s", 0) or round(
        time.time() - job.get("start_ts", time.time()))
    col3.metric("Elapsed", f"{elapsed}s")
    cost = job.get("cost_usd")
    col4.metric("Cost", f"${cost:.4f}" if isinstance(cost, float) else (cost or "—"))
    st.caption(f"{cmd} · {log_path}")

    @st.fragment(run_every="5s")
    def _live_log():
        jobs = _runner.load_jobs()
        current = next((j for j in jobs if j.get("job_id") == job_id), None) or job
        status = current.get("status", "running")
        log_panel(
            resolve_log_text(current, n=200),
            path=job_log_path(current),
            height=420,
            key=f"log_{job_id}_{status}",
            empty_hint="Collecting log output…",
        )
        if status not in ("running", "queued"):
            st.caption("Job finished — see summary below.")

    _live_log()

    jobs = _runner.load_jobs()
    current = next((j for j in jobs if j.get("job_id") == job_id), None)
    if current and current.get("status") not in ("running", "queued"):
        _render_completion(current)
    else:
        if st.button("Cancel run", type="secondary", key="cancel_run"):
            try:
                _runner.cancel_job(job_id)
                st.warning("Cancel signalled.")
                st.rerun()
            except Exception as e:
                st.error(f"Cancel failed: {e}")


def _render_completion(job: dict):
    from prospector.control_center import readers as _readers

    status = job.get("status", "?")
    job_id = job.get("job_id", "")
    cmd = _readers.summarize_job_command(job.get("argv"))
    outcome = _readers.job_outcome_summary(job)
    log_path = job_log_path(job)

    if status == "succeeded":
        st.success(f"Succeeded · {cmd} · {outcome}")
    elif status == "failed":
        st.error(f"Failed · {cmd} · {outcome}")
    else:
        st.warning(f"{_status_label(status)} · {cmd} · {outcome}")

    col1, col2, col3 = st.columns(3)
    col1.metric("Job", str(job_id)[-12:])
    col2.metric("Duration", f"{job.get('elapsed_s', '?')}s")
    cost = job.get("cost_usd")
    col3.metric("Cost", f"${cost:.4f}" if isinstance(cost, float) else (cost or "—"))
    st.caption(f"Log: `{log_path}`")

    log_file = Path(log_path)
    candidate_ids: list[str] = []
    if log_file.exists():
        for line in log_file.read_text(encoding="utf-8").splitlines():
            m = re.search(r"candidate_id['\":\s]+([0-9a-f]{16})", line, re.IGNORECASE)
            if m:
                candidate_ids.append(m.group(1))
            m = re.search(r"id=([0-9a-f]{16})", line)
            if m and m.group(1) not in candidate_ids:
                candidate_ids.append(m.group(1))
    if candidate_ids:
        st.caption("Candidates: " + ", ".join(c[:8] for c in candidate_ids[:8]))

    c1, c2 = st.columns(2)
    with c1:
        if st.button("View Catalogue", key="done_cat"):
            from prospector.control_center.components.chrome import go_page
            go_page("catalogue")
    with c2:
        if st.button("Launch another", type="primary", key="done_again"):
            st.rerun()


# ---------------------------------------------------------------------------
# Forms
# ---------------------------------------------------------------------------

# Catalogue yield: keep k small. Multi-lane MIX is a separate job — not this slider's job.
_CATALOGUE_K_MAX = 5


def _render_generate_form():
    with st.form("generate_form"):
        st.markdown("**Generate + vet (catalogue)** — side_hustle · statutory pack · publish")
        st.caption(
            "Default path for sellable UK packs. Multi-lane MIX is a separate research job "
            "(pick “(MIX multi-lane…)” under Lane) — do not grind MIX at high k for catalogue."
        )
        candidates = st.slider("Candidates (k)", 1, _CATALOGUE_K_MAX, 5)
        exploration = st.slider("Exploration", 0.2, 0.9, 0.5, 0.1)

        col1, col2, col3 = st.columns(3)
        with col1:
            lane = _lane_select("generate_lane")
            market = _market_select("generate_market")
        with col2:
            archetype = _archetype_select("generate_archetype")
            profile = _profile_select("generate_profile")
            operator = _operator_select("generate_operator")
        with col3:
            persona = st.selectbox(
                "Persona", ["", "shark", "minimalist", "academic"], index=0)
            board = st.checkbox("Advisory Board", value=False)

        fixtures = st.checkbox(
            "Offline fixtures (dry rehearsal)", value=False,
            help="Leave OFF for live runs.")
        publish = st.checkbox(
            "Publish on PASS", key="gen_pub", value=True,
            help="Catalogue default ON. Artifacts + Store listing on PASS. "
                 "Provisional PASSes never publish.")
        if not lane:
            st.warning(
                "MIX multi-lane selected — this is not the catalogue default. "
                f"k is still capped at {_CATALOGUE_K_MAX}. Prefer side_hustle + "
                "statutory_compliance_pack + publish for yield."
            )
        _scope_hint("generate", candidates, operator, fixtures)
        if st.form_submit_button("Launch generate", type="primary"):
            if candidates > _CATALOGUE_K_MAX:
                st.error(f"Catalogue generate caps k at {_CATALOGUE_K_MAX}.")
                return
            _launch_generate(
                candidates, exploration, lane, operator, fixtures, persona, board,
                market=market, archetype=archetype, profile=profile, publish=publish)


def _render_vet_form():
    with st.form("vet_form"):
        title = st.text_input("Title *", placeholder="e.g. Fuel duty rebate automation")
        one_liner = st.text_input("One-liner")
        why_now = st.text_input("Why now")
        col1, col2, col3 = st.columns(3)
        with col1:
            lane = _lane_select("vet_lane")
            market = _market_select("vet_market")
        with col2:
            archetype = _archetype_select("vet_archetype")
            operator = _operator_select("vet_operator")
        with col3:
            persona = st.selectbox(
                "Persona", ["", "shark", "minimalist", "academic"],
                index=0, key="vet_persona")
            board = st.checkbox("Advisory Board", value=False, key="vet_board")
        fixtures = st.checkbox("Offline fixtures", value=False, key="vet_fx")
        publish = st.checkbox("Publish on PASS", key="vet_pub")
        _scope_hint("vet", 1, operator, fixtures)
        submitted = st.form_submit_button("Launch vet", type="primary")
        if submitted and title:
            _launch_vet(
                title, one_liner, why_now, lane, operator, fixtures, publish,
                persona, board, market=market, archetype=archetype)
        elif submitted:
            st.warning("Title is required.")


def _render_signal_form():
    with st.form("signal_form"):
        text = st.text_area("Signal text *", height=80)
        count = st.slider("Candidates", 1, 10, 3, key="sig_k")
        col1, col2, col3 = st.columns(3)
        with col1:
            lane = _lane_select("sig_lane")
            market = _market_select("sig_market")
        with col2:
            archetype = _archetype_select("sig_archetype")
            operator = _operator_select("signal_operator")
        with col3:
            persona = st.selectbox(
                "Persona", ["", "shark", "minimalist", "academic"],
                index=0, key="sig_persona")
            board = st.checkbox("Advisory Board", value=False, key="sig_board")
        fixtures = st.checkbox("Offline fixtures", value=False, key="sig_fx")
        publish = st.checkbox("Publish on PASS", key="sig_pub")
        _scope_hint("signal", count, operator, fixtures)
        submitted = st.form_submit_button("Launch signal", type="primary")
        if submitted and text:
            _launch_signal(
                text, count, lane, operator, fixtures, publish, persona, board,
                market=market, archetype=archetype)
        elif submitted:
            st.warning("Signal text is required.")


def _render_discover_form():
    with st.form("discover_form"):
        count = st.slider("Discoveries", 1, 20, 5, key="disc_k")
        col1, col2 = st.columns(2)
        with col1:
            dry_run = st.checkbox("Dry run", value=False)
            fixtures = st.checkbox("Offline fixtures", value=False, key="disc_fx")
            market = _market_select("disc_market")
        with col2:
            persona = st.selectbox(
                "Persona", ["", "shark", "minimalist", "academic"],
                index=0, key="disc_persona")
            board = st.checkbox("Advisory Board", value=False, key="disc_board")
        if st.form_submit_button("Launch discover", type="primary"):
            _launch_discover(count, dry_run, fixtures, persona, board, market=market)


def _scope_hint(mode: str, candidates: int, operator: str, fixtures: bool):
    if fixtures:
        st.caption("Offline: fixtures, no API cost, ~30s")
        return
    checks = _ESTIMATED_CHECKS_PER_CANDIDATE
    latency = {"vet": "~1–5 min", "signal": "~5–15 min", "generate": "~2–8 min"}.get(
        mode, "~1–5 min")
    cost_per = 0.003 if operator in ("claude",) else 0.001
    st.caption(
        f"~{candidates} × {checks} checks · {latency} · "
        f"est. ${candidates * checks * cost_per:.3f}"
    )


def _maybe_operator(argv: list[str], operator: str) -> list[str]:
    if operator and operator != "(config)":
        argv += ["--operator", operator]
    return argv


def _maybe_scope(argv: list[str], *, lane: str = "", market: str = "",
                 archetype: str = "", profile: str = "") -> list[str]:
    if lane:
        argv += ["--lane", lane]
    if market:
        argv += ["--market", market]
    if archetype:
        argv += ["--archetype", archetype]
    if profile:
        argv += ["--profile", profile]
    return argv


def _launch_vet(title, one_liner, why_now, lane, operator, fixtures, publish,
                persona, board, market="", archetype=""):
    argv = [_sys.executable, "-m", "prospector.run", "vet", "--title", title]
    argv = _maybe_operator(argv, operator)
    argv = _maybe_scope(argv, lane=lane, market=market, archetype=archetype)
    if one_liner:
        argv += ["--one-liner", one_liner]
    if why_now:
        argv += ["--why-now", why_now]
    if persona:
        argv += ["--persona", persona]
    if board:
        argv += ["--board"]
    if fixtures:
        argv += ["--fixtures", "fixtures/golden_fixtures.json"]
    if publish:
        argv += ["--publish"]
    _do_launch(argv)


def _launch_signal(text, count, lane, operator, fixtures, publish, persona, board,
                   market="", archetype=""):
    argv = [_sys.executable, "-m", "prospector.run", "signal",
            "--text", text, "--count", str(count)]
    argv = _maybe_operator(argv, operator)
    argv = _maybe_scope(argv, lane=lane, market=market, archetype=archetype)
    if persona:
        argv += ["--persona", persona]
    if board:
        argv += ["--board"]
    if fixtures:
        argv += ["--fixtures", "fixtures/golden_fixtures.json"]
    if publish:
        argv += ["--publish"]
    _do_launch(argv)


def _launch_generate(candidates, exploration, lane, operator, fixtures, persona, board,
                     market="", archetype="", profile="", publish=False):
    argv = [_sys.executable, "-m", "prospector.run", "generate",
            "--candidates", str(candidates),
            "--exploration", str(exploration)]
    argv = _maybe_operator(argv, operator)
    argv = _maybe_scope(argv, lane=lane, market=market, archetype=archetype,
                        profile=profile)
    if persona:
        argv += ["--persona", persona]
    if board:
        argv += ["--board"]
    if fixtures:
        argv += ["--fixtures", "fixtures/golden_fixtures.json"]
    if publish:
        argv += ["--publish"]
    _do_launch(argv)


def _launch_discover(count, dry_run, fixtures, persona, board, market=""):
    argv = [_sys.executable, "-m", "prospector.run", "discover",
            "--count", str(count)]
    argv = _maybe_scope(argv, market=market)
    if dry_run:
        argv += ["--dry-run"]
    if persona:
        argv += ["--persona", persona]
    if board:
        argv += ["--board"]
    if fixtures:
        argv += ["--fixtures", "fixtures/golden_fixtures.json"]
    _do_launch(argv)


def _do_launch(argv: list[str]):
    if "--publish" in argv:
        from prospector.control_center.readers import load_certification
        cert = load_certification()
        if not cert.get("certified"):
            st.error("Publish blocked: config not certified by a passing golden run.")
            return
    try:
        job_id = _runner.launch(argv)
        st.success(f"Launched `{job_id}`")
        st.rerun()
    except RuntimeError as e:
        st.error(f"{e}")
    except Exception as e:
        st.error(f"Launch failed: {e}")
