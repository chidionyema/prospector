# Admin Console Programme — the Next.js console that replaces Streamlit

**Owner:** founder · **Opened:** 2026-08-16 · **Status:** spec + first build
**Supersedes:** the Streamlit surface described in `docs/OPS_CONSOLE_PROGRAM.md` §14. It does not
supersede that document's *requirements* (R15–R25) or its findings; it re-renders them.

The founder's ask, 2026-08-16: move the console to Next.js, add full store admin and full engine
admin. Store admin must write — change prices, unlist, republish — and expose every republish tool
already built. Engine admin means start/stop, pause, wave size, provider chain, spend caps, queue
inspection. The current console was rejected in these words: *"looks crap"*, *"unusable"*, and it
fails on Safari and inside Telegram's in-app browser.

---

## 1. The one fork the founder must choose

**Where the console runs.** There are two candidates and only one of them is physically possible
today. I have picked the possible one and built against it, but the founder should confirm.

| Option | Verdict | Evidence |
|---|---|---|
| **A. A separate Next.js app on the laptop** (chosen) | Works | The console must read `store/prospector.db`, `store/scheduler/*`, `store/dossiers/*.json` and `config.yaml`. All four live on the founder's Mac. A local Node process can open them. |
| **B. `/admin` inside the public storefront** | Impossible without new inbound network | `store_platform/src/Store.Web` is deployed to Fly.io as `prospector-store-web` (`deploy/fly/web.fly.toml:12`), 2 machines, London. Its Docker image contains only `.next/standalone`, `.next/static` and `public/` (`Dockerfile:64-66`). It has no filesystem access to the laptop and no route to it. Serving engine admin from Fly would mean opening an inbound port on the laptop — the exact thing `OPS_CONSOLE_PROGRAM.md` §10 forbids and §14.7 chose Tailscale to avoid. |

So the console is a **second Next.js app in this repo**, at `store_platform/src/Ops.Console`,
served from the laptop and reached over the tailnet, the same way Streamlit is reached today
(`OPS_CONSOLE_PROGRAM.md` §14.12: `http://chidis-macbook-pro-1.tail3f2ff4.ts.net:8601`, HTTP 200
over Tailscale, no public listener).

**What the founder is being asked to confirm:** that a local app on a tailnet address is the right
home, and that the console is *not* going on mumchimp.com. If the answer is "it must be on
mumchimp.com", the design changes completely — it needs the engine to push state to Store.Api, a
new authenticated admin surface on a public host, and a review of every write path. That is a
different programme, not a variation of this one.

**Second, smaller fork, no answer needed yet:** Streamlit stays running until the founder says
otherwise. The two consoles read the same modules (`prospector/ops/*`), so they cannot disagree.
Turning Streamlit off is a one-line `launchctl unload` whenever the founder wants it.

---

## 2. The rule that shapes everything: reuse, do not re-derive

`prospector/ops/` already is the read model. It was built for exactly this
(`OPS_CONSOLE_PROGRAM.md` §14.10–§14.11) and it carries scars the console must not re-open:

- `readmodel.queue_view` gets backlog from `run.drain_survey` — the same call the drain and the
  generation brake make. A second count is how a dashboard and a rail come to disagree.
- `readmodel.provider_view` reads raw `dead_until`, never `is_dead`, because `is_dead` claims the
  single half-open probe slot (`health.py::_claim_probe`). A page refreshing every few seconds
  would eat the one call that measures a brain's recovery.
- `readmodel.load_cfg` installs the process globals. A cold `import prospector.operator` answers
  `{claude_cli}` while the daemon rules on `[minimax, claude_cli]`.
- `spend.spend_view` resumes the ledger scan from a byte offset — 26 KB read, not 193 MB.

**Therefore: no TypeScript computes an engine metric.** Every number on every screen comes out of
a Python process that imports `prospector.ops`. The TypeScript layer fetches, caches for a few
seconds, and renders. This is enforced by a test (§9).

### 2.1 The seam: one Python gateway, one JSON contract

`prospector/ops/console_api.py` (new, added by this programme) is the only thing the web app
executes. It is a thin dispatcher over the existing modules:

```
.venv/bin/python -m prospector.ops.console_api read  <view> [--arg k=v ...]
.venv/bin/python -m prospector.ops.console_api act   <action> --payload '<json>'
```

It prints one JSON object on stdout and nothing else. Every response carries `as_of` (unix time)
and `as_of_iso`, so **every screen can state when its data was read** — the requirement below.

Why a gateway rather than calling each module's own `main()`: the six modules have six different
CLIs (`--view`, `--runs/--run/--candidate`, positional `arm|disarm|show`, positional `show|set`).
Six argv shapes in TypeScript is six places to get an argument wrong. One dispatcher is one
contract, and it is the place the read/write fence lives.

**It cannot import Streamlit.** `prospector/ops/*` has no Streamlit dependency (verified: `rg
streamlit prospector/ops/` returns nothing), and `console_api.py` must keep it that way.

---

## 3. Routes and screens

Mobile-first. The order below is the nav order, and it is the order of "what do I need to know
first".

| Route | Screen | Answers | Reads |
|---|---|---|---|
| `/` | **Now** | Is it running and is it healthy? | `read status` |
| `/queue` | **Queue** | What is waiting and how long has it waited? | `read queue` |
| `/runs` | **Runs** | What has the engine done, and when? | `read runs` |
| `/runs/[id]` | **Run detail** | What happened inside this run? | `read run --arg run_id=…` |
| `/candidates/[id]` | **Candidate** | Why did this idea die? | `read candidate --arg candidate_id=…` |
| `/spend` | **Spend** | How much today, against which cap, when does it hit? | `read spend` |
| `/metrics` | **Outcomes** | Pass/kill rates, kill reasons, funnel, composite | `read metrics` |
| `/catalogue` | **Shelf** | What is on sale, what is stranded, what is wrong | `read catalogue` |
| `/catalogue/[id]` | **Pack** | One pack, its dossier, its price history, its actions | `read pack --arg id=…` |
| `/engine` | **Engine controls** | Pause, resume, routing, wave size, caps | `read controls` + `act …` |
| `/tools` | **Tools** | Every operator CLI, what it does, how to run it | `read tools` |
| `/audit` | **Audit** | Every write anyone made, newest first | `read intents` |

### 3.1 `/` — Now

The one-glance screen. **Above the fold at 390px, no scrolling, no table.**

1. **One status line.** Green / amber / red, plus a sentence in plain words: `Producer up ·
   consumer draining · 279 rows waiting`. It names the surface it measures and it dates itself —
   the R25 defect was a landing page that read `Engine idle` off a 16-day-old manual job while the
   consumer was live and ruling.
2. **Four tiles**, two across on a phone: producer state + age of its heartbeat; consumer state +
   age of its heartbeat; rows waiting + age of the oldest; spend today vs cap.
3. **Alarm strip** — anything in `store/scheduler/ALERT.txt` / `alert_state.json`, or nothing at
   all. An empty strip renders as "no alarms", never as blank space.
4. **Pause state** — which of the three scopes are armed, who armed them, when, and why.
5. **As-of line** at the bottom: `read 4 seconds ago`, with a refresh control.

Sources: `readmodel.pause_view`, `readmodel.provider_view`, `readmodel.queue_view`,
`spend.spend_view`, plus the two heartbeat files.

### 3.2 `/queue` — Queue

`readmodel.queue_view`. Cards on a phone, not a grid.

- Rows by decision (`defer`, `provisional`, …) from one SQL through `Store.counts_by_decision`.
- Backlog from `run.drain_survey`: workable / orphaned / stalled / unpublishable, and **the
  timestamp of the oldest waiting row plus how long ago that was**.
- Lease census: held / expired / free. An expired lease is a worker that died mid-vet.
- Drain rate and ETA, **with the caveat string the read model already produces** when the rate
  comes from retired producer-era ticks rather than the consumer's own log. An ETA computed from a
  retired mechanism and presented as current is the defect this caveat exists for.
- `eta_h = null` renders as "not measurable yet" plus the reason. Never as `0`.

### 3.3 `/runs` and `/runs/[id]` — Runs, with timestamps everywhere

**Founder requirement, explicit: a run row with no time on it is not acceptable.** Every run row
carries four time facts, all four visible on a phone:

| Field | Source | Rendered as |
|---|---|---|
| started | `run_view.first_ts` | `04:12` on the day, `16 Aug 04:12` otherwise |
| ended | `run_view.last_ts` | same, or `still running` |
| took | `last_ts - first_ts` | `2m 41s` |
| how long ago | `now - last_ts` | `18 min ago` |

`runs.run_index` supplies the list; `runs.run_view` the detail. The detail screen is a vertical
timeline: candidates in order, per candidate the checks in order, per check the query, the
provider, the passage quoted, the verdict, the confidence, the cost.

**An outage never renders as a reading.** `runs.classify_check` splits `KIND_EVIDENCE` from
`KIND_OUTAGE`; outage rows carry `verdict=None, confidence=None` by construction. They render as
a marked outage block with the reason, never as a row in the verdict table. This is the
`2102bacc6dd75cf9` defect — a fully-reasoned-looking KILL caused by our own outage.

### 3.4 `/spend`

`spend.spend_view`. Metered leg and subscription leg **both**, because the Overview once showed
$0.69 while $19.53 of subscription burn went unreported. Cap, warn threshold, hours left today,
projected hit time, per-provider and per-phase splits. A cap of `0.0` renders as **disarmed**, in
red, not as "£0 cap".

### 3.5 `/metrics` — Outcomes

`metrics.snapshot`. Pass / kill / defer rates over time; kill reason by gate; the verdict matrix
per check; the funnel with attributed drop-off; composite distribution against the bar; cost per
outcome. Rates divide by `ruled`, never by the total — a DEFER is an outage, not an outcome.

Two known data hazards the screen must print rather than smooth over, both recorded in
`OPS_CONSOLE_PROGRAM.md` §14.11:

- The diagnostics window contains **two different `min_composite_to_pass` bars (2.5 and 3.2)**. Any
  single-bar composite chart is wrong for part of its own data. Print both.
- `run.py report`'s `min_composite` count is 776 against a true 767 — it absorbs 9 kills whose gate
  was never recorded. Use `metrics.gate_view`, which does not.

Charts are small, one per card, and they scroll inside their own container on a phone.

### 3.6 `/catalogue` and `/catalogue/[id]` — Shelf and Pack

Reads the **live catalogue** through Store.Api's public `/catalog`, not `store/listings/*.json`.
The local glob has been wrong the whole time: 77 files on disk against 59 selling packs
(`OPS_CONSOLE_PROGRAM.md` §13.4 S4).

Shelf columns (cards on a phone): title, listed / unlisted, price, facet count, content key
present, **whether a PASS dossier backs it**, age, last edit. A pack backed only by a KILL dossier
renders red — that is a real incident, not a hypothetical.

Pack screen: the rendered copy, the facets, the price and its history, the content pointer, the
dossier decision with a link to `/candidates/[id]`, and the action buttons of §5.

### 3.7 `/engine` — the controls

Every control on this screen calls a mechanism that already exists. Nothing here is a new engine
feature.

| Control | Mechanism | File |
|---|---|---|
| Pause everything | `ops.pause.arm(cfg, "PAUSE")` | `prospector/ops/pause.py` |
| Pause generation only (drain keeps running) | `ops.pause.arm(cfg, "PAUSE_GENERATION")` | same |
| Pause the drain only | `ops.pause.arm(cfg, "PAUSE_CONSUMER")` | same |
| Resume any of the three | `ops.pause.disarm(cfg, scope)` | same |
| Change who may rule finally | `ops.routing.set_moat_primary` | `prospector/ops/routing.py` |
| Wave size (`schedule.batch_size`) | `control_center.config_editor.write_config` via `yaml_surgery` | `config_editor.py:402` |
| Spend cap (`spend.daily_cap_usd`, `warn_at_usd`) | same | same |
| Provider chains (`operator`, `noncritical_operator`, `artifact_operator`, `retrieval.provider`) | same | same |

**The pause screen states the semantic difference on screen**, because the distinction exists in
code and in CLAUDE.md and is invisible to the operator today. `PAUSE` stops both roles.
`PAUSE_GENERATION` stops the producer and lets the drain finish. `PAUSE_CONSUMER` stops the drain
and lets the producer keep generating.

**Start/stop the daemon itself is deliberately NOT a button.** The producer and consumer are
launchd agents with `KeepAlive=true` (`deploy/com.prospector.scheduler.plist`). `launchctl unload`
from a web process would fight KeepAlive and leave the operator unable to tell "stopped" from
"crash-looping". Pause is the supported stop and it is what every reader in the engine honours.
The screen says so, and shows the `launchctl` command for the case where a real unload is wanted.

### 3.8 `/config` — Settings, every knob, grouped by what it does

Founder requirement, first-class: *"all this needs to be configurable from the admin portal"*, and
*"an operator should be able to find 'how many ideas per batch' without knowing it is called
`batch_size`"*.

So the screen is grouped by job, not by YAML path. Five groups, in this order
(`GROUP_ORDER`, `console_api.py:720`):

| Group | What it covers |
|---|---|
| **Work** — how much the engine takes on | ideas per signal, wave size, lease TTL, backlog brake, stop-inventing-while-search-is-broken |
| **Evidence** — where it looks for proof | search chain, backstop-only providers, minimum relevance |
| **Brains** — who rules a verdict | `operator`, `moat_primary`, `noncritical_operator` |
| **Speed** — how many calls at once | `minimax_concurrency`, `claude_concurrency` |
| **Money** — the ceiling | daily cap, warn-at |

Each knob renders its plain-English label first, its YAML path small and second, its current
value, and a help line that says what moves if you change it. The search box matches the label as
well as the path.

Every save shows, before it is applied: **the exact line diff** from `yaml_surgery`, whether the
change is **moat-affecting**, a **conflict warning** if the file moved under the editor
(`config_editor.mtime_conflict`), and the change **history** with who and when
(`config_editor.read_history`). **Backups and restore are reachable from the screen**
(`list_backups` / `restore_backup`, exposed as the `config.restore` action).

**Writability is measured, not declared.** The gateway runs the real rewriter over every knob and
reports what it actually refused, so a knob the surgeon cannot locate renders READ ONLY with the
refusal text. A UI that offered a save the writer then refused would read as a broken button.

### 3.9 `/tools` — the CLI catalogue

The console does not hide the CLI; it makes it findable. Every tool in §8 renders as a card with
its purpose, whether it reads or writes, its flags, and **the exact command to paste**. Tools the
console can run itself say so; tools it cannot say why not. This is the answer to "~40 operator
tools exist only as memorised command lines".

### 3.10 `/audit`

`store/ops/intents.jsonl`, newest first: actor, action, arguments, whether it applied, the reason
if refused, the nonce. Every write this console makes lands here, alongside the writes Streamlit
and the Telegram surface make. One log, three surfaces.

---

## 4. The API surface

**As built there are three HTTP routes, not twenty.** The spec first listed one Next.js route per
concern; the implementation collapsed them, and this section records what exists rather than what
was drawn. The reason is the fence: a route per concern is a fence per route, and the fence that
matters — confirmation, the intent log, the price refusal — has to be in one place or it is
already several places that can disagree.

| Method | Route | Purpose |
|---|---|---|
| GET | `/api/ops/read/[view]` | every read. `view` is checked against an allow-list; unknown views 404 |
| POST | `/api/ops/act/[action]` | every write. Refused without the confirm token of §6 |
| GET/POST/DELETE | `/api/ops/session` | password check, cookie mint, sign-out |

Both `read` and `act` shell out to exactly one command:
`python -m prospector.ops.console_api`. Nothing else is ever executed. The TypeScript never opens
`store/`, never reads SQLite, and never computes an engine number.

**Views** (`READS`, `console_api.py:697`): `status`, `queue`, `providers`, `routing`, `spend`,
`metrics`, `runs`, `run`, `candidate`, `config`, `intents`, `tools`, `catalogue`, `pack`.

**Actions** (`ACTIONS`, `console_api.py:1235`): `pause.arm`, `pause.disarm`,
`routing.set_moat_primary`, `config.set`, `config.restore`, `catalogue.set_listing`.

**Refused by name, with a reason** (`REFUSED`, `console_api.py:1246`): `catalogue.set_price`,
`catalogue.reprice`, `index.reconcile`. Refusal by name, not by absence — a 404 reads as a missing
feature, and the operator then goes looking for the button.

### 4.1 The envelope

Every gateway reply is one JSON document:

```
{ok, contract, view|action, as_of, as_of_iso, took_ms, data, error, error_kind}
```

Exit codes: `0` ok, `1` the read or write failed, `2` bad request, `3` refused by design,
`4` confirmation required. The web layer maps `3` → 403, `4` → 428, `1` → 502. A contract version
the web layer does not know is a 500, never a silent render of the wrong shape.

`as_of` is set by the gateway, not by the browser, so "read 4s ago" is the age of the *data*.

Store.Api internal endpoints are key-gated: header `X-Internal-Key`, value
`STORE_INTERNAL_API_KEY` (`Store.Api/Program.cs:465`, `:703`, `:803`, `:921`). The key never
reaches the browser and never reaches Node — the Python gateway holds it.

**Not built:** facets, copy, re-vet and republish have no action yet. `/tools` shows their
commands. Prices are refused by design (§7).

---

## 5. Auth

Single operator, one shared password, exactly as Streamlit does today
(`control_center/auth.py`, env `CONTROL_CENTER_PASSWORD`, timing-safe compare, fail closed).
This console reuses the same environment variable so there is one password to remember.

- The password is checked in a Next.js API route, never in client JavaScript.
- Success sets an `HttpOnly`, `SameSite=Strict`, `Secure=false` (tailnet HTTP) session cookie
  signed with `CONTROL_CENTER_PASSWORD` as the key. Expiry 12 hours.
- **Fail closed.** If `CONTROL_CENTER_PASSWORD` is unset the app refuses every route including the
  login page, and says why. An unconfigured portal is locked, not open. This is why
  `scripts/install_control_center_agent.sh` refuses to install a plist without the variable —
  `KeepAlive` would otherwise restart a fail-closed portal forever.
- **The network is the real fence.** The app binds one tailnet address, never `0.0.0.0`. A
  password-only portal on whatever cafe wifi the laptop joins is not acceptable, and a single
  address bind is what prevents it. Loopback deliberately does not answer; use the MagicDNS name
  at the desk too.
- Multi-user is out of scope. The intent log already carries `actor`, so adding accounts later is
  an auth change, not a redesign.

---

## 6. Write safety

Four rules, and they are all enforced in the writer, never in the button. A fence in the keyboard
is a fence a second caller walks around.

1. **Every write is two steps.** Step one returns a *preview*: what will change, from what to
   what, and what it affects. Step two applies it and requires a `confirm` token that the preview
   issued. A `POST` with no token is refused with the preview, never applied.
2. **Every write carries a nonce and is idempotent by stored nonce.** A double-tap on a phone
   keyboard cannot arm a pause someone has since cleared. Not a TTL cache — a stored nonce
   (`idempotency-keys-expire-they-are-not-dedup`).
3. **Every write appends to `store/ops/intents.jsonl`** with actor, action, arguments, applied
   yes/no, and the refusal reason when refused. Refusals are logged too; a refusal nobody can see
   reads as a broken button.
4. **Destructive writes are not on this surface at all.** `scripts/reconcile_orphan_index.py`
   deletes index rows. It is listed on `/tools` with its command and is not runnable from the web.

### 6.1 Class table

| Class | Example | Console behaviour |
|---|---|---|
| `READ_ONLY` | every `GET` above | no confirm |
| `MUTATES_STORE` | pause / resume | preview names the scope and the role it stops; one confirm |
| `MUTATES_CONFIG` | wave size, spend cap, provider chain, `moat_primary` | preview shows the **exact line diff** from `yaml_surgery`; confirm; certification drops to `certified: false` on a moat-affecting key |
| `MUTATES_PROD` | unlist / relist / republish | preview names the pack and the buyer-visible effect; confirm requires typing the pack id |
| `MONEY_RAIL` | price change | **not implemented** — §7 |
| `DESTRUCTIVE` | index reconciliation | not on this surface |

### 6.2 The config-write fences that already exist and must not be bypassed

`config_editor.write_config` is the only config writer this console calls, because it carries six
fixes that cost real incidents (`OPS_CONSOLE_PROGRAM.md` §14.11 T0-1…T0-6):

- `yaml_surgery.rewrite` edits single scalar lines and refuses anything else. A re-serialise
  destroyed 1,173 comment lines — the estate's entire calibration record.
- `validate_config` requires each hard gate key to be a real check name with a non-empty verdict
  list. The old form staged `[{"k": True}] × 6` and validation waved it through.
- The operator chain is validated against `operator.BUILDABLE_TIERS`, read from the builder.
- Refusals happen **before** the write, so `config.yaml` never enters the daemon's code
  fingerprint in a broken state and never auto-deploys itself at the next tick.
- History is JSON lines, and `MOAT_AFFECTING_KEYS` names paths that actually exist.

**The console adds no second config writer.** If a key cannot be reached through
`write_config`, the console shows it read-only and names the CLI that can change it.
**Any path that writes YAML without going through `yaml_surgery` is a defect.** That includes a
"fallback" serialiser, a templated rewrite, and a shell-out to `sed`. There is no acceptable
version of it: `yaml.safe_dump` on this repo's `config.yaml` measured 2034 lines in and 981 out,
destroying 1173 comment lines, among them founder directives and calibration receipts.

### 6.3 Editing a brain is a different class of write

`operator`, `moat_primary` and `noncritical_operator` decide which model rules a verdict. That is
the highest blast radius in the portal, so those three are not a casual dropdown:

- they are flagged `high_blast` in `KNOBS` and rendered with a distinct warning tone;
- `config_editor.is_moat_affecting` is surfaced **prominently** on the preview, not in small print;
- the confirm step names, in words, what will change and what stops being trusted-final;
- an extra acknowledgement is required beyond the ordinary confirm token, so the two-tap path that
  changes a spend cap cannot also change who rules a verdict;
- the preview repeats that a moat-affecting change drops certification to `certified: false`.

### 6.4 Four knobs the safe writer cannot reach — measured, not assumed

Running the real rewriter over the live `config.yaml` (2026-08-16):

| Knob | Writable? |
|---|---|
| `retrieval.provider`, `retrieval.backstop_only_providers`, `retrieval.min_relevance` | yes |
| `retrieval.minimax_concurrency`, `retrieval.claude_concurrency` | yes |
| `generation.candidates_per_signal` | yes |
| `spend.daily_cap_usd` | yes |
| `operator`, `moat_primary`, `noncritical_operator` | yes |
| `schedule.batch_size` | **no** — "could not locate a single scalar line" |
| `schedule.lease_ttl_s` | **no** — same |
| `schedule.backlog_cap` | **no** — same |
| `schedule.gate_generation_on_grounding` | **no** — same |

The cause is one thing: `schedule:` is written as a multi-line **flow** mapping (`{a: 1, b: 2}`
across several lines), and `yaml_surgery` edits a scalar that occupies its own line. It refuses
rather than guessing, which is the correct behaviour and is why nothing was worked around here.

**Wave size is the knob the founder named first, and it is currently read-only in the portal.**
Two candidate fixes, both outside this session's fence:

1. Convert `schedule:` in `config.yaml` to a block mapping. One-line-per-key, no semantic change,
   and every knob under it becomes writable immediately. `config.yaml` is owned by another session
   right now, so this was not done.
2. Teach `yaml_surgery` to locate and rewrite a single key inside a flow mapping. Larger change,
   needs its own tests, and touches the one file whose failure mode is silent comment loss.

No fallback writer was added. The screen shows these four with their current values and the
refusal reason.

---

## 7. Prices — specified, deliberately not built

**I stopped before writing any price code.** No file under `prospector/bridge.py`, `publish/`, or
any Stripe path was read for modification or changed. `/api/ops/catalogue/[id]/price` does not
exist; the pack screen renders price and price history read-only and links to the CLI.

### 7.1 Why the fence is there

`bridge.py` is the money rail. One `PriceDecision` mints the Stripe Price object **and** writes the
catalogue row, in one operation, so the two cannot drift. A drift charges the buyer at one price
and then fails the fulfilment fence at another. Two recorded incidents say this is not theoretical:
the catalogue took the fallback while the rail took the decision (£49), and a price change broke
fulfilment.

### 7.2 The flow, in full, for whoever builds it

1. **Read.** The pack screen already shows: current price, currency, rung index, the segment
   (`ambition_tier × market`) that chose it, and the price history from
   `GET /internal/catalog/{id}/price-history` (`Store.Api/Program.cs:1268`) joined to the local
   rationale record. `tools/price_history.py` is the existing reader; the screen renders what it
   renders.
2. **Choose a rung, never a number.** The form offers only the rungs declared in
   `config.yaml listing.pricing` for that segment. There is no free-text price input anywhere in
   the design. A continuous price is not a thing this system has.
3. **Preview.** Show: old rung → new rung, old pence → new pence, currency, the Stripe price id
   that will be superseded, and the count of live entitlements bought at the old price. A reason
   string is required — the API already refuses an unexplained change on the listing door and the
   price door should be no weaker.
4. **Confirm** by typing the pack id.
5. **Apply through `bridge.py` only.** One call, one `PriceDecision`, which mints the new Stripe
   Price and PATCHes `/internal/catalog/{id}/price` (`Program.cs:1057`) as one operation. The
   console must not call the PATCH endpoint directly; doing so writes the catalogue row while
   Stripe still holds the old price, which is the drift itself.
6. **Receipt.** Old price, new price, new Stripe price id, actor, reason, timestamp, appended to
   `store/ops/intents.jsonl` and readable at `/audit`.
7. **Verify.** After apply, re-read `/internal/catalog/{id}` and the Stripe price and assert they
   agree. A price change that reports success without that check is the failure mode.

### 7.3 What must be decided before it is built

- Does an in-flight checkout session at the old price get honoured? There are 168 expired sessions
  in the record and a scan that ignored status once already got this wrong.
- Do existing entitlements need any action at all? Current belief: no, entitlement is to content,
  not to a price. That belief needs a receipt before code ships.

**Recommendation: build the price change as a CLI-first flow** (`tools/set_live_pack_price.py`
already exists with `--pack`, `--to`, `--reason`, `--apply`) and give the console a *preview and a
copyable command* rather than an apply button, until the two questions above have answers.

---

## 8. Every operator CLI, and which screen exposes it

This table is the proof the inventory was taken rather than invented. `R` = read-only, `W` =
writes. "Screen" is where the console surfaces it; **Run** means the console can execute it,
**Show** means the console displays the command and the tool's own output is read elsewhere.

### 8.1 Engine

| Tool | Purpose | Class | Screen |
|---|---|---|---|
| `prospector.run vet` | vet one idea end to end | W | `/tools` Show |
| `prospector.run vet --resume` | re-vet the waiting rows | W | `/catalogue/[id]` Run, `/queue` Show |
| `prospector.run signal` | invent candidates from a signal | W | `/tools` Show |
| `prospector.run generate` | bounded generation batch | W | `/tools` Show |
| `prospector.run consume` | drain the queue | W | `/tools` Show |
| `prospector.run discovery` | stochastic discovery run | W | `/tools` Show |
| `prospector.run reprice` | re-vet published packs against pricing | W | `/tools` Show |
| `prospector.run report` | catalogue / metrics / costs / trend | R | `/metrics` (replaced by `ops.metrics`) |
| `prospector.run diagnose` | system diagnostics | R | `/tools` Show |
| `prospector.run operator` | operator state and quotas | R | `/engine` (replaced by `provider_view`) |
| `prospector.run lanes {add,remove,set}` | manage ambition lanes | W | `/tools` Show |
| `prospector.run markets {show,probe,open,close}` | manage markets | W | `/tools` Show |
| `prospector.scheduler.run_scheduled --daemon` | the producer loop | W | `/engine` Show (launchd owns it) |
| `prospector.consumer` | the drain loop | W | `/engine` Show (launchd owns it) |
| `touch/rm store/scheduler/PAUSE*` | the three stop switches | W | `/engine` **Run** via `ops.pause` |
| `python -m prospector.ops.routing set` | who may rule finally | W | `/engine` **Run** |
| `python -m prospector.ops.readmodel` | queue / pause / providers | R | `/`, `/queue` **Run** |
| `python -m prospector.ops.metrics` | outcome metrics | R | `/metrics` **Run** |
| `python -m prospector.ops.spend` | spend split vs cap | R | `/spend` **Run** |
| `python -m prospector.ops.runs` | run and candidate internals | R | `/runs` **Run** |
| `scripts/watch_engine.py` | live producer/consumer viewer | R | superseded by `/` |
| `tools/spend_today.py` | today's spend vs cap | R | superseded by `/spend` |
| `tools/govern.py` | run a command under a concurrency ceiling | R | `/tools` Show |

### 8.2 Publish and republish — the store admin ask

| Tool | Purpose | Class | Screen |
|---|---|---|---|
| `publish/publish.py` | the single publish entry point | W | called by the two below |
| `tools/publish_offline.py` | publish stored PASSes, no regeneration | W | `/catalogue` **Run** (republish) |
| `tools/publish_passes.py` | generate content then publish | W | `/catalogue` Show (costs model calls) |
| `tools/backfill_missing_listings.sh` | mass publish stranded PASSes | W | `/catalogue` Show — needs a review step first |
| `tools/unlist_killed.py` | unlist packs re-vetted to KILL | W | `/catalogue` **Run** (drain the unlist queue) |
| `tools/retire_rotted_passes.py` | retire PASSes whose citations rotted | W | `/catalogue` Show |
| `tools/verify_pass_shelf_coverage.py` | PASSes the shelf does not show | R | `/catalogue` **Run** (the stranded list) |
| `tools/verify_selling_catalogue.py` | every selling pack backed by a PASS | R | `/catalogue` **Run** (the red column) |
| `tools/preview_packs.py` | read any pack in full without buying | R | `/catalogue/[id]` Show |
| `tools/pack_defect_census.py` | count live packs carrying each defect | R | `/catalogue` Show |
| `tools/floor_signature.py` | count deterministic-floor copy on the shelf | R | `/catalogue` Show |
| `tools/pack_banner_probe.py` | live packs still showing a retired banner | R | `/catalogue` Show |

### 8.3 Backfill and repair

| Tool | Purpose | Class | Screen |
|---|---|---|---|
| `tools/backfill_facets.py` | tag packs with discovery facets | W | `/tools` Show |
| `tools/backfill_listing_copy.py` | replace floor copy with generated copy | W | `/tools` Show |
| `tools/backfill_bundle_html.py` | re-render a listed pack's zip | W | `/tools` Show |
| `tools/backfill_pack_currency.py` | repair £/$ on packs rendered before market | W | `/tools` Show |
| `tools/backfill_archived_url.py` | backfill archived source urls | W | `/tools` Show |
| `tools/backfill_audience.py` | copy audience tag into the index | W | `/tools` Show |
| `tools/backfill_market.py` | stamp legacy dossiers with market | W | `/tools` Show — **no rehearsal flag; banner says so** |
| `tools/sweep_shelf_copy.py` | re-grade and rewrite shelf copy | W | `/tools` Show |
| `tools/retitle_catalogue.py` | rewrite live pack titles | W | `/tools` Show |
| `tools/site_wide_dash_cleanup.py` | rewrite dashes in storefront source | W | `/tools` Show — commits to public source, never one-tap |
| `scripts/backfill_tiers.py` | fill `ambition_tier` on legacy dossiers | W | `/tools` Show |
| `scripts/backfill_price_anchors.py` | backfill cited price anchors | W | `/tools` Show |
| `scripts/reconcile_orphan_index.py` | delete index rows with no dossier | W | `/tools` Show — **DESTRUCTIVE, never runnable from the web** |
| `tools/review_figures.py` | human verification of untraceable figures | W | `/tools` Show |

### 8.4 Money rail — all Show, none runnable

| Tool | Purpose | Class | Screen |
|---|---|---|---|
| `tools/set_live_pack_price.py` | set one pack to a named rung | W money | `/catalogue/[id]` Show only |
| `tools/reprice_live_packs.py` | re-price packs with unbillable stub ids | W money | `/tools` Show only |
| `tools/reprice_to_charm_rungs.py` | move packs onto charm rungs | W money | `/tools` Show only |
| `scripts/backfill_ladder_prices.py` | move the catalogue onto the L1 ladder | W money | `/tools` Show only |
| `tools/depth_reprice_preview.py` | before/after for the depth ladder | R | `/tools` Show |
| `tools/price_history.py` | who moved a price and why | R | `/catalogue/[id]` Show |

### 8.5 Integrity, backup, probes

| Tool | Purpose | Class | Screen |
|---|---|---|---|
| `scripts/backup_store.py` | back up dossiers and ledger to R2 | W | `/tools` Show |
| `scripts/restore_drill.py` | prove the backup restores | R | `/tools` Show |
| `scripts/store_audit.py` | audit the operator's store | R | `/tools` Show |
| `scripts/blocker_probe.py` | which programme items are blocked | R | `/tools` Show |
| `scripts/load_gate.py` | is the machine fit to trust a test result | R | `/tools` Show |
| `scripts/popdd_verify.py` | the lane-aware proof runner | R | `/tools` Show |
| `scripts/site_spec_probe.py` | site spec ledger vs the tree | R | `/tools` Show |
| `scripts/graphify_sweep.py` | graph freshness scoreboard | W | `/tools` Show |
| `scripts/gen_budget_guard.py` | does generation fit its tick deadline | R | `/tools` Show |
| `scripts/guard_protected_deletions.py` | guard silent deletion of protected files | R | `/tools` Show |
| `scripts/unit_economics.py` | cost per pack | R | `/spend` Show |
| `tools/generation_survival.py` | survival by generation axis | R | `/metrics` Show |
| `tools/citation_quality_by_provider.py` | which provider gave the evidence | R | `/metrics` Show |
| `tools/meta_shape_monitor.py` | are one-liners collapsing into one cluster | R | `/metrics` Show |
| `tools/audit_swallow_sites.py` | rank swallowed failures by blast radius | R | `/tools` Show |
| `tools/prove_diversity.py`, `tools/prove_reliability.py` | proof harnesses | R | `/tools` Show |
| `tools/make_kill_log.py`, `tools/make_sample_report.py` | bake public artefacts | W | `/tools` Show |
| `tools/experiments/*` (36 files) | one-off experiment harnesses | R | not surfaced — not operator tools |

---

## 9. Mobile layout

The founder uses this from a phone, often through a link opened inside Telegram, which is a
WKWebView and not Safari. Design rules, all of them testable:

1. **390px is the design width, 320px is the floor.** No horizontal page scroll at either. Wide
   things — tables, charts, code, long ids — scroll inside their own `overflow-x: auto`
   container, and the container is visibly inset so it reads as scrollable.
2. **Cards, not tables, below 640px.** A run row on a phone is a card with four labelled lines
   (started / took / ended / ago), not a row in a grid the operator has to pan across.
3. **44px minimum tap target** (WCAG 2.5.8), and the same for the spacing between two destructive
   controls.
4. **One glance, no scroll, on `/`.** Status line plus four tiles plus alarms fits above the fold
   at 390px × 640px of usable height.
5. **Spacing scale 8 / 16 / 24 / 40 / 64**, from `docs/MOBILE_DESIGN_BRIEF_2026-08-15.md`. Section
   gaps cap at the largest step.
6. **12px minimum type**, ever, anywhere.
7. **Every screen states when its data was read.** An `as-of` line, in words (`read 4s ago`), and
   it goes amber past 60 seconds. Stale data that looks live is the defect this console has had
   repeatedly.
8. **No WebView-hostile CSS.** No `position: sticky` inside any ancestor that has
   `overflow: hidden` — that combination silently kills every descendant sticky. No `100vh`
   (Telegram's webview chrome makes it wrong); use `100dvh` with a `100vh` fallback. No entrance
   fade on above-the-fold content — it makes LCP wait for the animation.

### 9.1 Design tokens

The console imports the storefront's own tokens (`Store.Web/src/styles/tokens.css`) rather than
inventing a palette. Voice and typography follow `docs/SITE_SPEC_PROGRAM.md`: Switzer for
human-written text, Commit Mono for engine output, 2px radius everywhere, no pills, no box
shadows, depth from surface steps and hairlines.

**The one deliberate divergence, and why.** SITE_SPEC §3 proposed a dark palette and the founder
rejected exactly that one thing: *"apart from the dark we need all the other design requirement
fulfilled."* The storefront therefore ships light. **The console ships light too**, for the same
reason and to keep one token file. The console is not a place to re-litigate a rejected palette.

Verdict colours (`--succeed`, `--survive`, `--kill`, `--danger`, `--warning`) carry engine
meaning and are used only on engine output, never as decoration.

---

## 10. Tests

| What | How | Where |
|---|---|---|
| Auth, view allow-list, `as_of`, no-store, error mapping | vitest | `tests/read.test.ts` |
| No write applies without a confirm token; no price action exists | vitest | `tests/act.test.ts` |
| Cookie shape, fail-closed, expiry, forged tokens | vitest | `tests/session.test.ts` |
| No engine metric derived in TypeScript; TS view/action names are a subset of the Python registries | vitest source scan | `tests/pages.test.ts` |
| The confirm token's field name | vitest | `tests/contract.test.ts` |
| The Python gateway and every fence in it | pytest | `tests/ops/test_console_api.py` |
| Mobile: no horizontal scroll at 390px and 320px, 44px controls, 16px inputs | playwright | `e2e/mobile.spec.ts` |
| Build | `npm run build`, exit status captured before any pipe | — |

**Two honest limits, both stated in the test files themselves.** `tests/pages.test.ts` is a source
scan: it can prove no page imports `fs`, `child_process` or `path`, and it cannot prove no number
is computed in TypeScript. And the mobile run uses **Chromium**, not WebKit: `playwright install
webkit` reports the mac14 WebKit build is frozen, and driving it from Playwright 1.62.1 fails at
`newPage` with "Unknown setting: PushAPIEnabled". Width, overflow and tap size are still measured;
WebKit-only layout bugs are not.

---

## 11. Build order and status

| # | Step | Status |
|---|---|---|
| 1 | This spec | done |
| 2 | `prospector/ops/console_api.py` — the gateway | done |
| 3 | Read-only screens: `/`, `/queue`, `/runs`, `/runs/[id]`, `/spend`, `/metrics`, `/catalogue`, `/catalogue/[id]`, `/tools`, `/audit` | done |
| 4 | Engine controls: pause / resume, `moat_primary`, every knob in §3.8 | done, minus the four knobs of §6.4 |
| 5 | Catalogue writes except price: unlist / relist | done. Republish, re-vet, facets and copy are **not built** — commands shown on `/tools` |
| 6 | Prices | **spec only, §7** |

### 11.1 How to run it

```bash
export CONTROL_CENTER_PASSWORD='<a secret>'
scripts/run_ops_console.sh          # production build, bound to the tailnet address only
scripts/run_ops_console.sh dev      # hot reload, same binding
OPS_CONSOLE_HOST=127.0.0.1 scripts/run_ops_console.sh   # desk only
```

The script refuses to start without the password, and refuses to bind `0.0.0.0`. The interpreter
for the gateway comes from the script (`PROSPECTOR_PYTHON`), never from a path literal inside the
app — a literal joined to `process.cwd()` becomes a build-time file dependency under Turbopack,
and `.venv/bin/python` is a symlink out of the project root in a worktree, which failed
`next build` outright.

### 11.2 Running it permanently (launchd)

Installed 2026-08-16 as `com.prospector.ops-console`. It starts at login and restarts if it dies.

| Thing | Value |
|---|---|
| URL | `http://100.93.240.113:8611` (tailnet only) |
| Password | `test` (interim, set in the plist) |
| Agent | `~/Library/LaunchAgents/com.prospector.ops-console.plist` |
| Logs | `/tmp/ops-console.out.log`, `/tmp/ops-console.err.log` |

```bash
launchctl list | grep ops-console                       # is it loaded (pid, exit code)
launchctl kickstart -k gui/$(id -u)/com.prospector.ops-console   # restart it
launchctl bootout gui/$(id -u)/com.prospector.ops-console        # stop it
```

To change the password, edit `EnvironmentVariables.CONTROL_CENTER_PASSWORD` in the plist and
`bootout` then `bootstrap` the agent. `launchctl kickstart` alone does NOT re-read the plist.

Three things the plist must not lose:

1. **It execs `/usr/local/bin/node` directly, not `scripts/run_ops_console.sh`.** launchd runs a
   shell script through `/bin/bash`, and bash has no TCC grant for `~/Documents` on this Mac, so
   the agent dies with `Operation not permitted` before the first line runs. The same trap is
   documented for the Streamlit agent in `scripts/install_control_center_agent.sh`.
2. **The tailnet address is pinned in the plist**, because the app is started by launchd and there
   is no shell to resolve it. Re-run the install when the tailnet address changes.
3. **`PROSPECTOR_ROOT` and `PROSPECTOR_PYTHON` are set in the plist**, since the launcher script
   that normally sets them is bypassed. Without them the gateway cannot run the engine.

The app currently runs from the worktree at
`.claude/worktrees/agent-aaecfffaa54620133/store_platform/src/Ops.Console`. That path is in the
plist. Moving the console into the main checkout means reinstalling the agent.

## 12. Status ledger

Append receipts here, newest last. A row without a command output is not a receipt.

**2026-08-16 — first working build of the console.**

| Command | Result |
|---|---|
| `npx tsc --noEmit` | clean, no output |
| `npm run build` | `BUILD_EXIT=0`, 18 routes |
| `npx vitest run` | 5 files, 46 tests passed |
| `.venv/bin/python -m pytest tests/ops/test_console_api.py -p no:randomly -q` | 24 passed |

**2026-08-16 — the mobile run found three real defects, not one.**

1. `playwright.config.ts` used `import.meta.url`; Playwright compiles the config to CommonJS, so
   the config never loaded and zero tests ran. The run that "passed" had run nothing.
2. WebKit cannot be driven on this machine (frozen mac14 build). Switched to Chromium emulation
   and recorded the limit in §10.
3. `/spend` pushed the page 90px sideways at 390px. Cause: the "No burn rate" reason is engine
   prose carrying a long unbroken token, rendered 446px wide inside a 342px card. Fixed with
   `wrap-any`. The sign-out control measured 18px tall against a 44px floor, and the nav tabs 36px;
   both now 44px.
4. At 320px `/` still pushed 19px. Cause: the card header's as-of slot was `shrink-0`, so
   "read under a second ago · took under a second" could not wrap. The header now wraps.

**2026-08-16 — everything green.**

| Command | Result |
|---|---|
| `npm run build` | `BUILD_EXIT=0` |
| `npx tsc --noEmit` | `TSC_EXIT=0` |
| `npx vitest run` | 5 files, 46 tests passed |
| `.venv/bin/python -m pytest tests/ops/test_console_api.py -p no:randomly -q` | 24 passed |
| `npx playwright test` (both viewports) | `E2E_EXIT=0`, 6 passed |

**2026-08-16 — launched permanently on the tailnet.** Real route count is 16 compiled routes
across 13 screens; the "18 routes" row above counted build output including API handlers.

| Command | Result |
|---|---|
| `launchctl list \| grep ops-console` | `28626  0  com.prospector.ops-console` (running, last exit 0) |
| `lsof -nP -iTCP:8611 -sTCP:LISTEN` | `node 28626 … 100.93.240.113:8611 (LISTEN)` — tailnet only, not `*` |
| `curl /login /  /engine /queue /spend` | `200 200 200 200 200` |
| `POST /api/ops/session {"password":"nope"}` | `HTTP 401 {"ok":false,"error":"That password did not work."}` |
| `POST /api/ops/session {"password":"test"}` | `HTTP 200 {"ok":true,"signed_in":true}` |
| `GET /api/ops/read/{status,queue,providers,routing,spend,metrics}` | all `HTTP 200`, 543–11472 bytes of live engine data |
