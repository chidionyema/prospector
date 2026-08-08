import React from 'react';
import { Button, Icon, useToast, cx } from '@/components/ui';
import { MAX_CART_LINES, useCart, type CartLine } from '@/lib/cart';

interface AddToCartButtonProps {
  line: CartLine;
  /**
   * 'compact' sits on a shelf card next to the price; 'full' is a standalone secondary CTA;
   * 'link' is the demoted form used on the pack page, a labelled text action.
   *
   * 'link' exists because the pack page's basket affordance was a full-width secondary Button
   * directly under the primary buy button: two equal-weight blocks for a single £29 item, where
   * the second one is only ever a gain for a buyer who wants several. The alternative considered
   * was deleting it, which is silent feature removal, and the other was reusing 'compact' -- but
   * 'compact' is an unlabelled 32px icon square built for a shelf tile, so on the money page it
   * would hide the capability behind a bare glyph. This keeps the words and drops the weight.
   */
  size?: 'compact' | 'full' | 'link';
  className?: string;
}

/**
 * Put a pack in the basket, or take it out again.
 *
 * Deliberately secondary everywhere it appears. The direct "Buy now" path stays one click, because
 * a basket is only a gain for the buyer who wants more than one pack, making everyone route
 * through add → open → checkout would tax the far more common single purchase to serve the rarer
 * one. This button is the opt-in.
 */
export function AddToCartButton({ line, size = 'full', className }: AddToCartButtonProps) {
  const cart = useCart();
  const { toast } = useToast();
  const inCart = cart.has(line.id);
  const full = !inCart && cart.count >= MAX_CART_LINES;

  const onClick = (event: React.MouseEvent) => {
    // Shelf cards wrap the whole tile in a <Link>. Without this, adding to the basket also
    // navigates away from the shelf the buyer is still browsing.
    event.preventDefault();
    event.stopPropagation();

    if (inCart) {
      cart.remove(line.id);
      return;
    }
    if (full) {
      toast(`A basket holds at most ${MAX_CART_LINES} packs.`, 'warning');
      return;
    }
    cart.add(line);
  };

  // Rendered only once the browser has read localStorage: before that every button would claim
  // the pack is not in the basket, and the ones that are would visibly flip a frame later.
  if (!cart.ready) {
    // Each size reserves its OWN height. Reserving 44px for the text link would hold open a
    // button-sized gap that never fills, which is the layout shift this placeholder prevents,
    // running in reverse.
    const placeholder = size === 'compact' ? 'h-8 w-8' : size === 'link' ? 'h-5' : 'h-11';
    return <span aria-busy={true} aria-hidden className={cx(placeholder, 'block', className)} />;
  }

  if (size === 'link') {
    return (
      <button
        type="button"
        onClick={onClick}
        aria-pressed={inCart}
        className={cx(
          // No aria-label: unlike 'compact' this one has its words on screen, and a label that
          // repeated them would be read twice.
          'inline-flex items-center gap-1.5 rounded-sm text-caption font-medium text-muted',
          'underline decoration-border underline-offset-4 transition-colors',
          'hover:text-primary hover:decoration-primary',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus',
          className,
        )}
      >
        <Icon name={inCart ? 'check' : 'cart'} size={14} />
        {inCart ? 'In your basket' : 'Add to basket'}
      </button>
    );
  }

  if (size === 'compact') {
    return (
      <button
        type="button"
        onClick={onClick}
        aria-label={inCart ? `Remove ${line.title} from basket` : `Add ${line.title} to basket`}
        aria-pressed={inCart}
        className={cx(
          'inline-flex h-8 w-8 flex-none items-center justify-center rounded-sm border transition-all',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus',
          inCart
            ? 'border-primary bg-primary text-on-primary'
            : 'border-border bg-surface text-muted hover:border-primary hover:text-primary',
          className,
        )}
      >
        <Icon name={inCart ? 'check' : 'plus'} size={15} />
      </button>
    );
  }

  return (
    <Button variant="secondary" fullWidth onClick={onClick} className={className}>
      <Icon name={inCart ? 'check' : 'cart'} size={16} />
      {inCart ? 'In your basket' : 'Add to basket'}
    </Button>
  );
}
