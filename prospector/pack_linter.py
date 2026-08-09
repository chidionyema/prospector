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
from typing import Any, Dict, List, Optional, Tuple

import requests

from .copy_lint import (
    check_grammar,
    check_house_dashes,
    check_identifier_leak,
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
# Citation URLs resolvable (bounded, cached — the one networked check)
# ---------------------------------------------------------------------------

_URL_RE = re.compile(r"https?://[^\s<>\)\]\"']+")
_DEAD_STATUSES = frozenset({404, 410})
_URL_CACHE_TTL_S = 7 * 86400


# A real browser UA, matching retrieval._RESOLVE_UA. Without one, Cloudflare and friends
# 403 the probe on sight: 20 of the 21 citation warnings across the 2026-08-08 packs were
# this artifact, including en.wikipedia.org, which serves 200 to a browser GET. Those were
# only warnings, so they never blocked a pack — they just made the report unreadable.
_PROBE_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
             "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def _probe_url(url: str, timeout_s: float) -> Tuple[Optional[int], str]:
    """(status, note). status None = could not determine (network, not the citation)."""
    headers = {"User-Agent": _PROBE_UA}
    try:
        resp = requests.head(url, timeout=timeout_s, allow_redirects=True, headers=headers)
        if resp.status_code in (405, 501):  # HEAD not allowed ≠ page gone
            resp = requests.get(url, timeout=timeout_s, allow_redirects=True, stream=True,
                                headers=headers)
            resp.close()
        return resp.status_code, ""
    except requests.RequestException as exc:
        return None, type(exc).__name__


def check_urls(texts: Dict[str, str], *, cache_path: Optional[Path] = None,
               timeout_s: float = 5.0, max_urls: int = 20) -> Tuple[List[Problem], int]:
    """Probe up to `max_urls` distinct URLs across `texts` ({where: markdown}).

    Definitive 404/410 → error (the citation is dead and a buyer will find out).
    Any other failure → warning (our outage or their rate limit is not the citation's
    death — mirrors the engine-wide rule that an exception is never evidence).
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
        for url in _URL_RE.findall(text or ""):
            url = url.rstrip(".,;:")
            if url not in seen_urls:
                seen_urls.add(url)
                seen.append((where, url))

    problems: List[Problem] = []
    now = time.time()
    checked = 0
    for where, url in seen[:max_urls]:
        entry = cache.get(url)
        if entry and now - entry.get("ts", 0) < _URL_CACHE_TTL_S:
            status, note = entry.get("status"), entry.get("note", "cached")
        else:
            status, note = _probe_url(url, timeout_s)
            cache[url] = {"status": status, "note": note, "ts": now}
            checked += 1
        if status in _DEAD_STATUSES:
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
              grammar_enabled: bool = False,
              max_grammar_defects_per_1k: float = 0.0) -> Dict[str, Any]:
    """Run every lint check; return the machine-readable report.

    `report["ok"]` is False iff any problem has severity "error" — that is the half the
    publish gate ANDs into `is_listed`. Warnings ride along in the report only.

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
            url_texts, cache_path=url_cache_path, timeout_s=url_timeout_s, max_urls=max_urls)
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
