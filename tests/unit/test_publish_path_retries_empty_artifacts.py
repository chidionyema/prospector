"""The daemon's publish path must not accept an empty artifact as a finished pack.

`generate_artifacts` turns a per-artifact provider failure into `results[t] = ""`
(`prospector/artifacts.py:452`) so that one dead call cannot lose the other three. Nothing
in `run.py` looked at the result, so an outage was written to disk as a PASS whose prose was
empty, published UNLISTED because `pack_complete` is false, and never revisited.

Measured 2026-08-13 against the live catalogue: 24 engine passes were off the shelf and 12
of them were exactly this, failing on the same three artifacts every time — "generation
produced nothing" x10 build_spec, x10 ops_plan, x9 gtm_plan. `tools/publish_passes.py:228`
has always retried; the daemon's own path did not, which is the asymmetry these tests pin.
"""
from __future__ import annotations

import pytest

from prospector import run as run_mod

_BODY = "## Section\n\n" + ("Real, moat-verified prose that a buyer would pay for. " * 30)
_GOOD_ARTIFACTS = {k: f"# {k}\n\n{_BODY}\n\n## Second section\n\n{_BODY}"
                   for k in ("build_spec", "gtm_plan", "ops_plan", "financial_model")}
_GOOD_MARKETING = [{"type": "listing_page", "copy": "Listing copy that sells the pack. " * 8}]


class _Cand:
    candidate_id = "c" * 16
    tags: dict = {}


@pytest.fixture
def spy(monkeypatch):
    """Count generation calls and drive what each attempt returns."""
    calls = {"artifacts": 0, "marketing": 0}
    plan: list = []

    def _fake_artifacts(*a, **k):
        calls["artifacts"] += 1
        return plan[min(calls["artifacts"] - 1, len(plan) - 1)]

    def _fake_marketing(*a, **k):
        calls["marketing"] += 1
        return list(_GOOD_MARKETING)

    import prospector.artifacts as arts_mod
    monkeypatch.setattr(arts_mod, "generate_artifacts", _fake_artifacts)
    monkeypatch.setattr(arts_mod, "generate_marketing_content", _fake_marketing)
    return calls, plan


def _run():
    return run_mod._generate_pack_content(
        object(), _Cand(), [], query_op=None, quality_op=None, cfg=None, score=None)


class TestEmptyArtifactsAreRetried:
    def test_a_complete_pack_costs_exactly_one_generation(self, spy):
        calls, plan = spy
        plan.append(dict(_GOOD_ARTIFACTS))
        artifacts, marketing = _run()
        assert calls["artifacts"] == 1, "retried a pack that was already sellable"
        assert artifacts["build_spec"]
        assert marketing == _GOOD_MARKETING

    def test_an_empty_artifact_is_regenerated_not_published(self, spy):
        """The exact failure that stranded 12 packs: one empty prose artifact."""
        calls, plan = spy
        plan.append({**_GOOD_ARTIFACTS, "build_spec": ""})   # attempt 1: the outage
        plan.append(dict(_GOOD_ARTIFACTS))                   # attempt 2: the provider is back
        artifacts, _ = _run()
        assert calls["artifacts"] == 2, "accepted an empty build_spec without retrying"
        assert artifacts["build_spec"].strip(), "returned the empty artifact anyway"

    def test_a_stub_artifact_is_regenerated_too(self, spy):
        """`64c58072e2585c2b` shipped a 3-char build_spec — short, not empty."""
        calls, plan = spy
        plan.append({**_GOOD_ARTIFACTS, "ops_plan": "TBD"})
        plan.append(dict(_GOOD_ARTIFACTS))
        artifacts, _ = _run()
        assert calls["artifacts"] == 2
        assert len(artifacts["ops_plan"]) > 200

    def test_it_gives_up_after_the_configured_attempts(self, spy, caplog):
        """A sustained outage must stop costing money, and must say so at ERROR.

        Publishing UNLISTED is still the behaviour — the row records that the candidate
        passed — but a silent one is what let this go unnoticed for three days.
        """
        calls, plan = spy
        plan.append({**_GOOD_ARTIFACTS, "build_spec": "", "gtm_plan": ""})
        with caplog.at_level("ERROR"):
            artifacts, marketing = _run()
        assert calls["artifacts"] == run_mod._MAX_PACK_GEN_ATTEMPTS
        assert not artifacts["build_spec"], "must return what it got, not a fabricated pack"
        # Pinned on LEVEL + the named gap, not on the sentence: this assertion read
        # `"STILL incomplete" in r.message` and broke on 2026-08-14 when the same log line
        # was reworded to "STILL not sellable" (the loop now also refuses copy the publish
        # gate would refuse). A test that fails on the prose while the behaviour is intact
        # is a test that will be silenced rather than read.
        giving_up = [r for r in caplog.records if r.levelname == "ERROR"]
        assert giving_up, "gave up silently — the defect that made this invisible"
        assert any("build_spec" in r.message and "STILL" in r.message for r in giving_up), \
            "the final line must name what is missing, or it cannot be acted on"

    def test_the_retry_budget_matches_the_repair_tool(self):
        """One discipline, one number: a drift here is how the asymmetry came back."""
        import tools.publish_passes as pp
        assert run_mod._MAX_PACK_GEN_ATTEMPTS == pp.MAX_GEN_ATTEMPTS
