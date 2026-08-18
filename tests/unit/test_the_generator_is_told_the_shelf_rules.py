"""The generator must be handed the shelf rules, from the same place the gate reads them.

P3 of `docs/CONTENT_CONTRACT_PROGRAM.md`. Before this, `prompts/generate.md` named no title rule
and no shelf-copy rule anywhere. A title was written free-form, carried untouched through
prescreen, verify, kill filter and score — all of which judge the IDEA — and first read as words
a buyer would see at the publish gate, after the pack had been paid for. On 2026-08-17 that was
34 PASS packs no one could buy.

The rule that matters here is not "the prompt mentions titles". It is that the prompt text and
the checker's bar come from ONE declaration, so they cannot drift. A test that pinned the wording
would pass forever while the two definitions separated, which is the failure it would exist to
catch.
"""
from __future__ import annotations

from prospector import content_contract
from prospector.generate import _shelf_line_directive


class _Cfg:
    """Enough Config for the directive. It takes no config today and must not start to.

    The shelf rules are not a tunable: a title over the cap is refused by the gate whatever the
    config says, so a knob here could only ever make generation and the gate disagree.
    """

    weights: dict = {}


def test_the_directive_carries_the_rules_the_gate_applies():
    out = _shelf_line_directive(_Cfg())
    assert out, "the generator is being sent no shelf rules at all"
    for rule in content_contract.prompt_rules_for(
        content_contract.TITLE, content_contract.ONE_LINER
    ):
        assert rule in out, f"the generator is not told this rule: {rule!r}"


def test_the_text_is_not_a_paraphrase_of_the_registry():
    """The whole point of P3. A copy here drifts the first time a bar moves.

    So this asserts the directive contains the registry's strings VERBATIM, which is only
    possible if it renders them rather than restating them.
    """
    title_rule = content_contract.rule_for_check("title")
    shelf_rule = content_contract.rule_for_check("shelf_copy")
    out = _shelf_line_directive(_Cfg())
    assert title_rule.prompt_rule in out
    assert shelf_rule.prompt_rule in out


def test_the_two_bars_that_strand_packs_reach_the_generator():
    """Concretely: the 60-character cap and the third-person rule, in the words the model sees.

    These two blocked 35 of the 34 stranded packs on 2026-08-17 (a pack can fail more than one).
    If either stops reaching the prompt, the engine goes back to producing them.
    """
    out = _shelf_line_directive(_Cfg())
    assert "60 characters" in out, "the title length cap never reaches the generator"
    assert "third person" in out, "the shelf-copy voice rule never reaches the generator"
    assert "280 characters" in out, "the one-liner cut length never reaches the generator"


def test_an_empty_registry_leaves_the_prompt_byte_identical():
    """Golden-safe by construction, the same contract the directives beside it hold to.

    `prompts.render()` does not raise on an unsubstituted token, so a directive that returned
    something on an empty registry would ship placeholder text to the model verbatim.
    """
    real = content_contract.RULES
    try:
        content_contract.RULES = ()
        assert _shelf_line_directive(_Cfg()) == ""
    finally:
        content_contract.RULES = real


def test_it_is_appended_to_the_generation_prompt():
    """The directive existing is not the same as it being sent. This is the wiring.

    Read from the source rather than by running a generation, which needs a live provider.
    """
    import ast
    import inspect

    from prospector import generate as gen_mod

    src = inspect.getsource(gen_mod)
    tree = ast.parse(src)
    called = {
        n.func.id
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "_shelf_line_directive" in called, (
        "_shelf_line_directive is defined but never called — the generator is still not told "
        "the shelf rules"
    )
