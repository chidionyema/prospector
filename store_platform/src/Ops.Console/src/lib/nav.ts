/**
 * The console's map: which screens exist and which question each one answers.
 *
 * It lives here rather than inside `Shell.tsx` so it is data, not markup — a test can assert every
 * screen in the map has a page and every page is reachable from the map, and neither check needs
 * to render React.
 *
 * Grouped by the question an operator arrives with, not by the module that serves it. Somebody
 * opens this asking "is it running", "can we take money", "would we get the data back". Nobody
 * opens it asking for the scheduler subsystem.
 */
export type Screen = { href: string; label: string; what: string };
export type Group = { label: string; screens: Screen[] };

export const GROUPS: Group[] = [
  {
    label: 'Now',
    // Deploys sits beside Now because "is the thing I merged actually live?" is a
    // right-now question. It was invisible for twelve hours on 2026-08-19 while every
    // other screen read green.
    screens: [
      { href: '/', label: 'Now', what: 'what needs attention right now' },
      { href: '/deploys', label: 'Deploys', what: 'what each deployable is running, and how far behind main' },
    ],
  },
  {
    label: 'Engine',
    screens: [
      { href: '/engine', label: 'Engine', what: 'is the daemon running and what is it doing' },
      { href: '/queue', label: 'Queue', what: 'work waiting, and what is blocking it' },
      { href: '/runs', label: 'Runs', what: 'what each run produced' },
      { href: '/method', label: 'Method', what: 'how the agents work, and if it is improving' },
    ],
  },
  {
    label: 'Shelf',
    screens: [
      { href: '/catalogue', label: 'Catalogue', what: 'what is on offer' },
      { href: '/shelf', label: 'Stranded', what: 'passed every gate and cannot be bought' },
      { href: '/metrics', label: 'Yield', what: 'how much of what it generates survives' },
    ],
  },
  {
    // Sitting between Shelf and Money on purpose. Shelf is what is on offer, Shop is what actually
    // sold, Money is whether the rail that took it is healthy. That is the order an operator walks
    // when a buyer says they paid and got nothing.
    label: 'Shop',
    screens: [
      { href: '/orders', label: 'Orders', what: 'who bought what, and did they get it' },
      { href: '/revenue', label: 'Revenue', what: 'what the shop took, today and over a window' },
      { href: '/delivery', label: 'Delivery', what: 'who paid and has not received their link' },
      { href: '/disputes', label: 'Disputes', what: 'money a buyer has pulled back, or is trying to' },
    ],
  },
  {
    label: 'Money',
    screens: [
      { href: '/money', label: 'Rail', what: 'can the shop take money right now' },
      { href: '/spend', label: 'Spend', what: 'what the engine costs to run' },
    ],
  },
  {
    label: 'Data',
    screens: [
      { href: '/data', label: 'Backups', what: 'what survives if the volume is lost' },
      { href: '/audit', label: 'Audit', what: 'what changed, and who changed it' },
      { href: '/docs', label: 'Docs', what: 'the decisions, incidents and runbooks, in here' },
      { href: '/incidents', label: 'Incidents', what: 'what broke, and what stops it recurring' },
    ],
  },
  {
    label: 'Control',
    screens: [
      { href: '/config', label: 'Settings', what: 'the knobs, and their history' },
      { href: '/tools', label: 'Tools', what: 'run a tool, and undo it' },
      { href: '/share', label: 'Share', what: 'give someone outside a link to a file or the repo' },
      { href: '/processes', label: 'Processes', what: 'every automated job, and what is failing' },
    ],
  },
];

/**
 * Which screen a path is on, by LONGEST matching href.
 *
 * A `startsWith` sweep in declaration order would light up "Now" on every page, because every path
 * starts with `/`. Longest-match also keeps a detail route (`/runs/[id]`) inside its own group
 * instead of falling back to the root.
 */
export function activeScreen(path: string): { group: Group; screen: Screen } | null {
  let best: { group: Group; screen: Screen } | null = null;
  for (const group of GROUPS) {
    for (const screen of group.screens) {
      const hit = path === screen.href || path.startsWith(`${screen.href}/`);
      if (!hit) continue;
      if (!best || screen.href.length > best.screen.href.length) best = { group, screen };
    }
  }
  return best;
}
