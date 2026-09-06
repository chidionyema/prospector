import { describe, expect, it } from 'vitest';
import { lintPackCard } from '../summaryLint';

const ok = {
  title: 'CIS invoice hold for trade contractors',
  summary: 'A withhold calculator for building subcontractors, so they keep the cash HMRC would take.',
  category: 'trades_construction',
  market: 'uk',
  verifiedAt: '2026-08-15',
};

describe('lintPackCard', () => {
  it('passes a formula summary', () => {
    expect(lintPackCard(ok)).toEqual({ ok: true });
  });

  it('fails the live HMRC problem-not-offer line', () => {
    const r = lintPackCard({
      ...ok,
      summary:
        'HMRC can refuse a building subcontractor the right to be paid in full, so the contractor must withhold part of every invoice',
    });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.fails).toContain('summary-buyer');
  });

  it('fails a carer line with no outcome', () => {
    const r = lintPackCard({
      ...ok,
      summary: 'A carer who uses a direct payment to employ a personal assistant is legally the employer',
    });
    expect(r.ok).toBe(false);
  });

  it('fails a dataset line with no buyer', () => {
    const r = lintPackCard({
      ...ok,
      summary: 'A dataset of tribunal outcomes and DWP recalculation rules, built from freedom of information requests',
    });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.fails).toContain('summary-buyer');
  });

  it('fails a repeated expansion', () => {
    const r = lintPackCard({
      ...ok,
      summary: 'A noise tool under British Standard British Standard (BS) 4142 for site managers.',
    });
    expect(r.ok).toBe(false);
    if (!r.ok) {
      expect(r.fails.some((f) => f === 'summary-bracket' || f === 'summary-bigram')).toBe(true);
    }
  });

  it('fails a bracketed acronym', () => {
    const r = lintPackCard({ ...ok, summary: 'A register for (IP) filings so founders keep their rights.' });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.fails).toContain('summary-bracket');
  });

  it('fails a leading Not', () => {
    const r = lintPackCard({ ...ok, summary: 'Not a loan tool for carers, so they avoid a fine.' });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.fails).toContain('summary-leading-not');
  });

  it('fails a banned word in the title', () => {
    const r = lintPackCard({ ...ok, title: 'A business idea that survived our filter' });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.fails).toContain('title-banned');
  });
});
