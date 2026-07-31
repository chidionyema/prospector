"""Ledger-Aware Generator (Stage 1).

Before instantiating any CandidateSpec objects, the generator reads the last
15 laws from the durable ledger and injects them into the LLM system prompt.
This cures the "Goldfish Amnesia" — the generator now remembers what the
verification moat killed two hours prior.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Callable, List, Optional

from prospector.domain.primitives import CandidateSpec
from prospector.pipeline.moat_prompts import compile_generator_system_prompt

logger = logging.getLogger(__name__)


def generate_candidates(
    signal_text: str,
    structural_forms: List[str],
    target_audiences: List[str],
    llm_call: Callable[[str, str], str],
    batch_id: Optional[str] = None,
    k_per_form_audience: int = 1,
) -> List[CandidateSpec]:
    """Generate candidates across a form × audience matrix, cured of amnesia.

    Args:
        signal_text: The opportunity signal (empty string = blue-sky).
        structural_forms: Business forms to fan across (e.g. "vertical_tool").
        target_audiences: Audience personas to fan across.
        llm_call: (system_prompt, user_prompt) -> raw LLM response string.
        batch_id: Unique batch identifier (auto-generated if None).
        k_per_form_audience: Candidates per (form, audience) cell.

    Returns:
        List of frozen CandidateSpec instances, one per generated idea.
    """
    if batch_id is None:
        batch_id = f"batch_{int(time.time())}"

    candidates: List[CandidateSpec] = []

    for form in structural_forms:
        for audience in target_audiences:
            system = compile_generator_system_prompt(
                signal_text=signal_text or "Generate a novel, specific business idea.",
                structural_form=form,
                target_audience=audience,
            )
            user = "Return ONLY valid JSON. No prose, no code fences."

            for _ in range(k_per_form_audience):
                try:
                    raw = llm_call(system, user)
                    data = _extract_candidate_json(raw)
                    spec = CandidateSpec(
                        generation_batch_id=batch_id,
                        structural_form=data.get("structural_form", form),
                        target_audience=data.get("target_audience", audience),
                        core_concept_prose=data.get("core_concept_prose", raw[:200]),
                    )
                    candidates.append(spec)
                    logger.info(
                        "Generated candidate %s (form=%s, audience=%s)",
                        spec.id, form, audience)
                except Exception as e:
                    logger.warning(
                        "Generation failed for form=%s audience=%s: %s",
                        form, audience, e)

    return candidates


def _extract_candidate_json(raw: str) -> dict:
    """Extract candidate fields from raw LLM output.

    Tries direct JSON parse first, then hunts for a JSON object in the text.
    """
    import re

    raw = raw.strip()
    # Strip markdown fences.
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()

    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    # Hunt for the first JSON object.
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            pass

    # Fallback: return the raw text as core_concept_prose.
    return {"core_concept_prose": raw[:500]}
