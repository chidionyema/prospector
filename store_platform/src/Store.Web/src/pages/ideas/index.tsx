import React from 'react';
import Link from 'next/link';
import type { GetServerSideProps } from 'next';

import MarketingLayout from '@/components/marketing/MarketingLayout';
import { PageHero, Section } from '@/components/marketing/blocks';
import { Seo } from '@/components/Seo';
import { Icon, SearchInput, buttonClasses, textLinkClass } from '@/components/ui';
import { fetchCatalog } from '@/lib/api/client';
import { eligibleLandings, packMatchesLanding } from '@/lib/seo/landings';
import { priceRange, formatGbp } from '@/lib/priceRange';
import CategoryGraph, { type CategoryNode } from '@/components/discovery/CategoryGraph';
import { resolveVariant } from '@/lib/getCopyVariant';
import { VARIANTS, type VariantKey } from '@/lib/copyConfig';
import { breadcrumbNode, graph, itemListNode } from '@/lib/seo/schema';

/**
 * One tile of the taxonomy map.
 *
 * `low`/`high` are the real GBP bounds of the packs that actually match this landing, computed on
 * the server from the live catalogue by the same `packMatchesLanding` predicate the landing page
 * itself uses -- so the range on the tile and the packs behind the link can never disagree. They
 * are nullable because `priceRange` returns null when no matching pack carries a parseable price,
 * and a tile with no price says nothing about price rather than guessing at one.
 *
 * There is deliberately NO survival rate and NO representative kill per category, both of which
 * would be the natural third and fourth facts here. Neither is derivable: the kill log records a
 * `gate`, a `reason` and a date per rejected idea and carries no facet at all (see the entry shape
 * in `data/kill-log-examples.json`), so a per-category kill count would have to be invented and a
 * "representative kill" would have to be assigned by hand. On this storefront that is the one
 * thing a page may not do. The kill log stays whole, at /kill-log, where every record is real.
 */
interface Category {
  slug: string;
  h1: string;
  description: string;
  count: number;
  low: number | null;
  high: number | null;
  /**
   * `Landing.kind` -- payer / commitment / effort / advantage / mechanism / sector. It was always
   * in the data and never on the page: the old category graph encoded it as a position in a 4x4
   * grid with nothing on screen to say what the rows meant. It is now the caption over each group.
   */
  group: string;
}

interface Props {
  categories: Category[];
  total: number;
  variant: VariantKey;
}

/**
 * The first sentence of a landing's `metaDescription`.
 *
 * These strings are written for `<meta name="description">`, where each one has to stand alone in
 * a search result -- so every one of them restates the purchase terms at the end. Stacked fourteen
 * deep on this page that reads as a stutter, which is why only the opening sentence (the part
 * written about THIS category) reaches the screen. `landings.ts` is left untouched, so the tag a
 * crawler reads still says everything.
 *
 * Splits on `. ` rather than `.` so a decimal or an abbreviation mid-sentence cannot cut the line
 * short, and returns the whole string unchanged when there is no sentence break to find.
 */
function firstSentence(text: string): string {
  const trimmed = text.trim();
  const end = trimmed.search(/\.\s/);
  return end === -1 ? trimmed : trimmed.slice(0, end + 1);
}

export const getServerSideProps: GetServerSideProps<Props> = async (context) => {
  const { req, query } = context;
  const variant = resolveVariant(
    query.variant,
    req?.cookies?.['mumchimp.copy.variant'],
    req?.headers?.['user-agent'],
  );
  try {
    const packs = await fetchCatalog();
    return {
      props: {
        total: packs.length,
        categories: eligibleLandings(packs).map(({ landing, count }) => {
          // Same predicate the landing page filters on, so the range describes exactly the shelf
          // the tile links to. `priceRange` reads `pack.price` (a formatted string) and returns
          // null when nothing parses, which is why both bounds are nullable downstream.
          const range = priceRange(packs.filter((p) => packMatchesLanding(p, landing)));
          return {
            slug: landing.slug,
            h1: landing.h1,
            description: landing.metaDescription,
            group: landing.kind,
            count,
            low: range ? range.min : null,
            high: range ? range.max : null,
          };
        }),
        variant,
      },
    };
  } catch (error) {
    console.error('/ideas: catalog fetch failed:', error);
    return { props: { total: 0, categories: [], variant } };
  }
};

export default function IdeasHub({ categories, total, variant }: Props) {
  const [search, setSearch] = React.useState('');

  const filtered = React.useMemo(() => {
    // Biggest shelf first. The mosaic's two lead tiles are the two largest categories, so the
    // ordering IS the hierarchy -- without this the "lead" slot would go to whichever landing
    // `LANDINGS` happens to declare first, and the tile sizes would state a ranking that is not
    // one. Ties fall back to the name so the layout is stable across catalogue refreshes rather
    // than reshuffling every time the daemon publishes.
    if (!search.trim()) {
      return [...categories].sort((a, b) => b.count - a.count || a.h1.localeCompare(b.h1));
    }
    const q = search.toLowerCase();
    return categories.filter(
      (c) =>
        c.h1.toLowerCase().includes(q) ||
        c.description.toLowerCase().includes(q) ||
        c.slug.toLowerCase().includes(q),
    );
  }, [categories, search]);

  return (
    <MarketingLayout
      breadcrumbs={[{ href: '/', label: 'Catalogue' }, { href: '#', label: 'Categories' }]}
      breadcrumbsWidth="7xl"
    >
      <Seo
        title="Business ideas by category"
        description="Browse researched business ideas by industry. Every pack cites a source for every claim."
        jsonLd={graph(
          itemListNode(
            categories.map((c) => ({ name: c.h1, path: `/ideas/${c.slug}` })),
            'Business idea categories',
          ),
          breadcrumbNode([
            { name: 'Mumchimp', path: '/' },
            { name: 'Business ideas', path: '/ideas' },
          ]),
        )}
      />

      {/*
       * "BY INDUSTRY" WAS FALSE, and the nav is why it mattered (2026-08-14).
       *
       * The h1 read "Explore stress-tested ideas by industry." while five of the six groups this
       * page renders are not industries at all: who pays, hours needed, how automated, skills
       * suited, how it earns. Only `sector` is industry, and it is the last group on the page. The
       * heading described one sixth of what was under it.
       *
       * It also left the site calling this one destination three things at once: the nav item says
       * "Categories", the pack breadcrumb says "Browse by category", the URL says `/ideas`, and the
       * h1 said "ideas by industry". The URL is the one that cannot move cheaply -- `/ideas` and
       * all fourteen `/ideas/<slug>` pages are emitted into the sitemap (`sitemap.xml.tsx:26,110`)
       * and are built to rank for "business ideas" -- so the fix is the words, and the h1 now
       * carries BOTH nouns: the search phrase the URL targets, and the one the chrome uses.
       *
       * "Choose your battleground" went with it. This shop's proposition is that the checking
       * already happened and can be audited; the lead states what the grouping IS, which is the
       * question a visitor arriving on a list of fourteen unexplained links actually has.
       */}
      <PageHero
        width="7xl"
        eyebrow="Categories"
        title="Business ideas, by category."
        /*
         * THE WORDS ARE THE FOUNDER'S AND THEY STAY (2026-08-15).
         *
         * I rewrote this lead to stop it naming the six axes that `CategoryGraph.tsx:80-85` renders
         * as six group headings below. Founder's ruling on reading it: "there is nothing that wrong
         * with it, its just the format and presentation." So the defect here is not the sentence,
         * it is that a 34-word enumeration is being drawn as one undifferentiated paragraph of lead
         * type. Fix the setting, not the words -- see `PageHero`.
         */
        lead={
          total > 0
            ? `${total} researched packs, sorted six ways: who pays for it, the hours it needs, how much of it is automated, the skills it suits, how it makes money, and the sector it sits in.`
            : 'Researched packs, sorted six ways.'
        }
      />

      <Section bg="white" width="7xl">
        {/* Search */}
        <SearchInput
          label="Search industries, skills, or markets"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search industries, skills, or markets…"
          className="mb-8"
        />

        {/*
         * ONE OBJECT, NOT TWO. This page used to render the category graph under "Browse the
         * shape of the catalogue" and then every one of the SAME 14 categories again under
         * "All categories" -- one navigation, twice, on the page whose only job is showing a
         * visitor what the catalogue holds. Measured at 1440x900 on 2026-08-13, the pair ran
         * y=576 to y=3980 and the first 950px of it was grey circles carrying strictly less
         * than the list below them (no description, no price).
         *
         * `CategoryGraph` is now that single object: a row per category, grouped by facet with
         * the caption the grouping never had, the pack count drawn one mark per pack, and the
         * description and price range that used to force a second list. What US-7 asked for is
         * all still here -- see the component's own note -- and the duplicate is gone.
         */}
        {/* "All categories", VISIBLE ONLY WHILE SEARCHING (2026-08-14).
            Unsearched, this rendered the words "All categories" directly under a page titled
            "Business ideas, by category." and directly above a caption reading "Who pays for it" --
            a heading that told a visitor nothing the two lines either side of it had not already
            said, in the last 40px before the fold. Under a query it earns its place, because
            `12 matching categories` is a count that changes and cannot be got anywhere else.

            It stays in the accessibility tree either way. The list's groups are `h3`s, so dropping
            the element outright would leave the page jumping h1 to h3, and a screen-reader user
            navigating by heading would meet "Who pays for it" with nothing saying what it groups. */}
        {filtered.length > 0 && (
          <h2 className={search ? 'mb-4 text-meta font-semibold text-text' : 'sr-only'}>
            {search ? `${filtered.length} matching categor${filtered.length === 1 ? 'y' : 'ies'}` : 'All categories'}
          </h2>
        )}

        {/*
         * THE MOSAIC IS GONE, and this is what it was for and what replaced it.
         *
         * It was a two-step ladder of tiles: the two biggest categories took a full row, the rest
         * paired up, so size stated the hierarchy. The idea was right and the execution could not
         * work at the width. Measured at 1440x900 on 2026-08-13: a lead tile ran the full 1200px
         * with its name and description capped at 62ch on the left and its count and range flush
         * right, which put ~600px of nothing through the middle of the two most important rows on
         * the page -- and every tile spent a 40-48px square on `BespokeIcon`, which draws the same
         * generic mark for all 14 slugs.
         *
         * The rows above carry the same three facts (count, real price range, the facet's own
         * description) with the hierarchy expressed by the mark run rather than by tile area, so
         * a 28-pack category is visibly 28 and a 5-pack one is visibly 5 -- a thing the ladder
         * could only say twice, in two sizes. Nothing that was on a tile is missing from a row.
         *
         * Search still collapses the grouping, for the reason the mosaic collapsed its ladder:
         * once a query is typed, the facet a result sits in is not what is being looked at.
         */}
        {/* Two distinct empty states, not one. `filtered` is empty for two different reasons
            that read very differently to a buyer: a search with no hits (`search` is set --
            "Clear search" fixes it), or `categories` itself being empty because the catalog
            fetch failed or nothing has cleared the checks yet (`search` is still ''). The single
            branch this replaced rendered `No categories match "".` -- quoting an empty string --
            with a "Clear search" button that had nothing to clear, whenever the page loaded with
            zero categories. That is exactly the state a catalog outage produces (getServerSideProps
            above catches the fetch failure and returns `categories: []`), so it was the visible
            failure mode of an outage, not a rare edge case. */}
        {filtered.length > 0 ? (
          <CategoryGraph
            grouped={!search}
            filterPath={(slug) => `/ideas/${slug}`}
            categories={
              filtered.map((cat) => ({
                kind: cat.slug,
                label: VARIANTS[variant].categoryH1[cat.slug] ?? cat.h1,
                count: cat.count,
                group: cat.group,
                /* THE FIRST SENTENCE, not the whole meta description. These strings are written
                   for `<meta name="description">`, where every one has to restate the offer to
                   stand alone in a search result -- so 14 of them stacked on one page ended
                   ". Every claim sourced, one payment per pack." / ". One payment per researched
                   pack." / ". Every claim cited, one payment per pack." The purchase terms are
                   stated once on this site, on the home page's closing band; repeating them
                   fourteen times down a category list is the exact defect the US-7 audit opened
                   with ("the descriptions were repetitive") and did not fix. The first sentence
                   is the part written about THIS category, and it is left untouched in
                   `landings.ts` so the meta tag a crawler reads still says everything. */
                description: firstSentence(cat.description),
                /* `low === high` prints one figure rather than "£49 to £49", which reads as a
                   bug in a price ladder. */
                price:
                  cat.low !== null && cat.high !== null
                    ? cat.low === cat.high
                      ? formatGbp(cat.low)
                      : `${formatGbp(cat.low)} to ${formatGbp(cat.high)}`
                    : null,
              })) as CategoryNode[]
            }
          />
        ) : search ? (
          <div className="py-12 text-center">
            <p className="text-meta text-muted">No categories match &ldquo;{search}&rdquo;.</p>
            <button
              type="button"
              onClick={() => setSearch('')}
              className={buttonClasses({ variant: 'secondary', className: 'mt-3' })}
            >
              Clear search
            </button>
          </div>
        ) : (
          <div className="py-12 text-center">
            <p className="text-meta text-muted">
              No categories are available right now. Check back shortly.
            </p>
          </div>
        )}

        {/*
         * THE CLOSING `CtaBand` WAS DELETED AND ITS ACTION MOVED HERE. It was a full-width band
         * titled "Or see everything at once." with an EMPTY lead and one button, and measured at
         * 1440x900 on 2026-08-13 it spent 350px of page height to say that -- a heading and a
         * button alone in the left third, nothing in the other two. The page already ends on a
         * sentence about what the catalogue does and does not contain; the way out of a category
         * list is a control on that sentence, not a second screen restating it.
         */}
        <div className="mt-12 flex flex-wrap items-center justify-between gap-x-10 gap-y-5 border-t border-border pt-8">
          <p className="max-w-[62ch] text-meta leading-relaxed text-muted">
            Categories appear once enough packs have cleared the checks to fill them. Ideas that failed are in the{' '}
            <Link href="/kill-log" className={textLinkClass('font-medium')}>
              kill log
            </Link>{' '}
            with the sourced reason why.
          </p>
          <Link href="/" className={buttonClasses({})}>
            Browse every pack
            <Icon name="arrowRight" size={14} />
          </Link>
        </div>
      </Section>
    </MarketingLayout>
  );
}
