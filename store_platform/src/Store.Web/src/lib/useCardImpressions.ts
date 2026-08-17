import { useCallback, useEffect, useRef } from 'react';

import { trackCardImpressions } from '@/lib/analytics';

/**
 * Counts catalogue cards that actually entered the viewport, and reports them in batches.
 *
 * This is the denominator half of catalogue click-through. It exists because the storefront
 * could previously tell you that a card was clicked but never that it was seen, so there was
 * no ratio to compare one title form against another. There were only raw click totals, which
 * measure how far down the page a card sits.
 *
 * Three decisions worth knowing before changing this:
 *
 * A card counts when it is 50% visible, not when it is rendered. The catalogue mounts every
 * card at once, so "rendered" would count all 60-odd on every page load and make the
 * denominator a constant. The ratio would then just be the click count wearing a rate's
 * clothes.
 *
 * Each card counts at most once per mount, tracked in a Set. Scrolling a card in and out of
 * view repeatedly is one person looking at one card, and counting it four times deflates its
 * measured click-through for no reason but the visitor's scrolling habit.
 *
 * Sightings are buffered and flushed on a timer, not sent per card. Scrolling the catalogue
 * crosses dozens of cards in a second, and the API rate-limits its own storefront; one
 * beacon per card would trip that and lose the counts it was sent to record.
 */

/** How long to gather sightings before sending them. Long enough to coalesce a scroll. */
const FLUSH_MS = 1500;

/** A card must be half in view to count as seen. */
const VISIBLE_RATIO = 0.5;

export interface CardImpressionTracker {
  /**
   * Ref callback factory: `ref={observe(pack.id)}` on the card's outer element.
   * Passing the same id twice is safe.
   */
  observe: (packId: string) => (node: HTMLElement | null) => void;
}

export function useCardImpressions(): CardImpressionTracker {
  const seen = useRef<Set<string>>(new Set());
  const pending = useRef<string[]>([]);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const observer = useRef<IntersectionObserver | null>(null);
  const idByNode = useRef<WeakMap<Element, string>>(new WeakMap());

  const flush = useCallback(() => {
    if (timer.current) {
      clearTimeout(timer.current);
      timer.current = null;
    }
    if (pending.current.length === 0) return;
    const batch = pending.current;
    pending.current = [];
    trackCardImpressions(batch);
  }, []);

  useEffect(() => {
    // No IntersectionObserver during SSR, and jsdom without a polyfill. Absent
    // instrumentation must never break the catalogue, so this degrades to counting nothing.
    if (typeof window === 'undefined' || typeof IntersectionObserver === 'undefined') {
      return undefined;
    }

    observer.current = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          const packId = idByNode.current.get(entry.target);
          if (!packId || seen.current.has(packId)) continue;
          seen.current.add(packId);
          pending.current.push(packId);
          // Nothing more to learn from this card; stop watching it.
          observer.current?.unobserve(entry.target);
        }
        if (pending.current.length > 0 && timer.current === null) {
          timer.current = setTimeout(flush, FLUSH_MS);
        }
      },
      { threshold: VISIBLE_RATIO },
    );

    // A visitor who scrolls and then leaves inside the flush window is the common case on a
    // catalogue, so send whatever is buffered before the tab goes away. `pagehide` fires on
    // bfcache navigations where `unload` does not, and the beacon uses keepalive.
    const onHide = () => flush();
    window.addEventListener('pagehide', onHide);

    return () => {
      window.removeEventListener('pagehide', onHide);
      flush();
      observer.current?.disconnect();
      observer.current = null;
    };
  }, [flush]);

  const observe = useCallback(
    (packId: string) => (node: HTMLElement | null) => {
      if (!node || !observer.current || seen.current.has(packId)) return;
      idByNode.current.set(node, packId);
      observer.current.observe(node);
    },
    [],
  );

  return { observe };
}
