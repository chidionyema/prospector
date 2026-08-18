import React from 'react';
import Link from 'next/link';
import latestKill from '@/data/latest-kill.json';

/**
 * THE DARK STRIP, RIBBON VARIANT. Copied from the drawings' `<div class="strip ribbon">`
 * (`docs/design/mumchimp-build-bundle/mockups/index.html:5`, documented as component 02 in
 * `docs/design/mumchimp-build-bundle/components.html:541`).
 *
 * WHY IT EXISTS. It sits above the header on all eleven drawings and the app had no version of it
 * at all, so every built page rendered 44px higher than its drawing. Measured 2026-08-18 with
 * `scripts/visual_regression.mjs`: `/about` matched its drawing on height to within 17px and still
 * differed on 5.96% of pixels at 1280, because a whole-page vertical offset makes every glyph miss
 * its counterpart. It is the defect with the widest blast radius across the parity numbers.
 *
 * THE TAG SAYS THE DATE, NOT "TODAY". The drawing writes "Killed today", which is only true on the
 * day the kill log was generated. `src/data/latest-kill.json` is written by `tools/make_kill_log.py`
 * at build time, so on any other day that label would be a false claim about a dated fact, which is
 * the one thing this shop sells. The date is printed instead. Everything else is the drawing, class
 * for class.
 *
 * NO CLOCK IS READ. `new Date()` at render time gives one answer on the server and another in the
 * browser, and this element sits above the header, where a hydration correction moves the whole
 * page. The only date involved is the one in the data.
 */

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** "2026-08-07" becomes "Killed 7 Aug". An unparseable date falls back to the bare verb. */
export function killTagLabel(isoDate: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDate);
  if (!m) return 'Killed';
  const month = MONTHS[Number(m[2]) - 1];
  if (!month) return 'Killed';
  return `Killed ${Number(m[3])} ${month}`;
}

export function TodayRibbon() {
  const title = latestKill.title?.trim();
  if (!title) return null;
  return (
    <div className="strip ribbon">
      <div className="strip-in">
        <Link href="/kill-log">
          <span className="tag">{killTagLabel(latestKill.date)}</span>
          <span className="txt">{title}</span>
          <span className="go">Read the verdict {String.fromCharCode(8594)}</span>
        </Link>
      </div>
    </div>
  );
}

export default TodayRibbon;
