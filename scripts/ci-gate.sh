#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ci-gate.sh — Language-agnostic POPDD CI gate
#
# Reads git diff --name-only between HEAD and a merge-base ref (default: main),
# extracts function/class names from modified .py/.ts/.js/.cs files, then
# checks that each modified function has a corresponding POPDD receipt.
#
# Usage:
#   ./scripts/ci-gate.sh [REF]
#     REF — base ref for merge-base comparison (default: main)
#
# Exit codes:
#   0 — All modified functions have POPDD receipts
#   1 — One or more modified functions lack receipts (list printed)
#   2 — Internal/script error
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REF="${1:-main}"
cd "$(git rev-parse --show-toplevel)" || { echo "Not a git repo."; exit 2; }

exec python3 -c "
import json, os, re, subprocess, sys
from pathlib import Path
from collections import defaultdict

# ── Config ───────────────────────────────────────────────────────────────────
REF = '${REF}'
RECEIPTS_DIR = Path('.lux/receipts')

# ── Git helpers ──────────────────────────────────────────────────────────────

def git(*args: str) -> str:
    return subprocess.check_output(['git', *args], text=True).strip()

def get_changed_files() -> list[str]:
    \"\"\"Return list of files changed between HEAD and merge-base with REF.\"\"\"
    try:
        merge_base = git('merge-base', 'HEAD', REF)
    except subprocess.CalledProcessError:
        print(f'❌ Could not find merge-base with ref \"{REF}\". Does it exist?', file=sys.stderr)
        sys.exit(2)
    output = git('diff', '--name-only', merge_base, 'HEAD')
    return [f for f in output.splitlines() if f]

# ── Function/class extraction ────────────────────────────────────────────────

# Regex patterns keyed by file extension
EXTRACTORS: dict[str, list[re.Pattern]] = {
    '.py': [
        re.compile(r'^def\s+(\w+)\s*\('),                     # def foo(...)
        re.compile(r'^class\s+(\w+)\s*[:\(]'),                # class Foo:
        re.compile(r'^async\s+def\s+(\w+)\s*\('),             # async def foo(...)
    ],
    '.ts': [
        re.compile(r'(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\('),     # function / export function
        re.compile(r'(?:export\s+)?class\s+(\w+)\s*(?:extends|implements|{)?'),  # class / export class
        re.compile(r'(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s*)?\(?.*=>'),  # const foo = (args) => / const foo = async () =>
        re.compile(r'(?:export\s+)?default\s+(?:async\s+)?function\s+(\w+)\s*\('),  # default function / export default function
    ],
    '.js': [
        re.compile(r'(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\('),
        re.compile(r'(?:export\s+)?class\s+(\w+)\s*(?:extends|implements|{)?'),
        re.compile(r'(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s*)?\(?.*=>'),
    ],
    '.cs': [
        re.compile(r'(?:public|private|protected|internal|static|async|virtual|override|abstract|sealed|\s)*\s+(?:class|struct|record)\s+(\w+)'),  # class/struct/record
        re.compile(r'(?:public|private|protected|internal|static|async|virtual|override|abstract|sealed|\s)*\s+\w+\s+(\w+)\s*\('),  # methods
    ],
}

def extract_names(file_path: str) -> set[str]:
    \"\"\"Extract function and class names from a source file.\"\"\"
    _, ext = os.path.splitext(file_path)
    patterns = EXTRACTORS.get(ext)
    if not patterns:
        return set()

    try:
        text = Path(file_path).read_text()
    except (FileNotFoundError, OSError):
        return set()  # File may have been deleted

    names: set[str] = set()
    for line in text.splitlines():
        for pat in patterns:
            m = pat.search(line)
            if m:
                names.add(m.group(1))
    return names

# ── Receipt loading ──────────────────────────────────────────────────────────

def load_receipt_targets() -> set[str]:
    \"\"\"Collect all verified function/class names from receipt files.\"\"\"
    if not RECEIPTS_DIR.is_dir():
        return set()

    targets: set[str] = set()
    for rfile in sorted(RECEIPTS_DIR.glob('*.jsonl')):
        try:
            for line in rfile.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # Accept any 'verify' action with verdict PASS
                if rec.get('action') == 'verify':
                    verdict = rec.get('proof', {}).get('verdict', '')
                    target = rec.get('target', '')
                    if verdict == 'PASS' and target:
                        targets.add(target)
        except OSError:
            continue

    return targets

# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    changed_files = get_changed_files()
    if not changed_files:
        print('✅ No changed files to check.')
        sys.exit(0)

    # Filter to relevant extensions and extract names
    relevant_exts = {'.py', '.ts', '.js', '.cs'}
    modified: dict[str, set[str]] = {}  # file -> {names}
    for f in changed_files:
        _, ext = os.path.splitext(f)
        if ext in relevant_exts:
            names = extract_names(f)
            if names:
                modified[f] = names

    if not modified:
        print('✅ No modified functions/classes found in changed files.')
        sys.exit(0)

    # Load receipts
    receipt_targets = load_receipt_targets()

    # Check each modified function
    missing: list[str] = []
    for filepath, names in sorted(modified.items()):
        for name in sorted(names):
            if name not in receipt_targets:
                missing.append(f'  {name}  (in {filepath})')

    if missing:
        print(f'❌ POPDD Gate FAILED — {len(missing)} function(s) missing receipt(s):')
        print()
        for item in missing:
            print(item)
        print()
        print('   Create specs with: lux spec create <name>')
        print('   Then verify with:  lux spec verify <name>')
        sys.exit(1)
    else:
        print(f'✅ POPDD Gate PASSED — all {sum(len(v) for v in modified.values())} modified function(s)/class(es) have receipts.')
        sys.exit(0)

if __name__ == '__main__':
    main()
"
