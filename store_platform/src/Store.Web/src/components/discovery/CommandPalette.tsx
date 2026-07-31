import { useRouter } from 'next/router';
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { Icon } from '@/components/ui';
import { cx } from '@/components/ui/cx';
import { formatPrice, type Pack } from '@/lib/api/client';
import { matchesQuery, splitTitle } from '@/lib/discovery';

import { FacetChips } from './FacetChips';

/**
 * Search as a command palette (spec Part 6): opens on ⌘K / Ctrl+K, on `/`, and on clicking the
 * search field; results update as you type; there is no Enter-to-search and no results page.
 *
 * It searches title, one-liner, headline AND who-pays. Title-only search is the specific bug
 * this replaces: the feature's own worked example is a buyer typing "Uber", and "Uber" appears
 * in PlateStart's one-liner and who-pays but in no title in the catalogue — so a title-only
 * search returns nothing for the exact query the feature was asked for (AC-13).
 */

const MAX_ROWS = 7;

/** Opens the palette from anywhere and hands back the focus target Escape must restore to. */
export function useCommandPalette() {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing =
        target instanceof HTMLInputElement ||
        target instanceof HTMLTextAreaElement ||
        target?.isContentEditable === true;

      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setOpen(true);
        return;
      }
      // `/` is a shortcut only when the buyer is not already typing into something.
      if (event.key === '/' && !typing && !event.metaKey && !event.ctrlKey && !event.altKey) {
        event.preventDefault();
        setOpen(true);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  const close = useCallback(() => {
    setOpen(false);
    // Focus goes back where it came from, or the keyboard user is dumped at the top of the page.
    triggerRef.current?.focus();
  }, []);

  return { open, setOpen, close, triggerRef };
}

/** The always-visible field that opens the palette. Not an input: it is a button that looks like one. */
export function SearchTrigger({
  onOpen,
  triggerRef,
  className,
}: {
  onOpen: () => void;
  triggerRef: React.RefObject<HTMLButtonElement | null>;
  className?: string;
}) {
  return (
    <button
      ref={triggerRef}
      type="button"
      onClick={onOpen}
      className={cx(
        'flex w-full items-center gap-3 rounded-xl border border-border bg-surface px-4 py-3 text-left transition-colors hover:border-text/20',
        className,
      )}
    >
      <Icon name="search" size={16} />
      <span className="flex-1 text-sm font-medium text-muted">Search the catalogue</span>
      <kbd className="hidden rounded border border-border bg-bg px-1.5 py-0.5 font-mono text-[10px] font-bold text-muted sm:block">
        ⌘K
      </kbd>
    </button>
  );
}

/** Highlights the matched substring so the buyer can see WHY a row came back. */
function Highlight({ text, query }: { text: string; query: string }) {
  const needle = query.trim();
  if (!needle) return <>{text}</>;
  const at = text.toLowerCase().indexOf(needle.toLowerCase());
  if (at === -1) return <>{text}</>;
  return (
    <>
      {text.slice(0, at)}
      <mark className="rounded bg-primary/15 px-0.5 text-text">{text.slice(at, at + needle.length)}</mark>
      {text.slice(at + needle.length)}
    </>
  );
}

export function CommandPalette({
  packs,
  open,
  onClose,
  onSeeAll,
}: {
  packs: Pack[];
  open: boolean;
  onClose: () => void;
  /** "See all N matches" — hands the query to the catalogue filter. */
  onSeeAll?: (query: string) => void;
}) {
  // The dialog is a separate component so that opening MOUNTS it: query and cursor start clean
  // by construction instead of being reset by an effect that fires after a stale first paint.
  if (!open) return null;
  return <PaletteDialog packs={packs} onClose={onClose} onSeeAll={onSeeAll} />;
}

function PaletteDialog({
  packs,
  onClose,
  onSeeAll,
}: {
  packs: Pack[];
  onClose: () => void;
  onSeeAll?: (query: string) => void;
}) {
  const router = useRouter();
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  // Focus lands in the field the buyer just asked for. Done on mount rather than with `autoFocus`
  // so it happens once, when the dialog appears, and not on any later re-render.
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const matches = useMemo(
    () => (query.trim() ? packs.filter((pack) => matchesQuery(pack, query)) : packs),
    [packs, query],
  );
  const rows = matches.slice(0, MAX_ROWS);

  const go = (pack: Pack) => {
    onClose();
    void router.push(`/pack/${pack.id}`);
  };

  // Escape / arrows / Enter are bound on the window, not on the dialog element. A `role="dialog"`
  // div is non-interactive: hanging key handlers off it only works for keystrokes that happen to
  // land inside, and a keyboard user who has tabbed to the close button still expects Escape to
  // work. The window is where the dialog's keyboard contract actually lives. It rebinds as the
  // rows change, which is what keeps Enter pointing at the row the buyer can see highlighted.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        setActive((i) => (rows.length === 0 ? 0 : (i + 1) % rows.length));
        return;
      }
      if (event.key === 'ArrowUp') {
        event.preventDefault();
        setActive((i) => (rows.length === 0 ? 0 : (i - 1 + rows.length) % rows.length));
        return;
      }
      if (event.key === 'Enter') {
        const pack = rows[active];
        if (!pack) return;
        event.preventDefault();
        onClose();
        void router.push(`/pack/${pack.id}`);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [rows, active, onClose, router]);

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-text/30 px-4 pt-[12vh] backdrop-blur-sm">
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Search the catalogue"
        className="w-full max-w-2xl overflow-hidden rounded-2xl border border-border bg-surface shadow-[0_30px_80px_rgba(0,0,0,0.25)]"
      >
        <div className="flex items-center gap-3 border-b border-border px-4 py-3">
          <Icon name="search" size={16} />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              // Cursor resets with the query, in the handler that caused it.
              setActive(0);
            }}
            placeholder="Search packs, buyers, problems…"
            aria-label="Search the catalogue"
            role="combobox"
            aria-expanded
            aria-controls="command-palette-results"
            aria-activedescendant={rows[active] ? `command-palette-row-${rows[active].id}` : undefined}
            className="w-full bg-transparent text-base font-medium text-text outline-none placeholder:text-muted/70"
          />
          <button
            type="button"
            onClick={onClose}
            aria-label="Close search"
            className="rounded-md p-1 text-muted hover:bg-bg hover:text-text"
          >
            <Icon name="close" size={16} />
          </button>
        </div>

        <p aria-live="polite" className="sr-only">
          {matches.length} {matches.length === 1 ? 'result' : 'results'}
        </p>

        <ul id="command-palette-results" role="listbox" aria-label="Search results" className="max-h-[50vh] overflow-y-auto">
          {rows.map((pack, index) => {
            const { name, descriptor } = splitTitle(pack.title, pack.headline);
            return (
              <li
                key={pack.id}
                id={`command-palette-row-${pack.id}`}
                role="option"
                aria-selected={index === active}
                aria-label={`${name}${descriptor ? `, ${descriptor}` : ''}, ${formatPrice(pack.price)}`}
              >
                <button
                  type="button"
                  onMouseEnter={() => setActive(index)}
                  onClick={() => go(pack)}
                  className={cx(
                    'flex w-full items-center gap-3 px-4 py-3 text-left',
                    index === active ? 'bg-bg' : 'bg-transparent hover:bg-bg/60',
                  )}
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-bold text-text">
                      <Highlight text={name} query={query} />
                    </span>
                    {descriptor && (
                      <span className="block truncate text-xs text-muted">
                        <Highlight text={descriptor} query={query} />
                      </span>
                    )}
                    <FacetChips pack={pack} compact max={3} className="mt-1.5" />
                  </span>
                  <span className="shrink-0 text-sm font-black text-text">{formatPrice(pack.price)}</span>
                </button>
              </li>
            );
          })}

          {rows.length === 0 && (
            <li className="px-4 py-6 text-sm font-medium text-muted">
              Nothing in the catalogue matches “{query.trim()}”. Close this and we&apos;ll show you what to
              do next.
            </li>
          )}
        </ul>

        {matches.length > rows.length && (
          <button
            type="button"
            onClick={() => {
              onSeeAll?.(query);
              onClose();
            }}
            className="w-full border-t border-border px-4 py-3 text-left text-xs font-bold text-primary hover:bg-bg"
          >
            See all {matches.length} matches
          </button>
        )}
      </div>
    </div>
  );
}
