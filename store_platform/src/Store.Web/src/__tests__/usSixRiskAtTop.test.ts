import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

function readSource(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), 'utf8');
}

/**
 * US-6 — "Where this could break" moves to the top of the pack detail.
 *
 * The audit (§4.9, §7.3) found the strongest argument against the pack was
 * buried 1,500px below the title, after the buyer had already lost the
 * thread. The fix is to put the risk first, right after the title and
 * one-liner, before the deliverables. The risk is the first persuasion:
 * the buyer who reads the risk and buys is the buyer who is certain.
 *
 * This is a counter-intuitive move (the standard copywriting advice is
 * "don't lead with the objection"), but the Mumchimp voice is
 * refutational. The objection is the proof.
 */
describe('US-6 — Where this could break at the top', () => {
  const page = readSource('../pages/pack/[id].tsx');

  it('renders the "Where this could break" section in the upper half of the page', () => {
    // The risk section must come before the deliverables. The audit's order:
    // hero, then risk, then deliverables, then methodology.
    const riskIdx = page.indexOf('Where this could break');
    const deliverablesIdx = page.indexOf("What\u2019s inside your pack");
    expect(
      riskIdx > 0 && deliverablesIdx > 0 && riskIdx < deliverablesIdx,
      'pack/[id].tsx must render "Where this could break" before "What\u2019s inside your pack"',
    ).toBe(true);
  });

  it('renders the risk section after the title and one-liner', () => {
    // The risk sits below the title (h1) and the one-liner, but above the
    // deliverables. The title + one-liner is the buyer's "what is this?"
    // moment; the risk is the "is this real?" moment that comes immediately
    // after.
    const h1Idx = page.indexOf('<h1');
    const oneLinerIdx = page.indexOf('pack.oneLine');
    const riskIdx = page.indexOf('Where this could break');
    expect(
      h1Idx > 0 && oneLinerIdx > 0 && riskIdx > 0,
      'pack/[id].tsx must render title, one-liner, and risk',
    );
    expect(
      h1Idx < riskIdx && oneLinerIdx < riskIdx,
      'pack/[id].tsx must render the risk section after the title and one-liner',
    ).toBe(true);
  });

  it('risk section uses the warning-tinted box', () => {
    /*
     * The claim is unchanged: the risk is visually distinct, so a buyer who scans sees the
     * warning before reading the body. What changed is how the tint is produced.
     *
     * The old assertion pinned `border-warning/30` + `bg-warning/5` -- an opacity-derived tint of
     * the foreground colour. v3 declares the pair as real tokens (`--warning: #B45309` with
     * `--warning-bg: #FFFBEB` and `--warning-strong: #92400E`, globals.css:89-91) precisely
     * because the derived version had no contrast guarantee: `bg-warning/5` was whatever 5% of
     * the then-current warning hue happened to be, and v2's warning was #DC2626, i.e. identical
     * to --danger. So this now asserts the token, plus the left rule that replaced the full
     * border (a 4-sided tinted box reads as an alert banner; this is an aside).
     */
    const hasWarningStyle =
      /border-l-warning[\s\S]{0,200}bg-warning-bg/.test(page) ||
      /bg-warning-bg[\s\S]{0,200}border-l-warning/.test(page);
    expect(
      hasWarningStyle,
      'pack/[id].tsx must render the risk section against --warning-bg with a --warning left rule',
    ).toBe(true);
  });

  it('risk section is always visible (not collapsed behind a disclosure)', () => {
    // The audit: "The section is always visible (not collapsible)." Unlike
    // the methodology (US-4), the risk is the buyer's first test of whether
    // to trust the work; it must be on the page on load. The test confirms
    // the FIRST occurrence (the top-of-page risk) is not inside a <details>.
    const firstRiskIdx = page.indexOf('Where this could break');
    // Find the most recent <details> before the risk. If none, the risk
    // is outside any disclosure.
    const lastDetailsBefore = page.lastIndexOf('<details', firstRiskIdx);
    const lastDetailsEndBefore = page.lastIndexOf('</details>', firstRiskIdx);
    // If there's an open <details> before the risk with no matching </details>,
    // the risk is inside it. We expect: no such enclosing <details>.
    const insideOpenDetails =
      lastDetailsBefore > lastDetailsEndBefore;
    expect(
      !insideOpenDetails,
      'pack/[id].tsx must render the top-of-page "Where this could break" outside any <details> disclosure',
    ).toBe(true);
  });

  it('risk section uses the same data source as the original location', () => {
    // The risk comes from `verdict.risk` (splitVerdict on qaVerdictSummary).
    // The audit said: "the section uses the existing splitVerdict(pack.qaVerdictSummary).risk
    // data." The new location must use the same data source.
    const usesVerdictRisk = /verdict\.risk/.test(page);
    expect(
      usesVerdictRisk,
      'pack/[id].tsx must read the risk from verdict.risk (the same data source as the original location)',
    ).toBe(true);
  });
});
