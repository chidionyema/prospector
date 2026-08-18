import React from 'react';
import Link from 'next/link';
import { Button, Card, Icon, cx } from '@/components/ui';
import type { IconName, ButtonVariant } from '@/components/ui';
import { track } from '@/lib/analytics';

/**
 * Small presentational blocks shared across the WR-014 GTM marketing pages.
 * Semantic tokens only (raw hex/palette fails `npm run conformance`). No data, no API, these
 * are pure layout/typography so the pages stay static and Pact-free.
 */

/**
 * Full-bleed section background with the standard inner content container.
 *
 * Brand v3 (2026-08-06): `band` is GONE. It painted whole sections near-black, which is what
 * forced the `inverse`/`inverseGhost` buttons, the `--on-band*` text tokens and a second set of
 * contrast rules for every component that could land inside one. Two colour systems in one page
 * is how the site ended up with black-on-orange CTAs. Section separation now comes from
 * `--surface2` (#FAFAFA) and the hairline bottom border, nothing else.
 *
 * `band` and `vault-wash` are kept in the map as aliases so the ~20 call sites do not all have to
 * change in the same commit; both resolve to the off-white wash.
 */
type BandBg = 'surface' | 'surface2' | 'surface3' | 'band' | 'vault-wash' | 'white' | 'bg';
const BAND_BG: Record<BandBg, string> = {
  surface: 'bg-surface',
  surface2: 'bg-surface2',
  /*
   * THE GUTTER, added 2026-08-15. Founder, on the live shelf: "the cards have the same header and
   * colour as the page, bland."
   *
   * That was literally true rather than a matter of taste -- `--bg` and `--surface` are both
   * #FFFFFF (tokens.css), so a pack card was separated from the page it sits on by one #E4E4E7
   * hairline and nothing else. `--surface3` is declared in that same file as "the shelf gutter
   * behind cards" and no shelf was using it.
   *
   * The fix is under the cards, not on them: tinting the card would make it a grey box, while a
   * tinted GROUND makes the same white card read as paper. This codebase already proves the move
   * on the specimen plinth -- `PackSpecimen.tsx`: "--surface3 behind white paper is what makes
   * the paper read as paper; on the page's own white it would read as a bordered div."
   */
  surface3: 'bg-surface3',
  band: 'bg-surface2',
  'vault-wash': 'bg-surface2',
  white: 'bg-surface',
  bg: 'bg-bg',
};
const BAND_WIDTH = { '2xl': 'max-w-2xl', '3xl': 'max-w-3xl', '4xl': 'max-w-4xl', '6xl': 'max-w-6xl', '7xl': 'max-w-7xl' } as const;

export function SectionBand({
  bg = 'surface',
  width = '3xl',
  bandId,
  className,
  outerClassName,
  children,
}: {
  bg?: BandBg;
  width?: keyof typeof BAND_WIDTH;
  /**
   * Opt-in name for the `band_view` beacon (MASTER-BRIEF section 9).
   *
   * A band with no id is not counted. Counting every band on the site would report mostly
   * bands nobody chose to measure, and the id has to be a stable name a person picked: a
   * position in the file would change the meaning of the historic rows the next time a band
   * moves.
   */
  bandId?: string;
  className?: string;
  /**
   * Classes for the `<section>` itself, as opposed to the centred measure inside it.
   *
   * This exists because `className` goes to the INNER div, which is not obvious from a call
   * site and is silent when you get it wrong: a layout class that only means something to a
   * parent -- `order`, `col-span`, a flex-child `basis` -- lands on a node that is not the
   * parent's child, so it applies cleanly, cascades nothing, and the page measures exactly
   * as it did before. That is the worst kind of bug to chase, because the class IS in the
   * DOM. F-001's fold fix needs `order` on the band, so the band gets its own channel.
   */
  outerClassName?: string;
  children: React.ReactNode;
}) {
  const sectionRef = React.useRef<HTMLElement>(null);
  /**
   * Fire `band_view` once, the first time this band enters the viewport.
   *
   * IntersectionObserver rather than a scroll handler: the browser does the geometry off the
   * main thread, so nothing here reads layout. The observer disconnects on the first hit, so a
   * reader who scrolls past a band four times counts as one reader who reached it.
   */
  React.useEffect(() => {
    const el = sectionRef.current;
    if (!bandId || !el || typeof IntersectionObserver === 'undefined') return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return;
        observer.disconnect();
        track('band_view', bandId);
      },
      // A quarter of the band on screen. A single pixel counts a band the reader scrolled
      // straight past, which is not the same as reaching it.
      { threshold: 0.25 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [bandId]);

  return (
    <section ref={sectionRef} className={cx(BAND_BG[bg], "border-b border-border last:border-b-0", outerClassName)}>
      {/*
        `overflow-clip`, NEVER `overflow-hidden`. The two clip identically, but `hidden` makes this
        div a SCROLL CONTAINER, and a scroll container is the containing block for every descendant
        `position: sticky`. That silently disabled the pack page's buy rail: `sticky top-24` computed
        as `sticky`, so it read as correct in the DOM, while the rail scrolled away at 2,200px of a
        5,190px page and left the money off screen (probed 2026-08-14: railTop -2007 inside a parent
        4,082px tall). `clip` does not create a scroll container, so the clipping stays and sticky
        works. Anything inside a band that must stay put depends on this word.
      */}
      <div className={`mx-auto ${BAND_WIDTH[width]} overflow-clip px-6 md:px-8 lg:px-10 ${className ?? ''}`}>
        {children}
      </div>
    </section>
  );
}

/**
 * A page hero: label, headline, lead, up to two actions. Left-aligned and tight.
 *
 * Three things were removed and each was doing visible damage:
 *  - `md:min-h-[calc(100dvh-4rem)]` forced every marketing hero to fill the viewport, which is
 *    what pushed the content of every page below the fold on a laptop.
 *  - `text-center` centred prose up to 50ch wide; a centred ragged-both-edges paragraph is
 *    measurably slower to read because each line starts at a different x.
 *  - `uppercase tracking-wide font-bold` on the buttons: three loudness devices on one control.
 */
export function PageHero({
  bg = 'white',
  /**
   * The band width, which must be the width the REST of the page uses.
   *
   * It was hardcoded to '4xl' and four of the five pages that render a hero set their body bands
   * to 6xl or 7xl, so those pages had two left edges: on /how-it-works the headline and lead began
   * at x=432 and every one of the six checks below began at x=258 (desktop-how-it-works-fold.png,
   * 2026-08-06). The reader has to find a new left margin halfway down a page that is one column
   * of text.
   *
   * Widening the band does not lengthen a line of the hero: the measure is set inside by
   * `max-w-[46rem]` / `max-w-[20ch]` / `max-w-[60ch]`, which is the right place for it. The band
   * only decides where the column starts.
   */
  width = '4xl',
  eyebrow,
  title,
  lead,
  primary,
  secondary,
  /**
   * A SECOND COLUMN, beside the headline, on large screens only.
   *
   * WHY THIS EXISTS (2026-08-16, founder on /collections and /kill-log: "right first row/ish empty no
   * content, looks odd on desktop", and "the empty hero only happens on desktop... its the right
   * section only"). Both halves of that report are exactly right, and the second half is the
   * diagnosis. The measure below is `max-w-[46rem]` and every page that reported this sets the
   * BAND to 6xl or 7xl -- 72rem or 80rem. So on a desktop viewport the hero is a 46rem column of
   * text with 26 to 34rem of nothing to its right, and on a phone the band is narrower than the
   * measure and the two numbers coincide, which is why it is desktop-only. The measure is not the
   * bug: 46rem is the line length, and `width` deliberately does not lengthen a line (see its own
   * note). The bug is that there was never anywhere for a second column to go.
   *
   * So this is a SLOT, not content. It is deliberately not a default graphic: the pages that
   * reported the gap each have their own material that was already sitting below the fold or
   * stacked under the lead, and filling the column with decoration would be the thing this site
   * spends the rest of its code refusing to do. `children` is not that slot and cannot be -- it
   * renders full width UNDER the whole hero (`mt-12`), which is where a page puts a strip that
   * spans both columns.
   *
   * The grid appears only when an aside is passed, so every hero without one emits the same DOM it
   * emitted before, and the breakpoint is `lg` rather than `md`: at md the band is already close
   * to the measure and splitting it there would squeeze the headline to win back space that is not
   * empty at that width. `items-start` because the aside is a list beside a heading, not a thing
   * to centre against it.
   */
  aside,
  children,
}: {
  bg?: BandBg;
  width?: keyof typeof BAND_WIDTH;
  eyebrow?: string;
  title: React.ReactNode;
  lead?: React.ReactNode;
  primary?: { href: string; label: string; onClick?: () => void; variant?: ButtonVariant };
  secondary?: { href: string; label: string; variant?: ButtonVariant };
  aside?: React.ReactNode;
  children?: React.ReactNode;
}) {
  // `animate-settle`, not `animate-rise`. A page hero is by definition the largest thing above
  // the fold, so it is the LCP element on every route that uses this component, and `rise`
  // fades in from opacity 0 -- which is not LCP-eligible. Measured: /how-it-works 1824ms and
  // /collections 1860ms LCP against 164ms and 208ms first paint (F-005).
  return (
    /* `page-hero` on the BAND, not the measure: `globals.css` uses it as an adjacent-sibling hook
       to stop the section below opening with a full 96px on top of this band's own closing space.
       See the note there for the measurement. `pb` comes down with it -- 64px under a lead, above
       a rule, above another 96px, was the larger half of a 160px gap. */
    <SectionBand
      bg={bg}
      width={width}
      outerClassName="page-hero"
      className="pt-10 pb-10 md:pt-14 md:pb-12 animate-settle"
    >
      <div
        className={
          aside
            ? 'grid gap-10 lg:grid-cols-[minmax(0,46rem)_minmax(0,1fr)] lg:items-start lg:gap-16'
            : undefined
        }
      >
      <div className="max-w-[46rem]">
        {eyebrow && (
          <p className="mb-3 text-caption font-medium text-subtle">{eyebrow}</p>
        )}
        <h1 className="max-w-[20ch] text-balance text-h1 font-semibold text-text">{title}</h1>
        {lead && (
          <div className="mt-4 max-w-[60ch] text-body text-muted">
            {lead}
          </div>
        )}
        {(primary || secondary) && (
          <div className="mt-8 flex flex-col gap-3 sm:flex-row sm:items-center">
            {primary && (
              <Link href={primary.href} onClick={primary.onClick} className="w-full sm:w-auto">
                <Button variant={primary.variant || 'primary'} size="lg" className="w-full sm:w-auto">{primary.label}</Button>
              </Link>
            )}
            {secondary && (
              <Link href={secondary.href} className="w-full sm:w-auto">
                <Button variant={secondary.variant || 'secondary'} size="lg" className="w-full sm:w-auto">{secondary.label}</Button>
              </Link>
            )}
          </div>
        )}
      </div>
        {aside}
      </div>
      {children && <div className="mt-12 w-full md:mt-16">{children}</div>}
    </SectionBand>
  );
}

/**
 * The hero aside's one setting: a labelled list, beside the headline.
 *
 * All three pages that reported an empty right column have the same thing to put in it -- a short
 * enumeration the left column either names without showing (the six checks on /how-it-works) or
 * states as an undifferentiated run-on (the six sort axes on /collections, which a previous pass already
 * diagnosed as "not the sentence, it is that a 34-word enumeration is being drawn as one
 * paragraph of lead type. Fix the setting, not the words"). One component so the three cannot
 * drift into three treatments of the same object.
 *
 * `text-meta` and `text-muted`, not lead type: this is the subordinate column. The rule on the
 * left edge is what makes it read as a list rather than as a second paragraph, and it is
 * `border-l` on the items rather than a `<ul>` marker because the site sets no bullets anywhere
 * else. Ordered only where the order is real -- the checks run in a sequence and stop at the first
 * failure, the sort axes do not -- which is `storefrontDesignContract`'s own rule about numbering
 * encoding something true rather than decorating.
 */
export function HeroList({
  label,
  items,
  ordered = false,
}: {
  label: string;
  items: readonly string[];
  ordered?: boolean;
}) {
  const List = ordered ? 'ol' : 'ul';
  return (
    <div className="lg:pt-1">
      <p className="text-caption font-medium text-subtle">{label}</p>
      <List className="mt-4 space-y-2.5">
        {items.map((item, i) => (
          <li
            key={item}
            className="flex gap-3 border-l border-border pl-4 text-meta leading-relaxed text-muted"
          >
            {ordered && (
              <span className="shrink-0 font-mono tabular-nums text-subtle">{i + 1}</span>
            )}
            <span>{item}</span>
          </li>
        ))}
      </List>
    </div>
  );
}

/** A titled content section with consistent vertical rhythm. */
export function Section({
  bg = 'surface',
  width = '3xl',
  title,
  intro,
  children,
  className,
  outerClassName,
}: {
  bg?: BandBg;
  width?: keyof typeof BAND_WIDTH;
  title?: React.ReactNode;
  intro?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  /** Classes for the `<section>` element -- see the note on `SectionBand`. */
  outerClassName?: string;
}) {
  return (
  /* MOBILE SECTION RHYTHM, CAPPED (brief 2026-08-15, item 7: "cap section gaps").
     `py-16` on both sides of a band means two adjacent bands put 64 + 64 = 128px of pure
     whitespace between the last line of one and the first line of the next. MEASURED at a 390
     viewport before this change: the six largest whitespace bands on /how-it-works were 178, 149,
     129, 129, 129, 129px, and the 129s are exactly that stack. On a phone that is most of a
     screen of nothing between two paragraphs, which is the founder's complaint.

     `py-10` is 40px, on the brief's 8/16/24/40/64 scale, and takes the stacked gap to 80px. The
     desktop `md:py-24` is untouched: at 1280px a 96px band reads as composition, and the defect
     is specific to the width where the content column is 350px wide. */
    <SectionBand bg={bg} width={width} outerClassName={outerClassName} className={`py-10 md:py-24 scroll-mt-16 ${className ?? ''}`}>
      {(title || intro) && (
        <div className="mb-10">
          {title && <h2 className="text-h2 font-semibold text-text md:text-h1">{title}</h2>}
          {intro && <div className="mt-3 max-w-[60ch] text-body text-muted">{intro}</div>}
        </div>
      )}
      <div>{children}</div>
    </SectionBand>
  );
}

/** One numbered step in a flow. The counter is mono: it is an ordinal, i.e. data. */
export function Step({
  n,
  title,
  children,
}: {
  n: number;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <li className="flex gap-5">
      <div
        className="flex h-9 w-9 flex-none items-center justify-center rounded-md border border-border bg-surface2 font-mono text-caption font-medium text-subtle"
        aria-hidden="true"
      >
        {n.toString().padStart(2, '0')}
      </div>
      <div className="space-y-1.5 pt-1">
        <h3 className="text-body font-semibold leading-tight text-text">{title}</h3>
        <p className="text-meta text-muted">{children}</p>
      </div>
    </li>
  );
}

/** A feature/benefit card. */
export function FeatureCard({
  icon,
  title,
  children,
}: {
  icon: IconName;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <Card className="space-y-3 border-border bg-surface p-6">
      <div className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-border bg-surface2 text-subtle">
        <Icon name={icon} size={18} />
      </div>
      <h3 className="text-body font-semibold leading-tight text-text">{title}</h3>
      <p className="text-meta text-muted">{children}</p>
    </Card>
  );
}

/** Closing CTA band. Light, bordered, one primary action. */
export function CtaBand({
  title,
  lead,
  primary,
  secondary,
  /** Same rule as `PageHero`: match the page. A third left edge is worse than a wide band. */
  width = '3xl',
}: {
  width?: keyof typeof BAND_WIDTH;
  title: React.ReactNode;
  lead?: React.ReactNode;
  primary: { href: string; label: string };
  secondary?: { href: string; label: string };
}) {
  return (
    <SectionBand bg="surface2" width={width} className="scroll-mt-16 py-10 md:py-24">
      <h2 className="max-w-[20ch] text-balance text-h1 font-semibold text-text">{title}</h2>
      {lead && <p className="mt-3 max-w-[60ch] text-body text-muted">{lead}</p>}
      <div className="mt-8 flex flex-col items-start gap-3 sm:flex-row sm:items-center">
        <Link href={primary.href}>
          <Button variant="primary" size="lg">{primary.label}</Button>
        </Link>
        {secondary && (
          <Link href={secondary.href}>
            <Button variant="secondary" size="lg">{secondary.label}</Button>
          </Link>
        )}
      </div>
    </SectionBand>
  );
}
