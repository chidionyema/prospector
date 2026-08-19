import { readFileSync } from 'node:fs';
import path from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * THE GATES HAVE TO BE WIRED, NOT JUST INSTALLED.
 *
 * Everything this file checks is a thing that was, at some point, present and inert:
 *
 *   - `test:e2e:coreloop` ran `playwright test --project=coreloop` against a config that defines
 *     no such project. It could only ever exit 1, and nothing called it, so nobody found out.
 *     THAT is the first test below, generalised: every `--project=` in package.json must name a
 *     project the config actually defines.
 *   - Store.Web had a full eslint config with jsx-a11y as errors and no `npm run lint` in CI, so
 *     it linted nothing for months (see the comment in ci.yml's nextjs job).
 *   - The vitest suite had no enforcement point either, for the same reason.
 *
 * A tool installed and not run is worse than no tool: it reads as covered.
 */
const WEB = path.resolve(__dirname, '../..');
const REPO = path.resolve(WEB, '../../..');

const pkg = JSON.parse(readFileSync(path.join(WEB, 'package.json'), 'utf8')) as {
  scripts: Record<string, string>;
  devDependencies: Record<string, string>;
};
const playwrightConfig = readFileSync(path.join(WEB, 'playwright.config.ts'), 'utf8');
const stylelintConfig = readFileSync(path.join(WEB, 'stylelint.config.mjs'), 'utf8');
const ci = readFileSync(path.join(REPO, '.github/workflows/ci.yml'), 'utf8');
const smoke = readFileSync(path.join(REPO, '.github/workflows/e2e-live-smoke.yml'), 'utf8');

const definedProjects = [...playwrightConfig.matchAll(/name: '([a-z0-9-]+)'/g)].map((m) => m[1]);

describe('playwright projects', () => {
  it('defines the four projects the scripts drive', () => {
    expect(definedProjects).toEqual(
      expect.arrayContaining(['chromium', 'a11y', 'visual-mobile', 'visual-desktop']),
    );
  });

  it('never lets a script name a project that does not exist', () => {
    const named = Object.entries(pkg.scripts).flatMap(([script, cmd]) =>
      [...cmd.matchAll(/--project=([a-z0-9-]+)/g)].map((m) => ({ script, project: m[1] })),
    );
    // If this array is ever empty the assertion below is vacuous, which is its own failure.
    expect(named.length).toBeGreaterThan(0);
    for (const { script, project } of named) {
      expect(definedProjects, `${script} drives --project=${project}, which no config defines`).toContain(project);
    }
  });

  it('keeps the deploy smoke to the smoke', () => {
    // `npm run test:e2e` gates the post-deploy live smoke. A stale screenshot baseline or an axe
    // finding must not be able to turn that red: they are reported by their own jobs.
    expect(pkg.scripts['test:e2e']).toContain('--project=chromium');
    expect(playwrightConfig).toMatch(/testIgnore: NOT_THE_SMOKE/);
    expect(playwrightConfig).toMatch(/'\*\*\/a11y\.spec\.ts', '\*\*\/visual\.spec\.ts'/);
  });
});

describe('the CI wiring', () => {
  it('lints CSS on every web change', () => {
    expect(ci).toContain('npm run lint:css');
  });

  it('runs axe-core against the live site after every deploy', () => {
    expect(smoke).toContain('npm run test:a11y');
  });

  it('runs the Lighthouse budgets against the live site', () => {
    expect(smoke).toContain('npm run test:lighthouse');
  });

  it('only ever regenerates visual baselines on an explicit dispatch', () => {
    // The baseline job commits to the repo. It must never be reachable from the schedule or from
    // the post-deploy trigger, or a scheduled run could rewrite the thing it is checking.
    expect(smoke).toMatch(
      /if: \$\{\{ github\.event_name == 'workflow_dispatch' && inputs\.update_visual_baselines \}\}/,
    );
  });
});

describe('stylelint', () => {
  it('leaves the byte-locked design bundle alone', () => {
    // src/styles/mumchimp.css is the shipped bundle and a test pins it byte for byte. Linting a
    // file nobody may edit produces only findings nobody may act on.
    expect(stylelintConfig).toContain("'src/styles/mumchimp.css'");
  });

  it('is driven by a script', () => {
    expect(pkg.scripts['lint:css']).toContain('stylelint');
    expect(pkg.scripts.verify).toContain('lint:css');
  });
});

describe('the tools are actually installed', () => {
  it.each([
    ['@axe-core/playwright', 'runtime accessibility'],
    ['stylelint', 'CSS linting'],
    ['@lhci/cli', 'Lighthouse budgets'],
    ['@testing-library/react', 'component behaviour tests'],
    ['eslint-plugin-tailwindcss', 'class-string hygiene'],
    ['storybook', 'component isolation'],
  ])('%s is a devDependency (%s)', (name) => {
    expect(pkg.devDependencies[name]).toBeTruthy();
  });
});
