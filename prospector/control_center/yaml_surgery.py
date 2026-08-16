"""Comment-preserving edits to config.yaml — the T0-3 fix.

`yaml.safe_dump` round-trips the DATA and throws away everything else. Measured on this repo's
config.yaml: 2034 lines in, 981 lines out, **1173 comment lines destroyed** — every calibration
receipt, every founder directive, every "why this number" note, including the revenue decision
parked beside `require_figure_verification`. The console was, on that one axis, less safe than the
CLI it was built to replace.

So the console no longer re-serialises the file. It edits the LINES whose values actually changed
and leaves every other byte alone, which is what `git diff` on a config change should look like.

**The fence is that this refuses far more than it accepts.** Anything it cannot locate as a single
scalar line — a new key, a restructured block, a list of anything but single-key entries — comes
back in `unapplied`, and `write_config` declines the whole save rather than falling back to a
serialiser that would eat the comments. A refusal an operator can read beats a write that silently
loses the estate's calibration record.

Scope, stated plainly (memory: `feedback-no-silent-feature-removal`):
  * scalars at any depth               — edited in place
  * `- name: value` list entries        — edited, removed, and appended in place
  * anything else                      — refused by name, never guessed at
"""
from __future__ import annotations

import re
from typing import Any

import yaml

#: `key:` followed by an optional value and an optional trailing comment.
_KEY_RE = re.compile(r"^(?P<indent> *)(?P<dash>- )?(?P<key>[A-Za-z_][\w.\-]*)\s*:(?P<rest>.*)$")


def _split_comment(rest: str) -> tuple[str, str]:
    """Separate a scalar from its trailing comment WITHOUT breaking a `#` inside a string.

    Naive `rest.split('#')` would truncate `url: "https://x/#frag"` at the fragment, silently
    rewriting a value the operator never touched. Quotes are tracked instead.
    """
    in_single = in_double = False
    for i, ch in enumerate(rest):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            raw = rest[:i]
            # The GAP is returned with the comment, so column alignment survives an edit. A
            # config aligned into columns that loses its alignment on every save produces a diff
            # nobody can read, which is most of why re-serialising was unacceptable.
            # The scalar is stripped on BOTH sides: the leading space after `key:` is separator,
            # not value, and leaving it on made `like[0]` a space — which lost the operator's
            # quoting on every quoted string it rewrote.
            return raw.strip(), raw[len(raw.rstrip()):] + rest[i:]
    return rest.strip(), ""


def _emit(value: Any, like: str = "") -> str:
    """Render a scalar the way YAML would, on one line and with no trailing newline.

    `like` is the scalar text being replaced. Its QUOTING STYLE is carried over when the new
    value is also a string: a URL the operator wrote as `"https://…"` should not silently lose
    its quotes because a different field changed, and a value that needs quoting must keep them.
    """
    if isinstance(value, str) and like[:1] in ('"', "'") and "\n" not in value:
        q = like[0]
        return f"{q}{value.replace(q, q + q if q == chr(39) else chr(92) + q)}{q}"
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return repr(value) if isinstance(value, float) else str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_emit(v) for v in value) + "]"
    text = yaml.safe_dump(value, default_flow_style=True).strip()
    return text.removesuffix("...").strip()


def flatten(obj: Any, prefix: tuple = ()) -> dict[tuple, Any]:
    """Flatten a config into `path -> scalar`.

    A list of single-key dicts — which is exactly the shape of `hard_gates` — flattens to one
    path per entry, so a gate can be addressed by NAME rather than by index. Index-addressing is
    what makes a reordered list read as six changes and rewrite six lines that did not change.
    """
    out: dict[tuple, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(flatten(v, prefix + (str(k),)))
    elif isinstance(obj, list) and obj and all(
            isinstance(e, dict) and len(e) == 1 for e in obj):
        for entry in obj:
            (k, v), = entry.items()
            out[prefix + (str(k),)] = v
    else:
        out[prefix] = obj
    return out


def diff_paths(old: dict, new: dict) -> tuple[dict[tuple, Any], list[tuple], list[tuple]]:
    """(changed, added, removed) as flattened paths."""
    f_old, f_new = flatten(old), flatten(new)
    changed = {p: v for p, v in f_new.items() if p in f_old and f_old[p] != v}
    added = [p for p in f_new if p not in f_old]
    removed = [p for p in f_old if p not in f_new]
    return changed, added, removed


def apply_edits(text: str, edits: dict[tuple, Any],
                removals: tuple[tuple, ...] = ()) -> tuple[str, list[tuple]]:
    """Rewrite only the lines named by `edits`/`removals`. Returns (text, unapplied paths).

    The walk tracks a path stack by indentation, so `spend.daily_cap_usd` cannot be confused with
    `schedule.daily_cap_usd`. A path that never matches a line comes back in `unapplied` — the
    caller's cue to refuse the save, not to fall back to a full re-serialise.
    """
    lines = text.splitlines(keepends=True)
    stack: list[tuple[int, str]] = []
    pending = dict(edits)
    to_remove = set(removals)
    out: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            out.append(line)
            continue
        m = _KEY_RE.match(line.rstrip("\n"))
        if not m:
            out.append(line)
            continue

        indent = len(m.group("indent"))
        # A `- key:` entry belongs to the list its parent key opened, so it sits one level in.
        depth = indent + (2 if m.group("dash") else 0)
        while stack and stack[-1][0] >= depth:
            stack.pop()
        path = tuple(k for _, k in stack) + (m.group("key"),)

        scalar, comment = _split_comment(m.group("rest"))
        opens_block = scalar == ""

        if path in to_remove and not opens_block:
            continue                                  # drop the line entirely
        if path in pending and not opens_block:
            newline = "\n" if line.endswith("\n") else ""
            out.append(f"{m.group('indent')}{m.group('dash') or ''}{m.group('key')}: "
                       f"{_emit(pending.pop(path), scalar)}{comment}{newline}")
            if opens_block:
                stack.append((depth, m.group("key")))
            continue

        out.append(line)
        if opens_block:
            stack.append((depth, m.group("key")))

    unapplied = sorted(pending) + sorted(p for p in to_remove if p not in set(edits))
    # A removal that matched nothing is indistinguishable from one already absent, so it is only
    # unapplied if its line is still there.
    unapplied = [p for p in unapplied if p in pending or _has_path(out, p)]
    return "".join(out), unapplied


def _has_path(lines: list[str], path: tuple) -> bool:
    leaf = path[-1]
    return any(re.match(rf"^ *(- )?{re.escape(leaf)}\s*:", ln) for ln in lines)


def rewrite(text: str, old: dict, new: dict) -> tuple[str, list[str]]:
    """The one entry point: (new_text, problems). `problems` non-empty ⇒ do not write.

    Additions are refused rather than appended. Guessing WHERE a new key belongs in a 2000-line
    annotated file means guessing which comment block it falls under, and a key filed under the
    wrong rationale is worse than a key the operator has to add by hand.
    """
    changed, added, removed = diff_paths(old, new)
    problems = [f"cannot add a new key from the console: {'.'.join(p)}" for p in added]

    text_out, unapplied = apply_edits(text, changed, tuple(removed))
    problems += [f"could not locate a single scalar line for: {'.'.join(p)}" for p in unapplied]

    if not problems:
        # The write is only safe if re-parsing the edited text yields exactly the intended config.
        # Line surgery that produces valid YAML with the WRONG value is the failure this catches.
        try:
            if yaml.safe_load(text_out) != new:
                problems.append("the edited file does not re-parse to the intended config — "
                                "refusing to write (this is the surgical writer failing safe)")
        except yaml.YAMLError as exc:
            problems.append(f"the edited file is not valid YAML: {exc}")

    return text_out, problems
