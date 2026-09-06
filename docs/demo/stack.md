# stack.sh — what it looks like when you run it

Everything below is pasted from real runs on 2026-08-23. Nothing here is illustrative.

## Where is everything running?

```
$ bash deploy/stack.sh status

COMPONENT   PLATFORM STATE    DETAIL
----------- ------- -------- ------
engine      fly     DOWN     0/1 started
engine      laptop  DOWN     scheduler not running
store-api   fly     UP       1/1 machines started
store-api   fly     DOWN     HTTP 404
store-api   laptop  UNKNOWN  docker daemon not answering in 8s
store-api   laptop  DOWN     no answer from http://127.0.0.1:5291/health
store-web   fly     DOWN     0/2 started
store-web   fly     DOWN     no answer from https://mumchimp.com/
store-web   laptop  UNKNOWN  docker daemon not answering in 8s
store-web   laptop  DOWN     no answer from http://127.0.0.1:3000/
hermes      fly     DOWN     0/1 started
hermes-v2   fly     DOWN     0/1 started
hermes      laptop  UP       gateway running

2 up, 9 down, 2 unknown

flip the engine:   deploy/cutover.sh --from fly --to laptop      (and --from laptop --to fly to come back)
bring the stack up here: deploy/compose/preflight.sh && docker compose --profile store up -d --build
```

That run is what told us the production engine had been stopped, four minutes after it
happened, before anybody said so. It also shows the two things the layout is for.

**Two rows per component, on purpose.** `store-api fly UP 1/1 machines started` and
`store-api fly DOWN HTTP 404` are both true at once. Fly says the machine is allocated and
running. A request says it does not serve `/health`. Those fail differently, so both are
asked and both are printed rather than one being chosen.

**UNKNOWN is not DOWN.** The two `docker daemon not answering in 8s` rows mean the probe
could not run, not that the container is absent. A screen that painted those the same colour
as the real DOWN rows would make a dead checker look exactly like a healthy estate.

## What would we still have if the provider vanished?

```
$ bash deploy/stack.sh recover

WHAT WE STILL HAVE IF EVERYTHING ELSE BURNS

WHAT                         WHERE         AGE      NEWEST  RESTORE WITH
---------------------------  ------------  -------  ------  ------------
money ledger (20 obj)        r2:ledger/    17.4h    36.2M   python3 scripts/backup_store.py --restore-money ./restored
money db (12 obj)            r2:db/        17.4h    955.2K  python3 scripts/backup_store.py --restore-money ./restored
dossiers (4666 obj)          r2:dossiers/  17.4h    98.2K   python3 scripts/backup_store.py --restore ./restored
this repo (14 obj)           r2:repo/      5.9h     67.9M   git clone <the .bundle downloaded from r2> prospector
engine logs (15 obj)         r2:logs/      17.3h    308.4K  aws s3 cp --recursive s3://prospector-backup/logs/ ./logs
offsite mirror (114 obj)     r2:offsite/   4.9h     1.6M    see ~/.claude/scripts/estate/estate_push.sh (it wrote these)
hermes state (1 obj)         r2:hermes/    3.5h     313B    see ~/.claude/scripts/estate/estate_push.sh (it wrote these)
live store (this checkout)   this laptop   1.8h     9.2K    already here -- nothing to restore
age key                      this laptop   5.4d     189B    WITHOUT THIS FILE deploy/secrets.env.age CANNOT BE READ. Back it up off this laptop.
secret store                 this laptop   MISSING  -       bash deploy/secrets.sh push <target>

10 copies listed, 1 missing or unreadable, 0 older than 26h

prove a copy actually restores (do not wait for the outage to find out):
  python3 scripts/backup_store.py --restore-money ./restored   # money path, ~1 minute
  python3 scripts/restore_drill.py --backup ./restored --store ./store
```

The restore command sits in the same row as the copy it restores, and both are computed from
what is in the bucket at the moment you run it. That is the point. A runbook in a document
goes stale silently; this cannot, because there is nothing written down to go stale.

The `MISSING` row is a real finding, not a placeholder: there is no encrypted secret store
yet, so the store API's configuration exists only inside Fly.

## The claim this replaces

Asked on 2026-08-23 whether the money ledger could be recovered without Fly, I said it could
not. That was wrong. It was in R2 the whole time and the restore command already existed:

```
$ python3 scripts/backup_store.py --restore-money ./restored
restored ledger/prospector-2026-08-22.jsonl.gz -> prospector.jsonl, 1650225 records, 507397971 bytes, gzip CRC ok
restored db/prospector-2026-08-23.db.gz -> prospector.db, integrity ok, dossiers=3608
STORE_BACKUP RESTORE_MONEY PASS
```

Forty minutes of hunting produced a wrong answer. `recover` produces the right one in twenty
seconds, which is the entire reason it exists.
