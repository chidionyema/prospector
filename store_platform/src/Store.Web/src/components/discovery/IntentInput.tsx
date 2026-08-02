import React, { useMemo } from 'react';

import { Icon } from '@/components/ui';
import { cx } from '@/components/ui/cx';
import type { Pack } from '@/lib/api/client';
import { extractIntent, type DiscoveryState } from '@/lib/discovery';
import { label as facetLabel } from '@/lib/facets';
import type { Advantage, Commitment, Effort, Payer } from '@/lib/facets';

interface SuggestedChip {
  kind: 'advantage' | 'commitment' | 'payer' | 'effort';
  value: string;
  label: string;
}

/**
 * A single text input that replaces the FacetBar sidebar as the primary discovery surface.
 *
 * A buyer types natural language ("I can code, want B2B, evenings") and the component
 * extracts facet values via `extractIntent`, showing them as suggested chips below the
 * input. Clicking a chip applies it to the DiscoveryState immediately -- no submit button.
 *
 * Active chips (from state) render as removable pills inside the input area.
 */
export function IntentInput({
  packs: _packs,
  state,
  onChange,
  className,
}: {
  packs: Pack[];
  state: DiscoveryState;
  onChange: (next: DiscoveryState) => void;
  className?: string;
}) {
  const [text, setText] = React.useState('');
  const [collapsed, setCollapsed] = React.useState(true);

  const suggested = useMemo<SuggestedChip[]>(() => {
    if (!text.trim()) return [];
    const intent = extractIntent(text);
    const chips: SuggestedChip[] = [];

    // advantage chips (multi-select)
    if (intent.advantage) {
      for (const v of intent.advantage) {
        const lbl = facetLabel('advantage', v);
        if (lbl && !state.advantage.includes(v as Advantage)) {
          chips.push({ kind: 'advantage', value: v, label: lbl });
        }
      }
    }

    // single-value chips -- only suggest if not already active
    if (intent.commitment && intent.commitment !== state.commitment) {
      const lbl = facetLabel('commitment', intent.commitment);
      if (lbl) chips.push({ kind: 'commitment', value: intent.commitment, label: lbl });
    }
    if (intent.payer && intent.payer !== state.payer) {
      const lbl = facetLabel('payer', intent.payer);
      if (lbl) chips.push({ kind: 'payer', value: intent.payer, label: lbl });
    }
    if (intent.effort && intent.effort !== state.effort) {
      const lbl = facetLabel('effort', intent.effort);
      if (lbl) chips.push({ kind: 'effort', value: intent.effort, label: lbl });
    }

    return chips;
  }, [text, state.advantage, state.commitment, state.payer, state.effort]);

  const applyChip = (chip: SuggestedChip) => {
    if (chip.kind === 'advantage') {
      onChange({
        ...state,
        advantage: [...state.advantage, chip.value as Advantage],
      });
    } else {
      onChange({ ...state, [chip.kind]: chip.value });
    }
    setText('');
  };

  // Build active chip pills from current state
  const activeChips: { key: string; label: string; remove: () => void }[] = [];
  for (const v of state.advantage) {
    const lbl = facetLabel('advantage', v);
    if (lbl) {
      activeChips.push({
        key: `adv:${v}`,
        label: lbl,
        remove: () => onChange({ ...state, advantage: state.advantage.filter((a) => a !== v) }),
      });
    }
  }
  for (const [kind, value] of [
    ['commitment', state.commitment],
    ['payer', state.payer],
    ['effort', state.effort],
  ] as const) {
    if (value) {
      const lbl = facetLabel(kind, value);
      if (lbl) {
        activeChips.push({
          key: `${kind}:${value}`,
          label: lbl,
          remove: () => onChange({ ...state, [kind]: null }),
        });
      }
    }
  }

  if (collapsed && activeChips.length === 0) {
    return (
      <button
        type="button"
        onClick={() => setCollapsed(false)}
        className={cx(
          'inline-flex items-center gap-2 rounded-full border border-border bg-surface px-4 py-2 text-sm font-medium text-muted shadow-sm transition-colors hover:border-text/30 hover:text-text',
          className,
        )}
      >
        <Icon name="search" size={15} />
        What are you looking for?
      </button>
    );
  }

  return (
    <div className={cx('w-full', className)}>
      <div
        className={cx(
          'flex flex-wrap items-center gap-2 rounded-xl border border-border bg-surface px-4 py-3 shadow-sm transition-colors',
          'focus-within:border-primary/40 focus-within:shadow-[0_0_0_3px_rgba(4,47,46,0.08)]',
        )}
      >
        <Icon name="search" size={16} className="flex-none text-muted" />

        {/* Active chips */}
        {activeChips.map((chip) => (
          <span
            key={chip.key}
            className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2.5 py-1 text-xs font-semibold text-text"
          >
            {chip.label}
            <button
              type="button"
              onClick={chip.remove}
              aria-label={`Remove ${chip.label}`}
              className="ml-0.5 flex h-4 w-4 items-center justify-center rounded-full text-muted hover:bg-primary/20 hover:text-text"
            >
              <Icon name="close" size={10} />
            </button>
          </span>
        ))}

        {/* Text input */}
        <input
          type="text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              if (text) {
                setText('');
              } else if (activeChips.length === 0) {
                setCollapsed(true);
              }
            }
          }}
          onBlur={() => {
            // Collapse on blur if empty and no chips
            if (!text && activeChips.length === 0) {
              // Small delay so chip clicks register before collapse
              setTimeout(() => setCollapsed(true), 200);
            }
          }}
          placeholder={
            activeChips.length > 0 ? 'Add more...' : 'Describe your situation -- we\'ll find packs that fit'
          }
          className="min-w-[120px] flex-1 border-none bg-transparent text-sm text-text outline-none placeholder:text-muted/60"
        />
      </div>

      {/* Suggested chips */}
      {suggested.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {suggested.map((chip) => (
            <button
              key={`${chip.kind}:${chip.value}`}
              type="button"
              onClick={() => applyChip(chip)}
              className="inline-flex items-center gap-1 rounded-full border border-border bg-surface px-3 py-1.5 text-xs font-semibold text-text/70 transition-colors hover:border-primary/40 hover:bg-primary/5 hover:text-text"
            >
              + {chip.label}
            </button>
          ))}
        </div>
      )}

      {/* Collapse button when expanded with chips */}
      {activeChips.length > 0 && (
        <button
          type="button"
          onClick={() => {
            setText('');
            setCollapsed(true);
          }}
          className="mt-2 text-xs font-medium text-muted underline underline-offset-4 hover:text-text"
        >
          Hide
        </button>
      )}
    </div>
  );
}
