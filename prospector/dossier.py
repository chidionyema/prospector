"""Dossier assembly and human-readable rendering (Part 4/8).

build_dossier() is the single place that converts raw check results + score into a
Decision and assembles the Dossier record.  All callers pass in pre-computed values;
no datetime or model calls happen here (determinism in tests).

render_markdown() produces a human-readable audit document from a Dossier — KILL
dossiers render their cited reason prominently (a cited KILL is first-class).
"""
from __future__ import annotations

import re
from typing import Any, Optional

from . import admissibility, trimming
from .models import (
    DEFER_GATE,
    AdversarialResult,
    Candidate,
    CheckResult,
    Decision,
    Dossier,
    ScoreResult,
    Verdict,
    distinct_sources,
)
from .score import passes_composite

# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def grounded_support(checks, cfg) -> tuple[int, int, tuple[str, ...]]:
    """The source-or-die arithmetic a PASS must clear: (n_supported, moat_grounded, moat_checks).

    ONE definition, two callers — the decision layer (`build_dossier`, below) and the
    last-mile publish backstop (`EngineBridge.publish_pass`). They DID disagree: the bridge
    counted only `n_supported >= 1` against `confidence_floor` and never looked at
    `moat_grounded` at all. So a dossier hand-fed through `tools/publish_offline.py` — which
    trusts the `"decision"` string in the file it is given, and whose `reconstruct()`
    hardcodes `Decision.PASS` — could carry one incidental supported check and clear a guard
    that the real gate would have KILLed as `moat_ungrounded`. A second, weaker copy of a
    fence is not a backstop; it is a bypass. Same function, same config, same verdict.

    Deliberately attribute-defensive (`getattr`, not `c.verdict.value`): the bridge's caller
    may be a dossier rebuilt from stored JSON, where a malformed check must count as
    ungrounded rather than raise.
    """
    floor = getattr(cfg.thresholds, "min_supported_confidence", None)
    if floor is None:
        floor = getattr(cfg.thresholds, "confidence_floor", None)
    # TYPE TEST, not `try: float(...)`. A non-numeric floor is a broken config, not a licence
    # to crash the publish path — but coercion cannot detect one: `float()` SUCCEEDS on many
    # stand-ins (a unittest MagicMock defines __float__ and returns 1.0), so try/except
    # silently invents a 1.0 confidence bar that rejects every real 0.8 check while reporting
    # a confident "0 grounded-supported check(s)". Only the type answers the question.
    # 0.0 is the DOCUMENTED default (config.py:143), so this degrades to declared behaviour.
    if isinstance(floor, bool) or not isinstance(floor, (int, float)):
        floor = 0.0
    else:
        floor = float(floor)

    # An EMPTY decisive set is not "no requirement" — it makes `moat_grounded >= 1`
    # unsatisfiable, so every candidate KILLs as moat_ungrounded however well grounded it is.
    # That is precisely the structural unreachability config.py:150-154 records from the
    # Martyn's Law incident (2026-06-28). A declaration that yields nothing usable falls back
    # to the documented default, which still enforces source-or-die.
    declared = getattr(cfg.thresholds, "moat_critical_checks", None)
    try:
        moat_checks = tuple(str(x) for x in declared) if declared is not None else ()
    except TypeError:
        moat_checks = ()
    if not moat_checks:
        moat_checks = ("value_durability", "incumbency")

    def _supported(c) -> bool:
        if getattr(getattr(c, "verdict", None), "value", None) != "supported":
            return False
        try:
            return float(getattr(c, "confidence", 0.0) or 0.0) >= floor
        except (TypeError, ValueError):
            return False

    n_supported = sum(1 for c in checks if _supported(c))
    moat_grounded = sum(1 for c in checks
                        if getattr(c, "check_name", None) in moat_checks and _supported(c))
    return n_supported, moat_grounded, moat_checks


def build_dossier(
    cand: Candidate,
    checks: list[CheckResult],
    adversarial: Optional[AdversarialResult],
    gate_fired: Optional[str],
    score: Optional[ScoreResult],
    cfg,                          # Config — typed loosely to avoid circular import issues
    op_model_version: str,
    provider_chain: str = "",
    created_at: str = "",
    reverify_due_at: Optional[str] = None,
) -> Dossier:
    """Assemble a Dossier from pre-computed artefacts.

    Decision logic:
      - gate_fired is not None  -> Decision.KILL (hard gate or adversarial).
      - score passes composite  -> Decision.PASS.
      - otherwise               -> Decision.KILL with gate_fired="min_composite".

    The caller is responsible for computing `score` whenever gate_fired is None
    (i.e., the candidate survived all hard gates and needs ranking).
    """
    if gate_fired in (DEFER_GATE, "moat_exhausted"):
        # Not a kill: a decisive check could not be retrieved or the moat was unavailable.
        # Park the candidate for re-vet — never publish, never count as an evidentiary kill.
        decision = Decision.DEFER
        failed = next((c for c in checks if getattr(c, "retrieval_failed", False)), None)
        if gate_fired == "moat_exhausted":
            reason = ("Deferred — moat (verdict / adversarial pass) was unavailable "
                      "(Claude + Gemini exhausted).  NOT an evidentiary kill; re-vet when "
                      "moat recovers.  Candidate will auto-resume on next `vet --resume`.")
        else:
            cn = failed.check_name if failed else "a decisive gate"
            reason = (f"Deferred — could not retrieve evidence for '{cn}' "
                      f"(retrieval/infra failure). NOT an evidentiary kill; re-vet when "
                      f"retrieval is healthy.")
        gate_fired = None  # no real gate fired; keep the audit honest
    elif gate_fired is not None:
        decision = Decision.KILL
        # Plain-English reason with the internal gate name kept for audit.
        # adaptive.py strips on the first ":" — keep that contract so the
        # substance after the colon still feeds generation feedback.
        failing = next((c for c in checks if c.check_name == gate_fired), None)
        labelled = _labelled(gate_fired, _CHECK_LABEL)
        if failing is not None:
            reason = (
                f"It failed on: {labelled} — "
                f"{failing.verdict.value} (conf {failing.confidence:.2f}): "
                f"{failing.rationale}"
            )
        elif gate_fired == "adversarial_decisive":
            adv_text = adversarial.kill_case if adversarial else "the case against it was decisive"
            reason = f"It failed on: {labelled} — {adv_text}"
        elif gate_fired == "moat_ungrounded":
            moat_checks = tuple(getattr(cfg.thresholds, "moat_critical_checks",
                                        ("value_durability", "incumbency")))
            reason = (f"It failed on: {labelled} — no publish-critical check "
                      f"({', '.join(moat_checks)}) was grounded-supported. "
                      f"Source-or-die: refuse to publish without grounded evidence "
                      f"on the lane's decisive dimension.")
        elif gate_fired == "source_or_die":
            floor = getattr(cfg.thresholds, "min_supported_confidence", None)
            if floor is None:
                floor = cfg.thresholds.confidence_floor
            min_supported = getattr(cfg.thresholds, "min_supported_to_pass", 1)
            n_supported = sum(1 for c in checks
                              if c.verdict.value == "supported" and c.confidence >= floor)
            reason = (f"It failed on: {labelled} — only {n_supported} "
                      f"grounded-supported check(s) (need {min_supported}). "
                      f"Source-or-die: refuse to publish on unverifiable evidence.")
        elif gate_fired == "min_composite":
            reason = (f"It failed on: {labelled} — even the theoretical maximum "
                      f"composite cannot clear "
                      f"{cfg.thresholds.min_composite_to_pass}.")
        else:
            reason = f"It failed on: {labelled}."
    elif score is not None and passes_composite(score, cfg):
        # SOURCE-OR-DIE at the pass boundary. Clearing the composite is necessary but NOT
        # sufficient: the scorer rules on the candidate narrative and will happily score an
        # ungrounded idea highly. A PASS must rest on actual grounded evidence, or we are
        # "publishing on silence" — forbidden (CLAUDE.md: verdict-from-retrieval-only;
        # publish only on PASS). This is the exact class that minted 9 ungrounded "passes"
        # during the 2026-06-16 grounding outage (every check unverifiable, conf 0.0, 0
        # sources, yet composite 2.95 -> PASS). A genuine retrieval OUTAGE is caught upstream
        # (DEFER_GATE) and never reaches here; reaching here with no support means we looked
        # and found nothing to stand on.
        # PASS-SIDE floor: a SUPPORTED check only counts as grounded toward a PASS when its
        # confidence clears min_supported_confidence. Decoupled from confidence_floor (the
        # kill-side lever) so tightening passes never loosens kills. Falls back to
        # confidence_floor, then 0.0, for configs that predate the split.
        min_supported = getattr(cfg.thresholds, "min_supported_to_pass", 1)
        n_supported, moat_grounded, moat_checks = grounded_support(checks, cfg)
        # PUBLISH-CRITICAL requirement: at least one lane-declared decisive check must be
        # grounded-supported. The check set is LANE-AWARE (cfg.thresholds.moat_critical_checks)
        # so each lane requires its OWN headline evidence (smb: payer_solvency; side_hustle:
        # buyer_intent; venture/default: value_durability/incumbency). Hardcoding the venture moat
        # here made the smb/side_hustle PASS path structurally unreachable — those lanes never run
        # value_durability/incumbency (PROVEN 2026-06-28, Martyn's Law composite 2.95 KILLed on
        # moat_ungrounded). This still enforces source-or-die — a candidate cannot publish unless
        # the lane's decisive dimension is grounded in fetched evidence — it asks the RIGHT one.
        # (both counts come from `grounded_support` above — see its docstring.)
        if n_supported >= min_supported and moat_grounded >= 1:
            decision = Decision.PASS
            reason = (f"Survived all gates; composite {score.composite:.4f}; "
                      f"{n_supported} grounded-supported check(s) "
                      f"(moat grounded: {moat_grounded}).")
        elif moat_grounded < 1:
            decision = Decision.KILL
            gate_fired = "moat_ungrounded"
            reason = (f"Composite {score.composite:.4f} cleared the bar but no publish-critical "
                      f"check ({', '.join(moat_checks)}) was grounded-supported. "
                      f"Source-or-die: refuse to publish without grounded evidence on the lane's "
                      f"decisive dimension.")
        else:
            decision = Decision.KILL
            gate_fired = "source_or_die"
            reason = (f"Composite {score.composite:.4f} cleared the bar but only "
                      f"{n_supported} grounded-supported check(s) (need {min_supported}). "
                      f"Source-or-die: refuse to publish on unverifiable evidence.")
    else:
        # Composite below threshold (or score missing unexpectedly)
        decision = Decision.KILL
        gate_fired = "min_composite"
        comp = score.composite if score else 0.0
        reason = (
            f"It failed on: {_labelled('min_composite', _CHECK_LABEL)} — "
            f"composite {comp:.4f} below the bar of "
            f"{cfg.thresholds.min_composite_to_pass}."
        )

    # Provisional rollup: the decision is real but untrusted if ANY ruling that fed it
    # was served by the cheap emergency fallback tail (moat exhausted). A degraded/
    # deferred check never ruled, so it carries provisional=False and a DEFER stays
    # non-provisional. A provisional PASS will not publish; both PASS and KILL auto
    # re-vet on the next `vet --resume`.
    provisional = any(getattr(c, "provisional", False) for c in checks) or \
        bool(adversarial is not None and getattr(adversarial, "provisional", False))

    return Dossier(
        candidate=cand,
        decision=decision,
        gate_fired=gate_fired,
        reason=reason,
        checks=checks,
        adversarial=adversarial,
        score=score,
        model_version=op_model_version,
        provider_chain=provider_chain,
        persona=cfg.active_persona,
        created_at=created_at,
        reverify_due_at=reverify_due_at,
        provisional=provisional,
    )


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

_VERDICT_EMOJI = {
    "supported": "✅",
    "refuted": "❌",
    "unverifiable": "⚠️",
}

_VERDICT_LABEL = {
    "supported": "Yes — the sources back this",
    "refuted": "No — the sources contradict this",
    "unverifiable": "Can't tell — the sources don't say",
}

# A plain-English question for each check, for the person reading the dossier. The
# CHECKS text in models.py stays as it is: that is the verifier's contract with the
# moat, and rewording it would change what actually gets ruled on. This is a label.
_CHECK_LABEL = {
    "pain_reality": "Is the problem real?",
    "value_durability": "Will this still be worth money later?",
    "incumbency": "Is someone already doing this well?",
    "payer_solvency": "Can the customer afford it?",
    "distribution": "Can you actually reach the customer?",
    "legality": "Is it legal?",
    "buyer_intent": "Are people already looking for this?",
    "route_to_market": "Could a beginner reach buyers?",
    "currency": "Is this live right now?",
    "claims_verifiable": "Can the claims be checked?",
    "adversarial_decisive": "The case against it was decisive",
    "min_composite": "The overall score was too low",
    "moat_ungrounded": "The decisive checks weren't backed by evidence",
    "source_or_die": "Not enough grounded evidence to publish",
    DEFER_GATE: "We couldn't fetch enough evidence to rule",
}

# Legacy dossiers still carry a "Gate 'x' fired — " prefix. Strip it for the
# reader; new reasons are already plain English (see build_dossier).
_GATE_PREFIX = re.compile(r"^Gate '[^']+' fired(?: — |\.\s*)")

_AXIS_LABEL = {
    "pain_acuity": "How badly it hurts",
    "money_provability": "How provable the money is",
    "distribution": "How easy buyers are to reach",
    "defensibility": "How hard it is to copy",
    "build_feasibility": "How buildable it is",
    "automatability": "How much one person can automate",
}

_DECISION_BADGE = {
    Decision.PASS: "## ✅ PASS",
    Decision.KILL: "## ❌ KILL",
    Decision.DEFER: "## ⏸️ DEFER — no verdict yet",
}

_DECISION_GLOSS = {
    Decision.PASS: ("This cleared every check we hold it to, on evidence we fetched "
                    "and cited below."),
    Decision.KILL: "We stopped on this one. The reason and the evidence are below.",
    Decision.DEFER: ("We could not fetch enough evidence to rule either way, so this "
                     "waits for another run. Not knowing is not the same as a no."),
}


def _verdict_of(chk: Any) -> str:
    """A check's verdict as a plain lowercase string, whichever shape it arrived in.

    Two loaders reach this renderer: `run.py` builds `CheckResult` with a `Verdict` enum,
    while `pack_manifest.dossier_from_dict` leaves the raw string. `chk.verdict.value`
    raises `AttributeError` on the second — so a caller that loaded a stored dossier could
    not render it at all, and any code that fell back to a default would silently grade
    every check as unknown. One reader, both shapes.
    """
    # 2026-08-15: `chk.verdict` was still read bare here even though the docstring above is
    # entirely about the second shape. A stored check whose JSON never carried a `"verdict"`
    # key has no such attribute at all — `_ns` (pack_manifest.py:356) builds attributes from
    # dict keys and nothing else — so this raised `AttributeError` and took the whole render
    # with it rather than grading one check unknown.
    raw = getattr(chk, "verdict", "")
    return str(getattr(raw, "value", raw) or "").strip().lower()


def _mapping(obj: Any) -> dict:
    """A dict-shaped field as a real dict, whichever shape it arrived in.

    The same lesson as `_verdict_of`, on the other kind of field. `pack_manifest._ns`
    (`pack_manifest.py:354`) descends into every dict it meets, so a field whose KEYS are
    data rather than field names — `score.scores`, `score.justification`, a refinement
    entry's `before` — comes back from a stored dossier as a `SimpleNamespace`, and
    `.items()` / `.get()` on it raise. That is why every stored PASS dossier was
    unrenderable, and so unreachable for a re-render of the pack it was sold with.

    Read it here rather than teaching `_ns` which dicts are data: `_ns` sees only a dict
    and cannot tell the two apart, while the renderer knows exactly which fields are maps.
    One reader, both shapes.
    """
    if isinstance(obj, dict):
        return obj
    return dict(vars(obj)) if hasattr(obj, "__dict__") else {}


def check_label(name: str) -> str:
    """The buyer-facing question a check answers. Public because `pack_reference` renders the
    same checks into the consolidated evidence document, and two label maps is how the QA
    report and the reference document come to call the same check different things."""
    return _CHECK_LABEL.get(str(name or ""), str(name or "").replace("_", " ").strip().capitalize())


def _pass_gloss(dossier: Dossier) -> str:
    """The PASS banner, counted from the verdicts rather than asserted.

    Fixed 2026-08-14. The banner used to read "This cleared every check we hold it to" on
    every PASS, unconditionally — and pack `8d5e24fbe6c1f5d3` shipped that sentence three
    screens above `❌ Is the problem real? No — the sources contradict this`. The claim was
    false in every lane that RUNS more checks than it GATES on, which is by design: the
    `side_hustle` lane gates on four checks (`config.yaml:447-451`) and scores the rest
    (`:538-541`). The lane held it to four and the page claimed eight.

    We do not resolve that by hiding the negatives. The store's whole proposition is that
    the checks are real and published, so a buyer who finds a ❌ under a blanket PASS has
    caught us overselling — and the kill log, the best asset we have, becomes a joke. The
    banner now states the split and points at the dissent, which is the version the founder
    approved on sight (2026-08-13): "Two of eight checks came back against this idea. We
    are still selling you the kit."
    """
    checks = list(getattr(dossier, "checks", None) or [])
    if not checks:
        return _DECISION_GLOSS[Decision.PASS]
    total = len(checks)
    against = [c for c in checks if _verdict_of(c) == Verdict.REFUTED.value]
    unclear = [c for c in checks if _verdict_of(c) == Verdict.UNVERIFIABLE.value]
    passed = total - len(against) - len(unclear)
    if passed == total:
        return ("This cleared every one of the "
                f"{total} checks we hold it to, on evidence we fetched and cited below.")

    def _names(items: list[Any]) -> str:
        labels = [f"“{check_label(getattr(c, 'check_name', '') or '')}”" for c in items]
        if len(labels) == 1:
            return labels[0]
        return ", ".join(labels[:-1]) + " and " + labels[-1]

    def _count(n: int, verb_one: str, verb_many: str) -> str:
        return f"One {verb_one}" if n == 1 else f"{n} {verb_many}"

    parts = [f"**Passed {passed} of {total} checks.**"]
    if against:
        parts.append(f"{_count(len(against), 'came', 'came')} back against it "
                     f"— {_names(against)}.")
    if unclear:
        parts.append(f"{_count(len(unclear), 'could', 'could')} not be settled either way "
                     f"— {_names(unclear)}.")
    parts.append("We are listing it anyway, and every verdict below is shown in full, so "
                 "you can disagree with us before you spend anything.")
    return " ".join(parts)


def _source_index(dossier: Dossier) -> dict[str, Any]:
    """Every retrieved Source in the dossier, keyed by the id the checks cite it as.

    Built dossier-wide rather than per-check because the adversarial pass carries
    `citations` and no `sources` of its own (`models.py:286-295`) — its ids are only
    resolvable against the checks' passages.
    """
    index: dict[str, Any] = {}
    for chk in (getattr(dossier, "checks", None) or []):
        for src in (getattr(chk, "sources", None) or []):
            sid = getattr(src, "source_id", "")
            if sid and sid not in index:
                index[sid] = src
    return index


def _host(url: str) -> str:
    from urllib.parse import urlsplit
    host = (urlsplit(str(url or "")).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


# TWO OBJECT SHAPES REACH THIS RENDERER, AND ONLY ONE OF THEM HAS FIELDS — 2026-08-15
# ----------------------------------------------------------------------------------
# `run.py` hands `render_markdown` a live `models.Dossier`, where every field exists because
# the dataclass declares it and a missing value is a declared default. The backfill hands it
# `pack_manifest.dossier_from_dict`, whose `_ns` (pack_manifest.py:356) builds a
# `SimpleNamespace` out of dict KEYS alone: a key that was never written to
# `store/dossiers/<id>.json` is not a `None` field, it is an attribute that does not exist.
#
# The failure that produced these helpers: a stored source object with no `"url"` key made
# `render_markdown` raise `AttributeError: 'types.SimpleNamespace' object has no attribute
# 'url'` at the source appendix, and because a raise unwinds the whole function, the buyer's
# pack lost all fourteen sections — not the one line that had nothing to print. A renderer
# that cannot print a field should print less, never nothing.
#
# `all_sources` and `dense_reward` are the sharpest edge: they are PROPERTIES on the
# dataclass, so `Dossier.to_dict` never wrote them and no stored dossier can ever carry
# them. Reading `dossier.all_sources` was therefore not an edge case on the stored path, it
# was guaranteed. `_all_sources` re-derives the same distinct-by-URL list the property
# computes, so both shapes get the appendix.
#
# `scores` and `justification` are the other one: JSON objects become `SimpleNamespace`, not
# `dict`, so `sc.scores.items()` raised on every stored dossier that had a score at all.


def _mapping(obj: Any) -> dict:
    """A JSON object as a dict, whether it arrived as one or as a `SimpleNamespace`."""
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "__dict__"):
        return dict(vars(obj))
    return {}


def _num(value: Any, default: float = 0.0) -> float:
    """A stored number that arrived as a string, or as nothing at all, still formats."""
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _all_sources(dossier: Any) -> list[Any]:
    """`Dossier.all_sources` when the object has it; the same list re-derived when it cannot.

    Distinct by URL, first occurrence wins — the definition `models.distinct_sources` uses,
    kept identical here so the appendix a backfilled pack renders is the appendix a freshly
    generated one renders.
    """
    existing = getattr(dossier, "all_sources", None)
    if existing:
        return list(existing)
    out: list[Any] = []
    seen: set[str] = set()
    for chk in (getattr(dossier, "checks", None) or []):
        for src in (getattr(chk, "sources", None) or []):
            url = str(getattr(src, "url", "") or "")
            if not url or url in seen:
                continue
            seen.add(url)
            out.append(src)
    return out


#: What the engine actually does, in the words a buyer reads. It lives here as a constant
#: because TWO surfaces render it: `render_markdown` for every new pack, and
#: `rewrite_legacy_shelf_life` for the packs already on sale. Two copies of a promise is how a
#: backfilled pack comes to promise something different from a freshly generated one.
SHELF_LIFE_POLICY = (
    "We re-check the evidence behind this pack every 30 days. The date above is when we look "
    "again, not a date this stops being true. If a check no longer holds up, we take the pack "
    "off sale rather than leave it quietly going out of date."
)

#: The line as it shipped, on 62 of 62 live packs (censused 2026-08-14 against R2). The prose
#: pass left it verbatim, which is what makes a surgical rewrite of already-sold bundles safe.
_LEGACY_SHELF_LIFE_RE = re.compile(
    r"^-[ \t]+\*\*Evidence goes stale after:\*\*[ \t]*(?P<stamp>\S+)[ \t]*$", re.M)


def shelf_life_lines(reverify_due_at: str) -> list[str]:
    """The footer's freshness block, or nothing at all when there is no SLA stamp.

    Silence is the correct output for a pack with no stamp: an invented date would be a promise
    no sweep is behind.
    """
    stamp = _date_only(reverify_due_at)
    if not stamp:
        return []
    return [f"- **Next evidence check:** {stamp}", "", SHELF_LIFE_POLICY]


def rewrite_legacy_shelf_life(markdown: str) -> Optional[str]:
    """Replace the old expiry line in an ALREADY-SHIPPED report, or None if it isn't there.

    A live bundle's .md files are the deliverables of record and the backfill copies them
    byte-identical; this is the one deliberate exception, and it is narrow on purpose. It
    matches one exact line, rewrites it into the same text a new pack renders, and touches
    nothing else — so a pack that was already corrected returns None and is not rewritten twice.
    """
    if not _LEGACY_SHELF_LIFE_RE.search(markdown or ""):
        return None

    def _sub(m: re.Match) -> str:
        return "\n".join(shelf_life_lines(m.group("stamp")))

    return _LEGACY_SHELF_LIFE_RE.sub(_sub, markdown)


def _date_only(stamp: str) -> str:
    """`2026-08-31T00:41:12.904331+00:00` is a machine stamp, not a date a buyer reads.

    Kept lenient on purpose: an unparseable value is printed as it stands rather than dropped,
    because a missing date in the footer is a worse failure than an ugly one.
    """
    text = str(stamp or "").strip()
    return text[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", text) else text


def _cited(ids: list[str], index: dict[str, Any]) -> str:
    """Render citation ids as something a buyer can actually open.

    Fixed 2026-08-14, and the reason is worth keeping. This line used to be
    ``", ".join(f"`{c}`" for c in citations)`` — the raw 16-hex passage id in backticks —
    and every one of the 62 live packs rendered it as ``Sources used: , , , , , ,``,
    because `plain_text._BARE_ID` strips bare hex ids from prose and did not exempt a code
    span. That is now fixed at the regex, but restoring the ids would only have restored
    `1e62e0c381e1c8d3`, which tells a buyer nothing. An internal passage id is not a
    receipt. The domain, linked, is.

    Unresolvable ids keep their raw form: this is an audit document and losing the pointer
    is worse than showing an ugly one.
    """
    out: list[str] = []
    seen: set[str] = set()
    for cid in ids:
        src = index.get(cid)
        url = getattr(src, "url", "") if src is not None else ""
        if not url:
            if cid not in seen:
                seen.add(cid)
                out.append(f"`{cid}`")
            continue
        key = url.split("#", 1)[0]
        if key in seen:
            continue
        seen.add(key)
        out.append(f"[{_host(url) or url}]({url})")
    return ", ".join(out)


#: A model writes its citations into the rationale as `[c21b2c84c437b383, c666011f1509e3cc]`.
#: In the QA report those never reach a buyer: the bundle's prose pass strips bare hex ids
#: (`plain_text._BARE_ID`) and the paragraph reads cleanly (censused 2026-08-14 over 62 live
#: packs: zero `[]` or `[, ,]` residue in prose). `pack_reference` renders the SAME rationale
#: text with no prose pass at all — deterministic, zero model calls, which is what lets it be
#: backfilled — so it has to turn the ids into links itself rather than inherit a strip that
#: does not run on its path.
_INLINE_ID_GROUP = r"\[(?:[0-9a-f]{16})(?:\s*,\s*[0-9a-f]{16})*\]"

#: A RUN of adjacent groups, `[id][id][id]`, matched as ONE citation rather than three.
#:
#: The verdict brains write one bracket per passage, so a clause backed by three passages left
#: this in the pack, rendered and read on /sample for 13d41ccee9e96e2d on 2026-08-15::
#:
#:     ...integrates with accounting/ERP systems (payapps.com)(pbctoday.co.uk)(capterra.com), and
#:
#: Three parenthesised hosts butted together read as a broken template, not as three citations —
#: the same impression as a raw hex blob, arrived at from the other direction. Matching the run
#: gives `_cited` all three ids at once and it joins them with its own ", ".
_INLINE_IDS_RE = re.compile(rf"(?:{_INLINE_ID_GROUP})+")
_INLINE_ID_ONE = re.compile(r"[0-9a-f]{16}")

#: A citation cut off mid-id at the very end of the text: `[c33885f45` with no closing bracket
#: and nothing after it.
#:
#: This is not a rendering fault — it is what the dossier holds. The `incumbency` rationale on
#: 13d41ccee9e96e2d ends literally `...chasing retention on its due date in the UK [c33885f45`,
#: a verdict truncated mid-citation upstream, and every renderer downstream printed it verbatim
#: because the pattern above requires a full 16 hex digits and a closing bracket.
#:
#: `_cited`'s rule — "an ugly pointer beats a missing one" — is about an id that resolves to
#: nothing YET; it is still a pointer, and someone auditing the run can look it up. Nine hex
#: digits with no terminator is not a pointer to anything, and on a page whose argument is that
#: every claim is traceable, a half-written citation is worse than none: it looks fabricated.
#: The clause it was attached to is real and stays; only the stub goes, and the sentence gets
#: the full stop the truncation took.
_TRUNCATED_TAIL = re.compile(r"\s*\[[0-9a-f]{0,15}\s*$")


def link_inline_citations(text: str, index: dict[str, Any]) -> str:
    """Rewrite inline passage-id brackets into links a buyer can open.

    An id that resolves to nothing keeps its raw form via `_cited`: this is an audit document,
    and an ugly pointer beats a missing one. An id TRUNCATED mid-write is dropped instead — see
    `_TRUNCATED_TAIL`, which is the one case where there is no pointer left to preserve.
    """
    def _sub(m: "re.Match[str]") -> str:
        rendered = _cited(_INLINE_ID_ONE.findall(m.group(0)), index)
        return f"({rendered})" if rendered else ""

    body = str(text or "")
    trimmed = _TRUNCATED_TAIL.sub("", body)
    if trimmed != body and trimmed and trimmed[-1].isalnum():
        trimmed += "."
    return _INLINE_IDS_RE.sub(_sub, trimmed)


def source_index(dossier: Any) -> dict[str, Any]:
    """Public alias for `_source_index`, so `pack_reference` need not reach into a private."""
    return _source_index(dossier)


def _labelled(name: str, labels: dict[str, str]) -> str:
    """Plain label with the internal name kept alongside it. The token stays because a
    dossier is an audit document: someone has to be able to match this line to a gate
    in config.yaml. Clarity is added, never substituted."""
    label = labels.get(name)
    return f"{label} (`{name}`)" if label else f"`{name}`"


def render_markdown(dossier: Any) -> str:
    """Render a human-readable audit document from a Dossier.

    Both PASS and KILL are first-class: a KILL renders its cited reason prominently.

    Typed `Any` rather than `Dossier` since 2026-08-15, because that is what it has always
    accepted: the backfill renders stored JSON through `pack_manifest.dossier_from_dict`, and
    a signature that named only the dataclass was how the read-it-bare habit kept coming back.
    See the shape note above `_mapping`.
    """
    cand = getattr(dossier, "candidate", None)
    src_index = _source_index(dossier)
    lines: list[str] = []

    # --- Header ---
    #
    # The one-liner used to be repeated here. In a bundle it is the pack's standfirst, printed
    # under the title of section 1; this is section 14. Measured 2026-08-15 on pack
    # e698149e137fc164, it was one of five sentences this document shared with the opening.
    lines.append(f"# {getattr(cand, 'title', '') or 'Untitled'}")
    lines.append("")

    # --- Decision badge (prominent) ---
    #
    # An unrecognised or absent decision prints NO badge rather than a defaulted one. A
    # missing verdict rendered as PASS or KILL would be the renderer inventing the one fact
    # the document exists to report; silence is the only honest fallback here.
    decision = getattr(dossier, "decision", None)
    badge = _DECISION_BADGE.get(decision) if isinstance(decision, (str, Decision)) else None
    if badge:
        lines.append(badge)
        lines.append("")
    gloss = (_pass_gloss(dossier) if decision == Decision.PASS
             else _DECISION_GLOSS.get(decision, "") if badge else "")
    if gloss:
        lines.append(f"_{gloss}_")
        lines.append("")

    # Provisional banner: this verdict was reached by the cheap emergency fallback tail
    # because the trusted moat was exhausted. Real-but-untrusted — never publishes on
    # PASS, auto re-vetted by the moat on the next `vet --resume`.
    if getattr(dossier, "provisional", False):
        lines.append("> ⚠️ **This verdict is not final.** The models we trust to judge "
                     "were unavailable, so a cheaper backup ruled instead. We don't "
                     "trust that enough to publish on. It gets judged again properly "
                     "on the next `vet --resume`.")
        lines.append("")

    # KILL reason gets its own highlighted block
    if decision == Decision.KILL:
        lines.append("> **Why we stopped:**")
        lines.append(f"> {_GATE_PREFIX.sub('', str(getattr(dossier, 'reason', '') or '')).strip()}")
        gate_fired = getattr(dossier, "gate_fired", "")
        if gate_fired:
            lines.append(">")
            lines.append(f"> It failed on: {_labelled(str(gate_fired), _CHECK_LABEL)}")
        lines.append("")

    # --- Candidate details and the refinement diff: BOTH REMOVED 2026-08-15 ---
    #
    # `why_now`, `who_pays` and `hypothesis` were reprinted here under their own headings.
    # In a bundle those three fields ARE sections 1 and 2 of the pack — "Where this starts"
    # and "What you would be selling" — so this document restated the opening a hundred pages
    # later, word for word. `pack_linter.check_repetition` blocks on exactly that now.
    #
    # The refinement diff went for a different reason. It rendered our own generation history:
    # the first draft of the title, the first draft of the one-liner, struck through, with an
    # arrow to what we changed them to. It is a fact about our pipeline having a second pass,
    # it tells a buyer nothing about their market, and it invites them to read a draft we
    # ourselves rejected. The founder's words on 2026-08-15: "we ramble about composite
    # scores, things our engine does that does not concern us". This was the clearest example
    # of it in the pack. `refinement_history` is still on the Candidate and still in the JSON
    # dossier and the audit log, where the record belongs; it is not buyer-facing copy.
    #
    # MERGE NOTE (origin/main, 2026-08-15): main fixed the refinement loop's
    # `entry.get("before", {})` to `_mapping(_mapping(entry).get("before", {}))`, for the same
    # stored-dossier `SimpleNamespace` reason as `_mapping` exists at all. That fix is correct
    # and is deliberately dropped here only because the code it repairs is the code this
    # section removes. If the diff is ever restored, restore it through `_mapping`, twice, as
    # main wrote it — a stored `refinement_history` entry is a namespace and `.get` raises.

    # --- Per-check verdicts ---
    checks = list(getattr(dossier, "checks", None) or [])
    if checks:
        lines.append("---")
        lines.append("## What we checked")
        lines.append("")
        for chk in checks:
            v = _verdict_of(chk)
            emoji = _VERDICT_EMOJI.get(v, "?")
            label = check_label(str(getattr(chk, "check_name", "") or ""))
            verdict = _VERDICT_LABEL.get(v, v)
            lines.append(f"### {emoji} {label}")
            lines.append("")
            # `*(check: `pain_reality`)*` used to be appended here — our schema key, in the
            # buyer's document, next to the answer. The heading above already asks the
            # question in their words; the key only ever named the same thing in ours.
            lines.append(f"**{verdict}.** Confidence {_num(getattr(chk, 'confidence', 0.0)):.2f}.")
            lines.append("")
            if getattr(chk, "degraded", False):
                lines.append("> Some searches failed here, so this rests on thinner "
                             "evidence than usual.")
                lines.append("")
            # THE RATIONALE IS NOT PRINTED HERE. Removed 2026-08-15.
            #
            # It is the single most duplicated text in the pack: `pack_reference` argues the
            # supported checks, `pack_bear_case` argues the refuted and unproven ones,
            # `pack_field` argues incumbency, and `pack_floors` leads on the strongest few.
            # Every one of those is a section a buyer reads for the argument. This section is
            # the one they open to CHECK us, and it was printing all of it a second time —
            # measured on pack e698149e137fc164, this document appeared in 15 of the 17
            # duplicate-sentence pairs left in the pack after every other fix.
            #
            # What it keeps is what nothing else has: the verdict, the confidence, whether the
            # evidence was degraded, and the passages themselves. That is the receipt. The
            # argument is upstairs, and every check's argument has an owner — supported and
            # refuted in the evidence section, unproven in the bear case — so nothing is lost
            # by this document declining to be the fifth place it appears.
            citations = list(getattr(chk, "citations", None) or [])
            if citations:
                rendered = _cited(citations, src_index)
                if rendered:
                    lines.append("**Sources used:** " + rendered)
                    lines.append("")

            # --- Chain-of-Evidence (Contextual Snippets) ---
            chk_sources = list(getattr(chk, "sources", None) or [])
            if chk_sources:
                lines.append("**What those sources said:**")
                for src in chk_sources:
                    # `src.text[:300] + "..."` was a bare character slice, the exact defect
                    # `trimming` exists to end: it produced the QA report's "which still
                    # counts as demon", "which neither confi", "parents of autistic children
                    # spe". `clip_to_sentence` cuts where a human would and marks the cut.
                    snippet = trimming.clip_to_sentence(
                        " ".join(str(getattr(src, "text", "") or "").split()), 300)
                    url = str(getattr(src, "url", "") or "")
                    if not snippet:
                        continue
                    # A passage whose URL was never stored still gets quoted, unlinked. The
                    # quote IS the evidence; dropping it because the pointer is missing would
                    # lose the thing the reader came to check.
                    lines.append(f"- *“{snippet}”* — [{_host(url) or url}]({url})" if url
                                 else f"- *“{snippet}”*")
                lines.append("")

    # --- Adversarial case ---
    adv = getattr(dossier, "adversarial", None)
    if adv:
        lines.append("---")
        lines.append("## The case against")
        lines.append("")
        lines.append("> We argue against every idea on purpose. This is the strongest "
                     "case we could build for walking away.")
        lines.append("")
        lines.append("**Decisive on its own — this is enough to stop the idea.**"
                     if getattr(adv, "decisive", False) else
                     "**Not decisive.** Worth knowing, but it doesn't sink the idea.")
        lines.append("")
        lines.append(str(getattr(adv, "kill_case", "") or ""))
        adv_citations = list(getattr(adv, "citations", None) or [])
        if adv_citations:
            rendered = _cited(adv_citations, src_index)
            if rendered:
                lines.append("")
                lines.append("**Sources used:** " + rendered)
                lines.append("")

    # --- Scores table (PASS only, but render for KILLs that have a score too) ---
    sc = getattr(dossier, "score", None)
    if sc:
        lines.append("---")
        lines.append("## How it scored")
        lines.append("")
        lines.append(f"**Overall: {_num(getattr(sc, 'composite', 0.0)):.4f}** "
                     f"(each line is rated out of 5, then weighted)")
        lines.append("")
        lines.append("| What we rated | Score | Why |")
        lines.append("|---------------|------:|-----|")
        justification = _mapping(getattr(sc, "justification", None))
        for ax, val in _mapping(getattr(sc, "scores", None)).items():
            just = justification.get(ax, "")
            lines.append(f"| {_labelled(ax, _AXIS_LABEL)} | {val}/5 | {just} |")
        lines.append("")

    # PASS reason
    pass_reason = str(getattr(dossier, "reason", "") or "").strip()
    if decision == Decision.PASS and pass_reason:
        lines.append("---")
        lines.append("## Why this passed")
        lines.append("")
        lines.append(pass_reason)
        lines.append("")

    # --- All sources ---
    # The module function, not the `Dossier.all_sources` property: a stored record arrives
    # here as a `pack_manifest._ns` tree with no properties at all, and `distinct_sources`
    # exists (models.py:396) precisely so both shapes yield the same dedup. Reached through
    # `_all_sources` so `checks` is read with a default too — a stored dossier whose JSON
    # never carried the key has no such attribute at all, and `dossier.checks` raises.
    all_src = _all_sources(dossier)
    if all_src:
        lines.append("---")
        lines.append("## Every source we used")
        lines.append("")
        # Which questions each source was used to answer.
        #
        # This appendix used to reprint every source's passage a SECOND time, as a block quote
        # under its heading, having already printed it in the "What those sources said" list of
        # whichever check cited it. `all_sources` is `models.distinct_sources(checks)`, so that
        # was true of every entry without exception — measured on pack e698149e137fc164 on
        # 2026-08-15, the QA section alone was 5,082 words, 35.7% of the whole pack, and its
        # own largest component was this appendix quoting text the reader had already read.
        #
        # A back-reference is what the appendix is actually for: the per-check lists answer
        # "what does this check rest on", and this answers the other direction — "I have opened
        # this page, what did you use it for". Neither is now a copy of the other.
        used_by: dict = {}
        for chk in checks:
            label = check_label(getattr(chk, "check_name", "") or "")
            for s in getattr(chk, "sources", None) or []:
                s_url = str(getattr(s, "url", "") or "")
                if not s_url:
                    continue
                seen_for = used_by.setdefault(s_url, [])
                if label and label not in seen_for:
                    seen_for.append(label)
        archived_any = any(getattr(s, "archived_url", None) for s in all_src)
        lines.append("Every claim above traces back to one of these. Follow any of "
                     "them and check us."
                     + (" Where a page has since moved or gone, the archived copy is the "
                        "same text we read, captured on the day we read it."
                        if archived_any else ""))
        lines.append("")
        for n, src in enumerate(all_src, 1):
            url = str(getattr(src, "url", "") or "")
            published_at = getattr(src, "published_at", "")
            pub = f" ({published_at})" if published_at else ""
            # What KIND of page this is, in the buyer's words. Every entry here was rendered
            # identically — same heading, same quote block — so a Pinterest board and a CDC
            # page read as equals, and `8d5e24fbe6c1f5d3` shipped exactly that pair. The tier
            # is already computed for the admissibility gate; printing it is free, and it is
            # the difference between "33 links" and "here is what each link is". Blank for the
            # unaudited `other` tier, because a label there would be a claim we cannot support.
            provenance = admissibility.provenance_label(url)
            # Headed by host, not `source_id`. The id is ours — a 16-hex internal key means
            # nothing to a buyer, and it is the same string that leaked into the prose above.
            lines.append(f"### {n}. {_host(url) or url or 'Source (no URL recorded)'}"
                         + (f" — {provenance}" if provenance else ""))
            if url:
                lines.append(f"**URL:** [{url}]({url}){pub}")
            # The second pointer. `url` is the part that rots (measured 2026-08-09: 12 of 14
            # dead citations were genuinely gone), `text` below is the evidence and never
            # does. Rendering the memento is what stops "follow any of them and check us"
            # from quietly becoming false a year after the sale.
            archived = getattr(src, "archived_url", None)
            if archived:
                fetched_at = getattr(src, "fetched_at", "")
                fetched = fetched_at if isinstance(fetched_at, str) else ""
                on = f", as retrieved {fetched[:10]}" if fetched else ""
                lines.append(f"**Archived copy:** [permanent snapshot]({archived}){on}")
            answers = used_by.get(url) or []
            if answers:
                lines.append("**Used to answer:** " + "  ".join(answers))
            lines.append("")

    # --- Metadata footer ---
    lines.append("---")
    lines.append("## Run details")
    lines.append("")
    persona = getattr(dossier, "persona", "")
    if persona:
        lines.append(f"- **Persona:** {persona}")
    # `Judged by:` is deliberately NOT rendered. It printed `dossier.model_version`, which for
    # a chained operator is `fallback(cursor_cli+claude_cli+minimax)` (`operator.py:1272`) —
    # so the buyer was shown our internal failover chain, told the judge was a "fallback",
    # and handed a name (`cursor_cli`) deleted from this repo on 2026-08-06, which also dates
    # the pack. It stays in the JSON dossier and the audit log, where it belongs; a buyer
    # needs to know the evidence, not our provider routing.
    if getattr(cand, "market", ""):
        lines.append(f"- **Market:** {cand.market}")
    lines.append(f"- **Pack reference:** `{getattr(cand, 'candidate_id', '') or 'unknown'}`")
    lines.append(f"- **Created:** {getattr(dossier, 'created_at', '') or ''}")
    # This used to print `Evidence goes stale after: <date>`, which is `reverify_due_at`
    # (created_at + 30 days, `run.py:813`) — an INTERNAL scheduling stamp telling the decay
    # sweep when to look again. Printed in the buyer's copy it reads as a shelf life we never
    # priced: someone buying on day 28 is told they have three days left. What actually
    # happens is better than the promise, so we say that instead: the sweep re-runs the same
    # checks (`scheduler/run_scheduled.py:714` → `run.run_decay_sweep`), and a re-vet that
    # now fails a hard gate queues the pack for withdrawal (`decay.py::_queue_unlist`), while
    # a re-vet that could not look (DEFER) changes nothing.
    lines.extend(shelf_life_lines(getattr(dossier, "reverify_due_at", "") or ""))
    lines.append("")

    return "\n".join(lines)
