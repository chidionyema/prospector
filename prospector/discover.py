"""Signal discovery (Part 3, upstream of generation).

The engine was signal-bound: every run derived ideas from ONE hand-written signal
file, so the entire idea space was whatever niche that file described. This module
surfaces a DIVERSE portfolio of signals across many sectors, so generation can range
broadly instead of producing variations on a single theme. Like generation, it judges
nothing — the moat downstream grounds and kills.
"""
from __future__ import annotations

from typing import Any

from .config import Config
from .errors import ProviderExhaustedError
from .operator import Operator
from .prompts import render
from .telemetry import logger, track_latency

_DEFAULT_SECTORS = (
    "healthcare, logistics, agriculture, energy, construction, legal, hospitality, "
    "manufacturing, education, finance, retail, transport, real estate, media, "
    "public sector, insurance, waste, water, defence, pharma, automotive, tourism"
)


@track_latency(name="discover_signals")
def discover_signals(
    op: Operator, cfg: Config, n: int = 10, sectors: str = ""
) -> list[dict[str, Any]]:
    """Surface n diverse, sector-spread signals. Returns [{title, signal_text, sector}].

    Never raises on a bad model RESPONSE — returns [] so the caller can decide. It does raise
    `ProviderExhaustedError`, because that is not a response: see the `except` below.
    """
    sectors = sectors or _DEFAULT_SECTORS
    logger.info("Signal discovery started", extra={"n": n})
    system, user = render("discover", n=n, sectors=sectors)

    try:
        data = op.complete_json(system, user, temperature=0.9)
    except ProviderExhaustedError:
        # The one failure that must NOT become []. The caller (run.py:2864) prints
        # "No signals discovered (model returned nothing usable)" and exits 1 — a statement
        # about the MODEL'S ANSWER. When every tier of the chain is out of quota there was no
        # answer to be unusable, and that sentence is simply false: the same run on a live
        # brain would have produced signals. Exhaustion is the estate's typed failover signal
        # (errors.py:16) precisely so a caller can tell "the brain is benched, come back" from
        # "the brain replied with rubbish"; swallowing it here erased that distinction.
        logger.error("Signal discovery aborted: every operator tier is exhausted",
                     extra={"n": n})
        raise
    except Exception as e:  # noqa: BLE001 — never crash the hunt on a parse/model error
        logger.error(f"Signal discovery failed: {e}", extra={"error": str(e)})
        return []

    # Normalise: a bare list, or a wrapper dict with the list under some key.
    if isinstance(data, list):
        raw_list = data
    elif isinstance(data, dict):
        for key in ("signals", "results", "items", "opportunities"):
            if isinstance(data.get(key), list):
                raw_list = data[key]
                break
        else:
            raw_list = next((v for v in data.values() if isinstance(v, list)), [])
    else:
        raw_list = []

    signals: list[dict[str, Any]] = []
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        text = str(item.get("signal_text", "")).strip()
        if not text:
            continue
        signals.append({
            "title": str(item.get("title", "")).strip()[:120],
            "signal_text": text,
            "sector": str(item.get("sector", "")).strip(),
        })

    logger.info(f"Discovered {len(signals)} signals", extra={"count": len(signals)})
    return signals
