#!/usr/bin/env bash
# Prove the FULL publish loop end-to-end with ZERO prod secrets and no rotation:
#   PASS dossier -> EngineBridge (entitlements -> Stripe TEST price -> content store
#   -> POST /internal/catalog) -> pack LISTED on a locally-booted Store.Api.
#
# Both sides of every key are set here to local throwaway values; content uses the
# CONTENT_LOCAL_DIR dev fallback (the same dir the .NET LocalContentStorage serves from),
# so no R2 credentials are needed. Stripe runs in TEST mode using the key already in .env.
#
# This closes/proves the loop the daemon uses. The prod cutover is then purely:
#   point STORE_API_URL at prod + supply the 3 prod secrets (entitlements, internal, R2).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$(cd "$SCRIPT_DIR/../src" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
API_DIR="$SRC_DIR/Store.Api"
DOSSIER="${1:-$REPO_ROOT/store/dossiers/d9edf535bce2276b.pass.json}"   # a complete PASS pack

PY="${PYTHON:-$REPO_ROOT/.venv/bin/python}"; [ -x "$PY" ] || PY="python3"
[ -f "$DOSSIER" ] || { echo "dossier not found: $DOSSIER"; exit 1; }

# Stripe TEST key from the gitignored .env (unquoted line). Never printed.
STRIPE_KEY="$(grep -E '^STRIPE_API_KEY=' "$REPO_ROOT/.env" | head -1 | cut -d= -f2-)"
[ -n "$STRIPE_KEY" ] || { echo "STRIPE_API_KEY missing from .env"; exit 1; }

# Local throwaway keys — identical on both sides so every fail-closed gate passes.
INTERNAL_KEY="$(openssl rand -hex 32)"
ENTITLEMENTS_KEY="$(openssl rand -hex 32)"

TMP_DIR="$(mktemp -d)"
DB_PATH="$TMP_DIR/proof.db"
CONTENT_DIR="$TMP_DIR/content"
mkdir -p "$CONTENT_DIR"

cleanup() {
  [ -n "${API_PID:-}" ] && kill "$API_PID" 2>/dev/null || true
  lsof -ti tcp:5291 2>/dev/null | xargs -r kill 2>/dev/null || true
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

echo "==> Building Store.Api (Release)"
dotnet build "$API_DIR/Store.Api.csproj" -c Release -v quiet >/dev/null
DLL="$API_DIR/bin/Release/net9.0/Store.Api.dll"
[ -f "$DLL" ] || { echo "DLL not found: $DLL"; exit 1; }

echo "==> Booting Store.Api on :5291 (fresh db, content dir = $CONTENT_DIR)"
(
  cd "$API_DIR"
  ASPNETCORE_ENVIRONMENT=Development \
  ASPNETCORE_URLS="http://localhost:5291" \
  ConnectionStrings__DefaultConnection="Data Source=$DB_PATH" \
  Store__InternalApiKey="$INTERNAL_KEY" \
  Store__EntitlementsApiKey="$ENTITLEMENTS_KEY" \
  Content__LocalDir="$CONTENT_DIR" \
  Stripe__ApiKey="$STRIPE_KEY" \
  Stripe__WebhookSecret="whsec_localproof" \
  payments__active_provider="stripe" \
  dotnet "$DLL" >"$TMP_DIR/api.log" 2>&1
) &
API_PID=$!

echo "==> Waiting for API health"
for i in $(seq 1 60); do
  curl -fsS "http://localhost:5291/catalog" >/dev/null 2>&1 && { echo "    up after ${i}s"; break; }
  kill -0 "$API_PID" 2>/dev/null || { echo "API died. Log:"; tail -40 "$TMP_DIR/api.log"; exit 1; }
  sleep 1
done

BEFORE="$(curl -fsS http://localhost:5291/catalog/stats)"
echo "==> Catalog BEFORE: $BEFORE"

cat > "$TMP_DIR/driver.py" <<'PYEOF'
import json, sys
from prospector.config import load_config
from prospector.models import Candidate, Dossier, Decision
from publish.publish import publish
d = json.load(open(sys.argv[1]))
cand = Candidate.from_dict(d["candidate"])
dossier = Dossier(candidate=cand, decision=Decision.PASS)
cfg = load_config("config.yaml")
print("PUBLISH_RESULT:", json.dumps(publish(dossier, cfg)))
PYEOF

echo "==> Replaying PASS dossier through the real publish chain (EngineBridge)"
set +e
( cd "$REPO_ROOT" && \
  PYTHONPATH="$REPO_ROOT" \
  STORE_API_URL="http://localhost:5291" \
  STORE_INTERNAL_API_KEY="$INTERNAL_KEY" \
  PROSPECTOR_ENTITLEMENTS_API_KEY="$ENTITLEMENTS_KEY" \
  CONTENT_LOCAL_DIR="$CONTENT_DIR" \
  STRIPE_API_KEY="$STRIPE_KEY" \
  PAYMENTS_ACTIVE_PROVIDER="stripe" \
  "$PY" "$TMP_DIR/driver.py" "$DOSSIER" )
RC=$?
set -e

AFTER="$(curl -fsS http://localhost:5291/catalog/stats)"
echo "==> Catalog AFTER:  $AFTER"
echo "==> Content written to store: $(find "$CONTENT_DIR" -type f | sed "s#$CONTENT_DIR/##" | head)"
echo "==> Listed pack on local storefront:"
curl -fsS http://localhost:5291/catalog | "$PY" -c "import json,sys; [print('   -', p.get('id','?')[:12], '|', p.get('title','')) for p in json.load(sys.stdin)]" 2>/dev/null || true

[ "$RC" -eq 0 ] || { echo "driver failed; API log tail:"; tail -20 "$TMP_DIR/api.log"; exit "$RC"; }
echo "==> DONE. If AFTER shows listed:1, the full daemon->site loop is proven locally."
