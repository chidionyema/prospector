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
  /**
   * The opening of the real argument, in the page's own HTML.
   *
   * MASTER-BRIEF §7: "the argument is the row". Everything above deliberately keeps the reasoning
   * OUT of the initial payload, and that was right for the full 198 KB of `reason`; it was wrong
   * for the first sentence of it. A table of 400 titles and a cause label is a list of assertions:
   * the reader has to open a row to find a single piece of evidence, and on a phone that means
   * tapping blind to find out whether any of this is real. The excerpt is the cheapest possible
   * answer -- roughly 140 characters x 400 rows, ~56 KB, against the 371 KB the split saved.
   */
  excerpt: string;
};

/** What an expanded row shows, keyed by slug. Prose is already translated. */
export type KillDetail = { oneLiner: string; reason: string; citations: Citation[] };

export type GateBar = {
  gate: string;
  count: number;
  label: string;
  published: boolean;
  /** True when this cause is a STAGE of the process, not a CHECK on the idea. See STAGE_GATES. */
  isStage: boolean;
};

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
  // Added 2026-08-17. It was missing, and with no entry here the fallback below prints the raw
  // engine key with its underscores swapped for spaces -- "adversarial decisive". That is the
  // fourth largest cause of death on the site (142 kills), so the machine's own identifier was
  // being rendered to buyers on the biggest chart the page draws.
  adversarial_decisive: 'It did not survive the adversarial pass',
};

/*
 * STAGES ARE NOT CHECKS (MASTER-BRIEF §5.2, added 2026-08-17).
 *
 * A check is a question about the IDEA: is the pain real, can the payer pay. A stage is something
 * the PROCESS did -- it scored the idea, it attacked the idea, it went looking for evidence behind
 * a defensibility claim and found none. Both end an idea's life and both belong on this page, but
 * they answer different questions. Listing them in one undifferentiated column of "causes" tells a
 * reader that "scored below the bar" is a finding about the market. It is not. It is a fact about
 * our own threshold.
 *
 * The sizes are why this matters more here than anywhere else on the site. Measured against
 * `src/data/kill-log.json` totals on 2026-08-17: min_composite 624, moat_ungrounded 191,
 * adversarial_decisive 142 -- 957 of 1,364 kills, 70%. The single largest cause of death, and two
 * of the top four, are stages. A "how ideas die" chart that does not separate them is largely a
 * chart of our own process wearing the label of a market finding.
 *
 * Exactly the three the brief names. `source_or_die` and `buyer_intent` are deliberately NOT here:
 * they are evidence tests about the idea, which is what a check is.
 */
export const STAGE_GATES: ReadonlySet<string> = new Set([
  'min_composite',
  'moat_ungrounded',
  'adversarial_decisive',
]);

/**
 * Whether a cause is a stage of the process rather than a check on the idea.
 *
 * Keyed on the LABEL, not on the gate, because every reader-facing surface on this page is keyed
 * on label -- the filter chips, the sort, the chart's grouping -- for the reason written at
 * `gateCounts` below: two engine keys can carry one label, and keying on the key drew the same
 * claim twice with different counts. A helper that keyed on `gate` would reintroduce exactly that
 * split for stages.
 */
export function isStageLabel(label: string): boolean {
  for (const gate of STAGE_GATES) {
    if (EXTRA_LABELS[gate] === label) return true;
  }
  return false;
}

/** How much of the argument goes in the row. Two lines at the table's width, near enough. */
const EXCERPT_CHARS = 150;

/**
 * The opening of a kill's argument, cut to fit a table row.
 *
 * CUT ON A SENTENCE WHERE THERE IS ONE, ON A WORD OTHERWISE, NEVER MID-WORD. This page's entire
 * claim is that we are careful with evidence, so a row reading "the incumbent already bund…" makes
 * the argument look as carelessly handled as the sentence.
 *
 * A short reason is returned WHOLE and with no ellipsis. An ellipsis on a complete sentence says
 * there is more to read behind the row when there is not, and a reader who opens it finds the same
 * words again -- which teaches them the rest of the rows are not worth opening either.
 */
export function excerptOf(reason: string): string {
  const text = reason.replace(/\s+/g, ' ').trim();
  if (text.length <= EXCERPT_CHARS) return text;

  const window = text.slice(0, EXCERPT_CHARS + 1);

  // A full stop that ends a sentence, not one inside "3.2" or "e.g." -- it has to be followed by a
  // space and a capital, which is also why the search starts past the first few characters.
  const sentence = window.search(/[.!?]\s+[A-Z(]/);
  if (sentence > EXCERPT_CHARS / 3) return text.slice(0, sentence + 1);

  const space = window.lastIndexOf(' ');
  return `${text.slice(0, space > 0 ? space : EXCERPT_CHARS).replace(/[,;:]$/, '')}…`;
}

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
    // `plainEnglish` FIRST, then cut. The other way round, a translation that lengthens a phrase
    // ("the candidate" -> "the idea" shortens, but `payer_solvency` -> "whether the buyer can pay"
    // does not) would push the row past the width the cut was measured for, and the ellipsis would
    // land in a different place than the one that was checked.
    excerpt: excerptOf(plainEnglish(entry.reason)),
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
        // Read off the GATE here, where the gate is still in hand, rather than off the label. The
        // merge below is by label and the two agree, but a stage and a check can never share a
        // label, so this is the cheaper and more direct of the two.
        isStage: STAGE_GATES.has(gate),
      }))
      .reduce<Record<string, GateBar>>((acc, d) => {
        const existing = acc[d.label];
        if (existing) {
          existing.count += d.count;
          existing.published = existing.published || d.published;
          // OR, matching `published` directly above: merged bars share one label, and a label is
          // either a stage or it is not, so this can only ever re-assert what is already set.
          existing.isStage = existing.isStage || d.isStage;
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
