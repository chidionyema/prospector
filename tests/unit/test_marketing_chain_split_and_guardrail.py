"""The cheap chain writes the shelf copy — and never gets the last word.

Founder directive 2026-08-14: "isplit it but we needd strong guardrails to keep minimax. in
check". The split moves listing/marketing copy off `artifact_operator` onto a separate,
cheap `marketing_operator`; the £49 deliverable stays where it was. Measured on 2026-08-13
the daemon ran four concurrent `claude -p` calls at ~90s each and three of them were writing
a card line and a headline.

The guardrail is not a softer, generation-time rule. `_shelf_copy_breaches` calls the SAME
`pack_linter.check_shelf_copy` that `bridge.py:875` calls at publish time, with the same
`shelf_copy_block_on_breach` actuator and the same `_card_field`/`_cap_words` normalisation,
and a breach REGENERATES the copy on the deliverable chain instead of shipping the pack
UNLISTED. That is the whole of the difference: today a lint breach publishes an unsellable
row and nothing ever revisits it (`bridge.py:927` ANDs `lint_ok` into `is_listed`).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from prospector import artifacts as artifacts_mod
from prospector import run as run_mod
from prospector.config import load_config
from prospector.pack_validation import (
    MIN_MARKETING_CHARS,
    MIN_PROSE_BLOCKS,
    MIN_PROSE_CHARS,
    REQUIRED_ARTIFACTS,
)

# A line with an initialism a stranger has never met — `check_shelf_copy` rules this an
# `error` under `block=True` (probed on disk 2026-08-14), so it is a real publish-time
# refusal, not a fixture invented to make the test pass.
BREACHING_CARD_LINE = "Practices reclaim COSHH fees the ICB never paid"
CLEAN_CARD_LINE = "Clinics recover the fees insurers quietly wrote off"


def _artifacts() -> dict:
    """Artifacts that clear `validate_pack` — so a failure can only come from the copy."""
    body = ("\n\n".join(["A paragraph that carries real weight and keeps going for a while "
                         "so the substance floor is genuinely cleared."] *
                        (MIN_PROSE_BLOCKS + 1)))
    body = body + "x" * max(0, MIN_PROSE_CHARS + 100 - len(body))
    return {name: body for name in REQUIRED_ARTIFACTS}


def _marketing(card_line: str) -> list:
    return [{
        "type": "listing_page",
        "copy": "A listing page long enough to clear the marketing floor. " * 4,
        "card_line": card_line,
        "headline": "Recovering fees that were written off",
        "subhead": "A short second line about who this is for.",
    }]


def _cand():
    return SimpleNamespace(candidate_id="cand-guardrail", title="Fee recovery",
                           one_liner="Clinics recover written-off fees.")


# ---------------------------------------------------------------------------
# 1. The split is real config, in both places a config key must be declared
# ---------------------------------------------------------------------------

def test_marketing_operator_is_loaded_from_the_shipped_config():
    """A dataclass field without a loader entry is a YAML key that silently does nothing."""
    cfg = load_config()
    chain = cfg.marketing_operator
    chain = [chain] if isinstance(chain, str) else list(chain)
    assert chain, "marketing_operator must be declared"
    assert chain[0] != "claude_cli", (
        "the point of the split is that the CHEAP chain writes the shelf copy first; "
        f"config.yaml leads marketing_operator with {chain[0]}")


def test_the_deliverable_chain_is_still_led_by_claude():
    """The £49 prose is not ancillary work — the 2026-08-14 directive was about ancillary."""
    cfg = load_config()
    chain = cfg.artifact_operator
    chain = [chain] if isinstance(chain, str) else list(chain)
    assert chain[0] == "claude_cli"


def test_the_two_chains_are_read_from_two_different_keys():
    """A shared read would make the split a comment rather than a behaviour."""
    cfg = load_config()
    cfg.artifact_operator = ["mock"]
    cfg.marketing_operator = ["mock"]
    sentinel = object()
    seen = []

    def fake_chain(_cfg, order, fallback, *, label):
        seen.append((label, tuple(order)))
        return sentinel

    orig = run_mod._build_prose_chain
    run_mod._build_prose_chain = fake_chain
    try:
        cfg.artifact_operator = ["alpha"]
        cfg.marketing_operator = ["beta"]
        run_mod._build_artifact_op(cfg, sentinel)
        run_mod._build_marketing_op(cfg, sentinel)
    finally:
        run_mod._build_prose_chain = orig

    orders = {label: order for label, order in seen}
    assert set(orders.values()) == {("alpha",), ("beta",)}, orders


def test_a_config_predating_the_split_falls_back_to_the_expensive_chain():
    """An older Config / test double must not raise inside the daemon's publish path.

    It broke `tests/unit/test_publish_reuse_artifacts.py` 4x on 2026-08-14 before this
    fallback existed. The fallback is `artifact_operator`, NOT the non-critical chain: the
    safe default for buyer-visible copy is where it ran until this directive.
    """
    cfg = SimpleNamespace(artifact_operator=["alpha"], retrieval=load_config().retrieval)
    seen = []
    orig = run_mod._build_prose_chain
    run_mod._build_prose_chain = lambda _c, order, fb, *, label: seen.append(tuple(order))
    try:
        run_mod._build_marketing_op(cfg, object())
    finally:
        run_mod._build_prose_chain = orig
    assert seen == [("alpha",)]


# ---------------------------------------------------------------------------
# 2. The guardrail grades what publish grades
# ---------------------------------------------------------------------------

def test_a_breaching_card_line_is_reported():
    cfg = load_config()
    cfg.listing = dict(cfg.listing or {})
    cfg.listing["shelf_copy_block_on_breach"] = True
    breaches = run_mod._shelf_copy_breaches(_cand(), _marketing(BREACHING_CARD_LINE), cfg)
    assert breaches, "check_shelf_copy rules this an error at publish; generation must too"
    assert any("COSHH" in b for b in breaches)


def test_clean_copy_is_not_reported():
    cfg = load_config()
    cfg.listing = dict(cfg.listing or {})
    cfg.listing["shelf_copy_block_on_breach"] = True
    assert run_mod._shelf_copy_breaches(_cand(), _marketing(CLEAN_CARD_LINE), cfg) == []


def test_the_guardrail_follows_the_publish_actuator_not_its_own_opinion():
    """With the gate OFF, publish would list this pack — regenerating it is pure spend."""
    cfg = load_config()
    cfg.listing = dict(cfg.listing or {})
    cfg.listing["shelf_copy_block_on_breach"] = False
    assert run_mod._shelf_copy_breaches(_cand(), _marketing(BREACHING_CARD_LINE), cfg) == []


def test_only_fields_the_marketing_chain_writes_are_graded():
    """`title`/`oneLine` come off the Candidate; a rewrite cannot move them.

    Grading them here would burn all three attempts and escalate to the expensive chain over
    a line no regeneration touches.
    """
    cfg = load_config()
    cfg.listing = dict(cfg.listing or {})
    cfg.listing["shelf_copy_block_on_breach"] = True
    cand = SimpleNamespace(candidate_id="c", title="COSHH ICB fees",
                           one_liner="You should read this.")
    assert run_mod._shelf_copy_breaches(cand, _marketing(CLEAN_CARD_LINE), cfg) == []
    assert set(run_mod._MARKETING_SHELF_FIELDS) == {"cardLine", "headline", "subhead"}


# ---------------------------------------------------------------------------
# 3. The loop: cheap gets first refusal, never the last word
# ---------------------------------------------------------------------------

@pytest.fixture
def spy(monkeypatch):
    """Record which operator each generation call was routed to."""
    calls = {"artifacts": [], "marketing": []}
    state = {"card_line": BREACHING_CARD_LINE}

    def fake_artifacts(op, cand, checks, *, fast_op=None, quality_op=None, cfg=None,
                       score=None, dossier=None, **kw):
        calls["artifacts"].append(quality_op)
        return _artifacts()

    def fake_marketing(op, cand, checks, *, fast_op=None, quality_op=None, check_op=None,
                       cfg=None, **kw):
        calls["marketing"].append(quality_op)
        return _marketing(state["card_line"])

    monkeypatch.setattr(artifacts_mod, "generate_artifacts", fake_artifacts)
    monkeypatch.setattr(artifacts_mod, "generate_marketing_content", fake_marketing)
    return calls, state


def _cfg_blocking():
    cfg = load_config()
    cfg.listing = dict(cfg.listing or {})
    cfg.listing["shelf_copy_block_on_breach"] = True
    return cfg


def test_clean_cheap_copy_never_touches_the_deliverable_chain(spy):
    calls, state = spy
    state["card_line"] = CLEAN_CARD_LINE
    cheap, dear = object(), object()
    run_mod._generate_pack_content(
        object(), _cand(), [], query_op=object(), quality_op=dear, cfg=_cfg_blocking(),
        score=None, marketing_op=cheap)
    assert calls["marketing"] == [cheap], "clean copy must cost exactly one cheap call"
    assert calls["artifacts"] == [dear]


def test_a_breach_escalates_the_rewrite_to_the_deliverable_chain(spy):
    calls, state = spy
    cheap, dear = object(), object()
    run_mod._generate_pack_content(
        object(), _cand(), [], query_op=object(), quality_op=dear, cfg=_cfg_blocking(),
        score=None, marketing_op=cheap)
    assert calls["marketing"][0] is cheap, "cheap chain gets first refusal"
    assert calls["marketing"][1:] and all(o is dear for o in calls["marketing"][1:]), (
        "a chain that just failed the publish-time bar has no claim on the retries")


def test_a_copy_breach_does_not_re_pay_for_the_artifacts(spy):
    """Three claude_cli artifact calls at ~90s each are not the price of one bad card line."""
    calls, _ = spy
    dear = object()
    run_mod._generate_pack_content(
        object(), _cand(), [], query_op=object(), quality_op=dear, cfg=_cfg_blocking(),
        score=None, marketing_op=object())
    assert len(calls["artifacts"]) == 1, (
        f"artifacts regenerated {len(calls['artifacts'])}x for a marketing-only failure")
    assert len(calls["marketing"]) == run_mod._MAX_PACK_GEN_ATTEMPTS


def test_the_escalated_rewrite_is_what_ships(spy):
    """The whole guardrail is worthless if the good copy is generated and then discarded."""
    calls, state = spy
    seen = {"n": 0}
    orig = artifacts_mod.generate_marketing_content

    def escalating(*a, **kw):
        seen["n"] += 1
        state["card_line"] = CLEAN_CARD_LINE if seen["n"] > 1 else BREACHING_CARD_LINE
        return orig(*a, **kw)

    artifacts_mod.generate_marketing_content = escalating
    try:
        _arts, marketing = run_mod._generate_pack_content(
            object(), _cand(), [], query_op=object(), quality_op=object(),
            cfg=_cfg_blocking(), score=None, marketing_op=object())
    finally:
        artifacts_mod.generate_marketing_content = orig

    listing = next(m for m in marketing if m["type"] == "listing_page")
    assert listing["card_line"] == CLEAN_CARD_LINE
    assert len(calls["marketing"]) == 2, "it must stop as soon as the copy is sellable"


def test_an_unsplit_caller_keeps_its_old_behaviour_exactly(spy):
    """`marketing_op=None` is every pre-split call site; the copy runs where it always did."""
    calls, state = spy
    state["card_line"] = CLEAN_CARD_LINE
    dear = object()
    run_mod._generate_pack_content(
        object(), _cand(), [], query_op=object(), quality_op=dear, cfg=_cfg_blocking(),
        score=None)
    assert calls["marketing"] == [dear]


def test_the_breach_and_the_escalation_are_logged_not_silent(spy, caplog):
    """A guardrail that fires silently is indistinguishable from one that never fired."""
    with caplog.at_level("WARNING"):
        run_mod._generate_pack_content(
            object(), _cand(), [], query_op=object(), quality_op=object(),
            cfg=_cfg_blocking(), score=None, marketing_op=object())
    msgs = [r.getMessage() for r in caplog.records]
    assert any("COSHH" in m for m in msgs), "the breach must name the offending words"
    assert any("Escalating shelf copy" in m for m in msgs)
    assert any(r.levelname == "ERROR" for r in caplog.records), (
        "copy that fails even the deliverable chain publishes UNLISTED and must say so")


def test_the_marketing_floor_constant_still_gates_copy_length():
    """`validate_pack` is the other half of the gate; the guardrail does not replace it."""
    assert MIN_MARKETING_CHARS > 0
