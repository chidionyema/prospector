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
| Encrypted store, committed to the repo | `deploy/secrets.env.age` |
| `init` / `import` / `list` / `check` / `push` verbs | `deploy/secrets.sh` |
| Push path to the platform | `deploy/targets/fly.sh::t_secrets` → `fly secrets import --stage` |
| The private key | `~/.config/prospector/age-key.txt`, mode 600, never committed |

The estate already uses `age`, already commits the ciphertext, and already has a one-command push.

**So the gap is much narrower than M2 states: the age key itself has no restore path.** If the
laptop disk is lost, the committed ciphertext is unreadable and all 11 secrets have to be
re-minted by hand from six vendor consoles.

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

## D6 — Store API redundancy — **OPEN, for discussion**

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

---

## D7 — Local/production store sync — already decided 2026-08-19

**Founder:** *"prod is canonical, we need a way to keep local in sync"*

`/data/store` on the Fly volume is the source of truth. Tracked on #454. No change.
