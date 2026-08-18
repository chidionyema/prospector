import { describe, it, expect } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

import { SixInHundred, survivorDots } from '@/components/marketing/SixInHundred';
import { RESEARCH_STATS } from '@/lib/stats';

/**
 * THE PACK PAGE'S SIGNATURE (MASTER-BRIEF §7): a hundred dots, six of them teal.
 *
 * The failure this guards against is not a broken render. It is a picture that stops agreeing with
 * the sentence beside it. `survivorBoundLabel` is regenerated from the totals; a hardcoded six here
 * would keep drawing six teal dots on the day the real figure becomes five, and nothing would fail.
 */

const html = renderToStaticMarkup(<SixInHundred />);
const survivors = survivorDots();

const count = (needle: string) => html.split(needle).length - 1;

/**
 * The dots only, without the two `.sw9` swatches in the legend, which are also `<i>`.
 *
 * The field was an SVG of `<circle>` elements until 2026-08-18. The drawing sets it as a
 * `.dotfield` grid of a hundred `<i>`, which the stylesheet already knows how to draw, so what
 * these counts read changed while what they mean did not.
 */
const field = (markup: string) => {
  const start = markup.indexOf('class="dotfield"');
  return markup.slice(start, markup.indexOf('</div>', start));
};
const dots = (markup: string) => field(markup).split('<i').length - 1;
const alive = (markup: string) => field(markup).split('class="alive"').length - 1;

describe('the six-in-a-hundred field', () => {
  it('draws a hundred dots', () => {
    expect(dots(html)).toBe(100);
  });

  it('takes its teal count from the label, not from a constant', () => {
    expect(survivors).not.toBeNull();
    expect(alive(html)).toBe(survivors);
    expect(dots(html) - alive(html)).toBe(100 - (survivors as number));
    // The picture and the words are the same fact. If the totals are regenerated and the label
    // becomes "5 in 100", this stays true without anyone editing the component.
    expect(html).toContain(RESEARCH_STATS.survivorBoundLabel);
  });

  it('follows the label when the label moves', () => {
    const five = renderToStaticMarkup(<SixInHundred label="5 in 100" />);
    expect(alive(five)).toBe(5);
    expect(dots(five)).toBe(100);
  });

  it('renders nothing rather than a wrong picture', () => {
    // A malformed label means we do not know the rate. An absent illustration is a gap; a field
    // with the wrong number of teal dots is a false claim on a page that sells accuracy.
    for (const bad of ['about 6 in 100', '', '0 in 100', '100 in 100', 'six in 100']) {
      expect(survivorDots(bad), bad).toBeNull();
      expect(renderToStaticMarkup(<SixInHundred label={bad} />), bad).toBe('');
    }
  });

  it('never prints the survivor count', () => {
    // The 2026-08-13 directive. A rate is not a population: nothing here names the total the rate
    // applies to, so nothing here can be multiplied back into "80 survived".
    expect(html).not.toMatch(/\b(80|1,?444)\b/);
  });

  it('is decoration, and the caption carries the meaning', () => {
    // A screen reader should hear the sentence once, not a hundred unlabelled shapes.
    expect(html).toContain('aria-hidden="true"');
    expect(html).toContain('<figcaption');
  });

  it('ships zero client JavaScript', () => {
    expect(html).not.toContain('onclick');
    expect(html).not.toContain('<script');
  });
});
