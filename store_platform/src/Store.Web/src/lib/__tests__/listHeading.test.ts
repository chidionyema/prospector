import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { listHeading } from '@/lib/discovery';

const SRC = (rel: string) => readFileSync(resolve(__dirname, '../..', rel), 'utf8');

/**
 * The defect this file pins, in the founder's words on 2026-08-16:
 *
 *   "Freelance pay benchmarks for UK...", "Weekly judgment brief for UK...", "HMRC £100
 *   late-filing penalty appeals for UK...". Three consecutive rows truncating at the identical
 *   word makes the list look like one repeated item.
 *
 * The titles share a construction, so the clause that differs sits where every cut lands. A
 * wider column does not help: the tail is last, so the tail is what gets ellipsed.
 */
describe('the shelf row drops the trailing audience clause', () => {
  it('strips "for UK <audience>" from the three titles the founder named', () => {
    expect(listHeading('Freelance pay benchmarks for UK designers'))
      .toBe('Freelance pay benchmarks');
    expect(listHeading('Weekly judgment brief for UK litigators'))
      .toBe('Weekly judgment brief');
    expect(listHeading('HMRC £100 late-filing penalty appeals for UK accountants'))
      .toBe('HMRC £100 late-filing penalty appeals');
  });

  it('leaves those three reading differently from one another', () => {
    const rendered = [
      'Freelance pay benchmarks for UK designers',
      'Weekly judgment brief for UK litigators',
      'HMRC £100 late-filing penalty appeals for UK accountants',
    ].map(listHeading);
    // The whole point. Before the trim these agreed for their first word and then ellipsed on
    // "for UK"; a reader scanning the left edge saw one item three times.
    expect(new Set(rendered).size).toBe(3);
    expect(rendered.every((r) => !/for\s+UK/i.test(r))).toBe(true);
  });

  it('handles the US shelf and the "the UK" phrasing on the same terms', () => {
    expect(listHeading('Sales tax nexus checklist for US ecommerce sellers'))
      .toBe('Sales tax nexus checklist');
    expect(listHeading('Right to rent audit trail for the UK letting agents'))
      .toBe('Right to rent audit trail');
  });

  it('keeps the clause when stripping it would leave a stub, not a title', () => {
    // Two words left is not a title. Better a repeated tail than a heading that says nothing.
    expect(listHeading('Compliance pack for UK landlords'))
      .toBe('Compliance pack for UK landlords');
  });

  it('touches nothing when there is no trailing audience clause', () => {
    expect(listHeading('Weekly judgment brief')).toBe('Weekly judgment brief');
    expect(listHeading('A rota tool that prices overtime')).toBe('A rota tool that prices overtime');
  });

  it('only strips a TRAILING clause, never one mid-title', () => {
    // "for UK" here introduces the subject rather than closing the title, so it stays.
    const t = 'What for UK employers changed in April, and what it costs';
    expect(listHeading(t)).toBe(t);
  });

  it('survives an empty or whitespace heading without throwing', () => {
    expect(listHeading('')).toBe('');
    expect(listHeading('   ')).toBe('');
  });
});

/**
 * The trim is a LIST-context decision. If it ever reached the pack page the buyer would decide
 * to spend money against a shortened title, which is the opposite of the intent.
 */
describe('the trim stays in list contexts', () => {
  it('the row applies it and the pack page does not', () => {
    expect(SRC('components/discovery/PackRow.tsx')).toMatch(/listHeading\(heading\)/);
    expect(SRC('pages/pack/[id].tsx')).not.toMatch(/listHeading/);
  });
});

/**
 * Items 3 and 4 of the same brief. Asserted on the source because both are pure layout: there is
 * no rendered value to read back, and a jsdom box has no line height to measure.
 */
describe('the row gives the title the whole column', () => {
  const row = SRC('components/discovery/PackRow.tsx');

  it('clamps the description at two lines rather than truncating it at one', () => {
    // `truncate` is one line AND a mid-word cut. `cardLine` already ends the string on a word
    // boundary, and the one-line box then cut it again inside a word.
    expect(row).toMatch(/line-clamp-2 block text-meta text-muted/);
    expect(row).not.toMatch(/block truncate text-meta/);
  });

  it('puts the seen badge in the meta row, not beside the title', () => {
    // The badge is `flex-none`, so beside the heading it took its width off the top before the
    // title got a character. Everything after the meta-row container must contain it.
    const metaRow = row.indexOf('mt-1.5 flex min-w-0 flex-wrap');
    const badge = row.indexOf('>seen</span>');
    expect(metaRow).toBeGreaterThan(-1);
    expect(badge).toBeGreaterThan(metaRow);
  });

  it('still lets the price column take only the width the price needs', () => {
    // Already true before this brief, and pinned here so it stays true: the title column is
    // `flex-1` and the price column `flex-none`, not a fixed ratio.
    expect(row).toMatch(/className="min-w-0 flex-1"/);
    expect(row).toMatch(/className="flex flex-none items-center gap-3 sm:gap-4"/);
  });
});
