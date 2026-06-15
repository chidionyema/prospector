import { useEffect, useRef } from 'react';

/**
 * Accessible disclosure keyboard contract for the mobile-nav drawers — see
 * docs/engineering/ACCESSIBILITY-STANDARDS.md §"Disclosures & menus".
 *
 * While `open`, Escape closes the panel and returns focus to the trigger button, so a keyboard or
 * screen-reader user is never stranded at the top of the document after dismissing the menu. Attach
 * the returned `triggerRef` to the toggle <button>.
 *
 * This is deliberately NOT a focus trap. The mobile drawer is an IN-FLOW disclosure (it pushes the
 * page content down; it is not a modal overlay), so Tab should flow naturally from the menu into the
 * page. Trapping focus while the content behind stays visible and operable is itself a WCAG
 * anti-pattern. The trigger already carries aria-expanded / aria-controls at the call site.
 */
export function useDisclosure(open: boolean, onClose: () => void) {
  const triggerRef = useRef<HTMLButtonElement>(null);
  // Keep the latest onClose without resubscribing the Escape listener on every render. Written in an
  // effect (not during render) so it satisfies react-hooks/refs.
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  });

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onCloseRef.current();
        triggerRef.current?.focus();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open]);

  return { triggerRef };
}
