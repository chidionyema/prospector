"""§25.6 item 2 — the deterministic numeric-citation check, SHADOW MODE ONLY.

WHAT IT MEASURES (programme doc §25.5, `docs/COMMERCIAL_READINESS_PROGRAM.md`):
`q4c_claim_level_tracing.py` measured that **169 of 1,640 figures (10.3%) asserted
in a dossier rationale appear in NO passage the run retrieved** — the model
invented them. That is provable offline because `verify.py` builds the verdict
prompt as `[source_id] s.text[:VERDICT_PASSAGE_TRUNCATE]` with
`VERDICT_PASSAGE_TRUNCATE = 600`, so a check's cited `sources[].text[:600]` IS
the model's entire input for that ruling. A number absent from all of it was
never retrieved. No model, no network, microseconds.

WHY SHADOW ONLY (explicit founder decision, §25.6 item 2: "Open question for the
founder: demote the check to `unverifiable`, or keep the ruling and strip the
offending sentence? **Not implemented — this section measures; §15 P-items
decide.**"). Until that decision lands this module LOGS and nothing else.
`verify.run_check` calls `record_shadow()` after its `CheckResult` is finalised
and discards the return value, so the check is structurally incapable of
changing a verdict, not merely disciplined about it
(`tests/unit/test_numeric_citation.py::test_check_result_identical_with_shadow_on_and_off`).

THE FALSE-POSITIVE DIRECTION IS THE SAFE ONE, BY CONSTRUCTION. Two rules:

  1. **Extraction under-reaches.** A bare number with no unit is prose ("2 of the
     sources", "three times") far more often than evidence, so bare numbers are
     kept only above `bare_min_value` (1000) or when they wear a thousands
     separator. Missing a figure costs a measurement; inventing one accuses a
     rationale of fabricating a number it never asserted.
  2. **Matching over-reaches.** A figure counts as SUPPORTED if its surface form
     OR any normalised rendering of its value appears with digit boundaries —
     `£1.2m` is satisfied by "1.2 million", "1,200,000", "1200000" or a bare
     "1.2". And when the checker cannot judge at all (no passages, an
     unparseable value, any exception) it returns SUPPORTED with `unsure=True`.
     Anything this module calls unsupported is unsupported under any stricter
     test — the rate it reports is a LOWER bound.

CONFIG (`config.yaml numeric_citation`, read defensively with `getattr` so the
module is inert on a config that has no such block):
    enabled      (False) — write nothing at all unless explicitly turned on
    shadow_mode  (True)  — log-only. `False` is NOT implemented; see `record_shadow`.
    min_digits   (1)     — ignore figures whose surface carries fewer digits
    ignore_years (True)  — "in 2024" is a date, not a claim figure
    tolerance    (0.0)   — relative rounding tolerance; 0 = exact
    log_dir      ("")    — empty => `<cfg.store_dir>/numeric_citation_shadow`
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Optional

from .jsonl_atomic import append_jsonl
from .telemetry import logger

# Mirrors `verify.VERDICT_PASSAGE_TRUNCATE`. Imported by value, not by reference, to
# keep this module free of a circular import; `verify.record_shadow(...)` passes the
# live constant so the two cannot drift in production.
DEFAULT_TRUNCATE = 600

# A bare number with no unit below this is prose, not evidence (see rule 1 above).
BARE_MIN_VALUE = 1000.0

_DEFAULT_LOG_SUBDIR = "numeric_citation_shadow"


# --------------------------------------------------------------------------- #
# The extraction grammar
# --------------------------------------------------------------------------- #
# NUM covers "49", "12.5", "1,761", "1,200,000.50". The comma-grouped branch is
# first so "1,761" is never split into "1" + "761".
_NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
_CUR = r"[£$€¥]"
# Magnitude suffixes. Single letters are accepted ONLY attached or after one space in a
# currency/range context; the spelled words are accepted anywhere. `\b` stops "1.2m"
# logic firing on "1.2 mile".
_MAG = r"(?:trillion|billion|million|thousand|bn|tn|[kmb])\b"
_MAG_WORD = r"(?:trillion|billion|million|thousand)\b"
_MAG_ATTACHED = r"(?:bn|tn|[kmb])\b"

_MAG_MULT: dict[str, float] = {
    "k": 1e3, "thousand": 1e3,
    "m": 1e6, "million": 1e6,
    "b": 1e9, "bn": 1e9, "billion": 1e9,
    "tn": 1e12, "trillion": 1e12,
}

# One left-to-right scan. Alternatives are ordered MOST SPECIFIC FIRST because Python
# takes the first alternative that matches at a given position: the percent branch must
# beat the bare branch on "12%", and the range branches must beat both on "10–20".
_FIGURE_RE = re.compile(
    # Guard: never start a figure inside an identifier, a version string or the tail of
    # a longer number ("v2.5", the "345" of "12,345").
    r"(?<![\w.,])(?:"
    # (1) en/em-dash range, either or both ends optionally currency/magnitude/percent:
    #     "10–20", "£4.99–£9.99", "£1.2m–£3.4m", "10–20%"
    rf"(?P<r1c1>{_CUR})?\s?(?P<r1a>{_NUM})\s?(?P<r1am>{_MAG})?\s*[–—]\s*"
    rf"(?P<r1c2>{_CUR})?\s?(?P<r1b>{_NUM})\s?(?P<r1bm>{_MAG})?"
    r"(?:\s?(?P<r1pct>%|per\s?cent))?"
    # (2) hyphen/"to" range, but ONLY when a currency symbol anchors it — "5-6" in prose
    #     is not a range, and inventing one would invent a figure.
    rf"|(?P<r2c1>{_CUR})\s?(?P<r2a>{_NUM})\s?(?P<r2am>{_MAG})?\s*(?:-|to)\s*"
    rf"(?P<r2c2>{_CUR})?\s?(?P<r2b>{_NUM})\s?(?P<r2bm>{_MAG})?"
    # (3) percentage: "12%", "12.5 per cent", "12 percent", "12pc"
    rf"|(?P<pn>{_NUM})\s?(?P<pu>%|per\s?cent\b|pc\b)"
    # (4) currency: "$49", "£1.2m", "€3,400", "£5 million"
    rf"|(?P<cs>{_CUR})\s?(?P<cn>{_NUM})\s?(?P<cm>{_MAG})?"
    # (5) multiplier: "3x", "3-fold", "3 times"
    rf"|(?P<mn>{_NUM})\s?(?P<mu>x\b|-?\s?fold\b|times\b)"
    # (6) magnitude without currency: "4 million", "3bn", "5k"
    rf"|(?P<gn>{_NUM})(?:\s?(?P<gw>{_MAG_WORD})|(?P<ga>{_MAG_ATTACHED}))"
    # (7) bare count, with an optional trailing unit word: "1,761", "5,000 users"
    rf"|(?P<bn>{_NUM})(?:\s(?P<bu>[A-Za-z][A-Za-z-]{{2,}}))?"
    r")",
    re.IGNORECASE,
)

_YEAR_RE = re.compile(r"^(?:19|20)\d\d$")
_PLAIN_NUM_RE = re.compile(_NUM)

# Kinds. `count` is the only one that can be dropped for being small/bare.
KIND_CURRENCY = "currency"
KIND_PERCENT = "percent"
KIND_MULTIPLIER = "multiplier"
KIND_MAGNITUDE = "magnitude"
KIND_RANGE = "range"
KIND_COUNT = "count"
# Kinds whose value is a plain integer that could also be a calendar year.
_YEARABLE = {KIND_COUNT, KIND_RANGE}


@dataclass(frozen=True)
class Figure:
    """One numeric claim lifted out of a rationale.

    `value` is the comparable number (a magnitude suffix is already applied, so
    `£1.2m` carries 1200000.0); `surface` is the exact substring as written, and
    (`start`, `end`) is its span in the rationale.
    """
    surface: str
    value: float
    kind: str
    start: int
    end: int
    unit: str = ""
    # The digits exactly as written, commas stripped ("1,761" -> "1761"). Kept
    # separate from `value` because "1.2" and 1200000.0 are both legitimate
    # renderings of the same claim and both are searched for.
    raw: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"surface": self.surface, "value": self.value, "kind": self.kind,
                "start": self.start, "end": self.end, "unit": self.unit, "raw": self.raw}


@dataclass(frozen=True)
class Support:
    """The verdict on one figure. `supported=True` with `unsure=True` means
    "could not judge" — see the module docstring, rule 2."""
    figure: Figure
    supported: bool
    match_kind: str = ""          # surface | normalised | tolerance | unsure | ""
    matched_source_id: str = ""
    matched_url: str = ""
    matched_token: str = ""
    unsure: bool = False
    reason: str = ""
    self_ref: bool = False        # the figure is OUR OWN offer/price, not a claim about the world

    def to_dict(self) -> dict[str, Any]:
        return {"figure": self.figure.value, "surface": self.figure.surface,
                "kind": self.figure.kind, "unit": self.figure.unit,
                "supported": self.supported, "match_kind": self.match_kind,
                "matched_source_id": self.matched_source_id,
                "matched_url": self.matched_url, "matched_token": self.matched_token,
                "unsure": self.unsure, "reason": self.reason,
                "self_ref": self.self_ref}


@dataclass(frozen=True)
class Report:
    """Per-figure verdicts for one rationale plus the aggregate §25.5 metric."""
    supports: tuple[Support, ...] = ()
    figures_n: int = 0
    supported_n: int = 0
    unsupported_n: int = 0
    unsure_n: int = 0
    untraceable_rate: float = 0.0
    sources_n: int = 0
    self_ref_n: int = 0           # unsupported figures that restate OUR OWN offer or list price
    untraceable_n: int = 0        # unsupported AND not self-referential — the §25.5 metric

    @property
    def figures(self) -> tuple[Figure, ...]:
        return tuple(s.figure for s in self.supports)

    def to_dict(self) -> dict[str, Any]:
        return {"figures_n": self.figures_n, "supported_n": self.supported_n,
                "unsupported_n": self.unsupported_n, "unsure_n": self.unsure_n,
                # BACK-COMPAT: `untraceable_rate` is unsupported/figures, which lumps self_ref
                # in with genuinely fabricated numbers. Rows written before 2026-08-08 carry
                # only this field, so it keeps its meaning; `untraceable_rate_excl_self` below
                # is the one that answers §25.5 and the one an enforcement decision must use.
                "untraceable_rate": self.untraceable_rate,
                "self_ref_n": self.self_ref_n,
                "untraceable_n": self.untraceable_n,
                "untraceable_rate_excl_self": (
                    (self.untraceable_n / self.figures_n) if self.figures_n else 0.0),
                "sources_n": self.sources_n,
                "figures": [s.to_dict() for s in self.supports]}


@dataclass(frozen=True)
class NumericCitationSettings:
    """Resolved `config.yaml numeric_citation` block. Defaults = OFF and inert."""
    enabled: bool = False
    shadow_mode: bool = True
    min_digits: int = 1
    ignore_years: bool = True
    tolerance: float = 0.0
    log_dir: str = ""


# --------------------------------------------------------------------------- #
# 1. Extraction
# --------------------------------------------------------------------------- #

def _to_value(raw: str, mag: str | None) -> Optional[float]:
    try:
        v = float(str(raw).replace(",", ""))
    except (TypeError, ValueError):
        return None
    if mag:
        v *= _MAG_MULT.get(str(mag).strip().lower(), 1.0)
    return v


def _digits(raw: str) -> int:
    return sum(1 for ch in str(raw) if ch.isdigit())


def _span(m: "re.Match[str]", *names: str) -> tuple[int, int]:
    """Union span of the named groups that participated, else the whole match.

    Used so each figure carries its OWN surface form: the second endpoint of
    "£4.99–£9.99" is "£9.99", not the whole range, and "1,761 registered firms"
    yields the surface "1,761" with `unit="registered"` recorded separately.
    """
    lo = hi = None
    for n in names:
        if not n:
            continue
        s, e = m.span(n)
        if s < 0:
            continue
        lo = s if lo is None else min(lo, s)
        hi = e if hi is None else max(hi, e)
    return (lo, hi) if lo is not None and hi is not None else m.span()


def _mk(m: "re.Match[str]", raw: str, mag: str | None, kind: str, unit: str,
        *names: str) -> Optional[tuple[str, str, float, str, int, int]]:
    """(raw_digits, kind, value, unit, start, end), or None if it will not parse."""
    v = _to_value(raw, mag)
    if v is None:
        return None
    start, end = _span(m, *names)
    return (str(raw).replace(",", ""), kind, v, unit or (mag or ""), start, end)


def _endpoint_kind(cur: str | None, mag: str | None, pct: str | None) -> str:
    if pct:
        return KIND_PERCENT
    if cur:
        return KIND_CURRENCY
    if mag:
        return KIND_MAGNITUDE
    return KIND_RANGE


def _parsed(m: "re.Match[str]") -> list[tuple[str, str, float, str, int, int]]:
    """Every figure carried by one regex match.

    A range yields TWO — both endpoints are claims, and a rationale that says
    "£4.99–£9.99" has asserted both numbers.
    """
    g = m.groupdict()
    out = []
    if g.get("r1a") is not None:                                   # (1) dash range
        pct = g.get("r1pct")
        ends = ((g.get("r1c1"), g["r1a"], g.get("r1am"), ("r1c1", "r1a", "r1am")),
                (g.get("r1c2") or g.get("r1c1"), g["r1b"], g.get("r1bm"),
                 ("r1c2", "r1b", "r1bm", "r1pct")))
        for cur, num, mag, names in ends:
            out.append(_mk(m, num, mag, _endpoint_kind(cur, mag, pct),
                           cur or pct or "", *names))
    elif g.get("r2a") is not None:                                 # (2) currency range
        ends = ((g.get("r2c1"), g["r2a"], g.get("r2am"), ("r2c1", "r2a", "r2am")),
                (g.get("r2c2") or g.get("r2c1"), g["r2b"], g.get("r2bm"),
                 ("r2c2", "r2b", "r2bm")))
        for cur, num, mag, names in ends:
            out.append(_mk(m, num, mag, KIND_CURRENCY, cur or "", *names))
    elif g.get("pn") is not None:                                  # (3) percent
        out.append(_mk(m, g["pn"], None, KIND_PERCENT, "%", "pn", "pu"))
    elif g.get("cn") is not None:                                  # (4) currency
        out.append(_mk(m, g["cn"], g.get("cm"), KIND_CURRENCY, g.get("cs") or "",
                       "cs", "cn", "cm"))
    elif g.get("mn") is not None:                                  # (5) multiplier
        out.append(_mk(m, g["mn"], None, KIND_MULTIPLIER, "x", "mn", "mu"))
    elif g.get("gn") is not None:                                  # (6) magnitude
        mag = g.get("gw") or g.get("ga")
        out.append(_mk(m, g["gn"], mag, KIND_MAGNITUDE, mag or "", "gn", "gw", "ga"))
    elif g.get("bn") is not None:                                  # (7) bare count
        out.append(_mk(m, g["bn"], None, KIND_COUNT, g.get("bu") or "", "bn"))
    return [p for p in out if p is not None]


def extract_figures(
    text: str,
    *,
    ignore_years: bool = True,
    min_digits: int = 1,
    bare_min_value: float = BARE_MIN_VALUE,
) -> list[Figure]:
    """Every claim-bearing number in `text`, in order, deduped by (kind, value).

    Deliberately UNDER-reaches on bare numbers (module docstring, rule 1): a
    number with no currency symbol, percent sign, multiplier or magnitude word
    survives only if it carries a thousands separator or is >= `bare_min_value`.
    """
    src = str(text or "")
    out: list[Figure] = []
    seen: set[tuple[str, float]] = set()
    for m in _FIGURE_RE.finditer(src):
        for raw, kind, value, unit, start, end in _parsed(m):
            if _digits(raw) < max(0, int(min_digits)):
                continue
            if ignore_years and kind in _YEARABLE and _YEAR_RE.match(raw):
                continue                                   # "in 2024" is a date
            if kind == KIND_COUNT:
                had_separator = "," in src[start:end]
                if not had_separator and value < bare_min_value:
                    continue                               # prose counting, not evidence
            key = (kind, round(value, 6))
            if key in seen:
                continue
            seen.add(key)
            out.append(Figure(surface=src[start:end].strip(), value=value, kind=kind,
                              start=start, end=end, unit=unit, raw=raw))
    return out


# --------------------------------------------------------------------------- #
# 2. Matching
# --------------------------------------------------------------------------- #

def _fmt(v: float) -> str:
    """Plain decimal rendering, never scientific notation, no trailing zeros."""
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    return f"{v:.6f}".rstrip("0").rstrip(".")


def _group(digits: str) -> str:
    """"1200000" -> "1,200,000" (integers only; returns the input otherwise)."""
    if not digits.isdigit():
        return digits
    return f"{int(digits):,}"


def match_tokens(fig: Figure) -> list[str]:
    """Every digit-string a passage could legitimately use for this figure.

    `£1.2m` yields "1.2" (the mantissa as written), "1200000", "1,200,000" and
    "1200" — so "1.2 million", "1,200,000" and "1200 thousand" all match. This
    is deliberately generous: over-matching produces SUPPORTED, the safe answer.
    """
    toks: list[str] = []

    def add(s: str) -> None:
        if s and s not in toks:
            toks.append(s)

    add(fig.raw)
    add(_group(fig.raw) if fig.raw.isdigit() else fig.raw)
    whole = _fmt(fig.value)
    add(whole)
    if whole.isdigit():
        add(_group(whole))
    for scale in (1e3, 1e6, 1e9, 1e12):
        q = fig.value / scale
        if 1.0 <= q < 1000.0:
            add(_fmt(round(q, 6)))
    return toks


def _strip_thousands(text: str) -> str:
    return re.sub(r"(?<=\d),(?=\d\d\d)", "", str(text or ""))


def _contains_number(haystack: str, num: str) -> bool:
    """Digit-boundary containment. `35000` must NOT match inside `135000`."""
    if not num:
        return False
    h = _strip_thousands(haystack)
    esc = re.escape(num)
    if re.search(rf"(?<![\d.]){esc}(?![\d])", h):
        return True
    # Trailing zeros are the same number: 92 matches "92.0", 4.5 matches "4.50".
    tail = r"0*" if "." in num else r"\.0+"
    return bool(re.search(rf"(?<![\d.]){esc}{tail}(?![\d])", h))


def _norm_ws(s: str) -> str:
    return " ".join(str(s or "").split()).lower()


def _contains_surface(haystack: str, surface: str) -> bool:
    """Whitespace-tolerant surface containment, with DIGIT BOUNDARIES.

    A plain substring test is wrong here and quietly so: "35000" is a substring
    of "135000", which would report a fabricated figure as grounded in a passage
    about a different number. Whitespace inside the surface is matched loosely so
    "12.5 per cent" still finds "12.5  per  cent".
    """
    surf = _norm_ws(surface)
    if not surf:
        return False
    pattern = r"\s+".join(re.escape(part) for part in surf.split())
    guard_l = r"(?<![\d.])" if surf[0].isdigit() else ""
    guard_r = r"(?![\d])" if surf[-1].isdigit() else ""
    return bool(re.search(guard_l + pattern + guard_r, _norm_ws(haystack)))


def _passage_view(src: Any, truncate: int) -> tuple[str, str, str]:
    """(source_id, url, text[:truncate]) from a Source, a dict, or anything alike."""
    if isinstance(src, dict):
        sid = str(src.get("source_id") or "")
        url = str(src.get("url") or "")
        text = str(src.get("text") or "")
    else:
        sid = str(getattr(src, "source_id", "") or "")
        url = str(getattr(src, "url", "") or "")
        text = str(getattr(src, "text", "") or "")
    return sid, url, (text[:truncate] if truncate and truncate > 0 else text)


def figure_supported(
    fig: Figure,
    passages: Iterable[Any],
    *,
    tolerance: float = 0.0,
    truncate: int = DEFAULT_TRUNCATE,
) -> Support:
    """Does `fig` literally appear in the passages the rationale cited?

    Order: exact surface form, then any normalised rendering with digit
    boundaries, then (only when `tolerance > 0`) any number in the passage
    within that RELATIVE tolerance. Returns the first passage that matched.

    UNSURE => SUPPORTED. If there are no passages, none carries text, or the
    figure's value will not parse, this reports `supported=True, unsure=True`.
    The check exists to find fabricated numbers; a checker that cannot see the
    evidence has found nothing, and must not say otherwise.
    """
    try:
        views = [_passage_view(p, truncate) for p in (passages or [])]
    except Exception as e:                                   # pragma: no cover - defensive
        return Support(fig, True, match_kind="unsure", unsure=True,
                       reason=f"passages_unreadable: {e}")
    views = [v for v in views if v[2].strip()]
    if not views:
        return Support(fig, True, match_kind="unsure", unsure=True,
                       reason="no_passage_text")
    if fig.value != fig.value:                               # NaN
        return Support(fig, True, match_kind="unsure", unsure=True,
                       reason="unparseable_value")

    toks = match_tokens(fig)
    for sid, url, text in views:
        if _contains_surface(text, fig.surface):
            return Support(fig, True, match_kind="surface", matched_source_id=sid,
                           matched_url=url, matched_token=fig.surface)
    for sid, url, text in views:
        for tok in toks:
            if _contains_number(text, tok):
                return Support(fig, True, match_kind="normalised", matched_source_id=sid,
                               matched_url=url, matched_token=tok)
    if tolerance and tolerance > 0.0:
        span = abs(fig.value) * float(tolerance)
        for sid, url, text in views:
            for m in _PLAIN_NUM_RE.finditer(text):
                try:
                    other = float(m.group(0).replace(",", ""))
                except ValueError:                            # pragma: no cover - defensive
                    continue
                if abs(other - fig.value) <= span:
                    return Support(fig, True, match_kind="tolerance",
                                   matched_source_id=sid, matched_url=url,
                                   matched_token=m.group(0))
    return Support(fig, False, match_kind="", reason="not_in_any_cited_passage")


# --------------------------------------------------------------------------- #
# 3. The per-rationale report
# --------------------------------------------------------------------------- #

def _is_self_reference(fig: Figure, self_text: str) -> bool:
    """Is this figure OUR OWN offer or list price rather than a claim about the world?

    "a £49 report is within budget" asserts nothing retrievable; it restates our own listing
    rung. Counting it as an ungrounded claim is not merely noise — it is a number that MOVES
    with our own code. `verify._check_question` began stating the actual rung to the
    `payer_solvency` check on 2026-08-06 (§28.3), precisely so the check would stop inventing
    a price; the model now repeats the rung we handed it, and a checker with no self_ref bucket
    scores that obedience as a fabrication. An enforcement threshold calibrated on the lumped
    number would therefore tighten every time we told the model MORE truth.

    Matching only ever moves a figure OUT of `untraceable`, so this keeps that count a lower
    bound — the same conservative direction q4c takes (`q4c_claim_level_tracing.py:221`).
    """
    if not self_text:
        return False
    if _contains_surface(self_text, fig.surface):
        return True
    return any(_contains_number(self_text, tok) for tok in match_tokens(fig))


def audit_rationale(
    rationale: str,
    sources: Iterable[Any],
    *,
    settings: NumericCitationSettings | None = None,
    truncate: int = DEFAULT_TRUNCATE,
    self_text: str = "",
) -> Report:
    """Per-figure verdicts for one rationale plus `untraceable_rate`.

    `untraceable_rate` is unsupported / total figures, 0.0 when the rationale
    asserts no figures — a rationale with no numbers is not 100% untraceable.

    `self_text` is the candidate's own words plus the declared price rungs. Figures found
    there are still `supported=False` (they are genuinely in no retrieved passage) but are
    counted in `self_ref_n` and EXCLUDED from `untraceable_n`. Defaulting it to "" keeps every
    existing caller's numbers byte-identical; only a caller that supplies it gets the split.
    """
    s = settings or NumericCitationSettings()
    srcs = list(sources or [])
    figs = extract_figures(rationale, ignore_years=s.ignore_years,
                           min_digits=s.min_digits)
    supports = []
    for f in figs:
        sup = figure_supported(f, srcs, tolerance=s.tolerance, truncate=truncate)
        if not sup.supported and _is_self_reference(f, self_text):
            sup = replace(sup, self_ref=True, reason="self_reference_own_offer_or_rung")
        supports.append(sup)
    supports = tuple(supports)
    unsupported = sum(1 for x in supports if not x.supported)
    self_ref = sum(1 for x in supports if x.self_ref)
    unsure = sum(1 for x in supports if x.unsure)
    n = len(supports)
    return Report(supports=supports, figures_n=n,
                  supported_n=n - unsupported, unsupported_n=unsupported,
                  unsure_n=unsure,
                  untraceable_rate=(unsupported / n) if n else 0.0,
                  self_ref_n=self_ref, untraceable_n=unsupported - self_ref,
                  sources_n=len(srcs))


# --------------------------------------------------------------------------- #
# 4. Settings + the shadow log
# --------------------------------------------------------------------------- #

def settings_from_config(cfg: Any) -> NumericCitationSettings:
    """Read `cfg.numeric_citation` off a Config (or any object/dict). Never raises."""
    raw = getattr(cfg, "numeric_citation", {}) or {}
    if isinstance(raw, NumericCitationSettings):
        return raw
    if not isinstance(raw, dict):
        return NumericCitationSettings()
    d = NumericCitationSettings()
    try:
        return NumericCitationSettings(
            enabled=bool(raw.get("enabled", d.enabled)),
            shadow_mode=bool(raw.get("shadow_mode", d.shadow_mode)),
            min_digits=int(raw.get("min_digits", d.min_digits)),
            ignore_years=bool(raw.get("ignore_years", d.ignore_years)),
            tolerance=float(raw.get("tolerance", d.tolerance)),
            log_dir=str(raw.get("log_dir", d.log_dir) or ""),
        )
    except (TypeError, ValueError) as e:
        logger.warning(f"numeric_citation: unreadable config block ({e}); using defaults")
        return d


def resolve_log_path(cfg: Any, settings: NumericCitationSettings) -> Path:
    """Where the shadow log is written.

    `numeric_citation.log_dir` wins; then `PROSPECTOR_NUMERIC_CITATION_LOG_DIR`; otherwise
    `<cfg.store_dir>/numeric_citation_shadow`, which already honours `PROSPECTOR_STORE_DIR`
    (config.py:487). Resolved per call — a module-level path constant bound at import is
    exactly how tests have polluted production state in this repo four separate times.

    The env var is the fifth. `enabled` shipped `true` on 2026-08-07, and within one test
    run 118 rows carrying `"provider": "mock"` landed in the real
    `store/numeric_citation_shadow/shadow-2026-08.jsonl` — every test that drives a check
    with a `load_config()` cfg was logging into production state. `tests/conftest.py`
    points this var at tmp_path for the whole suite. It sits BELOW `settings.log_dir` so
    that a test pinning its own dir (tests/unit/test_numeric_citation.py:36) still wins.
    """
    if settings.log_dir:
        base = Path(settings.log_dir)
    elif os.environ.get("PROSPECTOR_NUMERIC_CITATION_LOG_DIR", "").strip():
        base = Path(os.environ["PROSPECTOR_NUMERIC_CITATION_LOG_DIR"].strip())
    else:
        store_dir = getattr(cfg, "store_dir", None)
        if store_dir is None:
            store = getattr(cfg, "store", None)
            store_dir = (store or {}).get("dir") if isinstance(store, dict) else None
        base = Path(store_dir) if store_dir else Path("store")
        base = base / _DEFAULT_LOG_SUBDIR
    return base / f"shadow-{time.strftime('%Y-%m')}.jsonl"


_SELF_FIELDS = ("title", "one_liner", "hypothesis", "who_pays", "why_now")


def _self_text(cfg: Any, cand: Any) -> str:
    """The candidate's own words + every declared price rung, as one haystack.

    Rungs are rendered in BOTH the stored unit and the spoken one — `listing.pricing.rungs`
    holds pence (4999) and a rationale writes "£49.99" — mirroring
    `q4c_claim_level_tracing.price_rungs()` so the live and offline numbers stay the same
    statistic. Anything unreadable yields "", which turns the split OFF for that row rather
    than guessing: a missing haystack must never invent a self-reference.

    The spoken form is pounds-and-pence ("49.99") for a charm-priced rung, or bare pounds
    ("49") for a whole-pound one — a rationale never writes "£49.00" for a round rung, so
    only appending the decimal form there would silently reopen the untraceable bucket for
    the entire back catalogue's rungs. `_contains_number` matches the exact digit string, so
    both forms must be present for their respective rung shape.
    """
    parts: list[str] = []
    for f in _SELF_FIELDS:
        try:
            parts.append(str(getattr(cand, f, "") or ""))
        except Exception:  # noqa: BLE001 — a stub candidate must not break an observer
            continue
    try:
        rungs = ((getattr(cfg, "listing", None) or {}).get("pricing", {}).get("rungs") or [])
        for r in rungs:
            pence = int(r)
            parts.append(str(pence))
            if pence % 100 == 0:
                parts.append(str(pence // 100))
            else:
                parts.append(f"{pence // 100}.{pence % 100:02d}")
    except Exception:  # noqa: BLE001 — an old Config has no listing block; that is fine
        pass
    return " ".join(p for p in parts if p)


def record_shadow(
    cfg: Any,
    cand: Any,
    result: Any,
    *,
    truncate: int = DEFAULT_TRUNCATE,
) -> Optional[dict[str, Any]]:
    """Audit a finished `CheckResult` and append ONE row per check. Log-only.

    The caller (`verify.run_check`) discards the return value, and every
    exception is swallowed here: an observability feature that can fail a moat
    check has changed a verdict, which is the one thing §25.6 forbids until the
    founder rules on enforcement. Returns None when disabled or on any failure.

    `shadow_mode: false` does NOT enable enforcement — enforcement is unbuilt.
    It only stamps the row so a future analysis can tell the two apart.
    """
    try:
        s = settings_from_config(cfg)
        if not s.enabled:
            return None
        rationale = str(getattr(result, "rationale", "") or "")
        sources = list(getattr(result, "sources", []) or [])
        report = audit_rationale(rationale, sources, settings=s, truncate=truncate,
                                 self_text=_self_text(cfg, cand))
        verdict = getattr(result, "verdict", None)
        row = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "candidate_id": str(getattr(cand, "candidate_id", "") or ""),
            "check": str(getattr(result, "check_name", "") or ""),
            "verdict": getattr(verdict, "value", verdict if isinstance(verdict, str) else ""),
            "provider": str(getattr(result, "provider", "") or ""),
            "truncate": int(truncate),
            "tolerance": s.tolerance,
            "ignore_years": s.ignore_years,
            "min_digits": s.min_digits,
            "shadow_mode": s.shadow_mode,
            "shadow_only": True,
            **report.to_dict(),
        }
        append_jsonl(resolve_log_path(cfg, s), row)
        return row
    except Exception as e:
        logger.warning(f"numeric citation shadow record failed: {e}")
        return None


# --------------------------------------------------------------------------- #
# 5. Read side — the §25.5 metric, recomputed from the live log
# --------------------------------------------------------------------------- #

def summarise_shadow_log(path: str | Path) -> dict[str, Any]:
    """Aggregate `untraceable_rate` overall and per check, from a shadow log.

    Weighted by FIGURES, not by rows, so a check that asserts twenty numbers
    counts twenty times — §25.5's headline is a rate over figures.
    """
    p = Path(path)
    per_check: dict[str, dict[str, int]] = {}
    rows = figures = unsupported = unsure = checks_with_figures = 0
    split_figures = unsplit_figures = self_ref = untraceable = 0
    if p.exists():
        with p.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue        # a torn line from another writer is not fatal
                rows += 1
                n = int(row.get("figures_n") or 0)
                bad = int(row.get("unsupported_n") or 0)
                figures += n
                unsupported += bad
                unsure += int(row.get("unsure_n") or 0)
                # Rows written before 2026-08-08 have no self_ref/untraceable split. They are
                # counted for `unsupported` and EXCLUDED from the split denominator rather
                # than assumed to hold zero self-references — assuming zero would silently
                # blend two different statistics into one headline, which is the mistake that
                # made the live 38.0% look like it contradicted q4c's 10.1%.
                if "untraceable_n" in row:
                    split_figures += n
                    self_ref += int(row.get("self_ref_n") or 0)
                    untraceable += int(row.get("untraceable_n") or 0)
                else:
                    unsplit_figures += n
                if n:
                    checks_with_figures += 1
                c = per_check.setdefault(str(row.get("check") or ""),
                                         {"figures": 0, "unsupported": 0})
                c["figures"] += n
                c["unsupported"] += bad
    return {
        "rows": rows,
        "checks_with_figures": checks_with_figures,
        "figures": figures,
        "unsupported": unsupported,
        "unsure": unsure,
        # LUMPED: self-references counted as untraceable. Kept because every row can produce it.
        "untraceable_rate": (unsupported / figures) if figures else 0.0,
        # SPLIT: the §25.5 metric, over only the rows that carry the split.
        "split_figures": split_figures,
        "unsplit_figures": unsplit_figures,
        "self_ref": self_ref,
        "untraceable": untraceable,
        "untraceable_rate_excl_self": (
            (untraceable / split_figures) if split_figures else None),
        "by_check": {k: {**v,
                         "untraceable_rate": (v["unsupported"] / v["figures"])
                         if v["figures"] else 0.0}
                     for k, v in sorted(per_check.items())},
    }
