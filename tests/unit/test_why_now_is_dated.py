"""The why-now check must rule on the page's date, not on the model's sense of the year.

THE DEFECT. `verify.py::verdict_for` builds the passage block the verdict brain reads. The
prompt template has always carried the placeholder `{for each: [source_id] (url,
published_at) text}` — but the line that replaced it rendered `[source_id] text` and nothing
else. Every check in this engine has therefore been ruled without ever seeing WHEN its
evidence was published. For five of the ten checks that costs little. For `currency` — "is
this opportunity live RIGHT NOW" — it is the whole question, and the only thing left to
answer it with was the model's own memory of what year it is, which is exactly the
prior-knowledge leak `verdict-from-retrieval-only` forbids.

Sources only started carrying dates on 2026-08-16 (`retrieval._extract_published_at`), so
until then there was nothing to render. Now there is.

THE RULE, pinned below:
  1. every passage handed to a verdict carries its publication date, or the literal
     `undated` — a caller must be able to tell "published 2019" from "we do not know";
  2. the `currency` question tells the brain to rule on those dates and to answer
     UNVERIFIABLE when they are absent. An undated page is not evidence that an
     opportunity is stale, only that we cannot tell — and `unverifiable` does not kill,
     while `refuted` does (side_hustle gates on this check);
  3. `venture` runs the check at all. It was the one lane that never asked.
"""
from __future__ import annotations

import pytest
import yaml

from prospector.config import load_config
from prospector.models import CHECKS, Candidate, Source
from prospector.operator import MockOperator
from prospector.verify import verdict_for

REPO_CONFIG = "config.yaml"


@pytest.fixture
def cfg():
    c = load_config()
    c.retrieval.provider = "fixture"
    c.retrieval.cache = False
    return c


@pytest.fixture
def cand() -> Candidate:
    return Candidate(title="Test Opportunity", one_liner="A test product",
                     hypothesis="People suffer from X", who_pays="SMEs")


def _prompt_for(cfg, cand, sources: list[Source]) -> str:
    """Run one verdict and return the USER prompt the brain actually received."""
    seen: dict[str, str] = {}

    def router(system: str, user: str) -> dict:
        seen["user"] = user
        return {"verdict": "supported", "confidence": 0.8,
                "rationale": "The 2026 rule cited in [S1] takes effect this year.",
                "citations": ["S1"]}

    verdict_for(MockOperator(router=router), cand, "currency", sources, cfg=cfg)
    return seen["user"]


def test_the_verdict_brain_is_told_when_each_passage_was_published(cfg, cand):
    sources = [Source(source_id="S1", url="https://example.com/rule",
                      text="The levy takes effect in April.", published_at="2026-04-01")]
    assert "2026-04-01" in _prompt_for(cfg, cand, sources), (
        "the passage block reached the brain without its publication date — the check "
        "cannot rule on how old the evidence is if it is never shown")


def test_an_undated_passage_says_so_rather_than_going_silent(cfg, cand):
    """Absence must be visible. A missing date rendered as nothing is indistinguishable
    from a date the brain simply did not read."""
    sources = [Source(source_id="S1", url="https://example.com/rule",
                      text="The levy takes effect in April.")]
    prompt = _prompt_for(cfg, cand, sources)
    assert "undated" in prompt, (
        "a source with no publication date rendered as if the field did not exist")


def test_a_mixed_set_keeps_each_passage_with_its_own_date(cfg, cand):
    sources = [
        Source(source_id="S1", url="https://a.example/x", text="Old news.",
               published_at="2019-02-02"),
        Source(source_id="S2", url="https://b.example/y", text="New rule.",
               published_at="2026-08-01"),
        Source(source_id="S3", url="https://c.example/z", text="No date on the page."),
    ]
    prompt = _prompt_for(cfg, cand, sources)
    for marker in ("[S1] (2019-02-02)", "[S2] (2026-08-01)", "[S3] (undated)"):
        assert marker in prompt, f"passage block lost {marker!r}"


def test_the_currency_question_rules_on_dates_and_never_kills_on_their_absence():
    """The question is the only instruction the brain gets about how to weigh a date.

    `refuted` on this check KILLS in the side_hustle lane (config.yaml hard_gates), so
    "no date anywhere" must route to `unverifiable`, which does not."""
    q = CHECKS["currency"].lower()
    assert "date" in q, "the why-now question never mentions dates"
    assert "unverifiable" in q, (
        "the question does not tell the brain what to answer when no passage carries a "
        "date — the default would be a refuted, which kills in the side_hustle lane")


def test_every_lane_runs_the_why_now_check():
    """venture ran neither a gate nor a score for it until 2026-08-16."""
    cfg_raw = yaml.safe_load(open(REPO_CONFIG, encoding="utf-8"))
    lanes = cfg_raw["lanes"]
    missing = []
    for name, lane in lanes.items():
        gated = any("currency" in (g or {}) for g in (lane.get("hard_gates") or []))
        scored = "currency" in (lane.get("score_checks") or [])
        if not (gated or scored):
            missing.append(name)
    assert not missing, (
        f"these lanes never ask whether the opportunity is live right now: {missing}")
