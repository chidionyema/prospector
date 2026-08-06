import React from 'react';
import Link from 'next/link';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Seo } from '@/components/Seo';
import { buttonClasses, chipClasses, Icon, SearchInput } from '@/components/ui';
import { Section, SectionBand } from '@/components/marketing/blocks';
import { WaitlistCallout } from '@/components/waitlist/WaitlistCallout';
import killLog from '@/data/kill-log.json';
import { RESEARCH_STATS, survivorsSummary } from '@/lib/stats';
import { fetchCatalog } from '@/lib/api/client';
import type { GetServerSideProps } from 'next';

/*
  The rejects, published.

  A visitor is asked for £49 on the strength of "these survived a filter built to kill them" and has no
  way to see the brutality. The conventional fix is testimonials, which we cannot honestly
  show, there are no reviews to quote, and inventing one is both a lie and an offence under
  the DMCCA 2024 fake-review rules. On a storefront whose entire pitch is source-or-die it
  would also be self-refuting: a reader who checks one claim, finds it fabricated, and then
  disbelieves the other forty-three has reasoned correctly.

  So we show the thing we already own and never showed anyone. 960 ideas researched and shot
  to put 103 on the shelf. Each entry below is a real rejection with the argument that killed
  it and, where the engine cited a page, a link to that page. It is checkable, which is the
  one property a testimonial can never have.

  Data comes from tools/make_kill_log.py, which reads the same dossiers the engine writes.
  It excludes kills whose reason is bookkeeping rather than an argument. See that file.
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
/* Read through `RESEARCH_STATS`, not off the JSON. This page used to compute `rejectRate` itself
   and then describe its denominator as `killed`, so the meta description shipped "We researched
   1168 business ideas" while /how-it-works said 1,313 from the identical file. `researched` is now
   an invariant (killed + survived) that no page can restate wrongly. See lib/stats.ts. */
const { killed, researched, rejectRate } = RESEARCH_STATS;
// How many of the kills are published here, as opposed to how many happened. These are wildly
// different numbers (60 vs 1,243) and the page has to be straight about which one it is showing.
const publishedKills = entries.length;

// Every REASON present in what we publish, ordered by how many kills it accounts for, so the
// filter reads as a map of how ideas actually die rather than an alphabetical list.
//
// Grouped by `gateLabel`, not by `gate`. The engine has emitted two keys for one check --
// `distribution` (2 entries) and `route_to_market` (1) -- and both carry the identical label
// "There is no route to reach buyers". Keyed by `gate`, the filter row rendered that sentence
// twice, side by side, with counts 2 and 1 (desktop-kill-log-fold.png, 2026-08-06): a reader
// clicking the first one is told there are two such kills when there are three, and the second
// chip is indistinguishable from the first.
//
// The label is the right identity here because it is the claim being filtered on -- the buyer is
// choosing a reason, not a database key. Reproduce the duplication with:
//   python3 -c "import json,collections;d=json.load(open('src/data/kill-log.json'));\
//   print(collections.Counter((e['gate'],e['gateLabel']) for e in d['entries']))"
// Fixing the engine to emit one key is the real repair; this stops the storefront lying meanwhile.
const gateCounts = entries.reduce<Record<string, number>>((acc, e) => {
  acc[e.gateLabel] = (acc[e.gateLabel] ?? 0) + 1;
  return acc;
}, {});
const gates = Object.keys(gateCounts).sort((a, b) => gateCounts[b] - gateCounts[a]);

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
  const shown = React.useMemo(() => {
    // `active` holds a gateLabel, matching how the chips above are keyed.
    let items = active ? entries.filter((e) => e.gateLabel === active) : entries;
    if (search.trim()) {
      const q = search.toLowerCase();
      items = items.filter(
        (e) =>
          e.title.toLowerCase().includes(q) ||
          e.oneLiner.toLowerCase().includes(q) ||
          e.reason.toLowerCase().includes(q),
      );
    }
    return items;
  }, [active, search]);

  return (
    <MarketingLayout>
      <Seo
        title="The kill log, the ideas we rejected, and the sourced reason why"
        description={`We researched ${researched.toLocaleString('en-GB')} business ideas and rejected ${rejectRate}% of them. Here are ${publishedKills} of the rejects, with the evidence that killed each one.`}
      />

      {/* Left-aligned, one column, no centred hero (spec §7.4). A centred 22ch headline over a
          centred 62ch paragraph over a centred stat row gives the reader three different left
          edges to find in the first screen of a page that is otherwise a list. */}
      <SectionBand bg="white" width="6xl" className="pt-14 pb-8 md:pt-20 md:pb-10">
        <div className="max-w-3xl">
          <p className="text-caption font-medium text-subtle">The kill log</p>
          {/* WAS "We killed 1,168 ideas to put 145 on the shelf." Two false claims in one line:
              145 is the number that SURVIVED, and the shelf holds 63 of them, so the sentence
              overstated the catalogue by 82 packs and sent anyone who counted straight to the
              contradiction. The survivor count and the published count are different facts and
              this page states both. */}
          <h1 className="mt-3 text-h1 font-semibold text-text md:text-display">
            We killed {killed.toLocaleString('en-GB')} ideas out of {researched.toLocaleString('en-GB')}.
          </h1>
          <p className="mt-5 max-w-[60ch] text-body text-muted">
            Anyone can claim their research is rigorous. This is the receipt. Every idea below was
            generated, researched against live sources, and then shot, with the argument that
            killed it and, where a page was cited, a link so you can check it yourself.
          </p>
          {/* THE CAVEAT, AT THE TOP.
              It used to sit in a paragraph below all 60 entries, under a homepage line promising
              the log "has every one". A reader met an implied 1,168-row page, scrolled 60 rows,
              and only then learned what they were actually looking at. On the one page whose job
              is to prove we do not overclaim, the correction has to arrive before the claim it
              corrects, not after the scroll. */}
          <p className="mt-4 max-w-[68ch] text-meta text-muted">
            This page publishes {publishedKills} of those kills, not all {killed.toLocaleString('en-GB')}.
            Rejections whose only reason was a score below the bar are left out, they are true and
            they tell you nothing. What you see here is every kill that came with an argument.
          </p>
          {/* Mono: both are counts, and the pair is the one place on the site where the rejection
              rate is stated as a measured quantity rather than a boast. */}
          <div className="mt-6 flex flex-wrap items-center gap-x-6 gap-y-2 font-mono text-meta">
            <span className="inline-flex items-center gap-2 text-danger">
              <Icon name="warning" size={14} />
              {rejectRate}% rejected
            </span>
            {/* "published" was the wrong noun on the survivor count: 145 survived, 63 are on the
                shelf. `survivorsSummary` states the gap rather than printing whichever of the two
                numbers happens to flatter the page. */}
            <span className="inline-flex items-center gap-2 text-success">
              <Icon name="check" size={14} />
              {survivorsSummary(listed ?? undefined)}
            </span>
          </div>
        </div>
      </SectionBand>

      <Section bg="bg" width="6xl" className="!pt-6 !pb-24">
        {/* Search + filter pills */}
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
            {/* "All 60" directly under a headline saying 1,168 read as a contradiction. It is all
                of what is PUBLISHED, and the chip now says which. */}
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

        <ul className="mt-8 list-none space-y-4 p-0">
          {shown.map((entry, i) => (
            <li
              key={`${entry.title}-${i}`}
              className="rounded-md border border-border bg-surface p-5 md:p-6"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  {/* Struck through because that is exactly what happened to it. Danger, not
                      warning: --warning means "proceed with care", and these did not proceed. */}
                  <h2 className="text-body font-semibold leading-snug text-muted line-through decoration-danger/60 decoration-2">
                    {entry.title}
                  </h2>
                  {entry.oneLiner && (
                    <p className="mt-2 max-w-[70ch] text-meta text-muted">{entry.oneLiner}</p>
                  )}
                </div>
                <span className="inline-flex flex-none items-center gap-1.5 rounded-full border border-danger/25 bg-danger-bg px-2.5 py-0.5 font-mono text-caption text-danger-strong">
                  KILLED
                </span>
              </div>

              <div className="mt-4 border-t border-border pt-4">
                {/* The gate that fired, in the data voice: it is the machine-readable reason, and
                    it is the field a reader would quote back at us. */}
                <p className="font-mono text-caption text-danger-strong">{entry.gateLabel}</p>
                <p className="mt-2 max-w-[72ch] text-meta text-muted">{entry.reason}</p>
              </div>

              {(entry.citations.length > 0 || entry.date) && (
                <div className="mt-4 flex flex-wrap items-center gap-2">
                  {/* 23 of the 60 published kills carry no resolvable source (measured
                      2026-08-06 against src/data/kill-log.json). The page promises "the sourced
                      reason why", so an entry with nothing to link was silently indistinguishable
                      from one whose sources we simply had not shown. Badging it is the honest
                      option: the argument is real and recorded, the citation is not published.
                      `make_kill_log.py` drops references it cannot resolve to a real URL rather
                      than rendering a dead hash, which is why these are empty. */}
                  {entry.citations.length === 0 && (
                    <span className="inline-flex items-center gap-1 rounded-md border border-dashed border-border px-1.5 py-0.5 font-mono text-caption text-subtle">
                      argument recorded, no source published
                    </span>
                  )}
                  {entry.citations.map((c, j) => (
                    <a
                      key={j}
                      href={c.url}
                      target="_blank"
                      rel="noopener noreferrer nofollow"
                      className="inline-flex max-w-full items-center gap-1 rounded-md border border-border bg-surface px-1.5 py-0.5 font-mono text-caption text-muted transition-colors duration-[120ms] hover:border-border-strong hover:text-text"
                    >
                      <Icon name="arrowRight" size={10} className="-rotate-45 shrink-0" />
                      <span className="truncate">{c.domain}</span>
                    </a>
                  ))}
                  {entry.date && (
                    <span className="ml-auto font-mono text-caption text-subtle">{formatDate(entry.date)}</span>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>

        {/* The "this is a sample" caveat that used to live here now runs directly under the H1.
            A reader has to know what they are looking at before they read 60 entries, not after.
            Do not re-add it here: one statement, at the top, is the whole point. */}

        <div className="mt-10 rounded-md border border-border bg-surface2 p-8 md:p-10">
          <h2 className="max-w-[26ch] text-h2 font-semibold text-text">
            Now read one that survived all of it.
          </h2>
          <p className="mt-3 max-w-[60ch] text-body text-muted">
            Same checks, same sourcing, opposite outcome. One full pack is free to read, no card and
            no email.
          </p>
          <div className="mt-6 flex flex-wrap items-center gap-3">
            <Link href="/sample" className={buttonClasses({ size: 'lg' })}>
              Read a full pack free
            </Link>
            {/* WAS "Browse the 145 that survived", which landed the reader on a grid of 63. The
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
 * The published-pack count has to be LIVE.
 *
 * `kill-log-totals.json` is a build-time snapshot, and listing a pack does not trigger a
 * redeploy, so any count baked into this page starts drifting the moment the engine publishes
 * again. This page previously printed the survivor count (145) as if it were the shelf, which is
 * the same class of error with a bigger gap. Reading `/catalog` at request time is what the
 * homepage already does.
 *
 * Best-effort by design: a catalogue outage must not 500 the page whose subject is our own
 * honesty. On failure `listed` is null and every surface that would name a number omits it.
 */
export const getServerSideProps: GetServerSideProps = async () => {
  try {
    const packs = await fetchCatalog();
    return { props: { listed: Array.isArray(packs) ? packs.length : null } };
  } catch {
    return { props: { listed: null } };
  }
};
