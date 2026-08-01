/**
 * Search-console ownership verification tokens.
 *
 * You cannot measure organic search without a verified property, and you cannot ask for a manual
 * recrawl without one either — so this is the prerequisite for every other SEO decision being
 * evidence-based rather than guessed.
 *
 * These are env-driven, not committed, for a mundane reason: a token is issued per property per
 * Google/Bing account. Hardcoding one means whoever owns the console today owns it forever, and a
 * token belonging to the wrong property fails verification silently — the tag renders, the console
 * keeps saying "not verified", and nothing indicates why.
 *
 * Set the ones you use; unset vars emit no tag at all rather than an empty `content=""`, which
 * Google reads as a failed verification attempt.
 *
 *   NEXT_PUBLIC_GOOGLE_SITE_VERIFICATION   Search Console -> HTML tag method -> the `content` value
 *   NEXT_PUBLIC_BING_SITE_VERIFICATION     Bing Webmaster Tools -> the `content` value
 *
 * NEXT_PUBLIC_ is required: these render in the browser-visible document head, and Next only
 * inlines env vars with that prefix into the client bundle.
 *
 * Bing's verification is also what feeds ChatGPT's and Copilot's web index, so it is not a
 * second-tier concern here the way it would be for a purely Google-facing site.
 */

export interface VerificationTag {
  name: string;
  content: string;
}

const CANDIDATES: { name: string; value: string | undefined }[] = [
  { name: 'google-site-verification', value: process.env.NEXT_PUBLIC_GOOGLE_SITE_VERIFICATION },
  { name: 'msvalidate.01', value: process.env.NEXT_PUBLIC_BING_SITE_VERIFICATION },
];

export const SEARCH_ENGINE_VERIFICATIONS: VerificationTag[] = CANDIDATES.filter(
  (candidate): candidate is { name: string; value: string } =>
    typeof candidate.value === 'string' && candidate.value.trim().length > 0,
).map(({ name, value }) => ({ name, content: value.trim() }));
