#!/usr/bin/env bash
# Ship our own metasearch to Fly. Run from the repo root, or from anywhere: it cd's itself.
#
# The build context is the REPO ROOT, not this directory, on purpose. The image reuses
# searxng/settings.yml — the very same file the laptop container runs — so the two hosts cannot
# drift into searching different engines. A second copy of that file under deploy/ would be the
# usual way this breaks: one gets an engine enabled and the other does not, and the difference
# only shows up as a coverage number nobody can explain.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APP="${PROSPECTOR_SEARXNG_APP:-prospector-searxng}"
cd "$ROOT"
[ -f searxng/settings.yml ] || { echo "no searxng/settings.yml at $ROOT" >&2; exit 1; }
flyctl deploy . --config deploy/searxng/fly.toml --dockerfile deploy/searxng/Dockerfile \
  --app "$APP" --remote-only --ha=false --yes
echo "deployed $APP (private only, reachable at http://$APP.internal:8080)"
