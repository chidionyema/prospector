import React from 'react';
import Link from 'next/link';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Seo } from '@/components/Seo';
import { Glyph, SearchInput, SourceChip, VerdictChip, textLinkClass } from '@/components/ui';
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
/* Rows printed before the reader asks for more. Declared, not implied, so the number is one edit
   and the shelf's own SHELF_PAGE has a sibling to be compared against. */
const KILL_PAGE = 40;

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
  /* THE PAGE IS 400 RECORDS AND IT PRINTED ALL OF THEM (2026-08-18). Measured at 40,440px against
     the drawing's 5,203 -- eight times the page, and every row's detail markup in the HTML before
     a reader has asked for one. `mockups/kill-log.html` shows a screen of rows and a control. */
  const [limit, setLimit] = React.useState(KILL_PAGE);
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

  /* Sliced AFTER the filter and the sort, so a search still reaches every record and the reader
     sees the best matches rather than the first page's matches. */
  const visible = React.useMemo(() => shown.slice(0, limit), [shown, limit]);

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
          odd on desktop"). Same diagnosis as /ideas and /how-it-works -- a 3xl measure inside a 6xl
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
        {/* THE RIGHT COLUMN WAS TOO NARROW TO READ. At `max-w-6xl` with `lg:px-10` the content box
            is 1072px; a 46rem left column and a 4rem gap left the caveat 272px, so a 40-word
            paragraph became a tall strip jammed against the container's right edge (founder,
            2026-08-16: "content is squashed against container esp on the right"). Narrowing the
            left column to 40rem and closing the gap to 3rem gives the caveat 384px, which is about
            38 characters a line instead of 27. */}
        <div className="grid gap-10 lg:grid-cols-[minmax(0,40rem)_minmax(0,1fr)] lg:items-start lg:gap-12">
        <div className="pagetop max-w-3xl">
          <p className="eyebrow">The kill log</p>
          {/* THE HERO: ONE COUNT. It read "1,364 killed. 80 survived.", and the second half was
              the figure the founder cut on 2026-08-13, because the shelf this page links to holds
              50. The live shelf count is not promoted into the headline to replace it: it is
              already in the chip row 200px below, and printing one number twice in one block is
              the defect this page has fixed twice before ("61 live now" / "60 live now"). The
              count carries the page on its own, and the caveat four lines down is what qualifies
              it. Nothing here promises a reason for all 1,364: only 400 came with an argument, and
              that sentence is already in the caveat rather than contradicted by this headline. */}
          <h1 className="mt-3">
            {killed.toLocaleString('en-GB')} ideas killed.
          </h1>
          <p className="lede big mt-5">
            Most ideas do not survive. Here is what we rejected, the reason each one failed, and
            the sources, so you can check the reasoning yourself.
          </p>
          {/* THE DRAWING'S `.facts` PANEL (`mockups/kill-log.html`): three bordered cells across
              the measure, each a mono uppercase label over a 24px figure. It was a `.metastrip` of
              verdict chips, which is the drawing's device for the SAMPLE page's offer terms, not
              for this page's counts, and it printed only two of the three numbers.

              THE GLYPHS STAY. `.facts span` is a label, not a chip, so the VerdictChip form does
              not fit here -- but MASTER-BRIEF §6 says colour is never the sole carrier, so the
              killed and survived glyphs sit inline in the label beside the word. The shapes differ
              (crossed, filled), so the panel still reads printed in one ink.

              "Published here" is new, and it is the number this hero was missing: the caveat
              beside it explains that this page holds a subset, and the panel now states the
              subset as a figure rather than leaving it to the prose. */}
          {/* `.facts span` and `.facts b` are what the drawing's stylesheet actually selects, so
              the label and the figure are a span and a b inside the dt/dd, exactly as
              how-it-works.tsx:212 already does it. A dt with the classes on itself draws nothing. */}
          <dl className="facts">
            <div>
              <dt>
                <span className="inline-flex items-center gap-1.5">
                  <Glyph name="killed" className="text-kill" />
                  Killed
                </span>
              </dt>
              <dd><b className="num">{rejectRateLabel}</b></dd>
            </div>
            <div>
              <dt><span>Published here</span></dt>
              <dd><b className="num">{publishedKills}</b></dd>
            </div>
            {listed ? (
              <div>
                <dt>
                  <span className="inline-flex items-center gap-1.5">
                    <Glyph name="survived" className="text-survive" />
                    Available now
                  </span>
                </dt>
                <dd><b className="num">{listed.toLocaleString('en-GB')}</b></dd>
              </div>
            ) : null}
          </dl>
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
          <p className="eyebrow">What this page publishes</p>
          <p className="mt-4 border-l border-border pl-4 lede">
            This page publishes {publishedKills} of those kills, not all {killed.toLocaleString('en-GB')}.
            The rest were rejected on a low overall score, with no single finding behind it, so
            there would be nothing here for you to read. Every kill below names the check it
            failed and why, and{` ${withSource}`} of them link the source.
          </p>
        </aside>
        </div>
      </SectionBand>

      <Section bg="bg" width="6xl" className="!pt-6 !pb-24">
        {/* THE DRAWING'S SECTION SEPARATORS (`mockups/kill-log.html`, two `hr.rule2`): a 2px ink
            rule above "How ideas die" and above the table. `!mt-0` because `.rule2` carries a 44px
            top margin for the drawing's flat page, and here the band's own padding is that gap. */}
        <hr className="rule2 !mt-0 mb-7" />
        {/* ── HOW IDEAS DIE ─────────────────────────────────────────────────────────────────────
            The chart is the page's thesis in one object, and it is placed above the table because
            it is what makes the table legible: a reader who knows incumbency is the largest
            publishable cause reads 188 incumbency rows as a pattern rather than as repetition. */}
        <section aria-labelledby="distribution-heading" className="rounded-card border border-border bg-surface p-6 md:p-7">
          <h2 id="distribution-heading" className="sec">
            How ideas die
          </h2>
          <p className="mt-2 max-w-[68ch] lede">
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
          <p className="mt-2 max-w-[68ch] lede">
            Causes marked <span className="mono">stage</span> are
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
          {/* THE DRAWING'S `.bars` AND `.barline` (`mockups/kill-log.html:137-143`): a two-column
              grid, the label and its 9px track on the left, the count in mono at 48px on the
              right. Every one of those numbers was a Tailwind utility here, so the page emitted
              none of the classes the mockup styles.

              THE LABEL STILL WRAPS ON A PHONE, and that is not the drawing. `.barline .lab` sets
              `white-space:nowrap` with an ellipsis at 52%, and measured at 390px on 2026-08-13
              that rendered "The defensibility claim was not evidence-b...". Truncating the CAUSE
              of a rejection is the one thing this chart cannot do: the label IS the finding. The
              utilities below `sm` turn the wrap back on, and they win over the class because
              mumchimp.css is imported into `layer(components)` and utilities sit above it. */}
          {/* `h-auto items-stretch` OVERRIDES THE SHIPPED STYLESHEET, AND THE STYLESHEET IS
              WRONG HERE. `mumchimp.css:103` reads
              `.bars{display:flex;flex-direction:column;align-items:flex-end;height:44px}`.
              That rule is written for a DIFFERENT component: the 44px sparkline of vertical
              bars on the home page (`mockups/index.html:629`, styled by `.bars i` at
              `mumchimp.css:356`). `mockups/kill-log.html:475` reuses the same class name for
              this ranked horizontal chart, so one name carries two components and the
              sparkline's rule lands on the chart.

              THE DRAWING BREAKS ON ITSELF, measured 2026-08-18 at 1280: its twelve rows run
              y=1638..1932, 294px of content in a box declared 44px tall, and every row is
              shrink-wrapped and pushed right (x=866, 823, 728, 753, ...) so no two labels or
              counts share a baseline. Ours did the same with thirteen rows, and they rendered
              on top of the search box and the chip rail below (founder, 2026-08-18: "layout
              badly broken").

              `h-auto` gives the list the height of its rows. `items-stretch` makes each row
              span the full width, which is what `.barline{grid-template-columns:1fr 48px}`
              was written for: labels on one left baseline, counts on one right baseline, and
              bars that are comparable because they start in the same place. Utilities win over
              `mumchimp.css` because it is imported into `layer(components)` (globals.css:8),
              so no `!important` is needed and the stylesheet stays shipped verbatim.
              `killLogBars.test.ts` pins both overrides. */}
          <ul className="bars h-auto items-stretch">
            {distribution.map((d) => (
              <li key={d.gate} className="barline">
                <span className="t max-sm:flex-col max-sm:items-start max-sm:gap-2">
                  <span
                    className="lab max-sm:max-w-none max-sm:whitespace-normal"
                    title={d.label}
                  >
                    {d.label}
                    {d.isStage && <span className="ml-1.5 text-subtle"> stage</span>}
                  </span>
                  {/* The bar is drawn against the LARGEST cause, not against the total. Against the
                      total every bar but one is a sliver and the chart shows nothing; against the
                      max, the comparison the reader came for is the one the picture makes. */}
                  <span className="bar max-sm:w-full">
                    <i
                      /* NEUTRAL BOTH WAYS (2026-08-14 colour audit, finding 2). These bars were
                         `bg-kill` when published and grey when not, on the one page that defines
                         red as "killed" -- so red here encoded PUBLICATION STATUS, and the
                         largest cause of death on the chart (624) was drawn in decoration grey
                         because nothing was published under it. A reader taking the page at its
                         word read the ranking backwards. Ink weight now carries "listed below"
                         and red goes back to meaning exactly one thing. The drawing paints
                         `.barline .bar i` in `--kill`; this overrides it for that reason. */
                      /* `max-w-none` UNDOES THE SPARKLINE CAP. `mumchimp.css:356` is
                         `.bars i{flex:1;max-width:26px;...}` -- the home page sparkline again,
                         selecting by descendant, so it also matches the fill inside
                         `.barline .bar i` here. Measured 2026-08-18 at 1280 before this line:
                         the 624 bar computed `width:100%` on a 665px track and RENDERED 26px,
                         and so did 203, 191, 142, 83 and 26. Every cause above about 4% drew
                         the same 26px stub, so the chart showed a ranking it did not have.
                         The class is written out twice rather than composed, because Tailwind
                         v4 only generates a rule for text it can find in this file. */
                      className={d.published ? 'max-w-none bg-text' : 'max-w-none bg-subtle/35'}
                      style={{ width: `${Math.max((d.count / distributionMax) * 100, 0.6)}%` }}
                    />
                  </span>
                </span>
                <span className="n num">
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
        <hr className="rule2 mb-7" />
        <div>
          <SearchInput
            label="Search kills by title, description, or reason"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search kills by title, description, or reason…"
            className="mb-4"
          />
          {/* THE DARK FILTER STRIP (`mumchimp.css:252-258`). These were pale `.chip` pills on
              paper, which read as the same control as the Sort row below them and disappeared
              into the page on a phone. The strip is `.strip.filterstrip > .strip-in`, it sticks
              to the top of the viewport while the table scrolls, and its own `overflow-x:auto`
              is what lets a long gate list scroll instead of widening the page. The count is a
              `.n` inside the chip, not part of its label. */}
          <div className="strip filterstrip">
            <div className="strip-in flex-wrap">
              <button
                type="button"
                onClick={() => setActive(null)}
                aria-pressed={active === null}
                className="dchip"
              >
                {/* "All 400" directly under a headline saying 1,330 read as a contradiction. It is
                    all of what is PUBLISHED, and the chip now says which. */}
                All published <span className="n num">{publishedKills}</span>
              </button>
              {gates.map((label) => (
                <button
                  key={label}
                  type="button"
                  onClick={() => setActive(label === active ? null : label)}
                  aria-pressed={label === active}
                  className="dchip"
                >
                  {label} <span className="n num">{gateCounts[label]}</span>
                </button>
              ))}
            </div>
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
                  className="chip"
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
          {/* THE DRAWING'S `.rows` CARD OF `.klrow` RECORDS (`mockups/kill-log.html:150-158`).
              This was a real `<table>` with four column headers. The drawing has no headers and no
              columns: each record is a card of title, the argument, a mono meta line, and a `.side`
              column carrying the verdict and the gate. Nothing sortable was lost with the `<thead>`
              -- the sort is its own control above -- and the per-record `id`, the expand button and
              the argument panel all survive.
              At 700px the drawing collapses `.klrow` to one column and moves `.side` to the top,
              which is why no responsive utilities are written here: the class already does it. */}
          <ul
            className="rows list-none p-0"
            aria-label="Killed ideas, with the check that killed each one, its published sources and the date it was assessed. Select a row to read the argument."
          >
            {visible.map((entry) => {
              const isOpen = open.has(entry.slug);
              const detail = details?.[entry.slug];
              return (
                /* One `<li>` per record, so the summary and its argument panel are one group to
                   assistive tech rather than two unrelated rows that happen to be adjacent. */
                /* The row's `onClick` is mouse sugar and nothing else: the `<button>` below is the
                   real control, it is in the tab order, it carries `aria-expanded`, and it does
                   the same `toggle`. Adding a key handler here would put a second stop in the tab
                   order for an action the button already offers, which is worse for a keyboard
                   user, not better. Same call, same two rules, as `ui/Dropdown.tsx:152`. */
                /* eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-noninteractive-element-interactions -- the nested <button> is the accessible control for this action */
                <li
                  key={entry.slug}
                  id={entry.slug}
                  className="klrow scroll-mt-24 cursor-pointer"
                  onClick={() => toggle(entry.slug, entry.gateLabel)}
                >
                    <h3>
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
                        /* `.klrow h4` owns the size, weight and leading. The mono/caption/muted
                           utilities that used to set them here are removed rather than layered:
                           mumchimp.css sits in `layer(components)` (globals.css:8), under the
                           utilities, so leaving one in place makes the class inert. NO
                           STRIKE-THROUGH: it is not in the drawing, it reads as a price
                           correction rather than a verdict, and the row already says the idea
                           was killed and on which gate. */
                        className="text-left"
                      >
                        {entry.title}
                      </button>
                    </h3>
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
                      {!isOpen && entry.excerpt && <p>{entry.excerpt}</p>}
                      {/* The mono meta line. A literal 0 for the sources, never a blank or a
                          placeholder glyph: this page is about evidence, and 0 is the actual
                          stated fact. */}
                      {/* `m num`, both classes, as the drawing writes it
                          (`mockups/kill-log.html`, `.klrow > p.m.num`). `.m` is the mono meta
                          line; `num` is the tabular-figures class every counted line on the site
                          carries, and this line is a date and a count. */}
                      <p className="m num">
                        {formatDate(entry.date)} &middot; {entry.sources}{' '}
                        {entry.sources === 1 ? 'source' : 'sources'}
                      </p>
                      <span className="side">
                        <VerdictChip kind="killed" />
                        <span className="mono num">
                          {entry.gateLabel}
                          {isStageLabel(entry.gateLabel) && <span className="text-subtle"> stage</span>}
                        </span>
                      </span>
                  {isOpen && (
                    <div className="mt-3 rounded-ctl bg-surface3 px-3 py-4 [grid-column:1/-1]">
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
                          <p className="max-w-[80ch] lede">{detail.oneLiner}</p>
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
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </div>

        {visible.length < shown.length && (
          <div className="more-row">
            <button type="button" className="more" onClick={() => setLimit((n) => n + KILL_PAGE)}>
              Show {Math.min(KILL_PAGE, shown.length - visible.length)} more of{' '}
              {shown.length.toLocaleString('en-GB')}
            </button>
          </div>
        )}

        {shown.length === 0 && (
          <p className="mt-8 lede">
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
        <p className="mt-10 max-w-[68ch] lede">
          This is a sample of the log, not all {killed.toLocaleString('en-GB')}. The rest were
          rejected on a low overall score, with no single finding behind it, so there would be
          nothing here for you to read. Every kill above names the check it failed and why.
        </p>

        {/* THE CLOSING BLOCK (`mockups/kill-log.html`, `.closing`): a 2px rule in ink across the
            full measure, then the offer. It was a filled card with a border. The drawing uses the
            rule everywhere a page ends, and a filled panel here reads as one more module rather
            than the end of the page. */}
        <div className="closing">
          <h2 className="max-w-[26ch] sec">
            Now read one that survived all of it.
          </h2>
          <p>
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
          <div className="ctarow">
            <Link
              href="/sample"
              className="btn"
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
              className="btn ghost"
              onClick={() => track('catalog_cta_clicked')}
            >
              {listed ? `Browse the ${listed} available now` : 'Browse the packs available now'}
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
