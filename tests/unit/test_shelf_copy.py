"""The shelf-copy gate, pinned to the corpus that produced it.

On 2026-08-13 the founder read a live card line back — "£180 a claim, filed on the
platform's own cover" — and asked whether it made sense to a website visitor. An audit of
the 50 live packs that afternoon found 48 carrying a copy defect of a class the linter
could not see. The strings below are those live packs' actual before/after text, so this
file is the regression guard on the fix, not a set of invented examples.

Two tiers are tested separately and deliberately:
  * the ERROR tier must be sound — every string that errors is a real defect, because
    `lint_pack` ANDs `ok` into `is_listed` and a false positive unlists a good pack;
  * the WARNING tier is allowed to be noisy and is asserted only where it must fire.
"""
from prospector.pack_linter import check_shelf_copy, lint_pack


def _errors(fields, **kw):
    return [p for p in check_shelf_copy(fields, block=True, **kw) if p["severity"] == "error"]


def _warnings(fields, **kw):
    return [p for p in check_shelf_copy(fields, block=True, **kw) if p["severity"] == "warning"]


def _residue(fields):
    return [p for p in check_shelf_copy(fields, block=True, report_residue=True)
            if "fragment" in p["detail"]]


# ---------------------------------------------------------------------------
# The actuator
# ---------------------------------------------------------------------------

def test_block_off_is_advisory_only():
    """Default off: findings still accrue, but nothing unlists. This is the setting the
    gate ships in until the live catalogue is clean against it."""
    bad = {"cardLine": "£149 per parent, from FOI tribunal outcome data"}
    off = check_shelf_copy(bad, block=False)
    assert off, "the finding must still be reported with the actuator off"
    assert all(p["severity"] == "warning" for p in off)
    assert any(p["severity"] == "error" for p in check_shelf_copy(bad, block=True))


def test_lint_pack_wires_the_actuator_through():
    """The wiring, end to end. `ok` is not asserted here because an empty fixture fails
    `check_sections` on its own; what is asserted is that the SHELF finding changes
    severity with the switch, which is what `ok` is computed from."""
    house = {"title": "IEP request letter service for parents of disabled kids"}
    def shelf(**kw):
        report = lint_pack(artifacts={}, listing_copy="", listing_texts={},
                           house_fields=house, market="us", **kw)
        return [p for p in report["problems"] if p["check"] == "shelf_copy"]
    assert [p["severity"] for p in shelf()] == ["warning"]
    assert [p["severity"] for p in shelf(shelf_copy_block_on_breach=True)] == ["error"]


# ---------------------------------------------------------------------------
# ERROR tier — soundness matters more than coverage
# ---------------------------------------------------------------------------

def test_unexplained_initialism_errors_on_the_live_offenders():
    """Every one of these was live on 2026-08-13 and is a word the trade says to itself."""
    for text in (
        "IEP request letter service for parents of disabled kids",
        "ADA fix kits for California small shop owners",
        "Prefilled COSHH assessments for mobile nail technicians",
        "CIS gross payment appeals for building subcontractors",
        "£149 per parent, from FOI tribunal outcome data",
        "A tool that pulls a fleet's DVSA record",
        "Carers ask the local ICB and get bounced",
        "solicitors and IFAs pay for a bulk licence",
    ):
        assert _errors({"cardLine": text}), f"should have errored: {text!r}"


def test_initialism_hiding_inside_a_mixed_case_token_is_caught():
    """`CalSTRS` reads as a proper noun; a token-equality test walks straight past it."""
    problems = _errors({"oneLine": "A per-call API that shows a California teacher their CalSTRS position"})
    assert problems and "STRS" in problems[0]["detail"]


def test_initialisms_a_stranger_already_knows_are_never_flagged():
    """The list is a claim that the reader knows the term. False positives here unlist
    good packs, so this is the check that keeps the error tier usable."""
    for text in (
        "Unpaid-hours audits for NHS doctors and nurses",
        "NHS care fee reclaim service for bereaved carers",
        "A tool that pulls a fleet's MOT and tacho data",
        "VAT and PAYE catch-up service for late filers",
        "UV lamp test cards for self-employed gel nail techs",
        "A per-call API for US school districts",
    ):
        assert not _errors({"title": text}), f"false positive on: {text!r}"


def test_second_person_errors_in_either_direction():
    """18 of 19 live instances were aimed at the service's end customer, who never sees this
    shop. The 19th addressed the buyer and was still better in the third person, which is
    why the rule is stated as register — that is the half a machine can decide."""
    for text in (
        "Automatically calculates your holiday pay entitlement from irregular earnings",
        "Get the pay your rota says you are owed",
        "Free to check, with a paid option to save a record of your checks",
    ):
        assert _errors({"oneLine": text}), f"should have errored: {text!r}"
    # The same fact, told to the person deciding whether to run this.
    assert not _errors({"oneLine": "Works out what a zero hours worker is owed in holiday "
                                   "pay from irregular earnings"})
    # Aimed at the buyer, and still a defect: the shelf speaks in the third person.
    assert _errors({"headline": "A worked plan for setting yourself up to certify wiring"})
    assert not _errors({"headline": "A worked plan for setting up to certify wiring"})


def test_internal_vocabulary_and_taxonomy_tokens_error():
    problems = _errors({"cardLine": "A cross_sector risk_financing wedge for the lens"})
    assert problems
    detail = problems[0]["detail"]
    assert "wedge" in detail and "lens" in detail
    assert "cross_sector" in detail and "risk_financing" in detail


def test_pack_is_the_readers_word_and_is_never_flagged():
    """The storefront sells a thing it calls a pack, so it is not our filing system."""
    assert not _errors({"oneLine": "A done-for-it evidence pack for refused Blue Badge appeals"})


def test_a_shelf_line_that_trails_off_errors_even_when_the_cut_was_clean():
    """`check_truncation` needs a source to prove a mid-word cut. On the shelf the line is
    all the reader gets, so an ellipsis is a defect either way — 29 of 50 live one-liners
    ended this way."""
    assert _errors({"oneLine": "A fixed-fee service for parents of closed nurseries…"})
    assert _errors({"oneLine": "A fixed-fee service for parents of closed nurseries..."})


def test_the_same_line_twice_errors():
    """13 of 48 live packs repeated their title as their headline, spending the pack
    page's most valuable line saying nothing new. Case and punctuation do not rescue it."""
    problems = _errors({
        "title": "Unpaid-hours audits for NHS doctors and nurses",
        "headline": "unpaid hours audits for nhs doctors and nurses.",
    })
    # Attributed to the REPEAT, never to the title: the title is the canonical line.
    assert problems and problems[0]["where"] == "headline"
    assert "title" in problems[0]["detail"]
    assert not _errors({
        "title": "Unpaid-hours audits for NHS doctors and nurses",
        "headline": "Doctors lose an estimated £1,500 a year to hours they never billed",
    })


# ---------------------------------------------------------------------------
# WARNING tier — the residue, named for the reviewer rather than ruled on
# ---------------------------------------------------------------------------

def test_the_telegraphic_card_lines_the_founder_rejected_are_at_least_named():
    """These four were true, sourced, dash-free and inside 60 characters, and all four had
    to be rewritten by hand. No regex rules on them: two carry a participle and one carries
    a real figure. They warn, so a human sees them; they never block."""
    for text in (
        "£180 a day, underwritten solo, fixed payout",
        "Rota plus timesheet against contract terms",
        "£180 a claim, filed on the platform's own cover",
        "Per lease call, built on discharge, tide and FSA history",
    ):
        assert _residue({"cardLine": text}), f"should have warned: {text!r}"


def test_the_residue_check_is_off_unless_a_reviewer_asks_for_it():
    """`lint_pack`'s receipt is asserted empty for a clean pack, so a check that cannot be
    complete does not get to spend that contract."""
    fragment = {"cardLine": "Rota plus timesheet against contract terms"}
    assert not check_shelf_copy(fragment, block=True)
    assert _residue(fragment)


def test_the_bare_infinitive_is_not_a_verb_on_a_shelf():
    """`cover`, `claim`, `check` and `file` are nouns here. Counting them scored a verb for
    the founder's own rejected line and made the check vacuous."""
    assert _residue({"cardLine": "£180 a claim, filed on the platform's own cover"})
    assert not _residue({"cardLine": "Reads the rota and timesheet and finds the hours owed"})


def test_the_fragment_check_never_grades_a_title():
    """`prompts/retitle.md` requires a noun phrase in the title, so a title with no finite
    verb is the declared shape. Grading it fired on 36 of 50 live packs."""
    noun_phrase = "Scope-creep pricing desk for UK freelance creatives"
    assert not _residue({"title": noun_phrase})
    assert _residue({"cardLine": noun_phrase})


def test_trade_shorthand_warns_but_never_blocks():
    """Legitimate once the plain description comes first, and whether it does is not
    decidable here — so this stays advisory even with the actuator on."""
    problems = check_shelf_copy(
        {"oneLine": "A parametric micro-bond that pays a fixed daily sum"}, block=True)
    shorthand = [p for p in problems if "trade shorthand" in p["detail"]]
    assert shorthand and all(p["severity"] == "warning" for p in shorthand)


# ---------------------------------------------------------------------------
# Corpus scope
# ---------------------------------------------------------------------------

def test_only_named_shelf_fields_are_graded():
    """Body prose is `check_grammar`'s corpus. Selecting by shape instead of by name is how
    `check_identifier_leak` once graded a .csv as writing."""
    body = "You will need your COSHH assessments and your IEP paperwork before you start."
    assert not check_shelf_copy({"financial_model": body}, block=True)
    assert _errors({"oneLine": body})


def test_both_spellings_of_the_card_line_are_graded():
    """The catalogue row says `cardLine`; the pack model says `card_line`. A field that
    reaches the gate under the other spelling would be silently ungraded."""
    bad = "£149 per parent, from FOI tribunal outcome data"
    assert _errors({"cardLine": bad})
    assert _errors({"card_line": bad})
