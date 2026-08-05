/**
 * The pack page promises "a clickable source behind every claim" and shipped zero source
 * anchors. These tests pin the parser against the shapes the LIVE API actually sends, captured
 * from `GET https://api.mumchimp.com/catalog/{id}` across 12 packs on 2026-08-05.
 *
 * That provenance is the point. The currency bug this repo shipped in the same release existed
 * because the unit tests fed `'49.00'` -- the shape the doc comment assumed -- while the API
 * sent `'£49.00'`. Every fixture below is a verbatim production string, pasted, not invented.
 */
import { describe, it, expect } from 'vitest';
import { parseCitations, hasCitation, hostLabel } from '@/lib/citations';

/** Verbatim `sampleExtract` lines from live packs. Do not "tidy" these. */
const PROD = {
  simple:
    'One site offers over 100 free social stories that a parent can personalise and download as printable PDFs (source: https://socialstorytemplates.com/).',
  quoted:
    'UK law requires food businesses to write down what they do to keep food safe (source: https://assets.publishing.service.gov.uk/media/69c5247ecdfd19de13d0f6ca/sfbb-caterers-pack-fixed_0_3.pdf — "The law says you must write down what you do to make sure food is safe").',
  twoSources:
    'Phase 3 — pilot run of 100 units. Sold at £149 through Shopify and Amazon UK — channels where this buyer already shops for exactly this category of product (source: https://www.amazon.co.uk/fridge-freezer-thermometer/s?k=fridge+freezer+thermometer; source: https://www.ebay.co.uk/b/bn_7024846446).',
  folded:
    'Card checkout for a single $2 report or a $12 monthly plan (pricing from opportunity brief — assumption — unverified that these exact prices convert; solvency support only: average salary $103,552 in 2024–25, source: https://www.cde.ca.gov/fg/fr/sa/cefavgsalaries.asp).',
  midSentence:
    'A published collection covers personal hygiene, medical visits, social interactions and family events, each page carrying picture symbols (source: https://www.scribd.com/document/821626746/social-stories-book).',
};

describe('parseCitations — production shapes', () => {
  it('shape 1: (source: URL) — extracts the link and leaves clean prose', () => {
    const { text, citations } = parseCitations(PROD.simple);
    expect(citations).toHaveLength(1);
    expect(citations[0].url).toBe('https://socialstorytemplates.com/');
    expect(citations[0].host).toBe('socialstorytemplates.com');
    // The whole aside goes, and the sentence keeps its full stop with no orphaned space.
    expect(text).toBe(
      'One site offers over 100 free social stories that a parent can personalise and download as printable PDFs.',
    );
  });

  it('shape 2: (source: URL — "quote") — keeps the quoted passage as the chip title', () => {
    const { text, citations } = parseCitations(PROD.quoted);
    expect(citations).toHaveLength(1);
    expect(citations[0].host).toBe('assets.publishing.service.gov.uk');
    expect(citations[0].quote).toBe(
      'The law says you must write down what you do to make sure food is safe',
    );
    expect(text).toBe(
      'UK law requires food businesses to write down what they do to keep food safe.',
    );
  });

  it('shape 3: two sources in one paren group — both become chips, the group disappears', () => {
    const { text, citations } = parseCitations(PROD.twoSources);
    expect(citations.map((c) => c.host)).toEqual(['amazon.co.uk', 'ebay.co.uk']);
    expect(text).toBe(
      'Phase 3 — pilot run of 100 units. Sold at £149 through Shopify and Amazon UK — channels where this buyer already shops for exactly this category of product.',
    );
    // The query string must survive intact -- it is what makes the link checkable.
    expect(citations[0].url).toBe(
      'https://www.amazon.co.uk/fridge-freezer-thermometer/s?k=fridge+freezer+thermometer',
    );
  });

  it('shape 4: a source folded into a larger aside — the aside survives, the citation leaves', () => {
    const { text, citations } = parseCitations(PROD.folded);
    expect(citations).toHaveLength(1);
    expect(citations[0].host).toBe('cde.ca.gov');
    // The caveat is the honest part of the sentence. Losing it while keeping the claim would be
    // strictly worse than not parsing at all.
    expect(text).toContain('assumption');
    expect(text).toContain('unverified that these exact prices convert');
    expect(text).toBe(
      'Card checkout for a single $2 report or a $12 monthly plan (pricing from opportunity brief — assumption — unverified that these exact prices convert; solvency support only: average salary $103,552 in 2024–25).',
    );
  });

  it('never leaves a bare URL, an empty aside, or a space before punctuation', () => {
    for (const line of Object.values(PROD)) {
      const { text } = parseCitations(line);
      expect(text).not.toMatch(/https?:\/\//);
      expect(text).not.toMatch(/\(\s*\)/);
      expect(text).not.toMatch(/\s[.,;:)]/);
      expect(text).not.toMatch(/source:/i);
      expect(text.length).toBeGreaterThan(20);
    }
  });
});

describe('parseCitations — degenerate input', () => {
  it('returns an unsourced line untouched', () => {
    const line = 'Phase 1 — validate demand with 20 conversations before building anything.';
    expect(parseCitations(line)).toEqual({ text: line, citations: [] });
  });

  it('handles empty and whitespace input without throwing', () => {
    expect(parseCitations('')).toEqual({ text: '', citations: [] });
    expect(parseCitations('   ')).toEqual({ text: '   ', citations: [] });
  });

  it('de-duplicates a URL cited twice in one line', () => {
    const { citations } = parseCitations(
      'Both figures come from the same page (source: https://example.com/a; source: https://example.com/a).',
    );
    expect(citations).toHaveLength(1);
  });

  it('keeps a bare URL that carries no `source:` label', () => {
    const { text, citations } = parseCitations('The register is published at https://example.gov.uk/list weekly.');
    expect(citations.map((c) => c.host)).toEqual(['example.gov.uk']);
    expect(text).toBe('The register is published at weekly.');
  });
});

describe('hasCitation', () => {
  it('is stable across repeated calls on the same input', () => {
    // A global regex + `.test()` alternates true/false because `lastIndex` persists. This test
    // fails on that implementation and passes on the non-global one.
    const line = PROD.simple;
    expect(hasCitation(line)).toBe(true);
    expect(hasCitation(line)).toBe(true);
    expect(hasCitation(line)).toBe(true);
  });

  it('is false for prose with no link', () => {
    expect(hasCitation('No sources here.')).toBe(false);
  });
});

describe('hostLabel', () => {
  it('strips www. and keeps meaningful subdomains', () => {
    expect(hostLabel('https://www.scribd.com/document/1')).toBe('scribd.com');
    expect(hostLabel('https://assets.publishing.service.gov.uk/x.pdf')).toBe(
      'assets.publishing.service.gov.uk',
    );
  });

  it('falls back to something renderable rather than throwing', () => {
    expect(() => hostLabel('http://')).not.toThrow();
    expect(hostLabel('http://')).toBeTruthy();
  });
});
