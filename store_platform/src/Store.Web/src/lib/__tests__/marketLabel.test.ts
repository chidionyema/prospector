import { describe, expect, it } from 'vitest';

import { marketLabel } from '@/lib/api/client';

/**
 * The shelf prints its counts as one `·`-joined series:
 *   `${n} ${marketLabel(market)} packs` · ... · `${total} in total`
 *
 * So a market label containing a `·` makes the line unreadable. Live on 2026-08-19 the home
 * page read "5 US · GA packs · 2 US · FL packs · 1 US · CA packs · 1 US · TX packs": the
 * separator between items and the separator inside an item were the same character, and there
 * was no way to tell where one count ended.
 */
describe('marketLabel', () => {
  it('never returns the character the count line joins with', () => {
    for (const code of ['us', 'uk', 'us-ga', 'us-fl', 'us-ca', 'us-tx', 'de-by']) {
      expect(marketLabel(code)).not.toContain('·');
    }
  });

  it('renders a subdivision so it survives being one item in a joined list', () => {
    const line = [`5 ${marketLabel('us-ga')} packs`, `2 ${marketLabel('us-fl')} packs`].join(' · ');
    expect(line).toBe('5 US (GA) packs · 2 US (FL) packs');
    expect(line.split(' · ')).toHaveLength(2);
  });

  it('leaves a plain market alone and falls back to the raw code', () => {
    expect(marketLabel('uk')).toBe('UK');
    expect(marketLabel('us')).toBe('US');
    expect(marketLabel('ie')).toBe('IE');
    expect(marketLabel()).toBe('');
  });
});
