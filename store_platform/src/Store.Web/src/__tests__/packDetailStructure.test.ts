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

const at = (needle: string) => CODE.indexOf(needle);

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
    expect(CODE).toMatch(/fixed inset-x-0 bottom-0[\s\S]{0,400}variant="sticky"/);
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
