"""OTLP/HTTP decoding, pinned against a payload the OpenTelemetry .NET exporter really wrote.

Issue #501 asked for "a test that decodes a real OTLP payload and asserts the resulting NDJSON
line, so the mapping is pinned rather than described". `tests/fixtures/otlp/` holds those bytes
and its README says how they were captured. That fixture is what makes this file worth having:
a hand-written protobuf reader tested only against a hand-written encoder proves that two
mistakes agree with each other.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from prospector import otlp
from prospector.log_ingest import normalise

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "otlp"
DOTNET = FIXTURES / "dotnet_1_15_3_logs.protobuf"

#: Read out of the fixture, not invented. `LogRecord.time_unix_nano` and `severity_number`.
DOTNET_NANO = 1787193828236944000
DOTNET_TS = "2026-08-20T02:43:48.236Z"

NOW = datetime(2026, 8, 20, 9, 0, 0, tzinfo=timezone.utc)


# ------------------------------------------------------- the ground-truth payload

def test_the_real_dotnet_payload_decodes_to_one_record():
    """The whole reason the protobuf half exists.

    OpenTelemetry .NET 1.15.3 offers `Grpc` and `HttpProtobuf` and nothing else -- there is no
    `HttpJson` -- so a JSON-only ingest could never receive the exporter Store.Api compiles.
    These are that exporter's own bytes. If the reader in prospector/otlp.py is wrong about a
    field number, a wire type or a varint, this fails against something we did not write.
    """
    records = otlp.decode(DOTNET.read_bytes(), "application/x-protobuf")
    assert len(records) == 1, "expected one LogRecord, got %d" % len(records)
    record = records[0]

    assert record["svc"] == "store-api", "service.name did not become svc: %r" % record
    assert record["lvl"] == "warn", "severityText 'Warning' did not map to warn: %r" % record
    assert record["msg"] == "checkout session cs_test_123 expired after 30 min"
    assert record["ts"] == DOTNET_TS
    assert record["evt"] == "otlp.Store.Api.Checkout"
    assert record["ctx"]["SessionId"] == "cs_test_123"
    assert record["ctx"]["Minutes"] == 30, "an intValue did not survive as an int"
    assert record["ctx"]["service.version"] == "1.2.3"
    assert record["ctx"]["otel.scope"] == "Store.Api.Checkout"


def test_the_real_payload_survives_normalise_unchanged():
    """The endpoint writes what `normalise` returns, so the assertion above is only worth
    something if nothing is lost on the way through the ingest's own gate."""
    record = otlp.decode(DOTNET.read_bytes(), "application/x-protobuf")[0]
    line = normalise(record, "10.0.0.7", NOW)
    assert line is not None, "the real payload was dropped by normalise"
    assert line["svc"] == "store-api"
    assert line["lvl"] == "warn"
    assert line["ts"] == DOTNET_TS, "normalise overwrote the producer's timestamp"
    assert line["host"] == "10.0.0.7", "host must come from the connection, never the client"


def test_the_severity_text_field_number_is_pinned():
    """Found by mutation, 2026-08-20. Changing `severity_text` from field 3 to field 4 broke
    nothing: the fixture also carries severityNumber 13, which lands on `warn` by itself, so
    every assertion still passed while the text was being read from a field that does not
    exist. This reads field 3 out of the fixture directly, and pins that the WORD beats the
    number when they disagree -- the only case where getting the field wrong shows up.
    """
    body = DOTNET.read_bytes()
    rl = otlp._fields(otlp._one(otlp._fields(body), 1))
    sl = otlp._fields(otlp._one(rl, 2))
    lr = otlp._fields(otlp._one(sl, 2))
    assert otlp._pb_str(otlp._one(lr, 3)) == "Warning", "field 3 is not severity_text"
    assert otlp._one(lr, 2) == 13, "field 2 is not severity_number"

    # The fixture alone cannot pin this: its text and its number both say warn, so a reader
    # that ignored the text entirely would still pass. Build one where they DISAGREE.
    disagreeing = _pb_request(sev_text="Error", sev_num=9)  # 9 is INFO
    assert otlp.decode(disagreeing, "application/x-protobuf")[0]["lvl"] == "error", (
        "severity_text was not read from field 3 -- the number won")


# --- a minimal protobuf ENCODER, for the cases the captured fixture cannot express -----------
# Deliberately separate from the reader and written from the same field numbers by hand. It is
# never the only evidence for anything: the fixture above is the ground truth, and this exists
# so a test can construct a payload .NET happened not to send.

def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _ld(field: int, payload: bytes) -> bytes:
    return _varint((field << 3) | 2) + _varint(len(payload)) + payload


def _vi(field: int, value: int) -> bytes:
    return _varint((field << 3) | 0) + _varint(value)


def _kv(key: str, value: str) -> bytes:
    return _ld(1, key.encode()) + _ld(2, _ld(1, value.encode()))


def _pb_request(*, svc: str = "store-api", sev_text: str = "", sev_num: int = 0,
                body: str = "a sentence", scope: str = "S") -> bytes:
    record = b""
    if sev_num:
        record += _vi(2, sev_num)
    if sev_text:
        record += _ld(3, sev_text.encode())
    record += _ld(5, _ld(1, body.encode()))
    scope_logs = _ld(1, _ld(1, scope.encode())) + _ld(2, record)
    resource_logs = _ld(1, _ld(1, _kv("service.name", svc))) + _ld(2, scope_logs)
    return _ld(1, resource_logs)


def test_the_hand_written_encoder_round_trips_through_the_reader():
    """The encoder above is only useful if it agrees with the reader on an ordinary payload.
    Without this, a test built on it could pass because both halves are wrong the same way --
    and the fixture, which is the real evidence, would not be the thing failing."""
    record = otlp.decode(_pb_request(sev_text="Information"), "application/x-protobuf")[0]
    assert record["svc"] == "store-api"
    assert record["lvl"] == "info"
    assert record["msg"] == "a sentence"
    assert record["evt"] == "otlp.S"


def test_the_exporter_pads_its_length_varints():
    """A reader that assumes minimal varint encoding decodes this payload as garbage.

    The .NET exporter reserves a fixed-width slot for each message length and writes a padded
    varint into it: the first bytes of the fixture are `0a fc 82 80 00`, where `fc 82 80 00` is
    380 written in four bytes instead of two. This asserts the fixture still has that shape, so
    the reason the reader must handle it does not quietly disappear from under the test above.
    """
    head = DOTNET.read_bytes()[:5]
    assert head[0] == 0x0A, "fixture no longer starts with field 1, wire type 2"
    assert head[1:5] == b"\xfc\x82\x80\x00", "fixture no longer carries a padded varint"
    value, index = otlp._read_varint(head, 1)
    assert (value, index) == (380, 5)


# ------------------------------------------------------- the two encodings agree

def dotnet_as_json() -> dict:
    """The same LogRecord in OTLP/JSON. Field for field with the captured protobuf."""
    return {"resourceLogs": [{
        "resource": {"attributes": [
            {"key": "service.name", "value": {"stringValue": "store-api"}},
            {"key": "service.version", "value": {"stringValue": "1.2.3"}},
        ]},
        "scopeLogs": [{
            "scope": {"name": "Store.Api.Checkout"},
            "logRecords": [{
                "timeUnixNano": str(DOTNET_NANO),
                "severityNumber": 13,
                "severityText": "Warning",
                "body": {"stringValue": "checkout session cs_test_123 expired after 30 min"},
                "attributes": [
                    {"key": "SessionId", "value": {"stringValue": "cs_test_123"}},
                    {"key": "Minutes", "value": {"intValue": "30"}},
                ],
            }],
        }],
    }]}


def test_json_and_protobuf_of_the_same_record_agree():
    """One mapping, two decoders. Without this the JSON path could drift from the protobuf path
    for a year and only the encoding nobody tested would be wrong."""
    from_json = otlp.decode(json.dumps(dotnet_as_json()).encode(), "application/json")
    from_proto = otlp.decode(DOTNET.read_bytes(), "application/x-protobuf")
    assert len(from_json) == len(from_proto) == 1

    j, p = dict(from_json[0]), dict(from_proto[0])
    # The .NET exporter adds two attributes this hand-written JSON does not claim to carry.
    for key in ("service.instance.id", "{OriginalFormat}"):
        p["ctx"].pop(key, None)
    assert j == p, "the JSON decoder and the protobuf decoder disagree:\n%r\n%r" % (j, p)


def test_uint64_arrives_as_a_string_in_json():
    """proto3 JSON encodes uint64 as a string because a JSON number loses precision past 2^53.
    Reading it as a number would put every OTLP/JSON line at the epoch."""
    assert otlp._as_nano(str(DOTNET_NANO)) == DOTNET_NANO
    assert otlp._as_nano(DOTNET_NANO) == DOTNET_NANO
    assert otlp._as_nano("not a number") is None
    assert otlp._as_nano(None) is None


# ------------------------------------------------------- svc is a candidate, not a gate

@pytest.mark.parametrize("name,expected", [
    ("store-api", "store-api"),
    ("Store.Api", "store-api"),
    ("my_service", "my-service"),
    ("  Engine  ", "engine"),
    ("../../../etc/cron.d/x", "etc-cron-d-x"),
    ("", ""),
    (None, ""),
])
def test_slug_produces_a_candidate(name, expected):
    assert otlp.slug(name) == expected


def test_a_traversing_service_name_is_refused_by_the_one_gate():
    """`svc` becomes part of a filename. This module must not hold a second copy of that gate --
    a second copy is a copy that can disagree -- so the traversal has to die in `normalise`.
    """
    payload = {"resourceLogs": [{
        "resource": {"attributes": [
            {"key": "service.name", "value": {"stringValue": "../../../etc/cron.d/x"}}]},
        "scopeLogs": [{"scope": {"name": "s"}, "logRecords": [
            {"body": {"stringValue": "hi"}}]}],
    }]}
    record = otlp.decode(json.dumps(payload).encode(), "application/json")[0]
    assert "/" not in record["svc"], "a path separator reached svc: %r" % record["svc"]
    assert normalise(record, "h", NOW) is not None, (
        "the slug happens to be legal here; if that changes, fix the test, not the gate")

    # And the case the slug cannot save: a name that leaves nothing legal behind.
    payload["resourceLogs"][0]["resource"]["attributes"][0]["value"]["stringValue"] = "../.."
    record = otlp.decode(json.dumps(payload).encode(), "application/json")[0]
    assert record["svc"] == ""
    assert normalise(record, "h", NOW) is None, "an unroutable record was accepted"


def test_a_record_with_no_service_name_is_dropped():
    """Filing an unattributable record under a default name makes that file a junk drawer and
    hides the producer's misconfiguration for ever."""
    payload = {"resourceLogs": [{"resource": {"attributes": []}, "scopeLogs": [
        {"scope": {"name": "s"}, "logRecords": [{"body": {"stringValue": "hi"}}]}]}]}
    record = otlp.decode(json.dumps(payload).encode(), "application/json")[0]
    assert normalise(record, "h", NOW) is None


# ------------------------------------------------------- severity

@pytest.mark.parametrize("text,number,expected", [
    ("Warning", 13, "warn"),
    ("WARN", None, "warn"),
    ("Information", None, "info"),
    ("Fatal", None, "crit"),
    ("Trace", None, "debug"),
    ("", 1, "debug"),      # TRACE band, folded into debug
    ("", 5, "debug"),
    ("", 9, "info"),
    ("", 13, "warn"),
    ("", 17, "error"),
    ("", 21, "crit"),
    ("", 99, "crit"),      # past the last band
    ("", 0, "info"),       # UNSPECIFIED
    ("", None, "info"),
    ("nonsense", None, "info"),
    ("nonsense", 17, "error"),   # an unrecognised word falls through to the number
    ("", "SEVERITY_NUMBER_ERROR", "error"),
])
def test_level_mapping(text, number, expected):
    assert otlp.level_of(text, number) == expected


# ------------------------------------------------------- evt

def test_evt_never_comes_from_the_body():
    """§4.3: `evt` is a "stable machine name ... never interpolated", and counting `evt` is only
    exact because of that. A body carries an order id, so deriving `evt` from it would mint a
    new event name per request -- the 97-instead-of-8 failure §4.3 names."""
    def evt(body, **kw):
        payload = {"resourceLogs": [{
            "resource": {"attributes": [
                {"key": "service.name", "value": {"stringValue": "store-api"}}]},
            "scopeLogs": [{"scope": {"name": kw.get("scope", "Store.Api.Checkout")},
                           "logRecords": [dict({"body": {"stringValue": body}}, **kw.get("lr", {}))]}],
        }]}
        return otlp.decode(json.dumps(payload).encode(), "application/json")[0]

    a = evt("order ord_111 shipped")
    b = evt("order ord_222 shipped")
    assert a["evt"] == b["evt"], "evt moved with the body text: %r vs %r" % (a["evt"], b["evt"])
    assert "ord_111" not in a["evt"]
    assert a["msg"] == "order ord_111 shipped", "the body must survive in full as msg"


def test_an_explicit_event_attribute_wins():
    payload = {"resourceLogs": [{
        "resource": {"attributes": [
            {"key": "service.name", "value": {"stringValue": "store-api"}}]},
        "scopeLogs": [{"scope": {"name": "Store.Api.Checkout"}, "logRecords": [{
            "body": {"stringValue": "whatever"},
            "attributes": [{"key": "evt", "value": {"stringValue": "checkout.session.created"}}],
        }]}],
    }]}
    record = otlp.decode(json.dumps(payload).encode(), "application/json")[0]
    assert record["evt"] == "checkout.session.created"
    assert "evt" not in record.get("ctx", {}), "a consumed attribute was duplicated into ctx"


def test_evt_falls_back_when_there_is_no_scope_either():
    payload = {"resourceLogs": [{
        "resource": {"attributes": [
            {"key": "service.name", "value": {"stringValue": "store-api"}}]},
        "scopeLogs": [{"logRecords": [{"body": {"stringValue": "x"}}]}],
    }]}
    record = otlp.decode(json.dumps(payload).encode(), "application/json")[0]
    assert record["evt"] == "otlp.log"
    assert normalise(record, "h", NOW) is not None, "the fallback must be an acceptable evt"


# ------------------------------------------------------- correlation and ctx

def test_the_trace_id_becomes_the_correlation_id():
    """§4.4 already has a correlation id. A trace id is the same idea arriving under another
    name, and dropping it would break a trail that crosses services."""
    trace = "5b8efff798038103d269b633813fc60c"
    payload = {"resourceLogs": [{
        "resource": {"attributes": [
            {"key": "service.name", "value": {"stringValue": "store-api"}}]},
        "scopeLogs": [{"scope": {"name": "s"}, "logRecords": [
            {"body": {"stringValue": "x"}, "traceId": trace, "spanId": "eee19b7ec3c1b174"}]}],
    }]}
    record = otlp.decode(json.dumps(payload).encode(), "application/json")[0]
    assert record["corr"] == trace
    assert record["ctx"]["span"] == "eee19b7ec3c1b174"


def test_an_explicit_corr_attribute_beats_the_trace_id():
    payload = {"resourceLogs": [{
        "resource": {"attributes": [
            {"key": "service.name", "value": {"stringValue": "store-api"}}]},
        "scopeLogs": [{"scope": {"name": "s"}, "logRecords": [{
            "body": {"stringValue": "x"}, "traceId": "aa" * 16,
            "attributes": [{"key": "corr", "value": {"stringValue": "req-42"}}]}]}],
    }]}
    assert otlp.decode(json.dumps(payload).encode(), "application/json")[0]["corr"] == "req-42"


def test_a_base64_trace_id_is_read_as_hex():
    """OTLP/JSON says hex, proto3 JSON would say base64, and clients ship both."""
    assert otlp._json_id("W47/95gDgQPSabYzgT/GDA==") == "5b8efff798038103d269b633813fc60c"
    assert otlp._json_id("5B8EFFF798038103D269B633813FC60C") == "5b8efff798038103d269b633813fc60c"
    assert otlp._json_id("not base64 or hex!!") == ""


def test_ctx_is_flattened_because_the_schema_says_flat():
    """§4.3: `ctx` is "flat key/value, no nesting". An OTLP attribute can be an array or a
    kvlist, so something has to give; the value becomes its JSON text rather than being lost."""
    payload = {"resourceLogs": [{
        "resource": {"attributes": [
            {"key": "service.name", "value": {"stringValue": "store-api"}}]},
        "scopeLogs": [{"scope": {"name": "s"}, "logRecords": [{
            "body": {"stringValue": "x"},
            "attributes": [
                {"key": "tags", "value": {"arrayValue": {"values": [
                    {"stringValue": "a"}, {"stringValue": "b"}]}}},
                {"key": "nested", "value": {"kvlistValue": {"values": [
                    {"key": "inner", "value": {"intValue": "7"}}]}}},
                {"key": "flag", "value": {"boolValue": True}},
                {"key": "ratio", "value": {"doubleValue": 0.25}},
            ]}]}],
    }]}
    ctx = otlp.decode(json.dumps(payload).encode(), "application/json")[0]["ctx"]
    assert ctx["tags"] == '["a", "b"]'
    assert ctx["nested"] == '{"inner": 7}'
    assert ctx["flag"] is True
    assert ctx["ratio"] == 0.25
    assert all(not isinstance(v, (dict, list)) for v in ctx.values()), ctx


# ------------------------------------------------------- refusing what is not OTLP

def test_an_empty_body_is_zero_records_not_an_error():
    assert otlp.decode(b"", "application/x-protobuf") == []
    assert otlp.decode(b"", "application/json") == []
    assert otlp.decode(b'{"resourceLogs":[]}', "application/json") == []


def test_a_truncated_protobuf_message_is_refused():
    """Reading past the end would invent data. The endpoint answers 400 and writes nothing."""
    body = DOTNET.read_bytes()
    with pytest.raises(otlp.OtlpDecodeError):
        otlp.decode(body[:-40], "application/x-protobuf")


def test_the_deprecated_group_wire_type_is_refused():
    """Wire types 3 and 4 are the removed group encoding. Skipping past one means we are not
    reading what we think we are reading, so the whole payload is refused rather than guessed."""
    with pytest.raises(otlp.OtlpDecodeError):
        otlp._fields(b"\x0b\x00")


def test_a_zero_field_number_is_refused():
    with pytest.raises(otlp.OtlpDecodeError):
        otlp._fields(b"\x00\x01")


def test_bytes_that_are_not_json_are_refused():
    with pytest.raises(otlp.OtlpDecodeError):
        otlp.decode(b"{not json", "application/json")
    with pytest.raises(otlp.OtlpDecodeError):
        otlp.decode(b"\xff\xfe\x00", "application/json")
    with pytest.raises(otlp.OtlpDecodeError):
        otlp.decode(b'["not an object"]', "application/json")


def test_an_undeclared_content_type_is_read_as_json():
    """A client that declares nothing is far likelier to be sending JSON than nothing at all,
    and a body that is not JSON still fails one line later."""
    body = json.dumps(dotnet_as_json()).encode()
    assert len(otlp.decode(body, "")) == 1
    assert len(otlp.decode(body, "application/json; charset=utf-8")) == 1


def test_nesting_deeper_than_the_limit_is_stringified_not_recursed():
    """The body cap bounds bytes, not depth: a few hundred bytes of kvlist can nest thousands
    deep and would take the interpreter's stack with it."""
    value: dict = {"stringValue": "bottom"}
    for _ in range(60):
        value = {"kvlistValue": {"values": [{"key": "k", "value": value}]}}
    assert "<nested too deep>" in json.dumps(otlp._json_any_value(value))


def test_an_int64_attribute_below_zero_survives_as_a_negative():
    """int64 on the wire is a 64-bit two's complement varint, not zigzag. Reading it as
    unsigned turns -1 into 18446744073709551615."""
    assert otlp._unzigzag_none((1 << 64) - 1) == -1
    assert otlp._unzigzag_none(30) == 30


# --- The seam: bytes Store.Api's own central log actually sent ------------------------------
#
# The fixture above proves the reader survives the OpenTelemetry .NET exporter. This one proves
# the whole path: Store.Api's CentralLog wiring, its redaction processor, the exporter, and this
# decoder, ending in a line that matches docs/LOGGING_AND_RETENTION.md §4.3. Captured by
# Store.Tests.Infrastructure.CentralLogOtlpWireTests with PROSPECTOR_OTLP_CAPTURE set; see
# tests/fixtures/otlp/README.md.

STORE_API_PAYLOAD = (FIXTURES / "store_api_central_log.protobuf").read_bytes()

#: The value that test logs into a field named `stripeApiKey`. It is not a credential; it is
#: shaped like one so a leak is visible.
NOT_A_KEY = "sk-live-NOT-A-REAL-KEY-0000"


def test_the_store_api_capture_becomes_one_line_of_the_documented_schema():
    records = otlp.decode(STORE_API_PAYLOAD, "application/x-protobuf")
    assert len(records) == 1
    line = records[0]
    assert line["svc"] == "store-api"
    assert line["lvl"] == "info"
    assert line["msg"] == "order ord_42 paid"
    # The stable machine name the caller passed as EventId.Name, not the interpolated message.
    # `msg` moves with every order id; `evt` must not, or counting events is impossible.
    assert line["evt"] == "checkout.started"
    assert line["ts"] == "2026-08-20T03:12:26.233Z"


def test_the_secret_never_reaches_the_reader_and_is_not_in_the_bytes():
    """Both halves matter. If the producer's redaction is removed the engine cannot restore it,
    so the second assertion is the one that would catch a regression on the other side of the
    seam -- in a repository this test cannot see when it runs on CI."""
    line = otlp.decode(STORE_API_PAYLOAD, "application/x-protobuf")[0]
    assert line["ctx"]["stripeApiKey"] == "[redacted]"
    assert NOT_A_KEY not in line["ctx"]["stripeApiKey"]
    assert NOT_A_KEY.encode() not in STORE_API_PAYLOAD

    # The NAME still travels. Dropping it too would hide that a call site handles a credential
    # at all, which is what an audit needs to see.
    assert "stripeApiKey" in line["ctx"]


def test_the_sdk_describing_itself_is_not_carried_on_every_line():
    line = otlp.decode(STORE_API_PAYLOAD, "application/x-protobuf")[0]
    assert not [k for k in line["ctx"] if k.startswith("telemetry.sdk.")]

    # Kept on purpose: it differs per process, so it separates two copies of one service on one
    # host. `host`, which the ingest sets from the connection, cannot.
    assert line["ctx"]["service.instance.id"]


def test_the_template_is_dropped_and_the_formatted_message_kept():
    """IncludeFormattedMessage on the producer, `{OriginalFormat}` skipped by its processor.
    Without both, every `msg` in the estate would read "order {OrderId} paid"."""
    line = otlp.decode(STORE_API_PAYLOAD, "application/x-protobuf")[0]
    assert "{OriginalFormat}" not in line["ctx"]
    assert line["ctx"]["OrderId"] == "ord_42"
    assert "{" not in line["msg"]


def test_the_capture_survives_the_ingests_own_normalise():
    """The decoder is not the gate. A line that decodes but fails normalise would be dropped as
    malformed at the ingest, and the whole path would be silently useless."""
    line = otlp.decode(STORE_API_PAYLOAD, "application/x-protobuf")[0]
    normalised = normalise(line, "10.0.0.7", NOW)
    assert normalised is not None
    assert normalised["svc"] == "store-api"
    assert normalised["evt"] == "checkout.started"
