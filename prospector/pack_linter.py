"""Deterministic pack linter — the Q2 quality floor on the publish path.

`validate_pack` asks "is the deliverable PRESENT?"; `audit_bundle` asks "did it reach the
zip?". This module asks the question neither can: "is what's present WRONG in a way a buyer
would see?" — a $ amount in a UK pack, a computed line whose arithmetic doesn't hold,
storefront copy cut mid-word, a citation that 404s. Every check is pure Python over the
already-built texts (URL resolution is the one networked check, and it is bounded and
cached); the verdict is machine-readable so each refusal leaves a receipt next to the
dossier instead of only a log line.

Severity contract: an "error" blocks listing (the pack registers UNLISTED for repair);
a "warning" is recorded but does not block — used where a defect cannot be told apart from
the world being unhelpful (a citation host timing out is not proof the citation is dead;
a definitive 404/410 is).
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

import requests

from .copy_lint import (
    check_grammar,
    check_house_dashes,
    check_identifier_leak,
    extract_urls,
    is_prose_artifact,
)
from .house_style import check_house_style, house_style_metrics
from .marketing_assets import BUSINESS_VOICE_TYPES, PACK_VOICE_RE, has_subject_line
from .register_lint import check_register, register_metrics

Problem = Dict[str, str]  # {"check", "severity", "where", "detail"}

# The one symbol table in the engine. `artifacts._render_financial_model` renders money
# with it and this linter checks money against it, so the writer and the checker cannot
# drift into disagreeing about what a pack's currency looks like — a drift here would
# either unlist every pack in a market or wave through the defect this check exists for.
SYMBOL_BY_CURRENCY = {"GBP": "£", "USD": "$", "EUR": "€"}

# Storefront currency by market prefix ("uk" and "uk-*" → £). Mirrors the `currency_hint`
# each market declares in config.yaml (tests pin the two against each other). An unmapped
# market lints currency-free rather than guessing — unknown must never block on symbols.
CURRENCY_BY_MARKET = {"uk": SYMBOL_BY_CURRENCY["GBP"], "us": SYMBOL_BY_CURRENCY["USD"]}
_ALL_SYMBOLS = frozenset(SYMBOL_BY_CURRENCY.values())


def symbol_for_currency(code: Optional[str], default: str = "£") -> str:
    """ISO code (a market's config-declared `currency_hint`) → symbol.

    Falls back to `default` for an unmapped or missing code: rendering a pack in £ is a
    recoverable cosmetic wrong, while raising here would fail the whole artifact build.
    The lint is the place that refuses to SELL such a pack.
    """
    return SYMBOL_BY_CURRENCY.get((code or "").strip().upper(), default)


def expected_currency(market: str) -> Optional[str]:
    m = (market or "").strip().lower()
    for prefix, sym in CURRENCY_BY_MARKET.items():
        if m == prefix or m.startswith(prefix + "-"):
            return sym
    return None


def _err(check: str, where: str, detail: str) -> Problem:
    return {"check": check, "severity": "error", "where": where, "detail": detail}


def _warn(check: str, where: str, detail: str) -> Problem:
    return {"check": check, "severity": "warning", "where": where, "detail": detail}


# ---------------------------------------------------------------------------
# Repetition across the assembled pack (the "why wasn't this caught at root" check)
# ---------------------------------------------------------------------------
#
# WHY THIS DID NOT EXIST UNTIL 2026-08-15
# ---------------------------------------
# The founder read a rebuilt pack and said "repetitions occur", then asked why nothing had
# caught it. The answer is structural rather than an oversight in any one rule: EVERY check in
# this module before this one grades a single document or a single field. `check_currency` is
# the only one that ever sees two texts at once, and it compares currency symbols.
#
# So nothing in this repo had ever read the pack as ONE DOCUMENT. Each renderer was verified
# on its own — word counts, unit tests, its own output — and each was correct on its own. The
# defect only exists BETWEEN them: `pack_reference` and `pack_bear_case` both walked the same
# `unverifiable` rows; `dossier.render_markdown` reprinted every passage its own per-check
# lists had already printed; `pack_bear_case` lifted two whole blocks out of the financial
# model. Measured on pack e698149e137fc164: 43 sentences appearing in two or more sections,
# 26 repeated inside a single section, 34 near-duplicate pairs.
#
# A per-document linter cannot see any of that, however many rules it has. This one takes the
# assembled reading order and is the only check here that does.
#
# WHAT IS DELIBERATELY NOT GRADED
# --------------------------------
# Block quotes are skipped. This module's own standing rule is that quoted third-party
# passages are never linted — two checks citing the same page SHOULD quote the same sentence,
# and "correcting" that would falsify the citation on a source-or-die storefront.
#
# Short sentences are skipped. Section furniture recurs by design ("Read this one before you
# build.") and a floor on length is what separates a repeated FACT from a repeated signpost.
# Sections whose JOB is to restate the pack. Membership is an argument, not a category, and
# the list is expected to stay at one entry: "Copy you can paste" hands the buyer a headline,
# a one-line description and a proof point to lift into a landing page, and every one of those
# is by definition a line printed elsewhere in the pack. See `check_repetition` for what
# membership actually buys (a downgrade to warning, and only when exactly one other section is
# involved) and why it is keyed on the buyer-visible title.
_REPETITION_RESTATES_ON_PURPOSE = frozenset({"Copy you can paste"})

_REPETITION_MIN_WORDS = 9
_REPETITION_NEAR_RATIO = 88.0     # rapidfuzz ratio, 0-100
_REPETITION_MD = re.compile(r"[*_`#\[\]()]|https?://\S+")
_REPETITION_LIST = re.compile(r"^\s*(?:\d+[.)]|[-•*])\s*")


def _repetition_sentences(markdown: str) -> List[str]:
    """Engine-authored sentences of a section, normalised for comparison."""
    out: List[str] = []
    fenced = False
    for line in str(markdown or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            fenced = not fenced
            continue
        # Headings carry no claim; block quotes are somebody else's words (see above).
        if fenced or not stripped or stripped.startswith(("#", ">", "|")):
            continue
        body = _REPETITION_MD.sub(" ", _REPETITION_LIST.sub("", stripped))
        for sentence in re.split(r"(?<=[.!?])\s+", body):
            words = sentence.split()
            if len(words) >= _REPETITION_MIN_WORDS:
                out.append(" ".join(words))
    return out


def _repetition_key(sentence: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", sentence.lower())


def readability_grades(sections: Optional[Mapping[str, str]]) -> Dict[str, float]:
    """US reading-grade per section, recorded and never actuated.

    Measured 2026-08-15 on pack e698149e137fc164, the fourteen sections spread from grade 5.9
    to grade 17.3, and the spread is not noise: the three sections rendered deterministically
    from the dossier came in at 5.9-7.3, and the four model-written documents at 12.6-13.8.
    The worst was "Copy you can paste" at 17.3 — the one section whose entire job is to hand
    the buyer sentences to put on a landing page.

    That is the finding, and it is the reason this returns numbers rather than problems. A
    grade ceiling would block a pack for quoting a statute, and the honest reading of the
    spread is that it grades WHO WROTE a section, not whether the writing is any good. It
    accrues in `<id>.lint.json` until there is enough of it to say something a threshold
    could act on.

    Returns {} when textstat is absent or when nothing is long enough to score — a readability
    number over two sentences is arithmetic, not a measurement.
    """
    if not sections:
        return {}
    try:
        import textstat  # declared in requirements.txt; pure Python, no build
    except ImportError:
        # The optional metric is absent. NARROWED from `except Exception` on merging
        # origin/main 2026-08-15, which brought the tier-1 swallow ratchet
        # (`tools/audit_swallow_sites.py`) that flagged this line: `{}` here is the SAME value
        # the success path returns for a pack with nothing long enough to score, so a broad
        # handler made "textstat is not installed" and "this pack has no scoreable section"
        # the same fact to every caller — and the whole point of this function is that the
        # numbers accrue in `<id>.lint.json` until there are enough of them to say something.
        # Accruing nothing, silently, because of an unrelated exception is how that never
        # happens. ImportError is the one condition this handler is actually for.
        return {}
    out: Dict[str, float] = {}
    for title, body in sections.items():
        plain = " ".join(_REPETITION_MD.sub(" ", str(body or "")).split())
        if len(plain.split()) < 60:
            continue
        try:
            out[title] = round(float(textstat.flesch_kincaid_grade(plain)), 1)
        except Exception:              # noqa: BLE001 — one unscoreable section, not the pack
            # Deliberately still broad, and NOT the same defect as the import above: this
            # skips ONE section of fourteen and the other thirteen still record their grade,
            # so a caller can see that a number is missing. `textstat` is a third party
            # scoring arbitrary prose and its failure modes are not enumerable from here;
            # widening a metric's blast radius to the whole publish would be the worse trade.
            continue
    return out


def check_repetition(sections: Optional[Mapping[str, str]],
                     *, block: bool = True) -> List[Problem]:
    """Grade the assembled pack for text the buyer reads twice.

    `sections` is the reading order the buyer actually gets — section TITLE -> markdown body,
    exactly what `bridge` hands the HTML renderer. Keyed by title rather than by filename
    because the title is what the report has to name for the defect to be actionable.

    Three findings, and only the first blocks:

      * the same sentence in TWO OR MORE sections. There is no case where this is right: two
        renderers each decided a fact was worth stating and neither knew about the other.
      * the same sentence twice INSIDE one section — a warning, because a genuinely long
        section can restate a premise on purpose.
      * a near-duplicate across sections (rapidfuzz >= 88) — a warning, because a rephrase is
        a judgement about meaning and this check is not the place to make it. It is the
        paraphrase problem `pack_reference`'s docstring measured at 3.5% of the corpus, and
        blocking on a similarity score would unlist packs over a style the model chose.

    `block=False` grades without the actuator, which is how `check_grammar` and
    `check_shelf_copy` earn their thresholds in this module: the report still carries the
    count, so a baseline accrues on live packs before anything refuses to sell one.
    """
    if not sections:
        return []
    from rapidfuzz import fuzz  # declared in requirements.txt; a wheel, no build step

    problems: List[Problem] = []
    by_key: Dict[str, List[Tuple[str, str]]] = {}
    for title, body in sections.items():
        counts: Dict[str, int] = {}
        for sentence in _repetition_sentences(body):
            key = _repetition_key(sentence)
            counts[key] = counts.get(key, 0) + 1
            by_key.setdefault(key, []).append((str(title), sentence))
        for key, n in counts.items():
            if n > 1:
                example = next(s for t, s in by_key[key] if t == str(title))
                problems.append(_warn(
                    "repetition", str(title),
                    f"one sentence printed {n} times in this section: {example[:160]!r}"))

    make = _err if block else _warn
    for key, hits in by_key.items():
        titles = sorted({t for t, _ in hits})
        if len(titles) > 1:
            # THE ONE EXEMPTION, AND WHY IT IS NARROW. A section that exists to hand the buyer
            # lines to paste elsewhere is restating on purpose; blocking it would mean the only
            # way to ship is to make the paste-ready copy differ from the pack it came out of,
            # which is a worse pack and a false claim. So restatement BY that section is
            # downgraded, not waived — the finding is still reported, so a renderer that starts
            # copying whole sections into it is still visible in the report.
            #
            # It is keyed on the section title rather than on a filename or a flag because the
            # title is what the exemption is an argument about: "Copy you can paste" earns it,
            # and a future section does not inherit it by being added to the reading order.
            # Two sections neither of which is exempt still block, even if one is adjacent to
            # the exempt one in the pack.
            exempt = _REPETITION_RESTATES_ON_PURPOSE.intersection(titles)
            downgraded = bool(exempt) and (len(titles) - len(exempt)) < 2
            report = _warn if downgraded else make
            note = (f" (allowed: {' + '.join(sorted(exempt))} exists to restate)"
                    if downgraded else "")
            problems.append(report(
                "repetition", " + ".join(titles),
                f"the same sentence is printed in {len(titles)} sections{note}: "
                f"{hits[0][1][:160]!r}"))

    # Near-duplicates. Compared once per unordered pair, over the SAME population the exact
    # rule uses. There was a second floor here (`len(k) >= 60`) justified as keeping two short
    # sentences of similar shape from scoring high, but `_repetition_sentences` has already
    # made that judgement at `_REPETITION_MIN_WORDS` = 9, and nine words is about 45-50
    # characters — so the floor was silently exempting the shortest third of real sentences
    # from the only check that catches a REPHRASE. Two gates answering one question is how a
    # corpus ends up smaller than the rule that defines it.
    keys = list(by_key)
    pairs = 0
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            # THE PREFILTER IS DERIVED FROM THE THRESHOLD, NOT A ROUND NUMBER (2026-08-15).
            # It was `abs(len(a) - len(b)) > 40`, and 40 is not conservative at ratio 88.
            # rapidfuzz's ratio is 2*matches/(la+lb), so reaching T needs the longer string
            # within `m*(200-T)/T` of the shorter — 1.27x at T=88, i.e. 43 characters apart at
            # m=160, not 40. A 160/205-character pair scoring 91 was skipped before it was
            # ever compared, which is a false CLEAN and the expensive direction to be wrong in.
            la, lb = len(a), len(b)
            if abs(la - lb) * _REPETITION_NEAR_RATIO > \
                    min(la, lb) * (200.0 - 2 * _REPETITION_NEAR_RATIO):
                continue
            titles_a = {t for t, _ in by_key[a]}
            titles_b = {t for t, _ in by_key[b]}
            if titles_a == titles_b and len(titles_a) == 1:
                continue  # one section: the within-section rule above already has it
            if fuzz.ratio(a, b) < _REPETITION_NEAR_RATIO:
                continue
            pairs += 1
            if pairs <= 20:   # the report names the worst; the count carries the rest
                problems.append(_warn(
                    "repetition", " + ".join(sorted(titles_a | titles_b)),
                    "near-duplicate sentences: "
                    f"{by_key[a][0][1][:110]!r} / {by_key[b][0][1][:110]!r}"))
    if pairs > 20:
        problems.append(_warn("repetition", "pack",
                              f"{pairs} near-duplicate sentence pairs across sections; "
                              "the first 20 are listed above"))
    return problems


# ---------------------------------------------------------------------------
# Currency consistency (the £/$ defect)
# ---------------------------------------------------------------------------

# The financial model is MOSTLY Python-rendered — but not all of it.
# `artifacts._render_financial_model` appends two model-authored lists at the end, and its
# own source marks them: those lists "are the only FREE TEXT in this artifact — everything
# above is Python formatting a number."
# The renderer's own heading for each model-authored list, plus the pre-2026-08-14 names
# still on every pack already on disk. Both spellings have to be recognised: this boundary
# decides which half of the document the currency check is allowed to rewrite, and a backfill
# run against an old pack (tools/backfill_pack_currency.py) with only the new names would
# treat a cited $ price as ours to change — the silent re-tightening that
# test_the_boundary_headers_match_what_the_renderer_actually_emits exists to catch.
# "What we could not work out" is deliberately NOT here: those sentences are Python
# literals, so they belong on the strict side with the rest of our own prose.
#: What the renderer emits TODAY. A test pins this pair against `_render_financial_model`,
#: so renaming a heading there goes red here instead of silently re-tightening the rule.
FINANCIAL_MODEL_FREE_TEXT_HEADERS_CURRENT = (
    "### What we assumed", "### Where this is weakest",
)
#: The pre-2026-08-14 spellings, on every pack already on disk. Nothing emits these now, so
#: they cannot be asserted against the renderer — which is exactly why they are kept OUT of
#: the current-contract tuple below and added back at the one place that needs them.
FINANCIAL_MODEL_FREE_TEXT_HEADERS_LEGACY = (
    "### Key Assumptions", "### Model Weaknesses",
)
#: The CURRENT renderer contract, and only that, so the drift guard can assert the renderer
#: still emits every name in it. The recognised BOUNDARY is the union of the two, formed in
#: `split_rendered_free_text` below — one place, so the guard and the boundary cannot drift.
FINANCIAL_MODEL_FREE_TEXT_HEADERS = FINANCIAL_MODEL_FREE_TEXT_HEADERS_CURRENT
_LEGACY_FREE_TEXT_HEADERS = FINANCIAL_MODEL_FREE_TEXT_HEADERS_LEGACY


def split_rendered_free_text(fin_text: str) -> Tuple[str, str]:
    """Split a financial model into (Python-rendered head, model-authored tail).

    A missing list is legal output (`if assumptions_list:`), so an artifact with neither
    header is ALL rendered — the fallback has to be "all of it", never "none of it", or the
    strict half of the currency rule would quietly stop applying to the packs it was
    written for.
    """
    text = fin_text or ""
    cuts = [text.index(h)
            for h in FINANCIAL_MODEL_FREE_TEXT_HEADERS + _LEGACY_FREE_TEXT_HEADERS
            if h in text]
    cut = min(cuts) if cuts else len(text)
    return text[:cut], text[cut:]


def _quoted_comparable_problems(text: str, home_haystack: str, sym: str,
                                market: str, where: str) -> List[Problem]:
    """Grade prose that may legitimately quote a foreign price.

    A foreign amount alongside the buyer's own currency is a comparable and rides as a
    warning; foreign-ONLY — the buyer never sees their own currency — stays an error.
    `home_haystack` is deliberately wider than `text`: the buyer reads the whole artifact,
    so a £ in a rendered row above satisfies "they can see their own currency" for a $
    quoted in the notes below.
    """
    problems: List[Problem] = []
    body = text or ""
    for w in sorted(_ALL_SYMBOLS - {sym}):
        if w not in body:
            continue
        if sym in (home_haystack or ""):
            problems.append(_warn(
                "currency", where,
                f"'{w}' appears alongside '{sym}' (foreign comparable is fine; check it is one)"))
        else:
            problems.append(_err(
                "currency", where,
                f"only '{w}' amounts in a '{market}' pack (expected '{sym}')"))
    return problems


def check_currency(fin_text: str, listing_copy: str, market: str,
                   *, listing_home: str = "") -> List[Problem]:
    """The financial model must price in the market's currency.

    Its RENDERED rows are Python formatting a number, so a wrong symbol there is OUR defect,
    never the model's prose licence — always an error. That is the whole defect class this
    check was written for: `_render_financial_model` hardcoded `£` until 091e806, so a `us`
    pack shipped `- **£295**` in its headline while its own justification said `$295`.

    Its trailing notes are NOT rendered, and grading them by the same rule made a cited
    comparable unfixable. "PACER charges $0.10 per page (source: pacer.uscourts.gov)" in a
    `uk` pack is foreign because the SOURCE is foreign, and the only edit that satisfied a
    whole-artifact rule was rewriting the figure to £0.10 — falsifying a citation on a
    storefront whose first rule is source-or-die. Measured 2026-08-09: four packs were held
    off the shelf with ZERO foreign amounts in their rendered region, every one of them
    quoting a price alongside a £ figure on the same line.

    So the notes are graded by the rule listing copy already gets: foreign alongside home is
    a warning, foreign-only is an error.
    """
    sym = expected_currency(market)
    if not sym:
        return []
    problems: List[Problem] = []
    rendered, notes = split_rendered_free_text(fin_text)
    for w in sorted(_ALL_SYMBOLS - {sym}):
        n = rendered.count(w)
        if n:
            problems.append(_err(
                "currency", "financial_model",
                f"{n} '{w}' amount(s) in a '{market}' pack (expected '{sym}')"))
    problems += _quoted_comparable_problems(
        notes, fin_text, sym, market, "financial_model_notes")
    # The listing page gets the same wider home haystack the notes already get, and for the
    # same stated reason: "a £ in a rendered row above satisfies 'they can see their own
    # currency'". It did not get one until 2026-08-17 — `home_haystack` was `listing_copy`
    # itself — and the buyer does not read `listing_copy` alone. The price on that page is
    # rendered from the catalogue row, not from this prose, so the one field carrying the
    # home symbol was the one field excluded from the evidence.
    #
    # Measured over the stranded packs: 2 of the 3 currency blocks were this. `c8da2ba4` is
    # a `uk` pack with 34 '£' across its artifacts, blocked because its listing page quotes
    # Microsoft's ISV Success programme — "$50K in Azure credits", "$126,000 of first-year
    # value" — which are denominated in USD by Microsoft. `f2ac7df9` quotes a US pricing
    # ladder ($129/$497/$1,997). Rewriting either into £ falsifies a citation on a
    # source-or-die storefront, which is the exact trap the notes half was fixed for on
    # 2026-08-09. The third, `48977b86`, is a REAL defect and still errors: one stray '£' in
    # the rendered rows of a `us` financial model, which no widening touches.
    problems += _quoted_comparable_problems(
        listing_copy, f"{listing_copy or ''} {listing_home or ''}", sym, market,
        "listing_page")
    return problems


# ---------------------------------------------------------------------------
# Arithmetic re-check of every computed line in 04_Financial_Model.md
# ---------------------------------------------------------------------------
# The renderer (artifacts._render_financial_model) computes from EXACT floats and prints
# ROUNDED operands, so re-multiplying the printed operands is only approximately equal to
# the printed result. Each tolerance below is the worst-case propagation of the display
# rounding (operand ±0.5 for :,.0f, ±0.005 for :,.2f, ±0.05 for :.1f) plus the result's own
# rounding — a genuine LLM-arithmetic error (the class FIX #3 killed) is orders of magnitude
# outside these bands.

def _num(s: str) -> float:
    return float(s.replace(",", ""))


# Unit word alternated 2026-08-14: a one-off business sells ORDERS, and a checker whose
# regex only knows "customers" would go silently vacuous on exactly those packs rather than
# fail — the worst failure available to a checker.
_MONTH_RE = re.compile(
    r"\*\*Month (1|12):\*\* [£$€]([\d,]+) × ([\d,]+) (?:customers|orders) = "
    r"\*\*[£$€]([\d,]+)\*\*")
_GROWTH_RE = re.compile(r"\*\*Growth \(M1→M12\):\*\* ([\d.]+)×")
_GM_RE = re.compile(
    r"\*\*Gross margin: (-?\d+)%\*\* — making and delivering it costs (\d+)%")
_PER_CUST_RE = re.compile(r"\*\*Kept per (?:customer|order): [£$€]([\d,]+\.\d{2})\*\*")
_PAYBACK_CALC_RE = re.compile(
    r"\*\*Paid back in: ~([\d.]+) months\*\* \([£$€]([\d,]+) to win a customer ÷ "
    r"[£$€]([\d,]+\.\d{2}) kept each month\)")
_CLV_CALC_RE = re.compile(
    r"- \*\*~[£$€]([\d,]+)\*\* — they pay [£$€]([\d,]+) a month and about "
    r"([\d.]+)% stop each month")


def check_arithmetic(fin_text: str) -> List[Problem]:
    t = fin_text or ""
    problems: List[Problem] = []
    revs: Dict[str, float] = {}

    for month, price_s, cust_s, rev_s in _MONTH_RE.findall(t):
        price, cust, rev = _num(price_s), _num(cust_s), _num(rev_s)
        revs[month] = rev
        if abs(price * cust - rev) > 0.5 * cust + 1:
            problems.append(_err(
                "arithmetic", "financial_model",
                f"Month {month}: {price:g} × {cust:g} = {price * cust:g}, printed {rev:g}"))

    m = _GROWTH_RE.search(t)
    if m and revs.get("1") and revs.get("12"):
        printed = float(m.group(1))
        ratio = revs["12"] / revs["1"]
        tol = 0.051 + ratio * (0.5 / revs["1"] + 0.5 / revs["12"])
        if abs(ratio - printed) > tol:
            problems.append(_err(
                "arithmetic", "financial_model",
                f"Growth M1→M12: {revs['12']:g}/{revs['1']:g} = {ratio:.2f}×, printed {printed:g}×"))

    gm = cog = None
    m = _GM_RE.search(t)
    if m:
        gm, cog = float(m.group(1)), float(m.group(2))
        if abs((100 - cog) - gm) > 1:
            problems.append(_err(
                "arithmetic", "financial_model",
                f"Gross margin: 100 − {cog:g}% = {100 - cog:g}%, printed {gm:g}%"))

    m = _PER_CUST_RE.search(t)
    if m and gm is not None and revs:
        # price is recovered from the Month-1 line (rounded), so widen the band accordingly.
        month1 = _MONTH_RE.search(t)
        if month1:
            price = _num(month1.group(2))
            printed = _num(m.group(1))
            expect = price * gm / 100
            if abs(expect - printed) > 0.5 * gm / 100 + price * 0.005 + 0.02:
                problems.append(_err(
                    "arithmetic", "financial_model",
                    f"Per-customer margin: {price:g} × {gm:g}% = {expect:.2f}, printed {printed:g}"))

    m = _PAYBACK_CALC_RE.search(t)
    if m:
        printed, cac, margin = float(m.group(1)), _num(m.group(2)), _num(m.group(3))
        if margin > 0:
            expect = cac / margin
            if abs(expect - printed) > 0.051 + 0.5 / margin * (1 + expect):
                problems.append(_err(
                    "arithmetic", "financial_model",
                    f"Payback: {cac:g} / {margin:g} = {expect:.1f} months, printed {printed:g}"))

    m = _CLV_CALC_RE.search(t)
    if m:
        printed, arpu, churn = _num(m.group(1)), _num(m.group(2)), float(m.group(3))
        if churn > 0:
            expect = arpu / (churn / 100)
            tol = expect * (0.5 / max(arpu, 1) + 0.05 / churn) + 1
            if abs(expect - printed) > tol:
                problems.append(_err(
                    "arithmetic", "financial_model",
                    f"CLV: {arpu:g} / {churn:g}% = {expect:.0f}, printed {printed:g}"))

    return problems


# ---------------------------------------------------------------------------
# Required sections (renderer contract — presence/emptiness is validate_pack's finding)
# ---------------------------------------------------------------------------

# Only the two the renderer GUARANTEES. Payback and lifetime value are computed from
# inputs a model may not supply, and requiring their headings is what forced the renderer
# to print `_(not specified)_` under an empty one — 23 of 68 shipped packs carried at least
# one, 4 carried nothing else. A section that cannot be computed is now omitted and
# declared under "What we could not work out"; the renderer returns "" (and the pack is
# held back) when even the headline is missing, which is what makes these two safe to pin.
REQUIRED_FIN_SECTIONS = ("## Financial Model", "### What it earns")

# What the same section was called before the 2026-08-14 rewrite. `check_sections` is a
# SELLABILITY gate — a `sections` error unlists the pack — so grading a pack rendered last
# week against this week's header names would take packs off the shelf for a rename. Present
# here, absent from REQUIRED_FIN_SECTIONS above, so a section that is genuinely missing is
# still reported under the name the renderer emits today.
_SECTION_ALIASES = {"### What it earns": ("### Revenue",)}


# ---------------------------------------------------------------------------
# Placeholders — a gap where a number should be
# ---------------------------------------------------------------------------
# Added 2026-08-14. `_(not specified)_`, `_(cannot compute without CLV and CAC)_` and
# `_(targets not specified)_` were RENDERED BY US, in place of every figure the model had
# not supplied. Measured across the 68 financial models on disk: 23 carried at least one and
# 4 carried nothing else — a document called "Financial Model", in a £49.99 pack, with no
# number in it. The renderer no longer emits them; this is the fence that keeps any future
# one off the storefront rather than trusting that it will not come back.
#
# `error` severity, deliberately: `report["ok"]` is what the publish gate ANDs into
# `is_listed`, so a placeholder holds the pack back instead of riding along in a warning
# nobody reads.
_PLACEHOLDER_RE = re.compile(
    r"_\((?:[^)]*\b(?:not specified|not stated|cannot compute|unspecified|to be "
    r"determined|tbd|todo|n/a)\b[^)]*)\)_", re.IGNORECASE)


def check_placeholders(artifacts: Mapping[str, str]) -> List[Problem]:
    """Every artifact, not just the financial model: the defect is a shape, not a file."""
    problems: List[Problem] = []
    for name, text in sorted((artifacts or {}).items()):
        for hit in dict.fromkeys(_PLACEHOLDER_RE.findall(str(text or ""))):
            problems.append(_err(
                "placeholders", name,
                f"a gap is printed where a figure belongs: {hit.strip()}"))
    return problems


def check_marketing(marketing: Optional[Iterable[Mapping[str, Any]]]) -> List[Problem]:
    """Is each marketing asset the document its label claims, written to its own reader?

    Three findings, and the severities are calibrated to what a republish can actually do:

    * **error** — a piece written to sell OUR pack where the buyer needs copy for THEIR
      business ("open the pack", "this is the plan for"). It is unusable as it stands and
      is unambiguous: 19 of 557 dossiers on 2026-08-14, so blocking cannot strand the
      corpus.
    * **error** — a `listing_page` that opens `Subject:`. That is the swap the founder
      found, and a listing page is the one piece the storefront actually renders.
    * **warning** — a `launch_email` with no subject line. Corpus-wide (177 of 177 before
      the prompt fix), so an error here would unlist every pack on disk over a defect that
      only regeneration can clear. It rides in the receipt and becomes countable.
    """
    problems: List[Problem] = []
    for piece in marketing or []:
        t = str((piece or {}).get("type", "") or "").strip().lower()
        copy = str((piece or {}).get("copy", "") or "")
        if not copy.strip():
            continue
        where = f"marketing:{t or 'asset'}"
        hit = PACK_VOICE_RE.search(copy)
        if hit and t in BUSINESS_VOICE_TYPES:
            problems.append(_err(
                "marketing_audience", where,
                f"written to sell this pack, not to the business's own customers: "
                f"{hit.group(0)!r}"))
        if t == "listing_page" and has_subject_line(copy):
            problems.append(_err(
                "marketing_audience", where,
                "the listing page opens with a subject line, so it is an email under the "
                "wrong heading"))
        if t == "launch_email" and not has_subject_line(copy):
            problems.append(_warn(
                "marketing_audience", where,
                "no subject line, so this is a description of the business rather than an "
                "email anyone could send"))
    return problems


def check_sections(fin_text: str) -> List[Problem]:
    t = (fin_text or "").strip()
    if not t:
        return []  # an empty artifact is validate_pack's finding; don't double-report
    return [
        _err("sections", "financial_model", f"missing required section {s!r}")
        for s in REQUIRED_FIN_SECTIONS
        if s not in t and not any(a in t for a in _SECTION_ALIASES.get(s, ()))
    ]


# ---------------------------------------------------------------------------
# Mid-word truncation in storefront copy
# ---------------------------------------------------------------------------

_WORD_CHAR = re.compile(r"[A-Za-z0-9]")


def check_truncation(fields: Dict[str, Tuple[str, str]],
                     caps: Optional[Dict[str, int]] = None) -> List[Problem]:
    """`fields` maps field name → (final rendered value, full pre-truncation source).

    Two cut styles exist in the publish path and both are checked against the source:
    an ellipsis suffix ("…"/"...") whose pre-ellipsis text stops inside a word of the
    source, and a bare hard slice (headline[:140], subhead[:280]) that ends exactly at
    its cap in the middle of a source word. The source is what makes this decidable —
    "…applicat…" is only provably mid-word because the source continues with a letter.
    """
    problems: List[Problem] = []
    for name, (final, source) in fields.items():
        f, s = (final or "").strip(), (source or "").strip()
        if not f:
            continue
        ell = next((e for e in ("…", "...") if f.endswith(e)), None)
        if ell:
            prefix = f[: -len(ell)].rstrip()
            if (prefix and s.startswith(prefix) and len(s) > len(prefix)
                    and _WORD_CHAR.match(prefix[-1]) and _WORD_CHAR.match(s[len(prefix)])):
                problems.append(_err(
                    "truncation", name,
                    f"ends mid-word: …{prefix[-20:]!r}{ell} (source continues {s[len(prefix):len(prefix) + 12]!r})"))
            continue
        cap = (caps or {}).get(name)
        if (cap and len(f) == cap and s.startswith(f) and len(s) > cap
                and _WORD_CHAR.match(f[-1]) and _WORD_CHAR.match(s[cap])):
            problems.append(_err(
                "truncation", name,
                f"hard-sliced mid-word at [:{cap}]: …{f[-20:]!r}"))
    return problems


# ---------------------------------------------------------------------------
# Title format — the marketing headline, and the only copy every surface shows
# ---------------------------------------------------------------------------

#: The declared shape (founder decision 2026-08-13, superseding "the name leads" of
#: 2026-08-09): `<what the business does> for <who pays>`. The trade comes first, in the
#: words a stranger already knows, because the reader is a person deciding whether to START
#: this business, not the end customer of the service it sells.
#: `TITLE_MAX_CHARS` mirrors `CARD_LINE_MAX` (artifacts.py) deliberately — the storefront
#: already produces a 40-60 char line for the same pack and renders it well, so the title
#: has no claim to be 90+.
TITLE_MAX_CHARS = 60

# The actuator's default, named once because it is read in two places — `check_title`/`lint`
# below, and `bridge.py`'s `listing_cfg.get(...)` fallback on the publish path. Two literals
# that must agree is the same drift this module exists to catch: the one that matters is
# bridge's, and a config file cannot be relied on to carry it (see check_title, 2026-08-14).
TITLE_BLOCK_ON_BREACH_DEFAULT = True

#: Kept for the LEGACY reading of a `Name, descriptor` title (see `split_title`). They no
#: longer gate `check_title`: under the current format there is no name in the title at all.
TITLE_NAME_MAX_WORDS = 4
TITLE_NAME_MAX_CHARS = 30

#: A coined product name — an intercapped word: `HoursBack`, `ScopeDrift`, `CareFeeRefund`,
#: `SwarmHold`, `SpatWindow`. This is the shape the founder called cryptic on 2026-08-13:
#: it is the first thing a scanner reads and it means nothing until you already own the pack,
#: while spending up to half the character budget. All-caps initialisms (`NHS`, `HMRC`, `FSA`)
#: do NOT match — they are words a reader already knows, which is the whole distinction.
_TITLE_COINAGE = re.compile(r"\b[A-Z][a-z]+[A-Z][A-Za-z]*\b")

def _ruleset_version() -> str:
    """A fingerprint of the rules themselves, so nobody has to remember to bump a number.

    This is stamped into every `<id>.lint.json` receipt, and `tools/publish_passes.py::
    _fresh_lint` refuses a receipt whose fingerprint differs — so a stored verdict can never
    outlive the rules that produced it.

    WHY IT IS DERIVED AND NOT A HAND-EDITED CONSTANT. The first cut of this was
    `RULESET_VERSION = 2`, and a hand-bumped constant is a rule that depends on someone
    remembering. That is the same shape as the defect it was written to fix: freshness was
    mtime alone, which answers "has the PACK changed" and cannot answer "have the RULES
    changed", because a linter edit touches no dossier. On 2026-08-17 five rules stopped
    blocking, every receipt on disk stayed byte-identical and newer than its pack, and seven
    freed packs would have gone on reading as blocked forever. A forgotten bump reproduces
    that exactly, silently, and only shows up as packs that never come back on sale.

    The fingerprint is the file's own bytes. A comment-only edit therefore invalidates every
    receipt too, and that is the deliberate trade: a re-gate is a rehearsal — no model call, no
    Stripe object, no listing — so the cost of an unnecessary one is a few seconds of daemon
    time, while the cost of a missed one is a finished pack off the shelf indefinitely.

    Same lesson as `_PROBE_LOGIC_VERSION` below, which exists because a cached 404 outlived
    the probe fix that would have cleared it.
    """
    try:
        return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]
    except OSError:
        # Unreadable source (a zipimport, a stripped deploy). Refusing every receipt forever
        # would be the safe direction but turns a packaging quirk into permanent re-gating, so
        # fall back to a fixed stamp: freshness degrades to mtime, which is where it started.
        return "unfingerprinted"


RULESET_VERSION = _ruleset_version()


def receipt_is_current(receipt: Any) -> bool:
    """Was this stored `<id>.lint.json` verdict produced by the rules running right now?

    ONE definition, three callers, because three copies of this comparison is how they drift:
    `tools/publish_passes.py::_fresh_lint` decides whether to re-gate,
    `scheduler/run_scheduled.py::_stale_verdicts` decides what the tick re-gates, and
    `ops/console_api.py::_read_shelf` decides whether to tell the operator "blocked by X" or
    "nobody has asked under today's rules". A console confidently printing a retired verdict is
    the same defect as the tool doing it, one screen further out.

    A receipt with no `ruleset` key predates the stamp and is not current by definition.
    """
    return isinstance(receipt, dict) and receipt.get("ruleset") == RULESET_VERSION

#: Intercapped words the buyer already knows. Same distinction as the all-caps exemption
#: above, applied to the other shape a known term comes in: a coinage is cryptic because the
#: reader has never seen it, and "GitHub" is not that.
#:
#: Measured on the lint receipts of 2026-08-17, where 19 findings named a coined name: three
#: were real-world vocabulary and all three were ERRORS holding a finished pack off the shelf.
#: `f2734b0fcec9ca32` said "GitHub Advanced Security alert investigation summaries for lean
#: dev teams", `7be1cb35e01902d7` said "AWS DevOps ops desk", `5597002395f8ea60` said
#: "DIR-contract SaaS vendors". The rule told all three to "say the trade instead" — and the
#: trade is what they were already saying. The other 16 are genuine coinages (`LicenceCraft`,
#: `ComputeSheet`, `MouldBreak`) and still block, which is the point of the rule.
#:
#: Matched case-sensitively, on the whole word. `Github` is a misspelling, not this term, and
#: the linter has no business quietly accepting it.
KNOWN_PRODUCT_NAMES = frozenset("""
    GitHub GitLab BigQuery PostgreSQL MongoDB PowerShell JavaScript TypeScript
    NodeJS YouTube LinkedIn QuickBooks WordPress SharePoint PayPal DocuSign NetSuite
    OpenAI DevOps DevSecOps SecOps FinOps SaaS PaaS IaaS AppSec InfoSec
    HubSpot ServiceNow WooCommerce MailChimp DoorDash AirTable NextJS OneDrive
""".split())

#: Openers that are a register breach rather than a wording preference. The imperative
#: ("Sell …", "Run …") was rejected by the founder as "overused and too blunt" for a £149
#: pack; the article ("A …", "The …") spends the two characters a scanner reads first.
#: Deliberately EXCLUDES verbs that are also ordinary nouns in this position — price, cover,
#: track, harvest, audit, claim — because "Price data for …" and "Standstill cover for …" are
#: correct titles. A false positive here would block a good line, which is worse than missing
#: a bad one the prompt already discourages.
_TITLE_IMPERATIVES = frozenset("""
    sell run start build launch get find turn earn make grow become stop reverse chase
    reclaim recover win create own
""".split())
_TITLE_ARTICLES = frozenset({"a", "an", "the"})

#: Third-person verbs seen leading the descriptor of live titles on 2026-08-09 ("HoursBack,
#: finds the pay …", "ScopeDrift, prices the extra work …", "CareFeeRefund, recovers care
#: fees …"). Under the current format nothing follows a comma except a qualifying phrase.
_TITLE_THIRD_PERSON = frozenset("""
    finds prices recovers reverses chases tracks turns gets helps pays sells runs builds
    makes reclaims wins delivers provides
""".split())

_TITLE_TRIM = " \t’'\"“”‘’.,;:!?"


def _title_word(text: str) -> str:
    """The first word of `text`, lower-cased and stripped of quoting/punctuation."""
    return text.strip().split(" ")[0].strip(_TITLE_TRIM).lower() if text.strip() else ""

#: `, ` first, matching TS `TITLE_SEPARATORS` in store_platform/.../lib/discovery.ts. The
#: dash forms are recognised so this check reads a RAW title honestly if handed one; the
#: dash itself is `check_house_dashes`'s finding, never re-reported here.
_TITLE_SEPARATORS = (", ", " — ", " – ", " - ")


def split_title(title: str) -> Tuple[str, str]:
    """`"RetainRelease, chases the retention contractors hold back"` → name, descriptor.

    First separator wins, so a descriptor may contain further commas. Returns
    `(title, "")` when no separator is present — i.e. the format was not followed, which
    is the caller's finding to report, not a reason to guess a split.
    """
    t = " ".join((title or "").split())
    best = len(t)
    out = (t, "")
    for sep in _TITLE_SEPARATORS:
        i = t.find(sep)
        if 0 < i < best:
            best, out = i, (t[:i].strip(), t[i + len(sep):].strip())
    return out


def check_title(title: str, *, max_chars: int = TITLE_MAX_CHARS,
                block: bool = TITLE_BLOCK_ON_BREACH_DEFAULT) -> List[Problem]:
    """The pack title must name the TRADE and its BUYER, and fit `max_chars`.

    Why this check exists, and why it is not cosmetic. The title is the ONE string that
    reaches every surface at once — shelf card, pack page H1, `<title>` in search results,
    the OG image on a shared link — and until 2026-08-09 nothing bounded it or shaped it.
    Measured on the 48 live catalogue rows that day: median title 96.5 chars, 2 of 48 inside
    the 40-60 band, 4 rows with no descriptor at all, and four different separators in use
    (`, ` x34, em-dash x7, none x4, en-dash x3). The engine was meanwhile producing a
    correctly-sized `card_line` for 36 of those same packs (min 40, median 52.5, max 60),
    which is the proof that the short form is writable — it just was not being asked for.

    The 2026-08-09 rule fixed the LENGTH and left the register wrong, because it kept the
    coined name in front: `SITE_SPEC §5.4` wrote the cost down at the time — "the opening
    characters are what a scanner reads, and a coined word spends them". On 2026-08-13 the
    founder read the bill: "the title tells me nothing, it feels cryptic". The deeper defect
    that surfaced with it is an AUDIENCE error, not a wording one. This storefront sells a
    business to someone weighing up whether to start it; the titles were addressing the
    end customer of the service instead — `HoursBack` (id b94760e86e62585a) is sold to a
    prospective owner for £79.99 and its copy speaks to an NHS doctor about their own rota.

    So the shape is now `<what the business does> for <who pays>`, and what is checked is
    what can be checked mechanically:

      * it fits `max_chars` and does not end in a full stop;
      * it carries no coined product name (`_TITLE_COINAGE`);
      * it does not open with an imperative or an article (`_TITLE_IMPERATIVES`);
      * nothing after a comma opens with a third-person verb (`_TITLE_THIRD_PERSON`);
      * it names a buyer at all — " for " or a qualifying clause after a comma.

    What it deliberately does NOT check: whether the trade named is the right one, and
    whether a multi-word Title Case brand ("Freelance Rate Compass") is a brand or a
    description. Neither is decidable without judgement, and a false positive blocks a good
    title, so both stay the prompt's job (`prompts/retitle.md`). This function catches
    "the format was not followed", never "this is a weak title".

    `block` is the ACTUATOR, and since 2026-08-14 it defaults ON. It shipped off for one
    stated reason — on 2026-08-09 this rule errored on 46 of 48 live packs, and blocking
    would have unlisted a catalogue that predated it — with the stated condition "turn it on
    once the catalogue has been retitled". That condition is now met and measured: all 62
    live rows were re-fetched from the API and 0 are flagged by this check.

    The default flipped rather than the config alone because of how the actuator nearly came
    undone. It was switched on in `config.yaml` only, so the single line standing between a
    breaching title and a buyer sat uncommitted in a file another session owned — one
    `git checkout config.yaml` and the gate silently unbinds, with a green suite either way,
    which is precisely the class of drift the rest of this module exists to stop. A gate
    whose safe state depends on a config edit surviving is not a gate. `max_chars` was
    already code-defaulted to `TITLE_MAX_CHARS` for the same reason; only the actuator was
    not. Config may still turn this OFF, but that now takes a deliberate `false`, which
    reads as a decision in a diff instead of as an absence.
    """
    mk = _err if block else _warn
    t = " ".join((title or "").split())
    if not t:
        return [_err("title", "title", "empty")]

    problems: List[Problem] = []
    if len(t) > max_chars:
        problems.append(mk("title", "title",
                           f"{len(t)} chars exceeds the {max_chars} limit: {t!r}"))
    if t.endswith("."):
        problems.append(mk("title", "title", f"ends in a full stop: {t!r}"))

    # The first intercapped word the reader does NOT already know. `KNOWN_PRODUCT_NAMES` is
    # the same exemption the all-caps initialisms get, for the other shape a familiar term
    # comes in; the receipts that produced it are at the constant.
    coined = next((m.group(0) for m in _TITLE_COINAGE.finditer(t)
                   if m.group(0) not in KNOWN_PRODUCT_NAMES), None)
    if coined:
        problems.append(mk(
            "title", "title",
            # Say WHERE it is. This said "leads with" on a rule that searches the whole
            # title, so a receipt could tell the writer to fix an opener that was fine.
            f"{'leads with' if t.startswith(coined) else 'carries'} a coined product name "
            f"{coined!r}, which means nothing to a reader who does not own the pack: say the "
            f"trade instead — {t!r}"))

    opener = _title_word(t)
    if opener in _TITLE_ARTICLES:
        problems.append(mk(
            "title", "title",
            f"opens with the article {opener!r}, spending the characters a scanner reads "
            f"first: {t!r}"))
    elif opener in _TITLE_IMPERATIVES:
        problems.append(mk(
            "title", "title",
            f"opens with the imperative {opener!r}; the register is a noun phrase naming the "
            f"business, not an instruction to the reader: {t!r}"))

    head, sep, tail = t.partition(", ")
    if sep:
        after = _title_word(tail)
        if after in _TITLE_THIRD_PERSON:
            problems.append(mk(
                "title", "title",
                f"the part after the comma opens with the verb {after!r}; the title says what "
                f"the business IS, and a comma qualifies it: {t!r}"))
    elif " for " not in f" {t.lower()} ":
        problems.append(mk(
            "title", "title",
            f"names no buyer: expected '<what the business does> for <who pays>', got {t!r}"))
    return problems


# ---------------------------------------------------------------------------
# Shelf copy — the short buyer-visible lines, graded as writing a stranger reads
# ---------------------------------------------------------------------------
#
# WHY THIS EXISTS. On 2026-08-13 the founder read a live card line back — "£180 a claim,
# filed on the platform's own cover" — and asked whether it made sense to a website
# visitor. It did not, and it passed every check in this file: short, sourced, true, in
# register, dash-free, inside its cap. An audit of the 50 live packs that afternoon found
# 48 carrying at least one copy defect of a class nothing here could see, and every one of
# them had been caught by the founder's eye rather than by the engine. A quality bar held
# up by one person reading every line is not a business operation, which is the whole
# reason these are functions and not another paragraph in `prompts/style/voice.md`: a
# prompt is a request evaluated by the same process that produces the error.
#
# SCOPE IS THE SHORT LINES ONLY, named explicitly in `SHELF_FIELDS`. Body prose is graded
# by `check_grammar`; these rules assume a single line written to a stranger and would
# misfire on a paragraph. Selecting a corpus by shape instead of by name is how
# `check_identifier_leak` once graded a .csv as writing.
#
# WHAT IS MECHANICAL AND WHAT IS NOT. Five classes below are decidable — an ellipsis, a
# duplicate, our own filing vocabulary, an unexplained initialism, and copy addressed to
# the end customer. The sixth, "this line does not parse to a stranger", is not: the
# founder's own example carries a verb, cites a real number and is grammatical. It is
# reported at `warning` with a stated false-positive rate, following the same doctrine as
# the title checks below — name the residue for the reviewer rather than pretend a regex
# ruled on it.

#: Every field this grades, by NAME. Both spellings of each are listed because the
#: catalogue row uses camelCase (`cardLine`) and the pack model uses snake (`card_line`),
#: and a field that reaches the gate under the other spelling is silently ungraded.
SHELF_FIELDS = frozenset({
    "title", "headline", "subhead",
    "cardLine", "card_line", "oneLine", "one_liner", "one_line",
})

#: Initialisms a capable adult outside the sector already knows, so they cost the reader
#: nothing. Everything else must be spelled out: `prompts/style/voice.md` puts it as "they
#: have never heard of any acronym you are about to use". The 14 live packs that failed
#: this on 2026-08-13 used FSA, CIS, IEP, COSHH, FOI, ICB, DVSA, HSE, ADA and CalSTRS —
#: each one a word the trade says to itself. Adding to this list is a claim that a stranger
#: knows the term; make it deliberately.
#: Measured against the 50 live packs on 2026-08-13: with this list, every remaining hit
#: was a real defect (IEP, ADA, COSHH, ICB, CIS, STRS, DVSA, FOI, IFA) and none was a false
#: positive. LED, UV and API are here because they are everyday words to a general reader,
#: which is the only test that matters — not because they are short.
#: US STATE POSTAL CODES, added 2026-08-15. These are the same CATEGORY as the `UK`/`US`/`EU`
#: already above — a geography a stranger reads without effort — not sector jargon, so they pass
#: the "costs the reader nothing" test this list is written against.
#: They are here because their absence was silently unsellable. `schedule.market_rotation`
#: (config.yaml:2015) was changed on 2026-08-14 to `us-tx,us-ca,us-fl,us-ny,uk,us-il,us-pa,
#: us-oh,us-ga,uk` — eight US states, each of which the generator names by its code. Every such
#: pack then FAILED this rule, and a shelf-copy failure is not a copy warning: it fails the
#: content gate, which skips Stripe provisioning and publishes the pack UNLISTED (bridge.py, and
#: launchd.err.log 2026-08-15T12:56:14Z for id 4f1fdd37b84da131). A validated PASS became
#: unbuyable over a two-letter state abbreviation. Ten packs went that way before this line.
#: ALL FIFTY are listed, deliberately, rather than only the eight in today's rotation: the defect
#: was a rotation edit that this file did not know about, and a partial list rebuilds that exact
#: trap the next time a state is added. The price is that a title SHOUTING an ordinary word that
#: happens to be a state code — IN, OR, OK, ME, HI, DE — no longer trips the initialism rule.
#: That is a style miss; the alternative was an unsellable pack.
_US_STATE_CODES = """
AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO
MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC
"""

KNOWN_INITIALISMS = frozenset("""
NHS HMRC DWP DVLA MOT PAYE VAT ISA GP GPS CV DIY PDF CSV TV CCTV PPE LED UV
UK US USA EU EEA IRS DMV FBI FDA CDC EPA USDA
AI IT HR API CEO CFO CTO MP MPs PhD BBC
OSHA
""".split()) | frozenset(_US_STATE_CODES.split())

#: OSHA, added 2026-08-16, is a deliberate claim under the rule this list states: a capable
#: adult outside the sector already knows it. "OSHA violation" is ordinary American speech,
#: the same register as MOT or NHS here, and the California agency's own name is `Cal/OSHA`
#: — an expansion ("California Division of Occupational Safety and Health") is longer than
#: the 60-character title budget and names a body no one searches for. It was the single
#: remaining initialism hit across the 61 live rows, on
#: `d6f72b9dc9a45c45 Cal/OSHA citation contest tool for California employers`, and spelling
#: it out would have made that title worse to satisfy a rule aimed at trade shorthand.
#: The neighbours it does NOT license stay out: COSHH, DVSA, IHT, DLA and PAH remain
#: defects, because each is a term only the trade says.

#: Words, for the lexicon tests. Apostrophes stay inside the token so "you're" survives as
#: one word; hyphens split, so "unpaid-hours" tests as "unpaid" and "hours".
_SHELF_WORD_RE = re.compile(r"[a-z][a-z'’]*")

#: A run of two or more capitals inside a word. Catches the bare initialism (`FSA`) and the
#: one hiding in a mixed-case token (`CalSTRS` → `STRS`) with the same rule, which matters
#: because the second shape reads as a proper noun and slips past a token-equality test.
#:
#: The leading digits belong to the run. Trade terms are built that way — `3PL`, `2FA`, `4PL`
#: — and dropping the digit made the linter name a term that is not in the copy: the receipt
#: on `19aaf66a4e9f7778` told the operator to spell out "PL" in the line "Savannah port
#: container dwell forecasts for 3PLs", where no "PL" appears. An instruction that names a
#: string the writer cannot find is not actionable, and `listing.initialism_glossary` is
#: keyed on the reported term, so the operator's own expansion could never match it either.
_CAPS_RUN_RE = re.compile(r"\d*[A-Z]{2,}")

#: Words an expansion skips over, so `Driver and Vehicle Standards Agency (DVSA)` still reads
#: as D-V-S-A. Every one is a joining word that no one puts in an initialism.
_EXPANSION_SKIP = frozenset("""
of and the for in on at to a an with de du la le los las
""".split())

#: A parenthetical, for the expand-on-first-use check below.
_PAREN_RE = re.compile(r"\(([^)]{1,120})\)")
_EXPANSION_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'’./-]*")


def _initials_spell(words: list[str], run: str, *, from_end: bool) -> bool:
    """Do these words' initials spell `run`, reading from the end (or the start)?

    Joining words are skipped, but only BETWEEN letters — the boundary word must carry a
    letter, or `Agency (DVSA)` would match on any four words that happen to sit near an
    `and`. Nothing else is allowed to be skipped, so a near-miss expansion fails rather
    than passing on a coincidence.
    """
    letters = list(run.upper())
    seq = list(words)
    if from_end:
        letters.reverse()
        seq.reverse()
    i = 0
    for letter in letters:
        matched = False
        while i < len(seq):
            word = seq[i]
            i += 1
            if word[0].upper() == letter:
                matched = True
                break
            if word.lower() in _EXPANSION_SKIP:
                continue  # a joining word between two initials
            return False
        if not matched:
            return False
    return True


def expands_on_first_use(text: str, run: str) -> bool:
    """Does this line spell `run` out in full, right where it uses it?

    The rule below tells the writer to "spell it out in full", and until 2026-08-16 it then
    refused the line that did: it only ever asked whether the CAPS RUN was in the known list,
    so `Amazon Web Services (AWS)` failed exactly as `AWS` did. The instruction was
    unsatisfiable — the only compliant copy deleted the letters. That was not a style miss:
    a shelf-copy error fails the content gate, so the pack skips Stripe provisioning and
    publishes UNLISTED. On 2026-08-16 it held 31 of the 33 defective live rows, on ordinary
    terms (METRC, CMMC, DVSA, ISV, PAC) that a line can perfectly well introduce.

    Both orders count, because both read fine:
        `Amazon Web Services (AWS)`      expansion first
        `AWS (Amazon Web Services)`      initialism first

    The match is on INITIALS, not on a dictionary, so nothing here decides what a term means
    — it only checks that the words next to it actually are that term spelled out. A garbled
    expansion still fails.
    """
    for match in _PAREN_RE.finditer(text):
        inside = match.group(1)

        # `Expansion (RUN)` — the run is the whole parenthetical, or the caps run inside it.
        if run in _CAPS_RUN_RE.findall(inside):
            before = _EXPANSION_WORD_RE.findall(text[:match.start()])
            if before and _initials_spell(before, run, from_end=True):
                return True

        # `RUN (Expansion)` — the run sits immediately before the bracket.
        head = _EXPANSION_WORD_RE.findall(text[:match.start()])
        if head and run in _CAPS_RUN_RE.findall(head[-1]):
            inside_words = _EXPANSION_WORD_RE.findall(inside)
            if inside_words and _initials_spell(inside_words, run, from_end=False):
                return True
    return False


def unexplained_initialisms(text: str, context: str | None = None) -> list[str]:
    """Every caps run this line uses that the reader has never met and the page never introduces.

    The linter's rule 3 and the shelf-copy sweep both need exactly this list, and they must
    agree: the sweep repairs a line, then the linter judges it. Two copies of the same
    condition is how a sweep ships a "fix" the gate still refuses.

    `context` is where the introduction may appear, defaulting to the line itself. The
    linter passes the whole shelf, because the buyer reads those lines together and a term
    the title spells out is introduced by the time the card line uses it. The terms REPORTED
    are still only the ones this line uses; the context widens where an expansion counts,
    never what is graded.
    """
    return sorted({run for run in _CAPS_RUN_RE.findall(text)
                   if run not in KNOWN_INITIALISMS
                   and not expands_on_first_use(context if context is not None else text, run)})


#: Our filing system, leaking onto the shelf. `voice.md`: "a reader who meets one of these
#: words has been handed our filing system by mistake". `pack` and `dossier` are NOT here —
#: the storefront sells a thing it calls a pack, so that is the reader's word too.
INTERNAL_VOCAB = frozenset("""
lens lenses wedge wedges moat moats prescreen taxonomy candidate candidates
""".split())

#: Any snake_case token is ours by construction — `risk_financing`, `durable_wedge_type`,
#: `weak_monetisation`, `ambition_tier`. No line written for a buyer contains an underscore.
_TAXONOMY_TOKEN_RE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")

#: Trade shorthand and register breaches from `voice.md`'s "prefer the everyday word".
#: These are warnings, not errors: each is legitimate ONCE the plain description has been
#: given first ("no assessor and no argument (the trade calls this 'parametric')"), and
#: whether that gloss is present is not decidable here.
TRADE_SHORTHAND = frozenset("""
parametric indemnify indemnifies indemnified indemnity procure procures procurement
thereby ceases cease aforementioned herein utilise utilises heretofore
""".split())

#: Second person on the shelf, in ANY direction. The rule is stated as register — these
#: lines describe the business in the third person — because that is the decidable test,
#: and the two cases behind it cannot be told apart by a machine. 18 of the 19 live
#: instances on 2026-08-13 were copy written to the END CUSTOMER of the service:
#: "calculates your holiday pay entitlement" talks to the worker, when the buyer is the
#: person deciding whether to run holiday-pay audits at all. `voice.md` calls that "the
#: most expensive mistake available here, because it reads fluently and is aimed at nobody
#: who can buy". The 19th ("setting yourself up to certify other electricians' wiring")
#: did address the buyer, and was still shorter and better in the third person.
_SECOND_PERSON_RE = re.compile(r"\b(you|your|yours|you're|yourself|yourselves)\b", re.I)

#: A shelf line that OPENS on a bare pronoun. The reader meets the line cold, with no
#: antecedent anywhere on the page, so "It takes a published NHS rota…" and "We handle your
#: stolen tool claim…" both start by naming nothing: the first word is a promise that the
#: previous sentence said what this is, and there is no previous sentence. The house shape
#: opens on the thing itself — "A tool for UK freelance designers, developers and writers
#: that turns every out-of-scope client request into a priced, dated change note" (founder,
#: 2026-08-16, naming this the line to copy). Matched on the FIRST word only: the same
#: pronoun mid-sentence has an antecedent and is fine.
_BARE_OPENER_RE = re.compile(
    r"^[\s\"'“‘(]*(it|its|it's|we|our|ours|us|they|them|their|theirs|this|that|these|those|i)\b",
    re.I)

#: Finite verbs, for the residue check only. THE BARE INFINITIVES ARE DELIBERATELY ABSENT
#: and this is the whole precision of the check: `cover`, `claim`, `check`, `file`, `pay`,
#: `work`, `run` and `list` are all nouns in shelf copy, and including them scored a verb
#: for "£180 a claim, filed on the platform's own cover" — the exact line the founder
#: rejected. Only third-person-singular and copula/modal forms count, because a shelf line
#: that says something is a present-tense statement about the business.
#: This warns rather than errors because the lexicon cannot be complete: "the platform
#: already bought" is finite, absent here, and a perfectly good line.
_FINITE_VERBS = frozenset("""
is are was were has have had does did can will would should must may might
pays recovers reclaims refunds covers claims files reads finds tells shows builds
makes checks audits chases tracks matches flags sells runs writes sends turns takes
gives works costs saves charges earns owes wins proves names lists ranks scores sorts
handles prepares drafts submits appeals spots catches stops starts keeps holds
lets helps needs wants gets puts sits comes goes means counts
""".split())

#: Pronouns that carry no antecedent when a shelf line is read on its own. A shelf line is
#: shown beside the title, never inside a paragraph, so "It takes a published NHS rota..."
#: (the live `b94760e86e62585a` one-liner the founder rejected on 2026-08-16 as "zero
#: content") points at nothing the sentence itself has named.
#:
#: Fires ONLY when the pronoun is followed immediately by a finite verb, which is what
#: makes it BARE. "This service reads your rota" names its subject and stays quiet; "It
#: takes" and "They read" do not. That pairing is why the check needs no exception list:
#: measured over the 75 live one-liners on 2026-08-16 it named exactly one, the founder's.
_BARE_PRONOUN_OPENERS = frozenset({"it", "they", "this", "that", "these", "those"})

#: Dedup attribution order: the title is the canonical line, so when a headline or card
#: line repeats it the finding is reported against the REPEAT, not against the title. Any
#: field not named here sorts after these, alphabetically.
_SHELF_DEDUP_ORDER = ("title", "headline", "subhead", "cardLine", "card_line",
                      "oneLine", "one_liner", "one_line")

#: Normalisation for the duplicate test: case, punctuation and spacing all differ between
#: the three lines without the reader gaining anything, so "Unpaid-hours audits for NHS
#: doctors" and "unpaid hours audits for nhs doctors." are the same line said twice.
_DEDUP_STRIP_RE = re.compile(r"[^a-z0-9 ]+")


def _dedup_key(text: str) -> str:
    return " ".join(_DEDUP_STRIP_RE.sub(" ", (text or "").lower()).split())


# ==============================================================================================
# Engine vocabulary in the BODY of the pack.
#
# WHY THIS IS A SECOND LIST AND NOT `INTERNAL_VOCAB`. That list grades `SHELF_FIELDS` — six
# short lines — where a single word out of register is fatal and `candidate` can only mean our
# candidate. The body is 5,800 words per pack of ordinary business English, and every loose word
# on the shelf list means something else there. Measured on 296 live buyer documents (427,687
# words) on 2026-08-15, a loose list scored 461 hits for "composite/score" and 191 for the check
# names, and the FIRST FIVE examples pulled at random were all false positives: "aluminum
# composite" in a signage build spec, a council "pre-screening addresses", "adversarial" used to
# describe a marketing tone, "churn signal", "no grounding in specific search volume". A check
# that cries wolf 90% of the time is how a rate ceiling gets set to a number that means nothing.
#
# So this list holds only tokens with NO other meaning in a business document. Retested against
# the same corpus it found 24 real hits and no false positives, all of the same shape — the
# engine quoting its own scoresheet at the buyer:
#
#     "The confidence scores on the supporting checks are low (value_durability 0.438,
#      distribution 0.430), and nothing retrieved demonstrates that…"
#
# `distribution`, `incumbency` and `legality` are check names and are ABSENT on purpose: they are
# also three of the commonest nouns in the corpus. They are caught in the sentence above by their
# neighbour, which is the correct precision to buy.
BODY_ENGINE_TOKENS = frozenset("""
pain_reality value_durability payer_solvency pain_acuity money_provability
min_composite ambition_tier durable_wedge_type weak_monetisation composite_score
provider_chain retrieval_failed score_failed prescreen prescreened unverifiable
""".split())

#: Multi-word engine phrases. Each is checked as a whole phrase because each has a harmless
#: single word inside it: "composite" (a material), "chain" (of shops), "judge" (a person),
#: "gate" (a milestone), "fail" (a test). The phrase is ours; the words are not.
BODY_ENGINE_PHRASES: Tuple[str, ...] = (
    "composite score", "kill filter", "kill-filter", "provider chain",
    "ai judge", "ai-judge", "adversarial review", "adversarial pass",
    "vetting pass", "grounding pass", "provisional verdict", "hard fail",
    "confidence score of", "our internal score",
)

_BODY_PHRASE_RE = re.compile(
    "|".join(re.escape(p) for p in sorted(BODY_ENGINE_PHRASES, key=len, reverse=True)),
    re.I,
)


def check_engine_leak(sections: Optional[Mapping[str, str]], *,
                      block: bool = False, max_per_1k: float = 0.0) -> List[Problem]:
    """Grade the assembled buyer read for OUR filing system leaking into the prose.

    `sections` is the same corpus `check_register` takes — the fourteen-section assembled
    read when the caller has it, the four prose artifacts otherwise. Nothing had ever graded
    it for engine vocabulary: `check_shelf_copy` reads six short lines and `INTERNAL_VOCAB`
    is scoped to them, so a financial model could print `value_durability 0.438` at a buyer
    and every check in this module passed.

    SHADOW-FIRST, like every other rate actuator here. `block` off, every finding is a
    warning and the receipt accrues on live packs; `max_per_1k` at 0.0 means the rate is
    measured and never enforced. A threshold is set from the baseline, not before it.
    """
    problems: List[Problem] = []
    if not sections:
        return problems

    mk = _err if block else _warn
    total_words = 0
    hits: List[Tuple[str, str]] = []          # (section, the offending text)

    for name, body in sorted((sections or {}).items()):
        if not isinstance(body, str) or not body.strip():
            continue
        total_words += len(body.split())
        lowered = body.lower()

        found = sorted({w for w in _SHELF_WORD_RE.findall(lowered) if w in BODY_ENGINE_TOKENS})
        # Underscored identifiers do not survive `_SHELF_WORD_RE`, which splits on the
        # underscore. Match them on the raw text instead — they are the whole point of the
        # token list, and every one of the 24 measured hits has this shape.
        found += sorted({t for t in _TAXONOMY_TOKEN_RE.findall(lowered)
                         if t in BODY_ENGINE_TOKENS})
        found += sorted({m.group(0).lower() for m in _BODY_PHRASE_RE.finditer(body)})

        for term in sorted(set(found)):
            i = lowered.find(term)
            window = body[max(0, i - 70):i + 90].replace("\n", " ").strip()
            hits.append((name, term))
            problems.append(mk("engine_leak", name,
                               f"our filing system in the buyer's prose: {term!r} — "
                               f"say what the thing does instead: …{window}…"))

    # The rate, reported whether or not it fires, so the baseline accrues.
    if total_words and max_per_1k > 0:
        rate = 1000.0 * len(hits) / total_words
        if rate > max_per_1k:
            problems.append(mk("engine_leak", "pack",
                               f"engine vocabulary at {rate:.2f} per 1,000 words over the whole "
                               f"pack, above the {max_per_1k:.2f} ceiling "
                               f"({len(hits)} in {total_words:,} words)"))
    return problems


def check_shelf_copy(fields: Dict[str, str], *, block: bool = False,
                     report_residue: bool = False) -> List[Problem]:
    """Grade the short buyer-visible lines the way a website visitor reads them.

    `fields` is the same `house` mapping the other house checks take; only the names in
    `SHELF_FIELDS` are graded, so passing a whole pack is safe.

    `block` is the actuator, exactly like `check_title`'s: off, every finding is a
    `warning` and the receipt accrues on live packs; on, the mechanical rules become
    `error`, which `lint_pack` turns into `ok=False` and the publish path ANDs into
    `is_listed`.

    ONE rule is exempt from `block` and always warns: the duplicate-line check (rule 7).
    It grades a line that is redundant, not one that is wrong, and it was refusing to sell
    finished packs over copy our own fallback had written. Founder decision 2026-08-17;
    the reasoning is at the rule itself.

    `report_residue` adds the "reads as a fragment" check, which is a reviewer's tool and
    never an actuator: it warns under either `block` setting, and it is off by default
    because it cannot be complete. Measured on the 50 live packs of 2026-08-13 it named all
    four card lines the founder rejected, at a cost of 43 findings over 200 fields.
    """
    problems: List[Problem] = []
    mk = _err if block else _warn
    graded = {k: v for k, v in sorted(fields.items())
              if k in SHELF_FIELDS and isinstance(v, str) and v.strip()}

    for name, raw in graded.items():
        text = raw.strip()

        # 1. A shelf line that trails off. `check_truncation` fires only where it can PROVE
        #    the cut landed mid-word against a source; on the shelf the line IS the whole of
        #    the copy, so an ellipsis is a defect whether or not the cut was clean. 29 of the
        #    50 live one-liners ended this way on 2026-08-13.
        if text.endswith("…") or text.endswith("..."):
            problems.append(mk("shelf_copy", name,
                               f"trails off on the shelf, where the line is all the reader gets: ...{text[-40:]!r}"))

        # 2. Our filing system on the shelf.
        lowered = text.lower()
        vocab_hits = sorted({w for w in _SHELF_WORD_RE.findall(lowered) if w in INTERNAL_VOCAB})
        taxonomy_hits = sorted(set(_TAXONOMY_TOKEN_RE.findall(text)))
        if vocab_hits or taxonomy_hits:
            problems.append(mk("shelf_copy", name,
                               f"uses our internal vocabulary, not the reader's: "
                               f"{', '.join(vocab_hits + taxonomy_hits)} in {text!r}"))

        # 3. An initialism the reader has never met AND THE PAGE never introduces.
        #
        #    Scope is the whole shelf, not this line. The buyer reads the title, the
        #    headline, the subhead and the card line at once, so a term the title spells out
        #    has been introduced by the time the card line uses it. Grading each field alone
        #    refused exactly that: `38029727242c23c9` titled itself "Cybersecurity Maturity
        #    Model Certification (CMMC) Level 2 evidence packs" — the expansion the rule asks
        #    for, in the field with the least room for it — and was then blocked because its
        #    card line said "CMMC Level 2 evidence binders". The only copy that satisfied the
        #    per-field rule spelled the term out four times on one page.
        unknown = unexplained_initialisms(text, context=" \n".join(graded.values()))
        if unknown:
            problems.append(mk("shelf_copy", name,
                               f"unexplained initialism(s) {', '.join(unknown)} — spell it out in full; "
                               f"the reader has never heard of it: {text!r}"))

        # 4. Written to the wrong reader.
        second = _SECOND_PERSON_RE.search(text)
        if second:
            problems.append(mk("shelf_copy", name,
                               f"second person on the shelf: {second.group(0)!r} — these lines describe "
                               f"the business in the third person, and copy written to the service's "
                               f"end customer is aimed at nobody who can buy: {text!r}"))

        # 5. Opens on a pronoun with nothing behind it (see `_BARE_OPENER_RE`).
        opener = _BARE_OPENER_RE.match(text)
        if opener:
            problems.append(mk("shelf_copy", name,
                               f"opens on {opener.group(1)!r}, a word that points back at a sentence the "
                               f"reader has not read — name the thing first ('A tool for …', 'A fixed-fee "
                               f"service that …'): {text!r}"))

        # 6. Trade shorthand, and the residue. Both advisory under either setting.
        shorthand = sorted({w for w in _SHELF_WORD_RE.findall(lowered) if w in TRADE_SHORTHAND})
        if shorthand:
            problems.append(_warn("shelf_copy", name,
                                  f"trade shorthand {', '.join(shorthand)} — give the plain description "
                                  f"first, then the term: {text!r}"))
        # The residue, OFF unless a reviewer asks for it. `title` is exempt under either
        # setting, and that is not a concession to the false-positive rate:
        # `prompts/retitle.md` requires a noun phrase there ("write a noun phrase that
        # names the trade the way a professional would say it"), so a title with no finite
        # verb is the declared shape. It stays off by default because `lint_pack`'s receipt
        # is asserted empty for a clean pack (`test_lint_pack_clean_is_ok_and_json_
        # serializable`), and a check that cannot be complete has no business spending that
        # contract. The copy-review sweep turns it on; the publish path does not.
        if (report_residue and name != "title"
                and not any(w in _FINITE_VERBS for w in _SHELF_WORD_RE.findall(lowered))):
            problems.append(_warn("shelf_copy", name,
                                  f"reads as a fragment, with no finite verb — a short line is still a "
                                  f"sentence: {text!r}"))

        # 6. A bare pronoun opener. The title is not a sentence the line can continue from,
        #    so a shelf line that starts "It takes ..." spends its first two words pointing
        #    at nothing. `title` is exempt: it is a noun phrase by contract
        #    (`prompts/retitle.md`), so it cannot open on a pronoun-plus-verb anyway.
        if name != "title":
            opener_words = _SHELF_WORD_RE.findall(lowered)
            if (len(opener_words) >= 2
                    and opener_words[0] in _BARE_PRONOUN_OPENERS
                    and opener_words[1] in _FINITE_VERBS):
                # WORDED TO AVOID "opens on", and that is load-bearing rather than stylistic.
                # Check 5 above (`_BARE_OPENER_RE`) and this check were added independently on
                # 2026-08-16 — one on this branch, one on main — for the same rule, and both
                # phrased their finding "opens on ...". Every caller that filters findings does
                # so BY SUBSTRING (`tools/sweep_shelf_copy.py:102`,
                # `tools/retitle_catalogue.py:223`, and the tests), so a line that trips both
                # was reported twice under one name and
                # `test_it_errors_under_the_actuator_and_warns_without_it` counted two errors
                # where it asserts one.
                #
                # Neither check can simply be deleted: check 5 catches "We handle ..." (a line
                # the founder rejected, and `handle` is a bare infinitive absent from
                # `_FINITE_VERBS` by design), while this one is the only check that stays quiet
                # on "This service reads ..." and exempts `title` — both pinned by
                # `tests/unit/test_shelf_copy.py:275-292`. Distinct wording keeps both findings
                # and gives each filter exactly one thing to match.
                problems.append(mk("shelf_copy", name,
                                   f"starts on the bare pronoun {opener_words[0]!r}, which has no "
                                   f"antecedent when the line is read beside the title rather than "
                                   f"after it; name the subject: {text!r}"))

    # 7. The same line twice. The shelf shows title and card line together and the pack page
    #    shows title and headline together, so a repeat spends the page's most valuable line
    #    saying nothing new. 13 of 48 live packs repeated their title as their headline.
    #
    #    THIS ONE NEVER BLOCKS, whatever `block` says. Founder decision 2026-08-17: "the
    #    linter is wrong clearly". A repeated line is worth less than a fresh one; it is not
    #    a reason to refuse to sell a pack whose evidence, artifacts and price are all sound.
    #    The other six rules grade a line that is WRONG — cut off mid-clause, addressed to
    #    the wrong reader, carrying an initialism the buyer has never seen. This one grades a
    #    line that is merely redundant, and redundancy is a preference.
    #
    #    We were also the ones writing the duplicate. `pack_floors.py:258` fills a missing
    #    listing with `headline = title` and `subhead = one_liner`, so when marketing
    #    generation failed, our own fallback produced copy our own gate then refused. The
    #    daemon's guardrail (`run._shelf_copy_breaches`) counts an error as a failed attempt,
    #    so each such pack burned MAX_GEN_ATTEMPTS of generation and an escalation to the
    #    expensive chain before landing UNLISTED anyway. Measured on the lint receipts of
    #    2026-08-17: 7 of the 32 blocked packs carried this error, 2 of them carried nothing
    #    else. Those two list the moment it stops blocking.
    #
    #    It stays REPORTED at warning, because `tools/sweep_shelf_copy.py` uses it to find
    #    copy worth rewriting. Reporting it and acting on it are different decisions.
    keys: Dict[str, str] = {}
    ordered = sorted(graded.items(),
                     key=lambda kv: (_SHELF_DEDUP_ORDER.index(kv[0])
                                     if kv[0] in _SHELF_DEDUP_ORDER
                                     else len(_SHELF_DEDUP_ORDER), kv[0]))
    for name, raw in ordered:
        k = _dedup_key(raw)
        if not k:
            continue
        if k in keys:
            problems.append(_warn("shelf_copy", name,
                                  f"repeats `{keys[k]}` verbatim; the reader learns nothing new: {raw.strip()!r}"))
        else:
            keys[k] = name
    return problems


# ---------------------------------------------------------------------------
# Title claims — the descriptor may only restate what the pack already says
# ---------------------------------------------------------------------------
#
# Why this is a function and not a line in a prompt. `prompts/retitle.md` carries a TRUTH
# RULE telling the model the descriptor may not out-claim the source. A prompt instruction
# is not a guarantee: it is a request, evaluated by the same process that produces the
# error. On a storefront whose whole premise is source-or-die, "the reviewer will spot it"
# is not a control either — it asks a human to diff two paragraphs 48 times and be right
# every time. So the dangerous classes are checked mechanically here, and the residue that
# cannot be checked mechanically is NAMED for the reviewer instead of left for them to find.
#
# Two tiers, deliberately:
#   HARD (`check: "title_claim"`) — a figure, a guarantee, a timescale, a place or an
#     institution that appears nowhere in the pack's own copy. These are not paraphrase
#     under any reading; they are new facts, and a new fact in a title is unsourced.
#   SOFT (`check: "title_new_word"`) — content words absent from the source. Most are fair
#     paraphrase ("chases" for "pursues"); some are a quiet narrowing of the audience
#     ("creatives" where the pack said "freelancers"). Machines cannot tell those apart, so
#     this tier reports the WORDS rather than ruling on them: the reviewer reads three words
#     instead of two paragraphs.

#: Absolutes and guarantees. Each is legal if the pack's own copy already says it — the rule
#: is "no NEW claim", not "no strong words", so a supported "every" passes untouched.
_CLAIM_ABSOLUTES = frozenset("""
guaranteed guarantee guarantees ensures ensure ensuring never always certain certainly
promise promises promised proven risk-free riskfree instantly instant immediately
automatically fully entirely completely every all unlimited
""".split())

#: Timescales that carry no digit, so the figure rule below cannot catch them.
_CLAIM_TIME_PHRASES = ("same-day", "same day", "overnight", "next-day", "next day",
                       "within days", "within hours", "in minutes", "in seconds",
                       "real-time", "real time", "24/7", "round the clock")

#: Nation-level synonyms may be satisfied by the row's DECLARED market rather than its prose:
#: a pack whose `market` is `uk` is a UK pack whether or not the word appears in its one-liner.
_GEO_MARKET_SYNONYM = {
    "uk": "uk", "u.k.": "uk", "britain": "uk", "british": "uk", "gb": "uk",
    "us": "us", "u.s.": "us", "usa": "us", "america": "us", "american": "us",
    "eu": "eu", "europe": "eu", "european": "eu",
}

#: Sub-national places and named institutions get NO market credit. "us" -> "Texas" is a
#: narrowing to one state and "an NHS claim" is a specific institutional claim; both are new
#: facts unless the pack's own copy already made them.
_GEO_PLACES = frozenset("""
england english scotland scottish wales welsh ireland irish london texas california
florida canada canadian australia australian germany german france french spain spanish
""".split())
_INSTITUTIONS = frozenset("""
hmrc nhs irs dwp fca sec ftc ofsted ofgem ofcom hse osha eeoc medicare medicaid
""".split())

_CLAIM_STOPWORDS = frozenset("""
a an the and or of for to in on at by with from that this your you their they them its it
as into out up off so if when who what which not no more most than then there here about
is are was were be been being do does did done have has had will would can could
""".split())

_TOKEN_RE = re.compile(r"\d+|[A-Za-z][A-Za-z'’.\-]*")


def _stem(word: str) -> str:
    """Crude suffix stripping, enough to see `charging` behind `charges`.

    Deliberately not a real stemmer: a false MATCH here only means a word is treated as
    supported and therefore not reported, which is the safe direction for the soft tier and
    irrelevant to the hard tier (whose vocabularies are closed sets of exact words).
    """
    w = re.sub(r"[^a-z0-9]", "", word.lower())
    for suf, repl in (("ings", ""), ("ing", ""), ("ies", "y"), ("ied", "y"),
                      ("ers", ""), ("es", ""), ("ed", ""), ("er", ""), ("s", ""),
                      # `charge` -> `charg`, so it meets `charging` -> `charg`. Without this
                      # the pair reads as unsupported and the soft tier reports a word the
                      # source plainly contains — a false report per pack is how a reviewer
                      # learns to skip the list.
                      ("e", "")):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[: -len(suf)] + repl
    return w


def check_claims(text: str, sources: Iterable[str], *, market: str = "",
                 block: bool = False, where: str = "title") -> List[Problem]:
    """Engine-authored copy may restate the pack's own description; it may not add to it.

    Written for the title descriptor and reused verbatim for the headline and the card line,
    because they are the same question about the same pack. A second implementation for
    "the same rule, but for the headline" is how two rules come to disagree, and the one a
    buyer sees is then whichever ran last.

    `sources` is the pack's own description and structured fields. It should NOT include the
    lines being rewritten: copy that is itself under repair cannot be the evidence that the
    repair is truthful — 13 live headlines are verbatim copies of their title, so a title
    checked against its own headline would support itself.

    `market` is the row's declared market, which is what makes "UK" checkable as data rather
    than as prose.
    """
    hard = _err if block else _warn

    blob = " ".join(str(s or "") for s in (sources or [])).lower()
    blob_stems = {_stem(t) for t in _TOKEN_RE.findall(blob)}
    mkt = (market or "").strip().lower()
    low = text.lower()
    problems: List[Problem] = []
    seen: set = set()

    def unsupported(tok: str) -> bool:
        return tok.lower() not in blob and _stem(tok) not in blob_stems

    def report(tok: str, detail: str) -> None:
        if tok.lower() in seen:
            return
        seen.add(tok.lower())
        problems.append(hard("title_claim", where, detail))

    # A DIGIT INSIDE A WORD IS NOT A FIGURE. `_TOKEN_RE` splits on the alpha/digit boundary,
    # so "3PLs" arrived here as the number 3, and the receipt on `19aaf66a4e9f7778` told the
    # operator that "Savannah port container dwell forecasts for 3PLs" states a figure its
    # copy does not: '3'. Trade terms are built that way — 3PL, 4PL, 2FA, K8s — and the pack
    # was blocked over a claim nobody made. The guards below require the run to stand alone.
    for num in re.findall(r"(?<![A-Za-z0-9])\d[\d,.]*%?(?![A-Za-z0-9])", text):
        bare = num.strip(".,")
        if bare and bare not in blob:
            report(bare, f"states a figure the pack's own copy does not: {bare!r}")

    for phrase in _CLAIM_TIME_PHRASES:
        if phrase in low and phrase not in blob:
            report(phrase, f"promises a timescale the pack's own copy does not: {phrase!r}")

    for tok in _TOKEN_RE.findall(low):
        if tok in _CLAIM_ABSOLUTES and unsupported(tok):
            report(tok, f"makes an absolute claim the pack's own copy does not: {tok!r}")
        code = _GEO_MARKET_SYNONYM.get(tok)
        if code and code == mkt:
            # Cleared BY DATA, and recorded as cleared so the proper-noun rule below does not
            # re-report it: "UK" is a capitalised token that appears in no prose, which is
            # exactly what that rule looks for. One token, one verdict, or a true statement
            # gets flagged and the check earns its way into being ignored.
            seen.add(tok)
        elif code and unsupported(tok):
            report(tok, f"names a market ({tok!r}) that is neither the pack's declared "
                        f"market ({mkt or 'unset'!r}) nor anywhere in its copy")
        if (tok in _GEO_PLACES or tok in _INSTITUTIONS) and unsupported(tok):
            report(tok, f"names {tok!r}, which appears nowhere in the pack's own copy — a "
                        f"place or institution is a specific claim, and gets no market credit")

    # The proper-noun rule INFERS "this is a name" from a capital letter, and that inference
    # is only valid in a string that is otherwise plain prose — which the declared format is.
    # In a Title Case legacy title every word is capitalised, so the rule reads
    # "The Primary Carer's DLA Child Claim Engine" as six unsourced claims. Measured over the
    # 48 live rows before this guard: 7 rows flagged, 5 of them purely for being title-cased.
    # A check that fires on a true statement is a check that gets switched off.
    words = [t for t in _TOKEN_RE.findall(text) if t.isalpha() and len(t) >= 3]
    capped = sum(1 for t in words if t[:1].isupper())
    if words and capped / len(words) < 0.6:
        for m in _TOKEN_RE.finditer(text):
            tok = m.group(0)
            # The first word of a sentence is capitalised by grammar, not because it is a
            # name. Measured on the 48 live rows: this exempts 'See' (x3) and 'Run' (x2),
            # every one of them the opening verb of a headline.
            before = text[: m.start()].rstrip()
            if not before or before[-1] in ".!?":
                continue
            # HALF A WORD IS NOT A PROPER NOUN. Same `_TOKEN_RE` split as the figure rule
            # above: "3PLs" yields the token "PLs", and the receipt on `19aaf66a4e9f7778`
            # told the operator that "PLs" appears nowhere in the pack's copy. It appears
            # nowhere in the TITLE either — no writer can act on that. If the character
            # immediately before the token is alphanumeric, the token is a fragment.
            if m.start() and text[m.start() - 1].isalnum():
                continue
            if tok[:1].isupper() and unsupported(tok):
                report(tok, f"introduces the proper noun {tok!r}, which appears nowhere in "
                            f"the pack's own copy")

    new = sorted({tok for tok in _TOKEN_RE.findall(low)
                  if tok.isalpha() and len(tok) >= 4 and tok not in _CLAIM_STOPWORDS
                  and tok.lower() not in seen and unsupported(tok)})
    if new:
        problems.append(_warn(
            "title_new_word", where,
            "words that are not in the pack's own copy — fair paraphrase, or a new claim? "
            f"read them: {', '.join(new)}"))
    return problems


def check_title_claims(title: str, sources: Iterable[str], *, market: str = "",
                       block: bool = False) -> List[Problem]:
    """`check_claims` applied to the WHOLE title.

    It used to read the descriptor half only, and return [] when there was no separator: a
    title with no descriptor was already reported by `check_title`, and adjudicating the
    claims of a string that is not in the format reported one defect twice.

    That exemption became a hole on 2026-08-13, when the format stopped carrying a name.
    Under `<what the business does> for <who pays>` there is no separator to find, so the
    truth rule — the reason this storefront can say source-or-die — was silently inert on
    every correctly-formatted title. The half it used to skip was a coined product name,
    which no longer appears in a title at all, so there is nothing left worth exempting and
    the whole string is judged.
    """
    t = " ".join((title or "").split())
    if not t:
        return []
    return check_claims(t, sources, market=market, block=block, where="title")


# ---------------------------------------------------------------------------
# Citation URLs resolvable (bounded, cached — the one networked check)
# ---------------------------------------------------------------------------

_DEAD_STATUSES = frozenset({404, 410})
_URL_CACHE_TTL_S = 7 * 86400

#: "Come back later", not an answer about the resource. Only the memento probe treats these
#: specially: a live citation that 503s is already handled (anything not in `_DEAD_STATUSES`
#: passes), while a memento that 503s was silently failing the pack.
_THROTTLED_STATUSES = frozenset({429, 503})

#: Retry ladder for a throttled memento probe. Short on purpose — this runs inside a publish.
_MEMENTO_BACKOFF_S = (3.0, 9.0)

#: Wayback PLAYBACK reassembles a stored page, so it is seconds slower than probing a live URL.
#: The citation probe's 5s default was timing mementos out and reading that as "not servable".
_MEMENTO_TIMEOUT_S = 20.0

#: Bumped whenever the probe's VERDICT LOGIC changes, and mixed into the cache key. Without
#: it, the 7-day TTL would keep serving verdicts a fixed probe would no longer reach:
#: `store/lint_url_cache.json` held `{'status': 404}` for a page that answers GET with 200,
#: so the fix below would have looked inert for a week on exactly the packs it unblocks.
_PROBE_LOGIC_VERSION = 2


# A real browser UA, matching retrieval._RESOLVE_UA. Without one, Cloudflare and friends
# 403 the probe on sight: 20 of the 21 citation warnings across the 2026-08-08 packs were
# this artifact, including en.wikipedia.org, which serves 200 to a browser GET. Those were
# only warnings, so they never blocked a pack — they just made the report unreadable.
_PROBE_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
             "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def _probe_once(url: str, timeout_s: float, *, method: str) -> Tuple[Optional[int], str]:
    """One request. (status, note); status None = could not determine (network, not the URL)."""
    headers = {"User-Agent": _PROBE_UA}
    try:
        if method == "head":
            resp = requests.head(url, timeout=timeout_s, allow_redirects=True, headers=headers)
        else:
            resp = requests.get(url, timeout=timeout_s, allow_redirects=True, stream=True,
                                headers=headers)
            resp.close()
        return resp.status_code, ""
    except requests.RequestException as exc:
        return None, type(exc).__name__


def _probe_url(url: str, timeout_s: float) -> Tuple[Optional[int], str]:
    """(status, note). status None = could not determine (network, not the citation).

    Never condemns a citation on the strength of a HEAD. The old code retried with GET only on
    405/501 ("HEAD not allowed != page gone"), but a server can refuse HEAD with a 404, and 404
    is in `_DEAD_STATUSES`. Proven 2026-08-09 with this module's own UA and requests call:
    `https://www.mcneilsafetyconsulting.com/services/osha-violation-defense` answers HEAD 404
    and GET 200, and it was already cached dead for 7 days.

    A dead GET then gets one more chance on the slash-toggled variant, because our own
    extractor is capable of storing `…/wiki/Life_settlement/` for a page that only exists
    without the slash. If that variant is alive the note names it, and `check_urls` downgrades
    to a warning: the SOURCE is fine, the stored string is ours to repair, and blocking a pack
    for our own defect is the false positive this whole path exists to avoid.
    """
    status, note = _probe_once(url, timeout_s, method="head")
    if status is None or status not in _DEAD_STATUSES:
        return status, note

    get_status, get_note = _probe_once(url, timeout_s, method="get")
    if get_status is not None and get_status not in _DEAD_STATUSES:
        return get_status, f"HEAD said {status}, GET said {get_status}"
    if get_status is None:
        # The GET could not be completed, so "dead" is unproven. Fall back to unreachable
        # rather than trusting the HEAD we just refused to trust.
        return None, get_note

    alt = url[:-1] if url.endswith("/") else url + "/"
    alt_status, _ = _probe_once(alt, timeout_s, method="get")
    if alt_status is not None and alt_status not in _DEAD_STATUSES and alt_status < 400:
        return get_status, f"{_ALT_ALIVE_NOTE}{alt}"
    return get_status, get_note


#: Sentinel prefix in the probe note meaning "the citation resolves at this other URL".
_ALT_ALIVE_NOTE = "resolves without/with trailing slash: "


def _memento_alive(memento: str, cache: Dict[str, Any], now: float, timeout_s: float) -> bool:
    """Is this Wayback capture actually servable right now?

    Deliberately strict: only a positively-confirmed live memento downgrades a dead citation,
    so an unreachable Internet Archive leaves the error standing. That asymmetry is on
    purpose. Everywhere else in this module an unproven state resolves in the citation's
    favour, because the alternative is condemning a source on our own outage. Here the
    unproven state would EXCUSE a citation the buyer cannot follow, which is the more
    expensive error on a source-or-die storefront.
    """
    key = f"v{_PROBE_LOGIC_VERSION}|memento|{memento}"
    entry = cache.get(key)
    if entry and now - entry.get("ts", 0) < _URL_CACHE_TTL_S:
        return bool(entry.get("status") is not None and entry["status"] < 400)

    # Neither a throttle nor a timeout is a probe RESULT; both are the archive declining to
    # answer, and both were reading as "not alive". Measured 2026-08-13 on
    # `5e8f3b69369be3a8`: replaying the same lint with a longer budget turned its one blocking
    # error into a warning and the pack lints clean, so the escape hatch was being shut on a
    # pack whose evidence WAS archived. Two causes, both here — web.archive.org PLAYBACK is far
    # slower than the citation probe this timeout was sized for (a live 404 answers instantly),
    # and it 503s a caller that has just walked its index.
    #
    # Neither outcome is ever cached: a 7-day entry would pin our own throttling onto the
    # memento long after the archive recovered, which is the same defect this module has now
    # found three times.
    budget = max(timeout_s, _MEMENTO_TIMEOUT_S)
    for backoff in (*_MEMENTO_BACKOFF_S, None):
        status, note = _probe_url(memento, budget)
        if status is not None and status not in _THROTTLED_STATUSES:
            cache[key] = {"status": status, "note": note, "ts": now}
            return status < 400
        if backoff is None:
            break
        time.sleep(backoff)
    return False        # unproven, so the citation's error stands — see the docstring


def check_urls(texts: Dict[str, str], *, cache_path: Optional[Path] = None,
               timeout_s: float = 5.0, max_urls: int = 20,
               archived: Optional[Mapping[str, str]] = None) -> Tuple[List[Problem], int]:
    """Probe up to `max_urls` distinct URLs across `texts` ({where: markdown}).

    Definitive 404/410 → error (the citation is dead and a buyer will find out).
    Any other failure → warning (our outage or their rate limit is not the citation's
    death — mirrors the engine-wide rule that an exception is never evidence).

    `archived` maps citation URL → Wayback memento (`models.Source.archived_url`). A dead
    citation that HAS a working memento is downgraded to a warning, because the thing this
    check exists to protect is the buyer's ability to verify a claim, and that ability
    survives: the passage text ships with the pack and the memento shows the page it came
    from. Blocking such a pack withholds evidence that is still checkable.

    The memento is PROBED before it earns that downgrade. Trusting a stored `archived_url`
    without asking would just invert the defect this module keeps finding — manufacturing
    "the buyer can verify this" from a field nobody checked.
    """
    cache: Dict[str, Any] = {}
    if cache_path is not None:
        try:
            cache = json.loads(Path(cache_path).read_text())
        except (OSError, ValueError):
            cache = {}

    seen: List[Tuple[str, str]] = []
    seen_urls = set()
    for where, text in texts.items():
        for url in extract_urls(text or ""):
            if url not in seen_urls:
                seen_urls.add(url)
                seen.append((where, url))

    problems: List[Problem] = []
    now = time.time()
    checked = 0
    for where, url in seen[:max_urls]:
        key = f"v{_PROBE_LOGIC_VERSION}|{url}"
        entry = cache.get(key)
        if entry and now - entry.get("ts", 0) < _URL_CACHE_TTL_S:
            status, note = entry.get("status"), entry.get("note", "cached")
        else:
            status, note = _probe_url(url, timeout_s)
            cache[key] = {"status": status, "note": note, "ts": now}
            checked += 1
        if status in _DEAD_STATUSES and note.startswith(_ALT_ALIVE_NOTE):
            # OUR stored string is wrong, not the source. Warn (naming the URL that works) so
            # the pack is not stranded by a defect on our side of the line.
            problems.append(_warn(
                "citation_urls", where,
                f"{url} → HTTP {status}, but the source is live — {note}"))
        elif status in _DEAD_STATUSES:
            memento = (archived or {}).get(url) or ""
            if memento and _memento_alive(memento, cache, now, timeout_s):
                # The pointer rotted; the evidence did not. The buyer still gets the quoted
                # passage in the QA report and a capture of the page it came from, so this
                # is a degraded convenience, not an unverifiable claim.
                problems.append(_warn(
                    "citation_urls", where,
                    f"{url} → HTTP {status}, archived copy stands in: {memento}"))
            else:
                problems.append(_err("citation_urls", where, f"{url} → HTTP {status}"))
        elif status is not None and status >= 400:
            problems.append(_warn("citation_urls", where, f"{url} → HTTP {status}"))
        elif status is None:
            problems.append(_warn("citation_urls", where, f"{url} unreachable ({note})"))

    if cache_path is not None and checked:
        try:
            Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
            Path(cache_path).write_text(json.dumps(cache))
        except OSError:
            pass  # cache is an optimisation; never let it block a lint verdict
    return problems, len(seen[:max_urls])


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------

def lint_pack(*, artifacts: Dict[str, str], listing_copy: str,
              listing_texts: Dict[str, Tuple[str, str]], market: str,
              marketing: Optional[Iterable[Mapping[str, Any]]] = None,
              truncation_caps: Optional[Dict[str, int]] = None,
              check_urls_enabled: bool = False,
              url_cache_path: Optional[Path] = None,
              url_timeout_s: float = 5.0, max_urls: int = 20,
              house_fields: Optional[Dict[str, str]] = None,
              archived_urls: Optional[Mapping[str, str]] = None,
              title_max_chars: int = TITLE_MAX_CHARS,
              title_block_on_breach: bool = TITLE_BLOCK_ON_BREACH_DEFAULT,
              shelf_copy_block_on_breach: bool = False,
              grammar_enabled: bool = False,
              max_grammar_defects_per_1k: float = 0.0,
              pack_sections: Optional[Mapping[str, str]] = None,
              repetition_block: bool = False,
              register_block: bool = False,
              max_register_per_1k: float = 0.0,
              max_long_sentence_rate: float = 0.0,
              max_clause_load_rate: float = 0.0,
              house_block_predictions: bool = False,
              house_block_quotes: bool = False,
              max_four_item_list_rate: float = 0.0,
              max_unsourced_figure_rate: float = 0.0,
              engine_leak_block: bool = False,
              max_engine_leak_per_1k: float = 0.0,
              human_register_block: bool = False) -> Dict[str, Any]:
    """Run every lint check; return the machine-readable report.

    `report["ok"]` is False iff any problem has severity "error" — that is the half the
    publish gate ANDs into `is_listed`. Warnings ride along in the report only.

    `archived_urls` maps citation URL -> Wayback memento, so a dead citation whose evidence
    is still reachable warns instead of blocking. Callers build it from `Source.archived_url`.

    `pack_sections` is the assembled read — buyer-visible section title -> markdown, in
    reading order — which is a DIFFERENT corpus from `artifacts` and the reason this
    parameter exists. `artifacts` holds the four model-written documents; the pack a buyer
    opens has fourteen sections, five of them rendered deterministically after those four,
    and until 2026-08-15 nothing in this module had ever seen them. Only `check_repetition`
    reads it, because repetition is the one defect that is invisible section by section and
    exists only in the assembly.

    `house_fields` carries engine-authored single-line copy that is NOT already in
    `listing_texts` — `title` above all. Its absence was the second half of the 2026-08-08
    dash defect: the field skipped the normaliser AND was never handed to the linter, so
    nothing on the publish path could see it. Callers pass every buyer-visible line.
    """
    fin = (artifacts or {}).get("financial_model", "") or ""
    problems: List[Problem] = []
    problems += check_currency(
        fin, listing_copy, market,
        # The pack's own artifacts are the evidence that it prices in the home currency.
        # See the listing_page block in `check_currency`.
        listing_home=" ".join(v for v in (artifacts or {}).values() if isinstance(v, str)))
    problems += check_arithmetic(fin)
    problems += check_sections(fin)
    problems += check_placeholders(artifacts or {})
    # The marketing pieces are graded from the LIST, not from the rendered
    # Marketing_Assets.md: the renderer stamps the heading, so grading the rendered file
    # would ask each piece to agree with a label this engine wrote over it.
    problems += check_marketing(marketing)
    problems += check_truncation(listing_texts or {}, truncation_caps)
    # Graded on the ASSEMBLY, not on any one document, which is why it takes its own corpus
    # and why it had none until 2026-08-15: `check_repetition` existed, was commented as live
    # in four renderers, and had zero callers. A sentence printed once in each of two sections
    # is correct in both files and a defect in the pack.
    problems += check_repetition(pack_sections, block=repetition_block)

    # --- copy quality -----------------------------------------------------------------
    # Engine-authored prose only. Quoted third-party passages are never linted: a cited
    # source may contain any dash or any identifier, and "correcting" it would falsify the
    # citation on a source-or-die storefront.
    house = dict(house_fields or {})
    for _name, _pair in (listing_texts or {}).items():
        _rendered = _pair[0] if isinstance(_pair, (tuple, list)) and _pair else ""
        if _rendered:
            house.setdefault(_name, _rendered)
    problems += check_house_dashes(house)

    # Same corpus as the dash check, graded as writing rather than as characters. It takes
    # the whole of `house` and selects `SHELF_FIELDS` itself, so a caller that starts
    # passing another short line gets it graded without a second wiring change — which is
    # how `cardLine`, the field the founder's 2026-08-13 complaint was actually about, came
    # to be linted by nothing at all.
    problems += check_shelf_copy(house, block=shelf_copy_block_on_breach)

    # The title is read from `house` rather than taking its own parameter: it is already
    # the field house_fields exists to carry, and a second entry point is how a caller ends
    # up linting a title the publish path never renders.
    if "title" in house:
        problems += check_title(house["title"], max_chars=title_max_chars,
                                block=title_block_on_breach)

    # `is_prose_artifact` is the SINGLE definition of what may be graded as writing; see
    # copy_lint.DATA_ARTIFACT_SUFFIXES for the pack this got wrong. Selecting the corpus by a
    # local `.json` test is what let .csv and .svg through to both copy checks at once.
    prose = {k: v for k, v in (artifacts or {}).items()
             if isinstance(v, str) and is_prose_artifact(k, v)}

    # THE TITLE'S CLAIMS ARE GRADED AGAINST THE PACK, NOT AGAINST THE SHELF CARD. Same
    # actuator as `check_title` above, because "the title is bad" is one question with two
    # halves: it can be the wrong SHAPE, or the right shape carrying a claim the pack never
    # made. It runs down here rather than beside its twin because it needs `prose`, and that
    # is the whole fix.
    #
    # Until 2026-08-17 the sources were `house` minus the title — the card line and the
    # listing texts, about 40 words. The rule's own docstring says "the pack's own
    # description and structured fields", and the shelf card is not that. So a title naming
    # a thing too specific to fit on a card was reported as an unsourced claim about a pack
    # that discusses it at length. Measured over the 9 stranded packs this blocked: 14 of the
    # 14 flagged tokens appear in the pack's own copy — House, Bill, Department, Information,
    # Resources, ISVs, DevOps, Spine, Markets, Competition, GA, CTOs and the figure 4. Every
    # error was false, and they could not be switched off separately because both halves
    # share `title_block_on_breach`.
    #
    # EVERY artifact counts here, not just `prose`. `is_prose_artifact` exists to choose what
    # may be graded AS WRITING — dashes, register, repetition — and that is a different
    # question from "does this pack mention this term at all", which a scorecard row or a
    # chart label answers perfectly well. Restricting the sources to prose left three of the
    # nine still blocked (HB, ISVs, DevOps), and all three appear in `scorecard.json` and
    # `scorecard_radar.svg`. Checked before trusting them: neither file contains the title
    # verbatim on either pack, so this is the pack's own evidence and not the title
    # supporting itself.
    #
    # The pack is never itself under repair, which is what makes it evidence in a way the
    # sibling shelf lines are not: 13 live headlines are verbatim copies of their title, and
    # a title checked against its own headline supports itself. The title is still excluded
    # from its own sources for that reason.
    if "title" in house:
        _t = " ".join(str(house["title"]).split()).casefold()
        problems += check_title_claims(
            house["title"],
            [v for v in (artifacts or {}).values() if isinstance(v, str)]
            # A SHELF LINE THAT COPIES THE TITLE IS NOT EVIDENCE FOR THE TITLE. Excluding
            # `title` by key was never enough: 13 live headlines are verbatim copies of
            # their own title, and `cardLine` can be too, so the title arrived back in its
            # own sources under another name and supported itself. Only exact self-copies
            # are dropped, so a card line that genuinely restates the pack still counts.
            + [v for k, v in house.items()
               if k != "title" and " ".join(str(v).split()).casefold() != _t],
            market=market, block=title_block_on_breach)

    problems += check_identifier_leak({**prose, **house})

    # --- the house writing spec -------------------------------------------------------
    # `docs/HOUSE_WRITING_SPEC.md`, on the corpus the buyer actually reads. Both checks run
    # unconditionally and both are ACTUATED by thresholds that default to off, which is a
    # deliberate choice over an `enabled` flag: `check_register` shipped fully tested in
    # 2026-08 with a rate actuator, no caller, and nothing measuring it, so nobody could ever
    # say what threshold to set. A check that always measures accrues the baseline that earns
    # its own threshold; a check behind a default-off flag accrues nothing.
    #
    # Graded on `pack_sections` when the caller has assembled the read, because that is what
    # a buyer opens, and on the prose artifacts otherwise so a caller that predates
    # `pack_sections` is still graded rather than silently exempt.
    style_corpus: Mapping[str, str] = pack_sections or prose
    register_metrics_ = register_metrics(style_corpus)
    problems += check_register(
        style_corpus, block=register_block, max_per_1k=max_register_per_1k,
        long_sentence_max_rate=max_long_sentence_rate,
        clause_load_max_rate=max_clause_load_rate,
        human_register_block=human_register_block, metrics=register_metrics_)
    # Same corpus, third question: is our own filing system in the buyer's prose? Nothing
    # asked it before 2026-08-15 — `INTERNAL_VOCAB` is scoped to the six shelf lines, so a
    # financial model could print `value_durability 0.438` and every check here passed.
    problems += check_engine_leak(style_corpus, block=engine_leak_block,
                                  max_per_1k=max_engine_leak_per_1k)

    house_metrics = house_style_metrics(style_corpus)
    problems += check_house_style(
        style_corpus, metrics=house_metrics,
        block_predictions=house_block_predictions, block_quotes=house_block_quotes,
        # R1 has ONE actuator, and it is `check_register`'s at 25 words. `house_style`
        # measures the spec's own 28-word ceiling and never blocks on it, so a pack cannot
        # be failed twice for one sentence under two limits, and so the report can still say
        # what the rate looks like at the number the spec actually writes down.
        max_over_28_rate=0.0,
        max_four_item_list_rate=max_four_item_list_rate,
        max_unsourced_figure_rate=max_unsourced_figure_rate)

    grammar_rate: Optional[float] = None
    if grammar_enabled:
        gp = check_grammar(prose, max_per_1k=max_grammar_defects_per_1k)
        problems += gp
        for p in gp:
            m = re.search(r"= ([\d.]+) per 1k", p.get("detail", ""))
            if m:
                grammar_rate = float(m.group(1))

    urls_seen = 0
    if check_urls_enabled:
        url_texts = {name: text for name, text in (artifacts or {}).items() if text}
        url_texts["listing_page"] = listing_copy or ""
        url_problems, urls_seen = check_urls(
            url_texts, cache_path=url_cache_path, timeout_s=url_timeout_s, max_urls=max_urls,
            archived=archived_urls)
        problems += url_problems

    return {
        "ok": not any(p["severity"] == "error" for p in problems),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "ruleset": RULESET_VERSION,
        "market": market,
        "urls_checked": urls_seen,
        # Recorded pass or fail so the receipt accrues a real baseline while the actuator
        # is still off — the number you turn `max_grammar_defects_per_1k` on with should be
        # one you have seen on live packs, not one guessed from a sample.
        "grammar_rate_per_1k": grammar_rate,
        # Same reason as `grammar_rate_per_1k`: the actuator is off, so the receipt is the
        # only thing that can earn it a threshold. Counted from the problems rather than
        # returned by the check so it stays right whether the finding blocked or warned.
        "repetition_findings": sum(1 for p in problems if p.get("check") == "repetition"),
        "sections_graded": len(pack_sections or {}),
        "readability_grade": readability_grades(pack_sections),
        # The house-spec baseline, recorded on every pack whether or not any actuator is on.
        # This is the receipt the LEDGER in docs/HOUSE_WRITING_SPEC.md gets filled from: a
        # threshold is only allowed to be set from a number seen on live packs, and 43.9% of
        # corpus sentences broke R1 on 2026-08-15, so a ceiling switched on today would fail
        # every pack rather than improve one.
        "house_spec": {
            "sentences": house_metrics["sentences"],
            "words": house_metrics["words"],
            "R1_over_25_rate": register_metrics_["long_sentence_rate"],
            "R1_over_28_rate": house_metrics["over_28_rate"],
            "R2_clause_load_rate": register_metrics_["clause_load_rate"],
            "R4_four_item_list_rate": house_metrics["four_item_list_rate"],
            "R5_unsourced_figures": house_metrics["unsourced_figures"],
            "R6_vague_quantities": house_metrics["vague_quantities"],
            "R8_orphan_openers": house_metrics["orphan_openers"],
            "R9_register_per_1k": register_metrics_["register_per_1k"],
            "R10_flat_predictions": house_metrics["flat_predictions"],
            "quotes": house_metrics["quotes"],
            "Q_bad_quotes": house_metrics["bad_quotes"],
        },
        # This pack measured the way 270 human ombudsman decisions were measured, and the
        # armed measures it sits outside the human range on. Recorded on every pack whether
        # or not `human_register_block` is on, for the same reason `house_spec` is: a
        # threshold may only be set from numbers seen on live packs.
        "human_register": {
            "measures": register_metrics_["prose_measures"],
            "outside": register_metrics_["human_register"],
            "error": register_metrics_["human_register_error"],
        },
        "problems": problems,
    }
