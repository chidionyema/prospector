import { useMemo, useState } from 'react';
import type { GetServerSideProps } from 'next';
import Image from 'next/image';
import Link from 'next/link';
import { ReviewFrame } from '@/components/experience/ReviewFrame';
import { fetchCatalog, type Pack } from '@/lib/api/client';
import { packImage } from '@/lib/sectorImage';
import { REVIEW_ARCHIVE } from '@/lib/reviewArchive';
import styles from '@/pages/experience.module.css';

interface CatalogueReviewProps {
  packs: Pack[];
  sourceAvailable: boolean;
}

/** 
 * The protected preview reads the SAME catalogue endpoint as the real shelf.
 * It does not synthesize products, prices, sales status, or a fallback stock list.
 */
export default function CatalogueReview({ packs, sourceAvailable }: CatalogueReviewProps) {
  const [query, setQuery] = useState('');
  const visible = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase('en-GB');
    if (!needle) return packs;
    return packs.filter((pack) =>
      [pack.title, pack.oneLine, pack.theProblem, pack.sector, pack.market]
        .some((part) => typeof part === 'string' && part.toLocaleLowerCase('en-GB').includes(needle)),
    );
  }, [packs, query]);

  return (
    <ReviewFrame title="Research catalogue">
      <section className={styles.journeyHero}>
        <div className={styles.journeyInner}>
          <div className={styles.eyebrow}><span className={styles.eyebrowLine} /> THE RESEARCH SHELF / PRIVATE REVIEW</div>
          <h1>Ideas worth <em>examining.</em></h1>
          <p>Explore the underlying questions, the recorded evidence and the trade-offs. This is a design review of the real Prospector catalogue contract, not a checkout or an assertion of current availability.</p>
          <div className={styles.journeyMeta}>
            <span>{sourceAvailable ? `${packs.length} records returned from catalogue API` : 'Catalogue API unavailable'}</span>
            <span>Read-only · No purchases</span>
          </div>
        </div>
      </section>
      <section className={styles.journeyContent} aria-labelledby="catalogue-title">
        <div className={styles.journeySectionTitle}>
          <div>
            <span className={styles.journeyKicker}>01 / THE RECORDS</span>
            <h2 id="catalogue-title">The work, <em>not the hype.</em></h2>
          </div>
          <p>These records are pulled from the existing Store.Api interface. A record is not proof of stock, payment readiness or fulfilment.</p>
        </div>
        {sourceAvailable && packs.length > 0 && (
          <div className={styles.reviewSearch}>
            <label htmlFor="review-catalogue-search">Find a research subject</label>
            <input id="review-catalogue-search" type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search problem, industry, title or market" />
            <span aria-live="polite">{visible.length} of {packs.length} records</span>
          </div>
        )}
        {!sourceAvailable ? (
          <>
            <div className={styles.journeyEmpty} role="status">
              <span>LIVE SOURCE UNAVAILABLE</span>
              <h3>The original catalogue is offline.</h3>
              <p>The Store.Api response is unavailable. The four archive specimens below are separately recorded design examples, not live inventory or a substitute for commerce data.</p>
              <Link href="/experience">Return to the design overview <span aria-hidden="true">↗</span></Link>
            </div>
            <div className={styles.reviewArchiveHead}>
              <span className={styles.journeyKicker}>ARCHIVE / VISUAL SPECIMENS ONLY</span>
              <h2>Explore the <em>research concepts.</em></h2>
            </div>
            <div className={styles.reviewCatalogueGrid}>
              {REVIEW_ARCHIVE.map((record) => (
                <Link href={`/experience/specimen/${record.id}`} className={styles.reviewRecord} key={record.id}>
                  <div className={styles.reviewRecordArt}>
                    <Image src={record.image} alt="" fill sizes="(max-width: 690px) 100vw, (max-width: 1100px) 50vw, 33vw" />
                    <span>{record.index}</span>
                  </div>
                  <div className={styles.reviewRecordBody}>
                    <span className={styles.reviewRecordTag}>{record.label} / archive</span>
                    <h3>{record.title}</h3>
                    <p>{record.description}</p>
                    <div className={styles.reviewRecordFoot}>
                      <span>Recorded concept · Availability unverified</span>
                      <span aria-hidden="true">Examine ↗</span>
                    </div>
                  </div>
                </Link>
              ))}
            </div>
          </>
        ) : packs.length === 0 ? (
          <div className={styles.journeyEmpty} role="status">
            <span>EMPTY RESPONSE</span>
            <h3>No records were returned.</h3>
            <p>The API responded successfully, but returned an empty catalogue. This is not a claim that the business has no sellable products.</p>
          </div>
        ) : visible.length === 0 ? (
          <div className={styles.journeyEmpty} role="status">
            <span>NO MATCHES</span>
            <h3>Nothing matches that search.</h3>
            <p>Try another problem, market or category. Your search applies only to the records returned by the API.</p>
          </div>
        ) : (
          <div className={styles.reviewCatalogueGrid}>
            {visible.map((pack, index) => (
              <Link href={`/experience/dossier/${encodeURIComponent(pack.id)}`} className={styles.reviewRecord} key={pack.id}>
                <div className={styles.reviewRecordArt}>
                  <Image src={packImage(pack)} alt="" fill sizes="(max-width: 690px) 100vw, (max-width: 1100px) 50vw, 33vw" />
                  <span>{String(index + 1).padStart(2, '0')}</span>
                </div>
                <div className={styles.reviewRecordBody}>
                  <span className={styles.reviewRecordTag}>{pack.sector?.replaceAll('_', ' ') || 'Research record'}</span>
                  <h3>{pack.title}</h3>
                  <p>{pack.oneLine || pack.theProblem || 'Open the dossier to examine this research record.'}</p>
                  <div className={styles.reviewRecordFoot}>
                    <span>{typeof pack.sourceCount === 'number' && pack.sourceCount > 0 ? `${pack.sourceCount} recorded sources` : 'Evidence-led dossier'}</span>
                    <span aria-hidden="true">Explore ↗</span>
                  </div>
                </div>
              </Link>
            ))}
          </div>
        )}
      </section>
    </ReviewFrame>
  );
}

export const getServerSideProps: GetServerSideProps<CatalogueReviewProps> = async () => {
  // The real customer-facing catalogue is "/" — review routes are never public.
  if (process.env.VERCEL_ENV !== 'preview') return { notFound: true };
  try {
    const packs = await fetchCatalog({ signal: AbortSignal.timeout(2500) });
    return { props: { packs, sourceAvailable: true } };
  } catch {
    return { props: { packs: [], sourceAvailable: false } };
  }
};
