import React from 'react';
import Link from 'next/link';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Seo } from '@/components/Seo';
import { buttonClasses, chipClasses, Glyph, SearchInput, SourceChip, textLinkClass } from '@/components/ui';
import { Section, SectionBand } from '@/components/marketing/blocks';
import { WaitlistCallout } from '@/components/waitlist/WaitlistCallout';
import killLog from '@/data/kill-log.json';
import { tightDecimal } from '@/components/ui/Money';
import { RESEARCH_STATS } from '@/lib/stats';
import { fetchCatalogStats } from '@/lib/api/client';
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

type Citation = { url: string; domain: string };
type Entry = {
  title: string;
  oneLiner: string;
  gate: string;
  gateLabel: string;
  reason: string;
  citations: Citation[];
  date: string;
};

const entries = killLog.entries as Entry[];
/* Read through `RESEARCH_STATS`, not off the JSON. This page used to compute its rejection rate itself
   and then describe its denominator as `killed`, so the meta description shipped "We researched
   1168 business ideas" while /how-it-works said 1,313 from the identical file. `researched` is now
   an invariant (killed + survived) that no page can restate wrongly. See lib/stats.ts. */
const { killed, researched, rejectRateLabel } = RESEARCH_STATS;
// How many of the kills are published here, as opposed to how many happened. These are different
// numbers (400 vs 1,330) and the page has to be straight about which one it is showing.
const publishedKills = entries.length;
const withSource = entries.filter((e) => e.citations.length > 0).length;

/*
  A STABLE ANCHOR PER KILL.

  Every row is individually linkable, which is the whole reason to publish a dataset rather than an
  article: a single rejection is the thing a reader actually wants to send to someone ("they killed
  this exact idea, and here is why"). It is also the only SEO surface a page like this has, because
  400 records under one URL is one document to a crawler and 400 addressable claims to a reader.

  The slug is derived from the TITLE, not from the array index, so adding kills to the top of the
  log (which `make_kill_log.py` does on every run, newest first) cannot silently repoint a link
  someone already shared at a different idea. Collisions get a numeric suffix in encounter order,
  which is stable for the same reason.
*/
const slugCounts = new Map<string, number>();
function slugFor(title: string): string {
  const base =
    title
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 60) || 'kill';
  const seen = slugCounts.get(base) ?? 0;
  slugCounts.set(base, seen + 1);
  return seen === 0 ? base : `${base}-${seen + 1}`;
}
const rows = entries.map((entry) => ({ ...entry, slug: slugFor(entry.title) }));

// Every REASON present in what we publish, ordered by how many kills it accounts for, so the
// filter reads as a map of how ideas actually die rather than an alphabetical list.
//
// Grouped by `gateLabel`, not by `gate`. The engine has emitted two keys for one check --
// `distribution` and `route_to_market` -- and both carry the identical label "There is no route to
// reach buyers". Keyed by `gate`, the filter row rendered that sentence twice, side by side, with
// different counts (desktop-kill-log-fold.png, 2026-08-06): a reader clicking the first is told
// there are two such kills when there are three, and the second chip is indistinguishable from the
// first. The label is the right identity here because it is the claim being filtered on, the buyer
// is choosing a reason, not a database key.
const gateCounts = rows.reduce<Record<string, number>>((acc, e) => {
  acc[e.gateLabel] = (acc[e.gateLabel] ?? 0) + 1;
  return acc;
}, {});
const gates = Object.keys(gateCounts).sort((a, b) => gateCounts[b] - gateCounts[a]);

/*
  THE DISTRIBUTION, OVER ALL 1,330 KILLS AND NOT JUST THE PUBLISHED 400.

  This is the one chart on the site that answers "how do ideas actually die", and answering it from
  the published subset would be sampling bias baked into a picture: the subset deliberately EXCLUDES
  the three score-only gates, and those are the largest causes of death by a wide margin. A chart of
  the published rows would therefore show `incumbency` as the number one killer when the real number
  one is a composite score below the bar, which is a false claim rendered as a bar chart, and harder
  to argue with than a false sentence.

  So the chart plots the true totals and marks the bars whose kills carry no publishable argument.
  `make_kill_log.py` drops those because their reason reads "Composite 0.0000 below threshold 3.2",
  which is true and tells a reader nothing.
*/
const BY_GATE = (killLog.totals as { byGate: Record<string, number> }).byGate;
// Labels for the gates that never appear in a published row, so the chart can name every bar it
// draws. The published rows carry their own `gateLabel` from the engine.
const EXTRA_LABELS: Record<string, string> = {
  min_composite: 'Scored below the bar overall',
  moat_ungrounded: 'The defensibility claim was not evidence-backed',
  source_or_die: 'Its own claims could not be sourced',
  buyer_intent: 'No sign anyone is trying to buy it',
};
const LABEL_FOR: Record<string, string> = { ...EXTRA_LABELS };
rows.forEach((r) => {
  LABEL_FOR[r.gate] = r.gateLabel;
});
const PUBLISHED_GATES = new Set(rows.map((r) => r.gate));
// Grouped by label, same reason as `gateCounts` above: `BY_GATE` is keyed by the engine's internal
// gate, and the engine has emitted two keys -- `distribution` and `route_to_market` -- for the
// identical claim "There is no route to reach buyers". Built straight from `Object.entries(BY_GATE)`
// this chart drew two bars for that one claim (8 and 6, on both breakpoints) sitting side by side
// under the same label, which is the histogram equivalent of the filter-chip bug the comment above
// already fixed -- this aggregation just never got it. A reader comparing bar lengths was comparing
// a real cause against half of itself.
const distribution = Object.values(
  Object.entries(BY_GATE)
    .map(([gate, count]) => ({
      gate,
      count,
      label: LABEL_FOR[gate] ?? gate.replace(/_/g, ' '),
      published: PUBLISHED_GATES.has(gate),
    }))
    .reduce<Record<string, { gate: string; count: number; label: string; published: boolean }>>((acc, d) => {
      const existing = acc[d.label];
      if (existing) {
        existing.count += d.count;
        existing.published = existing.published || d.published;
      } else {
        acc[d.label] = { ...d };
      }
      return acc;
    }, {}),
).sort((a, b) => b.count - a.count);
const distributionMax = Math.max(...distribution.map((d) => d.count), 1);

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

export default function KillLogPage({ listed }: { listed: number | null }) {
  const [active, setActive] = React.useState<string | null>(null);
  const [search, setSearch] = React.useState('');
  const [sort, setSort] = React.useState<Sort>('newest');
  const [open, setOpen] = React.useState<Set<string>>(() => new Set());

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
    let items = active ? rows.filter((e) => e.gateLabel === active) : rows.slice();
    if (search.trim()) {
      const q = search.toLowerCase();
      items = items.filter(
        (e) =>
          e.title.toLowerCase().includes(q) ||
          e.oneLiner.toLowerCase().includes(q) ||
          e.reason.toLowerCase().includes(q),
      );
    }
    // Every sort falls back to date descending, so the order is total and a re-sort never
    // reshuffles rows that tie. Without the tiebreak, sorting by cause would return the ties in
    // whatever order the previous sort happened to leave them, which reads as the table jittering.
    const byDate = (a: Entry, b: Entry) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0);
    if (sort === 'cause') {
      items.sort((a, b) => {
        const d = gateCounts[b.gateLabel] - gateCounts[a.gateLabel];
        if (d !== 0) return d;
        const l = a.gateLabel.localeCompare(b.gateLabel);
        return l !== 0 ? l : byDate(a, b);
      });
    } else if (sort === 'sources') {
      items.sort((a, b) => b.citations.length - a.citations.length || byDate(a, b));
    } else {
      items.sort(byDate);
    }
    return items;
  }, [active, search, sort]);

  const toggle = (slug: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(slug)) next.delete(slug);
      else next.add(slug);
      return next;
    });

  return (
    <MarketingLayout>
      <Seo
        title="The kill log, the ideas we killed, and the sourced reason why"
        description={`We researched ${researched.toLocaleString('en-GB')} business ideas and killed ${rejectRateLabel} of them. Here are ${publishedKills} of the kills, each with the evidence that killed it.`}
      />

      {/* Left-aligned, one column, no centred hero (spec §7.4). A centred 22ch headline over a
          centred 62ch paragraph over a centred stat row gives the reader three different left
          edges to find in the first screen of a page that is otherwise a table. */}
      <SectionBand bg="white" width="6xl" className="pt-14 pb-8 md:pt-20 md:pb-10">
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
            Anyone can claim rigour. This is the receipt: every rejected idea, the argument that
            killed it, and the sources so you can check it yourself.
          </p>
          {/* THE CAVEAT, AT THE TOP.
              It used to sit below all the entries, under a homepage line promising the log "has
              every one". A reader met an implied 1,330-row page, scrolled, and only then learned
              what they were actually looking at. On the one page whose job is to prove we do not
              overclaim, the correction has to arrive before the claim it corrects. */}
          <p className="mt-4 max-w-[68ch] text-meta text-muted">
            This page publishes {publishedKills} of those kills, not all {killed.toLocaleString('en-GB')}.
            Kills whose only reason was a score below the bar are left out. They&rsquo;re true, but
            they tell you nothing. What you see here is the kills that came with an argument,
            {` ${withSource}`} of them carrying a source you can open.
          </p>
          {/* Mono: both are counts, and the pair is the one place on the site where the rejection
              rate is stated as a measured quantity rather than a boast. */}
          <div className="mt-6 flex flex-wrap items-center gap-x-6 gap-y-2 font-mono text-meta">
            {/* §3.3: the killed square, not a warning triangle. A triangle is a caution sign --
                it tells the reader to be careful about something ahead. A kill is not a hazard,
                it is a finished ruling, and the crossed square is the mark the rest of the site
                uses for one. */}
            <span className="inline-flex items-center gap-2 text-kill">
              <Glyph name="killed" />
              {rejectRateLabel} killed
            </span>
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
              return (
                /* One <tbody> per record, so the summary row and its detail row are one group to
                   assistive tech rather than two unrelated rows that happen to be adjacent. */
                <tbody key={entry.slug} id={entry.slug} className="scroll-mt-24 border-b border-border align-baseline">
                  <tr
                    className="cursor-pointer transition-colors hover:bg-surface3"
                    onClick={() => toggle(entry.slug)}
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
                          toggle(entry.slug);
                        }}
                        className="text-left font-mono text-caption leading-snug text-muted line-through decoration-kill/60 hover:text-text"
                      >
                        {entry.title}
                      </button>
                    </td>
                    <td className="py-2.5 pr-4 font-mono text-caption text-kill-strong">
                      {entry.gateLabel}
                    </td>
                    <td className="py-2.5 pr-4 text-right font-mono text-caption tabular-nums text-subtle">
                      {/* A literal 0, not a blank or a placeholder glyph. This column is
                          sortable, so an empty cell would read as missing data in a table that is
                          about evidence; 0 is the actual, stated fact. */}
                      {entry.citations.length}
                    </td>
                    <td className="py-2.5 text-right font-mono text-caption tabular-nums text-subtle">
                      {formatDate(entry.date)}
                    </td>
                  </tr>
                  {isOpen && (
                    <tr>
                      <td colSpan={4} className="bg-surface3 px-3 py-4">
                        {entry.oneLiner && (
                          <p className="max-w-[80ch] text-meta text-muted">{entry.oneLiner}</p>
                        )}
                        <p className="mt-3 max-w-[80ch] text-meta text-text">{entry.reason}</p>
                        <div className="mt-3 flex flex-wrap items-center gap-2">
                          {/* Kills with no resolvable source are BADGED, not left blank. The page
                              promises "the sourced reason why", so an entry with nothing to link
                              was silently indistinguishable from one whose sources we simply had
                              not shown. `make_kill_log.py` drops references it cannot resolve to a
                              real URL rather than rendering a dead hash, which is why these are
                              empty. */}
                          {entry.citations.length === 0 && (
                            <span className="inline-flex items-center gap-1 rounded-md border border-dashed border-border px-1.5 py-0.5 font-mono text-caption text-subtle">
                              argument recorded, no source published
                            </span>
                          )}
                          {/* Was a byte-for-byte copy of `CitationChip`'s markup, pasted here. It
                              is the sixth such copy the source-chip consolidation found, and the
                              only one an agent survey of the tree missed -- `sourceChipIsTheOnlyOne`
                              caught it on its first run. */}
                          {entry.citations.map((c, j) => (
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
          This is a sample of the log, not all {killed.toLocaleString('en-GB')}. Kills whose only
          reason was a low score are left out, true, but they tell you nothing. Every kill here
          came with an argument.
        </p>

        <div className="mt-10 rounded-md border border-border bg-surface2 p-8 md:p-10">
          <h2 className="max-w-[26ch] text-h2 font-semibold text-text">
            Now read one that survived all of it.
          </h2>
          <p className="mt-3 max-w-[60ch] text-body text-muted">
            Same checks, same sourcing, opposite outcome. One full report is free to read, no card and
            no email.
          </p>
          <div className="mt-6 flex flex-wrap items-center gap-3">
            <Link href="/sample" className={buttonClasses({ size: 'lg' })}>
              Read a full report free
            </Link>
            {/* WAS "Browse the 145 that survived", which landed the reader on a smaller grid. The
                button now names the number it actually delivers, read live from /catalog, and
                falls back to no number at all if the catalogue is unreachable, rather than
                asserting a stale one. */}
            <Link href="/#catalog" className={buttonClasses({ variant: 'secondary', size: 'lg' })}>
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
export const getStaticProps: GetStaticProps = async () => {
  const stats = await fetchCatalogStats();
  return { props: { listed: stats?.listed ?? null }, revalidate: 300 };
};
