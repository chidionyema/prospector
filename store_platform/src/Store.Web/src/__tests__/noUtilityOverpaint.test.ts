import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

/**
 * THE BUNDLE IS THE OPINION; A UTILITY MUST NOT OVERRULE IT.
 *
 * `stylesheetIsShippedVerbatim.test.ts` proves the designer's CSS arrives unedited. It cannot
 * prove the markup lets it apply. It did not: `globals.css` imports the bundle into
 * `layer(components)`, and Tailwind's utilities live in `layer(utilities)`, which wins over
 * every layer beneath it regardless of specificity. So a single `max-w-[68ch]` on an element
 * that already carries `.lede` silently replaces the designer's measure -- no override warning,
 * no failing test, nothing to notice in review.
 *
 * Measured in this tree on 2026-08-30, before the first pass: 75 elements carried a designer
 * class and an unprefixed utility that set a property that class already owns. 45 of them were
 * on `.lede` alone, which the bundle sets to one value -- `max-width:60ch` -- and which the app
 * had restated eleven different ways: 60ch, 62ch, 68ch, 80ch, 52ch, sm, md, prose, 2xl, 3xl and
 * a `leading-[1.68]`. Twenty-three were the designer's own value retyped as a utility, which
 * changes nothing visually and everything about what the next edit is free to do.
 *
 * That is the mechanism behind the drift, not carelessness: 202 commits touching styles since
 * June, each locally reasonable, none of them able to see that the bundle already had an answer.
 *
 * The rule this pins: if an element carries a class the bundle styles, the bundle sets those
 * properties. Reach for a utility only for a property the bundle leaves open (vertical rhythm,
 * layout position), or behind a responsive/state prefix, which this check deliberately permits
 * because the bundle has no opinion at a breakpoint it never drew.
 */
const WEB = path.resolve(__dirname, "..", "..");
const SHEET = path.join(WEB, "src/styles/mumchimp.css");
const SRC = path.join(WEB, "src");
const SKIP_DIRS = new Set(["node_modules", "__tests__", "styles", ".next"]);

/** Utility prefix -> the CSS properties it controls. */
const UTILITY_PROPS: ReadonlyArray<readonly [RegExp, readonly string[]]> = [
  [/^-?m-/, ["margin"]],
  [/^-?mt-/, ["margin-top"]],
  [/^-?mb-/, ["margin-bottom"]],
  [/^-?ml-/, ["margin-left"]],
  [/^-?mr-/, ["margin-right"]],
  [/^-?mx-/, ["margin-left", "margin-right"]],
  [/^-?my-/, ["margin-top", "margin-bottom"]],
  [/^p-/, ["padding"]],
  [/^pt-/, ["padding-top"]],
  [/^pb-/, ["padding-bottom"]],
  [/^pl-/, ["padding-left"]],
  [/^pr-/, ["padding-right"]],
  [/^px-/, ["padding-left", "padding-right"]],
  [/^py-/, ["padding-top", "padding-bottom"]],
  [/^text-(xs|sm|base|lg|xl|\dxl|\[)/, ["font-size"]],
  [/^font-(thin|light|normal|medium|semibold|bold|extrabold|black|\[)/, ["font-weight"]],
  [/^bg-/, ["background"]],
  [/^rounded/, ["border-radius"]],
  [/^leading-/, ["line-height"]],
  [/^tracking-/, ["letter-spacing"]],
  [/^max-w-/, ["max-width"]],
  [/^w-/, ["width"]],
  [/^max-h-/, ["max-height"]],
  [/^h-/, ["height"]],
  [/^gap-/, ["gap"]],
  [/^(flex|grid|block|inline-block|hidden)$/, ["display"]],
  [/^grid-cols-/, ["grid-template-columns"]],
  [/^(uppercase|lowercase|capitalize)$/, ["text-transform"]],
  [/^items-/, ["align-items"]],
  [/^justify-/, ["justify-content"]],
  [/^flex-wrap$/, ["flex-wrap"]],
  [/^line-clamp-/, ["-webkit-line-clamp"]],
];

/**
 * Deliberate exceptions. Each is `file:class:utility` and carries the reason it is not drift.
 * Adding a line here is a design decision, so it needs a sentence a reviewer can disagree with.
 */
const ALLOW = new Map<string, string>([
  [
    "src/pages/kill-log.tsx:bars:h-auto",
    "The kill log reuses .bars as a list rather than the 44px chart the bundle drew; the rows " +
      "set their own height. Repointed when the kill-log geometry gap is closed.",
  ],
  [
    "src/pages/kill-log.tsx:bars:items-stretch",
    "Same list reuse: rows fill the width instead of aligning to the chart baseline.",
  ],
]);

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = path.join(dir, entry);
    if (statSync(full).isDirectory()) {
      if (!SKIP_DIRS.has(entry)) walk(full, out);
    } else if (/\.(tsx|jsx)$/.test(entry)) {
      out.push(full);
    }
  }
  return out;
}

/**
 * class -> properties, built ONLY from selectors that are a single bare class.
 *
 * This narrowness is the point. The bundle styles many classes by context -- `.sub` is one
 * thing under `h3`, another under `.comp`, another under `.hero`, and only the `.comp` one sets
 * a line-height. A scan of the source cannot know which ancestor an element will have at
 * runtime, so treating `.comp .sub` as if it were `.sub` would report a conflict that may not
 * exist on the page. A rule written as `.lede {}` has no such escape: it applies wherever the
 * class does, so a utility beside it always wins, and the finding is a fact rather than a guess.
 *
 * `h3.sub` and `.lede.big` are excluded for the same reason -- both need something else to be
 * true of the element before they apply.
 */
function bundleClassProps(): Map<string, Map<string, string>> {
  const css = readFileSync(SHEET, "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
  const map = new Map<string, Map<string, string>>();
  for (const m of css.matchAll(/([^{}@]+)\{([^{}]*)\}/g)) {
    const decls = [...m[2].matchAll(/([-a-zA-Z]+)\s*:\s*([^;]+)/g)];
    for (const selector of m[1].split(",")) {
      const trimmed = selector.trim();
      if (!/^\.[a-zA-Z][\w-]*$/.test(trimmed)) continue;
      const name = trimmed.slice(1);
      const entry = map.get(name) ?? new Map<string, string>();
      for (const d of decls) if (!entry.has(d[1].trim())) entry.set(d[1].trim(), d[2].trim());
      map.set(name, entry);
    }
  }
  return map;
}

function utilityProps(token: string): readonly string[] {
  for (const [pattern, props] of UTILITY_PROPS) if (pattern.test(token)) return props;
  return [];
}

describe("the bundle's classes are not overpainted by utilities", () => {
  it("finds no element carrying a designer class and a utility that overrules it", () => {
    const owned = bundleClassProps();
    const violations: string[] = [];

    for (const file of walk(SRC)) {
      const rel = path.relative(WEB, file);
      const source = readFileSync(file, "utf8");
      for (const attr of source.matchAll(/class(?:Name)?\s*=\s*(?:"([^"]*)"|\{`([^`]*)`\})/g)) {
        // Split on whitespace only: `sm:p-8` must stay one token so the prefix check sees it.
        const tokens = (attr[1] ?? attr[2] ?? "").split(/\s+/).filter(Boolean);
        const designer = tokens.filter((t) => owned.has(t));
        if (designer.length === 0) continue;

        for (const token of tokens) {
          // A prefixed utility (`sm:`, `hover:`, `max-sm:`) styles a state the bundle never drew.
          if (token.includes(":") || token.includes("${") || owned.has(token)) continue;
          const props = utilityProps(token);
          if (props.length === 0) continue;
          for (const cls of designer) {
            const clash = props.filter((p) => owned.get(cls)?.has(p));
            if (clash.length === 0) continue;
            if (ALLOW.has(`${rel}:${cls}:${token}`)) continue;
            const was = clash.map((p) => `${p}: ${owned.get(cls)?.get(p)}`).join("; ");
            violations.push(`${rel}  .${cls} + \`${token}\`  bundle already sets {${was}}`);
            break;
          }
        }
      }
    }

    expect(
      violations,
      `${violations.length} element(s) carry a bundle class and a utility that overrules it.\n` +
        "Drop the utility and let the bundle apply, or add the line to ALLOW with a reason.\n\n" +
        violations.join("\n"),
    ).toEqual([]);
  });
});
