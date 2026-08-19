import type { Meta, StoryObj } from '@storybook/nextjs-vite';

import { ProofLine } from './ProofLine';

/**
 * The line that carries the site's whole claim: how many sources, how many checks, when it was
 * last verified. It joins its parts with ` · `, which is the separator that made the home shelf
 * unreadable on 2026-08-19 when a market label contained one. The singular cases are stories
 * rather than an afterthought because "1 sources" is the classic way this line goes wrong.
 */
const meta: Meta<typeof ProofLine> = {
  title: 'UI/ProofLine',
  component: ProofLine,
};

export default meta;
type Story = StoryObj<typeof ProofLine>;

export const Full: Story = {
  args: { sources: 24, checks: 6, verifiedAt: '2026-08-19T09:36:00.123456+00:00' },
};

export const SingularBoth: Story = { args: { sources: 1, checks: 1 } };
export const SourcesOnly: Story = { args: { sources: 12 } };
export const NoneYet: Story = { args: { sources: 0, checks: 0 } };

export const OnMobile: Story = {
  args: { sources: 24, checks: 6, verifiedAt: '2026-08-19T09:36:00.123456+00:00' },
  globals: { viewport: { value: 'mobile' } },
};
