import type { Meta, StoryObj } from '@storybook/nextjs-vite';

import { VerdictChip } from './VerdictChip';

/**
 * The three verdicts a buyer sees on an idea. They are the site's core vocabulary, so they get a
 * story each: a chip that reads "killed" in the survived colour is a lie about the product, and
 * it is exactly the kind of thing that only shows up when the three are looked at side by side.
 */
const meta: Meta<typeof VerdictChip> = {
  title: 'UI/VerdictChip',
  component: VerdictChip,
};

export default meta;
type Story = StoryObj<typeof VerdictChip>;

export const Survived: Story = { args: { kind: 'survived' } };
export const PushedBack: Story = { args: { kind: 'pushed-back' } };
export const Killed: Story = { args: { kind: 'killed' } };

/** A count in place of the verdict word. The glyph still carries the meaning. */
export const WithCount: Story = { args: { kind: 'pushed-back', label: '3 pushed back' } };
