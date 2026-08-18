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
`control_center/readers.py` — two readers, one truth, and memory `one-reader-two-caller-shapes` is  <!-- doc-lint-ok: deleted with the Streamlit console, 2026-08-18 -->
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
| **O3** | `prospector/ops/readmodel.py` wraps `control_center/readers.py`; no new derivations. | test asserts no direct `sqlite3`/`json.load` of `store/` inside `ops/` |  <!-- doc-lint-ok: deleted with the Streamlit console, 2026-08-18 -->
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
  (`scheduler/status.py` vs `control_center/readers.py`) is read off the two ledgers' own "where the  <!-- doc-lint-ok: deleted with the Streamlit console, 2026-08-18 -->
  code lives" tables, not off a diff of the two implementations. **O6 must confirm the overlap
  before deleting anything.**
- **"Covers all business operations" is false today by design** — money reporting is deferred (§10)
  and listed as such rather than quietly dropped.

---

# 13. Rev 4 — Requirements derived from the operational record (2026-08-15)

> Rev 3 (§1–§12) was designed from this document's own inventory, and §12:593 correctly disowned
> that inventory as "recon output, not verified by me on disk this session". Rev 4 replaces the
> spec-derived backlog with one derived from **what actually broke**: 192 commits across the engine
> and the storefront (2026-07-05 → 2026-08-15), the live contents of `store/`, and the code on disk.
> Every requirement below names the incident that produced it. Claims carry `file:line` or command
> output; anything not verified this session is marked HYPOTHESIS.

## 13.1 The finding that reorders the entire backlog

**The console's config write path has never been used successfully by a human, and if it is used it
corrupts the engine.** This outranks every story in §9, because §9 builds new admin surface on top
of the page that carries these defects.

### Usage evidence (measured on disk, 2026-08-15)

| Ledger | Records | Successes | Human-sourced |
|---|---|---|---|
| `store/control_center/jobs.json` | 8 (all `prospector.run generate`, newest 2026-07-31) | **0** (6 failed, 1 cancelled, 1 unknown) | — |
| `store/control_center/config_history.jsonl` | 233 (2026-06-16 → 2026-08-06) | — | **0 of 233** — all pytest-sourced; `moat_affecting: true` count is **0** |

Both write paths are, in production terms, unexercised.

### T0-1 — Saving Parameters destroys the kill filter (CRITICAL)

`prospector/control_center/pages/_parameters.py:348`:  <!-- doc-lint-ok: deleted with the Streamlit console, 2026-08-18 -->

```python
gates = [{"k": True} for k, v in value.items() if v]
```

`k` is a **string literal**, not the comprehension variable. Six ticked checkboxes therefore stage
`hard_gates: [{"k": True}, {"k": True}, {"k": True}, {"k": True}, {"k": True}, {"k": True}]`.

On disk the real value is a different shape entirely — check name mapped to the verdicts that fail
it (`python3 -c "import yaml;print(yaml.safe_load(open('config.yaml'))['hard_gates'])"`):

```
[{'value_durability': ['refuted']}, {'incumbency': ['refuted']}, {'payer_solvency': ['refuted']},
 {'distribution': ['refuted']}, {'legality': ['refuted']}, {'pain_reality': ['refuted']},
 {'adversarial_decisive': False}]
```

So a Save loses every gate name, every failing-verdict list, and the `adversarial_decisive` entry.
`validate_config` (`config_editor.py:238-245`) waves it through because it only asserts
*list, of dicts* — it never checks the keys. **Effect: the six hard gates that decide what may be
sold stop matching any check name.** This is the money rail's kill filter.

### T0-2 — Saving Parameters blanks the operator chain

`_parameters.py:273-279` offers `["", "mock", "claude"]`. The live value is
`operator: [minimax, claude_cli]` (`config.yaml:58`). It is not in the option list, so `index`
falls to `0` and `_update_staged(cfg, "operator", "")` stages the **empty string** on every render
— no interaction required. `claude` is not even a valid tier: the paid Anthropic adapter was
deleted 2026-08-15 and `_build_operator` now raises `ValueError` on removed tiers.

### T0-3 — Saving Parameters deletes 58% of config.yaml

`config_editor.py:326` writes with `yaml.safe_dump`. Measured:

```
on_disk_lines= 2034   comment_lines= 1173
after_safe_dump_lines= 981   comment_lines_after= 0
```

**1,173 comment lines destroyed** — every calibration receipt, every founder directive, every
"why this number" note, including the revenue decision parked at `config.yaml:1414`
(`require_figure_verification: false`, with the inline note that enabling it delists ~30% of the
shelf). The CLI path does surgical regex edits and preserves them (`run.py:2571`, `:2741`).
**The console is today less safe than the CLI it was built to replace.**

### T0-4 — The amplifier: a corrupt Save auto-deploys itself

`config.yaml` is inside the daemon's redeploy fingerprint (`scheduler/run_scheduled.py:1655-1658`).
`_reload_on_code_change` (:1669) → `_redeploy` (:1674) → `os.execv` (:1723) means one Save ships
the corrupted file into the running daemon at the next tick boundary, with no human step between.
T0-1/2/3 are not "a bad file on disk"; they are a bad file **in production within one tick**.

### T0-5 — The change ledger is YAML in a file named `.jsonl`

`config_editor.py:344-345` appends `yaml.safe_dump(entry, ...)` to `config_history.jsonl`.
Verified: 932 lines / 233 four-line YAML blocks. Any JSONL reader — including a future audit page —
fails on line 1. (A recon pass this session did exactly that and reported the file "malformed".)

### T0-6 — The certification fence is keyed to keys that do not exist

`MOAT_AFFECTING_KEYS` (`config_editor.py:162-177`) names `moat_order`, `adversarial_decisive` and
`adversarial` as top-level paths. **None exists in config.yaml.** Meanwhile the keys that actually
decide what may be sold are *uncovered*: `moat_primary` (`:81`), `weights`, `listing.pricing.*`
(`:1555-1653`) and all nine `schedule.*` keys. `moat_affecting` has fired **0 times in 233 records**
— consistent with a fence pointed at nothing.

**R14 (new, blocking): no new admin surface ships on the Parameters page until T0-1…T0-6 are fixed
and each has a regression test that would have failed before the fix.**

## 13.2 Coverage: the console can edit 11 paths of 205

Config surface measured on disk: **40 top-level keys / 205 distinct key names**, plus ~50 env vars,
6 filesystem sentinels and 5 config-mutating CLI subcommands. `_parameters.py` exposes **11 paths**
(thresholds ×2, hard_gates, weights, spend ×2, operator, retrieval ×3, persona block).

Not editable anywhere in the console, ranked by blast radius:

| Not editable | Where it lives | Why it matters |
|---|---|---|
| `moat_primary` | `config.yaml:81` | decides which brains may rule finally — i.e. what may be sold |
| `spend.daily_subscription_cap_usd` / `_soft_cap_usd` | `:2011`, `:2024` | **both `0.0` = disarmed**, while subscription-equivalent burn runs ~$95.87/day |
| `listing.pricing.*` rungs, FX, `default_rung_index`, `rung_adjust_enabled` | `:1555-1653` | every price the buyer sees |
| `PAUSE` / `PAUSE_GENERATION` | `store/scheduler/` sentinels | the only stop button; today it is `touch`/`rm` over SSH |
| all 9 `schedule.*` keys | `:1997-2002` | cadence, batch size, backlog cap, market rotation |
| `noncritical_operator`, `artifact_operator` | `:129`, `:138` | the two chains that are not the moat |
| `retrieval.minimax_concurrency` | `:321` | throughput of the brain that now leads the chain |
| `admissibility.*`, `active_market` (`:748`), `active_profile` (`:1177`) | — | what gets generated at all |
| ~50 env vars incl. `ALERT_WEBHOOK_URL` | — | see S7 |

## 13.3 Engine requirements, each keyed to a real incident

| # | Requirement | Incident that produced it |
|---|---|---|
| **E1** | Provider-health panel: show every tier's `dead_until`, transient-vs-permanent class and probe state; one-click **clear dead mark** per tier | Provider-tier management is the **#1 recurring emergency — 9+ commits in 10 days**. Recovery every single time was hand-reading `store/provider_health.json` and deleting a mark. |
| **E2** | Edit **any** config key from a schema, not a hand-written form; unknown keys visible read-only rather than absent | Five commits exist *only* to promote a hardcoded constant into config after it caused an outage: `7d4f17e` (MOAT_PRIMARY), `a93310d` (non-critical chain), `9f03ced` (minimax max_tokens), `711cab8` (batch/deadline), `3c0f9a7` (market rotation). The pattern repeats because the console cannot reach new keys. |
| **E3** | Comment-preserving writes (round-trip YAML, e.g. `ruamel.yaml`, or the CLI's scoped-regex path) | T0-3. 1,173 comment lines are the estate's calibration record. |
| **E4** | Stop/resume control for `PAUSE` and `PAUSE_GENERATION` with the half-stop semantics stated in the UI | The distinction (full stop vs generation-only, drain continues) exists in code and in CLAUDE.md, and is invisible to the operator. |
| **E5** | Blocker inbox: surface `store/dossiers/*.lint.json` | **76 blocker files on disk with no reader anywhere in the console.** |
| **E6** | Backlog + drain view keyed to `run.drainable()`, the single definition of "backlog" | The rate-vs-stock brake decision (`gate_generation_on_grounding`) is unobservable today. |
| **E7** | Spend panel that reads the durable ledger and shows **both** subscription caps and their armed/disarmed state | Both are `0.0`. A disarmed cap that looks like a configured cap is the failure mode. |
| **E8** | Golden-gate runner that reports the **real** discrimination number | `_parameters.py:419-449` certifies with a hardcoded `discrimination=0.0`. |

## 13.4 Storefront requirements, each keyed to a real incident

| # | Requirement | Incident that produced it |
|---|---|---|
| **S1** | Shelf reconciliation view: catalogue rows vs Stripe Prices vs local receipts, with the drift listed | `ff17d78` — **9 of 59 rows desynced** from Stripe. |
| **S2** | Unlist queue with a visible worker health signal | `a447e4f` fixed killed packs still selling; `c954aac` — the drain then **died silently on a missing `sqlite3` binary in the Fly image while 6 packs kept taking money**. Live now: `pending_unlist.jsonl` 0 rows / `.done.jsonl` 15 rows. |
| **S3** | Stranded-PASS queue with age, and republish from the console | 24 stranded PASSes sat three days with nothing raised. Live now: `ALERT.txt` carries an unresolved `[critical] 6 PASS(es) stranded off the shelf`. |
| **S4** | Shelf-count truth: read the live catalogue, not local receipts | `readers.py:211-217` `_count_listings()` globs `store/listings/*.json` — **77 files on disk vs 59 selling packs**. The badge has been wrong the whole time. |
| **S5** | Copy/facet QA queue over the 8 existing `/internal/catalog/*` endpoints (`Program.cs:448,683,783,907,962,1050,1208,1261`) | **34 of 63 one-liners truncated mid-word**; **15 of 49 packs carry no facets** and are invisible to every filter. |
| **S6** | Citation-health view + the `require_figure_verification` decision surfaced as a decision, not a config comment | `967457f` — **one dead citation in twenty killed a whole pack.** `config.yaml:1414` parks a ~30%-of-shelf revenue decision in a comment, with a review queue (`tools.review_figures`) nobody sees. |
| **S7** | Alerting that is actually wired | `scheduler/alerts.py:235` reads `ALERT_WEBHOOK_URL`, which is **assigned nowhere in the estate**, while `deploy/com.prospector.watchdog.plist:9,15` documents it as a working feature. |
| **S8** | Every destructive tool behind an explicit apply step, per the §5 Actuator Registry | Every storefront recovery to date was a hand-typed CLI with `--apply`; `tools/retire_rotted_passes.py:177` literally prints "STILL LIVE until you run: `python3 tools/unlist_killed.py`". |

## 13.5 The shape of the whole record

Across 192 commits the dominant failure class in both halves is one thing: **a rail that exists,
reads as working, and is inert, welded into source, or invisible.** Inert (`ALERT_WEBHOOK_URL`,
both subscription caps, the `moat_affecting` fence). Welded (five constants promoted to config only
after an outage). Invisible (76 lint blockers, 24 stranded PASSes, 15 facet-less packs, the figure
review queue). The console's job is therefore **observability of rails first, actuation second** —
which is the reverse of Rev 3's ordering, where §9's story backlog leads with actuators.

## 13.6 Proposed build order

0. **T0-1…T0-6** — fix the destructive Save path, with a regression test per defect. Nothing else
   ships first. (§13.1)
1. **E1 + E5 + S3** — the three panels that answer "what is broken right now", all read-only, all
   backed by files already on disk.
2. **E2 + E3** — schema-driven, comment-preserving config editing; retires the promote-a-constant-
   after-an-outage cycle.
3. **E4 + E7 + S2** — the stop button, the spend truth, the unlist queue.
4. **S1 + S4 + S5 + S6** — storefront reconciliation and QA over the existing internal endpoints.
5. **S7 + S8** — wire alerting; put every destructive tool behind the Actuator Registry.

**Open founder decision:** the branch is 13 ahead / 19 behind `origin/main`, with 12 content
conflicts (`git merge-tree --write-tree HEAD origin/main`) — **none of them under
`control_center/`**. Recommend branching this work fresh off `origin/main` and treating the merge
as its own task.

**Status: requirements only. No code in this change.**

---

# 14. Rev 5 — Total realtime monitoring + full admin (2026-08-16)

> Rev 4 (§13) derived its backlog from 192 commits of failure history. **Rev 5 is forced by a
> change to the machine itself**: the producer/consumer split went live at ~00:40Z on 2026-08-16,
> and *no surface on either side knows it exists*. Every claim below carries a `file:line` or
> command output taken this session; recon claims are marked as such.

## 14.1 The ask

Founder, verbatim, 2026-08-16:

1. *"i need spec and build for advanced total monitoring realtime and admin from streamlit via
   hermes telegram agent, needs urgent build, the stuff we have is old and outdated"*
2. *"i need to be monitoring every aspect of the engine and full admin control"*
3. *"also being able to change which model runs which part of system"*
4. *"i also need details on internals, generation and verdict for every run"*
5. *"outcomes, pass kill rates, the reasons etc metrics"* · *"charts"*

## 14.2 Decisions taken 2026-08-16 (these close open questions in §11 and §13.6)

| # | Decision | Consequence |
|---|---|---|
| **D-A** | **Expose Streamlit to the phone.** Reverses Rev 3 §10 ("no tunnel, no inbound port") and §3's accepted desk-only cost. | Streamlit stops being desk-only; the §3 division of labour survives as an *editorial* rule (tables at the desk, verbs on the phone) but no longer as a *reachability* constraint. Transport decision in §14.7. |
| **D-B** | **Everything in parallel, ship as ready.** | R14's blocking rule is **narrowed, not waived**: monitors are read-only and ship immediately; T0-1…T0-6 must land before the *first config-writing actuator*, not before the first panel. |
| **D-C** | **`spend.daily_cap_usd` 20.0 → 100.0.** | **DONE this session**, `config.yaml:2190-2204`. `warn_at_usd` 15.0 → 75.0, holding the 75%-of-cap ratio. Round-tripped through the engine's own loader: `daily_cap_usd = 100.0`. 1,362 comment lines intact (no T0-3 loss). |

## 14.3 What shipped hours ago and is invisible to every surface

`launchctl list` — both roles live:

```
18820  com.prospector.scheduler   PRODUCER
18594  com.prospector.consumer    CONSUMER
1726   com.prospector.control-center  (streamlit :8601, 127.0.0.1)
25088  ai.hermes.gateway          (started Fri 14 Aug 23:42:57, newest panel source 14 Aug 22:41 → serving current code)
```

**Neither operator surface contains the word.** Greps run this session:

| Term | Streamlit `control_center/` | Hermes `hermes-agent/` |
|---|---|---|
| `consumer` | comment only (`readers.py:965,1013`) | **NO HITS** |
| `lease_owner` / `lease_until` | **NO HITS** | **NO HITS** |
| `PAUSE_CONSUMER` | **NO HITS** | **NO HITS** |
| `producer_mode` | **NO HITS** | **NO HITS** |
| `drainable` | — | **NO HITS** |

That is the literal content of *"the stuff we have is old and outdated"*: both consoles model a
single-daemon engine that stopped existing this morning.

### 14.3.1 The blocking defect — the consumer cannot be monitored at all

`rg -n "heartbeat" prospector/consumer.py` → **no hits**. The producer writes
`store/scheduler/heartbeat.json` from `run_scheduled.py:149 _write_heartbeat()` (8 call sites,
keys `ts, mono, pid, phase, beat_every_s, batch_size, code`). **The consumer writes no heartbeat,
so there is nothing for a monitor to read.**

This is not a missing panel; it is a missing emitter, and it is dangerous rather than merely
inconvenient. `alerts.py:424 alerts_for_tick` deliberately suppresses paging on an all-DEFER
producer tick — correct while the drain was in-tick, and now precisely wrong: **if the consumer
dies, the producer keeps ticking green and the queue fills silently.** The only artefact the
consumer touches today is `store/scheduler/consumer_decay.json` (26 bytes, `{"at": …}`), stamped
only when a decay sweep runs — cadence `decay_interval_s: 7200`, so it is silent for up to two
hours by design and cannot serve as liveness.

**R15 is therefore the first thing built, before any panel.**

## 14.4 The good news — the substrate for asks 4 and 5 already exists

Measured this session. Nothing below needs a new writer:

| Stream | Size / rows | Carries |
|---|---|---|
| `store/prospector.db` `dossiers` | kill **2140** · defer **105** · pass **81**; **3 live leases** | `decision, gate_fired, lease_owner, lease_until, reverify_due_at, ambition_tier, market, persona, composite`; indexed on `decision` and `lease_until` |
| `store/scheduler/batch_diagnostics.jsonl` | 120 records | `funnel{generated, dedup_dropped, prescreen_in, prescreened_out, novelty_selected, rejection_fastpath, vetted}` · `decisions{pass,kill,defer,provisional}` · `kill_gates{…}` · `verdict_matrix{6 checks}` · `composite{min,med,mean,max,near_bar_within_0.5}` · `usage{by_phase,by_provider,total_cost_usd}` · `closest_kills` · `passes` |
| `store/scheduler/ticks.jsonl` | **4431** rows | `ts, allowed, reason, dry_run, today_spend_usd, daily_cap_usd, batch_size, result, error` |
| `store/scheduler/audit/*.jsonl` | 42 files, 47 MB | per-check live trail: `candidate_start`, `check_result{verdict,confidence,retrieval_failed,idx,total}`, `candidate_done{decision,gate,provisional}`, `soft_early_exit`, `search`, `search_rank`, `page_fetch`, `fallback_resolved` — all stamped `run_id, pid, seq, candidate_id` |
| `store/dossiers/*.json` | per candidate | per check: `queries, query_source, provider, verdict, confidence, rationale, retrieval_failed, degraded, citations, sources[{url, text, query, fetched_at, published_at, archived_url}]`, plus `provider_chain`, `adversarial`, `score`, `gate_fired` |

**Ask 4 ("internals, generation and verdict for every run") and ask 5 ("outcomes, pass/kill rates,
reasons, metrics, charts") are therefore READ problems, not instrumentation problems.** The one
real gap is generation-side: `funnel.generated` gives the count, but the generation *prompt* and
the per-candidate *refinement_history* are in the dossier while the rejected-at-prescreen
candidates are not persisted at all (see R19).

**`store/run_metrics.db` is a decoy** — 20 rows, all written within 0.4s on 2026-08-02. It is not a
time series and must not be charted as one.

## 14.5 Ask 3 — "change which model runs which part of system"

Five chains exist. Measured on disk, and separately through the engine's own loader:

| Chain | `config.yaml` | Live value | Editable at desk | Editable on phone |
|---|---|---|---|---|
| `operator` (verdict/moat) | `:58` | `[minimax, claude_cli]` | read-only (`readers.py:490`) | ✅ R4 `🧠 Nodes` |
| `moat_primary` (**who may rule FINALLY**) | `:81` | `[minimax, claude_cli]` | ❌ | ❌ **no hits in the whole gateway** |
| `noncritical_operator` | `:136` | `[minimax, minimax_m27]` | ❌ | ✅ R4 |
| `artifact_operator` | `:145` | `[claude_cli, minimax]` | read-only (`readers.py:490`) | ✅ R4 |
| `retrieval.provider` | `:239` | `[ddg, exa, claude_cli]` | ❌ | ✅ R4 |

**Two findings:**

1. **`moat_primary` is unreachable from either surface.** The R4 `🧠 Nodes` panel shipped
   2026-08-10; `moat_primary` became a config key on 2026-08-15. The panel can reorder *which brain
   is tried first* but cannot change *which brains are trusted to publish* — the single knob that
   decides whether a verdict is final or `provisional`. That is the highest-value routing control
   in the engine and it is the one that is missing.
2. **CLAUDE.md is stale on the non-critical chain.** It records `minimax` alone; disk says
   `[minimax, minimax_m27]` (`config.yaml:136`, confirmed via `run._noncritical_order()`).

### 14.5.1 The trap any routing monitor must avoid

`operator.moat_primary()` takes **no arguments** and reads a process-global installed by
`config.load_config` (`config.py:1141-1142 set_moat_primary`). Measured this session:

```
cold import              -> ['claude_cli']          # MOAT_PRIMARY_DEFAULT, operator.py:1405
after load_config()      -> ['claude_cli','minimax'] # what the daemon actually uses
```

**A panel that imports `operator` without loading config reports a different trusted roster than
the running engine** — and would show `minimax` as untrusted while it is ruling and publishing.
This is `a-probe-must-call-it-the-way-the-process-does` waiting to happen, and it gets a test.

## 14.6 Requirements (continuing the ledger's numbering)

| # | Requirement | Probe |
|---|---|---|
| **R15** | **The consumer emits a heartbeat** (`store/scheduler/consumer_heartbeat.json`: `ts, mono, pid, phase, cycle, batch, blocked_reason, code`) and a **liveness alarm fires when it goes stale** — the producer-green/consumer-dead case `alerts_for_tick` structurally cannot see. | kill the consumer → alarm within one `idle_s`+grace; producer keeps ticking |
| **R16** | **Queue-depth + lease view**, keyed to `run.drainable()` (the single definition of backlog), with `lease_owner`/`lease_until`: held vs free vs expired, and drain rate → ETA. | count reconciles to `sqlite3 … group by decision` exactly |
| **R17** | **Three-scope pause table as a control**: `PAUSE` (both) · `PAUSE_GENERATION` (producer) · `PAUSE_CONSUMER` (consumer), each showing the semantic difference on screen, re-read every cycle so no restart is needed. | arm each → the right role stops, the other keeps running |
| **R18** | **Per-run internals view** (ask 4): one run → generation → per candidate → per check → query, provider, passage quoted, verdict, confidence, cost, latency → gate fired → score → publish. `retrieval_failed` renders as an **outage marker, never a datum** (§7.2 T2). | fixture PASS + KILL + a `retrieval_failed` row each render distinctly |
| **R19** | **Outcome metrics + charts** (ask 5): pass/kill/defer rates over time, kill reason by gate, verdict matrix per check, funnel with attributed drop-off, composite distribution vs bar, cost per outcome — all from `batch_diagnostics.jsonl` + `dossiers`, none recomputed client-side. | figures reconcile to `catalogue_stats()` and to `run.py report` |
| **R20** | **`moat_primary` is editable from both surfaces**, with the fence in the WRITER (a chain head outside the trusted set stops publication), and the reader calls `load_config()` first. | writer refuses an untrusted head; test asserts cold-import never answers |
| **R21** | **Per-role spend split** against the raised $100 cap, with projected hit-time; reads the cached scan, never the 193 MB ledger inline. | figure matches `guard.scan_today()`; no inline parse |
| **R22** | **Provider health is truthful**: `store/provider_health.json` currently holds **only dead/deleted tiers** (`openrouter/*`, `cursor_cli`, `standardcompute`) and **no entry for either live brain**. The panel shows every *configured* tier, reads raw `dead_until`, and never consumes the half-open probe slot. | panel lists minimax + claude_cli; test asserts `_claim_probe` uncalled |
| **R23** | **Both surfaces read one model** (`prospector/ops/readmodel.py`, §4) — no truth derived twice. | test forbids a second derivation of backlog/spend/moat |
| **R24** | **Streamlit is reachable from the phone** without a public inbound port. | reach `:8601` from the phone with the laptop's firewall unchanged |

## 14.7 Transport for D-A (Streamlit on the phone)

Measured on this box: **Tailscale is installed and already has this laptop and an iPhone in the
tailnet** (`/usr/local/bin/tailscale`, node `chidis-macbook-pro` `100.112.51.80`,
`iphone-13-pro-max` `100.121.96.36`) — but `tailscale status` reports **"Tailscale is stopped"**
and the iPhone was **last seen 39 days ago**. `cloudflared` and `ngrok` are also present.

**Recommendation: Tailscale**, because it is the only option that adds *no* public listener —
the laptop keeps binding a private address, the phone reaches it over WireGuard, and device auth
is the fence. Concretely: start the daemon, bind Streamlit to the tailnet IP instead of
`127.0.0.1`, re-authenticate the phone. `cloudflared`/`ngrok` publish to the open internet and
would put full engine admin behind a URL, which is a materially different risk and is **not**
what D-A was chosen for.

**Process risk, recorded as such:** this reverses a documented founder decision (Rev 3 §10, no
tunnel/no inbound port). It is the founder's call and is being executed; the note exists so the
reversal is legible later, not to re-litigate it.

## 14.8 Build order (D-B: parallel, ship as ready)

0. **R15** — the consumer heartbeat + liveness alarm. *Blocks everything consumer-shaped, and is
   the one defect that can lose work silently.* Engine-side, small.
1. **R16 + R17 + R22** — queue/lease view, the three-scope pause control, honest provider health.
2. **R18 + R19** — the internals view and the outcome charts (asks 4 and 5). Pure reads.
3. **R20 + R21** — routing control incl. `moat_primary`, and the spend split. *First config-writing
   actuators → T0-1…T0-6 must land before these.*
4. **R23 + R24** — the shared read model, and the tailnet reach.

## 14.9 R15 — DONE and live (2026-08-16 ~01:12Z)

**What shipped.** `prospector/consumer.py` gained a writer (`_write_heartbeat`, tmp + `os.replace`)
and a reader (`consumer_liveness`), and `run_scheduled.py::_check_consumer` wires the reader into
the watchdog — the estate's fastest clock at 900s, and a process that is not the one being judged.

**Receipts, on the live store.**

| Claim | Evidence |
|---|---|
| The consumer now beats | `store/scheduler/consumer_heartbeat.json` → `{"ts":"2026-08-16T01:11:55Z","mono":368769.5,"pid":40647,"role":"consumer","phase":"draining","cycle":1,"batch":5,"code":"ebf8f9245db4"}` |
| The reader agrees | `consumer_liveness(cfg)` → `state=running, age_s=0.73, pid_alive=True` |
| The producer is unaffected | `--watchdog` → `Watchdog: alive (phase=generating, 0.8 min ago)`, exit 0 |
| A dead consumer PAGES | isolated store, pid 999999: `ALERT.txt` → `🚨 [critical] Drain consumer is DEAD`, `active_alerts` → `['consumer_down']` |
| It reaches the phone | `consumer_down` added to `alerts.py::TELEGRAM_KEYS` |
| Tests | 109 passed — `tests/unit/test_consumer_heartbeat.py` (25 new) + the consumer, alert, heartbeat and drain suites |

**The guards were proved to fail on the before-state**, not merely to pass now (memory:
`prove-the-probe-fires-on-the-before-state`). Four mutations, each reinstating one pre-R15
behaviour: *no writer* → 5 red; *reader ignores the pid* → the dead-consumer alarm and the
before/after test go red; *one global staleness threshold instead of the beat's own `next_check`*
→ the late test goes red; *watchdog checks the producer only* → both alarm tests go red.

**Deliberate non-behaviours, each with its reason:**
- **The watchdog never kills the consumer**, unlike the daemon branch. A drain pass was measured at
  4127s against a ~251s median, and that tail is why the consumer exists; killing a `late` one
  aborts the long vet it was built to finish and bills it again on relaunch.
- **`unknown` never pages.** No heartbeat is also what "not deployed" looks like.
- **`blocked` never pages but always RESOLVES**, so an operator's own PAUSE cannot leave a stale
  CRITICAL banner up behind it.
- **The watchdog's exit code stays the producer's answer.** It is what decides whether the daemon
  was killed; folding a second process into it makes "the daemon is fine" unreadable.
- **A broken liveness check cannot take the daemon watchdog with it** — the failure mode where
  adding monitoring reduces coverage.

**Deployment note.** The consumer was restarted (`launchctl kickstart -k`, pid 18594 → 40647) so
the running process serves the new code; a daemon serves the code it started with. It had logged
nothing since 01:03Z, and there was no way to tell idle from wedged — which is the defect itself.

**Unrelated, pre-existing, still open:** `active_alerts` on the live store holds `stranded_passes`.

**Status: superseded by §14.10 below.**

## 14.10 R16 + R17 + R22 — DONE (2026-08-16 ~02:50Z)

**What shipped.** The spine of §4 exists: `prospector/ops/readmodel.py` (every operator READ,
derived once) and `prospector/ops/pause.py` (the one writer, with an append-only intent log at
`store/ops/intents.jsonl`). Two thin renderers consume them — `prospector/control_center/pages/
_engine.py` here, and the `--view {queue,pause,providers}` CLI for the Telegram surface, which
lives in a different repo and must not import Streamlit. `Store` gained the two SQL reads the
views need (`counts_by_decision`, `lease_census`) so the GROUP BY happens once, in SQLite.

**Receipts, on the live store** (`python -m prospector.ops.readmodel`, 2026-08-16T01:45Z).

| Claim | Evidence |
|---|---|
| R16 counts reconcile exactly | `by_decision` → `{defer 152, kill 2143, pass 81}`, byte-identical to `sqlite3 store/catalogue.db 'select decision,count(*) from dossiers group by decision'` |
| Backlog is `run.drain_survey`, not a second count | `backlog` → `workable 279, orphaned 0, stalled 0, unpublishable 0, oldest 2026-07-02T19:23:43Z` — the same call the drain and the generation brake make |
| The lease census is three states | `held 4 · expired 0 · unheld 2372 · total 2376`; *expired* is a worker that died mid-vet, and expiry IS the release |
| The ETA is measured, and says so | `rate 0.405/h over a 17.29h window from 3 passes → eta 689.1h (2026-09-13T18:51Z)` |
| An unmeasurable ETA is null with a reason | `eta_h=None` + `eta_reason` whenever nothing has drained; a burst is floored to a 1h window so "50 rows in 4 minutes" cannot mint 750/h |
| R17 lists three scopes with their real readers | `PAUSE`→`guard.py::SchedulerGuard.is_paused`, `PAUSE_GENERATION`→`run_scheduled.py::_generation_suppressed`, `PAUSE_CONSUMER`→`consumer.py::_blocked_reason` |
| R22 lists every CONFIGURED tier | `minimax` (trusted; verdict#0, noncritical#0, artifact#1, marketing#0) and `claude_cli` (trusted; verdict#1, artifact#0, marketing#1, grounding#2) both present — neither has an entry in the health file |
| The 9 stale marks are demoted, not rendered as brains | `orphan_marks` → `openrouter/*`, `cursor_cli`, `standardcompute` — tiers no chain names |
| The trusted set is the running one | `trusted_final` → `[claude_cli, minimax]` via `load_cfg()`; a cold import answers `{claude_cli}` (§14.5.1) |
| Tests | **26 new** (`tests/ops/`), **168 passed** with `tests/control_center/`, **279 passed** across `tests/scheduler/` + the consumer loop; the page renders against the live store with no exception |

**Proved on the before-state** (memory: `prove-the-probe-fires-on-the-before-state`). Three
mutations, each reinstating the wrong design: *backlog counted directly instead of via
`drain_survey`* → `test_a_defer_row_with_no_dossier_on_disk_is_named_orphaned_not_absorbed` red;
*`is_dead` instead of the raw `dead_until` read* → `test_the_panel_never_claims_the_half_open_probe`
red. Both green again on restore.

**The drain-rate series had to be created, not found.** The producer/consumer split moved the drain
out of the tick, and the consumer heartbeat is OVERWRITTEN each cycle — so it can say what is
happening now but can never answer "how fast is this draining", which is an ETA's only input.
`consumer.py::_record_drain` now appends one line per pass to `store/scheduler/consumer_drains.jsonl`.
Until a post-restart pass lands there the view merges the producer-era `ticks.jsonl` `result.resumed`
rows and **prints a caveat naming the source**, because an ETA computed from a retired mechanism
presented as current is exactly `a-saturated-metric-prints-as-a-confident-null`.

**Deliberate non-behaviours:**
- **The pause CONTROL adds provenance only.** All three readers decide on `.exists()` alone, so a
  hand-`touch`ed file is exactly as effective and renders with a null actor. The JSON body answers
  *who and why*; it is never load-bearing.
- **Arming an already-armed scope does not rewrite it.** A refresh loop would otherwise overwrite
  the original armer with its own timestamp — deleting the only thing the body is for.
- **Idempotent by STORED nonce, not a TTL cache** (`idempotency-keys-expire-they-are-not-dedup`): a
  double-tap on a phone keyboard cannot re-arm a pause someone has since cleared.
- **The scope name is fenced in the WRITER** (`UnknownScope`), so a typo cannot produce a file no
  reader consults — a control that reports success and stops nothing.
- **The panel never calls `is_dead`.** It can claim the single half-open probe slot
  (`health.py::_claim_probe`); a page refreshing every few seconds would eat the one call whose job
  is to measure a brain's recovery. A test asserts `_claim_probe` is never reached.
- **`drain_blind` is reported separately from `moat_blind`**, because the drain is trusted-only by
  design and that asymmetry is a decision, not a bug to reconcile away.

**Deployment note.** The consumer (pid 40647) is mid-drain and was NOT restarted — a pass was
measured at 4127s, and killing one aborts the long vet it exists to finish. `_record_drain` goes
live on its next natural restart; the caveat above is what covers the gap. The producer (pid 18820)
is running `code=2e2ed4ea0410` against `ebf8f9245db4` on disk and needs a `launchctl kickstart -k`
at a tick boundary.

**Status: superseded by §14.11 below.**


## 14.11 T0-1…T0-6 + R18 · R19 · R20 · R21 · R23 — DONE (2026-08-16 ~03:40Z)

**Everything in the programme is built except R24**, which is not a build: it needs the founder to
start the Tailscale daemon and re-authenticate the phone (last seen 39 days ago, §14.7).

### T0 — the actuator fences (they gate every config-writing requirement)

| # | Defect | Fix | Proof |
|---|---|---|---|
| T0-1 | Saving Parameters replaced every hard gate with `{"k": True}` — a string literal where the loop variable belonged — and `validate_config` waved it through because "a list of dicts" was true of the wreckage | `_parameters._stage_hard_gates`; `validate_config` now requires each key to be a real check name with a non-empty verdict list | `tests/control_center/test_t0_config_save.py` (4 tests) |  <!-- doc-lint-ok: deleted with the Streamlit console, 2026-08-18 -->
| T0-2 | The operator selector offered `["", "mock", "claude"]`: the live value is a LIST, so `index` fell to 0 and staged `""` **on every render, with no interaction**; `claude` has not been buildable since 2026-08-15 | multiselect over `operator.BUILDABLE_TIERS` (read from the builder, never a second list) + chain validation in the writer | 3 tests |
| T0-3 | A Save re-serialised config.yaml: **2034 lines in, 981 out, 1173 comment lines destroyed** | `prospector/control_center/yaml_surgery.py` — line surgery, refuses anything it cannot locate as a single scalar, re-parses and compares before writing | 6 tests; smoke on the real file: 2234 lines in/out, 1362 comments in/out, diff exactly 2 lines |  <!-- doc-lint-ok: deleted with the Streamlit console, 2026-08-18 -->
| T0-4 | config.yaml is inside `code_fingerprint`, so all of the above shipped to the daemon at its next tick with no human step | refusals now happen before the write; fingerprint unchanged across three refused saves | 1 test |
| T0-5 | `config_history.jsonl` was 233 four-line YAML blocks in a file named `.jsonl` — every reader fails on line 1 | writes JSON lines; `read_history()` tolerates both | 2 tests (100 legacy records parsed) |
| T0-6 | `MOAT_AFFECTING_KEYS` named three paths that **do not exist** in config.yaml, so the certification fence fired 0 times in 233 saves | 11 paths verified present on disk; `weights` added — it is the composite `min_composite_to_pass` is compared against | 3 tests + `test_config_editor.py::test_changing_weights_IS_moat_affecting` |

### R18 · R19 · R21 — built in parallel, each with its own read model

| # | Files | Probe met |
|---|---|---|
| R18 | `prospector/ops/runs.py`, `pages/_runs.py`, `tests/ops/test_runs.py` (26) | PASS `08b22037fc2afc07` renders 8 evidence rows / 0 outages; KILL `2102bacc6dd75cf9` renders 1 evidence row and **7 outage blocks** with the integrity warning; `32086d481c69567e` (`retrieval_failed`) renders 8 outages, 0 readings. Outage rows carry `verdict=None, confidence=None` by construction — no table can print a fail-safe as a datum. |  <!-- doc-lint-ok: deleted with the Streamlit console, 2026-08-18 -->
| R19 | `prospector/ops/metrics.py`, `pages/_metrics.py`, `tests/ops/test_metrics.py` (22) | `reconciled: true` against `catalogue_stats()` (pass 82 / kill 2143 / defer 151 / total 2376) and against `run.py report --metrics` (3.7% / 96.3%). Rates divide by `ruled = 2225`, never by 2376 — a DEFER is an outage, not an outcome. |  <!-- doc-lint-ok: deleted with the Streamlit console, 2026-08-18 -->
| R21 | `prospector/ops/spend.py`, `pages/_spend.py`, `tests/ops/test_spend.py` (28) | metered `$0.68845` **is** `guard.scan_today()[0]`; subscription `$19.530663` is `[1]`. Whole view 0.15 s, resuming at byte 202,620,400 of a 202,646,800-byte ledger — 26 KB read, not 193 MB. |  <!-- doc-lint-ok: deleted with the Streamlit console, 2026-08-18 -->

Two findings from R19 worth acting on separately: `run.py report`'s `min_composite` count is **776
vs a true 767** — it silently absorbs 9 kills whose gate was never recorded (`report.py:117` does
`gate_fired or "min_composite"`); and the diagnostics window contains **two different
`min_composite_to_pass` bars (2.5 and 3.2)**, so any single-bar composite chart is wrong for part
of its own data. The page prints both.

### R20 — the verdict roster is editable, and the fence is in the WRITER

`prospector/ops/routing.py` is the one writer. `routing_problems()` is called by
`set_moat_primary` (the CLI the phone reaches), by `config_editor.validate_config` (the Streamlit
Save) and by the Parameters page itself — one function, three surfaces.

| Claim | Evidence |
|---|---|
| The fence refuses an untrusted head | `set_moat_primary(cfg, ["claude_cli"])` while `operator: [minimax, claude_cli]` → `applied: false`, file byte-identical, refusal logged to `store/ops/intents.jsonl` |
| Why that is the fence | head outside the roster ⇒ every verdict stamped provisional (`operator.py:1509`) ⇒ nothing publishes (`run.py:1157`, `not dossier.provisional`). The engine keeps running, keeps spending, and stops selling — with no error anywhere |
| A trusted head with a provisional TAIL is still allowed | that is the 2026-08-08 directive; a fence demanding a fully-trusted chain would forbid the design (`test_a_trusted_head_with_a_provisional_tail_is_allowed`) |
| Cold import never answers | subprocess `import prospector.operator; moat_primary()` → `["claude_cli"]` while config.yaml says `[minimax, claude_cli]`; `routing_view` raises `StaleProcessGlobal` in that state rather than reporting the default as truth (§14.5.1) |
| Live, through `load_cfg` | `python -m prospector.ops.routing show` → `head: minimax`, `head_trusted: true`, `publishes: true`, `trusted_source: "config.yaml moat_primary"` |
| A write is surgical and moat-affecting | one line changes, every comment survives, certification drops to `certified: false` |
| A replayed nonce does not re-apply | a phone tap delivered twice returns the first receipt; a roster widened by hand in between is not re-narrowed |
| Mutation-proved | replacing the head check with `if False:` → **3 tests red across both surfaces** (`test_an_untrusted_head_is_a_problem`, the writer test, the Streamlit-save test); restored → 16 pass |

### R23 — one read model, and the second derivation it found

The probe is `tests/ops/test_one_read_model.py`. Writing it surfaced a live violation:
`readers.py` carried its **own reverse-tail parse of `store/prospector.jsonl`**, independent of the
rail. It summed `event: "spend"` + `amount_usd` only, so the Overview's "today's spend" was the
metered leg alone — **$0.69 shown while $19.53 of subscription burn went unreported**, a 28x
under-count with no warning (memory `never-hand-parse-the-spend-ledger`). That parser is deleted;
`_today_spend_from_ledger` now returns `SchedulerGuard.scan_today()` through `prospector.ops.spend`,
both legs.

Tests: renderer and CLI hold the **same function objects** (identity, not equivalence); every ops
module exposes the `main()` the Telegram surface calls; the Overview KPI equals the Spend page
figure; patching `scan_today` to a sentinel moves the KPI (a hand-parser would ignore the patch);
and an AST scan forbids any page from calling `drain_survey` / `drainable` / `scan_today` /
`spend_by_day` / `moat_primary` / `sqlite3.connect` itself. **One recorded exception, not hidden:**
`pages/_resume.py:225` still opens the catalogue DB directly — it predates the spine and is the  <!-- doc-lint-ok: deleted with the Streamlit console, 2026-08-18 -->
page R16's queue view replaces. It is allowlisted by name so the fence still fires on a second
offence there or a first anywhere else.

### Suite

`.venv/bin/python -m pytest tests/ops tests/control_center -q` → **297 passed, 1 skipped** (2026-08-16).
Nav now carries 🛠 Engine · 🔎 Runs · 📈 Outcomes · 💵 Spend, each wired in `app.py`
`_PAGE_MODULES`/`_PAGES_LIST` and pinned by `tests/control_center/test_page_routing.py`.  <!-- doc-lint-ok: deleted with the Streamlit console, 2026-08-18 -->

**Status: superseded by §14.12 below.**


---

## §14.12 R24 — the console is reachable from the phone (2026-08-16 ~04:05Z)

**Status: DONE on this machine's side. One tap remains on the phone, and it is not an auth tap.**

`http://chidis-macbook-pro-1.tail3f2ff4.ts.net:8601` — HTTP 200 over the tailnet, verified by
`curl`, not by `launchctl list`.

### Two of the three instructions were wrong, and both were wrong in the direction of silence

| Instruction | What was actually true | Receipt |
|---|---|---|
| "bind Streamlit to 100.112.51.80" | **This machine is 100.93.240.113.** 100.112.51.80 is a SECOND, stale registration of the same Mac (`chidis-macbook-pro` vs the live `chidis-macbook-pro-1`). Binding the pinned IP would have failed with `Can't assign requested address` — or, worse, bound a node the phone routes to and nothing serves. | `tailscale status --json` -> `Self.TailscaleIPs == ["100.93.240.113", ...]`; the .80 address appears under `Peer`. |
| "re-authenticate iphone-13-pro-max (last seen 39 days ago)" | **Its key is not expired.** `KeyExpiry: 2026-10-23T14:23:54Z`, `Expired: null`. The phone is simply *offline* — Tailscale is toggled off in the app. Re-authenticating would have fixed a problem that does not exist and left the real one in place. | `tailscale status --json` peer `localhost` / iOS. |
| "start the Tailscale daemon" | Correct, but not literally: `tailscaled` was already running (PID 340). The **node** was down — `BackendState: Stopped`, `WantRunning: false`. `tailscale up` refused a bare invocation because it would have dropped `--accept-routes`; the working command names it. | `tailscale up --accept-routes` -> `BackendState: Running`, `WantRunning: true` (so it survives reboot). |

### The bind, and why it is an install script rather than a smarter launcher

The obvious design — point the plist at `scripts/run_control_center.sh` and resolve the address  <!-- doc-lint-ok: deleted with the Streamlit console, 2026-08-18 -->
at launch — **was implemented, tried, and failed**, in a way that reads as a broken script:

```
/bin/bash: /Users/chidionyema/Documents/code/prospector/scripts/run_control_center.sh: Operation not permitted
```

macOS TCC grants access to `~/Documents` per EXECUTABLE. The venv's Python holds that grant (the
agent has been exec'ing `.venv/bin/streamlit` for months); `/bin/bash` does not, so the agent died
before the first line of the script ran. The plist must keep exec'ing `streamlit` directly.

So the address is resolved at INSTALL time by `scripts/install_control_center_agent.sh`  <!-- doc-lint-ok: deleted with the Streamlit console, 2026-08-18 -->
(read-only by default; `--apply` writes and reloads). It refuses to install a plist with no
`CONTROL_CENTER_PASSWORD` — `KeepAlive` would otherwise restart a portal that fails closed, every
few seconds, forever — and it verifies by REACHING the socket (`lsof` + `curl` for HTTP 200),
because `launchctl list` reports a healthy PID for a process that is failing to bind
(memory: `macos-ps-and-launchctl-probes-report-false-pass`). Re-run it whenever the tailnet
address changes. The IP is never hand-typed; only `BackendState == Running` is trusted, because
`tailscale ip -4` keeps serving the last-known address while the backend is Stopped.

`scripts/run_control_center.sh` carries the same resolution for the manual/foreground path.  <!-- doc-lint-ok: deleted with the Streamlit console, 2026-08-18 -->

### What changed for the operator

* **Loopback no longer answers.** A single-address bind is one address: use the MagicDNS URL at
  the desk too. This is deliberate — `0.0.0.0` would put a password-only portal on whatever cafe
  wifi the laptop joins.
* **The MagicDNS name, not the IP**, is the URL to save on the phone: it survives the next address
  change; a bookmarked `100.93.240.113` does not.
* **The remaining step is on the device**: open Tailscale on the iPhone and turn it on. No
  re-authentication, no login — the key is valid until 2026-10-23.

**Status: R15-R24 DONE. The programme is complete; the phone tap is the only thing outside this
repo's reach.**

---

## §14.13 R25 — the console was reachable and still unusable (2026-08-16 ~04:35Z)

**Status: DONE. Five defects, four of them invisible to every test in §14.11's 297.**

R24 proved `HTTP 200`. That is a claim about the socket, not about the operator: measured on the
live console at a 430px viewport, the console was unusable in four independent ways at once, and
the founder's report ("the UI is unusable, like totally") was exact.

| # | Defect, as measured | Cause | Fix |
|---|---|---|---|
| 1 | The sign-in screen renders Streamlit's own red **"Missing Submit Button — user interactions will never be sent to your app"**, and the Sign in button renders unlabelled at ~30×60px (a11y tree: `button [ref_5]`, no name). The button WORKS — the gate merely looks broken to the only person who ever sees it | `app.py` called `require_auth()` **before** `inject_theme()`. The gate halts the script with `st.stop()`, so the theme never reached the one screen every operator must pass | theme moved above the gate |
| 2 | At phone width the sidebar **occludes** the page rather than reflowing it: the first screenshot showed only right-hand slivers (`…k=5 failed`, `…generate`, `…fresh`). Every visit needs a collapse tap before anything can be read | `initial_sidebar_state="expanded"` | `"collapsed"` |
| 3 | The landing page headline read **`Engine idle · last generate k=5 failed (2376s)`** — job `31T012116136`, dated **2026-07-31** — while the consumer was live and ruling (run `3f66deb4afb7`: 3 PASS / 4 KILL, 0 outage checks). The console greeted the operator looking dead, with its working half behind a tap they had no reason to make | `readers.glance_status` is built from the last MANUAL launcher job and knows nothing about the daemon, but claimed the ENGINE's state | (a) landing page is now `engine`, whose hero is `producer up · consumer running · N rows workable`; (b) the sentence is now `No manual job running · last generate k=5 failed (2376s, 16d ago)` — it names the surface it measures and dates itself |
| 4 | `pyarrow.lib.ArrowInvalid: Could not convert '—' with type str: tried to convert to int64, Conversion failed for column elapsed_s`, twice in one session | `_overview.py:329` and `_resume.py:139` mixed an em-dash placeholder with ints in one column | one dtype per column |
| 5 | `get_price: provider 'minimax_m27' not in cfg.pricing or PRICING; returning $0 (will appear free in cost reports)` × 6. `minimax_m27` is a LIVE tier (`config.yaml:136`) | absent from `telemetry.PRICING` | priced at the flat MiniMax M2.7/M3 rate already in that table — the same account and adapter, so this is that price, not a new one |

**Probe that fires on the before-state** (a fix verified only on the after-state proves nothing).
Against the 8 real jobs in the live window:

```
OLD (shipped until now)  dtypes=['int','str'] -> Arrow RAISED: Could not convert '—' … to int64
NEW (this fix)           dtypes=['str']       -> Arrow OK
```

Nuance recorded, not hidden: where `elapsed_s == 0` the old expression (`or "—"`) printed `—`
because 0 is falsy; the new one prints `0s`. A sub-second job is a reading, not an unknown.

**Receipts.** `pytest tests/control_center tests/ops -q` → **297 passed, 1 skipped** (unchanged from
§14.11). Console restarted (pid 94778), `HTTP 200`, log clean since restart: **0 tracebacks, 0
ArrowInvalid, 0 unpriced-m27 warnings**. Verified in-browser at 430px: themed gate with a real
"Sign in" button → lands directly on Engine, sidebar collapsed, full width.

**One test was pinning the defect.** `test_job_outcome.py:108` asserted the exact string
`"Engine idle · last generate k=20 failed (987s)"`. The words were the bug, so the assertion is now
the contract: never claims the engine's state, and always dates itself.

### Still open after R25

* **`exa` is priced at $0 and that is NOT fixed.** It is a paid API, but `PRICING` is per-1M-tokens
  and Exa bills per SEARCH — the table cannot express it, and inventing a number is worse than the
  warning. Needs a rate from a retrievable source plus a per-search branch. (`ddg` at $0 is correct.)
* **`Drained in 879h`** at 0.37/h over 322 workable rows. The page says so honestly — the rate is
  from producer-era ticks and the consumer has never recorded a drain pass — but nobody has measured
  the consumer's REAL rate.
* **The console password is `test`** (founder request, 2026-08-16, for phone typing). Previous
  20-char secret is in `~/Library/LaunchAgents/com.prospector.control-center.plist.bak-pre-test-*`.

## §14.14 The slow tools were killed at two minutes by the console, not by Python (2026-08-16)

`scripts/store_audit.py` takes **239.9s** (`/usr/bin/time -p`, measured 2026-08-16 on the live
store: `real 239.87`, verdict `STORE_AUDIT FAIL checks=9 failed=1 [BACKFILL_ENTRIES]`). Python
allowed it 1800s (`console_api.py:1454 _TOOL_TIMEOUT_S = _SHELF_TIMEOUT_S = 1800`). The console
killed it at 120s.

**The ceiling that decides is the Node one**, because `ops.ts` SIGKILLs the gateway subprocess
itself. It was a single `OPS_TIMEOUT_MS` defaulting to 120,000 for every call, and the launchd
plist hid that by setting `1900000`. Any console started another way — `npm run dev`, `npm start`,
a plist written later — reported "the engine gateway did not answer within 120000ms" on a tool that
was working correctly.

What changed in `store_platform/src/Ops.Console/src/lib/ops.ts`:

1. **Two ceilings, one for each kind of job.** `OPS_READ_TIMEOUT_MS` (env `OPS_TIMEOUT_MS`, still
   120s) covers reads and previews — a panel is waiting on those and a wedged one must fail fast.
   `OPS_ACT_TIMEOUT_MS` defaults to **1,860,000ms**, above Python's 1800s, so a write that spawns a
   batch tool outlives it without any environment being set.
2. **The timeout kills the process GROUP** (`detached: true`, `process.kill(-pid)`). Killing only
   the gateway left the tool it spawned still writing to `store/` after the console had given up —
   a write with no receipt, no exit code and no undo id.
3. **`tests/timeouts.test.ts` reads `_SHELF_TIMEOUT_S` out of `console_api.py`** and fails if the
   act ceiling ever drops below it. A number copied into a comment goes stale in silence.
   **`tests/gateway.test.ts` drives the real `runPython` against a fake interpreter** and pins the
   three facts a mock cannot: a write survives past the read ceiling, a read still gives up on the
   short one, and a timed-out write leaves no grandchild alive to write afterwards. Checked against
   the pre-fix code (single ceiling, no process group, restored immediately after): **3 failed | 1
   passed** — the read test is the one that should still pass, and does. A test that passes before
   and after the change proves nothing, so this is the receipt that it does not.
4. **`OPS_TIMEOUT_MS=1900000` removed from the installed plist** (backup:
   `com.prospector.ops-console.plist.bak-timeout-2026-08-16`). It now means the READ ceiling, and
   giving a panel 31 minutes to answer is the opposite of what a panel wants.

**A live run alone could not prove this, and that is worth recording.** After the rebuild, running
`tools.run` on `store_audit` end-to-end through the API (sign in → preview → confirm) returned in
**49s** (`took_s=49`, `timed_out=false`, `exit_code=1` — the tool's own BACKFILL_ENTRIES failure,
matching the CLI). The same script had taken 239.9s cold an hour earlier. A run that comes in under
two minutes cannot distinguish a fixed ceiling from a lucky one, so the fake-interpreter tests are
the proof and the live run is only evidence that the door still opens.

Three comments named `scripts/run_ops_console.sh`, which is not on disk (doc-lint-ok: that is the
point of the sentence) — including the error text
an operator sees when `PROSPECTOR_PYTHON` is unset, which told them to run a missing file. They now
name `npm run dev` / `npm start` and the launchd plist. (`scripts/install_control_center_agent.sh`,  <!-- doc-lint-ok: deleted with the Streamlit console, 2026-08-18 -->
also referenced, does exist and installs the SEPARATE Streamlit `com.prospector.control-center`
job — it never writes the ops-console plist, so it cannot put `OPS_TIMEOUT_MS` back.)

## §14.15 A tool run is now a background job with a job id (2026-08-16)

A longer ceiling made the slow tools finish. It did not make them a sane shape: a 30-minute HTTP
request shows a spinner, dies with the tab, and cannot be checked from a second device.

`tools.run` now starts the tool and returns immediately.

- **Python starts a detached worker.** `_act_tools_run` takes the undo snapshot, mints a 12-hex job
  id, and `Popen`s `python -m prospector.ops.console_api run-tool <id> --job <job> --payload <json>`
  with `start_new_session=True`. The reply is `{"state": "running", "job": ..., "exit_code": null}`.
  The new session is load-bearing: §14.14 made the console kill the whole process GROUP on timeout,
  so a worker in the gateway's group would be killed with it.
- **The worker writes the second receipt.** `_run_tool_job` runs the tool at `_TOOL_TIMEOUT_S` and
  appends a receipt to `store/ops/intents.jsonl` (doc-lint-ok: untracked runtime state) with
  `state` `finished` or `timed_out`, the exit
  code, `took_s`, the undo id from the snapshot, and the last 60 lines of output. A timeout is
  reported as `timed_out`, never as an exit-code failure — the tool wrote whatever it wrote before
  the kill, and "we stopped waiting" is a different fact from "it failed".
- **`read job` is the poll.** It returns the latest receipt for that job id. A `running` receipt
  older than `_TOOL_TIMEOUT_S + 60` is reported **`lost`**, not `running`: past that point nobody
  can see the process, and a spinner that never stops is prose-drift in UI form.
- **The console polls it.** `tools.tsx` keeps the job id per tool and renders `JobWatch`, which
  reads `job` every 4s and refreshes the undo panel once the job ends.
- **The audit page labels a row by its state, not by `applied`.** One job writes two rows, and
  `applied` means different things in them: "the run started" in the first, "exit code 0" in the
  second. Read through the old rule, a started job showed "applied" before it had done anything and
  a tool that ran to completion and exited 1 showed **"refused"** — which is the word this console
  uses when a FENCE stopped an action. Rows carrying `state` now show `running` / `finished` /
  `timed_out` / `exit <n>` (`src/pages/audit.tsx`).

**Measured end to end on the live store (2026-08-16).** `tools.run` on `scripts/store_audit.py`
**returned in 0.04s** with `{"state": "running", "job": "4c07523d53dd", "exit_code": null}`. Polling
`read job` showed `running` at t+10s and `finished` at t+190s, with the receipt
`{"state": "finished", "exit_code": 1, "applied": false, "took_s": 174.7, "timed_out": false}` —
exit 1 is the tool's own `BACKFILL_ENTRIES` failure, the same verdict the CLI gives. So a 175-second
tool now costs a 0.04-second request.

Six tests in `tests/unit/test_console_tools_run.py` pin it: the run returns a job id and spawns with
`start_new_session=True`; the worker writes the finishing receipt; a timeout says `timed_out`; the
reader takes the latest receipt for the id; a stale `running` reads `lost`; an unknown id reads
`unknown` and a missing id raises.

**The view allow-list test found a live bug.** `test_the_browser_view_allowlist_matches_the_gateway`
compares `VIEWS` in `src/pages/api/ops/read/[view].ts` to `console_api.READS`. The gateway had
`undo`; the browser list did not — so `tools.tsx:171`'s `useOps<UndoView>('undo')` was 404ing on
every render and the undo panel on the tools page had never worked. `undo` (and `job`) are now in
the list. The equivalent test for the write door already existed; the read door had none.

Probed on the running console after the rebuild (signed in, tailnet address): `read/undo` → **200**
(it was 404 before this change), `read/job?job=4c07523d53dd` → **200** with
`"state":"finished"` for the real background run above, and an unknown view still → **404**.
