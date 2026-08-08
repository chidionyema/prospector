import { LEGAL } from '@/lib/config';
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
      // ANSWER-FIRST (email §6). State the 8 documents in one sentence, in the order the bundle
      // ships them, so a reader who only reads the first sentence has the answer. The previous
      // version opened "A pack is one vetted business opportunity in N documents" and listed them
      // across the same sentence, so a buyer who skimmed could not count to eight. Eight it is,
      // one sentence.
      `One vetted business opportunity, as ${PACK_CONTENTS.length} plain-text documents: a build spec, go-to-market plan, operations plan, financial model, first-week checklist, marketing assets, an executive summary, and a QA report with a source behind every claim. One zip, one payment, instant download.`,
    ],
  },
  { category: 'packs',
    question: 'What makes a pack evidence-backed?',
    answer: [
      // Per email §6: short, plain. The previous answer named the engine check list and the
      // adversarial review, which the buyer has not earned the vocabulary for yet on the FAQ.
      'Every claim links to a source you can open. Anything the engine couldn’t verify is marked absent, never invented. The QA report inside the pack is the audit trail.',
    ],
  },
  { category: 'payment',
    question: 'How do I get the pack after I pay?',
    answer: [
      // Per email §6: answer in the first sentence.
      'A download link, the moment payment clears. Also emailed to you. No account needed.',
    ],
  },
  { category: 'payment',
    question: 'Can I get a refund?',
    answer: [
      'Yes. 14 days, full refund, no questions. Email ',
      { text: LEGAL.supportEmail, href: `mailto:${LEGAL.supportEmail}` },
      // The route to the policy is not decoration. This is the answer a buyer reads BEFORE paying,
      // and the rewrite that shortened it removed the only link from it to the terms that actually
      // bind the refund. Brevity is the register; deleting the consumer's route to the terms is a
      // different thing, and the segment list exists precisely so a link costs one line.
      ', or read the full ',
      { text: 'refund policy', href: '/refund' },
      '.',
    ],
  },
  { category: 'process',
    question: 'Is a pack financial or investment advice?',
    answer: [
      'No. It’s research, sold for information. Nothing in a pack is advice about your money.',
    ],
  },
  { category: 'process',
    question: 'Are the opportunities guaranteed to work?',
    answer: [
      'No. The research is done and sourced; the execution is yours. No one can promise a business outcome, and we don’t.',
    ],
  },
  { category: 'packs',
    question: 'Can I share or resell a pack?',
    answer: [
      // Same reason as the refund answer: the licence question is answered in plain words, and the
      // words are a summary of a document the reader is entitled to reach from here.
      'It’s licensed to you. Build from it, edit it, quote it. Don’t republish or resell the pack itself. The full licence terms are in the ',
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
    question: 'What format is it delivered in?',
    answer: [
      // Per email §6: lead with the format, list open-in tools, link to the sample.
      'Plain Markdown files in a zip. They open anywhere: Notion, Obsidian, a text editor, your AI tool.',
    ],
  },
  { category: 'packs',
    question: 'If 500 people buy the same pack, aren’t 500 people copying my idea?',
    answer: [
      // Per email §6: 50 words, the only question that gets a longer answer because the answer
      // is the whole product.
      'In practice, almost nobody executes. And most packs win on a local patch (one school, one council, one trade) where the first mover in your area is the only one who matters. The research is shared; the ground isn’t.',
    ],
  },
  { category: 'process',
    question: 'What happens to ideas that don’t survive?',
    answer: [
      // Per email §6: short, link to the log.
      'They go in the kill log, in public, with the evidence that killed them.',
    ],
  },
];
