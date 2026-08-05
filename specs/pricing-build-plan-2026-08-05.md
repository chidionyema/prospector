# Dynamic pricing — build plan and delegation partition

Companion to `specs/dynamic-pricing-system-2026-08-05.md` (the analysis). That document argues
*what* to build and why. This one is the execution plan: what is already done, what must stay in
Claude, what can go to a cheaper model, and the exact contract + golden test that makes each
delegated unit safe to accept without reading its diff.

Written 2026-08-05.

---

## 1. Status: Layer 0 is built and green

| Claim | Proof |
|---|---|
| Price is now mutable post-publish | `PATCH /internal/catalog/{id}/price` in `store_platform/src/Store.Api/Program.cs`; before it, the upsert path ignored `PricePence` on update |
| Fulfilment no longer gates on a moving number | `FulfilmentService.cs:122` reads `pack.EffectiveFloorPence(DateTime.UtcNow)` |
| The floor logic holds across repeated changes | `PackPriceFloorTests` — 9/9 passing, incl. `Floor_never_exceeds_any_price_that_was_live_in_the_window` |
| The endpoint's guards hold | `PricePatchTests` — 12/12 passing |
| Nothing regressed, incl. the founder fence | full `Store.Tests` suite: `Passed! - Failed: 0, Passed: 257, Duration: 22 s` |

Not yet done at L0: the 61 live packs still carry the flat £49, and no caller invokes the new
endpoint. That is §4 step 3 below.

---

## 2. The partition rule

The global operating rules fix the line, and it is not negotiable per-task:

> "Money/identity/contract/migrations never leave Claude (founder fence)."
> "DeepSeek/MiniMax are reserved for non-critical generation and triage ONLY."

Applied here, the test is **not** "is this hard?" but **"can a wrong answer take money and deliver
nothing, or deliver without taking money?"** Two consequences that are easy to get backwards:

- **The `PriceEngine` ladder is delegatable even though it decides prices.** It is a pure function
  from segment to one of a fixed set of rungs. Its output is then written through the L0 endpoint,
  which independently re-checks billability and moves the floor correctly. A wrong rung is a
  *commercial* error (£79 where £49 was right) — recoverable, and caught by a golden matrix. It
  cannot strand a payment.
- **The 61-pack backfill is NOT delegatable even though it is mechanical.** It mutates live listed
  packs on the production rail. A wrong ordering there is exactly the failure L0 exists to prevent.

Rule of thumb for accepting delegated work: *if I would need to read the diff to trust it, the
spec is not tight enough to delegate.* Every unit below ships with a golden test that fails on the
plausible wrong implementations, so acceptance is "run it, don't read it".

---

## 3. Work units

### 3A. Claude-only (founder fence)

**C1 — Backfill the 61 live packs off the flat £49.**
Drive the new `PATCH /internal/catalog/{id}/price` against production, one pack at a time, each
with a `Reason` naming the ladder version and segment, and each Stripe `Price` minted before the
catalogue write. Stripe `Price` objects are immutable, so every change mints a new id
(`bridge.py:504-508` is the existing mint path to reuse). Verify by read-back from `/catalog`, not
by the write's status code — a 200 proves the handler ran, never that the value landed
(`store-catalog-metadata-is-typed-columns` memory).

**C2 — Repoint `bridge.py` off the flat constant.**
Two sites, both currently `int(self.cfg.listing.get("price_pence", 4900))`:
`prospector/bridge.py:507` (the Stripe price mint) and `prospector/bridge.py:854` (the catalogue
payload). Both must read the `PriceEngine` decision instead. This is the money rail's entry point,
so it stays with Claude even though the engine behind it is delegated.

**C3 — The `price_comparables` moat check.**
`verify.py` already retrieves willingness-to-pay passages and discards the quantitative content.
Adding a seventh check makes it a cited per-pack anchor. It is a *verification verdict*, and the
project rules are explicit that DeepSeek/MiniMax never touch those. Claude-only by rule, no
judgement call needed.

**C4 — Final review of every delegated diff before merge.** Run the golden tests; read only what
they don't cover.

### 3B. Delegatable — raw execution on MiniMax / cheaper Claude

Each unit is written so the executing model needs no context beyond the unit itself plus the named
files. **Specs to be written as separate hand-off files before dispatch** — this section is the
partition and the acceptance contract, not the hand-off text itself.

---

**D1 — `prospector/pricing.py`: the deterministic ladder.**

*Contract.* One pure function, no I/O, no network, no config mutation:

```python
def price_for(candidate: Candidate, score: ScoreResult, cfg: Config) -> PriceDecision
```

`PriceDecision` carries `price_pence: int`, `rung: str`, `segment: dict[str, str]`, and
`rationale: str`. Inputs are segment axes that already exist on the model and are proven present:
`Candidate.ambition_tier` (`models.py:113`, values `side_hustle|smb|growth|venture`),
`Candidate.market` (`models.py:117`), and the score axes.

*Non-negotiables the golden test must enforce:*
- Output is always one of a fixed rung set declared in `config.yaml` — never a computed continuous
  value. (Discrete rungs are the §3 spec's position; a continuous function is the wrong answer here
  and the test must reject it.)
- Deterministic: same inputs ⇒ same output, no clock, no RNG.
- Total: every `(ambition_tier, market)` combination including `""` (the back-compat default, see
  `models.py:112`) returns a rung. No `KeyError`, no `None`.
- The default `("", "")` case returns exactly `4900`, so the ladder is a no-op until deliberately
  moved off it.

*Acceptance:* `tests/test_pricing.py` with a golden matrix over the full cross-product of
`{side_hustle, smb, growth, venture, ""} × {uk, us, ""}`, expected pence hard-coded. Green suite,
no other test file touched.

*Also in scope:* delete `listing_price_signal` (`prospector/score.py:58`). It is dead — a
repo-wide grep for callers returns only its own definition and a worktree copy. Leaving a second,
unused pricing concept next to the real one is how the wrong one gets wired up later.

---

**D2 — Storefront analytics events.**

Add `price_viewed` and `checkout_started` emission in `store_platform/src/Store.Web`, carrying
`pack_id`, `price_pence`, and the rung/epoch label. This is the instrument that makes every
pricing decision afterwards measurable — the §3 spec's whole argument is that purchases are too
rare an event to learn from, so the cheaper events must exist first.

*Acceptance:* existing storefront test suite green, plus a test asserting both events fire with the
required fields. No change to any rendered price.

---

**D3 — Rationale record writer.**

Every price decision writes a JSON record under `store/pricing/rationale/` — inputs, rung chosen,
ladder version, timestamp — and the path is what `PricePatchRequest.RationaleRef` points at
(`store_platform/src/Store.Api/Contracts/PricePatchRequest.cs`). Pure serialisation against a
schema; no decision logic.

*Acceptance:* round-trip test — write a decision, read it back, assert every field survives; and a
test that the emitted path matches what the PATCH request carries.

---

**D4 — Demand simulator.**

Offline harness that replays a candidate ladder against synthetic demand curves so a proposed
change can be evaluated before it is posted. No production reads, no writes outside `store/`.
Deliberately last in the delegated set: it is the largest unit and the only one nothing else blocks
on.

*Acceptance:* deterministic under a seed passed in as a parameter; a fixed scenario file produces a
byte-identical report across two runs.

---

**D5 — Waitlist `PriceAnchorPence`.**

Capture the price shown at waitlist-join time. Additive column + write path, mirroring the existing
migration pattern. Note: it is a schema migration, which the fence names — so D5 is delegatable
*only* as a patch proposal; **Claude applies the migration**. If that split is awkward, fold D5
into C-work rather than relaxing the fence.

---

## 4. Order

1. **D1** (`pricing.py` + golden matrix) and **D2** (analytics) in parallel — independent, and D2's
   events want to be live before any price actually moves so the before/after is measurable.
   **D1 DONE 2026-08-05** — `prospector/pricing.py`, delegated to MiniMax, commit `0f9a6a7`.

   **D2 DONE 2026-08-05, but LATE, and the lateness cost something specific.** D2 was not built
   alongside D1; it landed after C1 had already moved 13 packs. The stated reason D2 went first was
   that its events must be live before any price moves, so the before/after is measurable — that
   window is closed and the before/after on the 2026-08-05 22:07Z reprice is unrecoverable. D2 is
   the instrument for the *next* move, not for the one already made. Do not read a later
   price→checkout rate as evidence about that reprice.

   What shipped: `price_viewed` (denominator) and `checkout_started` (numerator), each carrying
   `pack_id` and `price_pence`. `price_viewed` fires from the pack page keyed on
   `(pack.id, pack.pricePence)`, so a price that changes under a client-side navigation counts as
   the separate view it is. `checkout_started` fires from `usePackCheckout.buy()` — the ONE shared
   buy path, used by both the pack page and the shelf's Buy drawer — and fires on *intent*, before
   the provider call and outside the `try`, because a numerator that only counted checkouts the
   provider managed to open would hide exactly the failure a price change is most likely to cause.

   `price_pence` is also the rung. The ladder is a fixed set of seven values, so pence maps to a
   rung one-to-one and a separate rung field would be a second source of truth for one fact, free
   to disagree with the price it labels — the C2 failure mode one layer up. Which ladder was in
   force is recovered by joining on the event's server-side `CreatedAt`, never on a label the
   browser wrote.

   The storefront had no pence to report: `/catalog` served only the display string `"£49.00"`.
   `PricePence` is now on both catalogue projections (`Program.cs`) and optional on the client
   `Pack`, so web and API stay deployable in either order; against an older API the beacon emits
   *nothing* rather than a view at an unknown price, because a denominator inflated by unknowns is
   worse than a smaller honest one.

   **Trap found, pre-existing and live in production:** the client `AnalyticsEventName` union and
   the server `AllowedNames` allowlist are two halves of one contract and had silently drifted.
   `pack_shared`, `basket_removed`, `matchmaker_answered`, `palette_search` and `copy_variant` were
   all being emitted from live call sites and all 400d server-side, counted nowhere. A dropped
   beacon is indistinguishable from a visitor who never acted, so the bug read as "nobody uses this
   feature". All five are now allowlisted, and the drift is pinned from both sides.

   *Verified:* `503 passed` (43 files, `npx vitest run`), `tsc --noEmit` clean,
   `Passed! - Failed: 0, Passed: 257` (Store.Tests, +8 new). The contract test was proven
   non-vacuous by deleting `"pack_shared"` from the allowlist and confirming it fails with
   `expected [ 'pack_shared' ] to deeply equal []`, then restoring. The seven storefront event
   names are additionally proven by behaviour (`POST /events` → 202 and a counter delta), not by
   grepping the allowlist — a grep would still pass if the beacon 400d for some other reason.
2. **C3** (`price_comparables`) — starts producing cited anchors immediately; every batch that runs
   without it is a batch whose anchor evidence is lost.
   **DONE 2026-08-05** — `prospector/price_comparables.py`, `prompts/price_comparables.md`,
   `tests/test_price_comparables.py` (32 tests). Shipped `enabled: true` (retrieve) with
   `rung_adjust_enabled: false` (act) as two separate config keys, so landing it moves no price.
   Barred from the kill path in code (`kill_filter.is_hard_fail` returns `False` for
   `models.PRICING_CHECK`) and from `run_order` in `verify.py`, not by config omission — `hard_gates`
   is data, and a data edit passes through neither code review nor the test suite.
3. **C1** (backfill) — only after D1 is green, since the ladder is what decides each pack's rung.
   **DONE 2026-08-05 22:07Z** — `scripts/backfill_ladder_prices.py --apply`. 13 of 61 packs moved
   (5 cuts side_hustle/uk 4900→2900; 8 rises to 7900/9900/14900/19900), 48 held at 4900 because
   their dossier tier is unclassified, 0 packs without a dossier. Each pack: mint the Stripe Price
   first (an orphaned Price is inert; a catalogue row pointing at a nonexistent price is a listed
   pack that cannot take money), then PATCH, then **read back from `/catalog`** — abort the run on
   the first mismatch. All 13 read back correct. The drain behaved as designed: cuts took
   `floor = new price` immediately, rises held `floor = 4900` until `2026-08-07T00:07Z`. Every pack
   was `IsListed` (that is what `/catalog` filters on, `Program.cs:245`), so the endpoint ran
   `CanBillPriceAsync` against prod Stripe on each new price id before committing
   (`Program.cs:847-865`). Post-state: re-running the planner reports `move: 0  hold: 61`.
4. **C2** (`bridge.py` repoint) — after C1, so new packs and existing packs converge on one source.
   **DONE 2026-08-05** — one `PriceDecision` now feeds both the Stripe mint (`amount_pence`) and the
   catalogue row (`pricePence`); `_update_catalog`'s `price_pence` is a **required** parameter so no
   caller can reintroduce a second source of truth. Guarded by
   `tests/unit/test_bridge_pricing.py::test_the_minted_price_and_the_catalogue_row_are_the_same_number`.
   A no-op on today's catalogue: every live pack carries `ambition_tier=""`, so all 61 still publish
   at 4900 until lanes start tagging candidates (asserted, not assumed).
5. **D3**, then **D4**, then **D5**.

The L3 gated controller from the analysis spec (§5) is explicitly *not* in this plan. It consumes
D2's events and D4's simulator, neither of which has produced anything yet, and building a
controller before its inputs exist is the failure mode the analysis argues against.

---

## 5. Branch hygiene

Current branch is `fix/ui-production-readiness` and carries unrelated uncommitted work from another
agent (`git status` at session start: modified `store_platform/src/Store.Web/**`, `store/**`,
`checkpoints/**`). The L0 changes must be staged **selectively** onto their own branch — never a
wholesale copy, which has clobbered commits here before (`worktree-copy-clobbers-commits` memory).

`main` requires signed commits (a ruleset, not legacy protection), so unsigned local commits land
only via `gh pr merge --squash --admin`. Run `git commit` backgrounded: the POPDD gate exceeds
foreground timeouts under daemon contention (`tests-compete-with-live-daemon-for-cli-slots`).

Files belonging to L0, to stage:

```
store_platform/src/Store.Catalog/Domain/Pack.cs
store_platform/src/Store.Catalog/Domain/PackPriceHistory.cs
store_platform/src/Store.Catalog/Persistence/StoreDbContext.cs
store_platform/src/Store.Catalog/Migrations/20260805201134_AddPackPriceFloorAndHistory.cs
store_platform/src/Store.Catalog/Migrations/*ModelSnapshot.cs
store_platform/src/Store.Api/Program.cs
store_platform/src/Store.Api/Services/FulfilmentService.cs
store_platform/src/Store.Api/Contracts/PricePatchRequest.cs
store_platform/src/Store.Tests/Domain/PackPriceFloorTests.cs
store_platform/src/Store.Tests/Endpoints/PricePatchTests.cs
specs/dynamic-pricing-system-2026-08-05.md
specs/pricing-build-plan-2026-08-05.md
```

---

## 6. What this plan does not prove

- **That the ladder's rungs are the right numbers.** D1 makes the ladder *correct and testable*;
  it does not make it *right*. The rungs are a starting hypothesis until C3's comparables and D2's
  events say otherwise. The analysis spec §8 says the same and it has not changed.
- **That MiniMax can execute D1–D4 to this bar.** Untested here. The acceptance tests are the
  control: if a delegated unit cannot pass its golden test, it comes back to Claude rather than
  being patched up in review. Dispatch D1 first as the cheapest read on that question — it is the
  most tightly specified unit and the fastest to reject.
