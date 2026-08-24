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
Paddle implementation already written. Email abstracted behind `IEmailSender` and **optional** —
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
| SRC-1 | **Nothing is committed.** **Re-measured 2026-08-16: 158 uncommitted paths, 55 ahead / 31 behind `origin/main`** (was 201 / 52 / 29). The daemon runs code that exists in exactly one working tree, and a second session is writing to it. No rollback point exists. Still a blocker: the count fell because work was committed on branches, not because the main checkout was cleaned. | BLOCKER |
| SRC-2 | ~~No branch protection~~ **CORRECTED 2026-08-16: `main` IS protected.** Ruleset `strict` (id 20109556), enforcement `active`, target `~DEFAULT_BRANCH`, rules: `deletion`, `non_fast_forward`, `pull_request`, `code_quality`, `required_status_checks`. My first probe used the legacy `/branches/main/protection` endpoint, which returns 404 when protection comes from a **ruleset** rather than a classic rule. Ask `gh api repos/…/rulesets`, never the legacy path. | RESOLVED |
| SRC-3 | ~~**The repo is PUBLIC under MIT.**~~ **CLOSED 2026-08-17. The premise was wrong.** `gh repo view chidionyema/prospector --json visibility,licenseInfo` returns `{"visibility":"PRIVATE","licenseInfo":{"key":"mit"}}`. The repo is already private, so the engine is not readable by anyone; only the MIT `LICENSE` file remains, and it binds nobody who cannot fetch the source. The founder confirmed the public state was never deliberate, which is consistent with it not existing. Nothing to do. | CLOSED |
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
| DAT-1 | **The money data has one copy and a 5-day window.** Orders, entitlements, grant tokens and download counts live in SQLite on a single Fly volume. The only protection is Fly's scheduled snapshots, retention 5 days. **Nothing in this repo ever pulls that database off Fly.** Lose the volume and the account, or notice a corruption on day six, and every record of who bought what is gone. **Re-verified 2026-08-16, unchanged:** `vol_4ql6dzwjylqeygnr`, 1 GB, lhr, encrypted, scheduled snapshots on, retention 5 — five snapshots exist, newest 12 hours old, 289 MiB total. The repo's own backup (`scripts/backup_store.py`) copies `store/dossiers/*.json` and `store/prospector.jsonl` to R2; it never touches the Fly database, so the money data still has exactly one copy. **CLOSED 2026-08-16, PR #240.** `ops/automations/offsite_backup.py` copies `/data/store.db` and the `/data/keys` Data Protection key ring into R2 under `offsite/`, opens each copy before it counts (`PRAGMA integrity_check`), and answers "is there a fresh copy right now" as a measurement, exit 0/1/2. Receipts: the monitor read `STALE money-db: never` before the fix and `OK money-db: 0.0h old` after it, first copy `offsite/money-db/store-20260816T114707Z.db`, 3,592,192 bytes. Daily at 03:50 via `deploy/com.prospector.offsite-backup.plist`. **Restoring into a fresh Fly machine is still untested — that is DAT-2, and it stays open.** | ~~BLOCKER~~ CLOSED |
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
| BIZ-1 | **No company number, registered address or VAT number anywhere on the site.** The address is a placeholder: "Registered address available on request". A UK trader selling to consumers must display trading identity and a geographic address. This is a legal defect on a live shop, and it is a fifteen-minute fix once the details are decided. **Re-verified on the live site 2026-08-16, unchanged:** `/terms` and `/privacy` both still read "Registered address available on request", `/terms` says only "VAT where applicable", and neither page carries a company number. | BLOCKER |
| BIZ-2 | All legal pages are marked "pending review by qualified counsel". Terms, privacy, refund and the CCR-2013 waiver exist and read correctly, but none has been reviewed by a solicitor. | HIGH (decision) |
| BIZ-3 | No dedicated contact page; contact is an email address in config. UK distance-selling rules expect an accessible contact route. | MEDIUM |
| BIZ-4 | No cookie banner. The privacy policy asserts necessary-only cookies, which would make a banner unnecessary — but that assertion is not tested against what the deployed site actually sets. | MEDIUM |
| BIZ-5 | Content liability is covered in writing: AI-generated disclosure, no-warranty clause, personal non-transferable licence. The residual risk is a buyer acting on a wrong figure. The source-or-die rule is the control; it has no external audit. | ACCEPTED |
| BIZ-6 | Key-person risk. One founder, one laptop, one set of credentials, no documented handover. If the founder is unavailable for a week, nothing recovers itself beyond what the daemon already does. | HIGH |

### PAY — money rail

| ID | Risk | Sev |
|---|---|---|
| PAY-1 | **NARROWED 2026-08-16. The API knows whether it is in live mode and tells nobody.** `MoneyRailConfigGate` (`MoneyRailConfigGate.cs:88-94`) computes `isLive` at startup — and uses it only to reject a malformed key. A test-mode key in production is deliberately not fatal, because staging runs `ASPNETCORE_ENVIRONMENT=Production` for parity. No endpoint, log line or probe reports the mode: `rg` over `Endpoints/` and `Program.cs` for `live_mode\|sk_live\|"mode"` returns nothing. So "is the shop taking real money?" is still unanswerable — but the value already exists at startup, so the fix is to log it and expose it, not to build a checker. | HIGH |
| PAY-2 | Refunds, disputes and chargebacks have code (`StripeProvider` handles `Charge`, `Dispute`, `Event`) but no operational runbook and no alert. A dispute arrives in Stripe email only. | HIGH |
| PAY-3 | A price change breaks fulfilment if the catalogue and the provider drift. `bridge.py` mints both from one `PriceDecision`, which is the right design. It stays a human action on purpose. | ACCEPTED |
| PAY-4 | Stripe automatic tax is enabled (`StripeProvider.cs:432-442`). Registration thresholds are a business decision, not a code one. | ACCEPTED |

### ENG — engine operations

| ID | Risk | Sev |
|---|---|---|
| ENG-1 | **38 finished packs cannot be bought — now a probe, not a number.** `python -m ops.automations.stranded_packs` (2026-08-16): 38 of 100 passed packs stranded, 62 sellable; 29 fail the content lint and 9 were never linted. Blocking rules: grammar 27, citation_urls 27, shelf_copy 25, title_new_word 11, title_claim 7, currency 6, title 3, placeholders 2, marketing_audience 1. The 9 never-linted are free to clear (`tools.publish_passes --dry-run --all`, zero model calls); the 29 need copy regenerated, which costs model calls and is a separate explicit job. Re-measured 2026-08-16 (`tools/verify_pass_shelf_coverage.py` → `stranded passes: 36`), against 63 packs listed live (`api.mumchimp.com/catalog/stats` → `{"listed":63,"registered":148}`). Publishing is automated (`consume --publish`); the pack linter blocks them and **nothing ever retries a lint failure**. Today's split: `shelf_copy` 23, **no lint record at all 9**, `title_claim` 6, `title` 3, `citation_urls` 2, `placeholders` 1, plus 5 missing a bundle file. | BLOCKER |
| ENG-2 | **The loudest alert names the wrong cause.** `ALERT.txt` says "Generation DEAD: 8 consecutive barren ticks" and tells the founder to check `claude /login` and MiniMax credits. Measured: 8 of today's 28 ticks carry `generation_suppressed: "grounding degraded: the retrieval probe did not answer within 120s"`. `_trailing_barren_count` (`run_scheduled.py:1691`) skips only guard-skipped and dry-run rows, so a deliberate suppression counts as barren. Meanwhile the consumer wrote 264 dossiers. All three suggested checks are wrong. | HIGH |
| ENG-3 | **Grounding runs on one fast provider.** The chain is four (`config.yaml:259`: `[ddg, exa, searxng, claude_cli]`). exa is out of credits — 8 `Exa search error … 402` lines today, first at 04:24:01Z, latest 09:55:16Z, and no alert fires on any of them. searxng measures 0.10 mean coverage against `min_relevance` 0.35. claude_cli works but is the slow backstop (97.7s mean, 262s max — `config.yaml:225`). So ddg carries the fast path alone, and when ddg is slow the gate suppresses generation, which is what ENG-2 mislabels. **Decision 2026-08-16: leave exa in place, review later** — see §4. Row corrected 2026-08-16, note below the table. | HIGH |
| ENG-4 | 25 MiniMax calls hit the 600s hard deadline today. Up to 4 hours of wall clock spent learning nothing. Measure before fixing. | MEDIUM |
| ENG-5 | Logs and state grow unbounded: `launchd.err.log` 25 MB, `store/` 546 MB, no rotation code anywhere. 54 GiB free, so this is slow — but a full disk stops the daemon, the backup and the build at once. **CLOSED 2026-08-16, PR #241.** `ops/automations/log_rotation.py` rotates every log declared in `ops/config/log_rotation.yaml`, daily at 04:00. It copy-truncates rather than renaming, because a rename leaves a running daemon writing into the renamed file; the test pins the inode across a rotation. First run compressed 62.7 MB into 5.5 MB. **This was never only a disk risk:** the unrotated `launchd.err.log` is what made a lifetime `grep -c` read as today's count and put the wrong ENG-3 number in this document. `store/prospector.jsonl` (211 MB, 761,090 lines) is deliberately excluded — it is the durable spend ledger, not a log, and truncating it changes what the daily cap believes. | ~~MEDIUM~~ CLOSED |
| ENG-6 | **Docs describe a system that no longer exists.** 11 docs name `cursor_cli` (deleted 08-06), 4 name `standardcompute` (deleted 08-15), `RUN.md:95` names a Gemini quota, `RUN.md:60` points at a 0-byte stub. 3 docs are untracked. One real runbook exists (`AMBITION_LANES_RUNBOOK.md`, 08-01); there is none for start, stop, recover, publish, deploy, restore or key rotation. | MEDIUM |
| ENG-7 | Two guards are off: the batching guard is inert (`~/.claude/state/toolguard/OFF`), and the control-centre password is `test` on a tailnet-only address. | MEDIUM |

**Correction to ENG-3, 2026-08-16.** The first draft of this row said exa had returned 402 "from
03:15Z — 97 error lines today", and described a three-provider chain. Three things were wrong.

1. **97 was not today and not all exa.** It was `grep -c '402'` over an unrotated 25 MB log whose
   lines span 2026-08-06 to today, many of them from an older chain naming tavily and brave.
   Counting only exa-attributed 402s gives **8, all dated today**:
   `grep -c 'Exa search error.*402' store/scheduler/launchd.err.log` → 8.
2. **03:15Z was wrong.** The first exa 402 today is at 04:24:01Z.
3. **The chain has four providers, not three.** `config.yaml:259` reads
   `provider: [ddg, exa, searxng, claude_cli]`. The row omitted searxng.

The risk it names is still real and still HIGH: one fast provider carries grounding. The numbers
behind it were not. A count taken from an unrotated log is a lifetime count wearing today's date —
which is also why ENG-5 (no log rotation) is not only a disk-space risk.

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

> **"Move the engine off this Mac" has outgrown a paragraph.** The founder asked for the full
> migration on 2026-08-17, with the laptop kept as a cold failover and the process repeatable to a
> third provider. That audit, its 16 edge cases, the phased plan, the user stories and the estimate
> live in **`docs/ENGINE_MIGRATION_PROGRAM.md`** — read it before touching KEY-1. The half-day
> estimate at the foot of this section covers only the paths-and-systemd half. The founder set the
> deadline to one night on 2026-08-17, so the plan is 12 steps and about 6 hours with two abort
> gates, not the 9.5-day programme the first audit priced. Its first blocker is not infrastructure:
> it is `claude_cli`'s dependency on the Claude Code subscription
> (`prospector/claude_cli.py:191`).

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
| **Money** | **built 2026-08-17, PAY-1 only** | PAY-1 live-mode assertion and the unsellable gap. Revenue, PAY-2 disputes and the canary checkout are named on the screen as gaps with the route that would close each — they need `GET /internal/ops/sales-audit` and `GET /internal/ops/disputes`, which do not exist |
| **Data** | **built 2026-08-17** | DAT-1 off-Fly copy age, DAT-2 last restore drill (receipt `store/ops/restore_drill.json`), DAT-4 RPO stated as the age of the newest copy, AST-1 bucket versioning |
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
1. **DAT-1**: hourly copy of `/data/store.db` off Fly into R2, verified, alerting if the newest
   copy is over 26h old. **DONE — measured 2026-08-17.** `git ls-tree --name-only origin/main` now
   lists `ops`, and `origin/main:ops/config` carries `offsite_backup.yaml`; the newest line in
   `store/offsite_backup.log` reads `OK data-protection-keys: 0.0h old`. (This line said "NOT done"
   from 2026-08-16, when #240 was still an open branch. It merged. The correction is the measurement
   above, not this sentence.) Shipped daily rather than hourly: the
   database changes on a purchase, and at 3 orders total an hourly copy buys nothing over a daily
   one and costs 24x the R2 calls. The window is declared in `ops/config/offsite_backup.yaml`
   (`max_age_hours: 24`), so raising the cadence is a YAML edit, not a code change. Alerting is the
   console line (item 8), not yet built; today the receipt is the daily green line in
   `store/offsite_backup.log`.
2. **SRC-1**: commit the branch in slices by explicit path (never `git add -A` — `store/` and
   `storage/` are tracked runtime state pytest writes to), merge `origin/main`, tag `launch-rc1`.
3. **SRC-2**: turn on branch protection for `main` — required checks, no force push, signed commits.
   **BLOCKED on a paid plan — measured 2026-08-17.** Both server-side routes refuse on a private repo
   on the Free plan. `gh api -X PUT repos/chidionyema/prospector/branches/main/protection` and
   `gh api -X POST repos/chidionyema/prospector/rulesets` (rules `deletion`, `non_fast_forward`,
   `required_signatures`) each return HTTP 403 `Upgrade to GitHub Pro or make this repository public
   to enable this feature.` This is a founder decision, not an engineering one: GitHub Pro is about
   $4/month, and making the repo public is not an option. Until it is paid for, nothing on the GitHub
   side stops a force push or a delete of `main`, and the only fence is local to this machine.
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
3. ~~Clear the 35 — read-only report first~~ **read-only half done 2026-08-16**: `ops/automations/stranded_packs.py` reports 38 with the blocking rule per pack. The `--fix` half is deliberately NOT in that automation (repair costs model calls; R8/P3) and is still to build.
5. **Console:** the Catalogue screen gets a one-click 'repair and republish' on any stranded pack.
**Done when:** stranded count is 0, the check runs per tick, and the count is a line on the console home. **The console line is DONE (2026-08-19), and the 2026-08-17 correction above it was itself wrong.** `prospector/ops/automations_view.py` does exist. What was true is that nothing called it: it was written, tested and reachable from nothing — not `READS`, not the browser allow-list, not a page. That is why log rotation could be scheduled, running and freeing 1.0 GB a week while the console showed no sign of it. It is now wired at `prospector/ops/console_api.py::_read_automations`, listed in `READS`, allowed in `store_platform/src/Ops.Console/src/pages/api/ops/read/[view].ts`, and rendered by the Automations card on `/processes`. The view discovers its own subjects — any `ops/automations/<name>.py` with an `ops/config/<name>.yaml` beside it — so a new automation is two files and no console edit. `tests/unit/test_a_view_module_with_no_caller_is_unreachable.py` fails if the next view module is written and left unwired. Read-only and `--fix` rows for each automation are on `/tools`. Live on 2026-08-19 the card showed 5 automations, 2 needing attention.

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
2. ~~**`scripts/doc_lint.py` in CI**~~ **DONE 2026-08-18.** It runs two ways, and it needed both.
   `tests/unit/test_doc_lint_never_increases.py` holds a per-file ratchet in the python lane, but
   that lane is path-filtered on `.py`, `tests/`, `scripts/` and a few config files, so a pull
   request changing ONLY documentation skipped it — the one change that can break a doc. The
   `guard` job now runs `python3 scripts/doc_lint.py --check` on every pull request with no path
   filter, no virtualenv and no extra runner slot.
3. Move superseded docs to `docs/attic/` with a one-line reason. Never delete — the incidents are
   the reasoning behind current rules.
4. ~~Fix `RUN.md:95` (Gemini) and `RUN.md:60`~~ **DONE 2026-08-18.** Step 7 already pointed at
   `publish/publish.py`, the real 10,627-byte module. There used to be a 0-byte `prospector/publish.py` stub beside it; that file was deleted in #312 and no longer exists, which is why the shorthand it  <!-- doc-lint-ok: the sentence is about a file deleted in #312; naming it is the point -->
   used to name has no importer anywhere in the repo and is deleted. Three Gemini references
   survived the earlier pass — the retrieval line in step 4, the `generate --resume` comment and a
   heading claiming the batch command reads `GEMINI_API_KEY`. All three now name the config key
   that decides, not a brand, which is what made them go stale in the first place.
5. **Console:** the **Compliance** screen — every item in BIZ-1..4 with a date and an owner — and a
   deep link from every alert to the runbook section that answers it.
**Done when:** `doc_lint.py` exits 0 in CI, the runbook covers every task above, and every red line
on the console links to the runbook line that clears it.

### Decisions only the founder can make — with the cheapest credible option named

Cost is a constraint, so each one gets its free-or-near-free answer. **Every P0 blocker fix is
free**: the off-Fly database copy lands in an R2 bucket we already pay for (pennies at this size),
and commit, mirror, live-mode assert and company details cost nothing but time.

- ~~**SRC-3 — public or private?**~~ **Answered, and there was never a question.** The repo is
  already `PRIVATE` (`gh repo view chidionyema/prospector --json visibility`, 2026-08-17), and the
  founder confirms the public state was not deliberate. The rulesets worry was hypothetical and is
  moot: the rulesets protecting `main` are live on the private repo today (SRC-2). The only
  leftover is the MIT `LICENSE` file, which grants terms to people who cannot fetch the source.
  Deleting or changing it is cosmetic and can wait.
- **BIZ-2 — solicitor?** Split it. **BIZ-1 is free and mandatory**: publishing a company number, a
  real registered address and VAT status is typing facts you already have. Do that this week. The
  *review* is the optional, paid half — defer it until revenue justifies it, and record that as a
  decision with a date rather than leaving it as an open question.
- **ENG-3 — fund exa or drop it?** **Neither, yet. Leave exa in the chain and review it later**
  (founder decision, 2026-08-16). The drop was the wrong call to make now for two reasons. A 402 is
  a billing state, not a verdict on the provider: it reverses the day the account is funded, and
  deleting the tier turns a reversible outage into a config change plus a re-measurement. And the
  cost of leaving it is bounded and already paid — a dead tier costs one failed call per request
  and the health file benches it for an hour (`health.py:54`), so it is latency on the first call
  after each expiry, not on every call.
  **What to do instead, in order.** (1) Make the 402 visible: the provider-credit alert in P2 is
  what turns "97 error lines nobody read" into one line that names the provider and the amount.
  (2) Keep measuring: `_mean_coverage`, 5 real queries, head-to-head. ddg measured 0.40 mean
  coverage against `min_relevance` 0.35, searxng 0.10.
  **Review trigger.** Revisit when either is true: ddg's measured coverage drops below
  `min_relevance`, or the alert shows exa still unfunded after the first paying month. Until one
  fires, this is closed, not open.
- **BIZ-6 — second pair of hands?** **Do not hire; remove the need.** The cheap substitute for a
  person is three things that are already in this plan: the off-Fly backup (P0.1), the single
  runbook (P5.1), and credentials in a password manager with emergency access granted to one
  trusted person. Cost: a password-manager subscription, not a salary.

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
.venv/bin/python scripts/ops_state.py             # local probes, seconds
.venv/bin/python scripts/ops_state.py --network   # adds fly, gh, dns and the live API
.venv/bin/python scripts/ops_state.py --json      # machine-readable
```

That is the whole of §6 now. It used to be a list of commands with the answer written beside
each one as a comment, and every one of those answers was measured once and then rotted.
Checked 2026-08-17, four were wrong: uncommitted files said 201 and were 48, visibility said
PUBLIC and was PRIVATE, the catalogue said `{"listed":62,"registered":146}` and was
`{"listed":68,"registered":158}`, and `ENG-1: 35 stranded` was already corrected to 7
elsewhere in this document while §6 still said 35. A number written next to a command is a
claim about the past wearing the clothes of a measurement.

Each probe is bounded and independent. One that cannot answer prints `UNREACHABLE` and its
reason, and never stops the others — `SRC-2` does exactly that today, because rulesets on a
private repo need GitHub Pro, so branch protection can only be read in the web UI.

Sample run, 2026-08-17, kept as a receipt rather than as the answer:

```
SRC-1   uncommitted paths in this checkout             48 uncommitted path(s)
DAT-3   spend ledger size                              258,347,707 bytes (258.3 MB)
DAT-5   last store backup line                         STORE_BACKUP PASS dossiers=2579 verified=8/8
ENG-3   Exa 402s in the scheduler error log            14 line(s)
ENG-3   retrieval chain declared in config.yaml        provider: [ddg, exa, searxng, claude_cli]
ENG-4   hard-deadline kills in the scheduler error log 15 line(s)
ENG-7   operator roster declared in config.yaml        operator: [minimax, claude_cli] | moat_primary: [minimax, claude_cli]
KEY-1   which checkout production runs from            both daemons in prospector-live, 2 behind origin/main
OPS-1   launchd job definitions vs snapshot            PASS, 29 job(s) match
SRC-2   branch protection on main                      UNREACHABLE: private repo on a free plan
SRC-3   repository visibility                          PRIVATE (isPrivate=True)
INF-1   API machines and regions                       1 machine(s), regions=lhr, state=started
DAT-1   the volume holding the catalogue               vol_4ql6dzwjylqeygnr 1GB lhr attached=True
AST-1   live catalogue counts                          {"listed":68,"registered":158}
DNS-1   domain registrar and nameservers               123-Reg Limited, NS03/NS04.DOMAINCONTROL.COM, expires 2027-06-16
DNS-3   DKIM record                                    EMPTY — DKIM not published
```

---

## 7. Ledger — append results here

| Date | Item | Result | Receipt |
|---|---|---|---|
| 2026-08-16 | Full audit: infra, DNS, data, assets, repo, business, money, engine | 9 groups, 41 risks | this document |
| 2026-08-16 | SRC-2 re-probed | **RESOLVED** — ruleset `strict` protects `main`; legacy endpoint lied | `gh api repos/…/rulesets` |
| 2026-08-16 | PAY-1 re-probed | narrowed to HIGH — `isLive` computed at startup, never reported | `MoneyRailConfigGate.cs:88-94` |
| 2026-08-16 | Paddle audited | not in use anywhere; partial implementation; 5 latent defaults | PAY-5 |
| 2026-08-16 | ENG: daemon died and stayed dead | **FIXED** — `com.prospector.scheduler` was not loaded in launchd, so `KeepAlive` could not relaunch it and all three "launchd will relaunch it" lines in `_kill_stale_daemon` were false. Watchdog now checks and re-bootstraps; console gets a Start/Restart button (P3, "survive without you") | `prospector/ops/supervisor.py`; proved by bootout → repair → pid 18296, receipt `changed:true` in `store/ops/intents.jsonl` (doc-lint-ok: untracked runtime state) |
| 2026-08-16 | ENG: what unloaded that launchd job | **UNPROVEN** — no repo script or test boots out that label; `log show --last 12h` had no record. Next occurrence leaves an alert + timestamped receipt | open |
| 2026-08-16 | PAY-1 built | `MoneyRailStatus` records the live-or-test decision the gate already made; `GET /healthz/money-rail` serves it; `deploy-api.yml` fails the deploy on `"mode":"test"` and on `"decidedAtUtc":null` | `dotnet test` 42 passed / 0 failed with `STORE_INTERNAL_API_KEY` and `PROSPECTOR_ENTITLEMENTS_API_KEY` unset |
| 2026-08-16 | SRC-4 built | `mirror_repo()` bundles every ref and uploads it to the R2 bucket the nightly 03:40 job already uses, so the one-remote risk needs no second scheduled job. Verifies the bundle before upload, reads it back, prunes only after the read-back passes. `--skip-mirror` opts out | `scripts/backup_store.py:568`; `pytest tests/test_repo_mirror.py -q` → 4 passed. Written by MiniMax through the pi-bridge; its fake read `cmd[1]` (`"bundle"` for both git subcommands) so all 4 tests died on a FileNotFoundError blaming `mirror_repo` — fixed to `cmd[2]` |
| 2026-08-16 | DAT-1 correction | **NOT done.** The doc claimed done via PR #240; `git ls-tree HEAD` has no `ops` entry and `gh pr list` shows #240 still OPEN. A claim about a branch is not a claim about main | `git ls-tree --name-only HEAD`; `gh pr list` |
| 2026-08-16 | Shelf backlog correction | 7 stranded PASSes, not 37/38 | `console_api act shelf.publish_pending --preview` names exactly 7 dossiers |
| 2026-08-16 | P0.7: the live ops console was in no commit | `store_platform/src/Ops.Console` was absent from the working tree and from `HEAD`, while launchd job `com.prospector.ops-console` served it from `.claude/worktrees/agent-aaecfffaa54620133`. Its own receipts re-run and green, then copied into the repo | `tsc --noEmit` clean; `vitest run` 46 passed / 5 files. Full branch merge measured 20 conflicts (`git merge-tree`), so the subtree was taken alone; the repo's `prospector/ops/` is the superset (console_api 2031 lines vs 1507, plus `supervisor.py` and `undo.py`) |
| 2026-08-16 | Shelf: publishing the backlog does NOT clear it | **The stranded PASSes are not waiting for a publish button; they fail the content lint.** Every pack the run reached was published UNLISTED and skipped Stripe: each `has no billable price id ('price_stub_…')`. Reasons, one per pack: `482d0cdb9ec04d27` cites a URL that now returns 404; `7ba29bd2956e7e04` repeats `title` and `subhead` verbatim in the one-liner and leads with a coined name; `83f2e75faa80bb60` fails both the structural audit and the lint. So the work is the lint repair loop, not the publish path | run pid 49352 timed out at 1800.3s (`applied:false, changed:true, timed_out:true, exit_code:null`); reached 4 packs — `482d0cdb9ec04d27`, `7ba29bd2956e7e04`, `83f2e75faa80bb60`, `c763afa7fdd424b6`; shelf still reports 5 pending after the run |
| 2026-08-16 | Shelf: `Complete_Pack.pdf` cannot render for some packs | A code defect, not a copy defect, and it blocks the whole bundle for any pack it hits: `Named destination 'main-content' was referenced but never set with set_link(name=...)`. The renderer emits an internal link to an anchor it never registers, so the PDF raises instead of writing | seen on `83f2e75faa80bb60` in the same run; blocks its structural audit |
| 2026-08-17 | Shelf copy: the linter was the blocker | The content lint held 31 of 33 defective live rows off the shelf. Fixed, plus the `pack_pdf` fpdf2 anchor crash that blocked whole bundles, and `doc_lint` machine-dependence (88 findings in this checkout vs 91 in a worktree, same commit) | PR #247 `pr/pack-pdf-anchor-doc-lint-repo-mirror`, gate PASSED at `67a4ff2` |
| 2026-08-17 | Shelf copy: initialisms spelled out from a declared glossary | A glossary lives in `config.yaml listing.initialism_glossary`. The sweep never guesses an expansion: an unknown term is REPORTED, and a proposed rewrite is dropped unless it strictly lowers the errors the gate would raise. Measured `live packs: 104  defective: 33  rows the glossary alone repairs: 25`, zero provider spend | PR #248 `pr/shelf-copy-glossary` at `519ce28`; `131 passed in 36.26s`. Eight terms remain unexplained — CAP, CI, DCB, METRC, PL, RTY, SBS, STRS — and four are not initialisms at all (`CI`/`PL` are caps-run fragments, `RTY` is from the model number `PA RTY-100`, `METRC` is a product name), so that copy needs rewording |
| 2026-08-17 | Programme status made mechanical | `scripts/ops_status.py` grades all 44 ids against `origin/main`, never against the working tree. It caught two of my own wrong claims on first run: SRC-4 and PAY-1 were reported closed and live only in the unmerged PR #247 | `ACCEPTED: 7  DONE: 3  MANUAL: 24  OPEN: 10  TOTAL: 44`. Provably done on `origin/main`: SRC-3, DAT-1, ENG-5 |
| 2026-08-17 | Handoffs no longer collide | `checkpoints/LATEST.md` was overwritten by another session minutes after it was written, with 18 Claude processes and 59 worktrees on one checkout. Each session now writes `checkpoints/session-<id>.md` and `LATEST.md` is a generated index of all of them | `scripts/handoff.py --write / --index / --read` |
| 2026-08-17 | Duplicate work made visible | `ops_status.py --claim ID` writes a claim to `<git-common-dir>/ops-claims.jsonl`, which every worktree of this repo sees. A second session claiming a held item is refused by name and branch. Claims go stale after 12h so a dead session cannot block an item forever | `--claim ENG-6` then a second claim from another session exits 1 with the holder's id; verified the register is shared via `git rev-parse --git-common-dir` |
| 2026-08-17 | Money and Data screens built; the nav regrouped | The two missing halves of §3.5 now have screens. Money reads `GET /healthz/money-rail` and splits it four ways — `live`, `test`, `never-ran` (`decidedAtUtc` null) and `unreachable` — because a rail nobody checked must not read as a rail that was checked and found to be in test. Data runs the backup automation read-only (`fix=False`, so opening the screen never takes a backup), reads the restore-drill receipt, asks the bucket for versioning, and states the RPO as the age of the newest copy. What is NOT measured is printed on the screen with the route that would close it: revenue and disputes need `/internal/ops/sales-audit` and `/internal/ops/disputes`, neither of which exists. The nav was one flat strip of thirteen tabs that ran off a 390px phone; it is now six groups plus the screens in the open group, both rows wrapping | `prospector/ops/money.py`, `prospector/ops/data.py`, `console_api.py` READS `money`/`data`, `pages/money.tsx`, `pages/data.tsx`, `lib/nav.ts`; `scripts/restore_drill.py` now writes `store/ops/restore_drill.json` on pass AND on fail |
| 2026-08-16 | P0.8: daemon visibility AND admin on the ops console | `status` read now carries a `supervisor` block — per launchd job: held / not held / could-not-ask, pid, plist. That is the fact a heartbeat cannot give: a process can be beating and still unheld, which is exactly how the engine stayed dead. Engine page gains a Processes card rendering it beside the heartbeat, with a Restart button on the existing `daemon.restart` action | `console_api.py::_supervisor_view`; `read status` returns both jobs `loaded:true`, pids 30686 and 18296 |
| 2026-08-17 | ENG: production ran from the shared dev checkout | **FIXED.** The scheduler and consumer ran from `/Users/chidionyema/Documents/code/prospector`, a developer checkout sitting on whatever branch a session left it on. On 2026-08-17 that was `integrate/minimax-into-main`, 75 commits behind `origin/main`, so the daemon executed 17-hour-old code and changing a branch meant changing production. Both jobs now run from `/Users/chidionyema/Documents/code/prospector-live`, detached at `origin/main`, with `PROSPECTOR_STORE_DIR` pinning state to the canonical store. `scripts/live_checkout.py` reports it and `--update` rolls it forward; both are console buttons | `lsof -a -p <pid> -d cwd` on pids 99793/99800 → `prospector-live`; live HEAD == `origin/main` == `1800f38`; plist backups at `~/Library/LaunchAgents/*.plist.bak-2026-08-17` |
| 2026-08-17 | ENG: the move benched every MiniMax tier | **FIXED.** Git does not carry secrets. The new checkout had no `.env`, so the first tick after the move failed with `ProviderExhaustedError: All operators in ('minimax', 'minimax_m27') unavailable — check API keys and credentials`. `.env` and `.lux/keys/agent.pem` are symlinks back to the dev checkout, and the probe now checks both | `store/scheduler/launchd.err.log` 2026-08-17T12:54:05Z (failure) → 12:58:11Z tick generating with no exhaustion error after the link at 13:57 local |
| 2026-08-17 | ENG: moving the code split live state in two | **FIXED.** `PROSPECTOR_STORE_DIR` kept the ledger and dossiers canonical, but four constants derived the store from `Path(__file__)` and so followed the CODE: `provider_health.json`, `provider_health_noncritical.json`, `store/_cache/` and `store/scheduler/audit/`. For twenty minutes the daemon wrote health marks in one directory while every probe read the other — the state in which a benched provider can never be seen to recover. `config.store_root()` is the single resolver now (health, retrieval, audit, golden). With the env var unset the paths are byte-identical to before | leaked writes measured after the 13:52 clone: health 14:04, `_cache` 14:12, audit 14:13, against 948 files in the canonical store in the same window. 1748 audit rows and 237 cache files carried back; the four live paths are symlinks until the fix reaches main. `pytest -k "health or audit or store_dir or golden or cache or console_tools"` → 172 passed |
| 2026-08-17 | CI: `origin/main` was red, so every PR inherited the failures | **FIXED.** Four separate faults, none of them in any PR's own diff. (1) `MoneyRailStatusTests.NonStripeProvider_RecordsNotApplicable` asserted a state that could not exist: `MoneyRailConfigGate.StartAsync` throws for any provider missing from `RequiredKeys`, and stripe is the only entry, so `GuardStripeApiKeyShape` never saw a non-Stripe provider. The fail-closed throw is right and stays; the dead branch, the mode and the test went, and the test now pins the throw. (2) One em dash in `Store.Web/src/lib/config.ts:120`. (3) Four CI scripts landed unclassified in the console tool registry. (4) `PADDLE_API_KEY` was the last mention of the retired provider, in `test_dotenv_fence.py`. Also removed: an unresolved merge conflict committed into this file at lines 494-497, with a test so the next one cannot reach main | `dotnet test --filter MoneyRail` → 40 passed; `vitest dashFree` → 8 passed; `pytest test_console_tools_run test_retired_terms test_dotenv_fence` → 46 passed; `pytest test_no_conflict_markers` → 1 passed |
| 2026-08-17 | OPS: the console tool registry had drifted | **FIXED.** Three runnable scripts had no button and nothing stopped the hand-written registry drifting again. Buttons added, plus `NOT_AN_OPS_TOOL` so every file in `tools/` and `scripts/` is either registered or carries a written reason it is not. A test walks both directories and fails on a file in neither list, and on a stale exclusion naming a file that no longer exists | `pytest tests/unit/test_console_tools_run.py -q` → 25 passed; PR #255 |
| 2026-08-17 | Main carried conflict markers in this file, and a page fell out of the nav | `origin/main` at `81bca3f` (PR #260) committed three literal conflict-marker lines into this section, so every branch that merges main inherits them. Removed here. The same PR rewrote `lib/nav.ts` as grouped data and gave it no entry for `pages/method.tsx`, which exists only on this branch, so the merged tree broke the `every screen is reachable from the nav` assertion in `tests/nav.test.ts`. `/method` is in the Control group now | `git show origin/main:docs/LAUNCH_OPS_PROGRAM.md` greps 3 marker lines at 494, 496, 497; after this merge the same grep over every tracked file returns nothing. Nav checked without node_modules by replicating the test: nav entries with no page 0, pages with no nav entry 0, duplicates 0 |
| 2026-08-19 | Logs: the retention policy existed and nothing ran it | **FIXED.** `ops/automations/log_rotation.py` was report-and-rotate only, on no schedule. It now prunes by AGE as well as by size, which is the half a rotator cannot do — a directory of many small files never trips a size threshold and grows forever. Scheduled as `com.prospector.log-rotation` every 6h from the live checkout, writing to the canonical store | `~/Library/LaunchAgents/com.prospector.log-rotation.plist`; `StartInterval 21600`; `PROSPECTOR_STORE_DIR` pinned to `…/prospector/store` |
| 2026-08-19 | Logs: one policy for Hermes and for the estate | Hermes logs were outside every policy on the grounds that Hermes is not production. Volume does not care. Both are now described in one place, with what is kept, for how long, and where the copy lives | `docs/LOGGING_AND_RETENTION.md` |
| 2026-08-19 | CI: security and build gates in all three languages | Five gates added and everything they found cleared. Bandit at HIGH, and it also fails when bandit could not READ a file — `uvx` had been running it on Python 3.11.15 against a 3.14 repo, so one file came back a syntax error and was recorded in a JSON field nothing read. pip-audit, after filtering the editable requirement lines it ABORTS on rather than skips; three of 121 lines had been killing the whole audit. A step that parses every `Directory.*.props` before `dotnet restore`, because two hyphens in an XML comment silently turn off Central Package Management and restore then blames twenty-one innocent packages by name. `npm audit --audit-level=high` on both web apps | PR #393. `dotnet` 0 Warning(s) 0 Error(s), Store.Tests 365 passed; bandit `errors: []`, 348 findings, 0 HIGH; pip-audit found and pinned pillow 12.2.0 and pyasn1 0.6.3, six advisories between them; `ruff check .` clean. Written up in the code quality gates doc that PR #393 adds |
| 2026-08-19 | CI: a guard that could not fail was deleted, not kept | The props-file parse check was first a C# test. With the file broken MSBuild will not evaluate `Store.Tests.csproj`, so the assembly never loads and the test never runs. A guard has to fail on the ASSERTION, not before it. Moved to a pre-restore CI step and mutation-proved | `dotnet test --no-build --filter EveryBuildPropsFileIsWellFormedXml` printed MSB4024 and nothing else; the CI step exits 1 naming the file, line 47 column 15 |
| 2026-08-19 | Repo: a source file git could not see | `BuildFileTests.cs` landed in a `Build/` directory and `.gitignore` line 9 is `build/`. This filesystem is case-insensitive, so git ignored the directory and `git status --untracked-files=all` showed nothing. A source file git ignores is a file no reviewer and no CI job can see | A guard test added by PR #393, 2 passed. Its second test plants an ignored file and asserts the guard finds it |
| 2026-08-19 | Work strands tracked in one place | Strands lived in a per-session task list nobody else could read, and in chat replies that scroll away. `WORK_REGISTER.md` carries every strand — closed, in flight, blocked on the founder, and known-but-ungraded — each with the receipt or an explicit "unproven" | `docs/WORK_REGISTER.md` |

---

## 8. How this programme is run

Added 2026-08-17, after the founder said the team was "inefficient and chaotic". Every rule
below is a COMMAND, not a convention, because the conventions already existed in prose and
were not followed. If a rule here cannot be run, it does not belong in this section.

**1. Status comes from the probe, never from this document.**

```bash
.venv/bin/python scripts/ops_status.py --fetch
```

It grades all 44 ids against `origin/main`. A file in your working tree proves nothing: it
may be uncommitted, on a branch, or in another session's worktree. `MANUAL` means no
mechanical check is written yet and is never counted as done — it is a gap in the probe, not
a claim about the work. When this document and the probe disagree, the probe is right and the
document gets fixed.

**2. Claim an item before you start it.**

```bash
.venv/bin/python scripts/ops_status.py --claims             # who holds what
.venv/bin/python scripts/ops_status.py --claim ENG-6 --note "what you are doing"
.venv/bin/python scripts/ops_status.py --release ENG-6
```

The register is `<git-common-dir>/ops-claims.jsonl`, shared by every worktree of this repo.
Claiming an item someone else holds is refused, with their session id and branch. Claims go
stale after 12 hours, so a dead session cannot hold an item forever. This is the only thing
stopping two agents building the same item — `chore/remove-paddle` (PAY-5) sat pushed and
unnoticed for 20 hours while PAY-5 read as open.

**3. Check what the other sessions hold before picking work.**

```bash
.venv/bin/python scripts/ops_status.py --agents
```

Open PRs, live worktrees, and every branch pushed in the last three days. Read it first.
A branch pushed yesterday is somebody's work in progress, not an open item.

**4. Land before you start something new.** An open PR is unfinished work, not finished work.
Six PRs were open at once on 2026-08-17 and none of what they contained was on `origin/main`,
which is why the status was wrong in both directions at the same time.

**5. Write the handoff to your own file, not the shared one.**

```bash
.venv/bin/python scripts/handoff.py --write notes.md   # -> checkpoints/session-<id>.md
.venv/bin/python scripts/handoff.py --read             # everyone's, newest first
```

`LATEST.md` is generated from those and must not be hand-edited. It used to be one shared
file and a session's notes survived about ten minutes.

**6. Bulk mechanical implementation goes through the pi-bridge**, with Claude planning and
verifying. Money rail, identity, contract and migration work never leaves Claude; the bridge
refuses it in the server rather than in a prompt.

## 9. Working-method defects — the register

On 2026-08-17 the founder raised about twenty-five distinct complaints in a single session.
None of them was written down anywhere. They were answered one at a time, each answer was a
piece of code, and the next session would have started from zero. That is the defect this
section exists to stop: **an issue that is felt but not tracked is an issue that recurs.**

The complaints are not twenty-five problems. They are five, and they share one root cause.

**Nothing we produce is graded by anything except the person who produced it.** Every item
below is a consequence of that. An agent asserts a claim and grades it itself. An agent ships
a script and decides itself that it works. An agent picks a route and judges its own
efficiency. There is no independent, automatic grader anywhere in the loop, so nothing can
fail, so nothing improves.

Each cluster carries the one number that says whether it is fixed. **A cluster with no number
is not being worked on; it is being complained about.** Where a number does not exist yet,
that is stated rather than papered over.

---

### WM-1 — Claims made without proof

*Raised as:* "you need to be careful"; "delete ~23,000 lines. wtf"; "look this is really
irresponsible"; status reported without checking.

*Measured:* three false claims in one session — "PR #247 passed the gate" (no gate ran;
`core.hooksPath` is unset and `.git/hooks/pre-commit` does not exist), "merging deletes
~23,000 lines" (a two-point diff against a moved branch, read backwards; the true figure is
198 files / 31,522 insertions), "~22 items open, 4 console screens missing" (there are 44 ids
and 11 console pages; the search looked for App Router files in a Pages Router app).

*Costs:* a wrong claim was minutes from being published into a PR body, where it would have
justified closing work that was fine.

*Number:* false claims per session, counted from the transcript. **No probe exists yet.**
`~/.claude/scripts/reflect.py` finds where the founder stopped an agent, which is a proxy, not
this. It lives in the harness config, not in this repo — `ops/launchd/com.chidionyema.reflect.json`
is what runs it.

*State:* OPEN.

### WM-2 — Work that is never graded, and quietly goes inert

*Raised as:* "no spec no trace lots of invisible solutions broken"; "we write code for
everything but never follow up to see if its effective"; "half baked code and forgotten
about".

*Measured:* **10 of 16 mechanisms in `~/.claude/scripts/` have nothing that invokes them** —
`rule-guard.py` and `reflect.py` among them, both written the same day they were measured as
inert. `batching-compliance.py`, `cost-baseline.py`, `cost-guard-probe.sh`,
`cli-cache-experiment.py`, `estate-cost.py`, `estate_spend.py`, `cc-token-report.py` are the
archaeology of earlier programmes. The repo itself is healthy by comparison: 22 scripts, one
unreferenced.

*Costs:* every one of those was a day that felt like progress and changed nothing.

*Number:* **inert mechanisms: 10 of 16 (62%).** Target: every mechanism either wired to an
invoker or deleted. The audit is the loop in §9's closing rule.

*State:* OPEN, and it is the cheapest of the five to close.

### WM-3 — Knowledge that does not act

*Raised as:* "all the rules you enforced, are they working?"; "we have no way of enforcing
violations"; "repeating same failures"; "junior engineer forever, no improvement or
learning".

*Measured:* 333 memory files, two of which describe the exact two-point-diff mistake that was
then made twice in one day with both memories loaded in context. 13 hook scripts installed and
exactly one (`hang-guard.py`) that can refuse anything. The rules that RUN are obeyed; the
rules that are READ are not.

*Costs:* the same mistakes at the same cost, indefinitely.

*Number:* **1.68 founder-stop events per 100 tool calls** across 343 transcripts and 41,319
calls, from `~/.claude/scripts/reflect.py`. July 0.63, August 1.79 — the rate nearly tripled. Any
behaviour rule that lands must move that number or be deleted.

*State:* OPEN. `~/.claude/scripts/rule-guard.py` exists, passes its own selftest, and **has
never run** — the `settings.json` wiring was refused by the permission classifier twice and
the founder has to paste it.

### WM-4 — No route discipline

*Raised as:* "we always take the longest and convoluted route which gets us distracted, wastes
tokens and time, does the wrong thing, wrong outcome and ignores the problem"; "why tf u
getting distracted"; "this is what I mean about efficiency"; "just firefighting".

*Measured:* asked why a gate took fifteen minutes, the answer was already visible in
`scripts/popdd_verify.py:246` and `pytest.ini:42`. Instead: a 30-minute suite re-run was
launched for a number that signed receipts already held, followed by an unrelated CI log dive,
followed by a round trip to load a tool to kill the job. Four detours before a one-paragraph
answer. What the founder actually stops, from the transcripts: `Agent` launches 7.8%,
`pytest` runs 6.0%, `AskUserQuestion` 4.9%, shell loops 4.3% — that is 23% of all stops, and
every one of them is *starting something expensive before checking whether the answer already
exists*.

*Note:* the obvious theory was wrong and the data killed it. Read-only drift causes **1%** of
stops. A delegation guard would have been built, would have felt productive, and would have
fixed nothing.

*Number:* the same 1.68 per 100. Same scoreboard as WM-3.

*State:* OPEN.

### WM-5 — Nothing is tracked, grouped, or de-duplicated

*Raised as:* "who is tracking? do they overlap"; "no reasoning about cluster of issues and
grouping"; "just goes into ether"; "are you checking other agent sessions' work and PRs to
ensure no overlaps and duplicated work"; "what happened to all your work from other sessions".

*Measured:* 8 PRs open with nothing merged to `main` since **2026-08-16 14:13**; six blocked.
56 branches under `origin/pr/*` and `origin/fix/*`. Of 44 programme ids, only 3 are provably
done on `origin/main` and 24 have no mechanical check at all. `main` and
`integrate/minimax-into-main` differ by 63 files, so every session picks its own base and
"is it done?" has two true answers.

*Costs:* duplicated work between concurrent sessions, and this register itself — twenty-five
complaints that existed only in a chat window.

*Number:* **items with no mechanical check: 24 of 44.** Target: zero, either by writing the
check or by recording that a human must judge it.

*State:* OPEN. `scripts/ops_status.py` and its claim register are the mechanism; they are in
unmerged PR #250.

---

### WM-6 — The agent goes idle while a run it started is still going

*Raised as:* "this is another founder complaint, this is unacceptable, we need to enforce
multi tasking, i should not be having to sit watch a tool run for 15 mins while agent is idle
and there is work to do" (2026-08-17). Earlier form: "a lot of our time is spent waiting for
tests, we should be able to multitask, we have lots to do" (2026-08-16).

*Measured:* **15 minutes 50 seconds** of wall clock on one turn, one shell running, nothing
else started. The rule "never sit and watch a long command" had been in the global `CLAUDE.md`
since 2026-08-16 and was loaded in context at the moment it was broken. Backgrounding the
command was done correctly; ending the turn afterwards is the part that wasted the clock.

*Costs:* the founder watches a spinner instead of reading results, and pays for the context
re-read when the turn resumes.

*Number:* **turns ended with a background run still in flight.** Now zero by construction, if
the guard is wired. Read it from the guard's own refusals.

*State:* CODE WRITTEN, NOT YET LIVE. `~/.claude/scripts/idle-guard.py` is a Stop hook that
blocks the stop once and names the runs still going; selftest 6/6. It cannot wire itself —
the permission classifier refuses an agent editing `~/.claude/settings.json` — so
`~/.claude/scripts/wire-idle-guard.sh` is the founder's one command, then quit and relaunch.

---

### WM-7 — A complaint is answered, then forgotten

*Raised as:* "you lost track of all the process improvements we are trying to solve"; "in
fact these appear to be two separate workstreams"; "including losing track of founder
complaints, the transcripts, self improvements" (all 2026-08-17).

*Measured:* `reflect.py --complaints` reads every transcript and finds **373 complaints across
1,690 messages**, and it only ever PRINTED them. Nothing survived the terminal, so a complaint
was live only while somebody was looking at it. Worse, on 2026-08-17 the agent started writing
a second complaint scanner from scratch without noticing that reflect.py existed, and started
a second working-method register without noticing this section existed. Losing track produces
duplicate mechanisms, which is the same defect twice.

*Costs:* the same complaint is made three and four times. Work is redone. The founder has to
be the memory.

*Number:* **complaints with no tracked owner.** Read it by diffing the ledger against the task
list.

*State:* PARTLY CLOSED. `~/.hermes/scripts/complaint_ledger.py` persists reflect.py's own scan
to `~/.hermes/state/complaint_ledger.json` — it deliberately adds no scanner of its own.
Registered as capability `founder_complaint_ledger` (period 24h) and scheduled daily at 07:40,
so a stale ledger raises an alarm without being asked. The remaining half is the discipline of
giving each themed complaint a task id.

---

### The rule that closes all five

**Name the number before you start.**

1. **Before** — state the number that is wrong, its value now, the target, and the command
   that reads it. If you cannot name the command, do not start.
2. **Do the work.**
3. **After** — run the same command and record the result next to the prediction, *including
   when it did not move.*

Nothing is done until step 3 exists. A prediction written afterwards is not a prediction — it
cannot catch the case where the number improved for unrelated reasons and the fix took the
credit. That is the difference between a process and a habit, and it is the only thing on this
page that produces learning rather than activity.

Baselines cannot be predicted, only changes. The numbers above are baselines; predictions
attach to the fixes that follow them.

---

### 9.1 — Every session, not one session

The five clusters above were read off ONE session. That was the wrong sample and the founder
said so: "we have all transcripts of sessions, founder complaints etc, not just ur session".

`~/.claude/scripts/reflect.py --complaints` now reads all of them. **1,690 messages he
actually typed, de-duplicated; 373 of them are complaints (22%).** Getting to a number worth
trusting took four passes, and each failure is worth recording because each one is a way a
text measurement lies:

1. Counting every `role: user` record. `role: user` is not "he typed this" — it also covers
   tool results, task notifications, subagent turns, compaction summaries and replayed
   context. First run: 716 complaints, and the verbatim sample was a task-notification block.
2. Filtering those out but still counting whole messages. **He complains by pasting the reply
   he is complaining about**, so the classifier was reading the agent's vocabulary. The tell
   was that all nine themes scored between 173 and 284 — a flat ranking is what matching noise
   looks like.
3. Stripping pasted text by shape (line length, bullets, capitalisation). Better, still leaky:
   he pastes a reply as one long run-on line, so the whole paste survived as a single "line".
4. **Matching the paste against what an assistant actually wrote.** The paste is a copy, so
   the original is in the transcript one turn earlier. `_own_words()` drops any segment of 40
   characters or more that an assistant emitted somewhere on this machine. This is the one that
   works, and it needed no heuristic about his writing style.

The ranking, and the three clusters §9 missed:

| count | theme | tracked by |
|---:|---|---|
| 78 | efficiency / cost / speed | `token-audit.py`, tool-drip-guard |
| 77 | proof / unverified claims | nothing yet — WM-1 |
| 75 | sloppiness / broken output | POPDD gate (CI only) |
| 67 | rushing / scope / firefighting | `rule-guard.py` rule_pr_size — **not wired** |
| 60 | process / no follow-up | this register |
| 51 | repeating the same mistake | `rule-guard.py` — **not wired** |
| 42 | **cannot tell what you are doing** | Ops Console `/method` |
| 41 | **items raised then dropped** | this register |
| 32 | tracking / duplication / other agents | nothing yet |
| 27 | **is it actually shipped** | Ops Console `/method`, `ops_status.py` |
| 26 | communication / format | nothing mechanical |
| 22 | not following instruction | nothing mechanical |
| 89 | (unclustered) | — |

The three in bold were not in §9. They came out of reading the leftover bucket, which is
printed for exactly that reason: **a silent "other" bucket is how a new problem stays
invisible for months.** Together they are 110 complaints — roughly a third of the total — and
they are all one thing: *he cannot see the state without asking.* "hours later i dont even
know wat you are working on and if it is done." "is anything passing? has pricing been fied
and deployed?" "wtf are you even talking about."

That is not a communication problem to be solved with better prose. Prose is what caused it.

### 9.2 — The loop

Four pieces. Each is a command or a page, and none of them is a paragraph.

| # | piece | where | state |
|---|---|---|---|
| 1 | the number | `reflect.py --json` → `store/ops/method_metrics.json` | **live**, `com.chidionyema.reflect` every 4h |
| 2 | the register | `REGISTER` in `reflect.py`, one row per theme | **live**, carried in the snapshot |
| 3 | enforcement | `rule-guard.py`, 5 PreToolUse rules | written, selftest 19/19, **not wired** |
| 4 | visibility | Ops Console `/method` | **live**, `console_api.READS["method"]` |

The register lives in code rather than in this table on purpose. A row here cannot be
executed, so a row here cannot tell you it has gone stale. Every theme carries the command
that reads its number; a theme with no command renders as **untracked** on the page, so the
gap is visible instead of implied.

Staleness is handled the same way: the page refuses to present a scoreboard older than 36
hours without saying so. A dashboard quietly rendering a three-week-old number as state is the
defect this whole section exists to fix.

**Piece 3 is blocked on the founder.** The Claude Code permission classifier refuses an agent
editing `~/.claude/settings.json` — attempted through Bash and through Edit, refused all three
times. He has to paste this into `hooks.PreToolUse`, in the entry whose `matcher` is `Bash`,
next to `hang-guard.py`:

```json
{ "type": "command",
  "command": "python3 /Users/chidionyema/.claude/scripts/rule-guard.py" }
```

`settings.json` is read once at process start, so it takes effect on relaunch, not on
`/clear`. Until it is pasted, nothing about the enforcement layer can be proven — a rule that
has never executed has no evidence behind it, and the honest state is "written", not "done".

### 9.3 — What would prove this worked

**Falsifiable, dated, and it is one command.**

- Number: founder stops per 100 tool calls. **1.70 now** (July 0.63, August 1.82).
- Command: `python3 ~/.claude/scripts/reflect.py --trend`, or the `/method` page.
- Target: **below 1.20 by 2026-09-16. Below 0.80 by 2026-10-16.**
- If it does not fall, the rules were wrong and get **deleted, not defended.**

That last line is the part that matters. Every mechanism in WM-2 went inert because nothing
was ever going to declare it a failure.

### 9.4 — Tokens per move

*Raised as:* "we need to enforce getting the job done with the fewest possible tokens without
impact to quality or speed"; "efficient, surgical, military approach always, for everything,
as behaviour".

The measurable form of that is a **ratio, not a total.** A raw token total falls in a quiet
month, which would reward doing less rather than doing it in fewer moves.

| month | output tokens | tool calls | per call |
|---|---:|---:|---:|
| 2026-07 | 6,655,903 | 3,947 | **1,686.3** |
| 2026-08 | 85,319,454 | 37,506 | **2,274.6** |

**35% worse, month on month.** Output tokens only: an assistant record's input and cache_read
fields describe the whole resident context that turn, so summing them across records counts
the same context once per turn and inflates the total several times over.

Target: back under 1,686.3 by 2026-09-16. That is prediction P2.

### 9.5 — Predictions, and being told you were wrong

"Get better at getting better" is the goal, and it is only real if something can grade it.
`store/ops/method_predictions.json` holds one row per claim: the number it should move, the
value now, the target, and the date it gets scored. `reflect.py` grades every row whose date
has passed and renders `hit`, `missed`, `pending` or `unmeasured` on the `/method` page.

`unmeasured` is deliberate and it is not a failure state to hide. P3 below reads `unmeasured`
because nothing yet writes CI job times into the snapshot. That is visible on the page instead
of being quietly scored as pending.

| id | claim | number | now → target | due |
|---|---|---|---|---|
| P1 | Rules as refusals cut how often he has to stop a call | stop rate | 1.70 → 1.20 | 2026-09-16 |
| P2 | One round trip per intent cuts tokens per move | output tokens/call | 2,274.6 → 1,686.3 | 2026-09-16 |
| P3 | The CI long pole is the nextjs job, not the python suite | slowest job | 1025s → 600s | 2026-09-16 |

A prediction's `made_on` is recorded and never edited. One added after the fact cannot catch
the case where the number improved for unrelated reasons and the fix took the credit.

### 9.6 — CI, carried forward so it does not evaporate

Measured on run `31952065675`, and it overturns the assumption that the test suite is the
problem:

| job | time | outcome |
|---|---:|---|
| python | 96s | **FAIL** — `mkdir: /Users/runner: Permission denied` from `actions/setup-python` on the self-hosted mac runner. Not a test failure. |
| dotnet | 602s | FAIL |
| nextjs | **1025s** | PASS — the real wall-clock long pole |
| engine | 97s | FAIL |

The local test suite is already parallel (`pytest.ini:42 addopts = -n auto --dist loadfile`,
measured 493s at `-n 8`, 324s at `-n auto`), so that lever is spent. The gate is slow for a
different reason: `scripts/popdd_verify.py:246-247` runs ruff and pytest with **no path
arguments**, so any staged `.py` file runs all 4,189 tests. Collection alone is 68s.

This is P3. It is the one open item here that is engineering rather than method, and it is
recorded here so it stops living in one session's head.

### 9.7 — Wiring the guard, since the agent is not allowed to

`~/.claude/scripts/wire-rule-guard.sh`. It runs the selftest first, backs up `settings.json`
with a timestamp, adds the hook to the `Bash` matcher next to `hang-guard.py`, validates the
JSON before writing, and is idempotent. Dry-run against a copy on 2026-08-17 produced:

```
matcher None -> ['tool-drip-guard.py']
matcher Bash -> ['hang-guard.py', 'rule-guard.py']
```

Then **quit and relaunch Claude Code.** `settings.json` is read once at process start; `/clear`
does not reload it. Prove it fired by running `git add -A` — it must refuse.

