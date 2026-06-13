"""Monitoring and Observability (Part 15).
Structured JSON logging with latency tracking and context propagation.
"""
from __future__ import annotations

import contextvars
import json
import logging
import threading
import time
from functools import wraps
from typing import Any, Callable, Dict, Optional, TypeVar

from pythonjsonlogger import jsonlogger

# Context variables for tracing
SESSION_ID = contextvars.ContextVar("session_id", default=None)
CANDIDATE_ID = contextvars.ContextVar("candidate_id", default=None)
PHASE = contextvars.ContextVar("phase", default="main")

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


def set_context(session_id: Optional[str] = None, candidate_id: Optional[str] = None, phase: Optional[str] = None) -> None:
    """Set tracing context."""
    if session_id:
        SESSION_ID.set(session_id)
    if candidate_id:
        CANDIDATE_ID.set(candidate_id)
    if phase:
        PHASE.set(phase)


# ---------------------------------------------------------------------------
# Token / call audit (Part 15) — aggregate engine spend per phase so every run
# is self-auditing. Keyed by the active PHASE contextvar; thread-safe for the
# ThreadPoolExecutor vetting path.
# ---------------------------------------------------------------------------

_USAGE_LOCK = threading.Lock()
_USAGE: Dict[str, Dict[str, int]] = {}

_USAGE_KEYS = ("calls", "web_calls", "input", "output", "total", "cached")


def record_usage(*, input_tokens: int = 0, output_tokens: int = 0,
                 total_tokens: int = 0, cached_tokens: int = 0,
                 web: bool = False) -> None:
    """Record one model/search call's token usage against the current phase."""
    phase = PHASE.get() or "main"
    with _USAGE_LOCK:
        u = _USAGE.setdefault(phase, {k: 0 for k in _USAGE_KEYS})
        u["calls"] += 1
        if web:
            u["web_calls"] += 1
        u["input"] += int(input_tokens or 0)
        u["output"] += int(output_tokens or 0)
        u["total"] += int(total_tokens or 0)
        u["cached"] += int(cached_tokens or 0)


def get_usage_summary() -> Dict[str, Any]:
    """Return {'total': {...}, 'by_phase': {phase: {...}}} of all usage so far."""
    with _USAGE_LOCK:
        agg = {k: 0 for k in _USAGE_KEYS}
        for u in _USAGE.values():
            for k in _USAGE_KEYS:
                agg[k] += u.get(k, 0)
        return {"total": agg, "by_phase": {k: dict(v) for k, v in _USAGE.items()}}


def reset_usage() -> None:
    """Clear the usage ledger (e.g. at the start of a run or in tests)."""
    with _USAGE_LOCK:
        _USAGE.clear()
