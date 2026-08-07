"""E6 shadow-mode prefilter — the whole point is that it changes NOTHING.

The load-bearing test is `test_prescreen_result_identical_with_shadow_on_and_off`:
it runs the real `prescreen()` over a mixed batch with the flag off and on, and
asserts the results are byte-identical (compared as their JSON serialisation, so
a float that merely reprs the same is not enough).

No network, no LLM: the operator is a scripted stub. No production store is
touched: every test pins `prescreen_prefilter.log_dir` to `tmp_path`.
"""
from __future__ import annotations

import json
import re

import pytest

from prospector import prescreen_prefilter as pf
from prospector.config import Config, _validate_prescreen_prefilter, load_config
from prospector.models import Candidate
from prospector.prescreen import prescreen

# --------------------------------------------------------------------------- #
# Fixtures — no network, no LLM
# --------------------------------------------------------------------------- #

class ScriptedOp:
    """Deterministic stand-in for the prescreen LLM. Counts calls."""

    def __init__(self, decisions: dict[str, dict]) -> None:
        self.decisions = decisions
        self.calls: list[str] = []

    def complete_json(self, system: str, user: str) -> dict:
        # The rendered prompt embeds the candidate JSON inside prose, so pull the
        # title out with a regex rather than parsing the whole user message.
        m = re.search(r'"title"\s*:\s*"((?:[^"\\]|\\.)*)"', user)
        title = json.loads(f'"{m.group(1)}"') if m else ""
        self.calls.append(title)
        return self.decisions.get(title, {"keep": True, "score": 0.7,
                                          "reason": "kept", "diversity_features": "x"})


def _cands() -> list[Candidate]:
    return [
        # Structural reject (stage 1) — never reaches the LLM.
        Candidate(title="Two-sided marketplace for plumbers",
                  one_liner="A two-sided marketplace matching plumbers to homeowners"),
        # LLM keeps.
        Candidate(title="Probate clear-out concierge",
                  one_liner="Sorting and clearing a deceased relative's home for executors"),
        # LLM rejects.
        Candidate(title="Vibes-based analytics",
                  one_liner="Dashboards that feel right about your numbers"),
        Candidate(title="Retiree garden harvest share",
                  one_liner="Weekly produce boxes from retired gardeners' allotments"),
        Candidate(title="Mobile notary bonding service",
                  one_liner="Bond and insurance paperwork for travelling notaries"),
    ]


_DECISIONS = {
    "Vibes-based analytics": {"keep": False, "score": 0.1, "reason": "no mechanism",
                              "diversity_features": ""},
}


def _cfg(tmp_path, *, shadow: bool, **over) -> Config:
    block = {"shadow_mode": shadow, "log_dir": str(tmp_path / "shadow"), **over}
    return Config(prescreen_prefilter=block)


@pytest.fixture(autouse=True)
def _clean_cache():
    pf.reset_cache()
    yield
    pf.reset_cache()


# --------------------------------------------------------------------------- #
# THE invariant: zero decisions changed
# --------------------------------------------------------------------------- #

def test_prescreen_result_identical_with_shadow_on_and_off(tmp_path):
    """Shadow mode must be observationally inert on the RESULT."""
    off_op = ScriptedOp(_DECISIONS)
    off_cfg = _cfg(tmp_path, shadow=False)
    off = [prescreen(off_op, off_cfg, c) for c in _cands()]

    on_op = ScriptedOp(_DECISIONS)
    on_cfg = _cfg(tmp_path, shadow=True, min_exemplars=1, threshold=0.99,
                  min_similarity=0.0)
    on = [prescreen(on_op, on_cfg, c) for c in _cands()]

    # Byte-identical results (JSON, so 0.7 vs 0.7000000001 cannot slip through).
    assert json.dumps(off) == json.dumps(on)
    # And the LLM was called on exactly the same candidates, in the same order:
    # a prefilter that acted would have suppressed a call.
    assert off_op.calls == on_op.calls
    # threshold 0.99 + min_exemplars 1 means the prefilter WANTED to drop things —
    # proving the identity above is not vacuous.
    rows = _rows(tmp_path)
    assert any(r["would_drop"] for r in rows), "prefilter never fired; identity is vacuous"


def test_shadow_off_writes_nothing(tmp_path):
    op = ScriptedOp(_DECISIONS)
    for c in _cands():
        prescreen(op, _cfg(tmp_path, shadow=False), c)
    assert not (tmp_path / "shadow").exists()


def test_default_config_block_is_off():
    """Default = OFF, both in the dataclass and in the shipped config.yaml."""
    assert Config().prescreen_prefilter == {}
    assert pf.settings_from_config(Config()).shadow_mode is False
    shipped = load_config()
    assert shipped.prescreen_prefilter.get("shadow_mode") is False
    assert pf.get_shadow(shipped) is None


def test_record_shadow_never_raises_on_a_broken_recorder(tmp_path, monkeypatch):
    """An observer that can raise is a decision change by another name."""
    def boom(_cfg):
        raise RuntimeError("exemplar store on fire")
    monkeypatch.setattr(pf, "get_shadow", boom)
    op = ScriptedOp(_DECISIONS)
    out = prescreen(op, _cfg(tmp_path, shadow=True), _cands()[1])
    assert out == (True, 0.7, "kept", "x")


# --------------------------------------------------------------------------- #
# The shadow log itself
# --------------------------------------------------------------------------- #

def _rows(tmp_path) -> list[dict]:
    files = sorted((tmp_path / "shadow").glob("shadow-*.jsonl"))
    assert files, "no shadow log written"
    return [json.loads(line) for line in files[0].read_text().splitlines() if line.strip()]


def test_shadow_log_pairs_would_drop_with_the_llm_decision(tmp_path):
    op = ScriptedOp(_DECISIONS)
    cfg = _cfg(tmp_path, shadow=True)
    cands = _cands()
    for c in cands:
        prescreen(op, cfg, c)

    rows = _rows(tmp_path)
    assert len(rows) == len(cands)
    assert [r["title"] for r in rows] == [c.title for c in cands]
    assert all(r["shadow_only"] is True for r in rows)
    assert all(r["backend_used"] == "lexical" for r in rows)

    by_title = {r["title"]: r for r in rows}
    # Structural reject: LLM never called, so E6's saving metric must not count it.
    assert by_title["Two-sided marketplace for plumbers"]["llm_called"] is False
    assert by_title["Two-sided marketplace for plumbers"]["llm_keep"] is False
    # LLM stage ran for the survivors, and its verdict is recorded verbatim.
    assert by_title["Probate clear-out concierge"]["llm_called"] is True
    assert by_title["Probate clear-out concierge"]["llm_keep"] is True
    assert by_title["Vibes-based analytics"]["llm_keep"] is False
    assert by_title["Vibes-based analytics"]["llm_reason"] == "no mechanism"


def test_cold_start_abstains_and_never_drops(tmp_path):
    """Below min_exemplars the prefilter must abstain, whatever the threshold."""
    op = ScriptedOp(_DECISIONS)
    cfg = _cfg(tmp_path, shadow=True, min_exemplars=100, threshold=1.0)
    for c in _cands():
        prescreen(op, cfg, c)
    rows = _rows(tmp_path)
    assert all(r["abstained"] for r in rows)
    assert all(r["abstain_reason"] == "cold_start" for r in rows)
    assert not any(r["would_drop"] for r in rows)
    assert all(r["prefilter_score"] is None for r in rows)


def test_score_is_out_of_sample(tmp_path):
    """A candidate must not be scored against itself (prequential ordering)."""
    shadow = pf.PrescreenShadow(
        tmp_path / "s.jsonl",
        pf.PrefilterSettings(shadow_mode=True, min_exemplars=1, min_similarity=0.0),
    )
    cand = Candidate(title="Probate clear-out concierge", one_liner="executor clearances")
    first = shadow.record(cand, llm_keep=False, llm_score=0.0, llm_reason="r", llm_called=True)
    assert first["abstained"] is True and first["abstain_reason"] == "cold_start"
    # Now the corpus holds exactly one exemplar (a reject) — an identical candidate
    # scores 0.0 keep-mass off it, i.e. the score came from the CORPUS, not itself.
    second = shadow.record(cand, llm_keep=True, llm_score=1.0, llm_reason="r", llm_called=True)
    assert second["prefilter_score"] == 0.0
    assert second["neighbours_used"] == 1
    assert second["agreement"] == pf.DISAGREE_FALSE_DROP


def test_exemplars_seed_across_processes(tmp_path):
    """A second recorder re-reads the log, so agreement accumulates across runs."""
    path = tmp_path / "s.jsonl"
    settings = pf.PrefilterSettings(shadow_mode=True, min_exemplars=1, min_similarity=0.0)
    a = pf.PrescreenShadow(path, settings)
    for c in _cands():
        a.record(c, llm_keep=True, llm_score=0.9, llm_reason="kept", llm_called=True)

    b = pf.PrescreenShadow(path, settings)
    row = b.record(Candidate(title="Probate clear-out helper", one_liner="executor clearances"),
                   llm_keep=True, llm_score=0.9, llm_reason="kept", llm_called=True)
    assert row["abstained"] is False, "fresh recorder did not seed from the log"
    assert row["neighbours_used"] >= 1


def test_similarity_ranks_the_reworded_idea_above_an_unrelated_one():
    """The lexical vector must actually carry idea identity, not just noise."""
    v = pf.lexical_vector
    probate = v("Probate clear-out concierge sorting a deceased relative's home")
    reworded = v("Deceased estate clearance concierge for probate executors")
    unrelated = v("Weekly produce boxes from retired gardeners' allotments")
    assert pf._sparse_cosine(probate, reworded) > pf._sparse_cosine(probate, unrelated)
    assert pf._sparse_cosine(probate, probate) == pytest.approx(1.0)
    assert pf.lexical_vector("") == {}


def test_summarise_reports_the_e6_metrics(tmp_path):
    op = ScriptedOp(_DECISIONS)
    cfg = _cfg(tmp_path, shadow=True, min_exemplars=1, threshold=0.99, min_similarity=0.0)
    for c in _cands():
        prescreen(op, cfg, c)
    log = sorted((tmp_path / "shadow").glob("shadow-*.jsonl"))[0]
    s = pf.summarise_shadow_log(log)
    assert s["rows"] == 5
    # 1 structural reject never reached the LLM; the saving metric excludes it.
    assert s["llm_called"] == 4
    assert 0.0 <= s["llm_calls_saved_pct"] <= 100.0
    assert s["false_drops"] <= s["llm_kept"]
    assert sum(s["agreement_counts"].values()) == 5
    assert pf.summarise_shadow_log(tmp_path / "nope.jsonl")["rows"] == 0


# --------------------------------------------------------------------------- #
# Config validation
# --------------------------------------------------------------------------- #

def test_unknown_config_key_raises_at_startup():
    with pytest.raises(ValueError, match="unknown key"):
        _validate_prescreen_prefilter({"shadow_mod": True})
    with pytest.raises(ValueError, match="must be a mapping"):
        _validate_prescreen_prefilter(["shadow_mode"])
    assert _validate_prescreen_prefilter(None) == {}


def test_unknown_backend_degrades_to_lexical():
    assert pf.load_embedder("no-such-backend").name == "lexical"
    assert pf.load_embedder("sentence_transformers:nomic-ai/nomic-embed-text-v2-moe").name == \
        "lexical", "a dense backend appeared; update the E6 blocker note"


def test_log_path_defaults_under_the_store_dir(tmp_path):
    class C:
        store_dir = tmp_path / "store"
        prescreen_prefilter = {"shadow_mode": True}
    p = pf.resolve_log_path(C(), pf.settings_from_config(C()))
    assert p.parent == tmp_path / "store" / "prescreen_shadow"
    assert p.name.startswith("shadow-") and p.suffix == ".jsonl"
