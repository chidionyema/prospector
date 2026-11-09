import Head from 'next/head';
import Link from 'next/link';
import type { ReactNode } from 'react';
import styles from '@/pages/experience.module.css';

/**
 * Shared chrome for the private, read-only buyer-journey review.
 * Keep it outside the app's marketing/auth/checkout shell: this frame never
 * reads customer identity or offers a transaction.
 */
export function ReviewFrame({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className={styles.shell}>
      <Head>
        <title>{title} | Mumchimp review</title>
        <meta name="robots" content="noindex, nofollow, noarchive" />
        <meta name="description" content="Private non-transactional design review using recorded research and the Prospector catalogue contract." />
      </Head>
      <a href="#review-content" className={styles.skip}>Skip to content</a>
      <div className={styles.review}>
        <span className={styles.reviewDot} aria-hidden="true" />
        <span>PRIVATE DESIGN REVIEW</span>
        <span className={styles.reviewDivider} aria-hidden="true" />
        <span>Not a live shop. No transactions.</span>
      </div>
      <header className={styles.header}>
        <div className={styles.headerInner}>
          <Link href="/experience" className={styles.brand} aria-label="Mumchimp experience review">
            <span className={styles.brandMark} aria-hidden="true"><span /><span /><span /></span>
            <span><strong>Mum</strong>chimp<span className={styles.brandPeriod}>.</span></span>
          </Link>
          <nav className={styles.nav} aria-label="Review journey">
            <Link href="/experience">Overview</Link>
            <Link href="/experience/catalogue">Catalogue</Link>
            <Link href="/experience#method">Our method</Link>
          </nav>
          <Link href="/experience/catalogue" className={styles.headerAction}>Browse the records <span aria-hidden="true">↗</span></Link>
        </div>
      </header>
      <main id="review-content">{children}</main>
      <footer className={styles.footer}>
        <div>
          <Link href="/experience" className={styles.footerBrand}>Mumchimp<span>.</span></Link>
          <p>Evidence before commitment. The review is read-only; buyer functionality is operated separately.</p>
        </div>
        <div className={styles.footerNav}>
          <Link href="/experience">Overview</Link>
          <Link href="/experience/catalogue">Catalogue review</Link>
          <Link href="/sample">Free sample</Link>
          <Link href="/terms">Terms</Link>
        </div>
        <div className={styles.footerBase}>
          <span>PRIVATE VISUAL REVIEW · NO TRANSACTIONS</span>
          <span>Product of Merdian Intelligence</span>
        </div>
      </footer>
    </div>
  );
}
