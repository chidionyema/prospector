import { Head, Html, Main, NextScript } from 'next/document';

/**
 * This file exists for one attribute.
 *
 * Next's default document renders `<Html lang={locale}>`, and with no i18n config there is no
 * locale, so the console shipped `<html>` with no `lang` at all. axe rates that `serious`: a
 * screen reader with no declared language guesses one, and an English page read by a
 * French-pronunciation engine is not slightly worse, it is unusable.
 *
 * Found by `npm run test:a11y` on its first run, on every screen, at both widths.
 */
export default function Document() {
  return (
    <Html lang="en">
      <Head />
      <body>
        <Main />
        <NextScript />
      </body>
    </Html>
  );
}
