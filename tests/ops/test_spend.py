"""R21 — the spend view tells the truth about today's money, or says it cannot.

WHAT THESE PIN, in the words of the defects they close. Each one is written so that REVERTING the
behaviour turns it red, not merely so that the current code passes:

  * **One reader.** `store/prospector.jsonl` is 193 MB and has exactly one supported parser
    (`scheduler/guard.py`). A hand-rolled sum returns a confident $0.00 on a day with real spend —
    the rows are keyed `timestamp`, and the metered leg is `event: "spend"` + `amount_usd`
    (memory: `never-hand-parse-the-spend-ledger`). `test_the_view_never_opens_the_ledger_itself`
    watches every open of the ledger during the call and demands the frame nearest the open be
    `guard.py`; adding a parse to `ops/spend.py` fails it.
  * **The probe.** R21's acceptance is "figure matches `guard.scan_today()`". Not "reconciles to":
    the test asserts equality against the guard's own call on the same store.
  * **The cap is config.** A literal $100 goes stale the day the founder raises it (it was $20
    until 2026-08-16). Two configs with different caps must produce two different caps.
  * **Honest nulls.** No spend, a twenty-minute-old day, an absent ledger, an unarmed cap, a clock
    behind the ledger — every one is `hit_at: None` plus a sentence. A confident null is the
    failure mode (memory: `a-saturated-metric-prints-as-a-confident-null`).
"""
from __future__ import annotations

import builtins
import io
import json
import sys
import types
from datetime import datetime
from pathlib import Path

import pytest

from prospector.ops import spend as S
from prospector.scheduler import guard as G


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
def _cfg(tmp_path, *, cap=100.0, warn=75.0, sub_cap=0.0, **extra):
    """A cfg with a REAL store_dir. A `Path`, not a str: `Store.__init__` calls `.mkdir()` on
    `cfg.store_dir`, and `paths.store_dir` raises rather than defaulting to a cwd-relative
    `store/` — which under pytest is the LIVE store."""
    return types.SimpleNamespace(
        store_dir=tmp_path,
        spend=types.SimpleNamespace(daily_cap_usd=cap, warn_at_usd=warn,
                                    daily_subscription_cap_usd=sub_cap),
        **extra)


def _at(day: str, hour: int, minute: int = 0) -> float:
    """Epoch for a LOCAL wall-clock moment — the clock both the guard and the view sum by."""
    return datetime.fromisoformat(f"{day}T{hour:02d}:{minute:02d}:00").timestamp()


def _ledger(tmp_path, rows: list[dict]) -> Path:
    p = tmp_path / "prospector.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return p


def _spend_row(day: str, amount: float, provider="minimax") -> dict:
    return {"timestamp": f"{day} 09:00:00,000", "event": "spend",
            "provider": provider, "amount_usd": amount}


def _cli_row(day: str, amount: float) -> dict:
    # No `event` key — this is exactly what separates the subscription leg (claude_cli.py:82).
    return {"timestamp": f"{day} 09:00:00,000", "message": "Claude CLI usage", "cost_usd": amount}


DAY = "2026-08-16"


# --------------------------------------------------------------------------- #
# The probe: the figure IS guard.scan_today()
# --------------------------------------------------------------------------- #
def test_the_figure_is_guard_scan_today_exactly(tmp_path):
    """R21's own probe. Both legs, against the one supported reader on the same store."""
    _ledger(tmp_path, [_spend_row(DAY, 1.25), _spend_row(DAY, 0.75),
                       _cli_row(DAY, 40.0), _spend_row("2026-08-15", 99.0)])
    cfg = _cfg(tmp_path)
    view = S.spend_view(cfg, now=_at(DAY, 12))

    metered, subscription = G.guard_from_config(cfg, today=DAY).scan_today()
    assert (metered, subscription) == (2.0, 40.0)          # the arithmetic, stated
    assert view["legs"]["metered"]["usd"] == metered        # the probe, asserted
    assert view["legs"]["subscription"]["usd"] == subscription
    assert view["day"] == DAY
    assert view["source"].endswith("scan_today()")


def test_yesterdays_rows_are_not_in_todays_figure(tmp_path):
    """The day bucket is the whole point of the rail; a view that summed the file would read 99."""
    _ledger(tmp_path, [_spend_row("2026-08-15", 99.0), _spend_row(DAY, 3.0)])
    view = S.spend_view(_cfg(tmp_path), now=_at(DAY, 12))
    assert view["legs"]["metered"]["usd"] == 3.0
    assert view["history"]["2026-08-15"]["metered"] == 99.0


# --------------------------------------------------------------------------- #
# No inline parse — the mutation test
# --------------------------------------------------------------------------- #
def _watch_ledger_opens(monkeypatch) -> list[tuple[str, str]]:
    """Record (ledger_path, nearest non-stdlib frame) for every open of a `prospector.jsonl`.

    Both `builtins.open` and `io.open` are patched: `Path.open`/`Path.read_text` go through
    `io.open`, so patching only the builtin would watch half the ways a module can read a file —
    and the half it missed is the convenient one somebody would reach for.
    """
    seen: list[tuple[str, str]] = []
    real_builtin, real_io = builtins.open, io.open
    # 3.14 ships pathlib as a PACKAGE, so "pathlib.py" alone matches nothing and the
    # nearest frame reads as stdlib — a skip list that misses is a watcher that
    # accuses the wrong module.
    skip = ("/pathlib/", "pathlib.py", "/io.py", "<frozen")

    def _nearest() -> str:
        frame = sys._getframe(2)
        while frame is not None and any(s in frame.f_code.co_filename for s in skip):
            frame = frame.f_back
        return frame.f_code.co_filename if frame else "?"

    def _spy(real):
        def wrapper(file, *a, **k):
            if str(file).endswith("prospector.jsonl"):
                seen.append((str(file), _nearest()))
            return real(file, *a, **k)
        return wrapper

    monkeypatch.setattr(builtins, "open", _spy(real_builtin))
    monkeypatch.setattr(io, "open", _spy(real_io))
    return seen


def test_the_view_never_opens_the_ledger_itself(tmp_path, monkeypatch):
    """Every read of the 193 MB ledger must be made BY `guard.py`, the one supported reader.

    Mutation check: this is the test that goes red the moment `ops/spend.py` opens the ledger to
    "just sum the provider column". The proof that the watcher works is the positive half — it
    DOES see guard's own opens — so a passing assertion cannot be an artefact of watching nothing.
    """
    _ledger(tmp_path, [_spend_row(DAY, 1.0)])
    seen = _watch_ledger_opens(monkeypatch)
    S.spend_view(_cfg(tmp_path), now=_at(DAY, 12))

    assert seen, "watcher saw no ledger open at all — the probe would pass vacuously"
    offenders = [s for s in seen if not s[1].endswith("scheduler/guard.py")]
    assert offenders == [], f"the ledger was opened outside guard.py: {offenders}"
    assert not any(S.__file__ == caller for _p, caller in seen)


def test_the_watcher_would_catch_a_hand_parse(tmp_path, monkeypatch):
    """Proves the guard-rail above fires on the BEFORE state: a module that reads the ledger
    directly is caught. Without this, `test_the_view_never_opens_the_ledger_itself` could be
    passing because the detector cannot see anything (memory: `prove-the-probe-fires-on-the-
    before-state`)."""
    ledger = _ledger(tmp_path, [_spend_row(DAY, 1.0)])
    seen = _watch_ledger_opens(monkeypatch)
    ledger.read_text()                                     # the forbidden shape, from this file
    offenders = [s for s in seen if not s[1].endswith("scheduler/guard.py")]
    assert offenders, "a direct read outside guard.py must be visible to the watcher"
    assert offenders[0][1].endswith("test_spend.py"), offenders


def test_the_view_reads_the_cached_scan_checkpoint(tmp_path):
    """"Reads the cached scan" is a number on screen, not a claim: offset + lag_bytes."""
    ledger = _ledger(tmp_path, [_spend_row(DAY, 1.0)])
    cfg = _cfg(tmp_path)
    S.spend_view(cfg, now=_at(DAY, 12))                    # first pass writes the checkpoint
    view = S.spend_view(cfg, now=_at(DAY, 12))             # second pass must find it

    assert view["cache"]["present"] is True
    assert view["cache"]["offset"] == ledger.stat().st_size
    assert view["cache"]["lag_bytes"] == 0
    assert view["cache"]["newest_day"] == DAY
    assert not any("no scan checkpoint" in w for w in view["warnings"])


def test_a_missing_checkpoint_is_warned_about_not_hidden(tmp_path):
    """A cold cache means the next read is a full 100s+ pass over the ledger. Say so."""
    _ledger(tmp_path, [_spend_row(DAY, 1.0)])
    view = S.spend_view(_cfg(tmp_path), now=_at(DAY, 12))
    assert any("no scan checkpoint" in w for w in view["warnings"])


# --------------------------------------------------------------------------- #
# The cap comes from config, never a literal
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("cap", [100.0, 250.0, 20.0])
def test_the_cap_is_read_from_config(tmp_path, cap):
    """Mutation check: a hardcoded $100 (the value live on 2026-08-16, raised from $20 that
    morning) fails two of these three. The key is reported alongside the number so a figure is
    never read against a ceiling nobody can find."""
    _ledger(tmp_path, [_spend_row(DAY, 1.0)])
    view = S.spend_view(_cfg(tmp_path, cap=cap), now=_at(DAY, 12))
    leg = view["legs"]["metered"]
    assert leg["cap_usd"] == cap
    assert leg["cap_key"] == "spend.daily_cap_usd"
    assert leg["remaining_usd"] == pytest.approx(cap - 1.0)


def test_the_warn_threshold_is_config_too(tmp_path):
    _ledger(tmp_path, [_spend_row(DAY, 80.0)])
    view = S.spend_view(_cfg(tmp_path, cap=100.0, warn=75.0), now=_at(DAY, 12))
    assert view["legs"]["metered"]["state"] == "warn"
    assert view["legs"]["metered"]["warn_key"] == "spend.warn_at_usd"

    quiet = S.spend_view(_cfg(tmp_path, cap=100.0, warn=90.0), now=_at(DAY, 12))
    assert quiet["legs"]["metered"]["state"] == "ok"


# --------------------------------------------------------------------------- #
# Projected hit-time: a measurement, or a null with a reason
# --------------------------------------------------------------------------- #
def test_a_measured_rate_projects_a_hit_time(tmp_path):
    """$60 by noon against a $100 cap is $5/h, so the cap lands 8h out — inside today."""
    _ledger(tmp_path, [_spend_row(DAY, 60.0)])
    p = S.spend_view(_cfg(tmp_path, cap=100.0), now=_at(DAY, 12))["legs"]["metered"]["projection"]
    assert p["rate_per_h"] == pytest.approx(5.0)
    assert p["hit_in_h"] == pytest.approx(8.0)
    assert p["hits_today"] is True
    assert p["hit_at"] and p["reason"] == "" and p["caveat"] == ""


def test_a_projection_past_local_midnight_says_the_counter_resets_first(tmp_path):
    """A true "hits in 19h" that lands after the daily counter resets answers a different
    question than the one asked. The caveat is the answer to the asked one."""
    _ledger(tmp_path, [_spend_row(DAY, 12.0)])
    p = S.spend_view(_cfg(tmp_path, cap=100.0), now=_at(DAY, 12))["legs"]["metered"]["projection"]
    assert p["hit_in_h"] == pytest.approx(88.0)
    assert p["hits_today"] is False
    assert "counter resets" in p["caveat"]


def test_no_spend_today_is_a_null_with_a_reason_not_never(tmp_path):
    _ledger(tmp_path, [_spend_row("2026-08-15", 50.0)])
    p = S.spend_view(_cfg(tmp_path), now=_at(DAY, 12))["legs"]["metered"]["projection"]
    assert p["hit_at"] is None and p["hit_in_h"] is None and p["rate_per_h"] is None
    assert "no spend recorded" in p["reason"] and "measured zero" in p["reason"]


def test_a_twenty_minute_old_day_refuses_to_extrapolate(tmp_path):
    """$5 in the first twenty minutes is not $360/day. The floor is why one burst cannot mint a
    hit-time an operator would plan around."""
    _ledger(tmp_path, [_spend_row(DAY, 5.0)])
    p = S.spend_view(_cfg(tmp_path), now=_at(DAY, 0, 20))["legs"]["metered"]["projection"]
    assert p["hit_at"] is None and p["rate_per_h"] is None
    assert "20 min of the local day" in p["reason"]


def test_at_the_cap_reports_the_rail_refusing_now_not_a_forecast(tmp_path):
    _ledger(tmp_path, [_spend_row(DAY, 120.0)])
    leg = S.spend_view(_cfg(tmp_path, cap=100.0), now=_at(DAY, 12))["legs"]["metered"]
    assert leg["state"] == "at_cap"
    assert leg["projection"]["hit_at"] is None
    assert "refusing work NOW" in leg["projection"]["reason"]


def test_an_unarmed_subscription_cap_is_uncapped_with_a_reason(tmp_path):
    """`daily_subscription_cap_usd: 0.0` is live config — report-only, not enforced. The leg is
    still shown, because printing the metered leg alone reads as total consumption."""
    _ledger(tmp_path, [_cli_row(DAY, 250.0), _spend_row(DAY, 1.0)])
    view = S.spend_view(_cfg(tmp_path, sub_cap=0.0), now=_at(DAY, 12))
    sub = view["legs"]["subscription"]
    assert sub["usd"] == 250.0 and sub["enforced"] is False and sub["state"] == "uncapped"
    assert sub["projection"]["hit_at"] is None
    assert "no ceiling configured (spend.daily_subscription_cap_usd" in sub["projection"]["reason"]
    assert sub["usd"] != view["legs"]["metered"]["usd"], "the two legs must never be one number"


def test_an_armed_subscription_cap_projects(tmp_path):
    _ledger(tmp_path, [_cli_row(DAY, 120.0)])
    p = S.spend_view(_cfg(tmp_path, sub_cap=240.0),
                     now=_at(DAY, 12))["legs"]["subscription"]["projection"]
    assert p["rate_per_h"] == pytest.approx(10.0) and p["hit_in_h"] == pytest.approx(12.0)


# --------------------------------------------------------------------------- #
# Unreadable is not zero
# --------------------------------------------------------------------------- #
def test_an_absent_ledger_is_unreadable_not_unspent(tmp_path):
    """`scan_today()` answers (0.0, 0.0) for a missing file exactly as for a quiet day. Only the
    caller can tell the operator which, and a $0.00 with no caveat reads as "nothing spent"."""
    view = S.spend_view(_cfg(tmp_path), now=_at(DAY, 12))
    assert view["ledger"]["present"] is False
    assert any("UNREADABLE, not unspent" in w for w in view["warnings"])
    assert view["legs"]["metered"]["projection"]["hit_at"] is None
    assert "UNREADABLE" in view["legs"]["metered"]["projection"]["reason"]


def test_a_torn_ledger_does_not_take_the_page_down(tmp_path):
    """A monitor that dies on a half-written line is down exactly when the thing it watches is
    busy. The complete rows still count; the torn tail does not."""
    p = tmp_path / "prospector.jsonl"
    p.write_text(json.dumps(_spend_row(DAY, 2.0)) + "\n"
                 + "{not json at all\n"
                 + json.dumps(_spend_row(DAY, 3.0))[:20])   # no trailing newline: mid-append
    view = S.spend_view(_cfg(tmp_path), now=_at(DAY, 12))
    assert view["legs"]["metered"]["usd"] == 2.0
    assert view["legs"]["metered"]["usd"] == G.guard_from_config(
        _cfg(tmp_path), today=DAY).scan_today()[0]


def test_a_clock_behind_the_ledger_kills_the_projection(tmp_path):
    """The gate `guard.evaluate()` refuses to generate on: the cap is summing a day the ledger
    cannot have rows for, so it reads $0.00 whatever was spent. A projection off that figure is
    worse than none — it says "plenty of headroom" precisely when the rail is inert."""
    _ledger(tmp_path, [_spend_row("2026-08-20", 40.0)])
    view = S.spend_view(_cfg(tmp_path), now=_at(DAY, 12))
    assert any("clock is behind the ledger" in w for w in view["warnings"])
    assert view["legs"]["metered"]["projection"]["hit_at"] is None
    assert "2026-08-20" in view["legs"]["metered"]["projection"]["reason"]


# --------------------------------------------------------------------------- #
# The per-role split: attributed only where attribution is sound
# --------------------------------------------------------------------------- #
def _roles(view, name):
    return next(r for r in view["roles"] if r["role"] == name)


def test_a_tier_serving_two_roles_makes_the_split_a_null_with_the_reason(tmp_path):
    """LIVE SHAPE on 2026-08-16: `minimax` heads both `verdict` and `noncritical`, and the cached
    scan buckets by day and leg — never by provider. So the metered leg cannot be split between
    them, and the honest output names the tier that makes it ambiguous rather than halving it."""
    _ledger(tmp_path, [_spend_row(DAY, 8.0)])
    cfg = _cfg(tmp_path, operator=["minimax", "claude_cli"], noncritical_operator=["minimax"])
    view = S.spend_view(cfg, now=_at(DAY, 12))

    verdict = _roles(view, "verdict")
    assert verdict["usd"] is None and verdict["attributable"] is False
    assert "noncritical" in verdict["reason"] and "minimax" in verdict["reason"]
    assert {t["name"]: t["leg"] for t in verdict["tiers"]} == {
        "minimax": "metered", "claude_cli": "subscription"}


def test_a_sole_role_on_a_leg_gets_the_figure(tmp_path):
    """When nothing is shared the arithmetic IS sound, and a null there would be its own lie."""
    _ledger(tmp_path, [_spend_row(DAY, 8.0), _cli_row(DAY, 30.0)])
    # The pre-2026-08-15 roster: a claude-led moat with minimax alone on the non-critical chain.
    # One role per leg, so both figures are sound and a null there would be its own lie.
    cfg = _cfg(tmp_path, operator=["claude_cli"], noncritical_operator=["minimax"],
               artifact_operator=[], marketing_operator=[])
    view = S.spend_view(cfg, now=_at(DAY, 12))
    assert _roles(view, "verdict")["usd"] == 30.0          # the subscription leg, sole owner
    assert _roles(view, "verdict")["attributable"] is True
    assert _roles(view, "noncritical")["usd"] == 8.0       # the metered leg, sole owner


def test_an_unmetered_chain_says_it_writes_no_spend_rows(tmp_path):
    """The grounding chain (`ddg`, `exa`) has no price entry, so it emits no ledger row at all.
    That is a real $0, and it is labelled as one rather than left to look like an unread figure."""
    _ledger(tmp_path, [_spend_row(DAY, 8.0)])
    cfg = _cfg(tmp_path, operator=["minimax"],
               retrieval=types.SimpleNamespace(provider=["ddg", "exa"]))
    view = S.spend_view(cfg, now=_at(DAY, 12))
    grounding = _roles(view, "grounding")
    assert grounding["usd"] == 0.0 and grounding["legs"] == []
    assert "writes no spend rows" in grounding["reason"]


def test_the_role_chains_come_from_the_read_model_not_a_second_derivation(tmp_path, monkeypatch):
    """R23: no truth derived twice. `readmodel._configured_chains` already strips forbidden tiers
    from the non-critical chain, so a roster rebuilt here would name a chain the engine does not
    run."""
    from prospector.ops import readmodel as R

    called = {"n": 0}
    real = R._configured_chains

    def spy(cfg):
        called["n"] += 1
        return real(cfg)

    monkeypatch.setattr(R, "_configured_chains", spy)
    _ledger(tmp_path, [_spend_row(DAY, 1.0)])
    S.spend_view(_cfg(tmp_path, operator=["minimax"]), now=_at(DAY, 12))
    assert called["n"] == 1


# --------------------------------------------------------------------------- #
# The renderer holds no numbers of its own
# --------------------------------------------------------------------------- #
def test_the_page_renders_the_view_and_computes_nothing(tmp_path):
    """A panel that derives its own figure is how a console and a rail come to disagree about
    whether the daemon may spend.

    Checked on the AST rather than the text, so the page's own docstring may DISCUSS the guard and
    the ledger (it must, to say why it does not touch them) while the code is still proved free of
    both. A cap literal pasted into the renderer — the thing that goes stale the day the founder
    raises it — fails the last assertion. Static, because importing the page needs Streamlit.
    """
    import ast

    page = Path(S.__file__).resolve().parent.parent / "control_center" / "pages" / "_spend.py"
    tree = ast.parse(page.read_text())

    modules = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert "prospector.ops" in modules
    assert not [m for m in modules if m.startswith("prospector.scheduler")], \
        "the page reads the view; the guard is the view's business, not the panel's"

    called = {n.func.attr for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert called.isdisjoint({"scan_today", "spend_by_day", "guard_from_config", "evaluate"})

    literals = {n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, float)}
    assert literals.isdisjoint({100.0, 20.0, 75.0}), \
        f"a cap/threshold literal in the renderer: {literals}"


# --------------------------------------------------------------------------- #
# The per-tier split: the finest split the cache can support
# --------------------------------------------------------------------------- #
def _tier(view, name):
    return next(t for t in view["tiers"] if t["name"] == name)


def test_a_leg_with_one_tier_is_fully_that_tiers_spend(tmp_path):
    """THE LIVE SHAPE (2026-08-16): minimax is the only metered tier and claude_cli the only
    subscription one, so both legs are exactly attributable even though no ROLE is — which is the
    whole reason this layer exists. A role-only panel would show five nulls and answer nothing."""
    _ledger(tmp_path, [_spend_row(DAY, 8.0), _cli_row(DAY, 30.0)])
    cfg = _cfg(tmp_path, operator=["minimax", "claude_cli"], noncritical_operator=["minimax"])
    view = S.spend_view(cfg, now=_at(DAY, 12))

    assert _tier(view, "minimax")["usd"] == 8.0
    assert _tier(view, "minimax")["leg"] == "metered"
    assert "verdict#0" in _tier(view, "minimax")["roles"]
    assert _tier(view, "claude_cli")["usd"] == 30.0
    assert all(r["usd"] is None for r in view["roles"] if r["legs"])   # roles still honestly null


def test_two_metered_tiers_cannot_be_separated(tmp_path):
    """The pre-2026-08-15 shape (minimax + deepseek both billed). The cache has one metered
    number for the day, so splitting it between them would be invention, not measurement."""
    _ledger(tmp_path, [_spend_row(DAY, 8.0)])
    cfg = _cfg(tmp_path, operator=["minimax", "deepseek"])
    view = S.spend_view(cfg, now=_at(DAY, 12))
    assert _tier(view, "minimax")["usd"] is None
    assert "deepseek" in _tier(view, "minimax")["reason"]
    assert _tier(view, "deepseek")["attributable"] is False


def test_an_unpriced_tier_is_a_real_zero_not_an_unread_one(tmp_path):
    """`ddg`/`exa` have no price entry, so `telemetry.record_usage` emits no `event: spend` row
    for them at all — $0.00 here is a fact about the code path, and is labelled as one."""
    _ledger(tmp_path, [_spend_row(DAY, 8.0)])
    cfg = _cfg(tmp_path, operator=["minimax"],
               retrieval=types.SimpleNamespace(provider=["ddg", "exa"]))
    view = S.spend_view(cfg, now=_at(DAY, 12))
    assert _tier(view, "ddg")["usd"] == 0.0
    assert "emits no ledger spend row" in _tier(view, "ddg")["reason"]
