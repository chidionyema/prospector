/**
 * Contract test: every citation on /sample is attributable and openable.
 *
 * `src/data/sample-report.json` is regenerated from a dossier by `tools/make_sample_report.py` on
 * demand, and `sample.tsx:77` reads it through an `as Check[]` cast. A cast is not a check: TypeScript
 * permits the assertion whenever EITHER type is assignable to the other, so a regeneration that
 * dropped `domain` from every source would still typecheck, still build, and render a row of chips
 * with no publisher on them. That is the exact defect this data already shipped once, in a different
 * form: 2 of 11 chips read "INTRODUCTORY NOTES" and "- Sample Report" (measured 2026-08-06),
 * citations a reader cannot attribute to anyone, on the one page whose argument is "open it and
 * check who said this".
 *
 * The hash-stripping counterpart lives in `noRawCitationHashes.test.ts`.
 */

import { describe, expect, it } from "vitest";
import report from "../data/sample-report.json";

type Source = { url: string; domain: string; label: string };

const CHECK_SOURCES: [where: string, sources: Source[]][] = [
  ...report.checks.map(
    (c, i) => [`checks[${i}] ${c.key}`, c.sources as Source[]] as [string, Source[]],
  ),
  ["premortem", report.premortem.sources as Source[]],
];

describe("the baked free report is a citable document", () => {
  it("has checks and a premortem to check", () => {
    // Guards the whole file against passing vacuously if the generator's output shape moves.
    expect(report.checks.length).toBeGreaterThan(0);
    expect(CHECK_SOURCES.flatMap(([, s]) => s).length).toBeGreaterThan(0);
  });

  it.each(CHECK_SOURCES)("%s: every source names its publisher", (_where, sources) => {
    const anonymous = sources.filter((s) => !s.domain?.trim() || s.domain === "source");
    expect(
      anonymous.map((s) => s.url),
      "a chip with no domain is an unattributable citation; source_chip() in tools/make_sample_report.py owns this",
    ).toEqual([]);
  });

  it.each(CHECK_SOURCES)("%s: every source is openable", (_where, sources) => {
    const unopenable = sources.filter((s) => !/^https?:\/\//.test(s.url ?? ""));
    expect(unopenable.map((s) => s.url)).toEqual([]);
  });

  it("never carries a title that is a heading fragment rather than a title", () => {
    // The two tells `source_title()` rejects: an ALL-CAPS section heading lifted out of a PDF, and
    // a one-word stub. Either is dropped to "" so the domain stands alone, which is attributable.
    const fragments = CHECK_SOURCES.flatMap(([where, sources]) =>
      sources
        .filter((s) => s.label && (s.label === s.label.toUpperCase() || s.label.split(/\s+/).length < 2))
        .map((s) => `${where}: ${s.label}`),
    );
    expect(fragments).toEqual([]);
  });
});
