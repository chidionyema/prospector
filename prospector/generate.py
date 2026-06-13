"""Generate raw opportunity candidates from a signal (Part 3).

Nothing here judges or drops candidates on quality — that is Part 3's explicit
contract. Only structurally-invalid JSON elements are skipped.
"""
from __future__ import annotations

from typing import Any

from .config import Config
from .models import Candidate
from .operator import Operator
from .prompts import render
from .telemetry import logger, track_latency


@track_latency(name="generate")
def generate(
    op: Operator,
    cfg: Config,
    signal_text: str = "",
    sector: str = "",
    strategy_lens: str = "broaden",
    exploration_level: float = 0.5,
    target_qualities: str | None = None,
    recent_failure_modes: str | None = None,
    k: int | None = None,
) -> list[Candidate]:
    """Generate k raw Candidate opportunities from a signal.

    Never kills on quality — only skips elements that cannot be parsed as a
    dict with at least a 'title' key (structural invalidity only).
    """
    logger.info("Generation started", extra={
        "sector": sector, 
        "lens": strategy_lens, 
        "exploration": exploration_level,
        "k": k
    })
    
    gen_cfg: dict[str, Any] = cfg.generation

    if k is None:
        k = gen_cfg.get("candidates_per_signal", 20)

    if target_qualities is None:
        controller: dict[str, Any] = gen_cfg.get("controller", {})
        qualities: list[str] = controller.get("target_qualities", [])
        target_qualities = ", ".join(str(q) for q in qualities)

    if recent_failure_modes is None:
        recent_failure_modes = ""

    system, user = render(
        "generate",
        signal_text=signal_text,
        sector=sector,
        strategy_lens=strategy_lens,
        exploration_level=exploration_level,
        target_qualities=target_qualities,
        recent_failure_modes=recent_failure_modes,
        k=k,
    )

    try:
        data = op.complete_json(system, user, temperature=0.9)
    except Exception as e:
        logger.error(f"Generation failed: {e}", extra={"error": str(e)})
        return []

    # Normalise: the model may return a bare list or a wrapper dict.
    if isinstance(data, list):
        raw_list = data
    elif isinstance(data, dict):
        # Try common wrapper keys; fall back to first list-valued key.
        for key in ("opportunities", "candidates", "results", "items"):
            if isinstance(data.get(key), list):
                raw_list = data[key]
                break
        else:
            # Find the first list value in the dict.
            raw_list = next(
                (v for v in data.values() if isinstance(v, list)), []
            )
    else:
        raw_list = []

    candidates: list[Candidate] = []
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        if not item.get("title"):
            continue
        try:
            candidates.append(Candidate.from_dict(item))
        except Exception:
            # Skip any element that cannot be coerced; never crash.
            continue

    logger.info(f"Generated {len(candidates)} candidates", extra={"count": len(candidates)})
    return candidates
