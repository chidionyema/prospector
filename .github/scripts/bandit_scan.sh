#!/usr/bin/env bash
# Bandit over the Python we wrote, gated on HIGH severity only. Lifted out of ci.yml so the
# python job can run it alongside the test suite instead of after it: the scan reads the
# checkout and nothing else, so it shares no state with pytest.
#
# The HIGH-only threshold is a measurement, not a preference. On origin/main at da0d9589 the
# full scan reported 361 findings. Fourteen were HIGH: thirteen were sha1 or md5 hashing
# content to make a cache key, a dedup key or an ETag, and one was real — `scripts/ops_state.py`
# ran `whois … | grep …` through a shell.
#
# The thirteen are fixed by saying so in code, `usedforsecurity=False`, not by switching the
# check off. The digest is byte-identical either way; the flag is the language's own way to
# state that a hash is an identifier and not a security decision. That is what leaves the rule
# armed: a NEW sha1 that really does authenticate something still fails here. Adding B324 to a
# skip list would have disarmed it permanently.
#
# The other 347 are MEDIUM and LOW and are printed, not enforced. The largest groups are
# B603/B404/B607 (this repo shells out to git, fly and gh by design, 189 of them) and B310
# urllib (39). Walling the gate on those would mean 347 suppression comments on the first day,
# which teaches everyone to write `# nosec` and stops anyone reading it.
#
# --python matters and is not tidiness. uvx builds its own environment, and by default that was
# Python 3.11.15 while this repo runs 3.14.6. On 3.11 bandit could not parse
# tools/experiments/g_generation_ab.py and skipped it, reporting "syntax error while parsing AST
# from file" into a JSON field nothing read. A skipped file is an unscanned file, so this pins
# the interpreter AND fails if bandit's `errors` array is non-empty.
#
# `python` below is the shared venv's, put on PATH by the "in a shared venv" step. That step
# runs BEFORE the Test suite step that launches this one, and GITHUB_PATH applies to every step
# after the one that writes it, so the interpreter is there. It is only used to read bandit's
# own JSON. `uvx --python 3.14 python -` is NOT the same thing and does not work: uvx reads the
# first word as a TOOL to install, and there is no package called `python`, so it fails with
# "Because python was not found in the package registry".
#
# `scripts/claude_guards/` is excluded, and it is the only exclusion. It is a MIRROR: a
# byte-for-byte copy of the hook scripts under `~/.claude`, kept so the way this estate is
# worked survives a lost laptop. Its single guarantee is that the file here IS the file the
# hook runs, and that collapses the moment anything in this repo rewrites one side. So the
# repo cannot fix a finding in it, which makes scanning it a gate nobody can ever clear.
# `ruff.toml` excluded it for the same reason and says so at the same length.
#
# The two findings this hides, both in memory-loop.py, are real and neither is a hole here:
# B324 sha1 at :91 makes a 12-character checkpoint filename out of a summary, and B602
# shell=True at :151 runs an operator-authored probe command from the agent's own settings
# on the agent's own laptop. Nothing in this repo executes either line. The place to fix
# them is `~/.claude/scripts/memory-loop.py`, after which the mirror carries the fix.
#
# The gate stays armed everywhere else, including on anything NEW under scripts/ that is not
# the mirror. If a second mirror directory is ever added, add it here deliberately rather
# than widening this to `scripts`.
set -eu

: "${PYTHON_VERSION:?PYTHON_VERSION must be set}"
OUT=/tmp/bandit-all.json
NOT_OURS=scripts/claude_guards

uvx --python "${PYTHON_VERSION}" bandit \
  -r prospector ops scripts tools -q -f json -o "$OUT" -x "$NOT_OURS" || true

[ -s "$OUT" ] || { echo "::error::bandit wrote no report, so nothing was scanned"; exit 1; }

python - "$OUT" <<'PY'
import collections, json, sys
report = json.load(open(sys.argv[1]))
skipped = report["errors"]
if skipped:
    for e in skipped:
        print(f"::error::bandit could not read {e['filename']}: {e['reason']}")
    sys.exit("bandit skipped a file, so it did not scan it")
rows = report["results"]
by = collections.Counter((r["issue_severity"], r["test_id"]) for r in rows)
print(f"{len(rows)} findings, not enforced below HIGH:")
for (sev, tid), n in by.most_common():
    print(f"  {sev:<6} {tid} {n}")
PY

uvx --python "${PYTHON_VERSION}" bandit \
  -r prospector ops scripts tools -q --severity-level high -x "$NOT_OURS" \
  || { echo "::error::Bandit found a HIGH severity issue. If the hash is an identifier"
       echo "::error::rather than a security decision, pass usedforsecurity=False."
       exit 1; }
echo "no HIGH severity findings"
