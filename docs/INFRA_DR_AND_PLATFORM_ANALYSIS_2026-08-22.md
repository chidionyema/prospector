# Disaster recovery, portability and platform automation — what the estate actually needs

Written 2026-08-22, in answer to two founder asks: "document this and analyse, I think this is a
cheaper way to meet our infra automation and migration/portability and disaster recovery projects",
then "I need research and feedback".

Two proposals were pasted in. The first argues for warm-standby DR on a second provider with
Coolify as the control plane. The second argues for a platform-engineering layer — secrets, feature
flags, telemetry. This document grades both against measured facts about this estate.

Every number below has a command behind it. Where a number could not be verified it says so.

Read it as a page: https://claude.ai/code/artifact/d9c88fd6-cace-460f-9043-2f68a1a67f39
That page is generated from this file, so this file is the source.

---

## 1. The verdict, first

**The proposals are right about ordering and wrong about scale.**

Right: detection ranks above portability; your own deploys are the likeliest outage cause; an
untested standby is a hypothesis, not a plan; portability lives at the container boundary.

Wrong: the DR architecture is sized for a 40 GB Postgres. **This estate's entire production store
is 903 MB of files and there is no Postgres in the engine path at all.** Warm standby with
continuous replication is recurring cost against a problem we do not have.

And the specific thing the founder asked about — Coolify as a cheaper control plane — is a
**downgrade** on two axes that matter here, evidenced in §4.

**The five things that actually shorten recovery time cost £0/month between them.** They are in §6.

| | Proposal says | Measured here | Action |
|---|---|---|---|
| Data volume | ~40 GB Postgres | **903 MB files, no engine Postgres** | Drop streaming replication |
| Portability | Build it | **Already shipped: 4 adapters, contract-pinned by a test** | Nothing |
| Failover | Build it | **`scripts/engine_failover.py` already does it** | Point it somewhere alive |
| Detection | Cloudflare health checks, $5/mo | **`fly.toml` declares no health check at all** | Add the health check first |
| DNS | 60s TTL | 60s TTL buys ~nothing (§5) | Use a proxied edge, not TTL |
| Control plane | Coolify | 21 critical CVEs; backup check is `du -b > 0` | No |

---

## 2. What is actually running

Measured 2026-08-22 via `flyctl ssh console -a prospector-engine`:

```
903M    /data/store
1554703 /data/store/prospector.jsonl
3590    dossiers
458M    prospector.jsonl   233M dossiers   3.0M prospector.db
/dev/vdc  20G  1.8G  17G  10% /data
```

Fleet: **7 Fly apps, 8 machines, 4 volumes, 25 GB, all in `lhr`** — `prospector-engine`
(2 CPU / 4 GB / 20 GB volume), `hermes`, `searxng`, `shadow`, `store-api`, `store-web` ×2,
`tie-web` ×2.

Three facts that kill the pasted DR architecture outright:

1. **The engine store is SQLite plus append-only JSONL, not Postgres.** There is a Postgres 18.1 on
   the `shadow` app, on 1 GB, and **the engine does not use it.** "Continuous replication instead of
   nightly dumps" has nothing to replicate.
2. **903 MB, not 40 GB.** At even a modest 20 MB/s that is well under a minute of transfer. Data
   volume is not what bounds RTO here. Everything else is.
3. **`deploy/PORTABILITY.md` already defines a 6-item platform contract with four shipped
   adapters** — Fly, laptop launchd, `sshdocker` (any Linux box with SSH), and Kubernetes. Each is
   about 90 lines. `tests/unit/test_every_deploy_target_implements_the_contract.py` fails if an
   adapter drops an item. The portability project the proposal wants to start is done and guarded.

### What is genuinely missing

Also measured, and this is the part worth acting on:

| Gap | Evidence | Consequence |
|---|---|---|
| **No health check on the engine** | `deploy/engine/fly.toml` declares none. `store-api`, `store-web` and `tie-web` all do. | Fly cannot distinguish a hung engine from a healthy one. Nothing downstream can either. |
| **No published restore duration** | `scripts/restore_drill.py` runs weekly, prints `RESTORE_DRILL PASS/FAIL` and records `took_s` — the number is in the receipts and on no page. | **RTO is currently unknown.** Not slow — unknown. |
| **No rollback script** | Nothing wraps `fly deploy --image <digest>`. | The likeliest outage cause (our own deploy) has no one-command undo. |
| **Every monitor lives inside Fly or GitHub** | `e2e-live-smoke` daily 07:00 UTC, `production-runs-main` hourly, laptop launchd watchdog every 15 min. | A Fly-wide or Actions-wide outage silences the alarm and the thing it watches together. |
| **No Cloudflare in front of `mumchimp.com`** | Direct A record to Fly anycast. | No edge to fail over at, so today failover must be DNS — the slow mechanism (§5). |

### What is better than the proposal assumes

`scripts/backup_store.py` backs up daily to Cloudflare R2 bucket `prospector-backup` with **real
read-back verification** — it re-downloads an 8-dossier sample and compares SHA-256, checks the
ledger gzip CRC and byte count, and runs `PRAGMA integrity_check` on the restored database.
Retention: 30 ledger, 30 db, 14 bundles, 90 days of logs. A weekly unattended restore drill actually
restores it.

Hold that thought for §4. It is the standard Coolify would have to beat.

---

## 3. Where the pasted DR proposal is right

Not much is wrong with its reasoning; it is wrong about this estate's numbers. The reasoning that
survives:

- **Nothing on the list creates downtime.** Correct, and it is the reason to do the cheap items.
- **Detection ranks above portability.** Correct, and it is exactly what §2 shows is missing — the
  engine has no health check while the portability work is already finished and tested.
- **Your own deploys are the likeliest outage cause.** Correct, and the missing rollback script is
  the direct consequence.
- **An untested standby is a hypothesis.** Correct. This is the principle `restore_drill.py` was
  written for.
- **A solo founder cannot hit a 1-hour RTO manually at 3am, so it has to be a mechanism.** Correct.
  The mechanism already exists (`scripts/engine_failover.py`, an armed/disarmable watchdog that
  flips `~/.prospector/ACTIVE`); it is currently pointed at a laptop, which is not a DR target.
- **Portability lives at the container boundary.** Correct, and `PORTABILITY.md`'s `sshdocker`
  adapter is that boundary already.

Its five preconditions for a 1-hour RTO, graded against this estate:

| Precondition | State |
|---|---|
| Pre-provisioned target | **Missing.** But cheap — see §6. |
| Continuous replication, not nightly dumps | **Not applicable.** No Postgres, 903 MB of files, daily verified R2 copy. |
| Images on a registry that is not the provider | **Partly.** Images are on `registry.fly.io`. Worth moving to GHCR. |
| Cloudflare in front with a low TTL | **Missing, and the low TTL is the wrong half** — see §5. |
| Retrievable secrets and one rehearsed command | **Missing.** This is the real gap, and §7 covers it. |

---

## 4. Coolify, fact-checked

The proposal's claims were checked against primary sources on 2026-08-22 — Coolify's own docs,
pricing page, GitHub repository and advisory database.

### Claims that hold

| Claim | Verdict |
|---|---|
| Provisions servers on Hetzner, DigitalOcean, Vultr | **Verified**, verbatim in the docs |
| 280+ one-click templates | **Understated — there are 340** |
| MCP server exists | **Verified, and now understated**: v4.3.0 (2026-08-12) added deployment controls, so it is no longer read-only |
| Self-hosted is free, Apache-2.0 | **Verified** |
| $5/mo Cloud | **Nearly** — $5/mo covers **two** servers, then +$3/mo each |

### Claims that need correcting

**"Single server" is half true.** Coolify manages multiple servers over SSH. What it is not is a
clustering orchestrator — Docker Swarm support is documented as **experimental**.

**"v5 rewrite is in the air" is true but much weaker than it sounds.** Current release is v4.3.10
(2026-08-21). The `v5.x` branch's last commit is **2026-03-27** and it is **2,959 commits behind
main**. That is not an imminent rewrite; it is a stalled branch.

### The two findings that decide it

**a) Coolify's backup verification is weaker than what we already run.** The proposal's headline
feature for DR is S3 database backups. Reading `DatabaseBackupJob.php`, the "verification" is
`du -b <file>` and a check that the result is greater than zero. **A truncated or corrupt dump
passes.**

Compare with `scripts/backup_store.py`, in production today: re-download an 8-dossier sample and
compare SHA-256, verify the ledger gzip CRC and byte count, `PRAGMA integrity_check` on the restored
database, weekly unattended full restore drill. **Adopting Coolify's backup path would be a
regression in exactly the capability the founder is trying to buy.**

**b) The security record is the disqualifier.** Coolify has **70 GitHub security advisories, 21 of
them critical, and 45 of the 70 published in the last 90 days.** Among them:

- `CVE-2026-42204` — authenticated remote code execution
- `CVE-2026-41896` — webhook HMAC bypass
- `CVE-2026-34047` / `CVE-2026-34048` — websocket authentication-bypass RCE
- `CVE-2026-34592` — cross-team IDOR exposing SSH keys

Corroborated independently by The Hacker News, Censys, and Belgium's Centre for Cybersecurity.

The blast radius matters more than the count. **Coolify auto-injects `sudo`, so it holds root on
every server it manages.** Installing it to improve disaster recovery would create a single
internet-facing component whose compromise hands an attacker root on the entire fleet — including
the machine holding the store the DR plan exists to protect.

That is not a "keep it patched" risk. It is the wrong shape of risk to take on to solve a problem
that §6 solves for £0.

### Dokploy, the named alternative

Apache-2.0 core since 2026-01-21, $4.50/mo Hobby, genuinely Swarm-native — and **no provisioning**,
which was the main reason to want Coolify. Pre-1.0 (v0.30.2) and effectively single-maintainer. It
is a smaller version of the same bet. Same answer.

### What Coolify would actually replace here

Nothing. `deploy/PORTABILITY.md`'s `sshdocker` adapter already deploys this stack to any Linux box
over SSH, in about 90 lines, pinned by a test. Coolify's value is a UI and templates for people
running many unrelated services. This estate runs one product on seven apps with a deploy path that
already works and is already tested.

---

## 5. The failover mechanics, corrected

The proposal says: Cloudflare in front, 60-second TTL, health-check origin failover. Two of those
three are right. **The 60-second TTL is close to worthless, and the health-check product is slower
than the free alternative.**

### A 60s DNS TTL buys almost nothing

Verified from the Chromium source
(`net/dns/host_resolver_system_task.h`): Chrome caches system-resolver results for **exactly 60
seconds regardless of your TTL**, and applies a 60-second minimum even with its own resolver.
Anything below 60s is discarded. So a 60s TTL is the *floor of the benefit*, not a gain.

Worse, the tail is open-ended. Two independent measurement studies:

- **RIPE Atlas, 6,587 resolvers (2017):** 4.17% **increase** the TTL beyond what the authoritative
  server sets; 1.97% decrease it.
- **PAM 2023, 8,524 resolvers across 9,500 ASes:** **8.74% extend the TTL arbitrarily**, degrading
  an estimated 38% of popular CDN-fronted sites.

"Arbitrarily" is the operative word — neither paper bounds how long. And on the JVM, the default can
be *never refresh until restart* (`networkaddress.cache.ttl`, a security property, so `-D` does not
set it).

The researchers who produced the definitive TTL paper recommend **5–15 minutes** as the floor for
DNS-based traffic steering, not 60 seconds — below that you pay full query load for no additional
agility.

**No measured "% of traffic moved at T+n" curve for a 60s TTL exists in the published literature.**
The "95% within one TTL" figure that circulates is vendor blog material with no methodology. Do not
plan an RTO on it.

### The right mechanism is a proxied edge, and the free one is faster

Once traffic is proxied, the failover decision happens at Cloudflare's edge and **DNS TTL stops
mattering entirely**. Two ways to do that:

| Option | Cost | Detection | Notes |
|---|---|---|---|
| Cloudflare Load Balancing | **"Starting at $5/mo"** (add-on, available on the Free plan) | **60s minimum health-check interval** on a Pro-equivalent zone; ~1–3 min end-to-end | Cloudflare publishes **no** end-to-end failover figure. Its own docs contradict each other on the minimum interval (60s vs 15s). The billing page that used to state what $5 includes now 301s to a page that omits the product. |
| **Cloudflare Worker: fetch origin A, fall back to origin B** | **£0** | **Sub-second** — the fallback is a second `fetch` in the same request | Free plan: 100,000 requests/day, 50 subrequests/request, 10ms CPU. |
| Standalone Health Checks | — | — | **Not available on Free at all, and notification-only even on Pro.** Cannot fail anything over. |

**The free option has better failover latency than the paid one**, because a Worker fails over
inside the request rather than waiting for a 60-second polling cycle to notice. 100,000 requests/day
is roughly 1.15 requests/second sustained, which is far above current traffic.

That is the LAW 14 finding in this section: the recommended purchase is both slower and more
expensive than the thing that costs nothing.

---

## 6. What to actually do, ranked

Ordered by recovery-time bought per pound and per hour. **Items 1–5 cost £0/month between them.**
The pasted proposal's architecture costs a second provider bill plus $5/mo plus the engineering, and
does not do items 1–4 at all.

### 1. Put a health check on the engine — £0, ~20 minutes

`deploy/engine/fly.toml` declares none, while `store-api`, `store-web` and `tie-web` all do. This is
first because **every other item on this list depends on being able to tell "up" from "hung".**
Failover cannot trigger on a signal that does not exist, and neither can alerting. It is also the
smallest diff on the list.

### 2. Publish the restore-drill duration — £0, ~15 minutes

`scripts/restore_drill.py` already restores from R2 weekly, unattended, and records `took_s`. The
number is in the receipts and on no page. **Until it is published, the RTO is unknown, and an
unknown RTO cannot be improved or defended.** Read the last eight receipts, take the median and the
max, and put both in `deploy/PORTABILITY.md`.

This is the cheapest item that converts an opinion into a number.

### 3. A monitor that is neither Fly nor GitHub — £0

Every current watcher lives inside one of the two systems it watches: `e2e-live-smoke` (daily 07:00
UTC), `production-runs-main` (hourly), the laptop launchd watchdog (15 min). A Fly-wide or
Actions-wide incident takes out the alarm and the thing it watches in the same stroke.

Cheapest fix is a Cloudflare Worker on a cron trigger (free plan includes 5 per account, 1-minute
minimum granularity) hitting the health check from item 1 and messaging Telegram — the bot token is
already a deployed secret (`TELEGRAM_BOT_TOKEN`).

### 4. A rollback script — £0, ~30 minutes

The proposal's own strongest point is that our deploys are the likeliest outage cause. There is no
script that undoes one. `fly image show -a prospector-engine` already yields the digest; the undo is
`fly deploy --image registry.fly.io/prospector-engine@sha256:<digest>`. Wrap it, record the
pre-deploy digest automatically, and make it a console button beside the existing ones.

### 5. Rotate the two leaked keys — £0, founder's call

`docs/PLATFORM_MANIFESTO.md:123-125` records this as an **outstanding breach**:

> `PROSPECTOR_ENTITLEMENTS_API_KEY` and `STORE_INTERNAL_API_KEY` were printed into a session
> transcript on 2026-08-18 by a `/proc/<pid>/environ` read. Both need rotating. Rotating them is the
> test that this law is enforced rather than admired.

**Four days on, I cannot show them rotated.** `flyctl secrets list` prints a digest but no date;
`flyctl releases` describes every release as "Release" with no distinction; there is no rotation
script and no receipt anywhere in the repo. The honest state is *unproven*, and for a leaked
credential unproven should be read as *not done*.

It is flagged rather than done because Fly secrets are write-only — once rotated, the old value
cannot be restored, and both keys are shared between the engine and the store API. If any consumer
I have not found still holds the old one, it breaks with no way back. **That is your call, not
mine.** The rehearsed form is: mint new, `fly secrets set` on both apps in one command each, verify
with a live request, then delete the old grant at the issuer.

### 6. Then, and only then, automatic failover — £0

A Cloudflare Worker in front of `mumchimp.com` that fetches the primary origin and falls back on
failure. Sub-second, free, and no DNS TTL in the path (§5). This is where the proposal's instinct is
right and its mechanism is wrong.

Note what it needs first: **a second origin that is actually alive.** `scripts/engine_failover.py`
already exists and already flips `~/.prospector/ACTIVE` — it is currently pointed at the laptop,
which is a development machine, not a DR target. The `sshdocker` adapter in `deploy/PORTABILITY.md`
puts the stack on any Linux box with SSH, so the standby is a cheap VPS, not a re-architecture.

### 7. Move images to GHCR — £0

Images live on `registry.fly.io`. If Fly is the outage, the images needed to recover elsewhere are
behind the outage. GHCR is free for public repositories and the repository is already public.

### What NOT to do

- **Coolify or Dokploy.** §4. Root on the whole fleet, 21 critical advisories, and a backup check
  that is `du -b > 0` against a backup path we already do properly.
- **Warm standby with continuous replication.** Sized for 40 GB of Postgres. We have 903 MB of
  files and no engine Postgres.
- **A 60-second DNS TTL.** §5. Chrome floors at 60s anyway and 4–9% of resolvers extend TTLs with
  no published bound.
- **Kubernetes.** The pasted proposal already pushes back on this and is right. Nothing in §6 needs
  it, and the four items that actually shorten RTO get harder, not easier, with a cluster in the
  way.
- **AWS.** Fine as a rented Linux box, 3–5× the price for the same thing, and the reason to go there
  (managed services) is exactly the lock-in `PLATFORM_MANIFESTO.md:51` bans.

---

## 7. The platform-engineering proposal

The second pasted transcript argues that most of the platform-engineering discipline — Backstage,
golden paths, internal portals, DORA metrics — is baggage at this scale, and that three things
transfer: secrets, an agent-specific credential layer, and feature flags. **That triage is right.**
Its skip list (internal developer portals, service mesh, GitOps/ArgoCD, Vault, per-secret-priced
SaaS, SOC2 tooling) is also right, and §8 puts numbers on the last one.

Here is what is actually true of this estate, measured 2026-08-22.

### Already done — do not buy these again

**GitHub push protection is already on.** The proposal's item 6 is the one thing it recommends that
is already in place:

```
$ gh api repos/chidionyema/prospector --jq '.security_and_analysis'
{"dependabot_security_updates":{"status":"enabled"},
 "secret_scanning":{"status":"enabled"},
 "secret_scanning_non_provider_patterns":{"status":"disabled"},
 "secret_scanning_push_protection":{"status":"enabled"},
 "secret_scanning_validity_checks":{"status":"disabled"}}
```

Two switches in that output are off and both are free: `non_provider_patterns` (catches
custom-format keys the provider list misses — which is what `STORE_INTERNAL_API_KEY` is) and
`validity_checks` (tells you whether a leaked key is still live). **Turn both on.** That is the
whole of the "gitleaks pre-commit hook" recommendation, already paid for, minus the hook.

**Secrets are declared once and checked before boot.** `deploy/secrets.required` lists 11 entries;
`deploy/secrets.sh check` gates machine boot on their presence. Nothing is committed. The 11:
`CONTROL_CENTER_PASSWORD`, `EXA_API_KEY`, `MINIMAX_API_KEY`, `PROSPECTOR_ENTITLEMENTS_API_KEY`,
`R2_ACCESS_KEY_ID`, `R2_ACCOUNT_ID`, `R2_BUCKET`, `R2_SECRET_ACCESS_KEY`, `STORE_API_URL`,
`STORE_INTERNAL_API_KEY`, `STRIPE_LIVE_API_KEY`.

**Feature flags already exist, as config.** `config.yaml` carries `prescreen_prefilter.shadow_mode`,
`numeric_citation.enabled` and `.shadow_mode`, `coverage_sampler.enabled`, `denylist.enabled`,
`incumbent_seed.enabled`, `refinement_enabled`, `verbalized_sampling.enabled`, plus the kill-filter
toggles. **There is even a shadow-mode convention already in use** — the exact "decouple deploy
from release" pattern the proposal recommends buying a product for.

What config flags do not give you is flipping one *without a deploy*, which is the actual argument
for a flag service. Whether that is worth a dependency at this scale is a real question and §8
answers it with the free-tier numbers.

### The real exposure, and it is the one the proposal named

**Long-lived Fly tokens sit in GitHub Actions, and no OIDC federation exists anywhere.**

```
$ gh secret list --repo chidionyema/prospector
FLY_API_TOKEN          2026-07-31T09:39:49Z
FLY_API_TOKEN_API      2026-08-01T05:30:03Z
FLY_API_TOKEN_ENGINE   2026-08-18T07:53:06Z
```

Three static deploy tokens, the oldest 22 days old, referenced from eight workflows including
`deploy-engine.yml:96,176`, `deploy-api.yml:117,226`, `deploy-web.yml:146,193`,
`escape-hatch-drill.yml:49` and `production-runs-main.yml:76`. No `id-token: write` and no OIDC
action appears in any workflow — **absent, verified by search.**

A Fly deploy token is root on the app. Anything that can read Actions secrets can deploy arbitrary
code to production, which includes reading `/proc/<pid>/environ` for the other 11 — which is
precisely how the 2026-08-18 leak happened, from inside the machine.

That is the single highest-value item in this whole section, and it is why the CI-runner statistic
in the pasted transcript matters rather than being trivia.

### Supply chain, measured

| Control | State |
|---|---|
| `npm ci` rather than `npm install` | **Present** — `.github/workflows/ci.yml:578,831`, with lockfile-hash caching |
| `pip install --require-hashes` | **Absent.** CI runs `uv pip install -r requirements.txt` with no hash pinning, across 30 direct Python dependencies |
| SBOM generation | **Absent** |
| `pip-audit` / `npm audit` in CI | **Absent** — `npm ci` is run with `--no-audit` explicitly |
| Renovate / Dependabot version updates | **Absent.** No `renovate.json`, no `.github/dependabot.yml`. Dependabot *security* updates are enabled at the repo level, so critical advisories still raise PRs; scheduled version bumps do not happen. <!-- doc-lint-ok: absent by design — this line reports the path as MISSING --> |
| Secret scanning in the commit gate | **Absent.** `.lux/hooks/pre-commit` runs POPDD lane verification and receipt signing, and does not look for secrets. |

`--require-hashes` on 30 direct dependencies is the cheapest of these and the one that closes the
same class as the leak: a compromised package in CI is a compromised deploy token.

### Telemetry

`prospector/otlp.py` exists — 518 lines, a complete OTLP/HTTP decoder for both protobuf and JSON,
feeding the log-ingest schema. **It is a receiver, not an exporter**, and `config.yaml` has no
`otlp:` or `telemetry:` block switching it on. So the OpenTelemetry recommendation is neither
"already done" nor "greenfield": the wire format is already understood in-tree, and nothing is
currently emitting to it.

Given §6 item 3 — that there is no monitor outside Fly and GitHub at all — **a health check plus a
Worker cron is a better first move than an observability pipeline.** You cannot get value from
traces before you have an alarm.

---

## 8. The platform-engineering tools, fact-checked

Every claim in the second transcript was checked against primary sources on 2026-08-22 — vendor
pricing pages, licence files, GitHub release APIs, PyPI metadata, CNCF project pages. **Five of them
do not survive**, and two of the five are the reasons the transcript gives for its main
recommendation.

### Infisical — the two features it was recommended for are both paid

This is the decisive one. The transcript recommends Infisical over SOPS because it gives *dynamic
short-lived Postgres credentials* and *versioned secrets you can revert*.

- **Dynamic secrets: "available under Infisical's Advanced plan."** That is **$40/identity/month**
  annual, $46 monthly. Self-hosters must buy a licence for it.
- **Point-in-time recovery: "a paid feature… available under the Pro Tier."** Same story.
- Free tier is 5 identities. Pricing is **per identity, not per seat**, which for an agent estate
  is the expensive direction.
- The licence is MIT **except everything under `ee/`**; GitHub classifies the repo `NOASSERTION`.
- The Docker Compose path the transcript describes is real but the docs say it "is not designed for
  high-availability production scenarios" — Kubernetes is the documented production path.

**So the free, self-hosted Infisical the proposal describes does not exist.** No CVEs found against
it, for what that is worth.

### SOPS + age — the claim holds, with one correction and one live advisory

- **Maintained, and not Mozilla's problem any more.** Donated to the CNCF as a Sandbox project in
  2023, now under the `getsops` org. Latest **v3.13.3 (2026-07-23)**, last commit 2026-08-17,
  MPL-2.0. `age` is at **v1.3.1 (2025-12-28)** — BSD-3-Clause, slow but not archived.
- **"Rotation is manual" is partly wrong.** `sops rotate` generates a new data key and re-encrypts
  every value. What SOPS never touches is the **underlying secret value** — the actual token at the
  issuer. That distinction matters, because it is the value that leaked on 2026-08-18, not the key
  encrypting it.
- **One open advisory worth knowing:** `GHSA-jgf3-f6rg-8x3h`, high severity, published 2026-08-14 —
  Vault/OpenBao token exfiltration when decrypting an **untrusted** SOPS file. Affected range is
  `*` with **no patched version listed.** Not our threat model (we would author our own files), but
  it should be known before adopting.

### Vault and OpenBao — correct, and both are still wrong for one person

- HashiCorp adopted BUSL on **2023-08-10**. IBM's acquisition closed **2025-02-27**, and the current
  `hashicorp/vault` LICENSE names IBM as licensor. **No revert; the licence hardened.**
- OpenBao is real and healthy: **MPL-2.0, governed by the OpenSSF**, v2.6.2 (2026-08-18), with
  genuine divergence from Vault (transactional storage, paginated lists, per-namespace sealing).
  SAP staffs it full-time; EdgeX Foundry adopted it.
- **Neither fits.** Both need unseal-key custody, a storage backend, HA quorum and version-by-version
  upgrades. That is a second production system to keep alive in order to protect the first one. The
  transcript's "skip both" is right, for the right reason.

### GitHub push protection — already on here, and weaker than described

The claim was that push protection means an agent "physically cannot commit a key." **Refuted on
two counts:**

1. It blocks **pushes**, not commits. The local commit succeeds and the secret is in local history.
2. **Anyone with write access can self-serve a bypass** by picking a reason — "used in tests",
   "false positive", or **"I'll fix it later"**. No approver by default.

It is also partner-pattern-only and does not clean history. Free for public repositories (which
this one now is); **$19/active committer/month** for private.

The two free switches currently off — `non_provider_patterns` and `validity_checks` — are worth more
here than any of the above, because `STORE_INTERNAL_API_KEY` is exactly a non-provider pattern.

### gitleaks — MIT, but in maintenance

Licence unchanged. But the README now reads: *"Gitleaks is feature complete. I'm not merging new
features… Future releases will be security patches only. I'm shifting my focus to Betterleaks."*
Last release **v8.30.1 (2026-03-21)**, five months stale. Betterleaks (MIT, created 2026-02-03) is
at v1.8.1 (2026-08-18).

The pre-commit hook still works. Whether to add it is §9.

### Renovate — the claim holds

AGPL-3.0, actively maintained by Mend.io, release 44.39.1 on 2026-08-21. **The free hosted app is
real and not deprecated** — 73,195 installations, "$0", public and private repos, unlimited
repositories on Community Cloud, with 1 concurrent job and 4-hour scheduling.

But **Dependabot has closed most of the gap**: it now has `groups`, `directories` globbing and
`multi-ecosystem-groups`, and it does **not** bill against Actions minutes on standard runners.
Given that Dependabot security updates are *already enabled* on this repo, adding
`.github/dependabot.yml` is a smaller change than onboarding a second bot. <!-- doc-lint-ok: absent by design — this line reports the path as MISSING -->

The "PR volume" complaint is partly true — `prConcurrentLimit` defaults to 10 and `prHourlyLimit` to
0 (unlimited) — but Renovate ships a whole noise-reduction preset set for it.

### OpenTelemetry — "vendor switch is a config change" is partly true

- **Python: traces Stable, metrics Stable, logs still Development.** SDK/API 1.44.0 (2026-07-16).
  Auto-instrumentation is `0.65b0` — **a beta version string, so not stable.**
- The portability claim has a specific hole: **semantic conventions are explicitly not covered by
  the API/SDK stability guarantees.** Renaming span, metric, log and resource attributes is an
  allowed change, and there is currently "a moratorium on relying on schema transformations for
  telemetry stability." So the wire protocol ports; the meaning of your fields may not.
- Free backends, verified today: **Grafana Cloud** 10k active series / 50 GB logs / 50 GB traces /
  14-day retention; **Axiom** 500 GB/mo ingest, 25 GB storage, 30-day retention; **Honeycomb** 20M
  events/mo; **Uptrace** 50 GB/mo. Any of those is free at this estate's volume.

### Feature flags — two corrections

- **OpenFeature is CNCF *Incubating*, not graduated**, and the **Python SDK is v0.10.0 — pre-1.0**,
  as is every Python provider on PyPI. The vendor-neutral abstraction layer is the least mature
  piece of the stack in the language this estate is written in.
- **Unleash is AGPL-3.0-or-later, not Apache-2.0.** The OSS build caps at **2 environments**; RBAC,
  SSO, projects and change requests are paid. There is **no free hosted tier** — pay-as-you-go is
  **$75/seat/month** with a 5-seat minimum self-hosted.
- **PostHog is the one genuinely free option: the first 1,000,000 flag requests per month are
  free**, then $0.0001/request. MIT except `ee/`.

### SOC 2 — "skip until a customer asks" survives, with numbers

All three vendors hide pricing. Vendr's benchmarks (updated Feb 2026): **Vanta median $20k/yr**
(1–50 staff $12k–$28k, low $7,500), **Drata median $25k**, **Secureframe median $20k**. Audit fees
from startup-focused firms run **$5k–$7k for Type 1** and **$7k–$10k+ for Type 2** at the cheap end,
with a $20k median for Type 2.

**First-year all-in for one person: roughly $15k–$35k, and 6–9 months of elapsed time** (Type 2
needs a 3-month observation window minimum). Skip it.

---

## 9. The platform-engineering plan, ranked

Same rule as §6: cheapest first, and stop when the cost stops being zero.

| # | Action | Cost | Effort | Why here |
|---|---|---|---|---|
| 1 | Turn on `secret_scanning_non_provider_patterns` and `secret_scanning_validity_checks` | £0 | 2 min | Both free, both off. The first catches custom-format keys like `STORE_INTERNAL_API_KEY`; the second tells you whether a leaked key is still live. |
| 2 | **Rotate the two keys leaked on 2026-08-18** | £0 | founder's call | §6 item 5. Four days open, unproven, and `validity_checks` from item 1 will tell you if they are still live. |
| 3 | `pip install --require-hashes` for the 30 direct Python dependencies | £0 | ~1 hour | Closes the same class as the leak: a compromised package in CI is a compromised Fly deploy token. |
| 4 | Add `.github/dependabot.yml` | £0 | ~20 min | Security updates are already enabled; scheduled version bumps are not. Cheaper than onboarding Renovate, and Dependabot now groups. <!-- doc-lint-ok: absent by design — this line reports the path as MISSING --> |
| 5 | Cut the static Fly tokens out of Actions where possible | £0 | see below | The largest single exposure in the estate. |
| 6 | If flag-flipping-without-deploy is ever needed: PostHog | £0 to 1M req/mo | ~2 hours | The only genuinely free option. Wire it **directly** — OpenFeature's Python SDK is pre-1.0. |
| 7 | OpenTelemetry export | £0 (Grafana/Axiom/Honeycomb free tiers) | ~1 day | **After** §6 item 1. Traces before an alarm is the wrong order. |

### What not to buy

- **Infisical** — the two features it was recommended for are both behind the $40/identity/month
  Advanced plan (§8).
- **Vault or OpenBao** — a second production system to keep alive in order to protect the first.
- **Unleash** — AGPL, 2-environment OSS cap, $75/seat/month, no free hosted tier.
- **SOC 2 tooling** — $15k–$35k and 6–9 months. Not until a customer asks in writing.
- **gitleaks as a pre-commit hook** — in maintenance since March, and item 1 covers the same ground
  for free with no new dependency. If a local hook is genuinely wanted later, Betterleaks is the
  maintained fork.

### On the CI-runner exposure

The estate has **three long-lived Fly deploy tokens in GitHub Actions** — `FLY_API_TOKEN`
(2026-07-31), `FLY_API_TOKEN_API` (2026-08-01), `FLY_API_TOKEN_ENGINE` (2026-08-18) — referenced
from eight workflows, and **no OIDC federation anywhere** (`id-token: write` absent, verified by
search across all workflows).

A Fly deploy token is root on the app. Anything that can read an Actions secret can ship arbitrary
code to production, and code on the machine can read `/proc/<pid>/environ` for the other eleven —
which is exactly the mechanism of the 2026-08-18 leak, and the reason the transcript's point about
CI runners being the exposed surface is the one worth acting on rather than the tooling shopping
list around it.

Two mitigations that do not depend on any provider's OIDC support:

1. **Scope the tokens per app.** `FLY_API_TOKEN` is the broad one and is the oldest. Two
   app-scoped tokens already exist (`_API`, `_ENGINE`); the broad one should stop being a fallback.
2. **Rotate on a schedule and record it.** There is currently no rotation script and no receipt —
   which is why §6 item 5 cannot be answered either way. A `scripts/rotate_secret.py` that mints, <!-- doc-lint-ok: absent by design — this line reports the path as MISSING -->
   sets on every app that needs it, verifies with a live request, and writes a dated receipt turns
   "cannot tell" into a number.

---

## 10. What this costs, end to end

| | Pasted proposal | This plan |
|---|---|---|
| Control plane (Coolify Cloud, 2 servers) | $5/mo | £0 — `sshdocker` adapter already ships |
| Warm standby with continuous replication | second provider bill + engineering | £0 — 903 MB, daily verified R2 copy |
| Cloudflare Load Balancing | $5/mo, 60s detection | £0 — Worker fallback, sub-second |
| Secrets platform (Infisical Advanced) | $40/identity/mo | £0 — Fly secrets, already declared-once |
| Feature flags (Unleash) | $75/seat/mo | £0 — config flags today; PostHog free to 1M/mo if needed |
| Observability | vendor | £0 free tiers |
| SOC 2 tooling | $15k–$35k year one | £0 — not until asked |
| **Health check, rollback script, external monitor, published RTO** | **not in the proposal** | **£0** |

**The four items with the largest effect on recovery time are absent from the proposal and free.**
That is the whole finding.

### The one number still missing

`scripts/restore_drill.py` has been recording `took_s` weekly. Until that median is published,
**this estate's RTO is not a slow number or a fast number — it is an unknown one**, and every claim
about disaster recovery on either side of this document is standing on it. §6 item 2 is fifteen
minutes of work and it should be done before anything else on either list.

---

## 11. Fly's actual reliability record, and the one thing it changes

Neither pasted proposal put a number on how often the current provider has a bad day. Fly's own
infra log and status feed were read for the trailing 18 months on 2026-08-22.

### There is no SLA on the plan we are on

Verified first-hand at `https://fly.io/legal/sla-uptime/`: the 99.9% commitment is **Enterprise
only**. On Hobby, Launch and Scale, **Fly makes no contractual availability commitment at all**. The
remedy even on Enterprise is service credit against future billing, never cash, and the customer
must ask for it.

### The rate is roughly monthly, and the record understates it

Three independent third-party trackers agree on the order of magnitude: Pulsetic counts **62
incidents in the trailing 90 days**; IncidentHub counts **18 outages in the last 30 days across 9
components**; StatusGator has tracked 1,865+ since 2020 and grades Fly's status-page accuracy "B"
with a **15–30 minute lag** between users noticing and Fly acknowledging.

**And the record has a nine-month hole.** Fly's infra log says verbatim: *"The infra log took a long
sabbatical, but we're bringing it back with a new format."* **There are no entries between June 2025
and February 2026.** Treat that window as unverified, not as quiet.

Documented multi-hour incidents in the window include **9h59m on 2026-07-20** (token-validation host
offline → mass 5XX on the Machines API), 9h05m on 2026-08-04, 8h19m on 2026-08-04/05, **4h20m on
2026-08-09** ("app not found" errors from Corrosion propagation lag), and ~5h on 2025-02-16.

### The distinction that matters

**Most Fly incidents hit the control plane, not running containers.** Deploys, the Machines API,
certificate issuance, provisioning, secrets. Running apps mostly keep serving through them.

The shorter list that actually took customer traffic down: **2026-08-03** (12 min — a BGP
misconfiguration during Fly's own edge provisioning dropped most traffic from Europe, which includes
LHR), **2026-08-09** (4h20m, app-not-found), **2026-03-26** (both redundant fibre links to the FRA
rack dropped), **2026-07-14** (2h08m, SJC workers locked up), **2026-06-17** (SIN router).

BGP misconfiguration during Fly's own edge provisioning appears **three separate times in 2026**.

### The correction this forces

> **You usually cannot deploy your way out of a Fly incident, because the API is the thing that is
> broken.**

That is the single most useful sentence in this research, and it revises **§6 item 4**. The rollback
script is still right for what it is for — undoing *our own* bad deploy, when Fly is healthy, which
is the likeliest outage cause. But it is **not** the disaster-recovery plan, and neither is anything
else beginning with `flyctl`.

So the DR path has to be: **R2 (already off-Fly) → the `sshdocker` adapter → a Linux box that is not
Fly.** Both halves of that already exist and are already tested. What is missing is a target that is
alive and a rehearsed command, which is §6 item 6.

### Two more things worth recording

**Everything is in one region.** All 8 machines are in `lhr`. LHR specifically appears in the record
three times: capacity exhaustion on 2025-03-14 (deploy-blocking), a 1h05m networking incident on
2026-02-20, and the 2026-08-03 European ingress drop.

**Fly Managed Postgres is the weakest component in the whole record** — eleven distinct MPG incidents
in six months (2026-04-10, 04-27, 05-16, 06-11, 08-01, 08-04/05, 08-20, plus MPG degradation inside
the 07-20 and 08-19 incidents). On **2026-08-01** existing clusters kept serving **but their backups
were silently lagging.**

That last one is worth reading twice by anyone about to put this estate's store on Fly Managed
Postgres. It is also the strongest argument in this document for the thing `backup_store.py` already
does: an independent, verified, off-Fly copy.
