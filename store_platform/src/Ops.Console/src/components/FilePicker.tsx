/**
 * Pick a file or a folder out of this repo, instead of typing its path from memory.
 *
 * The founder, 2026-08-20, on the share flow: "there is a path output but the whole thing isnt
 * user friendly", and on what it has to cover: "any new file, whether code, doc etc". A free-text
 * box fails both. You cannot type a path you do not remember, and a typo returns an error rather
 * than a link.
 *
 * The odd part of the defect this fixes: the folder browser already existed. `share.folder_view`
 * is what the OUTSIDE reader gets when they open one of these links. The operator minting the
 * link was the one person in the exchange who never saw it.
 *
 * NEW FILES NEED NO ACTION. The list behind this is recomputed from `git ls-files` on every read,
 * with the deny-list applied -- nothing is cached and nothing is generated. A file committed a
 * minute ago is in the next page load, and a file that is never shareable is never in the list.
 */
import { useMemo, useState } from 'react';

import { Empty, Mono, Note, Pill, Spinner } from '@/components/ui';
import { useOps } from '@/lib/useOps';

type Folder = {
  path: string;
  count: number;
  bytes: number;
  files: { name: string; label: string; bytes: number }[];
};

/** One row in the list: a file or a folder, reduced to what the picker draws. */
type Pick = { path: string; label: string; bytes: number; count?: number };

export type RepoFiles = {
  folders: Folder[];
  total_bytes: number;
  revision: string;
  source: string;
};

/** Bytes, in the shortest form that is still honest. */
export function size(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** How many matches we will draw. A repo-wide list is thousands of rows and no help to anyone. */
const SHOWN = 60;

export default function FilePicker({
  scope,
  value,
  onPick,
}: {
  scope: 'file' | 'tree';
  value: string;
  onPick: (path: string) => void;
}) {
  const [q, setQ] = useState('');
  const { data, error, loading } = useOps<RepoFiles>('repo_files', {}, { pollMs: 0 });

  const all = useMemo<Pick[]>(() => {
    if (!data) return [];
    if (scope === 'tree') {
      return data.folders
        .filter((f) => f.path)
        .map((f) => ({ path: f.path, label: f.path, bytes: f.bytes, count: f.count }));
    }
    return data.folders.flatMap((f) =>
      f.files.map((x) => ({ path: x.name, label: x.name, bytes: x.bytes })),
    );
  }, [data, scope]);

  const hits = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return all.slice(0, SHOWN);
    // Every space-separated word must appear. "arch sec md" finds
    // docs/ARCHITECTURE_SECURITY_BASELINE.md without anyone recalling its capitalisation.
    const words = needle.split(/\s+/);
    return all.filter((x) => words.every((w) => x.path.toLowerCase().includes(w))).slice(0, SHOWN);
  }, [all, q]);

  const total = all.length;

  return (
    <div className="flex flex-col gap-2">
      <label className="flex flex-col gap-1 text-[13px]">
        <span className="text-subtle">
          {scope === 'file' ? 'Which file' : 'Which folder'} — type any part of the name
        </span>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={scope === 'file' ? 'manifesto  /  console_api  /  .yml' : 'docs'}
          spellCheck={false}
          className="tap rounded-sm border border-border-control bg-surface px-2 py-2 font-mono text-[16px]"
        />
      </label>

      {error ? <Note>could not list the repo: {error}</Note> : null}
      {loading && !data ? <Spinner what="the file list" /> : null}

      {data ? (
        <div className="max-h-72 overflow-y-auto rounded-sm border border-border-control">
          {hits.length === 0 ? (
            <Empty>nothing matches that</Empty>
          ) : (
            hits.map((x) => (
              <button
                key={x.path}
                type="button"
                onClick={() => onPick(x.path)}
                className="tap flex w-full items-center justify-between gap-3 border-b border-border-control px-2 py-2 text-left last:border-b-0"
              >
                <span className="wrap-any font-mono text-[13px]">
                  {x.path === value ? '✓ ' : ''}
                  {x.label}
                </span>
                <span className="shrink-0 text-[12px] text-muted">
                  {x.count !== undefined ? `${x.count} files · ` : ''}
                  {size(x.bytes)}
                </span>
              </button>
            ))
          )}
        </div>
      ) : null}

      {data ? (
        <div className="text-[12px] text-muted">
          {hits.length < total ? (
            <>
              showing {hits.length} of {total} {scope === 'file' ? 'files' : 'folders'} — keep
              typing to narrow it
            </>
          ) : (
            <>
              {total} {scope === 'file' ? 'files' : 'folders'}
            </>
          )}{' '}
          · listed by <Mono>{data.source}</Mono>, recomputed every time this page loads
        </div>
      ) : null}

      {value ? (
        <div className="flex flex-wrap items-center gap-2 text-[13px]">
          <Pill tone="ok">chosen</Pill>
          <Mono>{value}</Mono>
        </div>
      ) : null}
    </div>
  );
}
