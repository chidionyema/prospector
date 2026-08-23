# stack.sh — read this before you need it

## What it is for

Two questions that had no command behind them, so both got answered from memory, and both got
answered wrong at least once.

- **Where is each piece of the estate running right now?** `deploy/stack.sh status`
- **If the provider vanished, what would we still have and what do I type?**
  `deploy/stack.sh recover`

It is not a deployment tool. It does not start, stop, deploy, scale or delete anything, ever.
Every probe is a read.

## What it costs

Nothing recurring. It calls `fly machines list` five times, curls four URLs, and lists seven
prefixes in the R2 bucket we already pay for. `status` takes about fifty seconds, `recover`
about twenty. No machine is woken by it — `fly machines list` is a control-plane read and does
not trigger autostart the way an HTTP request to the app would.

## What it looks at

| It asks | About |
|---|---|
| `fly machines list` | prospector-engine, -store-api, -store-web, -hermes, -hermes-v2 |
| `curl` | mumchimp.com, api.mumchimp.com, and the same two on localhost |
| `pgrep` | the engine scheduler and the hermes gateway, when they run on the laptop |
| `docker ps` | prospector-store-api and prospector-store-web, when they run in compose |
| R2 `prospector-backup` | ledger/, db/, dossiers/, repo/, logs/, offsite/, hermes/ |
| this laptop | the store, the age key, and deploy/secrets.env.age |

It reads `.env` for the R2 credentials, the same file the backup job reads. If those are
absent it says so in the table rather than failing, because "we could not look" and "there is
no backup" are different answers and only one of them is an emergency.

## Where it lives

`deploy/stack.sh` in this repository. One file, no daemon, no state, nothing installed.

`~/.claude/scripts/estate/estate_audit.py` calls it once an hour and turns two of its answers
into audit rows. `estate_watch.py` sends those to Telegram when they change. That is the only
thing that runs it on a schedule.

## How to turn it off

The script itself is not running, so there is nothing to stop. To stop the hourly grading:

```
launchctl unload ~/Library/LaunchAgents/com.founder.estateaudit.plist
```

That silences every audit row, not just these two. To silence only these two, delete the last
line of `~/.claude/scripts/estate/estate_audit.py` — `CHECKS.append(c_disaster_recovery)`.

## How to turn it back on

```
launchctl load ~/Library/LaunchAgents/com.founder.estateaudit.plist
```

## Exit codes, if you script against it

| Code | Means |
|---|---|
| 0 | everything asked, everything answered |
| 1 | something is DOWN, or a copy is missing or stale |
| 2 | something could not be asked at all (no credential, no daemon, no network) |

2 is separate from 1 deliberately. "It is off" and "we did not look" need different responses
and one non-zero cannot say which happened.

## What goes wrong

**`docker daemon not answering in 8s`.** Colima or Docker Desktop is not up. Not a fault in
the estate; the laptop rows simply could not be measured. `colima start` fixes it.

**Every fly row says UNKNOWN.** `fly auth login` has expired, or there is no `fly` on this box.
The Fly half of the picture is missing and the script says so rather than reporting DOWN.

**A row says STALE.** An R2 prefix has not been written to in over 26 hours. That is a stopped
backup job, not a slow one. Check `com.prospector.backup` and `com.founder.estatepush`.

**`secret store MISSING`.** There is no `deploy/secrets.env.age`. Until there is, the store
API's configuration exists only inside Fly and cannot be moved to another provider.
