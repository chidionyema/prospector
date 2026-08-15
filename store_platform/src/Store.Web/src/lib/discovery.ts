/**
 * Discovery: filtering, matchmaking and similarity, the pure core of the storefront's
 * routing, with no React, no fetch and no DOM in it, so every rule below is unit-testable
 * (`src/lib/__tests__/discovery.test.ts`) rather than only reachable through a browser.
 *
 * The one rule that governs the whole file: **absent means absent**. A pack the engine could
 * not justify tagging is `null` for that facet, and a null facet never matches a specific
 * value, never scores, and is never inferred from the pack's text. That is what makes the
 * filter honest on a brand that sells "every claim has a clickable source", see
 * `src/lib/facets.ts` for the same rule at the vocabulary level.
 */

import {
  ADVANTAGE,
  COMMITMENT,
  EFFORT,
  MECHANISM,
  PAYER,
  SECTOR,
  VOCABULARY,
  shortLabel,
  type Advantage,
  type Commitment,
  type Effort,
  type FacetKind,
  type Mechanism,
  type Payer,
  type Sector,
  type SingleValuedKind,
} from './facets';

/**
 * The shape discovery needs from a pack. Declared structurally rather than importing `Pack`
 * from the API client so this module stays dependency-free and a test can build a two-field
 * fixture; `Pack` satisfies it by construction.
 */
export interface FacetedPack {
  id: string;
  title: string;
  oneLine?: string;
  headline?: string;
  cardLine?: string;
  whoPays?: string;
  sector?: string | null;
  payer?: string | null;
  effort?: string | null;
  commitment?: string | null;
  mechanism?: string | null;
  advantages?: string[] | null;
  sourceCount?: number;
  verifiedAt?: string;
}

// ---------------------------------------------------------------------------
// Discovery state and its URL codec
// ---------------------------------------------------------------------------

/**
 * Everything the catalogue view is filtered by. Lives in the URL so a filtered view is
 * shareable and so the server can render the first paint already filtered, a link to
 * "B2B, evenings-friendly" that arrives showing the whole catalogue and then reflows is the kind
 * of detail that reads as broken.
 */
export interface DiscoveryState {
  /** Free-text query. Matched against title, one-liner, headline and who-pays. */
  q: string;
  /** Multi-select; a pack matches if it carries ANY selected advantage (OR within the facet). */
  advantage: Advantage[];
  sector: Sector | null;
  payer: Payer | null;
  effort: Effort | null;
  commitment: Commitment | null;
  mechanism: Mechanism | null;
}

export const EMPTY_DISCOVERY_STATE: DiscoveryState = {
  q: '',
  advantage: [],
  sector: null,
  payer: null,
  effort: null,
  commitment: null,
  mechanism: null,
};

/** URL parameter names, and the deterministic order `encodeDiscoveryState` writes them in. */
const SINGLE_PARAMS: ReadonlyArray<[SingleValuedKind, string]> = [
  ['sector', 'sector'],
  ['payer', 'payer'],
  ['effort', 'effort'],
  ['commitment', 'commitment'],
  ['mechanism', 'mechanism'],
];

const VOCAB_BY_KIND: Record<SingleValuedKind, readonly string[]> = {
  sector: SECTOR,
  payer: PAYER,
  effort: EFFORT,
  commitment: COMMITMENT,
  mechanism: MECHANISM,
};

/** True when any filter is active. An all-empty state means "show everything". */
export function isFiltered(state: DiscoveryState): boolean {
  return (
    state.q.trim() !== '' ||
    state.advantage.length > 0 ||
    SINGLE_PARAMS.some(([kind]) => state[kind] !== null)
  );
}

/** How many facet constraints (not counting the text query) are active. Drives the near-miss rule. */
export function activeConstraintCount(state: DiscoveryState): number {
  return (
    (state.advantage.length > 0 ? 1 : 0) + SINGLE_PARAMS.filter(([kind]) => state[kind] !== null).length
  );
}

/** Serialise to a query string (no leading `?`). Empty state serialises to `''`. */
export function encodeDiscoveryState(state: DiscoveryState): string {
  const params = new URLSearchParams();
  const q = state.q.trim();
  if (q) params.set('q', q);
  if (state.advantage.length > 0) params.set('adv', state.advantage.join(','));
  for (const [kind, param] of SINGLE_PARAMS) {
    const value = state[kind];
    if (value) params.set(param, value);
  }
  return params.toString();
}

/** What Next hands us in `getServerSideProps` (`context.query`) and from `router.query`. */
export type QueryLike = Record<string, string | string[] | undefined>;

function firstValue(input: QueryLike, key: string): string | null {
  const raw = input[key];
  if (Array.isArray(raw)) return raw.length > 0 ? raw[0] : null;
  return raw ?? null;
}

/**
 * Parse a query string (or Next's parsed query object) into state.
 *
 * Every value is checked against the closed vocabulary and silently dropped if it is not a
 * member. A hand-edited or stale URL therefore degrades to a wider view rather than creating
 * a filter for a value that does not exist, which would render an empty catalogue with a
 * chip naming a facet the engine has never emitted.
 */
export function decodeDiscoveryState(input: string | QueryLike | undefined | null): DiscoveryState {
  if (!input) return { ...EMPTY_DISCOVERY_STATE, advantage: [] };

  let query: QueryLike;
  if (typeof input === 'string') {
    const params = new URLSearchParams(input.startsWith('?') ? input.slice(1) : input);
    query = {};
    for (const [key, value] of params.entries()) query[key] = value;
  } else {
    query = input;
  }

  const advantageRaw = firstValue(query, 'adv') ?? '';
  const advantage = advantageRaw
    .split(',')
    .map((v) => v.trim())
    .filter((v): v is Advantage => (ADVANTAGE as readonly string[]).includes(v));

  const state: DiscoveryState = {
    ...EMPTY_DISCOVERY_STATE,
    q: (firstValue(query, 'q') ?? '').trim(),
    // De-duplicate so `?adv=code,code` cannot double-count in the URL round-trip.
    advantage: Array.from(new Set(advantage)),
  };

  for (const [kind, param] of SINGLE_PARAMS) {
    const value = firstValue(query, param);
    if (value && VOCAB_BY_KIND[kind].includes(value)) {
      // Each vocabulary is the union type for its own kind, so the narrowing is sound; TS
      // cannot see that through the keyed lookup.
      (state[kind] as string) = value;
    }
  }
  return state;
}

// ---------------------------------------------------------------------------
// Filtering
// ---------------------------------------------------------------------------

/**
 * The fields the command palette and the query filter search, in row-display order.
 *
 * Joined on a NUL, written as the `\u0000` escape so this file stays plain text (a raw NUL byte
 * makes git treat the source as binary). A buyer cannot type this character, so a query can never
 * straddle two fields and score a match that reads as one phrase but is really the tail of the
 * title plus the head of the one-liner.
 */
export function searchableText(pack: FacetedPack): string {
  return [pack.title, pack.oneLine, pack.headline, pack.whoPays].filter(Boolean).join(' \u0000 ');
}

/**
 * Case-insensitive substring match across title, one-liner, headline and who-pays.
 *
 * Title alone is not enough, and the proof is the feedback's own worked example: a buyer types
 * "Uber", and the string "Uber" appears in PlateStart's one-liner and who-pays but in no title
 * in the catalogue. A title-only search returns nothing for the exact query the feature was
 * asked for.
 */
export function matchesQuery(pack: FacetedPack, q: string): boolean {
  const needle = q.trim().toLowerCase();
  if (!needle) return true;
  return searchableText(pack).toLowerCase().includes(needle);
}

/** True when the pack satisfies one single-valued facet constraint. Untagged never matches. */
function matchesSingle(pack: FacetedPack, kind: SingleValuedKind, wanted: string | null): boolean {
  if (!wanted) return true;
  const actual = pack[kind];
  // The null rule, in one line: an untagged pack is not a match for a specific value. It is
  // not "probably this" and it is not excluded from the catalogue, it appears under "All".
  if (!actual) return false;
  return actual === wanted;
}

/**
 * Apply the whole discovery state. AND across facets, OR within `advantage` (a buyer who can
 * both build and sell wants either kind of pack, not only packs tagged with both).
 */
export function filterPacks<T extends FacetedPack>(packs: readonly T[], state: DiscoveryState): T[] {
  return packs.filter((pack) => {
    if (!matchesQuery(pack, state.q)) return false;
    if (state.advantage.length > 0) {
      const tagged = pack.advantages ?? [];
      if (tagged.length === 0) return false;
      if (!state.advantage.some((a) => tagged.includes(a))) return false;
    }
    return SINGLE_PARAMS.every(([kind]) => matchesSingle(pack, kind, state[kind]));
  });
}

/**
 * How many packs each value of a facet would yield under the rest of the current state, the
 * counts shown beside each option in the filter bar. Computed with that facet's own constraint
 * removed, so the count answers "what happens if I click this" rather than "what is selected".
 */
export function facetCounts(
  packs: readonly FacetedPack[],
  state: DiscoveryState,
  kind: FacetKind,
): Record<string, number> {
  const relaxed: DiscoveryState =
    kind === 'advantage' ? { ...state, advantage: [] } : { ...state, [kind]: null };
  const pool = filterPacks(packs, relaxed);
  const counts: Record<string, number> = {};
  for (const pack of pool) {
    const values = kind === 'advantage' ? pack.advantages ?? [] : [pack[kind]];
    for (const value of values) {
      if (!value) continue;
      counts[value] = (counts[value] ?? 0) + 1;
    }
  }
  return counts;
}

/** The values of `kind` the buyer currently has selected. Single-valued facets yield 0 or 1. */
export function activeFacetValues(state: DiscoveryState, kind: FacetKind): string[] {
  return kind === 'advantage' ? [...state.advantage] : ([state[kind]].filter(Boolean) as string[]);
}

/**
 * How many individual chips are lit, which is NOT `activeConstraintCount`.
 *
 * `activeConstraintCount` counts `advantage` as one constraint however many values are in it,
 * because the near-miss rule asks "how many AND-ed constraints did this pack fail". A "Filters"
 * badge answers a different question, how many controls did I switch on, and a buyer who lit
 * "I can build" and "I can sell" and reads "Filters 1" has been told something they can
 * see is false.
 */
export function activeFacetSelectionCount(state: DiscoveryState): number {
  return state.advantage.length + SINGLE_PARAMS.filter(([kind]) => state[kind] !== null).length;
}

/**
 * The minimum number of packs in the whole catalogue that must carry a value before it is
 * offered as a filter control. See `offeredFacetValues`.
 */
export const MIN_OPTION_PACKS = 2;

/**
 * Which values of `kind` are worth rendering as controls.
 *
 * Three rules, in order:
 *
 * 1. A value no pack in the current pool carries is not offered, an option that can only ever
 *    return zero results is a promise the catalogue cannot keep.
 * 2. A value fewer than `minPacks` packs carry ANYWHERE in the catalogue is not offered.
 *    Measured on the live catalogue on 2026-07-31: `audience` was carried by 1 pack of 42,
 *    `full_time` by 1, `housing_rental` by 1, `professional_services` by 1, `audience_media`
 *    by 1, `data_intelligence` by 1. A control that takes the shelf from 42 to 1 charges every
 *    buyer the cost of reading and deciding on it and can only ever produce a near-empty grid.
 *    Nothing becomes unreachable: the pack keeps every chip it earned and still appears under
 *    "All", in search, in the matchmaker and in similar-packs.
 * 3. A value the buyer has already selected is ALWAYS offered, whatever its count, hiding it
 *    would strand them inside a filter with no visible control to leave it by. That is the case
 *    a shared-URL makes real: `?commitment=full_time` is a legal link.
 *
 * Rule 2 is judged against the catalogue and never against the filtered pool, so options do not
 * appear and vanish as the buyer clicks. `q` is cleared for the same reason, typing in the
 * search box must not silently delete filter controls.
 */
export function offeredFacetValues(
  packs: readonly FacetedPack[],
  state: DiscoveryState,
  kind: FacetKind,
  minPacks: number = MIN_OPTION_PACKS,
): string[] {
  const active = activeFacetValues(state, kind);
  const inPool = facetCounts(packs, state, kind);
  const inCatalogue = facetCounts(packs, EMPTY_DISCOVERY_STATE, kind);
  return VOCABULARY[kind].filter(
    (value) =>
      inPool[value] !== undefined &&
      (active.includes(value) || (inCatalogue[value] ?? 0) >= minPacks),
  );
}

/** What the filter bar renders once progressive disclosure has decided what to fold away. */
export interface FacetGroupFold<T> {
  /** The groups to render, in order. */
  visible: T[];
  /** How many groups are currently folded away, 0 when everything is on screen. */
  foldedCount: number;
  /** Whether to offer the expand/collapse control at all. */
  canFold: boolean;
}

/**
 * Decide which facet groups stay open (spec S9 / email US2 "progressive disclosure").
 *
 * This lives here rather than inline in `FacetBar` for one reason: the invariant it protects is
 * not a rendering detail. Folding a group that holds an active selection puts a buyer under a
 * constraint with no control on screen to see or release it, the exact way a shared or
 * bookmarked URL strands someone on a near-empty shelf with no visible cause. So the fold is
 * overridden whenever anything below the cut is selected, and the toggle is withdrawn with it,
 * because a collapse control that can re-hide a live constraint is the same bug behind a click.
 *
 * `openCount <= 0` folds nothing (there is no "collapse everything" mode), and a group count at
 * or below `openCount` reports `canFold: false` so the control never appears saying "0 more".
 */
export function foldFacetGroups<T extends { activeValues: readonly string[] }>(
  groups: readonly T[],
  openCount: number,
  expanded: boolean,
): FacetGroupFold<T> {
  const all = [...groups];
  if (openCount <= 0 || all.length <= openCount) {
    return { visible: all, foldedCount: 0, canFold: false };
  }
  const folded = all.slice(openCount);
  const constraining = folded.some((group) => group.activeValues.length > 0);
  if (expanded || constraining) {
    return { visible: all, foldedCount: 0, canFold: !constraining };
  }
  return { visible: all.slice(0, openCount), foldedCount: folded.length, canFold: true };
}

/** A pack that failed exactly one active facet constraint, plus the state that would include it. */
export interface NearMiss<T extends FacetedPack = FacetedPack> {
  pack: T;
  kind: FacetKind;
  /** The value the buyer asked for. For `advantage` this is the first advantage they picked. */
  wanted: string;
  /** What the pack actually carries, `null` when it is simply untagged for this facet. */
  actual: string | null;
  relaxedState: DiscoveryState;
}

/**
 * Packs that match everything except ONE facet (spec Part 7A).
 *
 * The text query is not a relaxable constraint here: if nothing matches the words the buyer
 * typed, they are not one facet away from a sale, they are in the catalogue-wide empty state and
 * the honest response is the waitlist. Only packs that already match the query are considered.
 */
export function nearMisses<T extends FacetedPack>(
  packs: readonly T[],
  state: DiscoveryState,
  limit = 3,
): NearMiss<T>[] {
  const out: NearMiss<T>[] = [];
  for (const pack of packs) {
    if (!matchesQuery(pack, state.q)) continue;

    const failures: Array<{ kind: FacetKind; wanted: string; actual: string | null }> = [];
    if (state.advantage.length > 0) {
      const tagged = pack.advantages ?? [];
      if (!state.advantage.some((a) => tagged.includes(a))) {
        failures.push({ kind: 'advantage', wanted: state.advantage[0], actual: tagged[0] ?? null });
      }
    }
    for (const [kind] of SINGLE_PARAMS) {
      const wanted = state[kind];
      if (wanted && !matchesSingle(pack, kind, wanted)) {
        failures.push({ kind, wanted, actual: pack[kind] ?? null });
      }
    }

    if (failures.length !== 1) continue;
    const [miss] = failures;
    out.push({
      pack,
      kind: miss.kind,
      wanted: miss.wanted,
      actual: miss.actual,
      relaxedState:
        miss.kind === 'advantage'
          ? { ...state, advantage: [] }
          : { ...state, [miss.kind]: null },
    });
  }
  return out.slice(0, limit);
}

// ---------------------------------------------------------------------------
// Matchmaker scoring (spec Part 5)
// ---------------------------------------------------------------------------

/**
 * The three quiz answers.
 *
 * `payer: null` covers both "Don't mind" and skipping Q3, the spec scores both as 0 rather
 * than as a miss, so declining to answer can never cost a pack points.
 *
 * Note on Q1's "None of these yet": the spec maps it to `nocode` + `hands_on`. NEITHER half is
 * applied, because the requirement attached to that answer is that it "must never dead-end" and
 * both halves break it. `hands_on` was dropped first, as a filter or a penalty it pushes a
 * beginner away from the automatable packs, which are the ones a beginner can actually run. The
 * `nocode` half was dropped on 2026-08-01 once the catalogue could be measured: `nocode` is
 * carried by 1 pack of 49, so copying it into `advantages` here sent `?adv=nocode` through
 * `stateFromAnswers` into `applyDiscoveryState`, which filtered the beginner's "show me
 * everything that matched" down to that single pack.
 *
 * So "None of these yet" now contributes NO advantage: `advantages` stays empty and the buyer is
 * routed on the answers they did give (commitment, payer, evidence). Empty is not a miss,
 * `scoreMatch` is additive and never punishes an absent term, so a beginner still gets a ranked
 * catalogue rather than a near-empty one.
 */
export interface MatchAnswers {
  advantages: Advantage[];
  commitment: Commitment | null;
  payer: Payer | null;
}

export const EMPTY_MATCH_ANSWERS: MatchAnswers = { advantages: [], commitment: null, payer: null };

/** Why a pack scored, the raw material for the one-sentence reason on the result screen. */
export interface MatchReason {
  kind: FacetKind | 'evidence';
  value: string;
  points: number;
}

/** Generic over the pack type so a caller holding a full `Pack` gets a full `Pack` back, the
 *  result screen needs `price`, which discovery itself never reads. */
export interface MatchResult<T extends FacetedPack = FacetedPack> {
  pack: T;
  score: number;
  reasons: MatchReason[];
}

/** Packs with at least this many sources earn the evidence point (live range 5 to 29). */
export const WELL_SOURCED_THRESHOLD = 15;

/**
 * Score one pack against the quiz answers. Pure, total, never negative.
 *
 * Every term is additive and every untagged facet contributes exactly 0, a pack is never
 * punished for a facet the engine declined to assert, because that would turn "we don't know"
 * into "no", which is a claim the dossier does not support.
 */
export function scoreMatch<T extends FacetedPack>(pack: T, answers: MatchAnswers): MatchResult<T> {
  const reasons: MatchReason[] = [];
  const tagged = pack.advantages ?? [];

  for (const advantage of answers.advantages) {
    if (tagged.includes(advantage)) reasons.push({ kind: 'advantage', value: advantage, points: 3 });
  }
  if (answers.commitment && pack.commitment === answers.commitment) {
    reasons.push({ kind: 'commitment', value: answers.commitment, points: 2 });
  }
  if (answers.payer && pack.payer === answers.payer) {
    reasons.push({ kind: 'payer', value: answers.payer, points: 1 });
  }
  if ((pack.sourceCount ?? 0) >= WELL_SOURCED_THRESHOLD) {
    reasons.push({ kind: 'evidence', value: String(pack.sourceCount), points: 1 });
  }

  const score = reasons.reduce((total, r) => total + r.points, 0);
  return { pack, score, reasons };
}

/** Newest first; a pack with no `verifiedAt` sorts after every pack that has one. */
function compareVerifiedAtDesc(a: FacetedPack, b: FacetedPack): number {
  const av = a.verifiedAt ?? '';
  const bv = b.verifiedAt ?? '';
  if (av === bv) return 0;
  if (!av) return 1;
  if (!bv) return -1;
  return av < bv ? 1 : -1;
}

/**
 * Score desc, then verifiedAt desc, then sourceCount desc, then title asc.
 *
 * The title tie-break is what makes the result deterministic: without a total order, two packs
 * on the same score could swap places between renders and the same three answers would hand
 * two buyers different "the answer" packs.
 */
function compareMatches(a: MatchResult<FacetedPack>, b: MatchResult<FacetedPack>): number {
  if (a.score !== b.score) return b.score - a.score;
  const byVerified = compareVerifiedAtDesc(a.pack, b.pack);
  if (byVerified !== 0) return byVerified;
  const bySources = (b.pack.sourceCount ?? 0) - (a.pack.sourceCount ?? 0);
  if (bySources !== 0) return bySources;
  return a.pack.title.localeCompare(b.pack.title, 'en');
}

export interface MatchOutcome<T extends FacetedPack = FacetedPack> {
  /** Null when the top score is 0, show the near-miss state, never a fabricated match. */
  winner: MatchResult<T> | null;
  /** Up to two, only ever packs that themselves scored above 0. */
  runnersUp: MatchResult<T>[];
  /** Every pack, ranked. Feeds "Show me everything that matched". */
  ranked: MatchResult<T>[];
}

export function rankMatches<T extends FacetedPack>(
  packs: readonly T[],
  answers: MatchAnswers,
): MatchOutcome<T> {
  const ranked = packs.map((pack) => scoreMatch(pack, answers)).sort(compareMatches);
  const scoring = ranked.filter((r) => r.score > 0);
  if (scoring.length === 0) return { winner: null, runnersUp: [], ranked };
  return { winner: scoring[0], runnersUp: scoring.slice(1, 3), ranked };
}

/** The catalogue state behind "Show me everything that matched", so the URL is already right. */
export function stateFromAnswers(answers: MatchAnswers): DiscoveryState {
  return {
    ...EMPTY_DISCOVERY_STATE,
    advantage: [...answers.advantages],
    commitment: answers.commitment,
    payer: answers.payer,
  };
}

// ---------------------------------------------------------------------------
// Similarity (spec Part 9)
// ---------------------------------------------------------------------------

/**
 * How alike two packs are, for the "more like this" row.
 *
 * Mechanism dominates and sector is a *penalty*, which is the whole point: the feedback's own
 * example is a buyer who likes the mechanics of B2B fee recovery but does not want another
 * vets business. Sector-similarity would hand them exactly the thing they said no to.
 */
export function scoreSimilar(a: FacetedPack, b: FacetedPack): number {
  let score = 0;
  if (a.mechanism && b.mechanism && a.mechanism === b.mechanism) score += 4;
  if (a.payer && b.payer && a.payer === b.payer) score += 2;
  if (a.effort && b.effort && a.effort === b.effort) score += 1;
  if (a.sector && b.sector && a.sector === b.sector) score -= 2;
  return score;
}

/**
 * Top 3 most similar packs, or `[]` when fewer than 2 score above 0, a "more like this" row
 * holding one weak suggestion is worse than no row, and on a mostly-untagged catalogue that is
 * the common case.
 */
export function similarPacks<T extends FacetedPack>(
  target: FacetedPack,
  all: readonly T[],
  limit = 3,
): T[] {
  const scored = all
    .filter((p) => p.id !== target.id)
    .map((pack) => ({ pack, score: scoreSimilar(target, pack) }))
    .filter((entry) => entry.score > 0)
    .sort((x, y) => {
      if (x.score !== y.score) return y.score - x.score;
      const byVerified = compareVerifiedAtDesc(x.pack, y.pack);
      if (byVerified !== 0) return byVerified;
      const bySources = (y.pack.sourceCount ?? 0) - (x.pack.sourceCount ?? 0);
      if (bySources !== 0) return bySources;
      return x.pack.title.localeCompare(y.pack.title, 'en');
    });

  if (scored.length < 2) return [];
  return scored.slice(0, limit).map((entry) => entry.pack);
}

// ---------------------------------------------------------------------------
// Title splitting
// ---------------------------------------------------------------------------

/** Comma, em dash, en dash, and a hyphen with spaces on both sides. A bare hyphen is left alone:
 *  it is usually part of a compound ("Private-Hire"), and splitting there mangles the name. The
 *  comma is the live separator since the marketeer rewrote the catalogue copy to drop em-dashes
 *  (the universal AI writing tell); em-dash and en-dash are kept as a safety net for any
 *  historical pack that resurfaces. */
// These are the separators this parser strips OUT of API-supplied pack titles, so the
// characters have to appear here literally rather than as displayed copy.
const TITLE_SEPARATORS = [', ', '—', '–', ' - ']; // dash-free-ignore

/**
 * Split "Brand, long descriptive subtitle" into a name a buyer can hold in their head and a
 * supporting descriptor.
 *
 * The version this replaces (`index.tsx:43-49`) matched the em dash only, so the 9 of 15 live
 * packs whose titles use another separator or none at all rendered their entire title as the
 * "name", which is why cards read as a paragraph. When there is no separator at all, the
 * descriptor falls back to `headline` rather than being invented from the title.
 */
export function splitTitle(
  title: string,
  headline?: string,
): { name: string; descriptor: string | null } {
  const fallback = { name: title, descriptor: headline?.trim() || null };

  let cut = -1;
  let separatorLength = 0;
  for (const separator of TITLE_SEPARATORS) {
    const at = title.indexOf(separator);
    if (at !== -1 && (cut === -1 || at < cut)) {
      cut = at;
      separatorLength = separator.length;
    }
  }
  if (cut === -1) return fallback;

  const name = title.slice(0, cut).trim();
  const descriptor = title.slice(cut + separatorLength).trim();
  return name && descriptor ? { name, descriptor } : fallback;
}

/** The longest heading that still scans as a shelf label rather than a paragraph. Mirrors
 *  `CARD_LINE_MAX` in `prospector/artifacts.py`; the front end re-checks rather than trusting
 *  the wire, because packs published by an older engine predate the enforcement. */
export const CARD_HEADING_MAX = 60;

/** What a pack card puts where. */
export interface CardHeading {
  /** The brand name, always. This is the pack's identity, what a basket line and an order
   *  confirmation must say, independently of whether the card chose to display it. */
  name: string;
  /** The card's H3. */
  heading: string;
  /** The brand name, shown small above the heading, only when the heading is not itself
   *  the name (otherwise the card would print the name twice). */
  eyebrow: string | null;
  /** Supporting line under the heading, or null when it would repeat the heading. */
  sub: string | null;
}

/**
 * Decide the card's hierarchy.
 *
 * A first-time visitor cannot buy from "PitchBrief", a brand name they have never heard is
 * the least useful string on the card, and it was the H3. But the descriptor derived from the
 * title runs to 90+ characters ("PitchCall Forensics, The Under-27 Gig Driver's
 * Insurance-Refusal Reversal & Telematics-Data Subject-Access Round"), so promoting THAT gives
 * twenty cards of wrapped bold text, which is not a shelf either.
 *
 * So the heading is the engine's short `cardLine` when there is one, with the brand demoted to
 * an eyebrow. When there is not, every pack published before the engine emitted it, and any
 * pack whose operator could not write a truthful short line, the pre-existing hierarchy is
 * kept exactly. Nothing is shortened here to manufacture a heading: a long line is left where
 * it already renders correctly rather than cut into a claim nobody made.
 */
/**
 * The three fields a heading is decided from, and nothing else.
 *
 * Narrowed from `FacetedPack` so the plain catalogue `Pack` can use it too. It had to: the
 * homepage called `cardHeading` and `/ideas/*` called `splitTitle` directly, so the SAME pack was
 * headed by its short descriptive card line on one page and by its brand name on the other. A
 * visitor who followed a category landing to the catalogue could not tell they were looking at
 * the same product twice.
 */
export interface CardHeadingInput {
  title: string;
  headline?: string;
  cardLine?: string;
}

/** A coined product name: an intercapped word (`HoursBack`, `ScopeDrift`). Mirrors
 *  `_TITLE_COINAGE` in `prospector/pack_linter.py`. All-caps initialisms (`NHS`, `HMRC`) do
 *  not match, which is the point: they are words the reader already knows. */
const COINED_NAME = /\b[A-Z][a-z]+[A-Z][A-Za-z]*\b/;

/**
 * Is this title written in the business-first format (founder decision 2026-08-13)?
 *
 * `<what the business does> for <who pays>`: no coined name, inside the card budget, and
 * naming a buyer either with "for" or with a qualifying clause after a comma. The three
 * conditions are exactly what `pack_linter.check_title` enforces on the way in, so the two
 * ends agree by construction rather than by comment.
 *
 * It has to be a test rather than an assumption because the catalogue is mixed while the
 * rewrite lands: a legacy title still leads with a name a first-time visitor cannot use, and
 * for those the pre-existing hierarchy (short `cardLine` as the heading, brand demoted to an
 * eyebrow) is still the right call. A business-first title IS the useful line, so promoting
 * it and demoting the card line is not a preference: it is the same rule applied to a title
 * that now carries the information.
 */
export function isBusinessFirstTitle(title: string): boolean {
  const t = (title ?? '').trim();
  if (!t || t.length > CARD_HEADING_MAX || COINED_NAME.test(t)) return false;
  return / for /i.test(t) || t.includes(', ');
}

export function cardHeading(pack: CardHeadingInput): CardHeading {
  const { name, descriptor } = splitTitle(pack.title, pack.headline);
  const card = pack.cardLine?.trim();

  const title = (pack.title ?? '').trim();
  if (isBusinessFirstTitle(title)) {
    const sub = card && card.toLowerCase() !== title.toLowerCase()
      ? card
      : pack.headline?.trim() || null;
    return { name: title, heading: title, eyebrow: null, sub: sub || null };
  }

  if (card && card.length <= CARD_HEADING_MAX) {
    return {
      name,
      heading: card,
      // Only worth a line if it says something the heading does not.
      eyebrow: name && name.toLowerCase() !== card.toLowerCase() ? name : null,
      sub: descriptor && descriptor.toLowerCase() !== card.toLowerCase() ? descriptor : null,
    };
  }

  return { name, heading: name, eyebrow: null, sub: descriptor };
}

// ── Discovery v2: intent extraction ──────────────────────────────────────

/**
 * Map free-text natural language to facet values using keyword matching.
 * Returns a partial DiscoveryState with only the facets the text mentions.
 * Never overrides existing selections; the caller merges.
 *
 * Matching uses word-boundary checks to avoid substring false positives
 * ("part" should not match part_time, "even" should not match evenings).
 */
export function extractIntent(signal: string): Partial<DiscoveryState> {
  if (!signal || !signal.trim()) return {};

  const s = signal.toLowerCase().trim();
  const result: Partial<DiscoveryState> = {};

  // Word-boundary helper: token is a whole word/phrase in the signal
  const hasWord = (word: string): boolean => {
    // Escape special regex chars, then match with word boundaries
    const escaped = word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    return new RegExp(`\\b${escaped}\\b`, 'i').test(s);
  };

  // ── advantage (multi-select) ──
  const advantages: string[] = [];
  if (hasWord('code') || hasWord('build') || hasWord('software') || hasWord('technical') || hasWord('developer') || hasWord('coding')) {
    advantages.push('code');
  }
  if (hasWord('sell') || hasWord('sales') || hasWord('marketing') || hasWord('growth')) {
    advantages.push('sales');
  }
  if (hasWord('ops') || hasWord('operations') || hasWord('systems') || hasWord('automate')) {
    advantages.push('ops');
  }
  if (hasWord('design') || hasWord('creative') || hasWord('brand')) {
    advantages.push('audience');
  }
  if (advantages.length > 0) result.advantage = advantages as Advantage[];

  // ── commitment (single-select, last match wins) ──
  if (hasWord('evenings') || hasWord('evening')) {
    result.commitment = 'evenings';
  }
  if (hasWord('weekend') || hasWord('weekends') || hasWord('side hustle') || hasWord('spare time') || hasWord('part-time') || hasWord('part time')) {
    result.commitment = 'part_time';
  }
  if (hasWord('full-time') || hasWord('fulltime') || hasWord('quit my job') || hasWord('quit') || hasWord('main job') || hasWord('primary')) {
    result.commitment = 'full_time';
  }

  // ── payer (single-select, last match wins) ──
  if (hasWord('b2b') || hasWord('business') || hasWord('businesses') || hasWord('company') || hasWord('enterprise') || hasWord('saas')) {
    result.payer = 'b2b';
  }
  if (hasWord('b2c') || hasWord('consumer') || hasWord('consumers') || hasWord('people') || hasWord('individual')) {
    result.payer = 'b2c';
  }

  // ── effort (single-select, last match wins) ──
  if (hasWord('done for you') || hasWord('automated') || hasWord('automatable') || hasWord('passive') || hasWord('hands-off') || hasWord('hands off') || hasWord('low touch') || hasWord('low-touch')) {
    result.effort = 'automatable';
  }
  if (hasWord('hands-on') || hasWord('hands on') || hasWord('active') || hasWord('build it') || hasWord('run it')) {
    result.effort = 'hands_on';
  }

  return result;
}

/**
 * Generate one-line match reasons for a pack given an intent.
 * Returns up to 2 reasons, most specific first, in buyer-facing language.
 * Returns empty array if nothing matches.
 */
export function matchReasons(pack: FacetedPack, intent: DiscoveryState): string[] {
  const reasons: string[] = [];

  // Advantage match
  if (intent.advantage.length > 0 && pack.advantages) {
    const matched = intent.advantage.filter((a) => pack.advantages!.includes(a));
    if (matched.length > 0) {
      const label = shortLabel('advantage', matched[0]);
      if (label) reasons.push(`Matches your skills (${label})`);
    }
  }

  // Payer match
  if (intent.payer && pack.payer && pack.payer === intent.payer) {
    const label = shortLabel('payer', intent.payer);
    if (label) reasons.push(`${label} revenue model`);
  }

  // Commitment match
  if (intent.commitment && pack.commitment && pack.commitment === intent.commitment) {
    const label = shortLabel('commitment', intent.commitment);
    if (label) reasons.push(`Fits your ${label.toLowerCase()} schedule`);
  }

  // Effort match
  if (intent.effort && pack.effort && pack.effort === intent.effort) {
    const label = shortLabel('effort', intent.effort);
    // No dash of any kind. This string is rendered, and nothing between here and the DOM turns
    // `--` into anything, so it printed as two hyphens; `dashFree.test.ts` bans the en dash that
    // would otherwise replace it. The sentence does not need the punctuation.
    if (label) reasons.push(`${label} matches your preference`);
  }

  return reasons.slice(0, 2);
}
