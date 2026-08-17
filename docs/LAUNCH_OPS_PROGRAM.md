# Launch Ops & Risk Programme — run the business without a human and without an agent

**Status: audit complete 2026-08-16. Nothing in the plan is built yet.**
This is the tracked ledger for pre-launch operational and business risk. Append results here, not
in CLAUDE.md. Siblings: `COST_PROGRAM.md`, `GRAPHIFY_ENFORCEMENT_SPEC.md`, `SITE_SPEC_PROGRAM.md`,
`OPS_CONSOLE_PROGRAM.md`.

---

## The goal

**Run the whole business — the engine and the shop — from one screen, with almost nothing left for
a person to do, and nothing at all left for an agent.**

Four things follow, and every decision in this document is judged against them:

1. **Automated by default.** Every routine action runs on a schedule or a trigger. A human acts
   only on the five exceptions in §5. If a task needs a terminal, it is not finished.
2. **One surface, Next.js.** `store_platform/src/Ops.Console` is that surface. It replaces the
   Streamlit console. Business screens (money, backups, DNS, infrastructure, legal) sit next to
   engine screens, because the founder does not care which side of the wall a problem is on.
3. **No LLM in the loop.** Claude Code builds the automation. It does not operate the shop. Every
   control must survive an agent being unavailable, out of credit, or wrong.
4. **Seen before it hurts.** Every risk in §1 becomes a line on the console and a threshold in §2.
   Green means measured today, not "no news".

**The test of done.** The founder opens one URL. Every risk in §1 shows one green or red line.
Every red line has either a button that fixes it or a runbook link that says exactly what to type.
No terminal, no plist, no agent, no guessing.

**Where we stand against that goal, measured today.** The console exists — 12 screens and a Python
gateway with preview-then-confirm writes — but it is **uncommitted in a worktree** and it covers
**engine operations only**. It has no screen for money, backups, DNS, hosting, or legal. §3.5 is
the inventory; §4 is the route from here to the test of done.

---

**The rule this document is built on.** Every risk below gets four things, or it is not managed:

1. a **control** that acts without a human,
2. a **probe** — one command that prints the true answer,
3. an **alert** that names the real cause and the first action,
4. a **written recovery** in the runbook, tested at least once.

A risk with prose instead of those four is an unmanaged risk. Today most of them have prose.

---

## 0. Live state, measured 2026-08-16 10:14–12:05 UTC

| Layer | Measured | Receipt |
|---|---|---|
| Web | Fly `prospector-store-web`, **2 machines**, lhr, deployed 5h ago | `fly status` |
| API | Fly `prospector-store-api`, **1 machine**, lhr, 1 health check passing | `fly status` |
| Prod DB | **SQLite `/data/store.db`** on Fly volume `store_data`, 1 GB, lhr zone 8169, encrypted | `fly volumes show` |
| DB snapshots | scheduled, **5-day retention**, newest 11h old, 5 held | `fly volumes snapshots list` |
| DNS | registrar **123-Reg**, nameservers **GoDaddy** (`ns03/04.domaincontrol.com`) | `whois`, `dig NS` |
| Domain expiry | 2027-06-16, all four client-* locks on | `whois` |
| A record | `66.241.124.37` → Fly **direct, no CDN or WAF in front** | `dig A`, response headers show `via: fly.io`, no `cf-ray` |
| TTL | A 600s, NS 3600s | `dig` |
| Mail | MX Google Workspace; SPF google+mailjet; DMARC `p=quarantine` | `dig MX/TXT` |
| DKIM | mailjet **published**; google `_domainkey` **empty** | `dig TXT google._domainkey` |
| Object storage | R2 `prospector-packs` (delivery) and `prospector-backup`; **no versioning on either** | `get_bucket_versioning` → `{}` |
| Engine backup | daily 03:40 local, **PASS, verified 8/8**, newest `db/prospector-2026-08-16.db.gz` 02:41Z | `store/backup.log`, R2 listing |
| Backup contents | `db/` 7 objs, `dossiers/` 2,680 objs 141 MB, `ledger/` 14 objs 147 MB | R2 listing |
| RPO | **up to 24h** — 255 dossiers written since the last backup | `find store/dossiers -newermt` |
| Repo | github.com/chidionyema/prospector, **PUBLIC**, MIT licence, **no branch protection on main** | `gh repo view`, `gh api …/protection` → 404 |
| Secrets in git history | **none** — every match is a placeholder (`REPLACE_ME`, `<your-key>`) | `git log --all -p` scan |
| `.env` | never committed, gitignored at `.gitignore:34`, **20 keys, plaintext, one laptop** | `git check-ignore -v .env` |
| Live shelf | **62 listed, 146 registered** | `GET /catalog/stats` |
| Stranded PASSes | **35** built and unsellable | `tools/verify_pass_shelf_coverage.py` |
| Engine | producer pid 30685, consumer pid 30686, both up 5h15m | `launchctl list` |
| Dossiers today | 264 (135 kill, 129 pass) | `find store/dossiers -newermt` |
| Spend | $6.60 of $100 billed; ledger **216,974,821 bytes** | `ls -l store/prospector.jsonl` |
| Uncommitted | **201 paths**; branch 52 ahead / 29 behind `origin/main` | `git status --porcelain` |
| Staging | `api.staging.fly.toml` exists; **no staging app deployed** | `fly apps list` |

**Controls that already work and must not be rebuilt.** Five launchd jobs run the engine
unattended. Kill switch (`store/scheduler/PAUSE`) plus two half-stops. Daily spend cap. A 15-minute
watchdog that SIGKILLs a wedged daemon. Escalating 5m/10m/20m retries. Alerts on four channels
including Telegram, with a delivery test. A nightly R2 backup that **verifies its own uploads**
(`verified=8/8`) and prunes on retention. Payments abstracted behind `IPaymentProvider` with a
Stripe as its one real implementation. Email abstracted behind `IEmailSender` and **optional** —
the buyer gets download links on the success page, not by email. Both web and API ship as plain
Dockerfiles. Legal pages exist: terms, privacy, refund, a Consumer Contracts Regulations 2013
waiver, an AI-generated disclosure, a licence grant, Stripe automatic tax.

That is a lot. The gaps are specific, and they are below.

---

## 1. Risk register

Severity: **BLOCKER** (do not launch), **HIGH** (launch degraded), **MEDIUM**, **ACCEPTED**.

### SRC — repository, source, secrets

| ID | Risk | Sev |
|---|---|---|
| SRC-1 | **Nothing is committed.** 201 uncommitted paths; branch 52 ahead / 29 behind `origin/main`. The daemon runs code that exists in exactly one working tree, and a second session is writing to it. No rollback point exists. | BLOCKER |
| SRC-2 | **`main` has no branch protection.** `gh api …/branches/main/protection` → 404 "Branch not protected". Any push, from anywhere, lands on the branch that deploys the storefront. Signed commits are enforced by a local hook only — a hook that is currently moved aside (`pre-commit.DISABLED-2026-08-14`). | BLOCKER |
| SRC-3 | **The repo is PUBLIC under MIT.** The whole engine — prompts, filter, generation strategy, pricing ladder — is readable and legally reusable by anyone. This may be deliberate. It is a business decision that must be made on purpose before launch, not discovered after. | HIGH (decision) |
| SRC-4 | **One remote, no mirror.** `origin` is the only copy off this laptop. GitHub account loss = source loss. `.git` is 87 MB; a mirror costs nothing. | HIGH |
| SRC-5 | **20 secrets live in one plaintext `.env` on one laptop.** No vault, no escrow. Verified clean: `.env` was never committed and no real key appears anywhere in git history. Fly holds its own copy as app secrets, so the API survives; the engine does not. | HIGH |
| SRC-6 | 62 runtime-state files under `store/` are tracked and therefore public, including `store/control_center/config_history.jsonl` and launch proofs. No customer data among them, checked. | MEDIUM |

### INF — hosting and compute

| ID | Risk | Sev |
|---|---|---|
| INF-1 | **The API is one machine in one region.** `min_machines_running = 1` (`api.fly.toml:58`). A host failure, or any deploy, takes the store's entire back end offline. The web tier has two. | HIGH |
| INF-2 | **No staging environment.** `api.staging.fly.toml` exists; no staging app is deployed. Every change is tested in production. | HIGH |
| INF-3 | **No CDN or WAF in front of the origin.** `mumchimp.com` resolves straight to a Fly IP; response headers show Fly with no Cloudflare hop. No caching, no rate-limit edge, no DDoS absorption beyond Fly's own. Rate limiting exists in-app (`RateLimiting__PermitPerMinute`). | HIGH |
| INF-4 | Single Fly account and single payment method for both apps and the volume. Account suspension is a total outage. | MEDIUM |
| INF-5 | Deploy is Fly-specific in CI (`superfly/flyctl-actions`, hardcoded app names) — but both services are plain Dockerfiles, so the lock-in is the pipeline, not the code. | MEDIUM |

### DAT — databases and backups

| ID | Risk | Sev |
|---|---|---|
| DAT-1 | **The money data has one copy and a 5-day window.** Orders, entitlements, grant tokens and download counts live in SQLite on a single Fly volume. The only protection is Fly's scheduled snapshots, retention 5 days. **Nothing in this repo ever pulls that database off Fly.** Lose the volume and the account, or notice a corruption on day six, and every record of who bought what is gone. | BLOCKER |
| DAT-2 | **The restore has never been proven end to end.** `scripts/restore_drill.py` exists and prints `RESTORE_DRILL PASS/FAIL`, but no dated receipt of a run exists on disk. A backup nobody has restored is a hypothesis. | HIGH |
| DAT-3 | **The spend ledger outgrew its readers.** `store/prospector.jsonl` is 207 MB. A cold read measured 108s (`ops/spend.py:345`). The daily cap works only while the incremental checkpoint survives; the state probe now refuses to read a ledger over 20 MB at all. No rotation code exists. | HIGH |
| DAT-4 | **RPO is 24 hours** on engine state. The last backup was 02:41Z; 255 dossiers have been written since. Engine data loss is recoverable work, not customer harm — but it should be an explicit number, not an accident. | MEDIUM |
| DAT-5 | Backup coverage is good where it exists: `db/`, `dossiers/`, `ledger/`, verified 8/8 daily. The gap is entirely the Fly-side database (DAT-1). | ACCEPTED |

### AST — assets and delivery

| ID | Risk | Sev |
|---|---|---|
| AST-1 | **No object versioning on either R2 bucket.** A bad sync, a wrong prefix, or a delete on `prospector-packs` destroys what buyers download, with no undo. The backup bucket's dated keys give effective history; the delivery bucket has none. | HIGH |
| AST-2 | **Live entitlement tokens are gitignored and unbacked.** `store_platform/.delivery-proof/` holds grant tokens that are bearer credentials for `/download/{token}`. They exist on one laptop and in the Fly database, nowhere else. | HIGH |
| AST-3 | `store/listings/*.json` is not backed up. Regenerable from dossiers, so this is a time cost, not a loss — but the regeneration path has never been run for real. | MEDIUM |
| AST-4 | Delivery keys are content-addressed and the storage client uses the plain S3 API, so moving to S3/MinIO/GCS is a credentials change, not a code change. | ACCEPTED |

### DNS — domain and mail

| ID | Risk | Sev |
|---|---|---|
| DNS-1 | **Registrar and DNS are split across two vendors** — 123-Reg holds the domain, GoDaddy nameservers serve it. Two accounts, two recovery paths, two ways to lose control of the name. Registrar locks are all on, which is the good half. | MEDIUM |
| DNS-2 | **DNSSEC unsigned.** | MEDIUM |
| DNS-3 | **Google Workspace DKIM is not published** (`google._domainkey` empty) while DMARC is `p=quarantine`. Mail sent from Workspace passes only on SPF alignment. Support and order mail can land in spam. Mailjet's DKIM is published. | MEDIUM |
| DNS-4 | A-record TTL is 600s, so a host move propagates in ten minutes. Nothing to fix; record it so nobody plans a migration around a stale assumption. | ACCEPTED |

### BIZ — business and legal

| ID | Risk | Sev |
|---|---|---|
| BIZ-1 | **No company number, registered address or VAT number anywhere on the site.** The address is a placeholder: "Registered address available on request". A UK trader selling to consumers must display trading identity and a geographic address. This is a legal defect on a live shop, and it is a fifteen-minute fix once the details are decided. | BLOCKER |
| BIZ-2 | All legal pages are marked "pending review by qualified counsel". Terms, privacy, refund and the CCR-2013 waiver exist and read correctly, but none has been reviewed by a solicitor. | HIGH (decision) |
| BIZ-3 | No dedicated contact page; contact is an email address in config. UK distance-selling rules expect an accessible contact route. | MEDIUM |
| BIZ-4 | No cookie banner. The privacy policy asserts necessary-only cookies, which would make a banner unnecessary — but that assertion is not tested against what the deployed site actually sets. | MEDIUM |
| BIZ-5 | Content liability is covered in writing: AI-generated disclosure, no-warranty clause, personal non-transferable licence. The residual risk is a buyer acting on a wrong figure. The source-or-die rule is the control; it has no external audit. | ACCEPTED |
| BIZ-6 | Key-person risk. One founder, one laptop, one set of credentials, no documented handover. If the founder is unavailable for a week, nothing recovers itself beyond what the daemon already does. | HIGH |

### PAY — money rail

| ID | Risk | Sev |
|---|---|---|
| PAY-1 | **Nothing proves production is in live Stripe mode.** `.env` holds both test and live keys; Fly holds `Stripe__ApiKey` whose value is not readable; the live page exposes no publishable key to inspect. The `deploy-web.yml` gate is the only control, and no probe answers "is the shop taking real money right now?" | BLOCKER |
| PAY-2 | Refunds, disputes and chargebacks have code (`StripeProvider` handles `Charge`, `Dispute`, `Event`) but no operational runbook and no alert. A dispute arrives in Stripe email only. | HIGH |
| PAY-3 | A price change breaks fulfilment if the catalogue and the provider drift. `bridge.py` mints both from one `PriceDecision`, which is the right design. It stays a human action on purpose. | ACCEPTED |
| PAY-4 | Stripe automatic tax is enabled (`StripeProvider.cs:432-442`). Registration thresholds are a business decision, not a code one. | ACCEPTED |

### ENG — engine operations

| ID | Risk | Sev |
|---|---|---|
| ENG-1 | **35 finished packs cannot be bought.** 56% of the current shelf, built and stranded. Publishing is automated (`consume --publish`); the pack linter blocks them — `placeholders` (`pack_linter.py:324-329`) and `shelf_copy` (`pack_linter.py:781`) — and **nothing ever retries a lint failure**. One has no lint record at all. | BLOCKER |
| ENG-2 | **The loudest alert names the wrong cause.** `ALERT.txt` says "Generation DEAD: 8 consecutive barren ticks" and tells the founder to check `claude /login` and MiniMax credits. Measured: 8 of today's 28 ticks carry `generation_suppressed: "grounding degraded: the retrieval probe did not answer within 120s"`. `_trailing_barren_count` (`run_scheduled.py:1691`) skips only guard-skipped and dry-run rows, so a deliberate suppression counts as barren. Meanwhile the consumer wrote 264 dossiers. All three suggested checks are wrong. | HIGH |
| ENG-3 | **Grounding runs on one provider.** exa returned HTTP 402 from 03:15Z — 97 error lines today, no alert. SearXNG measures 0.10 mean coverage against `min_relevance` 0.35. claude_cli is backstop-only. ddg alone carries it, and when ddg is slow the gate suppresses generation, which is what ENG-2 mislabels. | HIGH |
| ENG-4 | 25 MiniMax calls hit the 600s hard deadline today. Up to 4 hours of wall clock spent learning nothing. Measure before fixing. | MEDIUM |
| ENG-5 | Logs and state grow unbounded: `launchd.err.log` 25 MB, `store/` 546 MB, no rotation code anywhere. 54 GiB free, so this is slow — but a full disk stops the daemon, the backup and the build at once. | MEDIUM |
| ENG-6 | **Docs describe a system that no longer exists.** 11 docs name `cursor_cli` (deleted 08-06), 4 name `standardcompute` (deleted 08-15), `RUN.md:95` names a Gemini quota, `RUN.md:60` points at a 0-byte stub. 3 docs are untracked. One real runbook exists (`AMBITION_LANES_RUNBOOK.md`, 08-01); there is none for start, stop, recover, publish, deploy, restore or key rotation. | MEDIUM |
| ENG-7 | Two guards are off: the batching guard is inert (`~/.claude/state/toolguard/OFF`), and the control-centre password is `test` on a tailnet-only address. | MEDIUM |

### KEY — the single machine

| ID | Risk | Sev |
|---|---|---|
| KEY-1 | **The engine cannot run anywhere but this Mac.** Both plists carry absolute `/Users/chidionyema` paths; scheduling is launchd; desktop alerts are `osascript`. Moving to a server is a code change, not a config change. The storefront survives without the Mac; the product pipeline does not. | HIGH |
| KEY-2 | Laptop loss costs at most 24h of engine work (DAT-4) plus the `.env` (SRC-5), and the ability to produce anything new until KEY-1 is fixed. | HIGH |

---

## 2. The monitoring matrix — everything on one board

Today the state probe checks the engine well and the business not at all. This is the target set.
Every row is a line the probe prints, with a threshold that fires an alert.

| Signal | How | Threshold → alert |
|---|---|---|
| Storefront up | `GET /` status + ms | non-200 or >2s → CRITICAL |
| API up | `GET /catalog/stats` | non-200 → CRITICAL |
| Shelf size | `listed` vs local selling packs | drift > 0 → WARNING |
| Stranded PASSes | `verify_pass_shelf_coverage.py` | > 0 → CRITICAL |
| **Stripe mode** | live-mode assertion against the deployed API | test mode in prod → CRITICAL |
| Checkout works | synthetic purchase on a £0.50 canary pack, daily | failure → CRITICAL |
| Disputes/refunds | Stripe webhook counter | any dispute → CRITICAL |
| TLS expiry | `openssl … -enddate` | < 21 days → WARNING |
| Domain expiry | `whois` | < 60 days → WARNING |
| DNS answer | `dig A` vs expected | mismatch → CRITICAL |
| Mail auth | SPF/DKIM/DMARC present | missing → WARNING |
| Prod DB backup age | newest off-Fly copy | > 26h → CRITICAL |
| Fly snapshot count | `fly volumes snapshots list` | < 3 → WARNING |
| Engine backup | `STORE_BACKUP PASS` in `store/backup.log` | missing today → CRITICAL |
| Restore drill | dated receipt | > 30 days → WARNING |
| Disk free | `df` | < 20 GiB → WARNING |
| Largest log | `find store -size` | > 50 MB → WARNING |
| Ledger size | `ls -l` | > 50 MB → WARNING |
| Spend today | guard cache | > 80% of cap → WARNING |
| Provider credit | first permanent 402 per provider per day | any → CRITICAL |
| Grounding health | probe answer time | suppression → its own key, never `barren_streak` |
| Producer + consumer heartbeat | heartbeat files | > 45 min → CRITICAL |
| Uncommitted paths | `git status --porcelain \| wc -l` | > 0 for tracked source → WARNING |
| API machine count | `fly status` | < 2 → WARNING |

**Delivery.** Everything already routes through `alerts.py` to file, desktop, webhook and
Telegram, with throttling and auto-resolve. Nothing new is needed there. What is missing is a
**daily digest** — one message that says what happened, so silence means healthy instead of
meaning unmonitored.

---

## 3. Migration playbooks — the "what if we have to move" answers

Written now, while nothing is on fire. Each is a runbook section, not a paragraph.

**Move the host (Fly → anywhere).** Both services are plain Dockerfiles, so the images run
anywhere. What must be rewritten: the two GitHub workflows (`superfly/flyctl-actions`),
`deploy_web.sh`, the three `fly.toml` files, and 9 hardcoded `fly.dev` references in
`Store.Api/Program.cs`, `Services/DeliveryUrls.cs`, `Store.Web/next.config.ts` and the Dockerfile.
The volume becomes a mounted disk or a managed Postgres. **Estimate: a day, plus the DB move.**
*Cut the cost now* by moving those 9 hardcoded hosts into config.

**Change the domain.** Places that name `mumchimp.com` in source, not config: `StripeProvider.cs:25`
(hardcoded suffix), `Program.cs`, `pricing.py`, `decay.py`, `indexnow.py`, `lib/config.ts`. Plus
DNS at GoDaddy, the registrar record at 123-Reg, Fly certificates for both apps, `STORE_PUBLIC_URL`
/ `STORE_STOREFRONT_URL` / `STORE_ALLOWED_ORIGIN` secrets, Stripe redirect URLs, Google Workspace
and Mailjet sender domains with fresh SPF/DKIM/DMARC, and every already-issued download link.
A-record TTL is 600s so propagation is ten minutes. **Estimate: half a day, and old download links
must keep resolving — that is the part that bites.**

**Move the database.** SQLite on a volume is the cheapest thing that works and the hardest thing to
replicate. Two options: keep SQLite and add an hourly off-Fly copy (litestream or a scheduled
`fly ssh sftp get` into R2), or move to managed Postgres and take the migration cost once. EF Core
means the provider swap is a package and a connection string; the migration is the work.
**Recommendation: do the hourly off-Fly copy this week regardless — it removes DAT-1 today, and it
is still correct after any later move to Postgres.**

**Move object storage.** Credentials and an endpoint. The client is plain S3. **Estimate: an hour.**

**Move payments.** `IPaymentProvider` has one real implementation, Stripe, plus a fake for tests.
A second provider has to be written first: the stub that used to sit here threw
`NotSupportedException` and had never billed anyone, so it was not a head start. After that, swap
the DI registration and the credentials. Re-provisioning every product and price at the new
provider is the real work. **Estimate: a day of writing the provider, then a day of
re-provisioning.**

**Move the engine off this Mac.** The blocker is KEY-1: absolute paths in two plists, launchd, and
`osascript`. Fix by reading the root from an env var, shipping a systemd unit next to the plists,
and making the desktop notifier a no-op off macOS (it already degrades gracefully).
**Estimate: half a day, and it converts the largest single-point-of-failure into a rebuildable box.**

---

## 3.5 The console — the one surface, and what it does not yet cover

**What exists, measured today.** `store_platform/src/Ops.Console` — Next.js, Pages Router, 12
screens: `index`, `engine`, `queue`, `runs` (+ detail), `catalogue` (+ detail), `config`, `spend`,
`metrics`, `audit`, `tools`, `login`. Behind it, one Python gateway
(`prospector/ops/console_api.py`, 72 KB) with a reader table and an `ACTIONS` table
(`:1235`), preview-then-confirm write tokens (`_token`, `:915`), and an intent receipt written for
every action (`_record_intent`, `:1224`). Spec: `docs/ADMIN_CONSOLE_PROGRAM.md`.

**Its design rule is right and must be kept:** no TypeScript computes an engine number. Every
figure comes from a Python process that imports `prospector.ops`, so the console and the rails can
never disagree. That is what stopped the old dashboards drifting from the daemon.

**Three facts about its status, so nobody plans on sand.** It is uncommitted, in the worktree
`.claude/worktrees/agent-aaecfffaa54620133`. It was built by a background agent and its reported
receipts (build, tsc, vitest, pytest, playwright) are **unverified**. It reaches the laptop over
Tailscale, not the public internet, and `ADMIN_CONSOLE_PROGRAM.md §1` explains why putting it on
mumchimp.com is a different programme — the engine's state lives on the Mac.

**What it covers and what it does not.** Today: engine only. The whole right-hand column below is
missing, and it is the half the founder asked about.

| Screen | Status | Covers |
|---|---|---|
| Engine, Queue, Runs, Config, Spend, Metrics, Audit, Tools | **built, unverified** | ENG-1..7, DAT-3 |
| Catalogue | **built, unverified** | ENG-1, PAY-3 |
| **Money** | **missing** | PAY-1 live-mode assertion, PAY-2 disputes and refunds, today's revenue, the canary checkout |
| **Data** | **missing** | DAT-1 off-Fly DB copy age, DAT-2 last restore drill, DAT-4 RPO, AST-1 versioning |
| **Infrastructure** | **missing** | INF-1 machine counts, INF-2 staging, TLS expiry, deploy history |
| **Domain** | **missing** | DNS-1..4, domain expiry, DNS answer match, mail auth |
| **Repo** | **missing** | SRC-1 uncommitted, SRC-2 protection, SRC-4 mirror age |
| **Compliance** | **missing** | BIZ-1..4 as a checklist with dates, not prose |

**So the console work is not a separate project from the risk work.** Each phase below ships its
control, its probe, *and* the screen that shows it. A control with no line on the console fails
goal 4; a screen with no control behind it fails goal 1.

---

## 4. Delivery plan

### P0 — Stop being one bad day away from losing the business (this week)
1. **DAT-1**: hourly copy of `/data/store.db` off Fly into R2 under `db-store/`, verified, alerting
   if the newest copy is over 26h old. Nothing else in this document matters as much.
2. **SRC-1**: commit the branch in slices by explicit path (never `git add -A` — `store/` and
   `storage/` are tracked runtime state pytest writes to), merge `origin/main`, tag `launch-rc1`.
3. **SRC-2**: turn on branch protection for `main` — required checks, no force push, signed commits.
4. **SRC-4**: a second remote mirror, pushed by the nightly job.
5. **PAY-1**: a live-mode assertion that runs on every deploy and every probe.
6. **BIZ-1**: real company number, registered address and VAT status on the site.
7. **Console:** re-run the console's own build, tsc, vitest, pytest and playwright receipts myself,
   fix what fails, and commit it out of the worktree. An unverified, uncommitted console is not a
   surface — it is a second copy of SRC-1.
8. **Console:** ship the **Money** and **Data** screens against the P0 controls above, so the two
   blockers that can end the business are visible before they are fixed, not after.
**Done when:** the probe prints a green line for each, one of them has been tested by breaking it,
and the founder can read all six on the console without a terminal.

### P1 — Make the shelf self-clearing (revenue)
1. Lint repair loop: regenerate only the failing field, re-lint, re-publish; unlist and alert after
   the second failure.
2. Publish sweep every tick: any PASS without a listing gets one attempt.
3. Clear the 35 — read-only report first, then `--fix`.
5. **Console:** the Catalogue screen gets a one-click 'repair and republish' on any stranded pack.
**Done when:** stranded count is 0, the check runs per tick, and the count is a line on the console home.

### P2 — Make the meters honest
1. Ledger rotation into `store/ledger/YYYY-MM.jsonl` plus a compacted `daily_totals.json` the guard
   reads (DAT-3).
2. `barren_streak` excludes suppressed ticks; new `grounding_suppressed` key naming the provider
   that failed (ENG-2).
3. Provider-credit alert on the first permanent exhaustion, wired to `errors.looks_exhausted` (ENG-3).
4. Extend the state probe to every row in §2.
5. **Console:** the home screen becomes the board in §2 — one row per signal, green or red, with the age of the measurement next to it. Grey is not green.
**Done when:** the probe prints the full board, a suppressed tick no longer pages, and the console home shows every row.

### P3 — Survive without you
1. Restore drill run for real against R2 and the Fly copy; record time-to-restore (DAT-2).
2. API to 2 machines; deploy strategy that does not drop the API (INF-1).
3. Deploy the staging app that already has a config file (INF-2).
4. R2 versioning on `prospector-packs` (AST-1).
5. Log rotation in the nightly job (ENG-5).
6. Daily digest.
7. **Console:** **Infrastructure** and **Repo** screens.
**Done when:** the drill has a dated receipt, the digest has arrived three days running, and both new screens are green.

### P4 — Portability, cheaply, before it is urgent
1. Move the 9 hardcoded `fly.dev` and 6 hardcoded `mumchimp.com` references into config.
2. Engine root from an env var; a systemd unit alongside the plists (KEY-1).
3. Write the four migration playbooks from §3 into the runbook.
4. **Console:** the **Domain** screen, which is also the pre-flight for any domain move.
**Done when:** a fresh clone runs the engine on a Linux box with no source edits, and the console runs there too.

### P5 — Documentation that cannot go stale
1. **One `RUNBOOK.md`**: start/stop/pause · clear the backlog · publish stranded packs · deploy web
   and API · restore the store DB · restore the engine · rotate a key · move host, domain, DB,
   storage, payments · what each alert means and the first three checks · handle a dispute or
   refund · who to fund when a provider 402s.
2. **`scripts/doc_lint.py` in CI**: fail on any doc naming a provider absent from `config.yaml`, any
   referenced script path that does not exist, any 0-byte target. This is what stops ENG-6 recurring.
3. Move superseded docs to `docs/attic/` with a one-line reason. Never delete — the incidents are
   the reasoning behind current rules.
4. Fix `RUN.md:95` (Gemini) and `RUN.md:60` (`prospector/publish.py` is a 0-byte stub).
5. **Console:** the **Compliance** screen — every item in BIZ-1..4 with a date and an owner — and a
   deep link from every alert to the runbook section that answers it.
**Done when:** `doc_lint.py` exits 0 in CI, the runbook covers every task above, and every red line
on the console links to the runbook line that clears it.

### Decisions only the founder can make (not blocked on engineering)
- **SRC-3**: does the repo stay public under MIT?
- **BIZ-2**: does a solicitor review the legal pages before launch?
- **ENG-3**: fund exa, or replace it?
- **BIZ-6**: who is the second pair of hands, and what do they need access to?

---

## 5. What stays human, by design

1. Funding a provider — a 402 is money, not code. The rail names it within minutes.
2. A pack that fails automated repair twice.
3. A price change — it breaks fulfilment if it drifts.
4. Merging to `main`.
5. A refund or dispute decision.

Everything else in this document is a script.

---

## 6. Verification commands

```bash
cd ~/Documents/code/prospector
git status --porcelain | wc -l                                   # SRC-1: 201
gh api repos/chidionyema/prospector/branches/main/protection      # SRC-2: 404 not protected
gh repo view chidionyema/prospector --json isPrivate,visibility   # SRC-3: PUBLIC
fly volumes show vol_4ql6dzwjylqeygnr --app prospector-store-api  # DAT-1: 1GB, lhr, snapshots 5d
fly volumes snapshots list vol_4ql6dzwjylqeygnr --app prospector-store-api
fly status --app prospector-store-api                             # INF-1: 1 machine
tail -3 store/backup.log                                          # DAT-5: STORE_BACKUP PASS verified=8/8
ls -l store/prospector.jsonl                                      # DAT-3: 216,974,821 bytes
.venv/bin/python tools/verify_pass_shelf_coverage.py              # ENG-1: 35 stranded
grep -c 'exceeded 600s hard deadline' store/scheduler/launchd.err.log   # ENG-4: 25
grep -c '402' store/scheduler/launchd.err.log                     # ENG-3: 97
curl -s https://api.mumchimp.com/catalog/stats                    # {"listed":62,"registered":146}
whois mumchimp.com | grep -i 'expiry\|registrar\|name server'     # DNS-1: 123-Reg / GoDaddy NS
dig +short TXT google._domainkey.mumchimp.com                     # DNS-3: empty
```

---

## 7. Ledger — append results here

| Date | Item | Result | Receipt |
|---|---|---|---|
| 2026-08-16 | Full audit: infra, DNS, data, assets, repo, business, money, engine | 9 groups, 40 risks, 6 blockers | this document |
