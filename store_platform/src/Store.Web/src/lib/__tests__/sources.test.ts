import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import { CITED_FIGURES, citedFigure } from '../sources';

/**
 * Source-or-die, pointed at ourselves.
 *
 * The engine refuses to publish a pack whose claims lack a retrievable source, and the storefront
 * that sells that refusal shipped "Typically $300 to $1,000 a year", a price for somebody else's
 * product, from nowhere, hedged rather than sourced. The hedge is the tell: it is what you write
 * when you know the number is unbacked and want to keep it anyway.
 *
 * The rule these tests enforce draws the line at whose money it is:
 *
 *   £ , our price. We set it, so there is nothing to cite.
 *   $ €, someone else's price. It is a claim about the world and must come from `sources.ts`.
 *
 * That is why the scan below is not "no currency in the copy". It is narrower and, I think,
 * exactly right: a figure we invented needs no source, and a figure we observed always does.
 */
const HERE = new URL('.', import.meta.url);
const MARKETING_PAGES = ['../../pages/index.tsx'];

describe('every cited figure is complete enough to check', () => {
  it.each([...CITED_FIGURES])('$id carries publisher, url and date', (source) => {
    expect(source.figure.trim().length, 'figure').toBeGreaterThan(0);
    expect(source.of.trim().length, 'what the figure is a price of').toBeGreaterThan(0);
    expect(source.publisher.trim().length, 'publisher').toBeGreaterThan(0);
    expect(source.url, 'url must be https').toMatch(/^https:\/\//);
    expect(source.checkedOn, 'checkedOn must be ISO yyyy-mm-dd').toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(Number.isNaN(Date.parse(source.checkedOn)), 'checkedOn must parse').toBe(false);
    if (source.publishedOn) {
      expect(Number.isNaN(Date.parse(source.publishedOn)), 'publishedOn must parse').toBe(false);
    }
  });

  it('cites primary sources, never a site earning a referral on the answer', () => {
    // Affiliate review pages carry these prices too, and they are the easy fetch when the
    // vendor's own page rate-limits, which is exactly what happened on 2026-08-01. A price
    // sourced to a page paid to recommend the product is not sourced.
    const SECONDARY = /(?:^|\.)(?:toolsurf|tipsonblogging|g2|capterra|aipure|swipefile|maxaeo|preuve)\./;
    for (const source of CITED_FIGURES) {
      const host = new URL(source.url).hostname;
      expect(SECONDARY.test(host), `${source.id} cites the reseller ${host}`).toBe(false);
    }
  });

  it('throws on an unknown id rather than rendering an empty price', () => {
    expect(() => citedFigure('no-such-figure')).toThrow(/Unknown cited figure/);
    // Guards the registry against two rows quietly claiming the same key.
    expect(new Set(CITED_FIGURES.map((s) => s.id)).size).toBe(CITED_FIGURES.length);
  });
});

describe('no unsourced price can reappear in the marketing copy', () => {
  it.each(MARKETING_PAGES)('%s prints no bare $ or € figure', (page) => {
    const source = readFileSync(fileURLToPath(new URL(page, HERE)), 'utf8');

    // Comments are stripped first, deliberately. The doc comment on `ComparisonBlock` quotes the
    // exact string this test exists to keep out, because a fix whose reason is deleted grows back
    //, and a test that forbade naming the old bug would force us to delete the reason.
    const code = source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');

    const offenders = [...code.matchAll(/.{0,60}[$€]\s?\d[\d,.]*.{0,30}/g)].map((m) => m[0].trim());
    expect(
      offenders,
      'a $ or € figure is somebody else’s price, route it through lib/sources.ts',
    ).toEqual([]);
  });

  it('the specific unsourced range that shipped is gone', () => {
    const source = readFileSync(fileURLToPath(new URL(MARKETING_PAGES[0], HERE)), 'utf8');
    const code = source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
    expect(code).not.toMatch(/Typically \$300 to \$1,000 a year/);
  });
});

describe('the free sample is not gated behind the capture', () => {
  // The brief asked for the gate. It was declined because the page says "No payment, no email"
  // two lines above the form, and the two cannot both be true. This test is what stops that
  // becoming a lie later by accident: the promise and the open door are asserted together, so
  // gating the sample fails here rather than in a buyer's browser.
  const source = readFileSync(fileURLToPath(new URL(MARKETING_PAGES[0], HERE)), 'utf8');

  it('keeps the promise it makes next to the sample button', () => {
    expect(source).toContain('No payment, no email.');
  });

  it('keeps /sample reachable as a plain link', () => {
    expect(source).toMatch(/href="\/sample"/);
  });

  it('puts nothing between the reader and the sample link', () => {
    // This replaces two assertions that pinned the WRONG artifact. They required a
    // `<WaitlistForm source="home-after-sample">` to exist and to sit after the sample link in
    // SOURCE ORDER, as a proxy for "the sample is not gated". Both broke when that band was
    // deleted for being the home page's second email ask (brand v3, 2026-08-06) -- and the
    // proxy had already stopped describing the page: the surviving captures render at
    // index.tsx:543 and :557, above the sample link at :680, while the sample stayed exactly
    // as reachable as before. Source order is not gating. A form earlier in the file gates
    // nothing; a form is a gate only when the link stops working without it.
    //
    // So the source test now asserts only what source can honestly show -- the link is a plain
    // href, not wrapped in a submit handler -- and the real property, that /sample opens cold
    // with no address given, is proven against the running site in e2e/discovery.spec.ts.
    expect(source).toMatch(/href="\/sample"/);
    expect(source, 'the sample link must not be inside a form that could gate it').not.toMatch(
      /<form[\s\S]{0,2000}href="\/sample"[\s\S]{0,2000}<\/form>/,
    );
  });
});
