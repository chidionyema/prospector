#!/usr/bin/env bash
# pip-audit against the Python Advisory Database. Lifted out of ci.yml so the python job can run
# it alongside the test suite: it reads the shared venv that the suite also reads, and neither
# writes to it.
#
# It reads a frozen list rather than requirements.txt on purpose: freeze reports what the job
# will actually import, pins and transitive packages included, and needs no resolution step.
# requirements.txt would miss an advisory that arrives through a dependency of a dependency,
# which is how both of the .NET advisories this repo has carried arrived.
#
# The grep drops the two line shapes pip-audit cannot read: `-e <path or VCS url>` and
# `name @ file:///...`. Both name a checkout rather than a released version, so there is no
# advisory to look up, and pip-audit does not skip them — it aborts the whole run with "is not a
# valid editable requirement" and audits nothing. Measured on the founder's laptop: three such
# lines out of 121, and the step failed outright until they were cut. CI builds its venv from
# requirements.txt alone and has none of them, which is exactly why this would only ever have
# broken locally.
#
# Measured 2026-08-19 on origin/main: "No known vulnerabilities found". This goes in green.
#
# `uv pip freeze`, not `python -m pip freeze`. The shared venv is built by `uv venv`, and uv does
# not install pip into a venv it creates. So the first form is a ModuleNotFoundError in the only
# environment this ever runs in:
#
#   .../ci-venvs/py3.14-e49c923ecd1f4b82/bin/python: No module named pip
set -euo pipefail

uv pip freeze > /tmp/all-packages.txt
# grep exits 1 when it filters everything out, which under pipefail would read as a scan failure
# rather than an empty list. The floor below is what actually grades it.
grep -vE '^-e|@ ' /tmp/all-packages.txt > /tmp/frozen.txt || true
n="$(wc -l < /tmp/frozen.txt | tr -d ' ')"
echo "packages audited: $n of $(wc -l < /tmp/all-packages.txt | tr -d ' ')"
# A scan of an empty list passes and reports nothing. Measured on origin/main the venv holds 121
# packages, so under 20 means uv read a different environment rather than that this repo got
# smaller. This is the check that proves the scan and the suite share one venv, which is the
# whole reason it is safe to run the two at the same time.
[ "$n" -ge 20 ] || { echo "::error::froze $n packages, so this is not the venv the suite runs"; exit 1; }
# nltk 3.10.3 carries GHSA-8mgp-746c-j5xp (path traversal in the model-artifact loaders: nltk.data
# and nltk.download). No fixed release exists on PyPI as of 2026-09-03, and this repo imports only
# nltk.stem.PorterStemmer (prospector/retrieval.py), which never opens an artifact. The ignore is
# pinned to that exact version so it expires by itself: the first freeze that carries a newer
# nltk audits it in full, and a stale ignore never hides a later advisory.
ignore=()
if grep -qix 'nltk==3.10.3' /tmp/frozen.txt; then
  echo "nltk==3.10.3 frozen: GHSA-8mgp-746c-j5xp ignored (PorterStemmer only; no model-artifact API used)"
  ignore=(--ignore-vuln GHSA-8mgp-746c-j5xp)
fi
uvx pip-audit -r /tmp/frozen.txt "${ignore[@]}"
