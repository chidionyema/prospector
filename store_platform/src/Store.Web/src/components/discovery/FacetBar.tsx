import React from 'react';

import { buttonClasses, chipClasses, Icon } from '@/components/ui';
import { Modal } from '@/components/ui/Modal';
import { cx } from '@/components/ui/cx';
import type { Pack } from '@/lib/api/client';
import {
  activeFacetSelectionCount,
  activeFacetValues,
  facetCounts,
  filterPacks,
  offeredFacetValues,
  type DiscoveryState,
} from '@/lib/discovery';
import { KIND_LABEL, label, type FacetKind } from '@/lib/facets';

/**
 * The facet filter, a disclosure button below `lg`, a sidebar from `lg` up.
 *
 * Rules it enforces visibly:
 *
 * - **"All" is always present and always first**, because it is the only control that shows the
 *   untagged packs. Without it an untagged pack would be unreachable through the filter.
 * - **A facet with no data anywhere in the catalogue does not render at all** (AC-12). A filter
 *   group whose every option returns nothing is a dead control that makes the catalogue look
 *   broken; the honest move is to omit it until the engine has tagged something.
 * - **Only the first `OPEN_GROUPS` groups start open** (S9). The fold is decided by
 *   `foldFacetGroups`, not here, because its one hard rule, a folded group may never hold an
 *   active selection, is about buyer-visible constraint rather than layout, and needs a test.
 * - **Below `lg` the whole bar collapses behind one button.** The page grid is
 *   `lg:grid-cols-[15rem_1fr]` (`pages/index.tsx:428`) with this `<aside>` first, so under `lg`
 *   the grid is one column and every filter control stacked ABOVE the first product card. That
 *   is the same defect already fixed for the router panel (`pages/index.tsx:434-436`): space
 *   above the fold is the space that decides whether a buyer sees a product at all. As a
 *   sidebar it costs nothing; as a stacked column on a phone it cost the entire first screen.
 */

/** Order matters: the router's primary axis first, sector (display/exclusion only) last. */
const GROUPS: FacetKind[] = ['advantage', 'commitment', 'payer', 'effort', 'mechanism', 'sector'];

/**
 * The three primary groups shown as progressive questions.
 * Order is deliberate: skills first (buyer identifies), then time (buyer commits), then market
 * (buyer qualifies). These are the same three the old Matchmaker used, backed by the scoring in
 * `rankMatches`. The remaining three groups (effort, mechanism, sector) are power-user filters
 * behind "Advanced filters".
 */
const PRIMARY_GROUPS: FacetKind[] = ['advantage', 'commitment', 'payer'];
const ADVANCED_GROUPS: FacetKind[] = ['effort', 'mechanism', 'sector'];

/*
  SKILLS QUIZ COPY (email §1). The first step now opens with an outcome promise rather than a
  neutral question. "Show me packs I could actually run" is the buyer's actual test, and the
  filter that follows is a means to it; saying the means first ("What skills do you bring?")
  leaves the outcome implicit, so a reader who only read the question was not told what they
  were doing. The follow-ups stay as is -- they ask the next-best question once the first is
  answered -- and the subtitle ("Pick as many as you like") is the one instruction the buyer
  still needs to read.
*/
const QUESTION_COPY: Record<FacetKind, { question: string; subtitle: string }> = {
  advantage: { question: 'Show me packs I could actually run.', subtitle: 'Tick what you’re good at. We’ll hide the rest.' },
  commitment: { question: 'How much time can you commit?', subtitle: 'Choose the one that fits best' },
  payer: { question: 'Who do you want to sell to?', subtitle: 'Pick your target market' },
  effort: { question: '', subtitle: '' },
  mechanism: { question: '', subtitle: '' },
  sector: { question: '', subtitle: '' },
};

/* `stepFlow` used to render each facet value as a large two-column icon card, with a per-value
   icon picked by a `stepIcon()` lookup table. Brand v3 (2026-08-06) replaced those cards with the
   same chip shape the desktop bar already uses, so the guided flow and the bar now filter the
   catalogue through one visual control instead of two. The lookup table is deleted with them:
   most of its entries were a shrug ("commit part time" -> a clock, "sell to consumers" -> the
   same people icon as "bring an audience"), and it fell back to a tick for everything else. */

function ValueButton({
  active,
  count,
  onClick,
  children,
}: {
  active: boolean;
  count?: number;
  onClick: () => void;
  children: React.ReactNode;
}) {
  // A zero-count option stays clickable (the near-miss state rescues it honestly) but must not
  // LOOK like a live door: fifteen identical pills where four lead nowhere makes the buyer test
  // options instead of reading them. The count already says "0"; the dimming lets the eye skip
  // it without reading every number.
  const dead = count === 0 && !active;
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      // §6.6: one chip shape, and the SELECTED state is an ink fill rather than a tinted outline.
      // A 10%-tint pill differed from an unselected pill by a wash the eye reads as "slightly
      // warmer", which on a bar of fifteen made the current selection genuinely hard to find;
      // filled-vs-outlined is a difference in kind. That reasoning now lives in `chipClasses`,
      // which the kill log and the FAQ render too -- it was stated here and nowhere else, which is
      // how the FAQ ended up shipping the square tinted version this comment argues against.
      className={chipClasses({
        selected: active,
        className: cx('gap-1.5 whitespace-nowrap', dead && 'opacity-45'),
      })}
    >
      {children}
      {count !== undefined && (
        <span className={cx('font-mono text-caption', active ? 'text-white/70' : 'text-subtle')}>
          {count}
        </span>
      )}
    </button>
  );
}

/**
 * The active selections as removable chips, rendered by the page directly above the grid.
 *
 * This exists for the state the sidebar cannot cover: below `lg` the filter controls live inside
 * a closed sheet, so once it closes the only trace of a selection is a count badge on the
 * "Filters" button, the buyer sees a shortened shelf with nothing on screen saying WHY, and
 * undoing one choice means reopening the sheet and finding it again. Each chip names one active
 * constraint in the same buyer-facing copy as the controls, and removes exactly that constraint
 * in one tap. On desktop the row doubles as confirmation at the point the eye actually rests,
 * the grid, rather than in sidebar peripheral vision.
 *
 * The search query is a chip too: it constrains the shelf exactly like a facet, and it is even
 * less visible once the palette closes.
 */
export function AppliedFilterChips({
  state,
  onChange,
  className,
}: {
  state: DiscoveryState;
  onChange: (next: DiscoveryState) => void;
  className?: string;
}) {
  const chips: { key: string; text: string; remove: () => void }[] = [];

  if (state.q.trim()) {
    chips.push({
      key: 'q',
      text: `“${state.q.trim()}”`,
      remove: () => onChange({ ...state, q: '' }),
    });
  }
  for (const kind of GROUPS) {
    for (const value of activeFacetValues(state, kind)) {
      const text = label(kind, value);
      if (!text) continue;
      chips.push({
        key: `${kind}:${value}`,
        text,
        remove: () =>
          onChange(
            kind === 'advantage'
              ? { ...state, advantage: state.advantage.filter((v) => v !== value) }
              : { ...state, [kind]: null },
          ),
      });
    }
  }

  if (chips.length === 0) return null;

  return (
    <div className={cx('flex flex-wrap items-center gap-1.5', className)}>
      {chips.map((chip) => (
        <button
          key={chip.key}
          type="button"
          onClick={chip.remove}
          aria-label={`Remove filter: ${chip.text}`}
          className={chipClasses({ selected: true, removable: true, className: 'group/chip' })}
        >
          {chip.text}
          <span className="flex h-4 w-4 items-center justify-center rounded-full text-white/70 transition-colors group-hover/chip:text-white">
            <Icon name="close" size={10} />
          </span>
        </button>
      ))}
      {chips.length > 1 && (
        <button
          type="button"
          onClick={() => onChange({ ...state, q: '', advantage: [], sector: null, payer: null, effort: null, commitment: null, mechanism: null })}
          className="ml-1 text-meta font-medium text-muted underline underline-offset-4 transition-colors hover:text-text"
        >
          Clear all
        </button>
      )}
    </div>
  );
}

// ── StepFlow: progressive question flow, standalone so CatalogBrowser can embed it ──

export function StepFlow({
  packs,
  state,
  onChange,
}: {
  packs: Pack[];
  state: DiscoveryState;
  onChange: (next: DiscoveryState) => void;
}) {
  const [step, setStep] = React.useState(0);
  const [showAdvanced, setShowAdvanced] = React.useState(false);

  const allGroups = React.useMemo(
    () =>
      GROUPS.map((kind) => ({
        kind,
        counts: facetCounts(packs, state, kind),
        activeValues: activeFacetValues(state, kind),
        values: offeredFacetValues(packs, state, kind),
      })).filter((group) => group.values.length > 0),
    [packs, state],
  );

  const primaryGroups = allGroups.filter((g) => (PRIMARY_GROUPS as FacetKind[]).includes(g.kind));
  const advancedGroups = allGroups.filter((g) => (ADVANCED_GROUPS as FacetKind[]).includes(g.kind));
  const currentGroup = primaryGroups[step] ?? null;
  const activeCount = activeFacetSelectionCount(state);
  const matching = filterPacks(packs, state).length;

  const clearAll = () =>
    onChange({
      ...state,
      advantage: [],
      sector: null,
      payer: null,
      effort: null,
      commitment: null,
      mechanism: null,
    });

  // Active chips for summary
  const activeChips: { key: string; text: string; remove: () => void }[] = [];
  for (const kind of GROUPS) {
    for (const value of activeFacetValues(state, kind)) {
      const text = label(kind, value);
      if (!text) continue;
      activeChips.push({
        key: `${kind}:${value}`,
        text,
        remove: () =>
          onChange(
            kind === 'advantage'
              ? { ...state, advantage: state.advantage.filter((v) => v !== value) }
              : { ...state, [kind]: null },
          ),
      });
    }
  }

  // If no primary groups have values, don't render
  if (primaryGroups.length === 0) return null;

  return (
    <div className="flex flex-col">
      {step >= 0 && currentGroup ? (
        <>
          {/* Step indicator */}
          <div className="mb-5 flex items-center gap-2">
            {primaryGroups.map((_, i) => (
              <div
                key={i}
                className={cx(
                  'h-1.5 flex-1 rounded-full transition-colors',
                  i <= step ? 'bg-text' : 'bg-border',
                )}
              />
            ))}
            <span className="ml-2 font-mono text-caption text-subtle">
              {step + 1} of {primaryGroups.length}
            </span>
          </div>

          {/* Question */}
          <h3 className="text-body font-semibold text-text">
            {QUESTION_COPY[currentGroup.kind].question}
          </h3>
          <p className="mt-1 text-meta text-muted">
            {QUESTION_COPY[currentGroup.kind].subtitle}
          </p>

          {/* §6.6: one row of the same chips the rest of the shelf uses.
              This was a two-column grid of bordered cards, each ~100px tall with a 24px icon
              above the label -- four of them consumed most of a phone screen to ask one question,
              and the icons were decorative (the same `briefcase` stood for three different
              answers). Chips make the answers scannable in one line each and make this control
              visibly the same control as the filter bar, which is what it is. */}
          <div className="mt-4 flex flex-wrap gap-2">
            {currentGroup.values.map((value) => {
              const active = currentGroup.activeValues.includes(value);
              const isAdvantage = currentGroup.kind === 'advantage';
              const lbl = label(currentGroup.kind, value);
              const count = currentGroup.counts[value];
              return (
                <button
                  key={value}
                  type="button"
                  aria-pressed={active}
                  onClick={() => {
                    if (isAdvantage) {
                      const next = active
                        ? state.advantage.filter((v) => v !== value)
                        : [...state.advantage, value as (typeof state.advantage)[number]];
                      onChange({ ...state, advantage: next });
                    } else {
                      onChange({ ...state, [currentGroup.kind]: active ? null : value });
                    }
                  }}
                  className={chipClasses({ selected: active, className: 'gap-1.5 whitespace-nowrap' })}
                >
                  {lbl}
                  {count !== undefined && (
                    <span className={cx('font-mono text-caption', active ? 'text-white/70' : 'text-subtle')}>
                      {count}
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          {/* Navigation */}
          <div className="mt-5 flex items-center justify-between">
            <div className="flex gap-2">
              {step > 0 && (
                <button
                  type="button"
                  onClick={() => setStep((s) => s - 1)}
                  className="inline-flex h-10 items-center rounded-md border border-border-strong bg-surface px-4 text-meta font-medium text-text transition-colors hover:border-text hover:bg-surface2"
                >
                  ← Back
                </button>
              )}
              <button
                type="button"
                onClick={() => {
                  const isAdv = currentGroup.kind === 'advantage';
                  onChange(isAdv ? { ...state, advantage: [] } : { ...state, [currentGroup.kind]: null });
                  if (step >= primaryGroups.length - 1) setStep(-1);
                  else setStep((s) => s + 1);
                }}
                className="inline-flex h-10 items-center rounded-md px-4 text-meta font-medium text-muted transition-colors hover:bg-surface2 hover:text-text"
              >
                Skip
              </button>
            </div>
            {step < primaryGroups.length - 1 ? (
              <button
                type="button"
                onClick={() => setStep((s) => s + 1)}
                className={buttonClasses()}
              >
                Next →
              </button>
            ) : (
              <button
                type="button"
                onClick={() => setStep(-1)}
                className={buttonClasses()}
              >
                Show {matching} {matching === 1 ? 'pack' : 'packs'}
              </button>
            )}
          </div>

          {activeCount > 0 && (
            <button
              type="button"
              onClick={clearAll}
              className="mt-3 self-center text-meta font-medium text-muted underline underline-offset-4 transition-colors hover:text-text"
            >
              Start over
            </button>
          )}
        </>
      ) : (
        /* Summary state */
        <>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Icon name="check" size={16} className="text-success" />
              <p className="text-meta font-medium text-text">
                {activeCount > 0
                  ? `${matching} ${matching === 1 ? 'pack' : 'packs'} match`
                  : `Showing all ${matching} packs`}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setStep(0)}
                className="text-meta font-medium text-accent transition-colors hover:text-accent-hover"
              >
                Edit
              </button>
              {activeCount > 0 && (
                <button
                  type="button"
                  onClick={clearAll}
                  className="text-meta font-medium text-muted transition-colors hover:text-text"
                >
                  Clear
                </button>
              )}
            </div>
          </div>

          {/* Advanced filters */}
          {advancedGroups.length > 0 && (
            <div className="mt-3 border-t border-border pt-3">
              <button
                type="button"
                onClick={() => setShowAdvanced((prev) => !prev)}
                className="flex w-full items-center justify-between text-caption font-medium text-muted hover:text-text"
              >
                Advanced filters
                <Icon
                  name="arrowRight"
                  size={14}
                  className={cx('transition-transform', showAdvanced && 'rotate-90')}
                />
              </button>
              {showAdvanced && (
                <div className="mt-3 flex flex-col gap-4">
                  {advancedGroups.map(({ kind, counts, activeValues, values }) => {
                    const isAdvantage = kind === 'advantage';
                    return (
                      <div key={kind}>
                        <span className="text-caption font-medium text-subtle">
                          {KIND_LABEL[kind]}
                        </span>
                        <div className="mt-2 flex flex-wrap gap-1.5">
                          <ValueButton
                            active={activeValues.length === 0}
                            onClick={() =>
                              onChange(
                                isAdvantage
                                  ? { ...state, advantage: [] }
                                  : { ...state, [kind]: null },
                              )
                            }
                          >
                            All
                          </ValueButton>
                          {values.map((value) => {
                            const active = activeValues.includes(value);
                            return (
                              <ValueButton
                                key={value}
                                active={active}
                                count={counts[value]}
                                onClick={() => {
                                  if (isAdvantage) {
                                    const next = active
                                      ? state.advantage.filter((v) => v !== value)
                                      : [...state.advantage, value as (typeof state.advantage)[number]];
                                    onChange({ ...state, advantage: next });
                                  } else {
                                    onChange({ ...state, [kind]: active ? null : value });
                                  }
                                }}
                              >
                                {label(kind, value)}
                              </ValueButton>
                            );
                          })}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ── FacetBar: wraps StepFlow for mobile modal usage ──

export function FacetBar({
  packs,
  state,
  onChange,
  className,
}: {
  packs: Pack[];
  state: DiscoveryState;
  onChange: (next: DiscoveryState) => void;
  className?: string;
}) {
  const [sheetOpen, setSheetOpen] = React.useState(false);
  const activeCount = activeFacetSelectionCount(state);
  const matching = filterPacks(packs, state).length;

  return (
    <div className={className}>
      <div className="lg:hidden">
        <button
          type="button"
          onClick={() => setSheetOpen(true)}
          aria-expanded={sheetOpen}
          aria-haspopup="dialog"
          className="inline-flex h-10 w-full items-center justify-center gap-2 whitespace-nowrap rounded-md border border-border-strong bg-surface px-4 text-meta font-medium text-text transition-colors hover:border-text hover:bg-surface2"
        >
          Filter
          {activeCount > 0 && (
            <span className="inline-flex h-5 min-w-[1.25rem] items-center justify-center rounded-full bg-primary px-1.5 font-mono text-caption text-on-primary">
              {activeCount}
            </span>
          )}
        </button>

        <Modal
          open={sheetOpen}
          onClose={() => setSheetOpen(false)}
          title="Show me packs I could actually run"
          footer={
            <button
              type="button"
              onClick={() => setSheetOpen(false)}
              className={buttonClasses({ size: 'lg', fullWidth: true })}
            >
              Show {matching} {matching === 1 ? 'pack' : 'packs'}
            </button>
          }
        >
          <StepFlow packs={packs} state={state} onChange={onChange} />
        </Modal>
      </div>
    </div>
  );
}
