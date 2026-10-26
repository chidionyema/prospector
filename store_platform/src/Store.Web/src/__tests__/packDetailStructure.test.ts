import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

/**
 * THE PACK PAGE'S SHAPE (MASTER-BRIEF §7 `/pack/{id}`).
 *
 * This is a source scan, and it is a source scan on purpose: the properties below are about what
 * the page RENDERS AT ALL and in what order, and both survive any amount of styling churn. A
 * rendering test would need the whole `PackDetails` fixture, the checkout hook and a router, and
 * would then assert the same three facts through 400 lines of setup.
 *
 * The scan runs against the source with its comments stripped. The first version of the kill-grid
 * guard did not, and failed on a docblock explaining that the component does NOT use
 * `dangerouslySetInnerHTML` -- a scanner that cannot tell a mention from a use punishes writing
 * down the reasoning, and the only way to make it pass is to stop writing it down.
 */

const SOURCE = readFileSync(
  fileURLToPath(new URL('../pages/pack/[id].tsx', import.meta.url)),
  'utf8',
);

/** Comments removed, so a note ABOUT a deleted thing is not read as the thing. */
const CODE = SOURCE.replace(/\{?\/\*[\s\S]*?\*\/\}?/g, '').replace(/^\s*\/\/.*$/gm, '');

/**
 * The JSX element whose opening tag carries `marker`, from that opening tag to its own closing
 * tag. Braces are counted, so an inner element's close is not mistaken for the outer one's end.
 *
 * This replaces a proximity assertion. The old one asked for two markers to sit within 400
 * characters of each other, which is a proxy for "the sticky buy button is inside the fixed
 * bar" -- a proxy that broke the moment the bar grew the refund line it had always meant to
 * show, and would have broken again on the next honest copy edit. Proximity is not the claim;
 * containment is.
 */
function elementWith(code: string, marker: string): string {
  const start = code.indexOf(marker);
  if (start === -1) return '';
  let i = code.indexOf('>', start) + 1;
  let depth = 0;
  while (i < code.length) {
    const lt = code.indexOf('<', i);
    if (lt === -1) break;
    if (code.startsWith('</', lt)) {
      if (depth === 0) return code.slice(start, lt);
      depth--;
      i = lt + 2;
      continue;
    }
    if (code.startsWith('/>', lt)) {
      i = lt + 2;
      continue;
    }
    const gt = code.indexOf('>', lt);
    if (gt === -1) break;
    // An opening tag that closes itself adds no level.
    if (!code.slice(lt, gt).endsWith('/')) depth++;
    i = gt + 1;
  }
  return code.slice(start);
}

describe('the pack page on the kit (crew#700 CP1): one purchase panel, one sticky bar', () => {
  it('renders the Detail template exactly once, with the buy control as its CTA', () => {
    expect(CODE.split('<Detail').length - 1).toBe(1);
    expect(CODE).toContain('cta={buyControl}');
  });

  it('renders the detail buy button once and the sticky bar once, both on the same checkout', () => {
    expect(CODE.split('variant="detail"').length - 1).toBe(1);
    expect(CODE.split('variant="sticky"').length - 1).toBe(1);
    expect(CODE.split('usePackCheckout(').length - 1).toBe(1);
  });

  it('keeps the sticky bar, which is what the deleted inline box was doing', () => {
    // The bar is the phone's way to buy: fixed to the bottom of the viewport, carrying the same
    // checkout the detail panel uses. The claim is that the sticky buy button is INSIDE that bar,
    // so the containment is what is asserted, not the distance between two markers.
    const bar = elementWith(CODE, 'fixed inset-x-0 bottom-0');
    expect(bar, 'the page must render a fixed bottom bar').not.toBe('');
    expect(bar, 'the sticky bar must carry the sticky buy button').toContain('variant="sticky"');
    expect(bar, 'the sticky bar must carry the pack buy button').toContain('PackBuyButton');
  });

  it('mounts the embedded checkout on demand only', () => {
    expect(CODE).toContain("{ ssr: false }");
    expect(CODE.split('<EmbeddedCheckoutPanel').length - 1).toBe(1);
  });

  it('has dropped the per-source price', () => {
    expect(CODE).not.toMatch(/per source|a source\b.{0,20}£/i);
  });

  it('keeps the source count and the commissioned-research day rate', () => {
    expect(CODE).toContain('RESEARCH_RATE_ANCHOR.dayRateLabel');
    expect(CODE).toContain('sourceCount');
  });

  it('renders the hundred-dot field once', () => {
    expect(CODE.split('<SixInHundred').length - 1).toBe(1);
  });
});
