import React from 'react';
import { type Currency } from '@/lib/fx';

/**
 * The visitor's display currency, made ambient.
 *
 * WHY A CONTEXT AND NOT A PROP
 *
 * Currency is a per-REQUEST fact (derived from `Fly-Client-Country` in `getServerSideProps`),
 * not a per-component one, and threading it down as a prop is how you end up with most of a page
 * right and the rest wrong. That is not hypothetical -- it is what was measured on the served
 * production build on 2026-08-05, `GET /pack/8d5e24fbe6c1f5d3` with `Fly-Client-Country: US`,
 * after the fold had already been fixed by prop-threading:
 *
 *   Unlock this pack · $62.23   Charged £49 GBP...        <- fold, threaded, correct
 *   ...6 / 6 · 33 sources · Verified 3 days ago  £49      <- related rail, not threaded
 *   ...6 / 6 · 29 sources · Verified 3 days ago  £49
 *   ...6 / 6 · 48 sources · Verified 4 days ago  £49
 *
 * Three cards on the same page quoting a different currency from the price six inches above
 * them. Every one of those cards renders `<DossierCard pack={...} />` through an intermediary
 * (`SimilarPacks`, `PackGrid`) that has no reason to know about money, so a prop would have to be
 * added to each of them, and to the next such intermediary anyone writes.
 *
 * A context cannot be forgotten by an intermediary, only by the page -- and there is exactly one
 * place a page sets it (`_app.tsx`, from `pageProps.currency`), so "did this page set it?" is one
 * grep rather than an audit of the component tree.
 *
 * THE DEFAULT IS GBP AND THAT IS DELIBERATE
 *
 * GBP is the catalogue's source currency and the amount actually charged. A surface rendered
 * outside a provider therefore degrades to the TRUE number, never to a stale conversion.
 */
const CurrencyContext = React.createContext<Currency>('GBP');

export function CurrencyProvider({
  currency = 'GBP',
  children,
}: {
  currency?: Currency;
  children: React.ReactNode;
}) {
  return <CurrencyContext.Provider value={currency}>{children}</CurrencyContext.Provider>;
}

/** The visitor's display currency. `'GBP'` outside a provider. */
export function useCurrency(): Currency {
  return React.useContext(CurrencyContext);
}
