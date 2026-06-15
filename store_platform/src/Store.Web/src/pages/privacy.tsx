import React from 'react';
import Link from 'next/link';
import LegalDoc, { LegalHeading, LegalText, LegalList } from '@/components/LegalDoc';
import { LEGAL } from '@/lib/config';

/**
 * Interim Privacy Policy (L-05) including the Art.14-style notice to non-users whose details a
 * connector may have added to a private roster (L-01). Controller = us for accounts + roster targets;
 * Stripe independent for payments. Grounded in docs/legal/LEGAL-DECISIONS-LOG.md, pending counsel.
 */
export default function PrivacyPage() {
  return (
    <LegalDoc title="Privacy Policy">
      <LegalText>
        {LEGAL.entity} is the data controller for your account and for the platform. This notice explains
        what personal data we process, why, and the rights you have. We never sell personal data.
      </LegalText>

      <LegalHeading>What we collect and why</LegalHeading>
      <LegalList
        items={[
          'Account data (name or username, email, role, password hash), used to create and secure your account. Lawful basis: performance of our contract with you.',
          'Request and introduction data: the requests, offers, and introductions you create, to operate the marketplace.',
          'Payment data, handled by Stripe, our payment processor. We never see or store your full card details; card data is entered directly into Stripe.',
          'Usage and security logs, to keep the service safe and working. Lawful basis: our legitimate interests in security and reliability.',
        ]}
      />

      <LegalHeading>If a connector added you and you have not signed up</LegalHeading>
      <LegalText>
        A connector can privately note people they know (including a name and LinkedIn URL) so the
        platform can match them to a seeker&apos;s request. If that is you and you are not a user:
      </LegalText>
      <LegalList
        items={[
          'Our lawful basis for this is legitimate interests (running an introductions marketplace), balanced against your rights.',
          'Your details are never shown to a buyer. Only the connector who knows you, and you, ever see your identity, and only if you choose to accept an introduction after verifying yourself.',
          'You can object to this processing and ask us to remove your details at any time. Roster entries that never lead to an introduction are also automatically deleted after a limited period.',
        ]}
      />
      <LegalText>
        To object or be removed, use our{' '}
        <Link href="/remove-me" className="text-primary hover:underline">
          Data Opt-Out page
        </Link>
        {'. '}No account needed.
      </LegalText>

      <LegalHeading>Who we share data with</LegalHeading>
      <LegalText>
        We use a small number of sub-processors to run the service: Stripe (payments), Resend
        (transactional email), and our hosting and infrastructure providers. Some are based outside the
        UK; where that is so, transfers are protected by appropriate safeguards. We share data with them
        only as needed to operate the platform, and with authorities where the law requires.
      </LegalText>

      <LegalHeading>How long we keep it</LegalHeading>
      <LegalText>
        We keep account and transaction records for as long as needed to provide the service and to meet
        legal and financial-record obligations, then delete or anonymise them. Un-activated roster
        entries are purged automatically after a limited period.
      </LegalText>

      <LegalHeading>Your rights</LegalHeading>
      <LegalText>
        You can ask to access, correct, delete, or object to the processing of your personal data, and to
        restrict it or receive a copy. To exercise any of these rights, contact{' '}
        <a href={`mailto:${LEGAL.contactEmail}`} className="text-primary hover:underline">
          {LEGAL.contactEmail}
        </a>{' '}
        or, if you are not a user, use the{' '}
        <Link href="/remove-me" className="text-primary hover:underline">
          Data Opt-Out page
        </Link>
        . You also have the right to complain to the UK Information Commissioner&apos;s Office (ICO).
      </LegalText>

      <LegalHeading>Search engines and public pages</LegalHeading>
      <LegalText>
        Only our marketing and legal pages are public and open to search engines. We never place your
        personal data, a request&apos;s details, or anyone&apos;s identity on a publicly indexable page,
        so there is nothing about you for a search engine to index or cache. Your account and the people
        you note live behind sign-in and are kept out of search engines. In the rare event something was
        ever published and then removed, we would also ask the search engines to drop it from their cache.
      </LegalText>

      <LegalHeading>Cookies</LegalHeading>
      <LegalText>
        We use only the cookies and local session storage needed to keep you signed in and the service
        secure. We do not use advertising or third-party tracking cookies.
      </LegalText>

      <LegalHeading>Contact</LegalHeading>
      <LegalText>
        For any privacy question, email{' '}
        <a href={`mailto:${LEGAL.contactEmail}`} className="text-primary hover:underline">
          {LEGAL.contactEmail}
        </a>
        .
      </LegalText>
    </LegalDoc>
  );
}
