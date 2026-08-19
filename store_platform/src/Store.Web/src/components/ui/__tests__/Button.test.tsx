// @vitest-environment jsdom
//
// The jest-dom matchers and the cleanup are imported HERE rather than from a global setup file.
// Measured on this suite: a `setupFiles` entry that pulls in React Testing Library costs every
// fork, and 76 of the 78 test files never render a component -- 38.72s became 126.05s, with 170s
// of it in setup alone. A DOM test pays for the DOM; a pure function test does not.
import '@testing-library/jest-dom/vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { Button } from '../Button';

afterEach(cleanup);

/**
 * BEHAVIOUR, NOT APPEARANCE.
 *
 * Design assertions are suspended while the UI moves (see the block in vitest.config.ts), and this
 * file stays inside that line on purpose: not one assertion here names a colour, a radius or a
 * class. What it pins is what the control DOES.
 *
 * `loading` is the double-submit guard on the buy button. If it ever stops disabling the control,
 * a buyer's second click is a second checkout session, and nothing else in the suite would notice:
 * the component still renders, still reads correctly, still passes typecheck.
 */
describe('Button', () => {
  it('does not fire again while it is loading', async () => {
    const onClick = vi.fn();
    render(
      <Button loading onClick={onClick}>
        Buy this pack
      </Button>,
    );

    const button = screen.getByRole('button', { name: /buy this pack/i });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute('aria-busy', 'true');

    await userEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it('fires once when it is not loading', async () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Buy this pack</Button>);

    await userEvent.click(screen.getByRole('button', { name: /buy this pack/i }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  /**
   * The spinner is decorative. If it ever loses `aria-hidden` a screen reader announces it as part
   * of the button's name, and the accessible name of the money control stops being "Buy this pack".
   */
  it('keeps its accessible name while loading', () => {
    render(<Button loading>Buy this pack</Button>);
    expect(screen.getByRole('button')).toHaveAccessibleName('Buy this pack');
  });

  /**
   * Inside a <form>, a button with no explicit type submits. Every one of these is a control in
   * somebody's form, so the default matters more than it looks.
   */
  it('defaults to type=button so it cannot submit a form by accident', () => {
    render(<Button>Filter</Button>);
    expect(screen.getByRole('button')).toHaveAttribute('type', 'button');
  });
});
