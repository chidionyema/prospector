import React from 'react';
import { createPortal } from 'react-dom';

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
  // A zero-count option is DISABLED, not hidden and not merely dimmed (MASTER-BRIEF section 9,
  // checklist box 15). Hidden is worse than either: an option that disappears takes with it the
  // information that the category exists at all, so the buyer cannot tell a filter they have
  // already narrowed past from one this shelf has never carried.
  //
  // WHAT THIS CHANGED, SAID OUT LOUD. Until now the chip stayed clickable and the near-miss view
  // rescued the empty result. That rescue no longer runs for a zero-count facet, because the
  // control that led to it is now inert. The trade the brief is making is that fifteen identical
  // pills where four lead nowhere makes a buyer test options instead of reading them, and reading
  // them is the whole job of a facet bar.
  //
  // `disabled` rather than `aria-disabled`: the count is already rendered beside the label, so a
  // screen reader still hears that the option exists and holds nothing. Keeping it focusable would
  // put a control in the tab order that does nothing when activated.
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
      disabled={dead}
      className={chipClasses({
        selected: active,
        className: cx('gap-1.5 whitespace-nowrap', dead && 'cursor-not-allowed opacity-45'),
      })}
    >
      {children}
      {count !== undefined && (
        /* Same count treatment as the StepFlow tiles: the chip's own typeface and weight, one
           grey, tabular figures. NOT `justify-between` and no `min-w` slot -- these chips are
           content-width in a `flex-wrap` row, so there is no column for a count to align to and
           a fixed slot would only pad the gap. What carries across is the part that is about the
           count being a count: `font-mono` made it read as a different kind of thing from the
           label it belongs to, in a control where the two are one phrase. */
        <span className={cx('text-caption tabular-nums', active ? 'text-white/70' : 'text-subtle')}>
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
          <span className="flex h-4 w-4 items-center justify-center rounded-sm text-white/70 transition-colors group-hover/chip:text-white">
            <Icon name="close" size={10} />
          </span>
        </button>
      ))}
      {chips.length > 1 && (
        <button
          type="button"
          onClick={() => onChange({ ...state, q: '', advantage: [], sector: null, payer: null, effort: null, commitment: null, mechanism: null })}
          className="ml-1 py-3 text-meta font-medium text-muted underline underline-offset-4 transition-colors hover:text-text"
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
                  'h-1.5 flex-1 rounded-sm transition-colors',
                  i <= step ? 'bg-text' : 'bg-border',
                )}
              />
            ))}
            <span className="ml-2 font-mono text-caption text-subtle">
              {step + 1} of {primaryGroups.length}
            </span>
          </div>

          {/* Question */}
          <h3 className="sub">
            {QUESTION_COPY[currentGroup.kind].question}
          </h3>
          <p className="mt-1 lede">
            {QUESTION_COPY[currentGroup.kind].subtitle}
          </p>

          {/* §6.6: one row of the same chips the rest of the shelf uses.
              This was a two-column grid of bordered cards, each ~100px tall with a 24px icon
              above the label -- four of them consumed most of a phone screen to ask one question,
              and the icons were decorative (the same `briefcase` stood for three different
              answers). Chips make the answers scannable in one line each and make this control
              visibly the same control as the filter bar, which is what it is. */}
          {/* EQUAL FRACTIONS, NOT CONTENT WIDTH (founder review, 2026-08-15).
              This was `flex flex-wrap`, so each answer took the width of its own label and the
              rows packed greedily. Two consequences, both visible at 390 and worse at 320.
              Measured live (under the "Suits ..." copy these tiles carried until 2026-08-15;
              the widths moved with the rewrite, the geometry argument did not): row one held
              "Suits builders" (132px) and "Suits sellers" (124px), row two "Suits operators"
              (144px) and "Suits an audience" (152px) -- so the second
              column started at x=164 on one row and x=352 on the next, and the four answers to
              ONE question did not line up as a set. At 320 the pair on row two no longer fits
              (144+8+152 = 304 in ~272 of usable width), the last answer wraps alone, and the
              question ends on a single chip with a ragged gap beside it.

              A two-column grid fixes both at once: equal fractions means the columns align down
              the page, and an equal share is also a MINIMUM legible width -- no answer can be
              squeezed by a longer sibling. The `last:nth-child(odd)` variant is what handles an
              odd count, which is the founder's actual sighting: the orphan spans both columns
              instead of sitting alone next to a hole, so the grid always ends on a full row.
              From `sm` up the old flex row returns unchanged -- there is width for it there, and
              a 2-up grid on a desktop sheet would waste most of the line. */}
          <div className="mt-4 grid grid-cols-2 gap-2 [&>*:last-child:nth-child(odd)]:col-span-2 sm:flex sm:flex-wrap">
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
                  /* THE COUNT GETS A COLUMN, NOT A GAP (founder review, 2026-08-15).
                     `chipClasses` sets no `justify-*`, so its default is flex-start and the count
                     was an inline sibling of the label: it started wherever that label happened to
                     end. Across the 2x2 grid that put "4" hard against "I have an audience" while
                     15, 32 and 24 sat clear of theirs, and nothing lined up down either column.
                     `justify-between` is inert from `sm` up, where the container goes back to
                     `flex-wrap` and each chip is content-width with no free space to distribute --
                     which is correct, a shrink-wrapped chip has no column to align to. */
                  className={chipClasses({ selected: active, wrap: true, className: 'justify-between gap-2' })}
                >
                  {/* `whitespace-nowrap` came off with the `wrap` above, and the two go together:
                      holding one line is what pushed the count out of the box in the first place.
                      `text-left` because a button centres its text by default, which is invisible
                      on one line and obvious on two. `min-w-0` lets the label give way rather than
                      claim its min-content width and shove the count column sideways again. */}
                  <span className="min-w-0 text-left">{lbl}</span>
                  {count !== undefined && (
                    <span
                      /* `tabular-nums` is load-bearing and not decorative: the UI face draws a
                         proportional "1" narrower than a "3", so even two counts of equal DIGIT
                         length still fail to align without it. `min-w-[2.5ch]` gives the single
                         digits the same slot the double digits take (`ch` is the "0" advance, and
                         under tabular figures that is every digit's advance), and `text-right`
                         is what makes the slot align on the units column rather than the tens.
                         No weight and no family of its own -- both inherit from the chip, which
                         is the founder's "share the label's typeface" and drops the `font-mono`
                         that made these read as a different kind of thing from their labels.
                         One grey, `text-subtle`, on every unselected tile. The selected state is
                         the one exception and it is a contrast floor, not a style choice: the
                         chip fills with primary charcoal, where a subtle grey is unreadable. */
                      className={cx(
                        'min-w-[2.5ch] shrink-0 text-right text-caption tabular-nums',
                        active ? 'text-white/70' : 'text-subtle',
                      )}
                    >
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
              className="mt-3 self-center py-3 text-meta font-medium text-muted underline underline-offset-4 transition-colors hover:text-text"
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
                className="py-3 text-meta font-medium text-accent transition-colors hover:text-accent-hover"
              >
                Edit
              </button>
              {activeCount > 0 && (
                <button
                  type="button"
                  onClick={clearAll}
                  className="py-3 text-meta font-medium text-muted transition-colors hover:text-text"
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
                className="flex w-full items-center justify-between py-[13px] text-caption font-medium text-muted hover:text-text"
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
                        <span className="eyebrow">
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

// ── Reaching the filter: the sheet, and the pinned trigger that opens it ──

/*
 * WHY THIS EXISTS. Measured on the live page with Playwright, 2026-08-08:
 *
 *   desktop 1280x800   page 8362px (10.5 screens)   phone 390x844   page 10477px (12.4 screens)
 *     first pack card      y=  129                     first pack card      y=    0
 *     "Narrow it down"     y= 1256  (1.6 screens)      "Narrow it down"     y= 2010  (2.4 screens)
 *     the router           y= 4054  (5.1 screens)      the router           y= 4882  (5.8 screens)
 *
 * The router sat after the LAST of 53 cards, so narrowing the shelf cost a scroll past the entire
 * catalogue -- on a page whose reason to exist is that the catalogue is already narrow.
 *
 * Product-before-controls is RIGHT and is not being undone here; #149 measured that and it stands.
 * The defect is that reachability was expressed as a POSITION, and a position can only ever be
 * correct for the reader who happens to be standing at it. Every previous fix moved the block --
 * up when it hid the product, down when it interrupted the scan -- and each move traded one
 * reader's problem for another's, because a single position cannot serve both.
 *
 * So the block stops moving, and reaching it stops depending on where the reader is: the trigger
 * below pins itself the moment the controls scroll off the top, and opens them as a sheet. It
 * costs zero above-the-fold pixels, which is what made the position argument hard in the first
 * place.
 *
 * This REPLACES a dead `FacetBar` export that already wrapped `StepFlow` in this exact Modal with
 * this exact footer, and that no page ever rendered (`grep -rn "<FacetBar"` -> no matches,
 * 2026-08-08). It was also `lg:hidden` -- mobile only -- and mobile is where the scroll cost is
 * worst but not where it is exclusive: 5.1 screens on a 1280px desktop is not a phone problem.
 */

export function FilterSheet({
  packs,
  state,
  onChange,
  open,
  onClose,
}: {
  packs: Pack[];
  state: DiscoveryState;
  onChange: (next: DiscoveryState) => void;
  open: boolean;
  onClose: () => void;
}) {
  const matching = filterPacks(packs, state).length;

  return (
    <Modal
      open={open}
      onClose={onClose}
      placement="right"
      /* The sheet and the inline block carry the SAME name. They are one control with two ways in,
         and giving them two names would make them read as two different filters -- which is the
         confusion this change exists to remove, not one to add. */
      title="Narrow it down"
      footer={
        <button
          type="button"
          onClick={onClose}
          className={buttonClasses({ size: 'lg', fullWidth: true })}
        >
          Show {matching} {matching === 1 ? 'pack' : 'packs'}
        </button>
      }
    >
      <StepFlow packs={packs} state={state} onChange={onChange} />
    </Modal>
  );
}

export function FilterFab({
  anchorRef,
  endRef,
  state,
  open,
  onOpen,
}: {
  /** The inline controls block. The trigger appears only once this has scrolled off the top. */
  anchorRef: React.RefObject<HTMLElement | null>;
  /**
   * The END of the thing this filters. The trigger disappears again once the reader reaches it.
   * Optional: a page with nothing after its shelf can omit it and keep the old behaviour.
   */
  endRef?: React.RefObject<HTMLElement | null>;
  state: DiscoveryState;
  /** The sheet's open state: the trigger hides while the thing it opens is already open. */
  open: boolean;
  onOpen: () => void;
}) {
  const [scrolledPast, setScrolledPast] = React.useState(false);
  const [pastEnd, setPastEnd] = React.useState(false);
  const activeCount = activeFacetSelectionCount(state);

  /* There is deliberately no `mounted` flag here, though portalling to <body> is normally a reason
     to want one. `scrolledPast` starts false, and the ONLY thing that sets it is the observer
     below, which cannot run on the server -- so the server and the first client render both return
     null for the same reason, and hydration cannot mismatch. A `useState(false)` +
     `useEffect(() => setMounted(true))` pair would add a second render pass to prove a fact the
     first one already guarantees, and eslint rejects the synchronous setState besides. */
  React.useEffect(() => {
    const el = anchorRef.current;
    if (!el || typeof IntersectionObserver === 'undefined') return;
    /* `!isIntersecting` alone is true BOTH above and below the viewport, so on first paint -- when
       the controls are still far below the fold -- it would pin a "narrow it down" button to a
       reader who has not yet seen a single product. The `top < 0` half is what makes it mean
       "scrolled PAST" rather than "not currently on screen". */
    const io = new IntersectionObserver(
      ([entry]) => setScrolledPast(!entry.isIntersecting && entry.boundingClientRect.top < 0),
      { threshold: 0 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [anchorRef]);

  /* A FILTER HAS A JURISDICTION, AND IT ENDS (founder review, 2026-08-15).
     The observer above asks one question -- "have the controls left the top?" -- and on the home
     page that is true for the whole remaining 5,000px of document. So the trigger stayed pinned
     across the entire marketing tail and came to rest on top of the pack specimen's source
     citation, which is the founder's sighting. The occluder padding below cannot help: it moves
     the END of the document, and this was landing in the MIDDLE of it.

     The missing fact is where the shelf stops. `endRef` is a zero-height sentinel the page places
     immediately after its last shelf branch, and `pastEnd` is true once that sentinel has risen
     into the top half of the viewport -- the `-50%` bottom margin shrinks the observer's root to
     that half. Not the default root: with it, `isIntersecting` fires the moment the sentinel
     crosses the BOTTOM edge, which is while the last row of packs is still on screen and still
     worth filtering. `|| top < 0` keeps it true after the sentinel has scrolled off entirely,
     since an element above the viewport reports `isIntersecting: false` exactly like one below
     it -- the same asymmetry the anchor observer handles.

     Scrolling back up into the shelf restores it, because both flags are recomputed rather than
     latched. */
  React.useEffect(() => {
    const el = endRef?.current;
    if (!el || typeof IntersectionObserver === 'undefined') return;
    const io = new IntersectionObserver(
      ([entry]) => setPastEnd(entry.isIntersecting || entry.boundingClientRect.top < 0),
      { threshold: 0, rootMargin: '0px 0px -50% 0px' },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [endRef]);

  /** The single answer. The occluder's padding and the render guard must never disagree. */
  const visible = scrolledPast && !pastEnd && !open;

  /* THE OCCLUDER RESERVES ITS OWN SPACE (2026-08-14, founder review at 390px).
     This button is `fixed` and portalled to <body>, so no page that mounts it can know it is
     there, and none of them padded for it: at the bottom of the shelf it sat on top of the last
     row -- hiding that pack's PRICE -- and on top of the "Show the other N packs" button, which
     is the one control the whole tail of the page exists to offer. A floating element that
     covers content is a bug wherever it floats, so the fix belongs here rather than in each
     page's list, which is also the only version that stays true when a third page mounts one.

     Padding on <body> lands at the END of the document, which is exactly the reachability
     property wanted: every element can now be scrolled clear of the button. 4.5rem is the
     button's own box (h-10 = 2.5rem) plus its `bottom-4` inset (1rem) plus 1rem of air, and the
     safe-area inset matches the one the button itself applies so the two cannot disagree on a
     notched phone. Restored on unmount, so scrolling back up returns the page to its own
     geometry rather than leaving a permanent gap under the footer. */
  React.useEffect(() => {
    if (!visible) return;
    const { body } = document;
    const previous = body.style.paddingBottom;
    body.style.paddingBottom = 'calc(4.5rem + env(safe-area-inset-bottom))';
    return () => {
      body.style.paddingBottom = previous;
    };
  }, [visible]);

  if (!visible) return null;

  return createPortal(
    /* z-40: above the shelf, below `Modal`'s z-50, so the sheet it opens covers it rather than
       fighting it. Portalled for the same reason `Modal` is -- a `fixed` child of a transformed or
       blurred ancestor is positioned against that ancestor, not the viewport, and which ancestors
       those are is invisible from here. */
    <div
      className="pointer-events-none fixed inset-x-0 bottom-4 z-40 flex justify-center px-4"
      style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
    >
      <button
        type="button"
        onClick={onOpen}
        aria-haspopup="dialog"
        data-testid="filter-fab"
        className="pointer-events-auto inline-flex h-10 items-center gap-2 whitespace-nowrap rounded-sm border border-border-strong bg-surface px-4 text-meta font-medium text-text transition-colors hover:border-text hover:bg-surface2"
      >
        <Icon name="search" size={14} />
        Narrow it down
        {activeCount > 0 && (
          <span className="inline-flex h-5 min-w-[1.25rem] items-center justify-center rounded-sm bg-primary px-1.5 font-mono text-caption text-on-primary">
            {activeCount}
          </span>
        )}
      </button>
    </div>,
    document.body,
  );
}
