"""The producer half of the central log: never block, never leak, never lose a tick.

`docs/LOGGING_AND_RETENTION.md` Part 4.4 is the line schema these assert against, and
Part 8 step 7 is the requirement that a logging call cannot fail the work it describes.
"""
from __future__ import annotations

import json
import logging

import pytest

from prospector import log_shipper


def record(msg="hello", level=logging.INFO, **extra) -> logging.LogRecord:
    r = logging.LogRecord("prospector.scheduler", level, "f.py", 10, msg, None, None)
    for k, v in extra.items():
        setattr(r, k, v)
    return r


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    log_shipper._ATTACHED = None
    monkeypatch.setenv("STORE_INTERNAL_API_KEY", "k")
    monkeypatch.setenv("PROSPECTOR_LOG_INGEST_URL", "http://ingest.invalid/internal/logs")
    yield
    log_shipper._ATTACHED = None


# --------------------------------------------------------------------------- schema
def test_a_record_becomes_a_line_the_ingest_accepts():
    from prospector import log_ingest

    line = log_shipper.to_line(record(), "scheduler")
    assert set(("ts", "svc", "lvl", "evt")) <= set(line)
    assert log_ingest.normalise(line, "1.2.3.4", log_ingest._now()) is not None


def test_the_producer_never_sets_host():
    """`host` is the ingest's to set. A producer that sets it can impersonate."""
    assert "host" not in log_shipper.to_line(record(), "scheduler")


def test_levels_map_onto_the_five_the_schema_allows():
    from prospector.log_ingest import LEVELS

    for py, expected in [(logging.DEBUG, "debug"), (logging.INFO, "info"),
                         (logging.WARNING, "warn"), (logging.ERROR, "error"),
                         (logging.CRITICAL, "crit")]:
        lvl = log_shipper.to_line(record(level=py), "engine")["lvl"]
        assert lvl == expected and lvl in LEVELS


def test_an_explicit_event_name_is_used():
    assert log_shipper.to_line(record(event="tick.started"), "scheduler")["evt"] == "tick.started"


def test_evt_is_stable_and_never_the_interpolated_message():
    """A per-candidate `evt` makes the field uncountable, which is the point of having it."""
    a = log_shipper.to_line(record("vetted candidate abc123"), "engine")["evt"]
    b = log_shipper.to_line(record("vetted candidate def456"), "engine")["evt"]
    assert a == b == "log.prospector.scheduler"


def test_a_dirty_event_name_is_sanitised():
    assert log_shipper.to_line(record(event="Tick Started!!"), "e")["evt"] == "tick.started"


def test_extras_land_in_a_flat_ctx():
    line = log_shipper.to_line(record(candidate_id="c1", cost=0.02), "engine")
    assert line["ctx"]["candidate_id"] == "c1" and line["ctx"]["cost"] == 0.02


def test_a_nested_extra_is_rendered_not_nested():
    """`ctx` is flat by contract, so no shape can surprise a reader or a filter."""
    line = log_shipper.to_line(record(payload={"a": 1}), "engine")
    assert isinstance(line["ctx"]["payload"], str)


def test_a_correlation_id_is_promoted_out_of_ctx():
    line = log_shipper.to_line(record(corr="req-9"), "store-api")
    assert line["corr"] == "req-9" and "corr" not in line.get("ctx", {})


def test_a_broken_format_string_still_produces_a_line():
    r = logging.LogRecord("x", logging.INFO, "f.py", 1, "%s and %s", ("only-one",), None)
    assert log_shipper.to_line(r, "engine")["evt"]


# --------------------------------------------------------------------------- secrets
@pytest.mark.parametrize("field", [
    "api_key", "STORE_INTERNAL_API_KEY", "stripe_secret", "auth_token", "password",
    "authorization", "session_cookie", "agent_pem", "private_key", "credentials",
])
def test_a_credential_shaped_field_never_leaves_the_process(field):
    line = log_shipper.to_line(record(**{field: "sk-live-shouldnotappear"}), "engine")
    assert "shouldnotappear" not in json.dumps(line)
    assert line["ctx"][field] == "[redacted]"


def test_an_ordinary_field_is_not_redacted():
    line = log_shipper.to_line(record(pack_id="p-1"), "engine")
    assert line["ctx"]["pack_id"] == "p-1"


# --------------------------------------------------------------------------- non-blocking
def test_emit_does_no_io():
    """The whole design brief: a logging call must not be able to fail a tick."""
    h = log_shipper.IngestHandler("engine", url="http://ingest.invalid/x", key="k")

    def explode(*a, **k):
        raise AssertionError("emit() performed a network call")

    h.post = explode  # type: ignore[method-assign]
    h.emit(record())
    assert len(h._queue) == 1


def test_a_dead_ingest_never_raises_and_is_counted():
    h = log_shipper.IngestHandler("engine", url="http://127.0.0.1:1/x", key="k", timeout=0.2)
    h.emit(record())
    h.flush()
    assert h.counters["failed_posts"] == 1 and h.counters["sent"] == 0


def test_the_buffer_is_bounded_so_an_outage_costs_lines_not_memory():
    h = log_shipper.IngestHandler("engine", url="http://x/y", key="k", capacity=3)
    for _ in range(10):
        h.emit(record())
    assert len(h._queue) == 3 and h.counters["dropped_full"] == 7


def test_a_successful_post_drains_the_queue():
    h = log_shipper.IngestHandler("engine", url="http://x/y", key="k")
    sent: list[list[dict]] = []

    def capture(lines):
        sent.append(lines)
        h.counters["sent"] += len(lines)
        return True

    h.post = capture  # type: ignore[method-assign]
    for _ in range(3):
        h.emit(record())
    h.flush()
    assert not h._queue and sum(len(b) for b in sent) == 3


def test_flush_terminates_when_posting_fails():
    """A failing post must not put lines back and spin forever."""
    h = log_shipper.IngestHandler("engine", url="http://127.0.0.1:1/x", key="k", timeout=0.2)
    for _ in range(5):
        h.emit(record())
    h.flush()
    assert not h._queue


# --------------------------------------------------------------------------- attach
def test_attach_is_off_when_no_key_is_configured(monkeypatch):
    monkeypatch.delenv("STORE_INTERNAL_API_KEY", raising=False)
    assert log_shipper.attach("engine") is None


def test_attach_is_idempotent(monkeypatch):
    logger = logging.getLogger("test-attach-idem")
    first = log_shipper.attach("engine", logger=logger)
    second = log_shipper.attach("engine", logger=logger)
    assert first is second
    assert sum(isinstance(h, log_shipper.IngestHandler) for h in logger.handlers) == 1
    log_shipper._ATTACHED = None
    logger.handlers = [h for h in logger.handlers if not isinstance(h, log_shipper.IngestHandler)]


# --------------------------------------------------------------------------- wiring
def test_the_engine_entry_points_attach_the_shipper():
    """An ingest with no producer is a built-and-unreachable endpoint, and we have had
    several. These two call sites are the only reason a line ever leaves this machine."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    run_py = (root / "prospector" / "run.py").read_text()
    assert "log_shipper import attach" in run_py, (
        "prospector/run.py no longer ships its logs centrally; `vet`, `generate` and "
        "`consume` would go back to writing only a local file")

    sched = (root / "prospector" / "scheduler" / "run_scheduled.py").read_text()
    assert "log_shipper import attach" in sched, (
        "the scheduler daemon no longer ships its logs centrally")
    assert 'attach_central_log("scheduler")' in sched


def test_the_consumer_is_named_as_its_own_service():
    """`consume` is the drain. It shares a process entry point with the engine's other
    commands, so without this it would be indistinguishable in the console filter."""
    from pathlib import Path

    run_py = (Path(__file__).resolve().parents[2] / "prospector" / "run.py").read_text()
    assert '"consumer" if getattr(args, "command", "") == "consume"' in run_py
