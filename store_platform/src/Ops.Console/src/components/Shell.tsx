/**
 * The frame every screen sits in.
 *
 * Mobile first, and specifically Telegram-first: the founder opens this from a link inside
 * Telegram, which is a WKWebView with its own toolbar overlaying the bottom of the viewport. So
 * navigation lives at the TOP, not in a bottom bar — a bottom bar is exactly the strip that
 * webview hides.
 *
 * The nav is two short rows, not one long strip. It used to be a single horizontally scrolling
 * list of every destination; at thirteen screens the last four were off-screen at 390px width, so
 * reaching Audit meant swiping a strip that gave no sign there was anything to swipe to. Now the
 * first row is six groups that fit without scrolling, and the second row is the screens inside the
 * group you are in. Both rows wrap. Nothing here scrolls sideways.
 *
 * Still no hamburger. Every destination is at most two taps and the current one is always visible,
 * which a menu behind a tap cannot do.
 */
import Link from 'next/link';
import { useRouter } from 'next/router';
import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';

import { GROUPS, activeScreen } from '@/lib/nav';
import { useOps } from '@/lib/useOps';

const TAB_BASE =
  'tap inline-flex items-center gap-1.5 rounded-sm border px-3 text-[13px] font-[520] transition-colors';

type Attention = {
  groups: { group: string; state: string; count: number; findings: { what: string }[] }[];
  headline: string;
  worst: string;
};

/**
 * A dot on the group that has a problem.
 *
 * Before this, "is anything wrong" cost up to seven navigations: every screen derived its own
 * trouble in its own markup and nothing above a screen carried a signal. The dot is the whole
 * feature — it says WHICH group, and the group's own screen still says what.
 *
 * It renders for `bad` and `warn` only. `ok` and `unmeasured` both render nothing, and the
 * difference between them is deliberately not a dot: an absent dot means "no fault found here",
 * and if it could also mean "checked and healthy" versus "never asked" it would stop meaning
 * anything at a glance. Which groups went unchecked is a sentence on the Now page, not a symbol.
 *
 * Fixed width, so a dot arriving on a poll cannot reflow the nav under the founder's thumb.
 */
function Dot({ a }: { a?: { state: string; count: number; findings: { what: string }[] } }) {
  const on = a && (a.state === 'bad' || a.state === 'warn');
  if (!on) return <span aria-hidden className="w-1.5" />;
  const faults = a.findings.filter((f) => f.what).slice(0, 4).map((f) => f.what);
  return (
    <span
      title={faults.join('\n')}
      aria-label={`${a.count} need${a.count === 1 ? 's' : ''} attention`}
      className={`h-1.5 w-1.5 shrink-0 rounded-full ring-1 ring-bg ${
        a.state === 'bad' ? 'bg-bad' : 'bg-warn'
      }`}
    />
  );
}
const TAB_ON = 'border-action bg-action text-on-action';
const TAB_OFF = 'border-border bg-surface text-muted hover:bg-surface3';

export default function Shell({
  title,
  children,
  intro,
}: {
  title: string;
  children: ReactNode;
  intro?: ReactNode;
}) {
  const router = useRouter();
  // 120s, not the 30s every panel uses. This is the ONE read that happens on every screen, so its
  // cost is paid by all of them; a badge that is two minutes stale still answers "which group"
  // faster than opening seven screens, and the screen itself is always current.
  const { data: att } = useOps<Attention>('attention', {}, { pollMs: 120_000 });
  const byGroup = new Map((att?.groups ?? []).map((g) => [g.group, g]));
  const here = activeScreen(router.pathname);
  const openGroup = here?.group ?? GROUPS[0];
  const showScreens = openGroup.screens.length > 1;

  return (
    <div className="min-h-dvh bg-bg">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-20 focus:rounded-sm focus:border focus:border-action focus:bg-surface focus:px-3 focus:py-2 focus:text-[13px]"
      >
        skip to content
      </a>

      <header className="sticky top-0 z-10 border-b border-border bg-bg/95 backdrop-blur">
        <div className="mx-auto flex max-w-3xl items-baseline justify-between gap-3 px-4 pb-2 pt-3">
          <span className="font-mono text-[13px] font-[520] tracking-tight">prospector ops</span>
          <Where />
          <SignOut />
        </div>

        <nav className="mx-auto max-w-3xl px-4 pb-2" aria-label="Sections">
          <ul className="flex flex-wrap gap-1">
            {GROUPS.map((g) => {
              const on = g.label === openGroup.label;
              return (
                <li key={g.label}>
                  <Link
                    href={g.screens[0].href}
                    aria-current={on ? 'true' : undefined}
                    className={`${TAB_BASE} ${on ? TAB_ON : TAB_OFF}`}
                  >
                    {g.label}
                    <Dot a={byGroup.get(g.label)} />
                  </Link>
                </li>
              );
            })}
          </ul>

          {showScreens ? (
            <ul className="mt-1 flex flex-wrap gap-1" aria-label={`${openGroup.label} screens`}>
              {openGroup.screens.map((s) => {
                const on = here?.screen.href === s.href;
                return (
                  <li key={s.href}>
                    <Link
                      href={s.href}
                      title={s.what}
                      aria-current={on ? 'page' : undefined}
                      className={`tap inline-flex items-center rounded-sm px-2.5 text-[13px] ${
                        on
                          ? 'bg-surface3 font-[560] text-text'
                          : 'text-subtle hover:bg-surface3 hover:text-text'
                      }`}
                    >
                      {s.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          ) : null}
        </nav>
      </header>

      <main id="main" className="mx-auto max-w-3xl px-4 pb-16 pt-4">
        <h1 className="text-[20px] font-[560] leading-tight">{title}</h1>
        {intro ? <p className="mt-1 text-[13px] text-muted">{intro}</p> : null}
        <div className="mt-4 flex flex-col gap-4">{children}</div>
      </main>
    </div>
  );
}

// 44px tall, like every other control. This was 18px, sitting next to the header text, until the
// e2e run measured it on 2026-08-16. The negative margin keeps the header the same height.
function SignOut() {
  return (
    <button
      type="button"
      className="tap -my-2 inline-flex items-center px-2 text-[12px] text-subtle underline underline-offset-2 hover:text-text"
      onClick={async () => {
        await fetch('/api/ops/session', { method: 'DELETE', credentials: 'same-origin' });
        window.location.href = '/login';
      }}
    >
      sign out
    </button>
  );
}

/**
 * Which estate is on screen. Asked once per page load, never polled.
 *
 * The founder asked for this after the Fly cutover: a production console and one served by a
 * laptop dev server look identical, and they are one bookmark apart. Arming a pause on the wrong
 * machine because the screens match is the failure this badge exists to make impossible.
 *
 * It renders NOTHING until the answer arrives. A badge that guesses "production" while it waits is
 * worse than no badge, because it is only ever read at a glance.
 */
function Where() {
  const [w, setW] = useState<{ place: string; label: string } | null>(null);

  useEffect(() => {
    let live = true;
    fetch('/api/ops/where', { credentials: 'same-origin' })
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => {
        if (live && j?.label) setW({ place: j.place, label: j.label });
      })
      .catch(() => {
        // A badge is not worth an error state. Silence reads as "not answered", which is honest.
      });
    return () => {
      live = false;
    };
  }, []);

  if (!w) return null;
  const local = w.place !== 'production';
  return (
    <span
      title={local ? 'This console is not production.' : 'This console is served by production.'}
      className={`truncate rounded-sm border px-1.5 font-mono text-[11px] ${
        local ? 'border-bad/40 bg-bad-bg text-bad-strong' : 'border-border bg-surface2 text-subtle'
      }`}
    >
      {w.label}
    </span>
  );
}
