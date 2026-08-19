import type { StorybookConfig } from '@storybook/nextjs-vite';

/**
 * COMPONENT ISOLATION.
 *
 * The storefront's defects keep arriving in the same shape: a primitive renders correctly in the
 * one state anybody looked at, and wrongly in a state that only appears with real data. The "624"
 * bar key was a paragraph; the shelf line joined labels with the character one of the labels
 * contained. Neither needed a running API to see — both needed somebody to look at the component
 * in the state that breaks it, which is what a story is.
 *
 * `@storybook/nextjs-vite` rather than `@storybook/nextjs`: this app already builds its tests with
 * Vite (vitest), so the Vite builder reuses that toolchain instead of standing a second webpack
 * config beside it.
 *
 * Stories live next to their component (`Button.tsx` / `Button.stories.tsx`), so a component with
 * no story is visible in the file listing rather than hidden in a parallel tree.
 */
const config: StorybookConfig = {
  stories: ['../src/**/*.stories.@(ts|tsx)'],
  addons: [],
  framework: {
    name: '@storybook/nextjs-vite',
    options: {},
  },
  staticDirs: ['../public'],
  typescript: {
    // The prop tables are generated from the TypeScript types, which is the whole point: a story
    // that documents props by hand goes stale the first time a prop is renamed.
    reactDocgen: 'react-docgen-typescript',
  },
};

export default config;
