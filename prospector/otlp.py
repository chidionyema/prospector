"""OTLP/HTTP logs, decoded onto the §4.3 line schema.

Issue #501. `docs/LOGGING_AND_RETENTION.md` Part 7 rejected "OpenTelemetry collector" in one
row and took OTLP down with it. The collector is still rejected — it is a daemon whose whole
job is handing our own bytes back to us. The wire format is not: it costs nothing to emit, it
needs no daemon, and it is the only line on that page that is neither a vendor nor a bill. It
is what makes the sink a config line in both directions, which is the migration bar.

**Both encodings, and why the protobuf half is not optional.** OTLP/HTTP carries two content
types: `application/json` and `application/x-protobuf`. Measured 2026-08-20 against the version
this estate pins, OpenTelemetry .NET 1.15.3 (`Directory.Packages.props:68-71`)::

    find ~/.nuget/packages/opentelemetry.exporter.opentelemetryprotocol/1.15.3 -name '*.dll' \
      | head -1 | xargs strings | rg -i '^HttpJson$|^HttpProtobuf$|^Grpc$'
    -> HttpProtobuf

`OtlpExportProtocol` offers `Grpc` and `HttpProtobuf`. There is no `HttpJson`. A JSON-only
ingest could therefore never receive the exporter `Store.Api` already compiles, which is half
of what #501 asked for. So this module reads protobuf too.

**Why the protobuf reader is hand-written rather than `opentelemetry-proto`.** That package
pulls `protobuf`, a version-pinned package with a compiled runtime, into an engine that
declares neither (`requirements.txt` names no protobuf; the 7.35.1 on this laptop is a leftover
of streamlit, deleted 2026-08-18). Against a bar that says migrate the whole stack in thirty
minutes on any host, a stdlib-only reader is the cheaper thing to carry. It is safe to hand-write
because the only thing it needs is FIELD NUMBERS, and those are frozen: opentelemetry-proto has
not renumbered a logs field since v0.9 in 2021, and the wire format makes an added field
skippable by construction. The reader never sees a schema, only tags.

**What is NOT trusted here.** `svc` becomes part of a filename. This module produces a
CANDIDATE and `log_ingest.normalise` decides, against the same `_SVC_RE` every other producer
faces. There is one security gate for the whole ingest and it is not in this file.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
import struct
from datetime import datetime, timezone
from typing import Any

#: OTLP severity numbers, https://opentelemetry.io/docs/specs/otel/logs/data-model/#field-severitynumber.
#: 1-4 TRACE, 5-8 DEBUG, 9-12 INFO, 13-16 WARN, 17-20 ERROR, 21-24 FATAL. We have five levels
#: and no TRACE, so TRACE folds into debug and FATAL into crit.
_SEVERITY_BANDS = ((4, "debug"), (8, "debug"), (12, "info"), (16, "warn"), (20, "error"), (24, "crit"))

#: What other stacks call the same five levels. Anything unrecognised falls through to the
#: number, and then to `info` -- an unknown level must never cost us the line.
_SEVERITY_WORDS = {
    "trace": "debug", "verbose": "debug", "fine": "debug", "finest": "debug", "debug": "debug",
    "info": "info", "information": "info", "notice": "info",
    "warn": "warn", "warning": "warn",
    "error": "error", "err": "error", "severe": "error",
    "fatal": "crit", "critical": "crit", "crit": "crit", "alert": "crit", "emergency": "crit",
}

#: Resource attributes that name the producer, best first. `service.name` is the spec's own.
_SERVICE_KEYS = ("service.name", "svc", "service")

#: Attributes that carry a stable event name. See `_event_name` for why body is not one of them.
_EVENT_KEYS = ("evt", "event.name", "event_name")

_CORR_KEYS = ("corr", "correlation.id", "correlation_id")

#: Attributes consumed into a named field. Everything else survives into `ctx`.
_CONSUMED = frozenset(_SERVICE_KEYS + _EVENT_KEYS + _CORR_KEYS)

#: Resource attributes an SDK writes to describe ITSELF. They are identical on every line a
#: given process sends, so they answer nothing and are paid for once per record.
#:
#: Measured 2026-08-20 on tests/fixtures/otlp/store_api_central_log.protobuf, one real line from
#: Store.Api: 388 bytes with them, 284 without. 37% of every line, which is 134 MB of the 500 MB
#: volume cap in docs/LOGGING_AND_RETENTION.md §4.6 spent on three constants.
#:
#: `service.instance.id` is deliberately NOT here. It is a different value per process, so it
#: separates two copies of one service on one host, which `host` cannot do.
_SDK_SELF_DESCRIPTION = ("telemetry.sdk.",)

_HEX_RE = re.compile(r"^[0-9a-fA-F]+$")

#: A kvlist may contain a kvlist. The body cap bounds the bytes, not the depth, so a small
#: payload can still be nested thousands deep. Past this we stringify instead of recursing.
_MAX_DEPTH = 12

#: The most log records one request may yield. `max_lines_per_batch` applies the estate's real
#: cap in `log_ingest`; this one only stops a decode from building an unbounded list first.
MAX_RECORDS = 100_000

JSON_TYPES = ("application/json",)
PROTOBUF_TYPES = ("application/x-protobuf", "application/protobuf")


class OtlpDecodeError(ValueError):
    """The payload is not OTLP. The caller answers 400; nothing is written."""


# --------------------------------------------------------------------------- protobuf wire

def _read_varint(buf: bytes, i: int) -> tuple[int, int]:
    value = shift = 0
    while True:
        if i >= len(buf):
            raise OtlpDecodeError("varint runs off the end of the buffer")
        if shift > 63:
            raise OtlpDecodeError("varint is longer than 64 bits")
        byte = buf[i]
        i += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, i
        shift += 7


def _fields(buf: bytes) -> dict[int, list[Any]]:
    """Split one protobuf message into {field number: [value, ...]}, schema-free.

    Length-delimited fields come back as `bytes` and are decoded again by whoever knows what
    they are. Varints and fixed widths come back as `int`. An unknown field number is kept:
    skipping is the caller's decision, not this function's.
    """
    out: dict[int, list[Any]] = {}
    i = 0
    while i < len(buf):
        tag, i = _read_varint(buf, i)
        field, wire = tag >> 3, tag & 7
        if field == 0:
            raise OtlpDecodeError("field number 0 is not legal")
        if wire == 0:
            value, i = _read_varint(buf, i)
        elif wire == 1:
            if i + 8 > len(buf):
                raise OtlpDecodeError("fixed64 runs off the end of the buffer")
            value = struct.unpack_from("<Q", buf, i)[0]
            i += 8
        elif wire == 2:
            length, i = _read_varint(buf, i)
            if length < 0 or i + length > len(buf):
                raise OtlpDecodeError("length-delimited field runs off the end of the buffer")
            value = buf[i:i + length]
            i += length
        elif wire == 5:
            if i + 4 > len(buf):
                raise OtlpDecodeError("fixed32 runs off the end of the buffer")
            value = struct.unpack_from("<I", buf, i)[0]
            i += 4
        else:
            # 3 and 4 are the deprecated group encoding; 6 and 7 do not exist. Either means we
            # are not reading what we think we are reading, and guessing past it would invent
            # data. Refuse the whole payload.
            raise OtlpDecodeError("unsupported protobuf wire type %d" % wire)
        out.setdefault(field, []).append(value)
    return out


def _one(fields: dict[int, list[Any]], number: int) -> Any:
    """The last value of a non-repeated field, or None. Last wins, as protobuf specifies."""
    values = fields.get(number)
    return values[-1] if values else None


def _pb_str(raw: Any) -> str:
    if not isinstance(raw, (bytes, bytearray)):
        return ""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise OtlpDecodeError("a string field is not utf-8")


def _pb_any_value(raw: Any, depth: int = 0) -> Any:
    """AnyValue: 1 string, 2 bool, 3 int, 4 double, 5 array, 6 kvlist, 7 bytes."""
    if not isinstance(raw, (bytes, bytearray)):
        return None
    if depth >= _MAX_DEPTH:
        return "<nested too deep>"
    f = _fields(bytes(raw))
    if 1 in f:
        return _pb_str(_one(f, 1))
    if 2 in f:
        return bool(_one(f, 2))
    if 3 in f:
        return _unzigzag_none(_one(f, 3))
    if 4 in f:
        return struct.unpack("<d", struct.pack("<Q", _one(f, 4)))[0]
    if 5 in f:
        inner = _fields(bytes(_one(f, 5)))
        return [_pb_any_value(v, depth + 1) for v in inner.get(1, [])]
    if 6 in f:
        inner = _fields(bytes(_one(f, 6)))
        return {k: v for k, v in (_pb_key_value(kv, depth + 1) for kv in inner.get(1, []))}
    if 7 in f:
        return base64.b64encode(bytes(_one(f, 7))).decode("ascii")
    return None


def _unzigzag_none(value: Any) -> Any:
    """int64 on the wire is two's complement in a 64-bit varint, not zigzag (that is sint64)."""
    if not isinstance(value, int):
        return value
    return value - (1 << 64) if value >= (1 << 63) else value


def _pb_key_value(raw: Any, depth: int = 0) -> tuple[str, Any]:
    """KeyValue: 1 key, 2 value."""
    if not isinstance(raw, (bytes, bytearray)):
        return "", None
    f = _fields(bytes(raw))
    return _pb_str(_one(f, 1)), _pb_any_value(_one(f, 2), depth)


def _pb_attrs(raws: list[Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for raw in raws:
        key, value = _pb_key_value(raw)
        if key:
            out[key] = value
    return out


def _pb_hex(raw: Any) -> str:
    return bytes(raw).hex() if isinstance(raw, (bytes, bytearray)) and raw else ""


def decode_protobuf(body: bytes) -> list[dict]:
    """ExportLogsServiceRequest -> raw records, before `normalise`.

    Field numbers, from opentelemetry-proto v1 logs.proto and common.proto:
      ExportLogsServiceRequest 1 resource_logs
      ResourceLogs             1 resource, 2 scope_logs
      Resource                 1 attributes
      ScopeLogs                1 scope, 2 log_records
      InstrumentationScope     1 name
      LogRecord                1 time_unix_nano, 2 severity_number, 3 severity_text, 5 body,
                               6 attributes, 9 trace_id, 10 span_id, 11 observed_time_unix_nano,
                               12 event_name
    """
    if not body:
        return []
    records: list[dict] = []
    root = _fields(body)
    for rl_raw in root.get(1, []):
        rl = _fields(bytes(rl_raw))
        resource_raw = _one(rl, 1)
        res_attrs = _pb_attrs(_fields(bytes(resource_raw)).get(1, [])) if resource_raw else {}
        for sl_raw in rl.get(2, []):
            sl = _fields(bytes(sl_raw))
            scope_raw = _one(sl, 1)
            scope = _pb_str(_one(_fields(bytes(scope_raw)), 1)) if scope_raw else ""
            for lr_raw in sl.get(2, []):
                if len(records) >= MAX_RECORDS:
                    raise OtlpDecodeError("more than %d log records in one request" % MAX_RECORDS)
                lr = _fields(bytes(lr_raw))
                records.append(_record(
                    res_attrs=res_attrs,
                    scope=scope,
                    attrs=_pb_attrs(lr.get(6, [])),
                    time_nano=_one(lr, 1) or _one(lr, 11),
                    sev_num=_one(lr, 2),
                    sev_text=_pb_str(_one(lr, 3)) if 3 in lr else "",
                    body=_pb_any_value(_one(lr, 5)),
                    trace_id=_pb_hex(_one(lr, 9)),
                    span_id=_pb_hex(_one(lr, 10)),
                    event_name=_pb_str(_one(lr, 12)) if 12 in lr else "",
                ))
    return records


# --------------------------------------------------------------------------- OTLP/JSON

def _json_any_value(value: Any, depth: int = 0) -> Any:
    """AnyValue in proto3 JSON: a one-key wrapper. `intValue` arrives as a STRING."""
    if not isinstance(value, dict):
        return None
    if depth >= _MAX_DEPTH:
        return "<nested too deep>"
    if "stringValue" in value:
        raw = value["stringValue"]
        return raw if isinstance(raw, str) else ""
    if "boolValue" in value:
        return bool(value["boolValue"])
    if "intValue" in value:
        raw = value["intValue"]
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None
    if "doubleValue" in value:
        raw = value["doubleValue"]
        return raw if isinstance(raw, (int, float)) and not isinstance(raw, bool) else None
    if "bytesValue" in value:
        raw = value["bytesValue"]
        return raw if isinstance(raw, str) else None
    if "arrayValue" in value:
        inner = value["arrayValue"]
        items = inner.get("values", []) if isinstance(inner, dict) else []
        return [_json_any_value(v, depth + 1) for v in items] if isinstance(items, list) else []
    if "kvlistValue" in value:
        inner = value["kvlistValue"]
        items = inner.get("values", []) if isinstance(inner, dict) else []
        return _json_attrs(items, depth + 1) if isinstance(items, list) else {}
    return None


def _json_attrs(items: Any, depth: int = 0) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if not isinstance(items, list):
        return out
    for kv in items:
        if not isinstance(kv, dict):
            continue
        key = kv.get("key")
        if isinstance(key, str) and key:
            out[key] = _json_any_value(kv.get("value"), depth)
    return out


def _json_id(value: Any) -> str:
    """trace_id/span_id. OTLP/JSON specifies hex; proto3 JSON would say base64. Take either."""
    if not isinstance(value, str) or not value:
        return ""
    if _HEX_RE.match(value) and len(value) % 2 == 0:
        return value.lower()
    try:
        return base64.b64decode(value, validate=True).hex()
    except (binascii.Error, ValueError):
        return ""


def decode_json(payload: Any) -> list[dict]:
    """A decoded OTLP/JSON `ExportLogsServiceRequest` -> raw records, before `normalise`."""
    if not isinstance(payload, dict):
        raise OtlpDecodeError("OTLP/JSON payload is not an object")
    resource_logs = payload.get("resourceLogs", payload.get("resource_logs", []))
    if resource_logs is None:
        return []
    if not isinstance(resource_logs, list):
        raise OtlpDecodeError("resourceLogs is not a list")
    records: list[dict] = []
    for rl in resource_logs:
        if not isinstance(rl, dict):
            continue
        resource = rl.get("resource")
        res_attrs = _json_attrs(resource.get("attributes")) if isinstance(resource, dict) else {}
        scope_logs = rl.get("scopeLogs", rl.get("scope_logs", []))
        if not isinstance(scope_logs, list):
            continue
        for sl in scope_logs:
            if not isinstance(sl, dict):
                continue
            scope_obj = sl.get("scope")
            scope = scope_obj.get("name", "") if isinstance(scope_obj, dict) else ""
            log_records = sl.get("logRecords", sl.get("log_records", []))
            if not isinstance(log_records, list):
                continue
            for lr in log_records:
                if not isinstance(lr, dict):
                    continue
                if len(records) >= MAX_RECORDS:
                    raise OtlpDecodeError("more than %d log records in one request" % MAX_RECORDS)
                records.append(_record(
                    res_attrs=res_attrs,
                    scope=scope if isinstance(scope, str) else "",
                    attrs=_json_attrs(lr.get("attributes")),
                    time_nano=_as_nano(lr.get("timeUnixNano", lr.get("time_unix_nano"))
                                       or lr.get("observedTimeUnixNano",
                                                 lr.get("observed_time_unix_nano"))),
                    sev_num=lr.get("severityNumber", lr.get("severity_number")),
                    sev_text=lr.get("severityText", lr.get("severity_text")) or "",
                    body=_json_any_value(lr.get("body")),
                    trace_id=_json_id(lr.get("traceId", lr.get("trace_id"))),
                    span_id=_json_id(lr.get("spanId", lr.get("span_id"))),
                    event_name=lr.get("eventName", lr.get("event_name")) or "",
                ))
    return records


def _as_nano(value: Any) -> int | None:
    """uint64 in proto3 JSON is a STRING, because a JSON number loses precision past 2^53."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


# --------------------------------------------------------------------------- the mapping

def slug(value: Any) -> str:
    """A `service.name` as a filename-safe candidate. NOT the gate -- `normalise` is."""
    if not isinstance(value, str):
        return ""
    out = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return out[:32]


def level_of(text: Any, number: Any) -> str:
    """Word first, number second, `info` last. An unknown level never costs us the line."""
    if isinstance(text, str) and text.strip():
        mapped = _SEVERITY_WORDS.get(text.strip().lower())
        if mapped:
            return mapped
    if isinstance(number, str) and number.strip().lstrip("+-").isdigit():
        number = int(number)
    # SEVERITY_NUMBER_INFO etc. arrive as names when a producer serialises the enum by name.
    if isinstance(number, str):
        for word, mapped in _SEVERITY_WORDS.items():
            if number.strip().lower().endswith(word):
                return mapped
        return "info"
    if isinstance(number, int) and not isinstance(number, bool) and number > 0:
        for ceiling, mapped in _SEVERITY_BANDS:
            if number <= ceiling:
                return mapped
        return "crit"
    return "info"


def _event_name(attrs: dict, event_name: str, scope: str) -> str:
    """A STABLE machine name, never the body.

    §4.3: "stable machine name ... never interpolated", and §4.3's closing line says counting
    `evt` is exact where counting words inside `msg` produced 97 instead of 8. A body is free
    text with an order id in it; using it here would mint a new `evt` per request and make the
    count useless. The instrumentation scope is the best stable name a producer that sets no
    event attribute still gives us -- `Microsoft.AspNetCore.Hosting`, not "Request finished in
    31.4ms". The body is kept in full, as `msg`.
    """
    for key in _EVENT_KEYS:
        value = attrs.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:128]
    if isinstance(event_name, str) and event_name.strip():
        return event_name.strip()[:128]
    if scope.strip():
        return ("otlp." + scope.strip())[:128]
    return "otlp.log"


def _flatten(value: Any) -> Any:
    """§4.3: `ctx` is flat, no nesting. A structured attribute becomes its JSON text."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    try:
        return json.dumps(value, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(value)


def _record(*, res_attrs: dict, scope: str, attrs: dict, time_nano: Any, sev_num: Any,
            sev_text: Any, body: Any, trace_id: str, span_id: str, event_name: str) -> dict:
    """One OTLP LogRecord as a §4.3 object. `normalise` still has the last word on every field."""
    merged = dict(res_attrs)
    merged.update(attrs)

    line: dict[str, Any] = {
        "svc": slug(next((merged[k] for k in _SERVICE_KEYS if merged.get(k)), "")),
        "lvl": level_of(sev_text, sev_num),
        "evt": _event_name(merged, event_name, scope),
    }

    nano = _as_nano(time_nano)
    if nano:
        # Seconds since epoch would be ~1.7e9 and nanoseconds ~1.7e18. A producer sending the
        # wrong unit would otherwise land in year 56000, where the retention sweeper -- which
        # deletes by DATE -- would keep the file for ever.
        try:
            when = datetime.fromtimestamp(nano / 1_000_000_000, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            when = None
        if when is not None:
            line["ts"] = when.strftime("%Y-%m-%dT%H:%M:%S.") + f"{when.microsecond // 1000:03d}Z"

    if isinstance(body, str) and body:
        line["msg"] = body
    elif body is not None and not isinstance(body, str):
        line["msg"] = _flatten(body)

    corr = next((merged[k] for k in _CORR_KEYS if isinstance(merged.get(k), str) and merged[k]), "")
    if corr:
        line["corr"] = corr
    elif trace_id:
        line["corr"] = trace_id

    ctx = {k: _flatten(v) for k, v in merged.items()
           if k not in _CONSUMED and not k.startswith(_SDK_SELF_DESCRIPTION)}
    if scope:
        ctx.setdefault("otel.scope", scope)
    if span_id:
        ctx.setdefault("span", span_id)
    if ctx:
        line["ctx"] = ctx
    return line


def decode(body: bytes, content_type: str) -> list[dict]:
    """Decode one OTLP/HTTP request body by its declared content type.

    An unrecognised content type is read as JSON rather than refused: an OTLP client that
    declares nothing is far more likely to be sending JSON than to be sending nothing, and a
    body that is not JSON still fails loudly one line later.
    """
    kind = (content_type or "").split(";")[0].strip().lower()
    if kind in PROTOBUF_TYPES:
        return decode_protobuf(body)
    try:
        payload = json.loads(body.decode("utf-8")) if body.strip() else {}
    except UnicodeDecodeError:
        raise OtlpDecodeError("body is not utf-8")
    except ValueError as exc:
        raise OtlpDecodeError("body is not JSON: %s" % exc)
    return decode_json(payload)
