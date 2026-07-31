import { describe, expect, it } from 'vitest';

import { splitTitle } from '../discovery';

/**
 * AC-15. The fixture is real title data, not invented strings: every live title captured from
 * `GET https://prospector-store-api.fly.dev/catalog` on 2026-07-30.
 *
 * It is a FROZEN SAMPLE, not a claim about the catalogue's size. The catalogue grows — the
 * engine publishes on every PASS — so nothing here asserts how many packs exist, and a new pack
 * does not break this file. What it pins down is the shape variety that was actually observed:
 * em dash, en dash, no separator with a headline, and no separator with `headline: null`.
 *
 * Counted on that capture (not assumed): 6 em dash, 1 en dash, 0 spaced hyphen, 8 with no
 * separator — and of those 8, only 3 had a headline to fall back to. That last group is why the
 * fallback must tolerate a missing headline rather than assume one. (The spec's Part 0 figure of
 * "9 of 15" does not match the payload; the fixture below is the payload.)
 */
const LIVE_TITLES: ReadonlyArray<{ title: string; headline: string | null }> = [
  {
    title: "PlateStart — The Gig Driver's Private-Hire Licence Route Optimizer & Application Pack",
    headline: 'Everything you need to launch a licensing help service for new private hire drivers',
  },
  {
    title: "AccrueBack — The Casual Worker's Unpaid Holiday Pay Recovery Pack",
    headline: 'A complete plan for a service that helps casual workers claim unpaid holiday pay',
  },
  {
    title: "RentPass Dossier — The Gig Worker's Referencing Pass Pack",
    headline: 'Launch a tenant side service that turns messy gig income into referencing ready evidence',
  },
  {
    title: "PisteCheck — The Seasonnaire's Package Decoder",
    headline: 'Everything you need to launch a fixed fee ski season wage audit service',
  },
  {
    title: "The Carer's Allowance Clawback Settlement Desk",
    headline: "Run a contingency-fee desk that negotiates down carers' DWP overpayment demands for a cut",
  },
  {
    title: 'StockLift — The Dormant Side-Hustle Inventory Cash-Out Service',
    headline: "A complete plan to launch a done-for-you service that clears sellers' unsold stock",
  },
  {
    title: "PackProof — The Dog Walker's Group Walk Evidence Engine",
    headline: 'A complete blueprint to build and launch an evidence tool for UK dog walkers',
  },
  {
    title: 'The Brief Winnow',
    headline:
      'A complete, evidence-checked plan to launch a paid opportunity newsletter for freelance creatives',
  },
  {
    // En dash, not em dash — the separator the previous implementation missed.
    title: "FabQuote – The Solo Fabricator's Instant Quote Engine",
    headline: 'A complete plan to launch an instant CAD-to-quote tool for metal fabrication shops',
  },
  {
    title: 'The Creative Rights Recovery Agent',
    headline: 'The complete plan to launch a solo image-theft recovery bureau on contingency fees',
  },
  { title: 'The Garden Office Power Broker', headline: null },
  // Compound hyphens: "Time-Capture" and "Clear-Out" must survive intact.
  { title: "The Tradie's Time-Capture Agent", headline: null },
  { title: 'Probate Property Clear-Out Agent', headline: null },
  { title: "The Vet's Fee Extractor", headline: null },
  { title: "The Solo Builder's Warranty Audit", headline: null },
];

const WITH_SEPARATOR = new Set([
  'PlateStart',
  'AccrueBack',
  'RentPass Dossier',
  'PisteCheck',
  'StockLift',
  'PackProof',
  'FabQuote',
]);

/** Derived from the fixture, so adding a captured title never needs a magic number updated. */
const EXPECTED_SPLITS = LIVE_TITLES.filter((t) => /[—–]|\s-\s/.test(t.title)).length;

describe('splitTitle against the captured live titles (AC-15)', () => {
  it('exercises every title shape the catalogue has produced', () => {
    // Not a count of the catalogue — a guard that the fixture still covers all four shapes.
    expect(LIVE_TITLES.some((t) => t.title.includes('—'))).toBe(true);
    expect(LIVE_TITLES.some((t) => t.title.includes('–'))).toBe(true);
    expect(LIVE_TITLES.some((t) => !/[—–]/.test(t.title) && t.headline !== null)).toBe(true);
    expect(LIVE_TITLES.some((t) => !/[—–]/.test(t.title) && t.headline === null)).toBe(true);
  });

  it.each(LIVE_TITLES)('never invents or drops text: $title', ({ title, headline }) => {
    const { name, descriptor } = splitTitle(title, headline ?? undefined);
    expect(name.length).toBeGreaterThan(0);
    // The name is always a prefix of the real title — never rewritten, never truncated mid-word.
    expect(title.startsWith(name)).toBe(true);
    if (descriptor !== null) {
      const fromTitle = title.includes(descriptor);
      const fromHeadline = headline !== null && headline.includes(descriptor);
      expect(fromTitle || fromHeadline).toBe(true);
    }
  });

  it('splits exactly the titles that carry a separator, into a short brand name', () => {
    const split = LIVE_TITLES.map((t) => splitTitle(t.title, t.headline ?? undefined)).filter(
      (r, i) => r.name !== LIVE_TITLES[i].title,
    );
    expect(split).toHaveLength(EXPECTED_SPLITS);
    for (const { name } of split) expect(name.length).toBeLessThanOrEqual(20);
  });

  it('keeps every brand name the catalogue actually has', () => {
    for (const { title, headline } of LIVE_TITLES) {
      const { name } = splitTitle(title, headline ?? undefined);
      if (WITH_SEPARATOR.has(name)) expect(title.startsWith(`${name} `)).toBe(true);
    }
  });

  it('falls back to the headline when the title has no separator', () => {
    const result = splitTitle('The Brief Winnow', LIVE_TITLES[7].headline ?? undefined);
    expect(result.name).toBe('The Brief Winnow');
    expect(result.descriptor).toBe(LIVE_TITLES[7].headline);
  });

  it('returns no descriptor at all when there is neither a separator nor a headline', () => {
    expect(splitTitle('The Garden Office Power Broker')).toEqual({
      name: 'The Garden Office Power Broker',
      descriptor: null,
    });
  });
});

describe('splitTitle separators', () => {
  it('handles the em dash', () => {
    expect(splitTitle('Brand — Descriptor')).toEqual({ name: 'Brand', descriptor: 'Descriptor' });
  });

  it('handles the en dash', () => {
    expect(splitTitle('Brand – Descriptor')).toEqual({ name: 'Brand', descriptor: 'Descriptor' });
  });

  it('handles a hyphen surrounded by spaces', () => {
    expect(splitTitle('Brand - Descriptor')).toEqual({ name: 'Brand', descriptor: 'Descriptor' });
  });

  it('leaves a compound hyphen alone', () => {
    expect(splitTitle("The Tradie's Time-Capture Agent")).toEqual({
      name: "The Tradie's Time-Capture Agent",
      descriptor: null,
    });
  });

  it('splits on the earliest separator when a title has more than one', () => {
    expect(splitTitle('Brand — Descriptor – with an aside')).toEqual({
      name: 'Brand',
      descriptor: 'Descriptor – with an aside',
    });
  });

  it('falls back rather than producing an empty half', () => {
    expect(splitTitle('— Descriptor', 'A headline')).toEqual({
      name: '— Descriptor',
      descriptor: 'A headline',
    });
    expect(splitTitle('Brand —', 'A headline')).toEqual({ name: 'Brand —', descriptor: 'A headline' });
  });

  it('treats a blank headline as no headline', () => {
    expect(splitTitle('The Vet’s Fee Extractor', '   ')).toEqual({
      name: 'The Vet’s Fee Extractor',
      descriptor: null,
    });
  });
});
