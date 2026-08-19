/**
 * Docs — the decisions, incidents and runbooks, readable without a checkout.
 *
 * Why this page exists. On 2026-08-19 the founder asked twice whether the stack documents were
 * reachable from ops. They were not: no page rendered markdown, no API route read `docs/`, and
 * the console had no markdown dependency at all. So a decision record could be written, committed
 * and pushed, and still be readable only by someone at a terminal with a clone. That is the
 * "built and unreachable" failure this estate keeps hitting.
 *
 * What this is NOT yet: shareable. A link a non-operator can open, that expires and can be
 * revoked, needs a token store and a route that answers without a session. Tracked separately.
 * Everything here sits behind the console's own auth, exactly like every other page.
 *
 * Rendering is deliberately plain text rather than parsed markdown. The console has no markdown
 * dependency, and adding one in order to ship a reader is the scope creep that turns a same-day
 * answer into a week. Monospace with the source visible is honest and complete; a prettier
 * renderer is a later commit that touches only this file.
 */
import { useState } from 'react';

import Shell from '@/components/Shell';
import { AsOf, Card, Empty, Note, Problem, Scroll, Spinner } from '@/components/ui';
import { useOps } from '@/lib/useOps';

type DocEntry = { name: string; title: string; bytes: number; modified: number };
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

export default function Docs() {
  const [open, setOpen] = useState<string | null>(null);

  const index = useOps<DocsIndex>('docs');
  // The second read is skipped until something is selected — `useOps` takes a null view for
  // exactly this, so opening the page costs one gateway call rather than two.
  const doc = useOps<DocText>(open ? 'docs' : null, open ? { name: open } : {});

  return (
    <Shell
      title="Docs"
      intro="Every decision, incident and runbook in the repo. Read here, no checkout needed."
    >
      {index.error ? <Problem>{index.error}</Problem> : null}

      <Card
        title="Documents"
        right={<AsOf asOf={index.envelope?.as_of} tookMs={index.envelope?.took_ms} />}
      >
        {index.loading && !index.data ? <Spinner what="the document index" /> : null}
        {index.data?.note ? <Note>{index.data.note}</Note> : null}
        {index.data && index.data.count === 0 && !index.data.note ? (
          <Empty>No readable documents under docs/.</Empty>
        ) : null}

        {(index.data?.sections ?? []).map((section) => (
          <div key={section.label} className="mb-5 last:mb-0">
            <h3 className="mb-2 text-[11px] uppercase tracking-wide text-subtle">
              {section.label}
            </h3>
            <ul className="m-0 list-none p-0">
              {(section.docs ?? []).map((d) => (
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
          right={<AsOf asOf={doc.envelope?.as_of} tookMs={doc.envelope?.took_ms} />}
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
              <pre className="m-0 whitespace-pre-wrap break-words font-mono text-[12.5px] leading-[1.6]">
                {doc.data.text}
              </pre>
            </Scroll>
          ) : null}
        </Card>
      ) : null}
    </Shell>
  );
}
