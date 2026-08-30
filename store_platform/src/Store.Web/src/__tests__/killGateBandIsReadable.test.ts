import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import path from 'node:path';

/**
 * A CHART NOBODY CAN READ, ON THE BAND WHOSE ARGUMENT IS THAT THE EVIDENCE IS PUBLISHED.
 *
 * The founder pointed at this band on 2026-08-30 -- "THE STYLONG HERE 24 ... IS SHIT", "IT LOOKS
 * WEORD AND HAS DONE SINCE IT WAS INTROCDEC", "NNOT SURE WHY I NEED TO HIGHLIGHT THIS IT STICCKS
 * OUT LIKE A SORE THUNNB".
 *
 * Measured on the production build at 1280 on 2026-08-30: `.bars` rendered 846.3x44px with six
 * cells at 44.0, 14.5, 13.6, 10.1, 5.7 and 3.5px tall. Five of six under fifteen pixels, the
 * whole chart 171px of an 846px box, `aria-hidden` on the only ranked evidence the band carries,
 * and one caption naming one bar for six bars.
 *
 * It survived because the component said in a comment that the fix "needs a CSS rule that
 * `mumchimp.css` does not have". The rule was already there: `.barline` at `mumchimp.css:104-109`,
 * a `1fr 48px` grid with a label, a track and the count, used by `/kill-log` since 2026-08-18.
 *
 * That is the class of mistake this pins: a written-down reason a thing cannot be done, standing
 * in for the command that would have checked. Nothing else fails if the chart goes back -- the
 * page type-checks, builds and passes structural parity with the sparkline in place.
 */
describe('the kill-gate band draws a chart with labels, not a sparkline', () => {
  const source = readFileSync(
    path.join(process.cwd(), 'src/components/marketing/EvidenceBands.tsx'),
    'utf8',
  );

  const barsClass = /<ul className="([^"]*\bbars\b[^"]*)"/.exec(source);

  it('renders the chart as a `.bars` list, so the shipped rule reaches it', () => {
    expect(barsClass).not.toBeNull();
  });

  it('takes the height of its rows instead of the sparkline 44px', () => {
    expect(barsClass![1].split(/\s+/)).toContain('h-auto');
  });

  it('stretches each row to full width so every bar starts on one baseline', () => {
    expect(barsClass![1].split(/\s+/)).toContain('items-stretch');
  });

  it('lets a bar reach the length its count says, past the sparkline 26px cap', () => {
    // `.bars i{flex:1;max-width:26px}` (mumchimp.css:356) selects by descendant, so it also
    // matches the fill inside `.barline .bar i`. Without the override every cause above about
    // 4% draws the same 26px stub and the chart shows a ranking it does not have.
    expect(source).toMatch(/className="max-w-none"/);
  });

  it('pairs every bar with its own label, drawn by `.barline`', () => {
    expect(source).toMatch(/className="barline"/);
    expect(source).toMatch(/className="lab[^"]*"/);
  });

  it('names each cause with the canonical gate label, not a shorthand of its own', () => {
    // Removed 2026-08-18: this file and the kill log named the same cause of death two different
    // ways, on the band whose point is that the reason is published. One map, `lib/gateLabels.ts`.
    expect(source).toMatch(/GATE_LABELS\[gate\]/);
  });

  it('prints the count beside each bar', () => {
    expect(source).toMatch(/className="n num"/);
  });

  it('is not hidden from a screen reader', () => {
    const chart = source.slice(source.indexOf('<ul className="bars'));
    expect(chart.slice(0, chart.indexOf('</ul>'))).not.toMatch(/aria-hidden/);
  });

  it('never draws a vertical cell whose height is a percentage again', () => {
    // The exact shape of the defect: `style={{ height: `${...}%` }}` on a cell inside `.bars`.
    expect(source).not.toMatch(/style=\{\{\s*height:/);
  });

  it('scales the bars against the largest cause, so five of six are not slivers', () => {
    expect(source).toMatch(/n \/ max/);
  });

  it('counts the causes it is not showing instead of typing the number', () => {
    expect(source).toMatch(/\{ranked\.length\}/);
  });
});
