import { LEGAL } from '@/lib/config';
import { checksSentence } from '@/lib/checks';
/* The document count is COUNTED, never typed. `PACK_CONTENTS` is pinned to the engine's own
   `BUNDLE_FILES` by `__tests__/packContents.test.ts`, and this is the answer a buyer reads before
   paying: the last time the number was written out by hand it said four while the bundle had
   grown to eight. */
import { PACK_CONTENTS } from '@/components/marketing/PackContents';

/**
 * The FAQ copy, the ONE source both the visible page and the FAQPage structured data read.
 *
 * WHY IT IS NOT JUST JSX. Google requires the answer in `FAQPage` structured data to match the
 * answer a visitor actually reads; schema that says more than the page does gets dropped, and
 * repeat mismatches cost the whole site its rich-result eligibility. The answers here contain
 * inline links (refund policy, terms, support email) that matter for the human reader, so the
 * obvious two-copy fix, JSX for the page, a hand-written string for the schema, would put two
 * versions of the same sentence in the repo and let them drift the first time someone edits one.
 *
 * So an answer is a list of segments instead: plain strings, and `{ text, href }` links. The page
 * renders the segments as prose with real anchors; `plainAnswer` joins the same segments into the
 * text the schema publishes. Editing the copy updates both, and there is no second copy to forget.
 *
 * Apostrophes are written as the typographic `’` rather than escaped entities because these
 * strings are consumed as text by both renderers, JSX renders them literally and JSON.stringify
 * escapes them correctly.
 */

export interface FaqLink {
  text: string;
  /** Internal route (`/refund`) or an absolute `mailto:`/`https:` URL. */
  href: string;
}

export type FaqSegment = string | FaqLink;

export type FaqCategory = 'packs' | 'payment' | 'process';

export interface FaqItem {
  question: string;
  answer: FaqSegment[];
  category: FaqCategory;
}

export function isLink(segment: FaqSegment): segment is FaqLink {
  return typeof segment !== 'string';
}

/** The answer as the plain prose the structured data publishes, a link contributes its own
 *  visible text, which is exactly what the reader sees on the page. */
export function plainAnswer(item: FaqItem): string {
  return item.answer.map((segment) => (isLink(segment) ? segment.text : segment)).join('');
}

export const FAQS: FaqItem[] = [
  { category: 'packs',
    question: 'What am I actually buying?',
    answer: [
      `A pack is one vetted business opportunity in ${PACK_CONTENTS.length} documents: a build spec, a go-to-market plan, an operations plan, a financial model, a first-week checklist, marketing assets, an executive summary, and a QA report with a source behind every claim. It is delivered as a zip of plain-text files the moment payment clears, and runs to at least 5,000 words. One payment, no subscription, and the price is shown on each pack’s own page.`,
    ],
  },
  { category: 'packs',
    question: 'What makes a pack "evidence-backed"?',
    answer: [
      `Every claim and every number in it cites a source you can open, or it is not in the pack. To be listed at all, the idea had to clear every check built to kill it and then survive an adversarial review: the checks common to every idea are ${checksSentence()}. Some ideas face more, and each pack page names the checks that idea faced and how many it cleared.`,
    ],
  },
  { category: 'payment',
    question: 'How do I get the pack after I pay?',
    answer: [
      'Your download link appears on screen as soon as payment succeeds, so the pack is in your hands within seconds. Checkout runs through Stripe. The link is permanent: bookmark it and you can re-download whenever you need to.',
    ],
  },
  { category: 'payment',
    question: 'Can I get a refund?',
    answer: [
      'Yes: every pack comes with a 14 day money back guarantee, no questions asked. If it is not what you expected, email us within 14 days of purchase and we refund you. The full terms are on the ',
      { text: 'refund policy', href: '/refund' },
      ' page.',
    ],
  },
  { category: 'process',
    question: 'Is a pack financial or investment advice?',
    answer: [
      'No. A pack is research and information only, not financial, legal, or investment advice. It’s an evidence backed starting point, and what you do with it is your decision.',
    ],
  },
  { category: 'process',
    question: 'Are the opportunities guaranteed to work?',
    answer: [
      'No, and we won’t pretend otherwise. We guarantee the analysis is evidence-backed and sourced, not that the business will succeed. Execution is yours.',
    ],
  },
  { category: 'packs',
    question: 'Can I share or resell a pack?',
    answer: [
      'No. A pack is licensed for your own personal use, with no redistribution, resale, or use as training data. The details are in the ',
      { text: 'Terms of Service', href: '/terms' },
      '.',
    ],
  },
  { category: 'process',
    question: 'Is the store live right now?',
    answer: [
      'Yes. Everything on this site works today, and new packs are published as they clear the checks.',
    ],
  },
  { category: 'payment',
    question: 'Can I have my data removed?',
    answer: [
      'Of course. Email us at ',
      { text: LEGAL.supportEmail, href: `mailto:${LEGAL.supportEmail}` },
      ' or read how we handle data in the ',
      { text: 'Privacy Policy', href: '/privacy' },
      '.',
    ],
  },
  { category: 'packs',
    question: 'What format is the pack delivered in?',
    answer: [
      'Every pack arrives as a zip of plain Markdown files you can open with any text editor. See the ',
      { text: 'free sample', href: '/sample' },
      ' for a complete unredacted example, or visit any ',
      { text: 'pack page', href: '/pack/<id>#table-of-contents' },
      ' to preview the per-pack table of contents and the blurred evidence record behind it. No proprietary software, no platform lock-in.',
    ],
  },
  { category: 'packs',
    question: 'If 500 other people buy the same pack, aren\'t 500 people copying my idea?',
    answer: [
      'Yes, other people can buy the same pack: it is not sold exclusively, and we will not promise you are the only person holding it. What you are buying is the research, not a claim on the idea. Each pack is sized to a specific niche, with a named buyer and a concrete route to market, so two people working from the same one are competing on execution, on who they can reach and what they build, rather than on who found the opportunity first. If exclusivity is what you need, this is the wrong product and we would rather say so now. If you want to see how many ideas are killed before one reaches the store, the ',
      { text: 'kill log', href: '/kill-log' },
      ' shows every one that did not make it.',
    ],
  },
  { category: 'process',
    question: 'What happens to the ideas that don\'t survive the checks?',
    answer: [
      'Every one of them is published in the ',
      { text: 'kill log', href: '/kill-log' },
      ', with the check that killed it and the sourced argument behind that. Nothing is quietly dropped: you can read exactly why each idea was killed and, where a page was cited, open the source and check it yourself.',
    ],
  },
];
