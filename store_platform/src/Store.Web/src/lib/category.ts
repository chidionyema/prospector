/**
 * Client-derived industry taxonomy. Packs ship without a sector field, so we infer one from the
 * title + one-liner to give each card a colour, an icon, and a scannable label. The class strings
 * are FULL LITERALS (gradient + tint) so Tailwind keeps them at build time; never interpolate them.
 *
 * This is presentation only. The day the engine emits a real `sector` on the Pack, switch
 * `categoryFor` to read it and keep this table as the colour/icon map.
 */
import type { IconName } from '@/components/ui/Icon';

export interface Category {
  key: string;
  label: string;
  icon: IconName;
  /** Full-height card cover gradient. */
  cover: string;
  /** Label-pill tint (bg + text + inset ring), reads on white. */
  chip: string;
  /** Small accent text colour. */
  accent: string;
}

// Order = priority. The first pattern that matches the pack's text wins, so put the more specific
// sectors (probate, payments) above the broad ones (garden, operations).
const TABLE: Array<{ match: RegExp; cat: Category }> = [
  {
    match: /probate|deceased|estate|bereave|clear[- ]?out|clearance|inherit|locker|\bwill\b/i,
    cat: {
      key: 'estate',
      label: 'Estate & probate',
      icon: 'gavel',
      cover: 'bg-[linear-gradient(135deg,#4f46e5_0%,#7c3aed_100%)]',
      chip: 'bg-indigo-50 text-indigo-700 ring-1 ring-inset ring-indigo-600/20',
      accent: 'text-indigo-600',
    },
  },
  {
    // Garden wins over trades: a "gardening & handyman" pack reads as garden, and none of the real
    // trades packs (tradie time-capture, builder warranty) carry a garden word.
    match: /garden|harvest|produce|vegetable|allotment|landscap|\bgrow|outdoor|nursery/i,
    cat: {
      key: 'garden',
      label: 'Garden & outdoor',
      icon: 'home',
      cover: 'bg-[linear-gradient(135deg,#0d9488_0%,#059669_100%)]',
      chip: 'bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-600/20',
      accent: 'text-emerald-700',
    },
  },
  {
    // Trades wins over payments: "the tradie's time-capture" says "recover lost time", which would
    // false-match payments. A pack that is literally a tradie/builder service is a trades pack.
    match: /builder|warranty|\bsnag|inspection|tradie|\btrade|construction|completion|handyman|repair/i,
    cat: {
      key: 'trades',
      label: 'Trades & building',
      icon: 'building',
      cover: 'bg-[linear-gradient(135deg,#d97706_0%,#ea580c_100%)]',
      chip: 'bg-amber-50 text-amber-800 ring-1 ring-inset ring-amber-600/20',
      accent: 'text-amber-700',
    },
  },
  {
    // Deliberately NOT matching the bare word "fee" — many honest business models take a fee
    // ("fixed fee from the installer") without being a payments/recovery business.
    match: /\bvet\b|veterinary|payment recovery|recover|\bdebt|invoic|arrears|chasing|extractor/i,
    cat: {
      key: 'payments',
      label: 'Payments & recovery',
      icon: 'wallet',
      cover: 'bg-[linear-gradient(135deg,#2563eb_0%,#0284c7_100%)]',
      chip: 'bg-sky-50 text-sky-700 ring-1 ring-inset ring-sky-600/20',
      accent: 'text-sky-600',
    },
  },
  {
    match: /time[- ]?track|operations|\badmin|\bagent|office|broker|booking|scheduling|management/i,
    cat: {
      key: 'operations',
      label: 'Operations',
      icon: 'briefcase',
      cover: 'bg-[linear-gradient(135deg,#334155_0%,#4338ca_100%)]',
      chip: 'bg-slate-100 text-slate-700 ring-1 ring-inset ring-slate-500/20',
      accent: 'text-slate-600',
    },
  },
];

const DEFAULT: Category = {
  key: 'opportunity',
  label: 'Opportunity',
  icon: 'briefcase',
  cover: 'bg-[linear-gradient(135deg,#0f172a_0%,#334155_100%)]',
  chip: 'bg-slate-100 text-slate-700 ring-1 ring-inset ring-slate-500/20',
  accent: 'text-slate-600',
};

export function categoryFor(input: { title?: string; oneLine?: string }): Category {
  // Title first — it names what the pack IS. One-liners list examples ("for trades like gardeners,
  // plumbers...") that misclassify when matched directly, so they are only a fallback.
  const title = input.title ?? '';
  for (const row of TABLE) {
    if (row.match.test(title)) return row.cat;
  }
  const full = `${title} ${input.oneLine ?? ''}`;
  for (const row of TABLE) {
    if (row.match.test(full)) return row.cat;
  }
  return DEFAULT;
}
