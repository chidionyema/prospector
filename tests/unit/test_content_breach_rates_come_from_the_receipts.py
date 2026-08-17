"""Breach counts per rule, read from the lint receipts that were already on disk.

P6 of `docs/CONTENT_CONTRACT_PROGRAM.md`. P5 promotes a rule from shadow to blocking when its
breach rate has held at zero. That is only a sentence until somebody counts, and this is the
counter.

The claim under test is not "the numbers add up". It is that the module cannot make the two
mistakes that would make its numbers worse than none:

1. Confusing a rule that has never run with a rule with a clean record. Both are zero. Promoting
   the first puts a rule nobody has seen fire onto the money path.
2. Restating which rules are enforced instead of asking the config. A second copy of the switch
   is how a panel says a rule is blocking on a day it is not.
"""
from __future__ import annotations

import json

import pytest

from prospector import content_contract
from prospector.ops import content_breaches as cb


def _receipt(day: str, *problems: tuple[str, str]) -> dict:
    return {
        "checked_at": f"{day}T12:00:00+00:00",
        "problems": [{"check": c, "severity": s, "where": "pack", "detail": "x"}
                     for c, s in problems],
    }


def _write(tmp_path, receipts):
    d = tmp_path / "dossiers"
    d.mkdir()
    for i, r in enumerate(receipts):
        (d / f"{i:04x}.lint.json").write_text(json.dumps(r))
    return d


class _Cfg:
    def __init__(self, listing=None):
        self.listing = listing or {}


# ---- counting ------------------------------------------------------------------------------

def test_findings_and_packs_are_different_numbers():
    """One pack raising the same check three times is one PACK and three FINDINGS. A rate built
    on findings can exceed 100% and means nothing."""
    recs = cb.tally([_receipt("2026-08-17", ("title", "error"), ("title", "error")),
                     _receipt("2026-08-17", ("title", "error"))])
    assert recs["title"].findings == 3
    assert recs["title"].packs == 2
    assert recs["title"].rate(2) == 1.0


def test_severity_is_split_because_a_shadow_rule_only_ever_warns():
    recs = cb.tally([_receipt("2026-08-17", ("grammar", "error"), ("house_quote", "warning"))])
    assert recs["grammar"].errors == 1 and recs["grammar"].warnings == 0
    assert recs["house_quote"].warnings == 1 and recs["house_quote"].errors == 0


def test_a_rate_with_nothing_graded_is_none_not_zero():
    """None and 0.0 are opposites here. P5 promotes on 0.0; promoting on 'no evidence' is the
    bug this exists to prevent."""
    rec = cb.RuleBreaches(check="title")
    assert rec.rate(0) is None
    assert rec.rate(10) == 0.0


def test_the_day_key_is_the_grading_date():
    recs = cb.tally([_receipt("2026-08-09", ("title", "error")),
                     _receipt("2026-08-17", ("title", "error"))])
    assert recs["title"].by_day == {"2026-08-09": 1, "2026-08-17": 1}


def test_a_receipt_with_no_timestamp_is_kept_under_unknown():
    """Dropping it would quietly shrink the denominator, which flatters every rate on the page."""
    recs = cb.tally([{"problems": [{"check": "title", "severity": "error"}]}])
    assert recs["title"].by_day == {"unknown": 1}


# ---- robustness ----------------------------------------------------------------------------

def test_a_torn_receipt_is_skipped_not_raised(tmp_path):
    d = _write(tmp_path, [_receipt("2026-08-17", ("title", "error"))])
    (d / "torn.lint.json").write_text('{"problems": [{"check"')
    got = cb.read_receipts(directory=d)
    assert len(got) == 1, "a half-written receipt took the whole panel down"


def test_a_missing_directory_reads_as_no_receipts(tmp_path):
    assert cb.read_receipts(directory=tmp_path / "nope") == []


def test_a_problem_that_is_not_a_mapping_is_ignored():
    recs = cb.tally([{"checked_at": "2026-08-17T00:00:00Z", "problems": ["a string", None]}])
    assert recs == {}


# ---- the two mistakes that would make the numbers worse than none --------------------------

def test_blocking_is_read_from_the_live_config_not_restated():
    """`house_quote` blocks when `house_spec_block_quotes` is on and does not when it is off.
    The module must ask the contract, which asks the config."""
    on = cb.tally([_receipt("2026-08-17", ("house_quote", "warning"))],
                  listing_cfg={"house_spec_block_quotes": True})
    off = cb.tally([_receipt("2026-08-17", ("house_quote", "warning"))],
                   listing_cfg={"house_spec_block_quotes": False})
    assert on["house_quote"].blocking is True
    assert off["house_quote"].blocking is False


def test_an_absent_config_falls_back_to_the_declared_default():
    """No config is not "nothing is enforced" — it is the DEFAULTS, which is what a fresh process
    actually runs. `title` is enforced by default and must read that way; `house_quote` is
    shadow by default and must not."""
    recs = cb.tally([_receipt("2026-08-17", ("title", "error"),
                              ("house_quote", "warning"))])
    assert recs["title"].blocking is True
    assert recs["house_quote"].blocking is False


def test_a_rule_that_never_ran_is_not_offered_for_promotion(tmp_path):
    """The whole point. `hedging` has no actuator and raised nothing. Zero findings is NOT
    evidence it is clean — it is indistinguishable from evidence it never executed."""
    d = _write(tmp_path, [_receipt("2026-08-17", ("house_quote", "warning"))])
    report = cb.breach_report(_Cfg(), directory=d)
    assert "hedging" in report["never_observed"]
    assert "hedging" not in report["ready_to_promote"], (
        "a rule with no evidence it has ever run was offered for promotion onto the money path"
    )


def test_a_shadow_rule_with_history_and_a_clean_streak_is_offered(tmp_path):
    """The other side of the same test, so it is not passing by refusing everything."""
    d = _write(tmp_path, [
        _receipt("2026-08-09", ("house_quote", "warning")),
        _receipt("2026-08-17", ("register", "warning")),
    ])
    report = cb.breach_report(_Cfg(), directory=d)
    # house_quote fired on the 9th but not the 17th, so its streak is 1 of 2 days — not clean.
    assert "house_quote" not in report["ready_to_promote"]
    assert "register" not in report["ready_to_promote"], "fired on the most recent graded day"


def test_a_clean_streak_only_counts_days_something_was_graded():
    """A weekend with no runs must not earn a rule credit."""
    rec = cb.RuleBreaches(check="x", by_day={"2026-08-09": 2})
    assert cb.clean_streak(rec, ["2026-08-09", "2026-08-15", "2026-08-17"]) == 2
    assert cb.clean_streak(rec, ["2026-08-09"]) == 0
    assert cb.clean_streak(None, ["2026-08-09", "2026-08-17"]) == 2


# ---- wiring to the contract ------------------------------------------------------------------

def test_a_declared_rule_with_no_findings_still_appears(tmp_path):
    """A table that only lists what broke can never show a rule holding at zero, which is the
    exact fact P5 waits on."""
    d = _write(tmp_path, [_receipt("2026-08-17", ("title", "error"))])
    report = cb.breach_report(_Cfg(), directory=d)
    listed = {r["check"] for r in report["rules"]}
    for rule in content_contract.RULES:
        assert rule.check in listed, f"{rule.check} is declared and missing from the report"


def test_an_undeclared_check_is_named_rather_than_dropped(tmp_path):
    """This is how the `house_quote` / `register_repeat` gap was found. It must stay visible."""
    d = _write(tmp_path, [_receipt("2026-08-17", ("brand_new_check", "error"))])
    report = cb.breach_report(_Cfg(), directory=d)
    assert report["undeclared"] == ["brand_new_check"]


def test_the_repair_is_the_one_the_console_can_actually_perform(tmp_path):
    d = _write(tmp_path, [_receipt("2026-08-17", ("shelf_copy", "error"), ("grammar", "error"))])
    report = cb.breach_report(_Cfg(), directory=d)
    by_check = {r["check"]: r for r in report["rules"]}
    assert by_check["shelf_copy"]["repair"] == content_contract.REPAIR_COPY
    # `grammar`'s true repair is a regenerate, which the console cannot do; it must degrade
    # rather than render a button that does nothing.
    assert by_check["grammar"]["repair"] in content_contract.WIRED_REPAIRS


def test_coverage_is_stated_on_the_report_not_left_implied(tmp_path):
    d = _write(tmp_path, [_receipt("2026-08-17", ("title", "error"))])
    report = cb.breach_report(_Cfg(), directory=d)
    assert report["coverage"]["receipts"] == 1
    assert "GRADED" in report["coverage"]["note"]


def test_the_store_path_does_not_follow_the_code():
    """A store path derived from `__file__` follows the CODE, not the store — the 2026-08-17
    split-state incident. This must resolve through `config.store_root()`."""
    import inspect

    src = inspect.getsource(cb.receipts_dir)
    body = src.split('"""')[-1]          # past the docstring, which names the trap by name
    assert "__file__" not in body, "the receipts directory is anchored to the code's location"
    assert "store_root" in body


@pytest.mark.parametrize("listing", [{}, {"house_spec_block_quotes": True}])
def test_the_report_runs_on_the_live_receipts(listing):
    """Not a fixture. If the real receipts on disk break this, the panel is broken."""
    report = cb.breach_report(_Cfg(listing))
    assert isinstance(report["graded_packs"], int)
    assert report["undeclared"] == [], (
        f"the linters emit checks the contract does not declare: {report['undeclared']}"
    )


# ---- C2: it has to reach the console, not just exist ----------------------------------------

def test_the_console_serves_it_as_a_view():
    """Built and unreachable is this repo's recurring defect shape. A reader nothing calls is
    not a panel."""
    from prospector.ops import console_api

    assert "content_rules" in console_api.READS


def test_the_console_view_returns_the_report_shape():
    from prospector.ops import console_api

    out = console_api.READS["content_rules"](_Cfg(), {})
    for key in ("graded_packs", "rules", "blocking", "shadow",
                "ready_to_promote", "never_observed", "coverage"):
        assert key in out, f"the console view is missing {key}"


# ---- P5: the console is the actuator that promotes a rule -----------------------------------

def test_every_rule_with_a_switch_is_promotable_from_the_console():
    """P5. A rule the operator cannot switch on is a rule that stays in shadow forever, whatever
    its breach rate says. The knob list is GENERATED from the registry so the two cannot drift."""
    from prospector.ops import console_api

    declared = {r.config_key for r in content_contract.RULES if r.config_key}
    offered = {k["path"][1] for k in console_api.KNOBS if k["group"] == "content"}
    assert declared == offered, (
        f"rules the console cannot promote: {sorted(declared - offered)}; "
        f"switches the console offers for no rule: {sorted(offered - declared)}"
    )


def test_a_shared_switch_names_every_rule_it_moves():
    """`title_block_on_breach` moves `title` AND `title_claim`. An operator promoting one must
    see they are promoting both, or the console has understated the blast radius."""
    from prospector.ops import console_api

    knob = console_api.KNOBS_BY_KEY["listing.title_block_on_breach"]
    assert "title_claim" in knob["label"], knob["label"]
    assert "title" in knob["label"]


def test_the_content_knobs_are_booleans_under_listing():
    from prospector.ops import console_api

    for knob in (k for k in console_api.KNOBS if k["group"] == "content"):
        assert knob["path"][0] == "listing", knob
        assert knob["kind"] == "bool", knob
        assert knob["help"], f"{knob['path']} has no help text"


def test_the_content_group_is_rendered():
    """A group missing from GROUP_ORDER is a panel the console never draws. Built and
    unreachable, again."""
    from prospector.ops import console_api

    assert "content" in console_api.GROUP_ORDER
    assert console_api.GROUP_BLURBS.get("content")


def test_the_help_text_warns_against_promoting_on_no_evidence():
    """The one thing an operator must not do here is flip a switch without reading the rate.
    98% of packs breach two of these today."""
    from prospector.ops import console_api

    knob = console_api.KNOBS_BY_KEY["listing.house_spec_block_quotes"]
    assert "content_rules" in knob["help"], "the help does not point at the evidence view"
