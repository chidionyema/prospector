import { writeFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

import { EVIDENCE_TICK_CAP, evidenceLabel, evidenceRun } from '@/lib/evidenceTicks';
import { EvidenceRunOg, OG_HEIGHT, OG_WIDTH, PackOgCard, proofLine } from '@/pages/og/pack/[id]';

/**
 * The cited-source run is drawn on two surfaces by two renderers -- the shelf card as DOM, the
 * link-preview card as a satori-rasterised PNG. These tests exist for the failure that shape of
 * duplication produces: the two drift, and a buyer who posts a link sees a share card and a shelf
 * card claiming the same pack with two different pictures.
 *
 * They assert the SHAPE and the render, not the appearance. Colours, sizes and spacing are design
 * decisions and are deliberately not pinned here -- see the suspension note in vitest.config.ts.
 */

describe('evidenceRun: the shape both surfaces draw', () => {
  it('draws one tick per cited source', () => {
    expect(evidenceRun(17).shown).toBe(17);
    expect(evidenceRun(17).ticks).toHaveLength(17);
    expect(evidenceRun(17).over).toBe(false);
  });

  it('caps the run and flags the overflow rather than dropping the fact', () => {
    // 51 is the top of the live range measured 2026-08-14, so this is a state real packs are in.
    const run = evidenceRun(51);
    expect(run.shown).toBe(EVIDENCE_TICK_CAP);
    expect(run.ticks).toHaveLength(EVIDENCE_TICK_CAP);
    expect(run.over).toBe(true);
  });

  it('draws NOTHING rather than an empty track when the count is absent', () => {
    // The rule this pins: an empty evidence drawing on a product whose pitch is evidence says
    // "we checked and found none", when the truth is "this field is absent".
    for (const absent of [undefined, null, 0, -3, Number.NaN]) {
      const run = evidenceRun(absent as number | null | undefined);
      expect(run.shown, `count=${String(absent)}`).toBe(0);
      expect(run.ticks, `count=${String(absent)}`).toEqual([]);
      expect(run.over, `count=${String(absent)}`).toBe(false);
    }
  });

  it('is a function of the count and nothing else', () => {
    // The determinism rule the deleted `PackCoverArt` cover carried, kept: no seed, no randomness,
    // no dependence on what else is on the shelf. A buyer returning finds the same drawing.
    expect(evidenceRun(26)).toEqual(evidenceRun(26));
    expect(evidenceRun(26)).not.toEqual(evidenceRun(27));
  });

  it('is the SAME drawing at both scales, not two drawings', () => {
    // The anti-drift assertion. The shelf's small track is 12px and the share card's is 76px; the
    // run must be the identical skyline scaled, so a pack's two cards are recognisably one pack.
    const small = evidenceRun(34, { track: 12 });
    const large = evidenceRun(34, { track: 76 });

    expect(large.shown).toBe(small.shown);
    expect(large.over).toBe(small.over);
    small.ticks.forEach((tick, i) => {
      expect(large.ticks[i].height).toBeCloseTo((tick.height / 12) * 76, 6);
      // Fade is unitless, so it must be identical rather than merely proportional.
      expect(large.ticks[i].opacity).toBe(tick.opacity);
    });
  });

  it('fades toward the tail so a long run does not win on ink volume alone', () => {
    const { ticks } = evidenceRun(40);
    expect(ticks[0].opacity).toBeGreaterThan(ticks[39].opacity);
  });

  it('names itself for a screen reader, singular and plural', () => {
    expect(evidenceLabel(1)).toBe('1 cited source');
    expect(evidenceLabel(34)).toBe('34 cited sources');
  });
});

describe('EvidenceRunOg: the share card actually rasterises', () => {
  it('renders to real PNG bytes through satori', async () => {
    // The point of this test: satori supports only a subset of CSS and THROWS on a div with
    // multiple children and no explicit `display`. A tree that is valid React and invalid satori
    // fails at request time, on a route whose output social platforms then cache for days. Only a
    // real render proves it, so this one runs the real `next/og`.
    const { ImageResponse } = await import('next/og');

    const response = new ImageResponse(<EvidenceRunOg count={34} />, { width: 600, height: 120 });
    const bytes = Buffer.from(await response.arrayBuffer());

    expect(bytes.length).toBeGreaterThan(0);
    // PNG magic number. Asserting the header rather than a byte count, which would pin the encoder.
    expect(bytes.subarray(0, 8)).toEqual(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]));
  }, 30_000);

  it('renders nothing at all for a pack carrying no source count', () => {
    expect(EvidenceRunOg({ count: undefined })).toBeNull();
    expect(EvidenceRunOg({ count: 0 })).toBeNull();
  });

  it('rasterises the WHOLE card, at both a capped and an uncapped source count', async () => {
    // The route's own tree, not a reconstruction of it -- that is why `PackOgCard` is exported.
    // Two counts because they exercise different branches of the drawing: 48 is over
    // EVIDENCE_TICK_CAP and draws the overflow marker, 30 is under it and does not. Both are real
    // live values (packs 5b8720247589ae96 and 0bf4d472ef2b90ad, catalogue read 2026-08-15).
    const { ImageResponse } = await import('next/og');

    // The third case is a pack carrying NO source count. It renders the card with no run at all --
    // which is also, exactly, what this card looked like before the run was added, so it doubles as
    // the before state. It must still be a valid, complete card and not a hole.
    const cases = [
      [48, 'capped'],
      [30, 'uncapped'],
      [undefined, 'no-sources'],
    ] as const;

    for (const [count, name] of cases) {
      const card = (
        <PackOgCard
          title="Condo due diligence packets for Florida real estate closings"
          proof={proofLine(count ?? 48, '2026-08-14T09:00:00Z')}
          price="£49.99"
          sourceCount={count}
        />
      );
      const bytes = Buffer.from(
        await new ImageResponse(card, { width: OG_WIDTH, height: OG_HEIGHT }).arrayBuffer(),
      );

      expect(bytes.subarray(0, 8), name).toEqual(
        Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
      );
      // A satori tree that fails renders a near-empty card rather than throwing in every case, so
      // size is a second, cruder signal that something was actually drawn.
      expect(bytes.length, name).toBeGreaterThan(5_000);

      if (process.env.OG_SNAPSHOT_DIR) {
        writeFileSync(`${process.env.OG_SNAPSHOT_DIR}/og-${name}.png`, bytes);
      }
    }
  }, 60_000);
});
