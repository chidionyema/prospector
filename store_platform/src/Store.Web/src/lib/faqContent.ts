import { LEGAL } from '@/lib/config';
/* The document count is COUNTED, never typed. `PACK_DOCUMENTS` is pinned to the engine's own
   `BUNDLE_FILES` by `__tests__/packContents.test.ts`, and this is the answer a buyer reads before
   paying: the last time the number was written out by hand it said four while the bundle had
   grown to eight. */
import { PACK_DOCUMENTS } from '@/components/marketing/PackContents';

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

/*
 * THE ORDER IS THE PURCHASE BLOCKERS, BIGGEST FIRST (MASTER-BRIEF section 7 `/faq`).
 *
 * It used to be grouped by the three filter categories, which is the order the copy was WRITTEN in,
 * not the order a buyer reads in. The page opens with the first row expanded, so whatever sits at
 * index 0 is the only answer a visitor is guaranteed to see.
 *
 * "Why not just ask a chatbot?" is first because in 2026 it is the objection every visitor arrives
 * with, and no other answer matters until it is dealt with. Then what the thing is, then why to
 * believe it, then the two fears that stop a purchase (someone else buys the same pack; it might not
 * work), then money and delivery, then the housekeeping questions nobody is blocked on.
 *
 * The category filters still work: `category` is on every item and the chips filter on it. Order and
 * grouping are separate, and only the order is a claim about what a buyer needs first.
 */
export const FAQS: FaqItem[] = [
  { category: 'process',
    // THE OBJECTION THE SITE HAD NO ANSWER FOR (2026-08-13). Being quiet about AI was never an
    // ethics decision, it was this question going unanswered: in 2026 a buyer has already had
    // free business ideas from a chatbot and already knows it invents numbers, so naming the AI
    // without answering "why pay" reads as an admission. Answered here, next to the kill log
    // question it sets up, because the two together are the whole argument.
    question: 'Why not just ask a chatbot?',
    answer: [
      'Because it will agree with you. Ask a chatbot about your idea and you get an encouraging answer full of numbers it invented on the spot. Every figure here links to the page it came from, and the ideas that failed are published too, in the ',
      { text: 'kill log', href: '/kill-log' },
      '. No chatbot will ever show you that, because it costs nothing to tell you yes.',
    ],
  },
  { category: 'packs',
    question: 'What am I actually buying?',
    answer: [
      // ANSWER-FIRST (email §6). State the documents in one sentence, in the order the pack reads
      // them, so a reader who only reads the first sentence has the answer. The previous version
      // opened "A pack is one vetted business opportunity in N documents" and listed them across
      // the same sentence, so a buyer who skimmed could not count them.
      //
      // "Every one in Markdown you can edit" came out on 2026-08-15: the Markdown stopped shipping
      // when bridge.py split render input from archive contract. The second sentence replaces it
      // with what the buyer now actually opens, which is the more concrete claim anyway -- the
      // founder's objection was "we are not selling to developers", and "Markdown you can edit"
      // was the single most developer-facing sentence on the site.
      // TWO EDITS, 2026-08-16, both to sentences that read as arithmetic:
      //   - "as N documents: a, b, c ... and i" named nine things after a count of fourteen, so the
      //     colon promised a complete list and delivered two thirds of one. "Among them" claims
      //     what the sentence can actually deliver.
      //   - the format list is DELETED from this answer. It is the whole of the "What format is it
      //     delivered in?" answer four rows below, word for word, and repeating it here put the
      //     first-week checklist (a document) and the first-fortnight sheet (a file) in one
      //     paragraph, where they read as the same thing described twice at two different lengths.
      `One vetted business opportunity, written up as ${PACK_DOCUMENTS.length} documents. Among them: an executive summary, a build spec, a go-to-market plan, an operations plan, a financial model, a first-week checklist, marketing assets, the evidence in one place, and a QA report with a source behind every claim. One zip, one payment, instant download.`,
    ],
  },
  { category: 'packs',
    question: 'What makes a pack evidence-backed?',
    answer: [
      // Per email §6: short, plain. The previous answer named the engine check list and the
      // adversarial review, which the buyer has not earned the vocabulary for yet on the FAQ.
      // "never invented" was removed 2026-08-13: the figure trace measured 15 of 50 selling packs
      // asserting a number found in no retrieved passage (programme doc §33). What IS enforced is
      // that every verdict publishes the passages it was ruled on, and that an unverifiable check
      // is labelled rather than dropped. Say only that until 33-A gates the shelf.
      'Every verdict ships with the sources it was ruled on, so you can open them and judge the evidence yourself. Anything the engine could not verify is marked unverifiable rather than quietly dropped. The QA report inside the pack is the audit trail.',
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
    question: 'Are the opportunities guaranteed to work?',
    answer: [
      'No. The research is done and sourced; the execution is yours. No one can promise a business outcome, and we don’t.',
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
  { category: 'payment',
    question: 'How do I get the pack after I pay?',
    answer: [
      // Per email §6: answer in the first sentence.
      'A download link, the moment payment clears. Also emailed to you. No account needed.',
    ],
  },
  { category: 'packs',
    question: 'What format is it delivered in?',
    answer: [
      // Per email §6: lead with the format, list what opens each part.
      //
      // Rewritten 2026-08-15. "Plain Markdown files in a zip. They open anywhere: Notion,
      // Obsidian, a text editor, your AI tool." was false from the moment bridge.py stopped
      // writing the `.md` into the archive, and it was the answer to the one question a buyer
      // asks BEFORE paying. It was also the sentence the founder's objection was aimed at: it
      // names two tools most readers do not use to make a point ("it opens anywhere") that the
      // formats now make on their own, and it sold a research product as a developer artefact.
      'A zip you open like any other. A web page for reading the whole pack, a typeset PDF for printing, a one-page plan for your first fortnight, a spreadsheet of the assumptions, and the marketing copy as plain text to paste. Nothing to install, no account.',
    ],
  },
  { category: 'process',
    question: 'What happens to ideas that don’t survive?',
    answer: [
      // Per email §6: short, link to the log.
      'They go in the kill log, in public, with the evidence that killed them.',
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
    question: 'Is a pack financial or investment advice?',
    answer: [
      'No. It’s research, sold for information. Nothing in a pack is advice about your money.',
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
];
