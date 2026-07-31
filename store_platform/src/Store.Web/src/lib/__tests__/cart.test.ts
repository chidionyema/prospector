import { describe, expect, it } from 'vitest';

import { MAX_CART_LINES, addLine, cartTotal, hasLine, parseStoredCart, removeLine, type CartLine } from '../cart';

const line = (id: string, price = '£49.00'): CartLine => ({ id, title: `Pack ${id}`, price });

describe('addLine', () => {
  it('appends a new pack', () => {
    expect(addLine([line('a')], line('b')).map((l) => l.id)).toEqual(['a', 'b']);
  });

  it('is a no-op for a pack already in the basket', () => {
    const lines = [line('a')];
    // Identity, not just equality: a new array would re-render every subscriber for nothing.
    expect(addLine(lines, line('a'))).toBe(lines);
  });

  it('refuses to exceed the server cap', () => {
    const full = Array.from({ length: MAX_CART_LINES }, (_, i) => line(`p${i}`));
    expect(addLine(full, line('one-too-many'))).toBe(full);
  });

  it('does not mutate its input', () => {
    const lines = [line('a')];
    addLine(lines, line('b'));
    expect(lines).toHaveLength(1);
  });
});

describe('removeLine', () => {
  it('drops only the named pack', () => {
    expect(removeLine([line('a'), line('b')], 'a').map((l) => l.id)).toEqual(['b']);
  });

  it('tolerates an id that is not there', () => {
    expect(removeLine([line('a')], 'zzz').map((l) => l.id)).toEqual(['a']);
  });
});

describe('hasLine', () => {
  it('answers by id', () => {
    expect(hasLine([line('a')], 'a')).toBe(true);
    expect(hasLine([line('a')], 'b')).toBe(false);
  });
});

describe('cartTotal', () => {
  it('sums packs at the same price', () => {
    expect(cartTotal([line('a'), line('b'), line('c')])).toBe('£147.00');
  });

  it('sums packs at different prices', () => {
    expect(cartTotal([line('a', '£49.00'), line('b', '£19.50')])).toBe('£68.50');
  });

  it('reads thousands separators', () => {
    expect(cartTotal([line('a', '£1,200.00'), line('b', '£49.00')])).toBe('£1249.00');
  });

  it('is null for an empty basket', () => {
    expect(cartTotal([])).toBeNull();
  });

  it('is null when a price will not parse', () => {
    // A quiet "£49.00" for a two-pack basket would be reconciled against a card statement
    // showing something else. No total is the honest answer.
    expect(cartTotal([line('a'), line('b', 'Free')])).toBeNull();
  });

  it('is null when the lines disagree on a currency', () => {
    expect(cartTotal([line('a', '£49.00'), line('b', '$49.00')])).toBeNull();
  });

  it('does not drift on repeated decimals', () => {
    const lines = Array.from({ length: 3 }, (_, i) => line(`p${i}`, '£0.10'));
    expect(cartTotal(lines)).toBe('£0.30');
  });
});

describe('parseStoredCart', () => {
  it('round-trips what the store writes', () => {
    const lines = [line('a'), line('b')];
    expect(parseStoredCart(JSON.stringify(lines))).toEqual(lines);
  });

  it('returns an empty basket for nothing stored', () => {
    expect(parseStoredCart(null)).toEqual([]);
    expect(parseStoredCart('')).toEqual([]);
  });

  it('returns an empty basket for corrupt JSON', () => {
    expect(parseStoredCart('{not json')).toEqual([]);
  });

  it('returns an empty basket when the stored value is not an array', () => {
    expect(parseStoredCart('{"id":"a"}')).toEqual([]);
    expect(parseStoredCart('"a,b,c"')).toEqual([]);
  });

  it('drops malformed lines and keeps the good ones', () => {
    const raw = JSON.stringify([
      line('a'),
      null,
      'b',
      { id: '', title: 'blank id', price: '£49.00' },
      { id: 'c', title: 'no price' },
      { id: 'd', title: 'numeric price', price: 49 },
      line('e'),
    ]);
    expect(parseStoredCart(raw).map((l) => l.id)).toEqual(['a', 'e']);
  });

  it('truncates a hand-edited basket to the server cap', () => {
    const raw = JSON.stringify(Array.from({ length: MAX_CART_LINES + 5 }, (_, i) => line(`p${i}`)));
    expect(parseStoredCart(raw)).toHaveLength(MAX_CART_LINES);
  });
});
