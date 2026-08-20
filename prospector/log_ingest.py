"""The central log ingest. One endpoint; every service in the estate posts to it.

Design and rationale: `docs/LOGGING_AND_RETENTION.md` Part 4. This module is step 6 of
that document's Part 8 plan — the receiving end. Producers are steps 7 and 8, the
console page is step 10, the retention sweeper is step 11.

**Why this is its own app rather than a route on `prospector/api.py`.** Importing
`prospector.api` constructs a `Store` at module scope (`api.py:22`), which opens the
catalogue database. Running the commerce API under supervisord to get a log endpoint
would ship entitlement and listing code into production as a side effect of a logging
change, and would put a log flood in the same process as the money path. This module
imports no store and holds no database handle. A logging outage cannot reach commerce,
and a commerce outage cannot stop logs arriving.

**Why it must never push back.** The caps below DROP. They never queue, never block and
never return 5xx for a full disk. A logging endpoint that applies backpressure lets a
log problem become an outage in the service that was only trying to describe itself.
Every drop is counted and the counters are readable at `GET /internal/logs/stats`, so
dropping is loud in the one place that matters and silent everywhere else.

**Why `host` is taken from the connection.** A client that names its own host can claim
to be another service. The ingest overwrites it, always.

**Why the filename uses the INGEST's date, not the line's `ts`.** A client with a wrong
clock would otherwise create `store-api-2035-01-01.jsonl`, which the retention sweeper
would keep forever because it is not old. The line keeps whatever `ts` the client sent;
only the file it lands in is decided here.
"""
from __future__ import annotations

import hmac
import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.routing import Route

from .config import store_root

# --------------------------------------------------------------------------- caps
# Every one of these is an env override so a test can drive the boundary without
# writing 500 MB. The defaults are the numbers declared in LOGGING_AND_RETENTION.md §4.7.


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def max_body_bytes() -> int:
    return _int_env("PROSPECTOR_LOG_MAX_BODY_BYTES", 1024 * 1024)


def max_lines_per_batch() -> int:
    return _int_env("PROSPECTOR_LOG_MAX_LINES", 1000)


def max_line_bytes() -> int:
    return _int_env("PROSPECTOR_LOG_MAX_LINE_BYTES", 16 * 1024)


def max_file_day_bytes() -> int:
    return _int_env("PROSPECTOR_LOG_MAX_FILE_BYTES", 200 * 1024 * 1024)


def max_total_bytes() -> int:
    return _int_env("PROSPECTOR_LOG_MAX_TOTAL_BYTES", 500 * 1024 * 1024)


def rate_limit_rps() -> int:
    return _int_env("PROSPECTOR_LOG_RATE_LIMIT_RPS", 100)


def log_dir() -> Path:
    """`/data/logs` on the engine: a sibling of the store, never derived from `__file__`.

    `PROSPECTOR_LOG_DIR` wins. Otherwise it is `store_root().parent / "logs"`, so it
    follows the STORE — the same rule `config.store_root` exists to enforce. A path
    anchored to this file would follow the code instead, and production runs from a
    different checkout than the one a developer edits.
    """
    override = os.environ.get("PROSPECTOR_LOG_DIR", "").strip()
    return Path(override) if override else store_root().parent / "logs"


# --------------------------------------------------------------------------- schema
# `svc` becomes part of a FILENAME. This regex is the security gate, not a style check:
# it is what stops `svc: "../../../etc/cron.d/x"`. Anchored, lowercase, bounded.
_SVC_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")

LEVELS = ("debug", "info", "warn", "error", "crit")

# The services the design names. This is NOT a gate — a service missing from this tuple
# still gets its lines written, because dropping a real producer's logs over a stale
# tuple is the silent-failure class this whole programme exists to remove. It is the
# list the console offers as filters, and nothing more.
KNOWN_SERVICES = (
    "store-api",
    "store-web",
    "engine",
    "scheduler",
    "consumer",
    "watchdog",
    "console",
    "ci",
    "ingest",
)

_DAY_RE = re.compile(r"^(?P<svc>[a-z][a-z0-9-]{0,31})-(?P<day>\d{4}-\d{2}-\d{2})\.jsonl$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def rfc3339(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def normalise(obj: Any, host: str, now: datetime) -> dict | None:
    """Turn one decoded JSON object into a line we will store, or None to drop it.

    Lenient where leniency keeps data (a missing `ts` or an unknown `lvl` is repaired),
    strict where a bad value is dangerous or unroutable (`svc`, `evt`). Unknown fields
    are kept verbatim — the schema is a floor, not a whitelist.
    """
    if not isinstance(obj, dict):
        return None
    svc = obj.get("svc")
    evt = obj.get("evt")
    if not isinstance(svc, str) or not _SVC_RE.match(svc):
        return None
    if not isinstance(evt, str) or not evt or len(evt) > 128:
        return None

    line = dict(obj)
    ts = obj.get("ts")
    if not isinstance(ts, str) or not ts:
        line["ts"] = rfc3339(now)
    lvl = obj.get("lvl")
    if lvl not in LEVELS:
        line["lvl"] = "info"
    # Always ours. A client cannot claim to be somewhere else.
    line["host"] = host
    ctx = obj.get("ctx")
    if ctx is not None and not isinstance(ctx, dict):
        line["ctx"] = {"value": ctx}
    return line


# --------------------------------------------------------------------------- reading
#: The most bytes `search` reads from the END of any one day file. A day file is capped at 200 MB
#: (§4.6); pulling 200 MB to render 200 rows would hang the console page and pin the engine's CPU
#: while it did. 8 MB is 500 lines at the 16 KB line cap and tens of thousands at a realistic size.
#: When a file is larger than this the result says `truncated`, which is the whole point: it is the
#: difference between "there are no more matches" and "we stopped looking".
MAX_TAIL_BYTES = 8 * 1024 * 1024

#: The most day files one search opens, newest first. Bounded for the same reason.
MAX_FILES = 21

#: The most rows one search returns, whatever the caller asks for.
MAX_LIMIT = 2000


def day_files(directory: Path) -> list[tuple[str, str, Path]]:
    """`(day, svc, path)` for every valid day file, NEWEST FIRST.

    A file whose name `_DAY_RE` cannot parse is skipped, not guessed at. That is the same regex
    the writer uses to build the name, so a name this cannot read is a name we did not write.
    """
    out: list[tuple[str, str, Path]] = []
    for path in directory.glob("*.jsonl"):
        match = _DAY_RE.match(path.name)
        if match:
            out.append((match.group("day"), match.group("svc"), path))
    out.sort(reverse=True)
    return out


def tail_lines(path: Path, window: int | None = None) -> tuple[list[str], bool]:
    """The last `window` bytes of `path` as whole lines, and whether anything was cut off.

    `window` resolves from `MAX_TAIL_BYTES` at CALL time, never as a default argument. A default
    is evaluated once at import, which would make the module constant a copy rather than the knob
    — and the test that drives the truncation path could then never reach it.

    Reading from the end is what makes "newest first" cheap. The first line inside the window is
    almost always half a line, so it is dropped when the window did not reach the start of the
    file: a torn line parsed as data is worse than a line not shown, and the caller is told the
    result was truncated either way.
    """
    size = path.stat().st_size
    start = max(0, size - (MAX_TAIL_BYTES if window is None else window))
    with path.open("rb") as handle:
        handle.seek(start)
        blob = handle.read()
    truncated = start > 0
    if truncated:
        newline = blob.find(b"\n")
        blob = blob[newline + 1:] if newline >= 0 else b""
    return blob.decode("utf-8", errors="replace").splitlines(), truncated


def _min_level_index(level: str) -> int:
    """Index into `LEVELS` for a minimum-severity filter; -1 when there is no filter.

    An unknown level name means NO filter rather than an empty result. A typo in a query string
    must not look like a quiet system.
    """
    name = (level or "").strip().lower()
    return LEVELS.index(name) if name in LEVELS else -1


def _matches(row: dict, raw: str, *, service: str, min_level: int,
             since: str, until: str, corr: str, needle: str) -> bool:
    """Every filter, applied to one already-decoded row."""
    if service and str(row.get("svc") or "") != service:
        return False
    if min_level >= 0:
        lvl = str(row.get("lvl") or "info")
        if lvl not in LEVELS or LEVELS.index(lvl) < min_level:
            return False
    if corr and str(row.get("corr") or "") != corr:
        return False
    if since or until:
        # RFC3339 UTC sorts correctly as a string, which is why the schema fixes the format.
        # A row with no `ts` is never excluded by a time filter — the ingest stamps one, so a
        # missing `ts` here means a hand-written file, and dropping it would hide it.
        ts = str(row.get("ts") or "")
        if ts and since and ts < since:
            return False
        if ts and until and ts > until:
            return False
    if needle and needle not in raw.lower():
        return False
    return True


def search(*, directory: Path | None = None, service: str = "", level: str = "",
           since: str = "", until: str = "", corr: str = "", q: str = "",
           limit: int = 200) -> dict:
    """Newest-first log lines matching every filter given, with the cost of the answer attached.

    This is the read half of the design's Part 4, and the console's `/logs` page is its only
    caller today. It reads the files directly rather than asking the ingest process over HTTP,
    because both run on the same machine (`deploy/engine/supervisord.conf`, `[program:ops-console]`
    and `[program:log-ingest]`). Going through the ingest would mean the logs became unreadable
    exactly when the ingest is the process that died, which is when they are worth most.

    Every bound is reported, never silently applied: `truncated` when a file was longer than the
    tail window, `files_capped` when there were more day files than `MAX_FILES`, `unreadable` for
    torn lines. A reader who cannot tell "nothing matched" from "we stopped early" will eventually
    conclude a healthy silence from a bounded search.
    """
    directory = directory or log_dir()
    limit = max(1, min(int(limit or 200), MAX_LIMIT))
    needle = (q or "").strip().lower()
    service = (service or "").strip()
    corr = (corr or "").strip()
    min_level = _min_level_index(level)

    result: dict[str, Any] = {
        "dir": str(directory),
        "present": directory.exists(),
        "rows": [],
        "matched": 0,
        "scanned": 0,
        "unreadable": 0,
        "files_read": 0,
        "files_total": 0,
        "files_capped": False,
        "truncated": False,
        "days": [],
        "services": list(KNOWN_SERVICES),
        "levels": list(LEVELS),
        "limit": limit,
    }
    if not directory.exists():
        return result

    files = day_files(directory)
    result["files_total"] = len(files)
    result["days"] = sorted({day for day, _, _ in files}, reverse=True)
    if service:
        files = [f for f in files if f[1] == service]
    if len(files) > MAX_FILES:
        files = files[:MAX_FILES]
        result["files_capped"] = True

    rows: list[dict] = []
    for _day, _svc, path in files:
        if len(rows) >= limit:
            break
        try:
            lines, truncated = tail_lines(path)
        except OSError:
            # A file that vanished mid-read is the retention sweeper doing its job, not an error
            # worth failing the whole page over.
            continue
        result["files_read"] += 1
        result["truncated"] = result["truncated"] or truncated
        for raw in reversed(lines):
            raw = raw.strip()
            if not raw:
                continue
            result["scanned"] += 1
            try:
                row = json.loads(raw)
            except ValueError:
                result["unreadable"] += 1
                continue
            if not isinstance(row, dict):
                result["unreadable"] += 1
                continue
            if not _matches(row, raw, service=service, min_level=min_level,
                            since=since, until=until, corr=corr, needle=needle):
                continue
            result["matched"] += 1
            if len(rows) < limit:
                rows.append(row)
            else:
                break

    # Files are opened newest-day first and each is read back to front, so `rows` is already in
    # newest-first order WITHIN a service. Across services on the same day it is not, and an
    # operator reading a correlation id needs the true order. Sort by `ts`, stably.
    rows.sort(key=lambda r: str(r.get("ts") or ""), reverse=True)
    result["rows"] = rows
    return result


# --------------------------------------------------------------------------- limiter
class RateLimiter:
    """One token bucket per service. Refills at `rps`, capacity `rps`.

    Per SERVICE rather than per connection: the unit we are protecting the disk from is
    a service in a retry storm, and on 6PN one service is one or two addresses.
    """

    def __init__(self, rps: int) -> None:
        self.rps = max(1, rps)
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, svc: str, cost: int = 1, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            tokens, last = self._buckets.get(svc, (float(self.rps), now))
            tokens = min(float(self.rps), tokens + (now - last) * self.rps)
            if tokens < cost:
                self._buckets[svc] = (tokens, now)
                return False
            self._buckets[svc] = (tokens - cost, now)
            return True


# --------------------------------------------------------------------------- ingest
class Ingest:
    """Writes batches to `<dir>/<svc>-<day>.jsonl` and enforces the three size caps."""

    def __init__(self, directory: Path | None = None) -> None:
        self._dir = directory
        self._lock = threading.Lock()
        self.counters: dict[str, int] = {
            "accepted": 0,
            "dropped_malformed": 0,
            "dropped_oversize_line": 0,
            "dropped_file_full": 0,
            "dropped_write_error": 0,
            "dropped_rate_limited": 0,
            "evicted_files": 0,
        }

    @property
    def directory(self) -> Path:
        return self._dir if self._dir is not None else log_dir()

    # -- capacity ----------------------------------------------------------------
    def _total_bytes(self) -> int:
        try:
            return sum(p.stat().st_size for p in self.directory.glob("*.jsonl"))
        except OSError:
            return 0

    def _evict_until_under(self, headroom: int) -> list[str]:
        """Delete whole oldest DAYS until the directory fits. Never partial files.

        Deleting the oldest day rather than trimming a file keeps every remaining file a
        complete day, which is what makes `zcat | jq` over the archive answerable.
        """
        evicted: list[str] = []
        cap = max_total_bytes()
        files = []
        for p in self.directory.glob("*.jsonl"):
            m = _DAY_RE.match(p.name)
            if m:
                files.append((m.group("day"), p))
        files.sort(key=lambda t: t[0])
        today = _now().strftime("%Y-%m-%d")
        i = 0
        while self._total_bytes() + headroom > cap and i < len(files):
            day, path = files[i]
            i += 1
            if day == today:
                # Never evict the day we are writing: that would delete the batch we
                # just accepted and loop.
                continue
            try:
                path.unlink()
                evicted.append(path.name)
                self.counters["evicted_files"] += 1
            except OSError:
                continue
        return evicted

    # -- write -------------------------------------------------------------------
    def write(self, lines: list[dict], *, self_event: bool = False) -> dict[str, int]:
        """Append `lines` to their per-service day files. Returns per-call counts."""
        result = {"accepted": 0, "dropped_oversize_line": 0,
                  "dropped_file_full": 0, "dropped_write_error": 0}
        if not lines:
            return result

        day = _now().strftime("%Y-%m-%d")
        batches: dict[str, list[str]] = {}
        for line in lines:
            encoded = json.dumps(line, separators=(",", ":"), ensure_ascii=False)
            if len(encoded.encode("utf-8")) > max_line_bytes():
                result["dropped_oversize_line"] += 1
                continue
            batches.setdefault(line["svc"], []).append(encoded)

        directory = self.directory
        with self._lock:
            try:
                directory.mkdir(parents=True, exist_ok=True)
            except OSError:
                result["dropped_write_error"] += sum(len(v) for v in batches.values())
                self._bump(result)
                return result

            evicted: list[str] = []
            for svc, encoded_lines in batches.items():
                payload = "\n".join(encoded_lines) + "\n"
                size = len(payload.encode("utf-8"))
                path = directory / f"{svc}-{day}.jsonl"
                try:
                    current = path.stat().st_size
                except OSError:
                    current = 0
                if current + size > max_file_day_bytes():
                    result["dropped_file_full"] += len(encoded_lines)
                    continue
                if self._total_bytes() + size > max_total_bytes():
                    evicted.extend(self._evict_until_under(size))
                    if self._total_bytes() + size > max_total_bytes():
                        result["dropped_file_full"] += len(encoded_lines)
                        continue
                try:
                    with path.open("a", encoding="utf-8") as fh:
                        fh.write(payload)
                    result["accepted"] += len(encoded_lines)
                except OSError:
                    result["dropped_write_error"] += len(encoded_lines)

        self._bump(result)
        if evicted and not self_event:
            self.write(
                [{
                    "ts": rfc3339(_now()),
                    "svc": "ingest",
                    "lvl": "warn",
                    "evt": "logs.capacity.evicted",
                    "msg": f"deleted {len(evicted)} day file(s) to stay under the total cap",
                    "host": "ingest",
                    "ctx": {"files": ",".join(evicted)},
                }],
                self_event=True,
            )
        return result

    def _bump(self, result: dict[str, int]) -> None:
        for key, value in result.items():
            if value:
                self.counters[key] = self.counters.get(key, 0) + value


# --------------------------------------------------------------------------- auth
def _expected_key() -> str:
    return os.environ.get("STORE_INTERNAL_API_KEY", "").strip()


def authorised(header: str | None) -> bool:
    """Fail CLOSED. With no key configured nothing is accepted, ever.

    Reuses `STORE_INTERNAL_API_KEY`, the key `Store.Api` and `prospector/ops/console_api.py`
    already share. A new secret would be a new thing to rotate, restore and lose, for no
    extra isolation: anything that can reach this port on 6PN is already inside the estate.
    """
    expected = _expected_key()
    if not expected:
        return False
    if not header or not header.startswith("Bearer "):
        return False
    return hmac.compare_digest(header[len("Bearer "):].strip(), expected)


# --------------------------------------------------------------------------- app
_INGEST = Ingest()
_LIMITER = RateLimiter(rate_limit_rps())


async def post_logs(request: Request) -> Response:
    if not authorised(request.headers.get("authorization")):
        return PlainTextResponse("unauthorised", status_code=401)

    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_body_bytes():
        return PlainTextResponse("body too large", status_code=413)

    body = await request.body()
    if len(body) > max_body_bytes():
        return PlainTextResponse("body too large", status_code=413)

    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return PlainTextResponse("body is not utf-8", status_code=400)

    raw_lines = [ln for ln in text.split("\n") if ln.strip()]
    if len(raw_lines) > max_lines_per_batch():
        return PlainTextResponse("too many lines", status_code=413)

    host = request.client.host if request.client else "unknown"
    now = _now()
    parsed: list[dict] = []
    malformed = 0
    for raw in raw_lines:
        try:
            obj = json.loads(raw)
        except (ValueError, TypeError):
            malformed += 1
            continue
        line = normalise(obj, host, now)
        if line is None:
            malformed += 1
            continue
        parsed.append(line)

    if malformed:
        _INGEST.counters["dropped_malformed"] += malformed

    # Rate limit per service, and DROP rather than queue. A 429 tells a well-behaved
    # producer to slow down; a producer that ignores it still cannot hurt the disk.
    allowed: list[dict] = []
    limited = 0
    for line in parsed:
        if _LIMITER.allow(line["svc"]):
            allowed.append(line)
        else:
            limited += 1
    if limited:
        _INGEST.counters["dropped_rate_limited"] += limited

    counts = _INGEST.write(allowed)
    dropped = malformed + limited + counts["dropped_oversize_line"] \
        + counts["dropped_file_full"] + counts["dropped_write_error"]

    headers = {"X-Accepted": str(counts["accepted"]), "X-Dropped": str(dropped)}
    if limited and not counts["accepted"]:
        return PlainTextResponse("rate limited", status_code=429, headers=headers)
    return Response(status_code=204, headers=headers)


async def get_stats(request: Request) -> Response:
    """Counters and disk use. Unauthenticated readers get nothing.

    This exists so "is the log pipeline working?" is a command, not a belief. A producer
    that thinks it is shipping and an ingest that is dropping everything look identical
    from the producer's side.
    """
    if not authorised(request.headers.get("authorization")):
        return PlainTextResponse("unauthorised", status_code=401)
    directory = _INGEST.directory
    files = sorted(p.name for p in directory.glob("*.jsonl")) if directory.exists() else []
    return JSONResponse({
        "dir": str(directory),
        "files": len(files),
        "bytes": _INGEST._total_bytes(),
        "caps": {
            "line": max_line_bytes(),
            "file_day": max_file_day_bytes(),
            "total": max_total_bytes(),
            "batch_lines": max_lines_per_batch(),
            "body": max_body_bytes(),
            "rps": rate_limit_rps(),
        },
        "counters": dict(_INGEST.counters),
        "services": list(KNOWN_SERVICES),
    })


async def get_health(request: Request) -> Response:
    """Unauthenticated liveness only. Says nothing about content."""
    return JSONResponse({"ok": True, "svc": "log-ingest"})


app = Starlette(routes=[
    Route("/internal/logs", post_logs, methods=["POST"]),
    Route("/internal/logs/stats", get_stats, methods=["GET"]),
    Route("/internal/logs/health", get_health, methods=["GET"]),
])


def main() -> None:  # pragma: no cover - process entry point
    import uvicorn

    uvicorn.run(
        app,
        host=os.environ.get("PROSPECTOR_LOG_INGEST_HOST", "::"),
        port=_int_env("PROSPECTOR_LOG_INGEST_PORT", 8613),
        log_level="warning",
        access_log=False,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
