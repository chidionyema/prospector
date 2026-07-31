import "@/styles/globals.css";
import { useEffect } from "react";
import type { AppProps } from "next/app";
import { useRouter } from "next/router";
import { Hanken_Grotesk, Geist_Mono } from "next/font/google";
import { ToastProvider } from "@/components/ui";
import { Seo } from "@/components/Seo";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { track } from "@/lib/analytics";

// These two are the site's whole typeface. `variable` only publishes the family name as a CSS
// custom property on whatever element carries the className — globals.css is where it is read;
// without that read, next/font still downloads the file and nothing renders it.
//
// Weight 700 is loaded because `.font-bold` is used on the hero h1 and the CTAs. Without it the
// browser synthesises bold by smearing the 600, which is heavier and wider than the real cut.
//
// Playfair Display used to be loaded here as --font-serif-pref and was never read by any rule.
// It is not re-wired but removed: globals.css deliberately maps --font-serif onto the sans stack
// ("Typography Overhaul - Exclusively Sans"), so a serif has nowhere to render. Loading it only
// cost the buyer a font download on every page.
const hanken = Hanken_Grotesk({
  subsets: ["latin"],
  weight: ["400", "600", "700"],
  display: "swap",
  variable: "--font-sans-pref",
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
    // `fonts-wired` is not cosmetic: it is the globals.css rule that maps the two `variable`
    // classes above onto --font-sans/-serif/-mono and applies the result. Drop it and the fonts
    // still download and still never render. It replaces the `font-sans` utility that used to be
    // here, which resolved to the system fallback rather than to the loaded family.
    <div className={`${hanken.variable} ${geistMono.variable} fonts-wired`}>
      <ErrorBoundary>
        <ToastProvider>
          <Seo />
          <Component {...pageProps} />
        </ToastProvider>
      </ErrorBoundary>
    </div>
  );
}
