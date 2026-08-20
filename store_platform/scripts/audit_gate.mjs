#!/usr/bin/env node
/**
 * THE DEPENDENCY AUDIT GATE.
 *
 * WHY THIS EXISTS. On 2026-08-19 `main` went red because `npm audit --audit-level=high` found
 * 13 advisories in this tree. The fix that landed (PR #434) changed the command to
 * `npm audit --audit-level=high --omit=dev`. That turned CI green without changing a single
 * dependency. The founder's verdict was exact: "that fixed the build, not the issues the build
 * was complaining about."
 *
 * The real defect in that fix is not that it tolerated 13 known advisories. It is that
 * `--omit=dev` is not a decision about those 13 -- it is a permanent instruction to stop looking
 * at the dev tree at all. Every future dev advisory, including a genuinely dangerous one, lands
 * silent. A build-time package is not harmless: it executes on the CI runner, in the repo, with
 * whatever the job can reach. Narrowing the scanner is how you stop hearing about that class,
 * not how you become safe from it.
 *
 * SO THE GATE AUDITS THE WHOLE TREE AGAIN, and every advisory it will not fail on has to be
 * named, one line each, with a reason and a date, in `audit-allowlist.json`. Anything not on
 * that list at `--audit-level` or above fails the build, exactly as before.
 *
 * THREE WAYS THIS FAILS, and each of them is the point:
 *
 *  1. AN UNLISTED ADVISORY. A new vulnerable package arrives -> red. This is the check
 *     `--omit=dev` made impossible.
 *  2. AN EXPIRED EXCEPTION. Every entry carries `review_by`. Past that date it stops counting
 *     and the build goes red. An exception with no expiry is not an exception, it is a deletion
 *     with extra words -- it survives because nobody is ever reminded to look at it again.
 *  3. AN EXCEPTION THAT IS NO LONGER NEEDED. When upstream finally publishes a patch and the
 *     advisory leaves the tree, its entry is stale and the build goes red asking for the line
 *     to be deleted. Without this the list only ever grows, and a list that only grows is
 *     `--omit=dev` written out longhand.
 *
 * Usage: node scripts/audit_gate.mjs [--audit-level=high]
 */
import { execFileSync } from 'node:child_process';
import { readFileSync, existsSync } from 'node:fs';

const LEVELS = ['info', 'low', 'moderate', 'high', 'critical'];
const levelArg = process.argv.find((a) => a.startsWith('--audit-level='));
const MIN = levelArg ? levelArg.split('=')[1] : 'high';
if (!LEVELS.includes(MIN)) {
  console.error(`audit-gate: unknown --audit-level=${MIN}`);
  process.exit(2);
}
const atLeastMin = (sev) => LEVELS.indexOf(sev) >= LEVELS.indexOf(MIN);

// `npm audit` exits non-zero WHENEVER it finds anything, so its exit code cannot be the verdict
// here -- the verdict is ours. Capture stdout regardless and let a JSON parse failure be the
// thing that stops the build, because "the audit did not run" must never read as "the audit
// found nothing" (that is the same silence this gate exists to remove).
let raw;
try {
  raw = execFileSync('npm', ['audit', '--json'], { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 });
} catch (err) {
  raw = err.stdout;
}
let report;
try {
  report = JSON.parse(raw);
} catch {
  console.error('audit-gate: `npm audit --json` produced no parseable report. Refusing to pass.');
  console.error(String(raw).slice(0, 2000));
  process.exit(2);
}

// One advisory can appear under several package keys (the root vulnerable package and everything
// that depends on it), so collect by GHSA id -- the identity a human actually decides about.
const found = new Map();
for (const [pkg, v] of Object.entries(report.vulnerabilities ?? {})) {
  for (const via of v.via ?? []) {
    if (typeof via !== 'object' || !via.url) continue;
    const ghsa = via.url.split('/').pop();
    if (!found.has(ghsa)) {
      found.set(ghsa, { ghsa, severity: via.severity, title: via.title, pkg: via.name ?? pkg, paths: new Set() });
    }
    found.get(ghsa).paths.add(pkg);
  }
}

const ALLOW_PATH = 'audit-allowlist.json';
let allow = [];
if (existsSync(ALLOW_PATH)) {
  const parsed = JSON.parse(readFileSync(ALLOW_PATH, 'utf8'));
  allow = parsed.accepted ?? [];
}
// The clock is the CI run's own date. There is no way to freeze it, which is the intent:
// an exception cannot be renewed by doing nothing.
const today = new Date().toISOString().slice(0, 10);
const allowById = new Map(allow.map((a) => [a.ghsa, a]));

const unlisted = [];
const expired = [];
for (const adv of found.values()) {
  if (!atLeastMin(adv.severity)) continue;
  const entry = allowById.get(adv.ghsa);
  if (!entry) unlisted.push(adv);
  else if (entry.review_by < today) expired.push({ ...adv, entry });
}
const stale = allow.filter((a) => !found.has(a.ghsa));

const say = (adv) => `  ${adv.severity.padEnd(8)} ${adv.ghsa}  ${adv.pkg}\n            ${adv.title}\n            via: ${[...adv.paths].sort().join(', ')}`;

let bad = false;
if (unlisted.length) {
  bad = true;
  console.error(`\naudit-gate: ${unlisted.length} advisor${unlisted.length === 1 ? 'y' : 'ies'} at ${MIN}+ with no recorded decision:\n`);
  unlisted.forEach((a) => console.error(say(a)));
  console.error(`\n  Fix the dependency if a patched version exists. If none does, add an entry to
  ${ALLOW_PATH} saying why this is survivable and when it gets looked at again.\n`);
}
if (expired.length) {
  bad = true;
  console.error(`\naudit-gate: ${expired.length} accepted advisor${expired.length === 1 ? 'y is' : 'ies are'} past review (today is ${today}):\n`);
  expired.forEach((a) => console.error(`${say(a)}\n            review_by ${a.entry.review_by} -- recheck for an upstream patch, then move the date or drop the dependency.`));
}
if (stale.length) {
  bad = true;
  console.error(`\naudit-gate: ${stale.length} accepted advisor${stale.length === 1 ? 'y is' : 'ies are'} no longer in this tree. Delete ${stale.length === 1 ? 'it' : 'them'} from ${ALLOW_PATH}:\n`);
  stale.forEach((a) => console.error(`  ${a.ghsa}  ${a.package ?? ''}`));
}

if (bad) process.exit(1);

const accepted = [...found.values()].filter((a) => atLeastMin(a.severity)).length;
console.log(`audit-gate: clean at ${MIN}+. ${accepted} advisor${accepted === 1 ? 'y' : 'ies'} accepted on the record, 0 unlisted.`);
