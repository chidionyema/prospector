# Spec — Close the search-observability gap (P0, detected 2026-06-24)

## Problem (do not rewrite this; it's the bug we are fixing)

`web_calls=0` in `store/scheduler/DIAGNOSTICS_LATEST.txt` is a **broken metric**, not
evidence of a retrieval outage. `record_usage(web=True)` is the only thing that
increments the counter (`prospector/telemetry.py:206`), and **no search provider calls
it**. Direct invocation of `ExaSearchProvider.search()` returns 2 real URLs in ~18s —
the search works. But because nobody increments the counter, every diagnostics row
reports `web_calls=0` and the alert "0 web retrieval → all unverifiable" is a false
alarm as currently evidence-sourced.

This is a **testing-process gap**: we shipped a metric nobody incremented, and the
metric is what we used to decide whether the search was firing. The user directive
(2026-06-24): we cannot be guessing; we must log and observe thoroughly; we must
prevent this from ever happening again.

## Goals (acceptance criteria)

A change ships when ALL of the following are true:

1. **Every** invocation of `SearchProvider.search()` (or a subclass) increments
   `record_usage(web=True, provider=<root>)` exactly once, regardless of whether the
   call succeeded, returned [], or raised.
2. A new audit log `store/scheduler/search_audit.jsonl` (or `store/scheduler/audit/
   search.jsonl` if a per-event dir is cleaner) is **append-only** and records every
   search call with: `ts`, `provider`, `query` (truncated to 200 chars), `k`,
   `max_chars`, `returned_n`, `latency_ms`, `status` ("ok"|"empty"|"error"),
   `error` (if any), `invoked_from` (e.g. `verify.run_check`, `golden`, `cli`).
3. `verify.run_check` records, in the same audit log, when it calls search and how
   many passages came back per query, so we can answer "did the verifier actually
   reach the search call?" without reading code.
4. New invariant test `tests/invariants/test_search_observability.py` is **RED** before
   the fix and **GREEN** after. Test asserts:
   - `record_usage(web=True, ...)` is called inside each provider's `.search()`.
   - Audit log row is appended for every call (success or failure).
   - DiskCache hits/misses are recorded separately.
   - FallbackSearchProvider records the provider that actually answered (not just the
     chain name).
5. New alert distinguishes "counter never moved" (telemetry bug) from "counter moved
   then dropped to 0" (real outage). The current alert is renamed / rekeyed so the
   false-alarm text is gone.
6. The existing `pytest -q` suite is **still green** (489 tests + the new one). Any
   test that relied on `web_calls == 0` (i.e. mocked out) is updated to assert the new
   behaviour.
7. Live proof: after the change, the next daemon tick shows `web_calls > 0` in
   `DIAGNOSTICS_LATEST.txt` and at least one row in `search_audit.jsonl`. If the next
   tick does not show this, the change is not done.

## Scope (what to change)

### `prospector/retrieval.py` — wire `record_usage(web=True)` in every provider

Providers to instrument (every `.search()` method):

- `FixtureProvider.search` — provider="fixture" (yes, even fixtures should record, so
  the counter shows whether the verifier reached search at all)
- `GeminiGroundingProvider.search` — provider="gemini"
- `BraveSearchProvider.search` — provider="brave"
- `ExaSearchProvider.search` — provider="exa"
- `_LLMSearchProvider.search` (parent of DeepSeek / MiniMax / OpenRouter) —
  provider=self.provider_name; record once in the base so subclasses inherit it
- `DiskCache.search` — provider="cache", with a `cache_hit` boolean field so we can
  distinguish hits from misses
- `FallbackSearchProvider.search` — record the **actually-used** provider (the one
  whose call returned or raised), not "fallback" — otherwise the counter still shows
  0 when chain=[exa,brave] and exa succeeded

Pattern (apply to each `.search()`):

```python
@track_latency(name="exa_search")
def search(self, query, k=4, max_chars=1500):
    record_usage(web=True, provider="exa")   # ALWAYS, even on exception
    try:
        ... existing body ...
        _audit_search(provider="exa", query=query, k=k, max_chars=max_chars,
                       returned_n=len(results), status="ok" if results else "empty")
        return results
    except Exception as e:
        _audit_search(provider="exa", query=query, k=k, max_chars=max_chars,
                       returned_n=0, status="error", error=str(e)[:200])
        raise
```

`record_usage` must be called BEFORE the try/except so an exception still increments.

### `prospector/audit.py` (NEW) — append-only audit log

```python
"""Append-only audit log for search and verify events.

A 'we cannot guess what is wrong' file: every search call, every verify invocation,
and every retrieval failure leaves a structured row that can be replayed to reconstruct
what actually happened. No row is rewritten or deleted.
"""
import json, os, threading
from datetime import datetime, timezone
from pathlib import Path

_AUDIT_DIR = Path(os.environ.get("PROSPECTOR_AUDIT_DIR", "store/scheduler/audit"))
_AUDIT_DIR.mkdir(parents=True, exist_ok=True)
_LOCK = threading.Lock()

def audit(event: str, **fields) -> None:
    """Append one structured event to today's audit file."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = _AUDIT_DIR / f"{today}.jsonl"
    row = {"ts": datetime.now(timezone.utc).isoformat(), "event": event, **fields}
    line = json.dumps(row, separators=(",", ":"), default=str)
    with _LOCK:
        with path.open("a") as f:
            f.write(line + "\n")
```

Usage in providers: `audit("search", provider="exa", query=q[:200], k=k, max_chars=mc,
returned_n=n, status="ok", latency_ms=ms)`.

Usage in verify.py: `audit("verify_search", check=check_name, candidate_id=cand.candidate_id,
queries=queries, per_query_n=[n1, n2, ...], retrieval_failed=...)`.

### `prospector/verify.py` — add audit calls

Inside `run_check`, after the search block (around line 350), record:

```python
audit("verify_search",
      check=check_name,
      candidate_id=cand.candidate_id,
      queries=queries,
      queries_n=len(queries),
      n_failed=n_failed,
      passages_n=len(uniq),
      retrieval_failed=(queries and n_failed == len(queries)),
      short_circuit_empty=(not uniq and not n_failed))
```

This is the missing piece — even if the provider counter is broken, this audit row
proves whether `verify.run_check` reached the search block.

### `prospector/telemetry.py` — no change to `record_usage` (already correct)

The function is fine; we just need callers.

### `prospector/scheduler/diagnostics.py` — distinguish broken-counter from real outage

The alert currently fires whenever `web_calls == 0`. Update:

```python
# OLD: alert if web_calls == 0
# NEW: only alert if a search WAS attempted (audit shows ≥1 search event for this
# batch) and web_calls == 0. If audit shows zero search events either, the
# retrieval chain was never reached — different alert ("verifier never searched").
```

Rename the alert to `retrieval_not_fired` (was `zero_yield`) so the message is
accurate; keep `zero_yield` as a separate, downstream alert that fires when 0 PASSes
land across N batches regardless of search.

### `tests/invariants/test_search_observability.py` (NEW) — RED before fix, GREEN after

Required assertions (each in its own test function so failures are localised):

1. `test_exa_search_increments_web_calls` — invoke `ExaSearchProvider.search()` once
   against a stubbed Exa client (mock the network). Snapshot `record_usage` counters
   before/after. Assert `web_calls` delta >= 1 and provider bucket == "exa".

2. `test_brave_search_increments_web_calls` — same shape for Brave.

3. `test_fixture_search_increments_web_calls` — same shape for FixtureProvider (so
   even offline runs prove the verifier reached search).

4. `test_disk_cache_hit_and_miss_recorded` — invoke twice with same query. First
   miss, second hit. Assert two audit rows with `cache_hit=False` / `cache_hit=True`
   respectively, and `web_calls` incremented twice (cache wraps every call).

5. `test_fallback_records_actual_provider` — chain=[fixture, exa_stub]. Invoke a
   query the fixture misses. Assert audit row provider="exa" (not "fallback"), and
   `web_calls` incremented for "exa".

6. `test_verify_run_check_writes_audit_row` — invoke `run_check` with a stubbed
   operator and a FixtureProvider that has matching fixtures. Assert at least one
   `audit("verify_search", ...)` row was written with `check`, `queries_n`,
   `passages_n`.

7. `test_search_failure_still_increments_web_calls` — stub Exa to raise. Invoke
   `ExaSearchProvider.search()`. Assert `web_calls` delta >= 1, audit row status="error".

8. `test_search_audit_row_format` — schema-check an audit row has `ts`, `event`,
   `provider`, `query`, `k`, `max_chars`, `returned_n`, `latency_ms`, `status`.

9. `test_live_tick_proves_web_calls_moves` (integration, slow) — runs the daemon
   for one tick on a real Exa key (skipped if `EXA_API_KEY` is empty / mocked). Asserts
   `DIAGNOSTICS_LATEST.txt` next-write shows `web_calls > 0`.

Mark the test module `@pytest.mark.observability` so it can be run separately.

### CLI flag (nice-to-have, not blocking)

`python -m prospector.run --audit-tail N` to print the last N audit rows, so an operator
can ask "what just happened?" without grepping the JSONL.

## Out of scope

- Changing the alert thresholds, the lane config, the operator chain, or any moat logic.
- Replacing `_LLMSearchProvider` with a different architecture.
- Any change to `verify.py` verdict logic (we only add observability; no behaviour change).
- New tests for golden-set or invariants unrelated to this gap.

## Verify command (Builder runs this; exit 0 = done)

```
.venv/bin/python -m pytest tests/invariants/test_search_observability.py -v
.venv/bin/python -m pytest -q
```

After the test suite is green, the live proof is:

```
# wait for the next daemon tick (≤2h) or trigger one
.venv/bin/python -m prospector.scheduler.run_scheduled --once --config config.yaml
# then check
grep "web_calls" store/scheduler/DIAGNOSTICS_LATEST.txt   # MUST be > 0
wc -l store/scheduler/audit/$(date -u +%F).jsonl           # MUST be > 0
```

If the live tick shows `web_calls == 0` after the fix, the change is NOT done — go back
and find which provider path was missed.

## Founder fence (do NOT delegate money/identity changes)

This is observability + telemetry wiring. NOT a verdict rule change. NOT a moat logic
change. Safe to delegate per the architect protocol.

## Estimated scope

- ~50 lines added to `prospector/retrieval.py` (record_usage + audit calls in each
  provider's search method)
- ~30 lines for `prospector/audit.py` (new module)
- ~10 lines in `prospector/verify.py` (one audit call in run_check)
- ~15 lines in `prospector/scheduler/diagnostics.py` (alert rekey)
- ~150 lines for `tests/invariants/test_search_observability.py` (the new tests)

Total: ~250 lines, surgical, mostly mechanical. No public-API changes.