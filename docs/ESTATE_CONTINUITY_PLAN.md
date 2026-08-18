# Estate continuity plan — risk, disaster recovery, redundancy, and the way off any platform

Founder directives, 2026-08-18:
*"nothing business critical can run off this laptop"* ·
*"we cant be tied down and moving from fly needs to be seamless and pre-planned"* ·
*"sane approach for everything else even storefront needs migration plan away from fly"* ·
*"think business risks and disaster recovery as well as migration and redundancy"*.

Companion documents: `docs/ENGINE_MIGRATION_PROGRAM.md` (the engine move, step by step),
`deploy/PORTABILITY.md` (the eight-verb platform contract), `deploy/cutover.sh` (the automation).

Everything below the first table is measured, not assumed. Commands are quoted so you can re-run
any line of it.

---

## 1. What the business actually is

Money only moves along one path. Everything else is supply or admin.

```
buyer -> mumchimp.com          (Fly: prospector-store-web, 1 machine, no disk)
      -> api.mumchimp.com      (Fly: prospector-store-api, 1 machine, 1GB disk, SQLite)
      -> Stripe                (live key)
      -> R2                    (Cloudflare, the file the buyer downloads)
```

The engine — the thing we are moving tonight — makes what gets sold. It is **supply**. If the
engine is off for a day, nobody notices. If `api.mumchimp.com` is off for an hour, we cannot take
money and cannot deliver what has been paid for.

**That ordering is the whole plan.** We have been treating the engine as the critical system
because it is the noisy one. The critical system is the 1GB disk under the store API.

---

## 2. Risk register, ranked by what it costs

| # | Risk | What it costs | Likelihood | State today |
|---|---|---|---|---|
| **R1** | **Switching the laptop off also switches off the only backup of the money database** | Silent. The migration looks clean and leaves orders and entitlements uncovered from that day on. | **Certain, if we follow the migration plan as written** | **§4.1 — the order effect** |
| **R1b** | The store API's single volume is lost or corrupted | Every order, entitlement and delivery-outbox row. Buyers who paid cannot download. | Low per year, but non-zero — one volume, one host, one zone | Covered, from the laptop: `money-db/store.db` and the key ring, hourly-ish to R2, 30 kept (§4.1) |
| **R2** | Fly loses the `lhr` region, or the account is suspended | Store and API both down. No sales. | Low | Exit path exists (§6), untested |
| **R3** | This laptop dies tonight, before the migration | The engine's 0.49 GiB store: 2,935 dossiers, 119 listings, 906,341 ledger lines | Real — it is a laptop | Offsite backup runs (§4.2) |
| **R4** | Stripe key leaked or revoked | No payments | Low | Key lives in `.env` and Fly secrets only |
| **R5** | The domain lapses or the registrar account is lost | Everything. DNS is the one thing with no substitute. | Low | GoDaddy (`ns03/ns04.domaincontrol.com`) |
| **R6** | The engine spends past its cap | Up to 2× $100/day | Was real during cutover | Fenced — one container only (§5.1) |
| **R7** | Both admin dashboards keep rendering a store that stopped changing | We make decisions on stale numbers and cannot tell | Certain, if we do nothing | Fixed by moving them into the engine image |
| **R8** | Idle Fly apps burning money | Small but ongoing | Certain | §7 — five `tie-*` apps, dormant since June |

R1 is the finding of the night. It is a bigger exposure than the migration we set out to do.

---

## 3. Where everything runs, measured 2026-08-18

`fly apps list`, `fly machines list`, `fly volumes list`, `dig`:

| Thing | Platform | Redundancy | Holds data? |
|---|---|---|---|
| `mumchimp.com` | Fly `prospector-store-web`, 1 machine, `lhr` | **none — one machine** | no (stateless) |
| `api.mumchimp.com` | Fly `prospector-store-api`, 1 machine, `lhr` | **none — one machine** | **yes — `vol_4ql6dzwjylqeygnr`, 1GB, zone 8169, SQLite** |
| the engine | this laptop → Fly `prospector-engine` tonight | one by design (§5.1) | yes — 0.49 GiB, SQLite + JSONL |
| both dashboards | this laptop, Tailscale `100.93.240.113:8601/:8611` | none | no (they read the store) |
| CI runners | 4 self-hosted, this laptop | none | no |
| Hermes | this laptop, 8 launchd jobs | none | yes, small |
| DNS | GoDaddy nameservers, A → Fly anycast `66.241.124.37` | registrar-level | — |
| downloads | Cloudflare R2 | Cloudflare's own | **yes — the deliverables** |
| payments | Stripe | Stripe's own | yes |

Two things to notice. The storefront is **SQLite on a mounted volume**
(`Store.Api/Program.cs:26` → `Data Source=store.db`), not a managed database. That is good for
portability, because the data is a file that moves anywhere, and bad for redundancy, because
there is exactly one copy on exactly one disk. And `api.mumchimp.com` is a CNAME to
`prospector-store-api.fly.dev`, so leaving Fly is a DNS edit, not a re-architecture.

---

## 4. Disaster recovery

### 4.1 The store API — better than feared, and about to break

The money database **is** already declared as a backup source. `ops/config/offsite_backup.yaml`
lines 32-43 name `/data/store.db` on `prospector-store-api`, pulled over `fly ssh sftp` and
written to R2 as `money-db/store.db`. Someone did this properly, and the declaration even carries
a note explaining that it sits on a single 1GB volume in `lhr`.

The problem is **where the job runs**. It is a launchd job on this laptop
(`ops/launchd/com.prospector.offsite-backup.json`), reaching into Fly from here. So:

> **ORDER EFFECT — the one that would have bitten us.** Switching this laptop off after a
> successful engine migration also switches off the only backup of the money database. The
> migration would look clean and would quietly leave R1 uncovered.

That is exactly why the plan says the laptop stays cold-but-alive for seven days, and why the
backup job is one of the programs moving **into the engine container** rather than being left
behind. `deploy/engine/supervisord.conf` already runs `offsite-backup`; what has to be true is
that the container's copy carries the same declaration and can reach `prospector-store-api` —
which needs a Fly deploy token in the container, not a personal login.

The declaration covers a second thing that is easy to miss and would make a restore look
successful while handing every buyer a broken download: the **ASP.NET data protection key ring**
at `/data/keys`. Restore the database without it and the grant tokens it encrypted cannot be
decrypted.

Live state, checked 2026-08-18:

```
$ .venv/bin/python ops/automations/offsite_backup.py --config ops/config/offsite_backup.yaml
OK   money-db: 5.8h old
OK   data-protection-keys: 5.8h old
```

Both green, both inside the 24-hour bar the declaration sets. This is working today — from the
laptop.

Target: **RPO 1 hour, RTO 30 minutes.** Today's declaration is a file pull, which is a race
against SQLite writes. The safe version is `VACUUM INTO` inside the store API container first,
then ship the snapshot. Small change, and it removes the only reason a restored copy could be
torn.

There is a second copy we get for free and are not using: **Stripe is an independent ledger of
every payment ever taken.** If the volume is lost, Stripe can rebuild who paid for what and
entitlements can be re-issued from it. That makes R1 survivable rather than fatal — but only if a
rebuild script exists, and none does.

### 4.2 The engine

RPO 24 hours today (`com.prospector.backup` and `com.prospector.offsite-backup` to R2).
After tonight the same two jobs run inside the Fly container against `/data/store`, so the
backup follows the engine rather than staying on the laptop.

RTO is now a command rather than an afternoon: `scripts/store_migrate.py verify` proves a restore
is complete before it is trusted, and `deploy/cutover.sh --from X --to Y` rebuilds the engine
anywhere in one run.

### 4.3 What has no backup problem

R2 and Stripe are somebody else's durability problem, and both are the good kind of dependency:
their data is exportable and their APIs are standard.

### 4.4 The restore drill — the only thing that makes any of this real

A backup nobody has restored is a hypothesis. Quarterly, on the calendar:

1. `deploy/cutover.sh --from fly --to sshdocker --dry-run` — the exit path still parses.
2. Restore last night's store backup into a scratch directory and run
   `scripts/store_migrate.py verify` on it.
3. Restore the store API's SQLite backup into a throwaway Fly app and hit `/health`.

---

## 5. Redundancy — what we have, what we do not, and what is worth buying

### 5.1 Where redundancy is deliberately refused

The engine runs **one container, ever**. Two engines keep two spend ledgers and can spend twice
the $100 daily cap, and both write the same SQLite catalogue. This is a correctness fence, not a
capacity choice, and it is written into `deploy/PORTABILITY.md` as a condition any future platform
has to meet.

### 5.2 Where we have none and should

| Gap | Fix | Cost | Worth it? |
|---|---|---|---|
| Store API is one machine | run 2 machines | needs the SQLite write to move to one primary, or a swap to Postgres | **Not yet.** Restart takes seconds; the volume is the real risk, not the machine. Fix R1 first. |
| Store web is one machine | `fly scale count 2` | ~$2/mo | **Yes — it is stateless and it is the shop front.** One command. |
| One region (`lhr`) | second region | doubles cost, splits the SQLite | No. Region loss is rarer than the volume loss we have not covered. |
| CI runners on the laptop | move to a cheap VM | ~$5/mo | Yes, after the engine. Self-hosted stays free of GitHub minutes either way. |

The honest summary: we do not have a redundancy problem, we have a **backup** problem. Adding a
second machine in front of an unbacked-up volume protects against the less likely failure.

---

## 6. Leaving any platform — the pre-planned exit

The rule is the same for every component: **the thing that holds data must be a file, and the
platform must be behind one adapter.**

| Component | How we leave | Time | Tested? |
|---|---|---|---|
| engine | `deploy/cutover.sh --from fly --to sshdocker` | ~30 min | adapter written, dry-run pending |
| store API | image is a plain Dockerfile; data is `store.db`, one file. Copy, run, repoint DNS. | ~1 hour | not yet |
| store web | stateless container, rebuild anywhere, repoint DNS | ~20 min | not yet |
| DNS | GoDaddy — change the A/CNAME. Not Fly's. | minutes | — |
| R2 | S3-compatible; any S3 client, any S3 host | — | — |
| Stripe | not moving; Stripe is the business, not the platform | — | — |

**Lower the DNS TTL before any move.** A long TTL is what turns a 20-minute switch into a
half-day of split traffic.

The four things that would tie us down, and what we did instead:

| Lock-in refused | What we did |
|---|---|
| A managed database (Fly Postgres, Upstash, RDS) | SQLite files on a mounted volume, both sides |
| Platform APIs called from application code | only the adapters know the platform's name |
| A public hostname baked into the app | dashboards bind to loopback; access is a tunnel |
| Secrets that live only in the platform's vault | `.env` is the source of truth and is backed up |

---

## 7. What to do, in order

1. **Tonight — the engine to Fly.** `deploy/cutover.sh --from laptop --to fly`, dashboards
   inside the same image, laptop left cold as the backup for seven days. Closes R3 and R7.
2. **This week — back up the money.** Hourly `VACUUM INTO` + R2 upload in the store API
   container, 30-day retention. Closes R1, the largest exposure on this page.
3. **This week — `fly scale count 2` on `prospector-store-web`.** One command, one shop front
   becomes two.
4. **This week — write the Stripe rebuild script.** Turns R1 from fatal into slow.
5. **Then — CI runners off the laptop**, onto the same kind of box the `sshdocker` adapter
   already targets. Keeps them self-hosted and free of GitHub minutes.
6. **Then — delete the `tie-*` apps.** Five apps, last deployed 13 June, two of them Postgres
   machines with 11GB of volumes between them, all still running. Dormant spend and clutter in
   the same account as production.
7. **Quarterly — the restore drill in §4.4.** Otherwise this document is a wish.
