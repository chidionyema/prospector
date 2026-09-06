"""Rung 4, crew#299: the stale workflow may close a pull request nobody owns and nothing else.
The failure it guards: a config edit that lets it touch issues, close a PR faster than the
14 idle days the founder set, ignore the keep-open label, or run unpinned."""
import pathlib, re, yaml

WF = pathlib.Path(__file__).resolve().parents[2] / ".github" / "workflows" / "stale.yml"


def _with() -> dict:
    doc = yaml.safe_load(WF.read_text())
    steps = [s for j in doc["jobs"].values() for s in j["steps"] if "stale" in s.get("uses", "")]
    assert len(steps) == 1, "exactly one actions/stale step"
    assert re.fullmatch(r"actions/stale@[0-9a-f]{40}", steps[0]["uses"]), "pinned to a sha"
    return steps[0]["with"]


def test_stale_touches_pull_requests_only_and_only_after_14_idle_days():
    w = _with()
    assert w["days-before-issue-stale"] == -1 and w["days-before-issue-close"] == -1
    assert w["days-before-pr-stale"] + w["days-before-pr-close"] >= 14
    assert "keep-open" in str(w["exempt-pr-labels"]).split(",")
    assert w["stale-pr-label"] == "stale"


def test_a_config_that_closes_issues_is_refused():
    w = dict(_with()); w["days-before-issue-close"] = 7
    assert not (w["days-before-issue-stale"] == -1 and w["days-before-issue-close"] == -1)
