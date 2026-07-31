import React from 'react';

import { cx } from '@/components/ui/cx';
import type { Pack } from '@/lib/api/client';
import { facetCounts, type DiscoveryState } from '@/lib/discovery';
import { KIND_LABEL, VOCABULARY, label, type FacetKind } from '@/lib/facets';

/**
 * The facet filter — sticky under the header on mobile, a sidebar from `lg` up.
 *
 * Two rules it enforces visibly:
 *
 * - **"All" is always present and always first**, because it is the only control that shows the
 *   untagged packs. Without it an untagged pack would be unreachable through the filter.
 * - **A facet with no data anywhere in the catalogue does not render at all** (AC-12). A filter
 *   group whose every option returns nothing is a dead control that makes the catalogue look
 *   broken; the honest move is to omit it until the engine has tagged something.
 */

/** Order matters: the router's primary axis first, sector (display/exclusion only) last. */
const GROUPS: FacetKind[] = ['advantage', 'commitment', 'payer', 'effort', 'mechanism', 'sector'];

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
      )}
    >
      {children}
      {count !== undefined && <span className="text-[10px] font-bold text-muted">{count}</span>}
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
  const groups = GROUPS.map((kind) => ({ kind, counts: facetCounts(packs, state, kind) })).filter(
    // AC-12: nothing in the catalogue carries this facet — render no control at all.
    (group) => Object.keys(group.counts).length > 0,
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

  const anyActive =
    state.advantage.length > 0 ||
    state.sector !== null ||
    state.payer !== null ||
    state.effort !== null ||
    state.commitment !== null ||
    state.mechanism !== null;

  return (
    <div className={cx('flex flex-col gap-5', className)}>
      {groups.map(({ kind, counts }) => {
        const isAdvantage = kind === 'advantage';
        const activeValues = isAdvantage ? state.advantage : ([state[kind]].filter(Boolean) as string[]);
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
              {VOCABULARY[kind]
                // Only offer values some pack actually carries — an option that can only ever
                // return zero results is a promise the catalogue cannot keep.
                .filter((value) => counts[value] !== undefined)
                .map((value) => {
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

      {anyActive && (
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
}
