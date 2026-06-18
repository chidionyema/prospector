
/* TODO: replace [OPERATOR LEGAL NAME], [CONTACT EMAIL], [BUSINESS ADDRESS] before go-live */
/*
 * Draft legal copy — review with qualified counsel before go-live.
 * UK/EU storefront privacy policy: data collected, lawful basis, retention,
 * third parties, data subject rights (UK GDPR), contact.
 */
import React from 'react';
import Link from 'next/link';
import LegalDoc, { LegalHeading, LegalText, LegalList } from '@/components/LegalDoc';
import { LEGAL } from '@/lib/config';

/**
 * Privacy Policy for the Prospector digital-download storefront.
 * Covers: data collected (email, payment via Stripe/Paddle, download tokens),
 * lawful basis, retention, sub-processors (Stripe/Paddle, Postmark, storage),
 * UK GDPR data subject rights, contact.
 * Pending review by qualified legal counsel before go-live.
 */
export default function PrivacyPage() {
  return (
    <LegalDoc title="Privacy Policy">

      <LegalText>
        {LEGAL.entity} (&ldquo;we&rdquo;, &ldquo;us&rdquo;, &ldquo;our&rdquo;) is the data
        controller for personal data collected through this storefront. This policy explains
        what personal data we collect, why we collect it, how long we keep it, who we share it
        with, and the rights you have under UK data-protection law (UK GDPR and the Data
        Protection Act 2018). We never sell your personal data.
      </LegalText>
      <LegalText>
        Our registered details: [OPERATOR LEGAL NAME], [BUSINESS ADDRESS]. Contact for privacy
        matters:{' '}
        <a href={`mailto:${LEGAL.contactEmail}`} className="text-primary hover:underline">
          {LEGAL.contactEmail}
        </a>
        .
      </LegalText>

      <LegalHeading>1. What we collect and why</LegalHeading>
      <LegalList
        items={[
          <>
            <strong>Order and account data</strong> — your email address, name (if provided),
            order ID, and purchase history. We use this to process your order, deliver your
            download, and provide customer support. Lawful basis: performance of our contract
            with you (UK GDPR Art.&nbsp;6(1)(b)).
          </>,
          <>
            <strong>Payment data</strong> — payment is processed entirely by our payment
            processor (Stripe or Paddle, depending on which is active at checkout). We never
            see or store your full card number, CVV, or bank-account details. We receive only
            a payment confirmation and a transaction reference. The payment processor is an
            independent data controller for the card data it processes; please review their
            privacy policy for details.
          </>,
          <>
            <strong>Download tokens</strong> — a unique, time-limited token generated at the
            point of purchase to authenticate your download request. We store the token hash
            (not the raw token), the order it relates to, and whether it has been used.
            Lawful basis: performance of our contract with you.
          </>,
          <>
            <strong>Transactional email metadata</strong> — delivery receipts and open/click
            events recorded by our email provider to confirm that order-confirmation and
            download emails were delivered successfully. Lawful basis: legitimate interests in
            ensuring delivery of purchased goods.
          </>,
          <>
            <strong>Technical and security logs</strong> — server access logs (IP address,
            user-agent, request path, timestamp) retained for a short period for fraud
            detection and infrastructure security. Lawful basis: legitimate interests in
            operating a secure service.
          </>,
        ]}
      />

      <LegalHeading>2. Cookies and local storage</LegalHeading>
      <LegalText>
        We use only the cookies and browser storage strictly necessary to process your order
        (for example, to maintain a checkout session). We do not use advertising, analytics, or
        third-party tracking cookies. Our payment processor may set cookies on the checkout
        page; those are governed by its own cookie policy.
      </LegalText>

      <LegalHeading>3. Who we share data with</LegalHeading>
      <LegalText>
        We share personal data only as necessary to operate this storefront. Our current
        sub-processors are:
      </LegalText>
      <LegalList
        items={[
          <>
            <strong>Stripe, Inc.</strong> or <strong>Paddle.com Market Limited</strong> —
            payment processing. Acting as independent data controller for card and payment
            data; data may be transferred outside the UK under appropriate safeguards.
          </>,
          <>
            <strong>Postmark (Wildbit LLC / ActiveCampaign)</strong> — transactional email
            (order confirmations, download links). Processes your email address and message
            metadata on our behalf; data may be transferred outside the UK.
          </>,
          <>
            <strong>Cloud infrastructure and storage provider</strong> — hosts the application
            and stores order records. Operating under a data-processing agreement on our
            instructions.
          </>,
        ]}
      />
      <LegalText>
        We will also disclose personal data to law-enforcement authorities or regulators where
        required by law. We do not share data for marketing by third parties.
      </LegalText>

      <LegalHeading>4. International transfers</LegalHeading>
      <LegalText>
        Some of our sub-processors are based or process data outside the UK. Where this is the
        case, we ensure that appropriate safeguards are in place (such as the International
        Data Transfer Agreement (IDTA) or UK addendum to the EU Standard Contractual Clauses)
        as required by UK GDPR Chapter V.
      </LegalText>

      <LegalHeading>5. How long we keep your data</LegalHeading>
      <LegalList
        items={[
          'Order records (name, email, purchase, download token hash): retained for 7 years from the date of purchase to comply with UK financial record-keeping obligations, then securely deleted or anonymised.',
          'Security and access logs: retained for up to 90 days, then deleted.',
          'Transactional email metadata: retained for up to 12 months, then deleted.',
          'Download tokens: expired tokens are purged within 30 days of expiry.',
        ]}
      />

      <LegalHeading>6. Your rights under UK GDPR</LegalHeading>
      <LegalText>
        You have the following rights regarding your personal data. To exercise any of them,
        contact us at{' '}
        <a href={`mailto:${LEGAL.contactEmail}`} className="text-primary hover:underline">
          {LEGAL.contactEmail}
        </a>
        :
      </LegalText>
      <LegalList
        items={[
          <><strong>Right of access</strong> — to obtain a copy of the personal data we hold about you.</>,
          <><strong>Right to rectification</strong> — to ask us to correct inaccurate or incomplete data.</>,
          <><strong>Right to erasure</strong> — to ask us to delete your data, subject to our legal retention obligations.</>,
          <><strong>Right to restriction</strong> — to ask us to suspend processing while a dispute is resolved.</>,
          <><strong>Right to data portability</strong> — to receive your data in a structured, machine-readable format.</>,
          <><strong>Right to object</strong> — to object to processing based on legitimate interests.</>,
          <><strong>Right to withdraw consent</strong> — where we rely on consent as a lawful basis (currently we do not), you may withdraw it at any time.</>,
        ]}
      />
      <LegalText>
        We will respond to your request within one calendar month. If you are not satisfied
        with our response, you have the right to lodge a complaint with the UK Information
        Commissioner&apos;s Office (ICO) at{' '}
        <a
          href="https://ico.org.uk"
          target="_blank"
          rel="noopener noreferrer"
          className="text-primary hover:underline"
        >
          ico.org.uk
        </a>{' '}
        or by calling 0303&nbsp;123&nbsp;1113.
      </LegalText>

      <LegalHeading>7. Security</LegalHeading>
      <LegalText>
        We implement appropriate technical and organisational measures to protect your personal
        data against unauthorised access, disclosure, alteration, or destruction, including
        encrypted storage and transport (TLS), access controls, and regular security reviews.
        No transmission over the internet is entirely secure; if you have reason to believe that
        your interaction with us is no longer secure, please notify us immediately.
      </LegalText>

      <LegalHeading>8. Changes to this policy</LegalHeading>
      <LegalText>
        We may update this policy from time to time. The version date at the top of the page
        reflects the current version. If we make material changes we will notify you by email
        (if we hold your email address) or by posting a prominent notice on this page.
      </LegalText>

      <LegalHeading>9. Contact</LegalHeading>
      <LegalText>
        For any privacy question or to exercise your data-subject rights, email{' '}
        <a href={`mailto:${LEGAL.contactEmail}`} className="text-primary hover:underline">
          {LEGAL.contactEmail}
        </a>
        . Operator: [OPERATOR LEGAL NAME], [BUSINESS ADDRESS]. See also our{' '}
        <Link href="/terms" className="text-primary hover:underline">
          Terms of Service
        </Link>{' '}
        and{' '}
        <Link href="/refund" className="text-primary hover:underline">
          Refund Policy
        </Link>
        .
      </LegalText>

    </LegalDoc>
  );
}
