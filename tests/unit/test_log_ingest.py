"""The central log ingest: auth, the three caps, and the drops that must stay silent.

`docs/LOGGING_AND_RETENTION.md` Part 4 is the specification these assert against. Every
test here names the failure it would catch, because a cap with no test that hits it is a
number in a comment.
"""
from __future__ import annotations

import json

import pytest
from starlette.testclient import TestClient

from prospector import log_ingest

KEY = "test-internal-key"
AUTH = {"Authorization": f"Bearer {KEY}"}


@pytest.fixture
def ingest(tmp_path, monkeypatch):
    monkeypatch.setenv("STORE_INTERNAL_API_KEY", KEY)
    monkeypatch.setenv("PROSPECTOR_LOG_DIR", str(tmp_path / "logs"))
    log_ingest._INGEST = log_ingest.Ingest()
    log_ingest._LIMITER = log_ingest.RateLimiter(log_ingest.rate_limit_rps())
    return tmp_path / "logs"


@pytest.fixture
def client(ingest):
    return TestClient(log_ingest.app)


def ndjson(*objs) -> str:
    return "\n".join(json.dumps(o) for o in objs)


def line(**over):
    base = {"ts": "2026-08-19T12:00:00.000Z", "svc": "engine",
            "lvl": "info", "evt": "tick.started"}
    base.update(over)
    return base


# --------------------------------------------------------------------------- auth
def test_no_key_configured_refuses_everything(tmp_path, monkeypatch):
    """Fail CLOSED. An ingest with no key must not become an open write endpoint."""
    monkeypatch.delenv("STORE_INTERNAL_API_KEY", raising=False)
    monkeypatch.setenv("PROSPECTOR_LOG_DIR", str(tmp_path / "logs"))
    log_ingest._INGEST = log_ingest.Ingest()
    c = TestClient(log_ingest.app)
    r = c.post("/internal/logs", content=ndjson(line()),
               headers={"Authorization": "Bearer anything"})
    assert r.status_code == 401


def test_wrong_key_is_401(client):
    r = client.post("/internal/logs", content=ndjson(line()),
                    headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_missing_header_is_401(client):
    assert client.post("/internal/logs", content=ndjson(line())).status_code == 401


def test_stats_needs_the_key(client):
    assert client.get("/internal/logs/stats").status_code == 401
    assert client.get("/internal/logs/stats", headers=AUTH).status_code == 200


def test_health_is_open_and_says_nothing_about_content(client):
    r = client.get("/internal/logs/health")
    assert r.status_code == 200 and r.json()["ok"] is True


# --------------------------------------------------------------------------- writing
def test_a_good_batch_lands_in_one_file_per_service(client, ingest):
    r = client.post("/internal/logs",
                    content=ndjson(line(), line(svc="scheduler", evt="drain.done")),
                    headers=AUTH)
    assert r.status_code == 204
    assert r.headers["X-Accepted"] == "2"
    names = sorted(p.name.split("-2")[0] for p in ingest.glob("*.jsonl"))
    assert names == ["engine", "scheduler"]


def test_appends_rather_than_truncates(client, ingest):
    for _ in range(3):
        client.post("/internal/logs", content=ndjson(line()), headers=AUTH)
    written = list(ingest.glob("engine-*.jsonl"))
    assert len(written) == 1
    assert len(written[0].read_text().strip().splitlines()) == 3


def test_empty_body_is_accepted_not_an_error(client):
    """A producer flushing an empty buffer must never see a failure."""
    r = client.post("/internal/logs", content="", headers=AUTH)
    assert r.status_code == 204 and r.headers["X-Accepted"] == "0"


def test_unknown_fields_survive(client, ingest):
    client.post("/internal/logs",
                content=ndjson(line(corr="abc123", ctx={"pack": "p1"}, extra=7)),
                headers=AUTH)
    row = json.loads(next(ingest.glob("engine-*.jsonl")).read_text().splitlines()[0])
    assert row["corr"] == "abc123" and row["ctx"] == {"pack": "p1"} and row["extra"] == 7


# --------------------------------------------------------------------------- schema
def test_host_is_taken_from_the_connection_not_the_client(client, ingest):
    """A client that names its own host could impersonate another service."""
    client.post("/internal/logs", content=ndjson(line(host="i-am-store-api")),
                headers=AUTH)
    row = json.loads(next(ingest.glob("engine-*.jsonl")).read_text().splitlines()[0])
    assert row["host"] != "i-am-store-api"


def test_a_service_name_cannot_escape_the_directory(client, ingest, tmp_path):
    """`svc` is a filename component. This is the path-traversal gate."""
    for bad in ("../evil", "/etc/passwd", "eng/ine", "ENGINE", "", "a" * 40):
        r = client.post("/internal/logs", content=ndjson(line(svc=bad)), headers=AUTH)
        assert r.status_code == 204, bad
        assert r.headers["X-Accepted"] == "0", bad
    assert not list(tmp_path.rglob("evil*"))
    assert list(ingest.glob("*.jsonl")) == []


def test_a_line_with_no_event_name_is_dropped(client, ingest):
    r = client.post("/internal/logs",
                    content=ndjson({"svc": "engine", "lvl": "info"}), headers=AUTH)
    assert r.headers["X-Accepted"] == "0" and r.headers["X-Dropped"] == "1"


def test_a_missing_timestamp_is_repaired_not_dropped(client, ingest):
    client.post("/internal/logs",
                content=ndjson({"svc": "engine", "lvl": "info", "evt": "x"}),
                headers=AUTH)
    row = json.loads(next(ingest.glob("engine-*.jsonl")).read_text().splitlines()[0])
    assert row["ts"].endswith("Z") and row["ts"].startswith("20")


def test_an_unknown_level_becomes_info_rather_than_a_drop(client, ingest):
    client.post("/internal/logs", content=ndjson(line(lvl="VERBOSE")), headers=AUTH)
    row = json.loads(next(ingest.glob("engine-*.jsonl")).read_text().splitlines()[0])
    assert row["lvl"] == "info"


def test_one_malformed_line_does_not_lose_the_batch(client, ingest):
    body = ndjson(line()) + "\n{not json\n" + ndjson(line(evt="tick.done"))
    r = client.post("/internal/logs", content=body, headers=AUTH)
    assert r.status_code == 204
    assert r.headers["X-Accepted"] == "2" and r.headers["X-Dropped"] == "1"


def test_a_service_outside_the_known_list_is_still_written(client, ingest):
    """Dropping a real producer over a stale tuple is the failure this avoids."""
    client.post("/internal/logs", content=ndjson(line(svc="new-thing")), headers=AUTH)
    assert [p.name.split("-2")[0] for p in ingest.glob("*.jsonl")] == ["new-thing"]


# --------------------------------------------------------------------------- caps
def test_a_body_over_the_cap_is_413(client, monkeypatch):
    monkeypatch.setenv("PROSPECTOR_LOG_MAX_BODY_BYTES", "200")
    r = client.post("/internal/logs", content="x" * 500, headers=AUTH)
    assert r.status_code == 413


def test_more_than_the_line_limit_is_413(client, monkeypatch):
    monkeypatch.setenv("PROSPECTOR_LOG_MAX_LINES", "3")
    r = client.post("/internal/logs", content=ndjson(*[line()] * 4), headers=AUTH)
    assert r.status_code == 413


def test_one_oversize_line_is_dropped_and_the_rest_kept(client, ingest, monkeypatch):
    monkeypatch.setenv("PROSPECTOR_LOG_MAX_LINE_BYTES", "200")
    body = ndjson(line(), line(msg="y" * 400))
    r = client.post("/internal/logs", content=body, headers=AUTH)
    assert r.status_code == 204
    assert r.headers["X-Accepted"] == "1" and r.headers["X-Dropped"] == "1"


def test_a_full_day_file_stops_accepting_and_counts(client, ingest, monkeypatch):
    monkeypatch.setenv("PROSPECTOR_LOG_MAX_FILE_BYTES", "400")
    for _ in range(20):
        client.post("/internal/logs", content=ndjson(line()), headers=AUTH)
    written = next(ingest.glob("engine-*.jsonl"))
    assert written.stat().st_size <= 400
    assert log_ingest._INGEST.counters["dropped_file_full"] > 0


def test_the_total_cap_evicts_the_oldest_day_and_records_it(ingest, monkeypatch):
    """Deleting a whole old day keeps every remaining file a complete day."""
    monkeypatch.setenv("STORE_INTERNAL_API_KEY", KEY)
    monkeypatch.setenv("PROSPECTOR_LOG_DIR", str(ingest))
    ingest.mkdir(parents=True, exist_ok=True)
    old = ingest / "engine-2020-01-01.jsonl"
    old.write_text("x" * 890)
    monkeypatch.setenv("PROSPECTOR_LOG_MAX_TOTAL_BYTES", "900")
    ing = log_ingest.Ingest()
    log_ingest._INGEST = ing
    counts = ing.write([log_ingest.normalise(line(), "h", log_ingest._now())])
    assert counts["accepted"] == 1
    assert not old.exists()
    assert ing.counters["evicted_files"] == 1
    self_log = next(ingest.glob("ingest-*.jsonl")).read_text()
    assert "logs.capacity.evicted" in self_log


def test_eviction_never_deletes_todays_file(ingest, monkeypatch):
    monkeypatch.setenv("PROSPECTOR_LOG_DIR", str(ingest))
    ingest.mkdir(parents=True, exist_ok=True)
    today = log_ingest._now().strftime("%Y-%m-%d")
    mine = ingest / f"engine-{today}.jsonl"
    mine.write_text("x" * 800)
    monkeypatch.setenv("PROSPECTOR_LOG_MAX_TOTAL_BYTES", "10")
    ing = log_ingest.Ingest()
    ing._evict_until_under(0)
    assert mine.exists()


def test_a_write_error_is_counted_never_raised(ingest, monkeypatch):
    """A full disk must not turn into a 500 in the service that was only logging."""
    monkeypatch.setenv("PROSPECTOR_LOG_DIR", str(ingest))
    ing = log_ingest.Ingest()

    class Boom:
        def __call__(self, *a, **k):
            raise OSError("no space left on device")

    monkeypatch.setattr("pathlib.Path.open", Boom())
    counts = ing.write([log_ingest.normalise(line(), "h", log_ingest._now())])
    assert counts["accepted"] == 0 and counts["dropped_write_error"] == 1


# --------------------------------------------------------------------------- limiter
def test_the_limiter_drops_rather_than_queues():
    lim = log_ingest.RateLimiter(rps=2)
    assert lim.allow("engine", now=0.0)
    assert lim.allow("engine", now=0.0)
    assert not lim.allow("engine", now=0.0)
    assert lim.allow("engine", now=1.0)


def test_one_noisy_service_cannot_starve_another():
    lim = log_ingest.RateLimiter(rps=1)
    assert lim.allow("engine", now=0.0)
    assert not lim.allow("engine", now=0.0)
    assert lim.allow("store-api", now=0.0)


def test_a_fully_rate_limited_batch_is_429(client, ingest, monkeypatch):
    log_ingest._LIMITER = log_ingest.RateLimiter(rps=1)
    log_ingest._LIMITER.allow("engine", now=time_now())
    r = client.post("/internal/logs", content=ndjson(line()), headers=AUTH)
    assert r.status_code == 429
    assert r.headers["X-Accepted"] == "0" and r.headers["X-Dropped"] == "1"
    assert log_ingest._INGEST.counters["dropped_rate_limited"] == 1


def time_now() -> float:
    import time as _t
    return _t.monotonic()


# --------------------------------------------------------------------------- paths
def test_the_log_dir_follows_the_store_not_the_source_file(monkeypatch):
    """A `__file__`-anchored path follows the CODE. Production runs another checkout."""
    monkeypatch.delenv("PROSPECTOR_LOG_DIR", raising=False)
    monkeypatch.setenv("PROSPECTOR_STORE_DIR", "/data/store")
    assert log_ingest.log_dir() == __import__("pathlib").Path("/data/logs")


def test_an_explicit_log_dir_wins(monkeypatch):
    monkeypatch.setenv("PROSPECTOR_LOG_DIR", "/somewhere/else")
    assert str(log_ingest.log_dir()) == "/somewhere/else"


# --------------------------------------------------------------------------- wiring
def test_something_actually_runs_the_ingest():
    """An endpoint nothing starts is a design document with a test suite attached."""
    from pathlib import Path

    conf = (Path(__file__).resolve().parents[2]
            / "deploy" / "engine" / "supervisord.conf").read_text()
    assert "[program:log-ingest]" in conf, (
        "nothing on the engine runs prospector.log_ingest, so every producer would post "
        "into a connection refused")
    block = conf.split("[program:log-ingest]", 1)[1].split("[program:", 1)[0]
    assert "python -m prospector.log_ingest" in block
    assert "autostart=true" in block and "autorestart=true" in block


def test_the_ingest_port_is_not_published_publicly():
    """8613 writes to disk on a shared bearer key. It must stay on the private network."""
    from pathlib import Path

    toml = (Path(__file__).resolve().parents[2]
            / "deploy" / "engine" / "fly.toml").read_text()
    published = toml.split("[http_service]", 1)[1] if "[http_service]" in toml else ""
    assert "8613" not in published, (
        "the log ingest port appears in fly.toml's published service block, which would put "
        "a disk-writing endpoint on the public internet")


# --------------------------------------------------------------------------- OTLP (#501)
# The OTLP DECODING is pinned in tests/unit/test_otlp.py against bytes the OpenTelemetry .NET
# exporter really wrote. What is asserted here is the ENDPOINT: that OTLP arrives under the same
# auth, the same caps and the same drop-never-block rule as everything else, and that a producer
# we did not write can tell whether its lines landed.

import pathlib

OTLP_URL = "/internal/logs/otlp"
DOTNET_PAYLOAD = (pathlib.Path(__file__).resolve().parents[1]
                  / "fixtures" / "otlp" / "dotnet_1_15_3_logs.protobuf")
PB = {"Content-Type": "application/x-protobuf"}


def otlp_json(svc="engine", evt="tick.started", body="a sentence"):
    return {"resourceLogs": [{
        "resource": {"attributes": [
            {"key": "service.name", "value": {"stringValue": svc}}]},
        "scopeLogs": [{"scope": {"name": "s"}, "logRecords": [{
            "body": {"stringValue": body},
            "severityText": "Information",
            "attributes": [{"key": "evt", "value": {"stringValue": evt}}],
        }]}],
    }]}


def test_otlp_needs_the_same_bearer_key(client):
    """A new route is a new way in. Adding one that forgot auth would put the whole log store
    behind nothing at all."""
    assert client.post(OTLP_URL, json=otlp_json()).status_code == 401
    assert client.post(OTLP_URL, json=otlp_json(),
                       headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_otlp_json_lands_as_the_same_line_ndjson_would(client, ingest):
    r = client.post(OTLP_URL, json=otlp_json(), headers=AUTH)
    assert r.status_code == 200, r.text
    assert r.headers["X-Accepted"] == "1"
    assert r.headers["X-Dropped"] == "0"

    files = list(ingest.glob("engine-*.jsonl"))
    assert len(files) == 1, "OTLP did not write an engine day file: %s" % list(ingest.glob("*"))
    written = json.loads(files[0].read_text().splitlines()[0])
    assert written["svc"] == "engine"
    assert written["evt"] == "tick.started"
    assert written["lvl"] == "info"
    assert written["msg"] == "a sentence"
    assert written["host"], "host must be stamped by the ingest"


def test_the_real_dotnet_payload_lands_end_to_end(client, ingest):
    """The whole of #501 in one assertion: the exporter Store.Api compiles, posting its own
    bytes, ending up as a line in the same store every other service writes to."""
    r = client.post(OTLP_URL, content=DOTNET_PAYLOAD.read_bytes(), headers={**AUTH, **PB})
    assert r.status_code == 200, r.text
    assert r.headers["X-Accepted"] == "1"
    files = list(ingest.glob("store-api-*.jsonl"))
    assert len(files) == 1, "the .NET payload wrote nothing: %s" % list(ingest.glob("*"))
    written = json.loads(files[0].read_text().splitlines()[0])
    assert written["msg"] == "checkout session cs_test_123 expired after 30 min"
    assert written["lvl"] == "warn"


def test_both_route_spellings_reach_the_same_handler(client, ingest):
    """An OTLP client is usually configured with a BASE url and appends `/v1/logs` itself. If
    only one spelling existed, half the clients in the world would 404 with no line written."""
    for url in (OTLP_URL, OTLP_URL + "/v1/logs"):
        r = client.post(url, json=otlp_json(), headers=AUTH)
        assert r.status_code == 200, "%s -> %s" % (url, r.status_code)
    assert len(list(ingest.glob("engine-*.jsonl"))[0].read_text().splitlines()) == 2


def test_a_bad_otlp_payload_is_400_and_writes_nothing(client, ingest):
    r = client.post(OTLP_URL, content=b"\x0b\x00", headers={**AUTH, **PB})
    assert r.status_code == 400
    assert list(ingest.glob("*.jsonl")) == []


def test_an_oversized_otlp_body_is_413(client, ingest, monkeypatch):
    monkeypatch.setenv("PROSPECTOR_LOG_MAX_BODY_BYTES", "200")
    r = client.post(OTLP_URL, json=otlp_json(body="x" * 500), headers=AUTH)
    assert r.status_code == 413
    assert list(ingest.glob("*.jsonl")) == []


def test_too_many_records_in_one_request_is_413(client, ingest, monkeypatch):
    monkeypatch.setenv("PROSPECTOR_LOG_MAX_LINES", "2")
    payload = otlp_json()
    payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"] *= 3
    r = client.post(OTLP_URL, json=payload, headers=AUTH)
    assert r.status_code == 413
    assert list(ingest.glob("*.jsonl")) == []


def test_a_drop_is_reported_in_the_spec_s_own_field(client, ingest):
    """`X-Dropped` means nothing to a stock OpenTelemetry exporter. OTLP says a partial success
    is reported as `rejectedLogRecords` in the response body, and that is the only channel a
    producer we did not write will ever read."""
    payload = otlp_json()
    # No service.name on the second record, so it is unroutable and must be dropped.
    payload["resourceLogs"].append({
        "resource": {"attributes": []},
        "scopeLogs": [{"scope": {"name": "s"}, "logRecords": [
            {"body": {"stringValue": "orphan"}}]}]})
    r = client.post(OTLP_URL, json=payload, headers=AUTH)
    assert r.status_code == 200
    assert r.headers["X-Accepted"] == "1"
    assert r.headers["X-Dropped"] == "1"
    assert r.json()["partialSuccess"]["rejectedLogRecords"] == "1"


def test_a_clean_otlp_export_returns_the_empty_success_message(client, ingest):
    """OTLP: success is 200 with a serialised ExportLogsServiceResponse. All-default means zero
    bytes in protobuf and `{}` in JSON. A client that parses the body must not choke."""
    assert client.post(OTLP_URL, json=otlp_json(), headers=AUTH).json() == {}
    r = client.post(OTLP_URL, content=DOTNET_PAYLOAD.read_bytes(), headers={**AUTH, **PB})
    assert r.content == b"", "a clean protobuf export must return an empty message, got %r" % r.content


def test_a_protobuf_partial_success_is_a_readable_message(client, ingest):
    """The bytes we hand back have to be the message we claim, not a shape that only looks
    right. Decoded with our own reader: field 1 is partial_success, whose field 1 is the count.
    """
    from prospector import otlp as otlp_mod
    body = log_ingest._otlp_response(3, "application/x-protobuf").body
    outer = otlp_mod._fields(body)
    inner = otlp_mod._fields(bytes(otlp_mod._one(outer, 1)))
    assert otlp_mod._one(inner, 1) == 3


def test_otlp_is_rate_limited_by_the_same_limiter(client, ingest, monkeypatch):
    """One producer switching to OTLP must not get an exemption from the cap that protects the
    disk from all the others."""
    monkeypatch.setenv("PROSPECTOR_LOG_RATE_LIMIT_RPS", "1")
    log_ingest._LIMITER = log_ingest.RateLimiter(log_ingest.rate_limit_rps())
    payload = otlp_json()
    payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"] *= 5
    r = client.post(OTLP_URL, json=payload, headers=AUTH)
    assert int(r.headers["X-Dropped"]) >= 1, "the rate limit did not apply to OTLP: %s" % r.headers
    assert log_ingest._INGEST.counters["dropped_rate_limited"] >= 1
