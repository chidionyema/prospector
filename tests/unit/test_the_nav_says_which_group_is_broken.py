"""The nav badge, and the two ways it could lie.

The console has seven groups and twenty-four screens, and until `attention_view` existed the only
way to answer "is anything wrong" was to open all seven. A badge that answers it is only worth
having if it cannot be wrong in either direction, so both directions are pinned here:

  * it must not go GREEN on something it never checked (that is the expensive lie — an operator
    who trusts the dot stops opening the screen);
  * it must not go RED on the absence of a reading (that is the cheap lie, and it is the one the
    first hand-probe of the module actually printed).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from prospector.ops.attention import GROUPS, attention_view

REPO = Path(__file__).resolve().parents[2]
NAV_TS = REPO / "store_platform/src/Ops.Console/src/lib/nav.ts"


def _rows(view: dict) -> dict[str, dict]:
    return {r["group"]: r for r in view["groups"]}


# --------------------------------------------------------------------------------------------
# The badge is keyed to the nav by a string. A string key that stops matching fails SILENTLY.
# --------------------------------------------------------------------------------------------

def test_every_group_the_badge_knows_is_a_group_the_nav_renders():
    """If these two lists drift, the dot simply never appears — there is no error to notice.

    The badge looks its group up by label. Rename a group in `nav.ts` and the lookup misses, the
    dot stays off, and the console reports a healthy estate by saying nothing at all. That is the
    worst failure mode a warning light can have, so it is a test rather than a convention.
    """
    assert NAV_TS.exists(), f"nav.ts moved; this test is now grading nothing: {NAV_TS}"
    labels = re.findall(r"^\s*label: '([^']+)',\s*$", NAV_TS.read_text(), re.M)
    # Group labels are the ones followed by a `screens:` array; screen labels sit inside it.
    nav_groups = [m.group(1) for m in
                  re.finditer(r"label: '([^']+)',\s*\n(?:\s*//[^\n]*\n)*\s*screens: \[",
                              NAV_TS.read_text())]
    assert nav_groups, f"parsed no groups out of nav.ts (found {len(labels)} labels in total)"
    assert list(GROUPS) == nav_groups, (
        f"the badge is keyed to {list(GROUPS)} but the nav renders {nav_groups}; "
        "a dot keyed to a group that does not exist never renders and never errors"
    )


def test_the_view_reports_every_group_exactly_once():
    view = attention_view({})
    assert [r["group"] for r in view["groups"]] == list(GROUPS)


# --------------------------------------------------------------------------------------------
# The expensive lie: green on something nobody checked.
# --------------------------------------------------------------------------------------------

def test_an_empty_payload_is_unmeasured_and_never_ok():
    """No engine answered. Every group must say so; none may report health.

    `ok` here would mean "checked, and nothing is wrong". Nothing was checked.
    """
    view = attention_view({})
    for row in view["groups"]:
        assert row["state"] == "unmeasured", (
            f"{row['group']} reported {row['state']!r} from an empty payload — "
            "that is a health claim about a reading that never happened"
        )
    assert view["faults"] == 0
    assert view["worst"] == "unmeasured"


@pytest.mark.parametrize("group,payload", [
    ("Engine", {"routing": {"error": "StaleProcessGlobal"}}),
    ("Data", {"incidents": {"error": "no scripts/ in this image"}}),
])
def test_a_view_that_failed_makes_its_group_unmeasured_rather_than_green(group, payload):
    """`status` composes a dozen views and any one may return an `error` record by design.

    `_incident_headline` does exactly that rather than blanking the Now page. A sub-view that
    could not answer must not be read as a sub-view that answered "fine".
    """
    row = _rows(attention_view(payload))[group]
    assert row["state"] == "unmeasured", f"{group} was {row['state']!r} on a failed sub-view"
    assert any(f["state"] == "unmeasured" for f in row["findings"])


def test_the_groups_this_view_cannot_reach_say_so_by_name():
    """Money's rail, Shop, Shelf and Control are network or unread here, and must admit it.

    `status` makes no call to the store API, so nothing in this view knows whether the shop can
    take money. Silence there would render identically to health.
    """
    view = attention_view({})
    for group in ("Shelf", "Shop", "Control"):
        findings = _rows(view)[group]["findings"]
        assert findings, f"{group} produced no finding at all, so its absence reads as health"
        assert all(f["state"] == "unmeasured" for f in findings)
        assert any("open " in f["what"] for f in findings), (
            f"{group} must name the screen that does know")
    assert set(view["not_checked"]) >= {"Shelf", "Shop", "Control"}


# --------------------------------------------------------------------------------------------
# The cheap lie: red on the absence of a reading. The module's own first probe printed this.
# --------------------------------------------------------------------------------------------

def test_an_unreported_spend_cap_is_not_a_disarmed_spend_cap():
    """`cap_armed` absent is not `cap_armed` false.

    The first hand-probe of this module printed "the daily spend cap is disarmed" against an
    empty payload, which is a finding invented out of a missing key.
    """
    absent = [f for f in _rows(attention_view({"spend": {}}))["Money"]["findings"]
              if "cap" in f["what"]]
    assert absent and all(f["state"] == "unmeasured" for f in absent), absent

    off = [f for f in _rows(attention_view({"spend": {"cap_armed": False}}))["Money"]["findings"]
           if "disarmed" in f["what"]]
    assert off and off[0]["state"] == "warn", off

    on = [f for f in _rows(attention_view({"spend": {"cap_armed": True}}))["Money"]["findings"]
          if "cap" in f["what"]]
    assert on == [], f"an armed cap is not a finding: {on}"


def test_a_supervisor_job_that_could_not_be_asked_is_not_a_job_that_is_down():
    """`loaded` is tri-state and stays that way. None means launchctl did not answer."""
    unknown = _rows(attention_view(
        {"supervisor": {"jobs": [{"label": "com.prospector.scheduler", "loaded": None}]}}))["Now"]
    assert unknown["state"] == "unmeasured", unknown

    down = _rows(attention_view(
        {"supervisor": {"jobs": [{"label": "com.prospector.scheduler", "loaded": False}]}}))["Now"]
    assert down["state"] == "bad", down


def test_an_engine_that_does_not_report_stuck_work_is_not_an_engine_with_none():
    """The Fly engine's `status` returns no `stuck` key at all."""
    row = _rows(attention_view({}))["Engine"]
    assert any("does not report stuck work" in f["what"] for f in row["findings"])
    assert row["state"] == "unmeasured"


# --------------------------------------------------------------------------------------------
# Ranking, and the shape every consumer relies on.
# --------------------------------------------------------------------------------------------

def test_a_critical_alert_outranks_every_warning():
    view = attention_view({
        "alerts": {"active": [{"key": "engine_down", "severity": "critical"}]},
        "queue": {"backlog": {"stalled": 9}},
    })
    assert _rows(view)["Now"]["state"] == "bad"
    assert _rows(view)["Engine"]["state"] == "warn"
    assert view["worst"] == "bad"


def test_unmeasured_never_outranks_a_real_fault():
    """A group with one fault and one unread thing is FAULTY, not unmeasured."""
    row = _rows(attention_view({
        "spend": {"cap_armed": False},  # a warn, beside the rail line that is always unmeasured
    }))["Money"]
    assert row["state"] == "warn", row


def test_only_faults_are_counted_and_the_headline_agrees_with_the_count():
    empty = attention_view({})
    assert empty["headline"] == "nothing found wrong"

    one = attention_view({"spend": {"cap_armed": False}})
    assert one["faults"] == 1
    assert one["headline"] == "1 thing needs attention", one["headline"]

    two = attention_view({"spend": {"cap_armed": False}, "queue": {"backlog": {"stalled": 3}}})
    assert two["faults"] == 2
    assert two["headline"] == "2 things need attention", two["headline"]


def test_every_finding_names_what_and_where_so_the_badge_can_be_clicked_through():
    """A dot the operator cannot follow to a screen is a dot that starts a search."""
    view = attention_view({
        "alerts": {"active": [{"key": "engine_down", "severity": "critical"}], "banner": "down"},
        "heartbeats": {"producer": {"alive": False, "why": "no beat for 3h"},
                       "consumer": {"alive": True, "stale": True}},
        "providers": {"tiers": [{"name": "minimax", "state": "dead"}], "moat_blind": "all benched"},
        "routing": {"problems": ["head is untrusted"]},
        "queue": {"backlog": {"stalled": 4, "orphaned": 1}, "leases": {"expired": 2}},
        "stuck": {"needs_attention": 2},
        "incidents": {"blocked": 1},
        "spend": {"cap_armed": True, "warnings": ["82% of cap"]},
        "pause": {"any_armed": True, "scopes": [{"scope": "generation", "armed": True}]},
    })
    assert view["worst"] == "bad"
    for row in view["groups"]:
        for f in row["findings"]:
            assert f["state"] in {"bad", "warn", "unmeasured"}, f
            assert str(f["what"]).strip(), f"a blank finding renders as an unexplained dot: {f}"
            assert str(f["where"]).startswith("/"), f


def test_a_malformed_sub_view_cannot_crash_the_badge():
    """Anything that is not the expected shape must degrade, never raise.

    The badge is on every screen. An exception here blanks the whole console, which is a far
    worse outcome than a missing dot.
    """
    for junk in ({"alerts": "not a dict"}, {"queue": {"backlog": None}},
                 {"providers": {"tiers": "nope"}}, {"heartbeats": []},
                 {"supervisor": {"jobs": None}}, {"stuck": {"needs_attention": None}}):
        view = attention_view(junk)
        assert view["worst"] in {"bad", "warn", "ok", "unmeasured"}, junk


def test_the_reader_derives_nothing_that_is_not_in_status(monkeypatch):
    """The registered reader must compose `_read_status` and call nothing else.

    This is the property that stops the badge disagreeing with the screen it points at. If a
    future edit gives the badge its own file reads, this fails.
    """
    from prospector.ops import console_api

    seen = {}

    def fake_status(cfg, args):
        seen["called"] = True
        return {"spend": {"cap_armed": False}}

    monkeypatch.setattr(console_api, "_read_status", fake_status)
    view = console_api.READS["attention"](object(), {})
    assert seen.get("called"), "the reader did not go through _read_status"
    assert view["faults"] == 1
    assert view["headline"] == "1 thing needs attention"


def test_the_reader_is_registered_under_a_name_the_console_asks_for():
    from prospector.ops.console_api import READS

    assert "attention" in READS
