"""Monitoring and Observability (Part 15).
Structured JSON logging with latency tracking and context propagation.
"""
from __future__ import annotations

import contextvars
import logging
import threading
import time
from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable, Dict, Optional, TypeVar

from pythonjsonlogger import jsonlogger

# Context variables for tracing
SESSION_ID = contextvars.ContextVar("session_id", default=None)
CANDIDATE_ID = contextvars.ContextVar("candidate_id", default=None)
PHASE = contextvars.ContextVar("phase", default="main")
# stage = which pipeline step made the call (generate | prescreen | query_gen | verdict |
# adversarial | score | price_comparables | artifacts | claim_check | content_gen); finer-grained
# than phase, set by Operator.complete_json.
STAGE = contextvars.ContextVar("stage", default="")


@contextmanager
def stage(name: str):
    """Tag every record_usage() inside the block with this pipeline stage (E4).

    A context manager instead of a complete_json parameter so that test doubles and
    subclasses with strict signatures never have to know about it.
    """
    token = STAGE.set(name)
    try:
        yield
    finally:
        STAGE.reset(token)

F = TypeVar("F", bound=Callable[..., Any])


class CustomJsonFormatter(jsonlogger.JsonFormatter):
    def add_fields(self, log_record: Dict[str, Any], record: logging.LogRecord, message_dict: Dict[str, Any]) -> None:
        super().add_fields(log_record, record, message_dict)
        
        # Inject context variables
        sid = SESSION_ID.get()
        if sid:
            log_record["session_id"] = sid
            
        cid = CANDIDATE_ID.get()
        if cid:
            log_record["candidate_id"] = cid
            
        log_record["phase"] = PHASE.get()
        
        # Standardize level and timestamp
        if not log_record.get("timestamp"):
            log_record["timestamp"] = self.formatTime(record, self.datefmt)
        if log_record.get("level"):
            log_record["level"] = log_record["level"].upper()
        else:
            log_record["level"] = record.levelname


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Initialize structured JSON logging."""
    logger = logging.getLogger("prospector")
    logger.setLevel(level)
    
    # Avoid duplicate handlers if setup multiple times
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = CustomJsonFormatter(
            "%(timestamp)s %(level)s %(name)s %(message)s"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        
    return logger


# Global logger instance
logger = setup_logging()


def route_logs_to_file(path: str, level: int = logging.INFO) -> None:
    """Send the structured JSON audit log to a file instead of stderr, leaving
    stderr free for the human progress stream (progress.py). Idempotent. Set
    PROSPECTOR_JSON_LOG=stderr to keep JSON on the console for debugging."""
    import os
    from pathlib import Path

    if os.environ.get("PROSPECTOR_JSON_LOG") == "stderr":
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    # Drop existing stream handlers; attach a single file handler.
    for h in list(logger.handlers):
        logger.removeHandler(h)
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(CustomJsonFormatter("%(timestamp)s %(level)s %(name)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(level)


def track_latency(name: Optional[str] = None) -> Callable[[F], F]:
    """Decorator to log function execution time."""
    def decorator(func: F) -> F:
        func_name = name or func.__name__
        
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            start_time = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                latency_ms = (time.perf_counter() - start_time) * 1000
                logger.info(
                    f"Completed {func_name}", 
                    extra={
                        "event": "latency",
                        "operation": func_name,
                        "latency_ms": round(latency_ms, 2),
                        "status": "success"
                    }
                )
                return result
            except Exception as e:
                latency_ms = (time.perf_counter() - start_time) * 1000
                logger.error(
                    f"Failed {func_name}", 
                    extra={
                        "event": "latency",
                        "operation": func_name,
                        "latency_ms": round(latency_ms, 2),
                        "status": "error",
                        "error": str(e)
                    }
                )
                raise
        return wrapper # type: ignore
    return decorator


def set_context(session_id: Optional[str] = None, candidate_id: Optional[str] = None, phase: Optional[str] = None, stage: Optional[str] = None) -> None:
    """Set tracing context."""
    if session_id:
        SESSION_ID.set(session_id)
    if candidate_id:
        CANDIDATE_ID.set(candidate_id)
    if phase:
        PHASE.set(phase)
    if stage:
        STAGE.set(stage)


# ---------------------------------------------------------------------------
# Token / call audit (Part 15) — aggregate engine spend per phase so every run
# is self-auditing. Keyed by the active PHASE contextvar; thread-safe for the
# ThreadPoolExecutor vetting path.
# ---------------------------------------------------------------------------

_USAGE_LOCK = threading.Lock()
_USAGE: Dict[str, Dict[str, int]] = {}
_USAGE_BY_PROVIDER: Dict[str, Dict[str, int]] = {}

#: `cache_write` is the FIFTH term of `total`, and its absence is why the token ledger read
#: as broken. `claude_cli.py:78` computes
#:     total = input + output + cache_read + cache_creation
#: and until 2026-08-13 only four of those five had a column here, so the batch of
#: 2026-08-13T06:23:14 reported `input 420,082 + output 308,297 = 728,379` against a `total`
#: of `1,990,168` and looked corrupt. It was not: 420,082 + 308,297 + 647,108 (cached) +
#: 614,681 (cache_creation) = 1,990,168 exactly. The missing column WAS the discrepancy.
#:
#: These four token columns are NOT interchangeable units — they are billed at different
#: rates (cache_read ~0.1x an input token, cache_write ~1.25x). Any $/phase or $/vetted
#: figure computed from `total` is therefore wrong by construction, which is what
#: `reconcile()` below exists to keep visible.
_USAGE_KEYS = ("calls", "web_calls", "input", "output", "total", "cached", "cache_write",
               "self_corrections")

# Pricing per 1M tokens in USD (2026 typical rates). This is the FALLBACK
# when no config is provided; the canonical source is `config.yaml`'s
# `pricing` block (consumed via `get_price()`). Keeping the module-level
# `PRICING` for backwards compatibility with callers that don't have a
# Config object handy.
PRICING = {
    "claude": {"input": 3.00, "output": 15.00},
    "deepseek": {"input": 0.27, "output": 1.10},
    "minimax": {"input": 0.30, "output": 0.30}, # Flat rate for MiniMax M2.7/M3
    "ollama": {"input": 0.00, "output": 0.00},
    "mock": {"input": 0.00, "output": 0.00},
}


def get_price(provider: str, cfg=None) -> dict:
    """Return the {input, output} USD-per-1M-token price for `provider`.

    Reads from `cfg.pricing` (the canonical source) when a config is provided.
    Falls back to the module-level PRICING dict for backwards compatibility
    (callers without a Config object, primarily tests).

    Missing-provider lookups return $0/$0 (treated as free / unpriced). This
    is logged so spend is never silently wrong: a warning surfaces to the
    operator that their config doesn't have a price for this provider.
    """
    provider = provider.split("/")[0].lower() if "/" in provider else provider.lower()
    if cfg is not None and getattr(cfg, "pricing", None) is not None:
        tier = getattr(cfg.pricing, provider, None)
        if tier is not None:
            return {"input": float(tier.input), "output": float(tier.output)}
        # Provider not in config.pricing — fall through to module default
        # but warn (this is the case the audit wanted to surface).
        if provider not in PRICING:
            import logging as _logging
            _logging.getLogger(__name__).warning(
                f"get_price: provider {provider!r} not in cfg.pricing or PRICING; "
                f"returning $0 (will appear free in cost reports)"
            )
    # Fallback: module-level PRICING dict.
    if provider in PRICING:
        return PRICING[provider]
    return {"input": 0.0, "output": 0.0}


def record_usage(*, input_tokens: int = 0, output_tokens: int = 0,
                 total_tokens: int = 0, cached_tokens: int = 0,
                 cache_write_tokens: int = 0,
                 web: bool = False, provider: str = "unknown",
                 message: str = "", self_correction: bool = False,
                 cfg=None) -> None:
    """Record one model/search call's token usage against the current phase and provider.

    `cfg` is optional and defaults to None, so every existing call site (none of which
    currently has a Config object in scope) is unaffected. Pass it when the caller does
    have one (see StandardComputeOperator) so `get_price()` can read a real rate from
    `cfg.pricing` instead of the module-level fallback.
    """
    phase = PHASE.get() or "main"
    stage = STAGE.get() or ""
    # Extract root provider (e.g. 'claude-cli/default' -> 'claude-cli')
    root_provider = provider.split("/")[0].lower() if "/" in provider else provider.lower()
    
    with _USAGE_LOCK:
        # 1. Update by phase
        u = _USAGE.setdefault(phase, {k: 0 for k in _USAGE_KEYS})
        u["calls"] += 1
        if web:
            u["web_calls"] += 1
        if self_correction:
            u["self_corrections"] += 1
        u["input"] += int(input_tokens or 0)
        u["output"] += int(output_tokens or 0)
        u["total"] += int(total_tokens or 0)
        u["cached"] += int(cached_tokens or 0)
        u["cache_write"] += int(cache_write_tokens or 0)

        # 2. Update by provider
        p = _USAGE_BY_PROVIDER.setdefault(root_provider, {k: 0 for k in _USAGE_KEYS})
        p["calls"] += 1
        if self_correction:
            p["self_corrections"] += 1
        p["input"] += int(input_tokens or 0)
        p["output"] += int(output_tokens or 0)
        p["total"] += int(total_tokens or 0)
        p["cached"] += int(cached_tokens or 0)
        p["cache_write"] += int(cache_write_tokens or 0)

        # 3. Log a spend event. Routed through get_price() (not a direct PRICING.get())
        # so a caller that DOES pass `cfg` gets `cfg.pricing`'s real rate, not just the
        # module-level fallback (audit HIGH finding 4: this hardcoded lookup was the
        # reason standardcompute, the head of run.py's _NONCRITICAL_ORDER, always
        # priced at $0/$0 and could never move daily_cap_usd's sum no matter how many
        # calls it made — the config-aware path existed but nothing here ever called it).
        #
        # Only a caller that supplies `cfg` is asking for config-aware, audited pricing
        # (today that's just StandardComputeOperator — see the class docstring and audit
        # HIGH finding 4). For that caller, a provider missing from cfg.pricing must be
        # LOUD: warn, and log the spend event even at cost=0, so a real rate entered later
        # under config.yaml's pricing: block is the only way to make it stop warning.
        # Every OTHER call site (the ~19 that don't pass cfg, unchanged by this fix) keeps
        # the exact old behavior — log a spend event only when cost > 0, no new warnings —
        # which is what keeps claude_cli (subscription burn, deliberately $0, no PRICING or
        # cfg.pricing entry at all) from being newly and wrongly counted as a spend event:
        # tests/unit/test_scheduler_resume_drain.py::test_pricing_claude_cli_would_arm_the_metered_cap.
        price = get_price(root_provider, cfg=cfg)
        cost = (input_tokens * price["input"] / 1_000_000) + (output_tokens * price["output"] / 1_000_000)
        configured = cfg is not None and getattr(cfg, "pricing", None) is not None
        priced = (not configured) or getattr(cfg.pricing, root_provider, None) is not None
        if configured and not priced:
            logger.warning(
                f"record_usage: no price configured for provider {root_provider!r}; "
                f"logging spend at $0 rather than dropping the event silently. Add a "
                f"rate under config.yaml's pricing: block to make this real."
            )
        if cost > 0 or (configured and not priced):
            logger.info(
                f"Spend event: {provider} cost=${cost:.6f}" + ("" if priced else " (UNPRICED)"),
                extra={
                    "event": "spend",
                    "provider": provider,
                    "amount_usd": cost,
                    "priced": priced,
                    "phase": phase,
                    "stage": stage,
                    "input": input_tokens,
                    "output": output_tokens
                }
            )
        
        if message:
            logger.info(message, extra={
                "provider": provider,
                "input": input_tokens,
                "output": output_tokens,
                "cached": cached_tokens,
                "cost_usd": round(cost, 6)
            })


def reconcile(u: Dict[str, int]) -> Dict[str, int]:
    """Does this counter's `total` equal the four columns that are supposed to compose it?

    Returns `{"expected": ..., "total": ..., "residual": ...}`. `residual == 0` means the
    ledger is closed: every token in `total` is attributed to a priced dimension.

    WHY A RESIDUAL AND NOT AN ASSERTION. Providers do not agree on what `total_tokens` means.
    `claude_cli.py:78` builds it from four parts we can name; MiniMax, DeepSeek, Ollama,
    StandardCompute and OpenRouter each hand back their OWN `usage.total_tokens`
    (`operator.py:459`, `:554`, `:1061`, `:677`, `:956`) which may include routing or padding
    we never see. Raising would turn one provider's accounting quirk into a crashed batch;
    a non-zero residual makes it VISIBLE and attributable instead, which is the whole point —
    an unexplained 1.26M read as corruption for as long as nothing computed this number.

    Not a cost figure, on purpose. These four columns bill at different rates, so summing
    them is meaningless as money; this only answers "is anything unaccounted for?".
    """
    expected = int(u.get("input", 0)) + int(u.get("output", 0)) + \
        int(u.get("cached", 0)) + int(u.get("cache_write", 0))
    total = int(u.get("total", 0))
    return {"expected": expected, "total": total, "residual": total - expected}


def get_usage_summary() -> Dict[str, Any]:
    """Return {'total': {...}, 'by_phase': {phase: {...}}, 'by_provider': {...}}."""
    with _USAGE_LOCK:
        agg = {k: 0 for k in _USAGE_KEYS}
        for u in _USAGE.values():
            for k in _USAGE_KEYS:
                agg[k] += u.get(k, 0)
                
        # Calculate total cost
        total_cost = 0.0
        provider_stats = {}
        for prov, u in _USAGE_BY_PROVIDER.items():
            price = PRICING.get(prov, {"input": 0, "output": 0})
            cost = (u["input"] * price["input"] / 1_000_000) + (u["output"] * price["output"] / 1_000_000)
            total_cost += cost
            p_data = dict(u)
            p_data["cost_usd"] = round(cost, 6)
            # Per-provider, because a residual is only actionable when it names the adapter
            # whose accounting we cannot reproduce. The aggregate hides that: one provider's
            # quirk shows up as a mystery number spread across the whole batch.
            p_data["reconcile"] = reconcile(u)
            provider_stats[prov] = p_data

        return {
            "total": agg,
            "total_cost_usd": round(total_cost, 4),
            "reconcile": reconcile(agg),
            "by_phase": {k: dict(v) for k, v in _USAGE.items()},
            "by_provider": provider_stats
        }


def reset_usage() -> None:
    """Clear the usage ledger (e.g. at the start of a run or in tests).

    BOTH maps, because `total_cost_usd` and `by_provider` are computed from
    `_USAGE_BY_PROVIDER` (line 261) while only `by_phase` comes from `_USAGE`. Clearing one
    left the reported cost cumulative since PROCESS START, which every caller here contradicts
    — run.py:453 spells the intent "fresh token ledger for this run". A CLI process dies after
    one run so the leak was invisible; the scheduler daemon is long-lived and re-vets every 2h,
    so its per-tick cost could only ever grow. Found 2026-08-06 wiring the drain's spend into
    the tick row.

    Not a money-rail change: the daily cap is computed from the persistent
    store/prospector.jsonl ledger (scheduler/guard.py:158), never from this in-process map.
    """
    with _USAGE_LOCK:
        _USAGE.clear()
        _USAGE_BY_PROVIDER.clear()
