import React from 'react';
import { GetServerSideProps } from 'next';
import dynamic from 'next/dynamic';
import { useRouter } from 'next/router';
import Link from 'next/link';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Seo } from '@/components/Seo';
import { productJsonLd } from '@/lib/productJsonLd';
import { absolute, breadcrumbNode, graph } from '@/lib/seo/schema';
import { packOgImagePath } from '@/lib/seo/ogImage';
import { buttonClasses, Glyph, Icon, ErrorState, Breadcrumbs, SourcedLine, CitationList, PriceText, textLinkClass } from '@/components/ui';
import { parseCitations } from '@/lib/citations';
import { cx } from '@/components/ui/cx';
import { categoryFor } from '@/lib/category';
import { COMMON_CHECKS, checkForGate } from '@/lib/checks';
import { Section } from '@/components/marketing/blocks';
import { PackContentsSection, PACK_DOCUMENTS } from '@/components/marketing/PackContents';
import { ApiError, fetchCatalog, fetchPackDetails, freshnessLabel, marketLabel, parseCheckCounts, scoreAxes, splitVerdict, Pack, PackDetails, FinancialSnapshot } from '@/lib/api/client';
import { RESEARCH_STATS } from '@/lib/stats';
import { PACK_DISCLAIMER } from '@/lib/disclaimer';
import { formatPriceForMarket, formatChargeNote, formatApproxNote, currencyForCountry, type Currency } from '@/lib/fx';
import { isTruncated, repairTruncation } from '@/lib/copy';
import { track, trackPriceEvent } from '@/lib/analytics';
import { BuyerIdentityNote } from '@/components/checkout/BuyerIdentityNote';
import EvidenceExcerptPlate, { firstCitedIndex } from '@/components/marketing/EvidenceExcerptPlate';
import PackBuyButton from '@/components/checkout/PackBuyButton';
import { usePackCheckout } from '@/lib/checkout/usePackCheckout';
import { PREOPENED_CHECKOUT_PARAM, preopenedClientSecret } from '@/lib/preopenedCheckout';
import { FacetChips } from '@/components/discovery/FacetChips';
import { SimilarPacks } from '@/components/discovery/SimilarPacks';
import { LEGAL, FOUNDER, BRAND, hasFounder, RESEARCH_RATE_ANCHOR } from '@/lib/config';
import { AddToCartButton } from '@/components/cart/AddToCartButton';
import { FounderPreviewLink } from '@/components/founder/FounderPreviewLink';
import { similarPacks } from '@/lib/discovery';

// Loaded on demand, not on every page hit: `@stripe/react-stripe-js` only renders once
// `clientSecret` is set (after the buyer clicks Buy and the checkout session round trip
// completes), yet a static import bundled it into this route's own First Load JS regardless --
// measured pre-change, `/pack/[id]`'s own chunk carried the full Elements wrapper for every
// visitor, including the overwhelming majority who never click Buy. `ssr: false` is correct
// (not a compromise): the panel is a client-only overlay gated on client state, so there is
// nothing for the server to render.
const EmbeddedCheckoutPanel = dynamic(
  () => import('@/components/checkout/EmbeddedCheckoutPanel').then((m) => m.EmbeddedCheckoutPanel),
  { ssr: false },
);

const subscribeToNothing = () => () => {};

/**
 * "Same mechanics, different world", with the cheaper packs taken out of it.
 *
 * FOUNDER, 2026-08-16: the row read as a discount anchor. It did. `similarPacks` scores on
 * MECHANISM and is indifferent to price, so a £199 pack routinely showed three £29 matches, in a
 * row sitting between the buy rail and the footer -- a reader at the moment of commitment being
 * shown the same mechanics for a fifth of the money, by us. Whatever they then buy, the £199 sale
 * is the one we talked them out of.
 *
 * THE PLACEMENT WAS THE OTHER CANDIDATE FIX AND IS NOT THIS ONE. Moving the row up the page keeps
 * every cheaper pack in it and just shows them sooner; the anchoring is in the price gap, not the
 * scroll position. (Baymard's 50-site study is the evidence that cross-sells at the moment of
 * commitment "can distract users from initiating the checkout process" -- it does NOT prescribe a
 * placement, and this comment does not claim it does.)
 *
 * Same price or dearer, so the row can only ever trade up. It keeps its own empty-state contract:
 * `SimilarPacks` renders nothing on an empty list, and filtering to nothing is a normal outcome
 * for the dearest pack on the shelf. A pack with no `pricePence` is treated as 0 and dropped
 * rather than guessed at -- a missing price is not evidence that it is dearer.
 */
function sameOrDearer(pack: PackDetails, similar: Pack[]): Pack[] {
  const floor = pack.pricePence ?? 0;
  return similar.filter((p) => (p.pricePence ?? 0) >= floor);
}

interface PackPageProps {
  pack: PackDetails | null;
  /** Up to 3 pre-scored "same mechanics" matches, computed server-side from the catalogue --
   *  NOT the catalogue itself (measured 2026-08-14: shipping all ~59 packs as a page prop just to
   *  pick 3 in `SimilarPacks` doubled this route's `__NEXT_DATA__` payload for a row that renders
   *  at most 3 cards). `similarPacks` is the same pure function `pages/index.tsx` already runs
   *  server-side for its personalised row; running it here too means the client never receives a
   *  pack it cannot show. Empty when the catalogue fetch failed or nothing scored -- a catalogue
   *  outage must never take down a page someone is trying to buy from, and the row already hides
   *  itself on empty (AC-21, `SimilarPacks.tsx`). */
  similar: Pack[];
  error?: string;
  /** True when the pack could not be read because the API was unreachable, NOT because the pack
   *  is gone (a gone pack returns `notFound` and never reaches this component). Drives `noindex`,
   *  so a blip does not get a retry-able page dropped from the index the way a 404 would. */
  unavailable?: boolean;
  /** The currency to render prices in. Same as the home page: decoupled from market, derived
   *  from the country header on the server. */
  currency: Currency;
}

/**
 * The six fronts an idea is attacked on before it can be listed.
 *
 * These name the FILTER, not this pack's findings, deliberately, because this page has no
 * per-check verdicts to render (`PackDetails` in lib/api/client.ts carries none) and a static
 * list therefore may only say what is true of every listed pack.
 *
 * The previous copy said "We tried to show the value would not last. **It held.**" beside a green
 * success tick, six times. Two things make that a claim the page cannot support:
 *
 *   - a check that finds no matching passage returns `unverifiable`, which is silence, not a
 *     finding. Across the 111 passing dossiers, `incumbency` has no positive finding for 71 of
 *     them (59 unverifiable + 12 never run) and `legality` for 52;
 *   - and not every check runs in every lane at all, the smb and side_hustle lanes never run
 *     `value_durability` or `incumbency` (see the per-lane `hard_gates`/`score_checks` in
 *     config.yaml). "We tried" is false for those packs before the second clause even arrives.
 *
 * What IS true of every listed pack is the gate: it died on the first front where we found cited
 * evidence against it, and it did not die (kill_filter.is_hard_fail, only a cited killing
 * verdict kills; silence never does). So the lines state the front, the prose states what
 * surviving means, and the marker is a numeral rather than a green tick.
 *
 * Framing stays refutational, two-sided attack framing out-persuades one-sided "validated"
 * claims (Allen 1991, O'Keefe 1999, Eisend 2006). The change is scope, not tone: this pack's own
 * answers are real and directly below, in the scored axes with their weak ones left visible, and
 * in the QA report inside the pack, which marks each individual claim SUPPORTED or not.
 *
 * That refutational wording is a REGISTER of the shared vocabulary, not a private one. It used to
 * be a hand-typed array here, which is how `payer_solvency` came to be called three different
 * things on three pages. See lib/checks.ts.
 */
const CHECKS = COMMON_CHECKS.map((check) => check.refutation);

// The deliverable list lives in one shared place (PackContents) so this page and the homepage can
// never drift into promising different things for the same £49.

export default function PackPage({ pack, similar, error, unavailable, currency }: PackPageProps) {
  const router = useRouter();

  // Hooks must run unconditionally. If the server couldn't fetch the pack, render an error
  // panel, the inner component runs only when pack is non-null.
  const packId = router.query.id as string;

  if (!pack) {
    return (
      <MarketingLayout>
        {/* This branch is only ever an OUTAGE now -- a withdrawn pack returns `notFound` from
            getServerSideProps and renders the 404 page instead. The page still served
            "index, follow" here, which is how a temporarily-down pack could be crawled and
            recorded as a thin live page. `noindex` also suppresses the canonical (Seo.tsx:79). */}
        <Seo title="Pack temporarily unavailable" noindex={unavailable !== false} />
        <div className="flex min-h-[calc(100dvh-4rem)] items-center justify-center px-6 py-16">
          <ErrorState
            title="Could not load this pack"
            message={error || 'The pack data could not be retrieved. The server may be temporarily unavailable.'}
          />
          <button
            type="button"
            onClick={() => {
              import('@/lib/api/client').then(({ fetchPackDetails }) => {
                fetchPackDetails(packId).then(() => window.location.reload());
              });
            }}
            className="mt-4"
          >
            Try again
          </button>
        </div>
      </MarketingLayout>
    );
  }

  return <PackPageContent pack={pack} similar={similar} currency={currency} />;
}

/** Inner component: all hooks that require a non-null pack live here. */
function PackPageContent({ pack, similar, currency }: { pack: PackDetails; similar: Pack[]; currency: Currency }) {
  const router = useRouter();
  const preopened = preopenedClientSecret(router.query[PREOPENED_CHECKOUT_PARAM]);

  // The buy path itself, shared verbatim with the shelf's Buy drawer, which is the point: the
  // logic it holds is three production incidents written down, and two copies would mean the
  // next such fix lands in only one of them. See lib/checkout/usePackCheckout.
  const {
    checkingOut,
    checkoutError,
    clientSecret,
    canCheckout,
    provider,
    buy: handleBuy,
    handleUnreachable: handleEmbeddedUnreachable,
    closeOverlay,
  } = usePackCheckout(pack, preopened);

  // The denominator of the price→checkout rate. Keyed on (id, pricePence) rather than fired once
  // per mount, so a price that changes under a client-side navigation is counted as the separate
  // view it is -- the rate exists to compare prices, and folding two prices into one view would
  // erase the only thing being measured.
  React.useEffect(() => {
    trackPriceEvent('price_viewed', pack);
  }, [pack.id, pack.pricePence]);

  const axes = scoreAxes(pack.financialSnapshot);
  const verdict = splitVerdict(pack.qaVerdictSummary);
  const cat = categoryFor(pack);

  // The evidence line under the title, assembled from what this pack can actually state. Built as
  // a token list rather than inline conditionals so the separator can never lead or trail: with
  // three optional fragments, the JSX version leaves a dangling "·" on any pack missing the last
  // one, and packs missing a field are the common case, not the edge case.
  const checks = parseCheckCounts(pack.qaVerdictSummary);
  const evidenceTokens = [
    // The market leads, because it is the qualifier on everything after it: "34 sources" means
    // something different for a UK listing than a US one. It moved here from the identity plate
    // above the title, which was removed as duplicated chrome (see the note at its old site).
    pack.market ? pack.market.toUpperCase() : null,
    typeof pack.sourceCount === 'number' && pack.sourceCount > 0
      ? `${pack.sourceCount} sources`
      : null,
    checks ? `${checks.cleared}/${checks.total} checks` : null,
    freshnessLabel(pack.verifiedAt),
  ].filter((t): t is string => Boolean(t));

  // Every source this page can actually hand the visitor, right now, without buying anything.
  // Distinct from `pack.sourceCount` (51 on some packs), which counts what is INSIDE the pack.
  // The two numbers must never be presented as one: claiming "51 sources" on a page that lets
  // you open three is precisely the unearned-assertion move the six checks exist to kill.
  //
  // THE PULL-QUOTE'S SOURCE GOES LAST, NOT FIRST (founder, 2026-08-16: the same source four
  // times). This list is deduped by URL and was built in extract order, so its first chip was
  // always the citation on the line `EvidenceExcerptPlate` quotes at the top of the page -- the
  // one source the reader has already been shown, offered again under a heading promising more of
  // them. Rotating the hero's line to the back changes what is offered first and nothing else: the
  // set is identical, every source is still here, and a pack with exactly one source still shows
  // it. `firstCitedIndex` is the plate's own function, so the two cannot disagree about which line
  // is the hero.
  const openSources = React.useMemo(() => {
    const lines = pack.sampleExtract ?? [];
    const hero = firstCitedIndex(lines);
    const ordered =
      hero >= 0 ? [...lines.slice(hero + 1), ...lines.slice(0, hero + 1)] : lines;
    const seen = new Set<string>();
    return ordered.flatMap((line) =>
      parseCitations(line).citations.filter((c) => !seen.has(c.url) && seen.add(c.url)),
    );
  }, [pack.sampleExtract]);

  // THE HONEST HALF OF SOCIAL PROOF.
  //
  // The page has no customer count, no testimonial and no logo wall, and inventing any of them is
  // the one move that would falsify the whole storefront. What it does have is third-party
  // corroboration: the DOMAINS the free extract cites. Naming them near the title is the part of
  // "other people stand behind this" that is true, because the visitor can go and read them, and
  // the clickable list further down does exactly that.
  //
  // Deduped by host, not by URL: `openSources` already dedupes URLs, but three pages of
  // legislation.gov.uk are one institution vouching once, and printing it three times would turn
  // a trust mark back into a volume claim. The count is deliberately NOT restated here either --
  // `evidenceTokens` above owns the numbers.
  const sourceHosts = React.useMemo(() => {
    const seen = new Set<string>();
    return openSources
      .map((c) => c.host)
      .filter((h) => Boolean(h) && !seen.has(h) && seen.add(h));
  }, [openSources]);

  // Map internal axis keys to buyer-facing labels so the scored section
  // reads as consumer content, not internal tooling.
  //
  // These are the SCORE axes (`score.py`), a different set from the kill gates rendered above --
  // a survivor is ranked on them, it is not killed by them. Where an id belongs to both sets it
  // must not pick up a second name: `distribution` was "Can reach buyers" here and "A route to
  // the buyer" in the checks block, one engine id under two labels on one page, which is the
  // fragmentation `lib/checks.ts` exists to end. So the overlap defers to the shared vocabulary
  // and only the axis-only keys are named locally.
  const axisLabel = (key: string): string => {
    const labels: Record<string, string> = {
      pain_acuity: 'Real demand',
      money_provability: 'People will pay',
      defensibility: 'Hard to copy',
      build_feasibility: 'You can build this',
      automatability: 'Runs without you',
    };
    return labels[key] ?? checkForGate(key)?.name ?? key.replace(/_/g, ' ');
  };

  // Back-to-top visibility, revealed after scrolling past the hero (~600px).
  const [showBackToTop, setShowBackToTop] = React.useState(false);
  React.useEffect(() => {
    const onScroll = () => setShowBackToTop(window.scrollY > 600);
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  // N2: track viewed pack for the personalised "Based on your browsing" row on
  // the home page. The original implementation used localStorage, but the lint
  // rule forbids it (XSS-exfiltratable). The pack detail page is server-rendered,
  // so we set the cookie server-side in getServerSideProps; no client-side
  // tracking is needed.
  // (See the cookie write in getServerSideProps below.)

  const providerLabel = provider === 'stripe' ? 'Stripe' : 'Paddle';
  const priceLabel = formatPriceForMarket(pack.price, currency);

  // WHAT THE PRICE BUYS, PER UNIT. See the note at its render site for why this replaced the
  // modelled multiple. Stated in GBP for every buyer because GBP is what is actually debited
  // (`formatChargeNote` tells a non-GBP buyer the same thing against the button), so this is one
  // figure that does not move with the display currency and cannot drift from the charge.
  const perSource =
    typeof pack.pricePence === 'number' &&
    typeof pack.sourceCount === 'number' &&
    pack.sourceCount > 0
      ? `£${(pack.pricePence / pack.sourceCount / 100).toFixed(2)}`
      : null;

  const notifyHref =
    `mailto:${LEGAL.supportEmail}` +
    `?subject=${encodeURIComponent(`Notify me when "${pack.title}" opens`)}` +
    `&body=${encodeURIComponent(`Please email me the moment this pack is available to buy: ${pack.title} (${pack.id}).`)}`;

  // The buy box no longer renders modelled economics (email §4, Option A -- recommended).
  // The financial model is a document inside the pack (`04_Financial_Model.md`), and showing a
  // buyer one set of "if these inputs hold" numbers next to a £79 button contradicts the
  // "no invented revenue" promise the page leads with. The fields still arrive on the wire and
  // are still rendered inside the pack; what is gone is the buy-box presentation of them.

  // The survival line in the guarantee list. Four of the 61 packs listed on 2026-08-06 are at
  // 7/8 or 6/8, so "Survived all N checks" is not a safe phrasing to apply unconditionally: on
  // those it would claim a clean sweep the dossier does not support. Partial results say so.
  const panelChecks = parseCheckCounts(pack.qaVerdictSummary);
  const checksLine = !panelChecks
    ? 'Survived every check'
    : panelChecks.cleared === panelChecks.total
      ? `Survived all ${panelChecks.total} checks`
      : `${panelChecks.cleared} of ${panelChecks.total} checks cleared`;

  // The same fact as `checksLine`, as a sentence, for the methodology disclosure further down.
  //
  // That disclosure shipped the literal "This one survived all 9." The denominator is
  // lane-dependent, so a fixed 9 was false for 60 of the 63 packs measured on 2026-08-06
  // (6/6 x40, 8/8 x15, 7/8 x4, 9/9 x3, 6/8 x1 -- see `__tests__/fixedCheckCount.test.ts`), and on
  // the five 7/8 and 6/8 packs it claimed a clean sweep their own dossier refutes, on the page
  // that asks for the money. Derived here for the reason `checksLine` above is derived: this page
  // cannot know the denominator until it has read the pack.
  const outcomeSentence = !panelChecks
    ? 'This one cleared every check it faced.'
    : panelChecks.cleared === panelChecks.total
      ? `This one survived all ${panelChecks.total}.`
      : `This one cleared ${panelChecks.cleared} of ${panelChecks.total}.`;

  // Shared checkout body, rendered in the desktop sticky card and the mobile purchase bar.
  // Deliberately an element VALUE, not a component defined during render: a component declared
  // inline is a new type on every render, so React unmounts and remounts the subtree and the
  // checkout button loses its state mid-purchase. The same element object can be placed twice,
  // React instantiates it independently at each position.
  const checkoutBody = (
    <>
      {/*
       * ONE price, ONE guarantee list, ONE economics surface (brand v3, 2026-08-06).
       *
       * This panel previously stacked, in order: an uppercase letterspaced caption, a `font-black`
       * price, a green `bg-success/5` reassurance box, a green `rounded-full` "Survived 6 checks"
       * pill, a "Modelled economics" box, a "What it has to earn back" box restating the same
       * three numbers as a division, the buy button, an identity note, an add-to-basket, a
       * three-row feature list, and a refund paragraph -- thirteen elements, of which four were
       * green, before the buyer reached anything they could click.
       *
       * Both economics boxes said the same thing from the same fields, so they collapse into one
       * collapsed details: a buyer weighing £79 wants the price and the guarantee in the fold,
       * and the model when they go looking for it. Nothing sourced was deleted -- the caveat
       * travels with the figures, as it must.
       */}
      {/* "once" is gone from beside the number. The label two lines up already says "One-time
          price", so the rail read `One-time price / £29 once` -- the same fact, twice, in three
          words, on the most scrutinised element of the page. Saying a thing twice does not make
          a nervous buyer more confident that there is no subscription; it makes them re-read the
          sentence looking for the catch. */}
      {/* THE ANCHOR, ABOVE THE PRICE. What it costs to have this work done, before what it costs
          to buy it done. The figure, its source and the reason a day rate is the right comparison
          all live in `RESEARCH_RATE_ANCHOR` (lib/config.ts) -- including why the modelled multiple
          that used to carry this job is deleted rather than retuned.
          No number of days is stated. How long a contractor would take to reproduce this pack is
          not a fact we have, and the anchor does not need it: the reader compares a day to a pack
          and reaches their own answer. */}
      <p className="text-caption leading-relaxed text-subtle">
        Having this researched for you starts at{' '}
        <span className="font-medium text-text">{RESEARCH_RATE_ANCHOR.dayRateLabel} a day</span>{' '}
        <a
          href={RESEARCH_RATE_ANCHOR.url}
          target="_blank"
          rel="noopener noreferrer"
          className={textLinkClass()}
        >
          ({RESEARCH_RATE_ANCHOR.source})
        </a>
        . This is it already done.
      </p>
      <span className="mt-4 block text-caption text-subtle">One-time price</span>
      <div className="mt-1">
        <PriceText className="text-h2">{priceLabel}</PriceText>
      </div>
      {/* The hedge sits with the number it hedges. The old note ("£49 at today's rate") named
          the wrong figure -- £49 is the catalogue's source price, the converted one is what the
          rate produced -- and it sat below a green guarantee box, four elements away from the
          price. */}
      {currency !== 'GBP' && (
        <p className="mt-1 text-caption text-subtle">{formatApproxNote(currency)}</p>
      )}

      {/*
       * THE PRICE, DIVIDED BY THE WORK. (Founder, 2026-08-16: the price sits there naked.)
       *
       * A figure alone is not expensive or cheap, it is unreadable, and this rail gave the reader
       * nothing to read it against. What was there instead is the reason this is careful: the rail
       * printed "the pack's own model puts month one at 13x what the pack costs". That number is
       * not too big, it is the wrong KIND of number -- a modelled month of TURNOVER set against a
       * one-off PRICE, two things that are not comparable, so retuning the bound that let it
       * through (`CREDIBLE_MULTIPLE_CEILING`) would not have fixed it. It is gone.
       *
       * What replaces it is arithmetic on two numbers already printed on this page: the price, and
       * the source count in the evidence row under the title. The reader can multiply it back and
       * get the price, which is the only test a sceptic actually runs, and it is a claim about what
       * they are buying rather than a forecast of what they might earn. It invents nothing, it
       * cannot flatter (there is no branch where it appears only when the figure is pretty), and it
       * renders nothing at all when either input is missing.
       *
       * GBP for every buyer, on purpose: GBP is the currency debited, `formatChargeNote` says so
       * against the button, and a per-unit figure derived from a converted display price would move
       * with the FX table while the charge did not.
       */}
      {perSource && (
        <p className="mt-2 text-caption leading-relaxed text-subtle">
          {pack.sourceCount} cited sources behind it, <span className="font-medium text-text">{perSource} each</span>.
        </p>
      )}

      {/*
       * WHY THIS NUMBER, against the number.
       *
       * The rail printed a price and then eight lines of reassurance about refunds and downloads,
       * which answers "is it safe to pay" and never answers "why is it this". A buyer looking at
       * £29 beside a £199 pack on the same shelf asks the second question first, and the page that
       * answers it was /pricing -- a click away, from a rail that gave no reason to go.
       *
       * The claim is the engine's actual rule, not a sales line: `pricing.py` picks a rung on a
       * ladder declared in `config.yaml listing.pricing` from (ambition_tier x market), so the
       * price genuinely tracks how big the idea could get and which market it targets, and
       * genuinely does not track document count -- every pack ships the same eight documents. It
       * is
       * one sentence and a link because the rail is the wrong place to argue it at length; the
       * full argument, with the ladder, is on /pricing where the reader chose to read it.
       *
       * Deliberately NOT stated as this pack's own tier: `PackDetails` carries no ambition tier
       * (lib/api/client.ts), so naming a rung here would be a number the page cannot source.
       */}
      <p className="mt-2 text-caption leading-relaxed text-subtle">
        Set by how big this idea could get and the market it targets, never by the size of the
        pack.{' '}
        <Link href="/pricing" className={textLinkClass()}>
          See the ladder
        </Link>
        .
      </p>

      {/* The three terms of the sale, as three plain lines. Only the tick is coloured, and only
          because the survival line is the one claim here that IS a check result -- so it states
          this pack's real count (`parseCheckCounts`), not the flat "all 6" it used to claim.
          Packs whose summary does not parse say "every check", which is true of anything listed
          without asserting a number the page cannot back. */}
      <ul className="mt-5 space-y-2.5 border-t border-border pt-5">
        <li className="flex items-center gap-2 text-meta text-muted">
          <Icon name="shield" size={16} className="flex-none" />
          14-day money back, no questions asked
        </li>
        <li className="flex items-center gap-2 text-meta text-muted">
          {/* §3.3. The shield above this line stays lucide on purpose: a refund window is a
              commercial policy we chose, not something the engine ruled on. This line is the
              ruling, so it gets the verdict mark. That is where the boundary sits. */}
          <Glyph name="survived" className="mt-0.5 text-success" />
          {checksLine}
        </li>
        <li className="flex items-center gap-2 text-meta text-muted">
          <Icon name="download" size={16} className="flex-none" />
          Instant download the moment you pay
        </li>
      </ul>

      {checkoutError && (
        <div className="mt-4 rounded-md border border-danger bg-danger-bg p-3 text-caption text-danger-strong">
          {checkoutError}
        </div>
      )}

      {canCheckout ? (
        <>
          {/* US-1: the pack detail page's primary buy action is the canonical <PackBuyButton>.
              The page owns `usePackCheckout`, so it passes the buy flow down. The button does
              NOT call the hook itself, which would split the overlay state across two instances. */}
          <div className="mt-5">
            <PackBuyButton
              pack={pack}
              variant="detail"
              buy={handleBuy}
              checkingOut={checkingOut}
              canCheckout={canCheckout}
              currency={currency}
              className="w-full"
            />
            {/* The charge disclosure goes here, against the button, because this is the moment
                the buyer commits. The CTA quotes their currency; the debit is in GBP; both facts
                are on screen at the point of decision rather than one of them being implied. */}
            {currency !== 'GBP' && (
              <p className="mt-2 text-caption leading-relaxed text-subtle">
                {formatChargeNote(pack.price, currency)}
              </p>
            )}
          </div>
          {/* Secondary on purpose: buying this one pack stays a single click above. The basket is
              only a gain for someone who wants several, so it never sits in front of the direct path.

              `size='link'` rather than the default full-width secondary button. Two stacked
              full-width blocks made the rail read as a choice between two comparable actions on a
              single £29 item, and the second one serves the rarer buyer. Deleting it was the other
              option and was rejected as silent feature removal: multi-pack buying still works, is
              still labelled in words, and is still one click. Only its visual weight changed. */}
          <div className="mt-3">
            <AddToCartButton
              size="link"
              line={{ id: pack.id, title: pack.title, price: pack.price, pricePence: pack.pricePence }}
            />
          </div>
          {/* Under the button, not above it: the address only matters once the buyer has decided,
              and putting an account-shaped sentence in front of the price is how a storefront
              teaches guests that they need an account. They do not. */}
          <BuyerIdentityNote className="mt-3 text-caption leading-relaxed text-subtle" />
          {/* THE FREE SAMPLE, AT THE MOMENT OF THE DECISION (founder, 2026-08-16: "the free
              sample is buried"). It was one link inside "The receipts", ~1,000px below the buy
              button and after the sources list, so the only reader who found it was one already
              convinced enough to read that far -- the opposite of the reader it is for. It MOVED
              here rather than being duplicated: two live entry points to the same sample is how a
              page ends up arguing with itself about which one is the offer.
              Deliberately a text link under the button, not a second button: this is
              objection-handling for the buyer who is not ready, and giving it equal weight to Buy
              turns one decision into two. No lift figure is claimed for the placement -- the trial
              literature to hand benchmarks free trials, not link position, and inventing a number
              on the page that sells sourced numbers is the one thing this rail may not do. */}
          <p className="mt-3 text-caption leading-relaxed text-subtle">
            Not ready?{' '}
            <Link href="/sample" className={textLinkClass()}>
              Read a full pack free
            </Link>{' '}
            and see the depth before you pay.
          </p>
        </>
      ) : (
        <>
          <a
            href={notifyHref}
            className={buttonClasses({ size: 'lg', fullWidth: true, className: 'mt-5' })}
          >
            Notify me when this opens
          </a>
          <p className="mt-2 text-caption leading-relaxed text-subtle">
            Checkout is opening shortly. Tap to get a single email the moment this pack goes live.
          </p>
        </>
      )}

      {/* Outside the canCheckout branch on purpose: the pack most worth opening is the one that
          cannot be sold yet. Renders nothing for every visitor who is not the founder. */}
      <FounderPreviewLink packId={pack.id} className="mt-4" />

      {/*
       * THE NUMBERS LIVE IN THE PACK (email §4, Option A -- recommended).
       *
       * The buy box previously rendered modelled economics -- Month 1 revenue, LTV:CAC, payback --
       * as either an open set of figures or a collapsed disclosure. The email's analysis was that
       * a modelled LTV:CAC of 30.7× and a Month 1 revenue of £1,152 contradict the homepage's "no
       * invented revenue" promise, and read as fantasy to anyone who has operated. The financial
       * model is a document inside the pack -- `04_Financial_Model.md` -- and selling its existence
       * is the right level of detail for the buy box. Numbers shown here are computed from cited
       * inputs; a value the page cannot source is not rendered.
       */}
      {/*
       * THE PRICE, AGAINST SOMETHING. (Reinstates one line of what the note above removed.)
       *
       * The note above is right that a "Modelled economics" dashboard of three figures beside a
       * buy button reads as fantasy to anyone who has operated, and that box is not coming back.
       * But removing it left the rail with a cost and nothing to weigh it against: eight lines
       * about refunds and downloads answer "is it safe to pay" and never answer "is it worth it".
       *
       * So: the RATIO, in a sentence, and nothing else. It is the one form of this number that
       * survives every objection the note raised --
       *   - it is not a revenue promise, it is a comparison to the price on the same card;
       *   - `paybackEquation` refuses ranges, refuses unparseable figures, and returns null when
       *     the modelled month 1 does not even cover the pack price, so it cannot become a widget
       *     that appears only when the numbers flatter (lib/payback.ts:56-65);
       *   - it invents nothing: `month1Revenue` is computed in `artifacts.py::_financial_snapshot`
       *     from the pack's verified inputs, and the only new operation is the division;
       *   - and it is a RATIO, so it is currency-invariant. Stating it as money would have put a
       *     GBP figure beside an FX-converted price label, which is the drift `formatChargeNote`
       *     exists to prevent.
       *
       * The sentence points at `04_Financial_Model.md` rather than elaborating, because the rail
       * is the wrong place to argue economics at length -- that document IS the argument.
       */}
      {/* THE MODELLED MULTIPLE IS GONE (founder, 2026-08-16). It rendered "month one at 13x what
          the pack costs" -- a modelled month of turnover divided by a one-off price, which is a
          category error rather than an overstatement, so the ceiling in `lib/payback.ts` that let
          13 through was never the defect. The rail still answers "why this number": the per-source
          line sits against the price above, and the financial model is still sold as a document
          rather than quoted as a promise, which is the sentence below. */}
      <p className="mt-6 text-caption leading-relaxed text-subtle">
        The workings are the fourth document, and its arithmetic is computed rather than written.
      </p>

      <p className="mt-6 text-caption leading-relaxed text-subtle">
        {/* WAS "What couldn't be verified is marked absent, never invented." Same fact, stated as
            a promise the reader gets rather than as a confession of what we could not do. The
            page had eleven negations before this one; this is the cheapest to invert without
            losing a word of its meaning. */}
        {/* "every input sourced" removed 2026-08-13 for the same reason as the line above: the
            financial model's inputs are assumptions, listed as assumptions, with no per-input
            citation (artifacts.py:152). What survives is true and is still the selling point. */}
        The numbers are in the pack. Pricing mechanics and unit economics, the assumptions behind
        them listed in full, and anything the research could not stand up is marked so.
      </p>

      <p className="mt-6 text-caption leading-relaxed text-subtle">
        {/* Secure checkout named where it is relevant, in a sentence, instead of as a third
            icon row. */}
        Secure checkout via {providerLabel}. {PACK_DISCLAIMER} See our{' '}
        <Link href="/refund" className={textLinkClass()}>
          refund policy
        </Link>
        .
      </p>
    </>
  );

  // The one sentence under the h1. See the docblock at its render site for why it is `oneLine`
  // and not `subhead`: the shelf can only show `oneLine`, so it is the string the buyer clicked.
  const lead =
    pack.subhead && (!pack.oneLine || isTruncated(pack.oneLine))
      ? pack.subhead
      : repairTruncation(pack.oneLine);

  return (
    <MarketingLayout>
      <Seo
        title={`${pack.title} · A business idea that survived our filter`}
        description={pack.oneLine || undefined}
        ogType="product"
        ogImagePath={packOgImagePath(pack.id)}
        ogImageAlt={`${pack.title}, a researched business pack from Mumchimp${pack.price ? ` (${pack.price})` : ''}`}
        jsonLd={graph(
          productJsonLd(pack),
          // The trail Google renders in place of the raw URL, so a result reads
          // "Mumchimp › Business ideas › <pack>" instead of a 16-hex-character id.
          breadcrumbNode([
            { name: 'Mumchimp', path: '/' },
            { name: 'Business ideas', path: '/ideas' },
            { name: pack.title, path: `/pack/${pack.id}` },
          ]),
        )}
      />

      {clientSecret && (
        <EmbeddedCheckoutPanel
          clientSecret={clientSecret}
          title={pack.title}
          onClose={closeOverlay}
          onUnreachable={handleEmbeddedUnreachable}
        />
      )}

      <Section bg="bg" width="6xl" className="!pt-8 !pb-24">
        {/* Breadcrumb */}
        <Breadcrumbs
          items={[
            /* "Catalogue". The header nav, the footer, the hero eyebrow and the page title all
               say Catalogue; this one crumb said Catalog, on a UK-first storefront that prices in
               £ and sells packs about Section 46 notices and DVSA inspections. A stranger does
               not consciously register the spelling -- they register that the site was assembled
               by more than one hand, on the page where they are about to enter a card number. */
            { href: '/', label: 'Catalogue' },
            { href: '/ideas', label: 'Browse by category' },
            // Was `{ href: '#', label: pack.title }`. The title was rendered three times inside
            // the fold (breadcrumb, cover caption, h1) on a page where titles run past 100
            // characters, so the trail was competing with the headline instead of locating it.
            // The trail now ends where a trail should: the section this pack sits in.
            { href: '#', label: cat.tagged ? cat.label : 'Pack' },
          ]}
        />

        {/* There was a second, bolder `<Link href="/">Back to catalog</Link>` on the line below
            this trail, commented "prominent, always visible". It pointed at the same URL as the
            first crumb, one line above it, and rendered heavier than the crumb it duplicated.
            desktop-pack-fold.png (2026-08-06) showed the money page opening on two rows of
            navigation before anything about the pack. One trail, one link per destination. */}

        <div className="mt-6 flex flex-col gap-12 lg:flex-row">
          {/* Left: Content */}
          <div className="flex-1">
            {/*
             * Header block (brand v3, 2026-08-06). Three facts, then the title.
             *
             * What went: a `border-l-[3px] border-l-primary` rule holding an uppercase letterspaced
             * "SURVIVED SIX CHECKS" badge, and, below the title, a four-item icon row that printed
             * "{n} sources cited" while `EvidenceExcerptPlate` printed the same count immediately
             * above it. One fact, rendered once, in the data voice.
             */}
            {/*
             * THE MASTHEAD STRIP IS REMOVED (2026-08-15). It was a 96px `bg-ins-bg` band carrying
             * a generated `PackMark`, and it is the fourth and last near-black block to go under
             * the founder's 2026-08-14 ruling ("Remove the black media block until there is real
             * imagery for it", docs/SITE_SPEC_PROGRAM.md:1007). The other three were on the shelf;
             * this one was on the product page, which is why leaving it would have been the worse
             * outcome of the two -- a shelf of pale text cards opening onto a near-black hero is a
             * bigger discontinuity than the one being fixed.
             *
             * ITS OWN DOCBLOCK IS WHY IT GOES, and the argument is worth keeping. It ran to six
             * paragraphs, and every one of them tuned what to draw ON the block: the ground
             * (`cat.tint` -> `--ins-bg`), the ink (`--ins-dim` at 0.88, composited to #2A2E33),
             * the axis (`down`, because bands drawn `across` in a wide box are "the text-skeleton
             * idiom"), the radial lift, the decision to keep labels off it. Six corrections, each
             * one sound, none of them answering whether a shop with no photography should be
             * drawing a frame for photography it does not have.
             *
             * THE MORPH GOES WITH IT. `view-transition-name` needs both halves; the shelf's lead
             * card no longer renders one either (pages/index.tsx), so this is a matched removal
             * rather than a dangling source. `PackMark` is untouched and still exported --
             * `AccountPanel` renders it -- so a future imagery decision has the component intact.
             *
             * NOTHING IT STATED IS DROPPED, because it stated nothing: the sector is carried by
             * the breadcrumb's last crumb directly above, in words, and the strip deliberately
             * held no label at all. What is left in its place is the h1, which is what the fold
             * was always for.
             */}
            {/* `PackCover` was here, a 44px bordered strip holding the sector chip, the market and
                "№ 08B220". It is gone from the fold, and each of its three facts is accounted for
                rather than dropped:

                  - THE SECTOR CHIP was a duplicate. The breadcrumb directly above already ends on
                    `cat.label` (see the trail above, whose last crumb is exactly this string), so
                    "Care and benefits claims" rendered twice inside ~120px, once bold and once
                    tinted. The trail is the one that locates the pack, so the chip is the copy
                    that goes.
                  - THE MARKET moved into the evidence line below, which is where the page's other
                    mono facts already live.
                  - THE DOSSIER NUMBER was `pack.id.slice(0, 6)`, a TRUNCATED id presented as a
                    product number. The full, untruncated reference is already on this page in
                    `EvidenceExcerptPlate` ("dossier:08b22037fc2afc07"), so the strip was showing a
                    worse copy of an identifier the page states properly a few inches lower. A
                    buyer quoting a reference in a support email is better served by the complete
                    one.

                `PackCover` itself is untouched and still exported; this page was its only caller,
                so nothing else moves. */}

            {/* No `md:text-display` (48px). Titles here average ~90 characters, so at 48px the
                h1 alone consumed ~400px and was still unfinished at the fold. One step, 32px.
                24px on a phone, for the same reason one step further down: 32px on a 390px screen
                gave `IEPBlueprint, the parent's tool that turns your child's assessment into a
                legally-strong IEP service request...` eight lines, and it was STILL cut off by the
                sticky buy bar (mobile-pack-fold.png, 2026-08-06). The title is the longest string
                on the page, not a slogan, so it is the one headline that has to step down. */}
            <h1 className="text-h2 font-semibold text-text md:text-h1">{pack.title}</h1>
            {/* THE LEAD IS NEVER A CUT STRING.
                `oneLine` is truncated at 150 characters by the publish path on 34 of the 63 live
                packs (see `lib/copy.ts` for the measurement and `bridge.py` for the cause), and
                this paragraph is the first sentence a buyer reads about the product, four inches
                above the buy button. It rendered as `...under that council's own rules...`.

                Two different repairs, because two different situations:
                  - There is a `subhead`: the cut sentence is dropped outright and the subhead is
                    the lead. Nothing is lost -- the subhead is a complete sentence written for
                    exactly this slot, and the full description is in the sections below.
                  - There is no `subhead`: dropping it would leave the title with no sentence
                    under it at all, so the cut is repaired back to a word boundary instead. */}
            {/* ONE LEAD PARAGRAPH, NEVER TWO (2026-08-15, brief item 8) -- BUT IT IS THE SENTENCE
                THE BUYER CLICKED (2026-08-16, founder: the cards carry a description that is
                missing on the pack page, "very confusing").

                #225 resolved the double paragraph by keeping `subhead` whenever one exists, on the
                reasoning in the docblock above: `oneLine` was cut at 150 characters on 34 of 63
                packs, so the complete sentence won. That premise has expired at the source.
                Measured against the live catalogue on 2026-08-16 (61 packs, `api.mumchimp.com`):
                61 of 61 `oneLine` values end in a full stop, none carries a truncation mark, and
                the longest is 268 characters. The publish path is no longer cutting them, so what
                the rule does today is swap an intact sentence for a different one on the 52 packs
                that carry a subhead.

                The shelf cannot absorb that swap. `PackRow` heads every card with
                `cardLine(repairTruncation(pack.oneLine))`, and `oneLine` is the ONLY description
                `/catalog` returns -- there is no `subhead` in the catalog payload at all -- so the
                line a buyer clicks is by construction the opening of `oneLine`, and the page they
                landed on did not contain it. Measured before this change: the card's sentence was
                absent from 45 of 60 live pack pages.

                So the rule stands and the winner flips. The subhead leads only when `oneLine` is
                missing or comes through cut, which is the case the docblock above was written for.
                Nothing is lost when it stands down: its audience framing is the `whoPays` row
                below, and the full description is in the sections under that. */}
            {lead && <p className="mt-4 max-w-[60ch] text-body text-muted">{lead}</p>}

            {/* WHY THIS IS WORTH MONEY, STATED ONCE, AND THE SAME ON EVERY PACK.
                The page argues rigour from the first screen (checks, sources, survival) and never
                says what the rigour spares the reader, so a visitor who has not already decided to
                start a business has no reason to care that the vetting was thorough.

                It is a STATIC line, and that is the whole design of it. A per-pack version would
                have to assert something about this idea's stakes -- hours saved, money at risk --
                which is a figure the engine does not compute and the page could not cite, so it
                would be the first unsourced claim on the money page. This one asserts nothing
                about the pack: it describes what the product category is, in the second person,
                and every word of it is already backed by the sections below. Also carries no
                number, so there is nothing here for `source-or-die` to demand a citation for.

                REWRITTEN 2026-08-16. The previous wording ("is NOT having it. IT IS the time...")
                defined the product by what it is not, which is the exact antithesis construction
                `prompts/style/voice.md` now bans in generated prose; a hardcoded line on every
                pack page is the one place a style rule cannot be enforced by the linter, so it
                is enforced here by hand. It also opened on a negation, which read as zero
                content. Say what the buyer GETS, in the affirmative, naming only things that
                literally appear in the sections below. */}
            <p className="mt-4 max-w-[60ch] text-meta leading-relaxed text-muted">
              You get the checking already done: the evidence behind the idea, the sources it came
              from, and the objections it survived, all open below so you can judge them yourself.
            </p>

            {/* The evidence line: what stands behind the listing, in mono because every item on it
                is a quantity or a date. Renders nothing it cannot state.

                The check count is this pack's real one (`parseCheckCounts`), not the hardcoded
                `6/6` that used to sit here. Two defects went with it: the number was wrong for 21
                of 61 listed packs, and `verdict.summary` -- which is only ever the string
                "8/8 checks cleared · 33 sources cited" out of `bridge.py::_trust_fields` -- was
                rendered as a paragraph directly beneath, so the page stated the same two facts
                twice and disagreed with itself about one of them. */}
            {evidenceTokens.length > 0 && (
              <p className="mt-5 flex flex-wrap items-center gap-x-1.5 font-mono text-caption text-subtle">
                <Glyph name="source" className="text-success" />
                {evidenceTokens.map((token, i) => (
                  <React.Fragment key={token}>
                    {i > 0 && <span aria-hidden="true">·</span>}
                    <span>{token}</span>
                  </React.Fragment>
                ))}
              </p>
            )}

            {/* The source-domain roster. See `sourceHosts` for why this is the only form of social
                proof on the page and why it is deduped by host.

                Not mono, unlike the evidence line directly above it: that line is mono because
                every item on it is a quantity or a date, and a domain is neither. Four is the cap,
                because the job is "you have heard of these", not an inventory, and the inventory
                is the clickable `CitationList` further down. Plain text, not links, for the same
                reason: two clickable copies of one source list on one page is how a visitor ends
                up wondering which one is the real one.

                KNOWN TENSION, recorded rather than hidden: `EvidenceExcerptPlate` further down
                carries its own chip for the one line it quotes (`EvidenceExcerptPlate.tsx:70-76`,
                "One claim, one source row"), and that host will usually also appear in this
                roster, so one domain can be named twice on a long desktop screen. Accepted
                because the two are answering different questions -- this line is "who stands
                behind the pack", the chip is "who said that particular sentence" -- and because
                the alternative was for this element to duplicate `firstCitedLine`'s selection
                logic in order to subtract one host from a list of four. If the repetition reads
                badly on a real screen, delete this element and not the chip: the chip is
                attribution, this is decoration on top of it. */}
            {sourceHosts.length > 0 && (
              <p className="mt-3 max-w-[60ch] text-caption leading-relaxed text-subtle">
                Sourced from{' '}
                <span className="font-medium text-muted">
                  {sourceHosts.slice(0, 4).join(', ')}
                </span>
                {sourceHosts.length > 4 && `, and ${sourceHosts.length - 4} more`}
              </p>
            )}

            {/*
             * THE SELECTIVITY PLATE -- the page's one typographic peak, and the one place the
             * rigour is stated as confidence instead of as a disclaimer.
             *
             * TWO DEFECTS IT ANSWERS, both measured on the live page 2026-08-08
             * (mumchimp.com/pack/08b22037fc2afc07):
             *
             *   1. NO HIERARCHY. Every element on the money page rendered at body weight -- the
             *      only things above `text-body` were the h1 and four section headings. A page
             *      with no peak reads flat however good the content is, which is most of what
             *      "visually underwhelming" was pointing at.
             *
             *   2. RIGOUR WRITTEN AS NEGATION. Counted over the rendered text of that page:
             *      `kill` x6, `never` x5, `thin` x4, `killed` x2, `attack` x2, `could not` x2,
             *      `couldn't` x2, plus "not a promise of business success", "we don't guarantee
             *      any business outcome" and the footer disclaimer. The dominant register of the
             *      page asking for money was self-doubt, and a reader finishes that page thinking
             *      even we do not believe in this one.
             *
             * The fix is not to soften a single one of those lines -- they are true and they are
             * the moat. It is that the SAME fact has a confident face that was sitting unused in
             * the footer: the reject rate. "94% were killed" and "this is one of the survivors"
             * are one number read from either end, and only the second one is an argument for
             * buying. `RESEARCH_STATS` is the shared derivation, so this cannot drift from
             * /kill-log or /how-it-works the way the hand-rolled versions did (lib/stats.ts:9-21).
             *
             * The plate used to lead with "1 / 80", the survivor count. That figure is gone from
             * the site (lib/stats.ts, founder directive 2026-08-13): 80 ideas cleared the gates
             * and 50 are on the shelf, so printing 80 anywhere obliged the copy to explain the
             * difference. The argument for buying does not need it. "94.5% of 1,444 died on cited
             * evidence, and this one did not" is the same fact from the end we can prove, and both
             * figures come from `RESEARCH_STATS`, so it cannot drift from /kill-log.
             */}
            {/* THE FIGURE IS LABELLED, because unlabelled it said the opposite of the truth.
                `94.5%` sat alone, in the largest type on the page, immediately left of the words
                "This one came through the filter" -- and a number read next to that sentence reads
                as the share that came THROUGH. It is the share that was killed. The caption is not
                decoration on a big number; it is the difference between a 94.5% pass rate and a
                94.5% kill rate, and the second one is the argument. */}
            <div className="mt-8 flex flex-col gap-x-6 gap-y-3 rounded-md border border-border bg-surface p-6 sm:flex-row sm:items-center">
              {/* FLIPPED TO THE SURVIVOR END (founder, 2026-08-16: the scarcity is never used).
                  The plate led with the kill rate and then spent its second paragraph turning it
                  round -- and the docblock above had already worked out why that was wrong: "94%
                  were killed" and "this is one of the survivors" are one number read from either
                  end, and only the second is an argument for buying. It printed the first anyway.
                  A reader scanning a rail of figures gets the headline and not the correction.
                  The bound, not a rate to one decimal: see `survivorBoundLabel` in lib/stats.ts
                  for why rounding UP is what keeps the 2026-08-13 directive intact. The survivor
                  COUNT is still nowhere on this page and still cannot be derived from it. */}
              <p className="flex-none">
                <span className="block font-mono text-h1 font-semibold leading-none text-text">
                  {RESEARCH_STATS.survivorBoundLabel}
                </span>
                <span className="mt-2 block font-mono text-caption text-subtle">
                  or fewer get through
                </span>
              </p>
              <p className="max-w-[52ch] text-meta leading-relaxed text-muted">
                <span className="font-medium text-text">This is one of them.</span>{' '}
                {RESEARCH_STATS.researched.toLocaleString('en-GB')} ideas went through the filter
                and {RESEARCH_STATS.rejectRateLabel} of them died on cited evidence.{' '}
                <Link
                  href="/kill-log"
                  className={textLinkClass()}
                >
                  Read what killed them
                </Link>
                .
              </p>
            </div>

            {/* PROOF, BUT AFTER THE THING IT IS PROOF OF.
                This plate opened the page -- above the breadcrumb's own product, above the title,
                above every word saying what is for sale. What a stranger met first, verbatim from
                the built page at 1440 (2026-08-06):

                  "On top of that sits the legal pressure: councils can issue fixed penalty
                   notices of up to £400 for putting the wrong thing in a bin, under section 46A
                   of the Environmental Protection Act 1990."

                It begins "On top of that". It is an excerpt, so it is always a fragment of a
                longer argument, and lifted to the top of the page it has no antecedent -- the
                reader is shown the second half of a claim about a product they have not been
                told about yet. The argument for the slot was "proof, not decoration, in the prime
                visual position", and that is right about the CONTENT and wrong about the ORDER:
                evidence is only persuasive once the reader knows what it is evidence for.

                It moves down by exactly one block. Identity (title), promise (lead), scale
                (sources and checks), then the sample of the work itself -- still inside the first
                screen on desktop, still the largest object on the left column, and now reading as
                "here is a page of what you are buying" rather than as a stray quotation.
                Renders nothing when the pack has no sourced extract. */}
            <EvidenceExcerptPlate pack={pack} className="mt-8" />

            {/* US-6: the strongest case against the pack sits right under the title. The risk is
                the buyer's first test of whether to trust the work; surfacing it above the
                deliverables is the Mumchimp voice (refutational, not promotional). The buyer who
                reads the risk and buys is the buyer who is certain. Always visible, not collapsed.

                Now a warning-tinted plate with a 2px left rule rather than a bordered box under a
                mono-uppercase-letterspaced label: an amber all-caps heading on the money page read
                as a system alert about the listing rather than as our own argument against it. */}
            {verdict.risk && (
              <div className="mt-6 rounded-md border-l-2 border-l-warning bg-warning-bg py-4 pl-5 pr-5">
                <div className="flex items-center gap-2">
                  <Glyph name="pushed-back" className="text-warning-strong" />
                  <span className="text-meta font-semibold text-text">Where this could break</span>
                </div>
                {/* Also a SourcedLine: today `qaVerdictSummary` carries no URL, but the moment the
                    engine grounds a risk the page links it instead of printing it. An unsourced
                    string renders identically, so this costs nothing to leave in place. */}
                <SourcedLine className="mt-2 block max-w-[60ch] text-meta leading-relaxed text-muted">
                  {verdict.risk}
                </SourcedLine>
                <p className="mt-2 text-caption text-subtle">
                  The strongest case against the idea, with its source, also lives inside the pack.
                </p>
              </div>
            )}

            {/* Mobile purchase bar, keeps price + CTA above the fold on small screens */}
            <div className="mt-8 rounded-md border border-border bg-surface p-6 lg:hidden">
              {checkoutBody}
            </div>

            {/* Deliverables first: "what do I actually receive for £49" is the question that stalls a
                digital purchase, and it has to be answered before the trust argument. */}
            <div className="mt-12">
              <PackContentsSection
                heading="What’s inside your pack"
                lead={`The moment you pay, you download the whole pack. ${PACK_DOCUMENTS.length} documents, no drip feed, no login.`}
                sourceCount={pack.sourceCount}
              />
            </div>

            {/*
             * WHO RUNS IT -- moved ABOVE the two methodology disclosures.
             *
             * The order the page shipped was: deliverables, how we tried to kill it, how it
             * scores, and only then who this is for. That is the order of OUR interests. The
             * buyer's questions arrive as: what is it, could I do it, does it make money, is the
             * research real. "Could I do it" was the third-from-last thing the page answered, two
             * collapsed disclosures deep -- on the surface where the reader decides whether any
             * of the rest applies to them at all.
             *
             * The heading changed with the position. "Is this for you?" is a shopping question
             * about a document; "Could you run this?" is a question about the reader's own next
             * six months, which is the thing actually being sold. Nothing below it changed -- the
             * facts were always here, they were just filed under the wrong question, behind the
             * methodology.
             */}
            {(pack.market || pack.whoPays || pack.timeToFirstRevenue) && (
              <div className="mt-12">
                <h2 className="text-h2 font-semibold text-text">Could you run this?</h2>
                <p className="mt-2 max-w-[60ch] text-meta text-muted">
                  Behind the research is a business somebody has to actually operate. Here is who
                  they would be selling to, and how soon the first money arrives.
                </p>
                {/* The engine's own tags, in the buyer's words. Absent facets render nothing:
                    "Effort to build" used to print the legacy `effortTag` string, which was never
                    defined to mean how much of delivery is machine-doable (spec 2.3). */}
                <FacetChips pack={pack} className="mt-4" />
                {/*
                 * ONE SPEC SHEET, NOT THREE CARDS.
                 *
                 * These were three bordered boxes in a `sm:grid-cols-3` where two carried
                 * `sm:col-span-3`, so on any desktop width the grid was a lie: Market and Who pays
                 * each sat alone in a 976px box holding a label and one line, and the third took a
                 * third of a row on its own. Measured at 1440 on 2026-08-14, the block spent ~390px
                 * of height and three borders to state three fields.
                 *
                 * They are three fields OF ONE THING -- the business behind the research -- so they
                 * are a description list with the labels in their own column, which is the idiom
                 * this page already uses for the economics table below. A reader scanning for
                 * "who pays" now finds it down a rule of aligned labels instead of by reading three
                 * card headers of different widths.
                 */}
                <dl className="mt-6 divide-y divide-border overflow-hidden rounded-md border border-border bg-surface">
                  {pack.market && (
                    <div className="grid gap-1 p-5 sm:grid-cols-[9.5rem_1fr] sm:gap-6">
                      <dt className="text-caption font-medium text-subtle sm:pt-0.5">Market</dt>
                      <dd className="min-w-0">
                        <span className="text-meta font-semibold text-text">
                          {marketLabel(pack.market)}
                        </span>
                        {/* State it plainly: the research is about this jurisdiction, and the
                            pack is still sold in GBP. Leaving that implicit invites a refund. */}
                        <span className="mt-1.5 block max-w-[62ch] text-caption leading-relaxed text-muted">
                          The opportunity, its evidence and its economics are researched for this
                          market. The pack itself is priced and sold in GBP.
                        </span>
                      </dd>
                    </div>
                  )}
                  {pack.whoPays && (
                    <div className="grid gap-1 p-5 sm:grid-cols-[9.5rem_1fr] sm:gap-6">
                      <dt className="text-caption font-medium text-subtle sm:pt-0.5">Who pays</dt>
                      <dd className="min-w-0 max-w-[62ch] text-meta leading-relaxed text-muted">
                        {pack.whoPays}
                      </dd>
                    </div>
                  )}
                  {pack.timeToFirstRevenue && (
                    <div className="grid gap-1 p-5 sm:grid-cols-[9.5rem_1fr] sm:gap-6">
                      <dt className="text-caption font-medium text-subtle sm:pt-0.5">Time to first revenue</dt>
                      <dd className="min-w-0 text-meta font-semibold text-text">
                        {pack.timeToFirstRevenue}
                      </dd>
                    </div>
                  )}
                </dl>
              </div>
            )}

            {/* US-4: the six-check methodology collapses behind a details disclosure.
                On mobile (the primary surface), the buyer is not forced to read 200px
                of methodology before the deliverables. They can tap to expand if
                they care. The disclosure is open by default on lg+ where the page
                has the room. */}
            <details className="mt-12 group" open={undefined}>
              <summary className="cursor-pointer list-none text-h2 font-semibold text-text transition-colors hover:text-muted">
                <span className="inline-flex items-center gap-2">
                  <Icon name="arrowRight" size={16} className="transition-transform group-open:rotate-90" />
                  How we tried to kill it
                </span>
              </summary>
              <div className="mt-4">
                <p className="text-meta text-muted">
                  Each check is an attack, not a rubber stamp. An idea dies on the first check where cited evidence goes against it. {outcomeSentence} Finding nothing is not the same as finding a green light; see how each check works on{' '}
                  <Link
                    href="/how-it-works"
                    className={textLinkClass('font-medium')}
                  >
                    /how-it-works
                  </Link>
                  .
                </p>
                {/* WAS "...so the scores below show where this pack's case is strong and where it is
                    thin", directly above the six UNSCORED bullets that follow. The scored axes are
                    real and this page does render them, but in a different, collapsed details
                    further down, so the sentence pointed the reader at the one list on the page that
                    carries no scores at all and read as a promise the page then broke.

                    The scores are deliberately opt-in (US-4, see the disclosure below): the buyer
                    who wants the result meets the buy button first. That decision stands; what
                    changes is that the pointer now names where the scores actually are. */}
                <p className="mt-3 text-meta text-muted">
                  {/* THE COUNT A READER CAN SEE, RECONCILED WITH THE COUNT THE PAGE CLAIMS.
                      NOT "the six fronts": the check count is lane-dependent (6/6, 8/8, 7/8, 9/9
                      and 6/8 all occur live), which is why `fixedCheckCount.test.ts` exists and
                      why it failed on this sentence the moment it was written.

                      But the sentence then went to the opposite failure. The list below is
                      `COMMON_CHECKS` -- the ones that run on every idea in every lane -- and the
                      buy rail four inches away states this pack's OWN denominator. So the live
                      page said "7 of 8 checks cleared" above a list a reader can count to six,
                      and never closed the gap (verified on mumchimp.com/pack/08b22037fc2afc07,
                      2026-08-08). On a storefront whose pitch is that it checks its arithmetic,
                      an unexplained 6-vs-8 is the most expensive two digits on the page.

                      What is still NOT said, because the page cannot source it: WHICH check this
                      pack lost. `PackDetails` carries no per-check verdicts, so naming one would
                      be invention. The honest available facts are how many there were and where
                      the extra ones came from. */}
                  The {CHECKS.length} below run on every idea, whatever it is.
                  {panelChecks && panelChecks.total > CHECKS.length
                    ? ` This one's lane ran ${panelChecks.total - CHECKS.length} more on top, for ${panelChecks.total} in all.`
                    : ''}
                  {/* THE POINTER ONLY EXISTS WHEN ITS TARGET DOES.
                      "open How it scores further down" was unconditional, but that section is
                      guarded on `axes.length > 0`, and a pack whose `financialSnapshot` carries
                      no `N of 5` axes renders no such section. Verified against the live pack
                      08b22037fc2afc07 on 2026-08-08: its snapshot holds only the three financial
                      figures, so the page sent the reader down the page to a heading that was
                      never emitted. This is the same defect class as the 6-vs-8 two paragraphs
                      up -- the page asserting something about itself that it did not check. */}
                  {axes.length > 0 && (
                    <>
                      {' '}
                      For where this pack&rsquo;s case is strong and where it is thin, open{' '}
                      <span className="font-medium text-text">How it scores</span> further down,
                      weak bars included.
                    </>
                  )}
                </p>
                <ul className="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-2">
                  {CHECKS.map((check, i) => (
                    <li
                      key={check}
                      className="flex items-center gap-3 rounded-md border border-border bg-surface px-4 py-3"
                    >
                      {/* A numeral, not a tick: a green success mark on a static line reads as this
                          pack's verdict on that check, which is exactly what this page cannot know. */}
                      <span className="flex h-6 w-6 flex-none items-center justify-center rounded-sm border border-border bg-surface2 font-mono text-caption text-subtle">
                        {i + 1}
                      </span>
                      <span className="text-meta font-medium text-text">{check}</span>
                    </li>
                  ))}
                </ul>
                <Link
                  href="/how-it-works"
                  className="mt-5 inline-flex items-center gap-1.5 py-3 text-meta font-medium text-accent transition-colors hover:text-accent-hover"
                >
                  See how each check works
                  <Icon name="arrowRight" size={14} />
                </Link>
              </div>
            </details>

            {/* US-4: the scored axes collapse behind a details disclosure. The
                methodology is opt-in; the buyer who only cares about the
                result sees the buy button first, the methodology on demand. */}
            {/* OPEN BY DEFAULT, and no longer the risk plate's second home.
             *
             * Two changes, one cause: this page had no visual hierarchy. Every element on it was
             * body text at one weight, and the ONLY chart it owns -- these bars -- was the one
             * thing behind a click. US-4 collapsed it so "the buyer who only cares about the
             * result sees the buy button first", but the buy rail is `sticky top-24` on desktop
             * and a `lg:hidden` card in the fold on mobile, so it is on screen either way; the
             * disclosure was not protecting the CTA, it was hiding the page's only picture.
             *
             * It stays a `<details>` so it can still be collapsed, and so the summary keeps
             * carrying a heading a reader can scan to.
             *
             * The guard drops `|| verdict.risk`: the risk plate rendered here AND at the top of
             * the page (see "Where this could break" under the header), identical heading,
             * identical text, identical trailing sentence. Two copies of our own strongest
             * counter-argument reads as padding, which is the precise opposite of what stating
             * it is for. The top one is the one that stays -- it is above the deliverables,
             * where a buyer meets it before they have decided, which was the point of US-6. */}
            {axes.length > 0 && (
              <details className="mt-12 group" open>
                <summary className="cursor-pointer list-none text-h2 font-semibold text-text transition-colors hover:text-muted">
                  <span className="inline-flex items-center gap-2">
                    <Icon name="arrowRight" size={16} className="transition-transform group-open:rotate-90" />
                    How it scores
                  </span>
                </summary>
                <div className="mt-4">
                  <p className="max-w-[60ch] text-meta text-muted">
                    {/* WAS "Six things we measure", hardcoded, above a `dl` whose length is
                        `axes.length` -- a count the page reads off the snapshot and does not
                        control. Same defect class as the 6-vs-8 above, one scroll further down. */}
                    What we measure, scored. The strong ones are strengths. The weaker ones are
                    things you should know before you build, and they are left visible.
                  </p>

                {axes.length > 0 && (
                  <dl className="mt-6 grid grid-cols-1 gap-x-8 gap-y-4 sm:grid-cols-2">
                    {axes.map((a) => {
                      const tone =
                        a.value >= 4 ? 'bg-success' : a.value === 3 ? 'bg-text/40' : 'bg-warning';
                      return (
                        // Same `dlitem` / `definition-list` defect as /sample's scorecard, same fix:
                        // ONE wrapper div per pair is legal, a nested div and a non-dt/dd sibling
                        // are not. The bar lives inside <dd> and is absolutely positioned so it
                        // still spans the card; `pb-3` reserves the height `gap-1.5` + `h-1.5` used.
                        <div
                          key={a.label}
                          className="relative grid grid-cols-[1fr_auto] items-baseline gap-x-2 pb-3"
                        >
                          <dt className="text-meta font-semibold text-text">{axisLabel(a.label)}</dt>
                          <dd className="font-mono text-caption text-muted">
                            {a.value} / {a.outOf}
                            <span className="absolute inset-x-0 bottom-0 flex gap-1" aria-hidden>
                              {Array.from({ length: a.outOf }).map((_, i) => (
                                <span
                                  key={i}
                                  className={cx(
                                    'h-1.5 flex-1 rounded-sm',
                                    i < a.value ? tone : 'bg-border',
                                  )}
                                />
                              ))}
                            </span>
                          </dd>
                        </div>
                      );
                    })}
                  </dl>
                )}

                {/* The "Where this could break" plate that stood here is gone; it is rendered
                    once, under the page header, where the buyer meets it before deciding. */}
                </div>
              </details>
            )}

            {/* The per-pack table of contents. The generic four-asset breakdown is higher up the page. */}
            <div className="mt-12">
              <h2 className="text-h2 font-semibold text-text">The table of contents</h2>
              <p className="mt-2 max-w-[60ch] text-meta text-muted">
                Exactly what this pack covers, plus a blurred look at the document you receive.
              </p>

              {/* Blurred deliverable preview. Grey rectangles said "a document exists"; this
                  page's whole claim is that a SPECIFIC, sourced document exists, and a skeleton
                  is the one element on the page that could be identical for a pack with nothing
                  behind it. So the preview is now the pack's own text, the same headings and
                  sourced lines rendered elsewhere on this page, set as a document and blurred.
                  Blur is a legible-shape effect: what shows through is real structure, real
                  paragraph lengths, real tables. Nothing is invented to fill it; when there is
                  no real content to show, `PreviewDocument` renders the neutral skeleton. */}
              <PreviewDocument pack={pack} />

              {/* Per-pack contents only. The generic four-asset list now lives once, above, so it
                  cannot contradict this section. */}
              {pack.whatYouGet && pack.whatYouGet.length > 0 && (
                <ul className="mt-6 list-none space-y-3 p-0">
                  {pack.whatYouGet.map((item, i) => (
                    <li
                      key={i}
                      className="flex items-start gap-3 rounded-md border border-border bg-surface p-6"
                    >
           <span className="mt-0.5 text-caption font-medium text-subtle">
                        {String(i + 1).padStart(2, '0')}
                      </span>
                      <span className="text-meta leading-relaxed text-muted">{item}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {/* A look inside, real sourced lines lifted straight from the pack */}
            {pack.sampleExtract && pack.sampleExtract.length > 0 && (
              <div className="mt-12">
                <h2 className="text-h2 font-semibold text-text">A look inside</h2>
                <p className="mt-2 max-w-[60ch] text-meta text-muted">
                  Real, sourced lines taken straight from the pack. Every source below is a live
                  link: open one and check the claim before you buy.
                </p>
                {/* Peek inside: a page you are looking at the top of. The fade is over the page
                    itself, never over invented text, every line below is really in the pack, and
                    nothing is blurred to imply content that does not exist. */}
                <div className="relative mt-6 overflow-hidden rounded-md border border-border bg-surface">
                  <div className="flex items-center gap-2 border-b border-border bg-surface2 px-5 py-3">
                    <Icon name="briefcase" size={14} className="text-subtle" />
          <span className="text-caption font-medium text-subtle">
                      Extract · evidence record
                    </span>
                  </div>
                  {/* The claim, then the sources it stands on. Until this shipped these lines
                      printed "(source: https://...)" as plain text -- the page promised a
                      clickable source behind every claim and rendered zero anchors. The parse
                      happens at the render boundary (`lib/citations.ts`); the API contract for
                      `sampleExtract` is unchanged, so an email or a PDF of the same string still
                      reads correctly. */}
                  <ul className="list-none space-y-5 p-6 pb-16">
                    {pack.sampleExtract.map((line, i) => (
                      <li key={i} className="border-l-2 border-l-success pl-4">
                        <SourcedLine className="block text-meta leading-relaxed text-muted">
                          {line}
                        </SourcedLine>
                      </li>
                    ))}
                  </ul>
                  <div className="pointer-events-none absolute inset-x-0 bottom-0 h-24 bg-gradient-to-t from-white via-white/85 to-transparent" />
                  <span className="absolute inset-x-0 bottom-4 text-center text-caption font-semibold text-muted">
                    The rest of this section, and three more documents, are in the pack.
                  </span>
                </div>
              </div>
            )}

            {/* The receipts (email §4). The previous copy ended on "No hand waving, no vibes."
                which tried too hard for a voice that wins by understatement. The new copy is the
                same content in the same shape -- a count and a list of openable sources -- without
                the boast. */}
            <div className="mt-12 rounded-md border border-border bg-surface p-6">
              <div className="mb-3 flex items-center gap-2.5">
                <Glyph name="source" className="text-success" />
        <span className="text-caption font-medium text-subtle">The receipts</span>
              </div>
              {/* The count is GUARDED, and the "open these" instruction belongs to the block below
                  that actually renders the list. Unguarded, a pack with no `sourceCount` rendered
                  " sources, each cited..."; and the instruction sat OUTSIDE the
                  `openSources.length > 0` test below, so a pack with nothing openable printed
                  "Open any of these 0 now." followed by nothing at all. The block below already
                  gives the instruction once, against a list that exists. */}
              <p className="max-w-[60ch] text-meta leading-relaxed text-muted">
                {typeof pack.sourceCount === 'number' && pack.sourceCount > 0
                  ? `${pack.sourceCount} sources, each cited against the claim it supports.`
                  : 'Every claim in this pack is cited against the source it rests on.'}
              </p>

              {/* The proof, not the promise. The paragraph above is a claim; these are the actual
                  pages, openable before paying. The count is deliberately the number of sources
                  on THIS page, never `pack.sourceCount` -- see `openSources` above. */}
              {openSources.length > 0 && (
                <div className="mt-4 border-t border-border pt-4">
                  <p className="text-caption font-semibold text-muted">
                    {openSources.length === 1
                      ? 'One of them, open it now:'
                      : `${openSources.length} of them, open any of these now:`}
                  </p>
                  <CitationList citations={openSources} className="mt-2" />
                  {typeof pack.sourceCount === 'number' && pack.sourceCount > openSources.length && (
                    <p className="mt-3 text-caption text-muted">
                      The other {pack.sourceCount - openSources.length} are cited inside the pack, each
                      against the claim it supports.
                    </p>
                  )}
                </div>
              )}
              {/* The free-sample link that used to sit here now sits under the buy button, where
                  the reader deciding whether to pay can see it. See the note at its new site. */}

              {/* A NAMED HUMAN, HERE AND NOT ON THE BUY RAIL (founder, 2026-08-16: "nobody is
                  named", then, when it first shipped beside the button: "unnecessary when the
                  buyer is about to make a purchase decision"). Both are right, and they resolve to
                  a placement rather than a trade-off. Anonymity is a credibility liability, so the
                  name belongs in the block whose subject IS credibility -- this one, under the
                  sources a reader can open. It is not an objection to overcome at the moment of
                  commitment, where every extra line is something between the reader and the
                  button.
                  The NAME ONLY, and a link. §5.3: a fact renders on exactly one page, and the
                  founder's story is /about's (see where `bio` was deleted from `FOUNDER`). A
                  second telling here would drift from it. `hasFounder()` is the switch: with the
                  field empty this renders nothing at all, never a placeholder. */}
              {hasFounder() && (
                <p className="mt-4 border-t border-border pt-4 text-caption leading-relaxed text-subtle">
                  Researched and published by {FOUNDER.name}, who built {BRAND.name}.{' '}
                  <Link href="/about" className={textLinkClass()}>
                    Who that is
                  </Link>
                  .
                </p>
              )}
            </div>

            {/* Hides itself unless at least two packs genuinely score (AC-21). Scoring already
                happened server-side (see the `similar` prop's note above); this just renders. */}
            <SimilarPacks items={similar} />

            {/* Share sat at y~247, above the product, before the visitor knew what it was.
                Nobody shares a thing they have not read, so it moves to the foot of the article,
                where someone who has just read it might. */}
            <ShareRow title={pack.title} path={`/pack/${pack.id}`} />
          </div>

          {/* Right: Checkout (desktop sticky).
              THIS RAIL ONLY STARTED STICKING ON 2026-08-14. `sticky top-24` had been here for
              months and computed as `sticky`, but `SectionBand`'s inner div was `overflow-hidden`,
              which made it a scroll container and therefore the containing block for this rail --
              so the Buy button scrolled away at 2,200px of a 5,190px page and the right half of
              the money page was white for 3,400px. The band is `overflow-clip` now (see the note
              in `blocks.tsx`); clipping is identical, no scroll container is created.

              The cap is the second half of that fix. Pinned at `top-24` on a 900px viewport the
              rail has 804px and the panel measures 840, so its last line was cut with no way to
              reach it while pinned -- and on a 768px laptop 168px would be. It scrolls inside
              itself instead, which costs nothing: the buy button sits in the panel's top third,
              so what scrolls is the trailing prose. macOS overlay scrollbars mean no permanent
              gutter appears. */}
          <div className="hidden w-full shrink-0 lg:block lg:w-80">
            <div
              className={cx(
                'sticky top-24 rounded-md border border-border bg-surface p-8',
                'max-h-[calc(100svh-7rem)] overflow-y-auto overscroll-contain [scrollbar-width:thin]',
              )}
            >
              {checkoutBody}
            </div>
          </div>
        </div>

        {/* Sticky mobile checkout bar, keeps price + CTA above the fold on phones. */}
        {canCheckout && !clientSecret && (
          <div className="fixed inset-x-0 bottom-0 z-30 border-t border-border bg-surface p-4 pb-[env(safe-area-inset-bottom)] lg:hidden">
            <div className="flex items-center justify-between gap-3">
              {/* The terms, not the number. This said `One time  £79` beside a button reading
                  `Buy this pack  £79`, so the bar spent its whole left half repeating the figure
                  three centimetres to its right (mobile-pack-fold.png, 2026-08-06). The price
                  belongs on the CTA (founder decision, 2026-08-05: local currency on the headline
                  AND the button), which leaves this space for the two things the button cannot
                  say. */}
              <div className="text-caption leading-snug text-muted">
                <span className="block font-medium">One payment</span>
                <span className="block">14 day refund</span>
              </div>
              <PackBuyButton
                pack={pack}
                variant="sticky"
                buy={handleBuy}
                checkingOut={checkingOut}
                canCheckout={canCheckout}
                currency={currency}
              />
            </div>
          </div>
        )}

        {/* Back to top, desktop-only, revealed after scrolling. */}
        {showBackToTop && (
          <button
            type="button"
            onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
            className="fixed bottom-6 right-4 z-20 hidden rounded-sm border border-border bg-surface p-4 shadow-none transition-colors hover:bg-bg lg:block"
            aria-label="Back to top"
          >
            <Icon name="trending-up" size={16} />
            <span className="sr-only">Back to top</span>
          </button>
        )}
      </Section>
    </MarketingLayout>
  );
}

/**
 * The blurred look inside the deliverable.
 *
 * Built from the pack's OWN text, `whatYouGet` as the section headings a real build spec
 * carries, `sampleExtract` as the sourced body lines, the modelled economics as the figures
 * table. Nothing here is generated to fill space: every string is one the engine wrote and this
 * page already renders in full elsewhere, which is exactly why it is safe to show blurred.
 *
 * Falls back to the neutral skeleton when a pack carries neither bullets nor extracts (older
 * packs, and any pack whose bundle is incomplete). Showing a plausible-looking fake document for
 * a pack with nothing behind it is the single worst thing this element could do.
 */
/**
 * The modelled figures the preview may show, with the labels a buyer reads.
 *
 * `FinancialSnapshot` is a loose `Record<string, string>` (lib/api/client.ts:16) that carries the
 * SCORE AXES alongside the financial figures -- `pain_acuity: "4 of 5"` sits in the same object as
 * `month1Revenue: "£640"`. This element used to `Object.entries` over the whole thing and render
 * the key as the label, so the live page printed `month1Revenue`, `ltvCac` and `paybackMonths`,
 * in that raw camelCase, on the one element whose entire job is to look like a finished document
 * a buyer is about to pay for. Verified on mumchimp.com/pack/08b22037fc2afc07, 2026-08-08.
 *
 * An allow-list, not a de-camel-caser: a key with no buyer-facing name here is not rendered at
 * all, because mechanically un-camelling `ltvCac` yields "Ltv Cac", which is the same defect
 * wearing a space. New engine fields stay invisible until someone names them, which is the
 * failure direction that costs nothing.
 */
const PREVIEW_FIGURES: ReadonlyArray<{ key: string; label: string }> = [
  { key: 'month1Revenue', label: 'Month 1 revenue' },
  { key: 'ltvCac', label: 'LTV : CAC' },
  { key: 'paybackMonths', label: 'Payback' },
];

/** Named figures only, in a fixed order, with the engine's value verbatim apart from `tidyMonths`. */
function previewFigures(snapshot?: FinancialSnapshot): Array<{ label: string; value: string }> {
  return PREVIEW_FIGURES.flatMap(({ key, label }) => {
    const raw = snapshot?.[key];
    const value = typeof raw === 'string' ? raw.trim() : '';
    return value ? [{ label, value: tidyMonths(value) }] : [];
  });
}

/** "1 months" -> "1 month". The engine formats the plural unconditionally (`artifacts.py`), and
 *  the disagreeing plural landed on the money page next to a price. Display-side only: the stored
 *  value is untouched, and any count other than exactly one passes through unchanged. */
function tidyMonths(value: string): string {
  return value.replace(/^1\s+months\b/i, '1 month');
}

function PreviewDocument({ pack }: { pack: PackDetails }) {
  const headings = pack.whatYouGet ?? [];
  // NOT the same lines the pull-quote at the top of the page is already showing. This slice
  // started at index 0 and so did `EvidenceExcerptPlate`, which is two of the four surfaces that
  // opened on one source (founder, 2026-08-16). Dropping the hero line and keeping the order is
  // the whole fix; the preview is blurred and aria-hidden, so WHICH lines it shows only ever
  // mattered for the repetition a sighted reader sees down the page.
  const extract = pack.sampleExtract ?? [];
  const heroLine = firstCitedIndex(extract);
  const body = extract.filter((_, i) => i !== heroLine);
  const figures = previewFigures(pack.financialSnapshot);
  const hasRealContent = headings.length > 0 || body.length > 0;

  return (
    <div className="relative mt-6 overflow-hidden rounded-md border border-border bg-surface">
      {/* aria-hidden + a fixed height: this is an image of a document, not content. A screen
          reader gets the real, unblurred lists further down the page instead, and the clamp
          stops a pack with many bullets rendering a metre of blur. */}
      <div aria-hidden className="max-h-[320px] select-none overflow-hidden p-7 blur-[5px]">
        {hasRealContent ? (
          <div className="space-y-3">
            <p className="text-caption font-semibold leading-snug text-text">{pack.title}</p>
            {headings.slice(0, 2).map((h, i) => (
              <div key={`h-${i}`} className="space-y-1.5">
                <p className="text-caption font-medium text-subtle">
                  {String(i + 1).padStart(2, '0')} · {h}
                </p>
                {body.slice(i * 2, i * 2 + 2).map((line, j) => (
                  /* Prose only. A raw `(source: https://…)` run reads as text noise even at
                     blur(5px), and this element is aria-hidden, so a chip would be unreachable
                     anyway -- the citations render for real, clickable, further down the page. */
                  <p key={`b-${i}-${j}`} className="text-caption leading-relaxed text-muted">
                    {parseCitations(line).text}
                  </p>
                ))}
              </div>
            ))}
            {figures.length > 0 && (
              <div className="flex gap-3 pt-1">
                {figures.slice(0, 3).map(({ label, value }) => (
                  <div key={label} className="flex-1 rounded-md bg-bg p-2.5">
                    <p className="text-caption font-medium text-subtle">{label}</p>
                    <p className="mt-1 font-mono text-caption font-semibold text-text">{value}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        ) : (
          /* No real content to show. Neutral shapes that claim nothing. */
          <div className="space-y-2.5">
            <div className="h-3 w-2/5 rounded-md bg-text/80" />
            <div className="h-2 w-full rounded-md bg-text/15" />
            <div className="h-2 w-11/12 rounded-md bg-text/15" />
            <div className="h-2 w-10/12 rounded-md bg-text/15" />
            <div className="mt-4 h-3 w-1/3 rounded-md bg-text/40" />
            <div className="h-2 w-full rounded-md bg-text/15" />
            <div className="h-2 w-9/12 rounded-md bg-text/15" />
          </div>
        )}
      </div>
      <div className="absolute inset-0 flex items-center justify-center bg-gradient-to-t from-white via-white/70 to-white/30">
        <span className="inline-flex items-center gap-2 rounded-sm border border-border bg-surface px-4 py-2 text-caption font-medium text-text">
          <Icon name="lock" size={14} className="text-muted" />
          Unlocks the moment you buy
        </span>
      </div>
    </div>
  );
}

/** Share buttons: copy link, X, LinkedIn. URL via useSyncExternalStore to keep SSR clean.
 *
 * THE SERVER SNAPSHOT IS `absolute(path)`, NOT `''`.
 *
 * It returned an empty string, so the served HTML carried
 * `x.com/intent/tweet?text=...&url=` and `linkedin.com/sharing/share-offsite/?url=` with an empty
 * `url` param. Client hydration then filled it in, which is why this survived manual clicking --
 * but anything that reads the markup rather than running it shares nothing: LinkedIn's and X's
 * own crawlers, every "share" pulled from a scraped page, and any visitor whose JS has not
 * hydrated when they click. The pack's canonical path is known on the server, so there is no
 * reason to serve a broken link and repair it afterwards.
 *
 * `absolute()` returns undefined on a build with no SITE_URL (dev), which falls back to the old
 * empty-string behaviour and is then corrected at hydration exactly as before.
 */
function ShareRow({ title, path }: { title: string; path: string }) {
  const [copied, setCopied] = React.useState(false);

  const url = React.useSyncExternalStore(
    subscribeToNothing,
    () => window.location.origin + window.location.pathname,
    () => absolute(path) ?? '',
  );

  const handleCopy = React.useCallback(() => {
    track('pack_shared', 'copy');
    navigator.clipboard.writeText(url).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }, [url]);

  const btnClass =
    'rounded-sm border border-border bg-surface p-2 text-muted hover:text-text hover:border-text/30 transition-colors';

  return (
    <div className="mt-4 flex items-center gap-2">
      {/* Copy link */}
      <button type="button" onClick={handleCopy} className={btnClass} aria-label="Copy link">
        {copied ? (
          <span className="flex items-center gap-1 text-caption font-medium text-success">
            <Icon name="check" size={16} />
            Copied
          </span>
        ) : (
          <Icon name="link" size={16} />
        )}
      </button>

      {/* X and LinkedIn stay hand-inlined, and are the ONE exception to the one-family rule
          (brief 2026-08-15, Part Three). lucide-react 1.28 ships no brand marks -- `twitter.mjs`
          and `linkedin.mjs` do not exist in the package -- and a brand mark is not a UI icon: it
          is someone else's trademark, drawn to their spec, and redrawing it in a 2px outline hand
          would make it wrong rather than consistent. Everything else on this page is `Icon`. */}
      {/* X (Twitter) */}
      <a
        href={`https://x.com/intent/tweet?text=${encodeURIComponent(title)}&url=${encodeURIComponent(url)}`}
        target="_blank"
        rel="noopener noreferrer"
        className={btnClass}
        // The copy button beside these carried an aria-label and these two did not, so axe read
        // them as links with no discernible name: an SVG with no <title> exposes nothing, leaving
        // a screen reader or voice-control user with "link" and no way to say which one.
        aria-label="Share on X"
        onClick={() => track('pack_shared', 'x')}
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>
      </a>

      {/* LinkedIn */}
      <a
        href={`https://www.linkedin.com/sharing/share-offsite/?url=${encodeURIComponent(url)}`}
        target="_blank"
        rel="noopener noreferrer"
        className={btnClass}
        aria-label="Share on LinkedIn"
        onClick={() => track('pack_shared', 'linkedin')}
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 0 1-2.063-2.065 2.064 2.064 0 1 1 2.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/></svg>
      </a>
    </div>
  );
}

export const getServerSideProps: GetServerSideProps = async ({ params, req, res }) => {
  // US-5: the currency is decoupled from the market. Same source as the home page: the
  // country header, server-side, so the rendered HTML is correct on first paint.
  const countryHeader = req.headers['fly-client-country'];
  const currency = currencyForCountry(
    typeof countryHeader === 'string' ? countryHeader : null,
  );

  // N2: track the viewed pack in a first-party cookie so the home page can
  // show a personalised "Based on your browsing" row. The cookie is the same
  // shape the home page reads, a comma-separated list of pack ids in MRU
  // order. Server-side set, server-side read; no client JS needed. The cookie
  // is set ONLY when the pack loads successfully, so 404s do not pollute the
  // list. Path=/ so the home page sees it.
  const id = params?.id as string;
  if (id) {
    try {
      const raw = req.cookies.recentlyViewed;
      const ids: string[] = raw ? raw.split(',').filter(Boolean) : [];
      const next = [id, ...ids.filter((x) => x !== id)].slice(0, 10);
      res.setHeader(
        'Set-Cookie',
        `recentlyViewed=${encodeURIComponent(next.join(','))}; Path=/; Max-Age=2592000; SameSite=Lax`,
      );
    } catch {
      // Cookie write failure must not 500 the page; the buy path is the
      // critical thing here. The next request will re-set it.
    }
  }

  try {
    // Fetched together, not in series: the "same mechanics" row needs the catalogue, and paying
    // two sequential round trips before first byte would be a real cost for a decorative row.
    // The catalogue is best-effort, a failure there must not 404 a page someone is buying from.
    const [pack, catalog] = await Promise.all([
      fetchPackDetails(id),
      fetchCatalog().catch(() => [] as Pack[]),
    ]);
    // The catalogue itself never becomes a prop -- only its top-3 scored matches do (measured
    // 2026-08-14: this was serialising the whole catalogue into every pack page's `__NEXT_DATA__`
    // to render a 3-card row). See the `similar` field's note on `PackPageProps`.
    return {
      props: { pack, similar: sameOrDearer(pack, similarPacks(pack, catalog)), currency },
    };
  } catch (error) {
    console.error('Error fetching pack details:', error);

    /* "Gone" and "down" are not the same page, and this branch used to serve both as a 200.
     *
     * Measured on production 2026-08-05, for all three pack ids the e2e has been failing on
     * (42bf9861ecc08079, f7783abea10a4216, 54f775d91cbe09d8):
     *
     *     api.mumchimp.com/catalog/{id}  ->  404, and absent from /catalog
     *     mumchimp.com/pack/{id}         ->  200, empty ErrorState, robots "index, follow"
     *
     * A 200 on a withdrawn pack is a soft-404: the crawler is told the URL is a live page, keeps
     * it in the index, and keeps sending buyers to a dead end. `ApiError` has carried `status`
     * since it was written for exactly this distinction (see its docstring in lib/api/client.ts);
     * `/og/pack/[id]` already splits on it and this page never did.
     *
     * The two halves have to be different, and the memory of getting this wrong is why:
     * `notFound: true` OVERRIDES any `res.statusCode` set beside it, so collapsing the transient
     * case into it would tell Google a page is permanently gone every time the API blips. So:
     * gone -> a real 404 with no props; down -> 503 + Retry-After + noindex, keeping the
     * retry-able ErrorState the visitor can act on, and keeping the URL in the index.
     */
    const status = error instanceof ApiError ? error.status : 0;
    if (status === 404 || status === 410) {
      return { notFound: true };
    }

    res.statusCode = 503;
    res.setHeader('Retry-After', '60');
    const message =
      error instanceof Error ? error.message : 'Could not load pack details.';
    return {
      props: { pack: null, similar: [], error: message, currency, unavailable: true },
    };
  }
};
