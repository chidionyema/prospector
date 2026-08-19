#!/bin/bash
# One memory store for the whole prospector estate, instead of one per checkout.
#
# THE MEASUREMENT THAT PRODUCED THIS. Claude Code keeps agent memory in
# ~/.claude/projects/<cwd-slug>/memory/, one directory per working directory. This estate has
# three prospector checkouts and about thirty-five worktrees, so it has that many slugs.
# Counted 2026-08-19:
#
#     390 files   -Users-chidionyema-Documents-code-prospector
#      13 files   -Users-chidionyema-Library-...-CloudDocs-Documents-code-prospector
#       1 file    prospector
#       0 files   every worktree slug
#
# Overlap between the first two: MEMORY.md and nothing else. A session started in the iCloud
# checkout, or in any worktree, could see at most 13 of 391 lessons. The other 378 were written,
# indexed, and invisible.
#
# That is not a theory about what might go wrong. On 2026-08-19 two sessions hit the same trap
# on the same day -- CI runs on the Fly app prospector-ci, not on this Mac -- and each wrote its
# own memory file about it, in its own directory, neither able to see the other's:
# ci-runs-on-fly-not-this-mac.md and ci-runners-live-on-fly.md.
#
# WHAT THIS DOES. Copies every prospector memory store into ~/.claude/memory/prospector, merges
# the MEMORY.md index line by line, and replaces each per-slug directory with a symlink to the
# shared store. After that, a lesson written in any checkout is readable in every checkout.
#
# It is SAFE to re-run. Nothing is deleted: each original directory is renamed
# memory.pre-share-<timestamp> and left in place. Files are copied with `cp -n`, so a store that
# is already shared gains nothing and loses nothing.
#
#   bash ops/share_memory.sh --check     report the partition, change nothing (the default)
#   bash ops/share_memory.sh --apply     merge and link
set -u

SHARED="$HOME/.claude/memory/prospector"
PROJECTS="$HOME/.claude/projects"
MODE="${1:---check}"

# Which slugs belong to this estate. A worktree slug is included so a fresh worktree opens with
# the estate's memory instead of an empty directory. Other products keep their own memory: this
# shares the prospector family only.
slugs() {
  find "$PROJECTS" -maxdepth 1 -type d \
    \( -name '*code-prospector' -o -name '*code-wt-*' -o -name 'prospector' \) 2>/dev/null \
    | grep -v -- '-private-'
}

count() { ls "$1"/*.md 2>/dev/null | wc -l | tr -d ' '; }

if [ "$MODE" = "--check" ]; then
  echo "shared store: $SHARED ($(count "$SHARED") files)"
  linked=0; unlinked=0
  while IFS= read -r d; do
    m="$d/memory"
    [ -e "$m" ] || continue
    if [ -L "$m" ]; then
      linked=$((linked + 1))
    else
      unlinked=$((unlinked + 1))
      echo "  NOT SHARED  $(count "$m") files  $(basename "$d")"
    fi
  done < <(slugs)
  echo "$linked slug(s) share the store, $unlinked do not."
  [ "$unlinked" -eq 0 ] || echo "Run: bash ops/share_memory.sh --apply"
  exit 0
fi

if [ "$MODE" != "--apply" ]; then
  echo "usage: bash ops/share_memory.sh [--check|--apply]" >&2
  exit 2
fi

STAMP=$(date +%Y%m%d-%H%M%S)
mkdir -p "$SHARED"

# Copy the memories in. -n never overwrites, so a name that exists in two stores keeps the copy
# already shared and the other is preserved in that store's backup directory.
while IFS= read -r d; do
  m="$d/memory"
  [ -d "$m" ] && [ ! -L "$m" ] || continue
  cp -n "$m"/*.md "$SHARED"/ 2>/dev/null
done < <(slugs)

# MEMORY.md is the index every session loads, one line per memory. Each store has its own, so
# they are merged line by line rather than one winning: a dropped pointer is a memory nobody
# finds again.
python3 - "$SHARED" $(slugs) <<'PY'
import pathlib, sys
shared = pathlib.Path(sys.argv[1])
lines, seen = [], set()
for src in [shared, *[pathlib.Path(d) / "memory" for d in sys.argv[2:]]]:
    f = src / "MEMORY.md"
    if not f.exists():
        continue
    for ln in f.read_text(encoding="utf-8", errors="replace").splitlines():
        key = ln.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        lines.append(ln)
(shared / "MEMORY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"MEMORY.md merged: {len(lines)} pointer lines")
PY

while IFS= read -r d; do
  m="$d/memory"
  if [ -L "$m" ]; then continue; fi
  [ -e "$m" ] && mv "$m" "$m.pre-share-$STAMP"
  ln -s "$SHARED" "$m"
  echo "linked $(basename "$d")/memory -> $SHARED"
done < <(slugs)

echo "shared store now holds $(count "$SHARED") files."
echo "Originals kept as memory.pre-share-$STAMP in each project directory; nothing was deleted."
