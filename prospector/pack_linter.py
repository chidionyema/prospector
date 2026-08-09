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
# Currency consistency (the £/$ defect)
# ---------------------------------------------------------------------------

# The financial model is MOSTLY Python-rendered — but not all of it.
# `artifacts._render_financial_model` appends two model-authored lists at the end, and its
# own source marks them: those lists "are the only FREE TEXT in this artifact — everything
# above is Python formatting a number."
FINANCIAL_MODEL_FREE_TEXT_HEADERS = ("### Key Assumptions", "### Model Weaknesses")


def split_rendered_free_text(fin_text: str) -> Tuple[str, str]:
    """Split a financial model into (Python-rendered head, model-authored tail).

    A missing list is legal output (`if assumptions_list:`), so an artifact with neither
    header is ALL rendered — the fallback has to be "all of it", never "none of it", or the
    strict half of the currency rule would quietly stop applying to the packs it was
    written for.
    """
    text = fin_text or ""
    cuts = [text.index(h) for h in FINANCIAL_MODEL_FREE_TEXT_HEADERS if h in text]
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


def check_currency(fin_text: str, listing_copy: str, market: str) -> List[Problem]:
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
    problems += _quoted_comparable_problems(
        listing_copy, listing_copy, sym, market, "listing_page")
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


_MONTH_RE = re.compile(
    r"\*\*Month (1|12):\*\* [£$]([\d,]+) × ([\d,]+) customers = \*\*[£$]([\d,]+)\*\*")
_GROWTH_RE = re.compile(r"\*\*Growth \(M1→M12\):\*\* ([\d.]+)×")
_GM_RE = re.compile(r"### Gross Margin: \*\*(-?\d+)%\*\* \(COGS: (\d+)% of revenue\)")
_PER_CUST_RE = re.compile(r"\*\*Per customer/month:\*\* [£$]([\d,]+\.\d{2})")
_PAYBACK_CALC_RE = re.compile(
    r"\*\*~([\d.]+) months\*\* \(CAC [£$]([\d,]+) / gross margin [£$]([\d,]+\.\d{2})/month\)")
_CLV_CALC_RE = re.compile(r"~\*\*[£$]([\d,]+)\*\* \(ARPU [£$]([\d,]+) / ([\d.]+)% monthly churn\)")


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

REQUIRED_FIN_SECTIONS = ("## Financial Model", "### Revenue",
                         "### Payback Period", "### LTV:CAC Ratio")


def check_sections(fin_text: str) -> List[Problem]:
    t = (fin_text or "").strip()
    if not t:
        return []  # an empty artifact is validate_pack's finding; don't double-report
    return [
        _err("sections", "financial_model", f"missing required section {s!r}")
        for s in REQUIRED_FIN_SECTIONS if s not in t
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

#: The declared shape: a short name, a comma, then what it does for the buyer.
#: `TITLE_MAX_CHARS` mirrors `CARD_LINE_MAX` (artifacts.py) deliberately — the storefront
#: already produces a 40-60 char line for the same pack and renders it well, so the title
#: has no claim to be 90+.
TITLE_MAX_CHARS = 60

#: The name may be a coined word, an initialism, or a couple of real words. Past that it is
#: not a name, it is a sentence, and the format is not being followed. Deliberately loose:
#: this check exists to catch "no format at all", not to arbitrate good names.
TITLE_NAME_MAX_WORDS = 4
TITLE_NAME_MAX_CHARS = 30

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
                block: bool = False) -> List[Problem]:
    """The pack title must read as `Name, what it does` and fit `max_chars`.

    Why this check exists, and why it is not cosmetic. The title is the ONE string that
    reaches every surface at once — shelf card, pack page H1, `<title>` in search results,
    the OG image on a shared link — and until 2026-08-09 nothing bounded it or shaped it.
    Measured on the 48 live catalogue rows that day: median title 96.5 chars, 2 of 48 inside
    the 40-60 band, 4 rows with no descriptor at all, and four different separators in use
    (`, ` x34, em-dash x7, none x4, en-dash x3). The engine was meanwhile producing a
    correctly-sized `card_line` for 36 of those same packs (min 40, median 52.5, max 60),
    which is the proof that the short form is writable — it just was not being asked for.

    The root cause was a prompt, not a bug: `prompts/generate_system.md` asked for "a short
    name, then a dash, then what it does" and named no length, so the model obliged on both
    counts and `nodash` rewrote the mandated dash to `, ` at publish.

    `block` is the ACTUATOR and defaults off. Every breach is reported either way; with
    `block` false they are warnings, so shipping the check cannot unlist the 46 live packs
    that predate the rule. Turn it on once the catalogue has been retitled — the same
    order `max_grammar_defects_per_1k` was introduced in, for the same reason.
    """
    mk = _err if block else _warn
    t = " ".join((title or "").split())
    if not t:
        return [_err("title", "title", "empty")]

    problems: List[Problem] = []
    if len(t) > max_chars:
        problems.append(mk("title", "title",
                           f"{len(t)} chars exceeds the {max_chars} limit: {t!r}"))

    name, descriptor = split_title(t)
    if not descriptor:
        problems.append(mk(
            "title", "title",
            f"no descriptor: expected 'Name, what it does', got {t!r}"))
        return problems

    words = name.split()
    if len(words) > TITLE_NAME_MAX_WORDS or len(name) > TITLE_NAME_MAX_CHARS:
        problems.append(mk(
            "title", "title",
            f"the part before the separator is a sentence, not a name "
            f"({len(words)} words, {len(name)} chars): {name!r}"))
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

    for num in re.findall(r"\d[\d,.]*%?", text):
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
    """`check_claims` applied to the descriptor half of a title.

    Returns [] for a title with no descriptor: `check_title` has already reported that the
    format was not followed, and adjudicating the claims of a string that is not in the
    format would report the same defect twice under a second name.
    """
    _, descriptor = split_title(" ".join((title or "").split()))
    if not descriptor:
        return []
    return check_claims(descriptor, sources, market=market, block=block, where="title")


# ---------------------------------------------------------------------------
# Citation URLs resolvable (bounded, cached — the one networked check)
# ---------------------------------------------------------------------------

_DEAD_STATUSES = frozenset({404, 410})
_URL_CACHE_TTL_S = 7 * 86400

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
        status = entry.get("status")
    else:
        status, note = _probe_url(memento, timeout_s)
        cache[key] = {"status": status, "note": note, "ts": now}
    return status is not None and status < 400


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
              truncation_caps: Optional[Dict[str, int]] = None,
              check_urls_enabled: bool = False,
              url_cache_path: Optional[Path] = None,
              url_timeout_s: float = 5.0, max_urls: int = 20,
              house_fields: Optional[Dict[str, str]] = None,
              archived_urls: Optional[Mapping[str, str]] = None,
              title_max_chars: int = TITLE_MAX_CHARS,
              title_block_on_breach: bool = False,
              grammar_enabled: bool = False,
              max_grammar_defects_per_1k: float = 0.0) -> Dict[str, Any]:
    """Run every lint check; return the machine-readable report.

    `report["ok"]` is False iff any problem has severity "error" — that is the half the
    publish gate ANDs into `is_listed`. Warnings ride along in the report only.

    `archived_urls` maps citation URL -> Wayback memento, so a dead citation whose evidence
    is still reachable warns instead of blocking. Callers build it from `Source.archived_url`.

    `house_fields` carries engine-authored single-line copy that is NOT already in
    `listing_texts` — `title` above all. Its absence was the second half of the 2026-08-08
    dash defect: the field skipped the normaliser AND was never handed to the linter, so
    nothing on the publish path could see it. Callers pass every buyer-visible line.
    """
    fin = (artifacts or {}).get("financial_model", "") or ""
    problems: List[Problem] = []
    problems += check_currency(fin, listing_copy, market)
    problems += check_arithmetic(fin)
    problems += check_sections(fin)
    problems += check_truncation(listing_texts or {}, truncation_caps)

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

    # The title is read from `house` rather than taking its own parameter: it is already
    # the field house_fields exists to carry, and a second entry point is how a caller ends
    # up linting a title the publish path never renders.
    if "title" in house:
        problems += check_title(house["title"], max_chars=title_max_chars,
                                block=title_block_on_breach)
        # Same actuator, because "the title is bad" is one question with two halves: it can
        # be the wrong SHAPE, or the right shape carrying a claim the pack never made. The
        # sources are the pack's other buyer-visible lines — everything in `house` except
        # the title itself, so the descriptor is graded against copy that has already been
        # through the same grounding the storefront sells on.
        problems += check_title_claims(
            house["title"],
            [v for k, v in house.items() if k != "title"],
            market=market, block=title_block_on_breach)

    # `is_prose_artifact` is the SINGLE definition of what may be graded as writing; see
    # copy_lint.DATA_ARTIFACT_SUFFIXES for the pack this got wrong. Selecting the corpus by a
    # local `.json` test is what let .csv and .svg through to both copy checks at once.
    prose = {k: v for k, v in (artifacts or {}).items()
             if isinstance(v, str) and is_prose_artifact(k, v)}
    problems += check_identifier_leak({**prose, **house})

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
        "market": market,
        "urls_checked": urls_seen,
        # Recorded pass or fail so the receipt accrues a real baseline while the actuator
        # is still off — the number you turn `max_grammar_defects_per_1k` on with should be
        # one you have seen on live packs, not one guessed from a sample.
        "grammar_rate_per_1k": grammar_rate,
        "problems": problems,
    }
