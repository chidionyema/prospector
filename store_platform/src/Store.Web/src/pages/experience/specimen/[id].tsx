import type { GetServerSideProps } from 'next';
import Image from 'next/image';
import Link from 'next/link';
import { ReviewFrame } from '@/components/experience/ReviewFrame';
import { REVIEW_ARCHIVE } from '@/lib/reviewArchive';
import styles from '@/pages/experience.module.css';

type ArchiveRecord = (typeof REVIEW_ARCHIVE)[number];
interface SpecimenProps { record: ArchiveRecord }

export default function SpecimenReview({ record }: SpecimenProps) {
  return (
    <ReviewFrame title={record.title}>
      <section className={styles.journeyHero}>
        <div className={styles.journeyInner}>
          <Link href="/experience/catalogue" className={styles.reviewBack}>← Back to the catalogue review</Link>
          <div className={styles.eyebrow}><span className={styles.eyebrowLine} /> RESEARCH ARCHIVE / DESIGN SPECIMEN {record.index}</div>
          <h1>{record.title}</h1>
          <p>{record.description}</p>
          <div className={styles.journeyMeta}>
            <span>Archived concept · {record.label}</span>
            <span>No inventory claim · No purchase</span>
          </div>
        </div>
      </section>
      <section className={styles.journeyContent}>
        <div className={styles.reviewDossierGrid}>
          <article className={styles.reviewDossierMain}>
            <span className={styles.journeyKicker}>01 / THE OPPORTUNITY CONCEPT</span>
            <h2>Examine the question <em>before the conclusion.</em></h2>
            <p className={styles.reviewDossierLead}>{record.description}</p>
            <div className={styles.reviewDossierSection}>
              <span className={styles.journeyKicker}>02 / WHAT THIS PAGE REPRESENTS</span>
              <h3>A concept, not a verdict.</h3>
              <p>This record appears in the existing Mumchimp design archive. It is used to assess the presentation of a research dossier. It is not represented here as a currently published, verified, in-stock or purchasable product.</p>
              <p>The original Prospector API must supply the full dossier, citations, risk findings and terms before any customer-facing claims or transaction controls are displayed.</p>
            </div>
            <div className={styles.reviewRisk}>
              <span className={styles.journeyKicker}>EVIDENCE BOUNDARY</span>
              <h3>No findings have been manufactured.</h3>
              <p>Source citations, financial projections, verification dates, prices and acceptance findings are intentionally absent from this specimen. Their absence is not evidence that the opportunity has passed review.</p>
            </div>
          </article>
          <aside className={styles.reviewDossierAside} aria-label="Archive record identification">
            <div className={styles.reviewDossierArtwork}>
              <Image src={record.image} alt="" fill sizes="(max-width: 850px) 90vw, 360px" priority />
            </div>
            <div className={styles.reviewDossierFacts}>
              <span className={styles.journeyKicker}>ARCHIVE ENTRY</span>
              <dl>
                <div><dt>Concept</dt><dd>{record.title}</dd></div>
                <div><dt>Recorded category</dt><dd>{record.label}</dd></div>
                <div><dt>Archive reference</dt><dd>{record.id}</dd></div>
                <div><dt>Availability</dt><dd>Not verified</dd></div>
              </dl>
              <p>Private visual specimen. No customer registration, payment, or download endpoint is present on this page.</p>
            </div>
          </aside>
        </div>
        <div className={styles.reviewNext}>
          <span className={styles.journeyKicker}>CONTINUE THE DESIGN REVIEW</span>
          <h2>The complete journey. <em>Without false certainty.</em></h2>
          <Link href="/experience/catalogue" className={styles.primaryAction}>Back to the research shelf <span aria-hidden="true">↗</span></Link>
        </div>
      </section>
    </ReviewFrame>
  );
}

export const getServerSideProps: GetServerSideProps<SpecimenProps> = async ({ params }) => {
  if (process.env.VERCEL_ENV !== 'preview') return { notFound: true };
  const id = params?.id;
  if (typeof id !== 'string') return { notFound: true };
  const record = REVIEW_ARCHIVE.find((entry) => entry.id === id);
  if (!record) return { notFound: true };
  return { props: { record } };
};
