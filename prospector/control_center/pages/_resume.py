"""Resume & Queue — manage pending signals and DEFER backlog."""
from __future__ import annotations

import streamlit as st

import sys as _sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

from prospector.control_center import runner as _runner
from prospector.control_center import readers


def render():
    st.title("⏳ Resume & Queue")

    # ── Moat health gate ───────────────────────────────────────────────────
    health = readers.load_provider_health()
    moat_down = readers.moat_down(health)

    if moat_down:
        st.error("🚨 Moat is down — re-vet buttons are disabled. "
                 "Retry when Claude+Gemini recover.")

    # ── DEFER queue ────────────────────────────────────────────────────────
    st.subheader("⏸ DEFER queue (moat exhausted at verdict time)")
    defer_rows = readers.catalogue_index(decision="defer")
    if not defer_rows:
        st.success("No DEFER candidates — the queue is clear.")
    else:
        st.info(f"{len(defer_rows)} candidate(s) deferred. Re-vet them when the moat recovers.")

        display = []
        for r in defer_rows:
            display.append({
                "id": (r.get("candidate_id") or "")[:8],
                "title": r.get("title") or "(untitled)",
                "gate_fired": r.get("gate_fired") or "moat_exhausted",
                "created_at": r.get("created_at") or "—",
                "full_id": r.get("candidate_id") or "",
            })

        st.dataframe(
            display,
            use_container_width=True,
            hide_index=True,
            column_config={
                "id": st.column_config.TextColumn("id", width="small"),
                "title": st.column_config.TextColumn("title", width="large"),
                "gate_fired": st.column_config.TextColumn("gate", width="medium"),
                "created_at": st.column_config.TextColumn("created", width="medium"),
                "full_id": st.column_config.TextColumn("candidate_id", width="small"),
            },
        )

        col1, col2 = st.columns(2)
        with col1:
            disabled = moat_down
            tooltip = "Disabled while moat is down" if disabled \
                      else "Launch vet --resume for all DEFER candidates"
            if st.button("🔄 Re-vet all DEFER",
                        disabled=disabled,
                        help=tooltip):
                _launch_resume("vet")
        with col2:
            if st.button("🗑 Clear DEFER queue",
                        help="Remove DEFER markers without re-vetting (use with care — "
                             "candidates will be silently dropped)"):
                _clear_defer_queue()
                st.rerun()

    st.divider()

    # ── Pending signals ────────────────────────────────────────────────────
    st.subheader("⏳ Pending signals (generation chain exhausted)")
    pending = readers.load_pending_signals()
    if not pending:
        st.success("No pending signals — the generation chain is healthy.")
    else:
        st.info(f"{len(pending)} signal(s) saved for resume.")
        for p in pending:
            key = p.get("key") or p.get("_filename", "?").replace(".json", "")
            signal_text = p.get("signal_text", "")[:80]
            with st.expander(f"📌 `{key[:8]}` — {signal_text[:50]}…"):
                st.text(signal_text)
                col1, col2 = st.columns(2)
                with col1:
                    if st.button(f"🔄 Retry generation",
                               key=f"retry_{key}"):
                        _retry_pending_signal(p)
                with col2:
                    st.button(f"🗑 Discard",
                             key=f"discard_{key}",
                             help="Delete this pending signal without resuming")

        st.divider()
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔄 Resume all generation"):
                _launch_resume("generate")
        with col2:
            if st.button("🗑 Discard all pending",
                        help="Delete all pending signals without resuming"):
                _clear_pending_signals()
                st.rerun()

    st.divider()

    # ── Run history ────────────────────────────────────────────────────────
    st.subheader("📋 Run history")
    jobs = _runner.load_jobs()
    if not jobs:
        st.info("No run history yet. Launch a run from the **Launch** page.")
        return

    sorted_jobs = sorted(jobs, key=lambda j: j.get("start_ts", 0), reverse=True)
    display = []
    for j in sorted_jobs[:50]:
        status = j.get("status", "?")
        label = {
            "running": "🟡 Running",
            "succeeded": "✅ Succeeded",
            "failed": "❌ Failed",
            "cancelled": "⚠️ Cancelled",
            "deferred": "⏸ Deferred",
            "queued": "⏳ Queued",
            "unknown": "❓ Unknown",
        }.get(status, status)
        from datetime import datetime
        ts = j.get("start_ts", 0)
        dt = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else "—"
        display.append({
            "job_id": (j.get("job_id", "") or "")[:8],
            "status": label,
            "command": " ".join(j.get("argv", []))[:55],
            "started": dt,
            "elapsed_s": j.get("elapsed_s", "—"),
            "cost_usd": f"${j.get('cost_usd', 0):.4f}" if isinstance(j.get("cost_usd"), float) else "—",
        })

    st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "job_id": st.column_config.TextColumn("job", width="small"),
            "status": st.column_config.TextColumn("status", width="small"),
            "command": st.column_config.TextColumn("command"),
            "started": st.column_config.TextColumn("started", width="medium"),
            "elapsed_s": st.column_config.TextColumn("elapsed (s)", width="small"),
            "cost_usd": st.column_config.TextColumn("cost", width="small"),
        },
    )

    # ── Log viewer for selected job ─────────────────────────────────────────
    st.subheader("📄 Job log viewer")
    job_options = {j.get("job_id", ""): j for j in sorted_jobs}
    if job_options:
        selected_id = st.selectbox("Select a job to view its log",
                                  [""] + list(job_options.keys()),
                                  format_func=lambda x: x[:8] if x else "—")
        if selected_id:
            log_lines = _runner.get_log_lines(selected_id, n=500)
            if log_lines:
                st.code("\n".join(log_lines), language="bash", height=300)
            else:
                st.info("No log available for this job.")


def _launch_resume(mode: str):
    """Launch a resume run via the runner module."""
    try:
        if mode == "vet":
            argv = ["python", "-m", "prospector.run", "vet", "--resume"]
        else:
            argv = ["python", "-m", "prospector.run", "generate", "--resume"]
        job_id = _runner.launch(argv)
        st.success(f"Resume run launched: `{job_id}`. Live log will appear on the Launch page.")
        st.rerun()
    except RuntimeError as e:
        st.error(f"❌ {e}")
    except Exception as e:
        st.error(f"Failed to launch resume: {e}")


def _retry_pending_signal(p: dict):
    """Retry a single pending signal by launching generate with its key."""
    try:
        key = p.get("key") or ""
        argv = ["python", "-m", "prospector.run", "generate", "--resume"]
        if key:
            argv += ["--key", key]
        job_id = _runner.launch(argv)
        st.success(f"Resume run launched: `{job_id}`")
        st.rerun()
    except RuntimeError as e:
        st.error(f"❌ {e}")
    except Exception as e:
        st.error(f"Retry failed: {e}")


def _clear_defer_queue():
    """Remove DEFER markers from the catalogue (set decision='' in SQLite).

    This is a safety-unpleasant operation — candidates are silently dropped from
    the DEFER view. They still exist as JSON files. Invalidate the catalogue index cache.
    """
    import sqlite3
    db_path = Path("store/prospector.db")
    if not db_path.exists():
        return
    try:
        conn = sqlite3.connect(str(db_path), timeout=10.0)
        conn.execute("UPDATE dossiers SET decision='' WHERE decision='defer'")
        conn.commit()
        conn.close()
        # Invalidate cache
        readers.catalogue_index.clear()
        st.success("DEFER markers cleared from the catalogue index. "
                   "Dossier JSON files are preserved.")
    except Exception as e:
        st.error(f"Failed to clear DEFER queue: {e}")


def _clear_pending_signals():
    """Delete all pending signal files from signals/pending/."""
    pending_dir = Path("signals/pending")
    if not pending_dir.exists():
        return
    count = 0
    for p in pending_dir.glob("*.json"):
        try:
            p.unlink()
            count += 1
        except OSError:
            pass
    # Invalidate cache
    readers.load_pending_signals.clear()
    st.success(f"Discarded {count} pending signal(s).")
