/**
 * Wire types — snake_case, mirroring docs/ux/API-CONTRACT.md exactly.
 * Components import these; they do NOT redeclare backend shapes.
 *
 * IDENTITY-BLINDNESS (P0): `actual_name` / `linkedin_url` live ONLY on `ExternalTarget`
 * (the connector's own private roster). No buyer-facing type below carries them — a leak
 * therefore cannot even compile in a buyer view. Do not add them anywhere else.
 */

// ── Auth ────────────────────────────────────────────────────────────────────
export interface AuthResponse {
  /** ⚠️ the access token — field is `token`, NOT `access_token`. */
  token: string;
  refresh_token: string | null;
  user_id: string;
  username: string | null;
  email: string | null;
  expires: string; // ISO 8601
  message: string | null;
  /** E16: a fresh social signup with no role yet — the token only authorises select-role. */
  role_pending?: boolean;
}

// ── E16 social login ──────────────────────────────────────────────────────────
export interface ExternalProvider {
  name: string; // scheme name used in the challenge URL, e.g. "Google"
  display_name: string;
}

export interface ProvidersResponse {
  providers: ExternalProvider[];
}

/** A user's linked sign-in methods (Settings → Connected accounts). */
export interface UserLoginsDto {
  providers: string[];
  has_password: boolean;
}

/** The full-page start URL a link request returns (D9 link-ticket flow). */
export interface StartUrlResponse {
  start_url: string;
}

export interface RegisterRequest {
  username: string;
  email: string;
  password: string;
  /** Optional: the Buyer/Connector pick moved to /auth/choose-role on first login (role-less signup). */
  role?: string;
  tos_version?: string;
}

export interface LoginRequest {
  username: string;
  password: string;
}

export interface MessageResponse {
  message: string;
}

export interface VerifyEmailRequest {
  user_id: string;
  token: string;
}

export interface ResendVerificationRequest {
  email: string;
}

export interface Session {
  family_id: string;
  user_agent: string | null;
  ip_address: string | null;
  created_at: string;
  expires: string;
  is_current: boolean;
}

// ── Account / profile ────────────────────────────────────────────────────────
export interface UserProfile {
  first_name: string;
  last_name: string;
  display_name: string;
  phone: string;
  bio: string;
  website: string;
  avatar_url: string;
  country: string;
}

export interface UserAndProfile {
  id: string;
  email: string;
  username: string;
  verification_tier: string | null;
  stripe_account_id: string | null;
  payout_ready: boolean;
  profile: UserProfile;
}

// Full-replace profile edit (PUT /v1/me). All fields optional on the wire; omitted
// fields are cleared server-side (PUT semantics), country defaults to GB when blank.
export interface UpdateProfileRequest {
  first_name?: string;
  last_name?: string;
  phone?: string;
  bio?: string;
  website?: string;
  avatar_url?: string;
  country?: string;
}

// ── Seeker FOMO (WR-045) — Shadow Queue ──────────────────────────────────────
export interface MarketHeat {
  peers_watching: number;
  active_briefs: number;
  average_reward: number;
  currency: string;
}

export interface WatchPersonaRequest {
  persona: string;
}

export interface StripeAccountResponse {
  stripe_account_id: string;
}

export interface OnboardingLinkResponse {
  url: string;
}

/** E02-014/E02-015: live KYC state re-read from Stripe. `details_submitted` distinguishes
 * "Stripe is still reviewing" from "the form was never finished"; `requirements_due` lists the
 * provider's outstanding inputs for the connector's OWN account (empty + details_submitted =
 * in review, no action needed); `disabled_reason` is set when the provider disabled the account. */
export interface OnboardingRefreshResponse {
  payout_ready: boolean;
  details_submitted: boolean;
  requirements_due: string[];
  disabled_reason: string | null;
}

// ── Roster / targets (connector-private — HOLDS IDENTITY) ────────────────────
export interface ExternalTarget {
  id: string;
  connector_id: string;
  actual_name: string;
  company: string;
  job_title: string;
  linkedin_url?: string | null;
  created_at: string;
}

export interface CreateExternalTargetRequest {
  actual_name: string;
  company: string;
  job_title: string;
  linkedin_url?: string;
  // L-01: connector affirms a genuine relationship + lawful basis. Required true at create.
  acknowledge_genuine_relationship: boolean;
}

export interface PatchExternalTargetRequest {
  actual_name?: string;
  company?: string;
  job_title?: string;
  linkedin_url?: string;
}

// ── Bounty (buyer) ───────────────────────────────────────────────────────────
export type IntroType = 'WarmEmailIntro' | 'LiveMeeting' | 'InPerson';

export type BountyState =
  | 'Draft'
  | 'EscrowLocked'
  | 'PendingMatch'
  | 'BridgeActive'
  | 'AutoSettled'
  | 'Refunded'
  | 'Canceled'
  | 'Voided';

export interface CreateBountyRequest {
  target_persona: string;
  introduction_context: string;
  target_industry?: string;
  target_seniority?: string;
  meeting_objective?: string;
  presentation_currency: string;
  local_amount_units: number;
  escrow_amount_cents: number;
  acknowledge_deliverable_scope: boolean;
  // L-02 AUP attestation: buyer affirms the intro is not a prohibited category
  // (public official in office / restricted regulated-profession referral / bribery).
  acknowledge_prohibited_category: boolean;
  expires_at?: string;
  // E25 (3a guided requests, WR-031): structured capture of the guided composer. Omitted for a
  // free-text / escape-hatch post. Demand-side intent only — never a target name.
  brief_structured?: BriefStructured;
  // WR-044: the buyer-chosen introduction format (warm email / live video meeting / in-person). A
  // disclosed LABEL on the same verified-intro settlement; defaults to WarmEmailIntro server-side.
  intro_type?: IntroType;
}

export type PatchBountyRequest = Partial<CreateBountyRequest>;

// ── E25 Discovery Layer — 3a guided requests (WR-031) ────────────────────────
/** The structured selections from the guided composer, stored alongside the free-text brief. */
export interface BriefStructured {
  goal: string;
  sector?: string;
  role?: string;
  seniority?: string;
  template_id?: string;
}

/** A worked, fundable example ask — fields mirror the compose form so the client can pre-fill it. */
export interface RequestExample {
  id: string;
  label: string;
  target_persona: string;
  introduction_context: string;
  target_industry?: string | null;
  target_seniority?: string | null;
  meeting_objective?: string | null;
}

/** A guided-request goal and its worked examples. */
export interface RequestGoal {
  id: string;
  label: string;
  blurb: string;
  examples: RequestExample[];
}

/** GET /v1/discovery/request-templates — the versioned guided-request taxonomy. */
export interface RequestTemplateCatalog {
  version: string;
  goals: RequestGoal[];
}

// ── E25 admin: editable taxonomy + per-template funnel (WR-031) ───────────────
/** GET /v1/admin/discovery/taxonomy — the live taxonomy plus where it came from. */
export interface AdminTaxonomyResponse {
  version: string;
  goals: RequestGoal[];
  /** "db" when an admin override exists, "seed" when serving the in-code default. */
  source: 'db' | 'seed';
  updated_at?: string | null;
  updated_by?: string | null;
}

/** One row of the per-template funnel: started → posted → funded → replied. */
export interface TemplateFunnelRow {
  goal: string;
  template_id?: string | null;
  label?: string | null;
  started: number;
  posted: number;
  funded: number;
  replied: number;
}

/** GET /v1/admin/discovery/template-funnel — which guided templates convert. */
export interface TemplateFunnelResponse {
  version: string;
  generated_at: string;
  rows: TemplateFunnelRow[];
}

export interface CreateBountyResponse {
  bounty_id: string;
  status: string;
}

export interface FundingQuote {
  bounty_id: string;
  platform_fee_cents: number;
  held_amount_cents: number;
  success_cut_percent: number;
  connection_fee_ratio?: number; // E08-MTG
  currency: string;
  disclosure_version: string;
  quote_version: string;
}

export interface FundResult {
  payment_intent_id: string;
  client_secret: string;
  fee_payment_intent_id: string;
  fee_client_secret: string;
}

/**
 * How the target's acceptance was verified (E06-009). Mirrors the backend `VerificationMethod` enum;
 * the global JsonStringEnumConverter serialises verbatim (PascalCase) — keep these strings
 * byte-identical to the backend members.
 */
export type VerificationMethod = 'None' | 'LinkedInOidcMatch' | 'PlatformChannelInvite';

/**
 * The profile the buyer approved, snapshotted onto the bridge at approval (E06-001). The buyer's
 * comparison anchor — what they signed up to — shown beside the verified identity at BridgeActive.
 */
export interface ApprovedProfile {
  name: string | null;
  url: string | null;
}

/**
 * The accepting target's OWN OIDC-verified identity (E06-009). Surfaced to the owning buyer at
 * BridgeActive so a real face + verified name beside the approved profile exposes a same-name fake.
 * `email_verified` is the fraud signal (false ⇒ flag it loudly); the raw email is deliberately NOT
 * carried (WR-010 data-minimisation). `picture` may be null (render a no-photo state, not a blank).
 * `email_domain` is the corroborating `@company` part ONLY — never the local-part / a contactable
 * address — so the buyer can place where the person works; null when unknown.
 */
export interface VerifiedIdentity {
  name: string | null;
  email_verified: boolean;
  picture: string | null;
  verification_method: VerificationMethod;
  email_domain: string | null;
}

/**
 * The owning buyer's single-bounty read (GET /v1/bounties/{id}, G-B). The G5 fields
 * (`bridge_active_at` / `auto_release_at` / `connector_is_proven`) are null until the introduction
 * is live (`state === 'BridgeActive'`); once live they drive the auto-release countdown and the
 * standing-aware copy. `approved_profile` / `verified_identity` are likewise null until BridgeActive,
 * then let the buyer eyeball-confirm the verified person against what they approved (E06-009 / WR-010).
 * The CONNECTOR's identity is never carried here.
 */
import type { MeetingSnapshot, MeetingEconomics } from '../meeting';

export interface BountyDetail {
  id: string;
  target_persona: string;
  introduction_context: string;
  target_industry: string | null;
  target_seniority: string | null;
  meeting_objective: string | null;
  presentation_currency: string;
  escrow_amount_cents: number;
  state: BountyState;
  created_at: string;
  expires_at: string | null;
  /** When the target accepted (= the G5 clock start). Null before BridgeActive. */
  bridge_active_at: string | null;
  /** bridge_active_at + the shared auto-settle window. Null before BridgeActive. */
  auto_release_at: string | null;
  /** Proven connector → silence auto-PAYS; unproven → silence VOIDS. Null before BridgeActive. */
  connector_is_proven: boolean | null;
  bridge_id: string | null;
  /** The approved profile snapshot (E06-009). Null before BridgeActive. */
  approved_profile: ApprovedProfile | null;
  /** The target's OIDC-verified identity (E06-009). Null before BridgeActive. */
  verified_identity: VerifiedIdentity | null;
  meeting: MeetingSnapshot | null;
  meeting_economics: MeetingEconomics | null;
  intro_type: IntroType | null;
}

// ── LiveMeeting embedded room (WR-044) ───────────────────────────────────────
// The token-gated session a /meet/{token} page joins. `room_url` is the (private, inert without a
// token) Daily room; `meeting_token` is the per-participant short-lived join credential; together
// they mount the embedded iframe. `display_name` is the role label shown in the call, never a name.
export interface MeetingSession {
  room_url: string;
  meeting_token: string;
  display_name: string;
}

// POST /v1/bounties/{id}/meeting/schedule — `room_url` here is the TIE web join link
// (https://{webhost}/meet/{token}), NOT a Daily URL; null until the slot mints a room.
export interface ScheduleMeetingResponse {
  status: string;
  scheduled_at: string;
  room_url: string | null;
}

// ── Marketplace board (connector view — NO identity, NO local_amount_units) ───
export interface BoardBounty {
  id: string;
  target_persona: string;
  introduction_context: string;
  target_industry: string;
  target_seniority: string;
  meeting_objective: string;
  presentation_currency: string;
  escrow_amount_cents: number;
  connection_fee_ratio?: number; // E08-MTG
  current_state: BountyState;
  created_at: string;
  success_cut_percent: number;
}

export interface MarketplaceSearchParams {
  industry?: string;
  seniority?: string;
  min_amount_cents?: number;
  q?: string;
}

// ── My bounties (buyer's OWN funded intros — E28-001 dashboard) ──────────────
// GET /v1/bounties/mine. Owner-scoped (D-73), so it safely carries the buyer's own confidential deal
// intent (persona, context, budget). `escrow_amount_cents` is the actual charged hold, never the raw
// localized units (FIND-22). This is the buyer side of the authed dashboard.
export interface MyBounty {
  id: string;
  buyer_identity_id: string;
  target_persona: string;
  introduction_context: string;
  target_industry: string;
  target_seniority: string;
  meeting_objective: string;
  presentation_currency: string;
  escrow_amount_cents: number;
  current_state: BountyState;
  created_at: string;
  expires_at: string | null;
}

// ── Proposals ────────────────────────────────────────────────────────────────
export type ProposalStatus = 'Submitted' | 'Accepted' | 'Rejected' | 'Withdrawn';

export interface SubmitProposalRequest {
  blind_target_description: string;
  relationship_context: string;
  external_target_id: string;
}

/** What the connector gets back on submit — carries the E04-008 KYC nudge flag. */
export interface ProposalCreated {
  id: string;
  bounty_id: string;
  connector_identity_id: string;
  external_target_id: string;
  blind_target_description: string;
  relationship_context: string;
  status: ProposalStatus;
  submitted_at: string;
  payout_setup_required: boolean;
}

/**
 * G-A (WR-004) — the identity-free trust snapshot a buyer judges a blind pitch by. `completed_intros`
 * (the raw settled-success count) is ALWAYS shown; the two percentages are WITHHELD (null) until the
 * connector has ≥ K settled receipts, so a tiny sample can't manufacture a 100%/0%. Carries no
 * connector id, no join key — the snapshot is computed server-side and the identity never crosses.
 */
export interface ReputationSnapshot {
  completed_intros: number;
  success_rate_percent: number | null;
  dispute_rate_percent: number | null;
  /** ≥ ProvenThreshold settled successes — gates the G5 "silence pays" path. */
  is_proven: boolean;
  identity_verified: boolean;
  payout_ready: boolean;
}

/** Buyer view — identity is STRUCTURALLY EXCLUDED (no actual_name / linkedin_url). */
export interface BlindProposal {
  id: string;
  blind_target_description: string;
  relationship_context: string;
  status: ProposalStatus;
  submitted_at: string;
  /** G-A: the anonymous connector's gated trust signals (see ReputationSnapshot). */
  reputation: ReputationSnapshot;
}

/**
 * G-C — a connector's own proposal as seen from GET /v1/proposals/mine, so the board can hydrate
 * "already proposed" / Withdraw state across reloads. `external_target_id` is the connector's OWN
 * private roster handle (safe to return to its owner); `bounty_state` / `bounty_persona` come from a
 * left-join and are null if the bounty was since removed. No target identity is ever carried.
 */
export interface MyProposal {
  proposal_id: string;
  bounty_id: string;
  status: ProposalStatus;
  submitted_at: string;
  external_target_id: string | null;
  blind_target_description: string;
  relationship_context: string;
  bounty_state: BountyState | null;
  bounty_persona: string | null;
}

export interface AcceptProposalResponse {
  status: string;
  // No magic_link_token: the inert pitch link is delivered to the CONNECTOR to relay (E11-006 / WR-001),
  // never to the identity-blind buyer who calls accept. The buyer client only reads `status`.
}

// ── Guest target pitch (magic-link, UNAUTHENTICATED) ──────────────────────────
// The introduced target accepts/declines via the bridge's magic-link token. Accepting
// activates the bridge (→ BridgeActive) and starts settlement. A decline needs no name/email.
export interface TargetDecisionRequest {
  target_name: string;
  target_email: string;
  accept: boolean;
}

export interface TargetDecisionResponse {
  /** "ACCEPTED" | "DECLINED". */
  status: string;
}

// ── Disputes ─────────────────────────────────────────────────────────────────
export interface RaiseDisputeRequest {
  reason: string;
  evidence_url?: string;
}

// ── Messaging ────────────────────────────────────────────────────────────────
export interface ChatMessageResponse {
  id: string;
  bridge_id: string;
  sender_user_id: string | null;
  sender_role: string;
  content: string;
  created_at: string;
  hash: string;
}

// ── Bloomberg Pivot: Latent Network Valuation ────────────────────────────────
export interface ConnectorValuation {
  total_value_cents: number;
  delta_24h_cents: number;
  matching_proposals_count: number;
}

export interface ConnectorExpertise {
  id: string;
  persona: string;
  industry: string | null;
  seniority: string | null;
  created_at: string;
}

export interface ReputationLedger {
  acceptance_rate: number;
  settlement_rate: number;
  total_proposals: number;
  total_accepted: number;
  total_settled: number;
}

export interface AddExpertiseRequest {
  persona: string;
  industry?: string;
  seniority?: string;
}

// ── Errors ───────────────────────────────────────────────────────────────────
/** Uniform error envelope: { error, code? }. `code` drives recovery UX. */
export interface ApiErrorBody {
  error: string;
  code?: string;
  required_version?: string;
}
