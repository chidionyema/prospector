# The platform for the senior developer

You already know how to write the code. What you need is the map of what already exists, so you
extend a mechanism instead of adding a second one, and the list of edges that have actually drawn
blood.

The standing rule: **smallest diff that fixes it. A new module needs a demonstrated reason the
existing one cannot serve.**

## The mechanisms that already exist

Before you build any of these, read the one that is there.

| You are about to build | It exists as |
|---|---|
| A retry or failover policy | `prospector/errors.py` + `prospector/health.py`. One classifier, one persisted dead-mark file, half-open probes |
| A way to stop the pipeline | Three, deliberately different: `PAUSE`, `PAUSE_GENERATION`, `schedule.backlog_cap` |
| A rollback | `prospector/ops/undo.py`, plus a snapshot taken by every console action |
| A tool the operator can run | `prospector/ops/console_api.py:2206 TOOLS`, with `risk` levels and a drift test |
| A price change | `prospector/bridge.py`. One `PriceDecision` writes both halves |
| A store path | `config.store_root()`. Never `Path(__file__).parent.parent / "store"` |
| A grounding source | `prospector/retrieval.py`, chain `[ddg, exa, claude_cli]`, per-provider breakers |
| A model call that must not rule | The non-critical chain, `run.py:320 _noncritical_order` |
| A pack section | One of sixteen `prospector/pack_*.py` renderers, all deterministic and model-free |
| A status claim in a doc | A probe. `scripts/estate_map.py`, `scripts/ops_status.py`, `scripts/live_checkout.py` |

## The invariants you must not casually break

**The moat roster is config, not code.** `config.yaml:81 moat_primary:` names who may rule finally.
Anything outside that set that rules is stamped `provisional` by
`operator.is_provisional_provider` (`operator.py:1451`), never publishes on PASS (`run.py:864`), and
is automatically re-vetted. This was a hardcoded frozenset until 2026-08-15 — the one tier knob that
needed a source edit and a daemon re-exec to move.

A test that hardcodes "minimax is untrusted" is **pinning the roster, not the fence.** MiniMax is
inside `moat_primary` now and is also the only non-critical tier. Those two facts are independent.

**An exception is never evidence.** A verdict call that raises returns `retrieval_failed=True`
(`verify.py:365`), which fires the DEFER gate (`verify.py:693`). It does not contribute an
`unverifiable` check to the kill gates. Before this was true, `store/dossiers/2102bacc6dd75cf9.kill.json`
recorded a KILL whose seven checks all read `unverifiable, conf 0.0, "Verdict call failed;
fail-safe."` — a candidate killed by our own outage, in a dossier that reads as fully reasoned.

**Generation may run into a provisional tail; the drain may not.** `run.py::_cmd_resume` runs the
same classifier at `trusted_only=True`, because re-vetting a provisional row on a provisional brain
re-stamps it provisional: the row does not move and the money is spent. One shared function, one
parameter, so the two cannot disagree by accident.

**`price_comparables` can never kill.** Barred in `kill_filter.is_hard_fail` and in verify's run
order.

**Two loops never merge.** Sales metrics tune what to offer. Truth metrics veto what may ship. Demand
never overrides truth.

## Failure classes that keep recurring

These are worth recognising by shape, because each one has appeared more than once wearing a
different costume.

**A type that promises more than the wire delivers.** Three ops console pages crashed in one day
because a TypeScript type declared a shape the Python view never sends — `data.stuck`, six camelCase
field names, and `standby.files` values that are legitimately `null`. `tsc` cannot catch a type that
lies. Where a view is hand-written on both sides, the type is the thing most likely to be wrong.

**A path derived from `__file__` follows the code, not the data.** When the engine moved to Fly, four
such constants wrote provider health marks, the retrieval cache and the scheduler audit trail beside
the new code while the ledger went to the canonical store. A daemon writing one health file while a
probe reads another can never see a provider recover.

**A fence in the wrong process.** An in-process guard cannot stop a subprocess sender. A
selection-time fence misses a runtime substitution. A source scanner cannot see a label built at
render time.

**A redundant mechanism makes a test pin the wrong thing.** If two things both produce the right
answer, the test passes when you delete the one that matters.

**A fallback chain that works hides its own degradation.** The run succeeds, so nothing looks wrong,
while the head of the chain is a guaranteed failure paid before every call. That is why permanence is
classified by one shared tested function and why a dead brain leaves a trace.

**A substring match on an HTTP code benches a live brain.** `errors.py` matches on word boundaries
now, because a request id containing "429" benched a healthy provider.

## Reviewing someone else's change

The burden of proof is on the claim, whoever makes it. Do not reject a design without a demonstrated
failure mode. Transition cost and clobber risk are real, but they are **process risk** and must be
labelled as such — they are not arguments that a design is objectively worse.

Comparisons are claims. "Faster" and "more reliable" need the concrete scenario where A breaks and B
does not, plus a test that distinguishes them.

## What to read next

- [principal-developer.md](principal-developer.md) — which invariants are actually enforced.
- [architect.md](architect.md) — the seams and the portability contract.
- `docs/ENGINE_RELIABILITY_PROGRAM.md`, `docs/PACK_NARRATIVE_PROGRAM.md`.
