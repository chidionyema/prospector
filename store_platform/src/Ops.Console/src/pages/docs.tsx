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
 *  5. EVERY DOCUMENT IS SHAREABLE FROM HERE. `ShareDoc` below mints an expiring, revocable link
 *     for the document on screen. This paragraph used to read "What this is NOT yet: shareable",
 *     and it stayed true for a day after it stopped being the whole story: the token store and
 *     the sessionless route both shipped on 2026-08-19 as `/share`, and nothing joined them to
 *     the page where the operator is actually standing. Measured 2026-08-20 against the live
 *     store: 0 shares had ever been minted. Reading a path off this page and typing it into
 *     another one is a step nobody takes.
 */
import { useRouter } from 'next/router';
import { useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import Confirm from '@/components/Confirm';
import Shell from '@/components/Shell';
import { AsOf, Button, Card, Empty, Mono, Note, Problem, Scroll, Spinner } from '@/components/ui';
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

/**
 * A share link for the document on screen.
 *
 * Added 2026-08-20. The two halves of "expose every repo doc as a shareable link" both shipped on
 * 2026-08-19 and were never joined. This page could read 127 documents; `/share` could mint an
 * expiring, revocable link for any of 2,093 tracked files. Getting from one to the other meant
 * reading the path off this page and typing it into that one. Measured the same day, against the
 * live store: 0 shares had ever been minted. The founder checked and said the story was not done,
 * and he was right — a rail nobody can reach from where they are standing is not a rail.
 *
 * It mints through the SAME `share.create` action as `/share`, with the same preview-then-apply
 * gate, so what a link may cover is still decided in one place (`prospector/ops/share.py`). This
 * is a shorter walk to that fence, never a second one: a copy of the rule here would be a rule
 * that can disagree with itself.
 */
function ShareDoc({ name }: { name: string }) {
  const [panel, setPanel] = useState(false);
  const [days, setDays] = useState(7);
  const [note, setNote] = useState('');
  /** Held only until the operator navigates away. The token is never re-readable. */
  const [minted, setMinted] = useState<{ url: string; expires: number } | null>(null);
  const [copied, setCopied] = useState(false);

  const target = `docs/${name}`;

  async function copy(url: string) {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
    } catch {
      // Clipboard access is refused outside a secure context and in some browsers. The link is on
      // screen and selectable, so this is a missing convenience, never a lost token.
      setCopied(false);
    }
  }

  if (!panel) {
    return (
      <div className="mb-3">
        <Button onClick={() => setPanel(true)}>Share this doc</Button>
      </div>
    );
  }

  return (
    <div className="mb-3 rounded-sm border border-line px-3 py-3">
      <div className="text-[13px] font-[560]">
        A link to <Mono>{target}</Mono> that anyone can open without a login.
      </div>
      <div className="mt-2 flex flex-wrap gap-3">
        <label className="flex flex-col gap-1 text-[13px]">
          <span className="text-subtle">Days until it expires</span>
          <input
            type="number"
            min={1}
            max={90}
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="tap w-28 rounded-sm border border-border-control bg-surface px-2 py-2 text-[16px]"
          />
        </label>
        <label className="flex flex-1 flex-col gap-1 text-[13px]">
          <span className="text-subtle">Who is it for (recorded, not shown to them)</span>
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="architecture review"
            className="tap rounded-sm border border-border-control bg-surface px-2 py-2 text-[16px]"
          />
        </label>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Confirm
          action="share.create"
          label="Check what this covers"
          kind="primary"
          applyLabel="Mint the link"
          payload={() => ({ scope: 'file', target, days, note })}
          renderPreview={(p) => (
            <div className="flex flex-col gap-2">
              <div>
                <strong>{String(p.covers)}</strong> file, readable by anyone holding the link for{' '}
                {String(p.days)} days.
              </div>
              <div className="text-[12px] text-muted">{String(p.note ?? '')}</div>
            </div>
          )}
          onApplied={(receipt) => {
            setCopied(false);
            setMinted({
              url: `${window.location.origin}${String(receipt.path ?? '')}`,
              expires: Number(receipt.expires_at ?? 0),
            });
          }}
        />
        <Button onClick={() => setPanel(false)}>Close</Button>
      </div>
      {minted ? (
        <div className="mt-3 rounded-sm border border-ok/40 bg-ok-bg px-3 py-3">
          <div className="text-[13px] font-[560] text-ok-strong">
            Copy this now. It is not stored and cannot be shown again.
          </div>
          <div className="wrap-any mt-2 font-mono text-[12.5px]">{minted.url}</div>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Button onClick={() => copy(minted.url)}>{copied ? 'Copied' : 'Copy link'}</Button>
            <span className="text-[12px] text-muted">
              expires {minted.expires ? new Date(minted.expires * 1000).toLocaleString() : '—'}
            </span>
            <a className="text-[12px] underline" href="/share">
              Manage or revoke it on Share
            </a>
          </div>
        </div>
      ) : null}
    </div>
  );
}

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
          {doc.data ? <ShareDoc name={doc.data.name} /> : null}
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
