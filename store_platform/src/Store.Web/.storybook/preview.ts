import type { Preview } from '@storybook/nextjs-vite';

// The real stylesheets, in the order `_app.tsx` loads them. A story rendered without the shipped
// bundle is a story about a component that does not exist: every primitive here is styled by
// mumchimp.css plus the token layer, not by anything local.
import '../src/styles/globals.css';

const preview: Preview = {
  parameters: {
    controls: { matchers: { color: /(background|color)$/i, date: /Date$/i } },
    // The two widths the design is drawn at, so a story can be checked at both without resizing.
    viewport: {
      options: {
        mobile: { name: 'Mobile 390', styles: { width: '390px', height: '844px' } },
        desktop: { name: 'Desktop 1280', styles: { width: '1280px', height: '900px' } },
      },
    },
  },
};

export default preview;
