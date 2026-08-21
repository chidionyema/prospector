# 0003 — Founder rulings on the migration and DR programme

Status: **accepted, 2026-08-20.** Supersedes §7 "Open decisions" of
`docs/MIGRATION_AND_DR_PROGRAM.md`, which asked seven questions. Six were answered on
2026-08-20; the seventh had already been answered on 2026-08-19.

**Standing instruction that produced this file**, founder, 2026-08-20:

> "we need to research and decide should be providing thoughtful assessment comparison and
> recommendations not questions"

That is a rule about how this programme is run, not a comment on one item. A decision reaches the
founder as *an assessment, a comparison and a recommendation*, with the measurement behind it. A
bare question is not a decision request; it is work that has not been done yet.

The founder's replies are recorded verbatim below, each against the item it answers.

---

## D1 — Where secrets live, so a new machine can be brought up (blocks M2)

**Founder:** *"we need to research and decide should be providing thoughtful assessment
comparison and recommendations not questions"*

### What is actually true today

The question as written was already half-answered by the estate. Measured on `origin/main`:

| Fact | Where |
|---|---|
| 11 secrets, named, no values | `deploy/secrets.required` |
| Encrypted store | `deploy/secrets.env.age` — **NOT committed. See the correction below.** |
| `init` / `import` / `list` / `check` / `push` verbs | `deploy/secrets.sh` |
| Push path to the platform | `deploy/targets/fly.sh::t_secrets` → `fly secrets import --stage` |
| The private key | `~/.config/prospector/age-key.txt`, mode 600, never committed |

The estate already uses `age` and already has a one-command push.

> **CORRECTION, 2026-08-21 — the sentence that used to sit here said the estate "already commits
> the ciphertext". It does not, and has never done.** Two angles, both run today:
> `git ls-tree -r origin/main -- deploy/` returns `secrets.required` and `secrets.sh` and nothing
> else; `git log --all -- deploy/secrets.env.age` returns four commits, every one of them titled
> *"snapshot of uncommitted work in wt-fly-migration"* — that is `guard-autocommit.py` catching an
> uncommitted working file, on no branch anybody merges.
>
> **The whole secret backup of this estate survives by accident.** And it was needed: on
> 2026-08-21 `/Users/chidionyema/Documents/code/prospector/.env` was simply gone, with 31 dead
> symlinks across 114 checkouts and worktrees pointing at it. It was rebuilt from snapshot
> `56f9cf4f` with the age key on the laptop — 22 keys, and every name in `deploy/secrets.required`
> present. Had the snapshot guard not existed, or had those loose objects been pruned, the estate's
> secrets would have had to be re-minted from six vendor consoles.
>
> This changes what the recommendation below is worth. Escrowing the age key protects a ciphertext
> that is not in the repository; the key and the ciphertext have to be dealt with **together**, and
> the ciphertext half is the one nobody had noticed was missing.

**So the gap is wider than M2 states, in two places: the ciphertext is not committed, and the age
key itself has no restore path.** Lose the laptop disk today and both halves go at once.

### Comparison

| Option | Cost | Recovery after laptop loss | New dependency |
|---|---|---|---|
| (a) Status quo — one key file, one laptop | £0 | **Impossible** | none |
| (b) Print the age identity, keep it off-site | £0 | Type ~74 characters, ~5 min | none |
| (c) Escrow the identity in a password manager | £0–£3/mo | Instant, from a phone | one vendor, holding a key to ciphertext that is already public-in-repo |
| (d) Cloud KMS + SOPS | new cloud account | Automated | **the cloud we are trying to be independent of** |
| (e) Shamir split across three locations | £0 | Slow, needs three places | none, but three custodians for a one-operator estate |

### Recommendation — (b) and (c) together

Escrow the identity in the password manager for speed, *and* print it for the case where the
password manager account is the thing that is lost. Both are free, neither adds a runtime
dependency, and both leave `deploy/secrets.env.age` as the single source of truth.

M2's bootstrap script then becomes about twenty lines: install `age`, fetch the key, run
`secrets.sh import`, run `secrets.sh push <target>`.

**Why not (d).** `deploy/PORTABILITY.md` exists so that no component needs one specific cloud.
Encrypting the secrets with a cloud KMS makes the secrets themselves unrecoverable without that
cloud. That is the single worst place in the estate to accept a lock-in.

**Nothing left to decide. One action, and it is the founder's** because it is a secret value and
a physical act: put the age identity in the password manager, and print a copy.

---

## D2 — Which second provider proves portability (blocks M3 and drill D5)

**Founder:** *"not sure i understand"*

### Said plainly

`deploy/PORTABILITY.md` says any platform that wants to run the engine must provide eleven shell
functions — `t_name`, `t_preflight`, `t_provision`, `t_secrets`, `t_release`, `t_start`, `t_stop`,
`t_exec`, `t_put`, `t_pack`, `t_logs`, `t_health`. Three files implement that contract today:
`deploy/targets/fly.sh`, `deploy/targets/laptop.sh`, `deploy/targets/sshdocker.sh`.

`sshdocker.sh` is fully written and has **never been run against a real machine**. So "the engine
can leave Fly" is currently a claim about a shell script, not a fact about the estate.

The question was: what machine do we run it against, once, to turn the claim into a receipt.

### Comparison

| Target | Cost | What it proves | Problem |
|---|---|---|---|
| The laptop | £0 | `laptop.sh` works | It is the thing we are leaving, and it is at load 282 |
| A £4/mo Hetzner CX22 | ~£0.01 per drill if created and destroyed by the drill | A *foreign* machine can run the engine from a clean state | needs an API token |
| Dry-run only | £0 | Nothing. It proves the script parses | — |

### Recommendation — a Hetzner CX22, created and destroyed by the drill itself

The standing cost is hours, not months, so the bill is pennies. It converts "portable in
principle" into a dated receipt in the ledger, which is the entire point of M3 and drill D5.

---

## D3 — Hermes: cut over, or destroy (#74)

**Founder:** *"what do u mean?"*

### Said plainly

Hermes is **not part of prospector**. It is a separate thing: fourteen launchd jobs on the laptop
that drive an interactive Claude Code session over Telegram (`ops/launchd/ai.hermes.*.json`).

On 2026-08-18 a Fly app `prospector-hermes` was created with a 3 GB volume — and then nothing
happened. No `fly.toml` was committed, no code was deployed, and there have been no application
logs since the app was created. Meanwhile all fourteen laptop jobs are still running.

**So right now we pay for an empty Fly volume and still depend on the laptop.** Neither half is
finished.

It is in the DR programme because §4 nominates it as the rehearsal: cutting Hermes over exercises
inventory, secrets, cutover and state survival all at once, and if the drill fails, nobody loses
money.

### Comparison

| Option | Cost | Removes laptop dependency | Gives a rehearsal |
|---|---|---|---|
| (a) Finish the cutover — commit a `fly.toml`, deploy, stop the launchd jobs | volume already paid | yes | yes |
| (b) Destroy the Fly app, keep Hermes on the laptop | saves the volume | no | no — rehearse on something else |
| (c) Leave it as it is **(today)** | pays for both | no | no |

### Recommendation — (a), finish it

The laptop is precisely the risk this programme exists to remove, and Hermes is the safest thing
in the estate to practise on. Option (c) is strictly worse than both alternatives, and it is what
we currently have.

---

## D4 — Drill cadence

**Founder:** *"configurable from ops dashboard like everything should be"*

**Accepted as a requirement, not a preference.**

### Why it is not configurable today

Drills are GitHub Actions with hardcoded `cron:` lines — `dns-drift-drill.yml` at 05:00 UTC daily,
`escape-hatch-drill.yml` on its own schedule. A `cron:` in a workflow file is fixed at commit
time, so no console can ever change it directly. And `prospector/ops/console_api.py` has no
scheduling concept at all: `ACTIONS` (`console_api.py:3196`) is twenty one-shot handlers.

### How it gets built, using what already exists

1. Cadence moves into `config.yaml`, one key per drill.
2. Each key becomes a KNOB in `KNOBS` (`console_api.py:1827`), so it renders on the config page
   with the same preview-and-confirm write fence as every other setting.
3. Each drill workflow keeps a *frequent* `cron:` (hourly) and starts with a "am I due?" gate that
   reads the config. The schedule in the YAML stops being the schedule; it becomes the tick.
4. A "run now" entry in the console `TOOLS` list, so a drill can be fired by hand.

That is the only design in which a GitHub-scheduled job is genuinely operator-configurable. It
ships inside M6.

---

## D5 — DNS

**Founder:** *"api doable from ops dashboard"*

### What is already done — M9(a) is closed

`deploy/dns/mumchimp.com.zone` is committed, and `.github/workflows/dns-drift-drill.yml` diffs
live DNS against it daily and fails on drift. `scripts/dns_zone.py` reads the authoritative
nameservers with `dig`. **The "nobody knows what the records were" risk is gone.**

`scripts/dns_zone.py` is read-only. There is no write path, so "drive DNS from the console"
cannot be built on it yet.

### The real blocker

`mumchimp.com` resolves through **GoDaddy nameservers** (`ns03/ns04.domaincontrol.com`) while the
**registrar is 123-Reg**. Two vendors, and GoDaddy has the weakest API of the candidates.

The registrar does not have to move. Only the nameservers do.

| Nameserver | Cost | API | Minimum TTL | Notes |
|---|---|---|---|---|
| **Cloudflare** | free | first-class, scoped per-zone tokens, terraform provider | 1 minute | R2 is already Cloudflare, so no new vendor |
| Route 53 | ~£0.40/mo per zone | full | 1 second | ties DNS to an AWS account we do not otherwise have |
| Stay on GoDaddy | free | exists, rate-limited, tier-gated on some accounts | 600s | keeps the two-vendor split |

### Recommendation — Cloudflare nameservers, registrar stays at 123-Reg

It is the only option that is free, has a first-class API, and gives a sub-minute TTL — which is
what turns a cutover from hours into minutes. It adds no new vendor, because R2 is already there.

The move is: the zone is already exported, add the zone at Cloudflare, change the nameservers at
123-Reg. One propagation window.

Then DNS gets an adapter shaped like `deploy/targets/*` — `dns_diff` and `dns_apply` verbs — and a
console action that goes through the same preview-plus-confirmation-token fence as every other
write. Nothing about the console needs a new concept.

---

## D6 — Store API redundancy — **RULED 2026-08-21**

**Founder:** *"lets discuss, we need to haave a k8 ready alternative also . for futture, solves
these kinds sof problem, we need to brainstron what can work tody, ingle is fine but we need
scale readiness"*

And, separately: *"also ad the k8 lastt, needs nore analysis and dicussion"*

**Recorded rulings:** single instance is acceptable **today**; scale readiness is a requirement,
not a nice-to-have; a Kubernetes-ready path must exist; and **the k8s work moves to the END of the
sequence** pending more analysis. This item stays open deliberately — it is a design conversation,
not a yes/no.

### The facts it has to survive

| | |
|---|---|
| `prospector-store-api` | SQLite on a 1 GB Fly volume, **3.9 MB used** — orders, entitlements, catalogue, audit trail |
| Why exactly one machine | `store_platform/deploy/fly/api.fly.toml:30` — SQLite is a single-writer store. This is a **correctness fence**, not a capacity choice: two machines get two volumes, two ledgers counting against the same £100/day cap, and both writing the same Stripe catalogue |
| `prospector-store-web` | stateless, already runs 2 machines, scales freely |

### The brainstorm, cheapest first

| Path | Cost | Solves write scale | Solves durability | Breaks the portability rule |
|---|---|---|---|---|
| **1. Litestream / LiteFS → R2** | £0 | no | **yes** — warm standby, point-in-time restore | no |
| 2. LiteFS read replicas | £0 | no (read scale only) | yes | no |
| 3. Postgres | managed DB bill | yes | yes | **yes** — `PORTABILITY.md` refuses a managed database |
| 4. k8s + a PVC | cluster | **no** — it moves where the one machine runs | no | no |

### Recommendation to open the discussion with

**Do (1) now.** Litestream replicating SQLite to R2 turns the single instance from an undocumented
liability into a documented one, costs nothing, changes no schema and no code, and closes most of
M4 on the way past. Keep one writer.

Treat Postgres as a decision to take when write volume actually justifies it. At 3.9 MB it does
not, and taking it early buys a managed-database lock-in in exchange for capacity nobody is using.

**And say the k8s part out loud: Kubernetes is a portability answer, not a scale answer.** Running
the Store API on k8s still leaves exactly one writer against one PVC — the single-writer fence is
in SQLite, not in Fly. k8s is worth having as a fourth deploy target so no platform can hold the
estate hostage, and it is worth having before any second provider is chosen. It is not what makes
the money path scale. That is the analysis the founder asked for before it is scheduled, and it is
why it now sits last.

### RULED 2026-08-21 — Postgres for the storefront, SQLite for everything else

**Founder:** *"dont forget decision log, postgress for storefront, sqllite for the rest"*

This overturns the recommendation directly above, which was to keep one SQLite writer and add
Litestream. The recommendation is left in place unedited, because it is the record of what was
weighed. What it got wrong: it priced the decision on today's data size and on write volume, and
neither is the constraint that matters. The storefront is the part that takes money, and it is the
one part of the estate that cannot move (`docs/MIGRATION_AND_DR_PROGRAM.md:192`). A single SQLite
writer on a single mounted volume is what pins it there.

**What the ruling changes, measured on this branch:**

| | Today | After |
|---|---|---|
| Storefront data layer | EF Core + `Microsoft.EntityFrameworkCore.Sqlite` (`store_platform/src/Store.Api/Store.Api.csproj:13`), wired at `store_platform/src/Store.Api/Program.cs:29` `options.UseSqlite(connectionString)` | EF Core + Npgsql |
| Connection string | `Data Source=/data/store.db` (`store_platform/deploy/fly/api.fly.toml:29`) | a Postgres connection string, from the secret store |
| Machine count | fenced at exactly 1, because SQLite is a single writer | the fence dissolves; `prospector-store-web` already runs 2 |
| Storefront backup | file copy off a live volume, which can tear | `pg_dump` / WAL archiving, which cannot |
| Engine store | SQLite catalogue plus append-only JSONL | **unchanged — this is the "rest"** |
| Litestream | proposed for the storefront | **still wanted, but for the engine's SQLite only** |

**The one condition that keeps the portability rule intact.** `deploy/PORTABILITY.md:127` lists
"Fly Postgres / Upstash / any managed database" as lock-in the estate refused. That refusal is
about the word *managed*, not about Postgres. A Postgres we run ourselves — on the Kubernetes
target that §5.2 of the programme now settles on — moves with the rest of the estate and keeps the
rule. A managed Postgres from a provider's console would break it, and would also break the
30-minute bar, because the data would sit somewhere the cutover script cannot reach. **So:
self-hosted Postgres, and no exceptions to that.** Which operator runs it is the next thing to
research, not something to assume here.

**What this makes into work, in order:**

1. Swap the EF provider — package reference, `Program.cs:29`, and
   `store_platform/src/Store.Api/Persistence/StoreDbContextFactory.cs:18`.
2. Regenerate the migrations. EF Core migrations are provider-specific, and everything in
   `store_platform/src/Store.Catalog/Migrations` was generated against SQLite.
3. **Move the tests with it.** `Store.Tests` builds its contexts on `UseSqlite(_connection)` in at
   least five files. Left alone, the suite would grade a different database than production runs,
   which is the same class of fault as a guard that grades a proxy. The tests need a real Postgres.
4. Move the live data. It is 3.9 MB, so this is small — but it is orders, entitlements and the
   audit trail, so it is a rehearsed move with a proven restore, not a copy.
5. Rewrite the D2 money-restore drill against `pg_restore`, and re-time it.
6. Remove the single-machine fence only after 1–5 are proven, never before.

Nothing here is done until the D2 drill restores a Postgres storefront into a throwaway
environment and `/health` answers.

---

## D7 — Local/production store sync — already decided 2026-08-19

**Founder:** *"prod is canonical, we need a way to keep local in sync"*

`/data/store` on the Fly volume is the source of truth. Tracked on #454. No change.


---

## D8 — Centralised configuration management — **RECOMMENDED 2026-08-21, awaiting your ruling**

**Founder:** *"also dont forget contralised config nanagenet"*, then *"research and add to — we have
env files littered everywhere"*, and the bar it has to meet: *"this gold standard can be ported to
any provider, need can be on aws, gcp, fly, etc"*, *"provider agnostic"*, *"even onpren also"*,
*"the whole stack"*.

### What is actually true today — the census, run 2026-08-21

"Littered everywhere" is correct, and it is worse than the phrase suggests. Configuration for this
estate lives in **six different kinds of place**, and no two of them can be diffed against each
other:

| Where config lives | How much | What it means |
|---|---|---|
| `.env` files across every checkout and worktree | **261 env-ish files in 114 trees** | 226 are copies of two `.example` templates. **33 are real `.env` files, and 31 of those were dead symlinks** all pointing at one path |
| That one path | `/Users/chidionyema/Documents/code/prospector/.env` | **It was missing.** Restored on 2026-08-21 from an encrypted snapshot — see the correction in D1 |
| `[env]` blocks inside deploy files | 6 Fly configs, 20 key/value lines | Config that only exists if you read the deploy file |
| The engine's own config | `config.yaml`, 43 top-level keys | The only one with a schema and a loader |
| macOS job definitions | **33 launchd plists, 25 carrying their own environment** | Invisible to the repo entirely |
| CI and platform stores | 7 GitHub Actions variables, 3 repo secrets, **13 Fly apps each holding their own secret set** | Readable by name, never readable back by value |

**The failure this already caused.** One missing file took 31 working trees down at once, and the
error it produces names something else entirely: *"All operators unavailable — check API keys and
credentials"*. Nothing in that message points at a symlink.

### The comparison

Twelve candidates were researched against the founder's three words — **reliable**, **trusted**,
**open source** — with licence history checked, because "trusted" is a claim about who controls the
project, not about how good the software is.

| Candidate | Needs a server? | Licence and 2026 status | Verdict |
|---|---|---|---|
| **Git files + SOPS + age** (the baseline) | **No** | SOPS: CNCF Sandbox, MPL-2.0, v3.13.3 Jul 2026. age: BSD-3, v1.3.1 Dec 2025 | **Recommended** |
| **Kustomize overlays + ConfigMaps** | **No** (a CLI, already inside `kubectl`) | Kubernetes SIG-CLI, Apache-2.0, v5.8.1 Feb 2026 | **Recommended — the renderer** |
| **Flux** (decrypts SOPS at reconcile) | Runs in-cluster, no database | CNCF **Graduated**, v2.9.4 Aug 2026; survived the Weaveworks shutdown *because* of that status | **Recommended — the applier** |
| Helm values files | No | CNCF Graduated, Apache-2.0, current | More machinery than one operator needs |
| External Secrets Operator | **Yes**, plus a backing store | CNCF Sandbox since 2022, still sandbox | **Out — it has no SOPS and no git provider.** It only becomes useful *after* deciding to run a secret server |
| **HashiCorp Vault** | Yes | **BUSL-1.1 since Aug 2023; IBM is now the named Licensor.** No OSS-licensed Vault ships today | **Out on licence** |
| **OpenBao** (the Linux Foundation fork of Vault) | Yes — HA cluster, unseal, backups | **MPL-2.0, no paid tier, nothing gated.** OpenSSF sandbox. v2.6.2 Aug 2026. NVIDIA and GitLab run it in production | **Held in reserve** — the right answer when the answer becomes a server |
| Infisical | Yes | Root licence MIT, but `ee/` is proprietary; free self-host loses RBAC, secret versioning and audit streaming, and caps at 3 environments | Out |
| Confd / Consul KV | Yes | **Confd last released May 2018.** Consul is BUSL, no maintained fork found | Out |
| **Flipt** | Yes | **Relicensed to the Fair Core License at v2** — not an OSI licence | Out on licence |
| **Unleash** | Yes, plus Postgres | **Relicensed Apache-2.0 → AGPL at v8.0.0, Jun 2026.** Genuine open source, but a server and a database for one operator's flags | Out on proportion |
| OpenFeature + flagd / GO Feature Flag | A sidecar, **no database** — reads flags from a file, a ConfigMap or a git repo | OpenFeature: CNCF Incubating. GO Feature Flag: MIT, v1.55.2 Aug 2026 | **The next step, when it is needed. Not now** |

**Three of the named candidates changed licence inside twelve months.** That is the single most
useful thing this research produced, and it is exactly what the word "trusted" was asking about.

### Recommendation — no config server. One git repo of plain files, rendered by the deploy verb

1. **One directory per environment, plain YAML.** Non-secret config committed in the clear, so it
   is reviewable, greppable and diffable. This collapses all six locations above into one.
2. **Secrets live in the same files, not separate ones.** SOPS `encrypted_regex` ciphers only the
   secret values, so one file carries both halves with one history and one review. Today the
   secret half and the config half cannot even be looked at together.
3. **Kustomize renders it.** `configMapGenerator` appends a content hash, so a config change
   triggers a rollout by itself — the one genuinely useful thing a config server's watch API buys.
4. **Flux decrypts at reconcile.** Native SOPS support: no plugin, no custom image, no alpha flags.

**Why not a server, stated as a cost.** Every candidate that is a server adds a *seventh* place
config lives, an availability dependency, and an operational bill that one person pays forever in
CVE patching, upgrades, backups and a restore drill. It also makes the stated requirement harder,
not easier: a config server keeps its data in a database outside git, so "bring up a new
environment with no human reading a value" then needs a backup and restore path you would have to
build and test. Git gives that for free.

**Why this meets the provider-agnostic bar, which is the part that decides it.** Git, SOPS, age,
Kustomize and Flux are all files and CLIs. None of them is a service belonging to AWS, GCP, Fly or
anyone else, so the same repository brings the estate up on a managed cloud cluster and on a
machine in a cupboard with no fork (F-40), and it does it for **every plane, not compute alone**
(F-39). A hosted config service would have re-created by the back door exactly the lock-in the
programme exists to remove.

### The one irreducible human step, and the risk that comes with it

Every option on this list ends at the same place: **the age private key on a new laptop.** It is
the only value a human ever reads, it is read once, and today it exists in exactly one copy on one
disk. Two things follow, and neither is optional:

- **The ciphertext must actually be committed.** D1's correction above shows it is not, and that
  the estate's entire secret backup currently survives inside four automatic snapshot commits on no
  branch. This is now **F-44** in the register. The repository is private, and the blob is
  age-encrypted; committing it is what D1 always intended and nobody ever did. **It is a founder
  decision because git history cannot be un-published.**
- **A second recipient, held offline.** A hardware-backed key (`age-plugin-yubikey`) keeps the
  private key off disk entirely, but if it is the sole recipient and the token dies, every value in
  git history is unrecoverable. The offline backup recipient is mandatory, not a nicety.

**Honest limit of this recommendation.** SOPS+age has no read audit and no real revocation:
re-encrypting to a new recipient set does not undo the fact that anyone who ever held the key can
decrypt every past value in the history. At one operator that is an acceptable trade. **At two
operators, or at the first compliance question, the answer changes to OpenBao** — and only then
does External Secrets Operator earn its three components, as the thing that syncs OpenBao into
Kubernetes. That is the condition to watch for, written down now so it is noticed when it arrives.

**The other condition that changes the answer:** needing to change a value in production *without a
deploy* — a kill switch, a gradual rollout, per-request targeting. Everything above needs a commit
and a reconcile. When that day comes the step is small and reversible: add flagd or GO Feature Flag
pointed at the *same git repo*. Still no database, still one source of truth.

### What this makes into work

New rows in the register (§11.2, P3 — now "Secrets and configuration"): **F-41** one inventory of
every runtime value, **F-42** no value defined in two places, proven by a drift probe, **F-43** a
new environment gets config and secrets in the same one command, **F-44** the encrypted store is
committed and proven restorable from `origin/main`. **N-15** carries the census number above so the
sprawl is measured rather than described.
