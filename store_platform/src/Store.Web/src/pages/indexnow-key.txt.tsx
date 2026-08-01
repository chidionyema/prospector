import type { GetServerSideProps } from 'next';

/**
 * `/indexnow-key.txt` — the ownership proof for IndexNow submissions.
 *
 * The protocol verifies that whoever submits a URL controls the host by fetching a file whose
 * body is the submission key. The engine names this exact path as `keyLocation` in every payload
 * (`prospector/indexnow.py`), so BOTH sides read the same `INDEXNOW_KEY`; if they disagree the
 * endpoint answers 403 and nothing is indexed.
 *
 * WHY A FIXED PATH RATHER THAN `/<key>.txt`. The protocol's default is to serve the file at the
 * site root named after the key itself, which would need a root-level dynamic route — and a
 * catch-all at `/` in the Pages Router shadows real pages. Declaring `keyLocation` explicitly is
 * the protocol's own supported alternative and costs one field in the payload.
 *
 * Not `INDEXNOW_KEY` on the client: this is read server-side only, so it has no `NEXT_PUBLIC_`
 * prefix and never reaches the bundle. That is presentation, not secrecy — the whole point of the
 * file is that the value is public. The prefix would simply be a lie about where it is read.
 *
 * 404 when unset, rather than an empty 200. An empty key file is a *failed* ownership proof that
 * looks like a working one; a 404 is the honest statement that this site has not enrolled.
 */
export const getServerSideProps: GetServerSideProps = async ({ res }) => {
  const key = process.env.INDEXNOW_KEY;
  if (!key) return { notFound: true };

  res.setHeader('Content-Type', 'text/plain; charset=utf-8');
  // The engines re-fetch this on submission. A day of caching is plenty and keeps a burst of
  // publishes from turning into a burst of origin hits.
  res.setHeader('Cache-Control', 'public, max-age=86400');
  res.write(key);
  res.end();
  return { props: {} };
};

// Route only exists to serve the body above; nothing renders.
export default function IndexNowKey() {
  return null;
}
