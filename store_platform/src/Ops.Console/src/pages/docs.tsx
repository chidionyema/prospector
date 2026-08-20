/**
 * Docs — the decisions, incidents and runbooks, readable without a checkout.
 *
 * Why this page exists. On 2026-08-19 the founder asked twice whether the stack documents were
 * reachable from ops. They were not: no page rendered markdown, no API route read `docs/`, and
 * the console had no markdown dependency at all. So a decision record could be written, committed
 * and pushed, and still be readable only by someone at a terminal with a clone. That is the
 * "built and unreachable" failure this estate keeps hitting.
 *
 * WHAT CHANGED ON 2026-08-20, AND WHY IT WAS OWED. The first version of this file said, in this
 * docblock, that plain text was deliberate: "the console has no markdown dependency, and adding
 * one in order to ship a reader is the scope creep that turns a same-day answer into a week".
 * That was an honest trade and it bought a same-day answer. The founder then read a page of raw
 * markdown source and said: "i can see a list but cant read it, loads slow, no way to search and
 * filter etc or categorise". That is the bill for the deferral, and this commit pays it. Four
 * things, all of which the earlier version scoped as "a later commit that touches only this file":
 *
 *  1. RENDERED MARKDOWN, with a Source toggle. `react-markdown` + `remark-gfm` — the renderer
 *     with the largest community, and GFM because these documents are full of tables. Raw HTML is
 *     NOT enabled (no `rehype-raw`), so an HTML tag in a doc is inert rather than executed. That
 *     is the sanitisation: nothing is parsed into markup that react-markdown did not produce.
 *     `.json` documents render as source always — a JSON file put through a markdown parser is
 *     one long paragraph, which is worse than the file.
 *  2. SEARCH AND CATEGORY CHIPS, entirely client-side over the index that is already loaded.
 *     Typing costs nothing: no read, no spawn.
 *  3. REAL CATEGORIES, from `prospector/ops/docs_view.py::_CATEGORIES`. There used to be three
 *     sections and 78 of the 104 documents sat in the third one.
 *  4. NO POLLING ON THIS PAGE. `useOps` polls every 30s by default, and every poll is a fresh
 *     Python process — two of them here, one for the index and one for the open document.
 *     Documents change when someone deploys, not every thirty seconds, so both reads are
 *     `pollMs: 0` with a Refresh button. That is two spawns per 30s per open tab, removed.
 *
 * What this is NOT yet: shareable. A link a non-operator can open, that expires and can be
 * revoked, needs a token store and a route that answers without a session — that arrived
 * separately as `/share`. Everything here sits behind the console's own auth.
 */
import { useRouter } from 'next/router';
import { useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import Shell from '@/components/Shell';
import { AsOf, Button, Card, Empty, Note, Problem, Scroll, Spinner } from '@/components/ui';
import { useOps } from '@/lib/useOps';

type DocEntry = {
  name: string;
  title: string;
  bytes: number;
  modified: number;
  category?: string;
};
type DocsIndex = {
  root: string;
  count: number;
  note?: string;
  sections: { label: string; docs: DocEntry[] }[];
};
type DocText = {
  name: string;
  title: string;
  text: string;
  bytes: number;
  truncated: boolean;
  modified: number;
};

function size(bytes: number): string {
  return bytes < 1024 ? `${bytes} B` : `${Math.round(bytes / 1024)} KB`;
}

/**
 * How a rendered document is styled.
 *
 * Written out rather than pulled in as `@tailwindcss/typography`. The plugin is a build-time
 * dependency and a set of defaults tuned for marketing pages; this is twenty lines that match the
 * console's own type scale, and it is the only place a heading size is decided.
 */
const md = {
  h1: (p: object) => <h1 className="mb-3 mt-6 text-[20px] font-[650] first:mt-0" {...p} />,
  h2: (p: object) => <h2 className="mb-2 mt-6 text-[16px] font-[650]" {...p} />,
  h3: (p: object) => (
    <h3 className="mb-2 mt-5 text-[13px] font-[650] uppercase tracking-wide text-subtle" {...p} />
  ),
  p: (p: object) => <p className="my-3 text-[14px] leading-[1.65]" {...p} />,
  ul: (p: object) => <ul className="my-3 list-disc pl-5 text-[14px] leading-[1.65]" {...p} />,
  ol: (p: object) => <ol className="my-3 list-decimal pl-5 text-[14px] leading-[1.65]" {...p} />,
  li: (p: object) => <li className="my-1" {...p} />,
  blockquote: (p: object) => (
    <blockquote className="my-3 border-l-2 border-line pl-3 text-[14px] italic text-subtle" {...p} />
  ),
  code: (p: object) => (
    <code className="wrap-any rounded bg-black/5 px-1 py-[1px] font-mono text-[12.5px]" {...p} />
  ),
  // A fenced block is a `<pre>` wrapping the `<code>` above, and it is the one thing on the page
  // that is allowed to scroll sideways: wrapping a shell command changes what it says.
  pre: (p: object) => (
    <pre className="my-3 overflow-x-auto rounded bg-black/5 p-3 font-mono text-[12.5px]" {...p} />
  ),
  // Tables are why `remark-gfm` is here. They also overflow on a phone, so each one gets its own
  // horizontal scroller rather than pushing the page sideways.
  table: (p: object) => (
    <div className="my-3 overflow-x-auto">
      <table className="w-full border-collapse text-[13px]" {...p} />
    </div>
  ),
  th: (p: object) => (
    <th className="border border-line px-2 py-1 text-left font-[650] align-top" {...p} />
  ),
  td: (p: object) => <td className="border border-line px-2 py-1 align-top" {...p} />,
  hr: () => <hr className="my-5 border-0 border-t border-line" />,
};

export default function Docs() {
  // `?open=incidents/INC-....json` opens that document directly. The Incidents page links here
  // that way, and a link that lands on the right page and then does nothing is the same
  // "built and unreachable" defect as having no page at all.
  //
  // Derived, not copied into state by an effect. The query string is empty on the first render
  // and arrives at hydration, so an effect is the obvious way to do this and is also the one
  // eslint refuses. `undefined` means "nobody has clicked yet, the URL decides"; `null` means
  // the operator closed it and the URL must not reopen it.
  const router = useRouter();
  const fromUrl = typeof router.query.open === 'string' ? router.query.open : null;
  const [picked, setPicked] = useState<string | null | undefined>(undefined);
  const open = picked === undefined ? fromUrl : picked;
  const setOpen = setPicked;

  const [q, setQ] = useState('');
  const [chip, setChip] = useState<string | null>(null);
  const [source, setSource] = useState(false);

  // pollMs: 0 on both. See the docblock — a document does not change every thirty seconds, and
  // each poll is a fresh Python process.
  const index = useOps<DocsIndex>('docs', {}, { pollMs: 0 });
  // The second read is skipped until something is selected — `useOps` takes a null view for
  // exactly this, so opening the page costs one gateway call rather than two.
  const doc = useOps<DocText>(open ? 'docs' : null, open ? { name: open } : {}, { pollMs: 0 });

  const sections = useMemo(() => index.data?.sections ?? [], [index.data]);

  // Filtering happens here, over data already in the browser. `needle` matches the document's own
  // heading AND its path, because an operator looking for a decision record knows one or the
  // other and rarely both.
  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return sections
      .filter((s) => !chip || s.label === chip)
      .map((s) => ({
        label: s.label,
        docs: (s.docs ?? []).filter(
          (d) =>
            !needle ||
            d.title.toLowerCase().includes(needle) ||
            d.name.toLowerCase().includes(needle),
        ),
      }))
      .filter((s) => s.docs.length > 0);
  }, [sections, q, chip]);

  const total = sections.reduce((n, s) => n + (s.docs?.length ?? 0), 0);
  const matched = shown.reduce((n, s) => n + s.docs.length, 0);
  const filtering = Boolean(q.trim() || chip);
  const isJson = (doc.data?.name ?? open ?? '').toLowerCase().endsWith('.json');

  return (
    <Shell
      title="Docs"
      intro="Every decision, incident and runbook in the repo. Read here, no checkout needed."
    >
      {index.error ? <Problem>{index.error}</Problem> : null}

      <Card
        title="Documents"
        right={
          <div className="flex items-center gap-2">
            <AsOf asOf={index.envelope?.as_of} tookMs={index.envelope?.took_ms} />
            <Button onClick={index.refresh}>Refresh</Button>
          </div>
        }
      >
        {index.loading && !index.data ? <Spinner what="the document index" /> : null}
        {index.data?.note ? <Note>{index.data.note}</Note> : null}
        {index.data && index.data.count === 0 && !index.data.note ? (
          <Empty>No readable documents under docs/.</Empty>
        ) : null}

        {total > 0 ? (
          <div className="mb-4">
            <input
              type="search"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={`Search ${total} documents by title or path`}
              aria-label="Search documents"
              className="w-full rounded border border-line bg-transparent px-3 py-2 text-[14px] outline-none focus:border-text"
            />
            <div className="mt-2 flex flex-wrap gap-1.5">
              <button
                type="button"
                onClick={() => setChip(null)}
                aria-pressed={chip === null}
                className={`tap rounded-full border px-2.5 py-[3px] text-[12px] ${
                  chip === null ? 'border-text font-[600] text-text' : 'border-line text-subtle'
                }`}
              >
                All {total}
              </button>
              {sections.map((s) => (
                <button
                  key={s.label}
                  type="button"
                  onClick={() => setChip(chip === s.label ? null : s.label)}
                  aria-pressed={chip === s.label}
                  title={s.label}
                  className={`tap rounded-full border px-2.5 py-[3px] text-[12px] ${
                    chip === s.label ? 'border-text font-[600] text-text' : 'border-line text-subtle'
                  }`}
                >
                  {s.label.split('—')[0].trim()} {s.docs?.length ?? 0}
                </button>
              ))}
            </div>
            {filtering ? (
              <p className="mt-2 text-[12px] text-subtle">
                {matched} of {total} shown
                {matched === 0 ? ' — nothing matches that.' : '.'}
              </p>
            ) : null}
          </div>
        ) : null}

        {shown.map((section) => (
          <div key={section.label} className="mb-5 last:mb-0">
            <h3 className="mb-2 text-[11px] uppercase tracking-wide text-subtle">
              {section.label}
            </h3>
            <ul className="m-0 list-none p-0">
              {section.docs.map((d) => (
                <li key={d.name} className="py-[3px]">
                  <button
                    type="button"
                    onClick={() => setOpen(d.name === open ? null : d.name)}
                    aria-expanded={d.name === open}
                    className={`tap wrap-any text-left text-[14px] underline-offset-2 hover:underline ${
                      d.name === open ? 'font-[600] text-text' : 'text-text'
                    }`}
                  >
                    {d.title}
                  </button>
                  <span className="ml-2 font-mono text-[12px] text-subtle">
                    {d.name} · {size(d.bytes)}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </Card>

      {open ? (
        <Card
          title={doc.data?.title ?? open}
          right={
            <div className="flex items-center gap-2">
              <AsOf asOf={doc.envelope?.as_of} tookMs={doc.envelope?.took_ms} />
              {isJson ? null : (
                <Button onClick={() => setSource((v) => !v)}>
                  {source ? 'Rendered' : 'Source'}
                </Button>
              )}
              <Button onClick={doc.refresh}>Refresh</Button>
            </div>
          }
        >
          {doc.error ? <Problem>{doc.error}</Problem> : null}
          {doc.loading && !doc.data ? <Spinner what={open} /> : null}
          {doc.data?.truncated ? (
            <Note>
              Showing the first {size(doc.data.text.length)} of {size(doc.data.bytes)}. The rest is
              in the repo at docs/{doc.data.name}.
            </Note>
          ) : null}
          {doc.data ? (
            <Scroll>
              {source || isJson ? (
                <pre className="m-0 whitespace-pre-wrap break-words font-mono text-[12.5px] leading-[1.6]">
                  {doc.data.text}
                </pre>
              ) : (
                <div className="wrap-any">
                  <ReactMarkdown remarkPlugins={[remarkGfm]} components={md}>
                    {doc.data.text}
                  </ReactMarkdown>
                </div>
              )}
            </Scroll>
          ) : null}
        </Card>
      ) : null}
    </Shell>
  );
}
