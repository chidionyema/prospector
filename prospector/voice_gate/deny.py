"""Voice Gate — phase-0 deterministic deny gate for the evidence-export lane (spec §2/§7).

The wall the eight previous controls never built: nothing crosses from engine store to
storefront data without passing here. Patterns come from `prospector/voice_policy.yaml`
(the same file the Rust core reads), never from code, so the two runtimes cannot drift.

The 2026-09-06 boundary decision is load-bearing: EE rules fire on PROSE fields only and
never on enum/category fields (`gate`, `gateLabel`, `verdict`) — `gate: "SUPPORTED"` is
structured data, not copy, and firing on it would brick the export.

`excise` is the scrub: drop the sentences that carry engine-speak, keep the rest. Deletion,
not invention — a scrubber that writes new claims would be worse than the leak.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from ..register_lint import sentences

POLICY = Path(__file__).resolve().parent.parent / "voice_policy.yaml"

#: Enum/category fields a deny pattern never fires on (the phase-0 boundary decision).
EXCLUDE_FIELDS = frozenset({"gate", "gatelabel", "verdict"})


@dataclass(frozen=True)
class Finding:
    rule_id: str
    message: str
    start: int
    end: int


@dataclass(frozen=True)
class _Rule:
    id: str
    message: str
    is_phrase: bool
    re: re.Pattern


#: Stop word for a phrase body: the register_lint lookbehind/lookahead boundary is
#: word-or-hyphen on both sides. regex-automata has no lookaround, so the Rust engine
#: emits `(?:^|[^\w-]){body}(?:[^\w-]|$)` and reports the inner capture. deny.py must
#: mirror that exactly — same guards, same inner-span report — or the corpus diff rings.
#: Apostrophes: register_lint `_normalise` maps the three curly forms to straight before
#: matching; re-expressed position-preservingly, a straight `'` in the phrase also accepts
#: them, so a span keeps pointing at the source bytes.
_CURLY_APOS = "\u2018\u2019\u201b"  # ‘ ’ ‛


def _compile_phrase(phrase: str) -> re.Pattern:
    """Compile a register_lint lexicon phrase to the DFA-safe guarded form."""
    tokens = phrase.strip().split()
    body = []
    for tok in tokens:
        escaped = re.escape(tok)
        if "'" in escaped:
            escaped = escaped.replace("'", f"['{_CURLY_APOS}']")
        body.append(escaped)
    inner = r"\s+".join(body)
    # group 1 holds the guards-free phrase; case-insensitive, no multiline (register_lint
    # compiles phrases with re.I only).
    return re.compile(rf"(?:^|[^\w-])({inner})(?:[^\w-]|$)", re.I)


def _compile(entry: dict) -> _Rule:
    if "phrase" in entry:
        return _Rule(entry["id"], entry["message"], True, _compile_phrase(entry["phrase"]))
    pat = entry["pattern"]
    # patterns: case-insensitive by default (flag "i"), always multiline (legacy behaviour
    # every EE rule already runs under); phrase rules are case-insensitive only.
    mode = re.M | (re.I if "i" in entry.get("flags", "i") else 0)
    return _Rule(entry["id"], entry["message"], False, re.compile(pat, mode))


def _load_rules(lane: str = "evidence-export") -> list[_Rule]:
    doc = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    lanes = doc["lanes"]
    entries: list[dict] = []
    for parent in lanes[lane].get("inherit", []) or []:
        entries.extend(lanes[parent].get("deny_patterns", []) or [])
    entries.extend(lanes[lane].get("deny_patterns", []) or [])
    return [_compile(p) for p in entries]


_RULES = _load_rules()


def findings_for(text: str) -> list[Finding]:
    """Every deny-pattern or deny-phrase hit in one string, rule order then span order."""
    out: list[Finding] = []
    for rule in _RULES:
        for m in rule.re.finditer(text):
            s, e = m.span(1) if rule.is_phrase else (m.start(), m.end())
            out.append(Finding(rule.id, rule.message, s, e))
    return out


def grade_fields(fields: dict[str, str]) -> dict[str, list[Finding]]:
    """Grade named prose fields; enum fields are never graded. Empty = clean."""
    return {
        name: hits
        for name, text in fields.items()
        if name.lower() not in EXCLUDE_FIELDS and (hits := findings_for(text))
    }


def excise(text: str) -> tuple[str, list[str]]:
    """Drop sentences carrying a finding; return (clean_text, dropped_sentences)."""
    kept, dropped = [], []
    for sentence in sentences(text):
        (dropped if findings_for(sentence) else kept).append(sentence)
    return " ".join(kept).strip(), dropped


#: Leaf keys that hold enums, identifiers or citations, never prose. Grading them would
#: brick exports on structured data — the phase-0 boundary decision, generalised to walks.
ENUM_LEAF_KEYS = frozenset(
    {
        "verdict",
        "gate",
        "gatelabel",
        "key",
        "id",
        "url",
        "domain",
        "verifiedat",
        "decisive",
        "confidence",
        "type",
        "tag",
        "supported",
        "total",
        "sourcecount",
    }
)

_DOMAIN_RE = re.compile(r"^[a-z0-9.-]+\.(com|org|uk|net|gov|io)$", re.I)


def walk_prose(node, path: str = "$", parent=None, key=None):
    """Yield (parent, key, path, text) for every prose string leaf in a JSON-shaped tree.

    Skips enum/identifier leaves (ENUM_LEAF_KEYS), URLs and bare domains. Everything else —
    at any depth, in any block structure — is prose the gate must see. The export gate and
    the live-file scrub both walk with this, so a new section of the report can never again
    sneak engine text past a hand-maintained field list (the 2026-09-06 excerpt/withheld miss).
    """
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, str):
                if (
                    k.lower() in ENUM_LEAF_KEYS
                    or v.startswith(("http://", "https://"))
                    or _DOMAIN_RE.match(v)
                ):
                    continue
                yield node, k, f"{path}.{k}", v
            else:
                yield from walk_prose(v, f"{path}.{k}", node, k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            if isinstance(v, str):
                if v.startswith(("http://", "https://")) or _DOMAIN_RE.match(v):
                    continue
                yield node, i, f"{path}[{i}]", v
            else:
                yield from walk_prose(v, f"{path}[{i}]", node, i)
