import killLog from '@/data/kill-log.json';
import { plainEnglish } from '@/lib/plainEnglish';

/**
 * The kill corpus, SERVER SIDE ONLY, split into what a reader sees at once and what they open.
 *
 * WHY THIS FILE EXISTS -- measured on the live site, 2026-08-16:
 *
 *   https://mumchimp.com/kill-log   HTML  32,563 gz   JS  301,456 gz over 15 files
 *     of which one chunk           459,488 raw / 151,754 gz  <- `src/data/kill-log.json`
 *
 * That single chunk was 45% of what the browser downloaded for the page, and it is 456 KB of
 * JSON that a JS engine parses as an object literal before React renders anything. The page
 * displays none of it on arrival: `reason` (198 KB), `oneLiner` (93 KB) and `citations` (80 KB)
 * are rendered only inside a row the reader has expanded, and 371 of the 456 KB is those three
 * fields. A static `import` of a JSON file cannot be tree-shaken, so every visitor paid for all
 * four hundred arguments to read the four hundred titles.
 *
 * So the page now reads the corpus HERE, inside `getStaticProps`, which Next strips from the
 * client bundle along with everything only it imports. The reader gets:
 *
 *   - the SUMMARY of every kill in the page props (~50 KB raw: title, cause, date, source count),
 *     because all 400 rows stay in the HTML -- they are the deep-link anchors and the only SEO
 *     surface this page has (see the slug note below);
 *   - the DETAIL on demand from `/api/kill-log-detail`, fetched once when the reader first
 *     searches or first opens a row.
 *
 * `plainEnglish` is applied HERE too, once per string at build time. It used to run inside the
 * search filter -- both fields of all 400 rows, several dozen regexes each, on every keystroke.
 */

export type Citation = { url: string; domain: string };

/** What the table shows before anyone clicks anything. */
export type KillSummary = {
  slug: string;
  title: string;
  gateLabel: string;
  date: string;
  /** The count, not the list. The list is in the detail payload. */
  sources: number;
};

/** What an expanded row shows, keyed by slug. Prose is already translated. */
export type KillDetail = { oneLiner: string; reason: string; citations: Citation[] };

export type GateBar = { gate: string; count: number; label: string; published: boolean };

export type KillIndex = {
  summaries: KillSummary[];
  gates: string[];
  gateCounts: Record<string, number>;
  distribution: GateBar[];
  publishedKills: number;
  withSource: number;
};

type Entry = {
  title: string;
  oneLiner: string;
  gate: string;
  gateLabel: string;
  reason: string;
  citations: Citation[];
  date: string;
};

const entries = killLog.entries as Entry[];

/*
  A STABLE ANCHOR PER KILL.

  Every row is individually linkable, which is the whole reason to publish a dataset rather than an
  article: a single rejection is the thing a reader actually wants to send to someone ("they killed
  this exact idea, and here is why"). It is also the only SEO surface a page like this has, because
  400 records under one URL is one document to a crawler and 400 addressable claims to a reader.

  The slug is derived from the TITLE, not from the array index, so adding kills to the top of the
  log (which `make_kill_log.py` does on every run, newest first) cannot silently repoint a link
  someone already shared at a different idea. Collisions get a numeric suffix in encounter order,
  which is stable for the same reason.

  It is computed HERE, in one place, because the page and the detail endpoint have to agree on it:
  a slug that differed between the two would open an empty row on exactly the kills whose titles
  collide.
*/
function slugs(): string[] {
  const seen = new Map<string, number>();
  return entries.map((entry) => {
    const base =
      entry.title
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '')
        .slice(0, 60) || 'kill';
    const n = seen.get(base) ?? 0;
    seen.set(base, n + 1);
    return n === 0 ? base : `${base}-${n + 1}`;
  });
}

// Labels for the gates that never appear in a published row, so the chart can name every bar it
// draws. The published rows carry their own `gateLabel` from the engine.
const EXTRA_LABELS: Record<string, string> = {
  min_composite: 'Scored below the bar overall',
  moat_ungrounded: 'The defensibility claim was not evidence-backed',
  source_or_die: 'Its own claims could not be sourced',
  buyer_intent: 'No sign anyone is trying to buy it',
};

/** Everything the page needs at load. Called from `getStaticProps`, never from a component. */
export function buildKillIndex(): KillIndex {
  const slugList = slugs();
  // `gate` -- the engine's internal key -- is deliberately NOT in this object. Every reader-facing
  // use is keyed on `gateLabel` (the chips, the sort, the chart's grouping), and 400 copies of an
  // identifier nothing renders is payload the page pays for in its own HTML.
  const summaries: KillSummary[] = entries.map((entry, i) => ({
    slug: slugList[i],
    title: entry.title,
    gateLabel: entry.gateLabel,
    date: entry.date,
    sources: entry.citations.length,
  }));

  // Every REASON present in what we publish, ordered by how many kills it accounts for, so the
  // filter reads as a map of how ideas actually die rather than an alphabetical list.
  //
  // Grouped by `gateLabel`, not by `gate`. The engine has emitted two keys for one check --
  // `distribution` and `route_to_market` -- and both carry the identical label "There is no route
  // to reach buyers". Keyed by `gate`, the filter row rendered that sentence twice, side by side,
  // with different counts (desktop-kill-log-fold.png, 2026-08-06): a reader clicking the first is
  // told there are two such kills when there are three, and the second chip is indistinguishable
  // from the first. The label is the right identity here because it is the claim being filtered
  // on, the buyer is choosing a reason, not a database key.
  const gateCounts = summaries.reduce<Record<string, number>>((acc, e) => {
    acc[e.gateLabel] = (acc[e.gateLabel] ?? 0) + 1;
    return acc;
  }, {});
  const gates = Object.keys(gateCounts).sort((a, b) => gateCounts[b] - gateCounts[a]);

  /*
    THE DISTRIBUTION, OVER ALL 1,330 KILLS AND NOT JUST THE PUBLISHED 400.

    This is the one chart on the site that answers "how do ideas actually die", and answering it
    from the published subset would be sampling bias baked into a picture: the subset deliberately
    EXCLUDES the three score-only gates, and those are the largest causes of death by a wide
    margin. A chart of the published rows would show `incumbency` as the number one killer when the
    real number one is a composite score below the bar -- a false claim rendered as a bar chart,
    and harder to argue with than a false sentence.

    So the chart plots the true totals and marks the bars whose kills carry no publishable
    argument. `make_kill_log.py` drops those because their reason reads "Composite 0.0000 below
    threshold 3.2", which is true and tells a reader nothing.
  */
  const byGate = (killLog.totals as { byGate: Record<string, number> }).byGate;
  const labelFor: Record<string, string> = { ...EXTRA_LABELS };
  entries.forEach((r) => {
    labelFor[r.gate] = r.gateLabel;
  });
  const published = new Set(entries.map((r) => r.gate));
  // Grouped by label, same reason as `gateCounts`: built straight from `Object.entries(byGate)`
  // this chart drew two bars for one claim (8 and 6, on both breakpoints) sitting side by side
  // under the same label -- the histogram equivalent of the filter-chip bug above. A reader
  // comparing bar lengths was comparing a real cause against half of itself.
  const distribution = Object.values(
    Object.entries(byGate)
      .map(([gate, count]) => ({
        gate,
        count,
        label: labelFor[gate] ?? gate.replace(/_/g, ' '),
        published: published.has(gate),
      }))
      .reduce<Record<string, GateBar>>((acc, d) => {
        const existing = acc[d.label];
        if (existing) {
          existing.count += d.count;
          existing.published = existing.published || d.published;
        } else {
          acc[d.label] = { ...d };
        }
        return acc;
      }, {}),
  ).sort((a, b) => b.count - a.count);

  return {
    summaries,
    gates,
    gateCounts,
    distribution,
    publishedKills: summaries.length,
    withSource: summaries.filter((e) => e.sources > 0).length,
  };
}

/**
 * The expanded-row payload, keyed by the same slug the summaries carry.
 *
 * Translated here rather than in the browser: this is the engine's audit prose, written for an
 * operator, and `plainEnglish` is the last step before a reader sees it. Doing it once at build
 * time is also what took the translation off the keystroke path in the search box.
 */
export function buildKillDetails(): Record<string, KillDetail> {
  const slugList = slugs();
  const out: Record<string, KillDetail> = {};
  entries.forEach((entry, i) => {
    out[slugList[i]] = {
      oneLiner: plainEnglish(entry.oneLiner),
      reason: plainEnglish(entry.reason),
      citations: entry.citations,
    };
  });
  return out;
}
