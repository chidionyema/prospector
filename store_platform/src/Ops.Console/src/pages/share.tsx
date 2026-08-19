/**
 * Share — hand a file, a folder, or the whole repo to someone with no account.
 *
 * Why this page exists. The founder asked whether every file in the repo could be made shareable
 * from ops: "would nake eternal consulationo a breeze", "i can share with claude web nonre
 * easily". Until now the only way to show an outsider a file was to paste it, which loses the
 * path, the neighbours and the ability to take it back.
 *
 * The link is the credential, so three things about it matter more than the form around them:
 *
 *   1. The TOKEN IS SHOWN ONCE. Only its SHA-256 is stored, so a leaked share store is not a set
 *      of working links. If the operator loses it, the answer is to mint another and revoke this
 *      one, not to look it up.
 *   2. WHAT A LINK COVERS IS SHOWN BEFORE IT IS MINTED. A `repo` share and a `file` share look
 *      identical in a form and could not be less alike, so the preview counts the files and lists
 *      the first twenty of them.
 *   3. THE DENY-LIST IS THE FENCE, NOT THE TOKEN. `.env`, keys, `store/` and the rest are refused
 *      at mint time AND again at read time, because the point is not that a stranger cannot guess
 *      a token — it is that the operator cannot hand out a credential by accident.
 *
 * Every number on this page comes from `read shares`. Nothing here computes coverage itself.
 */
import { useState } from 'react';

import Confirm from '@/components/Confirm';
import Shell from '@/components/Shell';
import { AsOf, Button, Card, Empty, Mono, Note, Pill, Problem, Spinner } from '@/components/ui';
import { useOps } from '@/lib/useOps';

type ShareRow = {
  id: string;
  scope: string;
  target: string;
  note: string;
  actor: string;
  created_at: number;
  expires_at: number;
  revoked_at: number | null;
  reads: number;
  last_read_at: number | null;
  status: 'live' | 'expired' | 'revoked';
};

type Shares = {
  shares: ShareRow[];
  allow_list_source: string;
  shareable_count: number;
  scopes: string[];
  max_days: number;
  default_days: number;
};

function when(at: number | null): string {
  if (!at) return '—';
  return new Date(at * 1000).toLocaleString();
}

function tone(status: string): 'ok' | 'warn' | 'bad' | 'plain' {
  if (status === 'live') return 'ok';
  if (status === 'expired') return 'warn';
  return 'bad';
}

export default function Share() {
  const [scope, setScope] = useState('file');
  const [target, setTarget] = useState('');
  const [days, setDays] = useState(7);
  const [note, setNote] = useState('');
  /** The minted link, held only until the operator navigates away. It is never re-readable. */
  const [minted, setMinted] = useState<{ url: string; expires: number } | null>(null);
  const [copied, setCopied] = useState(false);

  const shares = useOps<Shares>('shares');
  const rows = shares.data?.shares ?? [];

  async function copy(url: string) {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
    } catch {
      // Clipboard access is refused outside a secure context and in some browsers. The link is
      // on screen and selectable, so this is a missing convenience, never a lost token.
      setCopied(false);
    }
  }

  return (
    <Shell
      title="Share"
      intro="Give someone outside the console a read-only link to a file, a folder, or the repo. It expires, and you can kill it."
    >
      {shares.error ? <Problem>{shares.error}</Problem> : null}

      <Card
        title="New link"
        right={<AsOf asOf={shares.envelope?.as_of} tookMs={shares.envelope?.took_ms} />}
      >
        {shares.loading && !shares.data ? <Spinner what="the share settings" /> : null}

        {shares.data ? (
          <Note>
            {shares.data.shareable_count} files can be shared, listed by{' '}
            {shares.data.allow_list_source}. Credentials, keys, <Mono>store/</Mono> and build
            output are refused whatever you type here.
          </Note>
        ) : null}

        <div className="flex flex-col gap-3">
          <label className="flex flex-col gap-1 text-[13px]">
            <span className="text-subtle">What</span>
            <select
              value={scope}
              onChange={(e) => setScope(e.target.value)}
              className="tap rounded-sm border border-border-control bg-surface px-2 py-2 text-[16px]"
            >
              <option value="file">One file</option>
              <option value="tree">A folder and everything under it</option>
              <option value="repo">The whole repo</option>
            </select>
          </label>

          {scope !== 'repo' ? (
            <label className="flex flex-col gap-1 text-[13px]">
              <span className="text-subtle">
                {scope === 'file' ? 'Path to the file' : 'Path to the folder'}
              </span>
              <input
                value={target}
                onChange={(e) => setTarget(e.target.value)}
                placeholder={scope === 'file' ? 'docs/PLATFORM_MANIFESTO.md' : 'docs'}
                spellCheck={false}
                className="tap rounded-sm border border-border-control bg-surface px-2 py-2 font-mono text-[16px]"
              />
            </label>
          ) : null}

          <div className="flex flex-wrap gap-3">
            <label className="flex flex-col gap-1 text-[13px]">
              <span className="text-subtle">Days until it expires</span>
              <input
                type="number"
                min={1}
                max={shares.data?.max_days ?? 90}
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

          <Confirm
            action="share.create"
            label="Check what this covers"
            kind="primary"
            applyLabel="Mint the link"
            disabled={scope !== 'repo' && !target.trim()}
            payload={() => ({ scope, target: scope === 'repo' ? '' : target.trim(), days, note })}
            renderPreview={(p) => {
              const sample = (p.sample as string[]) ?? [];
              return (
                <div className="flex flex-col gap-2">
                  <div>
                    <strong>{String(p.covers)}</strong> file{p.covers === 1 ? '' : 's'}, readable by
                    anyone with the link for {String(p.days)} days.
                  </div>
                  <div className="text-[12px] text-muted">{String(p.note ?? '')}</div>
                  <ul className="m-0 list-none p-0 font-mono text-[12px] text-muted">
                    {sample.map((f) => (
                      <li key={f} className="wrap-any">
                        {f}
                      </li>
                    ))}
                    {Number(p.covers) > sample.length ? (
                      <li>…and {Number(p.covers) - sample.length} more</li>
                    ) : null}
                  </ul>
                </div>
              );
            }}
            onApplied={(receipt) => {
              const path = String(receipt.path ?? '');
              setCopied(false);
              setMinted({
                url: `${window.location.origin}${path}`,
                expires: Number(receipt.expires_at ?? 0),
              });
              shares.refresh();
            }}
          />
        </div>

        {minted ? (
          <div className="mt-4 rounded-sm border border-ok/40 bg-ok-bg px-3 py-3">
            <div className="text-[13px] font-[560] text-ok-strong">
              Copy this now. It is not stored and cannot be shown again.
            </div>
            <div className="wrap-any mt-2 font-mono text-[12.5px]">{minted.url}</div>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <Button onClick={() => copy(minted.url)}>{copied ? 'Copied' : 'Copy link'}</Button>
              <span className="text-[12px] text-muted">expires {when(minted.expires)}</span>
            </div>
          </div>
        ) : null}
      </Card>

      <Card title="Links you have given out">
        {shares.loading && !shares.data ? <Spinner what="the links" /> : null}
        {shares.data && rows.length === 0 ? <Empty>No links have been minted.</Empty> : null}

        <ul className="m-0 list-none p-0">
          {rows.map((r) => (
            <li key={r.id} className="border-b border-border py-3 last:border-b-0">
              <div className="flex flex-wrap items-center gap-2">
                <Pill tone={tone(r.status)}>{r.status}</Pill>
                <span className="wrap-any font-mono text-[13px]">
                  {r.scope === 'repo' ? 'the whole repo' : r.target}
                </span>
                <span className="text-[12px] text-subtle">{r.scope}</span>
              </div>
              <div className="mt-1 text-[12px] text-muted">
                {r.note ? `${r.note} · ` : ''}minted {when(r.created_at)} · expires{' '}
                {when(r.expires_at)} · {r.reads} read{r.reads === 1 ? '' : 's'}
                {r.last_read_at ? `, last ${when(r.last_read_at)}` : ''}
              </div>
              {r.status === 'live' ? (
                <div className="mt-2">
                  <Confirm
                    action="share.revoke"
                    label="Revoke"
                    kind="danger"
                    applyLabel="Yes, kill this link"
                    payload={() => ({ id: r.id })}
                    renderPreview={(p) => (
                      <div>
                        <div className="font-mono text-[12.5px]">
                          {String(p.scope)} · {String(p.target) || '(repo)'}
                        </div>
                        <div className="mt-1 text-[12px] text-muted">{String(p.note ?? '')}</div>
                      </div>
                    )}
                    onApplied={() => shares.refresh()}
                  />
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      </Card>
    </Shell>
  );
}
