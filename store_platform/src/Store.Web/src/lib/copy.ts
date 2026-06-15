/**
 * Centralized microcopy for TIE (E17-008).
 * Ensures consistency across roles and screens. Follows the auth-hold framing (no "escrow").
 */
import { BRAND } from "./config";

export const COPY = {
  brand: {
    name: BRAND.name,
    tagline: "Warm intros, verified people, money that only moves when it's real",
  },
  money: {
    held: "Held by your bank",
    released: "Released only on verified introduction",
    released_on_meeting: "Released only on verified meeting",
    fee: "Platform fee (charged now, non-refundable)",
    connection_fee: "Connection fee (charged on accept, non-refundable)",
    meeting_reward: "Meeting reward (held by your bank)",
    hold_description:
      "A hold with your bank, like a hotel deposit. Not a charge.",
    auth_hold_framing:
      "A hold with your bank, like a hotel deposit. Not a charge.",
    no_meeting_no_charge: "Your request closed with no intro. Your bank has released the hold. Nothing was charged.",
  },
  blindness: {
    privacy_reassurance:
      "The introduced person's identity is kept private until you both agree to connect.",
    connector_privacy:
      "Connectors see only your brief, never your identity or shortlist, until you approve an offer.",
  },
} as const;
