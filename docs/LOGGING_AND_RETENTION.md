# Logging, Retention and Backup

**Status:** design and policy. Nothing in Part 4 or Part 5 is built yet.
**Measured:** 2026-08-18. Every number below carries the command that produced it.
**Siblings:** [`docs/personas/ops.md`](personas/ops.md) · [`docs/personas/sre-on-call.md`](personas/sre-on-call.md) · [`OPS_AUTOMATION_PRINCIPLES.md`](OPS_AUTOMATION_PRINCIPLES.md)

---

## What this is

There is no central log in this estate. Every service writes somewhere different, most of
those places are not backed up, and two of them are erased by the operating system without
warning. This document measures that, says what it costs, and specifies the cheapest thing
that fixes it.

Read this if you are about to answer a question that spans two services, if you are about to
buy a log product, or if you need to know what survives a machine dying.

The budget for this is zero. That is a constraint on the design, not a complaint about it.

---

## Part 0 — The finding that matters most

**The nightly backup has been failing since at least 2026-08-17, and the failure is silent.**

The installed launchd job runs `backup_store.py --mirror-only`. That flag does not exist.

```
$ plutil -p ~/Library/LaunchAgents/com.prospector.backup.plist | grep -A12 ProgramArguments
  "ProgramArguments" => [
    ...
    6 => "/Users/chidionyema/Documents/code/prospector-live/scripts/backup_store.py"
    7 => "--mirror-only"
  ]

$ grep -n 'add_argument' scripts/backup_store.py
752:    parser.add_argument("--verify-only", ...)
754:    parser.add_argument("--restore", metavar="DIR", ...)
756:    parser.add_argument("--sample", type=int, default=DEFAULT_SAMPLE, ...)
758:    parser.add_argument("--db-keep", type=int, default=DEFAULT_DB_KEEP, ...)
761:    parser.add_argument("--skip-mirror", action="store_true", ...)
763:    parser.add_argument("--bundle-keep", type=int, default=DEFAULT_BUNDLE_KEEP, ...)

$ grep -c 'mirror.only\|mirror_only' scripts/backup_store.py
0
```

The script accepts `--skip-mirror`. It does not accept `--mirror-only`. argparse exits 2 on an
unknown flag, so the job dies before it copies anything.

Corroborating evidence — the receipt log stops the day before today:

```
$ ls -la store/backup.log
-rw-r--r--  1 chidionyema  staff  15472 17 Aug 09:38 store/backup.log

$ tail -1 store/backup.log
STORE_BACKUP PASS dossiers=2579 uploaded=521 unchanged=2058 verified=8/8
  ledger=ledger/prospector-2026-08-17.jsonl.gz db=db/prospector-2026-08-16.db.gz
  mirror=repo/2026-08-17T083751Z.bundle bytes=15576077
```

The job is scheduled for 03:40 daily (`ops/launchd/com.prospector.backup.json`,
`StartCalendarInterval {Hour: 3, Minute: 40}`). Today is 2026-08-18. There is no entry for
today. The last successful run was 2026-08-17 09:38.

Why nobody noticed: the job writes stdout and stderr to the same file
(`ops/launchd/com.prospector.backup.json:16-17`, both paths are
`/Users/chidionyema/Documents/code/prospector/store/backup.log`), nothing reads that file on a
schedule, and no alert fires on a launchd job that exits non-zero. This is the exact blind spot
the rest of this document exists to close.

**Fix:** change the installed plist argument to a flag that exists, or add `--mirror-only` to
the script. Do not do it by editing the plist in place — see Part 6, step 1.

**HYPOTHESIS:** the flag was renamed `--mirror-only` → `--skip-mirror` (inverted sense) in the
repo and the installed plist was never regenerated. **Check that would confirm it:**
`git log -p --follow -- scripts/backup_store.py | grep -n 'mirror'` and compare the first
appearance date against the plist's mtime (`ls -la ~/Library/LaunchAgents/com.prospector.backup.plist`).
I did not run this because it needs no write and I ran out of scope, not because it is hard.

---

## Part 1 — Current state, measured

### 1.1 The estate is six live Fly apps and one Mac

```
$ fly apps list
 NAME                 │ OWNER    │ STATUS    │ LATEST DEPLOY
 prospector-ci        │ personal │ deployed  │ 23m12s ago
 prospector-engine    │ personal │ deployed  │ 1h21m ago
 prospector-hermes    │ personal │ deployed  │ 4h22m ago
 prospector-searxng   │ personal │ deployed  │ 4h18m ago
 prospector-store-api │ personal │ deployed  │ 7h21m ago
 prospector-store-web │ personal │ deployed  │ 3h4m ago
 tie-api              │ personal │ suspended │ Jun 13 2026 12:22
 tie-db               │ personal │ suspended │
 tie-smoke            │ personal │ suspended │ Jun 13 2026 03:36
 tie-smoke-db         │ personal │ suspended │
 tie-web              │ personal │ suspended │ Jun 13 2026 18:27
```

Six deployed apps. This repo contains deploy configuration for **two** of them:

```
$ find . -name "*.fly.toml" | grep -v node_modules
./store_platform/deploy/fly/api.fly.toml
./store_platform/deploy/fly/web.fly.toml
./store_platform/deploy/fly/api.staging.fly.toml
```

`prospector-engine`, `prospector-ci`, `prospector-hermes` and `prospector-searxng` have no
config in this repo at all:

```
$ rg -c "prospector-engine" -g '!node_modules' -g '!graphify-out' . | wc -l
0
```

Zero files. A live app running the engine, redeployed 1h21m before this measurement, and this
repository does not know it exists. That is a logging problem before it is anything else: you
cannot collect logs from a service you have no inventory of.

> Note on method: an earlier version of this measurement used
> `grep -rn "prospector-engine" --include=*.toml .` and returned 0. That 0 was worthless — zsh
> failed the unquoted glob and grep never ran. The `rg` count above is the real one. Memory:
> `zsh-does-not-word-split-unquoted-vars.md`.

### 1.2 Persistent volumes, per app, named

Every Fly app has its own `/data`. A free-space number without an app name is not a fact.

```
$ fly volumes list -a prospector-store-api
 vol_4ql6dzwjylqeygnr │ created │ store_data       │ 1GB  │ lhr │ encrypted │ 48ee019fd74e58

$ fly volumes list -a prospector-engine
 vol_42kyqo6g0kdzew14 │ created │ prospector_store │ 20GB │ lhr │ encrypted │ 80d34da6636478

$ fly volumes list -a prospector-store-web
 (no rows — no volume)
```

Free space, one command per app:

```
$ fly ssh console -a prospector-store-api -C "df -h /data"
Filesystem      Size  Used Avail Use% Mounted on
/dev/vdc        974M  3.9M  904M   1% /data

$ fly ssh console -a prospector-engine -C "df -h /data"
Filesystem      Size  Used Avail Use% Mounted on
/dev/vdc         20G  602M   18G   4% /data
```

| App | Volume | Size | Used | Available | Use% |
|---|---|---|---|---|---|
| `prospector-store-api` | `store_data` | 974M | 3.9M | 904M | 1% |
| `prospector-engine` | `prospector_store` | 20G | 602M | 18G | 4% |
| `prospector-store-web` | none | — | — | — | — |

Neither volume is close to full. The 20G engine volume has 18G free and is the only place in
this estate with room for a log archive that costs nothing.

What is on the engine volume today:

```
$ fly ssh console -a prospector-engine -C "sh -c 'du -sh /data/* 2>/dev/null'"
16K	/data/lost+found
44M	/data/state
558M	/data/store
156K	/data/store.old
```

The volume was created 12 hours before this measurement and already holds a 558M store, with a
`store.old` beside it. **The engine was migrated from the Mac to Fly on 2026-08-18** — confirmed,
because the engine's own heartbeats on that volume are live. Read at wall clock
`2026-08-18T13:15:18Z`:

```
$ fly ssh console -a prospector-engine -C "cat /data/store/scheduler/heartbeat.json"
{"ts": "2026-08-18T13:15:26.521057+00:00", "pid": 679, "phase": "sleeping",
 "interval_s": 7200, "cycles": 1, "beat_every_s": 60, "slept_s": 3840,
 "code": "617c2538c433"}
```

Three consequences for this document:

1. **`/data/store/scheduler/` on `prospector-engine` is now the live state directory.** It holds
   `heartbeat.json`, `consumer_heartbeat.json`, `ALERT.txt`, `alert_state.json` and
   `alerts.jsonl` — 485,586 bytes of alert history, measured. That is the real observability
   surface and it is documented in [`docs/personas/sre-on-call.md`](personas/sre-on-call.md) §4.0.
2. **The Mac paths in §1.3 below are now mostly historical.** The rotation config still names
   them and they still exist on disk, but the daemon writing to them has moved. Rotation targets
   need to follow.
3. **`CLAUDE.md`'s production-location rule is out of date**, and `scripts/live_checkout.py`
   still probes the retired setup, so it reports an outage that is not happening. Flagged here,
   fixed in neither — see `sre-on-call.md` §3.10.

### 1.3 The Mac: where local logs go

Every launchd job's log destination, read from the tracked declarations:

```
$ rg -n '"Standard(Out|Error)Path"' ops/launchd/*.json
```

| Job | stdout / stderr destination | Survives reboot? |
|---|---|---|
| `com.prospector.scheduler` | `store/scheduler/launchd.out.log` / `launchd.err.log` | yes |
| `com.prospector.consumer` | `store/scheduler/consumer.out.log` / `consumer.err.log` | yes |
| `com.prospector.watchdog` | `store/scheduler/watchdog.out.log` / `watchdog.err.log` | yes |
| `com.prospector.backup` | `store/backup.log` (both streams, same file) | yes |
| `com.prospector.ops-console` | `/tmp/ops-console.out.log` / `/tmp/ops-console.err.log` | **no** |
| `com.prospector.control-center` | `/tmp/prospector_control_center.log` (both streams) | **no** |

Two jobs log to `/tmp`. macOS purges `/tmp` on boot and prunes it by age while running. The ops
console's entire error history is on a filesystem the operating system is entitled to empty.
When the console misbehaves and you reboot to fix it, you destroy the evidence in the same act.

Files currently there, as proof they accumulate and then vanish:

```
$ ls -la /tmp/*.log | head -6
-rw-r--r--  1 chidionyema  wheel   1455 16 Aug 14:53 /tmp/243build.log
-rw-r--r--  1 chidionyema  wheel     76 15 Aug 14:12 /tmp/api-build.log
-rw-r--r--  1 chidionyema  wheel    847 15 Aug 14:38 /tmp/api-test.log
-rw-r--r--  1 chidionyema  wheel   1943 15 Aug 14:49 /tmp/api-test2.log
-rw-r--r--  1 chidionyema  wheel     66 15 Aug 08:15 /tmp/audit_run.log
-rw-r--r--  1 chidionyema  wheel   1423 15 Aug 07:39 /tmp/b.log
```

Mac disk headroom, which bounds any local retention policy:

```
$ df -h /Users/chidionyema/Documents/code/prospector
/dev/disk1s1   466Gi   426Gi    17Gi    97%   /System/Volumes/Data
```

**97% full, 17Gi free.** This is a finding in its own right. Any policy that keeps more logs on
this machine is spending a resource that is nearly gone. It also means a runaway log file has
roughly 17Gi of rope before it takes down the daemon, the console and the store together.

### 1.4 The Fly services log to stdout and nowhere else

`Store.Api`'s complete logging configuration:

```
$ cat store_platform/src/Store.Api/appsettings.json
{
  "Logging": {
    "LogLevel": {
      "Default": "Information",
      "Microsoft.AspNetCore": "Warning"
    }
  },
  "AllowedHosts": "*"
}
```

Two log levels. No sinks, no file, no exporter. Everything goes to stdout, where Fly captures
it into a short live buffer. `fly logs` is a tail, not an archive: it shows what is in the
buffer now and cannot answer a question about yesterday.

`Store.Web` has no error reporter either. The only mention of one in the whole application is a
comment saying it was deliberately not decided:

```
store_platform/src/Store.Web/src/components/ErrorBoundary.tsx:32
    // Surface in the console for now; a real reporter (Sentry) is a deferred, founder-gated decision.
```

### 1.5 There is exactly one file logger in the Python engine

```
$ rg -n "FileHandler|RotatingFileHandler|TimedRotating" --type py -g '!store/**' .
./prospector/telemetry.py:100:    handler = logging.FileHandler(path, encoding="utf-8")
```

One. It is inside `route_logs_to_file(path, level)` and is opt-in. Nothing rotates it; the
`logging` module's own rotating handlers are not used anywhere in this repo.

### 1.6 Proof that no log shipper exists

Per-term file counts, excluding `node_modules`, `graphify-out`, `package-lock.json` and
`store/` (so vendored names and captured web content cannot inflate the count):

| Term | Files | Term | Files |
|---|---|---|---|
| loki | 0 | datadog | 0 |
| promtail | 0 | opentelemetry | 0 |
| betterstack | 0 | syslog | 0 |
| logtail | 0 | fluentd | 0 |
| papertrail | 0 | fluent-bit | 0 |
| vector.dev | 0 | axiom | 1 |
| | | sentry | 3 |

The two non-zero rows were opened. Neither is a shipper:

```
$ rg -n -i "axiom" -g '!node_modules' -g '!store/**' .
./prompts/verdict.md:8:VERDICT AXIOM:

$ rg -n -i "sentry" -g '!node_modules' -g '!store/**' . | head -3
./store_platform/src/Store.Web/src/components/ErrorBoundary.tsx:32:  // ... (Sentry) is a deferred, founder-gated decision.
./store_platform/src/Store.Web/src/data/kill-log.json:5245:  "title": "SafeStep Eldercare Fall Sentry",
./store_platform/src/Store.Web/src/data/kill-log.json:6286:  "reason": "GovSentry is a funded rival ..."
```

"AXIOM" is a word in a prompt. Two of the three "sentry" hits are the names of candidate
companies in generated data. The third is the comment saying no reporter was chosen.

**Conclusion, proven: no service in this estate ships a log anywhere.**

### 1.7 What already exists and must not be rebuilt

Two automations are live and green today. The design in Part 4 extends them; it does not
replace them.

**`ops/automations/log_rotation.py` (298 lines) + `ops/config/log_rotation.yaml`.**

It copies content out, gzips it, then truncates the file **in place**. It does not rename.
That is deliberate: a daemon holds its log open by file descriptor, so a renamed file keeps
being written to under its old inode and the "rotated" copy never grows.

Defaults are `max_mb: 10` and `keep: 5`, and the config file states the reason for each
value rather than just the value. Targets and their limits:

| Target | max_mb | keep | Why (quoted from the config) |
|---|---|---|---|
| `store/scheduler/*.log` | 10 | 7 | the file that caused the rule |
| `store/*.log` | 5 | 7 | "the only proof a scheduled job ran" |
| `.pi/side-agents/runtime/*/backlog.log` | 5 | 2 | "short useful life" |

The incident recorded in that config is the reason this whole document exists:

> "on 2026-08-16 a grep over an unrotated 25 MB launchd.err.log counted 97 provider failures
> and read as '97 today'. Today's real number was 8, and most of the rest named a provider
> chain that had already been deleted. The wrong number reached a planning document as a
> blocker."

Two exclusions, both correct, both stated in the config with reasons:

- `store/prospector.jsonl` — "It looks like a log and it is not: it is the durable spend
  ledger the daily cap reads." Truncating it changes what the spend guard believes. Measured
  today: `-rw-r--r-- 1 chidionyema staff 270268948 18 Aug 13:55 store/prospector.jsonl` —
  **270,268,948 bytes**, up from the 211 MB recorded in the config on 2026-08-16.
- `store/scheduler/audit/*.jsonl` — "one file per day already, so it rotates by construction."

**`ops/automations/offsite_backup.py` (464 lines) + `ops/config/offsite_backup.yaml`.**

Copies two things out of Fly into Cloudflare R2, bucket `prospector-backup`, prefix `offsite/`.
Secret names only: `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`. Goes red if the
newest copy is older than `max_age_hours: 24`.

| Source | What | Verify | Keep |
|---|---|---|---|
| `money-db` | `/data/store.db` from `prospector-store-api` via `fly ssh sftp get` | `sqlite` (PRAGMA integrity_check) | 30 |
| `data-protection-keys` | `/data/keys` tarred | `nonempty` | 30 |

The config states the principle plainly, and it is the right one:

> "a provider snapshot is not a backup. Fly's snapshots of vol_4ql6dzwjylqeygnr live in the
> same Fly account as the volume, keep 5 days, and have never been restored."

The `data-protection-keys` entry is the subtle one. Losing the ASP.NET key ring does not lose
data, it makes data unreadable. Restoring the database alone "would look successful and hand
every buyer a broken download link."

### 1.8 Cross-service questions that cannot be answered today

Each of these is a question an on-call person actually asks. None can be answered.

| Question | Why not |
|---|---|
| A buyer paid at 14:02 and got no file. What happened? | The Stripe webhook log is in `prospector-store-api` stdout (gone), the delivery drain's log is in the same buffer, and the engine's view is on the Mac. Three places, no shared correlation id, two of them already expired. |
| Did the storefront error spike at the same time as the API? | `prospector-store-web` and `prospector-store-api` logs are separate `fly logs` buffers. There is no way to put them on one timeline after the fact. |
| Why did the console break yesterday? | `/tmp/ops-console.err.log`. If the Mac rebooted, the answer no longer exists. |
| How many provider failures happened today? | Requires a rotated, timestamped log. This is precisely the question that produced the wrong answer of 97 on 2026-08-16. |
| Did the nightly backup run? | Only by opening `store/backup.log` by hand. Nothing checks it. This is how Part 0 went unnoticed. |
| What did `prospector-engine` do overnight? | It has no logging configuration in this repo, because the repo does not know the app exists. |

---

## Part 2 — Requirements

These come from the runbooks in [`docs/personas/sre-on-call.md`](personas/sre-on-call.md). Each is a
question that document tells someone to answer under time pressure.

| # | Requirement | Driven by |
|---|---|---|
| R1 | One timeline across store-api, store-web, engine and the Mac daemons | "storefront down", "checkout failing" |
| R2 | A correlation id that follows one purchase from checkout to delivery | "delivery failing" |
| R3 | Logs survive a machine reboot and a Fly machine replacement | every runbook |
| R4 | Answers to "what happened yesterday", not just "what is happening now" | post-incident review |
| R5 | Counting is safe — a count over a log must mean what it says | the 97-vs-8 incident |
| R6 | Money and audit records are never mixed with operational noise | ledger integrity |
| R7 | Zero new recurring cost | founder constraint, stated |
| R8 | Leaving Fly is a file copy, not a migration | avoid lock-in |
| R9 | A failed scheduled job raises something a human sees | Part 0 |

---

## Part 3 — Design principles this must obey

From [`OPS_AUTOMATION_PRINCIPLES.md`](OPS_AUTOMATION_PRINCIPLES.md), the rules that bind here:

- **P1. The engine is generic. The startup is data.** The shipper is code; what it ships and
  how long it keeps it is YAML.
- **P3. Report before fix.** The retention sweeper ships read-only and takes `--fix` second.
- **P4. State is a probe, never a sentence.** "Logging is working" is a command.
- **P5. No LLM in the loop.**
- **P6. Fail closed, and say why.** If the sweeper cannot establish the age of a file, it does
  not delete it.
- **P8. Smallest thing that works.**
- **R7. No secrets in output.**
- **R8. Cheap by default.**

---

## Part 4 — Design: one ingest endpoint, plain files, zero new cost

### 4.1 Shape

Every service POSTs structured JSON lines to one endpoint on `prospector-engine`. The engine
appends them to rolling JSONL files on its own volume. The ops console reads those files
through the existing dispatcher.

```
  prospector-store-api ─┐
  prospector-store-web ─┤
  Mac daemons (scheduler,│  POST /internal/logs   ┌──────────────────────┐
    consumer, watchdog) ─┼──────────────────────► │ prospector-engine    │
  ops console ──────────┤   Bearer <shared key>   │ /data/logs/*.jsonl   │
  prospector-ci ────────┘                         │ 20G vol, 18G free    │
                                                  └──────────┬───────────┘
                                                             │ read-only
                                                  ┌──────────▼───────────┐
                                                  │ Ops.Console /logs    │
                                                  └──────────────────────┘
```

### 4.2 Why `prospector-engine` and not `prospector-store-api`

Measured, from §1.2:

- `prospector-engine` `/data`: 20G, 18G available, 4% used.
- `prospector-store-api` `/data`: 974M, 904M available, 1% used.

The store-api volume also holds `store.db`, which is the only record of who bought what. Logs
and the money database must not share a filesystem, because a log that fills the disk stops
sales. The engine volume is 20x larger, has no money on it, and can lose everything on it
without a customer noticing.

Capacity check: 18G at a 500 MB cap for all log classes combined (Part 4.6) is 3.6% of free
space. There is no scenario in this design where logs threaten the volume.

### 4.3 Line schema

One JSON object per line. Unknown fields are kept, not rejected — a shipper that drops fields
loses the evidence it exists to keep.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `ts` | string | yes | RFC3339 UTC, millisecond precision, e.g. `2026-08-18T13:55:02.481Z` |
| `svc` | string | yes | one of `store-api`, `store-web`, `engine`, `scheduler`, `consumer`, `watchdog`, `console`, `ci` |
| `lvl` | string | yes | `debug`, `info`, `warn`, `error`, `crit` |
| `evt` | string | yes | stable machine name, e.g. `checkout.session.created`. Never interpolated. |
| `msg` | string | no | human sentence |
| `corr` | string | no | correlation id — see 4.4 |
| `ctx` | object | no | flat key/value, no nesting, no secrets |
| `host` | string | yes | machine id, set by the ingest from the connection, not the client |

`ts` and `evt` being separate from `msg` is what makes R5 safe. Counting `evt` values is exact.
Counting words inside `msg` is what produced 97 instead of 8.

### 4.4 Correlation id

R2 is the requirement that pays for this whole design.

- `Store.Web` generates a `corr` on first page load and sends it as header `X-Corr-Id`.
- `Store.Api` reads that header, and where it is absent mints one at the edge.
- The id is written onto the Stripe Checkout Session metadata at creation
  (`CheckoutEndpoints.cs`, where the session is minted).
- The webhook reads it back off the session and puts it on the fulfilment log lines
  (`WebhookEndpoints.cs`, `FulfilmentService.cs`).
- The delivery drain carries it onto the outbox row it sends.

That gives one string that spans browser → checkout → webhook → entitlement → delivery. Without
it, "this buyer got no file" stays a manual hunt across three log buffers.

**This is the only part of the design that requires touching the money path.** It adds a
metadata field and log lines. It changes no amount, no price, no fence. It still gets the
money-path review.

### 4.5 Endpoint and auth

```
POST /internal/logs
Authorization: Bearer <STORE_INTERNAL_API_KEY>
Content-Type: application/x-ndjson
Body: up to 1000 newline-delimited JSON objects, max 1 MB
```

Responses: `204` accepted, `400` malformed body, `401` bad or missing key, `413` too large,
`429` over rate limit.

Auth reuses `STORE_INTERNAL_API_KEY`, which already exists in this estate and is already read
by the console (`prospector/ops/console_api.py`, `_store_api()`). No new secret is created. Name
only; the value never appears in a log line, a config file in git, or this document.

The endpoint is `/internal/` and must be unreachable from the public internet. On Fly that means
binding it to the private 6PN network, not the public listener.

Rate limit: 100 requests/second/service, dropped not queued. A logging endpoint that applies
backpressure to the caller lets a log problem become an outage.

### 4.6 Files, rotation and caps

Files live at `/data/logs/` on `prospector-engine`, one file per service per UTC day:

```
/data/logs/store-api-2026-08-18.jsonl
/data/logs/store-web-2026-08-18.jsonl
/data/logs/engine-2026-08-18.jsonl
```

One file per day means the file rotates by construction, which is the same reasoning
`ops/config/log_rotation.yaml` already applies to `store/scheduler/audit/*.jsonl`. No copy-truncate
dance is needed because no long-lived process holds these open across a day boundary.

Caps, enforced by the ingest before it writes:

| Cap | Value | Reason |
|---|---|---|
| Per line | 16 KB | a stack trace fits; a base64 payload does not |
| Per file per day | 200 MB | at 16 KB/line that is ~12k lines; far past useful |
| Total `/data/logs` | 500 MB | 2.7% of the 18G free measured in §1.2 |

When the total cap is hit the ingest deletes the oldest day's file and records
`evt: "logs.capacity.evicted"`. It does not stop accepting. Losing the oldest day is better
than losing today.

### 4.7 Reading it

A `/logs` page in the existing Ops.Console, served through the existing dispatcher contract
(`prospector/ops/console_api.py` — `read` verb, allow-listed view). Filters: service, level,
time range, correlation id, free text.

The console cannot import Python and does not read the volume directly. It calls the dispatcher,
which fetches from the engine over the private network. This keeps the existing rule intact:
reads cannot write, and the verb in argv is the fence.

### 4.8 Why plain files satisfies R8

The archive is gzipped JSONL in a directory. Leaving Fly is:

```
fly ssh sftp get /data/logs/... -a prospector-engine
```

There is no index to rebuild, no schema to migrate, no query language to port, and no vendor to
export from. `grep`, `jq` and `zcat` are the query tools and they run anywhere.

---

## Part 5 — Retention policy

### 5.1 The classes are not the same thing

The single most important line in this policy: **operational logs and the money trail are
different classes with different rules.** `ops/config/log_rotation.yaml` already had to learn
this the hard way with `store/prospector.jsonl`, which "looks like a log and it is not."

### 5.2 The table

| Class | What | Where it lives | Retention | Why that period | How it is deleted |
|---|---|---|---|---|---|
| **Operational — hot** | ingested JSONL, all services | `prospector-engine:/data/logs/` | **14 days** | covers "what happened last week"; two weekends of incidents | daily sweeper deletes files older than 14 days |
| **Operational — cold** | gzipped daily files | R2 `prospector-backup/logs/` | **90 days** | one quarter, enough for a pattern nobody spotted live | R2 lifecycle rule |
| **Daemon stdout/stderr** | `store/scheduler/*.log` | Mac | **7 archives** | already policy | `log_rotation.py`, copy-truncate |
| **Job receipts** | `store/backup.log`, `store/offsite_backup.log` | Mac | **7 archives** | only proof a job ran | `log_rotation.py` |
| **Console/control-center** | `/tmp/*.log` | Mac `/tmp` | **effectively none** | this is the defect, not the policy | macOS purges on boot |
| **Side-agent transcripts** | `.pi/side-agents/runtime/*/backlog.log` | Mac | **2 archives** | "short useful life" | `log_rotation.py` |
| **Spend ledger** | `store/prospector.jsonl` (270,268,948 bytes) | Mac | **forever** | the daily cap reads it; truncation changes what the guard believes | never truncated; compaction is a separate job with its own reader |
| **Scheduler audit** | `store/scheduler/audit/*.jsonl` | engine `/data` | **forever** | one file per day; the record of what the daemon decided | never |
| **Alert history** | `store/scheduler/alerts.jsonl` (485,586 bytes measured) | engine `/data` | **forever** | the only record of when an alert started; `ALERT.txt` shows active only | never |
| **Alert state** | `store/scheduler/ALERT.txt`, `store/scheduler/alert_state.json` | engine `/data` | **current only** | snapshots, rewritten each fire | overwritten in place |
| **Heartbeats** | `store/scheduler/heartbeat.json`, `store/scheduler/consumer_heartbeat.json` | engine `/data` | **current only** | liveness, not history | overwritten each beat |
| **Dossiers** | `store/dossiers/*.json` | Mac + R2 | **forever** | every KILL is a receipt that the filter is real | never |
| **Money DB** | `/data/store.db` on `prospector-store-api` | Fly + R2 | **forever**, 30 offsite copies | only record of who bought what | never |
| **Key ring** | `/data/keys` on `prospector-store-api` | Fly + R2 | **forever**, 30 offsite copies | losing it makes restored data unreadable | never |

### 5.3 Personal data

Operational logs will contain, unavoidably:

- IP addresses (from request logging)
- Email addresses (from checkout and delivery)
- Country codes (already read server-side from `Fly-Client-Country`)
- Stripe customer and session identifiers

That makes the 14-day hot and 90-day cold windows a data-protection decision, not just a disk
decision. Three rules follow:

1. **Never log a card number, a full Stripe secret, a grant token, or any value from an
   environment variable.** The `ctx` object is filtered against a deny-list at the ingest, not
   at the caller. A caller you have to trust is not a control.
2. **Email addresses are hashed in `ctx` unless the line is in the money class.** A support
   question needs "is this the same buyer as that one", which a hash answers.
3. **90 days is the outer bound for anything with an IP or an email in it.** If a longer
   window is ever wanted for analytics, that is a separate store with the personal fields
   stripped, not an extension of this one.

**HYPOTHESIS:** no data-protection or privacy policy currently states a log retention period.
**Check:** `rg -il "retention|gdpr|privacy" docs/ store_platform/src/Store.Web/src/pages/`. I did
not run it; it belongs in the first pull request of Part 6.

---

## Part 6 — Backup policy

### 6.1 What is backed up today

| Thing | By what | To where | Verified? | Working? |
|---|---|---|---|---|
| Engine store: dossiers, ledger, index | `scripts/backup_store.py` (803 lines) via `com.prospector.backup` | R2 `prospector-backup` | yes — `verified=8/8` sampled | **NO — broken, Part 0** |
| Repo mirror bundle | same job | R2 `repo/` | yes | **NO — same job** |
| Money DB `/data/store.db` | `ops/automations/offsite_backup.py` | R2 `offsite/money-db/` | yes — `PRAGMA integrity_check` | last receipt 17 Aug 19:50 |
| Key ring `/data/keys` | same automation | R2 `offsite/data-protection-keys/` | `nonempty` | same |

### 6.2 What is NOT backed up

- **Everything on `prospector-engine:/data`** — 558M of store and 44M of state, on a volume
  created 12 hours ago, with no config in this repo. Nothing copies it out.
- **All operational logs**, because none are collected.
- **The ops console's own state**, in `/tmp`.
- **The Mac's `store/scheduler/audit/*.jsonl`** — I could not confirm these are inside the
  `backup_store.py` set. **HYPOTHESIS:** they are not. **Check:**
  `.venv/bin/python scripts/backup_store.py --verify-only` and read which prefixes it lists.

### 6.3 Restore procedure

`backup_store.py` has a `--restore DIR` flag (`scripts/backup_store.py:754`). That is the
documented path for the engine store.

For the money database:

1. Pull the newest verified copy from R2 `offsite/money-db/`.
2. Open it locally and run `PRAGMA integrity_check` before trusting it.
3. Pull the matching-date key ring from `offsite/data-protection-keys/`.
4. Restore **both**. A database restored without its key ring produces a service that starts
   cleanly and hands every buyer a broken download link. This is stated in
   `ops/config/offsite_backup.yaml` and it is the failure mode most likely to be missed at 3am.
5. Verify with `GET /healthz/money-rail` before taking traffic, and confirm
   `Mode` is `live` and `DecidedAtUtc` is not null.

### 6.4 How a restore would be tested

It has not been. `ops/config/offsite_backup.yaml` says Fly's own snapshots "have never been
restored", and the same is true of the R2 copies.

Proposed drill, quarterly, one hour:

1. Create a throwaway Fly app from the same Dockerfile.
2. Restore the newest `money-db` and `data-protection-keys` into its volume.
3. Boot it. Confirm `MoneyRailConfigGate` does not refuse boot.
4. Hit `GET /catalog` and `GET /healthz/money-rail`.
5. Take one known-good historical grant token and confirm it still decrypts. **This is the
   step that proves the key ring restore, and it is the only step that can.**
6. Destroy the app. Record the date and result in `store/backup.log`.

Until step 5 has passed once, the correct statement about this estate is "we have copies", not
"we have backups".

---

## Part 7 — Rejected options

Every option below was rejected for cost, lock-in, or both. R7 is zero new recurring spend.

| Option | Cost | Lock-in | Verdict |
|---|---|---|---|
| **Grafana Loki, self-hosted** | A second Fly machine. `shared-cpu-1x`/512mb is roughly the same class as the store-api machine, plus a volume for the index and chunks. | LogQL queries and the chunk format are Loki's. Moving means re-writing every saved query. | **Rejected.** It is a database with a query language, an index and a compactor, to answer questions that `grep` over 500 MB answers in under a second. P8 says smallest thing that works. |
| **Grafana Cloud free tier** | £0 up to 50 GB, then metered. | Dashboards, alert rules and queries all live in their product. Exporting them is a project. | **Rejected.** The free tier is real, but the cost is not the objection — the objection is that the estate's observability would live in an account outside it, and the founder's constraint is zero budget precisely because budget can disappear. A free tier that becomes paid at 50 GB is a bill with a delay on it. |
| **Better Stack (Logtail)** | Free tier is 1 GB/month and 3 days retention. Our 14-day requirement (R4) is a paid plan. | Proprietary ingest and query. | **Rejected.** 3 days does not meet R4. Meeting R4 costs money. |
| **Papertrail** | Free tier 50 MB/month, 7 days search. | Proprietary. | **Rejected.** 50 MB/month is smaller than a single bad day. |
| **Axiom** | Generous free tier. | Proprietary query language and storage. | **Rejected on lock-in.** Also: the repo's only "axiom" hit is the word AXIOM in `prompts/verdict.md:8`, so nothing here is already committed to it. |
| **Datadog** | Priced per host and per GB ingested. The most expensive option on this list by a wide margin. | Total. Agent, tags, dashboards, monitors. | **Rejected.** Violates R7 immediately and R8 permanently. |
| **Sentry** | Free tier exists for errors. | Moderate. | **Not rejected — out of scope.** Sentry is error tracking, not logging. `ErrorBoundary.tsx:32` records it as "a deferred, founder-gated decision" and it stays that way. It would not satisfy R1, R2 or R4. |
| **A second Fly machine as a log host** | Roughly the cost of one more `shared-cpu-1x` machine plus a volume. | None. | **Rejected on cost only.** The `prospector-engine` volume has 18G free (§1.2). Paying for a second machine to hold 500 MB when an existing machine has 18G spare fails R7 and P8. |
| **OpenTelemetry collector** | Free software; needs somewhere to send data. | Low — OTLP is a standard. | **Rejected for now.** It is a pipeline with no destination. Every destination on this list is rejected. Revisit if a budget ever appears; the JSONL schema in §4.3 maps cleanly onto OTLP fields, which keeps that door open. |
| **`fly logs` piped into a file on the Mac** | £0. | None. | **Rejected as the primary mechanism.** It is a tail: when the collector is down or the Mac sleeps, those lines are gone forever, and there is no way to tell afterwards that they are missing. Silent, unmeasurable loss is worse than no logs, because it looks the same as quiet. Fine as a debugging tool; not a design. |

---

## Part 8 — Implementation plan

Each step is one pull request. Each is independently useful. Each ships report-only first where
it writes anything (P3).

**Step 1 — Fix the backup. CLOSED, and the premise was wrong.**
Measured 2026-08-20: `--mirror-only` is a real flag (`scripts/backup_store.py:854`, and `:786` in
the live checkout), so there was no bad argument to correct. The guard this step asked for already
exists and is green: `tests/unit/test_launchd_checks_the_script_not_the_interpreter.py`, 4 passed.

The job is still failing, for a different reason, and the difference is the whole point of this
document. Run by hand with launchd's exact `ProgramArguments` it PASSES:

    STORE_BACKUP PASS mirror=repo/2026-08-19T233340Z.bundle bytes=66664795   (2026-08-20 00:33)

Under launchd the same argv exits 78. Nothing recorded that. All three channels are empty:
`store/backup.log` (the job's own `StandardOutPath` AND `StandardErrorPath`) has an mtime of
2026-08-17 09:38 and its last line is that day's PASS; the wrapper's receipt ledger
`~/.hermes/state/capability_receipts.jsonl` has no `com.prospector.backup` row after 2026-08-19
09:09, and every row it does have says `exit_code: 0`; and `launchctl list` is the only place in
the estate that knows the number 78.

A job whose stdout, stderr and receipt ledger are all silent about a failure it definitely had is
not an under-logged job. It is an unobserved one, and no amount of shipping logs helps if the
failing run emits none. That is why Step 2 is graded on a DURABLE RECORD rather than on log
volume, and it is why `--mirror-only` under launchd stays open separately (task #92 proposes
unloading this job entirely, since the store it guards is no longer canonical).

**Step 2 — Alert on a failed scheduled job. DONE.**
The instruction above was to extend `prospector/scheduler/alerts.py` because "today nothing does".
Measured 2026-08-20, that was half wrong, and the wrong half is the interesting one.
`scripts/process_audit.py` already grades every launchd job on this Mac AND every supervisord
program inside `prospector-engine` (`grade_fly` marks non-RUNNING BAD, and marks "could not ask
supervisorctl" BAD too), and it already had an `--alert` flag. The rail existed. It could not fire.

`alert()` imported `~/.hermes/scripts/estate_alert.py` — a module in another project's checkout.
On any host without Hermes, which includes `prospector-engine` where production runs, the import
raised, the function returned the string `could not alert: No module named estate_alert`, and
NOTHING GRADED THAT STRING. The audit printed it, exited 1 for the findings, and the estate went
on being reported as watched. Same class as a workflow that can never run: the failure is
indistinguishable from ordinary output.

The fix routes through this repo's own alert door, `prospector.scheduler.alerts.emit_alert`, which
is strictly wider than what it replaced: it appends the record to `alerts.jsonl` with an fsync
BEFORE any sink is tried, and its Telegram sink loads the same Hermes sender this used to import,
so nothing is lost where Hermes IS present. When every sink is missing there is still a receipt
saying the estate was failing at this time. A broken alert path now returns
`ALERT PATH BROKEN (<Type>: <msg>) -- N failing went unsent`, which no reader mistakes for success.

Live evidence that made this a P0 rather than a tidy-up, all measured 2026-08-20:
`com.prospector.backup` last exit 78, `com.prospector.process-audit` last exit 2, and the laptop
backup silently dead since 2026-08-17 (see Step 1).

*Verification:* `tests/unit/test_a_failing_job_must_raise.py`, 7 passed. Mutation-checked by
restoring the old unreachable-import behaviour: 4 of the 7 fail, including
`test_a_failing_audit_leaves_a_durable_record_with_no_sinks_at_all`. The tests deliberately do not
assert a notification was delivered — no test can promise that, and one that mocked a sink into
returning True would be testing the mock. They assert the durable record, under an autouse fixture
that neutralises every sink, which is the permanent state of any host without Hermes.

**Step 3 — The two `/tmp` loggers. DONE, by deleting both jobs rather than moving their logs.**
The instruction above was to point `com.prospector.ops-console` and
`com.prospector.control-center` at `store/logs/` and give that a prune target. Measured
2026-08-20, before any edit, neither job was running and one of them no longer existed:

```
$ launchctl print gui/501/com.prospector.ops-console
Could not find service "com.prospector.ops-console" in domain for user gui: 501
$ launchctl print-disabled gui/501 | grep ops-console
        "com.prospector.ops-console" => disabled
$ lsof -nP -iTCP:8611 -sTCP:LISTEN        # nothing
$ ls ~/Library/LaunchAgents/com.prospector.control-center.plist
ls: No such file or directory
```

The console moved to Fly. It is `[program:ops-console]` in `deploy/engine/supervisord.conf`,
its two streams go to `/dev/stdout` and `/dev/stderr`, supervisord hands those to the container
log, and Part 4's ingest is what carries them off the machine. So the console's logs already
land where this document says they should, and moving a dead Mac job's `/tmp` files would have
polished a job nothing runs. Both were retired instead:

| label | what was done | evidence it was safe |
|---|---|---|
| `com.prospector.ops-console` | `launchctl bootout`, plist renamed `.RETIRED-2026-08-20` | already `disabled`, nothing on 8611, running on Fly |
| `com.prospector.control-center` | nothing to do | no plist, no snapshot, no override |
| `com.haworks.continuous-review` | `launchctl bootout`, plist retired | another project; `BROKEN` on every `--check` |
| `com.haworks.test-coverage` | `launchctl bootout`, plist retired | another project; `BROKEN` on every `--check` |
| `com.tie.ai-review` | `launchctl bootout`, plist retired | another project; `BROKEN` on every `--check` |

The last three are not Prospector's and were never meant to be tracked here. They were on this
Mac, `scripts/launchd_plists.py` snapshotted them because nothing said not to, and once their
checkouts went away `--check` printed three permanent `BROKEN` findings about jobs this repo
does not own. `--check` went from 11 findings to 1 after the retirement and re-snapshot, and the
one that remains is real: `com.prospector.process-audit` names a script the stale `prospector-live`
checkout does not have yet.

**What stops this coming back** is not the retirement, which any reinstall undoes. It is two
rules read out of files in this repository, so they hold on CI and not just on the Mac that has
the plists — `tests/unit/test_launchd_tracks_only_prospector.py`:

1. `com.haworks.` and `com.tie.` are in `_FOREIGN_PREFIXES`, so `--snapshot` cannot re-adopt
   them, and the test fails if either prefix is dropped from that tuple.
2. **No tracked job may declare a log path under `/tmp`.** macOS purges `/tmp` on reboot, so a
   log there cannot answer a question tomorrow — which is the defect this step existed to fix,
   stated once as a rule instead of twice as a fix. The check reads `StandardOutPath`,
   `StandardErrorPath` and every other string in the plist, so a redirect hidden in an argv is
   caught too.

*Verification:* 5 passed. Mutation-checked three ways, each killing exactly one test: drop
`com.haworks.` from `_FOREIGN_PREFIXES`; give a tracked job a `/tmp` `StandardOutPath`; put a
`com.haworks.*` snapshot back in `ops/launchd/`. Restored: 23 passed across all four launchd
suites. `rg -n '/tmp/' ops/launchd/` returns nothing.

**Step 4 — Bring `prospector-engine` into the repo. DONE.**
`deploy/engine/fly.toml` is committed and is what the app is deployed from, alongside
`deploy/engine/Dockerfile` and `deploy/engine/supervisord.conf`. The reason it mattered: an app
with 558M of live state and zero references in its own repository cannot be operated, logged or
restored.
*Verification:* `fly config show -a prospector-engine` matches `deploy/engine/fly.toml`.

**Step 5 — Back up the engine volume. ALREADY CLOSED.**
Measured 2026-08-20: `ops/config/offsite_backup.yaml` already declares three engine sources —
`engine-ledger` (:121), `engine-store-db` (:130) and `repo-mirror` (:139) — each with
`max_age_hours: 30`, and each written by the `[program:backup]` entry in
`deploy/engine/supervisord.conf`. Nothing to add. The step was written against an older config.

**Step 6 — The ingest endpoint, engine side.**
`POST /internal/logs` on `prospector-engine`, private network only. Writes
`/data/logs/<svc>-<date>.jsonl`. Enforces the three caps in §4.6. No client changes yet.
*Verification:* `curl` one line from inside the 6PN, confirm it lands; confirm a 17 KB line is
rejected with 413; confirm a bad key gets 401.

**Step 7 — First producer: the Mac daemons.**
A small writer in `prospector/telemetry.py` alongside the existing `route_logs_to_file`
(`telemetry.py:100`). Buffered, non-blocking, drops on failure. **A logging call must never be
able to fail a tick.**
*Verification:* `evt` counts in `/data/logs/scheduler-*.jsonl` match tick counts in
`store/scheduler/ticks.jsonl`.

**Step 8 — Second producer: `Store.Api`.**
An `ILoggerProvider` that batches to the ingest. This is the first PR that touches the money
service, so it is the first that needs the money-path review. It adds logging only.
*Verification:* a checkout in test mode produces lines in `/data/logs/store-api-*.jsonl`.

**Step 9 — The correlation id.**
`X-Corr-Id` through web → api → Stripe session metadata → webhook → fulfilment → delivery.
Money-path review again.
*Verification:* one test purchase yields one `corr` value that appears in every stage, queried
with a single `grep`.

**Step 10 — The console page.**
`/logs` in Ops.Console, through the existing dispatcher read verb. Registered in the view
allow-list, which the drift test in `tests/unit/test_console_tools_run.py`
(`test_the_browser_view_allowlist_matches_the_gateway`) already enforces.
*Verification:* the page renders and the drift test passes.

**Step 11 — The retention sweeper. DONE, and not as this step instructed.**
The instruction above was to write a new module, `ops/automations/log_retention.py` (doc-lint-ok),
carrying its own declaration, `ops/config/log_retention.yaml` (doc-lint-ok). Neither should ever
exist, and the reason is worth recording because the same mistake is available on every future
step of this document.

`ops/automations/log_rotation.py` already implements the whole contract this step asked for:
report-only by default, `--fix` to delete, `--json`, `--config PATH`, exit 0 clean / 1 findings /
2 could not establish, plus two things the new module would not have had on day one — a
`max_delete` cap that refuses a glob that matches more than its author believed, and
`resolve_prune`, which will not follow a symlink, will not cross a `.git` segment and skips any
file git is tracking. A second module would have been a second copy of a tested engine, and the
copy is where the next deletion accident lives.

So Step 11 is two edits to files that already exist, and a test that pins the one thing the edits
cannot prove about each other.

*The declaration.* One prune target appended to `ops/config/log_rotation.yaml`:
`/data/logs/*.jsonl`, `older_than_days: 14`, no `keep_newest`. Age only is deliberate — a count
bound holds a file forever on a service that stopped emitting, and that is precisely the case
where a stale log still contains personal data (§5.3) and no longer answers any question.

*The path is absolute on purpose, and this was the second design.* The first attempt set
`PROSPECTOR_LOG_DIR=/data/logs` in `deploy/engine/Dockerfile`, `deploy/engine/fly.toml` and the
Mac plist, and declared the target as `$PROSPECTOR_LOG_DIR/*.jsonl`. It was built, tested green
and then reverted, for two measured reasons:

- `ops/launchd/*.json` is a SNAPSHOT of the plists installed on this Mac, not a source that
  anything installs from — `scripts/launchd_plists.py` has `--check` and `--snapshot` and no
  installer, and it duly reported the edit as *drift*. Committing it would have asserted a
  machine state that does not exist.
- An unset variable is not a quiet no-op in this engine. `_assert_expanded` raises
  `CannotEstablish`, and `run()` catches that at the top level and returns `status="unknown"`
  for the WHOLE run. A Mac that never got the variable would therefore also stop reporting on
  Hermes' logs, the Adobe pile and the daemon's own stdout — one missing variable blanking four
  unrelated targets.

`/data/logs` simply does not exist on this Mac, so the target reports zero files, which is the
truth. The cost is that the string restates what `log_ingest.log_dir()` derives from the store
root, and that cost is paid by the test below.

*Something has to run it.* Measured before this step,
`rg -n log_rotation ops/launchd/ .github/workflows/ deploy/engine/` returned exactly one hit —
the Mac plist. Nothing pruned `/data/logs` at all, so the declaration alone would have been a
policy that is off. `[program:log-retention]` in `deploy/engine/supervisord.conf` runs it daily
(the bound is 14 days; a sweep a few hours late deletes the same files) through `receipt.sh`, so
the exit code lands in `$PROSPECTOR_STORE_DIR/ops/receipts/` — a silently failing sweep is the
Step 2 defect again, and this is what stops it being invisible. `priority=50` puts it after every
program that produces logs; it holds no descriptor on what it deletes and opens no database, so
it cannot wedge a producer.

*Verification:* `tests/unit/test_log_retention_sweeps_where_the_logs_land.py`, 8 passed.
Report mode names the old files and deletes nothing; `--fix` deletes past the window and leaves a
file one hour inside it; the glob leaves a `.json` and a `.db` sitting beside the logs. The test
that justifies the whole file asserts that the declared glob's parent equals
`log_ingest.log_dir()` under the `PROSPECTOR_STORE_DIR` the engine Dockerfile declares, so the
two halves cannot drift apart in silence. Mutation-checked four ways — remove
`[program:log-retention]`, point the glob at `/data/store/logs`, widen the window to 30 days, drop
`--fix` — each kills exactly one test, and the restore is green.

**Step 12 — Cold tier and the restore drill.**
Daily gzip of yesterday's files to R2 `prospector-backup/logs/` with a 90-day lifecycle rule.
Then run the §6.4 drill once and write the date and result into `store/backup.log`.
*Verification:* step 5 of the drill passes — a historical grant token decrypts against the
restored key ring.

---

## Part 9 — Open gaps and what closing each costs

| Gap | Cost to close | Consequence of leaving it |
|---|---|---|
| Backup broken (Part 0) | 1 line + a test. Under an hour. | No engine backup at all. Ongoing. |
| No alert on job failure | Half a day, Step 2. | Every future silent failure repeats Part 0. |
| `prospector-engine` not in the repo | Half a day, Step 4. | A live app with 558M of state that nobody can rebuild. |
| Engine volume not backed up | Config plus verification, Step 5. | Losing that volume loses 558M with no copy. |
| No restore has ever been tested | One hour per quarter, §6.4. | "We have copies" is being said as if it means "we have backups". |
| No correlation id | Steps 8–9, the largest item, and money-path review. | "Buyer paid, got nothing" stays a manual three-place hunt. |
| `/tmp` logs | An hour, Step 3. | The console's history dies on every reboot. |
| Mac at 97% full | Not a logging fix. Needs its own decision. | 17Gi of rope before three services fail at once. |
| `CLAUDE.md` names a production checkout that does not exist | Doc edit. The move is settled (§1.2); only the docs lag. | The operating rules describe a machine layout that is not the current one. |
| `ops/config/log_rotation.yaml` targets Mac paths the daemon no longer writes to | Config edit once the Fly layout is settled. | Rotation runs green against files nobody writes, while the engine's logs on `/data` rotate not at all. |
| `scripts/live_checkout.py` reports a false outage | One PR. | An on-call engineer restarts a retired daemon and creates a second writer on the engine store. |
| No stated log retention in any privacy policy | Unknown until the check in §5.3 is run. | Personal data kept with no declared period. |

---

## Part 10 — Where to look next

| You want | Go to |
|---|---|
| The operator's control surface, every tool and lever | [`docs/personas/ops.md`](personas/ops.md) |
| What to do at 3am when something is down | [`docs/personas/sre-on-call.md`](personas/sre-on-call.md) |
| The rules any new automation must follow | [`OPS_AUTOMATION_PRINCIPLES.md`](OPS_AUTOMATION_PRINCIPLES.md) |
| The rotation engine | `ops/automations/log_rotation.py` |
| What gets rotated and why | `ops/config/log_rotation.yaml` |
| What gets copied off Fly and why | `ops/config/offsite_backup.yaml` |
| The engine store backup | `scripts/backup_store.py` |
| The one file logger | `prospector/telemetry.py:100` |
| Launchd job declarations | `ops/launchd/*.json` |
| The console dispatcher | `prospector/ops/console_api.py` |

> An estate map was expected at `ESTATE_MAP.md`. It does not exist:
> `ls docs/ESTATE_MAP.md` → No such file or directory, and
> `rg -l "ESTATE_MAP" .` → zero hits. The link is left unmade rather than pointed at nothing.
