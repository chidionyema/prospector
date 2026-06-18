import React from 'react';

/**
 * Shared "not financial / investment advice" disclaimer.
 * Rendered on /terms and /refund at minimum; import wherever Pack content is described.
 *
 * Draft legal copy — review with qualified counsel before go-live.
 */
export default function Disclaimer() {
  return (
    <aside className="rounded-lg border border-border bg-bg/50 px-6 py-5 text-sm leading-relaxed text-muted shadow-[0_1px_3px_rgba(0,0,0,0.05)]">
      <strong className="text-text font-bold">Not financial, investment, or professional advice.</strong>{' '}
      Prospector Packs are research and information products produced for general informational
      purposes only. Nothing in any Pack constitutes, or should be construed as, financial
      advice, investment advice, legal advice, tax advice, or any other form of regulated or
      professional advice. AI-generated content may contain errors, omissions, or outdated
      information. You are solely responsible for conducting your own independent due diligence
      and for any decision you make in reliance on Pack content. Past opportunity signals are
      not indicative of future results. Always consult a qualified professional before making
      any financial, business, or investment decision.
    </aside>
  );
}
