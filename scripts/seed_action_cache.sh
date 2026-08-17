#!/usr/bin/env bash
# Seed the self-hosted runners' action archive cache.
#
# Why: the runner deletes _work/_actions at the start of every job, so it re-downloads
# actions/checkout and friends from codeload.github.com on every job. On 2026-08-17 ten PRs
# x seven jobs hit HTTP 429 and every run died before its first step.
#
# The runner reads ACTIONS_RUNNER_ACTION_ARCHIVE_CACHE and copies a tarball out of it instead
# of downloading (actions/runner src/Runner.Worker/ActionManager.cs, the block that builds
# cacheArchiveFile). That cache is READ-ONLY: the runner never writes to it. This script is
# what fills it.
#
# Layout the runner expects on macOS/Linux:
#   $CACHE/<owner>_<repo>/<resolved-sha>.tar.gz
#
# Downloads go through `gh api`, which is authenticated, so seeding does not itself hit the
# anonymous codeload rate limit.
#
# Re-run this whenever a workflow pins a new action or a tag moves. It is idempotent.
set -euo pipefail

CACHE="${ACTIONS_RUNNER_ACTION_ARCHIVE_CACHE:-$HOME/actions-archive-cache}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

mkdir -p "$CACHE"

# Every remote action any workflow uses, as owner/repo@ref. A path inside a repo
# (superfly/flyctl-actions/setup-flyctl) caches under the REPO, not the path.
mapfile -t USES < <(
  grep -hoE 'uses:[[:space:]]*[^[:space:]]+' "$ROOT"/.github/workflows/*.yml "$ROOT"/.github/workflows/*.yaml 2>/dev/null |
    sed -E 's/uses:[[:space:]]*//' |
    grep -v '^\./' |
    sed -E 's#^([^/]+/[^/@]+)(/[^@]*)?@(.+)$#\1@\3#' |
    sort -u
)

if [ "${#USES[@]}" -eq 0 ]; then
  echo "no remote actions found under $ROOT/.github/workflows" >&2
  exit 1
fi

seeded=0
kept=0
for u in "${USES[@]}"; do
  repo="${u%@*}"
  ref="${u#*@}"
  sha="$(gh api "repos/$repo/commits/$ref" --jq .sha)"
  dir="$CACHE/${repo//\//_}"
  out="$dir/$sha.tar.gz"
  if [ -s "$out" ]; then
    echo "kept    $repo@$ref -> ${sha:0:12}"
    kept=$((kept + 1))
    continue
  fi
  mkdir -p "$dir"
  # Build the archive with git rather than `gh api repos/.../tarball`. That endpoint redirects
  # to codeload, which is the host that rate-limited us in the first place, so seeding from it
  # fails exactly when we need it. `git fetch` talks to github.com and has its own budget.
  #
  # The runner requires the tarball to hold exactly ONE top-level directory (ActionManager.cs
  # throws "contains 'N' directories" otherwise), which is what --prefix gives us.
  tmp="$(mktemp -d)"
  git -C "$tmp" init -q
  git -C "$tmp" remote add origin "https://github.com/$repo.git"
  git -C "$tmp" fetch -q --depth 1 origin "$sha"
  git -C "$tmp" archive --format=tar.gz --prefix="${repo##*/}-$sha/" FETCH_HEAD > "$out.part"
  rm -rf "$tmp"
  mv "$out.part" "$out"
  echo "seeded  $repo@$ref -> ${sha:0:12}  $(wc -c < "$out" | tr -d ' ') bytes"
  seeded=$((seeded + 1))
done

echo "cache $CACHE: $seeded seeded, $kept already present"
