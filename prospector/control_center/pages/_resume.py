"""Resume & Queue — DEFER backlog, pending signals, run history + logs."""
from __future__ import annotations

import sys as _sys
from datetime import datetime
from pathlib import Path

import streamlit as st

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

from prospector import paths
from prospector.control_center import readers
from prospector.control_center import runner as _runner
from prospector.control_center.components.chrome import (
    job_log_path,
    log_panel,
    page_hero,
    resolve_log_text,
    tone_from_job_status,
)


def render():
    health = readers.load_provider_health()
    moat_is_down = readers.moat_down(health)
    defer_rows = readers.catalogue_index(decision="defer")
    pending = readers.load_pending_signals()

    try:
        from prospector.control_center.runner import filter_production_jobs
        jobs = filter_production_jobs(_runner.load_jobs())
    except Exception:
        jobs = _runner.load_jobs()

    active = next((j for j in jobs if j.get("status") == "running"), None)
    finished = [j for j in jobs if j.get("status") not in ("running", "queued")]
    latest = max(finished, key=lambda j: j.get("start_ts", 0)) if finished else None

    n_def = len(defer_rows)
    n_pend = len(pending)
    if moat_is_down:
        glance = f"Moat down · {n_def} DEFER · {n_pend} pending — re-vet locked"
        tone = "fail"
    elif n_def or n_pend:
        glance = f"{n_def} DEFER · {n_pend} pending signals · ready to resume"
        tone = "warn"
    else:
        glance = readers.glance_status(active, latest) if (active or latest) else "Queues clear"
        tone = tone_from_job_status((active or latest or {}).get("status")) if (active or latest) else "ok"

    page_hero("Resume & Queue", glance, tone=tone)

    if moat_is_down:
        st.error("Moat down — re-vet disabled until Claude/Gemini recover.")

    # Primary actions
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button(
            f"Re-vet all DEFER ({n_def})",
            type="primary",
            disabled=moat_is_down or n_def == 0,
            use_container_width=True,
            key="revet_all",
        ):
            _launch_resume("vet")
    with c2:
        if st.button(
            f"Resume generation ({n_pend})",
            disabled=n_pend == 0,
            use_container_width=True,
            key="resume_gen",
        ):
            _launch_resume("generate")
    with c3:
        if st.button("Open Launch", use_container_width=True, key="resume_to_launch"):
            from prospector.control_center.components.chrome import go_page
            go_page("launcher")

    # DEFER table
    st.markdown("**DEFER queue**")
    if not defer_rows:
        st.caption("Empty.")
    else:
        display = [{
            "id": (r.get("candidate_id") or "")[:8],
            "title": r.get("title") or "(untitled)",
            "gate": r.get("gate_fired") or "moat_exhausted",
            "created": (r.get("created_at") or "—")[:19],
            "candidate_id": r.get("candidate_id") or "",
        } for r in defer_rows]
        st.dataframe(display, use_container_width=True, hide_index=True, height=220)
        if st.button("Clear DEFER markers", key="clear_defer", help="Drops DEFER index rows; JSON kept"):
            _clear_defer_queue()
            st.rerun()

    # Pending signals
    st.markdown("**Pending signals**")
    if not pending:
        st.caption("Empty.")
    else:
        for p in pending:
            key = p.get("key") or p.get("_filename", "?").replace(".json", "")
            signal_text = p.get("signal_text", "") or ""
            with st.expander(f"{key[:10]} — {signal_text[:60]}"):
                st.text(signal_text)
                b1, b2 = st.columns(2)
                with b1:
                    if st.button("Retry", key=f"retry_{key}"):
                        _retry_pending_signal(p)
                with b2:
                    if st.button("Discard", key=f"discard_{key}"):
                        _discard_one_pending(p)
                        st.rerun()
        if st.button("Discard all pending", key="discard_all_pending"):
            _clear_pending_signals()
            st.rerun()

    # Run history + log (production jobs only)
    st.markdown("**Run history**")
    if not jobs:
        st.caption("No production runs yet.")
        return

    sorted_jobs = sorted(jobs, key=lambda j: j.get("start_ts", 0), reverse=True)
    display = []
    for j in sorted_jobs[:40]:
        status = j.get("status", "?")
        ts = j.get("start_ts", 0)
        dt = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else "—"
        # One dtype per column — see _overview._render_recent_runs: an em-dash beside ints
        # makes Arrow refuse the whole table.
        raw_elapsed = j.get("elapsed_s")
        display.append({
            "job_id": j.get("job_id", ""),
            "status": status,
            "command": readers.summarize_job_command(j.get("argv")),
            "started": dt,
            "elapsed_s": f"{int(raw_elapsed)}s" if isinstance(raw_elapsed, (int, float)) else "—",
            "outcome": readers.job_outcome_summary(j),
        })
    st.dataframe(display, use_container_width=True, hide_index=True, height=240)

    job_options = {j.get("job_id", ""): j for j in sorted_jobs if j.get("job_id")}
    ids = list(job_options.keys())
    default_id = (active or latest or {}).get("job_id") or (ids[0] if ids else "")
    default_idx = ids.index(default_id) if default_id in ids else 0
    selected_id = st.selectbox(
        "Job log",
        ids,
        index=default_idx if ids else 0,
        format_func=lambda x: (
            f"{x} · {readers.summarize_job_command(job_options[x].get('argv'))} · "
            f"{job_options[x].get('status')}"
        ),
    )
    if selected_id:
        job = job_options[selected_id]
        log_panel(
            resolve_log_text(job, n=400),
            path=job_log_path(job),
            height=320,
            key=f"resume_log_{selected_id}",
            empty_hint="No log available for this job.",
        )


def _launch_resume(mode: str):
    try:
        if mode == "vet":
            argv = [_sys.executable, "-m", "prospector.run", "vet", "--resume"]
        else:
            argv = [_sys.executable, "-m", "prospector.run", "generate", "--resume"]
        job_id = _runner.launch(argv)
        st.success(f"Launched `{job_id}` — watch Launch for live log.")
        st.rerun()
    except RuntimeError as e:
        st.error(str(e))
    except Exception as e:
        st.error(f"Failed to launch resume: {e}")


def _retry_pending_signal(p: dict):
    try:
        key = p.get("key") or ""
        argv = [_sys.executable, "-m", "prospector.run", "generate", "--resume"]
        if key:
            argv += ["--key", key]
        job_id = _runner.launch(argv)
        st.success(f"Launched `{job_id}`")
        st.rerun()
    except RuntimeError as e:
        st.error(str(e))
    except Exception as e:
        st.error(f"Retry failed: {e}")


def _discard_one_pending(p: dict):
    pending_dir = paths.repo_path("signals", "pending")
    name = p.get("_filename") or ""
    key = p.get("key") or ""
    targets = []
    if name:
        targets.append(pending_dir / name)
    if key:
        targets.append(pending_dir / f"{key}.json")
    for t in targets:
        try:
            if t.exists():
                t.unlink()
        except OSError:
            pass
    try:
        readers.load_pending_signals.clear()
    except Exception:
        pass


def _clear_defer_queue():
    import sqlite3
    db_path = paths.store_path("prospector.db")
    if not db_path.exists():
        return
    try:
        conn = sqlite3.connect(str(db_path), timeout=10.0)
        conn.execute("UPDATE dossiers SET decision='' WHERE decision='defer'")
        conn.commit()
        conn.close()
        readers.catalogue_index.clear()
        st.success("DEFER markers cleared. Dossier JSON preserved.")
    except Exception as e:
        st.error(f"Failed to clear DEFER queue: {e}")


def _clear_pending_signals():
    pending_dir = paths.repo_path("signals", "pending")
    if not pending_dir.exists():
        return
    count = 0
    for p in pending_dir.glob("*.json"):
        try:
            p.unlink()
            count += 1
        except OSError:
            pass
    readers.load_pending_signals.clear()
    st.success(f"Discarded {count} pending signal(s).")
