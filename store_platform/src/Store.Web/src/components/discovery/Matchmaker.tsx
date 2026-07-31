import Link from 'next/link';
import React, { useEffect, useMemo, useState } from 'react';

import { Button } from '@/components/ui';
import { cx } from '@/components/ui/cx';
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
import { label as facetLabel, type Advantage, type Commitment, type Payer } from '@/lib/facets';

import { FacetChips } from './FacetChips';

/**
 * The three-question router (spec Part 5). Copy is verbatim from the spec — it is the promise
 * the result screen has to keep, including the promise to say "we haven't built it yet".
 *
 * The one thing this component must never do is produce a winner when nothing scored. A
 * fabricated match is the exact failure the whole story exists to fix — and it stays a failure at
 * any catalogue size, so a top score of 0 routes to the near-miss state instead (AC-8).
 */

/** Q1 — multi-select, max 2. "None of these yet" is a real answer that must never dead-end. */
const Q1_OPTIONS: ReadonlyArray<{ text: string; advantage: Advantage }> = [
  { text: 'I can build software', advantage: 'code' },
  { text: 'I can sell', advantage: 'sales' },
  { text: 'I can run operations', advantage: 'ops' },
  { text: 'I have an audience', advantage: 'audience' },
  { text: 'None of these yet', advantage: 'nocode' },
];

const Q2_OPTIONS: ReadonlyArray<{ text: string; commitment: Commitment }> = [
  { text: 'Evenings and weekends', commitment: 'evenings' },
  { text: 'Part time, ~20 hrs', commitment: 'part_time' },
  { text: 'Full time, this is the plan', commitment: 'full_time' },
];

/**
 * `payer: null` is "Don't mind" — the spec scores it 0, never as a miss. The option carries its
 * own id so "Don't mind" can be a *chosen* answer that looks chosen, distinct from Q3 being
 * skipped; both produce the same `null` in the scored answers.
 */
const Q3_OPTIONS: ReadonlyArray<{ id: string; text: string; payer: Payer | null }> = [
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
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={selected}
      className={cx(
        'rounded-xl border px-4 py-3 text-left text-sm font-semibold transition-all duration-150',
        selected
          ? 'border-primary bg-primary/5 text-text shadow-[0_1px_3px_rgba(0,0,0,0.06)]'
          : 'border-border bg-surface text-text/80 hover:border-text/20 hover:bg-bg',
      )}
    >
      {children}
    </button>
  );
}

/**
 * One sentence saying why this pack won, built only from facets that actually scored. If the
 * only thing that scored was the evidence point, the sentence says so rather than implying a
 * fit the answers did not establish.
 */
function reasonSentence(result: MatchResult): string {
  const parts: string[] = [];
  for (const reason of result.reasons) {
    if (reason.kind === 'advantage') parts.push((facetLabel('advantage', reason.value) ?? '').toLowerCase());
    if (reason.kind === 'commitment') parts.push((facetLabel('commitment', reason.value) ?? '').toLowerCase());
    if (reason.kind === 'payer') parts.push((facetLabel('payer', reason.value) ?? '').toLowerCase());
  }
  const evidence = result.reasons.find((r) => r.kind === 'evidence');
  const tail = evidence ? `Backed by ${evidence.value} sources.` : '';
  if (parts.length === 0) return tail || 'It is the best-evidenced pack in the catalogue.';
  return `It matches you on ${parts.join(', ')}. ${tail}`.trim();
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
          <Button variant="prominent">See the pack — {formatPrice(pack.price)}</Button>
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

export function Matchmaker({
  packs,
  onShowAll,
  onNoMatch,
}: {
  packs: Pack[];
  /** Drops the buyer into the filtered catalogue with the URL already populated. */
  onShowAll: (state: DiscoveryState) => void;
  /** Called when nothing scored, so the page can show the near-miss state (AC-8). */
  onNoMatch?: (state: DiscoveryState) => void;
}) {
  const [answers, setAnswers] = useState<MatchAnswers>(EMPTY_MATCH_ANSWERS);
  const [payerChoice, setPayerChoice] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);

  const outcome = useMemo(() => rankMatches(packs, answers), [packs, answers]);

  const toggleAdvantage = (advantage: Advantage) => {
    setAnswers((prev) => {
      const has = prev.advantages.includes(advantage);
      if (has) return { ...prev, advantages: prev.advantages.filter((a) => a !== advantage) };
      // Max 2: selecting a third drops the oldest, so the control never silently ignores a click.
      const next = [...prev.advantages, advantage].slice(-MAX_Q1);
      return { ...prev, advantages: next };
    });
  };

  const canSubmit = answers.advantages.length > 0 && answers.commitment !== null;
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
            We haven&apos;t built yours yet — and we&apos;re not going to pretend otherwise.
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
              Change my answers
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
            Change my answers
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-border bg-surface p-6 md:p-8">
      <p className="text-sm font-semibold leading-relaxed text-text/80">
        Three questions. We&apos;ll tell you which one is yours — or tell you honestly that we haven&apos;t
        built it yet.
      </p>

      <fieldset className="mt-6">
        <legend className="text-base font-black tracking-tight text-text">What have you already got?</legend>
        <span className="text-xs font-medium text-muted">Pick up to two.</span>
        <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {Q1_OPTIONS.map((option) => (
            <OptionButton
              key={option.text}
              selected={answers.advantages.includes(option.advantage)}
              onClick={() => toggleAdvantage(option.advantage)}
            >
              {option.text}
            </OptionButton>
          ))}
        </div>
      </fieldset>

      <fieldset className="mt-6">
        <legend className="text-base font-black tracking-tight text-text">How much time, honestly?</legend>
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
        <Button variant="prominent" disabled={!canSubmit} onClick={() => setSubmitted(true)}>
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
