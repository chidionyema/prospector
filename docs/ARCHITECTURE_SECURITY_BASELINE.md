# Architecture and security baseline

Status: **BASELINE TAKEN 2026-08-18. RE-MEASURE MONTHLY.**
Every number here has the command that produced it on the same line. Nothing in this document is
an opinion about the code; it is what the code measures right now.

Founder, 2026-08-18: *"no architectural review, parts of the engine is a pile of mud. in fact
perhaps you can conduct a review, architecture and security audit and get baseline"*, and
separately *"as a founder i am concerned and need reassurance"*.

Reassurance in this estate is a number with a command behind it. Part 2 is the honest answer on
the critical paths, and it is better than expected. Part 4 is the mud, and it is real.

Rules this document serves: `docs/WAYS_OF_WORKING.md` W28, W29, W30.
Policy this document serves: `docs/PLATFORM_MANIFESTO.md` L6, L9, L10.

---

## Part 1. What the system is

Four moving parts and exactly one piece of state.

| Part | What it does | Where it runs |
|---|---|---|
| Engine (`prospector/`) | generates candidates, verifies them against cited sources, kills or passes, renders packs | Fly, one instance |
| Store API (`store_platform/src/Store.Api`) | catalogue, checkout, webhook, entitlement, delivery | Fly |
| Store Web (`store_platform/src/Store.Web`) | the storefront a buyer reads | Fly |
| Ops Console (`store_platform/src/Ops.Console`) | the operator's buttons | Fly |
| Store (`store/`) | the only state: catalogue, ledger, dossiers, scheduler files | one directory, pinned by `PROSPECTOR_STORE_DIR` |

The rule that keeps it portable: one container image, six platform requirements, nothing else
(`docs/PLATFORM_MANIFESTO.md` L2, `deploy/PORTABILITY.md`).

---

## Part 2. Critical path test coverage

The founder's question, answered link by link: *"do we have critical path tests? purchase,
payment, download pack, receive email, test stripe? and also engine, do we have critical tests?"*

**The short answer: yes, every link has a test. The gap is not coverage, it is that nothing runs
the whole chain against a real Stripe test account on a schedule.**

### The money path

| Link | Covered by | Real? |
|---|---|---|
| Price is legal to charge | `Payments/BillablePriceGateTests.cs`, `Domain/PackPriceFloorTests.cs` | yes |
| Price the rail charges equals the catalogue price | `Payments/MoneyRailConfigGateTests.cs`, `tests/unit/test_bridge_pricing.py` | yes |
| Basket and checkout rules | `Payments/BasketCheckoutRulesTests.cs`, `Payments/StripeBasketTests.cs` | yes |
| Stripe provider behaviour | `Payments/StripeProviderTests.cs`, `Payments/ProviderParityTests.cs` | in-process, `FakePaymentProvider` |
| Embedded checkout | `Endpoints/EmbeddedCheckoutTests.cs` | yes |
| Webhook to order | `Endpoints/OrderBySessionTests.cs` | yes |
| Entitlement written exactly once | `Infrastructure/IdempotencyFilterTests.cs`, `Fulfilment/DeliveryOutboxTests.cs` | yes |
| Fulfilment | `Fulfilment/FulfilmentServiceTests.cs` | yes |
| Download URL and its token | `Services/DeliveryUrlsTests.cs`, `Services/TokenGeneratorTests.cs` | yes |
| The email actually sent | `Services/MailjetEmailSenderTests.cs` | in-process |
| Resending a lost delivery | `Endpoints/OpsResendTests.cs` | yes |
| Only sellable packs are listed | `Endpoints/PublishListingGateTests.cs`, `Endpoints/HiddenFromCatalogueTests.cs` | yes |

Counted: **41 C# test files** (`find store_platform/src/Store.Tests -name '*.cs' | wc -l`), 14 of
which mention webhooks and 15 entitlements.

### The engine path

| Link | Covered by |
|---|---|
| A verdict is grounded in fetched sources | `tests/` verify and moat suites, 7 files matching `moat` |
| A failed call defers rather than kills | `tests/` drain suites, 5 files matching `drain` |
| Only a PASS publishes | 12 files matching `publish` |
| Provisional providers never finalise | the `is_provisional_provider` suites |
| Price becomes a rung, not a number | 7 files matching `price` |
| Catalogue row and rail price cannot drift | 7 files matching `bridge` |
| Duplicates do not reach the catalogue | 2 files matching `dedup` |

Counted: **386 Python test files** (`find tests -name 'test_*.py' | wc -l`).

### What already runs against production

`.github/workflows/e2e-live-smoke.yml` runs Playwright against the live site after every Store.Web
deploy **and daily at 07:00 UTC**. Its own comment says why the schedule matters: *"this storefront
breaks without anyone committing"* — the two unbuyable packs found on 2026-07-31 were a data fault
with no commit behind them. It asserts the home page lists at least one pack, which exercises the
live Store.Api catalogue and the Stripe-backed listing state.

Four spec files back it: `discovery.spec.ts`, `storefront.spec.ts`, `kill-log.spec.ts`,
`seo.spec.ts`.

### The honest gap

**The live drill stops at the shelf.** It proves a buyer can see a pack. It does not prove a buyer
can buy one. Nothing scheduled takes a Stripe test card through checkout, waits for the webhook to
write the entitlement, receives the email and follows the download link to real bytes.

Everything after "add to basket" is covered in-process only, against `FakePaymentProvider` and a
fake mail sender. That is the right default for speed and determinism, but it means the six links
where money actually moves are proven about the code rather than about production.

Extending the existing workflow past the shelf is the single highest-value missing test in the
estate. It costs nothing: Stripe test mode is free and the runners are self-hosted. It is an
extension of a workflow that already exists, not a new one — which is W6 applied to this document
itself, because the first draft of this paragraph claimed no live drill existed at all.

---

## Part 3. Security posture

| Question | Measured answer | Command |
|---|---|---|
| Is any live key committed? | No. Every `sk_live_` hit is a placeholder or documentation. | `rg -n "sk_live\|AKIA[0-9A-Z]{16}"` |
| How are secrets declared? | One list, 11 entries, one push mechanism | `deploy/secrets.required`, `t_secrets` |
| Is the declaration checked before boot? | Yes | `bash deploy/secrets.sh check` |
| How many API endpoints? | 53 | `rg -o 'Map(Get\|Post\|Put\|Delete)' store_platform/src/Store.Api/ \| wc -l` |
| How many carry an explicit auth guard? | 12 | `rg -o 'RequireAuthorization\|RequireInternalKey\|X-Api-Key' store_platform/src/Store.Api/` |
| Does a CI runner hold money keys? | No, by design: only `GITHUB_RUNNER_PAT` and `RUNNER_LABELS` | the runner app's secret list |
| Is authorisation tested? | 10 test files assert 401/403 or unauthorised paths | `rg -l -i "unauthori\|401\|403" store_platform/src/Store.Tests/` |

### Open findings

1. **Two secrets need rotating.** `PROSPECTOR_ENTITLEMENTS_API_KEY` and `STORE_INTERNAL_API_KEY`
   were printed into a session transcript on 2026-08-18. Manifesto L9 is not enforced until they
   are rotated. This is the oldest outstanding item in this document.
2. **HYPOTHESIS: 41 of 53 endpoints are unguarded, and most of them should be.** The catalogue,
   the storefront reads, the checkout start and the Stripe webhook are public by design; the
   webhook authenticates by signature rather than by a guard attribute, so it will not appear in
   the count above. The check that settles it: enumerate all 53 with their guard and mark each
   public-by-design or a finding. Until that runs, the 12 is a floor, not a verdict.
3. **`ops.mumchimp.com` has no DNS record**, so the console is reachable only by its Fly hostname.

---

## Part 4. Where the mud is

Founder: *"parts of the engine is a pile of mud"*. Correct, and here it is as a number rather
than a feeling.

### The largest modules

```
4470  prospector/run.py
2916  prospector/scheduler/run_scheduled.py
2906  prospector/ops/console_api.py
2511  prospector/retrieval.py
2477  prospector/bridge.py
2147  prospector/pack_linter.py
1845  prospector/operator.py
```

### The largest functions

**66 functions in `prospector/` are over 100 lines long.** The worst ten:

```
873  prospector/bridge.py:683    publish_pass
660  prospector/generate.py:316  generate
638  prospector/run.py:1494      run_signal
526  prospector/run.py:2687      _cmd_resume
462  prospector/bridge.py:1698   _create_bundle
337  prospector/dossier.py:738   render_markdown
335  prospector/run.py:4131      main
266  prospector/run.py:1219      vet_candidate
258  prospector/golden.py:116    run_golden_set
252  prospector/verify.py:1017   _verify_inner
```

An 873-line function on the money path is the finding. `publish_pass` is where a PASS becomes a
listing, a price and a Stripe product. It is the least testable code in the estate and it sits on
the most expensive path in the business.

### What the coupling says

Fan-in, counted by imports across `prospector/`, `tests/`, `tools/` and `scripts/`:

```
config   166      models 159      operator 79      store 41      run 35      verify 31
```

`config` and `models` being the most imported is correct: they are the contracts, and a contract
should be depended on. `run.py` at 35 is the problem — it is an entry point that 35 other things
reach into, which is what makes it 4470 lines.

### The ranking, by what it costs

1. `bridge.publish_pass`, 873 lines, on the money path. Highest risk in the repo.
2. `run.py`, 4470 lines, entry point and library at the same time.
3. 219 of 1567 tracked files referenced by nothing (`scripts/estate_census.py`). Not risk, drag.
4. `retrieval.py` and `operator.py`, both fine in shape, large because they carry many adapters.

**Nothing here is being refactored on the strength of this document.** Mud is only worth moving
where it costs something measurable, and the measurement now exists so that argument can be had
with numbers.

---

## Part 5. What to do, cheapest first

1. **Rotate the two leaked secrets.** Minutes. Closes the only real security finding.
2. **Extend the daily live smoke past the shelf**: buy a pack in Stripe test mode, assert the
   webhook, the entitlement, the email and the download bytes. Free, and it extends
   `.github/workflows/e2e-live-smoke.yml` rather than adding a workflow.
3. **Enumerate the 53 endpoints against their guards.** One script, read-only. Turns finding 2
   from a hypothesis into a verdict.
4. **Carve `publish_pass` into named steps.** Only after 1 to 3, and only with the money tests
   green before and after.
5. **Delete on evidence** from the census, in a second pass, never automatically.

---

## Part 6. Ledger

| Date | Change | Receipt |
|---|---|---|
| 2026-08-18 | Baseline taken: architecture, critical path coverage, security posture | this file |
| | Two secrets rotated | **outstanding** |
| | Live drill extended past the shelf to the money | **not built**; the shelf half runs daily |
| | Endpoint and guard enumeration | **not built** |

Re-measure with the commands in each section. When a number here disagrees with the tree, the
tree is right and this file is stale: fix it in the same turn you notice.
