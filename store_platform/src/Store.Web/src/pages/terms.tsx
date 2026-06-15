import React from 'react';
import Link from 'next/link';
import LegalDoc, { LegalHeading, LegalText, LegalList } from '@/components/LegalDoc';
import { LEGAL } from '@/lib/config';

/**
 * Interim Terms of Service (L-04). B2B framing, platform-as-facilitator, no-outcome-guarantee,
 * acceptable-use (L-02), funds-held-by-your-bank (L-03), auto-release disclosure (L-06),
 * governing law E&W (L-11). Grounded in docs/legal/LEGAL-DECISIONS-LOG.md, pending counsel.
 */
export default function TermsPage() {
  return (
    <LegalDoc title="Terms of Service">
      <LegalText>
        These terms are a contract between you and {LEGAL.entity} (&ldquo;we&rdquo;, &ldquo;us&rdquo;).
        By creating an account you confirm you accept them. The Intro Exchange is a marketplace
        for warm professional introductions: a <strong>buyer</strong> posts a request describing someone
        they want to meet, and a <strong>connector</strong> who genuinely knows a matching person can
        offer to make that introduction in exchange for the reward.
      </LegalText>

      <LegalHeading>1. Who can use the platform</LegalHeading>
      <LegalText>
        The service is for <strong>business and professional use only</strong>. By registering you
        confirm you are acting in the course of a business or profession and not as a consumer, that you
        are at least 18, and that you have authority to enter into this contract.
      </LegalText>

      <LegalHeading>2. We facilitate, we are not a party to the introduction</LegalHeading>
      <LegalText>
        We provide the platform that connects buyers and connectors. We are <strong>not</strong> a party
        to any introduction, and we do not guarantee that an introduction will lead to a meeting, a
        response, a deal, or any other outcome. The reward is for a delivered, double-opted-in
        introduction to a person matching the request, never a decision, a result, or anyone&apos;s
        ongoing cooperation.
      </LegalText>

      <LegalHeading>3. Acceptable use</LegalHeading>
      <LegalText>You must not use the platform to seek or make an introduction that is:</LegalText>
      <LegalList
        items={[
          'to or for a public official acting in their official capacity, or otherwise intended to corruptly influence any person or function (we operate to comply with the Bribery Act 2010);',
          'a referral within a regulated profession (for example financial, legal, or insurance services) where paying a referral fee is restricted or prohibited;',
          'based on personal data of a third party that you have no genuine relationship with, or that you obtained by scraping or bulk collection.',
        ]}
      />
      <LegalText>
        You confirm these points for each request when you create it. We may suspend or remove accounts
        and requests that breach this policy.
      </LegalText>

      <LegalHeading>4. Money: how funding and payment work</LegalHeading>
      <LegalText>
        When you fund a request, your payment is processed by <strong>Stripe</strong>. Your bank places an
        authorisation hold on the reward amount. The money stays with your bank and is only taken once
        the introduction is delivered and you approve it (or it auto-releases, see below). We never take
        custody of your funds and we are not a bank or a payment institution; Stripe is the regulated
        payment processor. A non-refundable platform fee is charged at the time you fund.
      </LegalText>
      <LegalText>
        <strong>Auto-release:</strong> once an introduction becomes active (the person being introduced
        has verified and accepted), if you take no action within the disclosed settlement window the held
        amount is released to the connector automatically. This window is shown to you before you fund.
      </LegalText>

      <LegalHeading>5. Refunds and disputes</LegalHeading>
      <LegalText>
        If an introduction is never delivered (for example, the person does not accept within the time
        limit), the hold is voided and nothing is taken from you. If you have a dispute about a delivered
        introduction you can raise it through the platform before the funds release. Our refund and
        dispute handling is described when you fund and may evolve during the beta.
      </LegalText>

      <LegalHeading>6. Your content and connectors&apos; claims</LegalHeading>
      <LegalText>
        Connectors are responsible for the accuracy of what they say about a possible introduction and
        warrant that they have a genuine relationship with the person. You are responsible for the
        content you post. You grant us a licence to use the content you submit only as needed to operate
        the platform.
      </LegalText>

      <LegalHeading>7. Liability</LegalHeading>
      <LegalText>
        We provide the platform &ldquo;as is&rdquo;. To the extent the law allows, we are not liable for
        the conduct of buyers, connectors, or introduced people, or for any business outcome. Nothing in
        these terms limits liability that cannot be limited by law.
      </LegalText>

      <LegalHeading>8. Taxes</LegalHeading>
      <LegalText>
        Connectors are responsible for declaring and paying any tax due on reward income. We may be
        required to collect and report connector income to HMRC under digital-platform reporting rules.
        We do not give tax advice.
      </LegalText>

      <LegalHeading>9. Changes, suspension and termination</LegalHeading>
      <LegalText>
        We may update these terms; the current version and its version number are always shown at the top
        of this page. We may suspend or end your access if you breach these terms. You can stop using the
        platform at any time.
      </LegalText>

      <LegalHeading>10. Governing law</LegalHeading>
      <LegalText>
        These terms are governed by the law of {LEGAL.governingLaw}, and the courts of{' '}
        {LEGAL.governingLaw} have exclusive jurisdiction. For privacy and your data rights, see our{' '}
        <Link href="/privacy" className="text-primary hover:underline">
          Privacy Policy
        </Link>
        . Questions: <a href={`mailto:${LEGAL.contactEmail}`} className="text-primary hover:underline">{LEGAL.contactEmail}</a>.
      </LegalText>
    </LegalDoc>
  );
}
