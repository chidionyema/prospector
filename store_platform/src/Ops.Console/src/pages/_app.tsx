import type { AppProps } from 'next/app';
import Head from 'next/head';
import { useEffect } from 'react';

import { ErrorBoundary } from '@/components/ErrorBoundary';
import { reportClientError } from '@/lib/report';
import '@/styles/globals.css';

export default function App({ Component, pageProps }: AppProps) {
  // The boundary below only sees throws that happen while React is rendering. A crash in an
  // event handler, a timer, or a rejected fetch goes straight past it and shows the operator
  // nothing at all. Those are caught here and reported to the same place.
  useEffect(() => {
    const onError = (e: ErrorEvent) => reportClientError('window.error', e.error ?? e.message);
    const onRejection = (e: PromiseRejectionEvent) =>
      reportClientError('unhandledrejection', e.reason);
    window.addEventListener('error', onError);
    window.addEventListener('unhandledrejection', onRejection);
    return () => {
      window.removeEventListener('error', onError);
      window.removeEventListener('unhandledrejection', onRejection);
    };
  }, []);

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
