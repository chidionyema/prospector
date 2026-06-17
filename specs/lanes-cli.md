# Spec: Lane Management CLI (`prospector.run lanes`)

## Goal
Add a `lanes` subcommand to `prospector/run.py` that lets the operator manage
ambition lanes from the CLI instead of manually editing `config.yaml`.

## Files to touch
- `prospector/run.py` — add `_manage_lanes()` helper + `_cmd_lanes()` handler + argparse

## Acceptance criteria
- `pytest tests/unit/test_lanes_cli.py -q` exits 0 (all tests pass)
- `pytest -q` still green overall (no regressions)

## Design

### `_manage_lanes(action, lane_name, config_path)` (line 1089, before `_save_discovered_signals`)
A helper that reads `config.yaml` as raw text, edits the `active_lane:` and
`active_lanes:` lines in place, and writes back. Must NOT use `yaml.safe_load` +
`yaml.dump` (would strip comments). Use regex-based line editing.

Actions:
- `"list"`: Read config with `load_config()`, print all defined lanes, active_lane,
  active_lanes. No mutation. Print format:
  ```
  Defined lanes: venture, side_hustle, smb, growth
  active_lane: ""  (multi-lane mode)
  active_lanes: [side_hustle, smb, growth, venture]
  ```

- `"nix"`: Remove `lane_name` from `active_lanes:` line.
  - If `lane_name` not in the list, print warning but exit clean (no-op).
  - After removal, update the YAML line. Empty list → `active_lanes: []`.
  - Print the new active_lanes.

- `"natch"`: Add `lane_name` to `active_lanes:` line (append to end).
  - If already present, print info and exit clean (no-op).
  - Print the new active_lanes.

- `"set"`: Set `active_lane:` to `lane_name`. Also clears `active_lanes: []` 
  (single-lane mode). If `lane_name` is empty string `""`, this is effectively
  "unset" — goes back to multi-lane.
  - Print the new active_lane.

- `"unset"`: Set `active_lane:` to `""` (empty). Goes back to multi-lane mode.
  - Print confirmation.

### Implementation detail — line-based YAML editing
The config.yaml has these lines (exact line numbers vary but the regex patterns are stable):
```yaml
active_lane: ""
active_lanes: [side_hustle, smb, growth, venture]
```

Use `re.sub` with multiline mode to replace these lines. Patterns to match:
- `active_lane:` line: match `^active_lane:\s*"?(.*?)"?\s*$` (multiline)
- `active_lanes:` line: match `^active_lanes:\s*\[(.*?)\]\s*$` (multiline)

For nix/natch: parse the list inside brackets, mutate, rebuild.
For set: replace the active_lane line AND clear active_lanes to `[]`.
For unset: replace active_lane line with `active_lane: ""`.

### `_cmd_lanes(args, log_path)` handler
Parses sub-action from args and calls `_manage_lanes()`.

### Argparse (in `main()`, after `operators` subcommand)
```python
lanes_p = sub.add_parser("lanes", help="Manage ambition lanes (list, nix, natch, set, unset)")
lanes_act = lanes_p.add_subparsers(dest="lanes_action", required=True)

lanes_act.add_parser("list", help="Show all defined lanes and active configuration")

nix_p = lanes_act.add_parser("nix", help="Remove a lane from active_lanes")
nix_p.add_argument("lane", help="Lane name to nix")

natch_p = lanes_act.add_parser("natch", help="Add a lane to active_lanes")
natch_p.add_argument("lane", help="Lane name to natch")

set_p = lanes_act.add_parser("set", help="Set active_lane (single-lane pin; empty = unset)")
set_p.add_argument("lane", nargs="?", default="", help="Lane name (empty to unset; default unset = multi-lane)")

lanes_act.add_parser("unset", help="Clear active_lane (return to multi-lane mode)")
```

### Edge cases
- Nixing a lane not in active_lanes: warn, no-op, exit 0
- Natching a lane already in active_lanes: inform, no-op, exit 0
- Setting to same lane already set: no-op, inform
- Config.yaml missing → error message
- Lane not defined in `lanes:` block → warn but still permit the operation (the
  operator may be adding a lane definition later)

### Verification
```bash
.venv/bin/python -m pytest tests/unit/test_lanes_cli.py -q
```
Must exit 0. The test file `tests/unit/test_lanes_cli.py` already exists with 16 tests
that import `_manage_lanes` and `_resolve_lanes` from `prospector.run`.
