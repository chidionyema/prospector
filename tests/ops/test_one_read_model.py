"""R23 — both surfaces read ONE model; no truth is derived twice.

The probe from `docs/OPS_CONSOLE_PROGRAM.md:923`: *"test forbids a second derivation of
backlog/spend/moat"*.

Why it needs a test rather than a convention: a second derivation never looks like a bug. It is a
helper that reads the same file and answers a slightly different question, and it only becomes
visible when a panel and a rail disagree in front of an operator during an incident. This repo has
already paid for all three:

  * **spend** — `readers.py` carried its own reverse-tail parse of `store/prospector.jsonl` that
    summed `event: "spend"` only, so the Overview's "today's spend" was the METERED leg alone:
    $0.69 shown against $19.53 of subscription burn (memory `never-hand-parse-the-spend-ledger`).
  * **backlog** — `run.drainable()`/`drain_survey` is THE definition, because the brake must only
    engage on a number the drain can move (`gate-on-the-rate-not-the-stock`).
  * **moat** — `operator.moat_primary()` is a process global; anything that re-reads the YAML key
    instead answers a roster the engine is not using (§14.5.1).

Two kinds of assertion here, deliberately. The identity checks are behavioural and cannot be
fooled. The source scan is a backstop and is known to be weaker than it looks
(`a-source-scanner-cannot-see-a-label-built-at-render-time`) — it can only catch a name, so it is
scoped to the three names above rather than pretending to be a general fence.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

PAGES = Path("prospector/control_center/pages")
OPS = Path("prospector/ops")


# --------------------------------------------------------------------------- #
# Behavioural: the renderer and the CLI hold the SAME function object
# --------------------------------------------------------------------------- #
def test_the_streamlit_page_and_the_cli_call_the_same_functions():
    """Not "equivalent" — identical. Both surfaces are thin over `prospector.ops`."""
    from prospector.control_center.pages import _engine, _metrics, _runs, _spend
    from prospector.ops import metrics as ops_metrics
    from prospector.ops import pause as ops_pause
    from prospector.ops import readmodel as ops_readmodel
    from prospector.ops import runs as ops_runs
    from prospector.ops import spend as ops_spend

    assert _engine._rm is ops_readmodel
    assert _engine._pause is ops_pause
    assert _spend._spend is ops_spend
    assert _runs._runs is ops_runs
    assert _metrics._mx is ops_metrics


def test_every_ops_module_has_the_cli_entry_point_the_telegram_surface_calls():
    """The second surface is `python -m prospector.ops.<view>` (§4). A module without `main()`
    is a view only the desk can see."""
    import importlib

    for name in ("readmodel", "pause", "spend", "metrics", "runs", "routing"):
        mod = importlib.import_module(f"prospector.ops.{name}")
        assert callable(getattr(mod, "main", None)), f"prospector.ops.{name} has no CLI"


def test_the_overview_kpi_and_the_spend_page_report_the_same_metered_figure(monkeypatch):
    """The regression that motivated R23, as an equality. `readers._today_spend_from_ledger`
    used to hand-parse the ledger; now it is the guard's own scan, so the Overview KPI and the
    Spend page cannot print different money."""
    from prospector.control_center import readers
    from prospector.ops import spend as ops_spend
    from prospector.ops.readmodel import load_cfg

    cfg = load_cfg()

    # The two figures are read from the LIVE ledger, and the daemon appends to it while this test
    # runs. A bare equality between two reads a second apart fails on the write in between, which
    # says nothing about whether the two surfaces agree. Measured 2026-08-16 on this checkout:
    # view_before=12.694156, kpi=12.695400, view_after=12.695410. So bracket it — read the view on
    # both sides of the KPI and require the KPI to sit inside. A today-ledger only grows, so when
    # nothing is written the bracket collapses to the original equality.
    before = ops_spend.spend_view(cfg)
    kpi = readers._today_spend_from_ledger.__wrapped__(0.0)   # unwrap st.cache_data
    after = ops_spend.spend_view(cfg)

    def _brackets(key: str, got: float) -> bool:
        lo = round(float(before["legs"][key]["usd"]), 4)
        hi = round(float(after["legs"][key]["usd"]), 4)
        return lo - 1e-4 <= got <= hi + 1e-4

    assert _brackets("metered", kpi["total_usd"]), (
        f"the Overview KPI reports {kpi['total_usd']} metered, outside the Spend page's "
        f"{before['legs']['metered']['usd']}..{after['legs']['metered']['usd']}"
    )
    assert _brackets("subscription", kpi["subscription_usd"]), (
        f"the Overview KPI reports {kpi['subscription_usd']} subscription, outside the Spend "
        f"page's {before['legs']['subscription']['usd']}..{after['legs']['subscription']['usd']}"
    )
    assert kpi["source"] == "prospector.scheduler.guard.SchedulerGuard.scan_today()"


def test_the_metered_figure_is_the_guards_own_call_not_a_reconciliation(monkeypatch):
    """`scan_today` is patched to a sentinel; the KPI must change with it. A reader that parsed
    the ledger itself would ignore the patch and keep answering the real number."""
    from prospector.control_center import readers
    from prospector.scheduler import guard as _guard

    monkeypatch.setattr(_guard.SchedulerGuard, "scan_today", lambda self: (4.25, 8.5))
    kpi = readers._today_spend_from_ledger.__wrapped__(0.0)

    assert kpi["total_usd"] == 4.25 and kpi["subscription_usd"] == 8.5


# --------------------------------------------------------------------------- #
# Source scan: the three names, and who is allowed to say them
# --------------------------------------------------------------------------- #
def _calls(path: Path) -> set[str]:
    """Every called NAME in a module (`f()` and `x.f()` alike). Comments and strings are not
    calls, which is the whole reason this is an AST walk and not a grep."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name):
                out.add(fn.id)
            elif isinstance(fn, ast.Attribute):
                out.add(fn.attr)
    return out


@pytest.mark.parametrize("page", sorted(PAGES.glob("_*.py")))
def test_no_page_derives_backlog_spend_or_the_roster_itself(page):
    """A renderer may call an ops view. It may not call the underlying source.

    `moat_primary` is the exception that proves it: reading it is not the sin, reading it from a
    process that never called `load_config` is (§14.5.1) — so pages must reach it through the ops
    views, which load config first.
    """
    forbidden = {"drain_survey", "drainable", "scan_today", "spend_by_day", "moat_primary",
                 "connect"}
    # ONE recorded exception, named rather than hidden. `_resume.py:225` opens the catalogue DB
    # itself (`sqlite3.connect`); it predates the ops spine and is the page R16's queue view
    # replaces. It is listed so the fence still fires on a SECOND offence in that file and on any
    # other page — an allowlist that says which line and why is a debt; a silently relaxed rule
    # is a lie.
    known_debt = {"_resume.py": {"connect"}}
    found = (_calls(page) & forbidden) - known_debt.get(page.name, set())
    assert not found, (
        f"{page} derives {sorted(found)} itself. Every operator READ goes through "
        "prospector/ops (§4) — two derivations of one number is how a panel and a rail come to "
        "disagree in front of an operator.")


def test_readers_no_longer_parses_the_spend_ledger():
    """The deleted parser, pinned by name so it cannot come back quietly."""
    src = Path("prospector/control_center/readers.py").read_text(encoding="utf-8")
    assert "_scan_today_spend_from_tail" not in src
    from prospector.control_center import readers

    assert not hasattr(readers, "_scan_today_spend_from_tail")


def test_backlog_is_defined_in_exactly_one_place():
    """`drain_survey` lives on `run`; `ops/readmodel` calls it. Any THIRD implementation of the
    same count is the defect — so the definition is asserted to be a single function."""
    from prospector import run
    from prospector.ops import readmodel

    assert callable(run.drain_survey)
    src = Path("prospector/ops/readmodel.py").read_text(encoding="utf-8")
    assert "drain_survey" in src, "the read model must consume the definition, not re-count"
    assert readmodel.queue_view.__module__ == "prospector.ops.readmodel"
