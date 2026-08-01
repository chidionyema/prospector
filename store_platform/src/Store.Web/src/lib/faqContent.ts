import { LEGAL } from '@/lib/config';

/**
 * The FAQ copy — the ONE source both the visible page and the FAQPage structured data read.
 *
 * WHY IT IS NOT JUST JSX. Google requires the answer in `FAQPage` structured data to match the
 * answer a visitor actually reads; schema that says more than the page does gets dropped, and
 * repeat mismatches cost the whole site its rich-result eligibility. The answers here contain
 * inline links (refund policy, terms, support email) that matter for the human reader, so the
 * obvious two-copy fix — JSX for the page, a hand-written string for the schema — would put two
 * versions of the same sentence in the repo and let them drift the first time someone edits one.
 *
 * So an answer is a list of segments instead: plain strings, and `{ text, href }` links. The page
 * renders the segments as prose with real anchors; `plainAnswer` joins the same segments into the
 * text the schema publishes. Editing the copy updates both, and there is no second copy to forget.
 *
 * Apostrophes are written as the typographic `’` rather than escaped entities because these
 * strings are consumed as text by both renderers — JSX renders them literally and JSON.stringify
 * escapes them correctly.
 */

export interface FaqLink {
  text: string;
  /** Internal route (`/refund`) or an absolute `mailto:`/`https:` URL. */
  href: string;
}

export type FaqSegment = string | FaqLink;

export interface FaqItem {
  question: string;
  answer: FaqSegment[];
}

export function isLink(segment: FaqSegment): segment is FaqLink {
  return typeof segment !== 'string';
}

/** The answer as the plain prose the structured data publishes — a link contributes its own
 *  visible text, which is exactly what the reader sees on the page. */
export function plainAnswer(item: FaqItem): string {
  return item.answer.map((segment) => (isLink(segment) ? segment.text : segment)).join('');
}

export const FAQS: FaqItem[] = [
  {
    question: 'What am I actually buying?',
    answer: [
      'A £49 pack: a grounded business opportunity dossier in four parts — a build spec, a go to market plan, an operations and financial model, and a QA report with a clickable source behind every claim. It arrives as one zip of plain Markdown files, 5,000+ words, yours to read and build from as soon as payment clears.',
    ],
  },
  {
    question: 'What makes a pack "grounded"?',
    answer: [
      'Every pack passed the Mumchimp engine’s six checks (real pain, durable value, room past incumbents, a solvent payer, a distribution route, and legality) and survived an adversarial review. Every claim and number cites a retrievable source, or it isn’t in the pack.',
    ],
  },
  {
    question: 'How do I get the pack after I pay?',
    answer: [
      'Checkout runs through Stripe. As soon as payment succeeds you get your download link on screen, so the pack is in your hands within seconds. The link is permanent — bookmark it and you can re-download whenever you need to.',
    ],
  },
  {
    question: 'Can I get a refund?',
    answer: [
      'Yes. Every pack comes with a 14 day money back guarantee, no questions asked. If it is not what you expected, email us within 14 days of purchase and we refund you. The full terms are on the ',
      { text: 'refund policy', href: '/refund' },
      ' page.',
    ],
  },
  {
    question: 'Is a pack financial or investment advice?',
    answer: [
      'No. A pack is research and information only, not financial, legal, or investment advice. It’s an evidence backed starting point, and what you do with it is your decision.',
    ],
  },
  {
    question: 'Are the opportunities guaranteed to work?',
    answer: [
      'No, and we won’t pretend otherwise. We guarantee the analysis is grounded and sourced, not that the business will succeed. Execution is yours.',
    ],
  },
  {
    question: 'Can I share or resell a pack?',
    answer: [
      'No. A pack is licensed for your own personal use, with no redistribution, resale, or use as training data. The details are in the ',
      { text: 'Terms of Service', href: '/terms' },
      '.',
    ],
  },
  {
    question: 'Is the store live right now?',
    answer: [
      'Yes. Everything on this site works today, and new packs are published as they clear the filter.',
    ],
  },
  {
    question: 'Can I have my data removed?',
    answer: [
      'Of course. Email us at ',
      { text: LEGAL.supportEmail, href: `mailto:${LEGAL.supportEmail}` },
      ' or read how we handle data in the ',
      { text: 'Privacy Policy', href: '/privacy' },
      '.',
    ],
  },
];
