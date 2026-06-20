
/* Operator legal facts (legalName, address, contactEmail) come from LEGAL in @/lib/config — set them there once before go-live. */
/*
 * Draft legal copy — review with qualified counsel before go-live.
 * Digital goods refund policy: UK Consumer Contracts Regulations 2013,
 * cancellation-right waiver on download commencement, discretionary window,
 * how to request, dispute/chargeback note.
 */
import React from 'react';
import Link from 'next/link';
import LegalDoc, { LegalHeading, LegalText, LegalList } from '@/components/LegalDoc';
import { LEGAL } from '@/lib/config';
import Disclaimer from '@/components/Disclaimer';

/**
 * Refund Policy for the Prospector digital-download storefront.
 * Statutory basis: UK Consumer Contracts (Information, Cancellation and Additional Charges)
 * Regulations 2013, Regulation 37 — cancellation right is lost once digital content delivery
 * begins with the consumer's prior express consent and acknowledgement of loss of cancellation right.
 * Pending review by qualified legal counsel before go-live.
 */
export default function RefundPage() {
  return (
    <LegalDoc title="Refund Policy">

      <LegalText>
        This policy explains your rights and our approach to refunds when you purchase a Pack
        (digital download) from {LEGAL.entity}. Please read it alongside our{' '}
        <Link href="/terms" className="text-primary hover:underline">
          Terms of Service
        </Link>
        .
      </LegalText>

      <LegalHeading>1. Our 14 day money back guarantee</LegalHeading>
      <LegalText>
        Every Pack comes with a <strong>14 day money back guarantee, no questions asked</strong>.
        If a Pack is not what you expected for any reason, email us within 14 days of your purchase
        and we will refund you in full. You do not need to explain why. This is a voluntary guarantee
        we offer in addition to your statutory rights described below, and it gives you more
        protection than the law requires for digital goods.
      </LegalText>
      <LegalText>
        The guarantee covers one refund per customer per Pack and is intended for genuine buyers.
        We may decline a request only in cases of clear abuse, such as repeated buy and refund
        cycles across many Packs.
      </LegalText>

      <LegalHeading>2. Statutory cancellation right for digital goods</LegalHeading>
      <LegalText>
        Under the <strong>Consumer Contracts (Information, Cancellation and Additional Charges)
        Regulations 2013</strong> (SI&nbsp;2013/3134), consumers normally have a 14 day
        right to cancel a distance contract. However, Regulation&nbsp;37 provides that the
        cancellation right is <strong>lost once performance of a digital content contract
        begins</strong>, provided that:
      </LegalText>
      <LegalList
        items={[
          'the consumer has given prior express consent to delivery beginning before the end of the cancellation period; and',
          'the consumer has acknowledged that they will lose their right to cancel once delivery begins.',
        ]}
      />
      <LegalText>
        At checkout you are asked to confirm both of these points before your purchase
        completes. By confirming, you expressly consent to immediate delivery of the digital
        content and acknowledge that <strong>your statutory 14 day cancellation right is
        waived once your download link is issued or your download begins, whichever is
        earlier.</strong> Our voluntary guarantee in clause 1 still applies regardless.
      </LegalText>
      <LegalText>
        If you are purchasing in the course of a business (not as a consumer), the Consumer
        Contracts Regulations do not apply to your purchase, and no statutory cancellation
        right arises.
      </LegalText>

      <LegalHeading>3. Situations we also cover</LegalHeading>
      <LegalText>
        Beyond the 14 day guarantee in clause 1, the following always apply:
      </LegalText>
      <LegalList
        items={[
          <>
            <strong>Pack not downloaded within 14 days of purchase:</strong> if your download
            link was issued but you have not downloaded the file within 14 days of your order
            date, you may request a full refund. We will verify download status against our
            token records before approving.
          </>,
          <>
            <strong>Faulty or corrupted file:</strong> if the downloaded file is technically
            defective (for example, the file is corrupt, blank, or does not match the
            description of what was sold), report this any time and we will offer a corrected
            replacement or a full refund.
          </>,
          <>
            <strong>Duplicate purchase:</strong> if you accidentally purchased the same Pack
            twice in the same session, contact us and we will refund the duplicate charge.
          </>,
        ]}
      />

      <LegalHeading>4. How to request a refund</LegalHeading>
      <LegalText>
        To request a refund, email{' '}
        <a href={`mailto:${LEGAL.supportEmail}`} className="text-primary hover:underline">
          {LEGAL.supportEmail}
        </a>{' '}
        with:
      </LegalText>
      <LegalList
        items={[
          'the email address used at checkout;',
          'your order ID or order confirmation email; and',
          'for a faulty file: a brief description of the defect (a reason is not needed for a guarantee refund).',
        ]}
      />
      <LegalText>
        We aim to respond within 3 business days. Approved refunds are processed to the
        original payment method. The time for funds to appear in your account depends on your
        bank or card provider (typically 5 to 10 business days). We are not responsible for delays
        caused by your financial institution.
      </LegalText>

      <LegalHeading>5. Chargebacks and payment disputes</LegalHeading>
      <LegalText>
        We ask that you contact us at{' '}
        <a href={`mailto:${LEGAL.supportEmail}`} className="text-primary hover:underline">
          {LEGAL.supportEmail}
        </a>{' '}
        before raising a chargeback or payment dispute with your bank or card provider.
        Initiating an unfounded chargeback where a refund was not due under this policy, or
        where we had already issued a refund, may result in us contesting the dispute and
        providing evidence of delivery to your payment provider.
      </LegalText>

      <LegalHeading>6. Disclaimer on Pack content</LegalHeading>
      <Disclaimer />

      <LegalHeading>7. Contact</LegalHeading>
      <LegalText>
        Refund enquiries:{' '}
        <a href={`mailto:${LEGAL.supportEmail}`} className="text-primary hover:underline">
          {LEGAL.supportEmail}
        </a>
        . General legal enquiries:{' '}
        <a href={`mailto:${LEGAL.contactEmail}`} className="text-primary hover:underline">
          {LEGAL.contactEmail}
        </a>
        . Operator: {LEGAL.legalName}, {LEGAL.address}. See also our{' '}
        <Link href="/terms" className="text-primary hover:underline">
          Terms of Service
        </Link>{' '}
        and{' '}
        <Link href="/privacy" className="text-primary hover:underline">
          Privacy Policy
        </Link>
        .
      </LegalText>

    </LegalDoc>
  );
}
