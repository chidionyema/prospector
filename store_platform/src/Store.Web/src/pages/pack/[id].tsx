import React from 'react';
import { GetServerSideProps } from 'next';
import { useRouter } from 'next/router';
import Link from 'next/link';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Seo } from '@/components/Seo';
import { productJsonLd } from '@/lib/productJsonLd';
import { absolute, breadcrumbNode, graph } from '@/lib/seo/schema';
import { packOgImagePath } from '@/lib/seo/ogImage';
import { buttonClasses, Icon, ErrorState, Breadcrumbs, SourcedLine, CitationList } from '@/components/ui';
import { parseCitations } from '@/lib/citations';
import { cx } from '@/components/ui/cx';
import { categoryFor } from '@/lib/category';
import { COMMON_CHECKS, checkForGate } from '@/lib/checks';
import { Section } from '@/components/marketing/blocks';
import { PackContentsSection, PACK_CONTENTS } from '@/components/marketing/PackContents';
import { ApiError, fetchCatalog, fetchPackDetails, freshnessLabel, marketLabel, parseCheckCounts, scoreAxes, splitVerdict, Pack, PackDetails } from '@/lib/api/client';
import { formatPriceForMarket, formatChargeNote, formatApproxNote, currencyForCountry, type Currency } from '@/lib/fx';
import { isTruncated, repairTruncation } from '@/lib/copy';
import { track, trackPriceEvent } from '@/lib/analytics';
import { EmbeddedCheckoutPanel } from '@/components/checkout/EmbeddedCheckoutPanel';
import { BuyerIdentityNote } from '@/components/checkout/BuyerIdentityNote';
import EvidenceExcerptPlate from '@/components/marketing/EvidenceExcerptPlate';
import PackMark from '@/components/ui/PackMark';
import PackBuyButton from '@/components/checkout/PackBuyButton';
import { usePackCheckout } from '@/lib/checkout/usePackCheckout';
import { PREOPENED_CHECKOUT_PARAM, preopenedClientSecret } from '@/lib/preopenedCheckout';
import { FacetChips } from '@/components/discovery/FacetChips';
import { SimilarPacks } from '@/components/discovery/SimilarPacks';
import { LEGAL } from '@/lib/config';
import { AddToCartButton } from '@/components/cart/AddToCartButton';

const subscribeToNothing = () => () => {};

interface PackPageProps {
  pack: PackDetails | null;
  /** The rest of the catalogue, for the "same mechanics" row. Empty when that fetch failed,
   *  a catalogue outage must never take down a page someone is trying to buy from. */
  catalog: Pack[];
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

export default function PackPage({ pack, catalog, error, unavailable, currency }: PackPageProps) {
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

  return <PackPageContent pack={pack} catalog={catalog} currency={currency} />;
}

/** Inner component: all hooks that require a non-null pack live here. */
function PackPageContent({ pack, catalog, currency }: { pack: PackDetails; catalog: Pack[]; currency: Currency }) {
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
  const openSources = React.useMemo(() => {
    const seen = new Set<string>();
    return (pack.sampleExtract ?? []).flatMap((line) =>
      parseCitations(line).citations.filter((c) => !seen.has(c.url) && seen.add(c.url)),
    );
  }, [pack.sampleExtract]);

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
      <span className="text-caption text-subtle">One-time price</span>
      <div className="mt-1">
        <span className="font-mono text-h2 font-semibold text-text">{priceLabel}</span>
      </div>
      {/* The hedge sits with the number it hedges. The old note ("£49 at today's rate") named
          the wrong figure -- £49 is the catalogue's source price, the converted one is what the
          rate produced -- and it sat below a green guarantee box, four elements away from the
          price. */}
      {currency !== 'GBP' && (
        <p className="mt-1 text-caption text-subtle">{formatApproxNote(currency)}</p>
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
       * genuinely does not track document count -- every pack ships the same eight files. It is
       * one sentence and a link because the rail is the wrong place to argue it at length; the
       * full argument, with the ladder, is on /pricing where the reader chose to read it.
       *
       * Deliberately NOT stated as this pack's own tier: `PackDetails` carries no ambition tier
       * (lib/api/client.ts), so naming a rung here would be a number the page cannot source.
       */}
      <p className="mt-2 text-caption leading-relaxed text-subtle">
        Set by how big this idea could get and the market it targets, never by the size of the
        pack.{' '}
        <Link href="/pricing" className="text-accent underline underline-offset-2 hover:text-accent-hover">
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
          <Icon name="verified" size={16} className="flex-none text-success" />
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
              only a gain for someone who wants several, so it never sits in front of the direct path. */}
          <div className="mt-3">
            <AddToCartButton
              line={{ id: pack.id, title: pack.title, price: pack.price, pricePence: pack.pricePence }}
            />
          </div>
          {/* Under the button, not above it: the address only matters once the buyer has decided,
              and putting an account-shaped sentence in front of the price is how a storefront
              teaches guests that they need an account. They do not. */}
          <BuyerIdentityNote className="mt-3 text-caption leading-relaxed text-subtle" />
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
      <p className="mt-6 text-caption leading-relaxed text-subtle">
        The numbers are in the pack. Pricing mechanics and unit economics, every input sourced.
        What couldn’t be verified is marked absent, never invented.
      </p>

      <p className="mt-6 text-caption leading-relaxed text-subtle">
        {/* Secure checkout named where it is relevant, in a sentence, instead of as a third
            icon row. */}
        Secure checkout via {providerLabel}. A pack is evidence-backed research, not a promise of business
        success. See our{' '}
        <Link href="/refund" className="text-accent underline underline-offset-2 hover:text-accent-hover">
          refund policy
        </Link>
        .
      </p>
    </>
  );

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
             * THE MORPH TARGET.
             *
             * The shelf's lead card renders `<PackMark morph />` (pages/index.tsx:354) and until
             * now nothing on this page claimed the same `view-transition-name`, so the shared
             * element had a source and no destination: the browser cross-faded the whole root and
             * the one animation worth paying for never ran. This strip is the other half.
             *
             * 96px, not 550px. The full-bleed sector cover was deleted for a measured reason
             * (see the note in `PackCover`): it pushed the h1, the price and the buy button below
             * the fold on a 1280x720 viewport. A strip this tall is a masthead, not a hero -- it
             * gives the transition somewhere to land and gives the page the pack's own mark,
             * without spending the fold on decoration.
             *
             * `cat.tint`/`cat.ink` and NOT a hash-derived hue: the mark draws in `currentColor`,
             * so form means this pack and colour still means sector. The chip and the dossier
             * number stay in `PackCover` below rather than being overlaid here, because a label
             * sitting on top of the mark is the thing that turns a masthead back into a cover.
             */}
            <div
              className={cx(
                'relative mb-3 h-20 w-full overflow-hidden rounded-md sm:h-24',
                cat.tint,
                cat.ink,
              )}
            >
              <PackMark id={pack.id} morph emphasis />
            </div>
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
            {!(isTruncated(pack.oneLine) && pack.subhead) && (
              <p className="mt-4 max-w-[60ch] text-body text-muted">
                {repairTruncation(pack.oneLine)}
              </p>
            )}
            {pack.subhead && (
              <p className="mt-4 max-w-[60ch] text-body text-muted">{pack.subhead}</p>
            )}

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
                <Icon name="verified" size={12} className="text-success" />
                {evidenceTokens.map((token, i) => (
                  <React.Fragment key={token}>
                    {i > 0 && <span aria-hidden="true">·</span>}
                    <span>{token}</span>
                  </React.Fragment>
                ))}
              </p>
            )}

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
                  <Icon name="shield" size={16} className="text-warning-strong" />
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
                lead={`The moment you pay, you download the whole pack. ${PACK_CONTENTS.length} documents, no drip feed, no login.`}
                sourceCount={pack.sourceCount}
              />
            </div>

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
                    className="font-medium text-accent underline underline-offset-2 hover:text-accent-hover"
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
                  {/* NOT "the six fronts". The check count is lane-dependent (6/6, 8/8, 7/8, 9/9
                      and 6/8 all occur live), which is why `fixedCheckCount.test.ts` exists and
                      why it failed on this sentence the moment it was written. */}
                  The checks every idea is attacked on are below. For where this pack&rsquo;s case
                  is strong and where it is thin, open <span className="font-medium text-text">How it
                  scores</span> further down, weak bars included.
                </p>
                <ul className="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-2">
                  {CHECKS.map((check, i) => (
                    <li
                      key={check}
                      className="flex items-center gap-3 rounded-md border border-border bg-surface px-4 py-3"
                    >
                      {/* A numeral, not a tick: a green success mark on a static line reads as this
                          pack's verdict on that check, which is exactly what this page cannot know. */}
                      <span className="flex h-6 w-6 flex-none items-center justify-center rounded-full border border-border bg-surface2 font-mono text-caption text-subtle">
                        {i + 1}
                      </span>
                      <span className="text-meta font-medium text-text">{check}</span>
                    </li>
                  ))}
                </ul>
                <Link
                  href="/how-it-works"
                  className="mt-5 inline-flex items-center gap-1.5 text-meta font-medium text-accent transition-colors hover:text-accent-hover"
                >
                  See how each check works
                  <Icon name="arrowRight" size={14} />
                </Link>
              </div>
            </details>

            {/* US-4: the scored axes collapse behind a details disclosure. The
                methodology is opt-in; the buyer who only cares about the
                result sees the buy button first, the methodology on demand. */}
            {(axes.length > 0 || verdict.risk) && (
              <details className="mt-12 group">
                <summary className="cursor-pointer list-none text-h2 font-semibold text-text transition-colors hover:text-muted">
                  <span className="inline-flex items-center gap-2">
                    <Icon name="arrowRight" size={16} className="transition-transform group-open:rotate-90" />
                    How it scores
                  </span>
                </summary>
                <div className="mt-4">
                  <p className="max-w-[60ch] text-meta text-muted">
                    Six things we measure. The strong ones are strengths. The weaker ones are things
                    you should know before you build.
                  </p>

                {axes.length > 0 && (
                  <dl className="mt-6 grid grid-cols-1 gap-x-8 gap-y-4 sm:grid-cols-2">
                    {axes.map((a) => {
                      const tone =
                        a.value >= 4 ? 'bg-success' : a.value === 3 ? 'bg-text/40' : 'bg-warning';
                      return (
                        <div key={a.label} className="flex flex-col gap-1.5">
                          <div className="flex items-baseline justify-between gap-2">
                            <dt className="text-meta font-semibold text-text">{axisLabel(a.label)}</dt>
                            <dd className="font-mono text-caption text-muted">
                              {a.value} / {a.outOf}
                            </dd>
                          </div>
                          <div className="flex gap-1" aria-hidden>
                            {Array.from({ length: a.outOf }).map((_, i) => (
                              <span
                                key={i}
                                className={cx(
                                  'h-1.5 flex-1 rounded-full',
                                  i < a.value ? tone : 'bg-border',
                                )}
                              />
                            ))}
                          </div>
                        </div>
                      );
                    })}
                  </dl>
                )}

                {verdict.risk && (
                  <div className="mt-6 rounded-md border-l-2 border-l-warning bg-warning-bg py-4 pl-5 pr-5">
                    <div className="flex items-center gap-2">
                      <Icon name="shield" size={15} className="text-warning" />
                      <span className="text-meta font-semibold text-text">
                        Where this could break
                      </span>
                    </div>
                    <p className="mt-2 max-w-[62ch] text-meta leading-relaxed text-muted">{verdict.risk}</p>
                    <p className="mt-2 text-caption text-muted">
                      The strongest case against the idea, with its source, also lives inside the pack.
                    </p>
                  </div>
                )}
                </div>
              </details>
            )}

            {/* Is this for you?, the concrete fit signals, when the pack carries them */}
            {(pack.market || pack.whoPays || pack.timeToFirstRevenue) && (
              <div className="mt-12">
                <h2 className="text-h2 font-semibold text-text">Is this for you?</h2>
                {/* The engine's own tags, in the buyer's words. Absent facets render nothing:
                    "Effort to build" used to print the legacy `effortTag` string, which was never
                    defined to mean how much of delivery is machine-doable (spec 2.3). */}
                <FacetChips pack={pack} className="mt-4" />
                <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
                  {pack.market && (
                    <div className="flex flex-col rounded-md border border-border bg-surface p-5 sm:col-span-3">
           <span className="text-caption font-medium text-subtle">
                        Market
                      </span>
                      <span className="mt-1.5 text-meta font-semibold text-text">
                        {marketLabel(pack.market)}
                      </span>
                      {/* State it plainly: the research is about this jurisdiction, and the
                          pack is still sold in GBP. Leaving that implicit invites a refund. */}
                      <span className="mt-1.5 text-caption leading-relaxed text-muted">
                        The opportunity, its evidence and its economics are researched for this
                        market. The pack itself is priced and sold in GBP.
                      </span>
                    </div>
                  )}
                  {pack.whoPays && (
                    <div className="flex flex-col rounded-md border border-border bg-surface p-5 sm:col-span-3">
           <span className="text-caption font-medium text-subtle">
                        Who pays
                      </span>
                      <span className="mt-1.5 text-meta leading-relaxed text-muted">{pack.whoPays}</span>
                    </div>
                  )}
                  {pack.timeToFirstRevenue && (
                    <div className="flex flex-col rounded-md border border-border bg-surface p-5">
           <span className="text-caption font-medium text-subtle">
                        Time to first revenue
                      </span>
                      <span className="mt-1.5 text-meta font-semibold text-text">{pack.timeToFirstRevenue}</span>
                    </div>
                  )}
                </div>
              </div>
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
                      className="flex items-start gap-3 rounded-md border border-border bg-surface p-5"
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
                <Icon name="verified" className="text-success" size={18} />
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
              <Link
                href="/sample"
                className="mt-4 inline-flex items-center gap-1.5 text-meta font-medium text-accent transition-colors hover:text-accent-hover"
              >
                Want to see the depth first? Read the free sample report
                <Icon name="arrowRight" size={14} />
              </Link>
            </div>

            {/* Hides itself unless at least two packs genuinely score (AC-21). */}
            <SimilarPacks pack={pack} all={catalog} />

            {/* Share sat at y~247, above the product, before the visitor knew what it was.
                Nobody shares a thing they have not read, so it moves to the foot of the article,
                where someone who has just read it might. */}
            <ShareRow title={pack.title} path={`/pack/${pack.id}`} />
          </div>

          {/* Right: Checkout (desktop sticky) */}
          <div className="hidden w-full shrink-0 lg:block lg:w-80">
            <div className="sticky top-24 rounded-md border border-border bg-surface p-7">
              {checkoutBody}
            </div>
          </div>
        </div>

        {/* Sticky mobile checkout bar, keeps price + CTA above the fold on phones. */}
        {canCheckout && !clientSecret && (
          <div className="fixed inset-x-0 bottom-0 z-30 border-t border-border bg-surface p-3 pb-[env(safe-area-inset-bottom)] lg:hidden">
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
            className="fixed bottom-6 right-4 z-20 hidden rounded-full border border-border bg-surface p-3 shadow-none transition-colors hover:bg-bg lg:block"
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
function PreviewDocument({ pack }: { pack: PackDetails }) {
  const headings = pack.whatYouGet ?? [];
  const body = pack.sampleExtract ?? [];
  const figures = Object.entries(pack.financialSnapshot ?? {}).filter(
    ([, v]) => typeof v === 'string' && v.trim(),
  );
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
                {figures.slice(0, 3).map(([label, value]) => (
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
        <span className="inline-flex items-center gap-2 rounded-full border border-border bg-surface px-4 py-2 text-caption font-medium text-text">
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
    'rounded-full border border-border bg-surface p-2 text-muted hover:text-text hover:border-text/30 transition-colors';

  return (
    <div className="mt-4 flex items-center gap-2">
      {/* Copy link */}
      <button type="button" onClick={handleCopy} className={btnClass} aria-label="Copy link">
        {copied ? (
     <span className="text-caption font-medium text-success">Copied ✓</span>
        ) : (
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>
        )}
      </button>

      {/* X (Twitter) */}
      <a
        href={`https://x.com/intent/tweet?text=${encodeURIComponent(title)}&url=${encodeURIComponent(url)}`}
        target="_blank"
        rel="noopener noreferrer"
        className={btnClass}
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
    return {
      props: { pack, catalog, currency },
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
      props: { pack: null, catalog: [], error: message, currency, unavailable: true },
    };
  }
};
