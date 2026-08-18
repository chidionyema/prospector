import React from 'react';
import Link from 'next/link';

import { fetchCatalog, formatPrice, type Pack } from '@/lib/api/client';
import { useCart } from '@/lib/cart';
import { newSince, readSeen, rememberSeen } from '@/lib/seenPacks';
import { Icon, textLinkClass } from '@/components/ui';

/**
 * The second and third blocks of the account page (MASTER-BRIEF section 7 `/account`): the
 * shortlist, then what is new since the last visit. The owned packs come first and are rendered by
 * `AccountPanel` above this.
 *
 * THE SHORTLIST IS THE BASKET. The brief's mockup shows a shortlist and this site has no separate
 * one, so the honest question is whether to build a second list of saved packs. It is not: the
 * basket already holds exactly what a shortlist holds -- packs a reader picked out and has not paid
 * for -- it survives a session in localStorage, and a pack can sit in it indefinitely because there
 * is no quantity and nothing expires. Two lists would have meant a reader saving a pack twice, and
 * a "saved" list that does not go to checkout is a dead end of the kind step 7 exists to remove.
 *
 * BOTH BLOCKS RENDER NOTHING WHEN THEY ARE EMPTY. An account page carrying two headings above two
 * "nothing here yet" boxes reads as an unfinished page. The heading appears when there is something
 * under it.
 *
 * CLIENT-SIDE, AND IT MUST BE. Both blocks are about this browser: one reads the basket out of
 * localStorage, the other compares the shelf against the ids this browser saw last time. Neither
 * has an answer on the server, so neither is fetched there. A catalogue failure here is silent by
 * design -- the account page's job is the customer's downloads, and it must not fall over because a
 * return hook could not load.
 */

function PackLine({ id, title, price }: { id: string; title: string; price?: string }) {
  return (
    <li>
      <Link
        href={`/pack/${id}`}
        className="flex items-baseline justify-between gap-4 border-b border-border py-4 last:border-b-0"
      >
        <span className="text-meta font-medium text-text">{title}</span>
        {price && (
          <span className="shrink-0 font-mono text-meta tabular-nums text-muted">
            {formatPrice(price)}
          </span>
        )}
      </Link>
    </li>
  );
}

function Block({
  title,
  lead,
  children,
  moreHref,
  moreLabel,
}: {
  title: string;
  lead: string;
  children: React.ReactNode;
  moreHref: string;
  moreLabel: string;
}) {
  return (
    <section className="mt-12">
      <h2 className="sec">{title}</h2>
      <p className="mt-2 max-w-[62ch] lede">{lead}</p>
      {/* `rounded-card`, not `rounded-md`. A bordered box on `--surface` holding rows IS a card,
          and 12px is what every other card on the site draws. The account area was the one place
          that gave its cards the 8px CONTROL corner, which is the sort of difference nobody names
          but everybody sees: the same shelf rows look softer on the catalogue than they do here. */}
      <ul className="mt-4 rounded-card border border-border bg-surface px-6">{children}</ul>
      <Link href={moreHref} className={textLinkClass('mt-4 inline-flex items-center gap-1 text-meta font-medium')}>
        {moreLabel} <Icon name="arrowRight" size={12} />
      </Link>
    </section>
  );
}

export function ReturnBlocks() {
  const cart = useCart();
  const [fresh, setFresh] = React.useState<Pack[]>([]);

  React.useEffect(() => {
    let live = true;
    fetchCatalog()
      .then((packs) => {
        if (!live) return;
        // READ BEFORE WRITE. `rememberSeen` overwrites the record this visit is being compared
        // against, so calling it first would make every visit report nothing new, for ever, with
        // no error anywhere.
        const seen = readSeen();
        setFresh(newSince(packs, seen));
        rememberSeen(packs.map((pack) => pack.id));
      })
      .catch(() => {
        // Silent: see the note above. The customer's downloads are what this page is for.
      });
    return () => {
      live = false;
    };
  }, []);

  return (
    <>
      {cart.ready && cart.lines.length > 0 && (
        <Block
          title="Saved for later"
          lead={
            cart.lines.length === 1
              ? 'One pack you picked out and have not bought yet.'
              : `${cart.lines.length} packs you picked out and have not bought yet.`
          }
          moreHref="/"
          moreLabel="Back to the shelf"
        >
          {cart.lines.map((line) => (
            <PackLine key={line.id} id={line.id} title={line.title} price={line.price} />
          ))}
        </Block>
      )}

      {fresh.length > 0 && (
        <Block
          title="New since your last visit"
          lead={
            fresh.length === 1
              ? 'One pack has cleared the checks and reached the shelf since you were last here.'
              : `${fresh.length} packs have cleared the checks and reached the shelf since you were last here.`
          }
          moreHref="/"
          moreLabel="See the whole shelf"
        >
          {/* Ten at most. The point of the block is a reason to click, and a list long enough to
              scroll is the shelf, which is one link away and better at being the shelf. */}
          {fresh.slice(0, 10).map((pack) => (
            <PackLine key={pack.id} id={pack.id} title={pack.title} price={pack.price} />
          ))}
        </Block>
      )}
    </>
  );
}

export default ReturnBlocks;
