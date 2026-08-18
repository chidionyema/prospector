import type { AppProps } from 'next/app';
import Head from 'next/head';

import { ErrorBoundary } from '@/components/ErrorBoundary';
import '@/styles/globals.css';

export default function App({ Component, pageProps }: AppProps) {
  return (
    <>
      <Head>
        {/*
          `viewport-fit=cover` plus the safe-area padding in the shell is what keeps a confirm
          button off the iPhone home indicator. `maximum-scale` is deliberately NOT set: pinching
          to read a stack trace is a legitimate thing to do on a phone, and blocking it is an
          accessibility failure.
        */}
        <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
        <meta name="robots" content="noindex, nofollow" />
        <meta name="color-scheme" content="light" />
        <title>prospector ops</title>
      </Head>
      <ErrorBoundary>
        <Component {...pageProps} />
      </ErrorBoundary>
    </>
  );
}
