import React, { useId } from 'react';
import { cx } from './cx';
import { Field, describedBy } from './Field';

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label: string;
  hint?: string;
  error?: string;
  hideLabel?: boolean;
}

/*
 * Brand v3 (2026-08-06), spec §6.13. Three concrete changes:
 *  - The resting border was `--border` (#E4E4E7), the same hairline that draws a card edge. On a
 *    white page a control you can type into looked identical to a static panel, so the field only
 *    read as a field once it was focused. Inputs get `--border-strong`.
 *  - The focus treatment was a 4px `ring-primary/10` wash plus a `border-primary` edge. With
 *    `--primary` now ink, that is a grey smudge around a grey box, i.e. no focus signal at all.
 *    Focus is `--accent`, the one colour on this site that means "interactive".
 *  - `transition-all duration-200` animated every property including layout ones; colour only,
 *    at the 120ms hover speed the rest of the site uses.
 */
/*
 * `padding` is an argument, not something a caller appends. `Select` needs a wider right gutter for
 * its chevron and `SearchInput` a wider left one for its magnifier, and both used to express that
 * by passing `pr-10` / `pl-9` in `className` on top of the `px-3` this function already emits.
 * Those two utilities have EQUAL specificity, so which one applies is decided by where Tailwind
 * emits them in the stylesheet, not by the order they appear in the class attribute. Measured in
 * the built CSS (2026-08-06, `.next/static/chunks/01kw0v8q_98w3.css`): `.px-3` at byte 26831,
 * `.pr-10` at 28604, `.pl-9` at 29559 -- the directional rules come later, so the override did
 * work. It worked because of Tailwind's internal ordering, which is not a promise this repo holds
 * and not something any test here would notice changing; the failure it protects against is a
 * chevron sitting on top of the selected option. Passing the padding in leaves one rule to win.
 */
const controlClass = (invalid: boolean, padding = 'px-3') =>
  cx(
    /* 44px on touch, 40px from `sm` up -- the same split `Button`'s `md` size and `chipClasses`
       take. Measured at 390px on 2026-08-13: the home page's search trigger, the shelf's sort
       control and the newsletter field all came back 40px, 4px under the floor the header
       buttons and both footer columns state explicitly. Desktop is unchanged to the pixel. */
    'h-11 w-full rounded-md border bg-surface text-meta text-text sm:h-10',
    padding,
    'transition-[border-color,outline-color] duration-[120ms] ease-[cubic-bezier(0.2,0,0,1)]',
    'placeholder:font-normal placeholder:text-subtle',
    'hover:border-text',
    'focus-visible:border-accent focus-visible:outline-2 focus-visible:outline-offset-0 focus-visible:outline-accent/25',
    'disabled:cursor-not-allowed disabled:bg-surface2 disabled:opacity-40',
    invalid
      ? 'border-danger focus-visible:border-danger focus-visible:outline-danger/25'
      : 'border-border-control',
  );

/** Labelled text input, label always present, error/hint slots, aria wired (UI-STANDARDS §2). */
export function Input({
  label,
  hint,
  error,
  required,
  hideLabel,
  id,
  className,
  ...rest
}: InputProps) {
  const autoId = useId();
  const inputId = id || autoId;
  return (
    <Field
      label={label}
      htmlFor={inputId}
      hint={hint}
      error={error}
      required={required}
      hideLabel={hideLabel}
    >
      <input
        {...rest}
        id={inputId}
        required={required}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(inputId, hint, error)}
        className={cx(controlClass(!!error), className)}
      />
    </Field>
  );
}

export { controlClass };
