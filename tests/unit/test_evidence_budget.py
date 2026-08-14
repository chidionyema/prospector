"""The length contract is arithmetic, so it is testable without a model call.

The defect these tests exist to prevent is the one measured on 2026-08-14: a pack asking
for 6,330 words of prose off 680 words of retrieved evidence, and filling the difference
with sentences that carry nothing. Two of them guard the delivery mechanism rather than
the arithmetic — `{length_rule}` reaching a model verbatim, and the config block being
silently dropped — because both fail SILENTLY and would leave the fix inert while every
unit test still passed.
"""
import json

import pytest

from prospector import evidence_budget as eb


def _src(sid, text):
    return {"source_id": sid, "url": f"https://example.com/{sid}", "text": text}


def _check(verdict, sources):
    return {"check_name": "pain_reality", "verdict": verdict, "sources": sources}


TWENTY = " ".join(["word"] * 20)


def test_only_supported_evidence_buys_words_but_all_of_it_is_counted():
    checks = [_check("supported", [_src("a", TWENTY)]),
              _check("unverifiable", [_src("b", TWENTY)])]
    p = eb.evidence_profile(checks)
    assert (p["words"], p["sources"]) == (20, 1)
    assert (p["words_all"], p["sources_all"]) == (40, 2)


def test_the_same_page_cited_by_three_checks_is_paid_for_once():
    # Otherwise one source bought three times the words, which is the inflation this
    # module exists to stop, reintroduced through the back door.
    checks = [_check("supported", [_src("a", TWENTY)]) for _ in range(3)]
    assert eb.evidence_profile(checks)["words"] == 20


def test_a_passage_reachable_from_a_supported_check_counts_as_supported():
    checks = [_check("unverifiable", [_src("a", TWENTY)]),
              _check("supported", [_src("a", TWENTY)])]
    p = eb.evidence_profile(checks)
    assert p["words"] == 20, "the supported route to the same page must win"
    assert p["words_all"] == 20


def test_empty_passages_are_not_evidence():
    assert eb.evidence_profile([_check("supported", [_src("a", "   ")])])["words"] == 0


def test_checks_may_be_objects_or_dicts():
    class Src:
        def __init__(self):
            self.source_id, self.url, self.text = "a", "u", TWENTY

    class Check:
        def __init__(self):
            self.verdict, self.sources = "supported", [Src()]

    assert eb.evidence_profile([Check()])["words"] == 20


@pytest.mark.parametrize("evidence,expected", [(0, 900), (100, 1000), (1000, 1900)])
def test_the_budget_is_the_base_plus_the_evidence(evidence, expected):
    assert eb.pack_word_budget(evidence, base=900, ratio=1.0,
                               floor=600, ceiling=3600) == expected


def test_the_budget_is_clamped_at_both_ends():
    assert eb.pack_word_budget(0, base=10, ratio=1.0, floor=600, ceiling=3600) == 600
    assert eb.pack_word_budget(99999, base=900, ratio=1.0, floor=600, ceiling=3600) == 3600


def test_a_pack_with_no_evidence_still_clears_the_existing_anti_stub_floor():
    # pack_validation rejects an artifact under 600 CHARS; the floor here is 600 WORDS
    # across three artifacts, so the budget can never be the reason a pack fails that gate.
    from prospector.pack_validation import MIN_PROSE_CHARS
    per = eb.per_artifact_words(eb.pack_word_budget(0, base=0, ratio=1.0,
                                                    floor=600, ceiling=3600))
    assert per * 4 > MIN_PROSE_CHARS, "one word is at least four characters"


def test_the_rule_names_its_own_numbers_and_leaks_no_placeholder():
    rule = eb.length_rule(527, 680)
    assert "527" in rule and "680" in rule
    assert "{" not in rule and "}" not in rule


def test_the_rule_sets_a_ceiling_and_never_a_minimum():
    rule = eb.length_rule(527, 680).lower()
    assert "at most" in rule
    assert "no minimum" in rule
    # The exact phrasing the 2026-08-14 measurement blamed for the padding.
    assert "many paragraphs" not in rule


def test_budget_is_computed_even_when_the_actuator_is_off():
    """A measurement that only runs once the gate is on cannot justify turning it on."""
    b = eb.budget_for([_check("supported", [_src("a", TWENTY)])],
                      type("C", (), {"artifacts": {"enforce_length_budget": False}})())
    assert b["enforced"] is False
    assert b["total_words"] > 0 and b["per_artifact_words"] > 0


def test_config_block_is_read_from_a_dict_or_an_object():
    want = {"enforce_length_budget": True, "claim_check": True, "base_words": 100,
            "words_per_evidence_word": 2.0, "floor_words": 1, "ceiling_words": 9}
    from_obj = eb.artifacts_cfg(type("C", (), {"artifacts": dict(want)})())
    from_dict = eb.artifacts_cfg({"artifacts": dict(want)})
    assert from_obj == from_dict == want


def test_the_shipped_config_actually_reaches_the_budget():
    """`config.py` validates blocks against a key allowlist and DROPS what it doesn't know.

    An unregistered block would leave every default in place, the actuator off, and no
    error anywhere — the fix inert with a green suite.
    """
    from prospector.config import load_config
    cfg = load_config("config.yaml")
    assert cfg.artifacts, "config.yaml `artifacts:` block did not survive validation"
    settings = eb.artifacts_cfg(cfg)
    assert settings["enforce_length_budget"] is True
    assert eb.budget_for([_check("supported", [_src("a", TWENTY)])], cfg)["enforced"]


def test_the_artifacts_prompt_has_no_unfilled_placeholder_after_render():
    """`prompts.render` is a blind str.replace: a kwarg a call site forgets ships verbatim.

    Only `{market_*}` has a shouting guard, so `{length_rule}` needs its own test.
    """
    from prospector.prompts import render
    system, user = render("artifacts", candidate_json="{}", claims_json="[]",
                          type="build_spec", length_rule=eb.length_rule(500, 700),
                          **{k: "" for k in __import__(
                              "prospector.prompts", fromlist=["x"]).ALL_MARKET_KEYS})
    assert "{length_rule}" not in system + user
    assert "at most 500 words" in (system + user).lower()


def test_the_padding_instruction_is_gone_from_the_prompt():
    from prospector.prompts import load_prompt
    raw = load_prompt("artifacts").lower()
    assert "many paragraphs" not in raw, "the instruction that bought the filler is back"


def test_metrics_are_json_shaped():
    json.dumps(eb.budget_for([_check("supported", [_src("a", TWENTY)])], None))


# --- the verifier, now pointed at the document the buyer pays for ----------------------

class _Writer:
    """Returns a prose artifact and remembers whether it was shown claim-check feedback."""

    def __init__(self):
        self.users = []

    def complete_json(self, system, user, **kw):
        self.users.append(user)
        return {"type": "build_spec", "content": "Order the printer's sample pack today."}


class _Checker:
    """Fails the first look, passes the second — the repair turn we pay for."""

    def __init__(self, verdicts):
        self.verdicts, self.calls = list(verdicts), 0

    def complete_json(self, system, user, **kw):
        ok = self.verdicts[min(self.calls, len(self.verdicts) - 1)]
        self.calls += 1
        return {"pass": ok, "violations": [] if ok else [
            {"text": "Most councils now require this.", "issue": "no source"}]}


def _gen(t="build_spec", check_op=None):
    from prospector.artifacts import _gen_one_artifact
    from prospector.prompts import ALL_MARKET_KEYS
    writer = _Writer()
    out = _gen_one_artifact(writer, "{}", "[]", t, {k: "" for k in ALL_MARKET_KEYS},
                            eb.length_rule(500, 700), check_op, [])
    return writer, out


def test_without_a_checker_the_artifact_path_makes_no_verification_call():
    writer, (_t, content, _raw, violations) = _gen()
    assert content and violations == []
    assert len(writer.users) == 1


def test_a_failed_claim_check_buys_exactly_one_repair_turn_that_sees_the_violations():
    checker = _Checker([False, True])
    writer, (_t, _content, _raw, violations) = _gen(check_op=checker)
    assert len(writer.users) == 2, "the draft must be regenerated once"
    assert "FAILED claim-check" in writer.users[1]
    assert "no source" in writer.users[1], "the repair turn must be told what was wrong"
    assert violations == [], "it passed on the retry"


def test_an_artifact_that_never_clears_still_ships_with_its_violations_recorded():
    """Dropping an unverified tweet costs a tweet. Dropping build_spec costs the pack."""
    writer, (_t, content, _raw, violations) = _gen(check_op=_Checker([False, False]))
    assert content, "the document must still be returned"
    assert violations and violations[0]["issue"] == "no source"
    assert len(writer.users) == 2, "and it must not retry forever"


def test_the_financial_model_is_never_claim_checked():
    """It is a JSON fill that Python renders; there is no prose in it to verify."""
    checker = _Checker([False, False])

    class FinWriter(_Writer):
        def complete_json(self, system, user, **kw):
            self.users.append(user)
            return {"type": "financial_model", "monthly_price": 12,
                    "target_customers_month_1": 40}

    from prospector.artifacts import _gen_one_artifact
    from prospector.prompts import ALL_MARKET_KEYS
    writer = FinWriter()
    _t, content, raw, violations = _gen_one_artifact(
        writer, "{}", "[]", "financial_model", {k: "" for k in ALL_MARKET_KEYS},
        eb.length_rule(500, 700), checker, [])
    assert checker.calls == 0 and violations == []
    assert raw == {"type": "financial_model", "monthly_price": 12,
                   "target_customers_month_1": 40} and content


def test_the_length_contract_does_not_reach_the_financial_model_prompt():
    writer, _ = _gen(t="financial_model")
    assert "LENGTH CONTRACT" not in writer.users[0]


def test_the_shipped_config_turns_the_artifact_claim_check_on():
    from prospector.config import load_config
    assert eb.artifacts_cfg(load_config("config.yaml"))["claim_check"] is True
