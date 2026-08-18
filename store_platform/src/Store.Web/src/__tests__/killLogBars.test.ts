import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import path from 'node:path';

/**
 * ONE CLASS NAME, TWO COMPONENTS, IN A STYLESHEET WE SHIP VERBATIM.
 *
 * `mumchimp.css:103` is `.bars{display:flex;flex-direction:column;align-items:flex-end;height:44px}`.
 * It is written for the home page's sparkline (`mockups/index.html:629`, cells styled by
 * `.bars i` at `mumchimp.css:356`), and `mockups/kill-log.html:475` reuses the same name for the
 * ranked horizontal chart of causes. The sparkline's fixed 44px height and right alignment
 * therefore land on a list of thirteen rows.
 *
 * The drawing breaks on itself: measured 2026-08-18 at 1280, its twelve rows run y=1638..1932 --
 * 294px of content in a 44px box -- each row shrink-wrapped and pushed right, so no two labels
 * share a baseline. Copied faithfully, ours did the same and the rows rendered on top of the search
 * box and the chip rail below it.
 *
 * Step 1 of the parity programme says the stylesheet is shipped and never written, so the fix is an
 * override at the one call site, not an edit to `mumchimp.css`. This pins the override, because
 * nothing else can: the page type-checks, builds and passes structural parity either way.
 */
describe('the kill-log cause chart overrides the sparkline rule it inherits', () => {
  const source = readFileSync(path.join(process.cwd(), 'src/pages/kill-log.tsx'), 'utf8');

  const barsClass = /<ul className="([^"]*\bbars\b[^"]*)"/.exec(source);

  it('renders the ranked chart as a `.bars` list', () => {
    expect(barsClass).not.toBeNull();
  });

  it('takes the height of its rows instead of the sparkline 44px', () => {
    expect(barsClass![1].split(/\s+/)).toContain('h-auto');
  });

  it('stretches each row to the full width so the bars share a baseline', () => {
    expect(barsClass![1].split(/\s+/)).toContain('items-stretch');
  });

  it('lets a bar reach the length its count says, past the sparkline 26px cap', () => {
    // `mumchimp.css:356` is `.bars i{max-width:26px}` -- the sparkline cell, matched by descendant,
    // so it also caps the fill in this chart. Measured 2026-08-18 at 1280 before the override: the
    // 624 bar computed `width:100%` on a 665px track and rendered 26px, and so did 203, 191, 142,
    // 83 and 26. Every cause above ~4% drew the same stub and the ranking was invisible.
    const fill = /className=\{d\.published \? '([^']*)' : '([^']*)'\}/.exec(source);
    expect(fill).not.toBeNull();
    expect(fill![1].split(/\s+/)).toContain('max-w-none');
    expect(fill![2].split(/\s+/)).toContain('max-w-none');
  });

  it('does not fix this by editing the shipped stylesheet', () => {
    const css = readFileSync(
      path.join(process.cwd(), '../../../docs/design/mumchimp-build-bundle/mumchimp.css'),
      'utf8',
    );
    // The bundle rule stays exactly as delivered. If this ever fails, the stylesheet was edited,
    // which `stylesheetIsShippedVerbatim.test.ts` also forbids.
    expect(css).toContain('.bars{display:flex;flex-direction:column;gap:3px;margin:20px 0;align-items:flex-end;height:44px;margin-top:16px}');
  });
});
