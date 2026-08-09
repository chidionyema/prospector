"""Copy-quality checks on the publish path — the house-voice floor.

`pack_linter` asks "is what's present WRONG in a way a buyer would see?" for money and
citations. This module asks it for PROSE, and exists because a grammar-engine trial on
2026-08-08 measured two defect classes that every existing gate waved through:

  1. HOUSE DASHES. 71 em/en-dashes reached the `title` of 68 of 72 live listings, against
     a standing founder rule that the catalogue carries none. Root cause was structural,
     not a typo: normalisation was applied field-by-field at the publish seam, so `title`
     (bridge.py, the catalog row) simply never got the call that `_card_field` gives every
     other buyer-facing field. Measured control that pins it: of the raw dossier fields,
     73 titles and 15 one_liners contained a dash; after publish, 71 titles and ZERO
     one_liners did. 15 -> 0 proves the normaliser works; 73 -> 71 proves title skipped it.

  2. INTERNAL IDENTIFIER LEAK. 589 occurrences of the engine's own schema names across 51
     of 79 pass-dossiers, inside prose the buyer pays for: "monthly_price of GBP 12 is
     assumption", "the opportunity's who_pays field", "(value_durability 0.438)". The model
     is handed internal field names as context and echoes them into copy.

What this module deliberately does NOT do is impose a style. The same trial ran the
off-the-shelf prose packs (write-good, proselint) over 312,886 words of engine prose and
measured 12,524 findings of which 11,980 (95.7%) were noise: `E-Prime` alone contributed
6,831 by objecting to the word "is", and `GenderBias` wanted "Ombudsman" -- the legal name
of a UK statutory body -- rewritten to "ombuds". On a source-or-die corpus that corrupts
cited fact. Only defects with a demonstrated buyer-visible failure are checked here.

Severity contract is `pack_linter`'s: "error" blocks listing, "warning" is recorded only.
"""
from __future__ import annotations

import dataclasses
import re
import shutil
import subprocess
from typing import Dict, List, Optional, Set

Problem = Dict[str, str]  # mirrors pack_linter.Problem; defined here to avoid an import cycle


def _err(check: str, where: str, detail: str) -> Problem:
    return {"check": check, "severity": "error", "where": where, "detail": detail}


def _warn(check: str, where: str, detail: str) -> Problem:
    return {"check": check, "severity": "warning", "where": where, "detail": detail}


# ---------------------------------------------------------------------------
# 0. URL extraction (shared — one definition, or the two copies disagree)
# ---------------------------------------------------------------------------

# ')' is deliberately IN the character class. Both previous extractors excluded it
# (`retrieval.py` and `pack_linter._URL_RE`), which silently truncated any URL that
# legitimately contains one. Measured 2026-08-09:
#     stored  https://en.wikipedia.org/wiki/Late_Payment_of_Commercial_Debts_(Interest  -> 404
#     real    https://en.wikipedia.org/wiki/Late_Payment_of_Commercial_Debts_(Interest)_Act_1998 -> 200
# The exclusion existed for a real reason -- prose writes "(see https://x.com/a)" -- so the
# fix is balanced-paren trimming below, not deleting the paren from the class.
_URL_CHARS_RE = re.compile(r"https?://[^\s<>\]\"'`]+")

#: Punctuation that ends a sentence, never a URL.
_URL_TRAILING_PUNCT = ".,;:!?"


def extract_urls(text: str) -> List[str]:
    """URLs in `text`, in order of appearance, duplicates preserved.

    Two rules, each paid for by a dead-citation false positive:

    1. A trailing ')' is dropped only while it is UNMATCHED, so `(see https://x.com/a)` loses
       its paren and `..._(Interest)_Act_1998` keeps both of its own.
    2. Sentence punctuation is trimmed from the end, repeatedly, because "…/a)." needs both
       passes.

    Note what is NOT done here: a trailing '/' is left alone. Some servers require it, so
    stripping it blindly would trade one false 404 for another -- the caller probes the
    slash-toggled variant instead (`pack_linter._probe_url`).
    """
    out: List[str] = []
    for raw in _URL_CHARS_RE.findall(text or ""):
        url = raw
        while url:
            trimmed = url.rstrip(_URL_TRAILING_PUNCT)
            if trimmed.endswith(")") and trimmed.count(")") > trimmed.count("("):
                trimmed = trimmed[:-1]
            if trimmed == url:
                break
            url = trimmed
        if url and url.lower() not in ("http://", "https://"):
            out.append(url)
    return out


# ---------------------------------------------------------------------------
# 1. House dashes
# ---------------------------------------------------------------------------

# The em-dash and en-dash are the founder's standing copy rule. U+2011 (non-breaking
# hyphen) joins them because it renders as a dash the buyer sees but survives every
# hyphen-shaped check written against U+002D -- 3 reached live titles that way.
HOUSE_DASH_CHARS: Dict[str, str] = {
    "—": "em-dash",
    "–": "en-dash",
    "‑": "non-breaking hyphen",
}


def check_house_dashes(fields: Dict[str, str]) -> List[Problem]:
    """Engine-authored fields must carry no em/en-dash.

    Callers pass ONLY prose the engine wrote. Quoted third-party passage text is never
    linted here: a cited source may legitimately contain any dash, and "correcting" it
    would falsify the citation on a source-or-die storefront.
    """
    problems: List[Problem] = []
    for name, text in sorted(fields.items()):
        if not isinstance(text, str) or not text:
            continue
        for ch, label in HOUSE_DASH_CHARS.items():
            n = text.count(ch)
            if not n:
                continue
            i = text.find(ch)
            excerpt = text[max(0, i - 40):i + 40].replace("\n", " ").strip()
            problems.append(_err(
                "house_dashes", name,
                f"{n} {label}(s) in `{name}` -- the catalogue carries none. "
                f"Normalise with plain_text.nodash(). Near: ...{excerpt}...",
            ))
    return problems


# ---------------------------------------------------------------------------
# 2. Internal identifier leak
# ---------------------------------------------------------------------------

# Derived from the dataclasses rather than hand-listed, so a field added to the schema is
# covered the day it is added. A hand-maintained denylist is the same defect shape as the
# per-field normalisation that let the dashes through: correct only while someone remembers.
_EXTRA_INTERNAL_IDENTS: Set[str] = {
    # the six filter checks (models/kill_filter vocabulary, not dataclass fields)
    "pain_reality", "value_durability", "payer_solvency",
    # scoring axes
    "pain_acuity", "money_provability", "build_feasibility",
    # financial-model input keys rendered by artifacts.py
    "monthly_price", "payback_months", "cost_of_goods_pct",
    "estimated_clv_gbp", "estimated_cac_gbp", "estimated_monthly_churn_pct",
    "overhead_month_1_gbp", "weighted_contribution", "max_score",
    # engine bookkeeping that showed up in prose
    "source_ids", "retrieval_failed", "gate_fired", "model_version",
    "provider_chain", "reverify_due_at", "dense_reward", "price_comparables",
    "commodity_premortem", "refinement_history", "weak_monetisation",
}

# Identifiers too generic to flag: they read as ordinary snake_case a buyer might
# legitimately meet in a build spec, and flagging them would be a false positive.
_IDENT_ALLOW: Set[str] = {"e_g", "i_e", "read_only", "opt_in", "opt_out"}

_IDENT_RE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
_URL_RE = re.compile(r"https?://\S+")


def _dataclass_field_names() -> Set[str]:
    """Field names of the engine's own contracts, best-effort.

    Wrapped because this runs on the publish path: an import or dataclass change must
    degrade the check, never crash a publish.
    """
    names: Set[str] = set()
    try:
        from . import models  # local import keeps module import cheap and cycle-free
    except Exception:
        return names
    for obj in vars(models).values():
        if isinstance(obj, type) and dataclasses.is_dataclass(obj):
            try:
                for f in dataclasses.fields(obj):
                    if "_" in f.name:
                        names.add(f.name)
            except Exception:
                continue
    return names


_INTERNAL_IDENTS_CACHE: Optional[Set[str]] = None


def internal_identifiers() -> Set[str]:
    global _INTERNAL_IDENTS_CACHE
    if _INTERNAL_IDENTS_CACHE is None:
        _INTERNAL_IDENTS_CACHE = (
            _dataclass_field_names() | _EXTRA_INTERNAL_IDENTS
        ) - _IDENT_ALLOW
    return _INTERNAL_IDENTS_CACHE


def _strip_code(text: str) -> str:
    """Remove fenced blocks, inline spans and URLs.

    A build spec may legitimately instruct the buyer to create a `monthly_price` column;
    that is documentation, not a leak. Only NARRATIVE occurrences are defects.
    """
    text = _FENCE_RE.sub(" ", text)
    text = _INLINE_CODE_RE.sub(" ", text)
    return _URL_RE.sub(" ", text)


# Artifact suffixes that are MACHINE-READABLE DATA, not writing. Grading these as prose is
# not a false positive to tune down — it is a category error, and it delisted a live pack on
# 2026-08-08 (2abc23c3c0d05bab, 404 on the shelf) for two "defects" no rewrite could fix:
#
#   * identifier_leak: the column headers. pack_data.py GENERATES them from the schema
#     (:253 scorecard_csv, :348 financial_csv, :416 comparables_csv), so `amount_pence_gbp`
#     is the correct name of that column and regeneration can never change it.
#   * grammar: measured on that pack's own artifacts, 28 of 32 counted defects came from
#     three CSVs and ZERO from prose -- `UnclosedQuotes x9` fires on the header row
#     `section,key,label,value`, and `CommaFixes x19` on the commas that ARE the format.
#     Excluding data files moves the pack from 4.46 to 0.64 defects per 1k words.
#
# The suffix is the whole test. Content-sniffing a leading `{`/`[` stays as a backstop for a
# JSON body handed over under a prose-shaped name, but a .csv never starts with one.
DATA_ARTIFACT_SUFFIXES = (".json", ".csv", ".tsv", ".svg", ".yaml", ".yml", ".xml")


def is_prose_artifact(name: str, text: str = "") -> bool:
    """True when an artifact is buyer-facing WRITING and may be graded as such.

    One definition, shared by every copy check and by `pack_linter`'s corpus selection, so
    a check can never disagree with the corpus about what counts as prose.
    """
    if name.lower().endswith(DATA_ARTIFACT_SUFFIXES):
        return False
    return text.lstrip()[:1] not in ("{", "[", "<")


# Labels for identifiers whose underscore-stripped form still reads like plumbing
# ("estimated cac gbp"). Everything else falls back to the underscore strip, which is
# adequate for `who_pays` -> "who pays" and stays correct for a field added tomorrow.
_IDENT_LABELS: Dict[str, str] = {
    "monthly_price": "monthly price",
    "target_customers_month_1": "customers in month 1",
    "target_customers_month_12": "customers in month 12",
    "estimated_cac_gbp": "customer acquisition cost",
    "estimated_clv_gbp": "customer lifetime value",
    "estimated_monthly_churn_pct": "monthly churn",
    "cost_of_goods_pct": "cost of goods",
    "overhead_month_1_gbp": "month 1 overhead",
    "payback_months": "payback period",
    "ltv_cac_ratio": "LTV to CAC ratio",
    "value_durability": "durability of the advantage",
    "payer_solvency": "whether the buyer can pay",
    "pain_reality": "whether the pain is real",
    "money_provability": "provability of the money",
    "weak_monetisation": "monetisation risk",
    "one_liner": "summary",
}

# Spans that are DOCUMENTATION, not narrative — the same three `_strip_code` exempts from
# the check. The normaliser must skip exactly what the gate skips, or a build spec telling
# the buyer to create a `monthly_price` column would be silently rewritten into nonsense.
_SKIP_SPAN_RE = re.compile(r"```.*?```|`[^`\n]+`|https?://\S+", re.DOTALL)


def buyer_readable(text: str) -> str:
    """Rewrite engine schema identifiers into words, for prose the buyer pays for.

    This is the SECOND half of the identifier fix and the reason the first half was not
    enough. `artifacts._candidate_prompt_view` stopped feeding the model the schema as
    vocabulary, but `financial_model` asks it to emit a JSON object literally keyed
    `estimated_cac_gbp` and then to narrate that object's weaknesses -- so the model names
    the key it has just filled, and regenerating only re-rolls the same dice. Measured on
    live pack 2abc23c3c0d05bab: 5 identifiers in the rendered weakness bullets, e.g.
    "estimated_cac_gbp (GBP 35) has no supporting source".

    Applied at the RENDER choke point it is deterministic and free: no model call, and no
    republish can reintroduce what the renderer strips. It reads `internal_identifiers()`
    -- the very set `check_identifier_leak` blocks on -- so the generator and the gate
    cannot drift apart the way per-field dash normalisation did.
    """
    if not text or "_" not in text:
        return text
    idents = internal_identifiers()

    def _one(m: "re.Match[str]") -> str:
        tok = m.group(0)
        if tok not in idents:
            return tok
        return _IDENT_LABELS.get(tok, tok.replace("_", " "))

    out: List[str] = []
    pos = 0
    for span in _SKIP_SPAN_RE.finditer(text):
        out.append(_IDENT_RE.sub(_one, text[pos:span.start()]))
        out.append(span.group(0))
        pos = span.end()
    out.append(_IDENT_RE.sub(_one, text[pos:]))
    return "".join(out)


def check_identifier_leak(texts: Dict[str, str]) -> List[Problem]:
    """The engine's own schema names must not appear in buyer-facing prose."""
    idents = internal_identifiers()
    problems: List[Problem] = []
    for name, text in sorted(texts.items()):
        if not isinstance(text, str) or not text:
            continue
        if not is_prose_artifact(name, text):
            continue
        body = _strip_code(text)
        found: Dict[str, int] = {}
        for m in _IDENT_RE.finditer(body):
            tok = m.group(0)
            if tok in idents:
                found[tok] = found.get(tok, 0) + 1
        if found:
            top = sorted(found.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
            listed = ", ".join(f"{t} x{n}" for t, n in top)
            problems.append(_err(
                "identifier_leak", name,
                f"{sum(found.values())} internal schema identifier(s) in buyer-facing "
                f"prose: {listed}. The buyer is reading the engine's field names.",
            ))
    return problems


# ---------------------------------------------------------------------------
# 3. Grammar (external engine, fail-open)
# ---------------------------------------------------------------------------

# Harper rule names that are genuine grammar defects. Measured over 312,886 words of
# engine prose: these fire at ~0.8 per 1k words, while its SpellCheck (4,202 hits) and
# UseTitleCase (1,300) are dominated by brand names and deliberate sentence-case headings.
# Counting only these keeps the rate a defect signal rather than a vocabulary complaint.
HARPER_GRAMMAR_RULES = frozenset({
    "Agreement", "MissingTo", "AnA", "MissingPreposition", "InflectedVerbAfterTo",
    "CommaFixes", "UnclosedQuotes", "Repetition", "NounVerbConfusion", "MassNouns",
    "SplitWords", "PhrasalVerbAsCompoundNoun", "CompoundNouns", "OrthographicConsistency",
})

_HARPER_RULE_RE = re.compile(r"<(\w+): (\d+)>")


# Absolute fallbacks searched when PATH lookup fails. The daemon runs under launchd, whose
# PATH is /usr/bin:/bin:/usr/sbin:/sbin and therefore does NOT contain the Homebrew prefix
# where harper-cli installs. Relying on `which` alone would leave this check permanently
# fail-open in production while passing every interactive test — built and unreachable.
_HARPER_FALLBACK_PATHS = (
    "/usr/local/bin/harper-cli",
    "/opt/homebrew/bin/harper-cli",
)


def harper_path() -> Optional[str]:
    found = shutil.which("harper-cli")
    if found:
        return found
    import os
    for p in _HARPER_FALLBACK_PATHS:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def harper_available() -> bool:
    return harper_path() is not None


def grammar_findings(texts: Dict[str, str], *, timeout_s: float = 120.0,
                     tmp_dir: Optional[str] = None) -> Optional[Dict[str, int]]:
    """Run Harper over the given texts; return {rule: count} or None if unavailable.

    FAIL-OPEN BY CONTRACT. `harper-cli` self-describes as a debugging tool and is at
    v0.1.0; it may be absent, hang, or change its output format. Any of those returns
    None, which the caller records as "unavailable" and does NOT treat as clean or as a
    defect. A missing checker must never unlist a good pack -- the same reason a citation
    host timing out is a warning in pack_linter while a definitive 404 is an error.
    """
    exe = harper_path()
    if exe is None:
        return None
    import tempfile
    from pathlib import Path
    try:
        with tempfile.TemporaryDirectory(dir=tmp_dir) as td:
            paths: List[str] = []
            for name, text in sorted(texts.items()):
                if not isinstance(text, str) or len(text.strip()) < 60:
                    continue
                p = Path(td) / (re.sub(r"[^A-Za-z0-9_.-]", "_", name) + ".md")
                p.write_text(_strip_code(text), encoding="utf-8")
                paths.append(str(p))
            if not paths:
                return {}
            r = subprocess.run([exe, "lint", "--no-color", *paths],
                               capture_output=True, text=True, timeout=timeout_s)
            out = (r.stdout or "") + (r.stderr or "")
            counts: Dict[str, int] = {}
            for m in _HARPER_RULE_RE.finditer(out):
                rule, n = m.group(1), int(m.group(2))
                if rule in HARPER_GRAMMAR_RULES:
                    counts[rule] = counts.get(rule, 0) + n
            return counts
    except Exception:
        return None


def check_grammar(texts: Dict[str, str], *, max_per_1k: float = 0.0,
                  timeout_s: float = 120.0) -> List[Problem]:
    """Grammar defect rate over buyer-facing prose.

    `max_per_1k <= 0` disables the actuator: findings are still recorded as a warning
    (so the receipt accrues real data), but nothing blocks. Above the threshold the pack
    is refused so the daemon's repair path picks it up -- no human in the loop.
    """
    counts = grammar_findings(texts, timeout_s=timeout_s)
    if counts is None:
        return [_warn("grammar", "-", "grammar_check_unavailable: harper-cli missing or "
                                      "failed; no grammar signal for this pack")]
    words = sum(len(t.split()) for t in texts.values() if isinstance(t, str))
    total = sum(counts.values())
    if words < 200:
        return []
    rate = 1000.0 * total / words
    detail = (f"{total} grammar defect(s) over {words:,} words = {rate:.2f} per 1k "
              f"({', '.join(f'{k} x{v}' for k, v in sorted(counts.items())) or 'none'})")
    if max_per_1k > 0 and rate > max_per_1k:
        return [_err("grammar", "-", detail + f" -- exceeds max_grammar_defects_per_1k={max_per_1k}")]
    return [_warn("grammar", "-", detail)] if total else []
