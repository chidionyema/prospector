# Architect

**What this is.** A complete audit of how the estate hangs together: every deployable unit, every
data store, every seam between them, and the honest grade of each against the no-lock-in rule.
**Read this if** you are about to add a service, move a store, swap a provider, or answer "what
breaks if X dies".
**Everything below was measured on 2026-08-18.** Every claim carries a `file:line` or the command
that produced it. Where I could not prove something I wrote `HYPOTHESIS:` and the check that
would settle it.

This document extends [`../ESTATE_MAP.md`](../ESTATE_MAP.md). The map is the shared factual spine —
the four paths, the buyer path, the state table, the probes-that-lie table. This file does not
repeat it. It adds the seams, the grades and the blast radii. Where the two disagree, re-measure
and fix both.

Siblings: [`sre-on-call.md`](sre-on-call.md) (what to do at 3am),
[`senior-developer.md`](senior-developer.md) (how to change the code safely),
[`principal-developer.md`](principal-developer.md), [`security.md`](security.md),
[`data-engineer.md`](data-engineer.md), [`ops.md`](ops.md), [`README.md`](README.md).

---

## 0. Re-measure this document

Every number here came from these commands. Run them before you trust a sentence.

```bash
# The estate
fly apps list
for a in prospector-engine prospector-store-api prospector-store-web prospector-searxng \
         prospector-hermes prospector-ci; do fly machines list -a $a; fly volumes list -a $a; done
for a in prospector-engine prospector-store-api; do fly secrets list -a $a; done   # NAMES only

# The engine's own view of where it lives
fly ssh console -a prospector-engine -C \
  "/usr/local/bin/python -c 'from prospector import paths, config; print(paths.store_root(), config.store_root())'"

# Local
.venv/bin/python scripts/live_checkout.py       # daemon cwd, live HEAD vs origin/main, secrets
python3 scripts/estate_map.py                   # the generated inventory
launchctl list | grep -E 'prospector|hermes|runner'
du -sh /Users/chidionyema/Documents/code/prospector/store
```

---

## 1. The shape in one screen

```
                       ┌─────────────────────────────────────────────┐
   buyer ── HTTPS ────►│ prospector-store-web   (Next.js 16, 2 mach.) │  mumchimp.com
                       │   SSR + same-origin rewrite proxy            │
                       └───────────────┬─────────────────────────────┘
                                       │ /api/store/* → API_ORIGIN
                                       ▼
                       ┌─────────────────────────────────────────────┐
   Stripe ── webhook ─►│ prospector-store-api   (.NET 9, 1 machine)   │  api.mumchimp.com
                       │   SQLite /data/store.db  ·  outbox  ·  auth  │
                       └───────┬──────────────────────────┬──────────┘
                               │ presigned GET            │ internal API
                               ▼                          │ (STORE_INTERNAL_API_KEY)
                       ┌───────────────┐                  │
                       │ Cloudflare R2 │                  │
                       │  pack files   │                  │
                       └───────────────┘                  │
                                                          │
                       ┌──────────────────────────────────┴──────────┐
   founder ─ HTTPS ───►│ prospector-engine      (Python 3.14, 1 mach)│  prospector-engine.fly.dev
                       │   supervisord: scheduler, consumer, watchdog,│
                       │   backup, offsite-backup, ops-console :8611  │
                       │   volume prospector_store → /data (20 GB)    │
                       └───────┬─────────────────────────┬───────────┘
                               │ 6PN .internal            │ brains: MiniMax, Claude CLI
                               ▼                          ▼ retrieval: ddg, exa, claude_cli
                       ┌───────────────┐          (outbound HTTPS)
                       │ searxng :8080 │
                       └───────────────┘

   laptop: 4 GitHub Actions runners (launchd) + backup job + hermes estate
   prospector-ci: 3 Fly machines, shared-cpu-4x/8 GB, same runner labels
```

Four independent failure domains: the storefront pair (web+api+R2), the engine, the CI fleet, and
the laptop. Only one crossing is load-bearing in the money path: engine → store-api over
`STORE_INTERNAL_API_KEY`.

---

## 2. Complete inventory of deployable units

### 2.1 Fly apps

`fly apps list` on 2026-08-18:

| App | Status | Last deploy | Machines (`fly machines list`) | Volume |
|---|---|---|---|---|
| `prospector-ci` | deployed | 22m ago | `83d1d69bd119e8`, `8e4530a7712248`, `8ee06eb7701628` — all `shared-cpu-4x:8192MB` | none |
| `prospector-engine` | deployed | 1h20m ago | `80d34da6636478` — `shared-cpu-2x:4096MB` | `vol_42kyqo6g0kdzew14` `prospector_store` 20 GB lhr |
| `prospector-hermes` | deployed | 4h21m ago | `185e352b061638` — `shared-cpu-2x:2048MB` | none |
| `prospector-searxng` | deployed | 4h17m ago | `48e4545a96e7e8` — `shared-cpu-1x:512MB` | none |
| `prospector-store-api` | deployed | 7h20m ago | `48ee019fd74e58` — `shared-cpu-1x:512MB` | `vol_4ql6dzwjylqeygnr` `store_data` 1 GB lhr |
| `prospector-store-web` | deployed | 3h3m ago | `28629d6b710128`, `185d417f753d58` — `shared-cpu-1x:512MB` | none |
| `tie-api`, `tie-db`, `tie-smoke`, `tie-smoke-db`, `tie-web` | suspended | Jun 13 2026 | — | — |

Five `tie-*` apps have been suspended since 13 June 2026. They are dead weight, not architecture.
See §11 debt item D5.

**A measured discrepancy, unresolved.** `fly apps list` reported `prospector-ci` as `deployed`
above, but an earlier run in this same session reported it `suspended` while `fly status -a
prospector-ci` showed machines at v2. The two commands disagreed within one session.
`HYPOTHESIS:` app-level status lags machine state after an autoscale event. Check:
`fly status -a prospector-ci; fly machines list -a prospector-ci` back to back and compare the app
line to the machine lines. Do not treat `fly apps list` STATUS as the liveness answer — this is a
new row for the "probes that lie" table in [`../ESTATE_MAP.md`](../ESTATE_MAP.md).

### 2.2 prospector-engine — the maker

- **Language / runtime.** Python 3.14 on `python:3.14-slim-bookworm` (`deploy/engine/Dockerfile`,
  stage 2). Stage 1 is `node:22`, which builds the Ops.Console `.next` bundle.
- **Config.** `deploy/engine/fly.toml`: `app = "prospector-engine"`, `primary_region = "lhr"`,
  `[http_service] internal_port = 8611`, `auto_stop_machines = false`, `auto_start_machines = false`,
  `min_machines_running = 1`, `[mounts] source = "prospector_store" destination = "/data"`,
  `[[vm]] shared-cpu-2x / 4gb`, `[deploy] strategy = "immediate"`.
- **Env baked into the app** (`deploy/engine/fly.toml` `[env]`): `PROSPECTOR_STORE_DIR=/data/store`,
  `PROSPECTOR_USAGE_WALL_MARKER`, `CLAUDE_CONFIG_DIR`, `ENGINE_BACKUPS_ENABLED=true`,
  `STORE_API_URL=https://api.mumchimp.com`,
  `SEARXNG_URL=http://prospector-searxng.internal:8080`.
- **Processes.** One container, six supervisord programs (`deploy/engine/supervisord.conf`), by
  priority: `scheduler` (10), `consumer` (20), `watchdog` (30), `backup` (40), `offsite-backup`
  (50), `ops-console` (70). The console runs
  `node node_modules/next/dist/bin/next start -H :: -p 8611` — the only program bound to a port.
- **Stores.** `/data/store` on the 20 GB volume: `prospector.jsonl` (the ledger),
  `prospector.db`, `dossiers/`, `_cache/`, `scheduler/`, `listings/`, `markets/`, `launch/`.
- **Secret NAMES** (`fly secrets list -a prospector-engine`, 14): `CONTROL_CENTER_PASSWORD`,
  `ENGINE_BACKUPS_ENABLED`, `EXA_API_KEY`, `FLY_API_TOKEN`, `MINIMAX_API_KEY`,
  `PROSPECTOR_ENTITLEMENTS_API_KEY`, `R2_ACCESS_KEY_ID`, `R2_ACCOUNT_ID`, `R2_BUCKET`,
  `R2_SECRET_ACCESS_KEY`, `STORE_API_URL`, `STORE_INTERNAL_API_KEY`, `STRIPE_LIVE_API_KEY`,
  `SEARXNG_URL`. No values appear in this repo or this document.
- **Port.** 8611, public HTTPS via Fly's proxy. Auth is a shared password plus a five-strike
  limiter, not a network fence — see §2.5.
- **Who calls it.** The founder (console UI). Nothing else. It calls out to: store-api
  (`STORE_API_URL`), searxng over 6PN, and the model/retrieval providers over the internet.

### 2.3 prospector-store-api — the seller

- **Language / runtime.** .NET 9 (`store_platform/src/Store.Api/Store.Api.csproj:4` `net9.0`),
  minimal API.
- **Config.** `store_platform/deploy/fly/api.fly.toml`:
  `ConnectionStrings__DefaultConnection = "Data Source=/data/store.db"` (:28),
  `Email__WebBaseUrl = "https://mumchimp.com"` (:43), mount `store_data` → `/data` (:47-49),
  `internal_port = 8080` (:52), health check `GET /catalog` (:62), `shared-cpu-1x / 512mb`.
- **Store.** SQLite at `/data/store.db` on a 1 GB volume. EF Core migrations are applied at
  startup with `MigrateAsync` — `Program.cs:201-207`, with the comment explaining why not
  `EnsureCreated`.
- **Schema.** `store_platform/src/Store.Catalog/Persistence/StoreDbContext.cs:17` — an
  `IdentityDbContext`, 13 explicit DbSets: `Packs` (:20), `PackPriceHistory` (:21), `SalesAudits`
  (:22), `Orders` (:23), `Entitlements` (:24), `PendingDeliveries` (:25), `IdempotencyJournal`
  (:26), `WebhookEvents` (:27), `WaitlistSignups` (:28), `AnalyticsEvents` (:29), `UserProfiles`
  (:31), `RefreshTokens` (:32), `RevokedTokens` (:33) — plus the ASP.NET Identity tables the base
  class brings.
- **Secret NAMES** (`fly secrets list -a prospector-store-api`, 24): `R2_ACCESS_KEY_ID`,
  `R2_ACCOUNT_ID`, `R2_BUCKET`, `R2_SECRET_ACCESS_KEY`, `STORE_ALLOWED_ORIGIN`, `STORE_PUBLIC_URL`,
  `Store__EntitlementsApiKey`, `Store__InternalApiKey`, `Stripe__ApiKey`, `Stripe__WebhookSecret`,
  `STORE_STOREFRONT_URL`, `MAILJET_API_KEY`, `MAILJET_API_SECRET`, `MAILJET_FROM_EMAIL`,
  `Stripe__SmokeTestPriceId`, `Data__KeyRingPath`, `Jwt__Audience`, `Jwt__Issuer`,
  `Jwt__SigningKeyPem`, `Authentication__Google__ClientId`,
  `Authentication__Google__ClientSecret`, `Security__KnownNetworks`,
  `RateLimiting__PermitPerMinute`, `Founder__Emails`.
- **Port.** 8080 internal, public as `api.mumchimp.com`.
- **Who calls it.** The storefront (SSR and the browser through the rewrite proxy), Stripe
  (webhooks), the engine (internal publish/price endpoints), and the ops console (through the
  engine's `console_api`).

Route surface, all verified in the worktree:

| Route | Where | Note |
|---|---|---|
| `GET /catalog` | `Program.cs:258` | also the Fly health check |
| `GET /catalog/{id}` | `Program.cs:332` | the pack page's SSR source |
| `GET /healthz/money-rail` | `Program.cs:404` | reads `MoneyRailStatus` (registered `:107`) |
| `GET /catalog/stats` | `Program.cs:412` | |
| `POST /catalog/waitlist` | `Program.cs:435` | |
| `POST /internal/catalog` | `Program.cs:473` | engine publishes here |
| `PATCH /internal/catalog/{id}/facets` | `Program.cs:704` | |
| `PATCH /internal/catalog/{id}/copy` | `Program.cs:804` | |
| `PATCH /internal/catalog/{id}/listing` | `Program.cs:928` | the `IsListed` fence |
| `PATCH /internal/catalog/{id}/content` | `Program.cs:983` | |
| `PATCH /internal/catalog/{id}/price` | `Program.cs:1071` | money-adjacent |
| `GET /internal/catalog/{id}/content` | `Program.cs:1229` | |
| `GET /internal/catalog/{id}/price-history` | `Program.cs:1282` | who moved a price |
| `POST /entitlements` | `Program.cs:1417` | guarded by `Store__EntitlementsApiKey` |
| `GET /dev-content/{**key}` | `Program.cs:1449` | dev only, inside a conditional |
| `POST /packs/{id}/checkout` | `CheckoutEndpoints.cs:24` | |
| `POST /checkout` | `CheckoutEndpoints.cs:40` | |
| `POST /webhooks/{provider}` | `WebhookEndpoints.cs:13` | Stripe lands here |
| `GET /orders/{token}` | `DeliveryEndpoints.cs:29` | HTML order page |
| `GET /api/orders/{token}` | `DeliveryEndpoints.cs:30` | JSON |
| `GET /api/orders/by-session/{sessionId}` | `DeliveryEndpoints.cs:31` | post-Stripe landing |
| `GET /download/{token}` | `DeliveryEndpoints.cs:32` | 302 to a presigned R2 URL |

Plus `AnalyticsEndpoints.cs`, `BackupEndpoints.cs`, `FounderPreviewEndpoints.cs`,
`OpsEndpoints.cs` (`ls store_platform/src/Store.Api/Endpoints/`).

### 2.4 prospector-store-web — the shelf

- **Language / runtime.** Next.js 16 pages router, React 19, Node.
- **Config.** `store_platform/deploy/fly/web.fly.toml`: `internal_port = 3000` (:19),
  `min_machines_running = 2` (:43), health check `/api/health` (:53), `shared-cpu-1x / 512mb`.
  Two machines is the only redundancy anywhere in the estate.
- **Store.** None. No volume (`fly volumes list -a prospector-store-web` returns an empty table).
  Every byte it shows comes from store-api.
- **Secrets.** Zero (`fly secrets list -a prospector-store-web` is empty). Its configuration is
  `NEXT_PUBLIC_*` build args, which are baked into the bundle at image build time and are
  therefore public by construction. That is correct and deliberate: a storefront with no secrets
  cannot leak one.
- **The proxy seam.** `next.config.ts:107` `async rewrites()`; `:120`
  `{ source: "/api/store/:path*", destination: "${API_ORIGIN}/:path*" }` and `:121`
  `{ source: "/api/:path*", destination: "${API_ORIGIN}/v1/:path*" }`. The comment at `:111`
  records why order matters — rewrites are tried in array order.
  `src/lib/config.ts:158` sets `API_BASE_URL` from `NEXT_PUBLIC_API_URL` (dev fallback
  `http://localhost:5291`); `:179` sets
  `API_FETCH_BASE = typeof window === 'undefined' ? API_BASE_URL : '/api/store'`. Server-side it
  calls the API directly; browser-side it calls same-origin so httpOnly cookies survive.
- **Who calls it.** Buyers. Also `redirects()` at `:152-154` enforces the canonical host.

### 2.5 Ops.Console — the operating surface

This is the correction that matters most for anyone reading older comments. **The console is
deployed.** It runs inside the engine container on Fly and answers on the public internet over
HTTPS. `store_platform/src/Ops.Console/next.config.ts` says so in its header comment and explains
why: the console reads `store/prospector.db`, `store/scheduler/*`, `store/dossiers/*` and
`config.yaml` **as a directory**, so it must sit on the machine that mounts the volume. Store.Web's
image carries only `.next/standalone`, `.next/static` and `public/` and has no filesystem route to
any of it.

- **How it ships.** `deploy/engine/Dockerfile` stage 1 builds it on `node:22`; `:92-93` copies
  `.next` and `node_modules` into `/app/store_platform/src/Ops.Console`.
  `deploy/engine/supervisord.conf` program `ops-console` (priority 70) runs `next start -H :: -p 8611`.
  There is deliberately no `output: 'standalone'` (comment in `next.config.ts`).
- **The door.** A shared password in `src/lib/auth.ts`: `COOKIE_NAME = 'ops_session'` (:23),
  `configuredPassword()` (:26), timing-safe compare via hash-then-`timingSafeEqual` (:34-40),
  `mintSession` (:48), `sessionValid` (:53), cookie written `HttpOnly; SameSite=Strict` (:84),
  `requireAuth` (:105). Rate limit in `src/lib/ratelimit.ts`: `WINDOW_MS = 15 * 60 * 1000` (:13),
  `MAX_FAILURES = 5` (:14), keyed per address (`clientKey` :19).
- **The headers.** `next.config.ts` sets `X-Frame-Options: DENY`, `nosniff`, `no-referrer`,
  `X-Robots-Tag: noindex, nofollow, noarchive`, HSTS `max-age=31536000; includeSubDomains`, and a
  CSP with `frame-ancestors 'none'` and `connect-src 'self'`.
- **The gateway.** `src/lib/ops.ts:15` imports `spawn` from `node:child_process`; `:104` spawns
  `python -m prospector.ops.console_api` with args, in its own process group (`:108`) so a timeout
  can kill the tool and not the gateway. `pythonBin()` (`:41`) resolves the interpreter and its
  comment records the worktree symlink trap that broke `next build`.
- **The contract.** `prospector/ops/console_api.py:62` `CONTRACT_VERSION = 1`, echoed in every
  envelope at `:111`. The Node side pins the same number (`ops.ts:96`).
- **The surface.** 27 read views, allow-listed at
  `src/pages/api/ops/read/[view].ts:17-43`: `engine_location`, `status`, `queue`, `providers`,
  `routing`, `spend`, `money`, `data`, `metrics`, `runs`, `run`, `candidate`, `config`, `intents`,
  `tools`, `job`, `undo`, `catalogue`, `pack`, `shelf`, `method`, `content_rules`, `orders`,
  `order`, `sales`, `deliveries`, `disputes`. 16 actions allow-listed at
  `src/pages/api/ops/act/[action].ts:22-40`: `pause.arm`, `pause.disarm`,
  `routing.set_moat_primary`, `config.set`, `config.restore`, `catalogue.set_listing`,
  `shelf.repair_copy`, `shelf.publish_pending`, `shelf.regate`, `daemon.restart`, `tools.run`,
  `tools.undo`, `deliveries.resend`, `engine.switch`, `engine.arm`, `engine.disarm`.
  Price writes are refused in code with a pointer to the reason (`[action].ts:61-63`: the money
  rail is `prospector/bridge.py`, which must mint the Stripe Price and the catalogue row
  together).

An allow-list of exactly 27 reads and 16 actions is the strongest architectural property in the
estate: the console cannot invent a capability, and adding one is a reviewable diff in two files.

### 2.6 prospector-searxng — the retrieval backstop

`shared-cpu-1x:512MB`, no volume, no secrets. Reached only over the 6PN private network at
`http://prospector-searxng.internal:8080` (`deploy/engine/fly.toml` `[env] SEARXNG_URL`). Nothing
outside the organisation can address it.

### 2.7 prospector-hermes — the operator estate

`shared-cpu-2x:2048MB`, no volume, 29 secret NAMES (`AGENT_BROWSER_EXECUTABLE_PATH`,
`ANTHROPIC_API_KEY`, `BROWSERBASE_*`, `DEEPSEEK_API_KEY`, `EXA_API_KEY`, `GEMINI_API_KEY`,
`MINIMAX_API_KEY`, `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `RSI_SIGNING_KEY`, `STANDARDCOMPUTE_API_KEY`,
`STANDARD_COMPUTE_API_KEY`, `TELEGRAM_*` ×7, `TERMINAL_*` ×3, `*_TOOLS_DEBUG` ×4). A separate
system with its own repo and its own memory index; it is in this document because it is in the
same Fly organisation and shares the credit card, not because prospector depends on it.

**Note the secret-count asymmetry.** Hermes holds 29 secret names, more than the engine (14) and
close to store-api (24), including `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` and two
`STANDARD*COMPUTE_API_KEY` variants that look like a rename that never finished. Blast radius of a
hermes compromise is larger than its role suggests.

### 2.8 prospector-ci — the burst runner fleet

Three `shared-cpu-4x:8192MB` machines, no volume. They register as GitHub Actions self-hosted
runners with the same labels as the laptop runners, so a job lands on whichever is free.

### 2.9 The laptop

`ops/launchd/` holds 29 job definitions plus a `pending/` directory. They are JSON, not plists —
`scripts/launchd_plists.py` renders them. Grouped:

| Group | Files | Note |
|---|---|---|
| GitHub runners | `actions.runner.chidionyema-prospector.mumchimp-mac{,-2,-3,-4}.json` | 4 runners |
| Prospector | `com.prospector.{backup,consumer,live-update,offsite-backup,ops-console,scheduler,watchdog}.json` | 7 |
| Hermes | `ai.hermes.{cockpit,coordinator,gateway,idle-engine,keepawake,ngrok,otto-server,progress,rsi,runaway-reaper,submodule-backup,watchdog}.json` | 12 |
| Other estates | `com.chidionyema.{graphify-sweep,reflect}.json`, `com.estate.costsentinel.json`, `com.haworks.{continuous-review,test-coverage}.json`, `com.signalengine.daemon.json`, `com.tie.ai-review.json` | 7 |

Every `com.prospector.*` job runs from `/Users/chidionyema/Documents/code/prospector-live` and sets
`PROSPECTOR_STORE_DIR=/Users/chidionyema/Documents/code/prospector/store`. That split — code from
the live checkout, state from the developer checkout — is the whole point of the 2026-08-17 move,
and it is also the setting that the store-root bug in §4.3 defeats.

`launchctl list` on 2026-08-18 showed the four `actions.runner.*` jobs holding pids
39139 / 39171 / 39214 / 39246. The prospector `scheduler`, `consumer` and `ops-console` jobs were
**not loaded**; only `com.prospector.backup` and three `com.prospector-control.*` jobs were loaded,
with no pid. Read that as: generation now runs on Fly, and the laptop is a runner host with a
backup job. The launchd definitions for the daemons still exist and would start a second scheduler
against the same store if anyone loaded them. See §11 debt item D3.

---

## 3. Request path traces

### 3.1 Trace A — a buyer loads a pack page and receives the file

Twelve hops, each with its line.

1. **Browser → `https://mumchimp.com/pack/<id>`.** Fly anycast → `prospector-store-web`,
   `internal_port = 3000` (`store_platform/deploy/fly/web.fly.toml:19`), one of two machines
   (`:43 min_machines_running = 2`).
2. **Canonical host redirect** if the host is wrong — `next.config.ts:152-154`.
3. **SSR.** `store_platform/src/Store.Web/src/pages/pack/[id].tsx:1793`
   `export const getServerSideProps`. The page is server-rendered per request, not statically
   generated: price and `IsListed` must be current.
4. **Fetch target.** `src/lib/config.ts:179` — on the server this is `API_BASE_URL` (`:158`,
   from `NEXT_PUBLIC_API_URL`), so the SSR call goes straight to store-api. In the browser the same
   constant is `/api/store`, rewritten at `next.config.ts:120` to `${API_ORIGIN}/:path*`. Same
   origin, so the httpOnly session cookie is sent and never exposed to JS.
5. **`GET /catalog/{id}`** — `store_platform/src/Store.Api/Program.cs:332`. Reads `Packs` from
   SQLite (`StoreDbContext.cs:20`). A pack with `IsListed = false` does not render;
   the storefront never decides sellability locally.
6. **Buy.** `POST /packs/{id}/checkout` — `CheckoutEndpoints.cs:24`. The payment provider is
   resolved by key: `builder.Services.AddKeyedScoped<IPaymentProvider, StripeProvider>("stripe")`
   (`Program.cs:103`). Keyed DI is what makes the provider swappable without touching the
   endpoint.
7. **Stripe hosted checkout.** Off our estate. The buyer returns to a landing page that polls
   `GET /api/orders/by-session/{sessionId}` (`DeliveryEndpoints.cs:31`).
8. **Webhook.** `POST /webhooks/{provider}` — `WebhookEndpoints.cs:13`. Signature verified and
   parsed at `:34` `VerifyAndParseAsync`. `WebhookEvents` (`StoreDbContext.cs:27`) and
   `IdempotencyJournal` (`:26`) exist so a replayed event is recognised rather than re-fulfilled.
9. **Fulfilment, one transaction.** `WebhookEndpoints.cs:56` calls
   `FulfilmentService.FulfilAsync` (`Services/FulfilmentService.cs:22`). Per purchased item it
   looks up the pack and refuses if `ContentKey` is empty (`:66`), creates an `Entitlement`
   (`:80-91`) that **snapshots** `ContentKey = pack.ContentKey` with the comment "deliver-as-sold"
   (`:87`), and adds a `PendingDelivery` outbox row (`:101-103`) using the navigation property
   because the entitlement id does not exist until insert. The comment at `:94` states the
   invariant: the delivery obligation is committed by the **same** `SaveChangesAsync` as the
   entitlement (`:151`). Either both exist or neither does.
10. **Drain.** `DeliverySweeper` is a hosted service (`Program.cs:101`
    `AddHostedService<DeliverySweeper>`). It loops on an interval read from configuration
    (`Services/DeliverySweeper.cs:21-38`) and calls `DrainOnceAsync` (`:43`), which uses the scoped
    `DeliveryDrain` (`Program.cs:100`, `Services/DeliveryDrain.cs:27`). `TrySendAsync` (`:88`) sends
    the email through `IEmailSender` → `MailjetEmailSender` (`Program.cs:94`), with a max-attempts
    bound (`DeliveryDrain.cs:74`).
11. **Download.** `GET /download/{token}` — `DeliveryEndpoints.cs:32`. It presigns at `:273`
    with `DownloadUrlTtl = TimeSpan.FromMinutes(5)` (`:19`) and returns `Results.Redirect(url)`
    (`:280`). The API never proxies bytes.
12. **Storage.** `IContentStorage` is chosen at `Program.cs:79-93`: if the Crux `IBlobStore` is
    configured, `CruxContentStorage` (`Services/CruxContentStorage.cs:10`); else if
    `Content:LocalDir` / `CONTENT_LOCAL_DIR` is set, `LocalContentStorage`
    (`Services/LocalContentStorage.cs:13`); else `CruxContentStorage` over an unconfigured store,
    whose callers get 503. `R2StorageBridge` (`Services/R2StorageBridge.cs:11`) maps the `R2:*`
    settings onto the `Storage:*` section Crux expects, composing the endpoint from the account id
    (`Program.cs:60-66`).

**What this trace proves architecturally.** Bytes never traverse our compute — R2 serves them
directly under a 5-minute grant. The payment provider is behind a keyed interface. The storage
provider is behind `IContentStorage` with three implementations already in tree. Those two are the
cleanest seams in the estate.

**What it exposes.** Every hop from 5 to 11 runs on **one machine** (`48ee019fd74e58`) against
**one SQLite file** on **one 1 GB volume**. See §9.

### 3.2 Trace B — a scheduler tick, from timer to `store/`

`prospector/scheduler/run_scheduled.py`, the tick body at `:1658-1877`. The gates run in this
order, and the order is the design.

1. **Entry.** `run_daemon` (`:2311`) loops. `producer_mode` (`:266`) decides whether this process
   generates or only drains. `code_fingerprint` (`:2251`) records which code is running, so a
   stale daemon is detectable rather than assumed.
2. **Heartbeat** (`:1668`) then `_refresh_tick_deadline` (`:1670`). A `threading.Timer` armed with
   `_TICK_HARD_DEADLINE_S` calls `_force_exit_hung_tick`, so a wedged tick dies instead of holding
   the lease.
3. **Spend guard.** `guard_from_config(cfg)` then `.evaluate()` (`:1671-1672`). Backed by the
   persistent ledger, ceiling `config.yaml:2569 daily_cap_usd: 100.0`.
4. **Queue target** (`:1677`), then `if not decision.can_run` (`:1712`) — this is where the
   `store/scheduler/PAUSE` kill switch stops the **whole** tick, generation and drain together.
5. **`queue_full`** (`:1717`), **`dry_run`** (`:1727`).
6. **Usage wall.** `usage_wall.reason()` (`:1742`).
7. **Moat preflight.** `_moat_blind_reason(cfg)` (`:1764` → definition `:788`) calls
   `health.moat_blind_reason(cfg, trusted_only=False)` (`:819`). The tick is skipped only when
   **every** configured verdict brain, trusted or provisional, carries a live dead mark. One live
   brain of any tier is enough to proceed.
8. **Generation brake.** `_generation_suppressed(cfg, decision)` (`:1789`, definition `:673`).
   This is the only skip that leaves the drain running. Inputs: `PAUSE_GENERATION`
   (`_GENERATION_PAUSE_FILENAME` `:301`), `schedule.backlog_cap` (`config.yaml:2429`, default 0 =
   off) compared against `_backlog_size` (`:463`), and the grounding-rate gate
   (`gate_generation_on_grounding`, read at `:660`, `config.yaml:2444 true`).
9. **Drain.** Inside `with _beating(cfg, "draining")`: `_drain_pass` (`:1833`), `_decay_pass`
   (`:1839`), `_recover_pass` (`:1842`). Budgeted by `_DRAIN_BUDGET_FRAC = 0.15` (`:837`,
   matching `config.yaml:2433`), paced by `_drain_only_interval_s` (`:933`) and
   `_drain_only_resume_per_tick` (`:945`).
10. **Generation** (`:1863`) → `prospector/run.py`. `run_signal` (`run.py:1494`) walks RUN.md's
    eight steps; `vet_candidate` (`run.py:1219`) is the moat call; `publish_and_record`
    (`run.py:1133`) is the only path that reaches the storefront.
11. **Out to store.** Every artefact lands under `config.store_root()` — the ledger
    `prospector.jsonl`, the dossier JSON under `dossiers/`, the queue under `scheduler/`.
    `run.py:2547 drainable()` is the single definition of "backlog", so the brake at step 8 can
    only engage on a number the drain can actually move.
12. **Publish.** On PASS, `POST /internal/catalog` on store-api (`Program.cs:473`) with
    `STORE_INTERNAL_API_KEY`. This is the only engine→storefront write path.

**What this trace proves.** The kill switch is at step 4, above everything, with no exceptions —
that is what makes it a rail. The two half-stops are at step 8, below the drain, by construction.
The moat preflight at step 7 is above generation, so the daemon cannot mint work no brain can
finish.

---

## 4. Data stores

### 4.1 The inventory

| Store | Where | Owner (writer) | Other readers | Size (measured) |
|---|---|---|---|---|
| `prospector.jsonl` (ledger) | `/data/store/` on `vol_42kyqo6g0kdzew14` | engine scheduler + consumer | ops console, spend guard, `scripts/ops_status.py` | 950,601 lines on Fly; 274 MB in the local store |
| `prospector.db` (SQLite) | `/data/store/` | engine | ops console readers | part of the 555 MB `/data/store` total |
| `dossiers/` | `/data/store/dossiers/` | `run.py` per verdict | ops console `read/candidate`, `read/run` | 190 MB locally |
| `_cache/` | `/data/store/_cache/` | `retrieval.py` | nothing else | 172 MB locally |
| `scheduler/` | `/data/store/scheduler/` | `run_scheduled.py` | ops console `read/queue`, `pause` | 54 MB locally |
| `listings/`, `pricing/`, `markets/`, `launch/` | `/data/store/` | `run.py`, `pricing.py` | ops console | small |
| `store.db` (storefront) | `/data/store.db` on `vol_4ql6dzwjylqeygnr` | store-api only | nothing — no other process mounts that volume | 1 GB volume |
| Pack files | Cloudflare R2 | engine (upload), store-api (presign) | buyers, under a 5-minute grant | off-estate |

Local developer store measured at
`du -sh /Users/chidionyema/Documents/code/prospector/store` → **707 MB**. The worktree used to
write these docs has its own near-empty `store/` (148 KB) — do not measure there and call it
production.

### 4.2 The `store/` layout

```
store/
  prospector.jsonl        the durable ledger: every run, verdict, cost, timing
  prospector.db           SQLite index over the same events
  prospector.db-shm/-wal  WAL sidecars — never copy the .db without these
  dossiers/               one JSON per verdict, PASS and KILL alike
  _cache/                 retrieval cache, keyed by query
  scheduler/              PAUSE, PAUSE_GENERATION, leases, heartbeats, queue
  listings/               published listing JSON
  pricing/rationale/      why a price was chosen, per candidate
  markets/                market open/closed state
  launch/                 launch-ops artefacts
```

### 4.3 The store root — and the split that is live right now

There are **two** store-root resolvers in the engine, they read **different** environment
variables, and only one of them is set anywhere.

```python
# prospector/config.py:12-31
REPO_ROOT = Path(__file__).resolve().parent.parent
def store_root() -> Path:
    override = os.environ.get("PROSPECTOR_STORE_DIR", "").strip()
    return Path(override) if override else REPO_ROOT / "store"
```

```python
# prospector/paths.py:49-69
ANCHOR = Path(__file__).resolve().parent.parent
STORE_ROOT_ENV = "PROSPECTOR_STORE_ROOT"
def store_root() -> Path:
    override = os.environ.get(STORE_ROOT_ENV)
    return Path(override) if override else repo_root() / "store"
```

`PROSPECTOR_STORE_ROOT` is set in **no** deployment. `rg` finds it only in `paths.py` itself, one
line of `docs/COMMERCIAL_READINESS_PROGRAM.md`, and tests. Every deployment sets only
`PROSPECTOR_STORE_DIR`: `deploy/engine/fly.toml:30`, `deploy/engine/Dockerfile:74`,
`deploy/compose/docker-compose.yml:68`, and all seven `ops/launchd/com.prospector.*.json`.

Proven on the running machine:

```
$ fly ssh console -a prospector-engine -C \
    "/usr/local/bin/python -c 'from prospector import paths, config; print(paths.store_root()); print(config.store_root())'"
paths.store_root=  /app/store
config.store_root= /data/store
```

`/app/store` exists inside the container. It holds **14 leaked files** written on 2026-08-18:
seven listing JSONs (e.g. `/app/store/listings/c6c12a566dcf56ad.json`, directory created 12:30)
and seven pricing rationale files (e.g.
`/app/store/pricing/rationale/5c38ed05aef619ac/2026-08-18T123015Z-546ba8259b04.json`, 12:37).
The real store is `/data/store`, 555 MB, ledger at 950,601 lines.

This matters beyond a few stray files. `prospector/ops/readers.py` resolves through
`paths.store_path()` at eleven call sites (`:61, :136, :168, :212, :225, :607, :705, :743, :809,
:883, :909`), and those readers are what the ops console renders. **The console reads a different
root than the engine writes.** Other `paths.store_path()` consumers: `prospector/decay.py:72,76,80`,
`prospector/ops/config_editor.py:58`, `prospector/ops/runner.py:55,107,132`,
`tools/_backfill_driver.py`, `tools/retire_rotted_passes.py`, `tools/unlist_killed.py`.

The irony is documented in the code itself. `config.py:15`'s docstring describes exactly this
defect class and says it was fixed on 2026-08-17 — "live state was split across two directories
for 20 minutes". It is split again, in a different pair of modules, for the same reason.
`deploy/engine/Dockerfile:74` carries a comment asserting `config.store_root()` "is the only
resolver". It is not.

**The fix is small and it is a one-line-per-file change, not a redesign.** Either make
`paths.store_root()` read `PROSPECTOR_STORE_DIR` as a fallback, or delete `paths.store_root()` and
route its callers through `config.store_root()`. `paths.py`'s per-call resolution is the better
design of the two — `config.py:12`'s `REPO_ROOT` is a `__file__` constant — so the merge should
keep `paths.py`'s shape and `config.py`'s variable name. Guard it with a test that asserts the two
functions return the same path under `PROSPECTOR_STORE_DIR`. Cost: under an hour. See §11 D1.

---

## 5. The numbers

Every figure below is paired with the command that produced it. Nothing here is remembered.

| Measurement | Value | Command |
|---|---|---|
| Fly apps, live | 6 | `fly apps list` |
| Fly apps, suspended | 5 (`tie-*`) | `fly apps list` |
| Fly machines, total | 10 | `fly machines list -a <app>` per app |
| Engine volume | 20 GB, lhr | `fly volumes list -a prospector-engine` |
| Store-api volume | 1 GB, lhr | `fly volumes list -a prospector-store-api` |
| Engine secret names | 14 | `fly secrets list -a prospector-engine` |
| Store-api secret names | 24 | `fly secrets list -a prospector-store-api` |
| Store-web secret names | 0 | `fly secrets list -a prospector-store-web` |
| Searxng secret names | 0 | `fly secrets list -a prospector-searxng` |
| Hermes secret names | 29 | `fly secrets list -a prospector-hermes` |
| `/data/store` on Fly | 555 MB | `fly ssh console -a prospector-engine -C "du -sh /data/store"` |
| Ledger lines on Fly | 950,601 | `fly ssh console ... "wc -l /data/store/prospector.jsonl"` |
| Local store | 707 MB (ledger 274 MB, dossiers 190 MB, `_cache` 172 MB, scheduler 54 MB) | `du -sh */` in the store |
| `prospector/*.py` top level | 101 | `ls prospector/*.py \| wc -l` |
| `prospector/**/*.py` | 135 | `find prospector -name '*.py' -not -path '*__pycache__*' \| wc -l` |
| Engine LOC | 64,836 | `find … -name '*.py' … \| xargs wc -l` |
| Test files | 383 | `find tests -name 'test_*.py' \| wc -l` |
| Test functions | 4,361 | `rg -c '^\s*def test_' tests \| awk -F: '{s+=$2} END {print s}'` |
| `scripts/` | 41 files | `ls scripts \| wc -l` |
| `tools/` | 45 files | `ls tools \| wc -l` |
| `config.yaml` | 2,602 lines | `wc -l config.yaml` |
| Ops console read views | 27 | `read/[view].ts:17-43` |
| Ops console actions | 16 | `act/[action].ts:22-40` |
| Store.Api DbSets | 13 explicit + Identity | `StoreDbContext.cs:20-33` |
| Store.Api endpoint files | 7 | `ls store_platform/src/Store.Api/Endpoints/` |
| launchd job definitions | 29 | `ls ops/launchd/` |

Live probes, all HTTP 200 on 2026-08-18 (`curl -s -o /dev/null -w '%{http_code} %{time_total}'`):

| Target | Code | Total |
|---|---|---|
| engine ops console | 200 | 1.083 s |
| `api.mumchimp.com/catalog` | 200 | 2.804 s |
| `api.mumchimp.com/healthz/money-rail` | 200 | 1.193 s |
| `mumchimp.com` | 200 | 2.114 s |
| `mumchimp.com/api/health` | 200 | 1.610 s |

Storefront cold start is recorded in `store_platform/deploy/fly/web.fly.toml`: first hit after
idle 9.216 s TTFB, warm 1.118 s of which 0.086 s is server time. That is why
`min_machines_running = 2`.

---

## 6. Portability: the contract, and an honest grade

The founder's rule is no lock-in. The estate has a real answer to it, not a slogan.

**The substrate.** `deploy/compose/docker-compose.yml` (219 lines) runs the whole thing on any
Docker host. Services: `engine` (unprofiled — the default), `api` (profiles `store`, `all`), `web`
(profiles `store`, `all`), `runner` (profiles `ci`, `all`). The runner service deliberately has
**no `env_file`**: it receives `GITHUB_RUNNER_PAT` and `RUNNER_LABELS` and nothing else, so a CI
runner can never hold a money key. That is a security property expressed in the compose file
rather than in a policy document.

**The adapter contract.** `deploy/PORTABILITY.md` names six things any platform must provide and
eleven functions a target script must implement: `t_name`, `t_preflight`, `t_provision`,
`t_secrets`, `t_release`, `t_start`, `t_stop`, `t_exec`, `t_put`, `t_pack`, `t_logs`, `t_health`.
Targets live in `deploy/targets/*.sh`. A new platform is one file.

**The grade, component by component.**

| Component | Lock-in | Grade | Evidence |
|---|---|---|---|
| Engine runtime | Plain Python in a Dockerfile; runs under compose today | **A** | `deploy/compose/docker-compose.yml` service `engine` |
| Engine storage | A POSIX directory behind `PROSPECTOR_STORE_DIR` | **A** | `deploy/engine/fly.toml:30`; any volume works |
| Store.Api runtime | Standard .NET 9 container | **A** | `api.fly.toml` is 60 lines of ports and mounts |
| Store.Api database | SQLite file on a mounted volume | **B** | Portable file, but §9 SPOF; EF Core would move to Postgres with a provider swap |
| Store.Web | Next.js container | **A** | no volume, no secrets |
| Ops.Console | Coupled to the engine's filesystem by design | **B** | `next.config.ts` header explains why; it moves wherever the volume moves |
| Content storage | S3-compatible behind `IContentStorage` | **A** | three impls in tree (`CruxContentStorage`, `LocalContentStorage`, plus the bridge); R2 is a config choice |
| Payments | Keyed DI, `IPaymentProvider` | **A−** | `Program.cs:103`; only one impl exists, so the seam is proven by shape not by use |
| Email | `IEmailSender` → Mailjet | **A−** | `Program.cs:94`; same caveat |
| Private networking | `*.internal` 6PN hostnames | **C** | `SEARXNG_URL=http://prospector-searxng.internal:8080` is Fly syntax; compose needs a different value |
| Deploy tokens / secret store | `fly secrets`, per-app `FLY_API_TOKEN_*` | **C** | `.github/workflows/deploy-*.yml`; a move means re-plumbing the secret injection |
| Volumes and regions | `[mounts]`, `primary_region = "lhr"` | **C** | Fly-shaped, but small: two mounts total |
| CI runners | GitHub Actions | **C** | The whole gate is `.github/workflows/ci.yml`; portable to any Actions-compatible host, not to a different CI product without a rewrite |

**Verdict.** The application layer is genuinely provider-neutral: the two things that actually
hold money and data — SQLite on a volume, S3-compatible object storage — are behind interfaces or
are plain files. What ties us to Fly is **operational glue**, not architecture: `.internal`
hostnames, `fly secrets`, `fly volumes`, and six `fly.toml` files. `HYPOTHESIS:` a cutover to a
plain Docker host is a day of work, dominated by secret plumbing and DNS, not by code. The check
that would settle it: run `docker compose --profile all up` from `deploy/compose/` against a
throwaway secret set and see how far the buyer path gets. `deploy/PORTABILITY.md` records three
rules that each cost a previous cutover attempt — read them before trying.

---

## 7. Seam quality

Each interface graded on how cleanly the far side could be replaced, with the reason.

| Seam | Mechanism | Grade | Why |
|---|---|---|---|
| **engine ↔ ops console** | Subprocess. Node spawns `python -m prospector.ops.console_api` (`ops.ts:104`), JSON envelope, `CONTRACT_VERSION = 1` (`console_api.py:62`), allow-lists of 27 reads and 16 actions | **A** | No port, no daemon, no shared memory. The console cannot call anything not on the list. A version integer sits on both sides. The failure mode is a non-zero exit, which is visible. |
| **api ↔ web** | HTTP + same-origin rewrite proxy (`next.config.ts:120-121`) | **A−** | Clean HTTP boundary; the proxy exists so cookies stay httpOnly. Deduction: `API_ORIGIN` is baked at build time, so pointing web at a different API is a rebuild, not a restart. |
| **engine ↔ store-api** | HTTPS + `STORE_INTERNAL_API_KEY`, `POST /internal/catalog` (`Program.cs:473`) and the `PATCH /internal/...` family | **B+** | Well-shaped and authenticated. Deduction: it is a shared bearer secret with no rotation story visible in this repo, and eight internal routes is a wide surface for one key. |
| **api ↔ payments** | Keyed DI `IPaymentProvider` (`Program.cs:103`) | **A−** | Textbook. Only Stripe implements it, so the seam is untested by a second implementation. |
| **api ↔ content storage** | `IContentStorage` (`Services/IContentStorage.cs:12`), three impls | **A** | Genuinely exercised: `LocalContentStorage` runs in dev, `CruxContentStorage` in prod, `R2StorageBridge` maps config between naming schemes. |
| **api ↔ email** | `IEmailSender`, typed HttpClient (`Program.cs:94`) | **A−** | Same shape, one impl. |
| **api ↔ its database** | EF Core over SQLite, migrations at startup (`Program.cs:201-207`) | **B** | Provider-swappable in principle; single-writer in practice. |
| **engine ↔ store (filesystem)** | **Two resolvers, one of them unset in every deployment** (§4.3) | **D** | This is the worst seam in the estate and it is currently broken in production. Files are being written to `/app/store` while the ops console reads `/data/store`. |
| **engine ↔ brains** | `config.yaml` roster + `is_provisional_provider` (`operator.py:1451`) | **A** | Promotion is a config line plus a golden gate. `moat_primary()` is config-declared since 2026-08-15; before that it was a hardcoded frozenset needing a source edit and a daemon re-exec. |
| **engine ↔ retrieval** | Chain `[ddg, exa, claude_cli]` with per-provider breakers (`retrieval.py`) | **A−** | Chain is config-declared, breakers are per provider. Deduction: searxng is reached by a Fly-shaped `.internal` URL. |
| **ci ↔ runners** | GitHub Actions labels; laptop launchd runners and `prospector-ci` machines share labels | **B** | Elastic and redundant by accident of shared labels. Deduction: `concurrency` with `cancel-in-progress: false` across `deploy-*.yml` is the guard against two deploys racing, and it is the only guard. |
| **ci ↔ Fly** | Per-app deploy tokens: `FLY_API_TOKEN_API`, `FLY_API_TOKEN_ENGINE`, `FLY_API_TOKEN` | **B+** | Correctly scoped per app rather than one org token. Deduction: the web workflow's token is unsuffixed, which reads as a leftover from before the split. |

---

## 8. Reliability model

### What is redundant

- `prospector-store-web`: two machines, `min_machines_running = 2` (`web.fly.toml:43`).
- CI: four laptop runners plus three Fly machines, same labels.
- Retrieval: a three-provider chain with independent breakers, plus a self-hosted searxng.
- Brains: `moat_primary: [minimax, claude_cli]` (`config.yaml:81`) — two, with half-open probes in
  `health.py:130` so a recovered brain returns in ~90 s.
- Pack files: R2, which is replicated by Cloudflare.

### Single points of failure

| SPOF | Blast radius | Detected by |
|---|---|---|
| `prospector-store-api` machine `48ee019fd74e58` | **All revenue.** No catalogue, no checkout, no webhook intake, no download. Stripe retries webhooks, so completed payments are not lost, but nothing fulfils until it returns. | Fly health check `GET /catalog` (`api.fly.toml:62`); `/healthz/money-rail` |
| `/data/store.db` volume `vol_4ql6dzwjylqeygnr` | **All orders, entitlements and pending deliveries.** A corrupt or lost volume loses the record of who bought what. | Backup endpoints (`Endpoints/BackupEndpoints.cs`) — verify the restore, not the backup |
| `prospector-engine` machine `80d34da6636478` | Generation, drain, backups and the console all stop together — six supervisord programs, one container. The storefront keeps selling what is already listed. | supervisord; the watchdog program; `scripts/ops_status.py` |
| `vol_42kyqo6g0kdzew14` (20 GB) | The ledger, every dossier, the retrieval cache and the scheduler queue. 555 MB of irreplaceable audit trail. | `ENGINE_BACKUPS_ENABLED=true` + the `offsite-backup` program |
| Stripe | Checkout stops. Existing entitlements still download. | `/healthz/money-rail`, `MoneyRailConfigGate` (`Program.cs:108`) |
| Cloudflare R2 | Downloads 503. Sales still complete; the outbox holds the obligation and the entitlement is durable, so delivery resumes. | `IBlobStore.IsConfigured` → callers 503 (`Program.cs:92`) |
| DNS / the Fly org | Everything. One account, one card. | Nothing in-estate |

### The property that saves the money path

The outbox. `FulfilmentService.cs:94-103` commits the `PendingDelivery` row in the same
`SaveChangesAsync` as the `Entitlement` (`:151`). If the process dies between purchase and email,
the obligation survives on disk and `DeliverySweeper` (`Program.cs:101`) picks it up. Combined
with `IdempotencyJournal` and `WebhookEvents` (`StoreDbContext.cs:26-27`), a replayed Stripe
webhook does not double-fulfil. This is the single best-engineered thing in the estate.

### The property that does not

The engine's crash-consistency story is a JSONL append plus a SQLite file plus a directory tree,
with no transaction spanning them. `HYPOTHESIS:` a SIGKILL mid-vet can leave a candidate with no
dossier and no index row. The memory index records exactly that outcome
(`a-killed-vet-destroyed-the-candidate.md`). Check: kill a vet process at a controlled point and
run `run.py drain_survey` (`run.py:2480`) to see whether the row is recoverable.

---

## 9. Failure modes

Symptom → root cause → fix. Every row is something that has happened in this estate.

| Symptom | Root cause | Fix |
|---|---|---|
| Console shows a stale queue while the engine is clearly working | Two store-root resolvers; console reads `paths.store_root()` = `/app/store`, engine writes `config.store_root()` = `/data/store` (§4.3) | Unify the resolvers; add a test asserting both return the same path under `PROSPECTOR_STORE_DIR` |
| The daemon runs 17-hour-old code and nothing reports it | Production ran from the shared developer checkout on whatever branch a session left it on | Production moved to `/Users/…/prospector-live`, detached at `origin/main`; probe with `scripts/live_checkout.py` |
| Every MiniMax tier benched with `ProviderExhaustedError … check API keys` right after a move | Git does not carry secrets; the new checkout had no `.env` | `.env` and `.lux/keys/agent.pem` are symlinks back to the developer checkout; the probe checks both |
| A live brain gets benched by a request id | HTTP codes matched as bare substrings, so "429" inside an id benched the provider | Word-boundary matching in `errors.py:134`; memory `substring-http-codes-bench-a-live-brain.md` |
| A candidate is KILLed on `min_composite` with seven checks reading "Verdict call failed; fail-safe." | An exception was treated as evidence | `verify.py:365` returns `retrieval_failed=True`, firing the DEFER gate at `verify.py:693`. Receipt: `store/dossiers/2102bacc6dd75cf9.kill.json` |
| Generation produces nothing all afternoon | A stock-based backlog brake with unbounded memory; one six-week-old outage suppressed generation indefinitely | Gate on the rate: `gate_generation_on_grounding` (`config.yaml:2444`), one bounded live search per tick; `backlog_cap` left at 0 as a floor |
| A `npm run build` failure reads as success | `cmd \| tail` reports **tail's** exit status | Capture the build's own status before any pipe |
| A commit fails with only "exit code 1" while the docs say no gate exists | `core.hooksPath` overrides `.git/hooks` entirely, so moving the old hook aside did nothing | `git config --get core.hooksPath` before believing anything about the gate |
| `fly apps list` STATUS disagrees with `fly status` | Measured this session on `prospector-ci` (§2.1) | Trust machine state, not app state; `HYPOTHESIS:` status lags autoscale |
| Storefront first request of the day takes 9 s | Cold start | `min_machines_running = 2` (`web.fly.toml:43`); numbers recorded in that file |
| Ops console comment says it is "not deployed anywhere" while it runs on Fly | Doc drift in a code comment | Corrected in `Ops.Console/next.config.ts`; the comment now names its own former error |

---

## 10. Invariants

Break one of these and the system misleads rather than fails.

1. **One canonical store.** `PROSPECTOR_STORE_DIR` names it. Every deployment sets it.
   *Broken today* by `paths.py` (§4.3). Consequence: split state, and a console that reports on a
   directory nobody writes.
2. **Never derive a store path from `__file__`.** The store must follow the data, not the code.
   `config.store_root()` exists for this. `config.py:15` documents the incident.
3. **The entitlement and its delivery obligation commit together.** One `SaveChangesAsync`
   (`FulfilmentService.cs:94-103`, `:151`). Break it and a buyer pays and receives nothing, with
   no record that they are owed anything.
4. **Deliver exactly what was sold.** The entitlement snapshots `ContentKey` (`:87`). Never
   dereference the pack's current key at download time.
5. **PAUSE stops the whole tick.** `run_scheduled.py:1712`, above the drain. A rail with
   exceptions is not a rail. The two half-stops (`PAUSE_GENERATION`, `backlog_cap`) live below the
   drain at `:1789`, deliberately.
6. **The daemon does not mint work no brain can finish.** `_moat_blind_reason` (`:1764`) runs
   before generation and calls `moat_blind_reason(..., trusted_only=False)` (`:819`).
7. **Only `moat_primary()` rules finally.** Anything else is stamped `provisional`
   (`operator.py:1451`) and never publishes on PASS (`run.py:864`).
8. **The drain stays trusted-only** while generation may run into a provisional tail. Same
   function, one parameter, so the two cannot disagree by accident.
9. **The money rail mints the Price and the catalogue row together** (`prospector/bridge.py`).
   The console refuses price writes for exactly this reason (`act/[action].ts:61-63`).
10. **`IsListed` is the sellability fence.** The storefront never decides locally.
11. **Bytes are never proxied.** Downloads are 302s to a 5-minute presigned URL
    (`DeliveryEndpoints.cs:19, :273, :280`).
12. **CI runners hold no money keys.** `deploy/compose/docker-compose.yml` gives the `runner`
    service no `env_file`.
13. **State is a probe, not a paragraph.** Any "is it working" claim in this file is accompanied
    by the command that answers it.

---

## 11. Architectural debt

Seven items, each with the cost of closing it.

**D1 — Two store-root resolvers, split in production. (§4.3)**
Cost: under an hour. Merge `paths.store_root()` onto `PROSPECTOR_STORE_DIR`, keeping `paths.py`'s
per-call resolution and dropping `config.py`'s `__file__` constant. Add a test asserting the two
agree. Then delete the 14 leaked files under `/app/store` and correct the comment at
`deploy/engine/Dockerfile:74` that claims one resolver exists. **Do this first** — it silently
corrupts what the operator sees.

**D2 — The store-api machine and its volume are an undefended SPOF for all revenue. (§8)**
Cost: a week, and it is not obviously worth paying yet. SQLite single-writer is the right call at
this volume; the cheap half is the part worth doing now — prove the restore path from
`Endpoints/BackupEndpoints.cs` actually reconstitutes a working `store.db`, and time it. A backup
nobody has restored is not a backup. Cost of that half: an afternoon.

**D3 — Dormant launchd definitions could start a second scheduler against the same store.**
The seven `com.prospector.*` jobs still exist and still point at the canonical store, while
generation now runs on Fly (§2.9). Nothing prevents a `launchctl load`. Cost: an hour — either
delete the daemon definitions or add a lease check that refuses to start when the Fly daemon holds
the lease. `schedule.lease_ttl_s` (`config.yaml:2457`, 7200) already exists; use it.

**D4 — One shared `STORE_INTERNAL_API_KEY` guards eight internal write routes with no rotation
story.** (§7) Cost: a day for scoped keys per capability; two hours for a documented rotation
procedure with a dual-key window. Do the cheap one first.

**D5 — Five suspended `tie-*` apps have sat in the org since 13 June 2026.**
Cost: ten minutes. They are attack surface and billing noise with no owner. `fly apps destroy`
each after confirming no volume holds anything wanted.

**D6 — `.internal` hostnames and `fly secrets` are the real lock-in, and no cutover has been
rehearsed.** (§6) Cost: a day to run `docker compose --profile all up` end to end and fix what
breaks. The value is not the compose file — it already exists — it is knowing which of the three
rules in `deploy/PORTABILITY.md` bites first.

**D7 — The engine has no crash-consistency story across ledger, SQLite and the dossier tree.**
(§8) Cost: two days for a write-ahead marker plus a recovery pass, or zero if the answer is "the
drain survey already catches it", which is untested. Cheapest first step: kill a vet at a
controlled point and see whether `drain_survey` (`run.py:2480`) recovers the row. An afternoon.

Ordering by damage-per-hour: **D1, D5, D3, D2's restore drill, D4's rotation doc, D7's experiment,
D6, D2 in full.**

---

## 12. Where to look next

| Question | Path or command |
|---|---|
| The shared factual spine | [`../ESTATE_MAP.md`](../ESTATE_MAP.md), `scripts/estate_map.py` |
| Is production running current code? | `.venv/bin/python scripts/live_checkout.py` |
| What is the engine doing right now? | `scripts/ops_status.py`; ops console `read/status` |
| Where does a module live? | [`senior-developer.md`](senior-developer.md) §1 |
| What do I do at 3am? | [`sre-on-call.md`](sre-on-call.md) |
| Every deploy knob | `deploy/engine/fly.toml`, `store_platform/deploy/fly/{api,web}.fly.toml` |
| Running it off Fly | `deploy/compose/docker-compose.yml`, `deploy/PORTABILITY.md`, `deploy/targets/*.sh` |
| The eight steps of a run | `RUN.md`, then `prospector/run.py:1494` |
| Every tick gate | `prospector/scheduler/run_scheduled.py:1658-1877` |
| The money rail | `prospector/bridge.py`; `store_platform/src/Store.Api/Services/FulfilmentService.cs` |
| Delivery | `store_platform/src/Store.Api/Endpoints/DeliveryEndpoints.cs` |
| The console contract | `prospector/ops/console_api.py:62`, `Ops.Console/src/pages/api/ops/{read,act}/` |
| CI | `.github/workflows/ci.yml` (jobs `changes:150`, `guard:267`, `python:339`, `engine:488`, `dotnet:569`, `nextjs:616`, `ops-console:686`, `ci-ok:748`) |
| Deploys | `.github/workflows/deploy-{api,engine,web}.yml`, `e2e-live-smoke.yml` |
| The gate before you commit | `.venv/bin/python scripts/popdd_verify.py --staged` |

---

*Measured 2026-08-18 against the worktree at `192aa0e4`. If a number here is more than a week old,
re-run the command in §0 rather than quoting the table.*
