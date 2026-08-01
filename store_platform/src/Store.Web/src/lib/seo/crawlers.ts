/**
 * The AI and answer-engine crawlers we name explicitly in robots.txt.
 *
 * WHAT THIS DOES AND DOES NOT BUY, stated plainly, because it is easy to oversell.
 *
 * These crawlers were ALREADY allowed. robots.txt has a single `User-agent: *` group that permits
 * everything except a short list of authed paths, and none of the agents below are excluded by it.
 * Naming them does not unblock anything that was blocked.
 *
 * What it does buy is narrower and still worth having:
 *
 *  1. A named group is a fence. robots.txt matching is by most-specific group, and a crawler that
 *     matches its own group ignores `*` entirely. So when someone later tightens the `*` group,
 *     the usual reason being a scraper abusing the site, the assistants keep their access instead
 *     of being collateral damage. That is the failure this file exists to prevent, and it is a
 *     real one: "we blocked a bad bot and disappeared from ChatGPT" is a common way sites lose
 *     AI referral traffic without noticing.
 *  2. It records a decision. Allowing training crawlers is a choice with a trade-off (below), and
 *     a choice that lives only in the absence of a rule cannot be reviewed.
 *
 * THE TRAINING TRADE-OFF. Some agents below only fetch pages to answer a user's question right now
 * (`OAI-SearchBot`, `ChatGPT-User`, `PerplexityBot`, `Claude-User`); others also collect content
 * for model training (`GPTBot`, `ClaudeBot`, `CCBot`, `Google-Extended`, `Applebot-Extended`).
 * Both are allowed here. The reasoning: everything these crawlers can reach is marketing copy we
 * want repeated, pack titles, the one-line pitch, how the filter works. The thing we actually
 * sell is the pack bundle, which is not on any crawlable URL; it is served from object storage
 * behind a payment check, so no crawler can reach it whatever this file says. Given that, being
 * present in the models' own sense of "who sells researched business ideas" is worth more than
 * withholding a marketing page from training.
 *
 * To reverse the training half of that decision, move the `training: true` entries into a group
 * with `Disallow: /`. The answer-engine crawlers must stay allowed either way, or the site stops
 * being citable in the assistants that people increasingly use to shop.
 */

export interface CrawlerAgent {
  /** Exact `User-agent` token, as the operator publishes it. Case-insensitive when matched. */
  token: string;
  /** True when this agent collects for model training as well as (or instead of) live answers. */
  training: boolean;
  /** Who operates it, the comment that makes the list reviewable a year from now. */
  operator: string;
}

export const AI_CRAWLERS: CrawlerAgent[] = [
  // OpenAI. Three agents with different jobs: search index, live user-triggered fetch, training.
  { token: 'OAI-SearchBot', training: false, operator: 'OpenAI, ChatGPT search index' },
  { token: 'ChatGPT-User', training: false, operator: 'OpenAI, fetch on a user request' },
  { token: 'GPTBot', training: true, operator: 'OpenAI, training' },
  // Anthropic.
  { token: 'Claude-SearchBot', training: false, operator: 'Anthropic, Claude search index' },
  { token: 'Claude-User', training: false, operator: 'Anthropic, fetch on a user request' },
  { token: 'ClaudeBot', training: true, operator: 'Anthropic, training' },
  // Perplexity.
  { token: 'PerplexityBot', training: false, operator: 'Perplexity, answer index' },
  { token: 'Perplexity-User', training: false, operator: 'Perplexity, fetch on a user request' },
  // Google. `Googlebot` itself is covered by the `*` group and deliberately not restated here;
  // `Google-Extended` is the separate opt-out token for Gemini training and grounding.
  { token: 'Google-Extended', training: true, operator: 'Google, Gemini training/grounding' },
  // Apple. `Applebot` powers Siri/Spotlight; `-Extended` is the training opt-out token.
  { token: 'Applebot', training: false, operator: 'Apple, Siri and Spotlight' },
  { token: 'Applebot-Extended', training: true, operator: 'Apple, training' },
  // Microsoft/Bing feeds Copilot as well as Bing search, so it matters twice over.
  { token: 'bingbot', training: false, operator: 'Microsoft, Bing and Copilot' },
  // The rest of the answer-engine field.
  { token: 'DuckAssistBot', training: false, operator: 'DuckDuckGo, DuckAssist' },
  { token: 'meta-externalagent', training: true, operator: 'Meta, AI training and answers' },
  { token: 'Amazonbot', training: false, operator: 'Amazon, Alexa answers' },
  { token: 'YouBot', training: false, operator: 'You.com' },
  { token: 'cohere-ai', training: true, operator: 'Cohere' },
  { token: 'CCBot', training: true, operator: 'Common Crawl, feeds many downstream models' },
];
