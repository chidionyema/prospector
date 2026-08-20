/**
 * No dashboard HTML for anyone without a session.
 *
 * THE DEFECT THIS REMOVES. Every page in this console was static. Auth was enforced only on
 * `/api/ops/*`, so an unauthenticated visitor got the full dashboard shell -- header, nav,
 * panels -- and was bounced to /login only after the browser had hydrated, fetched a view and
 * read a 401 back (`lib/contract.ts:43`). Founder, 2026-08-19: "i see the page before the login
 * screen apprea". The page was never a data leak; the panels were empty. It was still wrong:
 * the operator saw an interface they were not signed in to, and the sign-in arrived as an
 * interruption rather than as the door.
 *
 * WHAT THIS IS AND IS NOT. This is a gate on the HTML, not the fence on the data. Every read
 * and write still calls `requireAuth` (`lib/auth.ts`) and still answers 401 JSON, and that is
 * deliberate: a UI gate that quietly became the only check would be a fence that a single
 * `matcher` typo switches off. Two independent checks, and the API one is the one that matters.
 *
 * FAIL CLOSED, ALWAYS. No password configured, no cookie, a malformed cookie, or a throw inside
 * the check itself all end at /login. There is no path through here that serves a gated page
 * when the answer is unknown.
 */
import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

import { OPS_COOKIE_NAME, isPublicPath, sessionValidEdge } from '@/lib/sessionEdge';

export const config = {
  // Everything except the four public prefixes. Written as an exclusion rather than a list of
  // gated pages so a page added tomorrow is gated by default -- the direction a mistake should
  // fall. `isPublicPath` repeats the same decision in code, because a matcher is a string that
  // no test can call; that function is what tests/middleware.test.ts actually grades.
  matcher: ['/((?!api/|_next/|login|s/|favicon\\.ico|robots\\.txt).*)'],
};

export async function middleware(req: NextRequest): Promise<NextResponse> {
  const { pathname, search } = req.nextUrl;
  if (isPublicPath(pathname)) return NextResponse.next();

  let signedIn = false;
  try {
    signedIn = await sessionValidEdge(
      req.cookies.get(OPS_COOKIE_NAME)?.value,
      process.env.CONTROL_CENTER_PASSWORD || '',
    );
  } catch {
    // A throw here means we could not establish the answer. That is not permission.
    signedIn = false;
  }
  if (signedIn) return NextResponse.next();

  const url = req.nextUrl.clone();
  url.pathname = '/login';
  url.search = '';
  // So a deep link survives the door: /money bookmarked, signed out, still lands on /money.
  // Sanitised on the way back out by `safeNextPath`, never trusted as a URL.
  url.searchParams.set('next', `${pathname}${search}`);
  return NextResponse.redirect(url);
}
