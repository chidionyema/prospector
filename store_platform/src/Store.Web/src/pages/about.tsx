import React from 'react';
import Link from 'next/link';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Seo } from '@/components/Seo';
import { Icon, buttonClasses, textLinkClass } from '@/components/ui';
import { BRAND, FOUNDER, hasFounder } from '@/lib/config';
import { RESEARCH_STATS } from '@/lib/stats';

/**
 * L2 - The about page: the one human page on the site.
 *
 * REBUILT 2026-08-07. It was the wrong page entirely. The home page links here as "Who is behind
 * this" and the page contained zero human content: a condensed second account of the checks, a
 * second explanation of the kill log, and a third description of what a pack is. Every one of
 * those already had an owner (/how-it-works, /kill-log, the home page), so a reader who arrived
 * looking for a person met the mechanism described to them for the second time in two pages.
 *
 * What survives from the old page is nothing but the links. The content is the founder's story,
 * moved off the home page, where it sat as a two-line clamp in a bordered aside. The thesis is one
 * sentence -- "So I built the part I kept losing to doubt" -- and the page is built around it.
 *
 * DELETED DELIBERATELY, do not bring them back here:
 *   - the list of checks (owned by /how-it-works, which shows a real kill under each one);
 *   - the kill-log explanation (owned by /kill-log, which IS the log);
 *   - "what a pack actually is" (owned by the home page and /pricing);
 *   - "The voice is source-or-die. Sourced, not sold. Refutational, not promotional." That was our
 *     internal style guide, published. A reader is owed the practice, not the instruction we wrote
 *     to ourselves, so the practice is stated as what the engine does instead.
 */
export default function AboutPage() {
  // Via `RESEARCH_STATS`, not the raw JSON. This page was one of the seven that each imported
  // `kill-log-totals.json` and re-derived what the numbers meant; that is how "researched" ended
  // up printing the kill count elsewhere on the site. See lib/stats.ts.
  const totals = RESEARCH_STATS;
  return (
    <MarketingLayout>
      <Seo
        title={`About ${BRAND.name} - who is behind this`}
        description={`Why ${BRAND.name} exists, in the words of the person who built it, and where the engine that kills most of the ideas came from.`}
      />

      <section className="mx-auto max-w-3xl px-6 py-10 md:py-24">
        <p className="mb-3 text-caption font-medium text-muted">
          About
        </p>
        {/* The headline IS the thesis, quoted from the story below it rather than summarising it.
            It runs at `display`, the top of the six-step scale, which now carries its own mobile
            size. (The 96px `text-mega` this note used to contrast against was deleted from
            tokens.css on 2026-08-08 -- §3.2 has six sizes and that was a seventh.) */}
        <h1 className="text-h1 font-semibold text-text">
          So I built the part I kept losing to doubt.
        </h1>

        <p className="mt-6 max-w-[60ch] text-body leading-relaxed text-muted md:text-h2">
          I always wanted to run my own business, and the ideas were never the hard part.
        </p>

        {/* `id` is the ownership anchor, not a styling hook: §5.3 gives the founder story exactly
            one page, and `factOwnership.test.ts` matches on this id. It was previously told twice,
            here and from `FOUNDER.bio`. */}
        <div
          id="founder-story"
          className="mt-8 max-w-[60ch] space-y-5 text-body leading-relaxed text-muted"
        >
          <p>
            Launching them was. After a few attempts that never quite got off the ground, a habit
            set in: I would talk myself out of the next idea before it went anywhere. Not because I
            had checked it and found something wrong. Because I had not checked it at all, and
            doubt fills that space much faster than research does.
          </p>
          <p>
            {/* "the ideating" was the one word on this page a reader would not use themselves. */}
            What I enjoyed was having the ideas. What I kept losing was the bit in the middle,
            where you find out whether one holds up before you commit a year to it.
          </p>
          {/* The one sentence the page exists for, set apart and in the darker ink. It is the
              hinge between the problem and the product, and it was previously buried as line four
              of a five-sentence bio clamped to two lines on the home page. */}
          <p className="text-body font-semibold text-text md:text-h2 md:leading-snug">
            So I built the part I kept losing to doubt, and made it check every idea harder than I
            ever did.
          </p>
          <p>
            That is the seed {BRAND.name} grew from. It runs on ideas that are not mine now, and it
            publishes its workings either way: the few it clears, and the many more it kills.
          </p>
        </div>

        {hasFounder() && (
          <p className="mt-6 text-caption font-medium text-muted">
            {FOUNDER.name}, who built {BRAND.name}
          </p>
        )}

        <div className="mt-14">
          <h2 className="text-h2 font-semibold text-text md:text-h1">
            Where the engine came from
          </h2>
          <p className="mt-3 max-w-[60ch] text-body leading-relaxed text-muted">
            It started as the questions I made myself answer before starting anything: is the pain
            real, would anyone pay, is there any way to reach them. Those questions are the checks
            now, asked by software that has to fetch a source before it may answer. Every claim is
            cited, or the pack does not ship.
          </p>
        </div>

        {/* Two links, not two more explanations. Each names what the page it points at holds, and
            the kill count is read from the totals file so this page cannot restate it wrongly. */}
        <div className="mt-10 grid gap-3 sm:grid-cols-2">
          <Link
            href="/how-it-works"
            className="rounded-md border border-border bg-surface p-6 transition-colors hover:border-border-strong"
          >
            <p className="text-meta font-semibold text-text">How it works</p>
            <p className="mt-1 text-meta leading-relaxed text-muted">
              One idea taken through the checks end to end, with every source it was judged on.
            </p>
            <span className={textLinkClass('mt-3 inline-flex items-center gap-1 text-meta font-medium')}>
              Read it <Icon name="arrowRight" size={12} />
            </span>
          </Link>
          {/*
            KILL-LOG PARAGRAPH (email §8). The two-card link grid used to be both a link and a
            description; the description repeated the count the link's destination already names,
            and the card was a 1/3 of the page that said "click here". One paragraph naming the
            point of the log, one link, no second card. The log is the receipt behind the
            catalogue; the catalogue is what's left.
          */}
          <Link
            href="/kill-log"
            className="rounded-md border border-border bg-surface p-6 transition-colors hover:border-border-strong"
          >
            <p className="text-meta font-semibold text-text">The kill log</p>
            <p className="mt-1 text-meta leading-relaxed text-muted">
              Most ideas die. Every kill is public, with the argument that made it. The log is
              the receipt behind the catalogue; the catalogue is what’s left.
            </p>
            <span className={textLinkClass('mt-3 inline-flex items-center gap-1 text-meta font-medium')}>
              Read it <Icon name="arrowRight" size={12} />
            </span>
          </Link>
        </div>

        <div className="mt-14 rounded-md border border-text bg-surface p-8">
          <p className="text-caption font-medium text-muted">
            Read before you buy
          </p>
          <h2 className="mt-2 text-h2 font-semibold text-text md:text-h1">
            See the work first.
          </h2>
          <p className="mt-2 max-w-[60ch] text-meta text-muted">
            Read a full report, unredacted. Every check, every verdict, every source link. Judge
            the pack by it.
          </p>
          <div className="mt-6">
            <Link
              href="/sample"
              className={buttonClasses({ size: 'lg' })}
            >
              Read the free report
              <Icon name="arrowRight" size={14} />
            </Link>
          </div>
        </div>
      </section>
    </MarketingLayout>
  );
}
