# Platform directives — what the founder said, verbatim, with a date

> **Read this before doing any migration, DR, portability or platform work.** It is the record of
> what the founder has already decided. If something here contradicts your plan, he already ruled
> on it and you are about to make him say it a third time.

## Why this file exists

On 2026-08-19 at 15:09 the founder wrote, in seven consecutive messages:

> *"so recally this laptio is jst a backup for energency, you have to sepaarte developer workflow
> fron stack infra, also yyou were proposing relaing and deleting sone stuff, you need to check
> transscripts"*
> *"you have lost dontet and not taking notes"*
> *"you were doing web reseach"*
> *"oyou had alreaddy napped out innprovenes and what ould be replaced by better or oss solutuins etc"*
> *"in fucking fustratenow"*
> *"i have to be renebering stuuf five said"*
> *"anythingn i talk regading this progran ghas ben docunennted"*
> *"go throughthe trnsctipts also and recover contet"*

Every one of those things had been said before and was on disk. The record was complete and
useless: 3,249 founder messages spread across about 4,000 transcript `.jsonl` files, retrievable
only by writing a new scanner each time. So in practice each fresh session started from nothing and
asked him to repeat himself.

**The class of failure is: the founder's own words are captured but not retrievable, so context
dies at every compaction.** It is closed three ways, in the order LAW 0 demands.

1. **Capture, with no agent involved.** `~/.claude/scripts/directive-capture.py` is a
   `UserPromptSubmit` hook. Every message he sends, in every project, appends to
   `~/.claude/directives/<project-slug>.jsonl` as it is sent. No judgment about what matters,
   because what matters is only knowable later.
2. **Retrieval in one command**, so no agent ever writes a scanner again:

   ```bash
   python3 ~/.claude/scripts/directives.py --grep 'laptop|emergenc' --limit 20
   python3 ~/.claude/scripts/directives.py --since 2026-08-18 --full
   python3 ~/.claude/scripts/directives.py --backfill    # idempotent; mines transcripts into the log
   ```

   The backfill has already run: 3,249 messages, back to the start of the project.
3. **This file**, which is the curated layer. The log holds everything; this holds the decisions
   that bind. Append here at the moment he speaks, never later.

## 1. The bar

2026-08-19T15:06, verbatim and in full, because every requirement in it is load-bearing:

> *"ok not satis fied, if i have 30 ninutes to nigrate the wwhole stack, donain, third party deps/
> donain , everything running in this nachine because i also have a new laptop, so engine, hernes,
> jobs, and evertything on fly to another onpren or cloud provider, i should not epericne ny
> downtine and get this seanlessly done fron ops dashboard and prove and see realtine progress.
> this is the bar, even things like logs, etc nothing beig used can be nissed out, and this has to
> be resuable for any project not just prospector etc, should be able to probe and audit any systen
> and get this done. big challenge but doable"*

Eight requirements, each of which a design either meets or does not:

| # | Requirement | Status |
|---|---|---|
| B1 | 30 minutes, whole stack | not met |
| B2 | Domain and third-party dependencies move too | not met — see the DNS blocker below |
| B3 | Everything on the laptop moves | not met — Hermes is still on it (task #5) |
| B4 | Everything on Fly moves to on-prem or another cloud | partly — adapter contract exists, one target is a stub |
| B5 | Zero downtime | not met — the money DB is a file copy today |
| B6 | Driven from the ops dashboard, with real-time provable progress | not met |
| B7 | Nothing in use is missed, logs included | not met — no inventory (M1), no log shipping (M10) |
| B8 | Reusable for any project; probe and audit any system | not met — every probe written so far is prospector-specific |

**Three measured physical blockers stand between here and B1/B5.** Do not re-derive these.

- `www.mumchimp.com` and `api.mumchimp.com` are CNAMEs with a **3600-second TTL**. Caches hold for
  an hour, so a 30-minute domain cutover is impossible today. Dropping both to 60s is free and is a
  founder-only action: the zone is at GoDaddy (`ns03/ns04.domaincontrol.com`) with no API in use.
- The money datastore is a **SQLite file on a Fly volume**. Copying a live SQLite file is downtime
  by definition. Zero downtime needs continuous replication — task #94, Litestream.
- **Secrets have no restore path** (gap M2). On a new laptop the 30 minutes never start.

## 2. The two facts I made him repeat

### The laptop is an emergency backup. It is not stack infrastructure.

He said it on 2026-08-18T18:22 as part of the platform philosophy — *"we need to pick a range of
options, onpren, **lapopt as last resort**, cloud, aws, azure, gcp, and a few snaller players like
fly , digital ocean or any cheap provider"* — and had to say it again on 2026-08-19T15:09:
*"so recally this laptio is jst a backup for energency"*.

Earlier still, 2026-08-18T00:27: *"they eed to vove to fly, nothing business critical can run off
this laptop"*.

So: **no business-critical component may depend on this MacBook.** Not the engine, not Hermes, not
the jobs, not the ops dashboard, not a tunnel. The laptop is a target of last resort in a recovery
drill and a place to write code. Nothing else.

### Developer workflow is separate from stack infrastructure.

2026-08-19T15:09: *"you have to sepaarte developer workflow fron stack infra"*. This is a
modelling instruction, and the two halves have different rules. Mixing them is why "move off the
laptop" kept stalling: work that only ever needed to run on a developer's machine was being counted
as infrastructure to migrate, and infrastructure was being left on the laptop because a developer
workflow happened to reach it.

| | Developer workflow | Stack infrastructure |
|---|---|---|
| Runs on | any developer machine, disposable | Fly today, any provider tomorrow |
| May be laptop-only | yes | **never** |
| Examples | editors, Claude Code sessions, worktrees, the local `.venv`, `popdd_verify.py`, local pytest, the graphify hooks, session guards | engine scheduler and consumer, Hermes, Store.Api, Store.Web, the ops console, the 31 scheduled jobs, the money rail, the catalogue and ledger, log sinks, DNS, TLS, secrets, CI runners |
| If the machine dies | you get a new machine and clone | **a customer notices** |
| Migration obligation | none; it is re-created, never moved | in scope for the 30-minute bar, including its state |
| Backup obligation | none | RPO and a proven restore, per component |

The test for which side a thing is on: **if it stops and a customer or a scheduled job notices, it
is infrastructure.** Everything else is developer workflow, and it does not belong in the migration
programme at all.

## 3. Platform philosophy

2026-08-18T18:22, the message that set the shape of the whole programme:

> *"Whole-stack migration and portability document is nore like autonation, but can write doc before
> building i inagine we have sone of the bulding blocks already, this si a big one and we need to
> prove it and enforce regular drills, we need to pick a range of options, onpren, lapopt as last
> resort, cloud, aws, azure, gcp, and a few snaller players like fly , digital ocean or any cheap
> provider, as platfron philosophy we want cheap/free/opensource world class software, we really
> need platforn nanifesto where we clarify goals, autonatoion, self healing , little or no hunain in
> loop, secure, observable, reliable, stable, free/dirt cheap. yes Logging policy, monitoring,
> alerting is a big one, so our naifesto needs to be aplied ruthlessely to the platfron. we have the
> right idea but poor eecution with hernes agent, autononous healing, self inorovenent, autinious
> work"*

2026-08-18T19:26, on measurement and on who the platform is for:

> *"as founder i should never have to report this we should be neasuring everyting i nean everything
> becasue we eed the data to know how to inprove ... sshould be alerting way before founder finds out
> and alerts shoukld wake up agent to triage and resove and we should be neasring every incident and
> have rin books ... this platforn should be so well run, an idiot or cluless non technical person an
> run it beasssue it is nilitary surgical, every thing is visible an dobservable evryting sself heals
> ... everything we do can be reused for any project s no duplication of any work here as it can be
> applied to ther projjects seanlessly"*

The manifesto he asked for is `docs/PLATFORM_MANIFESTO.md`.

## 4. Directives on the record

Every quote below is retrievable with `directives.py --grep`. Where a directive has landed
somewhere, the landing is named; where it has not, it says so.

### Migration and portability

| When | Directive, verbatim | Where it landed |
|---|---|---|
| 2026-08-18T00:27 | *"they eed to vove to fly, nothing business critical can run off this laptop"* | R7/R8; task #5 (Hermes) still open |
| 2026-08-18T00:45 | *"Switching the laptop off what does this nean?"* | the drill this programme has to answer |
| 2026-08-18T04:23 | *"we need to finish all now, . Hermes to Fly — the last thing running on the laptop, ~2 days. stop being ridiculoous 0 ninutes or leave it"* | task #5, #10 |
| 2026-08-18T05:36 | *"the dashboad is not workig, ops dashboard, and also relying on a tunel on this nacbook to run operations is not snart, we novd ops dashbord to flyio so why we tunneling the dashboard thru the laptop"* | tunnel killed; console on Fly |
| 2026-08-18T05:51 | *"also in starting to think we should have considered terraforn or sonething else for deploy aand autonation but possibly late for that"* | see §5, the deploy-tooling reversal |
| 2026-08-18T05:56 | *"lets get everything working and theuse better tooling for whole stck deplynent overing laptop, fly and all najor providers, terrforn or if you have bettr suggestion"* | `docs/STACK_AUDIT.md`; OpenTofu chosen over Terraform |
| 2026-08-18T06:28 | *"we have fly already"* | rejected renting a Linux box for the portability proof |
| 2026-08-18T18:22 | the philosophy message, §3 above | `docs/PLATFORM_MANIFESTO.md`, `docs/MIGRATION_AND_DR_PROGRAM.md` |
| 2026-08-19T15:06 | the 30-minute bar, §1 above | **not met on any of its eight requirements** |
| 2026-08-19T15:09 | *"this laptio is jst a backup for energency"*, *"sepaarte developer workflow fron stack infra"* | §2 above |

Also on the record, un-timestamped in this table but repeated across sessions: *"look we need to
thik critically, hosting env if we need to nove , dns if we need to change donain, databasses,
assets backup, repo health and redundancy, backups, all business risks also, autonation, all you
nentioned is relevant but not ehaustive"* and *"we need log backup and retention plicies also"*.

### Tooling, OSS and replacement

| When | Directive, verbatim | Where it landed |
|---|---|---|
| 2026-08-19T11:21 | *"inprove, replace owth oss"* | `docs/STACK_AUDIT.md`, merged as PR #392 |
| 2026-08-19T11:21 | *"including recent docs, incidets , research web tooling ,oss solutions etc"* | same |
| 2026-08-19T11:21 | *"engine, ops, dev tooling, everyt srface that is touched as part of nigration and disaster recoever bot h on runing nnlaptop or fly"* | same |
| 2026-08-19T11:43 | *"wwhy eatcy? requres naintinng 2 databases, etc, this is concering ile"* | **unanswered.** See §6 |
| 2026-08-19T11:44 | *"wwhen advatage does it gve us"* | **unanswered.** See §6 |
| 2026-08-19T12:17 | *"fuck oss we have pats alreadt"* | **not about the OSS programme.** Read in context it answers the 12:09 automerge problem: `updateBranch` pushes with `GITHUB_TOKEN`, which cannot trigger CI, and the reply was reaching for a workaround. He is saying we already hold PATs. It does not retract the 11:21 OSS directive |

**The OSS research is not lost. It is `docs/STACK_AUDIT.md`, 521 lines, merged to `main` as PR
#392.** It measured the estate (53 scripts, 136 `tools/` files, 173 live docs, 31 launchd jobs, 11
Fly apps, 86 `sqlite3.connect` call sites, a 691 MB store, four Python interpreters and no version
pin) and returned a verdict per cluster: **Healthchecks** and **Gatus** for liveness, **Dagu** for
the 31 launchd jobs, **Litestream** plus **restic** for backup, **Steampipe** instead of writing an
inventory, **mise** and **uv** for the toolchain, **s6-overlay** instead of supervisord, **SOPS +
age** for secrets, **octoDNS** for DNS, **OpenTofu** over Terraform, **Vector** with **Loki** or
**OpenObserve** for logs, **Pumba** and **Toxiproxy** for chaos. It found that five of the twelve
migration gaps (M1, M2, M4, M6, M10) stop being things we build. Those verdicts became tasks #93,
#94 and #95, plus a delete list of about 90 files.

`docs/MIGRATION_AND_DR_PROGRAM.md` §5 still carries HYPOTHESIS markers saying this research could
not be done. That is stale; STACK_AUDIT answered it. Task #90 is to fold the answers in.

### Working practice, as it touches this programme

- *"we are opening prs when no throuput, naking the issue worse"* and *"we cant depend on a pr to
  get us out of a 26 open pr bottleneck"* — do not open new PRs while the queue is jammed.
- 2026-08-19T11:57: *"nnac runnners should be disabled"*, prefixed *"look for the ufcking lasttine
  this should nnever hhappenn"*.
- 2026-08-19T12:08: *"nai should always be green if broekn shoukd revert to last working version o
  uilds re never bloccked"* — main is always green; a break reverts to the last working version;
  builds are never blocked.
- 2026-08-18T19:11: close browser sessions after UI work; no hours spent on volatile UI layout
  tests; claim a ticket before the first edit; *"narrating issue without investgatig, fiing or
  ticketig"* is the failure to avoid.
- *"shipping does not nean connitingn / shipping is shipping / in production / know the
  difference"*.

## 5. Contradictions and reversals, recorded so they are not re-litigated

**The `tie-*` Fly apps. RESOLVED 2026-08-19: leave them.** On 2026-08-18T00:40 he annotated a waste
row reading *"Five tie-* Fly apps, last deployed 13 June, two Postgres machines, 11GB of volumes,
all still running"* with *"// this needs to be deleted pernanenly"*. On 2026-08-19 he changed it:
*"leave tie as it is fr now"*. The later instruction stands. Do not delete them. Revisit only when
he raises it.

**Kamal.** On 2026-08-18 I recommended Kamal for deploys and OpenTofu for provisioning. On
2026-08-19 `docs/STACK_AUDIT.md` reversed the first half: keep the adapter contract in
`deploy/PORTABILITY.md`, **not** Kamal, **not** Nomad. The later verdict stands, on the grounds
that the eleven-verb adapter contract already exists and works, and Nomad is BUSL. OpenTofu over
Terraform is unchanged and is not in dispute: Terraform went BUSL in August 2023, so choosing it to
avoid lock-in is a contradiction.

**The six Fly machines in `prospector-ci`. RESOLVED 2026-08-19: destroyed.** Created that day on a
guess that CI was congested — the mistake that produced LAW 1. He first refused the attempt to
destroy them, then ordered it: *"renove thhen"*. Four went immediately (`83d1d60cd66d68`,
`2860671c150d78`, `860097ae224e58`, `287356ebd15e18`). Two were **online and executing CI jobs** at
that moment (`80e9e0ef100dd8` running `python`, `859297f4e949e8` running `ops-console`, both on run
32271900907), so they were left to finish and reaped on idle. Destroying them live would have been
the exact failure LAW 0 names: an agent action that silently destroys another agent's in-flight
work. The lesson generalises — **Fly's machine state is not the safety check. GitHub's `busy` flag
is.** `80e9e0ef100dd8` read `stopped` in `fly machines list` while GitHub reported it online and
running a job.

## 6. Open questions, and the ones that turned out to be answered already

1. **Why two databases? ANSWERED — the answer was in the audit and I misreported it.** He asked
   *"wwhy eatcy? requres naintinng 2 databases, etc, this is concering ile"* / *"wwhen advatage does
   it gve us"*. I told him the numbers argued against the split. That was wrong, and it was wrong
   because I quoted the engine store's numbers at a question about the money path. They are two
   different datastores and the audit treats them separately:
   - **Money path — Postgres, decided.** Not about size. `prospector-store-api` runs **one machine,
     on one volume, in one zone** (`vol_4ql6dzwjylqeygnr`, 1 GB, lhr), because SQLite pins the API to
     the machine holding the file. So it cannot be made redundant, and every deploy is a window in
     which the estate cannot take money. `prospector-store-web` already runs two machines; the API
     cannot follow it. His own words on that arrangement: *"come on this is irresponsible"*.
     `STACK_AUDIT.md` §4a, decision §9.4, task #93. Confirmed by him again on 2026-08-19.
   - **Engine — SQLite stays.** `STACK_AUDIT.md` §9.5. The engine's data is 99.6% files, so moving
     2.5 MB of rows buys no discipline, and 48 test files build a real store from a temp file with
     no service in CI.
   - **So the estate runs two engines by choice, and that is the honest cost of the decision.** The
     price is two backup paths and two restore drills, and the audit is explicit that both must be
     automated and drilled rather than documented — tasks #94 (Litestream) and #80 (M4).
   - **The 258 MB `prospector.jsonl` ledger is a separate problem and still open.** Unindexed
     append-only text that the daily spend cap linear-scans, with no transaction to roll back a torn
     write. It is a file-format problem, not a database-engine one. `STACK_AUDIT.md` §9.1.
2. **Where do Healthchecks and Dagu run?** Answered on 2026-08-19 — `prospector-engine`, no new app,
   no new provider. **The answer is half wrong and is now task #97:** a dead-man's switch that runs
   on the machine it watches cannot report that machine dying; the silence and the alerter stop
   together. Dagu can stay; the alerter has to sit outside.
3. **The ~90-file delete list.** Answered: delete once each is confirmed run, docs updated in the
   same pass, report mode first. `STACK_AUDIT.md` §9.3.
4. **The two 3600s DNS TTLs. No longer a founder-only action, and my earlier note was wrong.** An
   hour of DNS cache makes the 30-minute bar unmeetable, so this is on B1's critical path. I recorded
   it as founder-only because GoDaddy has no API *in use here* — but GoDaddy publishes a DNS API,
   Steampipe ships a `godaddy_dns_record` table, and that plugin's own worked example lists records
   whose TTL exceeds a threshold. So the founder supplies a key once, and after that octoDNS owns the
   zone and a check fails whenever a record exceeds the cutover budget. Task #99, pairs with #77.

## 7. How to add to this file

At the moment he says something that binds, append it here with its timestamp and his exact words.
Not paraphrased, not tidied. If you are not sure whether it binds, append it anyway; a wrong entry
costs a line, a missing one costs him repeating himself.

Related: `docs/PLATFORM_MANIFESTO.md` (the laws and tenets), `docs/STACK_AUDIT.md` (the estate
measurement and the OSS verdicts), `docs/MIGRATION_AND_DR_PROGRAM.md` (the twelve gaps and the
sequence), `deploy/PORTABILITY.md` (the adapter contract).
