import type { GetServerSideProps } from 'next';
import Image from 'next/image';
import Link from 'next/link';
import { ReviewFrame } from '@/components/experience/ReviewFrame';
import { ApiError, fetchPackDetails, splitVerdict, type PackDetails } from '@/lib/api/client';
import { packImage } from '@/lib/sectorImage';
import styles from '@/pages/experience.module.css';

type DossierReviewProps = {
  pack: PackDetails | null;
  sourceAvailable: boolean;
};

/**
 * Zero-transaction readback of the ORIGINAL Store.Api dossier.
 * No speculative economics, fabricated sources, seller claims or payment links.
 */
export default function DossierReview({ pack, sourceAvailable }: DossierReviewProps) {
  const verdict = splitVerdict(pack?.qaVerdictSummary);
  return (
    <ReviewFrame title={pack?.title ?? 'Research dossier'}>
      <section className={styles.journeyHero}>
        <div className={styles.journeyInner}>
          <Link href="/experience/catalogue" className={styles.reviewBack}>← Back to the catalogue</Link>
          <div className={styles.eyebrow}><span className={styles.eyebrowLine} /> RESEARCH DOSSIER / READ-ONLY REVIEW</div>
          <h1>{pack ? pack.title : <>The research <em>record.</em></>}</h1>
          <p>{pack?.oneLine || 'This page presents the current research record supplied by the original Prospector API. This design-review route never sells products.'}</p>
          <div className={styles.journeyMeta}>
            <span>{pack ? 'Source: Store.Api' : 'Source not responding'}</span>
            <span>Preview only · No purchases</span>
          </div>
        </div>
      </section>
      {!sourceAvailable || !pack ? (
        <section className={styles.journeyContent}>
          <div className={styles.journeyEmpty} role="status">
            <span>RESEARCH SOURCE UNAVAILABLE</span>
            <h2>The dossier could not be retrieved.</h2>
            <p>No reconstructed dossier or invented evidence is displayed. The source must recover before this design can be evaluated against actual research.</p>
            <Link href="/experience/catalogue">Back to the catalogue <span aria-hidden="true">↗</span></Link>
          </div>
        </section>
      ) : (
        <section className={styles.journeyContent}>
          <div className={styles.reviewDossierGrid}>
            <article className={styles.reviewDossierMain}>
              <span className={styles.journeyKicker}>01 / THE CASE</span>
              <h2>{pack.headline || pack.title}</h2>
              <p className={styles.reviewDossierLead}>{pack.theProblem || pack.subhead || pack.oneLine}</p>
              {pack.whoPays && (
                <div className={styles.reviewDossierSection}>
                  <span className={styles.journeyKicker}>02 / WHO EXPERIENCES THIS</span>
                  <h3>Who pays, and why?</h3>
                  <p>{pack.whoPays}</p>
                </div>
              )}
              {verdict.summary && (
                <div className={styles.reviewDossierSection}>
                  <span className={styles.journeyKicker}>03 / SCRUTINY</span>
                  <h3>The recorded assessment.</h3>
                  <p>{verdict.summary}</p>
                </div>
              )}
              {verdict.risk && (
                <div className={styles.reviewRisk}>
                  <span className={styles.journeyKicker}>MAIN RISK IDENTIFIED</span>
                  <h3>The strongest objection matters.</h3>
                  <p>{verdict.risk}</p>
                </div>
              )}
              {Array.isArray(pack.sampleExtract) && pack.sampleExtract.length > 0 && (
                <div className={styles.reviewDossierSection}>
                  <span className={styles.journeyKicker}>04 / EXCERPT FROM THE RECORD</span>
                  <h3>A closer look.</h3>
                  {pack.sampleExtract.slice(0, 4).map((paragraph, index) => (
                    <p key={index}>{paragraph}</p>
                  ))}
                </div>
              )}
              {Array.isArray(pack.whatYouGet) && pack.whatYouGet.length > 0 && (
                <div className={styles.reviewDossierSection}>
                  <span className={styles.journeyKicker}>05 / DOCUMENTED CONTENTS</span>
                  <h3>What the record describes.</h3>
                  <ul className={styles.reviewContents}>
                    {pack.whatYouGet.map((item, index) => <li key={index}>{item}</li>)}
                  </ul>
                </div>
              )}
            </article>
            <aside className={styles.reviewDossierAside} aria-label="Research record identification">
              <div className={styles.reviewDossierArtwork}>
                <Image src={packImage(pack)} alt="" fill sizes="(max-width: 850px) 90vw, 360px" priority />
              </div>
              <div className={styles.reviewDossierFacts}>
                <span className={styles.journeyKicker}>RECORD DETAILS</span>
                <dl>
                  <div><dt>Reference</dt><dd>{pack.id}</dd></div>
                  {pack.market && <div><dt>Market</dt><dd>{pack.market}</dd></div>}
                  {pack.sector && <div><dt>Sector</dt><dd>{pack.sector.replaceAll('_', ' ')}</dd></div>}
                  {typeof pack.sourceCount === 'number' && <div><dt>Recorded sources</dt><dd>{pack.sourceCount}</dd></div>}
                  {pack.verifiedAt && <div><dt>Verification timestamp</dt><dd>{pack.verifiedAt}</dd></div>}
                </dl>
                <p>This page does not independently verify research claims or offer the dossier for purchase. Transactions remain on the original storefront after recovery.</p>
              </div>
            </aside>
          </div>
          <div className={styles.reviewNext}>
            <span className={styles.journeyKicker}>FINISH THE REVIEW</span>
            <h2>Evaluate the evidence. <em>Then decide.</em></h2>
            <Link href="/experience/catalogue" className={styles.primaryAction}>Explore more records <span aria-hidden="true">↗</span></Link>
          </div>
        </section>
      )}
    </ReviewFrame>
  );
}

export const getServerSideProps: GetServerSideProps<DossierReviewProps> = async ({ params }) => {
  if (process.env.VERCEL_ENV !== 'preview') return { notFound: true };
  const id = params?.id;
  if (typeof id !== 'string' || !/^[A-Za-z0-9_-]{5,100}$/.test(id)) return { notFound: true };
  try {
    const pack = await fetchPackDetails(id, { signal: AbortSignal.timeout(2500) });
    return { props: { pack, sourceAvailable: true } };
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return { notFound: true };
    return { props: { pack: null, sourceAvailable: false } };
  }
};
