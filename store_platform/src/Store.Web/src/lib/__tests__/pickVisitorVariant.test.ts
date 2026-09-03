import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { pickVisitorVariant, VARIANT_COOKIE, variantSetCookie } from '@/lib/getCopyVariant';
import { VARIANTS } from '@/lib/copyConfig';

describe('pickVisitorVariant', () => {
  it('keeps crawlers on the control headline', () => {
    expect(pickVisitorVariant(undefined, undefined, 'Mozilla/5.0 (compatible; Googlebot/2.1)', 0.9)).toEqual({
      key: 'a',
      persist: false,
    });
  });

  it('lets a query preview any variant and persists it', () => {
    expect(pickVisitorVariant('b', 'a', undefined, 0)).toEqual({ key: 'b', persist: true });
    expect(pickVisitorVariant('c', undefined, undefined, 0)).toEqual({ key: 'c', persist: true });
  });

  it('reuses a returning visitor cookie', () => {
    expect(pickVisitorVariant(undefined, 'b', undefined, 0)).toEqual({ key: 'b', persist: false });
  });

  it('splits first visits half and half', () => {
    expect(pickVisitorVariant(undefined, undefined, undefined, 0.49)).toEqual({ key: 'a', persist: true });
    expect(pickVisitorVariant(undefined, undefined, undefined, 0.5)).toEqual({ key: 'b', persist: true });
  });

  it('writes the cookie the hook already reads', () => {
    expect(variantSetCookie('b')).toContain(`${VARIANT_COOKIE}=b`);
  });
});

describe('homepage headlines under test', () => {
  it('keeps the current line as control and the stronger line as challenger', () => {
    expect(VARIANTS.a.globalHookLead).toBe('Business ideas with the research already done.');
    expect(VARIANTS.b.globalHookLead).toBe('Skip 6 months of research. Launch a business that\'s already vetted.');
  });
});

describe('rejected heading space', () => {
  it('prints the count and ideas as one string so the space cannot be compiled away', () => {
    const src = readFileSync(join(__dirname, '../../pages/kill-log.tsx'), 'utf8');
    expect(src).toMatch(/`\$\{killed\.toLocaleString\('en-GB'\)\} ideas that didn't pass\.`/);
  });
});
