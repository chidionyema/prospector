import React from 'react';
import Link from 'next/link';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { PageHero, Section, CtaBand } from '@/components/marketing/blocks';
import { Seo } from '@/components/Seo';
import { LEGAL } from '@/lib/config';

const FAQS: { q: string; a: React.ReactNode }[] = [
  {
    q: 'What am I actually paying for?',
    a: (
      <>
        A warm intro to the right person, made by a super-connector who knows them and believes the fit is real. The person confirms their identity when they accept, so you know you&apos;re meeting a real, named individual.
      </>
    ),
  },
  {
    q: "Isn&apos;t this just paying to pester people?",
    a: (
      <>
        No. It&apos;s designed so it can&apos;t become that. Every intro is made by a connector who already knows the person and thinks it&apos;s a genuine fit for both sides. The person has to accept before you ever meet. We don&apos;t sell contact details and we don&apos;t do cold outreach.
      </>
    ),
  },
  {
    q: 'Are you holding my money?',
    a: (
      <>
        No, and that&apos;s rather the point. The reward is a hold with your own bank, via Stripe, like a hotel deposit. We can&apos;t touch it. It becomes a charge only when you approve a completed intro.
      </>
    ),
  },
  {
    q: 'What if no one takes my request?',
    a: (
      <>
        Your bank releases the hold automatically. The only thing you&apos;ve spent is the posting fee.
      </>
    ),
  },
  {
    q: 'What if the meeting goes nowhere?',
    a: (
      <>
        That can happen. We can&apos;t promise outcomes, and we won&apos;t pretend otherwise. What we promise: the intro was real, the person was verified, and you approved it before paying.
      </>
    ),
  },
  {
    q: "Why don&apos;t I see names when I review an offer?",
    a: (
      <>
        Two reasons. You judge the opportunity on its merits, and the connector&apos;s relationships stay private. You meet the person once they&apos;ve agreed to the intro.
      </>
    ),
  },
  {
    q: 'Could someone steal my contacts through this?',
    a: (
      <>
        No. Reviews are identity-blind, networks aren&apos;t browsable, and a contact&apos;s identity is only revealed when they personally accept an intro.
      </>
    ),
  },
  {
    q: 'Do connectors have to take my request?',
    a: (
      <>
        No. You should be glad of that. Connectors only advance requests they can genuinely help with, because their standing depends on it. Their &quot;no&quot; is what makes their &quot;yes&quot; worth paying for.
      </>
    ),
  },
  {
    q: 'Why would the person want to meet me?',
    a: (
      <>
        Because a good intro is worth their time too. The connector only brings two people together when the fit works both ways, and the person accepts on their own terms.
      </>
    ),
  },
  {
    q: 'What does the connector get?',
    a: (
      <>
        The reward, minus our cut, paid only when the intro is accepted. Their incentive is the same as yours: a genuine fit.
      </>
    ),
  },
  {
    q: 'Is this live right now?',
    a: (
      <>
        Yes. Everything on this site is working today. We&apos;re in private beta and growing the connector network carefully.
      </>
    ),
  },
  {
    q: 'Can I have my data removed?',
    a: (
      <>
        Of course. Use the{' '}
        <Link href="/remove-me" className="text-primary font-bold hover:underline">
          data opt-out page
        </Link>{' '}
        or just email us. Details in the{' '}
        <Link href="/privacy" className="font-semibold text-text underline underline-offset-2">
          Privacy Policy
        </Link>
        .
      </>
    ),
  },
];

export default function Faq() {
  return (
    <MarketingLayout>
      <Seo
        title="FAQ"
        description="The money, the people, and how it all works."
      />

      <PageHero
        eyebrow="FAQ"
        title={<span className="leading-tight tracking-tighter">Common questions.</span>}
        lead="The money, the people, and how it all works."
      />

      <Section
        bg="white"
        width="7xl"
        title={<span className="font-black">Network Operations</span>}
      >
        <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-12 mt-12 md:mt-16 items-start">
          
          <div className="space-y-6">
            {FAQS.map((item, i) => (
              <div key={i} className="bg-white border border-border p-8 rounded-lg shadow-[0_8px_30px_rgba(0,0,0,0.04)] transition-standard hover:shadow-[0_12px_40px_rgba(0,0,0,0.06)] group">
                <h2 className="text-lg font-black text-text mb-4 leading-tight group-hover:text-primary transition-standard">{item.q}</h2>
                <div className="text-base text-text/80 leading-relaxed">{item.a}</div>
              </div>
            ))}
          </div>

          <aside className="space-y-6 lg:sticky lg:top-24">
            <div className="bg-white border border-border p-6 rounded-lg shadow-[0_8px_30px_rgba(0,0,0,0.04)] transition-standard hover:shadow-[0_12px_40px_rgba(0,0,0,0.06)] group">
              <h4 className="font-bold text-[10px] uppercase tracking-widest text-text mb-4">Contact Support</h4>
              <div className="space-y-4 font-mono text-[11px]">
                <div className="flex flex-col border-b border-border/60 pb-4">
                  <span className="text-muted uppercase font-bold tracking-tight mb-1">Email</span>
                  <a href={`mailto:${LEGAL.supportEmail}`} className="font-bold text-primary break-all hover:underline">{LEGAL.supportEmail}</a>
                </div>
                <div className="flex flex-col border-b border-border/60 pb-4">
                  <span className="text-muted uppercase font-bold tracking-tight mb-1">Response Time</span>
                  <span className="font-bold text-text">&lt; 4 business hours</span>
                </div>
                <div className="flex flex-col">
                   <span className="text-muted uppercase font-bold tracking-tight mb-1">Location</span>
                   <span className="font-bold text-text">London & San Francisco</span>
                </div>
              </div>
            </div>
          </aside>

        </div>
      </Section>

      <CtaBand
        title="Ready to join the exchange?"
        lead=""
        primary={{ href: '/register?role=Buyer', label: 'Get an intro' }}
        secondary={{ href: '/register?role=Connector', label: 'Make intros' }}
      />
    </MarketingLayout>
  );
}
