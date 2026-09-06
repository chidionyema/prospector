/**
 * DocBody — one decision about how a document is drawn, used by every page that draws one.
 *
 * WHY THIS EXISTS. Measured 2026-08-21 on origin/main (9e2cfef2): 18 `.html` documents are
 * tracked, listed on `/docs` with `readable: true`, and unreadable in both places that show them.
 * `docs.tsx` sent every non-`.json` document to `react-markdown` with raw HTML disabled, so an
 * HTML file arrived as its own source with the tags stripped — a page of stranded attribute text.
 * `/s/<token>` was worse: one `<pre>`, so a shared HTML document rendered as source to whoever
 * the founder handed the link to. The backend was never the problem. It returns the file
 * (`prospector/ops/docs_view.py::doc_view`; `.html` has been in `_TEXT_SUFFIXES` since
 * 2026-08-21). Both readers simply had no branch for it, and each had its own copy of the rule,
 * which is how they drifted.
 *
 * The founder's words: "this doc should be [mintable] fron adnin portal every single doc should
 * be". Every single doc means every format the index will list, not every format that happens to
 * be markdown.
 *
 * WHY AN IFRAME AND NOT `dangerouslySetInnerHTML`. A repo document is a whole page — its own
 * `<style>`, its own type scale, its own layout. Injected into the console's DOM, a document's
 * CSS restyles the console around it, and injecting markup nobody sanitised is not a call to make
 * on a component that also serves a public share link. A frame gives the document its own
 * document, which is what it already is. The sandbox, and the argument for it, are in
 * `@/lib/docKind`.
 *
 * `.md` renders as markdown and `.json` as source, exactly as `docs.tsx` already did. That code
 * moved here unchanged so the two readers cannot drift again.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { FRAME_SANDBOX, MIN_FRAME_PX, framedSrcDoc, kindOf } from '@/lib/docKind';

/**
 * How a rendered markdown document is styled.
 *
 * Written out rather than pulled in as `@tailwindcss/typography`. The plugin is a build-time
 * dependency and a set of defaults tuned for marketing pages; this is twenty lines that match the
 * console's own type scale, and it is the only place a heading size is decided.
 */
export const md = {
  h1: (p: object) => <h1 className="mb-3 mt-6 text-[20px] font-[650] first:mt-0" {...p} />,
  h2: (p: object) => <h2 className="mb-2 mt-6 text-[16px] font-[650]" {...p} />,
  h3: (p: object) => (
    <h3 className="mb-2 mt-5 text-[13px] font-[650] uppercase tracking-wide text-subtle" {...p} />
  ),
  p: (p: object) => <p className="my-3 text-[14px] leading-[1.65]" {...p} />,
  ul: (p: object) => <ul className="my-3 list-disc pl-5 text-[14px] leading-[1.65]" {...p} />,
  ol: (p: object) => <ol className="my-3 list-decimal pl-5 text-[14px] leading-[1.65]" {...p} />,
  li: (p: object) => <li className="my-1" {...p} />,
  blockquote: (p: object) => (
    <blockquote className="my-3 border-l-2 border-line pl-3 text-[14px] italic text-subtle" {...p} />
  ),
  code: (p: object) => (
    <code className="wrap-any rounded bg-black/5 px-1 py-[1px] font-mono text-[12.5px]" {...p} />
  ),
  // A fenced block is a `<pre>` wrapping the `<code>` above, and it is the one thing on the page
  // that is allowed to scroll sideways: wrapping a shell command changes what it says.
  pre: (p: object) => (
    <pre className="my-3 overflow-x-auto rounded bg-black/5 p-3 font-mono text-[12.5px]" {...p} />
  ),
  // Tables are why `remark-gfm` is here. They also overflow on a phone, so each one gets its own
  // horizontal scroller rather than pushing the page sideways.
  table: (p: object) => (
    <div className="my-3 overflow-x-auto">
      <table className="w-full border-collapse text-[13px]" {...p} />
    </div>
  ),
  th: (p: object) => (
    <th className="border border-line px-2 py-1 text-left font-[650] align-top" {...p} />
  ),
  td: (p: object) => <td className="border border-line px-2 py-1 align-top" {...p} />,
  hr: () => <hr className="my-5 border-0 border-t border-line" />,
};

function HtmlDoc({ text, title }: { text: string; title: string }) {
  const ref = useRef<HTMLIFrameElement | null>(null);
  const [height, setHeight] = useState(MIN_FRAME_PX);

  // Measured from the parent, because the frame cannot report its own size — it is not allowed to
  // run code, which is the point. `allow-same-origin` is what makes `contentDocument` readable.
  const measure = useCallback(() => {
    const doc = ref.current?.contentDocument;
    if (!doc?.body) return;
    const next = Math.max(
      doc.documentElement?.scrollHeight ?? 0,
      doc.body.scrollHeight,
      MIN_FRAME_PX,
    );
    // Only ever grow within one document. A re-measure mid-layout — a web font landing, an image
    // decoding — can briefly report a shorter body, and shrinking on that reading makes the page
    // jump under the reader's hands.
    setHeight((prev) => (next > prev ? next : prev));
  }, []);

  // A document that pulls a web font is taller once the font arrives, and taller again once its
  // images decode. One measurement at load lands before both. Three cheap reads over two seconds
  // rather than a ResizeObserver, which does not fire across a document boundary.
  //
  // Nothing resets the height here. Opening a different document REMOUNTS this component — see
  // the `key` in `DocBody` — so the fresh mount starts at `MIN_FRAME_PX` on its own. Resetting it
  // in the effect instead is a synchronous `setState` inside an effect, which React flags as a
  // cascading render (`react-hooks/set-state-in-effect`, and `npm run lint` fails on it).
  useEffect(() => {
    const timers = [250, 900, 2000].map((ms) => window.setTimeout(measure, ms));
    window.addEventListener('resize', measure);
    return () => {
      timers.forEach(window.clearTimeout);
      window.removeEventListener('resize', measure);
    };
  }, [text, measure]);

  return (
    <iframe
      ref={ref}
      sandbox={FRAME_SANDBOX}
      referrerPolicy="no-referrer"
      srcDoc={framedSrcDoc(text)}
      onLoad={measure}
      title={title}
      className="w-full border-0 bg-transparent"
      style={{ height }}
    />
  );
}

export default function DocBody({
  name,
  text,
  title,
  source = false,
}: {
  /** Repo-relative path. Its suffix is the only thing that decides the renderer. */
  name: string;
  text: string;
  /** The frame's accessible name. A frame without one is a screen-reader dead end. */
  title: string;
  /** The reader asked for source. Honoured for every format, HTML included. */
  source?: boolean;
}) {
  const kind = kindOf(name);

  if (source || kind === 'source') {
    return (
      <pre className="m-0 whitespace-pre-wrap break-words font-mono text-[12.5px] leading-[1.6]">
        {text}
      </pre>
    );
  }

  // `key` is the document, so switching documents remounts the frame rather than resizing one
  // — a fresh mount is how the measured height goes back to the floor.
  if (kind === 'html') return <HtmlDoc key={name} text={text} title={title} />;

  return (
    <div className="wrap-any">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={md}>
        {text}
      </ReactMarkdown>
    </div>
  );
}
