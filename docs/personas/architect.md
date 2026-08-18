# The platform for the architect

Two questions define this seat here. **What are the seams**, and **what happens the day we leave
Fly.** The second is a founder constraint, not a thought experiment: no platform lock-in, and moving
off must be seamless and pre-planned.

## The shape

Four paths through one estate.

```
MAKING     signal → generate → dedup → prescreen → verify (7 checks) → kill filter
                  → score (6 axes) → pack render (16 renderers) → publish
SELLING    mumchimp.com → api.mumchimp.com → Stripe → entitlement → download
OPERATING  ops console + Hermes/Telegram → ~76 catalogued tools → store/
BUILDING   worktree → commit gate → CI (8 jobs, self-hosted) → merge → deploy
```

**Making can stop for a day and nobody notices. Selling cannot stop for a minute.** Every
availability decision follows from that asymmetry.

## The deployment substrate

Six Fly apps, one process each, plus five `tie-*` apps belonging to a separate older product that are
kept on purpose.

| App | Role | Volume |
|---|---|---|
| `prospector-engine` | The pipeline, and it serves the ops console | `prospector_store`, 20G |
| `prospector-store-api` | Catalogue, checkout, entitlements, delivery | `store_data`, 974M |
| `prospector-store-web` | The storefront, 2 machines | none |
| `prospector-searxng` | Private search the engine grounds against | none |
| `prospector-hermes` | Telegram, coordinator, Otto | `hermes_state`, 2.9G |
| `prospector-ci` | Intended home of the CI runners. Suspended | none |

Two machines only for the storefront. That is where the availability requirement lives, and it is
the only app with redundancy.

## The portability contract

The founder chose route "c": **Compose substrate plus adapters now, declarative infrastructure
later.** The practical meaning is that every piece of the estate must be describable and runnable
without Fly-specific primitives.

What makes leaving cheap today:

- **Every app is a container with a Dockerfile.** No Fly buildpacks, no proprietary runtime.
- **Domain names and secrets are declared values**, not hardcoded strings. Changing
  `mumchimp.com` is configuration.
- **State is on volumes with plain formats**: SQLite files and JSONL. No managed database, no
  proprietary store. `prospector-engine` 20G, `store-api` 974M, `hermes` 2.9G — all small enough to
  move in one transfer.
- **The secret inventory is enumerable**: 14 on the engine, 24 on the store API, 29 on Hermes, 0 on
  the storefront and searxng. `scripts/estate_map.py` prints the names, never the values. That list
  is the actual migration checklist.
- **There is no hosted inference.** The engine runs locally or inside the subscription. This is the
  single biggest reason the estate is portable — the expensive dependency is an API contract, not an
  infrastructure one.

What still ties us:

- Fly volumes and Fly's own health-check and machine-restart semantics. The engine's supervisor knows
  it is not on launchd but it does not manage itself.
- `FLY_MACHINE_ID` is now read directly by the ops console to decide "am I production". That is one
  environment variable and one adapter's worth of work, but it is a real Fly reference.
- DNS and certificates are issued through Fly for `api.mumchimp.com`.

**R3, the leave-Fly proof, is the piece that closes this.** Until the whole stack has been stood up
somewhere else once, portability is a design claim, not a measured one.

## The seams, and how clean each one is

| Seam | Contract | Clean? |
|---|---|---|
| Engine ↔ model providers | `operator.py` adapters, roster declared in `config.yaml:58,81` | **Yes.** Swapping brains is a config line |
| Engine ↔ retrieval | `retrieval.py`, chain `[ddg, exa, claude_cli]`, per-provider breakers | **Yes.** Gemini was removed without a code change to callers |
| Engine ↔ store | `config.store_root()` | **Now yes.** Four constants derived paths from `__file__` and followed the code instead of the data |
| Engine ↔ money rail | `prospector/bridge.py`, one `PriceDecision` | **Yes, and deliberately narrow** |
| Store API ↔ payment provider | `/webhooks/{provider}` is parameterised | **Partly.** See `docs/PAYMENT_RAIL_INDEPENDENCE_SPEC.md` |
| Store API ↔ storefront | HTTP, `/catalog` | **Yes** |
| Engine ↔ ops console | Python view functions rendered by hand-written TypeScript types | **No.** This is the weakest seam in the estate |
| Estate ↔ operator | The console tool catalogue with risk levels and undo | **Yes** |

The console seam is the one to fix. Three pages crashed in a single day because a TypeScript type
declared a shape the Python view never sent. The types are written twice, by hand, and `tsc` cannot
catch a type that lies about the wire.

## The reliability model

Not high availability. **Recoverability, with honest state.**

- One machine per app except the storefront. A restart is the recovery mechanism.
- Provider failure is classified once, by one shared tested function, into transient (60s) and
  permanent (1h). The mark is half-open, so exactly one caller machine-wide re-probes and a provider
  that recovers in 90 seconds is back in 90 seconds.
- The pipeline defers rather than deciding wrongly. An unevaluated check produces "come back to it",
  never "this idea is dead".
- Three-state answers everywhere: `ok`, `FAIL`, and `?` for "could not ask". **"Could not ask" is not
  "fine"**, and collapsing the two is the most common observability bug in this estate.

## Known architectural debt

1. **The Python ↔ TypeScript view contract is hand-maintained.** Generate it.
2. **The canonical store is on the laptop** at `/Users/chidionyema/Documents/code/prospector/store`,
   pinned by `PROSPECTOR_STORE_DIR`, while the engine runs on Fly. That is deliberate and it works,
   but it is a laptop dependency in a stack whose stated goal is to have none.
3. **CI runners are still on the laptop** (R8). `prospector-ci` is provisioned and suspended.
4. **`~/Documents` is iCloud-synced with Optimize Storage**, so the working trees and the canonical
   store live on a filesystem that can evict files. It has happened.
5. **R3 is unproven.** Portability is designed, not demonstrated.

## What to read next

- [ESTATE_MAP.md](../ESTATE_MAP.md) §9 "Leaving Fly" — the actual runbook.
- [principal-developer.md](principal-developer.md) — enforcement versus prose.
- `docs/DECOUPLING_PROGRAM.md`, `docs/PAYMENT_RAIL_INDEPENDENCE_SPEC.md`.
