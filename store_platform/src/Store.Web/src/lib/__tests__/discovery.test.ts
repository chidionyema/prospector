import { describe, expect, it } from 'vitest';

import {
  EMPTY_DISCOVERY_STATE,
  EMPTY_MATCH_ANSWERS,
  activeConstraintCount,
  activeFacetSelectionCount,
  decodeDiscoveryState,
  encodeDiscoveryState,
  facetCounts,
  filterPacks,
  isFiltered,
  matchesQuery,
  nearMisses,
  foldFacetGroups,
  offeredFacetValues,
  rankMatches,
  scoreMatch,
  scoreSimilar,
  similarPacks,
  stateFromAnswers,
  type DiscoveryState,
  type FacetedPack,
} from '../discovery';

function pack(id: string, overrides: Partial<FacetedPack> = {}): FacetedPack {
  return { id, title: `Pack ${id}`, ...overrides };
}

/** A pack the engine could not justify tagging. The subject of the null rule. */
const untagged = pack('untagged');

describe('filterPacks, the null rule (AC-10)', () => {
  const tagged = pack('tagged', { effort: 'hands_on' });
  const other = pack('other', { effort: 'automatable' });
  const packs = [tagged, other, untagged];

  it('never shows an untagged pack under a specific value', () => {
    const state: DiscoveryState = { ...EMPTY_DISCOVERY_STATE, effort: 'hands_on' };
    expect(filterPacks(packs, state).map((p) => p.id)).toEqual(['tagged']);
  });

  it('always shows an untagged pack under "All"', () => {
    expect(filterPacks(packs, EMPTY_DISCOVERY_STATE).map((p) => p.id)).toEqual([
      'tagged',
      'other',
      'untagged',
    ]);
  });

  it('treats an empty advantages list as untagged, not as a match', () => {
    const empty = pack('empty', { advantages: [] });
    const state: DiscoveryState = { ...EMPTY_DISCOVERY_STATE, advantage: ['code'] };
    expect(filterPacks([empty], state)).toEqual([]);
  });

  it('ORs within advantage and ANDs across facets', () => {
    const builder = pack('builder', { advantages: ['code'], payer: 'b2b' });
    const seller = pack('seller', { advantages: ['sales'], payer: 'b2c' });
    const both = pack('both', { advantages: ['code', 'sales'], payer: 'b2b' });

    const eitherAdvantage: DiscoveryState = {
      ...EMPTY_DISCOVERY_STATE,
      advantage: ['code', 'sales'],
    };
    expect(filterPacks([builder, seller, both], eitherAdvantage)).toHaveLength(3);

    const andPayer: DiscoveryState = { ...eitherAdvantage, payer: 'b2b' };
    expect(filterPacks([builder, seller, both], andPayer).map((p) => p.id)).toEqual([
      'builder',
      'both',
    ]);
  });

  it('applies the text query alongside the facets', () => {
    const state: DiscoveryState = { ...EMPTY_DISCOVERY_STATE, q: 'tag' };
    expect(filterPacks([tagged, other], state).map((p) => p.id)).toEqual(['tagged']);
  });
});

describe('matchesQuery (AC-13 regression guard)', () => {
  const plateStart = pack('plate', {
    title: "PlateStart, The Gig Driver's Private-Hire Licence Route Optimizer",
    oneLine: 'A route optimizer for drivers moving off Uber onto private hire work',
    whoPays: 'New private hire drivers leaving Uber',
  });

  it('finds a term that appears only outside the title', () => {
    expect(plateStart.title.toLowerCase()).not.toContain('uber');
    expect(matchesQuery(plateStart, 'uber')).toBe(true);
  });

  it('is case-insensitive and whitespace-tolerant', () => {
    expect(matchesQuery(plateStart, '  UBER ')).toBe(true);
  });

  it('matches everything on an empty query', () => {
    expect(matchesQuery(untagged, '   ')).toBe(true);
  });

  it('does not bridge two fields into a phantom match', () => {
    expect(matchesQuery(plateStart, 'Optimizer A route')).toBe(false);
  });
});

describe('URL codec (AC-7)', () => {
  const state: DiscoveryState = {
    q: 'holiday pay',
    advantage: ['code', 'sales'],
    sector: 'employment_pay',
    payer: 'b2b',
    effort: 'automatable',
    commitment: 'evenings',
    mechanism: 'vertical_tool',
  };

  it('round-trips a full state', () => {
    expect(decodeDiscoveryState(encodeDiscoveryState(state))).toEqual(state);
  });

  it('round-trips the empty state as an empty query string', () => {
    expect(encodeDiscoveryState(EMPTY_DISCOVERY_STATE)).toBe('');
    expect(decodeDiscoveryState('')).toEqual(EMPTY_DISCOVERY_STATE);
  });

  it('accepts a leading ? and Next’s parsed query object alike', () => {
    const encoded = encodeDiscoveryState(state);
    expect(decodeDiscoveryState(`?${encoded}`)).toEqual(state);
    expect(
      decodeDiscoveryState({ q: 'holiday pay', adv: 'code,sales', sector: ['employment_pay'] }),
    ).toEqual({ ...EMPTY_DISCOVERY_STATE, q: 'holiday pay', advantage: ['code', 'sales'], sector: 'employment_pay' });
  });

  it('drops values outside the vocabulary instead of filtering on them', () => {
    const decoded = decodeDiscoveryState('sector=gardening&payer=b2b&adv=code,wizardry');
    expect(decoded.sector).toBeNull();
    expect(decoded.payer).toBe('b2b');
    expect(decoded.advantage).toEqual(['code']);
  });

  it('de-duplicates repeated advantages so the round-trip is idempotent', () => {
    const once = decodeDiscoveryState('adv=code,code');
    expect(once.advantage).toEqual(['code']);
    expect(decodeDiscoveryState(encodeDiscoveryState(once))).toEqual(once);
  });

  it('survives undefined (a cold SSR load with no query)', () => {
    expect(decodeDiscoveryState(undefined)).toEqual(EMPTY_DISCOVERY_STATE);
  });

  it('reports whether anything is actually filtered', () => {
    expect(isFiltered(EMPTY_DISCOVERY_STATE)).toBe(false);
    expect(isFiltered({ ...EMPTY_DISCOVERY_STATE, q: '  ' })).toBe(false);
    expect(isFiltered({ ...EMPTY_DISCOVERY_STATE, payer: 'b2b' })).toBe(true);
    expect(activeConstraintCount(state)).toBe(6);
  });
});

describe('facetCounts', () => {
  const packs = [
    pack('a', { payer: 'b2b', effort: 'automatable' }),
    pack('b', { payer: 'b2b', effort: 'hands_on' }),
    pack('c', { payer: 'b2c', effort: 'automatable' }),
    untagged,
  ];

  it('counts a facet with its own constraint relaxed, so the number answers "if I click this"', () => {
    const state: DiscoveryState = { ...EMPTY_DISCOVERY_STATE, payer: 'b2b' };
    expect(facetCounts(packs, state, 'payer')).toEqual({ b2b: 2, b2c: 1 });
  });

  it('narrows other facets by the active state', () => {
    const state: DiscoveryState = { ...EMPTY_DISCOVERY_STATE, payer: 'b2b' };
    expect(facetCounts(packs, state, 'effort')).toEqual({ automatable: 1, hands_on: 1 });
  });

  it('never counts an untagged pack toward a value', () => {
    const counts = facetCounts(packs, EMPTY_DISCOVERY_STATE, 'mechanism');
    expect(counts).toEqual({});
  });
});

describe('scoreMatch (spec Part 5 table)', () => {
  it('gives +3 per advantage overlap', () => {
    const p = pack('p', { advantages: ['code', 'sales'] });
    expect(scoreMatch(p, { ...EMPTY_MATCH_ANSWERS, advantages: ['code'] }).score).toBe(3);
    expect(scoreMatch(p, { ...EMPTY_MATCH_ANSWERS, advantages: ['code', 'sales'] }).score).toBe(6);
  });

  it('gives +2 for an exact commitment and +1 for an exact payer', () => {
    const p = pack('p', { commitment: 'evenings', payer: 'b2b' });
    expect(scoreMatch(p, { ...EMPTY_MATCH_ANSWERS, commitment: 'evenings' }).score).toBe(2);
    expect(scoreMatch(p, { ...EMPTY_MATCH_ANSWERS, payer: 'b2b' }).score).toBe(1);
  });

  it('gives 0 for "don’t mind" on payer rather than a miss', () => {
    const p = pack('p', { payer: 'b2b' });
    expect(scoreMatch(p, { ...EMPTY_MATCH_ANSWERS, payer: null }).score).toBe(0);
  });

  it('gives +1 for ≥15 sources and nothing below the threshold', () => {
    expect(scoreMatch(pack('p', { sourceCount: 15 }), EMPTY_MATCH_ANSWERS).score).toBe(1);
    expect(scoreMatch(pack('p', { sourceCount: 14 }), EMPTY_MATCH_ANSWERS).score).toBe(0);
    expect(scoreMatch(pack('p'), EMPTY_MATCH_ANSWERS).score).toBe(0);
  });

  it('never goes negative and never scores a facet the pack is not tagged for', () => {
    const answers = { advantages: ['code' as const], commitment: 'evenings' as const, payer: 'b2b' as const };
    const result = scoreMatch(untagged, answers);
    expect(result.score).toBe(0);
    expect(result.reasons).toEqual([]);
  });

  it('reports why it scored, for the result sentence', () => {
    const p = pack('p', { advantages: ['code'], commitment: 'evenings', sourceCount: 19 });
    const result = scoreMatch(p, { ...EMPTY_MATCH_ANSWERS, advantages: ['code'], commitment: 'evenings' });
    expect(result.score).toBe(6);
    expect(result.reasons.map((r) => r.kind)).toEqual(['advantage', 'commitment', 'evidence']);
  });
});

describe('rankMatches (AC-6, AC-8, AC-9)', () => {
  const answers = { advantages: ['code' as const], commitment: 'evenings' as const, payer: null };

  it('orders by score, then verifiedAt desc, then sourceCount desc, then title asc', () => {
    const packs = [
      pack('low', { advantages: ['code'] }),
      pack('older', { advantages: ['code'], commitment: 'evenings', verifiedAt: '2026-07-01' }),
      pack('newer', { advantages: ['code'], commitment: 'evenings', verifiedAt: '2026-07-20' }),
    ];
    expect(rankMatches(packs, answers).ranked.map((r) => r.pack.id)).toEqual([
      'newer',
      'older',
      'low',
    ]);
  });

  it('breaks a full tie on title, so the same answers always give the same winner', () => {
    const packs = [
      { ...pack('b', { advantages: ['code'] }), title: 'Beta' },
      { ...pack('a', { advantages: ['code'] }), title: 'Alpha' },
    ];
    expect(rankMatches(packs, answers).winner?.pack.title).toBe('Alpha');
    // Same input, reversed order in, same answer out.
    expect(rankMatches([...packs].reverse(), answers).winner?.pack.title).toBe('Alpha');
  });

  it('sorts a pack with no verifiedAt after one that has it', () => {
    const packs = [
      pack('undated', { advantages: ['code'] }),
      pack('dated', { advantages: ['code'], verifiedAt: '2026-01-01' }),
    ];
    expect(rankMatches(packs, answers).ranked.map((r) => r.pack.id)).toEqual(['dated', 'undated']);
  });

  it('returns no winner when the top score is 0 (AC-8)', () => {
    const outcome = rankMatches([untagged, pack('x', { payer: 'b2c' })], answers);
    expect(outcome.winner).toBeNull();
    expect(outcome.runnersUp).toEqual([]);
    expect(outcome.ranked).toHaveLength(2);
  });

  it('offers at most two runners-up, and only ones that scored', () => {
    const packs = [
      pack('1', { advantages: ['code'], sourceCount: 19 }),
      pack('2', { advantages: ['code'] }),
      pack('3', { advantages: ['code'] }),
      pack('4', { advantages: ['code'] }),
      untagged,
    ];
    const outcome = rankMatches(packs, answers);
    expect(outcome.runnersUp).toHaveLength(2);
    expect(outcome.runnersUp.every((r) => r.score > 0)).toBe(true);
  });

  /**
   * The previous version of this test built a pack tagged `nocode` and proved the scorer scores
   * it. True, and vacuous: it never asked whether the *catalogue* holds such packs. Measured on
   * the live catalogue 2026-08-01, `nocode` is carried by 1 pack of 49, so the answer that was
   * documented as one that "must never dead-end" was routing a beginner into a one-pack shelf,
   * and this test reported green throughout. "None of these yet" now carries no advantage at
   * all, so these two assert the property that actually matters.
   */
  it('never dead-ends "None of these yet", no advantage constraint, still ranks (AC-9)', () => {
    const beginner = { advantages: [], commitment: 'evenings' as const, payer: null };
    const packs = [
      pack('evening-pack', { advantages: ['code'], commitment: 'evenings' }),
      pack('elsewhere', { advantages: ['ops'], commitment: 'full_time' }),
    ];
    expect(rankMatches(packs, beginner).winner?.pack.id).toBe('evening-pack');
  });

  it('hands a beginner the whole shelf, not the packs matching a skill they disclaimed', () => {
    const state = stateFromAnswers({ advantages: [], commitment: 'evenings', payer: null });
    expect(state.advantage).toEqual([]);
    // The regression: `advantage: ['nocode']` arrived here as a hard constraint in
    // applyDiscoveryState, and only one live pack carries `nocode`.
    const packs = [pack('a', { advantages: ['code'] }), pack('b', { advantages: ['ops'] })];
    expect(filterPacks(packs, { ...state, commitment: null })).toHaveLength(2);
  });

  it('hands the catalogue a state that reproduces the quiz', () => {
    expect(stateFromAnswers({ advantages: ['code'], commitment: 'evenings', payer: 'b2b' })).toEqual({
      ...EMPTY_DISCOVERY_STATE,
      advantage: ['code'],
      commitment: 'evenings',
      payer: 'b2b',
    });
  });
});

describe('scoreSimilar / similarPacks (AC-21)', () => {
  const target = pack('target', {
    mechanism: 'transaction_broker',
    payer: 'b2b',
    effort: 'part_automatable',
    sector: 'pets_animals',
  });

  it('weights mechanism above payer above effort, and penalises the same sector', () => {
    expect(scoreSimilar(target, pack('m', { mechanism: 'transaction_broker' }))).toBe(4);
    expect(scoreSimilar(target, pack('p', { payer: 'b2b' }))).toBe(2);
    expect(scoreSimilar(target, pack('e', { effort: 'part_automatable' }))).toBe(1);
    expect(scoreSimilar(target, pack('s', { sector: 'pets_animals' }))).toBe(-2);
  });

  it('scores an untagged pack 0 on both sides, never a match by shared absence', () => {
    expect(scoreSimilar(target, untagged)).toBe(0);
    expect(scoreSimilar(untagged, untagged)).toBe(0);
  });

  it('prefers same mechanism in a different sector over same sector', () => {
    const differentSector = pack('cross', { mechanism: 'transaction_broker', sector: 'employment_pay' });
    const sameSector = pack('same', { mechanism: 'transaction_broker', sector: 'pets_animals' });
    expect(similarPacks(target, [sameSector, differentSector])).toEqual([differentSector, sameSector]);
  });

  it('excludes the pack itself', () => {
    const twin = { ...target, id: 'twin' };
    expect(similarPacks(target, [target, twin, pack('p', { payer: 'b2b' })]).map((p) => p.id)).not.toContain(
      'target',
    );
  });

  it('hides the row entirely when fewer than 2 candidates score above 0', () => {
    expect(similarPacks(target, [pack('only', { mechanism: 'transaction_broker' }), untagged])).toEqual([]);
    expect(similarPacks(target, [untagged])).toEqual([]);
  });

  it('returns at most 3', () => {
    const candidates = ['a', 'b', 'c', 'd'].map((id) =>
      pack(id, { mechanism: 'transaction_broker', sourceCount: id.charCodeAt(0) }),
    );
    expect(similarPacks(target, candidates)).toHaveLength(3);
  });
});

describe('nearMisses, the rescue before the email form (AC-16)', () => {
  const target = pack('target', { payer: 'b2b', effort: 'hands_on', commitment: 'evenings' });
  const oneOff = pack('one-off', { payer: 'b2c', effort: 'hands_on', commitment: 'evenings' });
  const twoOff = pack('two-off', { payer: 'b2c', effort: 'automatable', commitment: 'evenings' });
  const packs = [target, oneOff, twoOff];

  const state: DiscoveryState = {
    ...EMPTY_DISCOVERY_STATE,
    payer: 'b2b',
    effort: 'hands_on',
    commitment: 'evenings',
  };

  it('returns only packs that fail exactly one active constraint', () => {
    expect(nearMisses(packs, state).map((m) => m.pack.id)).toEqual(['one-off']);
  });

  it('names the facet that was missed and what the pack actually carries', () => {
    const [miss] = nearMisses(packs, state);
    expect(miss.kind).toBe('payer');
    expect(miss.wanted).toBe('b2b');
    expect(miss.actual).toBe('b2c');
  });

  it('reports an untagged pack as a miss with a null actual, never as a match', () => {
    const blank = pack('blank', { effort: 'hands_on', commitment: 'evenings' });
    const [miss] = nearMisses([blank], state);
    expect(miss.kind).toBe('payer');
    expect(miss.actual).toBeNull();
  });

  it('hands back a state that actually includes the pack when applied', () => {
    const [miss] = nearMisses(packs, state);
    expect(filterPacks(packs, miss.relaxedState).map((p) => p.id)).toContain('one-off');
  });

  it('relaxes advantage as a whole group, since it is OR-ed', () => {
    const seller = pack('seller', { advantages: ['sales'], payer: 'b2b' });
    const withAdvantage: DiscoveryState = {
      ...EMPTY_DISCOVERY_STATE,
      advantage: ['code'],
      payer: 'b2b',
    };
    const [miss] = nearMisses([seller], withAdvantage);
    expect(miss.kind).toBe('advantage');
    expect(miss.relaxedState.advantage).toEqual([]);
    expect(miss.relaxedState.payer).toBe('b2b');
  });

  it('is empty when the text query is what failed, that is the waitlist case, not a near miss', () => {
    const queried: DiscoveryState = { ...EMPTY_DISCOVERY_STATE, q: 'nothing-matches-this', payer: 'b2b' };
    expect(nearMisses(packs, queried)).toEqual([]);
  });

  it('never returns a pack that already matches everything', () => {
    expect(nearMisses(packs, state).map((m) => m.pack.id)).not.toContain('target');
  });
});

describe('offeredFacetValues, which controls are worth rendering', () => {
  // Three packs carry `evenings`, one carries `full_time`, the shape the live catalogue had on
  // 2026-07-31 (part_time 13 / evenings 6 / full_time 1 of 42).
  const packs = [
    pack('a', { commitment: 'evenings', payer: 'b2b' }),
    pack('b', { commitment: 'evenings', payer: 'b2b' }),
    pack('c', { commitment: 'evenings', payer: 'b2c' }),
    pack('rare', { commitment: 'full_time', payer: 'b2c' }),
    untagged,
  ];

  it('drops a value only one pack in the catalogue carries', () => {
    expect(offeredFacetValues(packs, EMPTY_DISCOVERY_STATE, 'commitment')).toEqual(['evenings']);
  });

  it('keeps that value once it is selected, so the buyer can switch it back off', () => {
    // The shared-link case: ?commitment=full_time must not render a chip-less group the buyer
    // is trapped in.
    const state: DiscoveryState = { ...EMPTY_DISCOVERY_STATE, commitment: 'full_time' };
    expect(offeredFacetValues(packs, state, 'commitment')).toEqual(['evenings', 'full_time']);
  });

  it('does not let another active filter delete an option, the threshold is catalogue-wide', () => {
    // Under payer=b2c only ONE pack carries `evenings`. A pool-relative threshold would remove
    // the control the buyer is looking at mid-click; a catalogue-relative one does not.
    const state: DiscoveryState = { ...EMPTY_DISCOVERY_STATE, payer: 'b2c' };
    expect(facetCounts(packs, state, 'commitment').evenings).toBe(1);
    expect(offeredFacetValues(packs, state, 'commitment')).toEqual(['evenings']);
  });

  it('does not let a search query delete an option either', () => {
    const state: DiscoveryState = { ...EMPTY_DISCOVERY_STATE, q: 'Pack a' };
    expect(offeredFacetValues(packs, state, 'commitment')).toEqual(['evenings']);
  });

  it('offers nothing for a facet the engine has tagged nowhere (AC-12)', () => {
    expect(offeredFacetValues(packs, EMPTY_DISCOVERY_STATE, 'sector')).toEqual([]);
  });

  it('still drops a value no pack in the current pool carries at all', () => {
    const state: DiscoveryState = { ...EMPTY_DISCOVERY_STATE, payer: 'b2b' };
    expect(offeredFacetValues(packs, state, 'commitment')).toEqual(['evenings']);
  });
});

describe('foldFacetGroups, progressive disclosure that cannot hide a constraint', () => {
  const group = (id: string, active: string[] = []) => ({ id, activeValues: active });
  const six = ['a', 'b', 'c', 'd', 'e', 'f'].map((id) => group(id));

  it('keeps the first n open and folds the rest', () => {
    const fold = foldFacetGroups(six, 3, false);
    expect(fold.visible.map((g) => g.id)).toEqual(['a', 'b', 'c']);
    expect(fold.foldedCount).toBe(3);
    expect(fold.canFold).toBe(true);
  });

  it('shows everything once expanded, and still offers the way back', () => {
    const fold = foldFacetGroups(six, 3, true);
    expect(fold.visible).toHaveLength(6);
    expect(fold.foldedCount).toBe(0);
    expect(fold.canFold).toBe(true);
  });

  it('never folds a group holding an active selection, and withdraws the toggle with it', () => {
    // The failure this prevents: a buyer opens a shared URL carrying `?mechanism=vertical_tool`,
    // sees a shelf cut to four packs, and has no control on screen naming the cut, because the
    // group that owns it is the fifth, below the fold. Collapsed is not an option here, so the
    // toggle must go too: leaving it would let one click re-hide the live constraint.
    const constrained = [...six.slice(0, 4), group('e', ['vertical_tool']), group('f')];
    const fold = foldFacetGroups(constrained, 3, false);
    expect(fold.visible.map((g) => g.id)).toEqual(['a', 'b', 'c', 'd', 'e', 'f']);
    expect(fold.canFold).toBe(false);
  });

  it('ignores a selection that is already above the fold', () => {
    const constrained = [group('a', ['code']), ...six.slice(1)];
    expect(foldFacetGroups(constrained, 3, false).foldedCount).toBe(3);
  });

  it('offers no toggle when there is nothing to fold', () => {
    expect(foldFacetGroups(six.slice(0, 3), 3, false).canFold).toBe(false);
    expect(foldFacetGroups(six.slice(0, 2), 3, false).visible).toHaveLength(2);
  });

  it('has no collapse-everything mode', () => {
    const fold = foldFacetGroups(six, 0, false);
    expect(fold.visible).toHaveLength(6);
    expect(fold.canFold).toBe(false);
  });
});

describe('activeFacetSelectionCount, the "Filters (n)" badge', () => {
  it('counts every lit chip, not every AND-ed constraint', () => {
    const state: DiscoveryState = {
      ...EMPTY_DISCOVERY_STATE,
      advantage: ['code', 'sales'],
      payer: 'b2b',
    };
    // activeConstraintCount collapses advantage to 1 because the near-miss rule needs it to.
    // A badge reading "1" beside three lit chips is a visible lie, hence the second function.
    expect(activeConstraintCount(state)).toBe(2);
    expect(activeFacetSelectionCount(state)).toBe(3);
  });

  it('ignores the text query, which has its own visible control', () => {
    expect(activeFacetSelectionCount({ ...EMPTY_DISCOVERY_STATE, q: 'pets' })).toBe(0);
  });
});
