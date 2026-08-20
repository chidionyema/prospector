# The estate: how it all hangs together

**Live status is a command, not this file.** Run `python3 scripts/estate_map.py`. It prints every
component, whether it answered, and where its state lives. This document explains what those rows
*mean* and how the parts connect — the things a probe cannot print.

Written 2026-08-18, the day the engine moved to Fly and the day the working trees vanished off the
laptop. Both events are in here, because both taught the estate something.

**Looking for your half of it?** [docs/personas/](personas/) is the same estate written twenty times,
once per seat: founder, analyst, finance, ops, SRE, security, legal, developer, senior, principal,
architect, QA, ML engineer, data engineer, product, content, growth, support, the buyer, and someone
on day one. This file is the shared factual spine those documents point back at, so a fact lives here
once instead of drifting in twenty places.

**Where this estate is going:** the [GOLD STAR PLAN](https://claude.ai/code/artifact/ef6fe784-7f6c-4981-85cd-37dfbe40b696) (adopted 2026-08-20) is the target
platform — ten planes, one portability contract each, and the 55 requirements between here and
there. This file says what exists today; that page says what it is being built into. Source of
truth for it is [MIGRATION_AND_DR_PROGRAM.md](MIGRATION_AND_DR_PROGRAM.md) §10 and §11.

---

## 1. The one-page picture

There are four paths through this estate. Every component belongs to exactly one of them.

```
MAKING                 SELLING                    OPERATING              BUILDING
prospector-engine  ->  prospector-store-api  <->  prospector-engine  <-  GitHub Actions
      |                       ^                   (the ops console)      (4 runners, laptop)
      v                       |                        ^                       |
prospector-searxng      prospector-store-web           |                       v
Exa, MiniMax            (mumchimp.com)            prospector-hermes         Fly deploys
      |                       ^                   (Telegram, Otto)
      v                       |
  Cloudflare R2  ------------ (the file the buyer downloads)
```

- **Making** turns a research question into a pack. It runs on `prospector-engine`.
- **Selling** takes money and hands over the file. It runs on `prospector-store-api` and
  `prospector-store-web`.
- **Operating** is how a human sees and steers the other three. It is the ops console (served by
  the engine) and Hermes on Telegram.
- **Building** is how code gets from a laptop into production. It is GitHub Actions.

The failure that matters most: **making can stop for a day and nobody notices; selling cannot stop
for a minute.** `prospector-store-api` is the only component with a hard uptime requirement.

---

## 2. Making: how a pack comes to exist

`prospector-engine` — Fly, region `lhr`, `shared-cpu-2x:4096MB`, 20 GB volume `prospector_store`
mounted at `/data` (575 MB used as of 2026-08-18).

1. The scheduler wakes and picks candidates.
2. It grounds them against real sources: **SearXNG** (`prospector-searxng`, our own search, so no
   third-party rate limit sits in the critical path) and **Exa** (`EXA_API_KEY`).
3. It drafts and vets with **MiniMax** (`MINIMAX_API_KEY`). MiniMax stays — that is a founder
   decision, not an accident.
4. A pack that passes gets artifacts written under `/data/store`, and a line appended to the
   ledger `/data/store/prospector.jsonl`.
5. Publishing pushes the pack to the store API with `STORE_INTERNAL_API_KEY`, and the file itself
   to **Cloudflare R2** (`R2_ACCOUNT_ID`, `R2_BUCKET`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`).

Prove the ledger is moving:

```sh
fly ssh console -a prospector-engine -C "sh -lc 'wc -l /data/store/prospector.jsonl; \
  date -r /data/store/prospector.jsonl'"
```

**The engine is not on the laptop any more.** It moved 2026-08-18, 03:03:49 to 03:09:29, 5m40s of
downtime. Anything that still says otherwise is stale. The discriminator a process can check is
`FLY_MACHINE_ID` — set inside a Fly machine, unset on the laptop.

### When a candidate is parked: DEFER, and what unparks it

A DEFER is not a verdict. It means the engine could not reach an answer — the brain was benched,
the call raised, retrieval was down — so the row is put back rather than killed. `prospector/verify.py:580` and `prospector/verify.py:682`
set `retrieval_failed=True` on any verdict call that raises, and the DEFER gate at `prospector/verify.py:1145`
fires on it. This exists because the honest verdict on a check that never ran is "come back to it",
never "this idea is dead". Killing on an outage is a real defect this system has had:
`store/dossiers/2102bacc6dd75cf9.kill.json` is a candidate killed by our own quota exhaustion, in a
dossier that reads as fully reasoned.

**Nothing unparks a row automatically at the moment a brain recovers.** There is no event, no
webhook, no queue trigger. A separate process re-reads the parked rows on a timer:

| Who | What it does | Where |
| --- | --- | --- |
| `com.prospector.consumer` | the drain. Wakes on its own cadence, takes a batch of parked rows, re-vets each one, writes the outcome | `prospector/consumer.py` |
| `run.py::_cmd_resume` | the same work by hand: `python -m prospector.run vet --resume` | `prospector/run.py:2735` |
| `run.drainable` | the ONE definition of what counts as parked-and-workable | `prospector/run.py:2595` |

So the answer to "MiniMax is back, what happens to the deferred rows" is: the consumer picks them
up a batch at a time on its next pass, and the backlog falls over hours, not at once.

**The drain is trusted-only, on purpose.** `_cmd_resume` runs the health classifier at the default
`trusted_only=True`. Re-vetting a `provisional` row on a provisional brain re-stamps it
`provisional`: the row does not move and the money is spent. Generation may run into a provisional
tail; the drain may not.

**A drain that runs is not the same as a drain that works.** Measured on production 2026-08-18,
three consecutive consumer passes each recorded:

```
attempted 24, resumed 24, passes 0, kills 0, defers 24, leased_skipped 8, backlog 169, metered_usd 0.0
```

Twenty-four rows picked up, twenty-four parked again, backlog flat, nothing spent. The console
reported this as a healthy 37.8 rows an hour and "empty by 21:30", because the rate was built from
`resumed` — rows PICKED UP — which says nothing about whether any of them finished. That number was
a fiction. `readmodel.queue_view` now compares the backlog the consumer recorded on its oldest pass
in the window against the count now, and when rows are being resumed while the backlog does not
fall it refuses to give an ETA and says why. The Queue page shows the last few passes as a table,
so a column of parked-again rows against a flat backlog is visible as a shape rather than as a
claim.

**Where to look, in order.** Queue page → "What the consumer is doing right now" (phase, how long
it has been in it, pid), then "Is it moving?" (what came of the work, backlog then and now), then
"The last few passes". Engine page → the brains, which is where a bench shows up. On disk:
`store/scheduler/consumer_drains.jsonl` is one line per pass, `store/consumer_heartbeat.json` is
the live phase, and `prospector/consumer.py:487` `consumer_liveness` is the only thing that reads
that format — the alarm and the panel share it so they cannot disagree.

**Alive is not working.** The same afternoon the consumer sat in phase `draining` for 61 minutes
with pid 678 alive and sleeping, after passes that had taken 1m41s and 8m20s. Nothing anywhere
said so. `consumer_liveness` calls that state `late`, and the Queue page now renders it amber with
the sentence "it is alive but has been in 'draining' for 61 min without a new beat".

---

## 3. Selling: how money becomes a download

This is the money rail. Read this section before touching anything under `store_platform/`.

**`prospector-store-web`** — Next.js, two machines, no volume. It is `mumchimp.com`. It holds no
state at all, which is why it can run two machines with no coordination between them. The browser
talks to the API through its own `/api/store` proxy; the server talks to it directly.

**`prospector-store-api`** — .NET minimal API, one machine, 1 GB volume `store_data` at `/data`
(3.9 MB used). It is `api.mumchimp.com`: the Fly certificate is issued and DNS resolves
`api.mumchimp.com -> prospector-store-api.fly.dev`. It owns the catalogue, checkout, entitlements,
delivery and the audit trail.

The buyer's path, end to end:

1. Browser loads `mumchimp.com`, which reads `GET /catalog` from the API.
2. Buyer clicks buy. `POST /packs/{id}/checkout` creates a **Stripe** checkout session
   (`Stripe__ApiKey`).
3. Stripe takes the card. We never see it. **We are not PCI-scoped and must stay that way.**
4. Stripe calls back on `POST /webhooks/{provider}`, verified with `Stripe__WebhookSecret`.
5. The API writes **one outbox row per entitlement**. That row, not the webhook, is the
   idempotency guard — Stripe retries webhooks, and Stripe idempotency keys expire.
6. The buyer gets an email through **Mailjet** (`MAILJET_*`) with a link to `/orders/{token}`.
7. `GET /download/{token}` redirects to a presigned R2 URL. The file never passes through the API.

There are no customer accounts in the buying path. A buyer is a token in an email, not a login.
Google OAuth and the JWT keys (`Jwt__SigningKeyPem`, `Authentication__Google__*`) exist for the
**founder** surface (`/v1/founder/*`), not for customers.

Prove the rail is up:

```sh
curl -s -o /dev/null -w '%{http_code}\n' https://api.mumchimp.com/healthz/money-rail   # want 200
curl -s -o /dev/null -w '%{http_code}\n' https://api.mumchimp.com/catalog              # want 200
```

**`/health` does not exist on this API and never did.** The Fly health check is `GET /catalog`
(`store_platform/deploy/fly/api.fly.toml`). Probing `/health`, `/healthz` or `/` returns 404 from a
perfectly healthy machine. That 404 has been read as an outage more than once, including today.

---

## 4. Operating: how a human sees and steers it

**The ops console** is a Next.js app served by `prospector-engine` at
`https://prospector-engine.fly.dev/`, behind `CONTROL_CENTER_PASSWORD`. It reads about twenty JSON
views from `prospector/ops/console_api.py`. There is no separate console app and no laptop tunnel:
the Streamlit control centre was deleted permanently, and the tunnel was killed.

**Hermes** — HALF MIGRATED. Do not read this section as a description of where Hermes runs.

`prospector-hermes` exists on Fly with a 3 GB volume `hermes_state` at `/data`, and a machine has
been `started` since 2026-08-18. That is all that is true of it. Measured 2026-08-19:

- The app has emitted **no application logs at all** since it was created — only `New SSH session`
  lines. Nothing is running on it.
- **No committed file in this repo describes it.** Five of the six `prospector-*` apps have a
  `fly.toml`; this one has none, so it cannot be reviewed, rebuilt, or moved off Fly.
  `scripts/fly_estate_probe.py` is the probe that says so, and it exits non-zero today.
- The **laptop still runs all eleven Hermes launchd jobs** — `ai.hermes.gateway`,
  `ai.hermes.coordinator`, `ai.hermes.otto-server`, `ai.hermes.idle-engine`, `ai.hermes.rsi`,
  `ai.hermes.progress`, `ai.hermes.watchdog`, `ai.hermes.runaway-reaper`,
  `ai.hermes.submodule-backup`, `ai.hermes.selfcheck`, `ai.hermes.keepawake`. Hermes is still an
  on-premises dependency.

This paragraph previously asserted that the Fly app runs "cockpit, coordinator, otto-server,
progress, rsi and submodule-backup" under supervisord. That was prose written from an intention,
never from a probe, and it stood for a day while the opposite was true. It is the exact failure
the estate rule names: state is a probe, not a paragraph.

The Telegram surface is still the gateway rather than the cockpit. Where it RUNS is task R7, open.

Two things about the console, both learned the hard way on 2026-08-18:

- **A 200 from a view does not mean the page renders.** `useOps` fetches in the browser, so a render
  crash never touches the server. Two pages were taking the whole app down with "a client-side
  exception has occurred" while every JSON view returned `ok: true`. The console now posts browser
  crashes to `POST /api/ops/client-error`, so the next one lands in `fly logs` instead of being
  guessed at.
- **A deploy of `main` silently reverts a hand-deploy.** Console fixes were live at 09:45 and gone
  by 10:12, overwritten by CI shipping `main`. Hand-deploying from a worktree is futile while CI
  deploys `main`. The only durable fix is a merged pull request.

Prove a deploy actually carries your change — `DEPLOY_RC=0` and HTTP 200 do not:

```sh
fly ssh console -a prospector-engine -C "sh -lc 'find /app/store_platform/src/Ops.Console/.next \
  -name \"*.js\" -exec grep -l <a-string-only-your-fix-contains> {} +'"
```

---

## 5. Building: how code reaches production

Everything ships from GitHub Actions. Four workflows: `ci.yml`, `deploy-api.yml`, `deploy-web.yml`,
`e2e-live-smoke.yml`.

**CI runs on the Fly app `prospector-ci`** (lhr), which registers two Linux container runners
labelled `self-hosted,X64,heavy,Linux,container,fly`. R8 is done; it landed in #335.

The laptop's `mumchimp-mac`, `-2` and `-3` are **offline by founder decision. Do not start them.**
`mumchimp-mac-4` stays online with the `light` label. A queued pull request is almost always the
Fly fleet being busy, not a dead runner — that misreading cost a session on 2026-08-19, when an
agent read three offline Mac jobs as halved capacity and told the founder to `launchctl kickstart`
them.

Never trust this paragraph. Ask:

```bash
gh api repos/chidionyema/prospector/actions/runners \
  --jq '.runners[] | "\(.name) \(.status) busy=\(.busy) \(.labels|map(.name)|join(","))"'
fly status -a prospector-ci
```

`scripts/process_audit.py` grades the same question on `/processes`, and `scripts/estate_map.py`
reports how many online runners are on Fly and how many on the laptop.

Self-hosted minutes are free. **Do not flip CI to GitHub-hosted.** Deleting `CI_RUNS_ON` is an
emergency lever, not a convenience.

The runner app holds `GITHUB_RUNNER_PAT` and `RUNNER_LABELS` and **nothing else** — a runner
executes code from every pull request, including one an outsider opened, so it must never hold a
money key. The PAT is fine-grained, *Only select repositories → prospector*, *Repository →
Administration → Read and write*, and nothing more.

Deploy credentials are per-app Fly tokens, because a Fly deploy token is scoped to its app:
`FLY_API_TOKEN` (web), `FLY_API_TOKEN_API`, `FLY_API_TOKEN_ENGINE`.

Rules that exist because breaking them cost real time:

- **Never merge while a check is queued or in progress.** GitHub keeps one run pending per
  concurrency group; merging evicts the waiter and cancels runs that were about to pass.
- A `guard` job that dies in seconds during `git fetch` with `The operation was canceled` was
  **cancelled by another merge**, not broken. Rebase onto the new `main` and force-push.
- **Never stage every file in a worktree.** `store/` and `storage/` are tracked runtime state that
  pytest writes to, so a blanket stage commits another process's test output. Stage explicit paths.

---

## 6. Where every byte of state lives

| What | Where | Size now | If it is lost |
|---|---|---|---|
| Packs, ledger, candidate DB | `prospector-engine` vol `prospector_store` at `/data` | 575 MB of 20 GB | The whole back catalogue. Backed up to R2. |
| Orders, entitlements, catalogue | `prospector-store-api` vol `store_data` at `/data` | 3.9 MB of 974 MB | Every sale ever made. This is the one that must not be lost. |
| Hermes state, coordinator DBs | `prospector-hermes` vol `hermes_state` at `/data` | 27 MB of 2.9 GB | Agent history. Annoying, not fatal. |
| The files buyers download | Cloudflare R2 | — | Delivery stops. Not on Fly, so it survives Fly. |
| Storefront | `prospector-store-web` | none | Nothing. It is stateless by design. |

`prospector-store-web` holding no state is the reason it can run two machines. Do not give it one.

Two data traps already paid for:

- **SQLite sidecars do not match a `*.db` glob.** A `.dockerignore` that excludes `*.db` still
  ships `state.db-wal`. On 2026-08-18 Hermes ran for 72 minutes on a 1.9 MB write-ahead log with no
  database behind it. Ship neither or ship both.
- **`with sqlite3.connect(...)` does not close the connection.** It only ends the transaction.

---

## 7. Where every secret lives

No secret value is in git, in this file, or in any `fly.toml`. Every one is a Fly app secret or a
GitHub Actions secret. `python3 scripts/estate_map.py` prints the NAMES per app, which is exactly
what you need to rebuild the estate somewhere else. As of 2026-08-18: engine 14, store-api 24,
hermes 29, store-web 0, searxng 0.

The one secret that exists nowhere but this laptop: **`~/.config/prospector/age-key.txt`**. Copy it
somewhere off this machine. Everything encrypted at rest is unreadable without it.

---

## 8. What still depends on this laptop

After the Fly cutover, this is the honest list:

Re-measured 2026-08-20 by running the command at the foot of this section, because the list
below had drifted in both directions.

- The **`ai.hermes.*` launchd jobs that are actually loaded**: `keepawake`, `idle-engine`,
  `lease-guard`, `runaway-reaper`. Those four, and no others.
- The **`com.prospector*` jobs**: `offsite-backup`, `backup`, `launchd-held`, `process-audit`,
  `log-rotation`, and the `com.prospector-control.*` set — `failover-watch`, `receipt-bridge`,
  `standby-sync`.

Two entries that used to be on this list are NOT on it, and both were wrong in a way that
would have sent someone looking for a process that does not exist:

- **The CI runners are not here.** `launchctl list` shows no `actions.runner.*` entry at all,
  and `ops/launchd/` defines no runner job. They run on Fly.
- **`ai.hermes.gateway`, `coordinator` and `otto-server` are not running on this laptop.**
  The gateway plist carries `<key>Disabled</key><true/>`, set on 2026-06-25 during the Phase 0
  estate surgery. The other two are not registered with launchd at all — `launchctl print`
  answers "Could not find service". The claim that "the laptop copies are still the ones
  running" was true once and stopped being true two months ago.

Nothing a customer touches depends on the laptop any more. That was the point of the migration.

```sh
launchctl list | grep -E 'actions\.runner\.|ai\.hermes\.|com\.prospector'
```

---

## 9. Leaving Fly

The constraint is standing: no platform lock-in. What actually ties us to Fly today:

- Volumes. `fly volumes` is a Fly concept; elsewhere these are block devices or a bucket.
- `fly ssh console` inside operational scripts.
- The `FLY_MACHINE_ID` environment discriminator.
- Fly-issued TLS certificates for `mumchimp.com` and `api.mumchimp.com`.

What does **not** tie us to Fly: the images. Every component is a plain Docker image, its non-secret
config is in the repo (`store_platform/deploy/fly/*.toml`), and its secrets arrive as environment
variables. The chosen route is **Compose substrate plus adapters now, declarative infrastructure
later**. The proof that leaving works is a `docker compose up` of the whole stack on a laptop, with
domain names and secrets read from one declared place rather than retyped per provider.

---

## 10. Probes that lie

Every line here is a false answer this estate has actually given.

| The probe | What it said | The truth |
|---|---|---|
| `curl api.mumchimp.com/health` | 404, "the API is down" | There is no `/health` route. The check is `/catalog`. |
| `DEPLOY_RC=0` plus HTTP 200 | "the fix is live" | Proves a deploy happened, not that it carried your change. Grep the built chunk. |
| Every console JSON view `ok: true` | "the dashboard is healthy" | The crash was in the browser render. An API probe cannot see it. |
| `fly auth whoami` | prints the account | Passes on a dead token. Every real call still returns 403. |
| `launchctl list` inside a container | `FileNotFoundError` | launchd is macOS only. That is "could not ask", not "not running". |
| `git -C <path>` | operates on the wrong repo | An inherited `GIT_DIR` beats `-C`. Use `env -u GIT_DIR git -C`. |
| `cmd \| tail` exit status | 0 | That is tail's status. Capture the real one before the pipe. |
| `pytest` exit 0 | "tests pass" | Also what it prints when it collects nothing. |
| `dotnet test` exit 0 | "tests pass" | It has reported 0 while tests were failing. |
| A branch with "no PR" | "unmerged work" | Check closed and merged pull requests too, not only open ones. |

This is why `scripts/estate_map.py` has three states and not two. **"Could not ask" is not "fine".**
Collapsing it into either colour is how a dead component gets reported healthy.

---

## 10a. When one of them breaks

Fixing it is [`RUNBOOKS.md`](RUNBOOKS.md). Making sure the same class of thing does not break in
the next component along is [`INCIDENT_PROCESS.md`](INCIDENT_PROCESS.md), and the records are in
[`incidents/`](incidents/). The store-resolver incident is why §6 of this file exists in the shape
it does: the bug was never in one file, it was in four, and nobody swept for the fifth.

## 11. The working-tree trap (2026-08-18)

`~/Documents` is iCloud-synced with Optimize Storage on. `~/Documents/code` and
`~/Library/Mobile Documents/com~apple~CloudDocs/Documents/code` are two different real directories
(inodes 281733976 and 52862672, same device 16777220). When the disk hit 94% — 29 GiB free of
466 GiB — macOS evicted the local copies, and every active agent session lost its working tree
mid-task.

Nothing was deleted. The recovery is `rsync -a --update` from the iCloud path, which never clobbers
a newer local file. Do **not** re-clone: re-cloning discards uncommitted work, which is exactly what
was at risk.

One thing that must not be "fixed" during a recovery: `~/.claude/scripts/idle-guard.py` is a
**symlink** into `prospector/scripts/claude_guards/`. It was never missing — its target had been
evicted. Overwriting the symlink with a stub permanently disables the guard.

The durable fix is to stop working inside a synced directory. Working trees belong somewhere macOS
will not evict them.

---

## 12. Adding a component

Add a row to `FLY_APPS` in `scripts/estate_map.py` with one line saying what it is for, and a
section here saying which of the four paths it belongs to and what breaks without it. If it cannot
be probed, it does not go on the map. A component nobody can check is a component nobody can trust.
