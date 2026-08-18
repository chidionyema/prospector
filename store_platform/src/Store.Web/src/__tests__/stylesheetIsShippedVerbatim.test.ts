import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

/**
 * THE STYLESHEET IS SHIPPED, NOT WRITTEN. Founder directive, 2026-08-18:
 * "mumchimp.css in this bundle is the complete stylesheet for the site. Import it unchanged.
 *  Do not write CSS. Do not rename classes. Do not 'tidy' it. If a style you need is not in
 *  that file, stop and ask."
 *
 * Prose cannot enforce that; a byte comparison can. `docs/design/mumchimp-build-bundle/` is the
 * delivered bundle and `src/styles/mumchimp.css` is the copy the app imports, so the only way a
 * rule can change is by a new bundle landing -- never by an edit in the app tree.
 *
 * Deliberate deviations do not go in this file. They go in the `@layer components` block in
 * `globals.css`, where each one carries the measurement that justifies it.
 */
const WEB = path.resolve(__dirname, "..", "..");
const ROOT = path.resolve(WEB, "..", "..", "..");

describe("the shipped stylesheet", () => {
  it("is byte-identical to the bundle it came from", () => {
    const shipped = readFileSync(
      path.join(ROOT, "docs/design/mumchimp-build-bundle/mumchimp.css"),
    );
    const imported = readFileSync(path.join(WEB, "src/styles/mumchimp.css"));
    expect(
      imported.equals(shipped),
      "src/styles/mumchimp.css has been edited. Change the bundle and re-copy, or put the " +
        "deviation in globals.css @layer components with its measurement.",
    ).toBe(true);
  });

  it("is the only stylesheet globals.css imports from the bundle", () => {
    const globals = readFileSync(path.join(WEB, "src/styles/globals.css"), "utf8");
    expect(globals).toContain('@import "./mumchimp.css" layer(components);');
    expect(globals).not.toContain("mockup.css");
  });
});
