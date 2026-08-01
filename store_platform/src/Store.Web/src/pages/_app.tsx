import "@/styles/globals.css";
import { useEffect } from "react";
import type { AppProps } from "next/app";
import { useRouter } from "next/router";
import { Hanken_Grotesk, Newsreader, Geist_Mono } from "next/font/google";
import { ToastProvider } from "@/components/ui";
import { Seo } from "@/components/Seo";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { AuthProvider } from "@/lib/auth/AuthContext";
import { track } from "@/lib/analytics";

// These three are the site's whole typeface. `variable` only publishes the family name as a CSS
// custom property on whatever element carries the className, globals.css is where it is read;
// without that read, next/font still downloads the file and nothing renders it.
//
// Weight 700 is loaded because `.font-bold` is used on the hero h1 and the CTAs. Without it the
// browser synthesises bold by smearing the 600, which is heavier and wider than the real cut.
const hanken = Hanken_Grotesk({
  subsets: ["latin"],
  weight: ["400", "600", "700"],
  display: "swap",
  variable: "--font-sans-pref",
});

// The editorial heading face, and the one font on this page with a history worth stating.
//
// Playfair Display used to sit here as --font-serif-pref, downloaded on every page load and read
// by no rule at all, so the previous change removed it rather than wiring it, correct, because
// --font-serif was mapped onto the sans stack and a serif had nowhere to render. This puts a
// serif back deliberately: globals.css now points --font-serif at --font-serif-pref, so the
// download buys something.
//
// Newsreader rather than Playfair. Headings here run from --text-hero (5.5rem) down to
// --text-h3 (1.25rem/20px), and most of them are at the small end, card titles, section heads.
// Playfair is a high-contrast Didone whose hairlines are drawn for display sizes; Newsreader is
// a text-first serif, so one family covers the whole range instead of looking authoritative in
// the hero and thin on a card.
//
// 600 is what `h1, h2, h3` ask for (globals.css); 400 is for running serif text.
const newsreader = Newsreader({
  subsets: ["latin"],
  weight: ["400", "600"],
  display: "swap",
  variable: "--font-serif-pref",
});

const geistMono = Geist_Mono({
  subsets: ["latin"],
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
    // `fonts-wired` is not cosmetic: it is the globals.css rule that maps the three `variable`
    // classes above onto --font-sans/-serif/-mono and applies the result. Drop it and the fonts
    // still download and still never render. It replaces the `font-sans` utility that used to be
    // here, which resolved to the system fallback rather than to the loaded family.
    <div className={`${hanken.variable} ${newsreader.variable} ${geistMono.variable} fonts-wired`}>
      <ErrorBoundary>
        <ToastProvider>
          {/* Mounted app-wide so the session is asked for once, not per page. It resolves to
              "anonymous" with a single 401 for a visitor who has never signed in, which is the
              overwhelmingly common case on a storefront. */}
          <AuthProvider>
            <Seo />
            <Component {...pageProps} />
          </AuthProvider>
        </ToastProvider>
      </ErrorBoundary>
    </div>
  );
}
