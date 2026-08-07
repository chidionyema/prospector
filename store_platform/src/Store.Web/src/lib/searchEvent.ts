/**
 * The window event that opens the catalogue's command palette from outside its React tree.
 *
 * It lives in its own module rather than in `CommandPalette.tsx` on purpose. `MarketingLayout`
 * renders on every marketing page and needs this constant to wire the header's search button;
 * importing it from `CommandPalette` would pull the palette, its fuzzy matcher and its row
 * renderers into the bundle of every page that has no catalogue to search.
 *
 * Exported as a constant, never written out as a string literal at either end: a typo in an event
 * name fails silently in both directions -- the dispatcher throws nothing and the listener simply
 * never fires -- so the only defence is that there is one spelling of it.
 */
export const SEARCH_OPEN_EVENT = 'mumchimp:search';
