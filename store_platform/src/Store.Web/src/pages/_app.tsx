import "@/styles/globals.css";
import { useEffect } from "react";
import type { AppProps } from "next/app";
import { useRouter } from "next/router";
import { Hanken_Grotesk, Playfair_Display, Geist_Mono } from "next/font/google";
import { ToastProvider } from "@/components/ui";
import { Seo } from "@/components/Seo";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { track } from "@/lib/analytics";

const hanken = Hanken_Grotesk({
  subsets: ["latin"],
  weight: ["400", "600"],
  display: "swap",
  variable: "--font-sans-pref",
});

const playfair = Playfair_Display({
  subsets: ["latin"],
  weight: ["600", "700"],
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
    <div className={`${hanken.variable} ${playfair.variable} ${geistMono.variable} font-sans`}>
      <ErrorBoundary>
        <ToastProvider>
          <Seo />
          <Component {...pageProps} />
        </ToastProvider>
      </ErrorBoundary>
    </div>
  );
}
