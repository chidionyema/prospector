#!/bin/sh
# The weekly drill, both halves: the LOCAL snapshot and the OFFSITE copy.
#
# WHY THIS FILE EXISTS. `scripts/restore_drill.py` with no --backup snapshots the live store and
# restores that snapshot. It is a real test of the drill's own machinery and it proves nothing at
# all about R2, because it never opens the bucket. Measured 2026-08-20, that is exactly what
# supervisord had been running weekly since the Fly cutover -- so the offsite copy, the only thing
# that survives losing the machine, had never been tested by anything automatic. M4 of
# docs/MIGRATION_AND_DR_PROGRAM.md says every backup is a hypothesis until one is restored; the
# local half cannot retire that sentence and the offsite half can.
#
# Keeping BOTH is deliberate, not caution. They fail differently, which is the only reason two
# checks are worth more than one. The local half still runs when the network is the outage --
# restore_drill.py:49 makes that its stated design -- and the offsite half is the only one that
# would notice R2 quietly holding nothing.
#
# The two halves already fit with no glue: `backup_store.py --restore DEST` writes DEST/dossiers/...
# and DEST/prospector.db, and the drill reads exactly DOSSIER_DIRNAME="dossiers" and
# DB_NAME="prospector.db" (restore_drill.py:81-82).
#
# NO `set -e`. Both halves run on every pass even when the first one fails, because a drill that
# stops at the first red tells you the state of one thing and hides the other. The exit code is
# non-zero if EITHER half failed, so the receipt goes red either way.
set -u

DEST="${OFFSITE_DRILL_DIR:-/data/store/tmp/offsite_drill}"
# The pull is ~250 MB against 18 GB free, measured 2026-08-20. It still goes on every exit path:
# a drill that fills the disk it is protecting has become the outage it was watching for.
cleanup() { rm -rf "$DEST"; }
trap cleanup EXIT INT TERM

echo "[drill] half 1 of 2 — the local snapshot (no network)"
python scripts/restore_drill.py
LOCAL_RC=$?

echo "[drill] half 2 of 2 — the offsite copy in R2"
rm -rf "$DEST" && mkdir -p "$DEST"
# Does R2 still hold the bytes we gave it? An ETag mismatch is the only thing that fails here,
# and that is deliberate: see backup_store.restore's docstring for why the other two checks
# report instead. A restore that can never finish cannot report a real failure.
python scripts/backup_store.py --restore "$DEST"
PULL_RC=$?
if [ "$PULL_RC" -eq 0 ]; then
    # And is the catalogue actually recoverable from those bytes? Coverage, index-vs-tree,
    # db integrity, and sampled rows parsed and matched against the source.
    python scripts/restore_drill.py --backup "$DEST"
    OFFSITE_RC=$?
else
    echo "[drill] the R2 pull failed, so there is nothing to grade offsite" >&2
    OFFSITE_RC="$PULL_RC"
fi

echo "[drill] local=$LOCAL_RC offsite=$OFFSITE_RC"
[ "$LOCAL_RC" -eq 0 ] && [ "$OFFSITE_RC" -eq 0 ]
