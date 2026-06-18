# Prospector Pipeline — Deep Review (2026-06-18)

> Full-engine review after substantial pipeline change. Method: 7 parallel subsystem
> reviews over ~11.2k LOC Python (`prospector/`) + the .NET money-rail (`store_platform/`),
> with the founder-fence findings (money + moat) independently re-verified by hand.
> Each finding is tagged **[VERIFIED]** (re-read by reviewer) or **[REPORTED]** (subagent
> finding, file:line given, not independently re-read).

---

## 1. Reflection — where the engine actually is

The engine has grown well past the original eight-step spec into a **two-lane, self-healing,
resumable** pipeline:

- **Two independent model lanes.** The *moat* (Claude→Gemini) runs verify/adversarial; a
  *non-critical* chain (intended DeepSeek→MiniMax→Gemini-flash) runs generation/prescreen/score.
  The doctrine that these never cross is the spine of the whole design.
- **Resilience is real and tested.** Circuit breakers (`breaker.py`), cross-run health marks
  (`health.py`), `ProviderExhaustedError`→DEFER→`vet --resume`, and pending-signal persistence
  →`generate --resume` are implemented and have dedicated tests (`test_failover.py`,
  `test_defer_on_retrieval_failure.py`, `test_fast_fail_exhaustion.py`).
- **The moat is genuinely grounded.** Source-or-die is enforced in code at three points:
  no-passages→`unverifiable` (verify.py:231, 362), `supported`-with-no-citations→`unverifiable`
  (verify.py:277‑280), and dead-URL dropping (retrieval.py:458). Confidence is computed
  deterministically from citation fraction/diversity/relevance, not self-reported.
- **A real money-rail exists end-to-end.** bridge→Stripe provisioning→checkout→signed
  webhook→idempotent fulfilment→active-gated download→magic-link email→content-addressed R2.

**Overall health:** the *architecture* is sound and the *doctrine is mostly enforced in code*.
What's missing for launch is **(a) two correctness bugs on the money + moat rails**, **(b) a
cluster of "recorded-but-not-implemented" decisions**, and **(c) real end-to-end + ops coverage.**
Engineering is ~90% there; the last 10% is the part that takes money safely and rules correctly.

### What changed since the original spec
- Added `discover` (self-sourced signal portfolio), multi-lane generation (`generate_multilane`),
  adaptive creativity (`adaptive.py`), calibration diagnostics (`diagnostics.py`), decay/re-vet
  (`decay.py`), the control-center UI, and the entire `store_platform` money-rail.
- `run.py` absorbed all of this and is now a **1,625-line file with a 345-line `run_signal()`
  god-function** — the single biggest maintainability liability.

---

## 2. Architecture as-built

```
SIGNAL ─► [1 GENERATE]──► [2 DEDUP]──► [3 PRESCREEN]──► [4 VERIFY (moat, kill-fast)]
            non-critical    difflib      regex+LLM         query_gen→fetch→verdict→adversarial
            chain           0.85         (keep-biased)      Claude→Gemini ; exa→brave→gemini_cli→claude_cli
                                                                   │
                                                          [5 GATE] KILL│PASS│DEFER
                                                                   │ (PASS only)
                                          [6 SCORE+ARTIFACTS+claim-check]──►[7 PUBLISH]──►[8 STORE]
                                                                                   │
                                          bridge.py ─► Stripe provision ─► R2 upload ─► catalog POST
                                                                                   │
   BUYER ─► checkout ─► signed webhook ─► idempotent fulfilment ─► entitlement ─► /download/{token} + email
```

- **State:** dossiers as `store/dossiers/<id>.<decision>.json` (atomic write+rename) + a 15-col
  SQLite index (`store/prospector.db`) + append-only JSONL telemetry. DEFERs persist as provisional
  dossiers; exhausted signals persist to `signals/pending/<sha1>.json`.
- **Config:** `config.yaml` → `Config` dataclass, resolved lane→profile→persona. The promise is
  "deterministic on config, no code change to swap operators."

---

## 3. Findings register (prioritized)

### P0 — blocks correct launch

| ID | Finding | Where | Status |
|----|---------|-------|--------|
| **P0-1** | **Stripe checkout sets no `pack_id` metadata** → webhook `ExtractItems` reads `session.Metadata["pack_id"]`, always absent → zero entitlements granted → **every Stripe payment is paid-but-unfulfilled.** Only bites if Stripe is the active rail (Paddle is the dev default). | `StripeProvider.cs:109‑128` (no `Metadata`) vs `:73` (reads it) | **[VERIFIED]** |
| **P0-2** | **`confidence_floor` is orphaned.** Declared in `config.yaml` 6× and `config.py:61`, read by **no** kill logic. `kill_filter.py` docstring *claims* "low confidence never kills," but `is_hard_fail` (line 32) kills on verdict value alone — a thinly-cited `refuted` (conf 0.05) still kills. This is the exact **value_durability over-restriction wall** the memory recorded a fix for; the fix was never implemented. | `kill_filter.py:18‑32` | **[VERIFIED]** |

### P1 — money-safety & moat integrity

| ID | Finding | Where | Status |
|----|---------|-------|--------|
| **P1-1** | No **refund/dispute webhook handler**. `charge.refunded` / `charge.dispute.created` are never handled; `EntitlementStatus.Revoked` / `OrderStatus.Refunded` exist but nothing flips them. A buyer who refunds or wins a dispute keeps Active download access. | `StripeProvider.cs:35‑38` | [REPORTED] |
| **P1-2** | **.NET StripeProvider missing idempotency keys** on Product/Price create (the Python bridge has them). Network retry duplicates Stripe objects. | `StripeProvider.cs:84‑103` | [REPORTED] |
| **P1-3** | **Non-critical chain shares the moat's health file and includes Gemini.** `gen_op`/`fast_op` are built from `(gemini, deepseek, gemini_cli)` and there is a single process-wide `provider_health.json`. Non-critical batch load can mark Gemini dead → starves the moat of its primary brain, violating the "completely independent health file" doctrine in CLAUDE.md. | `run.py:416‑425`, `health.py:107‑119` | [REPORTED] |
| **P1-4** | **Committed weak dev internal key** `dev-test-key-change-in-production`; no startup guard rejects it outside Development. | `appsettings.Development.json:9` | [REPORTED] |
| **P1-5** | **`synthesized://` source path** — when an LLM-search provider returns no real URLs it emits a Source whose URL is `synthesized://provider/knowledge`; this counts as a "valid" citation. **Not active in the default moat chain** (`[exa, brave, gemini_cli, claude_cli]`), so latent — but opens the moment `deepseek`/`minimax_search` is added to `retrieval.provider`. Also verify `claude_cli`/`gemini_cli` grounding returns real URLs, not synthesis. | `retrieval.py:470‑478`, gated by `config.yaml:46` | **[VERIFIED latent]** |
| **P1-6** | **Adversarial decisive kills require no citations.** `verify.py:409‑412` accepts `decisive=True` without asserting `adv.citations` is non-empty — a kill with no cited evidence can fire, contradicting source-or-die. | `verify.py:409‑412` | [REPORTED] |
| **P1-7** | **No rate limiting / no per-token download cap.** Webhook endpoint and `/download/{token}` are unthrottled; `DownloadCount` is tracked but never enforced — a forwarded link = permanent access. | `Program.cs` (no `UseRateLimiter`), `DeliveryEndpoints.cs:122` | [REPORTED] |

### P1 — quality / correctness (engine)

| ID | Finding | Where | Status |
|----|---------|-------|--------|
| **P1-8** | **Prescreen regex matches `hypothesis` prose.** `_FORBID_PATTERNS` (bare words like `marketplace`, `regulator`) is run over `title+one_liner+hypothesis`, so an idea is killed for *describing* the pain it solves. Violates "constraint never kills at generation." | `prescreen.py:55, 127‑129` | [REPORTED] |
| **P1-9** | **Score failure is silent.** Any LLM exception zeros all six axes → `composite=0.0` → silently dropped; an infra hiccup is indistinguishable from a genuinely weak idea. No `score_failed` flag. | `score.py:41‑43` | [REPORTED] |
| **P1-10** | **Shadow-moat / board personas run full `verify()` sequentially and blocking** — a `--board` run = ~4× moat token cost per candidate with no cost guard. | `run.py:207‑232` | [REPORTED] |
| **P1-11** | **`gen_op`/`fast_op` order disagrees with RUN.md** ("DeepSeek→MiniMax→Gemini-flash"): MiniMax is in the docstring but absent from the actual chain → unreachable tier. | `run.py:416‑425` | [REPORTED] |

### P2 — config purity, contracts, hygiene

| ID | Finding | Where | Status |
|----|---------|-------|--------|
| **P2-1** | **Hardcoded £30 price** (`amount_pence=3000`) bypasses `config.yaml listing.price_pence` — a price change in config does nothing. | `bridge.py:173, 343` | [REPORTED] |
| **P2-2** | `report.py` imports `PRICING` directly instead of `get_price(cfg)` → config price overrides don't reach spend reports. | `report.py:363, 715` | [REPORTED] |
| **P2-3** | `retrieval_failed`/`degraded` are read by the metrics report but are **not SQLite columns** → grounding-health section is permanently zero. | `store.py:20‑37` vs `report.py:127‑128` | [REPORTED] |
| **P2-4** | Dual-store atomicity gap: JSON `os.rename` and SQLite upsert aren't one transaction → crash between them orphans a dossier with no index row, no recovery path. | `store.py:114‑148` | [REPORTED] |
| **P2-5** | `api.py` honors `Bearer test-token` for blanket entitlement with no env gate — stub left live. | `api.py:31` | [REPORTED] |
| **P2-6** | Dedup threshold `0.85`, confidence sub-weights, `dense_reward` constants, adaptive magic numbers — all hardcoded despite the "params in config" directive. | `dedup.py:34`, `verify.py:85‑87`, `models.py:257‑258`, `adaptive.py:54‑65` | [REPORTED] |
| **P2-7** | `_save_pending_signal` swallows write failures (logs+continues) → silent signal loss; `signals/pending/` is unbounded/never aged. | `run.py:93‑98, 105‑112` | [REPORTED] |
| **P2-8** | `DiskCache` has no TTL — stale evidence served forever can kill a candidate on outdated pages. | `retrieval.py:885` | [REPORTED] |

### Self-debug loop — recorded directive NOT closed

The memory directive "detect over-restriction from historic data and self-**correct**, not just
warn" is **half-built**: `diagnostics.calibration_alarms()` detects zero-yield / gate-dominance /
dead-gate pathologies and `adaptive.py` adjusts *generation* creativity — but **nothing writes a
corrective delta back to gate thresholds or `confidence_floor`.** The loop warns; it does not
close. [REPORTED — `diagnostics.py`, `adaptive.py`]

---

## 4. Legal / compliance gaps (non-code, launch-blocking)

- **ToS/Privacy describe the wrong product** — the shells are "Intro Exchange" copy (connectors,
  introductions, escrow), none of which applies to digital-pack sales. `terms.tsx`, `privacy.tsx`. [REPORTED]
- **No "not financial/investment advice" disclaimer** anywhere — required for AI-generated business analysis.
- **No standalone refund policy** (refunds only mentioned inline in ToS §5).
- **No-warranty clause** for AI content quality is absent.

---

## 5. Test reality

- **Core engine logic is green** (kill_filter, failover, breaker, DEFER, moat-discipline,
  two-loops-never-merge invariants). .NET money-rail: **40/40**.
- **In this local env: 259 passed / 10 failed** — the 10 are *environment* gaps, not logic:
  4× `stripe` SDK not installed, 6× `streamlit`/`tomllib` (py<3.11). (CI on 3.14 with deps =
  prior 361-pass run.)
- **CI hole:** `tests/control_center/` is collection-broken (missing `streamlit`) and **not** in
  the CI `--ignore` list → a fresh `uv sync` without streamlit fails the whole Python job *before*
  the golden-set gate runs. `ci.yml:43`. [REPORTED]
- **Biggest untested surfaces:** `vet --resume` round-trip (zero tests), `generate --resume`
  write+pickup, full signal→PASS→publish→buy→download→refund e2e, `dedup.py` (no unit suite).
- **Golden-set blind spot (by design):** the regression gate uses a `MockOperator` router and
  **never exercises the live `verify.py`/`prompts.py` render path** — prompt-template corruption is
  invisible to it. `must_surface` is informational, not gating, so a right-decision/wrong-reason
  kill still scores 100%.

---

## 6. Recommended remediation sequence

**Gate A — correctness on the two rails (do first, small diffs):**
1. P0-1: add `Metadata["pack_id"]` to the Stripe checkout session (+ a test asserting the webhook fulfils). *Skip only if launching Paddle-only — then add a guard test that the chosen rail round-trips.*
2. P0-2: decide the `confidence_floor` question and implement it — either wire it into `is_hard_fail` (kill only when `refuted` AND `confidence ≥ floor`) or delete the misleading docstring. This is the value_durability wall; it WILL recur otherwise.
3. P1-6: require non-empty citations for an adversarial decisive kill.

**Gate B — money-safety before taking real money:**
4. P1-1 refund/dispute webhook → revoke entitlement; P1-2 .NET idempotency keys; P1-4 kill the committed dev key + startup guard; P1-7 rate-limit + download cap.
5. Legal: rewrite ToS/Privacy for pack sales, add refund policy + "not financial advice" disclaimer.

**Gate C — moat/lane hygiene:**
6. P1-3 give the non-critical chain its own `provider_health_noncritical.json` and drop Gemini from `gen_op`/`fast_op`; P1-11 fix the chain order or RUN.md.
7. P1-5: assert `retrieval.provider` never includes synthesizing LLM-search providers (or strip `synthesized://` before verdict).

**Gate D — confidence to ship:**
8. CI: `--ignore` control_center (or add streamlit) so the golden gate actually runs; add `stripe` to test deps.
9. Write the `vet --resume` and signal→PASS→publish→download→refund e2e tests.
10. Close the self-debug loop (diagnostics → corrective config delta) — or explicitly downgrade the directive to "warn-only" so it stops reading as built.

**Gate E — debt (non-blocking):** split `run_signal()` into a pipeline; lift hardcoded params
(P2-1/2/6) into config; add DiskCache TTL; fix dual-store atomicity + orphan recovery.

---

## 7. Single most important takeaway

The engine is **architecturally ready and doctrinally honest in code** — but two small, specific
defects sit on the two rails that matter most: **one Stripe payment never fulfils (P0-1)** and
**the moat's over-restriction guard was designed, documented, and never wired up (P0-2).** Both
are <20-line fixes. Neither is caught by the current test suite. Fix those two, add the refund
handler and the e2e test, and the "are we ready for launch" answer flips from *no* to *yes, pending
the legal copy and a payment-provider decision.*
