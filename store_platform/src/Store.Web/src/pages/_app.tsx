import "@/styles/globals.css";
import { useEffect } from "react";
import type { AppProps } from "next/app";
import { useRouter } from "next/router";
import { Geist, Geist_Mono } from "next/font/google";
import { ToastProvider } from "@/components/ui";
import { Seo } from "@/components/Seo";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { AuthProvider } from "@/lib/auth/AuthContext";
import { CurrencyProvider } from "@/lib/currency";
import { type Currency } from "@/lib/fx";
import { track } from "@/lib/analytics";

// TWO families, and they are a matched pair by design (brand v3, 2026-08-06).
//
// `variable` only publishes the family name as a CSS custom property on whatever element carries
// the className; globals.css is where it is read. Without that read, next/font still downloads
// the file and nothing renders it -- that has bitten this file twice.
//
// Geist replaces BOTH Hanken Grotesk and Newsreader. The serif is gone entirely: a high-contrast
// Didone over a grotesque over a mono was three type voices in one hero, and on a store selling
// sober sourced evidence the serif was reading as brochure, not product.
//
// Exactly three weights, and no 700. `font-bold`/`font-extrabold`/`font-black` are banned by the
// weight policy (600 is the heaviest anything gets), so loading 700 would only serve a class that
// should not exist. The risk is worth naming: if a stray `font-bold` survives, the browser
// SYNTHESISES it by smearing the 600, which is heavier and wider than a real cut -- that is the
// visible symptom, and `weightAndCasePolicy.test.ts` is what stops it reaching the build.
const geist = Geist({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  display: "swap",
  variable: "--font-sans-pref",
});

// The DATA voice, and only that: prices, pack IDs, source counts, gate tags, filenames, scores.
// Confining mono to checkable facts is what teaches the eye that monospace means "you can verify
// this" -- which is the entire proposition of the shop.
const geistMono = Geist_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  display: "swap",
  variable: "--font-mono-pref",
});

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
    // `fonts-wired` is not cosmetic: it is the globals.css rule that maps the two `variable`
    // classes above onto --font-sans/--font-mono and applies the result. Drop it and the fonts
    // still download and still never render. It replaces the `font-sans` utility that used to be
    // here, which resolved to the system fallback rather than to the loaded family.
    <div className={`${geist.variable} ${geistMono.variable} fonts-wired`}>
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
