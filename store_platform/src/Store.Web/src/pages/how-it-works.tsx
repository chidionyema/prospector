import React from 'react';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { PageHero, Section, CtaBand } from '@/components/marketing/blocks';
import { Seo } from '@/components/Seo';

export default function HowItWorks() {
  return (
    <MarketingLayout>
      <Seo
        title="How it works"
        description="How the Prospector Store works: every £49 pack is a grounded business opportunity, vetted against six checks and sourced to retrievable evidence before it can be listed."
      />

      <PageHero
        eyebrow="The panel"
        title={<span className="leading-tight tracking-tighter">Every idea faces a panel built to kill it.</span>}
        lead="Before anything reaches the store, it runs a gauntlet of AI agents that each hunt for the reason it fails. Here is exactly how an idea earns its place."
      />

      <Section
        bg="white"
        width="6xl"
        title={<span className="font-black">1. A panel of agents, each hunting a reason to kill it</span>}
      >
        <div className="max-w-3xl space-y-6">
          <p className="text-lg font-normal leading-relaxed text-text/80">
            Every candidate faces the same six checks: real pain, durable value, room past the incumbents, a payer who can actually pay, a route to distribution, and legality. The panel kills fast at the first hard fail. Only ideas that clear every gate and survive an adversarial cross examination become a pack, and every kill is logged with its reason, so the filter is auditable, not a black box.
          </p>
        </div>
      </Section>

      <Section
        bg="bg"
        width="6xl"
        title={<span className="font-black">2. Every claim is sourced, or it doesn&apos;t ship</span>}
      >
        <div className="max-w-3xl space-y-6">
          <p className="text-lg font-normal leading-relaxed text-text/80">
            Source or die: every factual claim and number in a pack cites a retrievable source, or it&apos;s marked unverifiable. The engine rules only on evidence it actually fetched, never on hand waving. No unsourced figures ever make it into a pack you buy.
          </p>
        </div>
      </Section>

      <Section
        bg="white"
        width="6xl"
        title={<span className="font-black">3. What&apos;s inside a £49 pack</span>}
      >
        <div className="max-w-3xl space-y-6">
          <p className="text-lg font-normal leading-relaxed text-text/80">
            Each pack bundles a Blueprint (the opportunity, the evidence, and why it clears the bar), a GTM plan (who pays, where they are, and how to reach them), and a Build Kit (the concrete steps to ship). You pay £49, checkout runs through Stripe, and the pack downloads instantly.
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
            A pack is grounded research, not a guarantee. It&apos;s a high quality, evidence backed starting point. The work of finding, vetting, and sourcing the opportunity is done for you. Execution is still yours, and no analysis can promise a business outcome.
          </p>
        </div>
      </Section>

      <CtaBand
        title="See what made it through."
        lead=""
        primary={{ href: '/', label: 'Browse the packs' }}
      />
    </MarketingLayout>
  );
}
