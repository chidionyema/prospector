import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { killTagLabel } from '@/components/marketing/TodayRibbon';
import latestKill from '@/data/latest-kill.json';

/**
 * The dark strip is chrome, so it is on every marketing page or it is on none. And its tag states
 * a dated fact, so it must never say "today" from a build-time file.
 */
describe('the dark strip above the header', () => {
  const layout = readFileSync(
    path.join(process.cwd(), 'src/components/marketing/MarketingLayout.tsx'),
    'utf8',
  );

  it('is rendered by the shared marketing shell, so every page carries it', () => {
    expect(layout).toContain('<TodayRibbon />');
  });

  it('prints the date the idea was killed, never the word today', () => {
    expect(killTagLabel('2026-08-07')).toBe('Killed 7 Aug');
    expect(killTagLabel('2026-12-25')).toBe('Killed 25 Dec');
    expect(killTagLabel('not-a-date')).toBe('Killed');
    expect(killTagLabel('2026-13-01')).toBe('Killed');
    expect(killTagLabel(latestKill.date).toLowerCase()).not.toContain('today');
  });

  it('has a title and an ISO date to render', () => {
    expect(latestKill.title.length).toBeGreaterThan(10);
    expect(latestKill.date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it('reads no clock, because a hydration correction here moves the whole page', () => {
    const source = readFileSync(
      path.join(process.cwd(), 'src/components/marketing/TodayRibbon.tsx'),
      'utf8',
    );
    const code = source.replace(/\/\*[\s\S]*?\*\//g, '');
    expect(code).not.toContain('new Date(');
    expect(code).not.toContain('Date.now(');
  });
});
