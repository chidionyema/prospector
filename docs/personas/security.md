# The platform for security

Blast radius, where the secrets are, and who can reach what.

## The single most important rule in this estate

**A CI runner must never hold the money keys.**

The runners execute code from every pull request, including one an outsider opened. Only two secrets
are pushed to the runner app: `GITHUB_RUNNER_PAT` and `RUNNER_LABELS`. Nothing else, ever.

The PAT itself is scoped down to the minimum that lets a runner register: fine-grained, **Only select
repositories → prospector**, **Repository → Administration → Read and write**, and nothing else.

A related handling rule, learned the hard way: **minting a token with `&&` prints it in full.**
`gh ... create && gh secret set ...` echoes the token to the terminal and stores nothing. Pipe it.

## Where secrets live

| Location | Contents |
|---|---|
| Fly app secrets | engine 14, store-api 24, hermes 29, store-web 0, searxng 0 |
| `.env` in the main checkout | Model provider keys. The live checkout **symlinks** to it |
| `.lux/keys/agent.pem` | Commit-gate signing key. Untracked, and symlinked into worktrees |
| `~/.config/prospector/age-key.txt` | Encryption key. **No copy exists off this laptop** |
| GitHub repo secrets | CI and deploy tokens, including `FLY_API_TOKEN_ENGINE` |

`scripts/estate_map.py` prints secret **names** only, never values. A name tells you what an app needs
in order to run somewhere else; a value is a leak. That distinction is what makes the inventory safe
to keep in a document.

**Git does not carry secrets, and that is a live trap rather than a policy.** When the engine moved to
Fly, the new checkout had no `.env`, so every MiniMax tier benched immediately with
`All operators unavailable — check API keys and credentials`. The key file was simply not there. The
symlinks and the probe that checks both exist because of that morning.

## The trust boundaries

**Public, unauthenticated.**

- `mumchimp.com` — the storefront.
- `api.mumchimp.com/catalog`, `/catalog/{id}`, `/catalog/stats` — the catalogue.
- `/checkout`, `/packs/{id}/checkout` — creates a Stripe session.
- `/webhooks/{provider}` — called by Stripe. Signature-verified.
- `/orders/{token}`, `/download/{token}` — **bearer-token by design.**

**The accountless model is a deliberate security posture, and it has a specific shape.** There are no
passwords and no accounts to breach. What replaces them is an unguessable token in a link. The token
is the entitlement: anyone holding it can download. That trades credential-stuffing risk for
link-sharing risk, which for research packs is the right trade, but it must be understood rather than
discovered.

**Internal.** `/internal/ops/*`, `/internal/analytics/*`, `/internal/catalog/{id}/content`,
`/internal/catalog/{id}/price-history`, and `/v1/founder/*`. These carry the interesting data and
must not be reachable without their key (`config.yaml entitlements_api_key` and the store API's own
configuration).

**The ops console.** Session-gated, served by the engine. One route is deliberately open:
`GET /api/ops/where`, which returns an app name, a machine id and a region. It carries no secret, and
the operator most in need of knowing which estate they are about to sign into is the one still
looking at the login screen.

## Blast radius by component

| If compromised | Reach |
|---|---|
| A CI runner | The repository, via the PAT. **Not** Stripe, not the store, not model keys |
| `prospector-store-api` | Orders, entitlements, the catalogue, and the Stripe key. **The worst case** |
| `prospector-engine` | Model keys, the pipeline, and the ops console |
| `prospector-hermes` | The operator surface. 29 secrets, the largest single holding |
| The laptop | Everything. `.env`, the age key, the canonical store, and all four runners |

**The laptop is still the largest concentration of risk in the estate.** That is the security reason
for the migration, independent of the availability reason.

## Controls that exist

- **A tool that reaches off this machine is labelled `external`** in the console catalogue, and its
  preview says undo covers the local half only. Blast radius is surfaced before the action, not after.
- **Every console action needs a preview and a confirmation token.**
- **`scripts/guard_protected_deletions.py`** runs as a required CI check, so a protected file cannot
  vanish quietly in a diff.
- **Refused actions name their reason.** `catalogue.set_price` is refused because it would drift from
  Stripe.
- **`prospector/bridge.py`** makes price-and-Stripe a single write, so no path exists to charge a
  buyer one number and record another.
- **The API rate-limits its own storefront** — worth knowing before you diagnose a 429 as an attack.

## Gaps, stated plainly

1. **`~/.config/prospector/age-key.txt` has no off-machine copy.** Single point of total loss.
2. **No secret rotation process.** Nothing tracks age or forces a change.
3. **No audit log of who ran what** beyond the console's own action trail and `store/scheduler/audit`.
4. **No dependency scanning or SBOM.** No Dependabot equivalent in the CI jobs.
5. **The canonical store sits on an iCloud-synced path** — data at rest in a consumer sync service.
6. **The runners are still on the laptop** (R8), which is the reason rule one at the top of this page
   is currently carried by discipline as well as by configuration.

## What to read next

- [legal-privacy.md](legal-privacy.md) — what personal data is actually held.
- [ESTATE_MAP.md](../ESTATE_MAP.md) §7 secrets, §8 laptop dependencies.
- `docs/CI_RUNNER.md`.
