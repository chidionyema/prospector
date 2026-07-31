import React from 'react';
import { Button, Icon, useToast, cx } from '@/components/ui';
import { MAX_CART_LINES, useCart, type CartLine } from '@/lib/cart';

interface AddToCartButtonProps {
  line: CartLine;
  /** 'compact' sits on a shelf card next to the price; 'full' is the pack page's secondary CTA. */
  size?: 'compact' | 'full';
  className?: string;
}

/**
 * Put a pack in the basket, or take it out again.
 *
 * Deliberately secondary everywhere it appears. The direct "Buy now" path stays one click, because
 * a basket is only a gain for the buyer who wants more than one pack — making everyone route
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
    return <span aria-hidden className={cx(size === 'compact' ? 'h-8 w-8' : 'h-11', 'block', className)} />;
  }

  if (size === 'compact') {
    return (
      <button
        type="button"
        onClick={onClick}
        aria-label={inCart ? `Remove ${line.title} from basket` : `Add ${line.title} to basket`}
        aria-pressed={inCart}
        className={cx(
          'inline-flex h-8 w-8 flex-none items-center justify-center rounded-full border transition-all',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus',
          inCart
            ? 'border-primary bg-primary text-white'
            : 'border-border bg-white text-muted hover:border-primary hover:text-primary',
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
