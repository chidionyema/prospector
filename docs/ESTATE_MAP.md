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

**Hermes** — `prospector-hermes`, 3 GB volume `hermes_state` at `/data` (27 MB used). It is the
Telegram surface, and the front door is the gateway, not the cockpit. Under supervisord it runs
cockpit, coordinator, otto-server, progress, rsi and submodule-backup.

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

The runners are **four self-hosted runners on the laptop** — `mumchimp-mac`, `-2`, `-3`, `-4`, with
labels `self-hosted,macOS,X64,heavy` (`-4` is `light`). Self-hosted minutes are free. **Do not flip
CI to GitHub-hosted.** Deleting `CI_RUNS_ON` is an emergency lever, not a convenience.

`prospector-ci` exists on Fly and is suspended. It is the intended home for the runners (R8). That
work is not done, and it is blocked on one decision: where the runner registration credential
lives. When it happens, that app gets `GITHUB_RUNNER_PAT` and `RUNNER_LABELS` and **nothing else** —
a runner executes code from every pull request, including one an outsider opened, so it must never
hold a money key. The PAT must be fine-grained, *Only select repositories → prospector*,
*Repository → Administration → Read and write*, and nothing more.

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

- The **four CI runners**. No runner, no deploy. Selling keeps working; shipping stops. (R8)
- The **`ai.hermes.*` launchd jobs** — gateway, coordinator, otto-server and the rest. Hermes is
  deployed on Fly, but the laptop copies are still the ones running, and the Fly `gateway` process
  is stopped. The cutover is half done. (R7)
- The **`com.prospector-control.*` jobs** — failover-watch, receipt-bridge, standby-sync — and
  `com.prospector.backup`.

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
