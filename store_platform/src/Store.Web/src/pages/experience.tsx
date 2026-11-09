import Head from 'next/head';
import Image from 'next/image';
import Link from 'next/link';
import styles from './experience.module.css';

/**
 * Isolated, read-only art-direction canary for crew#774.
 *
 * This is a review of the actual Mumchimp Store.Web app, not a parallel
 * e-commerce platform. Every showcased title and image id is taken from the
 * repository's recorded research catalogue (facets-backfill and public/pack).
 * The archive does NOT assert these are in stock or available to purchase.
 * Checkout, registration, analytics, API calls and payment affordances are
 * deliberately absent, including when the live API recovers.
 */
const archive = [
  {
    id: '0c6c74267f7485a3',
    label: 'Aquaculture / UK',
    title: 'SpatWindow',
    description: 'Forecasting shellfish harvest windows from rainfall, tide and water-quality signals.',
    image: '/pack/0c6c74267f7485a3.jpg',
    index: '01',
  },
  {
    id: '0ce623e80658e97c',
    label: 'Care / employment',
    title: 'PAHireRight',
    description: 'A fixed-fee personal-assistant employment setup service for people managing direct payments.',
    image: '/pack/0ce623e80658e97c.jpg',
    index: '02',
  },
  {
    id: '7fc5a381ad82c1ed',
    label: 'Trades / compliance',
    title: 'SparkCert',
    description: 'An electrical-work certification service concept for sole traders navigating Part P requirements.',
    image: '/pack/7fc5a381ad82c1ed.jpg',
    index: '03',
  },
  {
    id: '7dc94c897c7d28f4',
    label: 'Property / probate',
    title: 'IHT Valuation Barometer',
    description: 'A research concept about challenging inheritance-tax valuations using documented outcomes.',
    image: '/pack/7dc94c897c7d28f4.jpg',
    index: '04',
  },
] as const;

export default function MumchimpExperienceReview() {
  return (
    <div className={styles.shell}>
      <Head>
        <title>Experience review | Mumchimp</title>
        <meta name="robots" content="noindex, nofollow, noarchive" />
        <meta name="description" content="Private, read-only Mumchimp visual experience review." />
      </Head>
      <a href="#review-main" className={styles.skip}>Skip to content</a>
      <div className={styles.review}>
        <span className={styles.reviewDot} aria-hidden="true" />
        <span>PRIVATE DESIGN REVIEW</span>
        <span className={styles.reviewDivider} aria-hidden="true" />
        <span>Illustrative archive, no transactions</span>
      </div>

      <header className={styles.header}>
        <div className={styles.headerInner}>
          <Link href="/experience" className={styles.brand} aria-label="Mumchimp experience review home">
            <span className={styles.brandMark} aria-hidden="true"><span/><span/><span/></span>
            <span><strong>Mum</strong>chimp<span className={styles.brandPeriod}>.</span></span>
          </Link>
          <nav aria-label="Experience review" className={styles.nav}>
            <a href="#ideas">The ideas</a>
            <a href="#method">The method</a>
            <Link href="/sample">The sample</Link>
          </nav>
          <Link className={styles.headerAction} href="/sample">
            Read a sample <span aria-hidden="true">↗</span>
          </Link>
        </div>
      </header>

      <main id="review-main">
        <section className={styles.hero} aria-labelledby="experience-headline">
          <div className={styles.heroAmbient} aria-hidden="true" />
          <div className={styles.heroInner}>
            <div className={styles.heroCopy}>
              <p className={styles.eyebrow}><span className={styles.eyebrowLine} /> RESEARCH BEFORE THE LEAP</p>
              <h1 id="experience-headline">Build a business on <em>better questions.</em></h1>
              <p className={styles.heroLead}>
                The idea is the easy part. What matters is the evidence underneath it,
                the objections it survives, and whether you can actually execute it.
              </p>
              <div className={styles.heroActions}>
                <Link className={styles.primaryAction} href="/sample">
                  Read the actual research <span aria-hidden="true">↗</span>
                </Link>
                <Link className={styles.quietAction} href="/how-it-works">
                  Understand the method <span aria-hidden="true">↗</span>
                </Link>
              </div>
              <div className={styles.heroNote}>
                <span className={styles.noteIcon} aria-hidden="true">✳</span>
                Research is evidence to assess, not a guarantee of results.
              </div>
            </div>
            <div className={styles.heroVisual} aria-label="Illustrative presentation of a research dossier">
              <div className={styles.coverBacking} aria-hidden="true" />
              <div className={styles.heroDocument}>
                <div className={styles.documentTop}>
                  <span>MUMCHIMP / FIELD NOTES</span>
                  <span>EXAMPLE / 01</span>
                </div>
                <div className={styles.documentImage}>
                  <Image src="/pack/0c6c74267f7485a3.jpg" alt="SpatWindow opportunity dossier cover artwork" fill sizes="(max-width: 900px) 80vw, 420px" priority />
                </div>
                <div className={styles.documentBottom}>
                  <span>SPATWINDOW</span>
                  <span>RESEARCH DOSSIER</span>
                </div>
              </div>
              <div className={styles.stickyLabel}>
                <span className={styles.stickyIndex}>THE POINT</span>
                <span>Don&apos;t fall in love<br/>with the first answer.</span>
              </div>
            </div>
          </div>
          <div className={styles.heroRule}><div><span>THE WORK BEHIND THE OPPORTUNITY</span><span>SCROLL TO EXPLORE <span aria-hidden="true">↓</span></span></div></div>
        </section>

        <section className={styles.intro} aria-label="What Mumchimp delivers">
          <div className={styles.introInner}>
            <p className={styles.sectionIndex}>01 / THE PREMISE</p>
            <div className={styles.introText}>
              <h2>Less hype.<br/><em>More substance.</em></h2>
              <p>
                A catalogue of researched opportunity concepts, with the awkward questions
                left in. Because knowing why an idea might fail is part of knowing what
                it would take to make it work.
              </p>
            </div>
          </div>
        </section>

        <section className={styles.archive} id="ideas" aria-labelledby="ideas-heading">
          <div className={styles.sectionHead}>
            <div>
              <p className={styles.sectionIndex}>02 / FROM THE RESEARCH ARCHIVE</p>
              <h2 id="ideas-heading">Specific ideas.<br/><em>Real-world friction.</em></h2>
            </div>
            <p className={styles.sectionAside}>
              These examples are drawn from recorded research concepts, not a live availability
              or price list. The operational catalogue is being restored separately.
            </p>
          </div>
          <div className={styles.cardGrid}>
            {archive.map((item) => (
              <article className={styles.ideaCard} key={item.id}>
                <div className={styles.cardImage}>
                  <Image src={item.image} alt={item.title + ' concept cover art'} fill sizes="(max-width: 640px) 100vw, (max-width: 1100px) 50vw, 25vw" />
                  <span className={styles.cardNumber}>{item.index} / 04</span>
                </div>
                <div className={styles.cardBody}>
                  <span className={styles.cardCategory}>{item.label}</span>
                  <h3>{item.title}</h3>
                  <p>{item.description}</p>
                  <span className={styles.cardFoot}>RESEARCH CONCEPT <span aria-hidden="true">↗</span></span>
                </div>
              </article>
            ))}
          </div>
          <div className={styles.archiveFoot}>
            <span>NO INVENTED SALES CLAIMS. NO UNVERIFIED PRICES.</span>
            <Link href="/sample">See what a real dossier contains <span aria-hidden="true">↗</span></Link>
          </div>
        </section>

        <section className={styles.method} id="method" aria-labelledby="method-heading">
          <div className={styles.methodInner}>
            <div className={styles.methodHead}>
              <p className={styles.sectionIndex}>03 / HOW WE LOOK AT AN IDEA</p>
              <h2 id="method-heading">A good opportunity<br/>can withstand <em>scrutiny.</em></h2>
              <Link href="/how-it-works">Explore the full method <span aria-hidden="true">↗</span></Link>
            </div>
            <div className={styles.methodSteps}>
              <div><span>01</span><h3>Find the problem.</h3><p>Who experiences it, why it persists, and what they do about it today.</p></div>
              <div><span>02</span><h3>Make the case against it.</h3><p>Competing solutions, ability to pay, execution risk and missing evidence.</p></div>
              <div><span>03</span><h3>Show the work.</h3><p>The sources, the challenged claims, and the practical path that remains.</p></div>
            </div>
          </div>
        </section>

        <section className={styles.closing} aria-labelledby="closing-heading">
          <div className={styles.closingInner}>
            <p className={styles.sectionIndex}>04 / START WITH THE EVIDENCE</p>
            <h2 id="closing-heading">See the work.<br/><em>Judge for yourself.</em></h2>
            <p>Open a real research excerpt. No registration and no promise that an idea will succeed.</p>
            <Link href="/sample" className={styles.primaryAction}>Open the free sample <span aria-hidden="true">↗</span></Link>
          </div>
        </section>
      </main>
      <footer className={styles.footer}>
        <div><Link href="/experience" className={styles.footerBrand}>Mumchimp<span>.</span></Link><p>Research for people who would rather know more before they commit.</p></div>
        <div className={styles.footerNav}><Link href="/about">About</Link><Link href="/privacy">Privacy</Link><Link href="/terms">Terms</Link><Link href="/refund">Refund policy</Link></div>
        <div className={styles.footerBase}><span>PRIVATE VISUAL CANARY · NOT FOR PUBLIC SALE</span><span>Product of Merdian Intelligence</span></div>
      </footer>
    </div>
  );
}
