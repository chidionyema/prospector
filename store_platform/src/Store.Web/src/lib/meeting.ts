/**
 * Meeting-as-deliverable types (E08-MTG / WR-044).
 */

// WR-016 re-architected Phase 2 from a third-party video API to a first-party authenticated
// presence room, so 'ApiJoin' is retired in favour of 'FirstPartyRoom'. Phase 1 only ever emits
// 'MutualConfirmation'; the backend mirrors this union (see Tie.Domain.Enums.MeetingSource).
export type MeetingSource = 'MutualConfirmation' | 'FirstPartyRoom' | 'AdminOverride';

export interface MeetingSnapshot {
  scheduled_at: string | null;
  completed_at: string | null;
  confirmed_at: string | null;
  confirmed_by: string | null; // UserId
  source: MeetingSource | null;
  // The target's independent attestation (the corroboration tap). Strengthens the buyer's
  // confirmation and is decisive in a "no meeting" dispute; per WR-011 it never triggers settlement.
  corroborated_at: string | null;
  // WR-044: the TIE web join link (https://{webhost}/meet/{token}) once a LiveMeeting slot is
  // scheduled. Null for non-LiveMeeting intros or before a slot is set. Never a Daily URL.
  room_url?: string | null;
}

export interface MeetingEconomics {
  total_amount_cents: number;
  connection_fee_ratio: number; // e.g., 0.30
  connection_fee_cents: number;
  meeting_bounty_cents: number;
  currency: string;
}

/**
 * Mock fixtures for Storybook-style component testing and visual snapshots.
 */
export const MEETING_MOCKS = {
  economics: {
    ratio_30: {
      total_amount_cents: 50000, // £500
      connection_fee_ratio: 0.3,
      connection_fee_cents: 15000,
      meeting_bounty_cents: 35000,
      currency: 'GBP',
    } as MeetingEconomics,
    ratio_0: {
      total_amount_cents: 50000,
      connection_fee_ratio: 0,
      connection_fee_cents: 0,
      meeting_bounty_cents: 50000,
      currency: 'GBP',
    } as MeetingEconomics,
  },
  meeting: {
    not_scheduled: {
      scheduled_at: null,
      completed_at: null,
      confirmed_at: null,
      confirmed_by: null,
      source: null,
      corroborated_at: null,
    } as MeetingSnapshot,
    scheduled: {
      scheduled_at: '2026-06-10T14:00:00Z',
      completed_at: null,
      confirmed_at: null,
      confirmed_by: null,
      source: 'MutualConfirmation',
      corroborated_at: null,
    } as MeetingSnapshot,
    completed: {
      scheduled_at: '2026-06-10T14:00:00Z',
      completed_at: '2026-06-10T14:20:00Z',
      confirmed_at: '2026-06-10T14:30:00Z',
      confirmed_by: 'buyer-id',
      source: 'MutualConfirmation',
      // Target also tapped "yes, we met" — strengthens the buyer's confirmation.
      corroborated_at: '2026-06-10T14:25:00Z',
    } as MeetingSnapshot,
  },
};
