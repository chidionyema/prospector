import React from 'react';
import Link from 'next/link';
import { Icon } from '@/components/ui';
import { cx } from '@/components/ui/cx';
import report from '@/data/sample-report.json';

/*
  What the buyer is actually paying for, shown rather than described.

  The list above this says a pack contains a verification dossier. That is a noun, and the
  documented fear on a digital download page is paying £49 for a two-page Google Doc. So this
  shows the dossier itself: the real check names, the real verdicts, the real source domains
  from Report #00, the free sample. Nothing here is a mockup, it is the same JSON the /sample
  page renders in full, which is why one of the eight rows says the idea was pushed back.

  Keeping that row is the point. A preview showing eight green ticks would be a better advert
  and a worse claim, and the shop's whole pitch is that the checks can fail.
*/

type Source = { url: string; label: string };
type Check = { name: string; verdict: string; sources: Source[] };

const checks = report.checks as Check[];

function domainOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return '';
  }
}

export function DossierPreview() {
  return (
    <div className="mt-10 overflow-hidden rounded-2xl border border-border bg-surface">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-bg px-5 py-4 md:px-7">
        <div>
          <p className="font-mono text-[10px] font-bold uppercase tracking-widest text-primary">
            A real page from a real pack
          </p>
          <p className="mt-1 text-sm font-bold text-text">
            {report.title}, the verification dossier
          </p>
        </div>
        <span className="font-mono text-[11px] font-semibold text-muted">
          {report.supported} of {report.total} survived · {report.sourceCount} sources
        </span>
      </div>

      {/* Not a table: at phone width a table either scrolls sideways or crushes the check name,
          and the check name is the part that explains what was actually tested. */}
      <ul className="list-none divide-y divide-border/70 p-0">
        {checks.map((check, i) => {
          const supported = check.verdict === 'supported';
          const domain = domainOf(check.sources[0]?.url ?? '');
          return (
            <li key={i} className="flex flex-wrap items-center gap-x-4 gap-y-1.5 px-5 py-3 md:px-7">
              <span
                className={cx(
                  'flex h-5 w-5 flex-none items-center justify-center rounded-full',
                  supported ? 'bg-success/10 text-success' : 'bg-warning/10 text-warning',
                )}
                aria-hidden
              >
                <Icon name={supported ? 'check' : 'shield'} size={11} />
              </span>
              <span className="min-w-0 flex-1 text-sm font-medium text-text">{check.name}</span>
              <span
                className={cx(
                  'font-mono text-[11px] font-bold uppercase tracking-wide',
                  supported ? 'text-success' : 'text-warning',
                )}
              >
                {supported ? 'Survived' : 'Pushed back'}
              </span>
              {domain && (
                <span className="w-full font-mono text-[11px] text-muted md:w-auto md:min-w-[13rem] md:text-right">
                  {domain}
                </span>
              )}
            </li>
          );
        })}
      </ul>

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border bg-bg px-5 py-4 md:px-7">
        <p className="text-xs text-muted">
          Every source is a live link in the pack. This one is free to read in full.
        </p>
        <Link
          href="/sample"
          className="inline-flex items-center gap-2 text-sm font-bold text-primary underline underline-offset-4 transition-opacity hover:opacity-80"
        >
          Read a full pack free
          <Icon name="arrowRight" size={14} />
        </Link>
      </div>
    </div>
  );
}
