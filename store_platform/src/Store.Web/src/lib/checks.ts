/**
 * The checks, named once, for every surface that names them.
 *
 * WHY THIS EXISTS
 * ---------------
 * On 2026-08-06 the same six gates were written out independently in eight places, in four
 * mutually inconsistent lexicons:
 *
 *   /about              "Real demand"  "Someone will pay"        "No legal landmine"
 *   /how-it-works       "Real pain"    "Payer can actually pay"  "Legality"
 *   /pack/[id]          "Whether the pain is imagined"  "Whether anyone will actually pay"
 *   lib/faqContent.ts   "real pain, durable value, room past incumbents, a solvent payer..."
 *
 * A visitor reading two pages in one session met two different vocabularies for one mechanism and
 * had no way to tell whether "Real demand" and "Real pain" were the same gate or two of them. On a
 * shop whose entire pitch is that its process is rigid and repeatable, the process describing
 * itself differently on every page is evidence against the pitch.
 *
 * TWO REGISTERS, ONE VOCABULARY
 * -----------------------------
 * The pack page deliberately uses refutational phrasing ("Whether the pain is imagined") because
 * two-sided attack framing out-persuades one-sided "validated" claims (Allen 1991, O'Keefe 1999,
 * Eisend 2006). That is a real reason and it survives. What does not survive is each page also
 * inventing its own NOUN for the gate. So every check carries all three forms here, and a page
 * picks the register that fits; it never coins a word.
 *
 * COUNT IS NOT PART OF THE VOCABULARY
 * -----------------------------------
 * These are the checks common to EVERY lane. Some lanes add more: `config.yaml lanes.side_hustle`
 * adds buyer_intent, currency and claims_verifiable, so live packs report 6/6 (40), 8/8 (15),
 * 7/8 (4), 9/9 (3) and 6/8 (1). Copy must never say "the six checks" as though six were the whole
 * set -- `fixedCheckCount.test.ts` fails the build if it does. Render `COMMON_CHECKS` as a list;
 * let the pack page state that pack's real count, which is the only place the API supplies it.
 */

export interface Check {
  /** The engine's own gate id, as it appears in `config.yaml` and in dossier `gate_fired`. */
  id: string;
  /**
   * Other engine ids that mean this same gate. `side_hustle` calls distribution
   * `route_to_market` (`config.yaml:276,369`) while the other lanes call it `distribution`
   * (`197,258,353,406`). One gate, two ids, one buyer-facing name.
   */
  aliases: readonly string[];
  /** Title case. The gate as a thing that must be true. Headings and list items. */
  name: string;
  /** The question the check asks. Sentence case, ends in a question mark. */
  question: string;
  /** Refutational form, for surfaces that lead with what we tried to prove FALSE. */
  refutation: string;
  /** Lowercase noun phrase, for use inline in a running sentence. */
  prose: string;
}

export const COMMON_CHECKS: readonly Check[] = [
  {
    id: 'pain_reality',
    aliases: [],
    name: 'Real pain',
    question: 'Is the pain real, or are we imagining it?',
    refutation: 'Whether the pain is imagined',
    prose: 'real pain',
  },
  {
    id: 'value_durability',
    aliases: [],
    name: 'Lasting value',
    question: 'Does the value last, or does it decay?',
    refutation: 'Whether the value decays',
    prose: 'lasting value',
  },
  {
    id: 'incumbency',
    aliases: [],
    name: 'Room past the incumbents',
    question: 'Have the big players already won?',
    refutation: 'Whether incumbents already own the space',
    prose: 'room past the incumbents',
  },
  {
    id: 'payer_solvency',
    aliases: [],
    name: 'A payer who can pay',
    question: 'Is the buyer actually solvent?',
    refutation: 'Whether anyone will actually pay',
    prose: 'a payer who can pay',
  },
  {
    id: 'distribution',
    aliases: ['route_to_market'],
    name: 'A route to the buyer',
    question: 'Can this reach a market at all?',
    refutation: 'Whether it can reach a market at all',
    prose: 'a route to the buyer',
  },
  {
    id: 'legality',
    aliases: [],
    name: 'No legal landmine',
    question: 'Is there a regulatory path?',
    refutation: 'Whether there is a legal landmine',
    prose: 'no legal landmine',
  },
] as const;

/** Every id and alias that maps to `check`. Use when matching an engine-written `gate_fired`. */
export function idsFor(check: Check): readonly string[] {
  return [check.id, ...check.aliases];
}

/** The check a raw engine gate id belongs to, or null when the gate is lane-specific. */
export function checkForGate(gate: string | null | undefined): Check | null {
  if (!gate) return null;
  const key = gate.trim().toLowerCase().replace(/\s+/g, '_');
  return COMMON_CHECKS.find((c) => idsFor(c).includes(key)) ?? null;
}

/**
 * The checks as one comma-separated clause, Oxford comma and all, for use inside a sentence.
 * Built here rather than typed out so a rename cannot leave a stale copy in the FAQ.
 */
export function checksSentence(): string {
  const parts = COMMON_CHECKS.map((c) => c.prose);
  return `${parts.slice(0, -1).join(', ')}, and ${parts[parts.length - 1]}`;
}

/**
 * The engine's own identifiers, space-separated, for the one surface that quotes the machine's
 * vocabulary rather than ours. Derived, so the mono row on the homepage cannot drift from the
 * names above the way it did before (it was missed by a regression test that read about.tsx only).
 */
export function engineGateIds(): string {
  return COMMON_CHECKS.map((c) => c.id.replace(/_/g, ' ')).join(' · ');
}
