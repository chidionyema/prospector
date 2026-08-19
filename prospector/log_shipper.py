"""Ships this process's structured log to the central ingest.

The other half of `prospector/log_ingest.py`: step 7 of `docs/LOGGING_AND_RETENTION.md`
Part 8. Attach it once at start-up and every `telemetry.logger` record is also sent to
`POST /internal/logs` on the engine, in the Part 4.4 line schema.

**A logging call must never be able to fail a tick.** That is the whole design brief, and
it is why `emit()` does no I/O at all. It appends to a bounded deque and returns. A
background daemon thread does the posting, and every failure it meets — DNS, connection
refused, a 500, a timeout, the ingest not existing yet — is swallowed and counted. The
deque has a `maxlen`, so a long outage costs the oldest lines and never memory.

**Redaction happens here, at the producer.** The ingest cannot know which of a caller's
extra fields is a key. Anything whose field name looks like a credential is replaced with
`"[redacted]"` before it leaves the process, so a secret is never in the buffer, never on
the wire and never on the log volume.

**It is off unless configured.** No key or no URL means `attach()` does nothing and says
so once. A developer laptop and a test run therefore ship nothing by default.
"""
from __future__ import annotations

import atexit
import json
import logging
import os
import re
import threading
import urllib.error
import urllib.request
from collections import deque
from datetime import datetime, timezone
from typing import Any

DEFAULT_URL = "http://prospector-engine.internal:8613/internal/logs"

# The five levels the line schema allows, keyed by Python's names.
_LEVELS = {
    "DEBUG": "debug",
    "INFO": "info",
    "WARNING": "warn",
    "WARN": "warn",
    "ERROR": "error",
    "CRITICAL": "crit",
    "FATAL": "crit",
}

# Field NAMES that must never travel. Matched on the name, not the value, because a value
# scan cannot recognise a key it has not seen the shape of, and this one cannot be fooled
# by a new provider's format.
_SECRET_NAME_RE = re.compile(
    r"key|secret|token|password|passwd|credential|authorization|auth|cookie|session|pem|private",
    re.IGNORECASE,
)

# Fields logging puts on every record. None of them belong in `ctx`.
_RECORD_NOISE = frozenset(vars(logging.LogRecord("", 0, "", 0, "", None, None)).keys()) | {
    "message", "asctime", "taskName", "timestamp", "level", "event",
}

_EVT_RE = re.compile(r"[^a-z0-9._-]+")


def ingest_url() -> str:
    return os.environ.get("PROSPECTOR_LOG_INGEST_URL", DEFAULT_URL).strip()


def ingest_key() -> str:
    return os.environ.get("STORE_INTERNAL_API_KEY", "").strip()


def _rfc3339(epoch: float) -> str:
    dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _safe(value: Any) -> Any:
    """`ctx` is a FLAT object. Anything nested is rendered, so no shape can surprise a reader."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)[:512]


def event_name(record: logging.LogRecord) -> str:
    """A stable machine name, never interpolated with a value.

    `extra={"event": "..."}` is what most of this codebase already passes, so it is
    preferred. The fallback is the logger's own name, which is stable by construction —
    using the formatted message here would give a different `evt` per candidate id and
    make the field useless for counting.
    """
    raw = record.__dict__.get("event")
    if not isinstance(raw, str) or not raw:
        raw = f"log.{record.name}"
    cleaned = _EVT_RE.sub(".", raw.strip().lower()).strip(".")
    return (cleaned or "log.unnamed")[:128]


def to_line(record: logging.LogRecord, svc: str) -> dict:
    """One LogRecord as one Part 4.4 line. `host` is omitted: the ingest sets it."""
    ctx: dict[str, Any] = {}
    for name, value in record.__dict__.items():
        if name in _RECORD_NOISE or name.startswith("_"):
            continue
        ctx[name] = "[redacted]" if _SECRET_NAME_RE.search(name) else _safe(value)

    line: dict[str, Any] = {
        "ts": _rfc3339(record.created),
        "svc": svc,
        "lvl": _LEVELS.get(record.levelname.upper(), "info"),
        "evt": event_name(record),
    }
    try:
        message = record.getMessage()
    except Exception:  # a bad format string must not lose the record
        message = str(record.msg)
    if message:
        line["msg"] = message[:2000]
    corr = ctx.pop("corr", None) or ctx.pop("correlation_id", None)
    if isinstance(corr, str) and corr:
        line["corr"] = corr[:128]
    if record.exc_info:
        ctx.setdefault("exc", str(record.exc_info[1])[:512])
    if ctx:
        line["ctx"] = ctx
    return line


class IngestHandler(logging.Handler):
    """Buffers records and posts them from a background thread. Never blocks the caller."""

    def __init__(
        self,
        svc: str,
        url: str | None = None,
        key: str | None = None,
        *,
        capacity: int = 5000,
        batch: int = 500,
        interval: float = 2.0,
        timeout: float = 3.0,
    ) -> None:
        super().__init__()
        self.svc = svc
        self.url = url if url is not None else ingest_url()
        self.key = key if key is not None else ingest_key()
        self.batch = batch
        self.interval = interval
        self.timeout = timeout
        self._queue: deque[dict] = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.counters = {"queued": 0, "sent": 0, "dropped_full": 0, "failed_posts": 0}
        self._thread: threading.Thread | None = None

    # -- producer side (the caller's thread) -------------------------------------
    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = to_line(record, self.svc)
        except Exception:
            return  # a malformed record must never surface in the caller
        with self._lock:
            if len(self._queue) == self._queue.maxlen:
                self.counters["dropped_full"] += 1
            self._queue.append(line)
            self.counters["queued"] += 1

    # -- consumer side (the daemon thread) ---------------------------------------
    def _take(self) -> list[dict]:
        with self._lock:
            taken = [self._queue.popleft() for _ in range(min(self.batch, len(self._queue)))]
        return taken

    def post(self, lines: list[dict]) -> bool:
        """One POST. Returns success; raises nothing, ever."""
        if not lines:
            return True
        body = ("\n".join(json.dumps(line, separators=(",", ":")) for line in lines) + "\n")
        request = urllib.request.Request(
            self.url,
            data=body.encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.key}",
                "Content-Type": "application/x-ndjson",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                ok = 200 <= response.status < 300
        except Exception:
            # Every failure is the same failure here: the line does not arrive. DNS,
            # connection refused, a 500, a timeout, a proxy — none of them may reach the
            # caller, and none of them is worth a different branch.
            ok = False
        if ok:
            self.counters["sent"] += len(lines)
        else:
            self.counters["failed_posts"] += 1
        return ok

    def flush(self) -> None:
        while True:
            taken = self._take()
            if not taken:
                return
            self.post(taken)

    def _run(self) -> None:  # pragma: no cover - timing loop, exercised via flush()
        while not self._stop.wait(self.interval):
            try:
                self.flush()
            except Exception:
                pass
        try:
            self.flush()
        except Exception:
            pass

    def start(self) -> "IngestHandler":
        if self._thread is None:
            self._thread = threading.Thread(
                target=self._run, name="log-shipper", daemon=True
            )
            self._thread.start()
        return self

    def close(self) -> None:
        self._stop.set()
        try:
            self.flush()
        finally:
            super().close()


_ATTACHED: IngestHandler | None = None


def attach(svc: str, logger: logging.Logger | None = None) -> IngestHandler | None:
    """Send `logger`'s records to the central ingest. Returns None when not configured.

    Idempotent: a second call with the same service returns the handler already attached,
    so an entry point that is imported twice does not double every line.
    """
    global _ATTACHED
    if _ATTACHED is not None:
        return _ATTACHED
    if not ingest_key() or not ingest_url():
        return None
    if logger is None:
        from .telemetry import logger as telemetry_logger

        logger = telemetry_logger
    handler = IngestHandler(svc).start()
    logger.addHandler(handler)
    atexit.register(handler.close)
    _ATTACHED = handler
    return handler


def detach() -> None:
    """Undo `attach`. For tests and for a process that changes its identity."""
    global _ATTACHED
    handler = _ATTACHED
    _ATTACHED = None
    if handler is None:
        return
    from .telemetry import logger as telemetry_logger

    telemetry_logger.removeHandler(handler)
    handler.close()
