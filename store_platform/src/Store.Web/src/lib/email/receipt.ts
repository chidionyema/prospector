/**
 * L6 - The receipt email template.
 *
 * The audit (§11.3) said: "The voice is world-class. Should be in the
 * email receipts. The Stripe receipt is the first email. The receipt is
 * the voice. The buyer receives the receipt and reads the voice."
 *
 * The template is plain text + a small HTML wrapper, written in the
 * Mumchimp voice (source-or-die, refutational, not promotional). It
 * includes the permanent access link, the kill log, and a 14-day refund
 * reminder. It is deliberately not a corporate "Thank you for your
 * purchase!" boilerplate.
 *
 * The Mailjet worker is not yet wired (the .env.production does not have
 * MAILJET_API_KEY/SECRET configured). When configured, this template is
 * the input to the worker's render step.
 */
import { SITE_URL } from '@/lib/config';

export interface ReceiptOrder {
  id: string;
  packTitle: string;
  packId: string;
  buyerEmail: string;
  orderPath: string; // The permanent access link (e.g., /orders/abc123)
  amountGbp: number;
}

const SUBJECT_LINE =
  'Your {brand} pack is ready. Here is your permanent access link.';

const REFUND_WINDOW_DAYS = 14;

export function renderReceiptSubject(brand: string): string {
  return SUBJECT_LINE.replace('{brand}', brand);
}

/**
 * Plain-text body. Kept simple, no HTML, so it survives any email
 * client and any accessibility tool.
 */
export function renderReceiptText(order: ReceiptOrder, brand: string): string {
  return [
    `Your ${brand} pack is ready.`,
    '',
    `Pack: ${order.packTitle}`,
    `Amount: GBP ${order.amountGbp.toFixed(2)}`,
    '',
    'Your permanent access link. This is the only way back to your pack. Bookmark it or copy it somewhere safe.',
    '',
    `  ${order.orderPath}`,
    '',
    'Every claim in your pack cites a retrievable source. The QA report inside the pack lists every source, and the rejected list names the ideas that did not pass the checks.',
    '',
    `If the pack is not what the description said, email us within ${REFUND_WINDOW_DAYS} days and we refund in full. No forms, no friction. The full policy is on the refund page.`,
    '',
    `Read about how the checks work on the about page.`,
    '',
    `Mumchimp`,
  ].join('\n');
}

/**
 * HTML body. Inline styles only (most email clients strip <style>). The
 * layout is single-column, max-width 600px, system font stack. No
 * external assets, no images, no JavaScript.
 */
export function renderReceiptHtml(order: ReceiptOrder, brand: string): string {
  const safeOrderPath = escapeHtml(order.orderPath);
  // The site's own origin, from NEXT_PUBLIC_SITE_URL (one place, src/lib/config.ts); no hostname
  // is written here. Without it the link stays relative, as it always did for a second brand.
  const rejectedUrl = SITE_URL ? `${SITE_URL}/rejected` : '/rejected';
  const safePackTitle = escapeHtml(order.packTitle);
  const safeBrand = escapeHtml(brand);
  return [
    '<!doctype html>',
    '<html>',
    '<head><meta charset="utf-8"><title>Your pack is ready</title></head>',
    '<body style="margin:0;padding:0;background-color:#ffffff;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica Neue,Arial,sans-serif;color:#0A0A0A;line-height:1.5;">',
    '<div style="max-width:600px;margin:0 auto;padding:32px 24px;">',
    `<p style="margin:0 0 24px 0;font-size:12px;font-weight:500;color:#71717A;">${safeBrand}</p>`,
    `<h1 style="margin:0 0 16px 0;font-size:28px;font-weight:800;line-height:1.15;letter-spacing:-0.02em;color:#0A0A0A;">Your pack is ready.</h1>`,
    `<p style="margin:0 0 24px 0;font-size:16px;color:#0A0A0A;">${safePackTitle} is yours. Every claim in it cites a retrievable source. The QA report inside the pack lists every source, and the <a href="${rejectedUrl}" style="color:#0A0A0A;text-decoration:underline;">rejected ideas</a> lists the ${'{count}'} ideas that did not pass the checks.</p>`,
    '<div style="margin:0 0 24px 0;padding:16px;border:1px solid #E5E5E5;background-color:#F7F7F5;">',
    '<p style="margin:0 0 8px 0;font-size:12px;font-weight:500;color:#71717A;">Permanent access link</p>',
    `<p style="margin:0;font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;font-size:13px;word-break:break-all;color:#0A0A0A;">${safeOrderPath}</p>`,
    '</div>',
    `<p style="margin:0 0 24px 0;font-size:14px;color:#0A0A0A;">Bookmark it or copy it somewhere safe. This is the only way back to your pack if you lose the link.</p>`,
    `<p style="margin:0 0 24px 0;font-size:14px;color:#0A0A0A;">If the pack is not what the description said, email us within ${REFUND_WINDOW_DAYS} days and we refund in full. No forms, no friction. The full policy is on the <a href="${safeBrand === 'Mumchimp' ? 'https://mumchimp.com/refund' : '/refund'}" style="color:#0A0A0A;text-decoration:underline;">refund page</a>.</p>`,
    '<hr style="border:0;border-top:1px solid #E5E5E5;margin:24px 0;">',
    `<p style="margin:0;font-size:11px;color:#6B6B6B;">The voice is source-or-die. Sourced, not sold. Refutational, not promotional.</p>`,
    '</div>',
    '</body>',
    '</html>',
  ].join('\n');
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
