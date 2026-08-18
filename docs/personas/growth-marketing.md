# The platform for growth and marketing

How anybody finds this thing, what you can change without a deploy, and where the actual bottleneck
is.

## Start with the honest constraint

**The bottleneck is supply, not delivery.** Geo delivery works; supply does not. Only ideas that clear
six hard gates and score above `min_composite_to_pass: 2.5` reach the catalogue, and the historical
PASS rate by lane across 221 tier-tagged dossiers was smb 11.8%, growth 4.9%, side_hustle 4.3%,
venture 0.0%.

Marketing cannot fix that, and pushing traffic at a thin catalogue converts badly. **Facet coverage is
the discovery bottleneck**: what limits browsing is not the number of packs but how few of the
combinations a visitor might filter on have anything behind them.

The founder's steer on this is explicit and it is about supply: **improve generation quality, not the
kill rate.** Loosening the gates would be the fast way to fill the catalogue and it would destroy the
one thing that makes a pack worth money.

## The property to sell

The pitch is not "we have business ideas". It is:

- **Every claim cites a source you can open.** No unsourced numbers ship.
- **The verdicts are made only from passages actually fetched.** No prior knowledge, no confident
  guessing.
- **The kills are published too.** A dossier is rendered for every KILL, not only for passes. The kill
  log is the receipt that the filter is real — and it is the most differentiated asset here. Most
  competitors show you what survived. This shows you what died and why, with citations.
- **Any business, any sector, any scale, same six checks.** No sector cherry-picking.

## The surfaces

| Surface | Where | Changed by |
|---|---|---|
| `mumchimp.com` | `store_platform/src/Store.Web/` | Code change and deploy |
| Pack pages and listing copy | Generated, then linted | Backfill tools, no deploy |
| Share cards / Open Graph | Storefront, bundle-keyed | Regenerate the bundle |
| Catalogue facets | Store API `/catalog` | Depends on what has been published |

## Traps on the storefront that will bite a marketer

| Trap | What happens |
|---|---|
| **The storefront renders no markdown** | Asterisks and backticks appear literally. Copy from a markdown editor looks broken |
| **One-liners have truncated mid-word** | 34 of 63 at one point. Length limits live downstream of where copy is written |
| **A share card carried another product's image** | Bundle keys are content-addressed; a stale key resolved to the wrong bundle |
| **An empty source card** | Is a suppressed duplicate quote, not missing content |
| **An entrance fade makes LCP wait for it** | A tasteful animation directly damages the largest-contentful-paint score |
| **`overflow: hidden` kills every descendant sticky** | One CSS property silently disables a sticky header anywhere below it |
| **A fold test passes locally and fails in CI** | And Playwright at one viewport hides mobile entirely |
| **The API rate-limits its own storefront** | Diagnose a 429 before assuming an attack or a bot |

Two rules from the founder worth internalising before writing anything: **plain words, no clever
constructions**, and **no dashes stacking clauses**. `docs/HOUSE_WRITING_SPEC.md` is the voice, and
`docs/SITE_SPEC_PROGRAM.md` is the design and copy spec — read it before touching the storefront,
because its status kept evaporating between sessions until it was written down.

## What you can measure

- `/catalog/stats` and `/internal/analytics/*` on the store API.
- `store/listings/` — what has actually been published (119 files as last counted).
- `store/shelf_copy_log.jsonl` and `store/retitle_log.jsonl` — the audit trail of copy changes.

**What you cannot measure:** there is no analytics product, no attribution, no funnel instrumentation
between landing and checkout, and no email list. If you need conversion data, that instrumentation is
the first build.

## What is not built

No email marketing, no CRM, no referral mechanism, no SEO tooling, no A/B testing, no content
calendar. The storefront is the whole of the marketing stack.

## What to read next

- [product-manager.md](product-manager.md) — what the product actually is and where it is weak.
- [content-management.md](content-management.md) — how to change the words.
- `docs/SITE_SPEC_PROGRAM.md`, `docs/HOUSE_WRITING_SPEC.md`.
