import "@/styles/globals.css";
import { useEffect } from "react";
import type { AppProps } from "next/app";
import { useRouter } from "next/router";
import { ToastProvider } from "@/components/ui";
import { Seo } from "@/components/Seo";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { AuthProvider } from "@/lib/auth/AuthContext";
import { CurrencyProvider } from "@/lib/currency";
import { type Currency } from "@/lib/fx";
import { track } from "@/lib/analytics";

// ── §3.2 (2026-08-08): THE FONTS ARE NO LONGER LOADED FROM HERE ───────────────────────────────
//
// `next/font/google` loaded Geist + Geist Mono and published their family names as
// --font-sans-pref / --font-mono-pref onto the wrapper <div> below. Spec §3.2 names Switzer and
// Commit Mono, and both are now self-hosted @font-face declarations in styles/tokens.css, which
// also declares those same two custom properties at :root.
//
// This import had to GO, not merely stop being used. A next/font `variable` class sets the
// property on an ELEMENT, and an element declaration beats a :root one on every descendant -- so
// leaving the wrapper wearing `geist.variable` would have silently kept rendering Geist while
// tokens.css sat there declaring Switzer, with both files looking correct in isolation. The
// symptom would have been "the new font does not apply" and the cause would have been two files
// away. Deleting the import is what makes :root the only declaration site.
//
// The weight policy the deleted comment described still holds, and matters MORE now: Switzer is
// a VARIABLE face with a declared 100-900 axis, so a stray `font-bold` no longer gets synthesised
// by smearing a 600 -- it renders a real 700 and simply violates the policy silently.
// `weightAndCasePolicy.test.ts` is now the only thing catching that.

export default function App({ Component, pageProps }: AppProps) {
  const router = useRouter();

  // One page_view per client-side view: the initial load, then every completed route change.
  // routeChangeComplete fires after the URL updates, so track() reads the new pathname.
  useEffect(() => {
    track("page_view");
    const onRouteChange = () => track("page_view");
    router.events.on("routeChangeComplete", onRouteChange);
    return () => router.events.off("routeChangeComplete", onRouteChange);
  }, [router.events]);

  return (
    // `fonts-wired` is not cosmetic: it is the globals.css rule that resolves --font-sans-pref /
    // --font-mono-pref (now declared at :root by tokens.css) into --font-sans/--font-mono and
    // APPLIES the result as a font-family. Drop it and the faces still download and still never
    // render -- body copy has no font-family rule of its own and inherits from this element.
    <div className="fonts-wired">
      <ErrorBoundary>
        <ToastProvider>
          {/* Mounted app-wide so the session is asked for once, not per page. It resolves to
              "anonymous" with a single 401 for a visitor who has never signed in, which is the
              overwhelmingly common case on a storefront. */}
          <AuthProvider>
            {/* The visitor's display currency, resolved once per request in each page's
                getServerSideProps and made ambient here so no intermediary component has to
                forward it. Pages that resolve no currency fall through to GBP, the currency
                the catalogue is priced and charged in. See lib/currency.tsx. */}
            <CurrencyProvider currency={(pageProps as { currency?: Currency }).currency}>
              <Seo />
              <Component {...pageProps} />
            </CurrencyProvider>
          </AuthProvider>
        </ToastProvider>
      </ErrorBoundary>
    </div>
  );
}
