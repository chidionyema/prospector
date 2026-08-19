/**
 * The console's whole vocabulary of parts.
 *
 * One file, because the set is small and a page that has to hunt through eleven component files
 * to find a card is a page that reinvents the card. The rules these encode:
 *
 *   - Every panel says when its data was read (`AsOf`). Not when the page loaded — when the
 *     ENGINE read it. Those differ by however long the Python call took plus however long the
 *     browser sat idle, and the second number is the one that lies.
 *   - A missing value renders as a named absence, never as `0` or a dash. A null that looks like
 *     a number is how a dashboard reports an outage as a measurement.
 *   - Nothing wide is allowed to widen the page. `Scroll` is the only escape hatch.
 */
import Link from 'next/link';
import type { ReactNode } from 'react';

import { ABSENT, duration, freshness } from '@/lib/time';

export function Card({
  title,
  right,
  children,
  tone = 'plain',
}: {
  title?: ReactNode;
  right?: ReactNode;
  children: ReactNode;
  tone?: 'plain' | 'ok' | 'warn' | 'bad';
}) {
  const edge =
    tone === 'ok'
      ? 'border-ok/40'
      : tone === 'warn'
        ? 'border-warn/50'
        : tone === 'bad'
          ? 'border-bad/50'
          : 'border-border';
  return (
    <section className={`bg-surface border ${edge} rounded-sm`}>
      {(title || right) && (
        /* flex-wrap, and the right-hand slot may shrink. It used to be `shrink-0`, which at 320px
           pushed the whole page 19px sideways as soon as the as-of line read "read under a second
           ago · took under a second". Measured 2026-08-16. */
        <header className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-b border-border px-4 py-3">
          <h2 className="min-w-0 text-[15px] font-[560] leading-tight">{title}</h2>
          {right ? <div className="min-w-0 text-[12px] text-subtle">{right}</div> : null}
        </header>
      )}
      <div className="px-4 py-3">{children}</div>
    </section>
  );
}

/**
 * "read 4s ago". Amber past a minute.
 *
 * Founder requirement: "every screen states when its data was last read." This is that sentence,
 * and it takes the engine's `as_of`, so a stuck poller shows as stale instead of showing as
 * fresh-because-the-component-re-rendered.
 */
export function AsOf({ asOf, tookMs }: { asOf?: number | null; tookMs?: number | null }) {
  const f = freshness(asOf ?? null);
  return (
    <span className={f.stale ? 'text-warn-strong' : 'text-subtle'}>
      {f.label}
      {typeof tookMs === 'number' ? ` · took ${duration(tookMs / 1000)}` : ''}
    </span>
  );
}

/** A headline number with its unit and a caption. Absent renders as words. */
export function Stat({
  label,
  value,
  unit,
  note,
  tone = 'plain',
}: {
  label: string;
  value: ReactNode;
  unit?: string;
  note?: ReactNode;
  tone?: 'plain' | 'ok' | 'warn' | 'bad';
}) {
  const colour =
    tone === 'ok'
      ? 'text-ok-strong'
      : tone === 'warn'
        ? 'text-warn-strong'
        : tone === 'bad'
          ? 'text-bad-strong'
          : 'text-text';
  // `text-subtle`, not `text-faint`: axe measured --faint at 2.56:1 on white at this size, and a
  // stat that reads "not recorded" is information, not decoration. --faint is for rules and
  // placeholders that carry nothing.
  const missing = value === null || value === undefined || value === '';
  return (
    <div className="min-w-0">
      <div className="text-[12px] uppercase tracking-[0.06em] text-subtle">{label}</div>
      <div className={`font-mono text-[22px] leading-tight ${missing ? 'text-subtle' : colour}`}>
        {missing ? ABSENT : value}
        {!missing && unit ? <span className="ml-1 text-[13px] text-subtle">{unit}</span> : null}
      </div>
      {note ? <div className="mt-0.5 text-[12px] text-muted">{note}</div> : null}
    </div>
  );
}

export function Pill({
  tone = 'plain',
  children,
}: {
  tone?: 'plain' | 'ok' | 'warn' | 'bad' | 'mute';
  children: ReactNode;
}) {
  const cls = {
    ok: 'bg-ok-bg text-ok-strong border-ok/30',
    warn: 'bg-warn-bg text-warn-strong border-warn/30',
    bad: 'bg-bad-bg text-bad-strong border-bad/30',
    mute: 'bg-surface3 text-subtle border-border',
    plain: 'bg-surface3 text-text border-border',
  }[tone];
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-sm border px-1.5 py-0.5 font-mono text-[12px] ${cls}`}
    >
      {children}
    </span>
  );
}

/** A label/value line. Stacks on a phone, sits on one line from `sm` up. */
export function Row({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5 border-b border-border py-2 last:border-0 sm:flex-row sm:items-baseline sm:justify-between sm:gap-4">
      <div className="text-[13px] text-muted">{label}</div>
      <div className="wrap-any min-w-0 font-mono text-[13px] sm:text-right">{children}</div>
    </div>
  );
}

/**
 * The only place sideways scrolling is allowed.
 *
 * `tabIndex={0}` because a scroll container a keyboard cannot enter is content a keyboard user
 * cannot reach the right-hand side of. axe rates it `serious`, and it only fires at 390px --
 * where these actually overflow -- which is the width the console is used at.
 */
export function Scroll({ children }: { children: ReactNode }) {
  return (
    <div className="scroll-x -mx-4 px-4" tabIndex={0}>
      {children}
    </div>
  );
}

export function Button({
  children,
  onClick,
  kind = 'plain',
  disabled,
  type = 'button',
  title,
}: {
  children: ReactNode;
  onClick?: () => void;
  kind?: 'plain' | 'primary' | 'danger';
  disabled?: boolean;
  type?: 'button' | 'submit';
  title?: string;
}) {
  const cls = {
    primary: 'bg-action text-on-action border-action hover:bg-action-hover',
    danger: 'bg-bad text-white border-bad hover:bg-bad-strong',
    plain: 'bg-surface text-text border-border-control hover:bg-surface3',
  }[kind];
  return (
    <button
      type={type}
      title={title}
      onClick={onClick}
      disabled={disabled}
      className={`tap rounded-sm border px-3 text-[14px] font-[520] disabled:cursor-not-allowed disabled:opacity-45 ${cls}`}
    >
      {children}
    </button>
  );
}

/** A loud, unmissable failure. An error rendered small is an error nobody acts on. */
export function Problem({ children }: { children: ReactNode }) {
  return (
    <div className="wrap-any rounded-sm border border-bad/40 bg-bad-bg px-3 py-2 text-[13px] text-bad-strong">
      {children}
    </div>
  );
}

export function Note({ children }: { children: ReactNode }) {
  return (
    <div className="wrap-any rounded-sm border border-border bg-surface2 px-3 py-2 text-[13px] text-muted">
      {children}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="py-6 text-center text-[13px] text-subtle">{children}</div>;
}

export function Spinner({ what }: { what: string }) {
  return <div className="py-6 text-center text-[13px] text-subtle">reading {what}…</div>;
}

export function Mono({ children }: { children: ReactNode }) {
  return <span className="wrap-any font-mono text-[13px]">{children}</span>;
}

export function TileLink({
  href,
  title,
  detail,
}: {
  href: string;
  title: string;
  detail: ReactNode;
}) {
  return (
    <Link
      href={href}
      className="tap flex items-center justify-between gap-3 rounded-sm border border-border bg-surface px-3 py-2 hover:bg-surface3"
    >
      <span className="text-[14px] font-[520]">{title}</span>
      <span className="shrink-0 font-mono text-[12px] text-subtle">{detail}</span>
    </Link>
  );
}
