"""The content contract must be checked against the gate, never trusted over it.

`prospector/content_contract.py` declares, in one place, what each buyer-facing field promises,
what repairs it, and which config key switches it on. That declaration is only worth anything
while it matches the gate it describes. A registry that quietly falls behind is worse than no
registry: every lookup still returns something, and the something is wrong.

So these tests read the truth from two places that cannot be faked:

* `inspect.signature(pack_linter.lint_pack)` — the knobs the gate really takes.
* the `lint_pack(...)` call in `prospector/bridge.py`, read as a syntax tree — the config keys
  the gate is really wired to.

The registry is asserted against both. Add a knob to the gate and this fails until the contract
declares it. Rename a config key and this fails until the contract follows. That is the whole
point: §1.4 of `docs/CONTENT_CONTRACT_PROGRAM.md` is about rules whose three facts drifted apart
because nothing held them together.

Note the direction of every assertion. The gate is the source of truth and the contract is the
thing under test. A test written the other way round would pass while the gate grew a rule
nobody declared, which is exactly the failure this is here to catch.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from prospector import bridge, content_contract, pack_linter

_REPO = Path(__file__).resolve().parents[2]


def _gate_params() -> dict[str, inspect.Parameter]:
    return dict(inspect.signature(pack_linter.lint_pack).parameters)


def _is_actuator(name: str) -> bool:
    """Does this parameter switch a rule on or off, as opposed to setting a bar?

    Shape, not type. `title_block_on_breach` defaults to a module constant rather than a literal,
    so reading the default cannot classify it; and `max_grammar_defects_per_1k` is a float that
    nonetheless disables its rule at 0.0. The naming convention is what the codebase actually
    holds to, so it is what is used here — and `_bar_params_are_real_parameters` below covers the
    other half, so a knob cannot escape both tests by being named unusually.
    """
    return "_block" in name or name.endswith(("_enabled", "_on_breach"))


def _config_keys_passed_to_the_gate() -> dict[str, str]:
    """Map each `lint_pack` keyword to the `listing.*` key `bridge.py` reads for it.

    Read from the syntax tree rather than by calling the code, because the call site is inside a
    long publish path that needs a live candidate, a store and a provider. The wiring is a
    literal in the source; read the literal.
    """
    tree = ast.parse((_REPO / "prospector" / "bridge.py").read_text())
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name != "lint_pack":
            continue
        for kw in node.keywords:
            if kw.arg is None:
                continue
            # The value is usually wrapped — `int(listing.get("x", 60) or 60)` — so walk it for
            # the first `.get("literal")` rather than matching one exact expression shape.
            for sub in ast.walk(kw.value):
                if (
                    isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr == "get"
                    and sub.args
                    and isinstance(sub.args[0], ast.Constant)
                    and isinstance(sub.args[0].value, str)
                ):
                    out[kw.arg] = sub.args[0].value
                    break
    return out


def test_every_gate_actuator_is_declared_in_the_contract():
    """A rule the gate can enforce that the contract does not know about is invisible.

    That is the §1.4 failure exactly: the check exists, the switch exists, and nothing connects
    them to the field they grade or the repair that fixes them — so promoting the rule strands
    every pack made while it was off, and no one can see why.
    """
    actuators = {n for n in _gate_params() if _is_actuator(n)}
    assert actuators, "no actuator-shaped parameters found — the detector is broken, not the gate"

    declared = content_contract.declared_gate_params()
    missing = actuators - declared - content_contract.UNMAPPED_ACTUATORS
    assert not missing, (
        "lint_pack takes actuators the content contract does not declare: "
        f"{sorted(missing)}. Add a Rule for each in prospector/content_contract.py naming the "
        "field it grades and the repair that fixes it — or, if it genuinely has no check yet, "
        "add it to UNMAPPED_ACTUATORS so the gap is named rather than silent."
    )


def test_the_contract_declares_no_actuator_the_gate_does_not_have():
    """The other direction: a stale declaration is a lie that reads as coverage.

    `blocking_checks()` would report a rule as live off a config key nothing consumes.
    """
    params = set(_gate_params())
    stale = content_contract.declared_gate_params() - params
    assert not stale, (
        f"content_contract declares gate params lint_pack does not take: {sorted(stale)}. "
        "The gate was renamed or the knob removed; update the contract to match."
    )


def test_bar_params_are_real_parameters():
    """BAR_PARAMS is the contract's claim that these knobs set a threshold, not an on/off.

    If one is renamed the claim is stale, and the actuator test above would then have to decide
    about a name that no longer exists.
    """
    params = set(_gate_params())
    stale = content_contract.BAR_PARAMS - params
    assert not stale, (
        f"content_contract.BAR_PARAMS names parameters lint_pack does not take: {sorted(stale)}"
    )


def test_every_declared_config_key_is_the_one_the_gate_is_wired_to():
    """The strong one. This is the drift §1.4 describes, caught mechanically.

    The config key and the gate keyword are usually different words — `lint_grammar` actuates
    `grammar_enabled`, `house_spec_block_register` actuates `register_block`. The contract has to
    carry the mapping, and a mapping no one checks is a mapping that rots.
    """
    wiring = _config_keys_passed_to_the_gate()
    assert wiring, "could not read any listing keys from the lint_pack call in bridge.py"

    wrong = []
    for rule in content_contract.RULES:
        if not rule.gate_param or rule.config_key is None:
            continue
        actual = wiring.get(rule.gate_param)
        if actual is None:
            continue  # covered by the declared-vs-signature tests above
        if actual != rule.config_key:
            wrong.append((rule.check, rule.gate_param, rule.config_key, actual))

    assert not wrong, (
        "content_contract names the wrong config key for these rules "
        "(check, gate_param, declared, actually wired): " + repr(wrong)
    )


@pytest.mark.parametrize("rule", content_contract.RULES, ids=lambda r: r.check)
def test_each_rule_is_internally_coherent(rule):
    """Cheap shape checks, so a hand-edited registry cannot ship half a rule."""
    assert rule.repair in content_contract.REPAIRS, (
        f"{rule.check} declares repair {rule.repair!r}, which the console cannot action"
    )
    assert rule.fields, f"{rule.check} grades no field"
    if rule.config_key is not None:
        assert rule.gate_param, (
            f"{rule.check} names a config key with no gate param — the key would be read by "
            "nothing"
        )


def test_the_two_fields_that_strand_the_most_packs_carry_prompt_text():
    """P3 depends on this: the generator is handed the rule, not a paraphrase of it.

    Title and shelf copy blocked 35 of the 34 stranded packs on 2026-08-17 (a pack can fail more
    than one check). If either loses its prompt text, the generator goes back to being told the
    bar in prose that drifts — which is §1.1, the defect this programme exists to close.
    """
    for check in ("title", "shelf_copy"):
        rule = content_contract.rule_for_check(check)
        assert rule is not None, f"{check} is no longer declared in the content contract"
        assert rule.prompt_rule.strip(), (
            f"{check} has no prompt_rule; P3 cannot hand the generator a rule that is not written"
        )


def test_repair_lookup_answers_for_the_checks_the_console_already_maps():
    """`ops/console_api.py` holds the only copy of reason-to-repair today. This replaces it.

    Asserting the answers here means the console can switch to `repair_for_check` without a
    behaviour change, which is what makes the seam real rather than a second parallel map.
    """
    assert content_contract.repair_for_check("title") == content_contract.REPAIR_COPY
    assert content_contract.repair_for_check("shelf_copy") == content_contract.REPAIR_COPY
    assert content_contract.repair_for_check("placeholders") == content_contract.REGENERATE
    # An unknown check must answer, not raise: receipts on disk outlive the rules that wrote them.
    assert content_contract.repair_for_check("a_check_deleted_last_month") == content_contract.MANUAL


def test_blocking_and_shadow_split_on_the_live_config_block():
    """P5's ratchet reads this split. It has to follow config, not a hardcoded list."""
    off = content_contract.blocking_checks({"title_block_on_breach": False})
    on = content_contract.blocking_checks({"title_block_on_breach": True})
    assert "title" not in off and "title" in on

    # Absent key falls back to the rule's own default, matching the gate's safe default rather
    # than silently unbinding the rule.
    assert "title" in content_contract.blocking_checks({})

    cfg = {"title_block_on_breach": True}
    assert not (content_contract.blocking_checks(cfg) & content_contract.shadow_checks(cfg))
    assert (
        content_contract.blocking_checks(cfg) | content_contract.shadow_checks(cfg)
        == {r.check for r in content_contract.RULES}
    )


def test_wired_repairs_are_real_console_actions():
    """A repair the console cannot perform is a button that does nothing.

    `WIRED_REPAIRS` is the contract's claim about what has been built. `ACTIONS` is what has
    been built. When they disagree the operator is the one who finds out.
    """
    from prospector.ops import console_api

    claimed = content_contract.WIRED_REPAIRS - {content_contract.MANUAL}
    missing = claimed - set(console_api.ACTIONS)
    assert not missing, (
        f"content_contract.WIRED_REPAIRS names actions the console does not have: "
        f"{sorted(missing)}"
    )


def test_unwired_repairs_are_named_rather_than_silent():
    """The other half: a repair a rule needs that nothing can perform yet must be visible.

    Dropping it to `manual` inside the console and saying nothing is how a whole class of
    stranded packs becomes 'no tool repairs it today' with no record of what the tool would be.
    """
    from prospector.ops import console_api

    unwired = {r.repair for r in content_contract.RULES} - content_contract.WIRED_REPAIRS
    assert unwired == {content_contract.REGENERATE}, (
        f"the set of repairs no console action performs changed: {sorted(unwired)}. If one was "
        "just wired, move it into WIRED_REPAIRS so the rules that need it light up."
    )
    assert content_contract.REGENERATE not in console_api.ACTIONS, (
        "engine.regenerate_artifacts is now a console action — move it into WIRED_REPAIRS"
    )
    # And the degrade is real: a rule needing it shows as manual rather than as a dead button.
    assert content_contract.repair_for_check("placeholders") == content_contract.REGENERATE
    assert content_contract.console_repair_for_check("placeholders") == content_contract.MANUAL


def test_the_console_routes_a_stranded_row_through_the_contract():
    """The seam itself. The console must answer from the registry, not from a private map."""
    from prospector.ops import console_api

    # A title breach, phrased the way the survey prints it.
    assert console_api._shelf_repair_for(
        "blocked: 1 error(s): title)", ["title"]
    ) == content_contract.REPAIR_COPY

    # A pack that never reached the shelf at all is a lifecycle state, not a rule breach.
    assert console_api._shelf_repair_for(
        "never published", []
    ) == content_contract.PUBLISH_PENDING

    # Both at once: fix the rule first. Publishing it while it breaches only strands it again.
    assert console_api._shelf_repair_for(
        "never published; 1 error(s): shelf_copy)", ["shelf_copy"]
    ) == content_contract.REPAIR_COPY

    # A breach with no wired action degrades to manual instead of offering a dead button.
    assert console_api._shelf_repair_for(
        "blocked: 1 error(s): placeholders)", ["placeholders"]
    ) == content_contract.MANUAL


def test_the_contract_imports_nothing_from_the_engine():
    """It is read by the gate, the generator, the repair path and the console.

    Any engine import here creates a cycle the moment one of those four reads it, and the
    symptom is an ImportError in an unrelated module.
    """
    tree = ast.parse((_REPO / "prospector" / "content_contract.py").read_text())
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("prospector"):
            imported.append(node.module)
        elif isinstance(node, ast.Import):
            imported += [a.name for a in node.names if a.name.startswith("prospector")]
    assert not imported, f"content_contract imports from the engine: {imported}"


def test_the_gate_module_is_the_one_the_bridge_calls():
    """Guards the premise of every test above: that `bridge` really calls THIS `lint_pack`."""
    assert bridge.lint_pack is pack_linter.lint_pack
