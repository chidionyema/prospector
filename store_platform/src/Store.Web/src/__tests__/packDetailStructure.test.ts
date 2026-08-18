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

describe('the pack page renders one buy box and one closing bar', () => {
  it('renders the full purchase panel exactly once', () => {
    // §7: "The live page renders the full price box twice plus a sticky bar." The panel body is
    // built once and was rendered twice -- inline on mobile and in the desktop rail. The inline
    // copy is gone; the rail is the one sticky buy box.
    expect(CODE.split('{checkoutBody}').length - 1).toBe(1);
  });

  it('keeps the sticky bar, which is what the deleted inline box was doing', () => {
    // Removing the duplicate must not remove the reachable price on a phone. The fixed bar keeps
    // both within a thumb from any scroll position, which the inline box could not.
    expect(CODE).toContain('fixed inset-x-0 bottom-0');
  });

  it('closes on the ask, not on the share row', () => {
    // §7 order ends "... related packs -> closing bar". A reader who has read the checks, the
    // documents and the sources reached a share row and nothing else.
    expect(at('<ShareRow')).toBeGreaterThan(-1);
    expect(at('One payment. Download straight away.')).toBeGreaterThan(at('<ShareRow'));
  });

  it('does not make the closing bar a third purchase panel', () => {
    // Price, button, two facts. Everything else the panel carries has already been said at length
    // further up, and repeating it here is the duplication §7 removes, moved down the page.
    //
    // BOUNDED AT THE DESKTOP RAIL, not run to the end of the file. The first version of this took
    // everything after the marker and failed: the rail is composed LOWER in the source than the
    // main column it renders beside, so `{checkoutBody}` is legitimately down there. An unbounded
    // slice was asking a question about the whole rest of the page.
    const start = at('One payment. Download straight away.');
    // The locator stops at `lg:w-`, without the number. What this line needs to find is the
    // desktop rail; its width is a design measure that moved from 320px to the drawing's
    // 394px on 2026-08-18, and pinning the digits here made a layout change read as a
    // structural regression in a test about duplication.
    const rail = CODE.indexOf('hidden w-full shrink-0 lg:block lg:w-', start);
    expect(rail, 'the desktop rail must still follow the closing bar').toBeGreaterThan(start);
    expect(CODE.slice(start, rail)).not.toContain('{checkoutBody}');
  });
});

describe('the price is compared to the alternative, never to itself', () => {
  it('has dropped the per-source price', () => {
    // §7: drop "34 cited sources, £1.47 each". It invites price-shopping the sources -- the one
    // comparison we lose, since anyone can cite more pages more cheaply -- and it penalises the
    // pack whose topic needs eleven decisive sources rather than sixty.
    expect(CODE).not.toContain('perSource');
    expect(CODE).not.toMatch(/sourceCount[^\n]*\/\s*100/);
  });

  it('keeps the source count and the commissioned-research day rate', () => {
    // §7 keeps both. The count is a fact about the pack; the day rate is the comparison the buyer
    // is actually making, against what they would otherwise pay a person.
    expect(CODE).toContain('RESEARCH_RATE_ANCHOR.dayRateLabel');
    expect(CODE).toContain('pack.sourceCount');
  });
});

describe('the signature sits above the gates', () => {
  it('renders the hundred-dot field', () => {
    expect(CODE).toContain('<SixInHundred');
  });

  it('puts it above the six checks, because it is the question they answer', () => {
    expect(at('<SixInHundred')).toBeGreaterThan(-1);
    expect(at('<SixInHundred')).toBeLessThan(at('How we tried to kill it'));
  });
});
