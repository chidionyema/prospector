"""Regression fence for the 2026-08-08 copy defects.

Two defects reached production and neither was a typo; both were structural:

  1. `title` was the one buyer-facing field whose value did not pass through the
     normaliser, AND it was never handed to the linter either — so 71 em/en-dashes reached
     the title of 68 of 72 live listings with nothing on the publish path able to see it.
  2. The engine's own schema identifiers (`monthly_price`, `who_pays`, `payer_solvency`)
     appeared 589 times in prose buyers pay for, across 51 of 79 pass-dossiers.

These tests pin the FIX SHAPE, not just the symptom: the choke point must normalise a field
nobody remembered to list, and must leave the money-rail identifiers alone.
"""
from __future__ import annotations

from prospector.copy_lint import (
    buyer_readable,
    check_grammar,
    check_house_dashes,
    check_identifier_leak,
    internal_identifiers,
    is_prose_artifact,
)
from prospector.plain_text import nodash

# ---------------------------------------------------------------------------
# nodash — the U+2011 gap
# ---------------------------------------------------------------------------

def test_nodash_strips_the_three_house_dashes():
    assert "—" not in nodash("PanelPack — the fixed-fee pack")
    assert "–" not in nodash("HolidayPay Tracker – the app")
    assert "‑" not in nodash("the small haulier's O‑licence pipeline")


def test_nodash_keeps_compound_words_intact_across_a_nonbreaking_hyphen():
    """U+2011 joins a WORD, so it must become a hyphen — a comma would split it.

    "O‑licence" -> "O, licence" would be a worse defect than the dash it fixes: it invents
    a list where the source had a single compound noun.
    """
    assert nodash("an O‑licence audit") == "an O-licence audit"
    assert nodash("zero‑hour contracts") == "zero-hour contracts"


def test_nodash_still_preserves_numeric_ranges():
    """Guards the existing 2026-08-06 behaviour — a range must not become a comma."""
    assert nodash("Mothers 25—45") == "Mothers 25-45"
    assert nodash("for 2025–2026") == "for 2025-2026"


# ---------------------------------------------------------------------------
# check_house_dashes
# ---------------------------------------------------------------------------

def test_house_dashes_flags_the_exact_live_defect():
    """The real string from a live listing title."""
    problems = check_house_dashes(
        {"title": "PanelPack — the fixed-fee pack that gets your relative's care restored"})
    assert len(problems) == 1
    assert problems[0]["severity"] == "error"
    assert problems[0]["check"] == "house_dashes"
    assert problems[0]["where"] == "title"


def test_house_dashes_clean_after_normalisation():
    title = nodash("PanelPack — the fixed-fee pack")
    assert check_house_dashes({"title": title}) == []


def test_house_dashes_ignores_empty_and_non_string():
    assert check_house_dashes({"title": "", "subhead": None, "n": 3}) == []


# ---------------------------------------------------------------------------
# check_identifier_leak
# ---------------------------------------------------------------------------

def test_identifier_leak_flags_schema_names_in_buyer_prose():
    """Verbatim from a live financial_model artifact."""
    text = ("The confidence scores on the supporting checks are low "
            "(value_durability 0.438, distribution 0.430), and monthly_price of £12 "
            "is an assumption.")
    problems = check_identifier_leak({"financial_model": text})
    assert len(problems) == 1
    assert problems[0]["severity"] == "error"
    assert "value_durability" in problems[0]["detail"]


def test_identifier_leak_ignores_fenced_code():
    """A build spec may legitimately tell the buyer to create the column.

    Documentation is not a leak; only narrative prose is.
    """
    text = "Create the table:\n\n```sql\nALTER TABLE p ADD monthly_price INT;\n```\n"
    assert check_identifier_leak({"build_spec": text}) == []


def test_identifier_leak_ignores_inline_code_and_urls():
    text = ("Set `monthly_price` in config, per "
            "https://example.com/docs/payer_solvency_guide for details.")
    assert check_identifier_leak({"gtm_plan": text}) == []


def test_identifier_leak_skips_json_artifacts():
    """snake_case keys are CORRECT in a JSON artifact — it is data, not prose."""
    text = '{"max_score": 5, "weighted_contribution": 0.8}'
    assert check_identifier_leak({"scorecard.json": text}) == []
    assert check_identifier_leak({"scorecard": text}) == []


def test_identifier_denylist_is_derived_from_the_dataclasses():
    """The denylist must self-maintain.

    A hand-listed set is the same defect shape as per-field normalisation: correct only
    while someone remembers. `one_liner` and `who_pays` are Candidate fields and must be
    present without anyone having typed them into the extras set.
    """
    idents = internal_identifiers()
    assert "one_liner" in idents
    assert "who_pays" in idents
    assert "why_now" in idents


# ---------------------------------------------------------------------------
# The choke point — including the money-rail exclusion
# ---------------------------------------------------------------------------

def test_choke_point_normalises_a_field_nobody_listed():
    """THE point of the fix.

    A field added to the payload tomorrow, that no one thought to normalise, must still be
    covered. If this test fails, the choke point has degenerated back into a call site.
    """
    from prospector.bridge import _normalise_catalog_payload
    out = _normalise_catalog_payload({
        "title": "PanelPack — the fixed-fee pack",
        "someFieldInventedLater": "Copy with — a dash in it",
        "nested": {"deep": "Also — dashed"},
        "listed": ["An — item"],
    })
    assert "—" not in out["title"]
    assert "—" not in out["someFieldInventedLater"]
    assert "—" not in out["nested"]["deep"]
    assert "—" not in out["listed"][0]


def test_choke_point_never_touches_money_rail_identifiers():
    """`providerPriceId` and `contentHash` are read by the fulfilment fence.

    A normaliser that altered one would charge a buyer and then refuse delivery. They must
    come out byte-identical.
    """
    from prospector.bridge import _normalise_catalog_payload
    payload = {
        "id": "0f2109fb198341a4",
        "providerPriceId": "price_1Abc—Def",   # pathological on purpose
        "providerProductId": "prod_XYZ–123",
        "contentHash": "9f34a5—deadbeef",
        "contentKey": "packs/0f21—09fb.zip",
        "pricePence": 4900,
        "isListed": True,
    }
    out = _normalise_catalog_payload(dict(payload))
    for key in ("id", "providerPriceId", "providerProductId", "contentHash",
                "contentKey", "pricePence", "isListed"):
        assert out[key] == payload[key], f"{key} was altered by the copy normaliser"


# ---------------------------------------------------------------------------
# Grammar — fail-open contract
# ---------------------------------------------------------------------------

def test_grammar_fails_open_when_the_checker_is_missing(monkeypatch):
    """A missing checker must never unlist a good pack."""
    monkeypatch.setattr("prospector.copy_lint.harper_path", lambda: None)
    problems = check_grammar({"a": "Some prose. " * 100}, max_per_1k=1.0)
    assert all(p["severity"] == "warning" for p in problems)
    assert any("unavailable" in p["detail"] for p in problems)


def test_grammar_threshold_of_zero_never_blocks(monkeypatch):
    """0 = record only. The actuator is off until a number is chosen from real receipts."""
    monkeypatch.setattr("prospector.copy_lint.grammar_findings",
                        lambda *a, **k: {"Agreement": 50})
    problems = check_grammar({"a": "word " * 500}, max_per_1k=0.0)
    assert all(p["severity"] == "warning" for p in problems)


def test_grammar_blocks_above_threshold(monkeypatch):
    monkeypatch.setattr("prospector.copy_lint.grammar_findings",
                        lambda *a, **k: {"Agreement": 50})
    problems = check_grammar({"a": "word " * 500}, max_per_1k=3.0)
    assert any(p["severity"] == "error" for p in problems)


# ---------------------------------------------------------------------------
# Data artifacts are not prose — the 2026-08-08 delisting
# ---------------------------------------------------------------------------
# Live pack 2abc23c3c0d05bab was published UNLISTED (GET /catalog/... -> 404, shelf 52 -> 49)
# by two "defects" that were the same category error twice: three CSVs graded as writing.
# Measured on that pack's own artifacts: 28 of 32 counted grammar defects came from the CSVs
# and ZERO from prose, and every leaked identifier was a generated column header.

_SCORECARD_CSV = (
    "axis,raw_score,max_score,weight,weighted_contribution\n"
    "pain_acuity,4,5,0.25,1.0\n"
    "money_provability,3,5,0.2,0.6\n"
    "build_feasibility,4,5,0.15,0.6\n"
)


def test_a_generated_csv_header_is_not_an_identifier_leak():
    """pack_data.py:253 writes these column names from the schema; no rewrite can change them."""
    assert check_identifier_leak({"scorecard.csv": _SCORECARD_CSV}) == []


def test_the_same_identifiers_in_real_prose_are_still_caught():
    """The exemption is by artifact TYPE, not by token — the gate must not go vacuous."""
    problems = check_identifier_leak(
        {"build_spec": "Scoring uses the pain_acuity and money_provability fields."})
    assert [p["severity"] for p in problems] == ["error"]
    assert "pain_acuity" in problems[0]["detail"]


def test_data_artifacts_are_excluded_from_the_graded_prose_corpus():
    """Both copy checks share ONE definition of prose, so they cannot disagree about it."""
    assert not is_prose_artifact("financial.csv", "section,key,label,value\n")
    assert not is_prose_artifact("scorecard_radar.svg", "<svg viewBox='0 0 10 10'></svg>")
    assert not is_prose_artifact("scorecard.json", '{"axis": 1}')
    assert is_prose_artifact("build_spec", "The service files the appeal on the user's behalf.")


def test_pack_linter_does_not_grade_a_csv_as_prose(monkeypatch):
    """End to end: a pack whose only 'defects' live in generated data files still lists.

    Harper really does fire UnclosedQuotes on `section,key,label,value` and CommaFixes on the
    commas that ARE the format, so the stub below is not a strawman — it is what the checker
    returns when handed a CSV.
    """
    seen: dict = {}

    def fake_findings(texts, **kwargs):
        seen.update(texts)
        return {"UnclosedQuotes": 9, "CommaFixes": 19} if texts else {}

    monkeypatch.setattr("prospector.copy_lint.grammar_findings", fake_findings)

    from prospector.pack_linter import lint_pack

    report = lint_pack(
        artifacts={"scorecard.csv": _SCORECARD_CSV,
                   "financial.csv": "section,key,label,value\n" * 40},
        listing_copy="A tool that files the appeal for you.",
        listing_texts={},
        market="uk",
        grammar_enabled=True,
        max_grammar_defects_per_1k=6.0,
    )
    assert "scorecard.csv" not in seen, "a CSV reached the grammar checker"
    assert "financial.csv" not in seen, "a CSV reached the grammar checker"
    blocking = [p for p in report["problems"]
                if p["severity"] == "error" and p["check"] in ("grammar", "identifier_leak")]
    assert blocking == [], blocking
    assert report["ok"] is True


# ---------------------------------------------------------------------------
# buyer_readable — the second half of the identifier fix
# ---------------------------------------------------------------------------
# Projecting the PROMPT (artifacts._candidate_prompt_view) was not enough: financial_model
# asks the model for a JSON object literally keyed `estimated_cac_gbp` and then asks it to
# critique that object, so the model names the key it just filled. Regenerating re-rolls the
# same dice; normalising at the render/publish choke point cannot fail.

# Verbatim from live pack 2abc23c3c0d05bab's financial_model weakness bullets.
_LEAKED_BULLET = (
    "estimated_cac_gbp (£35) has no supporting source, and cost_of_goods_pct (8%) "
    "assumes a solo operator, so monthly_price and payback_months are assumption."
)


def test_buyer_readable_clears_the_leak_that_delisted_a_live_pack():
    out = buyer_readable(_LEAKED_BULLET)
    assert check_identifier_leak({"financial_model": out}) == []
    assert "customer acquisition cost (£35)" in out
    assert "cost of goods (8%)" in out
    assert "monthly price" in out and "payback period" in out


def test_buyer_readable_leaves_documentation_alone():
    """Same three spans `_strip_code` exempts: a build spec may TELL the buyer the column name."""
    doc = "Create a `monthly_price` column; schema at https://x.test/monthly_price"
    assert buyer_readable(doc) == doc
    fenced = "Use this:\n```\nmonthly_price,payback_months\n```\ndone."
    assert buyer_readable(fenced) == fenced


def test_buyer_readable_only_touches_the_engines_own_identifiers():
    """A snake_case word that is not ours is the buyer's, and must survive verbatim."""
    assert buyer_readable("Set your own_field and read_only flag.") == \
        "Set your own_field and read_only flag."


def test_buyer_readable_and_the_gate_share_one_definition():
    """Every identifier the gate blocks on must be one the normaliser resolves.

    If these two sets ever drift, the gate blocks something the choke point cannot fix and
    the pack is unlistable with no path forward — which is precisely what happened.
    """
    for ident in sorted(internal_identifiers()):
        cleaned = buyer_readable(f"The {ident} matters here.")
        assert check_identifier_leak({"prose": cleaned}) == [], ident
