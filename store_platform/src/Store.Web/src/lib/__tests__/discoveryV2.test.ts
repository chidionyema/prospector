import { describe, expect, it } from 'vitest';

/**
 * Contract tests for extractIntent and matchReasons (discovery v2).
 *
 * These tests FAIL until the implementation exists in lib/discovery.ts.
 * They define "done" for Stage 1: the NLP-light intent extraction that
 * maps natural language to facet values.
 *
 * Vocabulary matches the actual facet values from lib/facets.ts:
 *   Advantage: code, nocode, sales, ops, audience
 *   Commitment: evenings, part_time, full_time
 *   Payer: b2b, b2c, b2g
 *   Effort: automatable, part_automatable, hands_on
 */

import { extractIntent, matchReasons } from '@/lib/discovery';
import type { FacetedPack } from '@/lib/discovery';

describe('extractIntent — natural language → facet values', () => {
  it('extracts advantage:code from "I can code/build software"', () => {
    const result = extractIntent('I can code and build software');
    expect(result.advantage).toContain('code');
  });

  it('extracts advantage:sales from "I am good at sales and marketing"', () => {
    const result = extractIntent('I am good at sales and marketing');
    expect(result.advantage).toContain('sales');
  });

  it('extracts advantage:ops from "operations and automation expert"', () => {
    const result = extractIntent('operations and automation expert');
    expect(result.advantage).toContain('ops');
  });

  it('extracts commitment:part_time from "evenings and weekends"', () => {
    const result = extractIntent('I only have evenings and weekends');
    expect(result.commitment).toBe('part_time');
  });

  it('extracts commitment:part_time from "side hustle" and "spare time"', () => {
    expect(extractIntent('side hustle').commitment).toBe('part_time');
    expect(extractIntent('spare time').commitment).toBe('part_time');
    expect(extractIntent('part-time').commitment).toBe('part_time');
  });

  it('extracts commitment:full_time from "full-time" and "quit my job"', () => {
    expect(extractIntent('full-time commitment').commitment).toBe('full_time');
    expect(extractIntent('ready to quit my job').commitment).toBe('full_time');
  });

  it('extracts commitment:evenings from "evenings"', () => {
    expect(extractIntent('evenings only').commitment).toBe('evenings');
  });

  it('extracts payer:b2b from "B2B" and "selling to businesses"', () => {
    expect(extractIntent('B2B saas').payer).toBe('b2b');
    expect(extractIntent('selling to businesses').payer).toBe('b2b');
    expect(extractIntent('enterprise software').payer).toBe('b2b');
  });

  it('extracts payer:b2c from "B2C" and "selling to consumers"', () => {
    expect(extractIntent('B2C product').payer).toBe('b2c');
    expect(extractIntent('selling to consumers').payer).toBe('b2c');
  });

  it('extracts effort:automatable from "passive" and "hands-off"', () => {
    expect(extractIntent('passive income').effort).toBe('automatable');
    expect(extractIntent('hands-off business').effort).toBe('automatable');
    expect(extractIntent('automated').effort).toBe('automatable');
  });

  it('extracts effort:hands_on from "hands-on" and "active"', () => {
    expect(extractIntent('hands-on work').effort).toBe('hands_on');
    expect(extractIntent('active involvement').effort).toBe('hands_on');
  });

  it('extracts multiple facets from a compound sentence', () => {
    const result = extractIntent(
      'I can code, want something B2B that I can run on evenings',
    );
    expect(result.advantage).toContain('code');
    expect(result.payer).toBe('b2b');
    expect(result.commitment).toBe('evenings');
  });

  it('extracts multiple advantages from "I can code and sell"', () => {
    const result = extractIntent('I can code and sell');
    expect(result.advantage).toContain('code');
    expect(result.advantage).toContain('sales');
  });

  it('returns empty object for empty string', () => {
    expect(extractIntent('')).toEqual({});
  });

  it('returns empty object for irrelevant text', () => {
    const result = extractIntent('I like pizza and watching movies');
    expect(result.advantage).toBeUndefined();
    expect(result.commitment).toBeUndefined();
    expect(result.payer).toBeUndefined();
    expect(result.effort).toBeUndefined();
    expect(result.mechanism).toBeUndefined();
  });

  it('is case-insensitive', () => {
    const result = extractIntent('B2B SaaS for EVENINGS where I can CODE');
    expect(result.payer).toBe('b2b');
    expect(result.commitment).toBe('evenings');
    expect(result.advantage).toContain('code');
  });

  it('handles partial matches gracefully — "developer" → code', () => {
    const result = extractIntent('I am a developer');
    expect(result.advantage).toContain('code');
  });

  it('does not match substrings accidentally — "part" alone does not match part_time', () => {
    const result = extractIntent('I want to be part of something');
    // "part" appears inside "part" of but should not match part_time
    // It should not match anything since we use word-boundary matching
    expect(result.commitment).toBeUndefined();
  });
});

describe('matchReasons — why this pack fits the intent', () => {
  const basePack: FacetedPack = {
    id: 'test-1',
    title: 'Test Pack',
    advantages: ['code'],
    payer: 'b2b',
    commitment: 'part_time',
    effort: 'automatable',
  };

  it('returns match reasons when pack matches intent facets', () => {
    const reasons = matchReasons(basePack, {
      q: '',
      advantage: ['code'],
      payer: 'b2b',
      commitment: null,
      effort: null,
      mechanism: null,
      sector: null,
    });
    expect(reasons.length).toBeGreaterThan(0);
    expect(reasons.length).toBeLessThanOrEqual(2);
  });

  it('returns empty array when pack does not match', () => {
    const reasons = matchReasons(basePack, {
      q: '',
      advantage: ['sales'],
      payer: 'b2c',
      commitment: null,
      effort: null,
      mechanism: null,
      sector: null,
    });
    expect(reasons).toEqual([]);
  });

  it('returns at most 2 reasons even when many facets match', () => {
    const reasons = matchReasons(basePack, {
      q: '',
      advantage: ['code'],
      payer: 'b2b',
      commitment: 'part_time',
      effort: 'automatable',
      mechanism: null,
      sector: null,
    });
    expect(reasons.length).toBeLessThanOrEqual(2);
  });
});
