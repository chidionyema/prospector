# Code quality gates

What CI refuses to merge, in all three languages, and why each gate is set where it is.

Every gate named here is a step in `.github/workflows/ci.yml`. The line numbers are given so
you can read the step rather than trust this page. When a gate moves, this page is wrong and
the workflow is right.

The rule this page follows: **a gate is only real if it fails.** Every gate below was proved
by breaking the thing it guards and watching the step exit non-zero. Where a check could not
be made to fail, it was deleted rather than left in place looking like protection.

---

## Python

| Gate | Where | Fails on |
| --- | --- | --- |
| `ruff check` | `scripts/popdd_verify.py:166`, repo-wide | any lint error, anywhere in the repo |
| Test suite | `ci.yml:454` | any failing test |
| Golden-set regression | `ci.yml:495` | mixed-sector discrimination regression |
| Bandit security scan | `ci.yml:521` | any HIGH severity finding, or any file bandit could not read |
| Dependency advisory scan | `ci.yml:565` | any published advisory against a frozen package |

### Bandit

Armed at HIGH only. Everything below HIGH is printed as a table and not enforced, so the
count is visible without walling the build. Measured on the current tree: **348 findings
total, 0 at HIGH.**

Two things about this step are deliberate.

**It pins the interpreter.** The step runs `uvx --python "${PYTHON_VERSION}" bandit`. Without
the pin, `uvx` picked Python 3.11.15 while this repo is 3.14.6, and
`tools/experiments/g_generation_ab.py` came back as "syntax error while parsing AST from
file". Bandit does not fail on that. It records the file in an `errors` array in its JSON and
carries on, so the run was green while one file had not been scanned at all. A skipped file is
an unscanned file.

**It fails when bandit skips anything.** The step reads that `errors` array and exits non-zero
if it is not empty, naming each file. Measured after the pin: `errors: []`.

The 14 HIGH findings that existed before this gate went in were cleared without disarming a
rule:

- **13 were B324**, `hashlib.sha1()` or `md5()` used to build an identifier — a cache key, a
  dedup key, a claim lock. Each site got `usedforsecurity=False` rather than a skip-list entry.
  The digest is byte-identical either way (proved before the change). The difference is that a
  skip-list disarms B324 for the whole repo forever, while the annotation leaves it armed, so a
  *new* sha1 written for a security decision still fails. Sites:
  `prospector/claim_lock.py:174`, `prospector/generate.py:777`, `prospector/landscape.py:80`,
  `prospector/markets.py:108`, `prospector/models.py:119`,
  `prospector/ops/config_editor.py:150`, `prospector/ops/console_api.py:2905`,
  `prospector/retrieval.py:2045`, `prospector/run.py:472`,
  `prospector/scheduler/guard.py:183`, `scripts/backup_store.py:378` and `:703`,
  `scripts/graphify_sweep.py:203`.
- **1 was real.** `scripts/ops_state.py` ran `whois mumchimp.com | grep -iE ...` through a
  shell. The shell was removed and the filtering moved into Python. That fixed a second,
  unrelated bug in the same line: a pipeline reports the exit status of its **last** stage, so a
  `whois` that answered perfectly well but matched no line returned grep's `1`, and the probe
  printed `UNREACHABLE`. It now reports:
  `Registry Expiry Date: 2027-06-16T13:21:27Z | Registrar: 123-Reg Limited | Name Server: ...`

### Dependency advisories

`pip-audit` against `pip freeze`, with editable and local requirements filtered out first.
See `ci.yml:565` for the exact command.

The filter is required, not tidiness. `pip-audit` **aborts** on an editable or local
requirement line rather than skipping it. Three lines out of 121 did that here
(two `-e` lines and one `file:///` line), and the whole audit failed with
`is not a valid editable requirement`. An aborted audit audits nothing, and it is easy to read
the abort as noise.

Once it actually ran, it was not clean. It found six advisory rows across two transitive
packages nothing in this repo imports directly:

| Package | Advisories | First patched | Arrives through |
| --- | --- | --- | --- |
| pillow 12.2.0 | PYSEC-2026-3493, PYSEC-2026-3494 | 12.3.0 | fpdf2, streamlit |
| pyasn1 0.6.3 | PYSEC-2026-3455, -3456, -3457 | 0.6.4 | pyasn1_modules |

Both are now pinned in `requirements.txt` with a comment saying to delete the pin once the
package in front of it moves on its own. `uv pip install --dry-run` for the pinned versions
resolved in 81ms with no other package moving.

---

## .NET

| Gate | Where | Fails on |
| --- | --- | --- |
| MSBuild props files parse | `ci.yml:736` | any `Directory.*.props` that is not well-formed XML |
| Roslyn analyzers | `TreatWarningsAsErrors` in the projects | any analyzer warning |
| Test | `ci.yml:769` | any failing test |
| Vulnerable dependency scan | `ci.yml:788` | any package with a known advisory |

Current state: `0 Warning(s) 0 Error(s)`, `Passed! - Failed: 0, Passed: 365, Skipped: 0`.

### The props parse gate, and why it is not a test

`Directory.Packages.props` turns on Central Package Management for the whole solution. Two
hyphens in a row inside an XML comment make the file unparseable, and MSBuild then behaves as
if central package management simply is not on.

This is worth reading before you debug it the hard way, because the error output points
somewhere else entirely:

- `dotnet restore Store.sln` printed **NU1604, "does not contain an inclusive lower bound",
  twenty-one times** — once per centrally-versioned package across all three projects — and not
  one line naming `Directory.Packages.props`.
- `dotnet build` on the same broken tree **did** name it: `MSB4024`, with the file, line and
  column.

Restore runs first, fails first, and blames the dependencies. That is why the first diagnosis
went to the packages.

The guard was first written as a C# test, `EveryBuildPropsFileIsWellFormedXml`. It was inert,
and proved inert the same day: with the props file broken, MSBuild will not evaluate
`Store.Tests.csproj`, so `dotnet test --no-build --filter EveryBuildPropsFileIsWellFormedXml`
printed `MSB4024` and nothing else. The test assembly never loaded. **A guard has to fail on
the assertion, not before it.** The test was deleted, not left in place.

The check is now a CI step that runs **before** `dotnet restore`, which is the only place that
can see the problem. Mutation-proved: with the two hyphens reinserted, the step exits 1 and
names the file, line 47 column 15.

`store_platform/src/Store.Tests/BuildFiles/BuildFileTests.cs` keeps the two assertions a test
*can* make — that `ManagePackageVersionsCentrally` and `CentralPackageTransitivePinningEnabled`
are both on.

### Transitive pinning

`CentralPackageTransitivePinningEnabled` is on because it is the only way to patch an advisory
that sits behind a package on a local feed. `Crux.Observability 1.0.0` is the case here: it
cannot be rebuilt from this repo, so the packages underneath it are pinned centrally instead —
`SQLitePCLRaw.lib.e_sqlite3 2.1.13`, and the four `OpenTelemetry` packages at `1.15.3`.

### The scan step must grep

`dotnet list package --vulnerable` **always exits 0**, whether or not it found anything. The CI
step greps its output for `has the following vulnerable packages` and fails on a match. A step
that only checked the exit code would be permanently green.

---

## TypeScript / Next.js

Two apps, `store_platform/src/Store.Web` and `store_platform/src/Ops.Console`, with the same
gates.

| Gate | Where | Fails on |
| --- | --- | --- |
| `tsc --noEmit` | `ci.yml:848` / `:947` | any type error |
| ESLint (incl. `@next/eslint-plugin-next`) | `ci.yml:871` / `:950` | any lint error |
| Unit tests (vitest) | `ci.yml:877` / `:953` | any failing test |
| Dependency advisory scan | `ci.yml:891` / `:967` | `npm audit --audit-level=high` |
| Build | `ci.yml:895` / `:971` | any build failure |

Both apps measure clean today: `npm audit` "found 0 vulnerabilities", `tsc --noEmit` exit 0.

Watch the pipe when you run a build by hand. `npm run build 2>&1 | tail` reports **tail's**
exit status, so a failed build reads as `exit 0`. Capture the build's own status before any
pipe.

---

## Deliberately not adopted

Each of these was installed and run against the real tree. The number in the last column is
what decided it. None of them is rejected on principle; each is waiting for someone to do the
work the number describes.

| Tool | What it would do | Measured | Decision |
| --- | --- | --- | --- |
| `ruff format` | opinionated auto-format | **678 of 706 files would be reformatted**, 28 already formatted | Not adopted. A 678-file diff buries every real change behind it and makes `git blame` useless for a year. Adopt only as its own commit, with `.git-blame-ignore-revs`, and only when no branch is open. |
| xenon / radon complexity ratchet | fail CI above grade B | **517 of 2810 blocks are grade C or worse** | Not adopted as a gate. A ratchet that fails on day one is not a ratchet. The honest version is a per-file baseline that only forbids getting worse, which is a real piece of work, not a config line. |
| Biome | fast lint and format | duplicates the existing ESLint config, including `@next/eslint-plugin-next` | Not adopted. Two linters disagreeing is worse than one linter being slow. |
| Knip | find unused files, exports, deps | Ops.Console: 1 unused devDependency, 5 unused exports, 8 unused types. Store.Web: about 21 files of unused exported types, 18 duplicate exports | Not adopted as a gate. Useful as a periodic report. It also reported `postcss` as an unlisted dependency, which is a **false positive** — it infers that from the config filename, while `postcss.config.mjs` only references `@tailwindcss/postcss`, which is listed. |
| Sourcery | automated refactoring | not run | Deferred. It proposes rewrites; nothing here is ready to accept machine-authored refactors without review, and review is the scarce thing. |
| Wily | complexity trend over git history | not run | Deferred behind the complexity baseline above. A trend line with no threshold changes no decision. |

---

## A source file git cannot see

While adding `BuildFileTests.cs` it landed in `store_platform/src/Store.Tests/Build/`, and
`.gitignore` line 9 ignores `build/`. This filesystem is case-insensitive
(`core.ignorecase=true`), so git ignored the whole directory.
`git status --untracked-files=all` showed nothing. `git check-ignore -v` was the only thing
that said so.

A source file git ignores is a file no reviewer and no CI job can ever see. The directory was
renamed to `BuildFiles/`, and `tests/unit/test_no_source_file_is_gitignored.py` now fails if
any `.py`, `.cs`, `.ts` or `.tsx` file outside a known generated directory is ignored. Its
second test plants an ignored file and asserts the guard finds it, so the guard cannot quietly
stop looking.

---

## Running the gates locally

```bash
.venv/bin/python scripts/popdd_verify.py --staged
.venv/bin/python -m ruff check .
uvx --python 3.14 bandit -r prospector ops scripts tools -q --severity-level high
cd store_platform && dotnet build Store.sln && dotnet test src/Store.Tests/Store.Tests.csproj --no-build
cd store_platform/src/Ops.Console && npx tsc --noEmit && npm run lint && npm audit --audit-level=high
```

For `pip-audit`, copy the two-line command out of the "Dependency advisory scan" step at
`ci.yml:565` rather than retyping it. The filter in front of it is the part that matters.

Where the pre-commit gate is installed, and how to turn it on and off, is in `CLAUDE.md` under
"Working in a git worktree". Do not trust prose about whether it is on — run
`git config --get core.hooksPath` and look at the hooks directory git actually reads.
