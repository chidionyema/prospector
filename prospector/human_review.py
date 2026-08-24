"""The human verification layer for the publish path (programme doc §33.8, work item 33-G).

**Why this does not contradict "no human in the loop."** That decision (2026-06-20) is scoped in
`CLAUDE.md` to GENERATION: "Generation may run continuously and unattended (founder decision
2026-06-20: no human in the loop)". This is a gate on the PUBLISH path — a different loop. The
daemon keeps generating and vetting unattended; what changes is only what may reach the shelf
wearing a human-verified claim. Nothing in `scheduler/` has to know this module exists.

**Why it is affordable, which is the only reason it will actually happen.** A layer that asks one
person to read fifty packs does not get done, and a promise resting on a review nobody performs is
worse than no promise at all. So the queue is built from `figure_check`'s output: it lists SPECIFIC
FIGURES, not documents. At the last measurement that is ~19 figures across 15 packs — about twenty
decisions, not fifty document reads. The detector is what makes the human step bounded.

**Four properties this module exists to enforce, each one a way the layer could be fake:**

1. **Absence of a receipt is never verification.** `status()` returns `unreviewed`/`pending` by
   default; nothing is verified implicitly. This is exactly the §33.1 failure repeating one level
   up — copy asserting a guarantee nothing checked — so the default has to be the honest one.
2. **A re-vet invalidates its receipt.** Every receipt records the fingerprint of the item set it
   ruled on. If the engine re-vets a candidate and the untraceable set changes, the fingerprint no
   longer matches and the status drops to `stale`. A receipt that certifies prose written after the
   review is not an audit trail, it is a rubber stamp.
3. **`accepted` is a first-class decision.** `figure_check` is LENIENT on purpose, so false
   positives exist by design. If the reviewer's only options were "repair" or "drop", the layer
   would force a lie or a stall on every false positive. `accepted` records the human's judgement
   that the flag was not a claim about the world, with a note saying why.
4. **Decisions append; they never overwrite.** The latest decision for an item is authoritative,
   but the history stays on disk. A record that can be silently edited is not evidence.

**What `clean` means, and what it does NOT mean.** A pack whose checks flagged no figures gets
`clean` — machine-traceable, no human needed. That is not the same claim as `verified`, and the two
must not share a badge: 35 of 50 packs were clean at measurement and no human has ever read them.
`clean` licenses "every figure traces to a retrieved passage"; only `verified` licenses any wording
involving a person.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .config import store_root


def _default_root() -> Path:
    """Where per-pack receipts live when the caller names no root.

    One file per pack so two reviewers (or a reviewer and the daemon) cannot lose each other's
    writes the way a single shared queue file would.

    Resolved on every call, never bound at import. This used to be the module constant
    `Path("store") / "human_review"`, which names a directory relative to the process working
    directory. The engine image sets `WORKDIR /app` and copies the repo there
    (deploy/engine/Dockerfile:55, :68), so under the daemon that name pointed at the image layer
    every deploy erases instead of at the mounted volume. INC-2026-08-18-store-resolver.
    """
    return store_root() / "human_review"

logger = logging.getLogger(__name__)

#: What a reviewer may conclude about one flagged figure.
ACTIONS: frozenset[str] = frozenset({
    "repaired",   # the figure was wrong; the rationale was corrected
    "sourced",    # the figure is right; a passage supporting it was supplied
    "dropped",    # the claim was removed rather than defended
    "accepted",   # not a claim about the world (matcher false positive) — note required
})

STATUS_CLEAN = "clean"            # the trace ran and flagged nothing; no human needed
STATUS_VERIFIED = "verified"      # every flagged figure has a current decision
STATUS_PENDING = "pending"        # flagged figures still undecided
STATUS_STALE = "stale"            # a receipt exists but the engine re-vetted since
STATUS_UNREVIEWED = "unreviewed"  # flagged figures and no receipt at all
STATUS_UNTRACED = "untraced"      # the trace never ran on this pack — see `is_traced`

#: Statuses a pack may carry and still be offered for sale, when the fence is switched on.
#: `untraced` is deliberately absent: every dossier written before 2026-08-13 predates
#: `CheckResult.untraceable_figures`, so its checks flag nothing — and an empty flag list from a
#: check that never ran the trace is indistinguishable from a clean one unless we look for the field
#: itself. Reading those 2,011 dossiers as `clean` would have certified the exact 15 packs §33
#: measured as dirty. That near-miss is why `is_traced` exists and why `status` fails closed.
SELLABLE: frozenset[str] = frozenset({STATUS_CLEAN, STATUS_VERIFIED})


@dataclass(frozen=True)
class Item:
    """One flagged figure awaiting a human decision."""
    check: str
    figure: str

    @property
    def key(self) -> str:
        return f"{self.check}:{self.figure}"

    def to_dict(self) -> dict[str, str]:
        return {"check": self.check, "figure": self.figure, "key": self.key}


@dataclass
class Decision:
    """A human's ruling on one item. `reviewer` and `note` are required by `record_decision`."""
    key: str
    action: str
    reviewer: str
    note: str
    decided_at: str

    def to_dict(self) -> dict[str, str]:
        return {"key": self.key, "action": self.action, "reviewer": self.reviewer,
                "note": self.note, "decided_at": self.decided_at}


@dataclass
class Receipt:
    """The on-disk record for one pack. `history` is append-only; `current()` resolves the winner."""
    pack_id: str
    fingerprint: str = ""
    history: list[Decision] = field(default_factory=list)

    def current(self) -> dict[str, Decision]:
        """Latest decision per item key. Later entries win; earlier ones stay on disk."""
        out: dict[str, Decision] = {}
        for d in self.history:
            out[d.key] = d
        return out

    def to_dict(self) -> dict[str, Any]:
        return {"pack_id": self.pack_id, "fingerprint": self.fingerprint,
                "history": [d.to_dict() for d in self.history]}


def queue_items(checks: Iterable[Any]) -> list[Item]:
    """Build the review queue from ruled checks.

    Accepts `CheckResult` objects or their `to_dict()` form, because the queue is built both in
    process (right after `verify`) and out of process (from a stored dossier), and a builder that
    only understood one of the two would quietly return an empty queue for the other — which reads
    as `clean`, the most dangerous wrong answer this module can give.
    """
    items: list[Item] = []
    seen: set[str] = set()
    for c in checks or ():
        if isinstance(c, Mapping):
            name = str(c.get("check_name") or c.get("check") or "")
            figs = c.get("untraceable_figures") or []
        else:
            name = str(getattr(c, "check_name", "") or "")
            figs = getattr(c, "untraceable_figures", None) or []
        for f in figs:
            it = Item(check=name, figure=str(f))
            if it.key not in seen:
                seen.add(it.key)
                items.append(it)
    return items


def is_traced(checks: Iterable[Any]) -> bool:
    """Did the figure trace actually RUN on these checks?

    The signal is `untraceable_figures is not None`. `CheckResult` defaults it to `None`, and only
    a completed trace may write a list — so `[]` is a positive claim of cleanliness while `None`
    and a missing key both mean "nobody looked". That distinction is why the field is Optional
    (`models.py:270`): 2,011 dossiers on disk predate the trace, and reading them as clean would
    have certified the exact packs §33 measured as dirty. It also survives a JSON round-trip
    through any loader, which a key-presence test would not.

    Zero checks is `False`: you cannot prove a trace ran from an empty list.
    """
    for c in checks or ():
        val = c.get("untraceable_figures") if isinstance(c, Mapping) else getattr(
            c, "untraceable_figures", None)
        if val is not None:
            return True
    return False


def queue_from_checks(checks: Iterable[Any]) -> tuple[list[Item], bool]:
    """`(queue, traced)` in one call.

    Exists so the two facts cannot be separated by accident. `status` fails closed on `traced`, so
    a caller who forgot it would get `untraced` rather than a false `clean` — but a caller who
    cannot forget it is better than one who fails safely.
    """
    checks = list(checks or ())
    return queue_items(checks), is_traced(checks)


def fingerprint(items: Sequence[Item]) -> str:
    """Stable digest of the item SET.

    Order-independent, because the queue's order is an artifact of check sequencing and a reordered
    re-vet has not invalidated anything. Content-dependent, because a re-vet that flags a DIFFERENT
    figure has: property 2 in the module docstring is enforced entirely by this function.
    """
    keys = sorted({i.key for i in items})
    return hashlib.sha256("\n".join(keys).encode("utf-8")).hexdigest()[:16]


def receipt_path(pack_id: str, root: Path | str | None = None) -> Path:
    return Path(root if root is not None else _default_root()) / f"{pack_id}.json"


def load_receipt(pack_id: str, root: Path | str | None = None) -> Receipt | None:
    """The receipt on disk, or None. A corrupt receipt reads as None — never as verification.

    The fail-closed direction is right and unchanged. What changes is that it stops being
    silent: `status()` (:287) turns None into `unreviewed`, which is the correct and honest
    word for a pack nobody has looked at, and the WRONG one for a pack whose reviewer's
    decisions are sitting in a file we can no longer parse. Only the second is a defect, and
    only the file's existence tells them apart, so that case now logs at ERROR.
    """
    p = receipt_path(pack_id, root)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        if p.exists():
            logger.error("human_review receipt %s exists but is unreadable (%s); pack %s "
                         "will read as UNREVIEWED and any decisions it recorded are lost",
                         p, e, pack_id)
        return None
    if not isinstance(raw, Mapping):
        logger.error("human_review receipt %s is not a JSON object (%s); pack %s will read "
                     "as UNREVIEWED", p, type(raw).__name__, pack_id)
        return None
    hist = []
    for d in raw.get("history") or []:
        if not isinstance(d, Mapping):
            continue
        try:
            hist.append(Decision(key=str(d["key"]), action=str(d["action"]),
                                 reviewer=str(d["reviewer"]), note=str(d.get("note", "")),
                                 decided_at=str(d.get("decided_at", ""))))
        except KeyError:
            continue  # a half-written entry certifies nothing
    return Receipt(pack_id=str(raw.get("pack_id") or pack_id),
                   fingerprint=str(raw.get("fingerprint") or ""), history=hist)


def _write_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)  # a torn receipt would read as `unreviewed`; still, do not create one


def record_decision(pack_id: str,
                    items: Sequence[Item],
                    key: str,
                    action: str,
                    reviewer: str,
                    note: str = "",
                    *,
                    now: str | None = None,
                    root: Path | str | None = None) -> Receipt:
    """Append one decision and rewrite the receipt against the CURRENT item set.

    `items` is passed in rather than read from the receipt so the fingerprint is always recomputed
    from what the engine says now. A reviewer deciding against a stale queue re-stamps the receipt
    to the queue they actually saw, which is the only honest interpretation of their click.
    """
    if action not in ACTIONS:
        raise ValueError(f"unknown action {action!r}; expected one of {sorted(ACTIONS)}")
    if not reviewer.strip():
        raise ValueError("a decision without a named reviewer is not a receipt")
    if action == "accepted" and not note.strip():
        # The one action that ASSERTS the flag was wrong must say why, or it is indistinguishable
        # from clicking through the queue to clear it.
        raise ValueError("action 'accepted' requires a note explaining why the flag is not a claim")
    valid = {i.key for i in items}
    if key not in valid:
        raise ValueError(f"{key!r} is not in the current queue for {pack_id}")

    rec = load_receipt(pack_id, root) or Receipt(pack_id=pack_id)
    stamp = now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rec.history.append(Decision(key=key, action=action, reviewer=reviewer.strip(),
                                note=note.strip(), decided_at=stamp))
    rec.fingerprint = fingerprint(items)
    _write_atomic(receipt_path(pack_id, root), rec.to_dict())
    return rec


def root_for(cfg: Any) -> Path:
    """Receipts live under the configured store root (`cfg.store_dir`, `store.py:71`), not `store/`.

    Matters for tests: the suite has polluted the production stores before (memory
    `verify-pipeline-wrote-to-production-stores`), and a hardcoded `store/` here would do it again.
    """
    base = getattr(cfg, "store_dir", None) if cfg is not None else None
    return (Path(base) / "human_review") if base else _default_root()


def status(pack_id: str,
           items: Sequence[Item],
           *,
           traced: bool = False,
           root: Path | str | None = None) -> tuple[str, list[str]]:
    """`(status, outstanding_keys)`. See the module docstring for what each status licenses.

    `traced` defaults to False — FAIL CLOSED. A caller who forgets it gets `untraced`, which is not
    sellable, rather than `clean`, which would certify a pack nothing ever examined. Prefer
    `status_for_checks`, which cannot be called wrongly.

    Order matters: `traced` first, then `clean` from `items` alone before any receipt is read, so a
    pack the engine now traces fully is not held hostage by an old receipt.
    """
    if not traced:
        return STATUS_UNTRACED, [i.key for i in items]
    if not items:
        return STATUS_CLEAN, []
    rec = load_receipt(pack_id, root)
    if rec is None:
        return STATUS_UNREVIEWED, [i.key for i in items]
    if rec.fingerprint != fingerprint(items):
        return STATUS_STALE, [i.key for i in items]
    decided = rec.current()
    outstanding = [i.key for i in items if i.key not in decided]
    return (STATUS_PENDING, outstanding) if outstanding else (STATUS_VERIFIED, [])


def status_for_checks(pack_id: str,
                      checks: Iterable[Any],
                      *,
                      root: Path | str | None = None) -> tuple[str, list[str]]:
    """`status` from ruled checks — the call every caller should be making."""
    items, traced = queue_from_checks(checks)
    return status(pack_id, items, traced=traced, root=root)


def is_sellable(pack_id: str,
                items: Sequence[Item],
                *,
                traced: bool = False,
                root: Path | str | None = None) -> bool:
    """Would the human-verification fence let this pack be listed?

    Deliberately NOT called from `verify` or `kill_filter`: this is a revenue decision on the
    publish path, and wiring it into ruling would repeat the mistake §33.7 records.
    """
    return status(pack_id, items, traced=traced, root=root)[0] in SELLABLE


def is_sellable_checks(pack_id: str,
                       checks: Iterable[Any],
                       *,
                       root: Path | str | None = None) -> bool:
    """`is_sellable` from ruled checks. This is what `bridge.listing_gate`'s caller uses."""
    return status_for_checks(pack_id, checks, root=root)[0] in SELLABLE
