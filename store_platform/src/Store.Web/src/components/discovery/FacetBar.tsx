import React, { useEffect, useRef, useState } from 'react';

import { Icon } from '@/components/ui';
import { Modal } from '@/components/ui/Modal';
import { cx } from '@/components/ui/cx';
import type { Pack } from '@/lib/api/client';
import { useCart } from '@/lib/cart';
import {
  activeFacetSelectionCount,
  activeFacetValues,
  facetCounts,
  filterPacks,
  foldFacetGroups,
  offeredFacetValues,
  type DiscoveryState,
} from '@/lib/discovery';
import { KIND_LABEL, label, type FacetKind } from '@/lib/facets';
import { Q1_OPTIONS, Q2_OPTIONS, Q3_OPTIONS } from '@/components/discovery/Matchmaker';

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
 * How many groups stay open before the rest fold away.
 *
 * Three is not a round number picked for looks: the first three entries of `GROUPS` are exactly
 * the three facets the Matchmaker interrogates, advantages, commitment, payer
 * (`Matchmaker.tsx`, scored in `discovery.ts` `rankMatches`). So the open set is "the questions
 * we already believe decide a match" and the folded set is "the ways to refine afterwards",
 * which is a claim the code can be checked against rather than a designer's preference.
 *
 * Six groups of chips is roughly 90 controls of vertical run in a 15rem rail; the cost of that
 * is not aesthetic, it is that the sixth group is below the fold on a laptop and so the buyer
 * never learns the first three exist as a set.
 */
const OPEN_GROUPS = 3;

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
      className={cx(
        'flex items-center gap-1.5 whitespace-nowrap rounded-full border px-3 py-1.5 text-xs font-semibold transition-colors',
        active
          ? 'border-primary bg-primary/10 text-text'
          : 'border-border bg-surface text-text/70 hover:border-text/20 hover:bg-bg',
        dead && 'opacity-45',
      )}
    >
      {children}
      {count !== undefined && <span className="text-[10px] font-bold text-muted">{count}</span>}
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
          className="group/chip inline-flex items-center gap-1.5 rounded-full border border-primary/30 bg-primary/10 py-1 pl-3 pr-2 text-xs font-semibold text-text transition-colors hover:border-primary/50"
        >
          {chip.text}
          <span className="flex h-4 w-4 items-center justify-center rounded-full text-muted transition-colors group-hover/chip:bg-primary group-hover/chip:text-white">
            <Icon name="close" size={10} />
          </span>
        </button>
      ))}
      {chips.length > 1 && (
        <button
          type="button"
          onClick={() => onChange({ ...state, q: '', advantage: [], sector: null, payer: null, effort: null, commitment: null, mechanism: null })}
          className="ml-1 text-xs font-semibold text-muted underline underline-offset-4 hover:text-text"
        >
          Clear all
        </button>
      )}
    </div>
  );
}

const MAX_Q1 = 2;

function QuickStartPill({
  label,
  selectedLabel,
  open,
  setOpen,
  children,
}: {
  label: string;
  selectedLabel?: string;
  open: boolean;
  setOpen: (v: boolean) => void;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, [open, setOpen]);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className={cx(
          'flex items-center justify-between gap-1.5 rounded-xl border px-3 py-2 text-xs font-semibold transition-all duration-150',
          open || selectedLabel
            ? 'border-primary bg-primary/5 text-text'
            : 'border-border bg-surface text-text/70 hover:border-text/20 hover:bg-bg',
        )}
      >
        <span className="truncate">{selectedLabel ?? label}</span>
        <span
          aria-hidden="true"
          className={cx('h-2 w-2 flex-none rotate-45 border-b-2 border-r-2 border-muted transition-transform', open && '-rotate-[135deg]')}
        />
      </button>
      {open && (
        <div className="absolute left-0 top-full z-30 mt-1 w-48 overflow-hidden rounded-xl border border-border bg-white p-1 shadow-[0_18px_40px_rgba(0,0,0,0.12)]">
          {children}
        </div>
      )}
    </div>
  );
}

function PillOption({
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
      className={cx(
        'flex w-full items-center justify-between gap-2 rounded-lg px-3 py-2 text-left text-xs font-semibold',
        selected ? 'bg-primary/5 text-text' : 'text-text/70 hover:bg-bg',
      )}
    >
      {children}
      {selected && <Icon name="check" size={12} className="text-primary flex-none" />}
    </button>
  );
}

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
  const [expanded, setExpanded] = React.useState(false);
  const [skillsOpen, setSkillsOpen] = useState(false);
  const [timeOpen, setTimeOpen] = useState(false);
  const [payerOpen, setPayerOpen] = useState(false);
  const cart = useCart();

  // Auto-open the mobile sheet on first visit, guarded by cart readiness.
  useEffect(() => {
    const flag = localStorage.getItem('mumchimp.matchmaker.autoOpened.v1');
    if (!flag && cart.ready && cart.count === 0) {
      setSheetOpen(true);
      localStorage.setItem('mumchimp.matchmaker.autoOpened.v1', '1');
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // AC-12 now falls out of `offeredFacetValues`: a group with no offerable value renders nothing,
  // whether that is because the engine has tagged nothing or because every option it has is too
  // rare to be worth a control.
  const groups = React.useMemo(
    () =>
      GROUPS.map((kind) => ({
        kind,
        counts: facetCounts(packs, state, kind),
        activeValues: activeFacetValues(state, kind),
        values: offeredFacetValues(packs, state, kind),
      })).filter((group) => group.values.length > 0),
    [packs, state],
  );

  const activeCount = activeFacetSelectionCount(state);

  // `foldFacetGroups` owns the rule that a folded group may never hold an active selection, and
  // withdraws the toggle when it would be able to re-hide one (`lib/discovery.ts`).
  const { visible: visibleGroups, foldedCount, canFold } = foldFacetGroups(
    groups,
    OPEN_GROUPS,
    expanded,
  );

  if (groups.length === 0) return null;

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

  // Derive display labels from current state
  const skillsLabel = state.advantage.length > 0
    ? state.advantage.map((v) => Q1_OPTIONS.find((o) => o.advantage === v)?.text).filter(Boolean).join(', ')
    : undefined;

  const timeLabel = state.commitment
    ? Q2_OPTIONS.find((o) => o.commitment === state.commitment)?.text
    : undefined;

  const payerLabel = state.payer
    ? Q3_OPTIONS.find((o) => o.payer === state.payer)?.text
    : undefined;

  const panel = (
    <div className="flex flex-col gap-5">
      {/* Quick Start: three pill-dropdowns that map 1:1 onto the first three facet groups */}
      <div>
        <span className="font-mono text-[10px] font-bold uppercase tracking-widest text-muted">
          Quick start
        </span>
        <div className="mt-2 grid grid-cols-3 gap-1.5">
          {/* My skills -- maps to advantage, multi-select max 2 */}
          <QuickStartPill
            label="My skills"
            selectedLabel={skillsLabel}
            open={skillsOpen}
            setOpen={setSkillsOpen}
          >
            {Q1_OPTIONS.map((option) => {
              const active = option.advantage === null
                ? false
                : state.advantage.includes(option.advantage);
              return (
                <PillOption
                  key={option.text}
                  selected={active}
                  onClick={() => {
                    if (option.advantage === null) {
                      onChange({ ...state, advantage: [] });
                      return;
                    }
                    if (active) {
                      onChange({ ...state, advantage: state.advantage.filter((v) => v !== option.advantage) });
                    } else {
                      const next = [...state.advantage, option.advantage].slice(-MAX_Q1);
                      onChange({ ...state, advantage: next });
                    }
                  }}
                >
                  {option.text}
                </PillOption>
              );
            })}
          </QuickStartPill>

          {/* My time -- maps to commitment, single select */}
          <QuickStartPill
            label="My time"
            selectedLabel={timeLabel}
            open={timeOpen}
            setOpen={setTimeOpen}
          >
            {Q2_OPTIONS.map((option) => {
              const active = state.commitment === option.commitment;
              return (
                <PillOption
                  key={option.text}
                  selected={active}
                  onClick={() => {
                    onChange({ ...state, commitment: active ? null : option.commitment });
                  }}
                >
                  {option.text}
                </PillOption>
              );
            })}
          </QuickStartPill>

          {/* My payer -- maps to payer, single select */}
          <QuickStartPill
            label="My payer"
            selectedLabel={payerLabel}
            open={payerOpen}
            setOpen={setPayerOpen}
          >
            {Q3_OPTIONS.map((option) => {
              const active = state.payer === option.payer;
              return (
                <PillOption
                  key={option.id}
                  selected={active}
                  onClick={() => {
                    onChange({ ...state, payer: active ? null : option.payer });
                  }}
                >
                  {option.text}
                </PillOption>
              );
            })}
          </QuickStartPill>
        </div>
      </div>

      {/* Separator */}
      <div className="border-t border-border/40 pt-4">
        <p className="text-[11px] font-medium text-muted">Or refine below</p>
      </div>

      {/* Every group named an attribute, so nothing on screen said what clicking one would DO.
          One sentence, and the count already sitting beside each option explains itself. */}
      <p className="text-xs leading-relaxed text-muted">
        Pick any option to narrow the shelf. The number beside it is how many packs match.
      </p>

      {visibleGroups.map(({ kind, counts, activeValues, values }) => {
        const isAdvantage = kind === 'advantage';
        return (
          <div key={kind}>
            <span className="font-mono text-[10px] font-bold uppercase tracking-widest text-muted">
              {KIND_LABEL[kind]}
            </span>
            <div className="mt-2 flex flex-wrap gap-1.5">
              <ValueButton
                active={activeValues.length === 0}
                onClick={() =>
                  onChange(isAdvantage ? { ...state, advantage: [] } : { ...state, [kind]: null })
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

      {canFold && (
        <button
          type="button"
          onClick={() => setExpanded((prev) => !prev)}
          aria-expanded={foldedCount === 0}
          className="self-start text-xs font-semibold text-text/70 underline underline-offset-4 hover:text-text"
        >
          {foldedCount === 0 ? 'Fewer ways to narrow' : `${foldedCount} more ways to narrow`}
        </button>
      )}

      {activeCount > 0 && (
        <button
          type="button"
          onClick={clearAll}
          className="self-start text-xs font-semibold text-primary underline underline-offset-4"
        >
          Clear all filters
        </button>
      )}
    </div>
  );

  const matching = filterPacks(packs, state).length;

  return (
    <div className={className}>
      <div className="hidden lg:block">{panel}</div>

      <div className="lg:hidden">
        <button
          type="button"
          onClick={() => setSheetOpen(true)}
          aria-expanded={sheetOpen}
          aria-haspopup="dialog"
          className="inline-flex w-full items-center justify-center gap-2 whitespace-nowrap rounded-xl border border-border bg-white px-4 py-2.5 text-sm font-bold text-text transition-colors hover:border-text/30"
        >
          Your constraints
          {activeCount > 0 && (
            <span className="inline-flex h-5 min-w-[1.25rem] items-center justify-center rounded-full bg-primary px-1.5 text-[11px] font-bold text-white">
              {activeCount}
            </span>
          )}
        </button>

        {/* Modal owns Escape, backdrop click, body-scroll lock and the focus trap
            (`components/ui/Modal.tsx:20-25`), so the sheet inherits them rather than
            re-implementing a dialog that gets one of them wrong. */}
        <Modal
          open={sheetOpen}
          onClose={() => setSheetOpen(false)}
          title="Tell us what fits your life"
          footer={
            <button
              type="button"
              onClick={() => setSheetOpen(false)}
              className="w-full rounded-xl bg-primary px-4 py-2.5 text-sm font-bold text-white"
            >
              Show {matching} {matching === 1 ? 'pack' : 'packs'}
            </button>
          }
        >
          {panel}
        </Modal>
      </div>
    </div>
  );
}
