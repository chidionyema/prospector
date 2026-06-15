import React, { useEffect, useState } from 'react';
import type { GetServerSideProps } from 'next';
import Layout from '@/components/Layout';
import { Seo } from '@/components/Seo';
import { Card } from '@/components/ui';
import {
  MoneyTermsBreakdown,
  MeetingStatusTimeline,
  MeetingScheduleCard,
  DisputeBanner,
  MoneyBand,
  MeetingSchedulePanel,
  MeetingResolutionPanel,
} from '@/components/domain';
import { MEETING_MOCKS } from '@/lib/meeting';

/**
 * E08-MTG component preview page (DS12).
 * Used for visual regression snapshots of the Meeting-as-Deliverable feature.
 *
 * Dev-only: this renders mock data and must not be reachable in production. The guard below
 * returns a real 404 there, so the route is invisible to crawlers and users while still serving
 * the Playwright snapshot run in non-production builds.
 */
export const getServerSideProps: GetServerSideProps = async () => {
  if (process.env.NODE_ENV === 'production') {
    return { notFound: true };
  }
  return { props: {} };
};

export default function MtgPreviewPage() {
  const econ = MEETING_MOCKS.economics.ratio_30;
  const [future, setFuture] = useState<string>('');

  useEffect(() => {
    setTimeout(() => setFuture(new Date(Date.now() + 100000000).toISOString()), 0);
  }, []);

  if (!future) return null;

  return (
    <Layout>
      {/* Belt-and-suspenders: the getServerSideProps guard already 404s this route in production,
          but keep an explicit noindex so the dev-only surface can never be indexed. */}
      <Seo title="Component preview" noindex />
      <div className="mx-auto max-w-4xl space-y-12 px-6 py-12">
        <h1 className="text-display font-semibold">Meeting Feature Components</h1>

        {/* DS01: MoneyTermsBreakdown */}
        <section className="space-y-4">
          <h2 className="text-h2 font-semibold border-b border-border pb-2">DS01: MoneyTermsBreakdown</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
            <div className="space-y-2">
              <p className="text-caption font-semibold uppercase text-muted">Ratio 0.30 (Default)</p>
              <Card>
                <MoneyTermsBreakdown
                  totalAmountCents={econ.total_amount_cents}
                  platformFeeCents={500}
                  currency={econ.currency}
                  connectionFeeRatio={0.3}
                  successCutPercent={10}
                />
              </Card>
            </div>
            <div className="space-y-2">
              <p className="text-caption font-semibold uppercase text-muted">Ratio 0.00 (Fenced)</p>
              <Card>
                <MoneyTermsBreakdown
                  totalAmountCents={econ.total_amount_cents}
                  platformFeeCents={500}
                  currency={econ.currency}
                  connectionFeeRatio={0}
                  successCutPercent={10}
                />
              </Card>
            </div>
          </div>
        </section>

        {/* DS02: MeetingStatusTimeline */}
        <section className="space-y-4">
          <h2 className="text-h2 font-semibold border-b border-border pb-2">DS02: MeetingStatusTimeline</h2>
          <div className="space-y-6">
            <div className="space-y-2">
              <p className="text-caption font-semibold uppercase text-muted">State: BridgeActive, No Schedule</p>
              <Card><MeetingStatusTimeline state="BridgeActive" /></Card>
            </div>
            <div className="space-y-2">
              <p className="text-caption font-semibold uppercase text-muted">State: BridgeActive, Scheduled</p>
              <Card><MeetingStatusTimeline state="BridgeActive" hasScheduledMeeting /></Card>
            </div>
            <div className="space-y-2">
              <p className="text-caption font-semibold uppercase text-muted">State: BridgeActive, Completed</p>
              <Card><MeetingStatusTimeline state="BridgeActive" hasScheduledMeeting hasCompletedMeeting /></Card>
            </div>
            <div className="space-y-2">
              <p className="text-caption font-semibold uppercase text-muted">State: Disputed</p>
              <Card><MeetingStatusTimeline state="Disputed" /></Card>
            </div>
          </div>
        </section>

        {/* DS04: MeetingScheduleCard */}
        <section className="space-y-4">
          <h2 className="text-h2 font-semibold border-b border-border pb-2">DS04: MeetingScheduleCard</h2>
          <MeetingScheduleCard scheduledAt="2026-06-10T14:00:00Z" />
        </section>

        {/* DS05: DisputeBanner */}
        <section className="space-y-4">
          <h2 className="text-h2 font-semibold border-b border-border pb-2">DS05: DisputeBanner</h2>
          <DisputeBanner autoReleaseAt={future} />
        </section>

        {/* DS08-11: MoneyBand Extended */}
        <section className="space-y-4">
          <h2 className="text-h2 font-semibold border-b border-border pb-2">DS08: MoneyBand (Extended)</h2>
          <div className="flex gap-12">
             <div className="space-y-2">
               <p className="text-caption font-semibold uppercase text-muted">Standard</p>
               <MoneyBand amount={50000} currency="GBP" state="BridgeActive" />
             </div>
             <div className="space-y-2">
               <p className="text-caption font-semibold uppercase text-muted">With Breakdown</p>
               <MoneyBand 
                 amount={50000} 
                 currency="GBP" 
                 state="BridgeActive" 
                 breakdown={{ connectionFeeCents: 15000, meetingRewardCents: 35000 }} 
               />
             </div>
          </div>
        </section>

        {/* UX: Schedule & Resolution Panels */}
        <section className="space-y-4">
          <h2 className="text-h2 font-semibold border-b border-border pb-2">UX: Coordination Panels</h2>
          <div className="space-y-8">
            <div className="space-y-2">
              <p className="text-caption font-semibold uppercase text-muted">UX08: Schedule (Buyer, Propose)</p>
              <MeetingSchedulePanel 
                role="Buyer"
                scheduledAt={null}
                authHoldExpiresAt={future}
                onPropose={() => {}}
                onAccept={() => {}}
              />
            </div>
            <div className="space-y-2">
              <p className="text-caption font-semibold uppercase text-muted">UX08: Schedule (Target, Awaiting)</p>
              <MeetingSchedulePanel 
                role="Target"
                scheduledAt="2026-06-10T14:00:00Z"
                authHoldExpiresAt={future}
                onPropose={() => {}}
                onAccept={() => {}}
              />
            </div>
            <div className="space-y-2">
              <p className="text-caption font-semibold uppercase text-muted">UX10b: Resolution (Buyer, Confirm)</p>
              <MeetingResolutionPanel 
                role="Buyer"
                status="pending"
                amountCents={35000}
                currency="GBP"
                autoReleaseAt={future}
                onConfirm={async () => {}}
                onDispute={async () => {}}
              />
            </div>
            <div className="space-y-2">
              <p className="text-caption font-semibold uppercase text-muted">UX10b: Resolution (Target, Awaiting)</p>
              <MeetingResolutionPanel 
                role="Target"
                status="pending"
                amountCents={35000}
                currency="GBP"
                autoReleaseAt={future}
                onConfirm={async () => {}}
                onDispute={async () => {}}
              />
            </div>
          </div>
        </section>
      </div>
    </Layout>
  );
}
