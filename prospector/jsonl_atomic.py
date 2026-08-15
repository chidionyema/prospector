"""Torn-write-safe append and tolerant read for the append-only JSONL trails.

R3 of `docs/COMMERCIAL_READINESS_PROGRAM.md` §2.6. Covers the scheduler's state files —
`store/scheduler/ticks.jsonl`, `store/scheduler/alerts.jsonl`, and their siblings under
`store/scheduler/` (`audit/<day>.jsonl`, `batch_diagnostics.jsonl`,
`pending_unlist.done.jsonl`).

WHY NOT tmp+rename
------------------
The spec offers "tmp+rename or fsync + tolerant reader". For these files tmp+rename is not
merely the weaker option, it is **actively destructive**, and the reason is the shape of the
workload rather than a preference:

1. These files are APPEND-ONLY LOGS WITH CONCURRENT WRITERS. `ticks.jsonl` is written by the
   live daemon (pid 19735 at the time of writing) *and*, at a measured 59.6 rows/hour, by a
   one-shot driver in the adjacent Hermes estate (`run_scheduled._append_tick` docstring).
   `audit/<day>.jsonl` is written by the daemon, backfills and every manual CLI run at once.
2. To append via tmp+rename you must read the whole file, add your line, and rename the copy
   over the original. Every line another process appended between your read and your rename is
   **silently deleted** — the copy never contained it. That is a data-loss bug that scales with
   traffic and is invisible in the result.
3. `os.replace` also swaps the inode. Any peer holding an open O_APPEND descriptor keeps
   writing into the now-unlinked old inode, so its subsequent lines vanish too.

So the design here is the other branch: a single `O_APPEND` write, optional `fsync`, and a
reader that tolerates a torn tail.

WHY A SINGLE O_APPEND write IS THE SAFE PRIMITIVE
-------------------------------------------------
POSIX (`write()`, XSH 2.9.7) requires that when `O_APPEND` is set the offset is moved to
end-of-file and the write performed with *no intervening file modification*. Linux and Darwin
implement that under the inode lock, so two appenders can never overwrite each other and can
never interleave their byte ranges. One record therefore lands as one contiguous run of bytes
or not at all — which is exactly guarantee (a), "fully present or absent".

The residual torn-write risks are narrow and handled explicitly:

* **Short write** (ENOSPC, EFBIG, EINTR). We issue ONE `os.write` for the whole payload and
  deliberately DO NOT retry the remainder. Retrying under `O_APPEND` re-seeks to the *current*
  end of file, so a peer's complete line can land between our two fragments — turning one torn
  record into two corrupt ones. A short write raises `TornAppendError` (an `OSError`, so every
  existing `except OSError` caller keeps working) and leaves exactly one damaged line.
* **Crash / power loss.** Without `fsync` the tail of the file may be a partial line after
  recovery. `fsync=True` (the default for these low-rate trails) makes the record durable
  before the call returns; the tolerant reader covers the window regardless.

WHAT THE FORMAT CANNOT DO
-------------------------
Bare newline-delimited JSON has no framing, so a mid-file short write costs the damaged record
and merges it with its successor. Fixing that needs a length prefix or a checksum, which would
break every existing reader of these files (including external ones). Out of scope for R3; the
reader below reports such lines instead of hiding them.

Paths are ARGUMENTS, never module state: nothing here binds a store path at import, which is
the defect that let pytest reach the production audit log and durable ledger.
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional, Union

logger = logging.getLogger(__name__)

__all__ = [
    "TornAppendError",
    "append_jsonl",
    "append_line",
    "consume_jsonl",
    "iter_jsonl",
    "read_jsonl",
    "read_jsonl_with_stats",
    "ReadStats",
]

#: Above this a single record is large enough that a short write stops being negligible
#: (the kernel still writes it under one inode lock, but ENOSPC/EFBIG get likelier). Logged,
#: never refused: dropping a diagnostic because it was big is worse than a warning.
_LARGE_RECORD_BYTES = 1 << 20  # 1 MiB


class TornAppendError(OSError):
    """A record was only partially written and the remainder was deliberately not retried.

    Subclasses `OSError` on purpose: every existing appender in this repo already wraps its
    write in `except OSError` and logs, so a torn append degrades to the same handled path
    rather than escaping as a novel exception type into the daemon loop.
    """


def _payload(record: Any, *, compact: bool) -> bytes:
    if isinstance(record, (bytes, bytearray)):
        raw = bytes(record)
    elif isinstance(record, str):
        raw = record.encode("utf-8")
    else:
        sep = (",", ":") if compact else (", ", ": ")
        raw = json.dumps(record, default=str, separators=sep).encode("utf-8")
    # A record containing a newline would split into two "records" on read. Refuse rather than
    # write a line the reader can never reassemble.
    if b"\n" in raw:
        raise ValueError("JSONL record must not contain a newline; got embedded \\n")
    return raw + b"\n"


def append_line(
    path: Union[str, Path],
    payload: bytes,
    *,
    fsync: bool = True,
    mkdir: bool = True,
    heal: bool = True,
) -> int:
    """Append `payload` (which must already end in b"\\n") with one O_APPEND write.

    `heal` bounds the blast radius of a torn tail to the ONE record that was torn. Without it,
    a file whose last byte is not a newline splices the next record onto the fragment, so a
    single short write (or a crash) silently destroys every subsequent append as well. When the
    file does not end in a newline we prepend one to the payload — still a single write, so
    atomicity is unchanged, and the worst case if two appenders both heal is a blank line, which
    the reader already skips. Set `heal=False` only to demonstrate the unhealed behaviour.

    Returns the number of bytes written. Raises `TornAppendError` on a short write and plain
    `OSError` on anything else the kernel reports.
    """
    p = Path(path)
    if mkdir:
        p.parent.mkdir(parents=True, exist_ok=True)
    if len(payload) > _LARGE_RECORD_BYTES:
        logger.warning(
            "Appending a %d-byte record to %s; large records raise short-write risk", len(payload), p
        )
    # O_RDWR rather than O_WRONLY when healing: `os.pread` on a write-only descriptor fails
    # with EBADF. O_APPEND still forces every write to the current end of file either way.
    flags = (os.O_RDWR if heal else os.O_WRONLY) | os.O_APPEND | os.O_CREAT
    fd = os.open(str(p), flags, 0o644)
    try:
        # Advisory exclusive lock. This is NOT what makes concurrent appends safe — the single
        # O_APPEND write already is, and that guarantee holds for writers who never take this
        # lock. It exists so a CONSUMER (`consume_jsonl`) can take records out of the file
        # without a producer's append landing in the window between its read and its rewrite.
        # Two syscalls; released by the kernel on close or process death, so it cannot be left
        # held by a crash.
        fcntl.flock(fd, fcntl.LOCK_EX)
        if heal:
            size = os.fstat(fd).st_size
            # O_APPEND writes always land at the then-current EOF, so reading the size here and
            # writing after it is not a TOCTOU on our own record — only on the heal decision,
            # whose worst outcome is a redundant blank line.
            if size and os.pread(fd, 1, size - 1) != b"\n":
                logger.warning(
                    "%s does not end in a newline (torn tail); prefixing one so this record "
                    "is not spliced onto the fragment", p,
                )
                payload = b"\n" + payload
        written = os.write(fd, payload)
        if written != len(payload):
            # See module docstring: no retry. A second write would re-seek to the *current*
            # EOF and could land after a peer's line, corrupting two records instead of one.
            raise TornAppendError(
                f"short append to {p}: wrote {written} of {len(payload)} bytes; "
                "remainder NOT retried (a retry under O_APPEND can interleave with a peer)"
            )
        if fsync:
            os.fsync(fd)
        return written
    finally:
        os.close(fd)


def append_jsonl(
    path: Union[str, Path],
    record: Any,
    *,
    fsync: bool = True,
    compact: bool = False,
    mkdir: bool = True,
    heal: bool = True,
) -> int:
    """Serialise `record` to one JSON line and append it atomically. Returns bytes written.

    Safe for concurrent appenders in other processes — see the module docstring. Non-serialisable
    values fall back to `str` (`json.dumps(default=str)`), matching every call site this replaced.
    """
    return append_line(
        path, _payload(record, compact=compact), fsync=fsync, mkdir=mkdir, heal=heal
    )


def consume_jsonl(path: Union[str, Path], *, fsync: bool = True) -> list:
    """Take every COMMITTED record out of `path` and leave the file empty. Returns the records.

    For the queue-shaped trails: one process appends work, another drains it. The obvious drain
    is `read()` the file, do the work, then `write_text("")` — and it silently deletes every
    record the producer appended in between. `tools/unlist_killed.py:113` did exactly that
    against `decay._queue_unlist`, on the path that pulls a pack the engine has re-vetted to
    KILL out of the live catalogue. A lost record there is a killed pack that keeps selling,
    which is the specific failure that path was built to end.

    This is the same lost-update class as the tmp+rename the module docstring rejects, arriving
    by a different route: there the loss is a peer's line dropped from a copy, here it is a
    peer's line dropped by a truncation. Both are "I decided what the whole file should contain
    from a snapshot that was already stale."

    How the window is closed: the read, the truncate and the rewrite all happen under one
    `flock(LOCK_EX)` that `append_line` also takes, so a producer either got its bytes in
    before the drain (and is returned here) or waits and appends to the emptied file.

    A torn trailing fragment — bytes after the last newline, an append still in flight or
    crash-truncated — is NOT consumed and NOT deleted. It is written back as the file's new
    contents, because a record without its terminating newline was never committed and is not
    this function's to take. Corrupt but newline-terminated lines ARE consumed and dropped,
    with a warning: leaving them would re-present the same unparseable line on every drain
    forever.

    Missing file → `[]`, no file created. Never raises on content.
    """
    p = Path(path)
    try:
        fd = os.open(str(p), os.O_RDWR)
    except FileNotFoundError:
        return []
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        size = os.fstat(fd).st_size
        data = b""
        while len(data) < size:
            chunk = os.pread(fd, size - len(data), len(data))
            if not chunk:
                break
            data += chunk

        head, sep, tail = data.rpartition(b"\n")
        if not sep:
            # No committed record at all: either empty, or one fragment mid-append. Leave the
            # file exactly as found — truncating here would destroy an in-flight append.
            return []

        records: list = []
        corrupt = 0
        for raw in head.split(b"\n"):
            obj = _decode(raw)
            if obj is None:
                if raw.strip():
                    corrupt += 1
                continue
            records.append(obj)

        os.ftruncate(fd, 0)
        if tail:
            os.pwrite(fd, tail, 0)
        if fsync:
            os.fsync(fd)
    finally:
        os.close(fd)

    if corrupt:
        logger.warning("Dropped %d unparseable line(s) while draining %s", corrupt, p)
    if tail:
        logger.warning(
            "Left a %d-byte torn tail in %s undrained (no terminating newline, so the record "
            "was never committed)", len(tail), p,
        )
    return records


class ReadStats:
    """What a tolerant read had to throw away. Observability, not control flow."""

    __slots__ = ("rows", "torn_tail_bytes", "corrupt_lines", "first_corrupt_lineno",
                 "read_error")

    def __init__(self) -> None:
        self.rows = 0
        self.torn_tail_bytes = 0
        self.corrupt_lines = 0
        self.first_corrupt_lineno: Optional[int] = None
        #: Set when the file could not be OPENED (not when it was merely absent). This is the
        #: one condition under which zero rows is not a fact about the file's contents, and
        #: without it "no ticks yet" and "ticks.jsonl is unreadable" are the same empty list.
        self.read_error: Optional[str] = None

    @property
    def clean(self) -> bool:
        return (self.torn_tail_bytes == 0 and self.corrupt_lines == 0
                and self.read_error is None)

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (
            f"ReadStats(rows={self.rows}, torn_tail_bytes={self.torn_tail_bytes}, "
            f"corrupt_lines={self.corrupt_lines}, read_error={self.read_error!r})"
        )


def _decode(raw: bytes) -> Optional[Any]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def iter_jsonl(
    path: Union[str, Path],
    *,
    stats: Optional[ReadStats] = None,
    warn: bool = True,
) -> Iterator[Any]:
    """Yield every INTACT record in `path`, skipping a torn trailing line and corrupt lines.

    The rule for the tail is mechanical rather than a parse heuristic: **a record is committed
    only when its terminating newline is on disk.** Bytes after the last newline are an
    in-flight or crash-truncated append and are dropped without being parsed — a truncated
    record can still be syntactically valid JSON (`{"a": 1}` is a prefix of
    `{"a": 1, "b": 2}`), so trusting `json.loads` on the tail would silently return a record
    that was never written.

    Streams line-by-line with a one-line lookahead: `ticks.jsonl` is already ~1300 lines and the
    ledger-shaped trails run to hundreds of thousands, so the reader must not need the file in
    memory. Missing file → empty iterator. Never raises on content.

    `warn` governs tolerance of CONTENT — a torn tail, unparseable lines. It does NOT silence a
    failure to open the file, because that is not a fact about the content: every live caller
    passes `warn=False` (`scheduler/status.py:85`, `scheduler/run_scheduled.py:1288,1779`), so an
    unreadable `ticks.jsonl` used to return the same empty list as a daemon that had never
    ticked, with nothing logged anywhere. `status.py:85` even wraps this call in
    `except (OSError, ValueError)` — a handler that could never fire, because the error was
    swallowed here. `ReadStats.read_error` is how a caller tells the two apart.
    """
    p = Path(path)
    st = stats if stats is not None else ReadStats()
    try:
        fh = open(p, "rb")
    except FileNotFoundError:
        return                            # genuinely no records: nothing has been appended yet
    except OSError as exc:
        st.read_error = f"{type(exc).__name__}: {exc}"
        logger.error("Cannot read %s: %s — returning 0 records, which is NOT evidence the file "
                     "is empty", p, exc)
        return
    with fh:
        lineno = 0
        prev: Optional[bytes] = None

        def _emit(raw: bytes, no: int):
            obj = _decode(raw)
            if obj is None:
                if raw.strip():
                    st.corrupt_lines += 1
                    if st.first_corrupt_lineno is None:
                        st.first_corrupt_lineno = no
                return None
            st.rows += 1
            return (obj,)

        for raw in fh:
            lineno += 1
            if prev is not None:
                got = _emit(prev, lineno - 1)
                if got:
                    yield got[0]
            prev = raw
        if prev is not None:
            if prev.endswith(b"\n"):
                got = _emit(prev, lineno)
                if got:
                    yield got[0]
            else:
                # No terminating newline: an append that did not complete. Drop it.
                st.torn_tail_bytes = len(prev)
                if warn:
                    logger.warning(
                        "Skipping torn trailing line in %s (%d bytes, no terminating newline); "
                        "%d intact records returned", p, len(prev), st.rows,
                    )
    if warn and st.corrupt_lines:
        logger.warning(
            "Skipped %d unparseable line(s) in %s (first at line %s)",
            st.corrupt_lines, p, st.first_corrupt_lineno,
        )


def read_jsonl(
    path: Union[str, Path],
    *,
    tail: Optional[int] = None,
    warn: bool = True,
) -> list:
    """All intact records in `path` as a list; `tail=N` keeps only the last N intact records."""
    return read_jsonl_with_stats(path, tail=tail, warn=warn)[0]


def read_jsonl_with_stats(
    path: Union[str, Path],
    *,
    tail: Optional[int] = None,
    warn: bool = True,
) -> tuple[list, ReadStats]:
    """`(records, ReadStats)` — same as `read_jsonl` but also reports what was discarded."""
    st = ReadStats()
    it: Iterable[Any] = iter_jsonl(path, stats=st, warn=warn)
    if tail is None:
        return list(it), st
    if tail <= 0:
        for _ in it:
            pass
        return [], st
    from collections import deque

    return list(deque(it, maxlen=tail)), st
