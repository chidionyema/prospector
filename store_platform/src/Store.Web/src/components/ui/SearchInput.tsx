import React, { useId } from 'react';
import { cx } from './cx';
import { Icon } from './Icon';
import { controlClass } from './Input';

export interface SearchInputProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'type' | 'children' | 'className'> {
  /** Read by a screen reader in place of the visible label a search box does not get. */
  label: string;
  /**
   * Applied to the WRAPPER, not to the input. The magnifier is positioned against the wrapper, so
   * spacing put on the input (`mb-8`, the call site that first needed this) grows the wrapper under
   * the icon and drags the icon's `top-1/2` down with it. The input's own classes are the
   * component's business; a caller only ever has business with where the control sits.
   */
  className?: string;
}

/**
 * The filter-as-you-type box, with its magnifier.
 *
 * `Input` cannot serve this: it renders a `Field`, i.e. a visible label above the control, which is
 * wrong for a box that sits under a page heading already naming what is being searched. So three
 * pages hand-rolled a raw `<input>` instead, and came out three different ways (2026-08-06):
 *
 *   kill-log.tsx      h-10, rounded-md, border-STRONG, accent focus ring   (a copy of controlClass)
 *   faq.tsx           py-3, SQUARE, border-border, `focus:border-primary/40`
 *   ideas/index.tsx   py-3, SQUARE, border-border, `focus:border-primary/40`
 *
 * Two of them are the same defect twice. `border-border` (#E4E4E7) is the hairline that draws a
 * static card edge, so the box a buyer is supposed to type into was drawn as a panel; and
 * `--primary` is now ink, so `focus:border-primary/40` is a grey edge fading to a slightly greyer
 * edge, which is not a focus signal. `Input.tsx` had already written down both of those repairs and
 * both were unreachable from here, because the shape lived in a component that insists on a label
 * rather than in a class function. This exports the shape; `controlClass` stays the single owner of
 * the border, focus and disabled treatment, shared with every labelled field on the site.
 *
 * The palette's input (`CommandPalette.tsx`) is deliberately not this: there the MODAL is the field
 * and the input is transparent inside it, so it has no border of its own to agree about.
 */
export function SearchInput({ label, id, className, ...rest }: SearchInputProps) {
  const autoId = useId();
  const inputId = id || autoId;
  return (
    <div className={cx('relative', className)}>
      <Icon
        name="search"
        size={16}
        className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-subtle"
      />
      <input
        {...rest}
        id={inputId}
        type="search"
        aria-label={label}
        // The magnifier sits in the left gutter, so the padding goes IN to `controlClass` rather
        // than on top of it -- see the note there on why appending `pl-9` next to its `px-3` is
        // decided by Tailwind's emission order rather than by anything in this file.
        className={controlClass(false, 'pl-9 pr-3')}
      />
    </div>
  );
}
