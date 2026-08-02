import Link from 'next/link';
import React, { useEffect, useMemo, useState } from 'react';

import { Button, Icon } from '@/components/ui';
import { cx } from '@/components/ui/cx';
import { track } from '@/lib/analytics';
import { formatPrice, type Pack } from '@/lib/api/client';
import {
  EMPTY_MATCH_ANSWERS,
  rankMatches,
  splitTitle,
  stateFromAnswers,
  type DiscoveryState,
  type MatchAnswers,
  type MatchResult,
} from '@/lib/discovery';
import type { Advantage, Commitment, Payer } from '@/lib/facets';

import { FacetChips } from './FacetChips';

/**
 * The three-question router (spec Part 5). Copy is verbatim from the spec, it is the promise
 * the result screen has to keep, including the promise to say "we haven't built it yet".
 *
 * The one thing this component must never do is produce a winner when nothing scored. A
 * fabricated match is the exact failure the whole story exists to fix, and it stays a failure at
 * any catalogue size, so a top score of 0 routes to the near-miss state instead (AC-8).
 *
 * COLLAPSED BY DEFAULT, and this component is only mounted once it has been opened. Expanded, the
 * three fieldsets are ~470px of form, and they sat between the hero and the shelf: at 1280x720 the
 * first pack card was at y=1094, below a 720px fold, so a storefront whose entire pitch is "here is
 * what survived" opened on a questionnaire instead of on the product. The router is a shortcut for
 * a buyer who wants one, not a toll gate for the buyer who would rather just look. `open` lives in
 * the parent (`CatalogBrowser`) rather than here because the thing that opens it, `MatchmakerTrigger`
 *, sits in the toolbar row next to search and sort, where it costs no vertical space at all.
 */

/**
 * Q1, multi-select, max 2, plus one mutually-exclusive escape hatch.
 *
 * "None of these yet" is a real answer that must never dead-end, and it carries
 * `advantage: null` to keep that promise. This is the null rule (`facets.ts:18`) applied to the
 * router: a buyer saying they hold none of these skills has not claimed they can build with
 * no-code tools, and recording it as `nocode` turned "I have nothing" into an assertion nobody
 * made.
 *
 * It mattered, not just semantically. `stateFromAnswers` copies the answer into the URL, so
 * "Show me everything that matched" used to hand a beginner `?adv=nocode`, and
 * `applyDiscoveryState` hard-filters on it. Measured on the live catalogue 2026-08-01, `nocode`
 * is carried by **1 pack of 49**, so the least confident buyer in the funnel was filtered down
 * to a single pack by answering honestly. `discovery.ts` had already dropped the spec's
 * `hands_on` half of this mapping for dead-ending a beginner; the data now says the `nocode`
 * half dead-ends them too.
 *
 * `nocode` is NOT retired from the vocabulary, one pack earns it on its own evidence (CureSafe
 * Strip, whose dossier names a Shopify build in so many words). It is simply no longer the
 * dumping ground for "nothing".
 */
export const Q1_OPTIONS: ReadonlyArray<{ text: string; advantage: Advantage | null }> = [
  { text: 'I can build software', advantage: 'code' },
  { text: 'I can sell', advantage: 'sales' },
  { text: 'I can run operations', advantage: 'ops' },
  { text: 'I have an audience', advantage: 'audience' },
  { text: 'None of these yet', advantage: null },
];

export const Q2_OPTIONS: ReadonlyArray<{ text: string; commitment: Commitment }> = [
  { text: 'Evenings and weekends', commitment: 'evenings' },
  { text: 'Part time, ~20 hrs', commitment: 'part_time' },
  { text: 'Full time, this is the plan', commitment: 'full_time' },
];

/**
 * `payer: null` is "Don't mind", the spec scores it 0, never as a miss. The option carries its
 * own id so "Don't mind" can be a *chosen* answer that looks chosen, distinct from Q3 being
 * skipped; both produce the same `null` in the scored answers.
 */
export const Q3_OPTIONS: ReadonlyArray<{ id: string; text: string; payer: Payer | null }> = [
  { id: 'b2b', text: 'Businesses', payer: 'b2b' },
  { id: 'b2c', text: 'Consumers', payer: 'b2c' },
  { id: 'b2g', text: 'Councils and public bodies', payer: 'b2g' },
  { id: 'any', text: "Don't mind", payer: null },
];

const MAX_Q1 = 2;

function OptionButton({
  selected,
  onClick,
  children,
}: {
  selected: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  // The tick is not decoration: selection here is a border-and-tint change, and on Q1 two
  // options can be lit at once, a colour-only signal both fails low-vision buyers and reads
  // as "highlighted" rather than "chosen". aria-pressed already tells a screen reader; the
  // tick tells everyone else the same thing.
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={selected}
      className={cx(
        'flex items-center justify-between gap-3 rounded-xl border px-4 py-3 text-left text-sm font-semibold transition-all duration-150',
        selected
          ? 'border-primary bg-primary/5 text-text shadow-[0_1px_3px_rgba(0,0,0,0.06)]'
          : 'border-border bg-surface text-text/80 hover:border-text/20 hover:bg-bg',
      )}
    >
      {children}
      <span
        aria-hidden
        className={cx(
          'flex h-5 w-5 flex-none items-center justify-center rounded-full transition-all duration-150',
          selected ? 'bg-primary text-white' : 'bg-transparent text-transparent ring-1 ring-inset ring-border',
        )}
      >
        <Icon name="check" size={11} />
      </span>
    </button>
  );
}

/**
 * Sentence-slot phrases for the reason line, one per facet value that can score.
 *
 * The chip labels ("Suits builders", "Evenings-friendly") are heading fragments, and dropping
 * them into a sentence produced "It matches you on suits builders, evenings-friendly", the
 * same heading-vs-noun trap `KIND_NOUN` exists for (`lib/facets.ts`). These strings are written
 * for exactly one slot: after "Picked because ". They live here and not in `facets.ts` because
 * the reason line is the only sentence that speaks about the buyer's own answers, and each
 * phrase deliberately echoes the wording of the option the buyer just clicked.
 */
const REASON_PHRASES: Record<'advantage' | 'commitment' | 'payer', Record<string, string>> = {
  advantage: {
    code: 'you can build software',
    nocode: 'it needs no code',
    sales: 'you can sell',
    ops: 'you can run operations',
    audience: 'you have an audience',
  },
  commitment: {
    evenings: 'it fits evenings and weekends',
    part_time: 'it fits part-time hours',
    full_time: 'it earns full-time focus',
  },
  payer: {
    b2b: 'it sells to businesses',
    b2c: 'it sells to consumers',
    b2g: 'it sells to public bodies',
  },
};

/** "a, b and c", the serial join that keeps a three-reason sentence readable. */
function joinClauses(parts: string[]): string {
  if (parts.length <= 1) return parts.join('');
  return `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}`;
}

/**
 * One sentence saying why this pack won, built only from facets that actually scored. If the
 * only thing that scored was the evidence point, the sentence says so rather than implying a
 * fit the answers did not establish.
 */
function reasonSentence(result: MatchResult): string {
  const parts: string[] = [];
  for (const reason of result.reasons) {
    if (reason.kind === 'advantage' || reason.kind === 'commitment' || reason.kind === 'payer') {
      const phrase = REASON_PHRASES[reason.kind][reason.value];
      if (phrase) parts.push(phrase);
    }
  }
  const evidence = result.reasons.find((r) => r.kind === 'evidence');
  const tail = evidence ? `Backed by ${evidence.value} sources.` : '';
  if (parts.length === 0) return tail || 'It is the best-evidenced pack in the catalogue.';
  return `Picked because ${joinClauses(parts)}. ${tail}`.trim();
}

function WinnerCard({ result }: { result: MatchResult<Pack> }) {
  const { pack } = result;
  const { name, descriptor } = splitTitle(pack.title, pack.headline);
  return (
    <div className="rounded-2xl border border-primary/30 bg-surface p-6 shadow-[0_18px_40px_rgba(0,0,0,0.08)]">
      <span className="font-mono text-[11px] font-bold uppercase tracking-widest text-primary">Build this one.</span>
      <h3 className="mt-2 text-2xl font-black leading-tight tracking-tight text-text">{name}</h3>
      {descriptor && <p className="mt-1 text-sm leading-relaxed text-muted">{descriptor}</p>}
      <p className="mt-3 text-sm font-medium leading-relaxed text-text/80">{reasonSentence(result)}</p>
      <FacetChips pack={pack} className="mt-4" />
      <div className="mt-5 flex flex-wrap items-center gap-4">
        <Link href={`/pack/${pack.id}`}>
          <Button variant="prominent">See the pack, {formatPrice(pack.price)}</Button>
        </Link>
      </div>
    </div>
  );
}

function RunnerUp({ result }: { result: MatchResult<Pack> }) {
  const { name, descriptor } = splitTitle(result.pack.title, result.pack.headline);
  return (
    <Link
      href={`/pack/${result.pack.id}`}
      className="flex flex-col rounded-xl border border-border bg-surface p-4 transition-colors hover:border-text/20"
    >
      <span className="text-sm font-bold text-text">{name}</span>
      {descriptor && <span className="mt-0.5 line-clamp-1 text-xs text-muted">{descriptor}</span>}
      <span className="mt-2 text-xs font-semibold text-text/60">{formatPrice(result.pack.price)}</span>
    </Link>
  );
}

/**
 * The collapsed state: a toolbar control, sized like the search box and the sort dropdown beside it.
 *
 * The label keeps the count ("three questions") rather than reducing to "Find your match": what
 * this asks of the buyer is the thing that decides whether they start it, and three is a small
 * enough number to be an argument for clicking. The honesty clause it used to carry inline
 * ("or we'll say we haven't built it yet") is the first line of the form itself, which is where
 * it is read by everyone who actually answers.
 */
export function MatchmakerTrigger({ onOpen, count, countLabel }: { onOpen: () => void; count?: number; countLabel?: string }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-expanded={false}
      className="inline-flex w-full items-center justify-center gap-2 whitespace-nowrap rounded-xl border border-border bg-white px-4 py-2.5 text-sm font-bold text-text transition-colors hover:border-text/30 sm:w-auto"
    >
      {count !== undefined ? `Find my fit, ${count} ${countLabel}` : 'Find my fit'}
    </button>
  );
}

export function Matchmaker({
  packs,
  onShowAll,
  onNoMatch,
  onAnswersChange,
}: {
  packs: Pack[];
  /** Drops the buyer into the filtered catalogue with the URL already populated. */
  onShowAll: (state: DiscoveryState) => void;
  /** Called when nothing scored, so the page can show the near-miss state (AC-8). */
  onNoMatch?: (state: DiscoveryState) => void;
  /** Called whenever the buyer's answers change, so the trigger can show a live count. */
  onAnswersChange?: (answers: MatchAnswers) => void;
}) {
  const [answers, setAnswers] = useState<MatchAnswers>(EMPTY_MATCH_ANSWERS);
  const [payerChoice, setPayerChoice] = useState<string | null>(null);
  /**
   * "None of these yet" needs its own flag because it is an *answer* that adds no constraint.
   * Without it, `answers.advantages` stays `[]` and the form cannot tell "told us they have
   * nothing" apart from "has not answered Q1 yet", so the submit button would never enable.
   */
  const [noSkillsYet, setNoSkillsYet] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  const outcome = useMemo(() => rankMatches(packs, answers), [packs, answers]);

  // Lift answers up to the parent so the trigger button can show a live count even
  // after the panel is closed.
  useEffect(() => {
    onAnswersChange?.(answers);
  }, [answers, onAnswersChange]);

  const chooseAdvantage = (advantage: Advantage | null) => {
    // Mutually exclusive with every skill claim: nobody both has nothing and has something.
    if (advantage === null) {
      setNoSkillsYet((prev) => !prev);
      setAnswers((prev) => ({ ...prev, advantages: [] }));
      return;
    }
    setNoSkillsYet(false);
    setAnswers((prev) => {
      const has = prev.advantages.includes(advantage);
      if (has) return { ...prev, advantages: prev.advantages.filter((a) => a !== advantage) };
      // Max 2: selecting a third drops the oldest, so the control never silently ignores a click.
      const next = [...prev.advantages, advantage].slice(-MAX_Q1);
      return { ...prev, advantages: next };
    });
  };

  const canSubmit = (answers.advantages.length > 0 || noSkillsYet) && answers.commitment !== null;
  const noMatch = submitted && outcome.winner === null;

  // Told in an effect, not during render: `onNoMatch` sets state on the page, and doing that
  // while this component renders is a React error, not a style preference.
  useEffect(() => {
    if (noMatch) onNoMatch?.(stateFromAnswers(answers));
  }, [noMatch, onNoMatch, answers]);

  if (submitted) {
    const state = stateFromAnswers(answers);
    if (!outcome.winner) {
      return (
        <div className="rounded-2xl border border-border bg-surface p-6">
          <h3 className="text-xl font-black tracking-tight text-text">
            We haven&apos;t built yours yet, and we&apos;re not going to pretend otherwise.
          </h3>
          <p className="mt-2 text-sm leading-relaxed text-muted">
            Nothing in the catalogue matches what you told us. Rather than hand you a pack that nearly fits,
            here is everything we have, and the option to tell us where to point the engine.
          </p>
          <div className="mt-4 flex flex-wrap gap-3">
            <Button variant="secondary" onClick={() => onShowAll(state)}>
              Show me everything
            </Button>
            <Button variant="ghost" onClick={() => setSubmitted(false)}>
              Revise answers
            </Button>
          </div>
        </div>
      );
    }

    return (
      <div className="flex flex-col gap-5">
        <WinnerCard result={outcome.winner} />
        {outcome.runnersUp.length > 0 && (
          <div>
            <span className="font-mono text-[11px] font-bold uppercase tracking-widest text-muted">
              Close behind
            </span>
            <div className="mt-2 grid gap-3 sm:grid-cols-2">
              {outcome.runnersUp.map((result) => (
                <RunnerUp key={result.pack.id} result={result} />
              ))}
            </div>
          </div>
        )}
        <div className="flex flex-wrap gap-3">
          <Button variant="secondary" onClick={() => onShowAll(state)}>
            Show me everything that matched
          </Button>
          <Button variant="ghost" onClick={() => setSubmitted(false)}>
            Revise answers
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-border bg-surface p-6 md:p-8">
      <p className="text-sm font-semibold leading-relaxed text-text/80">
        Three questions. We&apos;ll tell you which one is yours, or tell you honestly that we haven&apos;t
        built it yet.
      </p>

      <fieldset className="mt-6">
        {/* The trigger promised "three questions"; the numbers keep that promise visibly and
            let a skimmer see the whole cost of the form before starting it. */}
        <legend className="text-base font-black tracking-tight text-text">
          <span className="mr-2 font-mono text-xs font-bold text-primary">Step 1 of 3</span>
          What have you already got?
        </legend>
        <span className="text-xs font-medium text-muted">Pick up to two.</span>
        <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {Q1_OPTIONS.map((option) => (
            <OptionButton
              key={option.text}
              selected={
                option.advantage === null ? noSkillsYet : answers.advantages.includes(option.advantage)
              }
              onClick={() => chooseAdvantage(option.advantage)}
            >
              {option.text}
            </OptionButton>
          ))}
        </div>
      </fieldset>

      <fieldset className="mt-6">
        <legend className="text-base font-black tracking-tight text-text">
          <span className="mr-2 font-mono text-xs font-bold text-primary">Step 2 of 3</span>
          How much time, honestly?
        </legend>
        <div className="mt-3 grid gap-2 sm:grid-cols-3">
          {Q2_OPTIONS.map((option) => (
            <OptionButton
              key={option.text}
              selected={answers.commitment === option.commitment}
              onClick={() => setAnswers((prev) => ({ ...prev, commitment: option.commitment }))}
            >
              {option.text}
            </OptionButton>
          ))}
        </div>
      </fieldset>

      <fieldset className="mt-6">
        <legend className="text-base font-black tracking-tight text-text">
          <span className="mr-2 font-mono text-xs font-bold text-primary">Step 3 of 3</span>
          Who would you rather sell to?
        </legend>
        <span className="text-xs font-medium text-muted">Optional.</span>
        <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {Q3_OPTIONS.map((option) => (
            <OptionButton
              key={option.id}
              selected={payerChoice === option.id}
              onClick={() => {
                setPayerChoice(option.id);
                setAnswers((prev) => ({ ...prev, payer: option.payer }));
              }}
            >
              {option.text}
            </OptionButton>
          ))}
        </div>
      </fieldset>

      <div className="mt-7 flex flex-wrap items-center gap-4">
        <Button variant="prominent" disabled={!canSubmit} onClick={() => { track('matchmaker_answered'); setSubmitted(true); }}>
          Show me mine
        </Button>
        {!canSubmit && (
          <span className="text-xs font-medium text-muted">
            Answer the first two and we&apos;ll route you.
          </span>
        )}
      </div>
    </div>
  );
}
