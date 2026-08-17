"""E6 shadow-mode prefilter — the whole point is that it changes NOTHING.

The load-bearing test is `test_prescreen_result_identical_with_shadow_on_and_off`:
it runs the real `prescreen()` over a mixed batch with the flag off and on, and
asserts the results are byte-identical (compared as their JSON serialisation, so
a float that merely reprs the same is not enough).

No network, no LLM: the operator is a scripted stub. No production store is
touched: every test pins `prescreen_prefilter.log_dir` to `tmp_path`.
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.error

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
    pf.reset_embed_cache()
    yield
    pf.reset_cache()
    pf.reset_embed_cache()


# --------------------------------------------------------------------------- #
# ollama backend — mocked HTTP (CI has no ollama; the ONE live test is below)
# --------------------------------------------------------------------------- #

def _fake_vector(text: str, dim: int = 16) -> list[float]:
    """Deterministic pseudo-embedding with REAL similarity structure.

    Content words are hashed into `dim` buckets, so a reworded idea lands in
    overlapping buckets and an unrelated one does not. A constant vector would
    make every kNN test vacuous.
    """
    vec = [0.0] * dim
    for tok in pf._content_tokens(text):
        vec[int(hashlib.sha1(tok.encode("utf-8")).hexdigest(), 16) % dim] += 1.0
    if not any(vec):
        vec[0] = 1.0
    return vec


class FakeOllamaHTTP:
    """Stands in for `pf._http_post_json`. Records every call; can fail on cue."""

    def __init__(self, dim: int = 16, fail_after: int | None = None,
                 error: Exception | None = None, body: dict | None = None) -> None:
        self.dim = dim
        self.fail_after = fail_after
        self.error = error or urllib.error.URLError("Connection refused")
        self.body = body
        self.calls: list[tuple[str, dict, float]] = []

    def __call__(self, url: str, payload: dict, timeout: float) -> dict:
        self.calls.append((url, payload, timeout))
        if self.fail_after is not None and len(self.calls) > self.fail_after:
            raise self.error
        if self.body is not None:
            return self.body
        return {"embedding": _fake_vector(payload["prompt"], self.dim)}


@pytest.fixture
def fake_http(monkeypatch):
    """Mocked transport AND a pinned environment.

    Without the delenv the url/timeout assertions below read whatever
    `OLLAMA_BASE_URL` the developer's shell happens to export, which is a test
    that passes on one machine and fails on the next.
    """
    monkeypatch.delenv(pf.OLLAMA_BASE_URL_ENV, raising=False)
    monkeypatch.delenv(pf.OLLAMA_TIMEOUT_ENV, raising=False)
    http = FakeOllamaHTTP()
    monkeypatch.setattr(pf, "_http_post_json", http)
    return http


def test_ollama_backend_is_accepted_in_the_same_backend_slot(fake_http):
    """`ollama:<model>` loads a dense encoder and talks to /api/embeddings."""
    emb = pf.load_embedder("ollama:nomic-embed-text")
    assert emb.name == "ollama:nomic-embed-text"
    assert emb.degraded is False
    # Loading probes once, so an unreachable daemon is caught before the run.
    url, payload, timeout = fake_http.calls[0]
    assert url == "http://localhost:11434/api/embeddings"
    assert payload["model"] == "nomic-embed-text"
    assert timeout == pf.OLLAMA_DEFAULT_TIMEOUT_S

    vec = emb.encode("Probate clear-out concierge")
    assert len(vec) == 16 and sorted(vec, key=int)[0] == "0"
    assert all(isinstance(v, float) for v in vec.values())
    # Dense keys are positional indices; lexical keys are "w:"/"c:" prefixed.
    assert not any(k.startswith(("w:", "c:")) for k in vec)


def test_ollama_backend_keeps_the_model_tag_and_defaults_the_model(fake_http):
    assert pf.load_embedder("ollama:nomic-embed-text:latest").model == "nomic-embed-text:latest"
    assert pf.load_embedder("ollama").model == pf.OLLAMA_DEFAULT_MODEL


def test_ollama_embeddings_are_cached_by_content_hash(fake_http):
    emb = pf.load_embedder("ollama:nomic-embed-text")
    before = len(fake_http.calls)
    a = emb.encode("Probate clear-out concierge")
    assert len(fake_http.calls) == before + 1
    b = emb.encode("Probate clear-out concierge")
    assert b == a, "cache returned a different vector"
    assert len(fake_http.calls) == before + 1, "re-embedded a text already seen"
    emb.encode("Retiree garden harvest share")
    assert len(fake_http.calls) == before + 2, "a new text must actually be embedded"


def test_ollama_unreachable_degrades_to_lexical_and_says_so(monkeypatch):
    """The write-only-field trap: degraded lexical must not read as chosen lexical."""
    monkeypatch.setattr(pf, "_http_post_json",
                        FakeOllamaHTTP(fail_after=0))  # probe itself fails
    emb = pf.load_embedder("ollama:nomic-embed-text")
    assert emb.degraded is True
    assert emb.name == "lexical<-ollama:nomic-embed-text"
    vec = emb.encode("Probate clear-out concierge")
    assert vec and all(k.startswith(("w:", "c:")) for k in vec), "not the lexical vector"


@pytest.mark.parametrize("body", [{"error": "model 'nope' not found"}, {"embedding": []}, {}])
def test_a_daemon_that_answers_without_an_embedding_is_a_failure(monkeypatch, body):
    """200-with-an-error-body must degrade, not yield an empty vector that abstains."""
    monkeypatch.setattr(pf, "_http_post_json", FakeOllamaHTTP(body=body))
    emb = pf.load_embedder("ollama:nomic-embed-text")
    assert emb.degraded is True and emb.name == "lexical<-ollama:nomic-embed-text"


def test_every_shadow_row_records_the_degraded_backend(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "_http_post_json", FakeOllamaHTTP(fail_after=0))
    op = ScriptedOp(_DECISIONS)
    cfg = _cfg(tmp_path, shadow=True, backend="ollama:nomic-embed-text")
    for c in _cands():
        prescreen(op, cfg, c)
    rows = _rows(tmp_path)
    assert rows and all(r["backend_used"] == "lexical<-ollama:nomic-embed-text" for r in rows)


def test_a_mid_run_ollama_failure_flips_backend_used_on_the_row_it_happens(tmp_path, monkeypatch):
    """Rows embedded densely keep the dense name; rows after the outage do not."""
    # 1 probe + 1 successful encode, then the daemon dies.
    monkeypatch.setattr(pf, "_http_post_json", FakeOllamaHTTP(fail_after=2))
    emb = pf.load_embedder("ollama:nomic-embed-text")
    shadow = pf.PrescreenShadow(
        tmp_path / "s.jsonl",
        pf.PrefilterSettings(shadow_mode=True, backend="ollama:nomic-embed-text",
                             min_exemplars=1, min_similarity=0.0),
        embedder=emb,
    )
    first = shadow.record(_cands()[1], llm_keep=True, llm_score=0.9,
                          llm_reason="kept", llm_called=True)
    second = shadow.record(_cands()[3], llm_keep=True, llm_score=0.9,
                           llm_reason="kept", llm_called=True)
    assert first["backend_used"] == "ollama:nomic-embed-text"
    assert second["backend_used"] == "lexical<-ollama:nomic-embed-text"


def test_prescreen_result_identical_with_shadow_on_and_off_ollama_backend(tmp_path, fake_http):
    """The E6 invariant again, on the dense path: still zero decisions changed."""
    off_op = ScriptedOp(_DECISIONS)
    off = [prescreen(off_op, _cfg(tmp_path, shadow=False), c) for c in _cands()]

    on_op = ScriptedOp(_DECISIONS)
    on_cfg = _cfg(tmp_path, shadow=True, backend="ollama:nomic-embed-text",
                  min_exemplars=1, threshold=0.99, min_similarity=0.0)
    on = [prescreen(on_op, on_cfg, c) for c in _cands()]

    assert json.dumps(off) == json.dumps(on)
    assert off_op.calls == on_op.calls
    rows = _rows(tmp_path)
    # The dense encoder really ran (no silent degradation), and it WANTED to drop
    # something — otherwise the identity above proves nothing.
    assert all(r["backend_used"] == "ollama:nomic-embed-text" for r in rows)
    assert any(r["would_drop"] for r in rows), "prefilter never fired; identity is vacuous"
    assert len(fake_http.calls) > 1


def test_host_and_timeout_come_from_the_environment(monkeypatch):
    """No config key exists for either (config.py's strict allowlist), so: env."""
    monkeypatch.delenv(pf.OLLAMA_BASE_URL_ENV, raising=False)
    monkeypatch.delenv(pf.OLLAMA_TIMEOUT_ENV, raising=False)
    assert pf.ollama_base_url() == "http://localhost:11434"
    assert pf.ollama_timeout_s() == pf.OLLAMA_DEFAULT_TIMEOUT_S

    # operator.py's OLLAMA_BASE_URL points at the OpenAI-compatible /v1 root;
    # /api/embeddings is not under it, so the suffix must be stripped or every
    # call 404s and reads as "ollama is down".
    monkeypatch.setenv(pf.OLLAMA_BASE_URL_ENV, "http://box:11434/v1/")
    assert pf.ollama_base_url() == "http://box:11434"
    monkeypatch.setenv(pf.OLLAMA_BASE_URL_ENV, "http://box:11434")
    assert pf.ollama_base_url() == "http://box:11434"

    monkeypatch.setenv(pf.OLLAMA_TIMEOUT_ENV, "2.5")
    assert pf.ollama_timeout_s() == 2.5
    for bad in ("", "abc", "0", "-1"):
        monkeypatch.setenv(pf.OLLAMA_TIMEOUT_ENV, bad)
        assert pf.ollama_timeout_s() == pf.OLLAMA_DEFAULT_TIMEOUT_S


# --------------------------------------------------------------------------- #
# The ONE live test: skipped whenever ollama is not reachable.
# Run it explicitly with: -k live_ollama
# --------------------------------------------------------------------------- #

def test_a_degraded_embedder_says_so():
    """The property the live test's mid-run skip depends on, pinned without a daemon.

    The live test below can only skip on `emb.degraded`, and it never runs on a box with no
    ollama — so without this, the branch that keeps main green would itself be untested.
    """
    emb = pf.OllamaEmbedder(model=pf.OLLAMA_DEFAULT_MODEL)
    assert emb.degraded is False
    emb.degrade(TimeoutError("timed out"))
    assert emb.degraded is True
    assert emb.name == f"lexical<-ollama:{pf.OLLAMA_DEFAULT_MODEL}"
    # And it still answers, with the shorter lexical vector that made CI read `67 == 768`.
    assert 0 < len(emb.encode("probate clear-out concierge")) < 768


def test_live_ollama_backend_discriminates_paraphrase_from_unrelated():
    """Proof the dense backend is real: 768 dims, and it ranks a rewording higher.

    Skips (never fails) when the daemon or the model is absent — CI has neither.
    """
    try:
        probe = pf.ollama_embed("prescreen prefilter probe",
                                model=pf.OLLAMA_DEFAULT_MODEL, timeout=15.0)
    except Exception as e:  # unreachable daemon, missing model, timeout
        pytest.skip(f"live ollama unavailable ({type(e).__name__}: {e})")

    assert len(probe) == 768, f"nomic-embed-text should be 768-dim, got {len(probe)}"

    emb = pf.load_embedder(f"ollama:{pf.OLLAMA_DEFAULT_MODEL}")
    assert emb.degraded is False and emb.name == f"ollama:{pf.OLLAMA_DEFAULT_MODEL}"

    probate = emb.encode("Probate clear-out concierge sorting a deceased relative's home")
    reworded = emb.encode("Deceased estate clearance concierge for probate executors")
    unrelated = emb.encode("Weekly produce boxes from retired gardeners' allotments")

    # The load-time probe above proves the daemon answered ONCE. It can still time out on a
    # real embed a second later, and `encode` then calls `degrade()`, which swaps in the
    # lexical fallback for the rest of the encoder's life and returns a 67-dim sparse
    # vector. Asserting 768 on that measures the fallback while claiming to measure ollama:
    # on 2026-08-17 this failed in CI as `assert 67 == 768` and left main red, which then
    # blocked the deploy gate from shipping anything.
    #
    # A mid-run fallback is the same condition the docstring already skips for, so skip on
    # it — but only on it. `emb.degraded` is exact (`_fallback is not None`), so a genuine
    # discrimination regression still fails below and cannot hide behind this branch.
    if emb.degraded:
        pytest.skip(f"live ollama degraded mid-test — backend is now {emb.name!r}")

    assert len(probate) == 768

    near = pf._sparse_cosine(probate, reworded)
    far = pf._sparse_cosine(probate, unrelated)
    print(f"\n[live ollama {pf.OLLAMA_DEFAULT_MODEL}] dim={len(probate)} "
          f"cos(probate, reworded)={near:.4f}  cos(probate, unrelated)={far:.4f}  "
          f"margin={near - far:+.4f}")
    assert near > far, f"no discrimination: paraphrase {near:.4f} <= unrelated {far:.4f}"
    assert pf._sparse_cosine(probate, probate) == pytest.approx(1.0, abs=1e-6)


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


def test_an_absent_config_block_is_off():
    """A config that never mentions the block must not enable it. This is the half of the
    old `test_default_config_block_is_off` that is a SAFETY property rather than a record of
    what config.yaml happened to say, and it does not move when the shipped file does."""
    assert Config().prescreen_prefilter == {}
    assert pf.settings_from_config(Config()).shadow_mode is False
    assert pf.get_shadow(Config()) is None


# The shipped file's own value is asserted separately and deliberately. The old single test
# bundled both, so turning the shadow on — the ONLY route to E6's measurement, since no
# historical prescreen decision is persisted to replay offline — read as a safety regression
# when it is nothing of the kind. Splitting them keeps the safety guard load-bearing while
# letting the operational value change with a reason attached.
_LOG_ONLY_KEYS = {"shadow_mode", "backend", "threshold", "neighbours", "min_similarity",
                  "min_exemplars", "max_exemplars", "log_dir"}


def test_shipped_block_is_on_and_still_cannot_act():
    """Shadow ON since 2026-08-07, and every key in the block is log-only.

    `shadow_mode` being true is not a licence to drop anything: there is no acting key in
    this block at all, and that is what this pins. If someone adds one, the key-set
    assertion fails here before it can ever run against a live candidate.
    """
    shipped = load_config()
    block = shipped.prescreen_prefilter
    assert block.get("shadow_mode") is True, "E6 needs live rows; see config.yaml"
    assert pf.get_shadow(shipped) is not None
    assert set(block) <= _LOG_ONLY_KEYS, f"new key in a log-only block: {set(block) - _LOG_ONLY_KEYS}"
    # The backend stays lexical while E6 is being measured — switching it mid-measurement
    # would change what the agreement number means (config.yaml says so at the `backend` key).
    assert block.get("backend") == "lexical"


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


def test_log_path_defaults_under_the_store_dir(tmp_path, monkeypatch):
    """The fallback branch — asserted with the env override explicitly OFF.

    `tests/conftest.py::_isolate_prescreen_shadow` now sets
    PROSPECTOR_PRESCREEN_SHADOW_LOG_DIR for every test, because without it every test
    that drove a candidate through a `load_config()` cfg wrote shadow rows into the real
    store/prescreen_shadow/ — the corpus E6's decision reads. That fixture is what makes
    this test's own precondition (no env override) something it has to state rather than
    assume."""
    monkeypatch.delenv("PROSPECTOR_PRESCREEN_SHADOW_LOG_DIR", raising=False)

    class C:
        store_dir = tmp_path / "store"
        prescreen_prefilter = {"shadow_mode": True}
    p = pf.resolve_log_path(C(), pf.settings_from_config(C()))
    assert p.parent == tmp_path / "store" / "prescreen_shadow"
    assert p.name.startswith("shadow-") and p.suffix == ".jsonl"


def test_log_path_env_override_beats_the_store_dir(tmp_path, monkeypatch):
    """The escape hatch the test fence rides on, pinned in both directions.

    Without this, a future tidy-up could delete the env branch from `resolve_log_path`
    and only the conftest fixture would break — silently, since shadow rows are log-only
    by construction and nothing turns red when they land in the wrong file."""
    monkeypatch.setenv("PROSPECTOR_PRESCREEN_SHADOW_LOG_DIR", str(tmp_path / "elsewhere"))

    class C:
        store_dir = tmp_path / "store"
        prescreen_prefilter = {"shadow_mode": True}
    p = pf.resolve_log_path(C(), pf.settings_from_config(C()))
    assert p.parent == tmp_path / "elsewhere"

    # …and explicit config still outranks the env var.
    class D:
        store_dir = tmp_path / "store"
        prescreen_prefilter = {"shadow_mode": True, "log_dir": str(tmp_path / "declared")}
    q = pf.resolve_log_path(D(), pf.settings_from_config(D()))
    assert q.parent == tmp_path / "declared"
