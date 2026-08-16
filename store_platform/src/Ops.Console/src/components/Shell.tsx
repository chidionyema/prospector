/**
 * The frame every screen sits in.
 *
 * Mobile first, and specifically Telegram-first: the founder opens this from a link inside
 * Telegram, which is a WKWebView with its own toolbar overlaying the bottom of the viewport. So
 * navigation lives at the TOP, not in a bottom bar — a bottom bar is exactly the strip that
 * webview hides. The nav is a horizontally scrolling strip of tabs; it is the one element
 * allowed to scroll sideways, inside itself.
 *
 * There is no hamburger. A menu behind a tap is a menu that costs a tap on every navigation, and
 * this console has nine destinations, not ninety.
 */
import Link from 'next/link';
import { useRouter } from 'next/router';
import type { ReactNode } from 'react';

const TABS: { href: string; label: string }[] = [
  { href: '/', label: 'Now' },
  { href: '/engine', label: 'Engine' },
  { href: '/config', label: 'Settings' },
  { href: '/queue', label: 'Queue' },
  { href: '/runs', label: 'Runs' },
  { href: '/spend', label: 'Spend' },
  { href: '/metrics', label: 'Yield' },
  { href: '/catalogue', label: 'Shelf' },
  { href: '/tools', label: 'Tools' },
  { href: '/audit', label: 'Audit' },
];

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
  const path = router.pathname;

  return (
    <div className="min-h-dvh bg-bg">
      <header className="sticky top-0 z-10 border-b border-border bg-bg/95 backdrop-blur">
        <div className="mx-auto flex max-w-3xl items-baseline justify-between gap-3 px-4 pb-2 pt-3">
          <span className="font-mono text-[13px] font-[520] tracking-tight">prospector ops</span>
          <SignOut />
        </div>
        <nav className="scroll-x mx-auto max-w-3xl px-4 pb-2" aria-label="Sections">
          <ul className="flex gap-1 whitespace-nowrap">
            {TABS.map((t) => {
              const active = t.href === '/' ? path === '/' : path.startsWith(t.href);
              return (
                <li key={t.href}>
                  <Link
                    href={t.href}
                    aria-current={active ? 'page' : undefined}
                    className={`tap inline-flex items-center rounded-sm border px-3 text-[13px] font-[520] ${
                      active
                        ? 'border-action bg-action text-on-action'
                        : 'border-border bg-surface text-muted hover:bg-surface3'
                    }`}
                  >
                    {t.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
      </header>

      <main className="mx-auto max-w-3xl px-4 pb-16 pt-4">
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
