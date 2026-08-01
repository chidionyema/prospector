# Storefront Institutional Intelligence Polish

## Goal

Apply the supplied “dossier” visual system to the Mumchimp storefront without changing catalogue, discovery, analytics, cart, checkout, fulfilment, identity, pricing, or copy behavior.

## Scope

Presentation-layer files under `store_platform/src/Store.Web` only:

- `src/styles/globals.css`
- `src/components/ui/Logo.tsx`
- `src/pages/index.tsx`
- `public/icon.svg` (favicon source)
- shared presentational primitives only where needed for visual consistency

## Design contract

1. Global tokens:
   - page `#F8FAFC`; surface `#FFFFFF`; text `#0F172A`; muted `#64748B`; border `#E2E8F0`
   - primary/accent `#042F2E`; primary hover `#022C22`
   - verified background `#ECFDF5`; verified text `#065F46`
   - UI font Inter/Geist-compatible sans; metadata/data font Roboto Mono-compatible monospace
   - H1 48px desktop / 36px mobile, weight 700, line-height 1.1, tracking -0.02em
   - H2 24px, weight 600, line-height 1.3
   - body 16px / 1.6; metadata 13px / 500
2. Catalogue blueprint cards:
   - white, 1px border, 8px radius, 24px content padding, 16px grid gap
   - hover: `translateY(-2px)` and `0 10px 15px -3px rgba(15, 23, 42, 0.08)`
   - preserve semantic links, headings, price, source/survival metadata, and cart interaction
3. Primary CTAs:
   - `#042F2E`, white, 14px/500, 12px 24px, 6px radius; hover `#022C22`
4. Wordmark:
   - typographic only, one word: `Mum` text color, `chimp` muted, teal period
   - weight 800; accessible name remains `Mumchimp`
   - dark-ground variant remains legible
5. Favicon:
   - white `M` in a square `#042F2E` field; no monkey/chimp imagery
6. Layout:
   - principal content remains bounded at no more than 1200px
   - desktop catalogue sidebar is 280px, sticky, with 24px top offset
   - mobile collapsed-filter behavior remains unchanged
7. Accessibility:
   - preserve focus-visible treatment, reduced-motion-safe behavior, semantic heading order, and contrast

## Acceptance

- New static design-contract test fails before implementation and passes afterward.
- `npm test`, `npm run verify`, and `npm run build` exit 0 in `store_platform/src/Store.Web`.
- No money, API, data, identity, migration, or product-truth files change.
