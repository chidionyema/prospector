"""How long a pack may be is a function of the evidence it holds, not a constant.

Measured 2026-08-14 across the live catalogue (`store/dossiers/*.pass.json`, n=59 for
prose, n=75 for evidence): the three prose artifacts carried a median 3,566 words,
written from a median 4,807 characters — roughly 800 words — of retrieved passage text.
A 4.5x inflation. The prompt asked for "several titled sections ... substantial (many
paragraphs)" with no ceiling and no floor on what a sentence had to carry, so the model
filled the gap the only way a model can: connective prose that asserts nothing. 78.3% of
its sentences contained no number, price or percentage.

That is the cause of the register complaint. "Reads like an LLM" is what prose looks like
when it has to occupy length without information, so banning the words only changes the
words. The fix is upstream: give the writer a word ceiling derived from the evidence it
actually holds, and no minimum at all.

This module computes that contract. It is pure arithmetic over the checks — no model call,
no I/O — so the number injected into the prompt and the number reported by the sweep are
the same number, and a change to one cannot silently miss the other.

Nothing here blocks a listing. Over-length is not a truth defect, and a gate that unlists
a pack for being long would be a worse product than the one it protects. The ceiling
removes the model's REASON to pad; the claim-check on the artifacts removes its ABILITY
to pad with unsupported statements. Those are separate mechanisms and only the second one
is a gate.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

# The prose artifacts this budget governs. `financial_model` is excluded on purpose: it is
# a JSON fill that Python renders into arithmetic (`artifacts._render_financial_model`),
# so its length is a property of the template, not of the model's restraint.
PROSE_TYPES: Tuple[str, ...] = ("build_spec", "gtm_plan", "ops_plan")

_WORD = re.compile(r"[A-Za-z0-9£$€%][A-Za-z0-9£$€%'\-.,/]*")


def _words(text: Any) -> int:
    return len(_WORD.findall(str(text or "")))


def _as_dict(obj: Any) -> Dict[str, Any]:
    """Accept a CheckResult, a Source, or the dict either becomes.

    Call sites differ: `generate_artifacts` holds CheckResult objects, the sweep tools
    hold the JSON they were serialised to. One reader, both shapes — the alternative is
    two readers that drift, which is a defect class this repo has already paid for.
    """
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "to_dict"):
        try:
            return dict(obj.to_dict())
        except Exception:
            pass
    return {k: v for k, v in vars(obj).items() if not k.startswith("_")} if hasattr(obj, "__dict__") else {}


def _is_supported(check: Dict[str, Any]) -> bool:
    verdict = check.get("verdict")
    name = getattr(verdict, "value", verdict)
    return str(name or "").strip().lower().endswith("supported")


def _passages(checks: Iterable[Any]) -> List[Tuple[str, str, bool]]:
    """Every retrieved passage as ``(key, text, from_supported_check)``, deduped by source.

    Deduping matters: the same page is commonly cited by three checks, and counting it
    three times would buy the model three times the words for one piece of evidence.
    """
    seen: Dict[str, Tuple[str, str, bool]] = {}
    for raw in checks or []:
        check = _as_dict(raw)
        supported = _is_supported(check)
        for src_raw in (check.get("sources") or []):
            src = _as_dict(src_raw)
            text = str(src.get("text") or "").strip()
            if not text:
                continue
            key = str(src.get("source_id") or src.get("url") or text[:80])
            prior = seen.get(key)
            if prior is None:
                seen[key] = (key, text, supported)
            elif supported and not prior[2]:
                # A passage reachable from a supported finding counts as supported
                # evidence even if an unverifiable check also cited it.
                seen[key] = (key, prior[1], True)
    return list(seen.values())


def evidence_profile(checks: Iterable[Any]) -> Dict[str, int]:
    """What the writer actually holds, in words.

    ``words`` is the material behind SUPPORTED findings — the only evidence the artifact
    prompt is given today. ``words_all`` includes passages retrieved for checks that came
    back unverifiable; those are real retrieved text about a real market, and 38% of the
    corpus by volume, but they sit behind their own config flag because handing them to
    the writer without a label invites a pack that presents unverified material as vetted.
    """
    passages = _passages(checks)
    supported = [p for p in passages if p[2]]
    return {
        "words": sum(_words(t) for _k, t, _s in supported),
        "sources": len(supported),
        "words_all": sum(_words(t) for _k, t, _s in passages),
        "sources_all": len(passages),
    }


def pack_word_budget(evidence_words: int, *, base: int, ratio: float,
                     floor: int, ceiling: int) -> int:
    """Total prose words a pack may ask for, across all three prose artifacts.

    ``base`` is the allowance for operational judgement that is legitimately NOT in any
    source — the sequencing, the stop conditions, the "make fifteen by hand before you
    write code" instruction the founder singled out as the best thing in the pack on
    2026-08-13. That content is the product, and a budget purely proportional to retrieved
    text would price it at zero. ``ratio`` prices the part that restates evidence.

    ``floor`` keeps a pack whose retrieval went badly from collapsing to a stub that the
    existing anti-stub gate (`pack_validation.MIN_PROSE_CHARS`) would reject anyway.
    """
    raw = float(base) + float(ratio) * max(0, int(evidence_words))
    return int(max(int(floor), min(int(ceiling), round(raw))))


def per_artifact_words(total: int, n_types: int = len(PROSE_TYPES),
                       narrative: int = 0) -> int:
    """Evidence-proportional share, plus a flat NARRATIVE allowance per artifact.

    THE 2026-08-15 CHANGE, AND WHY IT IS NOT A CAP LIFT
    ---------------------------------------------------
    The founder's reading of the shipped packs: "our tone and language is hurried and
    cryptic". That is this file's doing, and the diagnosis in the module docstring above is
    still correct — the prose WAS padded, 78.3% of sentences carrying no figure. What was
    wrong is the prescription. A flat ceiling cuts padding and connective tissue with the
    same cut, because it cannot tell them apart: both are sentences without a number in
    them. The model, optimising against "shorter is better", deleted the cheapest words
    first, and the cheapest words are the ones that make a paragraph land.

    Pullum's objection to "Omit needless words" is this defect exactly: a rule that only
    restates the goal helps nobody, since a writer who could identify the needless words
    would not need telling. So the fix is not a bigger number, it is a NAMED one. `narrative`
    is an allowance with a stated job — the sentence that says what a section decides, and
    the transition into it — and the prompt below spends it on that and says so. The
    evidence-proportional part is untouched, which is what keeps this a reallocation rather
    than a lift: an artifact with no evidence behind it gains 150 words of scaffolding, not
    150 words of new claims, and the claim-check still governs what may be asserted.

    Default 0 so every caller that has not opted in computes exactly the old number.
    """
    share = round(total / max(1, n_types))
    return int(max(1, share + max(0, int(narrative))))


def length_rule(per_artifact: int, evidence_words: int) -> str:
    """The prompt fragment. Written in the house voice — the buyer never sees it, but a
    model reproduces the register it is addressed in, and half this file exists because
    the previous instruction ("substantial (many paragraphs)") was an invitation to pad.

    "Shorter is better and there is no minimum" was removed on 2026-08-15. It is the
    sentence that produced the cryptic register: a model told that brevity is itself a
    virtue writes telegrams. The ceiling stays — it is what removed the padding — but the
    instruction under it now asks for density, which is a property of a sentence, rather
    than for shortness, which is a property of a document.
    """
    return (
        f"LENGTH CONTRACT: this artifact must be AT MOST {per_artifact} words. There is no "
        "minimum. Do not pad to reach a length, and do not compress to beat it: an artifact "
        "that comes in under the ceiling by dropping the sentence that made the next one "
        "land has not saved the reader anything.\n"
        f"You have been given about {evidence_words} words of retrieved source material "
        "for the whole pack. Everything beyond that is your own judgement, which earns "
        "its place only where it tells the reader what to DO.\n"
        "Every paragraph must pass this test: it names a figure, a source, a named tool, "
        "a place, or an instruction the reader can carry out today. A paragraph that only "
        "restates what the reader has already been told is deleted, not rewritten.\n"
        "ONE EXCEPTION, AND IT IS DELIBERATE: each section may open with a single sentence "
        "that says what this section DECIDES, in plain words, carrying no figure. That "
        "sentence is not padding — it is the only thing that tells a reader whether to read "
        "on or skip, and a document made entirely of dense findings with no signposts is "
        "unreadable however true every line is. One such sentence per section. Not two.\n"
        "Structure the artifact as several titled sections (markdown headings), each with "
        "real substance — never a heading with one thin line under it. Title each section "
        "with what it CONCLUDES, not with its topic: 'Sell to the commissioner, not the "
        "family' rather than 'Route to market'."
    )


def artifacts_cfg(cfg: Optional[Any]) -> Dict[str, Any]:
    """Read the `artifacts:` config block, with the shipped defaults as the fallback.

    Defaults are deliberately generous — `enforce: false` and a ceiling above today's
    median — because the house rollout doctrine is to ship the measurement first, sweep
    the live catalogue, and only then choose the number. A threshold picked before the
    sweep is a guess wearing a decimal point.
    """
    block: Dict[str, Any] = {}
    if cfg is not None:
        raw = getattr(cfg, "artifacts", None)
        if raw is None and isinstance(cfg, dict):
            raw = cfg.get("artifacts")
        if isinstance(raw, dict):
            block = raw
        elif raw is not None:
            block = {k: v for k, v in vars(raw).items() if not k.startswith("_")}
    return {
        "enforce_length_budget": bool(block.get("enforce_length_budget", False)),
        "claim_check": bool(block.get("claim_check", False)),
        "base_words": int(block.get("base_words", 900)),
        "words_per_evidence_word": float(block.get("words_per_evidence_word", 1.0)),
        "floor_words": int(block.get("floor_words", 600)),
        "ceiling_words": int(block.get("ceiling_words", 3600)),
        # Flat per-artifact allowance for signposting prose. Config-declared, not a
        # constant, because it is exactly the kind of number that should be movable
        # without a source edit. See `per_artifact_words` for why it is separate from
        # `base_words` rather than folded into it.
        "narrative_words": int(block.get("narrative_words", 150)),
    }


def budget_for(checks: Iterable[Any], cfg: Optional[Any] = None) -> Dict[str, Any]:
    """One call for both consumers: the generator and the sweep.

    Always computes, whatever `enforce_length_budget` says — a measurement that only runs
    when the actuator is on cannot be the evidence for turning the actuator on.
    """
    settings = artifacts_cfg(cfg)
    profile = evidence_profile(checks)
    total = pack_word_budget(
        profile["words"],
        base=settings["base_words"],
        ratio=settings["words_per_evidence_word"],
        floor=settings["floor_words"],
        ceiling=settings["ceiling_words"],
    )
    return {
        **profile,
        "enforced": settings["enforce_length_budget"],
        "total_words": total,
        "narrative_words": settings["narrative_words"],
        "per_artifact_words": per_artifact_words(
            total, narrative=settings["narrative_words"]),
    }
