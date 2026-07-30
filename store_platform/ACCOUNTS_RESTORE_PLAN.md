# Accounts + Social Login — Restore Plan

**Status:** approved direction (user chose "restore accounts + social login", 2026-06-19). Not yet built.
**Why this exists:** the storefront was repurposed from a prior product "TIE" that had full accounts +
social login. During the repurpose the auth *backend* was dropped and the FE auth was stubbed, then the
last components were deleted **silently inside an unrelated logo commit** (`d98c38b`). This doc is the
deliberate, documented decision + build plan that should have existed then. A CI guard (`.protected-paths`
+ `scripts/guard_protected_deletions.py`) now makes silent deletion of identity/money/moat files
un-mergeable.

This is identity + money-adjacent (founder fence): correctness and security over speed. Recommended to
build in a fresh, escalated session.

---

## Current state confirmed (grounded in repo)

- **Migrations:** EF Core migrations (NOT EnsureCreated). `Program.cs` runs `db.Database.MigrateAsync()`
  at startup. Migrations in `store_platform/src/Store.Catalog/Migrations/`. A Users table = a NEW
  migration scaffolded against `StoreDbContext`; money tables must get zero diff.
- **ASP.NET auth:** none. No `AddAuthentication/Authorization`, no `UseAuthentication`. Existing
  protection is hand-rolled fixed-time key compare (`/internal/catalog`, `/entitlements`). The recovered
  FE's "RLS-enforced" assumption is FALSE on sqlite — authorization must be explicit server-side checks.
- **Entitlements:** `Entitlement{BuyerEmail, GrantToken(unique), PackId, Status, ContentKey...}`,
  `Order{BuyerEmail, ...}`. Download authority = opaque `GrantToken` → `/download/{token}` (.NET redirect
  to 5-min presigned R2 URL). `BuyerEmail` (provider-attested) is the natural join key for "my purchases".
- **FE shell partly survives:** `client.ts` has stubs (authApi/externalAuthApi/accountApi/setAccessToken/
  setOnUnauthorized); `types.ts` has TIE-shaped `UserAndProfile`/`ExternalProvider` (trim, don't invent).
  `AuthContext.tsx`, `SocialSignIn.tsx`, `useProtectedRoute.ts` recover cleanly from `d98c38b~1`.
  **Do NOT restore `ModeContext.tsx`** (TIE seeker/connector role logic, irrelevant).
- **Tests:** `Store.Tests` xUnit, no WebApplicationFactory; service tests use real in-memory sqlite
  (`:memory:` + EnsureCreated) so unique indexes enforce. No web tests exist.

## Decisions (recommended defaults — adjustable)

1. **Auth ownership → .NET-native.** ASP.NET Core auth; API issues its own session. Use built-in OAuth
   handler for the Google handshake only, then mint our own session. Identity stays in Store.Api/sqlite
   alongside entitlements (founder fence). Hosted IdP (Clerk/Auth0/Supabase) rejected: externalizes
   identity + splits authz from entitlements.
2. **Session → httpOnly + Secure + SameSite=Lax cookie** issued by the API. Drop the old in-memory-JWT
   design (built for a cross-origin SPA). Cookie = XSS-safe; close CSRF with SameSite + CSRF token on
   mutations + existing CORS allowlist. FE: `setAccessToken` ~no-op, all auth fetches `credentials:'include'`.
3. **Providers → Google only first.** Apple (paid + key rotation) and GitHub (wrong audience) deferred.
   Endpoints to satisfy the existing FE contract: `GET /external-auth/providers` (only-configured),
   `GET /external-auth/challenge?provider&redirectUrl` (state+PKCE → Google), OAuth callback (verify
   `email_verified`, upsert user, set cookie, 302 to validated redirectUrl=`/auth/callback`),
   `GET /auth/me`, `POST /auth/logout`, `GET/PUT/DELETE /account`, `POST /account/accept-tos`.
   Password login deferred (Phase 5).
4. **Account ↔ purchases → match `Entitlement.BuyerEmail == verified session email`, server-side.**
   Authed `GET /account/orders` returns past purchases + the EXISTING `downloadPath` (reuse proven
   `/download/{token}`, no new download authority, no token reissue). Guest checkout 100% unchanged.
   Only link when provider `email_verified==true` AND equals (normalized) `BuyerEmail`.
5. **Data model:** `User{Id, Email(unique, lower), EmailVerified, CreatedAt, TosVersion, TosAcceptedAt}`,
   `ExternalLogin{Id, UserId(FK), Provider, ProviderKey, unique(Provider,ProviderKey)}`. Start with
   stateless signed-cookie sessions (no session table); add `UserSession` only if "log out all devices"
   is needed. Scaffold: `dotnet ef migrations add AddUsersAndExternalLogins --project Store.Catalog
   --startup-project Store.Api`. Verify money tables get zero diff.
6. **Security checklist:** OAuth `state` + PKCE; redirect-URI allowlist (reuse `Store:AllowedOrigin`/
   `Store:PublicUrl`, no open redirect); httpOnly/Secure/SameSite cookie, no token in localStorage, CSRF
   token on mutations; session expiry + sliding renewal; email-verification trust anchor; tighter per-IP
   rate-limit partition for `/auth*` + `/external-auth*` (extend the existing limiter, keep webhooks
   exempt); explicit authz on every account/download endpoint (replaces the never-existent RLS).

## Phased build (each phase independently shippable; guest checkout never breaks; money path read-only)

- **Phase 0 — auth pipeline skeleton (0.5d):** `AddAuthentication().AddCookie()` + `AddAuthorization()`
  + `UseAuthentication/UseAuthorization` (after UseRateLimiter, CORS first). New `Store.Api/Auth/
  AuthEndpoints.cs`: `/auth/me`→401, `/auth/logout`. Uncomment `^store_platform/src/Store\.Api/Auth/` in
  `.protected-paths`. Risk: middleware ordering.
- **Phase 1 — user schema + migration (0.5d):** `User.cs`, `ExternalLogin.cs` in `Store.Catalog/Domain`,
  DbSets + OnModelCreating, scaffold `AddUsersAndExternalLogins`. Test unique-email via `:memory:` sqlite.
- **Phase 2 — Google OAuth + session (2d, RISKIEST):** Google handler (PKCE+state, config-gated like R2/
  MoneyRailConfigGate). `ExternalAuthEndpoints.cs`: providers / challenge (redirect allowlist) / callback
  (verify email_verified, idempotent upsert on unique (Provider,ProviderKey), set cookie, 302). Tighter
  rate-limit partition. Tests: provider filter, redirect allowlist rejects foreign host, unverified email
  rejected. **Concentrate review here: open-redirect, unverified-email trust, duplicate-account race.**
- **Phase 3 — FE un-stub + restore + pages (2d):** real fetch impls in `client.ts` (`credentials:'include'`);
  trim `UserAndProfile`; restore AuthContext/SocialSignIn/useProtectedRoute from `d98c38b~1` (fix stale
  RLS/in-memory-token comments); new pages `/login`, `/auth/callback`, `/account`; wrap `_app.tsx` in
  `<AuthProvider>`; header account entry-point. Uncomment the 3 FE lines in `.protected-paths`.
- **Phase 4 — order history + re-download (1d):** authed `GET /account/orders` (read-only, filter by
  verified email), `accountApi` backed by `/account*`, FE account page lists orders + "Download again".
  Tests: matching email surfaces, non-matching never leaks, guest magic-link unchanged.
- **Phase 5 — (optional) password auth + deletion polish (1.5d):** only if wanted; never cascade delete
  into `SalesAudit`/`Order` (anonymize).

**Total ~6 days (~5.5 without passwords). Riskiest = Phase 2 OAuth callback.**

## Guard sync (do as files land)
Uncomment the matching identity entries in `/.protected-paths` as each auth file is created, so it can
never be silently deleted again (the whole reason this plan exists).
