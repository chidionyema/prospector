import React from 'react';
import { monogram } from '@/lib/cover';

/**
 * Decorative cover motif: a faint assay-hallmark seal (the octagonal punch from the brand mark) with
 * the pack's monogram struck inside it. It echoes the logo, so each gradient cover reads as a stamped,
 * certified pack rather than carrying an accidental clipped letter. Purely presentational; the title
 * sits beside/below it, so the seal is `aria-hidden`. Sits centered on the cover, behind the chips.
 */
export function CoverArt({ title }: { title: string }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 100 100"
      className="pointer-events-none absolute left-1/2 top-1/2 h-[78%] w-auto -translate-x-1/2 -translate-y-1/2 select-none text-white"
    >
      <polygon
        points="35,10 65,10 90,35 90,65 65,90 35,90 10,65 10,35"
        fill="none"
        stroke="currentColor"
        strokeOpacity="0.28"
        strokeWidth="2.25"
      />
      <text
        x="50"
        y="51"
        textAnchor="middle"
        dominantBaseline="central"
        fontSize="30"
        fontWeight="800"
        letterSpacing="-1"
        fill="currentColor"
        fillOpacity="0.9"
      >
        {monogram(title)}
      </text>
    </svg>
  );
}
