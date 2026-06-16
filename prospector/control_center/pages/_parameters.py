"""Parameters — config.yaml editor with safety guards (§3.5).

All edits are staged in session_state until "Save changes" is clicked.
The diff is shown before write. Moat-affecting edits are flagged uncertified.
"""
from __future__ import annotations

import streamlit as st
from pathlib import Path

from prospector.control_center import config_editor as _ce
from prospector.control_center import readers


def render():
    st.title("⚙️ Parameters")

    # ── Certification banner ─────────────────────────────────────────────────
    cert = readers.load_certification()
    if cert.get("certified"):
        st.success("✅ Configuration is certified by a passing golden run. "
                   "Publish is enabled.")
    else:
        st.warning("⚠️ Configuration is **uncertified** — a golden-set regression "
                   "is required before publishing. Publish is disabled.")

    # ── Initialise staged config ──────────────────────────────────────────
    _init_staged()

    cfg = st.session_state["staged_config"] or _ce.load_config_raw()
    orig_mtime = st.session_state.get("_config_mtime", 0.0)

    # ── Raw YAML view ─────────────────────────────────────────────────────
    with st.expander("📄 Raw config.yaml (read-only)"):
        st.code(readers.load_config_dict(), language="yaml", height=300)

    # ── Backup management ──────────────────────────────────────────────────
    with st.expander("💾 Config backups"):
        backups = _ce.list_backups()
        if not backups:
            st.info("No backups yet.")
        else:
            for b in backups[:10]:
                col1, col2 = st.columns([4, 1])
                from datetime import datetime
                ts = datetime.fromtimestamp(b["mtime"]).strftime("%Y-%m-%d %H:%M")
                with col1:
                    st.caption(f"`{b['filename']}`  {ts}  {b['size']:,}B")
                with col2:
                    if st.button("↩️ Restore", key=f"bak_{b['filename']}"):
                        ok, msg = _ce.restore_backup(b["filename"])
                        if ok:
                            st.session_state["staged_config"] = _ce.load_config_raw()
                            st.session_state["_config_mtime"] = _ce.get_config_mtime()
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)

    st.divider()

    # ── Groups ─────────────────────────────────────────────────────────────
    _render_thresholds(cfg)
    st.divider()
    _render_hard_gates(cfg)
    st.divider()
    _render_weights(cfg)
    st.divider()
    _render_spend_guard(cfg)
    st.divider()
    _render_operator_routing(cfg)
    st.divider()
    _render_retrieval(cfg)
    st.divider()
    _render_lanes(cfg)
    st.divider()
    _render_personas(cfg)

    st.divider()
    _render_diff_and_save(cfg, orig_mtime)
...
# ---------------------------------------------------------------------------
# Personas
# ---------------------------------------------------------------------------

def _render_personas(cfg: dict):
    st.subheader("👤 Personas (Analytical Multi-Tenancy)")
    st.caption("A persona 'tints' the entire pipeline with a specific analytical bias. "
               "Generation, verdicts, and adversarial cases are all affected.")

    personas = cfg.get("personas", {})
    active_persona = cfg.get("active_persona", "")

    st.write(f"Default persona: `{active_persona or '(none)'}`")

    for p_name, p_cfg in personas.items():
        with st.expander(f"Persona: **{p_name}**"):
            # Threshold overrides
            st.markdown("**Threshold Overrides**")
            p_thresh = p_cfg.get("thresholds", {})
            min_comp = p_thresh.get("min_composite_to_pass", 3.2)
            new_min = st.number_input(
                f"Min composite to PASS ({p_name})", 0.0, 20.0, float(min_comp), 0.1,
                key=f"p_thresh_{p_name}")
            _update_staged(cfg, f"personas.{p_name}.thresholds.min_composite_to_pass", new_min)

            # Biases
            st.markdown("**Analytical Biases**")
            gen_bias = st.text_area(
                "Generation bias", p_cfg.get("generation_bias", ""),
                help="Injected into the generation system prompt.",
                key=f"p_gen_{p_name}")
            verdict_bias = st.text_area(
                "Verdict bias", p_cfg.get("verdict_bias", ""),
                help="Injected into the verdict system prompt.",
                key=f"p_ver_{p_name}")
            adv_bias = st.text_area(
                "Adversarial bias", p_cfg.get("adversarial_bias", ""),
                help="Injected into the adversarial system prompt.",
                key=f"p_adv_{p_name}")

            _update_staged(cfg, f"personas.{p_name}.generation_bias", gen_bias)
            _update_staged(cfg, f"personas.{p_name}.verdict_bias", verdict_bias)
            _update_staged(cfg, f"personas.{p_name}.adversarial_bias", adv_bias)

            if gen_bias != p_cfg.get("generation_bias") or \
               verdict_bias != p_cfg.get("verdict_bias") or \
               adv_bias != p_cfg.get("adversarial_bias"):
                st.session_state["_changed_moat"] = True


# ---------------------------------------------------------------------------
# Initialise staged config
# ---------------------------------------------------------------------------

def _init_staged():
    """Set up the staged config in session_state on first load."""
    if st.session_state.get("staged_config") is None:
        st.session_state["staged_config"] = _ce.load_config_raw()
    if "_config_mtime" not in st.session_state:
        st.session_state["_config_mtime"] = _ce.get_config_mtime()
    if "_changed_moat" not in st.session_state:
        st.session_state["_changed_moat"] = False


# ---------------------------------------------------------------------------
# Threshold controls
# ---------------------------------------------------------------------------

def _render_thresholds(cfg: dict):
    st.subheader("📊 Thresholds")
    col1, col2 = st.columns(2)

    thresh = cfg.get("thresholds", {})
    conf_floor = thresh.get("confidence_floor", 0.6)
    min_comp = thresh.get("min_composite_to_pass", 3.2)

    new_conf = col1.slider(
        "Confidence floor", 0.0, 1.0, conf_floor, 0.05,
        help="Minimum confidence per check to consider it valid")
    new_comp = col2.number_input(
        "Min composite to PASS", 0.0, 20.0, min_comp, 0.1,
        help="Minimum composite score for a PASS verdict")

    _update_staged(cfg, "thresholds.confidence_floor", new_conf)
    _update_staged(cfg, "thresholds.min_composite_to_pass", new_comp)

    if new_conf != conf_floor:
        st.session_state["_changed_moat"] = True


# ---------------------------------------------------------------------------
# Hard gates
# ---------------------------------------------------------------------------

def _render_hard_gates(cfg: dict):
    st.subheader("🚪 Hard gates (kill-on-refuted)")
    st.caption("A gate fires when its check returns REFUTED. Candidates killed "
               "at a hard gate stop immediately — no score is computed.")

    gate_checks = [
        ("pain_reality",     "Pain is real and felt by the buyer"),
        ("value_durability", "Value is durable (12+ month moat)"),
        ("incumbency",       "Incumbent can be displaced"),
        ("payer_solvency",   "The payer is creditworthy"),
        ("distribution",     "Distribution is achievable"),
        ("legality",         "Legality: no fatal legal blockers"),
    ]

    gates = cfg.get("hard_gates", [])
    active_gates: set[str] = set()
    for g in gates:
        active_gates.update(g.keys())

    new_gates: dict[str, bool] = {}
    cols = st.columns(3)
    for i, (check, description) in enumerate(gate_checks):
        with cols[i % 3]:
            active = check in active_gates
            new_gates[check] = st.checkbox(
                f"**{check}**",
                active,
                help=description,
            )
            if new_gates[check] != active:
                st.session_state["_changed_moat"] = True

    _update_staged(cfg, "__hard_gates__", new_gates)


# ---------------------------------------------------------------------------
# Score weights
# ---------------------------------------------------------------------------

def _render_weights(cfg: dict):
    st.subheader("⚖️ Score weights (must sum to 1.0)")
    weights_cfg = cfg.get("weights", {})
    default_weights = {
        "pain_acuity":         0.20,
        "money_provability":   0.20,
        "automatability":      0.20,
        "distribution":       0.15,
        "defensibility":      0.15,
        "build_feasibility":  0.10,
    }
    w = {k: weights_cfg.get(k, v) for k, v in default_weights.items()}

    new_weights: dict[str, float] = {}
    cols = st.columns(3)
    for i, (k, v) in enumerate(w.items()):
        with cols[i % 3]:
            new_weights[k] = st.slider(
                k, 0.0, 1.0, float(v), 0.05,
                help=f"Scoring weight for {k} (default: {v:.2f})")

    total = sum(new_weights.values())
    col1, col2 = st.columns([1, 3])
    with col1:
        st.metric("Sum", f"{total:.2f}")
    with col2:
        if abs(total - 1.0) > 0.005:
            st.error(f"Weights sum to {total:.4f} — save will be BLOCKED")
            if st.button("🔄 Normalise to 1.0"):
                norm = {k: round(v / total, 4) for k, v in new_weights.items()}
                for k, v in norm.items():
                    st.session_state[f"_weight_{k}"] = v
                st.rerun()
        else:
            st.success("Weights sum to 1.0 ✓")

    _update_staged(cfg, "__weights__", new_weights)


# ---------------------------------------------------------------------------
# Spend guard
# ---------------------------------------------------------------------------

def _render_spend_guard(cfg: dict):
    st.subheader("💰 Spend guard")
    spend = cfg.get("spend", {})
    col1, col2 = st.columns(2)
    new_daily_cap = col1.number_input(
        "Daily cap (USD)", 0.0, 1000.0,
        float(spend.get("daily_cap_usd", 50.0)), 1.0)
    new_warn_at = col2.number_input(
        "Warn at (USD)", 0.0, 1000.0,
        float(spend.get("warn_at_usd", 40.0)), 1.0)
    _update_staged(cfg, "spend.daily_cap_usd", new_daily_cap)
    _update_staged(cfg, "spend.warn_at_usd", new_warn_at)


# ---------------------------------------------------------------------------
# Operator routing
# ---------------------------------------------------------------------------

def _render_operator_routing(cfg: dict):
    st.subheader("🧠 Operator routing")
    st.caption("Moat order: models that run kill-check verdicts and adversarial passes. "
               "Non-critical chain: models for generation/prescreen/score only.")

    op = cfg.get("operator", "")
    new_op = st.selectbox(
        "Primary operator",
        ["", "mock", "gemini_cli", "claude", "gemini"],
        index=["", "mock", "gemini_cli", "claude", "gemini"].index(op) if op in ["", "mock", "gemini_cli", "claude", "gemini"] else 0,
    )
    _update_staged(cfg, "operator", new_op)

    moat_order = cfg.get("moat_order", [])
    st.caption(f"Moat order (current): {moat_order or [op]}")


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

def _render_retrieval(cfg: dict):
    st.subheader("🔍 Retrieval")
    retr = cfg.get("retrieval", {})
    col1, col2, col3 = st.columns(3)
    new_qpc = col1.slider(
        "Queries per check", 1, 10,
        int(retr.get("queries_per_check", 3)), 1,
        help="Number of search queries generated per kill-check")
    new_rpq = col2.slider(
        "Results per query", 1, 20,
        int(retr.get("results_per_query", 5)), 1,
        help="Max results per query")
    new_retries = col3.slider(
        "Search retries", 0, 5,
        int(retr.get("search_retries", 2)), 1,
        help="Retry count on search failure")
    _update_staged(cfg, "retrieval.queries_per_check", new_qpc)
    _update_staged(cfg, "retrieval.results_per_query", new_rpq)
    _update_staged(cfg, "retrieval.search_retries", new_retries)


# ---------------------------------------------------------------------------
# Ambition lanes
# ---------------------------------------------------------------------------

def _render_lanes(cfg: dict):
    st.subheader("🛤 Ambition lanes")
    lanes = cfg.get("lanes", {})
    active_lane = cfg.get("active_lane", "")
    active_lanes = cfg.get("active_lanes", [])

    if lanes:
        for lane_name, lane_cfg in lanes.items():
            with st.expander(f"Lane: **{lane_name}**"):
                st.caption(f"Type: {lane_cfg.get('type', '?')}")
                hard_gates = lane_cfg.get("hard_gates", [])
                st.caption(f"Hard gates: {hard_gates}")
    else:
        st.info("No lanes configured. Set `active_lane` in config.yaml to enable.")

    st.caption(f"Active lane: `{active_lane}`")
    st.caption(f"Active lanes: `{active_lanes}`")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _update_staged(cfg: dict, key: str, value):
    """Write a value into the staged config in session_state."""
    import copy
    if "staged_config" not in st.session_state:
        st.session_state["staged_config"] = copy.deepcopy(cfg)

    staged = st.session_state["staged_config"]

    if key.startswith("__"):
        # Special keys: __hard_gates__, __weights__
        if key == "__hard_gates__":
            gates = [{"k": True} for k, v in value.items() if v]
            staged["hard_gates"] = gates
        elif key == "__weights__":
            staged["weights"] = value
        return

    # Dot-notation path: "thresholds.confidence_floor"
    parts = key.split(".")
    target = staged
    for p in parts[:-1]:
        target = target.setdefault(p, {})
    target[parts[-1]] = value
    st.session_state["staged_config"] = staged


def _render_diff_and_save(cfg: dict, orig_mtime: float):
    """Show the diff preview and Save / Reset buttons."""
    old_cfg = _ce.load_config_raw()
    new_cfg = st.session_state.get("staged_config", old_cfg)
    diff = _ce.diff_configs(old_cfg, new_cfg)

    st.subheader("🔍 Change diff")
    if diff:
        st.code(diff, language="yaml", height=200)
    else:
        st.info("No changes detected.")

    # ── Moat-affecting warning ──────────────────────────────────────────────
    moat_affecting = _ce.is_moat_affecting(old_cfg, new_cfg)
    st.session_state["_changed_moat"] = moat_affecting

    if moat_affecting:
        st.warning("🚨 This change affects the moat. Saving will mark the config "
                   "as **uncertified**. Run golden regression to re-certify before publishing.")
        if st.button("🎯 Run golden regression",
                     help="Launch pytest -k golden to verify prompts haven't regressed"):
            _run_golden_regression()

    st.divider()

    # ── Save / Reset ───────────────────────────────────────────────────────
    col1, col2, col3 = st.columns(3)

    # Validate weights
    new_cfg = st.session_state.get("staged_config", old_cfg)
    weights = new_cfg.get("weights", {})
    total_w = sum(v for v in weights.values() if isinstance(v, (int, float)))
    weights_ok = abs(total_w - 1.0) <= 0.005

    with col1:
        save_disabled = not weights_ok or not diff
        tooltip = "Weights must sum to 1.0" if not weights_ok else \
                  "No changes to save" if not diff else ""
        if st.button("💾 Save changes", type="primary",
                    disabled=save_disabled, help=tooltip):
            ok, msg = _ce.write_config(new_cfg, moat_affecting, orig_mtime)
            if ok:
                st.session_state["staged_config"] = _ce.load_config_raw()
                st.session_state["_config_mtime"] = _ce.get_config_mtime()
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)

    with col2:
        if st.button("↩️ Reset to saved"):
            st.session_state["staged_config"] = _ce.load_config_raw()
            st.session_state["_config_mtime"] = _ce.get_config_mtime()
            st.session_state["_changed_moat"] = False
            st.rerun()

    with col3:
        if st.button("↪️ Discard all"):
            st.session_state["staged_config"] = _ce.load_config_raw()
            st.session_state["_changed_moat"] = False
            st.rerun()

    if not weights_ok:
        st.error(f"Weights sum to {total_w:.4f} — save is blocked.")


def _run_golden_regression():
    """Launch golden regression as a Streamlit rerun-safe subprocess."""
    import subprocess
    from pathlib import Path
    try:
        result = subprocess.run(
            [".venv/bin/python", "-m", "pytest", "tests/", "-k", "golden",
             "--tb=short", "-q"],
            capture_output=True, text=True, timeout=300,
            cwd=str(Path(__file__).resolve().parent.parent.parent.parent),
        )
        output = result.stdout[-2000:] if result.stdout else result.stderr[-2000:]
        st.code(output, language="bash")
        if result.returncode == 0:
            # Mark as certified
            cert = readers.load_certification()
            _ce.certify_from_golden(
                golden_run_id="regression_run",
                operator="regression",
                discrimination=0.0,
                floor=0.75,
                passed=True,
            )
            st.session_state["staged_config"] = _ce.load_config_raw()
            st.session_state["_changed_moat"] = False
            st.success("✅ Golden regression passed. Config is now certified. "
                       "Publish is enabled.")
            st.rerun()
        else:
            st.error("❌ Golden regression failed. Config remains uncertified.")
    except Exception as e:
        st.error(f"Regression run failed: {e}")
