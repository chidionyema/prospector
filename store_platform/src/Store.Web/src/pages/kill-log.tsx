import React from 'react';
import Link from 'next/link';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Seo } from '@/components/Seo';
import { buttonClasses, chipClasses, Glyph, SearchInput, SourceChip, VerdictChip, textLinkClass } from '@/components/ui';
import { Section, SectionBand } from '@/components/marketing/blocks';
import { CauseGrid } from '@/components/marketing/CauseGrid';
import { WaitlistCallout } from '@/components/waitlist/WaitlistCallout';
import { tightDecimal } from '@/components/ui/Money';
import { RESEARCH_STATS } from '@/lib/stats';
// Types only in the client bundle; `buildKillIndex` is referenced solely inside `getStaticProps`,
// which Next removes from the page's client JS along with everything only it imports. That is what
// keeps `data/kill-log.json` (456 KB) out of the browser -- see `lib/killLog.server.ts`.
import {
  buildKillIndex,
  isStageLabel,
  type KillDetail,
  type KillIndex,
  type KillSummary,
} from '@/lib/killLog.server';
import { fetchCatalogStats, fetchKillLogDetail } from '@/lib/api/client';
import { track } from '@/lib/analytics';
import type { GetStaticProps } from 'next';

/*
  The rejects, published, AS AN INSTRUMENT.

  A visitor is asked for £49 on the strength of "these survived a filter built to kill them" and has
  no way to see the brutality. The conventional fix is testimonials, which we cannot honestly show,
  there are no reviews to quote, and inventing one is both a lie and an offence under the DMCCA 2024
  fake-review rules. On a storefront whose entire pitch is source-or-die it would also be
  self-refuting: a reader who checks one claim, finds it fabricated, and then disbelieves the other
  forty-three has reasoned correctly.

  WHAT CHANGED, AND WHY. This page used to render its kills as a column of bordered cards at
  `space-y-4`, each with 20px of padding. That is an ARTICLE: a shape that says "read me in order,
  top to bottom", which is the correct shape for forty words and the wrong one for four hundred
  records. It also meant a reader could not answer the only questions a body of evidence this size
  can actually answer, all of which are comparative: what kills ideas most often, is that reason
  ever used to kill something like mine, has the filter been running recently, how many of these
  come with a source. Cards answer none of those. A table answers all of them.

  So the page is now a dense monospace table over 400 records with a distribution chart above it, a
  cause filter, a sort, and a stable anchor on every row. The type is small and the rows are tight
  on purpose: density is the argument. Four hundred struck-through names that you can sort is a
  claim about scale that no paragraph beginning "we rigorously evaluate" can make.

  Data comes from tools/make_kill_log.py, which reads the same dossiers the engine writes.
  It excludes kills whose only reason is a score below the bar. See that file.
*/

/* Read through `RESEARCH_STATS`, not off the JSON. This page used to compute its rejection rate
   itself and then describe its denominator as `killed`, so the meta description shipped "We
   researched 1168 business ideas" while /how-it-works said 1,313 from the identical file.
   `researched` is now an invariant (killed + survived) that no page can restate wrongly. */
const { killed, researched, rejectRateLabel } = RESEARCH_STATS;

/* The corpus itself is read at build time in `lib/killLog.server.ts`; everything that used to be
   computed here at module scope -- the slugs, the cause counts, the distribution chart -- arrives
   as props. Nothing in this file may reach for `data/kill-log.json` again: a single static import
   of it puts all 456 KB back in the client bundle, which is the defect this split fixed. */

type Sort = 'newest' | 'cause' | 'sources';
const SORTS: { key: Sort; label: string }[] = [
  { key: 'newest', label: 'Newest first' },
  { key: 'cause', label: 'Cause of death' },
  { key: 'sources', label: 'Most sources' },
];

function formatDate(iso: string) {
  if (!iso) return '';
  const d = new Date(`${iso}T00:00:00Z`);
  return Number.isNaN(d.getTime())
    ? ''
    : d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
}

type Props = KillIndex & { listed: number | null };

export default function KillLogPage({
  listed,
  summaries,
  gates,
  gateCounts,
  distribution,
  publishedKills,
  withSource,
}: Props) {
  const [active, setActive] = React.useState<string | null>(null);
  const [search, setSearch] = React.useState('');
  const [sort, setSort] = React.useState<Sort>('newest');
  const [open, setOpen] = React.useState<Set<string>>(() => new Set());
  /* The arguments, fetched once. `null` until something needs them: an expanded row or a search.
     A reader who scrolls the table and leaves never downloads them at all. */
  const [details, setDetails] = React.useState<Record<string, KillDetail> | null>(null);
  const wanted = open.size > 0 || search.trim().length > 0;

  React.useEffect(() => {
    if (!wanted || details) return;
    let live = true;
    // Best effort, and the swallowing now lives in the client function: a failed request leaves
    // the table, the filters and the sort working; only the expanded prose is missing, and the
    // row says so rather than rendering an empty panel.
    fetchKillLogDetail().then((d) => {
      if (live && d) setDetails(d);
    });
    return () => {
      live = false;
    };
  }, [wanted, details]);

  /* One lowercase haystack per kill, built once when the detail arrives instead of on every
     keystroke. The old filter ran `plainEnglish` over both prose fields of all 400 rows for each
     character typed; the prose now arrives already translated, and this reduces a keystroke to 400
     `includes` calls on strings that already exist. */
  const haystacks = React.useMemo(() => {
    if (!details) return null;
    const map = new Map<string, string>();
    for (const s of summaries) {
      const d = details[s.slug];
      map.set(s.slug, `${s.title} ${d?.oneLiner ?? ''} ${d?.reason ?? ''}`.toLowerCase());
    }
    return map;
  }, [details, summaries]);

  /*
    A DEEP LINK MUST SURVIVE THE FILTERS.

    Rows are hidden by `active`/`search`, so arriving at /kill-log#some-idea with a filter state
    that excludes that row would scroll to nothing and look like a dead link on the one page whose
    subject is our own honesty. The filters start empty on every load, so the only thing needed is
    to open the targeted row and bring it into view once, after paint.
  */
  React.useEffect(() => {
    const hash = decodeURIComponent(window.location.hash.replace('#', ''));
    if (!hash) return;
    /* Two frames, and the state change happens inside the first callback rather than in the effect
       body. Both details are load-bearing:
         - opening in a callback keeps this off React's synchronous render path, which is what
           `react-hooks/set-state-in-effect` is guarding against;
         - scrolling on the SECOND frame means the detail row has already been laid out, so the
           browser scrolls to the row's final position instead of to where it sat before it
           expanded, which otherwise lands the target off screen by the height of its own reason. */
    let scrollFrame = 0;
    const openFrame = window.requestAnimationFrame(() => {
      setOpen(new Set([hash]));
      scrollFrame = window.requestAnimationFrame(() => {
        document.getElementById(hash)?.scrollIntoView({ block: 'center' });
      });
    });
    return () => {
      window.cancelAnimationFrame(openFrame);
      window.cancelAnimationFrame(scrollFrame);
    };
  }, []);

  const shown = React.useMemo(() => {
    // `active` holds a gateLabel, matching how the chips above are keyed.
    let items = active ? summaries.filter((e) => e.gateLabel === active) : summaries.slice();
    if (search.trim()) {
      const q = search.toLowerCase();
      // Searched in the words the reader can SEE: the haystack is built from the translated prose,
      // so a query matches the word 104 of these rows now display rather than the engine's own.
      // Until the prose lands, the title is what there is to search -- one round trip, and only on
      // the first keystroke of the session.
      items = items.filter((e) =>
        haystacks ? (haystacks.get(e.slug) ?? '').includes(q) : e.title.toLowerCase().includes(q),
      );
    }
    // Every sort falls back to date descending, so the order is total and a re-sort never
    // reshuffles rows that tie. Without the tiebreak, sorting by cause would return the ties in
    // whatever order the previous sort happened to leave them, which reads as the table jittering.
    const byDate = (a: KillSummary, b: KillSummary) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0);
    if (sort === 'cause') {
      items.sort((a, b) => {
        const d = gateCounts[b.gateLabel] - gateCounts[a.gateLabel];
        if (d !== 0) return d;
        const l = a.gateLabel.localeCompare(b.gateLabel);
        return l !== 0 ? l : byDate(a, b);
      });
    } else if (sort === 'sources') {
      items.sort((a, b) => b.sources - a.sources || byDate(a, b));
    } else {
      items.sort(byDate);
    }
    return items;
  }, [active, search, sort, summaries, gateCounts, haystacks]);

  // The bar is drawn against the LARGEST cause, not the total: against the total every bar but one
  // is a sliver and the chart shows nothing.
  const distributionMax = Math.max(...distribution.map((d) => d.count), 1);

  /**
   * Open or close one record, and count the opens (MASTER-BRIEF section 9, `kill_row_click`).
   *
   * The beacon fires on open only. A close is the same click on the same row, so counting both
   * would double every reader who finished reading and tidied up after themselves.
   *
   * The cause travels with the slug because the whole question this event answers is which
   * causes readers choose to open. Joining a slug back to its cause afterwards would need the
   * kill log at the time of the click, which we do not keep.
   *
   * The beacon is sent here rather than inside the `setOpen` updater. React calls an updater
   * twice in development StrictMode, so a side effect in there is a double count that only
   * shows up in the data, never on screen.
   */
  const toggle = (slug: string, cause: string) => {
    if (!open.has(slug)) track('kill_row_click', `${slug}:${cause}`);
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(slug)) next.delete(slug);
      else next.add(slug);
      return next;
    });
  };

  return (
    <MarketingLayout
      breadcrumbs={[{ href: '/', label: 'Catalogue' }, { href: '#', label: 'Kill log' }]}
      breadcrumbsWidth="6xl"
    >
      <Seo
        title="The kill log, the ideas we killed, and the sourced reason why"
        description={`We researched ${researched.toLocaleString('en-GB')} business ideas and killed ${rejectRateLabel} of them. Here are ${publishedKills} of the kills, each with the evidence that killed it.`}
      />

      {/* Left-aligned, one column, no centred hero (spec §7.4). A centred 22ch headline over a
          centred 62ch paragraph over a centred stat row gives the reader three different left
          edges to find in the first screen of a page that is otherwise a table. */}
      {/* TWO COLUMNS ON DESKTOP (2026-08-16, founder: "right first row/ish empty no content, looks
          odd on desktop"). Same diagnosis as /collections and /how-it-works -- a 3xl measure inside a 6xl
          band leaves about 24rem of nothing to the right of the headline, and only above `lg`,
          which is why the report was desktop-only. This page does not use `PageHero`, so it takes
          the same grid by hand rather than adopting the component: the hero here is four blocks in
          two registers, not a headline with a lead, and routing it through `PageHero` would mean
          bending that component to a fifth shape for one caller.

          WHAT MOVES IS THE CAVEAT, and nothing is written to fill the space. It is the one block
          here in a different register -- a correction, in `text-meta`, qualifying the count above it
          -- and it was set as a fourth paragraph in the same column, which is what buried it below
          all three claims it corrects. Beside them it is read with them.

          The mobile order changes slightly and deliberately: the caveat now falls after the chip row
          instead of before it. Its own docblock's requirement is that the correction arrive before
          the CLAIM IT CORRECTS -- the implied 1,364-row page -- and it still does, by a whole
          screen, since the table is far below. */}
      <SectionBand bg="white" width="6xl" className="pt-14 pb-8 md:pt-20 md:pb-10">
        <div className="grid gap-10 lg:grid-cols-[minmax(0,46rem)_minmax(0,1fr)] lg:items-start lg:gap-16">
        <div className="max-w-3xl">
          <p className="text-caption font-medium text-subtle">The kill log</p>
          {/* THE HERO: ONE COUNT. It read "1,364 killed. 80 survived.", and the second half was
              the figure the founder cut on 2026-08-13, because the shelf this page links to holds
              50. The live shelf count is not promoted into the headline to replace it: it is
              already in the chip row 200px below, and printing one number twice in one block is
              the defect this page has fixed twice before ("61 live now" / "60 live now"). The
              count carries the page on its own, and the caveat four lines down is what qualifies
              it. Nothing here promises a reason for all 1,364: only 400 came with an argument, and
              that sentence is already in the caveat rather than contradicted by this headline. */}
          <h1 className="mt-3 text-h1 font-semibold text-text">
            {killed.toLocaleString('en-GB')} ideas killed.
          </h1>
          <p className="mt-5 max-w-[60ch] text-body text-muted">
            Most ideas do not survive. Here is what we rejected, the reason each one failed, and
            the sources, so you can check the reasoning yourself.
          </p>
          {/* Mono: both are counts, and the pair is the one place on the site where the rejection
              rate is stated as a measured quantity rather than a boast. */}
          <div className="mt-6 flex flex-wrap items-center gap-x-6 gap-y-2 font-mono text-meta">
            {/* §3.3: the killed square, not a warning triangle. A triangle is a caution sign --
                it tells the reader to be careful about something ahead. A kill is not a hazard,
                it is a finished ruling, and the crossed square is the mark the rest of the site
                uses for one. */}
            {/* Composed rather than hand-drawn (MASTER-BRIEF §6). The glyph, the word and the
                red arrive together, and this page is the one place red means exactly what it
                says. */}
            <VerdictChip
              kind="killed"
              label={`${rejectRateLabel} killed`}
              className="gap-2 text-meta"
            />
            {/* The green chip counts what is BUYABLE, not what cleared the gates. It has carried
                "80 survived" and then "80 survived the checks", both against a shelf of 50; the
                survivor figure is gone from the site (lib/stats.ts, founder directive 2026-08-13)
                and this is the number the reader can act on anyway. Omitted entirely when the
                catalogue call failed, because a chip with no number is not a stat. */}
            {listed ? (
              <span className="inline-flex items-center gap-2 text-survive">
                <Glyph name="survived" />
                {listed.toLocaleString('en-GB')} on the shelf
              </span>
            ) : null}
          </div>
        </div>

        {/* THE CAVEAT. It used to sit below all the entries, under a homepage line promising the log
            "has every one": a reader met an implied 1,330-row page, scrolled, and only then learned
            what they were actually looking at. On the one page whose job is to prove we do not
            overclaim, the correction has to arrive before the claim it corrects, so it came to the
            top -- and then sat as a fourth paragraph in the same column, under the three claims it
            qualifies. It is a different register from all of them. Here it is beside them.
            `border-l` and `text-meta` are `HeroList`'s grammar, so the three heroes that gained a
            right-hand column on 2026-08-16 read as one treatment. */}
        <aside className="lg:pt-1">
          <p className="text-caption font-medium text-subtle">What this page publishes</p>
          <p className="mt-4 border-l border-border pl-4 text-meta leading-relaxed text-muted">
            This page publishes {publishedKills} of those kills, not all {killed.toLocaleString('en-GB')}.
            The rest were rejected on a low overall score, with no single finding behind it, so
            there would be nothing here for you to read. Every kill below names the check it
            failed and why, and{` ${withSource}`} of them link the source.
          </p>
        </aside>
        </div>
      </SectionBand>

      <Section bg="bg" width="6xl" className="!pt-6 !pb-24">
        {/* ── HOW IDEAS DIE ─────────────────────────────────────────────────────────────────────
            The chart is the page's thesis in one object, and it is placed above the table because
            it is what makes the table legible: a reader who knows incumbency is the largest
            publishable cause reads 188 incumbency rows as a pattern rather than as repetition. */}
        <section aria-labelledby="distribution-heading" className="rounded-md border border-border bg-surface p-6 md:p-7">
          <h2 id="distribution-heading" className="text-h2 font-semibold text-text">
            How ideas die
          </h2>
          <p className="mt-2 max-w-[68ch] text-meta text-muted">
            Every rejection across all {killed.toLocaleString('en-GB')} kills, by the check that
            fired first. The checks stop at the first hard failure, so each idea is counted once,
            against the cheapest gate that killed it.
          </p>
          {/* A STAGE IS NOT A CHECK, and until now the page drew them identically. Three of these
              causes are stages of the run rather than findings about the idea: the idea scored too
              low across all six checks, the evidence never grounded, or adversarial review was not
              decisive. A reader comparing "no durable advantage" with "scored too low" was
              comparing a finding with a tally, and nothing on the page marked the difference.
              `isStageLabel` keys on the LABEL for the reason given where it is defined: every
              surface on this page is keyed on label, and two engine keys can share one. */}
          <p className="mt-2 max-w-[68ch] text-meta text-muted">
            Causes marked <span className="font-mono text-caption text-subtle">stage</span> are
            points in the run rather than findings about the idea: it scored too low overall, or
            the evidence never grounded well enough to rule on.
          </p>
          {/* ── THE SIGNATURE (MASTER-BRIEF §7) ────────────────────────────────────────────────
              The grid FIRST, the bars second, and they are the same numbers twice on purpose.

              A bar chart answers "which cause is biggest" and it answers it by asking the reader
              to compare lengths. It cannot show SCALE: nothing in a row of bars says whether this
              is a hundred ideas or fourteen hundred. The grid draws one cell per idea, so the size
              of the claim is the size of the picture, and the reader gets it before reading a
              single label. The bars then give the ranking precisely, with the counts, which the
              grid cannot do. Neither is redundant; the brief asks for both, in this order. */}
          <CauseGrid distribution={distribution} className="mt-6" />

          {/* The label column is fixed at 15rem so the bars share one baseline and the chart
              compares -- but 15rem plus a bar plus a count does not fit 390px, and measured on
              2026-08-13 at that width the row rendered "The defensibility claim was not
              evidence-b...". Truncating the CAUSE of a rejection is the one thing this chart
              cannot do: the label IS the finding. So below `sm` the label takes the full row on
              its own and wraps, and the bar and count drop to a second line under it; the fixed
              column and the single-line row return the moment there is width for them. */}
          {/* `space-y-4` below `sm` because the row is two lines there: at `space-y-2` a label sat
              21px from its own bar and 25px from the next label, so the pairing was ambiguous at
              exactly the width where the pairing is the only thing holding the chart together. On
              `sm` and up each row is one line again and 8px is the right rhythm. */}
          <ul className="mt-6 list-none space-y-4 p-0 sm:space-y-2">
            {distribution.map((d) => (
              <li
                key={d.gate}
                className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1.5 sm:grid-cols-[15rem_minmax(0,1fr)_auto]"
              >
                <span
                  className="col-span-2 text-caption leading-snug text-muted sm:col-span-1 sm:truncate"
                  title={d.label}
                >
                  {d.label}
                  {d.isStage && <span className="ml-1.5 text-subtle"> stage</span>}
                </span>
                {/* The bar is drawn against the LARGEST cause, not against the total. Against the
                    total every bar but one is a sliver and the chart shows nothing; against the
                    max, the comparison the reader came for is the one the picture makes. */}
                <span className="block h-3 min-w-0 bg-surface3">
                  <span
                    /* NEUTRAL BOTH WAYS (2026-08-14 colour audit, finding 2). These bars were
                       `bg-kill` when published and grey when not, on the one page that defines
                       red as "killed" -- so red here encoded PUBLICATION STATUS, and the
                       largest cause of death on the chart (624) was drawn in decoration grey
                       because nothing was published under it. A reader taking the page at its
                       word read the ranking backwards. Ink weight now carries "listed below"
                       and red goes back to meaning exactly one thing. */
                    className={d.published ? 'block h-3 bg-text' : 'block h-3 bg-subtle/35'}
                    style={{ width: `${Math.max((d.count / distributionMax) * 100, 0.6)}%` }}
                  />
                </span>
                <span className="w-14 text-right font-mono text-caption tabular-nums text-text">
                  {tightDecimal(d.count.toLocaleString('en-GB'))}
                </span>
              </li>
            ))}
          </ul>
          {/* The legend explains the grey, which would otherwise read as "smaller" rather than as
              "not shown below" and leave a reader hunting the table for rows that are not in it. */}
          <p className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1 text-caption text-subtle">
            <span className="inline-flex items-center gap-2">
              <span className="inline-block h-2 w-4 bg-text" aria-hidden />
              listed in the table below
            </span>
            <span className="inline-flex items-center gap-2">
              <span className="inline-block h-2 w-4 bg-subtle/35" aria-hidden />
              killed on a score, no argument to publish
            </span>
          </p>
        </section>

        {/* ── CONTROLS ──────────────────────────────────────────────────────────────────────── */}
        <div className="mt-10">
          <SearchInput
            label="Search kills by title, description, or reason"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search kills by title, description, or reason…"
            className="mb-4"
          />
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => setActive(null)}
              aria-pressed={active === null}
              className={chipClasses({ selected: active === null })}
            >
              {/* "All 400" directly under a headline saying 1,330 read as a contradiction. It is
                  all of what is PUBLISHED, and the chip now says which. */}
              All {publishedKills} published
            </button>
            {gates.map((label) => (
              <button
                key={label}
                type="button"
                onClick={() => setActive(label === active ? null : label)}
                aria-pressed={label === active}
                className={chipClasses({ selected: label === active })}
              >
                {label} {gateCounts[label]}
              </button>
            ))}
          </div>

          <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-caption text-subtle">Sort</span>
              {SORTS.map((s) => (
                <button
                  key={s.key}
                  type="button"
                  onClick={() => setSort(s.key)}
                  aria-pressed={sort === s.key}
                  className={chipClasses({ selected: sort === s.key })}
                >
                  {s.label}
                </button>
              ))}
            </div>
            {/* The live count of what the controls are currently showing. Without it, filtering a
                400-row table gives no feedback that anything happened until you scroll. */}
            <p className="font-mono text-caption tabular-nums text-subtle">
              {tightDecimal(shown.length.toLocaleString('en-GB'))} shown
            </p>
          </div>
        </div>

        {/* ── THE TABLE ─────────────────────────────────────────────────────────────────────────
            A real <table>, not a grid of divs, because this is tabular data and the semantics are
            free: a screen reader user gets column headers announced against every cell, which is
            the only way 400 rows of four fields are navigable without sight.

            `overflow-x-auto` on the wrapper, never on the page. The site's body must not scroll
            sideways, and a dense table at 360px will exceed it.

            Below `md` the Idea column wraps against the table's own 44rem floor, not the phone's
            390px viewport, so the first title on the page was cut off mid-word ("...a family
            carer") with nothing on screen to say the row continues -- a reader saw a truncated
            sentence, not a scrollable table. The mask is a static fade on the wrapper's right
            edge, present whenever the table is narrower than its content, that reads as "there is
            more this way" without needing scroll-position JS. Both the standard and `-webkit-`
            property are set because this is exactly the iOS Safari path the bug was found on. */}
        <div className="mt-6 overflow-x-auto border-y border-border max-md:[-webkit-mask-image:linear-gradient(to_right,black_calc(100%-2rem),transparent)] max-md:[mask-image:linear-gradient(to_right,black_calc(100%-2rem),transparent)]">
          <table className="w-full min-w-[44rem] border-collapse text-left">
            <caption className="sr-only">
              Killed ideas, with the check that killed each one, its published sources and the
              date it was assessed. Select a row to read the argument.
            </caption>
            <thead>
              <tr className="border-b border-border">
                <th scope="col" className="py-2 pr-4 text-caption font-medium text-subtle">Idea</th>
                <th scope="col" className="py-2 pr-4 text-caption font-medium text-subtle">Killed by</th>
                <th scope="col" className="w-20 py-2 pr-4 text-right text-caption font-medium text-subtle">Sources</th>
                <th scope="col" className="w-28 py-2 text-right text-caption font-medium text-subtle">Assessed</th>
              </tr>
            </thead>
            {shown.map((entry) => {
              const isOpen = open.has(entry.slug);
              const detail = details?.[entry.slug];
              return (
                /* One <tbody> per record, so the summary row and its detail row are one group to
                   assistive tech rather than two unrelated rows that happen to be adjacent. */
                <tbody key={entry.slug} id={entry.slug} className="scroll-mt-24 border-b border-border align-baseline">
                  <tr
                    className="cursor-pointer transition-colors hover:bg-surface3"
                    onClick={() => toggle(entry.slug, entry.gateLabel)}
                  >
                    <td className="py-2.5 pr-4">
                      <button
                        type="button"
                        aria-expanded={isOpen}
                        // The button carries the whole interaction for keyboard and screen reader
                        // users; the row's onClick is a convenience for a mouse. Stopping
                        // propagation keeps a click on the button from toggling twice.
                        onClick={(e) => {
                          e.stopPropagation();
                          toggle(entry.slug, entry.gateLabel);
                        }}
                        className="text-left font-mono text-caption leading-snug text-muted line-through decoration-kill/60 hover:text-text"
                      >
                        {entry.title}
                      </button>
                      {/* THE ARGUMENT IS THE ROW (MASTER-BRIEF §7). Before this, a row carried a
                          title and a cause label, and the reasoning was behind a click. That makes
                          400 rows of assertion: the reader is told an idea failed on incumbency and
                          has no evidence in front of them that we did any work, so the only way to
                          find out whether the page is real is to open a row and hope. On a phone
                          that is a tap, a wait on a fetch, and a scroll. Two lines of the actual
                          finding on every row means the reader can scan twenty of them and see the
                          arguments are specific, before deciding whether to open one.

                          IT DISAPPEARS WHEN THE ROW OPENS, because the panel below starts with the
                          same sentence. Two copies of one sentence three lines apart reads as a
                          rendering fault on the page whose subject is our own carefulness. */}
                      {!isOpen && entry.excerpt && (
                        <p className="mt-1 max-w-[60ch] text-caption leading-relaxed text-subtle">
                          {entry.excerpt}
                        </p>
                      )}
                    </td>
                    <td className="py-2.5 pr-4 font-mono text-caption text-kill-strong">
                      {entry.gateLabel}
                      {isStageLabel(entry.gateLabel) && (
                        <span className="ml-1.5 text-subtle"> stage</span>
                      )}
                    </td>
                    <td className="py-2.5 pr-4 text-right font-mono text-caption tabular-nums text-subtle">
                      {/* A literal 0, not a blank or a placeholder glyph. This column is
                          sortable, so an empty cell would read as missing data in a table that is
                          about evidence; 0 is the actual, stated fact. The COUNT is in the page's
                          own HTML even though the source list is not: it is a column of the table
                          and a sort key, so it cannot wait on a fetch. */}
                      {entry.sources}
                    </td>
                    <td className="py-2.5 text-right font-mono text-caption tabular-nums text-subtle">
                      {formatDate(entry.date)}
                    </td>
                  </tr>
                  {isOpen && (
                    <tr>
                      <td colSpan={4} className="bg-surface3 px-3 py-4">
                        {/* The argument arrives from /api/kill-log-detail, once per session. Until
                            it does the row says what it is waiting for: an empty panel under a
                            row a reader just opened reads as a broken page, and this is the page
                            whose subject is our own honesty. */}
                        {!detail ? (
                          <p className="text-meta text-subtle">
                            {details ? 'This argument could not be loaded. Reload the page to try again.' : 'Loading the argument…'}
                          </p>
                        ) : (
                        <>
                        {detail.oneLiner && (
                          <p className="max-w-[80ch] text-meta text-muted">{detail.oneLiner}</p>
                        )}
                        {/* THE ENGINE'S OWN WORDS, TRANSLATED ON THE WAY OUT. This paragraph is
                            written by the verdict brain for an audit trail and rendered verbatim
                            to a buyer, and on 2026-08-15 that meant 104 of these 400 reasons said
                            "the candidate" and 32 named a gate as `payer_solvency`. The JSON keeps
                            the engine's words; `plainEnglish` is the last step before a reader --
                            now applied once at build time in `lib/killLog.server.ts` rather than
                            on every render. See lib/plainEnglish.ts for what it does NOT translate. */}
                        <p className="mt-3 max-w-[80ch] text-meta text-text">{detail.reason}</p>
                        <div className="mt-3 flex flex-wrap items-center gap-2">
                          {/* Kills with no resolvable source are BADGED, not left blank. The page
                              promises "the sourced reason why", so an entry with nothing to link
                              was silently indistinguishable from one whose sources we simply had
                              not shown. `make_kill_log.py` drops references it cannot resolve to a
                              real URL rather than rendering a dead hash, which is why these are
                              empty. */}
                          {detail.citations.length === 0 && (
                            <span className="inline-flex items-center gap-1 rounded-md border border-dashed border-border px-1.5 py-0.5 font-mono text-caption text-subtle">
                              argument recorded, no source published
                            </span>
                          )}
                          {/* Was a byte-for-byte copy of `CitationChip`'s markup, pasted here. It
                              is the sixth such copy the source-chip consolidation found, and the
                              only one an agent survey of the tree missed -- `sourceChipIsTheOnlyOne`
                              caught it on its first run. */}
                          {detail.citations.map((c, j) => (
                            <SourceChip key={j} url={c.url} host={c.domain} />
                          ))}
                          {/* The per-kill permalink. This is the share mechanic: the interesting
                              unit of this page is one rejection, not the page. */}
                          <a
                            href={`#${entry.slug}`}
                            className={textLinkClass('ml-auto font-mono text-caption')}
                          >
                            link to this kill
                          </a>
                        </div>
                        </>
                        )}
                      </td>
                    </tr>
                  )}
                </tbody>
              );
            })}
          </table>
        </div>

        {shown.length === 0 && (
          <p className="mt-8 text-meta text-muted">
            Nothing matches that. Clear the search or pick a different cause of death.
          </p>
        )}

        {/*
          FOOTER NOTE (email §7). The page used to put a "X of N" caveat in the hero and
          another, longer one at the foot. The hero carries the headline and the counts; this
          note carries the honest qualifier about what the table is a sample OF. The two-line
          form is what the email asks for, and it sits between the last row and the closing
          CTA so a reader who reaches the end still meets it.
        */}
        <p className="mt-10 max-w-[68ch] text-meta text-muted">
          This is a sample of the log, not all {killed.toLocaleString('en-GB')}. The rest were
          rejected on a low overall score, with no single finding behind it, so there would be
          nothing here for you to read. Every kill above names the check it failed and why.
        </p>

        <div className="mt-10 rounded-md border border-border bg-surface2 p-8 md:p-10">
          <h2 className="max-w-[26ch] text-h2 font-semibold text-text">
            Now read one that survived all of it.
          </h2>
          <p className="mt-3 max-w-[60ch] text-body text-muted">
            Same checks, same sourcing, opposite outcome. One full report is free to read, no card and
            no email.
          </p>
          {/* INSTRUMENTED 2026-08-15. The claim this page exists to test is "a reader who finds the
              kill log is likelier to buy", and it was untestable: `page_view` counts arrivals here
              but nothing counted departures TOWARDS the shelf, so the funnel had a denominator and
              no numerator.

              These are the two event names the allowlist already carries
              (`AnalyticsEndpoints.cs`), not new ones, because `track()` sends
              `window.location.pathname` with every beacon -- so a `catalog_cta_clicked` at
              `/kill-log` is already distinguishable from the same event fired on the home page. No
              schema change, no server deploy.

              What this canNOT answer, and no amount of client code here will: whether the SAME
              visitor later bought. `analytics.ts` deliberately stores nothing on the device (PECR
              reg 6(1)), so there is no per-visitor join, only page-level rates. Read it as "does
              the kill log route people to the shelf", never as "kill-log readers convert at X%". */}
          <div className="mt-6 flex flex-wrap items-center gap-3">
            <Link
              href="/sample"
              className={buttonClasses({ size: 'lg' })}
              onClick={() => track('sample_cta_clicked')}
            >
              Read a full report free
            </Link>
            {/* WAS "Browse the 145 that survived", which landed the reader on a smaller grid. The
                button now names the number it actually delivers, read live from /catalog, and
                falls back to no number at all if the catalogue is unreachable, rather than
                asserting a stale one. */}
            <Link
              href="/#catalog"
              className={buttonClasses({ variant: 'secondary', size: 'lg' })}
              onClick={() => track('catalog_cta_clicked')}
            >
              {listed ? `Browse the ${listed} on the shelf` : 'Browse the packs on the shelf'}
            </Link>
          </div>
        </div>

        <WaitlistCallout />
      </Section>
    </MarketingLayout>
  );
}

/**
 * The published-pack count has to be LIVE, but "live" does not mean "read on every request".
 *
 * `kill-log-totals.json` is a build-time snapshot, and listing a pack does not trigger a
 * redeploy, so any count baked into the FILE starts drifting the moment the engine publishes
 * again. This page previously printed the survivor count as if it were the shelf, which is the
 * same class of error with a bigger gap. Reading the catalogue is what the homepage already does.
 *
 * ISR, not `getServerSideProps` (measured 2026-08-14): this function has no per-request input at
 * all -- no `context` param, nothing from cookies/query/headers -- so every visitor was paying a
 * live round trip to the API for a single integer no visitor-specific fact depends on. 300s
 * revalidate means the count is at most 5 minutes stale after a publish, which is a fair trade
 * for turning every hit but one per window into a cache read. `fetchCatalogStats` (GET
 * /catalog/stats) replaces `fetchCatalog` for the same reason `pages/index.tsx` does not use it
 * here: this page only ever needed the COUNT, never the 59 packs' worth of fields the full
 * catalogue carries.
 *
 * Best-effort by design: a catalogue outage must not fail the build/revalidate for the page whose
 * subject is our own honesty. On failure `listed` is null and every surface that would name a
 * number omits it.
 */
export const getStaticProps: GetStaticProps<Props> = async () => {
  const stats = await fetchCatalogStats();
  // The corpus is read HERE and nowhere a component can see, which is what keeps 456 KB of JSON
  // out of the browser. What crosses is the summary of each kill (~50 KB, and all 400 rows stay in
  // the HTML because each one is a deep-link anchor); the arguments are fetched on demand from
  // /api/kill-log-detail.
  return { props: { listed: stats?.listed ?? null, ...buildKillIndex() }, revalidate: 300 };
};
