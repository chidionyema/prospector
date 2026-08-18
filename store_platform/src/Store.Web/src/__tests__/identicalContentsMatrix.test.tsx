import { describe, it, expect } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

import { IdenticalContentsMatrix, type PriceRung } from '@/components/marketing/IdenticalContentsMatrix';

/**
 * THE IDENTICAL-CONTENTS MATRIX (MASTER-BRIEF §7 `/pricing`).
 *
 * The argument is the repetition: the same fourteen marks on every rung, so a reader can see that
 * the cheap pack is not the cut-down one. A "tidy" version that draws the marks once and adds a
 * note makes no argument at all, so the test that matters is the one that counts them.
 */

const rungs: PriceRung[] = [
  { price: '£29', description: 'Small local markets', count: 9 },
  { price: '£49', description: 'The usual rung', count: 16 },
  { price: '£79', description: 'Bigger budgets', count: 30 },
  { price: '£129', description: 'Regulated or technical', count: 17 },
  { price: '£199', description: 'Large B2B contracts', count: 2 },
];

const DOCS = 14;
const html = renderToStaticMarkup(<IdenticalContentsMatrix rungs={rungs} documents={DOCS} />);

describe('the identical-contents matrix', () => {
  it('draws every document mark on every rung, not once with a note', () => {
    // 5 rungs x 14 documents. The repetition IS the proof; compressing it turns the proof back
    // into the assertion the reader was suspicious of.
    expect(html.split('<i class="bg-text"').length - 1).toBe(rungs.length * DOCS);
  });

  it('renders one row per rung, in the order given', () => {
    expect(html.split('<tr').length - 1).toBe(rungs.length + 1); // + the header row
    expect(html.indexOf('£29')).toBeLessThan(html.indexOf('£199'));
  });

  it('takes the prices from the caller, never from a copy of its own', () => {
    // A pricing page carrying its own ladder is the defect where a buyer is quoted one number and
    // charged another. Every price rendered must be one that was passed in.
    const rendered = [...html.matchAll(/£[\d,]+/g)].map((m) => m[0]);
    const given = new Set(rungs.map((r) => r.price));
    expect(rendered.every((p) => given.has(p))).toBe(true);
  });

  it('states the pack counts on each rung', () => {
    expect(html).toContain('>9<');
    expect(html).toContain('>30<');
  });

  it('does not use teal for a document tick', () => {
    // §2: teal means an idea survived the filter. A document is not an idea, and a tick in the
    // survivor colour puts a verdict on a contents list.
    expect(html).not.toContain('bg-survive');
    expect(html).not.toContain('text-survive');
  });

  it('gives assistive tech the sentence, not seventy shapes', () => {
    expect(html).toContain(`All ${DOCS} documents included`);
    expect(html).toContain('aria-hidden');
  });

  it('renders nothing rather than an empty table', () => {
    expect(renderToStaticMarkup(<IdenticalContentsMatrix rungs={[]} documents={DOCS} />)).toBe('');
    expect(renderToStaticMarkup(<IdenticalContentsMatrix rungs={rungs} documents={0} />)).toBe('');
  });

  it('scrolls inside its own container, never the page', () => {
    // §9: the site body must not scroll sideways. A five-column table at 390px will exceed it.
    expect(html).toContain('overflow-x-auto');
  });
});
