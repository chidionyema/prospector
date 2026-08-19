/**
 * A shared file, or a shared tree, for someone with no account.
 *
 * Deliberately NOT wrapped in the console `Shell`, and deliberately NOT reading through
 * `useOps`. The Shell carries the operator navigation — money, spend, the daemon controls — and
 * rendering it around a public page would show an outsider the shape of the estate and hand them
 * links that all 401. `useOps` calls the authed read door, which is exactly the door this page
 * does not have a key to.
 *
 * That makes this the one page in the console that fetches for itself, so `tests/pages.test.ts`
 * excludes it from the operator-screen guards and `tests/share.test.ts` pins the exclusion narrow:
 * no Shell, no ops client, and exactly one URL — its own.
 *
 * Nothing here decides what may be seen. Scope, expiry, revocation and the deny-list all live in
 * `prospector.ops.share.open_share`.
 */
import Head from 'next/head';
import { useRouter } from 'next/router';
import { useEffect, useState } from 'react';

type FileRow = { name: string; label: string; bytes: number };

type Shared =
  | {
      kind: 'index';
      scope: string;
      target: string;
      files: string[];
      count: number;
      folders: { path: string; count: number; bytes: number; files: FileRow[] }[];
      total_bytes: number;
      revision: string;
      source: string;
      generated_at: number;
      note: string;
      expires_at: number;
    }
  | {
      kind: 'file';
      name: string;
      text: string;
      bytes: number;
      truncated: boolean;
      scope: string;
      target: string;
      note: string;
      expires_at: number;
    }
  | {
      kind: 'binary';
      name: string;
      bytes: number;
      scope: string;
      target: string;
      note: string;
      expires_at: number;
    };

function size(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function expiry(at: number): string {
  const days = Math.max(0, Math.round((at * 1000 - Date.now()) / 86_400_000));
  return days <= 1 ? 'expires within a day' : `expires in ${days} days`;
}

export default function SharedPage() {
  const router = useRouter();
  const token = typeof router.query.token === 'string' ? router.query.token : '';
  const name = typeof router.query.name === 'string' ? router.query.name : '';

  /**
   * ONE piece of state, stamped with the request it answers, exactly as `useOps` does it.
   *
   * The obvious shape — a `loading` flag set at the top of the effect — calls setState
   * synchronously inside an effect body, which cascades a render and is what
   * `react-hooks/set-state-in-effect` refuses. Derived from the stamp it costs nothing and cannot
   * disagree with the data beside it.
   */
  const [result, setResult] = useState<{
    key: string;
    data: Shared | null;
    error: string | null;
  } | null>(null);

  const key = `${token}|${name}`;
  const loading = token !== '' && result?.key !== key;
  const data = result?.key === key ? result.data : null;
  const error = result?.key === key ? result.error : null;

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    const url = `/api/s/${encodeURIComponent(token)}${name ? `?name=${encodeURIComponent(name)}` : ''}`;
    fetch(url)
      .then(async (r) => {
        const body = await r.json();
        if (cancelled) return;
        if (r.ok) setResult({ key, data: body as Shared, error: null });
        else setResult({ key, data: null, error: String(body?.error || 'This link is not valid.') });
      })
      .catch(() => {
        if (!cancelled) {
          setResult({ key, data: null, error: 'This link could not be opened. Try again shortly.' });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [token, name, key]);

  const title = data ? (data.kind === 'index' ? data.target || 'Shared files' : data.name) : 'Shared';

  return (
    <>
      <Head>
        <title>{title}</title>
        <meta name="robots" content="noindex, nofollow" />
      </Head>
      <main className="mx-auto min-h-screen max-w-5xl px-5 py-8">
        <header className="mb-6 border-b border-border pb-4">
          <p className="m-0 text-[11px] uppercase tracking-[0.14em] text-subtle">
            Shared, read only
          </p>
          <h1 className="wrap-any m-0 mt-1 font-mono text-[18px] font-[600]">{title}</h1>
          {data ? (
            <p className="m-0 mt-2 text-[12px] text-muted">
              {expiry(data.expires_at)}
              {data.note ? ` — ${data.note}` : ''}
            </p>
          ) : null}
        </header>

        {loading ? <p className="text-[13px] text-muted">Loading…</p> : null}

        {error ? (
          <div className="wrap-any rounded-sm border border-warn/40 bg-warn-bg px-3 py-3 text-[13px] text-warn-strong">
            {error}
          </div>
        ) : null}

        {/*
          The index, grouped by folder. A flat list of ~1,800 paths is not a view of a repo, it is
          a wall, so each folder carries its own count and size and the reader can skim the shape
          of the tree before opening anything.

          READ THE LINE UNDER THE COUNT. This listing is computed from the working tree on every
          single request, so the page a reader reloads tomorrow is tomorrow's repo. Nothing is
          generated, nothing is cached, and there is no job that can stop and leave it lying.
        */}
        {data?.kind === 'index' ? (
          <>
            <p className="mb-1 text-[13px] text-muted">
              {data.count} file{data.count === 1 ? '' : 's'} in {data.folders.length} folder
              {data.folders.length === 1 ? '' : 's'}, {size(data.total_bytes)}. Nothing outside this
              list can be reached through this link.
            </p>
            <p className="mb-5 text-[12px] text-subtle">
              Read from the repository just now
              {data.revision ? ` at ${data.revision}` : ''}, listed by {data.source}. Reload for the
              current state — this page is never a snapshot.
            </p>
            {data.folders.map((folder) => (
              <section key={folder.path || '(root)'} className="mb-5">
                <h2 className="m-0 mb-1 flex flex-wrap items-baseline gap-2 border-b border-border pb-1">
                  <span className="wrap-any font-mono text-[13px] font-[600]">
                    {folder.path || '(repository root)'}
                  </span>
                  <span className="text-[11.5px] font-[400] text-subtle">
                    {folder.count} file{folder.count === 1 ? '' : 's'} · {size(folder.bytes)}
                  </span>
                </h2>
                <ul className="m-0 list-none p-0">
                  {folder.files.map((f) => (
                    <li key={f.name} className="flex flex-wrap items-baseline gap-2 py-[3px]">
                      <a
                        href={`/s/${encodeURIComponent(token)}?name=${encodeURIComponent(f.name)}`}
                        className="wrap-any font-mono text-[13px] underline-offset-2 hover:underline"
                      >
                        {f.label}
                      </a>
                      <span className="text-[11.5px] text-subtle">{size(f.bytes)}</span>
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </>
        ) : null}

        {data?.kind === 'file' ? (
          <>
            {data.truncated ? (
              <p className="mb-3 rounded-sm border border-warn/40 bg-warn-bg px-3 py-2 text-[12px] text-warn-strong">
                Shown from the top only — the whole file is {data.bytes.toLocaleString()} bytes.
              </p>
            ) : null}
            <div className="scroll-x">
              <pre className="m-0 whitespace-pre-wrap break-words font-mono text-[12.5px] leading-[1.6]">
                {data.text}
              </pre>
            </div>
          </>
        ) : null}

        {data?.kind === 'binary' ? (
          <p className="rounded-sm border border-border bg-surface2 px-3 py-3 text-[13px] text-muted">
            This is a binary file ({data.bytes.toLocaleString()} bytes), so it is listed and not
            rendered.
          </p>
        ) : null}

        {data && data.kind !== 'index' && (data.scope === 'tree' || data.scope === 'repo') ? (
          <p className="mt-6 text-[13px]">
            <a href={`/s/${encodeURIComponent(token)}`} className="underline underline-offset-2">
              ← all shared files
            </a>
          </p>
        ) : null}
      </main>
    </>
  );
}
