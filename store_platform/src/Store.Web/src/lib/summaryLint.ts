/**
 * Card summary lint (founder brief 2026-09-02, §3).
 *
 * Every pack on a card: [what it is] for [who], so [outcome]. One sentence, 8-22 words.
 * A pack that fails does not go on the shelf.
 */

const BANNED =
  /\b(kill|killed|kills|die|died|dead|death|survive|survived|survivor|destroy|sink|landmine|doom|graveyard)\b/i;

const BRACKET = /\([^)]{1,12}\)/;
const HAS_FOR = /\bfor\b/i;
const HAS_SO = /\bso\b/i;

export type PackLintInput = {
  title: string;
  summary: string;
  category?: string | null;
  market?: string | null;
  publishedAt?: string | null;
  verifiedAt?: string | null;
};

export type LintFail =
  | 'title-length'
  | 'title-bracket'
  | 'title-banned'
  | 'summary-words'
  | 'summary-sentences'
  | 'summary-bracket'
  | 'summary-banned'
  | 'summary-leading-not'
  | 'summary-buyer'
  | 'summary-bigram'
  | 'category'
  | 'market'
  | 'date';

export type LintResult = { ok: true } | { ok: false; fails: LintFail[] };

function wordCount(text: string): number {
  return text.trim().split(/\s+/).filter(Boolean).length;
}

function sentenceCount(text: string): number {
  const parts = text.trim().split(/(?<=[.!?])\s+/).filter((s) => s.trim());
  return Math.max(parts.length, text.trim() ? 1 : 0);
}

function repeatedBigram(text: string): boolean {
  const words = text.toLowerCase().replace(/[().,:;]/g, '').split(/\s+/).filter(Boolean);
  for (let i = 0; i < words.length - 3; i += 1) {
    const a = `${words[i]} ${words[i + 1]}`;
    for (let j = i + 2; j < words.length - 1; j += 1) {
      if (`${words[j]} ${words[j + 1]}` === a && words[i].length > 2) return true;
    }
  }
  return false;
}

export function lintPackCard(pack: PackLintInput): LintResult {
  const fails: LintFail[] = [];
  const title = (pack.title ?? '').trim();
  const summary = (pack.summary ?? '').trim();

  if (title.length === 0 || title.length > 70) fails.push('title-length');
  if (BRACKET.test(title)) fails.push('title-bracket');
  if (BANNED.test(title)) fails.push('title-banned');

  const words = wordCount(summary);
  if (words < 8 || words > 22) fails.push('summary-words');
  if (sentenceCount(summary) !== 1) fails.push('summary-sentences');
  if (BRACKET.test(summary)) fails.push('summary-bracket');
  if (BANNED.test(summary)) fails.push('summary-banned');
  if (/^not\b/i.test(summary)) fails.push('summary-leading-not');
  if (!HAS_FOR.test(summary) || !HAS_SO.test(summary)) fails.push('summary-buyer');
  if (repeatedBigram(summary)) fails.push('summary-bigram');

  if (!pack.category) fails.push('category');
  if (!pack.market) fails.push('market');
  if (!pack.publishedAt && !pack.verifiedAt) fails.push('date');

  return fails.length === 0 ? { ok: true } : { ok: false, fails };
}

const HARD: LintFail[] = ["title-banned", "title-bracket", "summary-banned", "summary-bracket", "summary-leading-not"];

/** Off the shelf only for banned words, brackets, and a leading Not. Formula lint stays in CI. */
export function packsOnShelf<T extends { title: string; oneLine?: string; cardLine?: string; sector?: string | null; market?: string | null; verifiedAt?: string | null }>(
  packs: readonly T[],
): T[] {
  return packs.filter((pack) => {
    const result = lintPackCard({
      title: pack.title,
      summary: pack.cardLine || pack.oneLine || "",
      category: pack.sector,
      market: pack.market,
      verifiedAt: pack.verifiedAt,
    });
    if (result.ok) return true;
    return !result.fails.some((f) => HARD.includes(f));
  });
}
