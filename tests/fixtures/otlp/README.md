# OTLP fixtures

`dotnet_1_15_3_logs.protobuf` is 385 bytes of `application/x-protobuf` produced by the
OpenTelemetry .NET exporter this estate pins — the same package version `Store.Api` compiles
(`store_platform/Directory.Packages.props`, `OpenTelemetry.Exporter.OpenTelemetryProtocol`
1.15.3). It is ground truth, not something we encoded: `tests/unit/test_otlp.py` decodes it
with our own hand-written protobuf reader, so if that reader is wrong the test fails against
bytes we did not write.

Captured 2026-08-20 by pointing the real exporter at a local capture server:

```csharp
o.SetResourceBuilder(ResourceBuilder.CreateEmpty()
    .AddService(serviceName: "store-api", serviceVersion: "1.2.3"));
o.IncludeFormattedMessage = true;
o.ParseStateValues = true;
o.AddOtlpExporter(e => {
    e.Endpoint = new Uri("http://127.0.0.1:4319/internal/logs/otlp");
    e.Protocol = OtlpExportProtocol.HttpProtobuf;
    e.ExportProcessorType = ExportProcessorType.Simple;
});
// then:
log.LogWarning("checkout session {SessionId} expired after {Minutes} min", "cs_test_123", 30);
```

Two things in these bytes are worth knowing before anyone edits the reader. The exporter pads
its length varints to a fixed width rather than writing the minimal encoding (`0a fc 82 80 00`
is a 4-byte varint for 380), so a reader that assumes minimal varints reads this payload wrong.
And the endpoint was used verbatim — the exporter appended no `/v1/logs`, which is why
`log_ingest` registers both spellings rather than guessing which one a client will use.

## `store_api_central_log.protobuf`

437 bytes, and the more important of the two: it is not a payload from a hand-built emitter, it
is what `Store.Api`'s own central-log wiring sent. The exporter, the redaction processor, the
resource and the batch settings are all the ones the service runs with. Decoding it in
`tests/unit/test_otlp.py` is the only test that spans both languages, so it is what would catch
the producer and the reader agreeing with themselves and not with each other.

Re-record it by running the .NET test that captures it:

```bash
cd store_platform
PROSPECTOR_OTLP_CAPTURE="$PWD/../tests/fixtures/otlp/store_api_central_log.protobuf" \
  dotnet test src/Store.Tests/Store.Tests.csproj \
  --filter "FullyQualifiedName~CentralLogOtlpWireTests"
```

The field named `stripeApiKey` in it holds `[redacted]`. That is the point of the fixture: the
value the test logged was `sk-live-NOT-A-REAL-KEY-0000`, shaped like a credential so a leak
would be visible, and it does not appear anywhere in these bytes.

`corr` is absent because the capture runs outside a request. In the service the processor reads
the same `X-Correlation-Id` pipeline as everything else; the engine falls back to the OTLP trace
id when the attribute is missing.
