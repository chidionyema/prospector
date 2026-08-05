import React from 'react';
import Link from 'next/link';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Seo } from '@/components/Seo';
import { Icon } from '@/components/ui';
import { cx } from '@/components/ui/cx';
import { Section, SectionBand } from '@/components/marketing/blocks';
import { WaitlistCallout } from '@/components/waitlist/WaitlistCallout';
import killLog from '@/data/kill-log.json';

/*
  The rejects, published.

  A visitor is asked for £49 on the strength of "these survived six brutal checks" and has no
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
const { killed, passed } = killLog.totals;
const rejectRate = Math.round((killed / (killed + passed)) * 100);

// Every gate present in what we publish, ordered by how many kills it accounts for, so the
// filter reads as a map of how ideas actually die rather than an alphabetical list.
const gateCounts = entries.reduce<Record<string, number>>((acc, e) => {
  acc[e.gate] = (acc[e.gate] ?? 0) + 1;
  return acc;
}, {});
const gates = Object.keys(gateCounts).sort((a, b) => gateCounts[b] - gateCounts[a]);
const gateLabel = (gate: string) => entries.find((e) => e.gate === gate)?.gateLabel ?? gate;

function formatDate(iso: string) {
  if (!iso) return '';
  const d = new Date(`${iso}T00:00:00Z`);
  return Number.isNaN(d.getTime())
    ? ''
    : d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
}

export default function KillLogPage() {
  const [active, setActive] = React.useState<string | null>(null);
  const [search, setSearch] = React.useState('');
  const shown = React.useMemo(() => {
    let items = active ? entries.filter((e) => e.gate === active) : entries;
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
        description={`We researched ${killed} business ideas and rejected ${rejectRate}% of them. Here are the rejects, with the evidence that killed each one.`}
      />

      <SectionBand bg="white" width="6xl" className="pt-14 pb-8 md:pt-20 md:pb-10 text-center">
    <p className="mb-4 text-caption font-bold uppercase tracking-[0.2em] text-muted">
          The kill log
        </p>
        <h1 className="mx-auto max-w-[22ch] text-balance text-h1 font-bold leading-[1.08] tracking-tight text-text md:text-display">
          We killed {killed.toLocaleString('en-GB')} ideas to put {passed} on the shelf.
        </h1>
        <p className="mx-auto mt-6 max-w-[62ch] text-body leading-relaxed text-text/75 md:text-body">
          Anyone can claim their research is rigorous. This is the receipt. Every idea below was
          generated, researched against live sources, and then shot, with the argument that
          killed it and, where a page was cited, a link so you can check it yourself.
        </p>
        <div className="mx-auto mt-7 flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-meta font-semibold text-muted">
          <span className="inline-flex items-center gap-2">
            <Icon name="shield" size={14} className="text-warning" />
            {rejectRate}% rejected
          </span>
          <span className="inline-flex items-center gap-2">
            <Icon name="check" size={14} className="text-success" />
            {passed} survived and published
          </span>
        </div>
      </SectionBand>

      <Section bg="bg" width="6xl" className="!pt-6 !pb-24">
        {/* Search + filter pills */}
        <div className="relative mb-4">
          <Icon name="search" size={16} className="absolute left-4 top-1/2 -translate-y-1/2 text-muted" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search kills by title, description, or reason…"
            className="w-full border border-border bg-surface py-3 pl-11 pr-4 text-meta text-text outline-none transition-colors focus:border-primary/40"
          />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setActive(null)}
            className={cx(
              'px-3.5 py-1.5 text-caption font-bold transition border',
              active === null
                ? 'bg-text text-white border-text'
                : 'border-border bg-surface text-text/70 hover:border-text/30',
            )}
          >
            All {entries.length}
          </button>
          {gates.map((gate) => (
            <button
              key={gate}
              type="button"
              onClick={() => setActive(gate === active ? null : gate)}
              className={cx(
                'px-3.5 py-1.5 text-caption font-bold transition border',
                gate === active
                  ? 'bg-text text-white'
                  : 'border border-border bg-surface text-text/70 hover:border-text/30',
              )}
            >
              {gateLabel(gate)} {gateCounts[gate]}
            </button>
          ))}
        </div>

        <ul className="mt-8 list-none space-y-4 p-0">
          {shown.map((entry, i) => (
            <li
              key={`${entry.title}-${i}`}
              className="border border-border bg-surface p-5 md:p-6"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  {/* Struck through because that is exactly what happened to it. */}
                  <h2 className="text-body font-bold leading-snug text-text/60 line-through decoration-warning/60 decoration-2">
                    {entry.title}
                  </h2>
                  {entry.oneLiner && (
                    <p className="mt-1.5 max-w-[70ch] text-meta leading-relaxed text-muted">{entry.oneLiner}</p>
                  )}
                </div>
                <span className="inline-flex flex-none items-center gap-1.5 rounded-full bg-warning/10 px-2.5 py-1 text-caption font-bold uppercase tracking-wide text-warning">
                  <Icon name="shield" size={12} />
                  Killed
                </span>
              </div>

              <div className="mt-4 border-t border-border/70 pt-4">
                <p className="font-mono text-caption font-bold uppercase tracking-widest text-warning">
                  {entry.gateLabel}
                </p>
                <p className="mt-2 max-w-[72ch] text-meta leading-relaxed text-text/80">{entry.reason}</p>
              </div>

              {(entry.citations.length > 0 || entry.date) && (
                <div className="mt-4 flex flex-wrap items-center gap-2">
                  {entry.citations.map((c, j) => (
                    <a
                      key={j}
                      href={c.url}
                      target="_blank"
                      rel="noopener noreferrer nofollow"
                      className="inline-flex max-w-full items-center gap-1.5  bg-bg px-2.5 py-1.5 text-caption font-semibold text-text/75 transition hover:bg-surface2"
                    >
                      <Icon name="arrowRight" size={12} className="-rotate-45" />
                      <span className="truncate">{c.domain}</span>
                    </a>
                  ))}
                  {entry.date && (
          <span className="ml-auto text-caption text-muted">{formatDate(entry.date)}</span>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>

        {/* Said plainly, because a page of rejections invites exactly this question. */}
        <p className="mx-auto mt-10 max-w-[68ch] text-center text-meta leading-relaxed text-muted">
          This is a sample of the log, not all {killed.toLocaleString('en-GB')} kills. Rejections whose
          only reason was a score below the bar are left out, they are true, and they tell you
          nothing. What you see here is every kill that came with an argument.
        </p>

        <div className="mt-10 border border-border bg-surface p-8 text-center md:p-10">
          <h2 className="mx-auto max-w-[26ch] text-balance text-h2 font-black tracking-tight text-text md:text-h1">
            Now read one that survived all of it.
          </h2>
          <p className="mx-auto mt-3 max-w-[56ch] text-body leading-relaxed text-text/75">
            Same checks, same sourcing, opposite outcome. One full pack is free to read, no card and
            no email.
          </p>
          <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
            <Link
              href="/sample"
              className="inline-flex items-center gap-2  bg-primary px-6 py-3 text-meta font-bold text-on-primary shadow-none transition hover:opacity-90"
            >
              Read a full pack free
              <Icon name="arrowRight" size={15} />
            </Link>
            <Link
              href="/#catalog"
              className="inline-flex items-center gap-2 rounded-full border border-border bg-surface px-6 py-3 text-meta font-bold text-text transition hover:border-text/30"
            >
              Browse the {passed} that survived
            </Link>
          </div>
        </div>

        <WaitlistCallout />
      </Section>
    </MarketingLayout>
  );
}
