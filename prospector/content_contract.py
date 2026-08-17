"""What each buyer-facing field promises, who repairs it, and what switches it on.

THE PROBLEM THIS EXISTS FOR. On 2026-08-17 the engine held 34 PASS packs no one could buy.
Every one was made in the previous three days, and every one was made after the rule that
blocked it. The rules were not the problem and the packs were not old stock. The problem is that
a rule's three facts — which field it grades, what repairs that field, and what switches it on —
live in three different places, connected by nothing but someone remembering.

Today the checks are 18 functions in `pack_linter` and its siblings; the repair is a private
mapping inside `ops/console_api.py` written for one page; the actuator is a `listing.*` key read
at the call site in `bridge.py`. Adding a rule means three edits in three files, and forgetting
the second or the third is invisible until packs strand.

This module is the one place those facts are declared together. It is deliberately data, not
behaviour: it imports nothing from the engine, so the gate, the generator, the repair path and
the console can all read it without a cycle.

WHAT MAKES IT LOAD-BEARING RATHER THAN A FOURTH LIST TO FORGET.
`tests/unit/test_the_content_contract_covers_every_gate_knob.py` reads `lint_pack`'s own
signature and the keywords `bridge.py` actually passes it, and fails if either grows an actuator
this file does not declare, or if a config key declared here is not the one the gate is really
wired to. The gate is the source of truth. This file is checked against it, never trusted over
it.

TWO NAMES, KEPT SEPARATE ON PURPOSE. The `listing.*` config key and the `lint_pack` keyword are
often different — `lint_grammar` actuates `grammar_enabled`, `house_spec_block_register`
actuates `register_block`. Collapsing them into one field is a defect that reads as working:
every lookup still returns something, and the something is wrong for a third of the rules.

See `docs/CONTENT_CONTRACT_PROGRAM.md` for the diagnosis and for what reads this next.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

#: The repair a breach needs. These are the ids `ops/console_api.py` already uses, so the console
#: maps a breach to a button by reading this instead of keeping its own copy.
MANUAL = "manual"
REPAIR_COPY = "shelf.repair_copy"
PUBLISH_PENDING = "shelf.publish_pending"
REGENERATE = "engine.regenerate_artifacts"

REPAIRS = frozenset({MANUAL, REPAIR_COPY, PUBLISH_PENDING, REGENERATE})

#: The repairs a console action can actually perform today. `ACTIONS` in
#: `prospector/ops/console_api.py` is the source of truth for this and the drift guard checks it.
#:
#: This set exists because the two are not the same thing and pretending they are produces a
#: button that does nothing — the defect class where something is built and unreachable. A rule
#: declares the repair it TRULY needs, which is what P4 and P5 have to reason about; the console
#: degrades to `manual` for anything not in here, which is what the operator sees. When
#: `engine.regenerate_artifacts` is wired as an action, it moves into this set and the rules that
#: name it light up on their own.
WIRED_REPAIRS = frozenset({MANUAL, REPAIR_COPY, PUBLISH_PENDING})

#: FIELD NAMES, as the Candidate carries them rather than as the catalogue renders them
#: (`one_liner`, not `oneLine`). The repair happens on the Candidate, upstream of the rename;
#: naming them in catalogue form here is how a repair gets wired to the wrong end.
TITLE = "title"
ONE_LINER = "one_liner"
HEADLINE = "headline"
SUBHEAD = "subhead"
CARD_LINE = "card_line"
ARTIFACTS = "artifacts"
MARKETING = "marketing"

SHELF_FIELDS = (TITLE, ONE_LINER, HEADLINE, SUBHEAD, CARD_LINE)


@dataclass(frozen=True)
class Rule:
    """One lint check, stated with everything a caller needs in order to act on it.

    `check` is the string a `Problem` carries in its `"check"` key — the value the gate writes
    into `<id>.lint.json` and the console reads back. It is the identity here rather than the
    function name because that is the join key the rest of the system already uses: one function
    can emit several checks (`check_register` emits three), and a function can be renamed without
    a single receipt on disk changing.
    """

    check: str
    #: Buyer-facing fields this check grades.
    fields: tuple[str, ...]
    #: The console action that repairs a breach.
    repair: str
    #: The `lint_pack` keyword that switches it on, or None when it blocks unconditionally.
    gate_param: Optional[str] = None
    #: The `listing.*` config key wired to that keyword. Often a different word — see the module
    #: docstring. None when the actuator is code-side only.
    config_key: Optional[str] = None
    #: The code-side default when the config key is absent. Mirrors the call site in `bridge.py`,
    #: where a missing key must never silently unbind a live rule.
    enforced_by_default: bool = True
    #: The rule as the GENERATOR should be told it, in the generator's own second person. Empty
    #: means it has not been lifted into the prompt yet. A rule with text here can be rendered
    #: into the generation prompt from this file, so the bar the generator is given and the bar
    #: the gate applies cannot drift apart.
    prompt_rule: str = ""
    #: Why the operator should care, shown on the console.
    note: str = ""


RULES: tuple[Rule, ...] = (
    # ---- the two that strand the most packs -------------------------------------------------
    Rule(
        check="title",
        fields=(TITLE,),
        repair=REPAIR_COPY,
        gate_param="title_block_on_breach",
        config_key="title_block_on_breach",
        enforced_by_default=True,
        prompt_rule=(
            "The title is at most 60 characters. It names the thing plainly. It is not a "
            "marketing headline and not a claim. If it will not fit, say a shorter true thing "
            "— never truncate."
        ),
        note="Blocked 20 of the 34 stranded packs on 2026-08-17.",
    ),
    Rule(
        check="shelf_copy",
        fields=(ONE_LINER, HEADLINE, SUBHEAD, CARD_LINE),
        repair=REPAIR_COPY,
        gate_param="shelf_copy_block_on_breach",
        config_key="shelf_copy_block_on_breach",
        enforced_by_default=False,
        prompt_rule=(
            "Shelf copy is third person throughout. Never the words you, your, yours, yourself. "
            "Do not open on a bare pronoun — it, we, our, they, this, that, these, those — open "
            "on the thing itself. The reader is someone deciding whether to BUILD this business, "
            "never the business's own customer. Keep the one-liner under 280 characters: over "
            "that the catalogue cuts it, and a cut line trails off on the shelf."
        ),
        note="Blocked 15 of the 34 stranded packs on 2026-08-17.",
    ),
    # ---- the rest of the shelf lines ---------------------------------------------------------
    Rule(
        check="truncation",
        fields=(ONE_LINER, HEADLINE, SUBHEAD),
        repair=REPAIR_COPY,
        prompt_rule=(
            "Every shelf line must read as a complete thought on its own, because the catalogue "
            "may show it alone."
        ),
        note="Catches a field cut mid-word by the catalogue's own length caps.",
    ),
    Rule(
        check="house_dashes",
        fields=SHELF_FIELDS,
        repair=REPAIR_COPY,
        prompt_rule="Do not use dashes to join clauses. Use separate sentences.",
        note="71 dashes reached 68 of 72 live listings before this was graded.",
    ),
    Rule(
        check="title_new_word",
        fields=(TITLE,),
        repair=REPAIR_COPY,
        prompt_rule=(
            "Every term in the title must appear in the pack itself. Do not introduce a word in "
            "the title that the pack never uses."
        ),
        note="Grades the title against the pack, not against the shelf card.",
    ),
    # ---- the pack documents -----------------------------------------------------------------
    Rule(
        check="placeholders",
        fields=(ARTIFACTS,),
        repair=REGENERATE,
        prompt_rule=(
            "Never print a gap where a figure belongs. No '(not specified)', no 'TBD', no "
            "bracketed blank. If the number is not known, say what is not known and why."
        ),
        note="A gap printed where a figure belongs is an unfinished artifact.",
    ),
    Rule(
        check="sections",
        fields=(ARTIFACTS,),
        repair=REGENERATE,
        note="The financial model must carry its required sections.",
    ),
    Rule(
        check="arithmetic",
        fields=(ARTIFACTS,),
        repair=MANUAL,
        prompt_rule="Every computed line must re-check. If you state a total, it must be the sum.",
        note="No tool repairs bad arithmetic — it needs the model to redo the working.",
    ),
    Rule(
        check="currency",
        fields=(ARTIFACTS,),
        repair=MANUAL,
        prompt_rule=(
            "Use one currency, the market's own, in every figure. A price quoted from a source "
            "in another currency stays in that currency and says so."
        ),
        note="One stray symbol in a rendered row blocks the pack.",
    ),
    Rule(
        check="citation_urls",
        fields=(ARTIFACTS,),
        repair=MANUAL,
        gate_param="check_urls_enabled",
        config_key="lint_check_urls",
        enforced_by_default=False,
        note="Blocked 4 of the 34 stranded packs on 2026-08-17. A dead citation is link rot, not "
             "a bad pack, so the archived copy is what resolves it.",
    ),
    Rule(
        check="identifier_leak",
        fields=(ARTIFACTS,),
        repair=REGENERATE,
        prompt_rule="Never print an internal id, candidate hash or engine field name.",
        note="Engine internals must not reach a buyer.",
    ),
    Rule(
        check="engine_leak",
        fields=(ARTIFACTS,),
        repair=REGENERATE,
        gate_param="engine_leak_block",
        config_key="engine_leak_block",
        enforced_by_default=False,
        note="SHADOW. Rate knob: max_engine_leak_per_1k.",
    ),
    Rule(
        check="marketing_audience",
        fields=(MARKETING,),
        repair=REGENERATE,
        note="Marketing assets must name who they address.",
    ),
    # ---- measured but not blocking: the population P5's ratchet promotes ----------------------
    Rule(
        check="repetition",
        fields=(ARTIFACTS,),
        repair=REGENERATE,
        gate_param="repetition_block",
        config_key="lint_repetition_block",
        enforced_by_default=False,
        note="SHADOW. Baseline uncollected. One pack went 33 blocking to 0 on the rewritten "
             "renderers, and one pack is not a corpus.",
    ),
    Rule(
        check="grammar",
        fields=(ARTIFACTS,),
        repair=REGENERATE,
        gate_param="grammar_enabled",
        config_key="lint_grammar",
        enforced_by_default=False,
        note="Live, actuated by a RATE rather than a boolean: max_grammar_defects_per_1k.",
    ),
    Rule(
        check="register",
        fields=(ARTIFACTS,),
        repair=REGENERATE,
        gate_param="register_block",
        config_key="house_spec_block_register",
        enforced_by_default=False,
        note="SHADOW.",
    ),
    Rule(
        check="register_rate",
        fields=(ARTIFACTS,),
        repair=REGENERATE,
        gate_param="register_block",
        config_key="house_spec_block_register",
        enforced_by_default=False,
        note="SHADOW. Rate knob: max_register_per_1k.",
    ),
    Rule(
        check="human_register",
        fields=(ARTIFACTS,),
        repair=REGENERATE,
        gate_param="human_register_block",
        config_key="human_register_block",
        enforced_by_default=False,
        note="SHADOW.",
    ),
    Rule(
        check="house_style",
        fields=(ARTIFACTS,),
        repair=REGENERATE,
        gate_param="house_block_predictions",
        config_key="house_spec_block_predictions",
        enforced_by_default=False,
        note="SHADOW. 43.9% of engine sentences already break house rule R1, which is why this "
             "cannot be switched on until the generator has been taught it.",
    ),
    Rule(
        check="house_rate",
        fields=(ARTIFACTS,),
        repair=REGENERATE,
        gate_param="house_block_quotes",
        config_key="house_spec_block_quotes",
        enforced_by_default=False,
        note="SHADOW. Rate knobs: max_long_sentence_rate, max_clause_load_rate, "
             "max_four_item_list_rate, max_unsourced_figure_rate.",
    ),
    Rule(
        check="hedging",
        fields=(ARTIFACTS,),
        repair=REGENERATE,
        enforced_by_default=False,
        note="SHADOW. Measured only; no actuator of its own.",
    ),
    Rule(
        check="nominalisation",
        fields=(ARTIFACTS,),
        repair=REGENERATE,
        enforced_by_default=False,
        note="SHADOW. Measured only; no actuator of its own.",
    ),
)


#: `lint_pack` keywords that set a BAR rather than switch a rule on. They are not actuators and
#: the drift guard must not demand a rule for them.
BAR_PARAMS = frozenset({
    "title_max_chars",
    "max_grammar_defects_per_1k",
    "max_register_per_1k",
    "max_long_sentence_rate",
    "max_clause_load_rate",
    "max_four_item_list_rate",
    "max_unsourced_figure_rate",
    "max_engine_leak_per_1k",
    "max_urls",
    "url_timeout_s",
})

#: Actuators that exist in the gate and are NOT yet attributed to a declared check.
#: NAMED RATHER THAN OMITTED, deliberately. An undeclared actuator that simply does not appear
#: reads as full coverage; this set is the honest statement that coverage is partial, and the
#: drift guard keeps it from growing silently.
UNMAPPED_ACTUATORS: frozenset[str] = frozenset()


_BY_CHECK = {r.check: r for r in RULES}


def rule_for_check(check: str) -> Optional[Rule]:
    """The declared rule for a check name, or None if it is not declared here.

    None is not an error. A receipt on disk can name a check that has since been deleted, and a
    reader of old receipts must not crash on one.
    """
    return _BY_CHECK.get(check)


def repair_for_check(check: str) -> str:
    """The console action that repairs a breach of `check`, or MANUAL.

    This replaces the private map that lived in `ops/console_api.py`, where the console held the
    only copy of this knowledge — so the engine could not act on it, and a new rule reached the
    console correct and the engine unaware.
    """
    r = _BY_CHECK.get(check)
    return r.repair if r else MANUAL


def console_repair_for_check(check: str) -> str:
    """The repair the CONSOLE can offer today: `repair_for_check`, degraded when nothing is wired.

    Kept separate from `repair_for_check` so the two questions stay distinct. "What fixes this?"
    is a fact about the rule and P4 and P5 need the true answer. "What button can I show?" is a
    fact about what has been built, and answering the second with the first is how an operator
    gets a button that does nothing.
    """
    r = repair_for_check(check)
    return r if r in WIRED_REPAIRS else MANUAL


def rules_for_field(field: str) -> tuple[Rule, ...]:
    """Every declared rule that grades `field`."""
    return tuple(r for r in RULES if field in r.fields)


def prompt_rules_for(*fields: str) -> tuple[str, ...]:
    """The rule text to hand the generator for these fields, deduplicated, in declared order.

    This is what closes the gap between the maker and the grader. The generator gets the same
    rules the gate applies, from the same declaration, instead of a prose paraphrase in a prompt
    file that drifts the first time a bar moves.
    """
    seen: set[str] = set()
    out: list[str] = []
    for f in fields:
        for r in rules_for_field(f):
            if r.prompt_rule and r.prompt_rule not in seen:
                seen.add(r.prompt_rule)
                out.append(r.prompt_rule)
    return tuple(out)


def declared_gate_params() -> frozenset[str]:
    """Every `lint_pack` keyword this file claims to know about."""
    return frozenset(r.gate_param for r in RULES if r.gate_param)


def blocking_checks(listing_cfg: Optional[dict] = None) -> frozenset[str]:
    """The checks that would block a pack right now, given the live `listing` config block.

    A check with no actuator blocks unconditionally. One with an actuator blocks when its config
    key is true, falling back to `enforced_by_default` when the key is absent — the same
    code-side safe default the gate itself uses, so a missing key cannot quietly unbind a rule.
    """
    cfg = listing_cfg or {}
    out = set()
    for r in RULES:
        if r.config_key is None:
            if r.enforced_by_default:
                out.add(r.check)
        elif bool(cfg.get(r.config_key, r.enforced_by_default)):
            out.add(r.check)
    return frozenset(out)


def shadow_checks(listing_cfg: Optional[dict] = None) -> frozenset[str]:
    """The checks that are measured but not blocking — the population P5's ratchet promotes."""
    return frozenset(r.check for r in RULES) - blocking_checks(listing_cfg)
