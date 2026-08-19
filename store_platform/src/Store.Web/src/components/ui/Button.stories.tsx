import type { Meta, StoryObj } from '@storybook/nextjs-vite';

import { Button } from './Button';

const meta: Meta<typeof Button> = {
  title: 'UI/Button',
  component: Button,
  args: { children: 'Buy this pack' },
};

export default meta;
type Story = StoryObj<typeof Button>;

export const Primary: Story = { args: { variant: 'primary' } };
export const Secondary: Story = { args: { variant: 'secondary' } };
export const Ghost: Story = { args: { variant: 'ghost' } };
export const Danger: Story = { args: { variant: 'danger', children: 'Cancel this order' } };

export const Large: Story = { args: { size: 'lg' } };
export const FullWidth: Story = { args: { fullWidth: true } };

/**
 * The money state. `loading` is what stops a double-submit on the buy button, so it is the one
 * state that has to be right and the one nobody clicks through by accident.
 */
export const Loading: Story = { args: { loading: true } };
export const Disabled: Story = { args: { disabled: true } };

/**
 * The label the shipped design actually uses, at the length that breaks: a long call to action in
 * a 390px column is where a button either wraps or overflows its row.
 */
export const LongLabelOnMobile: Story = {
  args: { children: 'Buy this pack and the three it links to' },
  globals: { viewport: { value: 'mobile' } },
};
