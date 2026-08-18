import React from 'react';
import { cx } from '@/components/ui/cx';

/*
  THE DOCUMENT RAIL: in-document navigation with a live position.

  WHAT PROBLEM THIS SOLVES. /sample is the longest page on the site and the highest-leverage one:
  it is the only place a visitor can check the product before paying. It rendered as a single
  column roughly six screens tall with no contents, no sense of length, and no way to move inside
  it. A reader four screens down could not tell how much was left, could not get back to a check
  they had passed, and had no signal that the document was STRUCTURED rather than merely long. That
  is the difference between reading a document and reading a web page, and it is the whole of what
  a docs application provides.

  WHY A RAIL AND NOT AN ACCORDION. Collapsing the sections would shorten the page and destroy the
  argument: the length IS the evidence. Eight checks, each with its own sources, is the thing being
  demonstrated, and a reader who has to open eight panels to find that out will open one. The rail
  leaves every word on the page and adds the map.

  WHY SCROLL POSITION IS OBSERVED RATHER THAN COMPUTED. An `IntersectionObserver` reports what the
  browser actually laid out. Deriving the active section from `scrollY` against measured offsets
  means recomputing on every resize, every font swap and every image load, and being wrong in the
  window between them.
*/

export interface DocSectionRef {
  /** The `id` of the element in the document, without the `#`. */
  id: string;
  label: string;
  /** Rendered indented, for entries that are subordinate to the one above (individual checks). */
  nested?: boolean;
  /** A short mono annotation on the right, e.g. a verdict. Never prose. */
  note?: string;
  /** Tints the note. `kill` marks the objection the reader most wants to find. */
  /** 'kill' is red and means something died. 'warn' is amber and means unsettled, never dead. */
  tone?: 'kill' | 'warn';
}

export function DocRail({
  sections,
  eyebrow,
  className,
}: {
  sections: DocSectionRef[];
  eyebrow: string;
  className?: string;
}) {
  const [active, setActive] = React.useState<string>('');

  React.useEffect(() => {
    const nodes = sections
      .map((section) => document.getElementById(section.id))
      .filter((node): node is HTMLElement => node !== null);
    if (nodes.length === 0) return;

    /* The band, not the whole viewport. `-88px` clears the sticky header so a section is not
       "current" while it sits behind it; `-62%` closes the bottom of the band so only the upper
       third of the screen can claim the highlight. Without the bottom margin, every section
       visible on a tall viewport intersects at once and the rail flickers between them on any
       scroll. */
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible.length > 0) setActive(visible[0].target.id);
      },
      { rootMargin: '-88px 0px -62% 0px', threshold: 0 },
    );
    nodes.forEach((node) => observer.observe(node));
    return () => observer.disconnect();
  }, [sections]);

  return (
    // `hidden lg:block` and no mobile equivalent, deliberately. A rail collapsed into a phone-width
    // dropdown is a control the reader must open to learn anything from, which is strictly worse
    // than the linear scroll they already have; and the mobile fix that would actually help (a
    // progress bar) is a different component. Below `lg` the document simply reads top to bottom.
    /* THE DRAWING'S CONTENTS CARD (`mockups/sample.html`, `.toc`): a bordered, sticky card whose
       rows are the anchors themselves. It was a hairline-and-marker list, which is a different
       object: the drawing draws the contents as one card beside the sheet, numbered, with the
       current row filled in brand tint. `.toc` carries its own `position:sticky`, so the wrapping
       sticky div is gone rather than nested inside it -- two sticky boxes cannot both work.
       No <ul>/<li>: `.toc a:last-child{border-bottom:0}` is what closes the card's bottom edge,
       and a <li> between the card and the anchor makes every anchor its own parent's last child,
       which deletes every divider in the list. */
    /* 861px, not `lg`. `.reader` and `.legal` both collapse to one column at 860px
       (`mumchimp.css`), so a rail that appears at 1024 leaves a 230px empty column between the two
       breakpoints, and one that appears earlier stacks under a body it is meant to sit beside. */
    <div className={cx('hidden min-[861px]:block', className)}>
      <p className="mono mb-3">{eyebrow}</p>
      <nav aria-label="Contents of this report" className="toc">
        {sections.map((section, i) => {
          const current = active === section.id;
          return (
            <a
              key={section.id}
              href={`#${section.id}`}
              aria-current={current ? 'true' : undefined}
              className={cx('transition-colors', section.nested && 'pl-7')}
            >
              <span className="i num">{String(i + 1).padStart(2, '0')}</span>
              <span className="min-w-0 flex-1">{section.label}</span>
              {section.note && (
                <span
                  className={cx(
                    'flex-none font-mono text-caption',
                    section.tone === 'kill' ? 'text-kill' : section.tone === 'warn' ? 'text-warning-strong' : 'text-subtle',
                  )}
                >
                  {section.note}
                </span>
              )}
            </a>
          );
        })}
      </nav>
    </div>
  );
}

export default DocRail;
