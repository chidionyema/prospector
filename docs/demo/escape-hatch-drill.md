# Demo: the escape hatch drill

The drill answers one question every week: if we had to leave Fly, could we get the store out.
It packs the live store on the Fly VM, pulls it down, restores it, and counts the rows against
the live ledger. It changes nothing on Fly and it does not take production down.

## The transfer now proves its own bytes

`fly ssh sftp get` truncates and exits 0. Measured 2026-08-23: 112,474,776 bytes packed on the
VM, 12,779,520 bytes received, flyctl printed "12779520 bytes written" and returned success.
Two 100 MB control transfers the same day came back byte-exact, so it is intermittent.

`t_pack` in `deploy/targets/fly.sh` now splits the archive into parts, checksums every part on
the VM, refetches any part that does not match, and refuses to produce a file at all if it
cannot. This is that behaviour under test.

### Command

```
.venv/bin/python -m pytest -n 0 -q --no-header \
  tests/unit/test_fly_pack_refuses_a_truncated_export.py
```

### Output, 2026-08-23

```
2 passed, 1 warning in 10.70s
```

The two cases are the two halves of the rule. One truncates a part twice and then serves it
honestly: the export has to recover and come out byte-exact. One truncates it forever: the
export has to abort and leave no file behind, because a file that is present gets read as the
store.

## The same test against the old code

The test is only worth its runtime if it fails on the code it was written for. Swapping in the
version of `deploy/targets/fly.sh` from `origin/main` before the fix and running the same
command:

```
FAILED tests/unit/test_fly_pack_refuses_a_truncated_export.py::test_incident_20260823_a_truncated_part_is_refetched_until_the_export_is_byte_exact
FAILED tests/unit/test_fly_pack_refuses_a_truncated_export.py::test_incident_20260823_an_export_that_cannot_be_completed_leaves_no_file
2 failed, 1 warning in 2.45s
```

Old code fails both, new code passes both.

## What the drill prints when it runs

The pack step now reports what it agreed with the VM about, rather than only that it finished:

```
fly: packed on the VM — 40012474 bytes, sha256 a6b638bab90d8f30862b3745f56f10be5b1a832e4d6ec259632ef057ded927db
fly: 3 parts to fetch
fly: handover.part.002 sha mismatch on attempt 1 (1000000 bytes) — refetching
fly: handover.part.002 sha mismatch on attempt 2 (1000000 bytes) — refetching
fly: exported /tmp/out.tar.gz — 40012474 bytes, sha256 a6b638..., byte-exact against the VM, archive opens
```

That run came from a local harness that reproduces the measured truncation against a real
40,012,474 byte archive. When the truncation does not clear, the same harness gives:

```
fly: handover.part.002 failed 3 attempts; EXPORT ABORTED
t_pack exit code: 1
output file: absent
```

## The completeness check

An archive can open, match its manifest and re-hash 50 sampled rows while still holding a
fraction of the store, if it was packed from a partial volume. The manifest cannot catch that,
because the census inside it is computed at pack time on the VM and describes what was packed.

So the drill counts `/data/store/prospector.jsonl` on the VM and in the restored copy and
compares them:

```
live ledger rows: 148213   restored ledger rows: 148207
complete: 148207/148213 ledger rows, within the 1% the live store drifts during a drill
```

If either count cannot be read, the drill fails and says `NOT PROVED` rather than going green.
