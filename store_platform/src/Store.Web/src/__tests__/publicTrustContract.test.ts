import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

function source(path: string): string {
  return readFileSync(fileURLToPath(new URL(path, import.meta.url)), 'utf8');
}

function relativeLuminance(hex: string): number {
  const bytes = hex.replace('#', '').match(/.{2}/g);
  if (!bytes || bytes.length !== 3) throw new Error('Invalid colour token');
  const values = bytes.map((pair) => {
    const channel = parseInt(pair, 16) / 255;
    return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * values[0] + 0.7152 * values[1] + 0.0722 * values[2];
}
function contrast(foreground: string, background: string): number {
  const a = relativeLuminance(foreground);
  const b = relativeLuminance(background);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}
function token(css: string, name: string): string {
  const match = css.match(new RegExp('^\\s*' + name + ':\\s*(#[0-9A-Fa-f]{6})\\s*;', 'm'));
  if (!match) throw new Error('Missing token ' + name);
  return match[1];
}

describe('buyer-trust regressions', () => {
  it('keeps small informational text at WCAG AA contrast on paper and white', () => {
    const css = source('../styles/tokens.css');
    const foreground = token(css, '--subtle');
    for (const background of [token(css, '--bg'), token(css, '--surface')]) {
      expect(contrast(foreground, background)).toBeGreaterThanOrEqual(4.5);
    }
    expect(source('../../e2e/a11y.spec.ts')).not.toMatch(/'color-contrast'\s*:/);
  });
  it('gives the 14-day guarantee one meaning across the summary and the terms', () => {
    const policy = source('../pages/refund.tsx');
    expect(policy).toMatch(/For any pack you purchase/);
    expect(policy).toMatch(/14 day money back guarantee, no questions asked/);
    expect(policy).not.toMatch(/If a pack is not what the description said/);
    expect(policy).not.toMatch(/refund covers the pack not matching its description/);
  });
  it('does not publish conflicting support SLAs or delivery-time claims', () => {
    const policy = source('../pages/refund.tsx');
    expect(policy).not.toMatch(/under one\s+business day/i);
    expect(policy).not.toMatch(/within five working days/i);
    expect(policy).toMatch(/within three business days/);
    expect(policy).toMatch(/typically five to ten business days/);
  });
  it('never describes the entire unpublished research corpus as public', () => {
    const faq = source('../lib/faqContent.ts');
    expect(faq).toMatch(/publish a selection of rejected ideas/);
    expect(faq).not.toMatch(/They are published in public/);
    expect(faq).not.toMatch(/Everything on this site works today/);
  });
});
