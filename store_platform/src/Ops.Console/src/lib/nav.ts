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
    screens: [{ href: '/', label: 'Now', what: 'what needs attention right now' }],
  },
  {
    label: 'Engine',
    screens: [
      { href: '/engine', label: 'Engine', what: 'is the daemon running and what is it doing' },
      { href: '/queue', label: 'Queue', what: 'work waiting, and what is blocking it' },
      { href: '/runs', label: 'Runs', what: 'what each run produced' },
      { href: '/metrics', label: 'Yield', what: 'how much of what it generates survives' },
    ],
  },
  {
    label: 'Shelf',
    screens: [
      { href: '/catalogue', label: 'Catalogue', what: 'what is on offer' },
      { href: '/shelf', label: 'Stranded', what: 'passed every gate and cannot be bought' },
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
    ],
  },
  {
    label: 'Control',
    screens: [
      { href: '/config', label: 'Settings', what: 'the knobs, and their history' },
      { href: '/tools', label: 'Tools', what: 'run a tool, and undo it' },
      { href: '/method', label: 'Method', what: 'how the agents work, and if it is improving' },
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
