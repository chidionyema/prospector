import React from 'react';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { PageHero, Section, CtaBand } from '@/components/marketing/blocks';
import { Seo } from '@/components/Seo';

export default function HowItWorks() {
  return (
    <MarketingLayout>
      <Seo 
        title="How it works" 
        description="The technical and economic logic behind reputation-backed introductions. Incentive alignment, professional discretion, and the cost of noise." 
      />

      <PageHero
        eyebrow="How it works"
        title={<span className="leading-tight tracking-tighter">Why this works when cold outreach doesn&apos;t.</span>}
        lead="Three design decisions, explained in plain English."
      />

      <Section
        bg="white"
        width="6xl"
        title={<span className="font-black">1. Money up front means everyone&apos;s serious</span>}
      >
        <div className="max-w-3xl space-y-6">
          <p className="text-lg font-normal leading-relaxed text-text/80">
            Cold outreach is free, which is exactly the problem. There&apos;s no cost to wasting someone&apos;s time. Here, a request only goes live once your bank has placed a hold on the reward. Connectors know every request they see is real. You know your money hasn&apos;t gone anywhere: it&apos;s a hold, not a charge, and it&apos;s released automatically if nothing happens.
          </p>
        </div>
      </Section>

      <Section
        bg="bg"
        width="6xl"
        title={<span className="font-black">2. Connectors are paid for judgement, not volume</span>}
      >
        <div className="max-w-3xl space-y-6">
          <p className="text-lg font-normal leading-relaxed text-text/80">
            A good connector&apos;s value isn&apos;t their contact list: it&apos;s knowing which intros are right. So connectors here are rewarded for saying no as much as yes. They decline anything that isn&apos;t a genuine fit, because their standing rests on the doors they open. That&apos;s why an intro from this platform gets answered: it arrives with someone&apos;s reputation behind it.
          </p>
        </div>
      </Section>

      <Section
        bg="white"
        width="6xl"
        title={<span className="font-black">3. Nobody&apos;s network is exposed</span>}
      >
         <div className="max-w-3xl space-y-6">
            <p className="text-lg font-normal leading-relaxed text-text/80">
              Requests are reviewed without names. A connector&apos;s contacts stay private until the person themselves accepts the intro. You can&apos;t browse anyone&apos;s network, scrape contacts, or go around the connector. That&apos;s deliberate: the moment networks become harvestable, people stop sharing them.
            </p>
         </div>
      </Section>

      <Section
        bg="bg"
        width="6xl"
        title={<span className="font-black">The honest limits</span>}
      >
         <div className="max-w-3xl space-y-6">
            <p className="text-lg font-normal leading-relaxed text-text/80">
              We verify two things: the intro is real, and the person is who they say they are. We cannot guarantee replies, meetings, or outcomes; no one honestly can. You&apos;re paying for a high-quality shot at the right conversation, vouched for by someone who knows both sides.
            </p>
         </div>
      </Section>

      <CtaBand
        title="See it from either side."
        lead=""
        primary={{ href: "/for-buyers", label: "Get an intro" }}
        secondary={{ href: "/for-connectors", label: "Make intros" }}
      />
    </MarketingLayout>
  );
}
