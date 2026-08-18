/**
 * What the operator sees when a page throws while rendering.
 *
 * Added 2026-08-18, after the console went public and reported only Next's default
 * "Application error: a client-side exception has occurred". That screen is useless twice
 * over: the operator cannot act on it, and neither can anyone diagnosing it, because the
 * real message is in a console nobody has open on a phone. A dashboard whose failure mode
 * is a blank page is not an operations tool.
 *
 * So this catches the throw and prints it. The console shows queue contents and spend, and
 * it already sits behind a password, so showing a stack trace here leaks nothing to anyone
 * who is not already signed in.
 */
import React from 'react';

import { reportClientError } from '@/lib/report';

type Props = { children: React.ReactNode };
type State = { error: Error | null };

export class ErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    // Two destinations, because they answer different questions. The browser console is for
    // someone with devtools already open. The POST is so the fault reaches `fly logs` and can
    // be read from here — the whole reason the first report of this bug could not be diagnosed.
    console.error('ops console render failure', error, info.componentStack);
    reportClientError('render', error, info.componentStack ?? undefined);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <main className="mx-auto flex min-h-dvh max-w-2xl flex-col justify-center gap-4 px-4 py-10">
        <h1 className="font-mono text-[15px] font-[520]">This page broke while drawing itself</h1>
        <p className="text-[13px] text-muted">
          The engine may well be fine — this is the console failing, not the daemon. The message
          below is the actual fault.
        </p>
        <pre className="overflow-x-auto rounded-sm border border-border-control bg-surface p-3 font-mono text-[12px] whitespace-pre-wrap">
          {error.name}: {error.message}
          {error.stack ? `\n\n${error.stack}` : ''}
        </pre>
        <div className="flex gap-3">
          <button
            type="button"
            className="tap rounded-sm border border-border-control px-3 font-mono text-[13px]"
            onClick={() => window.location.reload()}
          >
            reload
          </button>
          {/*
            A plain anchor, not next/link, on purpose. The router has just failed inside this
            tree; a client-side navigation would re-enter the same broken state and land the
            operator back on this screen. A full document load is the point.
          */}
          {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
          <a
            className="tap rounded-sm border border-border-control px-3 font-mono text-[13px] leading-[2.4]"
            href="/"
          >
            back to Now
          </a>
        </div>
      </main>
    );
  }
}
