import "@/styles/globals.css";
import type { AppProps } from "next/app";
import { Hanken_Grotesk, Playfair_Display, Geist_Mono } from "next/font/google";
import { ToastProvider } from "@/components/ui";
import { Seo } from "@/components/Seo";
import { ErrorBoundary } from "@/components/ErrorBoundary";

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
