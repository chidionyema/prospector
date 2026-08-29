#!/usr/bin/env bash
# Can this box actually run the escape hatch? Ask before the outage, not during it.
#
# WHY THIS FILE EXISTS. On 2026-08-23 the whole-stack compose file was run on the laptop for the
# first time since it was written. It did not fail on a service, a secret or a Dockerfile. It
# failed twice on the toolchain:
#
#   validating docker-compose.yml: services.api.env_file.0 must be a string
#   compose build requires buildx 0.17.0 or later
#
# Docker Desktop's bundled plugins were compose 2.19.1 and buildx 0.11.0, both from 2023. The
# compose file's own comment already said it needs compose >= 2.24 and recorded that the laptop
# "was upgraded for this". The upgrade had installed Homebrew's binary and left ~/.docker/
# cli-plugins pointing at Docker Desktop's, so `docker compose` never saw it. A note in a comment
# is not a check, which is the entire lesson.
#
# The escape hatch is the one thing that is only ever run on the worst day of the year. Every
# check below is a thing that was silently wrong on a laptop that looked fine.
#
#   bash deploy/compose/preflight.sh          # exits 0 when this box can run the stack
#
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FAIL=0

say()  { printf '  %-9s %s\n' "$1" "$2"; }
ok()   { say "OK" "$1"; }
bad()  { say "MISSING" "$1"; printf '            fix: %s\n' "$2"; FAIL=1; }

# sort -V is the only version comparison that is right about 2.19.1 vs 2.24.0 and about
# 0.11.0 vs 0.17.0. A string compare says 2.19.1 is the newer one, which is how a stale
# toolchain passes a check that was written to catch it.
atleast() { [ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -1)" = "$2" ]; }

echo "escape hatch preflight"

# 1. A docker daemon that answers. Not `command -v docker`: the CLI is present on a laptop
#    whose VM is not running, and that is the common case on a Mac.
if docker info >/dev/null 2>&1; then
  ok "docker daemon answering ($(docker info --format '{{.ServerVersion}}' 2>/dev/null))"
else
  bad "no docker daemon" "start Docker Desktop, or: colima start"
fi

# 2. Compose >= 2.24, for the `env_file: [{path: ..., required: false}]` mapping form. That form
#    is what lets the stack be PARSED on a rented box before its .env has arrived, which is
#    precisely the situation the escape hatch exists for.
CV="$(docker compose version --short 2>/dev/null | tr -d 'v')"
if [ -n "$CV" ] && atleast "$CV" "2.24.0"; then
  ok "docker compose $CV"
else
  bad "docker compose ${CV:-absent}, need >= 2.24" \
      "brew install docker-compose && ln -sf \"\$(brew --prefix docker-compose)/bin/docker-compose\" ~/.docker/cli-plugins/docker-compose"
fi

# 3. Buildx >= 0.17, which compose 5.x requires to build anything at all.
BV="$(docker buildx version 2>/dev/null | awk '{print $2}' | tr -d 'v')"
if [ -n "$BV" ] && atleast "$BV" "0.17.0"; then
  ok "docker buildx $BV"
else
  bad "docker buildx ${BV:-absent}, need >= 0.17" \
      "brew install docker-buildx && ln -sf \"\$(brew --prefix docker-buildx)/bin/docker-buildx\" ~/.docker/cli-plugins/docker-buildx"
fi

# 4. The addresses file. Absent is not fatal on its own — compose falls back to the defaults
#    baked into the file — but on a laptop those defaults are the production hostnames, and a
#    local stack answering to mumchimp.com is a confusion nobody needs at 3am.
if [ -f "$HERE/stack.env" ]; then
  ok "stack.env present"
else
  bad "no stack.env" "cp deploy/compose/stack.env.example deploy/compose/stack.env"
fi

# 5. Secrets. Optional by design (see the env_file comment in docker-compose.yml): the stack
#    must parse and build without them. Say so rather than staying silent, because "the API
#    started and every payment call 401s" is a worse discovery than this line.
if [ -f "$HERE/../../.env" ]; then
  ok ".env present (secrets will be injected)"
else
  say "NOTE" "no .env — the stack will build and start, but nothing that needs a"
  say ""    "credential will work. That is on purpose; it is not a failure here."
fi

echo
if [ "$FAIL" -eq 0 ]; then
  echo "PASS — this box can run the stack:  docker compose --profile store up -d --build"
else
  echo "FAIL — fix the lines above first. None of them are about the code."
fi
exit "$FAIL"
