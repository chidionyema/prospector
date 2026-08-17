#!/usr/bin/env bash
# Build every wheel CI needs, once, into the shared uv cache the runners read.
#
# Why this exists: this box is an Intel Mac running Python 3.14, and several dependencies
# publish no wheel for that pair. uv builds them from source with rustc. A source build that
# does not finish inside the job's timeout is never cached, so the next job starts the same
# build from scratch and is killed at the same point. That deadlock is why no CI run went green
# between 2026-08-16 and 2026-08-17: run 32038516212 spent 12m45s in `uv pip install` and was
# cancelled with rustc still running.
#
# Running this once breaks the deadlock. It has no timeout, so the build completes and lands in
# the cache, and every job afterwards installs from it.
#
# Run it after changing requirements.txt or the Python version. It is idempotent and cheap when
# the cache is already warm.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# The same directory the workflow gives the runners, via the repo variable CI_UV_CACHE_DIR.
# Keep the two in step: `gh variable set CI_UV_CACHE_DIR --body <path>`.
export UV_CACHE_DIR="${CI_UV_CACHE_DIR:-$HOME/.cache/uv-ci}"

PYV="$(grep -m1 'PYTHON_VERSION:' .github/workflows/ci.yml | sed -E 's/.*: *.?([0-9.]+).?/\1/')"
if [ -z "$PYV" ]; then
  echo "could not read PYTHON_VERSION from .github/workflows/ci.yml" >&2
  exit 1
fi

UV="$(command -v uv || true)"
if [ -z "$UV" ]; then
  echo "uv is not on PATH. Install it: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  exit 1
fi

mkdir -p "$UV_CACHE_DIR"
echo "warming $UV_CACHE_DIR for Python $PYV"

# A throwaway venv. Only the cache it fills is wanted; the venv itself is discarded.
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
"$UV" venv --python "$PYV" "$tmp/venv" >/dev/null
VIRTUAL_ENV="$tmp/venv" "$UV" pip install -r requirements.txt

echo "cache warm: $(du -sh "$UV_CACHE_DIR" | cut -f1) in $UV_CACHE_DIR"
