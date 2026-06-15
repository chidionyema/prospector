import React, { useEffect, useState, useMemo } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { useAuth } from '@/context/AuthContext';
import { useMode } from '@/context/ModeContext';
import ModeToggle from '@/components/ModeToggle';
import { Logo, Icon, useToast, cx, type IconName } from '@/components/ui';
import { BRAND } from '@/lib/config';
import { useDisclosure } from '@/lib/useDisclosure';
import { bountiesApi, proposalsApi } from '@/lib/api/client';

interface LayoutProps {
  children: React.ReactNode;
}

type NavItem = { href: string; label: string; icon: IconName; count?: number };

const ACCOUNT_LINKS: NavItem[] = [{ href: '/settings/profile', label: 'Settings', icon: 'settings' }];

/** A route is active when it is the exact path, or (for nested sections) a child of it. Home matches
 *  only itself so it does not light up under every /proposals/* route. */
function isActive(href: string, pathname: string): boolean {
  if (href === '/dashboard') return pathname === '/dashboard';
  return pathname === href || pathname.startsWith(`${href}/`);
}

/** One nav row — icon + label, with a clear "you are here" state (a brass-free primary accent bar +
 *  tinted icon), reused by the desktop rail and the mobile drawer. */
function NavRow({
  item,
  active,
  onNavigate,
}: {
  item: NavItem;
  active: boolean;
  onNavigate?: () => void;
}) {
  return (
    <Link
      href={item.href}
      onClick={onNavigate}
      aria-current={active ? 'page' : undefined}
      className={cx(
        'group relative flex items-center gap-3 rounded-md px-3 py-2 text-small transition-colors',
        active ? 'bg-surface2 text-text' : 'text-muted hover:bg-surface2 hover:text-text',
      )}
    >
      {active && (
        <span
          className="absolute inset-y-1.5 left-0 w-0.5 rounded-full bg-primary"
          aria-hidden="true"
        />
      )}
      <Icon
        name={item.icon}
        size={18}
        className={active ? 'text-primary' : 'text-faint group-hover:text-muted'}
      />
      <span className={cx('flex-1 truncate', active ? 'font-semibold' : undefined)}>
        {item.label}
      </span>
      {item.count !== undefined && item.count > 0 && (
        <span className="flex h-4.5 min-w-[18px] items-center justify-center rounded-full bg-primary/10 px-1 text-[10px] font-bold text-primary">
          {item.count}
        </span>
      )}
    </Link>
  );
}

/** App shell — a persistent left rail (brand, mode-scoped nav, account + mode switch at the foot) so the
 *  logged-in product reads as a product, not a marketing page with a dashboard bolted on. Collapses to a
 *  top bar + drawer below `lg`. Semantic tokens only, real session state (SITE-POLISH-SPEC §2.1). */
export default function Layout({ children }: LayoutProps) {
  const { user, logout, loading } = useAuth();
  const { mode } = useMode();
  const router = useRouter();
  const { toast } = useToast();
  const [menuOpen, setMenuOpen] = useState(false);
  const { triggerRef: menuButtonRef } = useDisclosure(menuOpen, () => setMenuOpen(false));
  const name = user?.profile.display_name || user?.email;

  const [counts, setCounts] = useState({ seeker: 0, connector: 0 });

  // Hydrate action counts for the sidebar — gives the "Linear-grade" sense of what needs doing
  // before you even click.
  useEffect(() => {
    if (!user) return;
    let active = true;
    void (async () => {
      try {
        const [b, p] = await Promise.all([
          bountiesApi.mine(),
          proposalsApi.listMine(),
        ]);
        if (!active) return;
        setCounts({
          seeker: b.filter(x => x.current_state === 'PendingMatch').length,
          connector: p.filter(x => x.status === 'Accepted' && x.bounty_state === 'PendingMatch').length,
        });
      } catch {
        // Silent fail for counts — navigational intelligence is a progressive enhancement.
      }
    })();
    return () => { active = false; };
  }, [user]);

  const navLinks = useMemo<NavItem[]>(() => {
    if (mode === 'seeker') {
      return [
        { href: '/dashboard', label: 'My Requests', icon: 'home', count: counts.seeker },
        { href: '/proposals/new', label: 'Start a Brief', icon: 'post' },
        { href: '/proposals/funded', label: 'Funded Briefs', icon: 'landmark' },
        { href: '/proposals/completed', label: 'Completed Intros', icon: 'completed' },
      ];
    }
    return [
      { href: '/dashboard', label: 'My Earnings', icon: 'home', count: counts.connector },
      { href: '/board', label: 'Review Queue', icon: 'board' },
      { href: '/roster', label: 'Private Roster', icon: 'roster' },
      { href: '/settings/payouts', label: 'Payouts & Wallet', icon: 'wallet' },
    ];
  }, [mode, counts]);

  async function handleLogout() {
    await logout();
    toast('Signed out successfully');
  }

  // Close the mobile drawer on any navigation (back/forward, or a link that does not already close
  // it), so it never lingers open over a new page.
  useEffect(() => {
    const close = () => setMenuOpen(false);
    router.events.on('routeChangeComplete', close);
    return () => router.events.off('routeChangeComplete', close);
  }, [router.events]);

  const legal = (
    <nav className="flex flex-wrap items-center gap-x-4 gap-y-1 text-caption text-muted" aria-label="Legal">
      <Link href="/terms" className="hover:text-text">
        Terms
      </Link>
      <Link href="/privacy" className="hover:text-text">
        Privacy
      </Link>
      <Link href="/remove-me" className="hover:text-text">
        Remove me
      </Link>
    </nav>
  );

  // The signed-out shell is a bare frame: marketing/login pages bring their own chrome, so here we only
  // need the skip-link + the content well (no rail, no account foot).
  if (!loading && !user) {
    return (
      <div className="min-h-screen bg-bg font-sans text-text">
        <a
          href="#main"
          className="sr-only focus-visible:not-sr-only focus-visible:absolute focus-visible:left-4 focus-visible:top-4 focus-visible:z-50 focus-visible:rounded-md focus-visible:bg-primary focus-visible:px-4 focus-visible:py-2 focus-visible:text-on-primary"
        >
          Skip to content
        </a>
        <main id="main" className="mx-auto max-w-6xl px-6 py-12 md:px-8 lg:px-10">
          {children}
        </main>
      </div>
    );
  }

  const railNav = (onNavigate?: () => void) => (
    <>
      <nav className="flex flex-col gap-0.5" aria-label="Primary">
        {navLinks.map((l) => (
          <NavRow key={l.href} item={l} active={isActive(l.href, router.pathname)} onNavigate={onNavigate} />
        ))}
        <div className="my-2 h-px bg-border" />
        {ACCOUNT_LINKS.map((l) => (
          <NavRow key={l.href} item={l} active={isActive(l.href, router.pathname)} onNavigate={onNavigate} />
        ))}
      </nav>
    </>
  );

  const railFoot = (
    <div className="space-y-3">
      {/* The role switch leads at the foot of the rail — a connector must always be able to find funding
          (and vice versa), never have it buried (WR-036). */}
      <ModeToggle fullWidth />
      <div className="flex items-center justify-between gap-2 rounded-md border border-border bg-bg px-3 py-2">
        <span className="flex min-w-0 items-center gap-2 text-small text-muted">
          <Icon name="account" size={16} className="shrink-0 text-faint" />
          <span className="truncate">{name}</span>
        </span>
        <button
          type="button"
          onClick={() => void handleLogout()}
          aria-label="Sign out"
          className="shrink-0 rounded-md p-1.5 text-muted hover:bg-surface2 hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus"
        >
          <Icon name="signout" size={16} />
        </button>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen bg-bg font-sans text-text">
      <a
        href="#main"
        className="sr-only focus-visible:not-sr-only focus-visible:absolute focus-visible:left-4 focus-visible:top-4 focus-visible:z-50 focus-visible:rounded-md focus-visible:bg-primary focus-visible:px-4 focus-visible:py-2 focus-visible:text-on-primary"
      >
        Skip to content
      </a>

      {/* Desktop left rail (lg+). Fixed so the content scrolls under a persistent product frame. */}
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-64 flex-col border-r border-border bg-surface lg:flex">
        <div className="flex h-full flex-col gap-6 p-4">
          <Link
            href={user ? '/dashboard' : '/'}
            aria-label={`${BRAND.name} home`}
            className="px-1 py-1 transition-opacity hover:opacity-80"
          >
            <Logo />
          </Link>
          <div className="flex-1 overflow-y-auto">
            {loading ? (
              <div className="space-y-2" aria-hidden="true">
                <div className="h-9 animate-pulse rounded-md bg-border/60" />
                <div className="h-9 animate-pulse rounded-md bg-border/40" />
                <div className="h-9 animate-pulse rounded-md bg-border/30" />
              </div>
            ) : (
              railNav()
            )}
          </div>
          {user && railFoot}
          {legal}
        </div>
      </aside>

      {/* Mobile top bar (below lg) — brand + a drawer trigger. */}
      <header className="sticky top-0 z-40 border-b border-border bg-surface/90 backdrop-blur-md lg:hidden">
        <div className="flex items-center justify-between gap-4 px-5 py-3">
          <Link
            href={user ? '/dashboard' : '/'}
            aria-label={`${BRAND.name} home`}
            className="transition-opacity hover:opacity-80"
          >
            <Logo />
          </Link>
          {user && (
            <button
              ref={menuButtonRef}
              type="button"
              className="inline-flex items-center justify-center rounded-md p-2 text-muted hover:bg-surface2 hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus"
              aria-label={menuOpen ? 'Close menu' : 'Open menu'}
              aria-expanded={menuOpen}
              aria-controls="mobile-drawer"
              onClick={() => setMenuOpen((o) => !o)}
            >
              <Icon name={menuOpen ? 'close' : 'menu'} />
            </button>
          )}
        </div>
      </header>

      {/* Mobile drawer */}
      {user && menuOpen && (
        <>
          <div
            className="fixed inset-0 z-40 bg-text/30 backdrop-blur-sm lg:hidden"
            aria-hidden="true"
            onClick={() => setMenuOpen(false)}
          />
          <div
            id="mobile-drawer"
            className="fixed inset-y-0 right-0 z-50 flex w-72 max-w-[85%] flex-col gap-6 border-l border-border bg-surface p-5 shadow-2 lg:hidden"
          >
            <div className="flex-1 overflow-y-auto">{railNav(() => setMenuOpen(false))}</div>
            {railFoot}
            {legal}
          </div>
        </>
      )}

      {/* Content well, offset by the rail on lg+. */}
      <div className="lg:pl-64">
        <main id="main" className="mx-auto max-w-6xl px-6 py-10 md:px-8 lg:px-12 lg:py-12">
          {children}
        </main>
      </div>
    </div>
  );
}
