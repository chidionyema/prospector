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
    re: re.Pattern


def _load_rules(lane: str = "evidence-export") -> list[_Rule]:
    doc = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    lanes = doc["lanes"]
    patterns: list[dict] = []
    for parent in lanes[lane].get("inherit", []) or []:
        patterns.extend(lanes[parent].get("deny_patterns", []) or [])
    patterns.extend(lanes[lane].get("deny_patterns", []) or [])
    return [
        _Rule(
            p["id"],
            p["message"],
            re.compile(p["pattern"], (re.I if "i" in p.get("flags", "i") else 0) | re.M),
        )
        for p in patterns
    ]


_RULES = _load_rules()


def findings_for(text: str) -> list[Finding]:
    """Every deny-pattern hit in one string, in rule order then span order."""
    out = [
        Finding(rule.id, rule.message, m.start(), m.end())
        for rule in _RULES
        for m in rule.re.finditer(text)
    ]
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
