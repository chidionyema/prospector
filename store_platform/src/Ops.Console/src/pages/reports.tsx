/**
 * Reports — every sheet and sample that has been published, and who can see each one.
 *
 * Why this page exists. The founder asked three times for the same thing and did not get it:
 * "i also want a page where i ccan view all sanples generated so far", "and updated as we go
 * along", and then "i cant pi cannt preview what else what produced". The links were not lost —
 * `docs/LINKS.md` has held them since 2026-08-18 — but a file is not a gallery. Measured
 * 2026-08-20: the docs index carries 128 documents, so LINKS.md is one row in a list of 128, and
 * finding it means already knowing it exists. That is the estate's recurring "built and
 * unreachable" failure, one level up: built, linked, and still not findable.
 *
 * WHERE THE CONTENT COMES FROM, AND WHY IT IS NOT A SECOND LIST. This page holds no list of its
 * own. It reads `docs/LINKS.md` through the same `docs` read the Docs page uses and parses the
 * tables out of it. So the gallery updates when LINKS.md updates, which is the rule that file
 * already carries: "When you publish a page, add the line here in the same commit." A hand-kept
 * second copy would drift, and a drifted index of shareable links is worse than none — it is a
 * page that confidently omits things.
 *
 * TWO KINDS OF LINK, AND THEY ARE NOT THE SAME KIND. This is the distinction the page exists to
 * make legible, because getting it wrong means believing something is private when it is not:
 *
 *   1. THE PUBLISHED PAGE is hosted on claude.ai. Whether a stranger can open it is decided in
 *      the artifact's own share menu, NOT here. This console cannot revoke one, and this page
 *      never implies otherwise — it says "opens on claude.ai" and leaves it at that.
 *   2. THE SOURCE FILE in this repo is shareable through our own token store, and that one we do
 *      control: `share.create` mints an expiring link, `share.revoke` kills it. The founder's
 *      words when asking for this page: "recall the links can be turned on/off fron being
 *      publically share". That is the second column, and it is a real on/off switch.
 *
 * Every row joins the two by the source path LINKS.md already records in its third column, so the
 * join is data the estate keeps, not a mapping invented here.
 *
 * NO POLLING. Both reads are `pollMs: 0` behind a Refresh button, for the reason `docs.tsx`
 * gives: every poll is a fresh Python process, and published documents change when someone
 * deploys, not every thirty seconds.
 */
import { useMemo, useState } from 'react';

import Confirm from '@/components/Confirm';
import Shell from '@/components/Shell';
import { AsOf, Button, Card, Empty, Mono, Note, Pill, Problem, Spinner } from '@/components/ui';
import { useOps } from '@/lib/useOps';

type DocText = { name: string; text: string };

type ShareRow = {
  id: string;
  scope: string;
  target: string;
  note: string;
  created_at: number;
  expires_at: number;
  reads: number;
  status: 'live' | 'expired' | 'revoked';
};
type Shares = { shares: ShareRow[]; default_days: number; max_days: number };

type Sheet = {
  section: string;
  title: string;
  url: string;
  /** The repo file the page was rendered from, when LINKS.md records one. */
  source: string | null;
  /** LINKS.md's own one-line "what it decided", where the table carries one. */
  note: string | null;
};

/**
 * Pull the published pages out of LINKS.md.
 *
 * The file is markdown tables under `## ` headings, and every row that matters holds a cell like
 * `[title](https://claude.ai/code/artifact/<id>)` plus, usually, a backticked source path. Rows
 * are matched on the ARTIFACT URL rather than on position, because the tables do not all have the
 * same columns and a positional parser would silently drop the ones that differ.
 *
 * A link whose text is the word "link" carries no title of its own — those tables put the name in
 * the first cell instead — so the first cell is the fallback.
 *
 * The remaining cell, where there is one, is LINKS.md's own "what it decided" line. It is carried
 * through rather than dropped, because a gallery of forty-four titles with no descriptions is the
 * problem this page was asked to solve, not a smaller version of it.
 */
export function parseSheets(markdown: string): Sheet[] {
  const out: Sheet[] = [];
  const seen = new Set<string>();
  let section = 'Published';
  for (const line of markdown.split('\n')) {
    const heading = /^##\s+(.*\S)/.exec(line);
    if (heading) {
      section = heading[1];
      continue;
    }
    if (!line.startsWith('|')) continue;
    const cells = line.split('|').map((c) => c.trim());
    const linkCell = cells.find((c) => /\]\(https:\/\/claude\.ai\/code\/artifact\//.test(c));
    if (!linkCell) continue;
    const link = /\[([^\]]*)\]\((https:\/\/claude\.ai\/code\/artifact\/[^)\s]+)\)/.exec(linkCell);
    if (!link) continue;
    const [, text, url] = link;
    if (seen.has(url)) continue;
    seen.add(url);
    const first = cells.find((c) => c.length > 0) ?? '';
    const bare = text.trim().toLowerCase();
    const title = bare && bare !== 'link' ? text.trim() : first.replace(/[*`]/g, '').trim();
    const path = cells.map((c) => /^`([^`]+)`$/.exec(c)).find(Boolean);
    const rest = cells
      .filter((c) => c && c !== linkCell && c !== first && !/^`[^`]+`$/.test(c))
      .sort((a, b) => b.length - a.length);
    out.push({
      section,
      title: title || 'Untitled',
      url,
      source: path ? path[1] : null,
      note: rest.length ? rest[0].replace(/\*\*|`/g, '') : null,
    });
  }
  return out;
}

function when(at: number | null): string {
  if (!at) return '—';
  return new Date(at * 1000).toLocaleDateString();
}

/** The one live share for a path, if there is one. Expired and revoked rows are history. */
function liveShare(rows: ShareRow[], source: string | null): ShareRow | null {
  if (!source) return null;
  return rows.find((r) => r.status === 'live' && r.scope === 'file' && r.target === source) ?? null;
}

export default function Reports() {
  const [q, setQ] = useState('');

  const index = useOps<DocText>('docs', { name: 'LINKS.md' }, { pollMs: 0 });
  const shares = useOps<Shares>('shares', {}, { pollMs: 0 });

  const sheets = useMemo(() => parseSheets(index.data?.text ?? ''), [index.data?.text]);
  const rows = shares.data?.shares ?? [];
  const days = shares.data?.default_days ?? 7;

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return sheets;
    return sheets.filter((s) =>
      `${s.title} ${s.section} ${s.source ?? ''}`.toLowerCase().includes(needle),
    );
  }, [sheets, q]);

  const sections = useMemo(() => {
    const by = new Map<string, Sheet[]>();
    for (const s of shown) by.set(s.section, [...(by.get(s.section) ?? []), s]);
    return [...by.entries()];
  }, [shown]);

  const sharedNow = rows.filter((r) => r.status === 'live').length;
  // Said once, at the top. It used to be said on every row that had no source file, which on the
  // real LINKS.md is 21 of 44 — the same sentence twenty-one times, pushing the sheets apart.
  const noFile = sheets.filter((s) => !s.source).length;

  return (
    <Shell
      title="Reports"
      intro="Every sheet and sample that has been published, and whether the file behind it is shared outside."
    >
      {index.error ? <Problem>{index.error}</Problem> : null}
      {shares.error ? <Problem>{shares.error}</Problem> : null}

      <Card
        title="Published sheets"
        right={
          <div className="flex items-center gap-2">
            <AsOf asOf={index.envelope?.as_of} tookMs={index.envelope?.took_ms} />
            <Button
              onClick={() => {
                index.refresh();
                shares.refresh();
              }}
            >
              Refresh
            </Button>
          </div>
        }
      >
        {index.loading && !index.data ? <Spinner what="the published pages" /> : null}

        {index.data ? (
          <Note>
            {sheets.length} published from <Mono>docs/LINKS.md</Mono>, {sharedNow} repo file
            {sharedNow === 1 ? '' : 's'} shared outside right now. A sheet opens on claude.ai and is
            made public from its own share menu — this console cannot revoke one. The file it was
            written from is a different link, and that one has an off switch under it.{' '}
            {noFile > 0
              ? `${noFile} of the ${sheets.length} were written straight to claude.ai and have no repo file behind them, so those carry no switch.`
              : ''}
          </Note>
        ) : null}

        {index.data && sheets.length > 0 ? (
          <label className="mt-3 flex flex-col gap-1 text-[13px]">
            <span className="text-subtle">Find a sheet</span>
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="assay, samples, cost"
              spellCheck={false}
              className="tap rounded-sm border border-border-control bg-surface px-2 py-2 text-[16px]"
            />
          </label>
        ) : null}

        {index.data && sheets.length === 0 ? (
          <Empty>
            No published pages found in <Mono>docs/LINKS.md</Mono>.
          </Empty>
        ) : null}
        {index.data && sheets.length > 0 && shown.length === 0 ? (
          <Empty>Nothing matches “{q}”.</Empty>
        ) : null}

        {sections.map(([name, items]) => (
          <section key={name} className="mt-4">
            <h2 className="text-[13px] font-[560] text-subtle">
              {name} <span className="text-muted">· {items.length}</span>
            </h2>
            <ul className="m-0 mt-1 list-none p-0">
              {items.map((s) => {
                const live = liveShare(rows, s.source);
                return (
                  <li key={s.url} className="border-b border-border py-3 last:border-b-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <a
                        href={s.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-[14px] font-[560] underline decoration-border underline-offset-2"
                      >
                        {s.title}
                      </a>
                      <span className="text-[12px] text-muted">opens on claude.ai</span>
                      {live ? <Pill tone="ok">file shared</Pill> : null}
                    </div>

                    {s.note ? <div className="mt-1 text-[13px] text-muted">{s.note}</div> : null}

                    {s.source ? (
                      <div className="mt-1 flex flex-wrap items-center gap-2">
                        <span className="wrap-any font-mono text-[12px] text-muted">
                          {s.source}
                        </span>
                        {live ? (
                          <span className="text-[12px] text-muted">
                            link live until {when(live.expires_at)} · {live.reads} read
                            {live.reads === 1 ? '' : 's'}
                          </span>
                        ) : null}
                      </div>
                    ) : null}

                    {s.source ? (
                      <div className="mt-2">
                        {live ? (
                          <Confirm
                            action="share.revoke"
                            label="Turn the file link off"
                            kind="danger"
                            applyLabel="Yes, kill this link"
                            payload={() => ({ id: live.id })}
                            renderPreview={(p) => (
                              <div>
                                <div className="font-mono text-[12.5px]">
                                  {String(p.target) || '(repo)'}
                                </div>
                                <div className="mt-1 text-[12px] text-muted">
                                  Anyone holding this link stops being able to read the file. The
                                  page on claude.ai is not affected.
                                </div>
                              </div>
                            )}
                            onApplied={() => shares.refresh()}
                          />
                        ) : (
                          <Confirm
                            action="share.create"
                            label="Share the file"
                            applyLabel="Mint the link"
                            payload={() => ({
                              scope: 'file',
                              target: s.source,
                              days,
                              note: `report: ${s.title}`,
                            })}
                            renderPreview={(p) => (
                              <div>
                                <div>
                                  <strong>{String(p.covers)}</strong> file, readable by anyone with
                                  the link for {String(p.days)} days.
                                </div>
                                <div className="mt-1 font-mono text-[12px] text-muted">
                                  {s.source}
                                </div>
                              </div>
                            )}
                            onApplied={() => shares.refresh()}
                          />
                        )}
                      </div>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
      </Card>

      <Card title="Every link you have given out">
        {shares.loading && !shares.data ? <Spinner what="the links" /> : null}
        {shares.data && rows.length === 0 ? (
          <Empty>No links have been minted. Nothing in this repo is readable from outside.</Empty>
        ) : null}
        {rows.length > 0 ? (
          <Note>
            The full history, including links that have expired or been killed. Minting a new one
            for a folder or the whole repo is on <Mono>/share</Mono>.
          </Note>
        ) : null}
        <ul className="m-0 list-none p-0">
          {rows.map((r) => (
            <li key={r.id} className="border-b border-border py-2 last:border-b-0">
              <div className="flex flex-wrap items-center gap-2">
                <Pill tone={r.status === 'live' ? 'ok' : r.status === 'expired' ? 'warn' : 'bad'}>
                  {r.status}
                </Pill>
                <span className="wrap-any font-mono text-[12.5px]">
                  {r.scope === 'repo' ? 'the whole repo' : r.target}
                </span>
              </div>
              <div className="mt-1 text-[12px] text-muted">
                {r.note ? `${r.note} · ` : ''}minted {when(r.created_at)} · expires{' '}
                {when(r.expires_at)} · {r.reads} read{r.reads === 1 ? '' : 's'}
              </div>
            </li>
          ))}
        </ul>
      </Card>
    </Shell>
  );
}
