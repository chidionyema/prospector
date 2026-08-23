# Demo — the offsite restore drill

Every night the backup job writes thirteen things to Cloudflare R2 and exits 0. This is the
thing that goes and gets them back out again, one by one, and opens each one to see whether
there is anything inside. It is the difference between a backup and a hope.

## What one run looks like

Real output, 2026-08-23, from `prospector-live` against the live `prospector-backup` bucket:

```
$ .venv/bin/python -m ops.automations.offsite_restore_drill

PASS money-db               (4,419,584 bytes) sqlite verified
PASS data-protection-keys   (821 bytes) tgz verified
PASS agent-estate           (12,086,164 bytes) tgz verified
PASS hermes-state           (2,351,104 bytes) sqlite verified
PASS maestro-experience     (18,458 bytes) tgz verified
PASS secret-store           (2,860 bytes) nonempty verified, decrypted to 25 secrets
PASS architect-code         (1,031,679 bytes) nonempty verified, 5 refs, tip bdf2c1b fix: stop truncating the laws out of the agent's own
PASS maestro-code           (524,547 bytes) nonempty verified, 3 refs, tip 80896a8 Merge remote-tracking branch 'origin/fix/wal-and-cir
PASS logs                   (3,897,703 bytes) tgz verified
PASS engine-ledger          (37,931,605 bytes) downloaded and non-empty
PASS engine-store-db        (978,134 bytes) downloaded and non-empty
PASS repo-mirror            (72,450,244 bytes) 28 refs, tip 64a9557d Merge remote-tracking branch 'origin/main' into fix
PASS engine-logs            (315,829 bytes) downloaded and non-empty

13/13 prefixes restored from prospector-backup.
```

Fourteen seconds. Every line is a thing that came back off the internet and opened on this
machine. The money database was opened as SQLite and passed an integrity check. The secret
store was decrypted and found to hold 25 secrets — the count, never a value. Both agents'
repositories were cloned and their tips read. The whole prospector repository was cloned and
28 branches came out of it.

## What it looks like when it is not fine

This is the run that mattered. The first time it was ever run, 2026-08-23:

```
11/13 prefixes restored from prospector-backup
FAIL secret-store   no age key at .
FAIL repo-mirror    the bundle cannot be cloned, so it is not a backup (rc=128):
                    error: Could not read 788dca7d2ff81b13301ac38b55069a2ea0e5fa1b
                    fatal: Failed to traverse parents of commit d932e28e
                    fatal: remote did not send all necessary objects
```

`repo-mirror` is the whole source repository — every branch, every commit, the only copy that
does not live inside GitHub. It had been broken for five nights. Fourteen bundles in the
bucket, the newest three each exactly 71,176,969 bytes, and not one of them could be opened.

The backup job never noticed because it checked its own work with `git bundle verify`, which
reads the bundle's header and stops. It exits 0 on a file truncated to 300 bytes. It had
printed *"The bundle contains these 169 refs"* about a file from which zero refs come back.

The cause was that the checkout the backup runs from had quietly become a shallow clone on
18 August. A shallow repository is perfectly healthy from the inside — `git fsck` stayed green
the whole time — and produces bundles that look complete and are not.

Both are now fixed, which is why the run above is green.

## Where the answer goes when nobody is watching

The job runs itself once a day and signs a receipt. Nothing needs to be typed:

```
$ launchctl print gui/501/com.prospector.restore-drill | grep -E 'runs|last exit'
	runs = 1
	last exit code = 0

$ tail -1 ~/Documents/code/prospector/store/restore_drill.log
offsite-backup-restore  PASS  rc=0  14.5s  13/13 prefixes restored from prospector-backup.
```

And the estate's own health audit picks the receipt up, which is what puts it in front of a
person rather than in a log file:

```
$ python3 ~/.hermes/scripts/capability_audit.py
   offsite_restore_drill          last=24s     expected≤24.0h  Prove the offsite backup can be RESTORED, not merely written
                                  └─ 1/1 run(s) of offsite_restore_drill met [exit0]
```

If a night goes by with no green line, that reads as a failure rather than as silence. That is
the point of the whole thing: the old arrangement could not tell the difference between a
backup that worked and a backup that had never run.
