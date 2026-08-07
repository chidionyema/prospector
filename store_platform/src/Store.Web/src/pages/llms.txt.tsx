import type { GetServerSideProps } from 'next';

import { fetchCatalog, type Pack } from '@/lib/api/client';
import { checksSentence } from '@/lib/checks';
import { priceRange, formatGbp } from '@/lib/priceRange';

/**
 * `/llms.txt`, a curated, plain-Markdown map of this site for large language models.
 *
 * WHAT IT IS. A proposed convention (llmstxt.org) answering the same question robots.txt answers
 * for crawlers, but for a model with a limited context window: not "what may you read" but "what
 * is worth reading, and what is this site actually for". An assistant that fetches this gets the
 * catalogue and the honest scope of the product in one request, instead of inferring it from a
 * 344KB marketing page whose content is mostly layout.
 *
 * HONESTY. It is adopted, not universal, no search engine is known to require it, and it is not
 * a ranking factor. It is cheap (one route, no build step) and it is the only artefact on the site
 * that states, in machine-first prose, what a pack is and is not. That is the case for it; there
 * is no evidence-backed traffic claim to make here and none is implied.
 *
 * WHY IT MIRRORS THE SITEMAP. The pack list is generated from the live catalogue for the same
 * reason the sitemap is: a hand-maintained list goes stale the first time the engine publishes,
 * and a stale list is worse than none because it teaches a model URLs that 404.
 *
 * Deliberately NOT here: anything from inside a pack. The bundle is the product; this file
 * advertises the shelf. The manifest.jsonld paragraph is not an exception to that: it describes the
 * SHAPE of what a buyer receives, which is the one thing an agent evaluating the purchase needs and
 * cannot get any other way, and quotes none of the content.
 */

// Keep the file small enough to be read in full. The catalogue is newest-first, so a cap keeps the
// most recent work and drops the tail, and the sitemap still lists every pack for crawlers that
// want the complete set.
const MAX_PACKS = 60;

function originFromReq(headers: { host?: string; 'x-forwarded-proto'?: string }): string {
  const rawHost = headers.host ?? 'localhost:3000';
  const fwdProto = headers['x-forwarded-proto'];
  const proto =
    fwdProto === 'http' || fwdProto === 'https'
      ? fwdProto
      : rawHost.startsWith('localhost')
        ? 'http'
        : 'https';
  // Same rail as robots.txt/sitemap.xml: the Host header is attacker-controllable and is
  // interpolated into the body below, so only a clean hostname[:port] is accepted.
  if (!/^[a-zA-Z0-9.-]+(:\d+)?$/.test(rawHost)) {
    return (process.env.NEXT_PUBLIC_SITE_URL || 'https://localhost:3000').replace(/\/$/, '');
  }
  return `${proto}://${rawHost}`;
}

const SAFE_PACK_ID = /^[A-Za-z0-9_-]{1,64}$/;

/** Markdown link text must not contain unescaped `[` or `]`, and a pack title is operator-authored
 *  prose that may. Collapse whitespace too: a title with a newline would break the list item. */
export function markdownSafe(text: string): string {
  return text.replace(/\s+/g, ' ').replace(/([[\]])/g, '\\$1').trim();
}

function packLine(pack: Pack, origin: string): string {
  const title = markdownSafe(pack.title || pack.id);
  const summary = markdownSafe(pack.cardLine || pack.oneLine || '');
  return `- [${title}](${origin}/pack/${pack.id})${summary ? `: ${summary}` : ''}`;
}

export const getServerSideProps: GetServerSideProps = async ({ req, res }) => {
  const origin = originFromReq(req.headers as { host?: string; 'x-forwarded-proto'?: string });

  // Best-effort, exactly like the sitemap: a catalogue outage degrades this to the guide sections
  // rather than 500ing. A file that fails to load teaches a model nothing.
  let packs: Pack[] = [];
  try {
    packs = (await fetchCatalog()).filter((pack) => SAFE_PACK_ID.test(pack.id));
  } catch (error) {
    console.error('llms.txt: catalog fetch failed, emitting guide sections only:', error);
  }

  /* Computed, never written: this file is what an assistant quotes when asked what Mumchimp
     sells, so a stale price here is repeated by third parties long after a deploy fixes the site.
     No catalogue (the fetch above failed) means no price clause at all. */
  const range = priceRange(packs);
  const priceClause = range
    ? range.uniform
      ? ` for ${range.label} each`
      : `, priced per pack from ${formatGbp(range.min)} to ${formatGbp(range.max)} (most are ${formatGbp(range.mode)})`
    : '';

  const body = `# Mumchimp

> Mumchimp sells researched business opportunity packs${priceClause}. Every pack is one business
> idea that passed an automated kill-first filter: ${checksSentence()}. It then survived an
> adversarial review. Each claim in a pack cites a retrievable source.

A pack is a zip of plain Markdown (5,000+ words), eight documents: an executive summary, a build
spec, a go-to-market plan, an operations plan, a financial model, a first-week checklist, marketing
assets, and a QA report with a source behind every claim. It is delivered instantly on payment and
carries a 14-day, no-questions refund.

Every pack also ships manifest.jsonld, a JSON-LD document written for the agent rather than the
reader. It lists every file with its sha256 and its reading position, and it carries the
verification record as schema.org ClaimReview nodes, one per check, each with the verdict, the
confidence, the rationale, and the sources it cites. Every source node carries the URL, the fetch
date, and the exact passage the model was shown when it ruled. That last part is the point: an agent
can re-check a ruling against the same text the ruling was formed from, offline, without refetching
a page that may since have changed. Verdicts are supported, refuted, or unverifiable, and
unverifiable is a finding (retrieval ran and no passage settled it), not a missing value.

What a pack is NOT, stated so it is not inferred wrongly: it is not financial, legal, or investment
advice, and it is not a guarantee that the business will succeed. The guarantee is that the
analysis is grounded and sourced. Execution is the buyer's.

Ideas that FAIL the filter are published too, with the sourced reason they were rejected, that is
the kill log, and it is the evidence the filter is real rather than a marketing claim.

## Guide

- [How it works](${origin}/how-it-works): the checks, the adversarial review, and what lands in the zip.
- [Sample pack](${origin}/sample): a real pack's contents, readable without buying.
- [Kill log](${origin}/kill-log): ideas rejected by the filter, each with its sourced reason.
- [FAQ](${origin}/faq): what you are buying, delivery, refunds, and licensing.

## Packs

${packs.length > 0 ? packs.slice(0, MAX_PACKS).map((pack) => packLine(pack, origin)).join('\n') : '- (catalogue temporarily unavailable)'}

## Optional

- [Full URL list](${origin}/sitemap.xml): every indexable page, including packs beyond the ${MAX_PACKS} listed above.
- [Terms](${origin}/terms) · [Privacy](${origin}/privacy) · [Refund policy](${origin}/refund)
- Contact: support@mumchimp.com
`;

  res.setHeader('Content-Type', 'text/plain; charset=utf-8');
  res.setHeader('Cache-Control', 'public, max-age=3600');
  res.write(body);
  res.end();
  return { props: {} };
};

// Route only exists to serve the body above; nothing renders.
export default function LlmsTxt() {
  return null;
}
