# Checkpoint — 2026-06-20 (session complete)

## Status: ✅ Deployment Build Hardening Completed & Proven on Fly

**1 commit added on `launch-hardening-2026-06-18`**:
```
a20d9e0 fix(deploy): fix fly.toml paths, add migrations .editorconfig, and rename kernel references
```

## What was built & fixed
- **Fly configuration fixes**:
  - `store_platform/deploy/fly/api.fly.toml`: Pointed `[build].dockerfile` to `../../src/Store.Api/Dockerfile` to resolve correctly relative to the config file's directory.
  - `store_platform/deploy/fly/web.fly.toml`: Pointed `[build].dockerfile` to `../../src/Store.Web/Dockerfile` to resolve correctly relative to the config file's directory.
- **Migration Analyzer Bypass**:
  - `store_platform/src/Store.Catalog/Migrations/.editorconfig`: Explicitly marks EF-generated migration files as generated and disables Meziantou/Sonar style rules inside this directory. This prevents cold Docker builds from failing on style warnings treated as errors.
- **Kernel Renaming & Venv Test execution**:
  - Refactored all references to "Keystone" kernel to "Crux" to match the actual packages.
  - Updated `tests/control_center/test_runner.py` to use `sys.executable` to run tests on the active python venv interpreter.
- **Fly Apps Created**:
  - Created the missing `prospector-store-web` app on the personal organization using `flyctl apps create`.

## Verification & Real Build Proofs
- **Python Tests**: `.venv/bin/python -m pytest -q` → **404 passed, 3 skipped** ✅
- **C# Tests**: `dotnet test Store.Tests/Store.Tests.csproj` → **61 passed, 0 failed** ✅
- **API Remote Build**: `flyctl deploy . --config deploy/fly/api.fly.toml --build-only --remote-only` from `store_platform/` completes successfully via Fly's Depot builder and generates the registry image. ✅
- **Web Remote Build**: `flyctl deploy . --config ../../deploy/fly/web.fly.toml --build-only --remote-only --build-arg NEXT_PUBLIC_API_URL=https://prospector-store-api.fly.dev` from `store_platform/src/Store.Web` completes successfully and compiles page output under alpine-node. ✅

## Next Steps
- Run the actual app deployments (now that the remote builds are proven regression-clean and fully compile):
  1. Set up Fly secrets (`fly secrets set ...`) using production keys per [PROD_DEPLOY.md](file:///Users/chidionyema/documents/code/prospector/store_platform/deploy/PROD_DEPLOY.md).
  2. Provision a volume for `store.db` on the API app.
  3. Deploy the apps live to Fly:
     - API: `fly deploy . --config deploy/fly/api.fly.toml`
     - Web: `fly deploy . --config ../../deploy/fly/web.fly.toml --build-arg NEXT_PUBLIC_API_URL=https://<your-deployed-api-slug>.fly.dev`
