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

/*
 * DELETED 2026-08-18: `describe('the row gives the title the whole column')`.
 *
 * Its three tests matched literal Tailwind class strings in `PackRow.tsx`: `text-meta text-muted`,
 * `mt-1.5 flex min-w-0 flex-wrap`, and `flex flex-none items-center gap-3 sm:gap-4`. The row was
 * rebuilt to the mockups' `.row` and all three strings changed, so all three failed while every
 * behaviour they were named for stayed true: the description still clamps at two lines, the seen
 * badge still sits in the meta row, and the price column still takes only the width it needs.
 *
 * A class list is not a contract. Pinning one makes every redesign look like a regression, which
 * is the founder's standing instruction on tests over a moving UI ("ui is always changing", "why
 * waste time and resources"). The `listHeading` tests above stay: they assert what a reader is
 * shown, not what class draws it.
 */
