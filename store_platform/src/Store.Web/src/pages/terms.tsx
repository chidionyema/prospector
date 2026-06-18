
/* TODO: replace [OPERATOR LEGAL NAME], [CONTACT EMAIL], [BUSINESS ADDRESS] before go-live */
/*
 * Draft legal copy — review with qualified counsel before go-live.
 * Covers: digital download licence, delivery, buyer obligations, limitation of liability,
 * no-warranty on AI-generated content, governing law England & Wales.
 */
import React from 'react';
import Link from 'next/link';
import LegalDoc, { LegalHeading, LegalText, LegalList } from '@/components/LegalDoc';
import { LEGAL } from '@/lib/config';
import Disclaimer from '@/components/Disclaimer';

/**
 * Terms of Service for the Prospector digital-download storefront.
 * Covers: what is sold (AI-generated business-analysis dossier, digital download),
 * licence grant, delivery, buyer obligations, limitation of liability,
 * no-warranty on AI output quality, governing law E&W.
 * Pending review by qualified legal counsel before go-live.
 */
export default function TermsPage() {
  return (
    <LegalDoc title="Terms of Service">

      <LegalText>
        These Terms of Service (&ldquo;Terms&rdquo;) form a legally binding contract between you
        (&ldquo;you&rdquo;, &ldquo;buyer&rdquo;) and {LEGAL.entity} (&ldquo;we&rdquo;,
        &ldquo;us&rdquo;, &ldquo;our&rdquo;). By completing a purchase you confirm that you have
        read, understood, and agree to these Terms. If you do not agree, do not purchase.
      </LegalText>

      <LegalHeading>1. What we sell</LegalHeading>
      <LegalText>
        We sell digital information products (&ldquo;Packs&rdquo;). Each Pack is an
        AI-generated, source-grounded business-opportunity dossier delivered as a
        digital download (PDF and/or structured data file). Packs are <strong>information
        products only</strong> — they are not financial advice, investment advice, legal advice,
        or any other form of professional advisory service.
      </LegalText>

      <LegalHeading>2. Licence to use</LegalHeading>
      <LegalText>
        On completed payment we grant you a <strong>personal, non-exclusive, non-transferable,
        non-sublicensable licence</strong> to access, read, and use the Pack content for your
        own personal or internal business research purposes. You may not:
      </LegalText>
      <LegalList
        items={[
          'resell, redistribute, sublicence, or otherwise make the Pack content available to any third party, whether for payment or free of charge;',
          'pass off the Pack content as your own original research or analysis;',
          'use the Pack content to train, fine-tune, or otherwise develop machine-learning models without our prior written consent;',
          'remove or obscure any copyright notice, disclaimer, or attribution contained in the Pack.',
        ]}
      />

      <LegalHeading>3. Delivery</LegalHeading>
      <LegalText>
        After your payment is confirmed, access to the Pack is provided by means of a
        time-limited download link sent to the email address you supplied at checkout and/or
        made available immediately on-screen. Delivery is deemed complete when the download
        link is made available. It is your responsibility to download the file promptly and to
        ensure that your email address is correct at the time of purchase. If you experience a
        technical problem preventing download, contact us at{' '}
        <a href={`mailto:${LEGAL.supportEmail}`} className="text-primary hover:underline">
          {LEGAL.supportEmail}
        </a>{' '}
        within 14 days of purchase.
      </LegalText>

      <LegalHeading>4. Prices and payment</LegalHeading>
      <LegalText>
        All prices are shown in GBP (£) and are inclusive of VAT where applicable. Payment is
        processed by our third-party payment processor (currently Paddle or Stripe — see the
        checkout page for the active processor). We do not store your full card details.
        A transaction is complete when you receive an order-confirmation email.
      </LegalText>

      <LegalHeading>5. Buyer obligations</LegalHeading>
      <LegalText>
        You warrant and represent that:
      </LegalText>
      <LegalList
        items={[
          'you are at least 18 years old;',
          'you are not purchasing on behalf of a consumer where different statutory rights apply unless you are acting in the course of a trade, business, craft, or profession;',
          'any information you provide at checkout (in particular your email address) is accurate and complete;',
          'you will use the Pack in compliance with all applicable laws and regulations.',
        ]}
      />

      <LegalHeading>6. Nature of AI-generated content — no warranty</LegalHeading>
      <LegalText>
        Packs are produced by automated AI systems and are provided <strong>&ldquo;as
        is&rdquo;</strong>. While we use source-grounding and editorial processes to improve
        accuracy, <strong>we make no warranty, express or implied, that the Pack content is
        accurate, complete, current, or fit for any particular purpose.</strong> AI-generated
        content may contain errors, omissions, or outdated information. You are responsible for
        conducting your own independent due diligence before acting on any information contained
        in a Pack.
      </LegalText>
      <LegalText>
        Nothing in a Pack constitutes financial advice, investment advice, legal advice, tax
        advice, or any other professional or regulated advice. See our disclaimer below.
      </LegalText>

      <Disclaimer />

      <LegalHeading>7. Limitation of liability</LegalHeading>
      <LegalText>
        To the fullest extent permitted by applicable law:
      </LegalText>
      <LegalList
        items={[
          'our total aggregate liability to you in connection with any purchase or these Terms shall not exceed the amount you paid for the relevant Pack;',
          'we are not liable for any indirect, consequential, special, or exemplary loss, including loss of profits, loss of opportunity, or loss of data, even if we have been advised of the possibility of such loss;',
          'we are not liable for any loss arising from your reliance on Pack content for a commercial, investment, or financial decision.',
        ]}
      />
      <LegalText>
        Nothing in these Terms limits liability for death or personal injury caused by our
        negligence, fraud, or any other liability that cannot be excluded or limited by law.
      </LegalText>

      <LegalHeading>8. Intellectual property</LegalHeading>
      <LegalText>
        All intellectual property rights in and to the Packs (including underlying data,
        prompts, and formatted output) are owned by or licensed to {LEGAL.entity}. These Terms
        do not transfer any ownership rights to you; the licence in clause&nbsp;2 is the full
        extent of your rights.
      </LegalText>

      <LegalHeading>9. Changes and availability</LegalHeading>
      <LegalText>
        We may update or withdraw Packs from sale at any time. We may update these Terms;
        the version date shown at the top of this page is the current version. Continued use
        of the service after a material change constitutes acceptance of the revised Terms.
        We will endeavour to notify you of material changes by email.
      </LegalText>

      <LegalHeading>10. Governing law and jurisdiction</LegalHeading>
      <LegalText>
        These Terms are governed by the law of {LEGAL.governingLaw}. You and we both agree
        to submit to the exclusive jurisdiction of the courts of {LEGAL.governingLaw}, save
        that if you are a consumer resident in Scotland, Northern Ireland, or the EU, you may
        also bring proceedings in the courts of your country of residence.
      </LegalText>

      <LegalHeading>11. Contact</LegalHeading>
      <LegalText>
        Questions about these Terms or your purchase:{' '}
        <a href={`mailto:${LEGAL.contactEmail}`} className="text-primary hover:underline">
          {LEGAL.contactEmail}
        </a>
        . Operator: [OPERATOR LEGAL NAME], [BUSINESS ADDRESS]. For our refund policy, see{' '}
        <Link href="/refund" className="text-primary hover:underline">
          Refund Policy
        </Link>
        . For privacy, see our{' '}
        <Link href="/privacy" className="text-primary hover:underline">
          Privacy Policy
        </Link>
        .
      </LegalText>

    </LegalDoc>
  );
}
