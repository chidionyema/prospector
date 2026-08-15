# Ops Console Programme — design, safety model and story backlog

**Owner:** founder · **Author:** Claude (Opus 5) · **Opened:** 2026-08-14 · **Rev 3, same day**
**Status:** design only. No code in this change.

**Founder decisions, 2026-08-14:**
1. *"Keep it on Telegram."* — Telegram is the door. No `/admin` on mumchimp.com, no tunnel, no
   inbound port to the laptop.
2. *"We have the Streamlit."* — the pixel problem is already solved. `prospector/control_center/`
   is the workbench for anything that needs a table, a chart, a timeline or a diff.
3. *"The whole Telegram is a complete mess, nothing works, the UI is cryptic and confusing… we need
   both Streamlit and the currently useless cockpit."* — **both surfaces are first-class and both
   need remediation before any new feature lands.** See §1.1: the R1–R8 "CLOSED" grades are
   **disputed by use** and do not survive this.

Rev 1 proposed three faces and a phone-hosted `/admin`; rev 2 proposed reviving the Telegram Mini
App. **Both are dead.** Two surfaces already exist and are running — this programme builds the
spine that makes them one system, and fills what neither covers.

**Scope:** Catalogue administration · Engine operation · Customers/support/growth · **every
backfill and repair tool** · **full engine transparency**. Money *reporting* stays deferred (§10);
money-rail *actuators* are in scope, fenced.

> **Status rows live in `docs/TELEGRAM_OPERATOR_PROGRAM.md`**, which already tracks R1–R8 for this
> surface. The requirements below continue its numbering as **R9–R13** so the estate keeps one
> ledger, not two. Append receipts there.

---

## 1. What is already true (verified this session)

**Two surfaces exist, both running, both mature.**

**Telegram — the door.** `docs/TELEGRAM_OPERATOR_PROGRAM.md` (471 lines) records R1 Monitor
**DONE**, R2 Tune/set params in real time **LIVE**, R3 Administer **DONE**, R4 Node priority per
pipeline step + fallbacks **LIVE** (22 tests), R5 Extreme visibility **CLOSED**, R7 Every screen
state-of-the-art **CLOSED**, R8 Estate-wide deploy view **LIVE**. ~45 panel modules under
`~/.hermes/hermes-agent/gateway/operator_shell/`; suite figures recorded there: **797–907 passed**.
`launchctl` shows `ai.hermes.gateway` live at pid 59053.

**Streamlit — the workbench.** `prospector/control_center/` — 2,658 lines, 7 pages (`Overview,
Catalogue, Launch, Diagnostics, Parameters, Reports, Resume`), 12 test files, its own design tokens
(`theme.py`), a real job runner and a validated config writer. Running now as pid 1726:
`streamlit run .../control_center/app.py --server.port 8601 --server.address 127.0.0.1`.

**The Telegram surface already learned the dead-button lesson the hard way.** R7 closed with
`test_every_button_dispatches.py:104 _UNBUILT = {}` and `test_destination_vocabulary.py:75
BASELINE = 0` — 34 hand-written button sites audited, 15 quarantined actions built/repointed/
deleted, *"nothing was wired to a stub."* **Any design that adds controls must feed those two
ratchets or it regresses a closed requirement.**

**The gateway serves the code it started with.** Every change below is inert until
`ai.hermes.gateway` restarts.

**One thing to clean up, not build.** `~/.hermes/mini-app/index.html` (440 lines) and
`~/.hermes/scripts/mini_app_server.py` (395 lines) exist but are unreachable: `rg
'web_app|WebAppInfo|startapp'` over the gateway returns **zero hits**, no process runs them, no
launchd job exists — and `mini_app_server.py:12` binds **`localhost:8801`**, the exact port
`~/.hermes/ESTATE_STATE.md` lists as the retired cockpit (*"do not revive without an explicit
dual-door decision"*). With Streamlit as the workbench, the Mini App has no job. **It gets archived
(§9 Tier 3), not revived** — leaving it as-is is the estate's own
`built-and-unreachable-is-the-cockpit-defect-class`, still squatting on a retired port.

---

## 1.1 The status is disputed, and the founder wins

The ledger says R1–R8 **DONE / LIVE / CLOSED** with 797–907 passing tests. The founder, using it,
says *"nothing works, the UI is cryptic and confusing."* **Both statements are true, and that is
the finding.** They were measuring different things:

- `test_every_button_dispatches.py` **says of itself**: *"It is static. It proves an action reaches
  a branch, not that the branch works."*
- `test_destination_vocabulary.py` counts *label* violations against a baseline of 0 — it proves no
  new cryptic word was added, never that the existing vocabulary means anything to a human.
- R7's own closing note records the right instinct and stops one step short: *"a card that says
  'would restart' while restarting is exactly the defect."* That is a correctness test wearing a UX
  costume. It cannot catch *"I do not know which of these 45 panels does the thing I came for."*

So the grades are real measurements of the **wrong property** (memory:
`measure-the-violation-not-the-property`), and a ledger row that reads CLOSED while the product is
unusable is `a-stale-assertion-fails-like-a-product-bug`. **Consequence for this programme:**

1. **R1–R8 are re-opened as 🟡 ROUTING-PROVEN, USE-UNPROVEN.** Not reverted to ❌ — the plumbing
   demonstrably exists and the tests are worth keeping. But no row returns to ✅ on a test alone.
2. **The grading instrument changes.** A requirement closes when the founder completes a named
   operator task **unaided, from the phone, without asking what a label means** — a task-completion
   record, not a green suite. The suite becomes the regression net beneath that, not the verdict.
3. **Remediation outranks features.** Tier −1 (§9) ships before Tier 0. Adding 40 registry-generated
   tools to a UI nobody can navigate multiplies the problem it is meant to solve.

**What I cannot tell you from here, and will not guess:** *which* screens are cryptic and *where*
the journeys break. I have read the ledger and the code layout; I have not used the bot. Diagnosing
this by reading source would be exactly the `never-judge-design-by-grepping-html` error in another
medium — **and it must be captured at render time anyway**, since a source scanner cannot see a
label built at render time (memory `a-source-scanner-cannot-see-a-label-built-at-render-time`).
That capture is U1–U3, done by a crawler, not by the founder. `~/.hermes/scripts/
telegram_ux_probe.py` + `telegram-ux-probe.sh` already exist and should be assessed as the harness
before writing a new one.

---

## 1.2 The foundation is weak — and the evidence says exactly where

Founder, 2026-08-14: *"the foundation is weak."* Agreed, and it is diagnosable rather than vague.

**The damning evidence is that the symptom tests already exist and already pass.** Verified on disk
in `~/.hermes/hermes-agent/tests/gateway/operator_shell/` (39 test files):

| Test on disk | The symptom it targets |
|---|---|
| `test_cockpit_ia.py` | information architecture |
| `test_no_screen_says_one_word_twice.py` | vocabulary repetition |
| `test_destination_vocabulary.py` (212 lines) | cryptic labels |
| `test_panel_chrome_spine.py` | consistent card chrome |
| `test_action_outcome_is_visible.py` | "I tapped it and nothing said anything" |
| `test_every_button_dispatches.py` (335) · `test_dead_buttons_now_work.py` (376) · `test_declared_buttons_are_wired.py` | dead buttons |

Five tests aimed squarely at "cryptic and confusing", all green, product still unusable. **That is
not a testing gap. It is a structural one**, and it kills the rev-3 assumption that remediation is
mostly a UX pass.

### The measurement — and the correction it forced

I first wrote that the fix was a new `Screen(...)` model, because a screen is *code, not data*.
**Measuring adoption before building it showed that was half wrong, and the true finding is
sharper and much cheaper to act on.**

`gateway/operator_shell/panel_chrome.py` (288 lines) **already is** most of that renderer:
`compose(header, groups, …) -> (text, rows)` generates the message body and the button grid
together in one order, and guarantees the invariant that makes a dense card readable — *every
legend line has buttons under it, and every button sits under a legend line.* `Group` labels the
blocks. `VERDICT_GLYPHS` is the one state vocabulary. `nav()` is the one spine.

Census over the 61 panel modules (`tests/gateway/operator_shell/test_spine_adoption.py`, run
2026-08-14):

| Spine piece | Adopted by | What it does |
|---|---|---|
| `nav()` / `with_nav()` | **39 / 61** | the navigation row — cosmetic, and adopted |
| `compose()` | **4 / 61** | ties the body to the grid — *the piece that creates coherence* |
| `Group()` | **3 / 61** | labelled blocks |
| `VERDICT_GLYPHS` | **1 / 61** | one meaning for 🟢🟡🔴⚠️ |
| raw 🟢/🔴/🟡 hardcoded | **33 / 61** | every panel inventing that vocabulary itself |

**The foundation was never missing. It was OPTIONAL** — and the three pieces that actually produce
one coherent product have 6%, 5% and 2% uptake, while the decorative one has 64%. That is the whole
diagnosis, and it also explains the five green symptom tests: they ratchet *violations* at zero
(`test_destination_vocabulary.py:75 BASELINE = 0`, `test_every_button_dispatches.py:104
_UNBUILT = {}`). **A ratchet stops decay; it cannot create coherence.** Nothing anywhere measured
whether the spine was being *used*.

The 33 hand-rolled glyph panels are not a style problem. `VERDICT_GLYPHS` has four slots and the
fourth is `unproven: ⚠️` — the one a hand-rolled panel always omits, so *"the probe could not run"*
renders as green. That is `estate-probe-green-fence-line-is-not-evidence` reproduced once per panel.

**So the fix is adoption, not a new abstraction:**

- **The adoption meter** — floors that only rise, a raw-glyph ceiling that only falls, failure
  output that names the next modules to migrate. This is the inverse of a violation ratchet: it
  fails when the migration *stops*, not only when someone regresses. **Shipped.**
- **Migrate panels onto `compose()`/`Group()`/`VERDICT_GLYPHS`**, raising the floor per commit.
- **One lexicon** (`panel_chrome.LABELS` + `label_for()`) so a screen cannot invent a word. Seeded;
  it is what `test_destination_vocabulary` should eventually read *instead of* a violation baseline.
- **Actions resolve against the §5 registry**, so a screen cannot offer a control that does not exist.

### The other half: there was no way back, at all

`nav_stack.py` — back/forward history and breadcrumbs — **was dead code from the day it was
written.** Its own docstring claimed *"the nav() function reads this stack and adds ← Back /
→ Forward buttons"*. It did not: `panel_chrome.py` contained zero references to it, and **no module
in the repo imported it.** So 63 panels had no way back, while a file describing the way back sat
beside them asserting it was wired. A docstring asserting its own integration is exactly the prose
that *"state is a probe, not a paragraph"* exists to forbid.

**Fixed and wired at one seam** — `estate.handle_estate_action`, the single funnel every tap passes
through — so all 63 panels gained ← and a breadcrumb without any of them being edited. Three real
defects were fixed in the process: the state path was resolved at *import* time (so the test suite
would have written the founder's live history on every run — memory
`tests-polluted-the-production-audit-log`), the write was non-atomic, and the error handling was a
bare `except:` that swallowed `KeyboardInterrupt`.

---

## 2. The gap — what neither surface covers today

R1–R8 gave monitoring, tuning, node routing, administration and estate visibility from the phone.
The Streamlit console gives dossier browsing, launching, config editing and reports at the desk.
Three things in the current ask are covered by **neither**:

1. **The tool catalogue.** ~40 operator tools — including **13 backfill/reprocess tools**, several
   of which mutate the **live Stripe rail** (`scripts/backfill_ladder_prices.py`,
   `tools/reprice_live_packs.py`, `tools/reprice_to_charm_rungs.py`) or **on-sale product content**
   (`tools/backfill_bundle_html.py`, `tools/backfill_pack_currency.py`) — exist only as memorised
   command lines. They are on neither surface, and the dangerous ones are indistinguishable from
   the safe ones. *(Inventory recon-reported — see §12.)*
2. **Causal transparency.** Both surfaces answer *what* the engine did. Neither answers *why this
   candidate died, on which provider, against which retrieved passage, at what cost.*
3. **Catalogue and customer administration.** Withdraw/restore a pack, re-price, retag facets, look
   up a buyer's entitlement, resend a magic link. The store API's `/internal/catalog/*` endpoints
   exist and are **curl-only**. *(Recon-reported.)*

And one structural gap behind all three: **the two surfaces share no code.** Everything added twice
drifts, and everything added once is missing from the other.

---

## 3. The division of labour

The split is by **what the answer looks like**, not by who is asking.

| The answer is… | Surface |
|---|---|
| a state, a verdict, a number, a yes/no, an alert | **Telegram card** |
| a verb you want to press, from anywhere | **Telegram inline keyboard** |
| a table, a chart, a timeline, a diff, a long list | **Streamlit** |

Stated as two rules:

- **Telegram is the operator.** Everything you *do* is doable from the phone, including the
  dangerous things, because that is where you are when something breaks.
- **Streamlit is the workbench.** Everything you *study* lives at the desk, because studying is a
  desk activity and a chat card is a bad table.

**The honest cost, recorded rather than glossed:** Streamlit binds `127.0.0.1`, so the deep views
are **laptop-only**. From the phone you get status, verbs and alerts — not the funnel, not the
lineage, not a 60-row shelf. That is accepted. The escape hatch if it ever bites is a paginated
chat card for the specific view that bit, decided then, not built now.

**A chat card that summarises a deep view ends with the exact desk command** — e.g.
`Funnel: 412→0 · biggest loss: grounding 71% · desk: Console ▸ Funnel ▸ lane=frontier`. The phone
tells you *what*, and tells you where to go for *why*.

---

## 4. Architecture — one spine, two renderers

```
   ┌─────────────────────────────┐        ┌──────────────────────────────┐
   │ TELEGRAM  (the door)        │        │ STREAMLIT  (the workbench)   │
   │ ai.hermes.gateway, launchd  │        │ :8601 localhost, running     │
   │ ~45 operator_shell panels   │        │ 7 pages + the new ones       │
   │                             │        │                              │
   │ status · verbs · alerts     │        │ tables · charts · timelines  │
   │ confirms · receipts         │        │ diffs · dossier browsing     │
   └──────────────┬──────────────┘        └───────────────┬──────────────┘
                  │                                       │
                  │        both import, neither owns      │
                  └───────────────┬───────────────────────┘
                                  ▼
                  ┌───────────────────────────────────────┐
                  │  prospector/ops/   — THE SPINE        │
                  │   registry.py   every actuator, once  │
                  │   readmodel.py  every read, once      │
                  │   storeclient.py /internal/* wrapper  │
                  │   intents.py    intent + receipt log  │
                  └───────────────┬───────────────────────┘
                                  ▼
                  ┌───────────────────────────────────────┐
                  │ control_center/readers.py   (33 fns)  │
                  │ control_center/runner.py    (jobs)    │
                  │ control_center/config_editor.py       │
                  │ store/*.db · store/*.jsonl · store-api│
                  └───────────────────────────────────────┘
```

**The spine is the whole point.** Today Telegram reads engine state through
`prospector/scheduler/status.py` while Streamlit reads it through
`control_center/readers.py` — two readers, one truth, and memory `one-reader-two-caller-shapes` is
what that costs. `prospector/ops/readmodel.py` becomes the single reader; both surfaces import it.

Nothing is rewritten: `readers.py` (33 public functions), `runner.py` (881 lines, jobs survive an
app restart, SIGTERM→grace→SIGKILL cancel) and `config_editor.py` (validate, backup, audit trail,
mtime conflict detection, moat-affecting certification reset) are **promoted, not replaced**.

### 4.1 Actuation path — one path, two entry points

`tap → intent {actuator_id, args, actor, nonce} → registry resolves it → runner.launch() →
receipt (exit code, diff summary, duration, cost) → rendered on the surface that asked`

- Intents are **idempotent by stored nonce** (`idempotency-keys-expire-they-are-not-dedup`).
- Every intent and receipt appends one line to `store/ops/intents.jsonl`, append-only, actor-stamped.
- **A run started on one surface is visible on the other.** The receipt log is shared, so a backfill
  launched from the phone is inspectable at the desk, and vice versa.

---

## 5. The Actuator Registry — the one new abstraction

One declaration per tool, in `prospector/ops/registry.py`. **The Telegram keyboard and the Streamlit
tool cards are both generated from it.** A control cannot exist without an entry; an entry cannot
exist without a real executable behind it.

```python
Actuator(
    id="backfill.facets",
    label="Backfill pack facets",
    group="Backfill & reprocess",
    argv=["python", "tools/backfill_facets.py"],
    args=[Arg("pack_id", "str", required=False, help="omit = all packs")],
    klass=MUTATES_PROD,            # READ_ONLY | MUTATES_STORE | MUTATES_PROD | DESTRUCTIVE
    needs=["STORE_INTERNAL_API_KEY"],
    dry_run_flag="--check-only",   # None requires an explicit written waiver
    preflight="scripts/verify_selling_catalogue.py --quiet",
    blast="Changes discovery metadata on live packs; conflicting facets can hide a pack.",
    receipt="listing_diff",
)
```

### 5.1 Why this is the centre

R7 closed by auditing 34 **hand-written** button sites and emptying a 15-entry quarantine.
Hand-writing is what made that audit necessary. A registry makes the next ~40 controls generated,
and makes `_UNBUILT` unable to refill: a control exists **iff** an entry exists, and
`tests/ops/test_registry.py` asserts every entry resolves to a real file with real flags. It also
guarantees the two surfaces offer the *same* tools with the *same* fences — which no amount of
discipline achieves across two hand-written UIs.

### 5.2 The catalogue it must cover *(recon-reported; verify at build)*

**Backfill & reprocess — 13.** `scripts/backfill_ladder_prices.py` (MUTATES_PROD, Stripe) ·
`scripts/backfill_tiers.py` (MUTATES_STORE) · `tools/backfill_audience.py` (MUTATES_STORE) ·
`tools/backfill_market.py` (**DESTRUCTIVE until it grows a rehearsal — no recovery path but the
restore drill**) · `tools/backfill_listing_copy.py` (MUTATES_PROD) ·
`tools/backfill_pack_currency.py` (MUTATES_PROD — edits on-sale content) ·
`tools/backfill_archived_url.py` (MUTATES_STORE) · `tools/backfill_bundle_html.py` (MUTATES_PROD —
rewrites purchased zips) · `tools/backfill_facets.py` (MUTATES_PROD) ·
`tools/backfill_missing_listings.sh` (MUTATES_PROD — mass publish; needs a review step, memory
`republishing-stranded-passes-fails-on-link-rot`) · `tools/reprice_live_packs.py` (MUTATES_PROD) ·
`tools/reprice_to_charm_rungs.py` (MUTATES_PROD) · `scripts/reconcile_orphan_index.py`
(**DESTRUCTIVE** — deletes index rows; `--check-only` vs `--apply` is one character apart today).

**Engine.** `run.py {vet, signal, generate, report, diagnose, discover, operators, lanes{list,nix,
natch,set,unset}, markets{list,show,probe,open,close}}` · `vet --resume` (the drain) ·
`run_scheduled.py --daemon` · `PAUSE` / `PAUSE_GENERATION` *(already live via R3 —
`prospector_daemon.py:431-437`; the registry **adopts** them, it does not rebuild them)*.

**Backup / integrity.** `scripts/backup_store.py` · `scripts/restore_drill.py` ·
`scripts/verify_selling_catalogue.py` · `scripts/reconcile_orphan_index.py`.

**Probes (READ_ONLY).** `blocker_probe` · `pack_banner_probe` · `site_spec_probe` · `store_audit` ·
`popdd_verify` · `load_gate` · `generation_survival` · `spend_today` · `graphify_sweep`.

**Publish / storefront.** `publish/publish.py` · `make_kill_log.py` · `site_wide_dash_cleanup.py`
(MUTATES_PROD — commits to public source; **never one-tap**).

### 5.3 Registry integrity — the test that keeps the ratchet at zero

For **every** entry: `argv[1]` exists and is executable; every declared flag appears in that file's
arg parser; `klass` is explicit with no default; `MUTATES_PROD`/`DESTRUCTIVE` declare a `blast`
string and either a `dry_run_flag` or a written `dry_run_waiver`; every `needs` env var is named in
`.env.example`. Plus **coverage**: every executable in `scripts/` and `tools/` is either registered
or listed in `registry.UNREGISTERED` with a reason — so a new script reddens the suite until someone
decides whether it is an operator tool.

---

## 6. Safety model

| Class | Telegram | Streamlit | Gate |
|---|---|---|---|
| `READ_ONLY` | one tap | one click | none |
| `MUTATES_STORE` | one tap + "writes to store/" chip | same | receipt |
| `MUTATES_PROD` | **dry-run tap first**, blast shown, confirm types the affected count | same, with the full diff on screen | rehearsal receipt < 15 min old |
| `DESTRUCTIVE` | as above **plus** auto-backup first, confirm types the exact id | same | receipt names the restore command |

- **The confirm screen shows the real diff, not prose.** R7's own lesson: *"a card that says 'would
  restart' while restarting is exactly the defect."* Screen one must **be** the dry-run. On the
  phone that means a truncated diff plus a count and a desk pointer — never a summary that stands
  in for a rehearsal that never ran.
- **The fence lives in the writer, never in the keyboard.** D4 in the Telegram ledger is this exact
  scar; `brains.py:213 fence_check` is the pattern to copy.
- **Money rail:** re-pricing offers **rungs from `config.yaml listing.pricing`, never a free-text
  price**, and executes as **one `bridge.py` `PriceDecision`** so the Stripe price and the catalogue
  row cannot drift (`price-change-breaks-fulfilment`,
  `the-catalogue-took-the-fallback-the-rail-took-the-decision`).
- **One writer.** A machine-wide lock — the two surfaces run on the same machine and must not run
  two actuators against `store/` at once.
- **Truth/demand firewall.** No screen lets a sales metric change a gate, weight or threshold.

---

## 7. Screens

**[T]** Telegram · **[S]** Streamlit · **[T→S]** Telegram card that summarises and names the desk view.

### 7.1 Engine

| Screen | Where | Content |
|---|---|---|
| **Now** | T | Exists (R1). Add: code-fingerprint-vs-disk, drain ETA, oldest backlog row. |
| **Funnel** | T→S | generated → prescreened → grounded → verdicted → gated → scored → published: count, loss and top-3 loss reasons per step, by lane/market/date. The view that shows `21 consecutive barren ticks` as a *shape*. |
| **Providers** | T | Exists (R4/R5). Add: share of verdicts ruled, spend today, `dead_until` countdown. Reads raw `dead_until`, **never** `is_dead`, so the panel cannot consume the half-open probe slot (`health.py:_claim_probe`). |
| **Spend** | T→S | Metered vs subscription legs, per provider/lane/pack, cap runway. Uses `today_spend_cached()`; **never** re-parses the 177 MB ledger inline. |
| **Runs / drain** | T + S | Launch, cancel, resume, queue depth, per-run cost. Both surfaces, one job model. |
| **Parameters** | T + S | Both exist already (R2/R4 and `_parameters.py`). **Unify on `config_editor.py`** so there is one validator, one backup path, one audit trail. |

### 7.2 Transparency — the headline ask

| Screen | Where | Content |
|---|---|---|
| **Lineage** | S | One candidate, the whole causal chain as a vertical timeline: signal → generation prompt/operator/cost → prescreen → dedup match (and the exact string matched) → per check: query, provider, URLs fetched, the passage quoted, verdict + confidence → kill gate fired or DEFER reason → score by axis × weight → composite vs threshold → price rung + comparables → publish. Every node carries provider, latency, cost, artifact path. |
| **Outage honesty** | S | A `retrieval_failed=True` node renders as an **outage marker, not a datum** — the defect that produced `store/dossiers/2102bacc6dd75cf9.kill.json`, a fully-reasoned-looking KILL caused by our own outage. |
| **Receipts feed** | T→S | One reverse-chronological stream: ticks, jobs, intents, config edits, price changes, publishes, backfills — actor, class, duration, cost, exit code, diff summary. Phone shows the last 5; desk shows all. |

### 7.3 Catalogue administration

| Screen | Where | Content |
|---|---|---|
| **Shelf** | S | Every pack: listed/unlisted, price + rung + currency, facets, content key + version, dossier decision, age, last edit, **and whether a PASS dossier backs it** (`a-listed-pack-had-only-a-kill-dossier`, as a column not a script). |
| **Pack detail** | S | Real rendered copy preview (never a grep — `never-judge-design-by-grepping-html`), facets, price history with reason + actor, content pointer, buyer count, lineage link. |
| **Pack ops** | T + S | Withdraw/restore (reason required), retag facets, edit copy, repoint content, re-price by rung. On the phone because a bad pack must be pullable from anywhere. |
| **Coverage** | T→S | Facet coverage vs demand, stranded PASSes, truncated one-liners, missing share cards, dead citations — **each row carries the registry actuator that fixes it**. |

### 7.4 Tools — the backfill console

The registry, rendered on both. Each card: label, class chip, blast radius, last-run receipt, and
whether preconditions hold (env vars present, store API reachable, git tree clean).

- **[S]** is where you *read the diff* — long dry-run output belongs on a screen with scrollback.
- **[T]** is where you *press the button* — including from the phone, with the truncated diff, the
  affected count and the typed confirm.
- **Except `DESTRUCTIVE`**, which requires the full diff on screen and is therefore **desk-only**.

A tool with no rehearsal shows an explicit *"this tool cannot rehearse"* banner — the pressure that
gets `--check-only` added to `tools/backfill_market.py`.

### 7.5 Customers, support, growth

| Screen | Where | Content |
|---|---|---|
| **Growth** | T→S | `/internal/analytics/summary`: sessions, pack views, checkout starts, conversion by pack/facet/country, 14-day trend, waitlist. |
| **Support lookup** | T | Email / order token / session id → orders, entitlements, download count, content version at purchase. A card, not a table — one buyer at a time. |
| **Support actions** | T | Resend magic link, reissue entitlement, re-presign download. `MUTATES_STORE`, one tap — a customer is waiting. |
| **Delivery health** | T→S | Failed downloads, expired presigns, entitlements pointing at a dead content key, unprocessed webhooks. |

### 7.6 New store-API reads this needs *(none exist today — recon)*

`GET /internal/ops/sales-audit` · `GET /internal/ops/entitlements?email|pack_id` ·
`POST /internal/ops/entitlements/{id}/reissue` · `GET /internal/ops/audit?actor&from`. Key-gated,
read-only except the reissue. Each touches buyer data and gets its own small review.

---

## 8. Requirements — continuing the Telegram ledger's numbering

| Req | Statement | Probe |
|---|---|---|
| **R9** | Every operator tool in the repo is reachable from both surfaces, declared once, classed by blast radius, and impossible to add without a test noticing. | `pytest tests/ops/test_registry.py` |
| **R10** | The engine can be *interrogated*, not just watched: any candidate's full causal chain, and the cohort funnel with attributed drop-off. | render fixture PASS + KILL; funnel reconciles to `catalogue_stats()` |
| **R11** | The shelf and every pack can be administered, with the money rail fenced to rungs and one `PriceDecision`. | `pytest tests/ops/test_price_actuator.py` |
| **R12** | A buyer problem can be diagnosed and fixed from the phone in one session. | seeded buyer resolves on email/token/session; reissue works |
| **R13** | The two surfaces share one read model and one actuator registry — no truth is derived twice. | test forbids `scheduler/status.py`-style parallel readers in `ops/` callers |

---

## 9. Story backlog

Each story's acceptance is a **command**. No story is done without it exiting 0 and being quoted.

### Tier −1 — make both surfaces usable (ships FIRST, blocks everything below)

The founder's verdict is the requirement, and the final acceptance is **a completed task by a
human**, never a passing test — that is the mistake §1.1 exists to correct. But *finding* the
defects is machine work, and *fixing the ability to create them* is structural work (§1.2).

**The founder is not the test harness.** *"I can't test and list all"* — correct, and a design that
required it was wrong. **The bot gets crawled by a machine.** This is possible because panels
already return typed cards (`render_panel_view() -> PanelView`) and 12 of the 39 test files already
capture rendered output, so the capture rig is an extension, not a new build.

| # | Story | Acceptance |
|---|---|---|
| **U1** | **Crawler.** Walk the reachable screen graph in-process from the root menu: render a card, record its verbatim text + every button label + callback id, tap each button, recurse, detect cycles. **Fenced:** classify each callback against the §5 registry and *never* tap anything above `READ_ONLY`; stop at any confirm screen and record it unpressed. Run against a sandbox `HERMES_HOME`/`store/`. | a machine-readable map: every screen, its verbatim text, its buttons, its edges — produced by one command, zero human taps |
| **U2** | **Does it work — the mechanical sweep.** From the crawl, flag every: tap with no reply · tap that raises · tap returning a generic *"Action failed"* · tap that returns an identical screen (silent no-op) · button reachable from nowhere (orphan) · screen with no way back (dead end) · label appearing twice routing to different actions · action needing more than 4 taps from root. All deterministic, no model involved. | a defect list with counts per class, each entry naming the screen and the verbatim text |
| **U3** | **Is it comprehensible — the graded sweep.** Run a rubric over each captured card (cheap, Haiku): does it say what it is · is every button plain English rather than an internal id or abbreviation · can you tell where you are and how to go back · does it state current state or only offer actions. **The grader reads the captured verbatim card, never a summary of it** — grading a model's own prose is memory `a-gate-that-graded-model-prose-as-its-own-output`. | a ranked list of unclear screens with the offending text quoted |
| **U4** | **Founder arbitrates, does not test.** Review the ranked U2+U3 list: keep / discard / "that one actually matters most". Plus **five** journeys you personally care about, walked by hand — not twelve, and not an inventory. | a signed-off defect list; total founder time measured in minutes |
Then the foundation itself — **§1.2's fix, not a UX pass.** Patching 45 panels is what produced 39
tests and an unusable product; these stories remove the ability to author an inconsistent screen.

| # | Story | Acceptance |
|---|---|---|
| **U5** ✅ | **The adoption meter.** Census the 61 panel modules for `compose()` / `Group()` / `VERDICT_GLYPHS` / `nav()`; floors that only rise, a raw-glyph ceiling that only falls, failure output naming the next modules to migrate. | **SHIPPED** — `tests/gateway/operator_shell/test_spine_adoption.py`, floors 4 / 3 / 1 / 39, ceiling 33 |
| **U6** ✅ | **The way back.** Wire the dead `nav_stack` at the single funnel so all 63 panels gain ← and a breadcrumb without being edited; fix its import-time state path, non-atomic write and bare `except:`. **Seed the lexicon** (`LABELS` + `label_for()`) so a screen cannot invent a word. | **SHIPPED** — 17 tests in `test_back_navigation.py`, incl. a source assertion that the chrome still *imports* the history module (a unit test of `go_back()` would have passed throughout the years it was unreachable) |
| **U7** | **Migrate panels onto `compose()`/`Group()`/`VERDICT_GLYPHS`**, in U4's defect-rank order, raising the meter's floors per commit. Panel by panel, behind the 39 existing tests. Never big-bang — routing and plumbing are working assets. | each commit raises a floor or lowers the ceiling; full suite green; U1's crawl shows that panel's defects gone with no new ones anywhere |
| **U8** | **Every action reports its outcome — now the renderer's job, not each author's.** Tap → acknowledgement → receipt naming what changed, or naming the failure specifically. A generic *"Action failed"* is a defect (R7 found this class already; it recurs because it was 45 people's responsibility). | trigger 5 failure modes; each returns a distinct, specific card, with no per-panel code |
| **U9** | **Same treatment for Streamlit**, scoped by its own U2/U3 sweep. It is not exempt — 7 pages built over months by the same process. | the U4 journeys complete at the desk unaided |
| **U10** | **Re-grade R1–R8 against completed tasks.** Each row gets ✅ only with a task-completion record; anything else stays 🟡 with the blocking defect named. | the ledger's status column matches the founder's experience |

**Gate:** U1–U3 are machine work and start immediately. **U4 is the only founder-blocking step**, and
it is an arbitration of a ranked list, not a test campaign. U5–U6 (the foundation) block U7–U9.
Tier 0's registry may proceed in parallel from U5 onward — the registry is what U5's `actions` field
points at, so the two are the same design arriving from opposite ends.

### Tier 0 — the spine (R13)

| # | Story | Acceptance |
|---|---|---|
| **O1** | `prospector/ops/registry.py` — every tool declared once with class, blast, dry-run. | `pytest tests/ops/test_registry.py` (the six rules, §5.3) |
| **O2** | Coverage gate: a new script in `scripts/`/`tools/` reddens the suite until registered or waived. | add a dummy script → red → register → green |
| **O3** | `prospector/ops/readmodel.py` wraps `control_center/readers.py`; no new derivations. | test asserts no direct `sqlite3`/`json.load` of `store/` inside `ops/` |
| **O4** | The Telegram gateway renders its tool keyboard **generated from the registry**, not hand-written. | `test_every_button_dispatches` green with `_UNBUILT == {}` |
| **O5** | Streamlit renders its tool cards from the same registry. | one registry entry → appears on both surfaces; test asserts parity |
| **O6** | Telegram's engine-state reads move onto `ops/readmodel.py`; `scheduler/status.py` becomes a thin caller or is retired. | one reader; test asserts no second derivation of spend/backlog/moat |
| **O7** | Intent + receipt log `store/ops/intents.jsonl`, append-only, actor-stamped, nonce-idempotent, **shared by both surfaces**. | launch from Telegram → receipt visible in Streamlit; replay nonce → original receipt |
| **O8** | One-writer lock across gateway and console. | two concurrent actuators, one blocks |

### Tier 1 — transparency (R10)

| # | Story | Acceptance |
|---|---|---|
| **T1** | Lineage page in Streamlit: every check with provider, passage, cost, latency. | snapshot test on node sequence for a known PASS and KILL |
| **T2** | `retrieval_failed` nodes render as **outage**, never evidence. | fixture `2102bacc6dd75cf9` shows an outage banner, not seven `unverifiable` rows |
| **T3** | Funnel with attributed drop-off, filterable by lane/market/date, plus its Telegram summary card. | counts reconcile to `catalogue_stats()` exactly |
| **T4** | Provider panel reads raw `dead_until`. | test asserts `_claim_probe` is never called by the panel |
| **T5** | Receipts feed unifying ticks, jobs, intents, config edits, publishes. | a day's feed matches `alerts.jsonl` + `jobs.json` + `config_history.jsonl` line counts |
| **T6** | Cost per pack and per lane from the canonical reader only. | figure matches `run.py report`; test forbids hand-parsing |

### Tier 2 — the tool catalogue (R9)

| # | Story | Acceptance |
|---|---|---|
| **A1** | Tools screen on both surfaces: class chips, blast radius, preconditions. | every §5.2 tool appears on both; a missing env var shows as blocked |
| **A2** | Mandatory dry-run for `MUTATES_PROD`; the confirm screen **is** the rehearsal receipt. | a re-price with no fresh rehearsal is refused, with reason |
| **A3** | Rehearsal-less tools grow `--check-only` or get a written waiver. | registry test passes with no unexplained `dry_run_flag=None` |
| **A4** | `reconcile_orphan_index.py` is `DESTRUCTIVE` and desk-only: auto-backup, typed confirm, restore command in the receipt. | run on a scratch store; receipt names a restorable backup |
| **A5** | Re-price = rungs only, one `bridge.py` `PriceDecision`. | test asserts no free-text price path exists |
| **A6** | `backfill_missing_listings.sh` gains a review step enumerating the stranded PASSes it will publish. | dry-run receipt lists ids; link-rot check runs first |
| **A7** | Decide, tool by tool, which of the 13 backfills are spent one-shot migrations → `tools/archive/`. | each registered **or** archived with a note; none ambiguous |

### Tier 3 — clean up the dead surface (R13)

| # | Story | Acceptance |
|---|---|---|
| **D1** | Archive `~/.hermes/mini-app/` and `scripts/mini_app_server.py`; free port `:8801`. | `rg 'mini_app' ~/.hermes/scripts` → only the archive path; nothing binds 8801 |
| **D2** | `ESTATE_STATE.md` updated: `:8801` retired **and** nothing on disk still tries to bind it. | `verify_estate.sh` still exits 0; the port list is true |

### Tier 4 — catalogue + customers (R11, R12)

| # | Story | Acceptance |
|---|---|---|
| **C1** | Shelf view with the PASS-dossier-backing column. | a pack with only a KILL dossier shows red |
| **C2** | Pack ops on both surfaces: withdraw/restore with reason, retag, copy edit, repoint content. | each writes; price-history/audit row appears |
| **C3** | Store API gains the four `/internal/ops/*` reads (§7.6). | contract test against a seeded db |
| **C4** | Support lookup by email / token / session id, as a Telegram card. | seeded buyer resolves on all three |
| **C5** | Resend magic link / reissue entitlement, audited, from the phone. | new token works, old revoked, audit row written |
| **C6** | Delivery health: expired presigns, dangling content keys, unprocessed webhooks. | seed a dangling key → row appears |
| **C7** | Growth panel from `/internal/analytics/summary`, no client-side recompute. | figures match the endpoint exactly |

### Tier 5 — deferred, specified so it is not designed out

| # | Story | Note |
|---|---|---|
| **X1** | Revenue by day / pack / country from `SalesAudit`. | deferred by founder decision 2026-08-14 |
| **X2** | Refund + dispute handling with entitlement revoke. | deferred; stays in the Stripe dashboard for now |
| **X3** | Stripe ↔ `SalesAudit` reconciliation. | deferred; **C3 is the seam that makes it small later** |

---

## 10. Explicitly not in scope

- **Money reporting screens** (revenue/orders/refunds/disputes) — founder decision. The money-rail
  *actuators* stay, fenced (§6). C3 keeps the seam open.
- **A third surface.** No `/admin` on mumchimp.com, no Mini App, no tunnel, no inbound port.
  Telegram and Streamlit are the complete set.
- **Exposing Streamlit publicly.** It stays on `127.0.0.1`. The desk-only cost is accepted in §3.
- **Multi-user.** Single operator. The intent log carries `actor`, so that stays an auth change
  rather than a redesign.

---

## 11. Decisions needed from the founder

0. **Remediate in place, or rebuild on the foundation?** §1.2 says the weakness is that a screen is
   code rather than data, and U5–U7 propose fixing that by migrating all ~45 panels onto one screen
   model behind the existing tests. The alternative is to keep patching panels. **Proposal:
   migrate — five symptom tests already pass on an unusable product, so patching is measured not to
   converge.** **This is the blocking decision.** Your only other input is U4: arbitrating the
   crawler's ranked defect list, plus five journeys you care about. Not twelve tasks, not an
   inventory.
1. **Which of the 13 backfills are spent?** A registry entry for a migration that must never run
   again is a hazard, not a feature. **Proposal: decide one by one in A7; archive the spent ones.**
2. **`DESTRUCTIVE` desk-only — agreed?** It means `reconcile_orphan_index.py` cannot be run from the
   phone. **Proposal: yes, desk-only; the phone can still see that it needs running.**
3. **Does `scheduler/status.py` get retired or kept as a thin caller (O6)?** Retiring is cleaner;
   keeping is lower risk since the gateway depends on it today. **Proposal: thin caller first,
   retire once the gateway has run a week on the shared reader.**

---

## 12. What this document does not claim

- **The tool inventory (§5.2), the store-API surface (§7.6) and the "13 backfills" count are recon
  output, not verified by me on disk this session.** The first task of any tier that touches them
  re-verifies them. An agent's result is a claim — the Telegram ledger's own near-miss (a subagent
  reporting five existing scripts as absent, which would have deleted five working buttons) is the
  standing reason.
- Verified directly this session: the Streamlit console's existence, size, page list and running
  pid; the Telegram ledger's R1–R8 status text and its two ratchet constants; the Mini App files,
  their line counts, `mini_app_server.py`'s `:8801` binding, the absence of any `web_app` reference
  in the gateway, and the absence of a running mini-app process or launchd job.
- The claim that Telegram and Streamlit currently derive engine state through **different** readers
  (`scheduler/status.py` vs `control_center/readers.py`) is read off the two ledgers' own "where the
  code lives" tables, not off a diff of the two implementations. **O6 must confirm the overlap
  before deleting anything.**
- **"Covers all business operations" is false today by design** — money reporting is deferred (§10)
  and listed as such rather than quietly dropped.
