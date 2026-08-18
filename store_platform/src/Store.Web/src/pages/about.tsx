import React from 'react';
import Link from 'next/link';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Seo } from '@/components/Seo';
import { Icon, textLinkClass } from '@/components/ui';
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
    <MarketingLayout
      breadcrumbs={[{ href: '/', label: 'Catalogue' }, { href: '#', label: 'About' }]}
      breadcrumbsWidth="6xl"
    >
      <Seo
        title={`About ${BRAND.name} - who is behind this`}
        description={`Why ${BRAND.name} exists, in the words of the person who built it, and where the engine that kills most of the ideas came from.`}
      />

      {/* THE SHELL, NOT A COLUMN OF ITS OWN. This was `max-w-3xl px-6 py-10 md:py-24`: a 768px
          measure at a 24px gutter, so the About page's left edge missed the logo above it by 180px.
          The drawing puts every page in one frame, `.wrap{max-width:1080px;padding:0 20px}`
          (`mockups/about.html`), and gives the page head `.pagetop{padding:14px 0 8px}` under the
          crumb. The ESSAY keeps its own 56ch measure inside this frame; that is a reading measure
          and it is set on the prose itself, below. */}
      <section className="mx-auto max-w-[1080px] px-5 pt-3.5 pb-16">
        <div className="pagetop">
        <p className="eyebrow">About</p>
        {/* The headline IS the thesis, quoted from the story below it rather than summarising it.
            It runs at `display`, the top of the six-step scale, which now carries its own mobile
            size. (The 96px `text-mega` this note used to contrast against was deleted from
            tokens.css on 2026-08-08 -- §3.2 has six sizes and that was a seventh.) */}
        <h1>
          So I built the part I kept losing to doubt.
        </h1>

        <p className="mt-6 max-w-[60ch] md:text-h2 lede">
          I always wanted to run my own business, and the ideas were never the hard part.
        </p>
        </div>

        {/* `id` is the ownership anchor, not a styling hook: §5.3 gives the founder story exactly
            one page, and `factOwnership.test.ts` matches on this id. It was previously told twice,
            here and from `FOUNDER.bio`. */}
        {/* THE ESSAY SETTING (MASTER-BRIEF section 3 type table, "About essay body", and section 7
            `/about`): 18px, line-height 1.68, `--ink`, 56ch measure.

            IT IS A READING SETTING, NOT A SEVENTH SCALE STEP. tokens.css carries six sizes and a
            note recording that a seventh was deleted for being a seventh. This is not one: the UI
            scale sizes labels, headings and controls, and this sizes one page of continuous prose,
            which is the one thing on the site a reader reads rather than scans. It is written here,
            on the only page that has an essay, rather than promoted to a token nothing else uses.

            56ch, not 60ch, and `text-text`, not `text-muted`. The old setting was the site's
            standard body paragraph: 16px of grey at the width of a marketing column. That is the
            right treatment for a paragraph under a heading and the wrong one for eight hundred
            words of first-person writing, which is why the one human page on the site read like a
            product description. */}
        <div
          id="founder-story"
          className="essay mt-8 space-y-5"
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
          {/* `.quiet` in the mockup: this paragraph steps out of the story and back to the
              product, so it drops to the muted ink the rest of the site uses. */}
          <p className="quiet">
            That is the seed {BRAND.name} grew from. It runs on ideas that are not mine now, and it
            publishes its workings either way: the few it clears, and the many more it kills.
          </p>
        </div>

        {/* THE SIGNATURE RULE. A hairline above the name, at the essay's own measure, which is what
            closes a signed piece of writing and says the first person stops here. It was a 12px
            caption sitting directly under the last paragraph, indistinguishable from the metadata
            captions everywhere else on the site, so the one page written by a person did not read
            as signed by one. */}
        {hasFounder() && (
          <p className="sign">
            <strong className="font-semibold text-text">{FOUNDER.name}</strong>, who built{' '}
            {BRAND.name}
          </p>
        )}

        {/* THE FACTS ROW (`mockups/about.html`, `.facts{grid-template-columns:repeat(3,1fr);
            border:1px solid var(--line);border-radius:var(--r-card)}`, cells at 17px of padding,
            figures at 24px/680). It stacks to one column on small screens, which is the drawing's
            own media rule.

            THE THIRD CELL IS NOT THE DRAWING'S. The drawing's third cell reads "On the shelf 74".
            That is the survivor count, and the founder barred it on 2026-08-13: `lib/stats.ts`
            exports no such field, so no page can print it and tsc refuses any attempt. The kill
            rate is the same fact from the side that is allowed, it comes from the same file, and a
            reader can check it against the other two cells.

            THE LABELS ARE NOT THE DRAWING'S EITHER. `.facts span` is mono, uppercase and letter
            spaced. Two guard tests refuse all three: `monoIsTheDataVoice` ("an eyebrow is
            language, not data") and `weightAndCasePolicy` ("sets nothing in all-caps via CSS",
            "letterspaces nothing out into small caps"). Those rules are older founder decisions
            with tests behind them, so the labels keep the site's caption setting and the drawing
            loses this one. */}
        <dl className="facts">
          <div>
            <dt><span>Researched</span></dt>
            <dd><b className="num">{totals.researched.toLocaleString('en-GB')}</b></dd>
          </div>
          <div>
            <dt><span>Killed, published</span></dt>
            <dd><b className="num">{totals.killed.toLocaleString('en-GB')}</b></dd>
          </div>
          <div>
            <dt><span>Kill rate</span></dt>
            <dd><b className="num">{totals.rejectRateLabel}</b></dd>
          </div>
        </dl>

        {/* `.rule2{border-top:2px solid var(--ink);margin:44px 0 0}`. A 2px ink rule, not a
            hairline: it separates the personal half of the page from the mechanical half. */}
        <hr className="rule2" />

        <div className="mt-8">
          <h2 className="sec">
            Where the engine came from
          </h2>
          <p className="mt-3 max-w-[60ch] lede">
            It started as the questions I made myself answer before starting anything: is the pain
            real, would anyone pay, is there any way to reach them. Those questions are the checks
            now, asked by software that has to fetch a source before it may answer. Every claim is
            cited, or the pack does not ship.
          </p>
        </div>

        {/* Two links, not two more explanations. Each names what the page it points at holds, and
            the kill count is read from the totals file so this page cannot restate it wrongly. */}
        <div className="twocard">
          <Link
            href="/how-it-works"
            className="card tc transition-colors hover:border-border-strong"
          >
            <p className="text-meta font-semibold text-text">How it works</p>
            <p className="mt-1 lede">
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
            className="card tc transition-colors hover:border-border-strong"
          >
            <p className="text-meta font-semibold text-text">The kill log</p>
            <p className="mt-1 lede">
              Most ideas die. Every kill is public, with the argument that made it. The log is
              the evidence behind the catalogue; the catalogue is what’s left.
            </p>
            <span className={textLinkClass('mt-3 inline-flex items-center gap-1 text-meta font-medium')}>
              Read it <Icon name="arrowRight" size={12} />
            </span>
          </Link>
        </div>

        {/* THE CLOSING BLOCK (`mockups/about.html`, `.closing{border-top:2px solid var(--ink);
            margin-top:46px;padding:34px 0 0}`). It was a bordered card on a surface fill, which
            made the last thing on the page look like one more component. The drawing ends the page
            on a rule and lets the two actions sit on the canvas. */}
        <div className="closing">
          <p className="eyebrow">Read before you buy</p>
          <h2 className="sec">
            See the work first.
          </h2>
          <p>
            Read a full report, unredacted. Every check, every verdict, every source link. Judge
            the pack by it.
          </p>
          {/* `.ctarow`: the free report, then the shelf. Two actions, gap 12px. */}
          <div className="ctarow">
            <Link href="/sample" className="btn">
              Read the free report
              <Icon name="arrowRight" size={14} />
            </Link>
            <Link href="/" className="btn ghost">
              Browse the packs
            </Link>
          </div>
        </div>
      </section>
    </MarketingLayout>
  );
}
