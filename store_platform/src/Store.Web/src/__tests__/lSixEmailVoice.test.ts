import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

function readSource(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), 'utf8');
}

function existsRelative(relativePath: string): boolean {
  return existsSync(fileURLToPath(new URL(relativePath, import.meta.url)));
}

/**
 * L6 - Voice in the email.
 *
 * The audit (§11.3) said: "The voice is world-class. Should be in the
 * email receipts. The Stripe receipt is the first email. The receipt is
 * the voice. The buyer receives the receipt and reads the voice."
 *
 * Out of scope: actually sending the email (the .env.production does not
 * yet have MAILJET_API_KEY/SECRET configured; the Audit runbook documents
 * the gap). The deliverable is the receipt template, written in the
 * Mumchimp voice, that the Mailjet worker can render when configured.
 */
describe('L6 - Voice in the email', () => {
  const templateExists = existsRelative('../lib/email/receipt.ts');

  it('declares an email receipt template module', () => {
    expect(
      templateExists,
      'lib/email/receipt.ts must exist',
    ).toBe(true);
  });

  it('exports a render function that takes an order and returns a string', () => {
    if (!templateExists) return;
    const source = readSource('../lib/email/receipt.ts');
    const hasRender =
      /export\s+function\s+render|export\s+const\s+render|module\.exports\s*=\s*render/.test(source);
    expect(
      hasRender,
      'lib/email/receipt.ts must export a render function',
    ).toBe(true);
  });

  it('rendered receipt uses the source-or-die voice', () => {
    if (!templateExists) return;
    const source = readSource('../lib/email/receipt.ts');
    const voice = /source-or-die|every claim cited|every source is cited|kill log|verified/i.test(source);
    expect(
      voice,
      'lib/email/receipt.ts must use the source-or-die voice',
    ).toBe(true);
  });

  it('rendered receipt includes the orderPath permanent access link', () => {
    if (!templateExists) return;
    const source = readSource('../lib/email/receipt.ts');
    const hasAccessLink = /orderPath|access\s*link|permanent\s*access|your\s*pack/i.test(source);
    expect(
      hasAccessLink,
      'lib/email/receipt.ts must include the permanent access link',
    ).toBe(true);
  });

  it('rendered receipt includes the kill log link', () => {
    if (!templateExists) return;
    const source = readSource('../lib/email/receipt.ts');
    const hasKillLog = /\/rejected|kill-?log/i.test(source);
    expect(
      hasKillLog,
      'lib/email/receipt.ts must link to the rejected ledger (/rejected, once /kill-log)',
    ).toBe(true);
  });
});
