"""CLI orchestrator (Part 3/4/8). The runtime entrypoint.

Usage examples:
  python -m prospector.run vet --title "Fuel duty rebate automation" \\
      --one-liner "SaaS to reclaim fuel duty for fleets" --why-now "2024 HMRC rule change"

  python -m prospector.run signal --text "Rising energy costs for SME manufacturers"

  python -m prospector.run signal --file signals/fuel_duty.txt \\
      --fixtures fixtures/fuel_duty_passages.json
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import uuid
from pathlib import Path
from typing import NamedTuple, Optional


# Max candidates vetted in parallel. Each vet drives slow CLI subprocesses, so the
# real throughput ceiling is retrieval.claude_concurrency; this caps how many candidate
# vets are in flight at once. Sourced from config (retrieval.vet_workers).
# Keep it <= retrieval.claude_concurrency so workers do not self-induce queue_timeout —
# oversubscribing the CLI is what produced the ~3s HTTP-429 failures that flapped the moat
# on 2026-08-06. PROSPECTOR_VET_WORKERS overrides for ops. Not a verdict knob.
def _vet_workers(cfg) -> int:
    env = os.environ.get("PROSPECTOR_VET_WORKERS")
    if env:
        return max(1, int(env))
    # DEFENSIVE ON THE SECTION, not just on the key. `_cmd_resume` began calling this when the
    # drain became a pool, and its callers include Namespace configs and test fixtures with no
    # `retrieval` section at all — `cfg.retrieval` raised AttributeError where the old serial loop
    # simply never asked. A missing SECTION must fall back to the default exactly as a missing key
    # does. The isinstance branch is not paranoia: `cfg.generation` is a dict built verbatim from
    # the YAML, and assuming an object there silently returned a hardcoded 5 on every unattended
    # tick for as long as the line existed (see run.py:1430).
    r = getattr(cfg, "retrieval", None)
    raw = (r.get("vet_workers", 3) if isinstance(r, dict) else getattr(r, "vet_workers", 3))
    return max(1, int(raw))


# A sentinel, not None and not a Dossier: "another worker already holds this row's lease."
# It needs to be distinguishable from BOTH other outcomes. `None` already means "the index row
# has no dossier JSON on disk", which is a store INCONSISTENCY an operator should chase; a
# contended lease is the queue working exactly as designed and must not be reported as damage.
_LEASE_HELD = object()


def _host_id() -> str:
    """Which machine this worker runs on. Part of every lease owner string.

    One definition, in `audit.host_id`, because the consumer heartbeat asks the same question
    about the same kind of persisted pid. A second copy here would be the rule everyone
    reimplements slightly differently. Imported inside the function to match how the rest of
    this module reaches `audit`, and to keep the import graph unchanged.
    """
    from .audit import host_id

    return host_id()


def _mint_lease_owner() -> str:
    """`host:pid:uuid`. The uuid makes it per-INVOCATION, not per-process (see `_cmd_resume`)."""
    return f"{_host_id()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


def _owner_is_gone(owner: str) -> bool:
    """True when a lease owner is a process that is definitely not running any more.

    Owners are minted as `host:pid:uuid` by `_mint_lease_owner`. `os.kill(pid, 0)` is the check:
    it signals nothing and only asks whether the pid exists.

    UNSURE ALWAYS MEANS ALIVE. An unparsable owner, a pid we lack permission to signal, or a pid
    another program has since been given all return False, so the lease stands and the TTL is the
    only thing that frees it. The cost of a false "gone" is two workers on one row, which is the
    double-publish this lease exists to prevent; the cost of a false "alive" is one row waiting.
    """
    parts = owner.split(":")
    if len(parts) >= 3:
        # `host:pid:uuid`. A PID IS ONLY MEANINGFUL ON THE MACHINE THAT MINTED IT. Asking
        # `os.kill` about another host's pid answers a question about OUR process table: the pid
        # is usually absent, so a live worker on the other machine reads as gone, its row is
        # reclaimed, and two workers vet one candidate — the double-publish this lease prevents.
        # Pid reuse makes the other direction possible too. So a foreign host is always ALIVE
        # here and only the TTL frees its rows, which is the same rule the rest of this function
        # follows: unsure means alive.
        if parts[0] != _host_id():
            return False
        head = parts[1]
    else:
        # LEGACY `pid:uuid`, minted before owners carried a host. Kept reading as before rather
        # than as foreign, so the 2026-08-16 dead-worker reclaim does not regress on rows already
        # in the store; they age out within one `lease_ttl_s` and stop appearing.
        head = parts[0]
    if not head.isdigit():
        return False
    try:
        os.kill(int(head), 0)
    except ProcessLookupError:
        return True
    except (PermissionError, OverflowError, OSError):
        return False
    return False


def _drop_leased(pending: list, store) -> tuple[list, int]:
    """Take the rows another worker is holding out of a re-vet pass. Returns (rows, dropped).

    Ordering is preserved, so the ranked, highest-value-first priority the caller already built
    is untouched — this only removes rows nothing can work right now.

    Applies to the SELECTION only, never to the backlog count: a leased row has no verdict yet
    and has not left the queue, and `drainable()` feeds the generation brake as well as this
    drain (store.py:560). Narrowing one side and not the other is how the brake deadlocks.

    Never raises. A store that cannot answer "what is in flight" must not be able to end a drain
    pass; the worst case of a failed read is the behaviour that existed before this filter.
    """
    try:
        rows = store.leased()
    except Exception:  # noqa: BLE001 — see the docstring
        return pending, 0
    held = set()
    for r in rows:
        cid = str(r.get("candidate_id", "") or "")
        if _owner_is_gone(str(r.get("lease_owner", "") or "")):
            # A DEAD WORKER MUST NOT PARK A ROW FOR ITS FULL TTL. `lease_ttl_s` is 7200, sized
            # off the worst measured vet (4127s) so a live worker is never expired mid-vet. That
            # is right for a worker that is running and wrong for one that is gone: on
            # 2026-08-16 four SIGKILLed processes held the front of the queue, and the consumer
            # is SIGKILLed routinely because it ignores SIGTERM mid-wave. Every restart would
            # otherwise cost two hours of the 24 best rows.
            #
            # Reclaimed rather than merely ignored: `store.claim` still honours the unexpired
            # lease, so a row we skipped the filter for would come straight back as _LEASE_HELD
            # and waste the slot anyway. Releasing is scoped to that owner (store.py:545), so
            # this cannot take a row from anyone else.
            #
            # Every owner is a pid on THIS machine — the engine is local by design, and the
            # owner string is minted as `os.getpid():uuid` a few lines below. Pid reuse fails
            # SAFE: an unrelated process holding the number reads as alive and the row is left
            # alone. The reverse — a live worker whose pid is gone — cannot happen.
            if store.release(cid, str(r.get("lease_owner", "") or "")):
                logger.info("released a lease held by a dead worker",
                            extra={"candidate_id": cid, "owner": r.get("lease_owner")})
                continue
        held.add(cid)
    if not held:
        return pending, 0
    kept = [r for r in pending if str(r.get("candidate_id", "") or "") not in held]
    return kept, len(pending) - len(kept)


def _lease_ttl_s(cfg) -> float:
    """How long a worker may hold a queue row before the lease expires and frees it.

    Sized off the WORST measured vet, not the median: a drain row took 4127s on 2026-08-15
    (content phase 51-56% of it), so a TTL near the ~251s average would expire mid-vet and hand
    a live row to a second worker — manufacturing the exact double-work the lease exists to
    prevent, and doing it most often on the slowest, most expensive rows. Too long is the safe
    direction: an over-long lease on a crashed worker delays one row, while an over-short one
    duplicates paid work and can reach the publish path twice.

    Read defensively for the same reason `_vet_workers` is (run.py:33) — this function's callers
    include None and SimpleNamespace configs from the daemon's own tests.
    """
    env = os.environ.get("PROSPECTOR_LEASE_TTL_S")
    if env:
        return max(1.0, float(env))
    s = getattr(cfg, "schedule", None)
    raw = (s.get("lease_ttl_s", 7200) if isinstance(s, dict) else getattr(s, "lease_ttl_s", 7200))
    return max(1.0, float(raw))


# Kill-fast is a rule about IDEAS: stop paying for a candidate the moment one gate is decisive.
# This is that rule applied to INFRASTRUCTURE, and it had no implementation until 2026-08-06.
# That day's 10:00 UTC batch vetted 14 candidates end-to-end and deferred all 14. The
# non-critical chain that generates each check's search queries had been benched by a monthly
# spend limit, so 52 of 98 checks never produced a query — and a check with no query has no
# passages, which verify.py reports as retrieval_failed -> DEFER_GATE. Retrieval was healthy
# throughout (200/200 ddg searches `ok`, every completed search 5-42 passages), which is why a
# preflight probe would NOT have caught this: the subsystem that died is not the one we probe.
# Nothing counted defers ACROSS candidates, so candidates 3..14 each re-learned the same
# outage at full price, and all 14 landed in a backlog the drain must pay for a SECOND time.
#
# Deliberately cause-agnostic. Three different subsystems (query-gen, retrieval, the moat)
# produce an identical batch-level signature, and on 2026-08-06 two confident diagnoses of
# which one it was were both wrong. Counting the signature is reliable; inferring the cause
# from inside the batch is not.
#
# A STREAK, not a total: a healthy batch may legitimately defer one or two candidates, so only
# CONSECUTIVE infra-gated defers mean the subsystem is down rather than the ideas being
# awkward. 0 disables. Not a verdict knob — it can only stop work, never change a ruling.
def _infra_abort_streak(cfg) -> int:
    env = os.environ.get("PROSPECTOR_INFRA_ABORT_STREAK")
    if env:
        return max(0, int(env))
    return max(0, int(getattr(cfg.retrieval, "infra_defer_abort_streak", 3)))


def _infra_abort_check(dossier, streak: int, threshold: int, pending) -> tuple:
    """Advance the consecutive-infra-defer streak; cancel un-started vets if it trips.

    Returns ``(new_streak, cancelled_or_None)``. ``cancelled_or_None`` is ``None`` while the
    batch should keep going, otherwise the number of vets cancelled before they started.

    Only ``Future.cancel()`` is used, which by contract refuses a vet that is already running.
    So an abort can never discard a verdict we have paid for — it declines to buy more.
    """
    streak = streak + 1 if dossier.gate_fired in _INFRA_GATES else 0
    if not threshold or streak < threshold:
        return streak, None
    return streak, sum(1 for f in pending if f.cancel())


def _vet_budget_cancel(deadline_mono: Optional[float], pending) -> Optional[int]:
    """Cancel every vet that has not started once the vetting phase's wall clock is spent.

    Returns the number cancelled, or ``None`` while budget remains (and always when no budget
    was set, which is every CLI caller). 0 is a real answer — "the budget is spent and nothing
    was left to cancel" — and must NOT read as "keep going", which is why the sentinel is None.

    Deliberately built on `Future.cancel()`, the same primitive as `_infra_abort_check` above,
    for the same reason: cancel() refuses a vet that is already running, so this can only
    decline to buy more work. Every verdict already paid for is banked and persisted
    (`store.save` lives inside `vet_candidate`), so the rail costs no evidence.

    THE FAILURE THIS REPLACES. `_TICK_HARD_DEADLINE_S` is enforced by a `threading.Timer` that
    calls `os._exit` — five recorded breaches, 2026-08-13 to 2026-08-15, every one at
    batch=15. A SIGKILL mid-candidate cannot bank anything, cannot write a tick row, and
    cannot say what it was doing, so the one event most worth measuring left the least
    evidence. A deadline the loop checks itself turns that into an ordinary, logged decision.
    The force-exit timer stays as the true last resort, for a hang this check cannot reach
    (a wedged single call inside one vet); it is not the normal path any more.
    """
    if deadline_mono is None:
        return None
    import time as _t
    if _t.monotonic() < deadline_mono:
        return None
    return sum(1 for f in pending if f.cancel())


def enqueue_as_defer(cand, *, store, cfg, op, reason: str) -> Dossier:
    """Write ONE candidate into the queue as a DEFER row, and return the row.

    This is the enqueue half of the producer/consumer split, and it is deliberately the SAME
    function the budget-park rail below uses. A DEFER row is already what this repo means by
    "generated, not yet ruled" — `drainable()` selects it, `vet --resume` finishes it, the
    backlog counters count it — so the queue needs no new table and no second state machine.
    What it does need is ONE writer: two call sites each building "a queued row" by hand is
    how the producer's rows and the parked rows drift into two shapes the consumer then has
    to tell apart.

    `reason` is the only thing that differs between callers, and it rides in `gate_fired` so
    the row says why it is waiting: `queued_for_vetting` (never started — a producer minted
    it) versus `vet_budget_spent` (started, then the tick's clock ran out). The consumer
    treats them identically; a human diagnosing where a backlog came from does not.

    Raises on a failed save rather than swallowing it. Both callers catch — but they catch
    for their own reasons, and a writer that silently returns a row it never persisted would
    make both of them count a queue entry that does not exist.
    """
    # A `gate_fired` outside DEFER_REASONS decides KILL (dossier.py:113), which is right for a
    # real gate and catastrophic here: a typo would mint an evidentiary kill on a candidate no
    # check has looked at, in a row that reads as fully reasoned. That is the
    # `2102bacc6dd75cf9.kill.json` defect, and this is the one place it can be introduced.
    # Fail loudly at the call rather than silently in the catalogue.
    if reason not in DEFER_REASONS:
        raise ValueError(
            f"enqueue reason {reason!r} is not a deferral — it would be recorded as a KILL. "
            f"Add it to models.DEFER_REASONS ({sorted(DEFER_REASONS)}) if it is one.")

    now = datetime.datetime.now(datetime.timezone.utc)
    d = build_dossier(
        cand=cand, checks=[], adversarial=None,
        gate_fired=reason, score=None, cfg=cfg,
        op_model_version=getattr(op, "model_version", ""),
        provider_chain="", created_at=now.isoformat(),
        reverify_due_at=(now + datetime.timedelta(days=30)).isoformat())
    if store is not None:
        store.save(d)
    return d


def enqueue_candidates(kept, *, store, cfg, op) -> list[Dossier]:
    """THE PRODUCER. Park every selected candidate in the queue, vetting none of them.

    The reason the split exists is that generating and ruling have incompatible clocks.
    Generation is bounded and fairly predictable; a single vet has been measured at 4127s
    against a ~251s median, so a tick that must do both under one deadline either sizes its
    generation for the vet's worst case or force-exits mid-verdict. Both were happening.

    Separated, the producer's contract is exactly: novelty-selected candidates become durable
    rows, then it is done. It never waits on a brain, so a benched moat costs it nothing; it
    never publishes, so it touches no money rail; and its failure mode is a short queue rather
    than a truncated batch that reports nothing amiss.

    A save that fails is logged and skipped rather than raised — the batch's other rows are
    already paid for and one lost row must not take them with it. The RETURN is the rows
    actually written, never the count attempted: a producer that reports its intent instead of
    its effect is the counters-lie failure mode, and every queue-depth reading downstream is
    built on this number.
    """
    queued: list[Dossier] = []
    for idx, cand in enumerate(kept, start=1):
        try:
            queued.append(enqueue_as_defer(cand, store=store, cfg=cfg, op=op,
                                           reason="queued_for_vetting"))
        except Exception as e:  # noqa: BLE001 - one lost row must not cost the batch
            logger.error("Could not enqueue candidate %s: %s", idx, e,
                         extra={"candidate_index": idx, "error": str(e)})
    return queued


def _defer_unstarted_candidates(fut_meta, kept, already_cancelled, *,
                                store, cfg, op, dossiers) -> int:
    """Park every vet the budget stop just cancelled as a DEFER row, and return how many.

    WHY THIS EXISTS. `_vet_budget_cancel` above buys the tick its clean stop, but a cancelled
    future is a candidate that has already been generated, prescreened, deduped and diversity-
    selected — the expensive half of the funnel, paid for. Dropping it on the floor makes a
    k=50 batch pay a k=50 generation bill for a k≈18 yield and report nothing amiss, which is
    the "counters lie" failure mode: the tick summary would show 18 vetted out of 18 banked.

    DEFER is not a new concept invented for this rail; it is what the house already means by
    "we did not evaluate this, come back to it" (moat exhaustion and retrieval failure both
    land here). Writing that row is therefore the whole integration: `drainable()` sees it,
    `vet --resume` finishes it, and the backlog counters count it as the real backlog it is.

    `already_cancelled` is the set of futures cancelled BEFORE this stop (by the infra rails),
    diffed out so this function reports and parks only its own work rather than inheriting
    another rail's cancellations.

    A failed save is logged and skipped, never raised: losing one parked candidate is a cost,
    losing the batch's banked verdicts to an exception on the way out is a much larger one.
    """
    parked = 0
    for fut, idx in list(fut_meta.items()):
        if not fut.cancelled() or fut in already_cancelled:
            continue
        try:
            d = enqueue_as_defer(kept[idx - 1], store=store, cfg=cfg, op=op,
                                 reason="vet_budget_spent")
            dossiers.append(d)
            parked += 1
        except Exception as e:  # noqa: BLE001 - see docstring: never lose the batch
            logger.error("Could not park budget-cancelled candidate %s as DEFER: %s",
                         idx, e, extra={"candidate_index": idx, "error": str(e)})
    return parked


def _infra_exception_action(streak: int, threshold: int) -> str:
    """What to do when a vet RAISES GroundingInfrastructureError, rather than returning a
    defer. Takes the streak ALREADY incremented for this failure.

    A returned infra-gated defer and a raised GroundingInfrastructureError are the same
    event wearing two coats: "the pipeline could not rule". Until 2026-08-07 only the first
    reached `_infra_abort_check`; the raise was re-thrown unconditionally at the first
    occurrence, straight past the streak rail and out to `run_scheduled.py`'s `sys.exit(1)`.
    One unlucky tail query therefore killed the daemon. Measured blast radius, so nobody
    re-derives it: across 195 real ticks 2026-08-01..07, exactly ONE tick row in
    `store/scheduler/ticks.jsonl` carries GroundingInfrastructureError at TOP level (the
    signature of the exit path) — 2026-08-06T21:58:21, costing 17 min against the 2.00h
    interval. Do NOT count daemon deaths from the audit log's pid column: any process
    writing audit rows appears there, so that column reads ~8 restarts/hour while the
    daemon is provably up. This is a latent-risk fix, not a headline outage.

    Returns one of:
      "raise"    — the streak rail is disabled (threshold 0), so preserve the pre-2026-08-07
                   immediate halt rather than silently becoming a weaker rail than we had.
      "halt"     — the outage is sustained: cancel un-started vets, let running ones bank
                   themselves, and halt once the batch has drained.
      "continue" — a blip. Bank nothing for this candidate, keep vetting the rest.
    """
    if not threshold:
        return "raise"
    return "halt" if streak >= threshold else "continue"


def _sync_cli_concurrency(cfg) -> None:
    """Apply retrieval.*_concurrency to CLI governors (env vars still win when set)."""
    r = getattr(cfg, "retrieval", None)
    if r is None:
        return
    try:
        from .claude_cli import configure_concurrency as _claude_conc
        _claude_conc(int(getattr(r, "claude_concurrency", 2) or 2))
    except Exception:
        pass


def _resolve_lanes(cfg, args) -> Optional[list]:
    """Which ambition lanes this run spans (Part 14 — multi-lane-by-default).

    --lane X            => single pinned tier [X] (classify skipped; tier is the user's word).
    else active_lane    => single config-pinned tier (today's single-lane behaviour).
    else active_lanes   => the multi-lane set (a mixed-ambition catalogue).
    else                => None (no lane engaged → byte-for-byte today's single default).
    """
    lane = getattr(args, "lane", None)
    if lane:
        return [lane]
    if getattr(cfg, "active_lane", ""):
        return [cfg.active_lane]
    if getattr(cfg, "active_lanes", None):
        return list(cfg.active_lanes)
    return None


def _lane_counts(cfg, lanes: list, k: Optional[int]) -> dict:
    """How many candidates to generate per lane. With no explicit total (`k` None) use the
    per-lane `lane_quota` (default 3). With an explicit `--candidates k`, distribute k across
    the lanes PROPORTIONAL to the quota weights (every lane keeps >=1) so the flag scales the
    whole fan-out rather than any single tier. All values are config-sourced — no hardcoding.

    G9: with `generation.lane_quota_mode: measured` the static quota is replaced by one
    derived from realised value per lane (`prospector/lane_yield.py`). The measured quota is
    a pure REALLOCATION — it sums to exactly the static total, so switching modes changes
    which lanes the candidates land in and never how many are generated. It fails open to
    the static quota on any error, and the mode is `static` by default."""
    if not lanes:
        return {}
    quota = {t: max(1, int((cfg.lane_quota or {}).get(t, 3))) for t in lanes}
    mode = str((getattr(cfg, "generation", {}) or {}).get(
        "lane_quota_mode", "static")).strip().lower()
    if mode == "measured":
        measured = measured_lane_quota(cfg, list(lanes), sum(quota.values()))
        if measured:
            quota = measured
    if k is None:
        return quota
    total_w = sum(quota.values()) or len(lanes)
    counts = {t: max(1, round(k * quota[t] / total_w)) for t in lanes}
    # Nudge the rounded counts toward the requested total k (never below 1 per lane).
    order = sorted(lanes, key=lambda t: quota[t], reverse=True)
    i = 0
    while sum(counts.values()) != k and i < 10_000:
        t = order[i % len(order)]
        diff = k - sum(counts.values())
        if diff > 0:
            counts[t] += 1
        elif counts[t] > 1:
            counts[t] -= 1
        i += 1
    return counts


# ---------------------------------------------------------------------------
# Pending signal persistence (generation resilience)
# When the generation chain (DeepSeek → MiniMax → Gemini) is exhausted, the signal
# text is saved here so the operator can re-run generation with `generate --resume`
# when the chain recovers.  Each pending signal is one JSON file keyed by a hash of
# the signal text so re-runs don't create duplicates.
# ---------------------------------------------------------------------------
_PENDING_DIR = Path(__file__).resolve().parent.parent / "signals" / "pending"


def _save_pending_signal(signal_text: str, cfg: Config) -> Optional[Path]:
    """Persist a failed signal so `generate --resume` can retry it later.

    Returns the path on a CONFIRMED write, or None if the signal could not be
    durably saved. A write failure here means the signal would be silently lost,
    so it is logged at ERROR (not warning) and surfaced to the caller — never
    swallowed as if the deferral succeeded.
    """
    import hashlib
    key = hashlib.sha1(signal_text.encode()).hexdigest()[:16]
    path = _PENDING_DIR / f"{key}.json"
    try:
        _PENDING_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"signal_text": signal_text, "key": key}), encoding="utf-8")
        tmp.replace(path)  # atomic publish — a half-written file is never resumed
        if not path.exists():
            raise OSError(f"pending signal not present after write: {path}")
        return path
    except Exception as e:
        logger.error(
            f"FAILED to persist pending signal {key} — it will NOT be resumable: {e}",
            extra={"signal_key": key, "pending_dir": str(_PENDING_DIR)},
        )
        return None


def _save_pending_signal_or_shout(signal_text: str, cfg: Config) -> Optional[Path]:
    """`_save_pending_signal`, but a failed write is never left to the log alone.

    The saver returns None on a failed write and every caller here used to discard that
    return, so "the signal is safely queued for `generate --resume`" and "the signal is gone"
    printed the same reassuring progress line. When the queue file cannot be written the
    signal TEXT itself goes to the log at CRITICAL, because the log is then the only place it
    still exists.
    """
    path = _save_pending_signal(signal_text, cfg)
    if path is None:
        logger.critical(
            "PENDING SIGNAL LOST — it could not be queued for `generate --resume` and is "
            "recoverable only from this line. Signal text: %s", signal_text,
            extra={"signal_lost": True, "signal_text": signal_text})
    return path


def _load_pending_signals() -> list[tuple[Path, str]]:
    """Return all pending signals as (path, text) pairs."""
    if not _PENDING_DIR.exists():
        return []
    results = []
    for p in sorted(_PENDING_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            results.append((p, data.get("signal_text", "")))
        except (OSError, ValueError) as e:
            # Narrow on purpose: an unreadable or corrupt queue file is a signal that will
            # never be resumed, so it is logged at ERROR rather than skipped in silence —
            # and a TypeError from a future refactor now surfaces instead of quietly
            # emptying the resume queue.
            logger.error(f"pending signal {p.name} is unreadable and will NOT be resumed: {e}",
                         extra={"path": str(p), "error": str(e)})
    return results

# Base imports for the deferred import block below; see _INFRA_GATES comment for the rationale.
from . import drain_state, field_write  # noqa: E402 - deferred import after the helper block
from .config import Config, load_config  # noqa: E402 - deferred import after the helper block
from .dedup import dedup, drops_by_market  # noqa: E402 - deferred import after the helper block
from .diversity import write_receipt  # noqa: E402 - deferred import after the helper block
from .dossier import (  # noqa: E402 - deferred import after the helper block
    build_dossier,
    render_markdown,
)
from .errors import ProviderExhaustedError  # noqa: E402 - deferred import after the helper block
from .generate import generate  # noqa: E402 - deferred import after the helper block

# Imported here, below `_lane_counts` that uses it: the helper block above deliberately
# precedes the package imports, and a function body resolves its globals at CALL time, so
# the ordering is fine and matches every other name in this block.
from .lane_yield import measured_lane_quota  # noqa: E402 - deferred import after the helper block
from .models import (  # noqa: E402 - deferred import after the helper block
    DEFER_GATE,
    DEFER_REASONS,
    Candidate,
    Decision,
    Dossier,
)

#: Gates meaning "the pipeline could not rule", as opposed to "this idea failed". Both are set
#: by verify.py when a check never got an answer — never by a grounded verdict. Defined here
#: rather than beside `_infra_abort_check` above, because this module's early helper block
#: precedes its import block: a module-level tuple there evaluates DEFER_GATE too soon.
_INFRA_GATES = (DEFER_GATE, "moat_exhausted")
from .operator import Operator  # noqa: E402 - deferred import after the helper block
from .prescreen import prescreen  # noqa: E402 - deferred import after the helper block
from .retrieval import SearchProvider  # noqa: E402 - deferred import after the helper block
from .score import score_candidate  # noqa: E402 - deferred import after the helper block
from .store import Store  # noqa: E402 - deferred import after the helper block
from .telemetry import (  # noqa: E402 - deferred import after the helper block
    logger,
    set_context,
    track_latency,
)


# verify is imported lazily inside vet_candidate to avoid a pre-existing
# dead-import error in verify.py (gate_check listed but not defined in
# kill_filter.py).  Lazy import keeps the module-level import of run.py clean
# while still providing full runtime access.
def _get_verify():
    from .verify import verify as _verify
    return _verify


# Non-critical chain order: claude_cli (subscription) → minimax emergency tail.
# Founder directive 2026-08-06: "we need to use claude code and minimax".
#
# This was `(deepseek, cursor_cli, minimax)`. Both leading tiers were measured DEAD on
# 2026-08-06 — one JSON call to each configured brain:
#
#     deepseek    RuntimeError: DeepSeek call failed: HTTP Error 402: Payment Required
#     cursor_cli  ProviderExhaustedError: cursor cli exit 1: ActionRequiredError:
#                 You've hit your usage limit
#     minimax     OK
#     claude_cli  OK
#
# So EVERY generation, prescreen and score call was being served by minimax — the guardrailed
# emergency tail — after paying two guaranteed failures first. Nothing raised and nothing was
# logged above INFO, so from the outside the chain looked healthy: that is the failure mode of a
# fallback that works. The tail is not a neutral place to land, either: minimax was measured
# NON-DETERMINISTIC on the classify call at temperature 0.0 (4 of 6 candidates returned a
# different tier across 3 repeat runs), while claude_cli returned the identical answer 18/18.
#
# claude_cli is in MOAT_PRIMARY, so this does put a moat brain on the
# non-critical chain. That is a deliberate, founder-directed change to the rule in CLAUDE.md,
# and it is not unprecedented: `_build_artifact_op` below has always generated the customer-
# facing pack prose on the CLI operators. The rule that still binds absolutely is the one about
# VERDICTS: DeepSeek/MiniMax never rule as trusted-final — is_provisional_provider enforces it.
# PROCESS RISK, stated as such: claude_cli work is slot-governed (cli_governor), so a large
# non-critical burst can now queue behind — or ahead of — the daemon's verdict calls. It costs
# throughput, not correctness. Restoring deepseek/cursor_cli is a one-line change when billing
# and usage limits recover; their breakers already half-open on their own.
#
# Ollama REJECTED 2026-07-01 (markdown, not JSON). Module-level so run_signal, `operators`, and
# the proof tools all reference the SAME chain.
#
# HEAD CHANGED 2026-08-08 (founder directive: "non critical, use standardcompute first";
# standardcompute has since been removed entirely — see the note above _NONCRITICAL_ORDER).
# claude_cli headed this chain from 2026-08-06 only because the alternatives were dead at the
# time (deepseek measured HTTP 402, cursor_cli at its usage limit). That made "non-critical"
# a name with no cost meaning: the cheap chain and the moat chain were the SAME three
# providers in the same order, so ancillary generation was paying the moat's price. Measured
# on the 2026-08-08 republish of 34 packs: 36 claude_cli calls, 3227s of CLI wall-clock, ~90s
# each. standardcompute was live at the time (no dead mark in provider_health_noncritical.json),
# so it took the head and claude_cli became the failover it was always meant to be. Both names
# have since left this chain — see the 2026-08-14/08-15 notes below; this paragraph is history.
#
# Scope is deliberately ONLY the non-critical chain. `cfg.operator` (the moat) and
# `cfg.artifact_operator` (the pack prose) are untouched, and claim-check still runs on
# the moat: a truth gate that vetoes ungrounded copy is not an ancillary call, and this repo
# holds those on MOAT_PRIMARY.
#
# claude_cli REMOVED ENTIRELY 2026-08-14 (founder directive: "we are over using claude cli and we
# have Minimax, claude should never be used for non-critical"). Demoting it to failover in 08-08
# was not enough: a failover still RUNS, and it ran at ~90s and full moat price every time
# standardcompute so much as blinked. "Never" is only true if the name is absent from the chain,
# so it is absent here AND stripped in `_noncritical_order` — the rule is enforced where the chain
# is BUILT, not merely where it is configured.
#
# standardcompute REMOVED ENTIRELY 2026-08-15 (founder directive), adapter and all. It took the
# head on 2026-08-08, lost it to minimax on 2026-08-14 because it was measurably out of allowance
# (store/provider_health_noncritical.json: strikes 4, last_error "StandardCompute returned an
# out-of-allowance notice instead of a completion: You've used up your free trial"), and was kept
# one more day as "the failover tier: a chain of one is not a chain". That reasoning does not
# survive contact with the measurement: a name that answers every call with an upsell body is not
# depth, it is a guaranteed failed call before each fall-through. STANDARDCOMPUTE_API_KEY is unset
# here and the trial is spent, so the tier could not have served even if it were healthy.
#
# The chain is therefore minimax alone, and `prospector/operator._build_operator` now raises an
# explicit ValueError on the name so a stale config or plist fails loudly at startup rather than
# quietly building a shorter chain. Funding a real second cheap tier is a config.yaml line
# (`noncritical_operator:`), not a source edit — that is what `_noncritical_order` is for.
_NONCRITICAL_ORDER = ("minimax",)

#: Providers that may never appear on the non-critical chain, whatever config.yaml says.
_NONCRITICAL_FORBIDDEN = frozenset({"claude_cli", "claude"})

#: How many times the publish path will generate a pack's content before giving up on it.
#: Mirrors `tools/publish_passes.py:53 MAX_GEN_ATTEMPTS`, deliberately — see
#: `_generate_pack_content` for why the daemon needs the discipline the repair tool has
#: always had.
_MAX_PACK_GEN_ATTEMPTS = 3


#: The shelf lines the MARKETING chain actually writes, and therefore the only ones a
#: marketing rewrite can fix. `title` and `oneLine` are graded at publish too, but they come
#: off the Candidate — grading them here would loop three times and escalate to the expensive
#: chain over a line no regeneration touches. Naming the fields is also what keeps this
#: honest as `SHELF_FIELDS` grows: a new candidate-sourced field cannot silently start
#: costing rewrites.
_MARKETING_SHELF_FIELDS = ("cardLine", "headline", "subhead")


def _shelf_copy_breaches(cand, marketing, cfg) -> list[str]:
    """Grade the generated shelf copy against the SAME bar `bridge.py` applies at publish.

    This is the guardrail the founder attached to moving marketing copy onto the cheap chain
    ("isplit it but we needd strong guardrails to keep minimax. in check", 2026-08-14). It is
    not a second, softer rule written for generation: it calls `check_shelf_copy` with the
    same `block` actuator `bridge.py:907` reads from `listing.shelf_copy_block_on_breach`, on
    fields normalised through the same `_card_field`/`_cap_words` the catalogue row uses. A
    line that would be graded on a shelf field the catalogue never receives is the defect that
    unlisted two live packs on 2026-08-08 (see `bridge._card_field`), so the normalisation is
    shared rather than re-implemented.

    When the actuator is OFF this returns `[]` and costs nothing: regenerating copy that
    publish would have accepted is spend with no buyer-visible change.

    Returns the `error` details only — warnings are a reviewer's residue, never an actuator.
    """
    listing_cfg = cfg.listing if isinstance(getattr(cfg, "listing", None), dict) else {}
    if not bool(listing_cfg.get("shelf_copy_block_on_breach", False)):
        return []
    from .bridge import _cap_words, _card_field
    from .pack_linter import check_shelf_copy

    listing = next((m for m in (marketing or []) if m.get("type") == "listing_page"), {})
    fields = {
        "cardLine": _card_field(listing.get("card_line")),
        "headline": _cap_words(_card_field(listing.get("headline")), 140),
        "subhead": _cap_words(_card_field(listing.get("subhead")), 280),
    }
    assert set(fields) == set(_MARKETING_SHELF_FIELDS)

    # THE TITLE IS PASSED IN AND NEVER GRADED, and both halves of that matter.
    #
    # Passed in, because two shelf rules read the whole page rather than one field: a term
    # the title spells out is introduced by the time the card line uses it, and a line that
    # repeats the title is the repeat. Grading the card line without the title in front of it
    # is a DIFFERENT bar from the one `bridge.py` applies at publish, and a generator that
    # refuses copy the gate would accept burns three attempts plus an escalation to the
    # expensive chain to arrive at the same pack.
    #
    # Never graded, for the reason `_MARKETING_SHELF_FIELDS` exists: the title comes off the
    # Candidate, so no marketing rewrite can fix it, and looping over it is spend with no
    # buyer-visible change. Filtering on `where` is what keeps the two facts independent —
    # the context can widen without the actuator widening with it.
    graded = dict(fields)
    graded["title"] = _card_field(getattr(cand, "title", "") or "")
    return [pb["detail"] for pb in check_shelf_copy(graded, block=True)
            if pb.get("severity") == "error"
            and pb.get("where") in _MARKETING_SHELF_FIELDS]


#: Both re-exported from `field_write`, which is where they are declared. They stay named here
#: because they are part of this module's tested surface: `_MAX_TITLE_REPAIR_ATTEMPTS` is how
#: many times the title repair asks before leaving the title the candidate came with, and
#: `_ONE_LINER_CUT_AT` mirrors the length at which `bridge.py` cuts a catalogue one-liner.
_MAX_TITLE_REPAIR_ATTEMPTS = field_write.MAX_TITLE_REPAIR_ATTEMPTS
_ONE_LINER_CUT_AT = field_write.ONE_LINER_CUT_AT


def _repair_title(cand, cfg, *, op) -> list[str]:
    """Rewrite `cand.title` in place when it breaches the rule the publish gate enforces.

    THE TITLE AND THE ONE-LINER ARE THE SHELF LINES NO RETRY CAN FIX. `_MARKETING_SHELF_FIELDS`
    excludes both on purpose: they come off the Candidate, so regenerating the pack's copy
    three times cannot change them, and grading them inside that loop would escalate to the
    expensive chain over lines no regeneration touches. The consequence was that a breach was
    found only at the publish gate, after a ~7,700-word pack had been generated, vetted and
    paid for — and the pack then sat unsellable, because nothing downstream repairs either
    line. Measured 2026-08-17 against the live catalogue: `title` blocked 20 stranded passes,
    all 20 made in the previous three days, and `oneLine` blocked 21, 9 of them made in the
    previous two. Between them they are the biggest live defect on the shelf, and every one of
    those packs was already finished when it was caught.

    So both are repaired ONCE, here, before anything is built on them, by the same code that
    repairs the LIVE shelf after the fact: `prompts/retitle.md` + `check_title` for the title
    (as `tools/retitle_catalogue.py` does) and `shelf_copy_repair.rewrite_one` for the
    one-liner (as `tools/sweep_shelf_copy.py` does). Same prompts, same bars, moved upstream of
    the spend they were previously discovered downstream of.

    The grade-repair-re-grade-record loop is `field_write.repair`, shared with every other
    buyer-facing field (P2). This function is the WIRING, not a second copy of the loop. It
    stays a named function for two reasons: `_generate_pack_content` and its tests reach it by
    module attribute, and `candidate_id` is deliberately not recomputed on a retitle — it is
    already the catalogue row's identity and the dossier filename, so rehashing it would fork
    the pack.

    Returns the audit trail (empty when nothing needed repairing).
    """
    return field_write.repair(cand, "title", op=op, log=logger).trail


def _repair_one_liner(cand, cfg, *, op) -> list[str]:
    """Rewrite `cand.one_liner` in place when the shelf would refuse it, or cut it.

    Two triggers, and the second is the engine refusing its own handiwork:

    - **Voice.** Second person, or an opener on a bare pronoun.
    - **Length.** A line over `_ONE_LINER_CUT_AT` is cut by `bridge.py:878` and the cut ends in
      `…`, which `check_shelf_copy` then refuses as "trails off on the shelf". Nine of the 21
      stranded `oneLine` packs fail on exactly that, so the engine was manufacturing the defect
      it goes on to reject. Repaired here the line is short enough that no cut happens.

    Both bars are `field_write.grade_one_liner`, which is also what re-grades the rewrite and
    what the park check asks. Before P2 the length bar was typed out twice in this file, twelve
    lines apart — the drift `field_write` exists to make impossible.

    `rewrite_one` is the sweep's own function, so it also refuses a rewrite that introduces a
    proper noun or figure the original did not have. A refusal leaves the candidate the line it
    had, which is why this is safe to run unattended.
    """
    return field_write.repair(cand, "one_liner", op=op, log=logger).trail


def _repair_shelf_lines(cand, cfg, *, op) -> list[str]:
    """Both Candidate-sourced shelf lines, repaired before anything is built on them.

    The title first, because `rewrite_one` is given the title as context for the trade and a
    breached title is poor context. Neither half can raise and neither can make a line worse.
    """
    return _repair_title(cand, cfg, op=op) + _repair_one_liner(cand, cfg, op=op)


def _unrepaired_shelf_breaches(cand) -> list[str]:
    """What the publish gate will STILL refuse about this candidate's shelf lines.

    Run after `_repair_shelf_lines`, on the same two bars the repair used and the gate applies,
    so this is the gate's own answer arrived at before the money is spent. It is the SAME
    grader object, not a matching one — `field_write.breaches` and `field_write.repair` share
    `FIELDS`, so the two cannot drift.

    It exists because the repair is best-effort by contract and swallows its own failure. That
    is correct — a failed repair must never lose a PASS — but it left the engine knowing a pack
    was unsellable and building it anyway: `_repair_title` logs, in these words, "building the
    pack on its own title, which the publish gate will refuse", and then ~7,700 words are
    generated on the deliverable chain. The knowledge existed and nothing acted on it.
    """
    return field_write.breaches(cand, "title", "one_liner")


def _generate_pack_content(op, cand, checks, *, query_op, quality_op, cfg, score,
                           marketing_op=None, artifact_time_budget_s=None,
                           vet_deadline_mono=None):
    """The pack's prose and marketing copy, generated until it is actually sellable.

    Generate, then CHECK, then retry. `generate_artifacts` reports an operator outage as an
    EMPTY STRING rather than an exception — `artifacts.py:452` turns every per-artifact
    failure into `results[t] = ""` so that one dead artifact cannot lose the other three.
    That is defensible inside the fan-out and indefensible at the call site: with no check, a
    transient provider failure was written to disk as a finished PASS whose build_spec /
    gtm_plan / ops_plan were empty, published UNLISTED because `pack_complete` is false, and
    then revisited by nothing, ever.

    Measured 2026-08-13 against the live catalogue: of 24 engine passes not on the shelf, 12
    are exactly this, and the same three artifacts fail every time — "generation produced
    nothing" x10 build_spec, x10 ops_plan, x9 gtm_plan. Not one is a bad candidate. Each is a
    provider hiccup fossilised into a permanently unsellable pack, because the one call that
    could still have fixed it cheaply — this one, with the candidate and its checks already
    in memory — did not look at what it got back.

    `tools/publish_passes.py:228` has had this loop since it was written; the daemon's own
    path never got it, and the daemon is what produces packs. That asymmetry, not the outage,
    is why the shelf sat at 50 for three days.

    Returns `(artifacts, marketing)` whether or not the pack came out complete: an incomplete
    pack still publishes UNLISTED, exactly as before, because an unsellable row is still the
    record that this candidate passed. What changes is that it now says so at ERROR with the
    gaps named, instead of looking like a success.
    """
    from .artifacts import generate_artifacts, generate_marketing_content
    from .pack_validation import validate_pack

    # `marketing_op=None` keeps every existing caller byte-for-byte: the copy runs on the
    # deliverable chain exactly as it did until the 2026-08-14 split.
    copy_op = marketing_op or quality_op
    escalated = copy_op is quality_op

    # AN ESCALATION TO THE SAME BRAIN IS NOT AN ESCALATION. Until 2026-08-18 the two chains
    # led with different brains (`marketing_operator: [minimax, ...]` against
    # `artifact_operator: [claude_cli, ...]`), so "escalate to the quality chain" and "escalate
    # past the brain that just failed" were the same sentence. Making Claude Code optional made
    # both chains lead with `minimax`, and the difference stopped being cosmetic: the rewrite
    # would have gone to the brain whose copy the publish gate had just refused, logged as an
    # escalation, and produced the same copy again.
    esc_order = _escalation_order(cfg)
    if not escalated and not esc_order:
        # Every tier of the quality chain is the brain already writing this copy. Say so once
        # here rather than at the breach, where it would read as a rewrite that happened.
        escalated = True
        logger.info(
            "No shelf-copy escalation available for %s: the quality chain has no brain the "
            "marketing chain does not already lead with", cand.candidate_id,
            extra={"candidate_id": cand.candidate_id})

    # THE ARTIFACT/MARKETING PHASE'S WALL-CLOCK CEILING, consumed by `generate_artifacts` and
    # `generate_marketing_content` (both take `deadline_mono`, an absolute `time.monotonic()`
    # instant, and bound their ThreadPoolExecutor's `as_completed(..., timeout=)` with it
    # exactly as generate.py:771 bounds the generation wave).
    #
    # MEASURED, which is why this exists at all. Profiling the tick that force-exited at
    # 2026-08-15T13:17:56Z (window 10:17:56 -> 13:17:56, batch=15, every inter-line gap in
    # store/scheduler/launchd.err.log attributed to the line before it, all 10800s accounted):
    # 9 candidates survived all gates and the artifact/content markers span 10:40 -> 13:12 —
    # 152 of the tick's 180 minutes. `gen_budget_frac` bounded GENERATION alone, so the phase
    # that actually consumed the tick was the one phase with no budget at all. All five
    # recorded `_TICK_HARD_DEADLINE_S` breaches say "exceeded 10800s during generation", which
    # is the label `run_scheduled` puts on the whole `run_signal` call, not on drafting.
    #
    # Converted ONCE here rather than per attempt, deliberately: this is one ceiling for the
    # candidate's whole content phase, and `_MAX_PACK_GEN_ATTEMPTS` (3) retries share it. A
    # per-attempt budget would let a degraded chain spend 3x the number config declares — the
    # unbounded behaviour this replaces, in smaller instalments.
    #
    # None (every CLI caller, and the daemon when `schedule.artifact_budget_frac` is 0) leaves
    # the phase unbounded, byte-for-byte as before.
    #
    # CLAMPED TO THE BATCH DEADLINE, which is what makes the batch rail an actual guarantee
    # rather than a good intention. `_vet_budget_cancel` can only cancel vets that have NOT
    # started; every vet already running keeps going, and with `_vet_workers` of them in
    # flight, each holding a per-candidate artifact ceiling of 4320s (0.40 x 10800), the
    # batch could sail past the tick deadline having "stopped". Whichever instant comes
    # first wins, so no content call outlives the batch it belongs to.
    import time as _time
    _art_deadline = ((_time.monotonic() + artifact_time_budget_s)
                     if artifact_time_budget_s else None)
    if vet_deadline_mono is not None:
        _art_deadline = (min(_art_deadline, vet_deadline_mono)
                         if _art_deadline is not None else vet_deadline_mono)

    # BEFORE anything is built on it, and outside the attempt loop on purpose: this is one
    # field on a candidate that already passed, not a retry of the pack. See
    # `_repair_shelf_lines`.
    _repair_shelf_lines(cand, cfg, op=(marketing_op or quality_op))

    # P4 of docs/CONTENT_CONTRACT_PROGRAM.md. Repair is best-effort by contract and swallows its
    # own failure, which is right — a failed repair must never lose a PASS. But the engine then
    # KNEW the pack was unsellable and bought it anyway. Grade once more, on the gate's own bars,
    # before the deliverable chain is paid for.
    #
    # Measure-first, per the project rule that a new rule ships read-only and takes a second,
    # explicit switch to act: this logs on every candidate and only parks when
    # `listing.park_unrepairable_shelf_lines` is on. Default OFF, because parking turns a PASS
    # into a pack that does not exist, and the honest way to choose that is with a count of how
    # often it would fire, from the log line below.
    _shelf_breaches = _unrepaired_shelf_breaches(cand)
    if _shelf_breaches:
        _listing = cfg.listing if isinstance(getattr(cfg, "listing", None), dict) else {}
        _park = bool(_listing.get("park_unrepairable_shelf_lines", False))
        logger.error(
            "Shelf lines of %s still breach the publish gate after repair%s: %s",
            cand.candidate_id, " — PARKED, no pack built" if _park else
            " — building the pack anyway (park_unrepairable_shelf_lines is off)",
            "; ".join(_shelf_breaches),
            extra={"candidate_id": cand.candidate_id,
                   "shelf_breaches": _shelf_breaches,
                   "shelf_parked": _park,
                   "shelf_unrepaired": True})
        if _park:
            # Stamped, never silent. An empty artifacts dict with no reason on the candidate is
            # the "empty artifacts" failure class this repo has already had once; the tag is what
            # lets the stranded-pack scan and the ops console tell a park from a breakage.
            cand.tags["shelf_parked"] = _shelf_breaches
            return {}, []

    artifacts: dict = {}
    marketing: list = []
    problems: list = []
    breaches: list = []
    attempt = 0
    _budget_spent = False
    for attempt in range(1, _MAX_PACK_GEN_ATTEMPTS + 1):
        # Regenerate the ARTIFACTS only when the artifacts are what failed. A shelf line that
        # trails off is not a reason to re-pay the deliverable chain for three long documents
        # it already produced correctly; measured on the 2026-08-08 republish, each artifact
        # call was ~90s of claude_cli wall-clock. `validate_pack` names its problems by
        # prefix (`pack_validation.py:63/86`), which is what makes the attribution safe.
        if not artifacts or any(str(pb).startswith("artifact '") for pb in problems):
            artifacts = generate_artifacts(
                op, cand, checks, fast_op=query_op, quality_op=quality_op, cfg=cfg, score=score,
                deadline_mono=_art_deadline)
        marketing = generate_marketing_content(
            op, cand, checks, fast_op=query_op, quality_op=copy_op, check_op=op, cfg=cfg,
            deadline_mono=_art_deadline)
        complete, problems = validate_pack(artifacts, marketing)

        # A GAP PRINTED WHERE A FIGURE BELONGS IS AN UNFINISHED ARTIFACT, and until now this
        # loop could not see it. `validate_pack` grades that each artifact EXISTS and is long
        # enough and has sections; it never reads what is inside one. So a financial model
        # that printed `_(not specified)_` where the price should be counted as a successful
        # attempt, the pack published UNLISTED, and the only way back was a hand-run of
        # `tools/publish_passes.py`. Three live packs are stranded exactly that way
        # (08dbe23f7be7af97, 25363e54b649587a, 82a9c38fea398376), all created before the
        # renderer stopped emitting that string on 2026-08-14. The publish gate has always
        # refused it (`pack_linter.check_placeholders`) — the generator just never asked.
        #
        # Named in `validate_pack`'s own `artifact '<name>' ...` shape on purpose: that prefix
        # is what makes the block above regenerate the ARTIFACTS on the next attempt. A gap in
        # a figure is an artifact defect, and re-paying the copy chain would not touch it.
        from .pack_linter import check_placeholders
        for gap in check_placeholders(artifacts):
            complete = False
            problems.append(f"artifact '{gap['where']}' {gap['detail']}")

        breaches = _shelf_copy_breaches(cand, marketing, cfg)
        if complete and not breaches:
            return artifacts, marketing
        logger.warning(
            "Pack content not sellable on attempt %d/%d for %s: %s%s",
            attempt, _MAX_PACK_GEN_ATTEMPTS, cand.candidate_id, problems,
            f" shelf-copy breaches: {breaches}" if breaches else "",
            extra={"candidate_id": cand.candidate_id, "attempt": attempt,
                   "problems": problems, "shelf_copy_breaches": breaches})

        # CHEAP GETS FIRST REFUSAL, NEVER THE LAST WORD. The cheap chain wrote copy the
        # publish gate would refuse, so the rewrite goes to the deliverable chain MINUS the
        # brain that just failed. One escalation per pack, and it is permanent for that pack: a
        # chain that just failed this bar has no claim on the remaining attempts.
        if not escalated and (breaches or any(
                str(pb).startswith("marketing '") for pb in problems)):
            escalated = True
            copy_op = _build_prose_chain(cfg, esc_order, quality_op,
                                         label="Shelf-copy escalation")
            logger.warning(
                "Escalating shelf copy for %s to %s after the cheap chain breached the "
                "publish-time bar", cand.candidate_id, esc_order,
                extra={"candidate_id": cand.candidate_id, "shelf_copy_breaches": breaches,
                       "problems": problems, "escalation_order": esc_order})

        # A RETRY AGAINST A SPENT BUDGET IS NOT A RETRY. The three attempts share ONE
        # deadline (converted above), so once it passes, `generate_artifacts` and
        # `generate_marketing_content` return without calling anything: the remaining
        # attempts are no-ops that only make the log claim the chain failed three times.
        # Measured 2026-08-15 on candidate f2ac7df9995c334e — attempts 1, 2 and 3 all
        # logged at 15:36:08Z, the same second.
        if _art_deadline is not None and _time.monotonic() >= _art_deadline:
            _budget_spent = True
            break

    logger.error(
        # NAME THE REAL CAUSE. "generation produced nothing" reads as a prose-operator
        # outage and sends the next reader to debug the operator; when the budget is what
        # ran out, the operator was healthy and the ceiling is the thing to change.
        "Pack content STILL not sellable for %s after %d attempt(s) — %s; it will publish "
        "UNLISTED and needs `tools/publish_passes.py <dossier>`: %s%s",
        cand.candidate_id, attempt,
        ("the content phase ran out of TIME BUDGET, not a failing operator; raise "
         "`schedule.artifact_budget_floor_s`" if _budget_spent
         else "the content chain returned unsellable output"),
        problems,
        f" shelf-copy breaches: {breaches}" if breaches else "",
        extra={"candidate_id": cand.candidate_id, "problems": problems,
               "shelf_copy_breaches": breaches, "attempts": attempt,
               "artifact_budget_exhausted": _budget_spent})
    return artifacts, marketing


def _noncritical_order(cfg: Config | None = None) -> tuple[str, ...]:
    """The non-critical chain for THIS config, defaulting to `_NONCRITICAL_ORDER`.

    Why a config key and not the constant it reads: every other lever on this chain — how many
    candidates it makes, how often, under what spend ceiling — is a config line the operator can
    move from a phone, while the one that decides what the ancillary work COSTS could only be
    moved by editing source and re-execing the daemon. That is backwards: the head of this chain
    has changed three times in two weeks (deepseek → claude_cli → standardcompute, all three since
    removed from it), each time by
    a source edit, and each edit was a code deploy to express a billing fact.

    Deliberately NOT extended to `cfg.operator`: the verdict chain must stay led by a trusted
    brain, and a config key that can be written from a phone is not where that fence belongs.
    The tail is still fenced by `is_provisional_provider` regardless of what
    is configured here — nothing on this chain can finalise a ruling.

    An empty/missing value keeps today's behaviour byte for byte.
    """
    raw = getattr(cfg, "noncritical_operator", None) if cfg is not None else None
    if isinstance(raw, str):
        raw = [raw]
    order = tuple(str(k).strip() for k in (raw or ()) if str(k).strip())
    # Strip Claude, loudly. A config key that can be written from a phone is exactly where a
    # "never use Claude for ancillary work" rule gets undone by accident, so the fence lives at
    # the point the chain is BUILT rather than in the file that declares it. Dropping is
    # deliberate over raising: this runs inside the unattended daemon, and a stale config must
    # cost a degraded chain and a WARNING, never a dead engine.
    kept = tuple(k for k in order if k not in _NONCRITICAL_FORBIDDEN)
    if len(kept) != len(order):
        logger.warning(
            "noncritical_operator names %s, which is barred from the non-critical chain "
            "(founder directive 2026-08-14); using %s",
            "/".join(k for k in order if k in _NONCRITICAL_FORBIDDEN),
            "/".join(kept or _NONCRITICAL_ORDER))
    return kept or _NONCRITICAL_ORDER


# ---------------------------------------------------------------------------
# Core vetting unit
# ---------------------------------------------------------------------------

@track_latency(name="vet_candidate")
def _build_prose_chain(cfg: Config, order, fallback_op: Operator, *, label: str) -> Operator:
    """Build a prose-generation chain from a config-declared operator list.

    Shared by the deliverable chain and the marketing-copy chain so the two can never drift in
    breaker wiring or failure semantics — only in WHICH providers they name. Each tier is
    circuit-broken against the NON-CRITICAL health file (a CLI hiccup in prose must never blind
    the moat verdict path). Falls back to ``fallback_op`` when no configured tier can be built,
    so generation never hard-fails on this.
    """
    from .health import get_noncritical_health
    from .operator import FallbackOperator, _build_operator

    if isinstance(order, str):
        order = [order]
    tiers = []
    for kind in (order or []):
        try:
            tiers.append((kind, _build_operator(kind, cfg, fast=False)))
        except RuntimeError:
            pass  # CLI not on PATH / not configured — skip this tier
    if not tiers:
        logger.warning("%s chain %s unavailable; falling back", label, order)
        return fallback_op
    if len(tiers) == 1:
        logger.info("%s operator: %s", label, tiers[0][0])
        return tiers[0][1]
    r = cfg.retrieval
    logger.info("%s chain: %s", label, " → ".join(n for n, _ in tiers))
    return FallbackOperator(tiers, failure_threshold=r.breaker_failure_threshold,
                            cooldown_s=r.breaker_cooldown_s, health=get_noncritical_health())


def _build_artifact_op(cfg: Config, fallback_op: Operator) -> Operator:
    """Build the quality chain for the customer-facing £49 deliverable.

    The pack's prose (build_spec / gtm_plan / ops_plan) IS the product, so it is generated by
    ``cfg.artifact_operator`` rather than the cheap non-critical tail. Deliberately NOT moved to
    the non-critical chain by the 2026-08-14 split: the founder's "claude should never be used
    for non-critical" is about ancillary work, and the thing the buyer paid £49 for is not
    ancillary.

    What DID change, 2026-08-18: this chain no longer LEADS with a subscription CLI. `claude_cli`
    is a binary whose auth lives in `~/.claude` and does not travel to a server, so leading with
    it made a Claude subscription a hard requirement for producing the product at all. It is now
    second — reached when the lead fails, and used as the shelf-copy escalation target via
    `_escalation_order` — which is what "an option, not a dependency" means in code.
    """
    return _build_prose_chain(cfg, cfg.artifact_operator, fallback_op,
                              label="Artifact deliverable")


def _escalation_order(cfg: Config) -> list[str]:
    """Where a shelf-copy breach is rewritten: the quality chain, minus the brain that failed.

    The marketing chain wrote copy the publish gate refused. Rewriting it on a chain that leads
    with that same brain spends a second call to get the same answer, while the log says the
    guardrail fired. So the escalation order is ``cfg.artifact_operator`` with the marketing
    chain's LEAD removed.

    Returns an empty list when nothing is left, which is a real state and not an error: it means
    the two chains are the same brain all the way down, and the honest thing is to skip the
    escalation rather than perform one. `_generate_pack_content` says so once, at INFO.

    This was cosmetic until 2026-08-18. `artifact_operator` led with `claude_cli` and
    `marketing_operator` with `minimax`, so any escalation was already a change of brain. Making
    Claude Code optional (founder: "we cant be depedint on claude code, it has to be a option
    only") put `minimax` at the head of both, and the two sentences stopped meaning the same
    thing.
    """
    # `getattr`, not `cfg.artifact_operator`, because `cfg` is optional on this path: several
    # callers and every budget-rail test pass `cfg=None` to `_generate_pack_content`. A plain
    # attribute read raised `AttributeError: 'NoneType' object has no attribute
    # 'artifact_operator'` and took six tests in tests/unit/test_tick_budget_rails.py down with
    # it. No config means no chain to escalate to, which is the empty list this already returns.
    quality = list(getattr(cfg, "artifact_operator", None) or [])
    marketing = list(getattr(cfg, "marketing_operator", None) or quality)
    lead = marketing[0] if marketing else None
    return [kind for kind in quality if kind != lead]


def _build_marketing_op(cfg: Config, fallback_op: Operator) -> Operator:
    """Build the CHEAP chain for shelf/marketing copy (founder directive 2026-08-14).

    Splitting this off the deliverable chain is the whole point: measured live on 2026-08-13
    the daemon was running four concurrent `claude -p` calls at ~90s each, and three of them
    were writing listing and marketing copy — a card line and a headline, at the price of the
    product itself.

    The guardrail that makes this safe is NOT this function, it is
    `_generate_pack_content`: copy from this chain is graded against the same shelf bar that
    `bridge.py` applies at publish time, and a breach ESCALATES the rewrite to
    ``cfg.artifact_operator`` MINUS this chain's lead (`_escalation_order`) instead of shipping
    the pack UNLISTED. Cheap gets first refusal, never the last word.
    """
    # `getattr` with the deliverable chain as the fallback, so a Config that predates the
    # split — an older config object, a test double, a pickled cfg — keeps its pre-split
    # behaviour byte-for-byte instead of raising inside the daemon's publish path. Falling
    # back to `artifact_operator` and not to `_NONCRITICAL_ORDER` is deliberate: the safe
    # default for buyer-visible copy is the EXPENSIVE chain, because that is where it ran
    # until this directive.
    order = getattr(cfg, "marketing_operator", None) or cfg.artifact_operator
    return _build_prose_chain(cfg, order, fallback_op, label="Marketing copy")


def publish_and_record(dossier: Dossier, cfg: Config, store: Optional[Store] = None) -> str:
    """Publish a non-provisional PASS and RECORD the outcome on the dossier. Returns the status.

    A publish failure USED to be caught here, logged to `store/prospector.jsonl` (NOT the
    interactive stream) and swallowed: the dossier came back normally, the exit code never
    changed, and no field anywhere distinguished "PASS, listed" from "PASS, listing never
    written". A scheduled batch printed PASS while `store/listings/<id>.json` was never
    created — the drift class this repo already tracks in
    `a-listed-pack-had-only-a-kill-dossier`.

    Two failure shapes, both recorded:
      * the call RAISES (network, provisioning, a crashed bundler); and
      * the call RETURNS a refusal. `publish()` reports most refusals by return value
        (`{"status": "error"|"skipped"|"dry_run"|...}`), not by raising, so "did not throw"
        was never evidence that anything was listed.

    Module-level rather than inline in `vet_candidate` so this is provable without running a
    full vet — a live vet cannot run offline and the test would skip in CI, which is exactly
    where the guard most needs to hold.
    """
    from . import claim_lock, progress
    cid = getattr(getattr(dossier, "candidate", None), "candidate_id", "?")

    # THE MONEY RAIL'S MUTUAL EXCLUSION. Publishing mints a provider Price and writes the
    # catalogue row (`bridge.py`), so it is the one step in this engine that costs real money
    # and cannot be made idempotent by retrying: two processes publishing one candidate mint
    # TWO prices for one pack, and the catalogue then disagrees with the rail — the drift that
    # `the-catalogue-took-the-fallback-the-rail-took-the-decision` records, which charges a
    # buyer and then fails the fulfilment fence.
    #
    # Under the tick this could not happen: one process, one deadline. The producer/consumer
    # split is what makes it reachable — `consume --publish` is designed to be run as more than
    # one worker, and the queue lease (`store.claim`) deliberately does not cover this. The
    # lease excludes two consumers from VETTING one row; it says nothing about a manual
    # `vet --resume --publish` racing a consumer, or a re-publish racing a first publish.
    #
    # Refusal is a SKIP, never a wait and never a failure: `claim_lock.claiming` returns
    # immediately (claim_lock.py:170) because a rail that blocks is a rail that stalls a drain,
    # and "someone else is publishing this right now" is not an error to record. Critically the
    # loser also does NOT write to the dossier or the store — the winner is mid-publish with its
    # own copy of this row, and a `store.save` here would overwrite `published` with a status
    # about our own lock. Nothing to say, so nothing is written.
    with claim_lock.claiming(cid, claim_lock.PUBLISH_PURPOSE, cfg=cfg) as got:
        if not got:
            logger.info("Publish skipped for %s — another process holds the publish claim", cid,
                        extra={"candidate_id": cid, "purpose": claim_lock.PUBLISH_PURPOSE})
            progress.note(f"publish skipped for {cid} — another worker holds the publish claim")
            return "skipped_locked"
        return _publish_and_record_claimed(dossier, cfg, store, cid=cid)


def _publish_and_record_claimed(dossier: Dossier, cfg: Config, store: Optional[Store],
                                *, cid: str) -> str:
    """The body of `publish_and_record`, run only by the holder of the publish claim.

    Split out so the claim is visibly the OUTER scope of every path that can write a listing —
    an early `return` added inside this body later cannot accidentally escape the lock, which
    is how a `with` that wraps 40 lines of branching eventually leaks.
    """
    from . import progress
    try:
        from publish.publish import publish as _publish
        res = _publish(dossier, cfg) or {}
        status = str(res.get("status", "")) if isinstance(res, dict) else ""
        if status == "published":
            dossier.publish_status = "published"
            dossier.publish_error = None
        else:
            dossier.publish_status = "failed"
            dossier.publish_error = f"publish returned status={status or 'unknown'!r}: {res}"
            logger.error(f"Publication did not list {cid}",
                         extra={"candidate_id": cid, "status": status})
            progress.note(f"PUBLISH FAILED for {cid} — status={status or 'unknown'} "
                          f"(dossier is a PASS, but nothing was listed)")
    except Exception as e:
        dossier.publish_status = "failed"
        dossier.publish_error = f"{type(e).__name__}: {e}"
        logger.error(f"Publication failed for {cid}", extra={"error": str(e)})
        progress.note(f"PUBLISH FAILED for {cid} — {type(e).__name__}: {e} "
                      f"(dossier is a PASS, but nothing was listed)")
    if store is not None:
        # Re-save so the PERSISTED dossier carries the publish outcome, not just the verdict.
        store.save(dossier)
    return dossier.publish_status


def vet_candidate(
    cand: Candidate,
    op: Operator,
    search: SearchProvider,
    cfg: Config,
    store: Optional[Store] = None,
    query_op: Optional[Operator] = None,
    publish: bool = False,
    show_checks: bool = False,
    label: Optional[str] = None,
    skip_adversarial: bool = False,
    full_vet: bool = False,
    experimental_op: Optional[Operator] = None,
    board_personas: Optional[list[str]] = None,
    artifact_time_budget_s: Optional[float] = None,
    vet_deadline_mono: Optional[float] = None,
) -> Dossier:
    """Run the full verification pipeline for a single candidate.

    Steps:
      1. Run the six kill-checks (kill-fast).
      2. Score only if no gate fired.
      3. Assemble Dossier with UTC timestamps.
      4. Persist via store if provided.

    Secondary artifacts + marketing content (~12 model calls) and syndication are
    deferred behind ``publish``: a plain vet produces only the grounded verdict +
    score (cheap). Pass publish=True to generate listing content and publish on
    PASS. ``query_op`` is an optional lighter model for the mechanical query-gen
    step (model tiering); falls back to ``op``.

    Args:
        full_vet: When True, bypasses kill-fast and runs ALL checks (Stochastic Full-Vetting).
        experimental_op: Optional operator to run verification against in parallel
            (Shadow Moat). Findings are logged but do not change the dossier decision.
        board_personas: Optional list of persona names to run as 'Advisory Board'.
            Each persona runs verification in parallel and findings are logged.
        artifact_time_budget_s: Wall-clock ceiling on THIS candidate's publish-time artifact
            + marketing phase (`_generate_pack_content`, and only when ``publish``). Forwarded
            untouched; see that function for the measurement that produced the rail. Ignored
            on a plain vet, which generates no content. None leaves the phase unbounded.
        vet_deadline_mono: Absolute `time.monotonic()` instant the whole BATCH stops at, used
            here only to clamp the artifact ceiling above. A vet already running when the
            batch budget is spent cannot be cancelled, so without this clamp it could still
            spend its full per-candidate allowance past the tick's hard deadline.
    """
    set_context(candidate_id=cand.candidate_id, phase="vetting")
    logger.info(f"Vetting candidate: {cand.title!r} (full_vet={full_vet}, persona={cfg.active_persona})")

    from . import progress
    from .audit import audit
    from .audit import run_id as _run_id

    # SUB-TICK PROGRESS (R5): the boundary rows. Per-check rows alone cannot say whether a
    # candidate is still being worked or was abandoned, so a reader would call a crashed vet
    # "in flight" forever. Emitted HERE rather than at submission in run_signal because this
    # runs in the worker thread — it marks the moment work actually started, and it covers
    # every caller (single vet, `vet --resume`, the daemon), not just the batch pool.
    #
    # Deliberately NOT wrapped in try/finally: vet_candidate has exactly one return
    # (`return dossier`), and re-indenting ~160 lines to catch the raise path would be a far
    # larger diff than the case warrants. A start with no done is instead resolved by the
    # READER, which must handle it regardless — a SIGKILLed daemon can never emit its own
    # `candidate_done`, so staleness has to be the reader's rule, not the writer's promise.
    # THE AUDIT ROW IS NOT A RECORD OF THE WORK. It names the candidate; it does not hold it.
    # A process killed here left no dossier and no index row, so the candidate itself ceased to
    # exist — measured 2026-08-17: 10 of 12 candidates abandoned by two daemon restarts had no
    # record anywhere in `store/`. `inflight` keeps the candidate on disk for exactly as long as
    # this vet owns it, so `vet --resume` can pick it up when this process dies.
    if store is not None:
        from . import inflight as _inflight

        _inflight.open_(store.root, cand, run_id=_run_id(), label=label or "",
                        full_vet=bool(full_vet))

    audit("candidate_start",
          candidate_id=cand.candidate_id,
          title=(cand.title or "")[:120],
          tier=getattr(cand, "ambition_tier", "") or "",
          full_vet=bool(full_vet),
          label=label or "")

    def _check_line(res, prefix: str = "") -> str:
        v = res.verdict.value
        mark = "✗" if v in ("refuted", "unverifiable") else "✓"
        return f"{prefix}{mark} {res.check_name} → {v} (conf {res.confidence:.2f})"

    on_check = None
    if label:
        # Concurrent signal pool: tag EVERY line with the candidate so interleaved
        # output from parallel vets stays attributable, and emit a line the moment
        # the vet starts so the user gets immediate feedback (not a 60s silence).
        progress.note(f"{label} ▸ vetting started" + (" [FULL-VET]" if full_vet else ""))
        def on_check(res) -> None:
            progress.note(_check_line(res, prefix=f"{label} "))
    elif show_checks:
        # Single-vet: no interleaving, so no candidate prefix needed.
        if full_vet:
            progress.note("Full-vet mode: short-circuit disabled.")
        def on_check(res) -> None:
            progress.note(_check_line(res))

    verify = _get_verify()
    # Build the moat operator chain string for the audit trail (e.g. "claude/claude-opus-4-8 →
    # claude-cli/default").  FallbackOperator.name is already in that format.
    _provider_chain = getattr(op, "name", "") or getattr(op, "model_version", "") or str(op)
    
    # Shadow Moat: Run experimental verification in parallel if requested.
    # We do this first (or concurrently) to ensure it doesn't wait for the primary.
    exp_res = None
    if experimental_op:
        logger.info(f"SHADOW MOAT: Running experimental vet for {cand.title!r}")
        try:
            # Run a silent verification (no progress updates)
            exp_res = verify(experimental_op, search, cfg, cand, 
                            skip_adversarial=skip_adversarial, full_vet=full_vet)
        except Exception as e:
            logger.warning(f"Shadow Moat failed for {cand.candidate_id}: {e}")

    # ADVISORY BOARD (Part 16 principal upgrade): Run shadow personas in parallel.
    board_results = {}
    if board_personas:
        for p_name in board_personas:
            if p_name == cfg.active_persona:
                continue
            logger.info(f"ADVISORY BOARD: persona {p_name!r} analyzing {cand.title!r}")
            try:
                p_cfg = cfg.for_persona(p_name)
                # Run silent verification with shadow persona
                p_res = verify(op, search, p_cfg, cand, 
                               skip_adversarial=skip_adversarial, full_vet=full_vet)
                board_results[p_name] = p_res
            except Exception as e:
                logger.warning(f"Advisory Board failed for persona {p_name!r}: {e}")

    try:
        checks, adversarial, gate = verify(op, search, cfg, cand,
                                           on_check=on_check, query_op=query_op,
                                           skip_adversarial=skip_adversarial,
                                           full_vet=full_vet,
                                           # THE HOP THAT WAS MISSING. Until now this deadline
                                           # reached only `_generate_pack_content`, where it
                                           # clamped the ARTIFACT ceiling (run.py:559-561) —
                                           # the cheap end. Query gen, retrieval and seven
                                           # verdict calls, which are where the time actually
                                           # goes, never saw it. That is why the drain's 270s
                                           # wall was measured spending 1462s on 2026-08-15:
                                           # the wall stopped new ROWS and could not stop the
                                           # row that was running.
                                           deadline_mono=vet_deadline_mono)
    except ProviderExhaustedError as e:
        # Both Claude AND Gemini are exhausted — the moat is down.  This is NOT a
        # candidate quality failure; defer the candidate for re-vet when the moat
        # recovers.  Log a moat-outage telemetry event so the audit trail is complete.
        logger.warning(f"Moat exhausted for {cand.title!r}: {e}; deferring "
                       f"(re-vet when moat recovers via `vet --resume`)",
                       extra={"candidate_id": cand.candidate_id,
                              "provider_exhausted": str(e)[:200],
                              "event": "moat_outage"})
        from .telemetry import record_usage
        record_usage(input_tokens=0, output_tokens=0, total_tokens=0, cached_tokens=0, web=False,
                     message=f"MOAT OUTAGE: {cand.candidate_id} deferred — {str(e)[:100]}")
        checks, adversarial = [], None
        gate = "moat_exhausted"

    # Log Shadow Moat drift
    if exp_res:
        exp_checks, exp_adv, exp_gate = exp_res
        if exp_gate != gate:
            logger.warning(f"SHADOW MOAT DRIFT for {cand.candidate_id}: "
                           f"Primary={gate} vs Experimental={exp_gate}",
                           extra={"primary": gate, "experimental": exp_gate, 
                                  "candidate": cand.title})
    
    # Log Advisory Board findings
    for p_name, (p_checks, p_adv, p_gate) in board_results.items():
        if p_gate != gate:
            logger.info(f"ADVISORY BOARD ({p_name!r}) differs for {cand.candidate_id}: "
                        f"Primary={gate} vs {p_name}={p_gate}",
                        extra={"primary_persona": cfg.active_persona, "shadow_persona": p_name,
                               "primary_gate": gate, "shadow_gate": p_gate})
        else:
            logger.info(f"ADVISORY BOARD ({p_name!r}) agrees with primary decision ({gate})")

    score = None
    if gate is None:
        logger.info("Candidate survived all gates. Scoring...")
        # FIX #12: score is a rubric classification — route to flash-lite via query_op.
        score = score_candidate(op, cfg, cand, checks, scorer_op=query_op)

        if publish:
            # --- Task B: Secondary artifacts + claim-check (publish-time only) ---
            # FIX #12: route artifact/marketing generation to flash-lite (query_op/fast_op).
            # FIX #13: generate_artifacts and generate_marketing_content are now
            # parallelized internally (ThreadPoolExecutor) — 4 threads instead of
            # sequential, cutting PASS-survivor latency by ~50%.
            logger.info("Generating publish-time artifacts + marketing content...")
            from .artifacts import generate_artifacts, generate_marketing_content  # noqa: F401
            # The £49 deliverable's prose runs on the quality CLI chain (Gemini CLI -> Claude
            # CLI), not flash-lite. The financial model (Python-computed) and ancillary
            # marketing stay on fast_op; claim-check runs on the moat `op` (a verification gate
            # must never be judged by the cheap model that wrote the copy).
            quality_op = _build_artifact_op(cfg, op)
            marketing_op = _build_marketing_op(cfg, op)
            # `score` (computed just above) is passed explicitly because this call runs
            # BEFORE `build_dossier` below — without it the pack's scorecard artifact ships
            # `score_available: false` (register §27.2 item 4).
            cand.tags["artifacts"], cand.tags["marketing"] = _generate_pack_content(
                op, cand, checks, query_op=query_op, quality_op=quality_op,
                marketing_op=marketing_op, cfg=cfg,
                score=score, artifact_time_budget_s=artifact_time_budget_s,
                vet_deadline_mono=vet_deadline_mono)

    now = datetime.datetime.now(datetime.timezone.utc)

    created_at = now.isoformat()
    reverify_due_at = (now + datetime.timedelta(days=30)).isoformat()

    dossier = build_dossier(
        cand=cand,
        checks=checks,
        adversarial=adversarial,
        gate_fired=gate,
        score=score,
        cfg=cfg,
        op_model_version=op.model_version,
        provider_chain=_provider_chain,
        created_at=created_at,
        reverify_due_at=reverify_due_at,
    )

    if store is not None:
        store.save(dossier)

    if publish and dossier.decision == Decision.PASS and not dossier.provisional:
        publish_and_record(dossier, cfg, store)
    elif publish and dossier.decision == Decision.PASS and dossier.provisional:
        # Provisional PASS: the moat was exhausted and the cheap fallback tail ruled.
        # Real-but-untrusted — never publish. It will auto re-vet on `vet --resume`.
        logger.warning(
            f"Provisional PASS held back from publication for {cand.candidate_id} "
            f"(ruled by emergency fallback; awaiting moat re-vet via `vet --resume`).",
            extra={"candidate_id": cand.candidate_id, "provider_chain": _provider_chain})

    logger.info(f"Vetting complete: {dossier.decision.value.upper()}",
                extra={"decision": dossier.decision.value, "gate": gate})
    # SUB-TICK PROGRESS (R5): the closing boundary. `provisional` is carried because a
    # provisional row is not a finished answer — it is scheduled for re-vet — and a panel that
    # showed it as settled would report the drain as shorter than it is.
    _sc = getattr(dossier, "score", None)
    audit("candidate_done",
          candidate_id=cand.candidate_id,
          decision=dossier.decision.value,
          gate=gate or "",
          provisional=bool(getattr(dossier, "provisional", False)),
          # `composite` is OMITTED, not defaulted, when the candidate never reached scoring
          # (kill-fast returns before score_candidate) or when scoring itself failed. A
          # default of 0.0 here would be indistinguishable from a real 0.0 composite, which
          # is the `score_failed` distinction models.py:336 exists to preserve.
          **({} if _sc is None or getattr(_sc, "score_failed", False)
             else {"composite": round(float(_sc.composite or 0.0), 3)}))
    # The verdict is on disk, so this candidate is no longer work anyone has to recover.
    if store is not None:
        from . import inflight as _inflight

        _inflight.close(store.root, cand.candidate_id)
    return dossier



# ---------------------------------------------------------------------------
# Signal pipeline
# ---------------------------------------------------------------------------

@track_latency(name="run_signal")
def run_signal(
    signal_text: str,
    cfg: Optional[Config] = None,
    op: Optional[Operator] = None,
    search: Optional[SearchProvider] = None,
    store: Optional[Store] = None,
    k: Optional[int] = None,
    publish: bool = False,
    exploration: Optional[float] = None,
    lanes: Optional[list] = None,
    focus: Optional[str] = None,
    board_personas: Optional[list[str]] = None,
    gen_time_budget_s: Optional[float] = None,
    artifact_time_budget_s: Optional[float] = None,
    vet_time_budget_s: Optional[float] = None,
    vet: bool = True,
) -> list[Dossier]:
    """Generate candidates from a signal, dedup, prescreen, vet each, return dossiers.

    ``vet=False`` makes this the PRODUCER: it runs the funnel down to novelty selection and
    then enqueues every survivor as a DEFER row instead of ruling on it (see
    ``enqueue_candidates``). The returned dossiers are queue entries with no verdict — the
    consumer (``vet --resume``) turns them into rulings on its own clock. Every rail above the
    split still applies unchanged, deliberately: dedup, prescreen and novelty selection are
    what stop the producer from filling the queue with near-duplicates that the consumer would
    then pay a moat verdict each to reject. The default stays True so the single-process path,
    the CLI and every existing caller behave exactly as before.

    Any of cfg/op/search/store may be None — defaults are loaded automatically.
    Plain runs are cheap (verdict + score only); pass publish=True to also
    generate listing artifacts and publish PASSes. ``signal_text=""`` runs
    blue-sky generation. ``exploration`` overrides the adaptive exploration level
    when provided (e.g. the ``generate`` CLI's ``--exploration``).

    ``gen_time_budget_s``: wall-clock budget for the GENERATION phase only. The scheduler
    passes a fraction of its tick deadline (schedule.gen_budget_frac x
    PROSPECTOR_TICK_DEADLINE_S) so a degraded generation chain can never spend the whole
    tick generating and force-exit before vetting runs (the 2026-08-14 failure). None (the
    CLI default) leaves generation unbounded, exactly as before.

    ``artifact_time_budget_s``: per-candidate ceiling on the publish-time artifact + marketing
    phase, forwarded to every `vet_candidate` and consumed in `_generate_pack_content`. Named
    per-CANDIDATE, not per-tick, on purpose: a tick-absolute artifact deadline would let the
    first survivors spend the whole allowance and leave every later survivor with an empty
    build_spec/gtm_plan/ops_plan — which publishes UNLISTED and unsellable
    (`_generate_pack_content`'s docstring: 12 of 24 off-shelf passes are exactly that).

    ``vet_time_budget_s``: ceiling on the WHOLE vetting loop below. When it is spent the loop
    cancels every vet that has not started and returns what it has. This is the rail that
    makes a tick end by its own decision instead of by `_force_exit_hung_tick`'s SIGKILL.

    Why the second rail is not optional arithmetic: profiling the tick that force-exited at
    2026-08-15T13:17:56Z (batch=15) measured 1200s of wall clock PER SURVIVING CANDIDATE —
    3 hours bought 18 vets, 9 survivors, 3 publishes and 528 LLM calls. At `batch_size: 50`
    that is ~10 hours of work inside a 10800s deadline on a 7200s interval, so NO budget can
    make the batch fit. What a budget can do is change the failure from "the process is killed
    mid-candidate and the tick row is lost" to "the tick banks every verdict it paid for, says
    how many it declined to start, and hands the rest to the next tick". Partial and honest
    beats complete and dead.

    Both default to None, which is byte-for-byte the pre-2026-08-15 behaviour for every CLI
    caller; only the daemon passes them.

    ``lanes`` (Part 14 — multi-lane-by-default): the ambition tiers this run spans.
      - None         => no lane engaged; byte-for-byte today's single-default behaviour.
      - [X]          => single pinned tier (generate + vet in tier X; classify skipped).
      - [X, Y, ...]  => MIXED catalogue: fan generation out per tier, auto-classify each idea
                        into its natural tier, then vet EACH against its OWN tier's bar.
    """
    from . import progress
    from .telemetry import get_usage_summary, reset_usage
    set_context(phase="signal_pipeline")
    logger.info("Starting signal pipeline")
    reset_usage()  # fresh token ledger for this run
    progress.banner("Signal pipeline starting")

    # --- Load defaults ---
    if cfg is None:
        cfg = load_config()
    _sync_cli_concurrency(cfg)

    if op is None:
        from .operator import make_operator
        op = make_operator(cfg)

    # Tiered non-critical chain (fast_op): cheapest operators first, last-resort
    # fallback to Gemini-flash.  Claude is deliberately EXCLUDED — it is too expensive
    # for mechanical JSON work (prescreen, scoring, content).  The moat chain (Claude→
    # Gemini) is only used for kill-check verdicts and adversarial analysis.
    #
    # Tier 1: DeepSeek-chat  $0.27/M in  (best for structured JSON output)
    # Tier 2: MiniMax-M2.7   $0.30/M in  (secondary; robust fallback)
    # Tier 3: Gemini-flash   $0.075/M in (last resort; cheaper per-token than Claude)
    #
    # Each tier is guarded by an independent circuit breaker.  A quota exhaustion on
    # DeepSeek skips it and tries MiniMax; MiniMax exhausted skips to Gemini-flash;
    # Gemini-flash exhausted → all three skipped → ProviderExhaustedError → DEFER.
    # A tier's health mark does NOT pollute the moat health file (moat stays clean).
    from .errors import GroundingInfrastructureError, ProviderExhaustedError
    from .health import get_noncritical_health
    from .operator import FallbackOperator, _build_operator

    # Founder-fence: the non-critical chain records exhaustion to its OWN health file,
    # never the moat's. A dead DeepSeek/MiniMax/Gemini-flash here must not blind the
    # Claude→Gemini moat (and vice versa).
    _noncritical_health = get_noncritical_health()

    def _build_operator_chain(order: tuple[str, ...], fast: bool) -> Operator:
        """Build a FallbackOperator from the given tier order. Raises if none available."""
        tiers = []
        for kind in order:
            try:
                tiers.append((kind, _build_operator(kind, cfg, fast=fast)))
            except RuntimeError:
                pass  # tier not configured or missing API key
        if len(tiers) == 0:
            raise ProviderExhaustedError(
                f"All operators in {order} unavailable — check API keys and credentials.")
        if len(tiers) == 1:
            logger.info(f"Single operator: {tiers[0][0]}")
            return tiers[0][1]
        r = cfg.retrieval
        chain = FallbackOperator(tiers, failure_threshold=r.breaker_failure_threshold,
                                cooldown_s=r.breaker_cooldown_s,
                                health=_noncritical_health)
        logger.info(f"Chain: {' → '.join(n for n, _ in tiers)}")
        return chain

    # gen_op: divergent candidate generation (non-critical).
    _nc_order = _noncritical_order(cfg)
    gen_op = _build_operator_chain(_nc_order, fast=True)

    # fast_op: prescreen / scoring / mechanical JSON (non-critical), same order.
    fast_op = _build_operator_chain(_nc_order, fast=True)

    # Shadow Moat (Part 16 principal upgrade): optionally load an experimental 
    # operator to run in parallel. Findings are logged for drift analysis.
    experimental_op = None
    exp_name = getattr(cfg, "experimental_operator", None)
    if exp_name:
        try:
            experimental_op = _build_operator(exp_name, cfg)
            logger.info(f"SHADOW MOAT ENABLED: using experimental operator {exp_name!r}")
        except Exception as e:
            logger.warning(f"Could not initialize shadow moat operator {exp_name!r}: {e}")

    if search is None:
        from .retrieval import make_provider
        search = make_provider(cfg)

    if store is None:
        store = Store(cfg)

    # --- Adaptive creativity (Part 3) ---
    from .adaptive import (
        blue_sky_failure_steer,
        calculate_exploration_level,
        calculate_grid_priorities,
        get_exemplars,
        get_recent_failure_modes,
        select_lenses,
    )
    expl = exploration if exploration is not None else calculate_exploration_level(store, cfg=cfg)
    fails = get_recent_failure_modes(store, cfg=cfg)
    # Blue-sky (no signal): the kill log is domain-specific and, fed raw, drags
    # generation back into the saturated domain. Reframe it as a no-go zone +
    # cross-sector mandate so blue-sky actually ranges (Part 15B breadth KPI).
    if not signal_text.strip():
        fails = blue_sky_failure_steer(fails)
    
    # ML Improvement: Exemplar injection (Stage 2)
    exemplars = get_exemplars(store, op)
    if exemplars:
        fails = (fails or "") + "\n\n" + exemplars

    # ML Improvement: Grid Scheduler (Stage 3)
    grid_priorities = calculate_grid_priorities(store, cfg)

    lenses = select_lenses(cfg, expl, k=k or 5)
    logger.info(f"Adaptive Controller: expl={expl:.1f}", extra={"exploration_level": expl, "fails": fails, "lenses": lenses, "grid_priorities": grid_priorities})

    # --- Spend guard (Part 9) ---
    from .spend import SpendGuard
    guard = SpendGuard(daily_cap_usd=cfg.spend.daily_cap_usd,
                       warn_at_usd=cfg.spend.warn_at_usd)

    # --- Generate ---
    # Positive learning: extract PASS survivor patterns for injection into generation.
    from .adaptive import get_pass_traits
    patterns = get_pass_traits(store)

    # CROSS-RUN ANTI-DUPLICATION MEMORY. The blue-sky daemon re-runs generation every cycle;
    # without telling the model what it has ALREADY produced (PASS and KILL alike), it keeps
    # regenerating the same idea families (the live near-duplicate probate packs). Seed the
    # generator's `avoid` list from the freshest dossier titles so it explores NEW ground.
    prior_titles = store.recent_titles(limit=200)

    # Chain-exhaustion sink. `generate`/`generate_multilane` write `chain_exhausted` here when
    # the non-critical chain hits its quota wall MID-RUN. The aggregate `if not candidates:`
    # test below cannot see that case — waves that already produced survivors mask it — so
    # partial exhaustion used to skip `_save_pending_signal` entirely and lose the signal.
    _gen_diag: dict = {}

    # ONE absolute deadline for the whole generation phase, converted here so multi-lane
    # (concurrent lanes) and single-lane paths share the same wall-clock bound.
    import time as _time
    _gen_deadline = (_time.monotonic() + gen_time_budget_s) if gen_time_budget_s else None
    # The vetting loop's own absolute bound, taken from the SAME instant so the two phases
    # are measured against one clock and their fractions are comparable.
    _vet_deadline = (_time.monotonic() + vet_time_budget_s) if vet_time_budget_s else None

    # FIX: MiniMax generation — gen_op (MiniMax) for generation; op (Claude/Gemini) stays
    # for verification.  gen_op falls back to op if MINIMAX_API_KEY is not configured.
    if lanes and len(lanes) > 1:
        # MULTI-LANE (Part 14): fan generation out across tiers.
        # Tier is set inside generate_multilane() directly from the lane loop variable —
        # no LLM call needed to re-confirm what generation already assigned.  The lane
        # config (cfg.for_lane(tier)) shaped the idea at generation time; the tier tag
        # is the authoritative routing key for the downstream vetting bar.
        from .generate import generate_multilane
        counts = _lane_counts(cfg, lanes, k)
        progress.step(f"multi-lane generation across {len(lanes)} tier(s): {counts}")
        candidates = generate_multilane(
            op, cfg, lanes=lanes, lane_counts=counts, signal_text=signal_text,
            strategy_lens=lenses, exploration_level=expl, recent_failure_modes=fails,
            prior_titles=prior_titles,
            gen_op=gen_op, grid_priorities=grid_priorities, focus=focus,
            pass_patterns=patterns, diagnostics=_gen_diag, deadline_mono=_gen_deadline)
        # ambition_tier already set inside generate_multilane (c.ambition_tier = tier).
    elif lanes:
        # SINGLE pinned tier (--lane X or config active_lane): generate in that tier, tag it,
        # skip classify (the tier is fixed by the operator's choice).
        tier = lanes[0]
        # ML Improvement: Grid Scheduler (Stage 3)
        priorities = (grid_priorities or {}).get(tier)
        candidates = generate(
            op, cfg.for_lane(tier), signal_text=signal_text, k=k,
            strategy_lens=lenses, exploration_level=expl, recent_failure_modes=fails,
            gen_op=gen_op, grid_priorities=priorities, focus=focus,
            pass_patterns=patterns, prior_titles=prior_titles, diagnostics=_gen_diag,
            deadline_mono=_gen_deadline)
        for c in candidates:
            c.ambition_tier = tier
    else:
        # DEFAULT (no lane engaged): byte-for-byte today's single-default behaviour.
        # Use 'venture' (default) prioritized forms
        priorities = (grid_priorities or {}).get("venture")
        candidates = generate(
            op, cfg, signal_text=signal_text, k=k,
            strategy_lens=lenses, exploration_level=expl, recent_failure_modes=fails,
            gen_op=gen_op, grid_priorities=priorities, focus=focus,
            pass_patterns=patterns, prior_titles=prior_titles, diagnostics=_gen_diag,
            deadline_mono=_gen_deadline,
        )
    if not candidates:
        # Generation chain exhausted — save the signal text so the operator can
        # re-run it later with `generate --resume`.  Never lose a signal.
        _save_pending_signal_or_shout(signal_text, cfg)
        logger.warning(f"Generation chain exhausted ({'/'.join(_noncritical_order(cfg))} all "
                       f"unavailable or quota depleted). Signal saved for retry. Run "
                       f"`generate --resume` when generation chain recovers.")
        progress.step("generation chain exhausted — signal saved, re-run with generate --resume")
        return []
    if _gen_diag.get("chain_exhausted"):
        # PARTIAL exhaustion: some candidates came back, then the chain died. The candidates in
        # hand are real and are vetted below — but the signal was NOT fully generated, so it is
        # saved for `generate --resume` exactly as a total exhaustion would be.
        _save_pending_signal_or_shout(signal_text, cfg)
        _errs = "; ".join(str(e) for e in _gen_diag.get("exhaustion_errors", [])[:3])
        logger.error(
            f"Generation chain exhausted MID-RUN after producing {len(candidates)} "
            f"candidate(s) ({'/'.join(_NONCRITICAL_ORDER)}). Signal saved for "
            f"`generate --resume`. Causes: {_errs}",
            extra={"chain_exhausted": True, "candidates": len(candidates)})
        progress.step(f"generation chain exhausted MID-RUN after {len(candidates)} candidate(s) "
                      f"— signal saved, re-run with generate --resume")
    elif _gen_diag.get("batch_failures") or _gen_diag.get("lane_failures"):
        # A generation CALL THREW (bad JSON, a crashed adapter, one lane dying) rather than
        # hitting a quota wall. `generate` returns `[]` for that exactly as it does for a wave
        # the model had no ideas for, so with a sibling wave producing survivors the run reads
        # as a normal, slightly thin batch and the signal is dropped — the zero-yield defect
        # this engine has re-diagnosed six times. Treated like partial exhaustion: the
        # candidates in hand are real and are vetted below, but the signal was not fully
        # generated, so it is saved for `generate --resume`.
        _save_pending_signal_or_shout(signal_text, cfg)
        _errs = "; ".join(str(e) for e in _gen_diag.get("batch_errors", [])[:3])
        logger.error(
            f"Generation PARTIALLY FAILED: {_gen_diag.get('batch_failures', 0)} batch(es) and "
            f"{_gen_diag.get('lane_failures', 0)} lane(s) raised after producing "
            f"{len(candidates)} candidate(s). Signal saved for `generate --resume`. "
            f"Causes: {_errs}",
            extra={"batch_failures": _gen_diag.get("batch_failures", 0),
                   "lane_failures": _gen_diag.get("lane_failures", 0),
                   "candidates": len(candidates)})
        progress.step(f"generation partially FAILED ({_gen_diag.get('batch_failures', 0)} batch, "
                      f"{_gen_diag.get('lane_failures', 0)} lane) — signal saved, re-run with "
                      f"generate --resume")
    logger.info(f"Generated {len(candidates)} candidates")
    progress.step(f"generated {len(candidates)} candidates")

    # --- Dedup against catalogue (per market: the same idea elsewhere is not a dupe) ---
    catalogue = store.catalogue_titles()
    # G1: per-batch diversity receipts, gated by cfg.generation.diversity_meter. The
    # meter is best-effort (returns None on any failure) so a misconfigured receipt
    # never breaks the generation path. "generated" captures the raw output before
    # dedup; "post_dedup" captures the survivors after near-duplicates are removed.
    write_receipt(cfg, "generated", candidates)
    unique, dropped = dedup(candidates, catalogue, threshold=cfg.dedup_threshold,
                            token_threshold=cfg.dedup_token_threshold,
                            default_market=_default_market(cfg))
    write_receipt(cfg, "post_dedup", unique)
    if dropped:
        by_market = drops_by_market(dropped)
        logger.info(f"Dedup dropped {len(dropped)} near-duplicate pair(s)",
                    extra={"dropped_by_market": by_market})
        detail = " ".join(f"{m or 'unset'}:{n}" for m, n in sorted(by_market.items()))
        progress.note(f"dedup dropped {len(dropped)} near-duplicate(s) [{detail}]")

    # --- Rejection fast-path (Part 8) ---
    # If an exact near-duplicate was KILLED within the SLA window, return that dossier immediately.
    final_candidates = []

    # Load recent KILLS
    all_kills = store.all(decision=Decision.KILL.value)
    now_dt = datetime.datetime.now(datetime.timezone.utc)

    for cand in unique:
        found_recent_kill = False
        for k_row in all_kills:
            # Check SLA (e.g. 30 days)
            due_str = k_row.get("reverify_due_at")
            if due_str and now_dt < datetime.datetime.fromisoformat(due_str):
                from .dedup import is_near_duplicate
                if is_near_duplicate(cand.title, k_row["title"]):
                    logger.info(f"REJECTION FAST-PATH: reusing kill record for {cand.title!r}", 
                                extra={"candidate_id": cand.candidate_id, "original_id": k_row["candidate_id"]})
                    k_dossier_dict = store.get(k_row["candidate_id"])
                    if k_dossier_dict:
                        found_recent_kill = True
                        break

        if not found_recent_kill:
            final_candidates.append(cand)

    # --- Prescreen (parallel) ---
    # prescreen() is a pure, no-web per-candidate call that NEVER raises (keep-biased
    # on any error). Running candidates concurrently overlaps the calls without changing
    # any keep/reject decision — physical load is still bounded by the CLI semaphores.
    # Results are collected in submission order so kept[] stays in generation order.
    from concurrent.futures import ThreadPoolExecutor
    prescreened_data: list[tuple[Candidate, float, str]] = []
    pre_workers = _vet_workers(cfg)
    with ThreadPoolExecutor(max_workers=pre_workers) as pre_ex:
        pre = [(cand, pre_ex.submit(prescreen, fast_op, cfg, cand))
               for cand in final_candidates]
        for cand, fut in pre:
            keep, score, reason, features = fut.result()
            if keep:
                prescreened_data.append((cand, score, features))
            else:
                logger.info(f"PRESCREENED OUT: {cand.title!r}", extra={"reason": reason})
                progress.note(f"prescreened out: {cand.title!r}")

    if not prescreened_data:
        logger.warning("No candidates survived prescreen")
        progress.step("0 candidates survived prescreen")
        return []

    # --- ML Improvement: DPP Novelty Selection ---
    # Instead of vetting ALL prescreened candidates, we select the most diverse 
    # and high-quality subset. This prevents spending moat tokens on near-duplicates.
    from .novelty import select_diverse_candidates
    # `cfg.generation` is a DICT (config.py builds it from the YAML block verbatim), so the
    # `getattr(cfg.generation, "candidates_per_signal", 5)` that stood here could never find
    # the key and silently returned the hardcoded 5 — on EVERY unattended tick, for as long as
    # the line has existed. Measured 2026-08-13 on the live config: `config.yaml:798` declares
    # `candidates_per_signal: 50` and this expression evaluated to `5`. The batch funnels agree
    # (`store/scheduler/batch_diagnostics.jsonl`, five ticks that day): `prescreen_in: 15` and
    # `novelty_selected: 5` every time. Ten of every fifteen candidates the engine had already
    # paid to generate, dedup and prescreen were thrown away one step before the moat, and
    # nothing logged it, because a default is not an error.
    #
    # `generate.py:218` reads the same key CORRECTLY (`gen_cfg.get(...)`). That asymmetry is the
    # whole bug: generation honoured the founder's number and vetting quietly did not, so raising
    # `candidates_per_signal` bought more candidates and vetted exactly as many as before.
    #
    # Read it the way the rest of the codebase reads a config section, and tolerate an object in
    # case the shape ever changes — never `getattr` alone on something that is a dict today.
    _gen_cfg = cfg.generation or {}
    _declared_k = (_gen_cfg.get("candidates_per_signal", 5) if isinstance(_gen_cfg, dict)
                   else getattr(_gen_cfg, "candidates_per_signal", 5))
    target_k = k or int(_declared_k)
    kept = select_diverse_candidates(op, prescreened_data, k=target_k)
    if len(kept) < len(prescreened_data):
        # Say it out loud. The silent version of this line is why a 3x throughput cut went
        # unnoticed: the funnel recorded the drop in a JSON file nobody reads per-tick.
        logger.info(
            "Novelty selection vetting %d of %d prescreened candidate(s) (cap k=%d from %s)",
            len(kept), len(prescreened_data), target_k,
            "--candidates" if k else "config generation.candidates_per_signal",
            extra={"novelty_selected": len(kept), "prescreened": len(prescreened_data),
                   "target_k": target_k})

    # THE PRODUCER/CONSUMER SPLIT. Everything above this line is generation — bounded, cheap,
    # and dependent on no brain that can be benched. Everything below is vetting, whose cost is
    # a moat verdict per candidate and whose tail was measured at 4127s. `vet=False` stops here:
    # the survivors become durable queue rows and this call returns without opening a pool.
    #
    # The split is HERE, after novelty selection, not before it. Dedup and prescreen are what
    # make the queue worth draining — enqueueing prescreened-out or near-duplicate candidates
    # would move the expensive decisions to the consumer, which is exactly what already happened
    # once (a k=50 batch minting rows a moat verdict each would then reject).
    if not vet:
        queued = enqueue_candidates(kept, store=store, cfg=cfg, op=op)
        progress.step(f"queued {len(queued)} candidate(s) for vetting")
        logger.info("Producer queued %d of %d selected candidate(s) as DEFER",
                    len(queued), len(kept),
                    extra={"queued": len(queued), "selected": len(kept)})
        return queued

    workers = _vet_workers(cfg)
    progress.step(f"vetting {len(kept)} candidate(s) diverse subset live (max {workers} in parallel)…")

    # --- Vet each candidate (Bounded Concurrency Task E) ---
    from concurrent.futures import CancelledError, ThreadPoolExecutor, as_completed
    dossiers: list[Dossier] = []

    def _label(idx: int, total: int, title: str) -> str:
        short = (title[:34] + "…") if len(title) > 35 else title
        return f"[{idx}/{total} {short}]"

    with ThreadPoolExecutor(max_workers=workers) as executor:
        fut_meta: dict = {}  # future -> stable candidate index (1-based, survives reorder)
        for idx, cand in enumerate(kept, start=1):
            # Check spend guard (rough check before submitting)
            if guard.tripped():
                logger.error(f"ABORTING: Spend guard tripped (${guard.total():.2f})")
                break
            
            # Stochastic Full-Vetting (Part 16 principal upgrade): 1-in-10 candidates 
            # bypass kill-fast to gather a complete failure surface for the 
            # Adaptive Controller.
            should_full_vet = (idx % 10 == 0)
            
            # Each candidate carries a stable [idx/N title] tag so its live per-check
            # lines stay attributable even though parallel vets interleave on stderr.
            # Per-tier vetting (Part 14): resolve config to THIS candidate's ambition tier so
            # the gates/thresholds/weights/adversarial framing match the idea's own bar. For an
            # untagged candidate (today's default) for_lane("") returns cfg unchanged.
            vet_cfg = cfg.for_lane(cand.ambition_tier)
            fut = executor.submit(
                vet_candidate, cand, op, search, vet_cfg,
                store=store, query_op=fast_op, publish=publish,
                label=_label(idx, len(kept), cand.title),
                full_vet=should_full_vet,
                experimental_op=experimental_op,
                board_personas=board_personas,
                artifact_time_budget_s=artifact_time_budget_s,
                vet_deadline_mono=_vet_deadline)
            fut_meta[fut] = idx
            # Rough cost estimate increment
            guard.add(0.01)

        total_submitted = len(fut_meta)
        # Stream each verdict the MOMENT its vet finishes (completion order), not in
        # submission order — a fast KILL no longer waits behind a slow candidate.
        infra_abort = _infra_abort_streak(cfg)
        infra_streak = 0
        infra_aborted = False
        infra_halt: Optional[BaseException] = None
        n_cancelled = 0
        budget_stopped = False
        for future in as_completed(fut_meta):
            idx = fut_meta[future]
            # THE TICK'S OWN STOP. Checked before banking this result rather than after, so a
            # breach is acted on at the first completion past the deadline instead of one
            # candidate later. Fires at most once: `_vet_budget_cancel` is idempotent in
            # effect (already-cancelled futures return False) but the announcement is not.
            if not budget_stopped:
                already_cancelled = {f for f in fut_meta if f.cancelled()}
                n_over = _vet_budget_cancel(_vet_deadline, fut_meta)
                if n_over is not None:
                    budget_stopped = True
                    n_cancelled += n_over
                    # THE CANDIDATES ARE NOT DROPPED. An earlier draft of this rail told the
                    # log they "were never started", which is comfortable and wrong in the way
                    # that matters: each one was already generated, prescreened and diversity-
                    # selected — paid for — so discarding it would make k=50 spend a k=50
                    # generation bill for a k≈18 yield, silently. Each gets a DEFER row, the
                    # decision the house already uses for "unevaluated, come back to it", which
                    # puts it in `drainable()` and the existing `vet --resume` drain with no
                    # new machinery. Written INSIDE the stop so a crash later in this loop
                    # cannot lose them.
                    n_parked = _defer_unstarted_candidates(
                        fut_meta, kept, already_cancelled,
                        store=store, cfg=cfg, op=op, dossiers=dossiers)
                    msg = (f"VET BUDGET SPENT after {vet_time_budget_s:.0f}s: banking the "
                           f"{len(dossiers) - n_parked} verdict(s) already paid for and "
                           f"cancelling {n_over} un-started vet(s) of {total_submitted}; "
                           f"{n_parked} parked as DEFER for the drain. This is the tick "
                           f"stopping on its own terms with nothing thrown away.")
                    # CRITICAL because launchd.err.log drops info/warning (measured
                    # 2026-08-05), and a rail nobody can see fire is a rail nobody trusts.
                    logger.critical(msg, extra={"vet_budget_s": vet_time_budget_s,
                                                "cancelled": n_over,
                                                "parked_defer": n_parked,
                                                "submitted": total_submitted,
                                                "banked": len(dossiers) - n_parked})
                    print(f"⏱ {msg}", file=sys.stderr, flush=True)
                    progress.note(f"⏱ {msg}")
            try:
                d = future.result()
                gate_str = f" [gate={d.gate_fired}]" if d.gate_fired else ""
                logger.info(f"Result: {d.candidate.title!r} → {d.decision.value.upper()}{gate_str}",
                            extra={"candidate_id": d.candidate.candidate_id, "decision": d.decision.value, "score": d.score.composite if d.score else None})
                progress.result(idx, total_submitted, d.decision.value, d.candidate.title,
                                gate=d.gate_fired,
                                composite=(d.score.composite if d.score else None))
                dossiers.append(d)

                # Kill-fast on INFRASTRUCTURE (see _infra_abort_streak). Counted AFTER the
                # dossier is kept: work already paid for is banked, never discarded. Only
                # UN-STARTED vets are cancelled, so this can lose no evidence — it can only
                # decline to buy more of it while the pipeline is unable to rule.
                infra_streak, cancelled = _infra_abort_check(
                    d, infra_streak, 0 if infra_aborted else infra_abort, fut_meta)
                if cancelled is not None:
                    infra_aborted = True
                    n_cancelled = cancelled
                    msg = (f"INFRA ABORT: {infra_streak} consecutive candidates deferred on "
                           f"gate={d.gate_fired!r} — the pipeline cannot rule, so this is an "
                           f"outage, not a verdict. Cancelled {n_cancelled} un-started vet(s) "
                           f"of {total_submitted}; {len(dossiers)} kept.")
                    # CRITICAL: the daemon's launchd log drops info/warning, so a quieter
                    # level here would make the abort invisible exactly where it matters.
                    logger.critical(msg, extra={"infra_gate": d.gate_fired,
                                                "cancelled": n_cancelled,
                                                "submitted": total_submitted})
                    print(f"⏸ {msg}", file=sys.stderr, flush=True)
                    progress.note(f"⏸ {msg}")
            except CancelledError:
                # A vet this loop cancelled above — expected, not an error. It must be caught
                # HERE: since 3.8 CancelledError derives from BaseException, so the generic
                # `except Exception` below cannot see it and it would escape and kill the batch.
                continue
            except GroundingInfrastructureError as e:
                # Every grounding provider was dead for THIS candidate's searches. Route it
                # through the same consecutive-streak rail that governs infra-gated defers
                # (see _infra_exception_action) instead of halting on first sight: a
                # sustained outage still stops the daemon, a single tail-query failure
                # no longer does.
                infra_streak += 1
                action = _infra_exception_action(infra_streak, infra_abort)
                logger.warning(
                    f"GROUNDING OUTAGE vetting candidate {idx}/{total_submitted} "
                    f"(consecutive {infra_streak}/{infra_abort or 'rail-disabled'} → "
                    f"{action}): {e}",
                    extra={"infra_streak": infra_streak, "infra_threshold": infra_abort,
                           "infra_action": action, "error": str(e)[:300]})
                progress.note(f"[{idx}/{total_submitted}] ⚠ grounding outage "
                              f"(streak {infra_streak}, {action})")
                if action == "raise":
                    raise
                if action == "halt" and infra_halt is None:
                    infra_halt = e
                    # Future.cancel() refuses an already-running vet, so this declines to buy
                    # more work; it cannot discard a verdict we have paid for.
                    n_cancelled += sum(1 for f in fut_meta if f.cancel())
                    msg = (f"GROUNDING LAYER COLLAPSE: {infra_streak} consecutive "
                           f"infrastructure failures — the pipeline cannot rule, so this is "
                           f"an outage, not a verdict. Cancelled {n_cancelled} un-started "
                           f"vet(s) of {total_submitted}; halting once in-flight vets bank.")
                    # CRITICAL: the daemon's launchd log drops info/warning.
                    logger.critical(msg, extra={"cancelled": n_cancelled,
                                                "submitted": total_submitted})
                    print(f"⏹ {msg}", file=sys.stderr, flush=True)
                    progress.note(f"⏹ {msg}")
                continue
            except Exception as e:
                logger.error(f"ERROR vetting candidate: {e}", extra={"error": str(e)})
                progress.note(f"[{idx}/{total_submitted}] ⚠ error: {e}")

        # Halt only AFTER the completion loop has drained. Every vet that was already
        # running got to finish and persist itself (store.save lives inside vet_candidate),
        # so the daemon halt costs us no evidence we have already paid for.
        if infra_halt is not None:
            raise infra_halt

    # --- Summary ---
    n_pass = sum(1 for d in dossiers if d.decision == Decision.PASS)
    n_defer = sum(1 for d in dossiers if d.decision == Decision.DEFER)
    n_kill = len(dossiers) - n_pass - n_defer
    ruled = n_pass + n_kill
    survival = n_pass / ruled if ruled else 0.0  # deferrals excluded — not real kills
    usage = get_usage_summary()
    logger.info("Signal pipeline complete", extra={
        "total_vetted": len(dossiers),
        "pass_count": n_pass,
        "kill_count": n_kill,
        "defer_count": n_defer,
        "survival_rate": survival,
        "usage": usage,
    })
    progress.summary(n_pass, n_kill, usage, n_defer=n_defer)

    # Production self-watch (free, no model calls): flag calibration pathologies
    # — zero-yield, single-gate dominance, dead gates — the moment they appear, so a
    # mis-calibrated filter (e.g. a gate killing on silence) is surfaced, not silent.
    from .diagnostics import calibration_alarms
    for a in calibration_alarms(store, cfg):
        progress.note(("🚨 " if a["level"] == "alarm" else "⚠️  ") + f"[{a['code']}] {a['message']}")

    # Per-batch funnel diagnostics — emitted on EVERY generation run (founder
    # requirement 2026-06-22: every generation ships WITH diagnostics). Purely
    # additive instrumentation: derived from this batch's own dossiers + the
    # top-of-funnel counts already in scope. Wrapped so a diagnostics failure can
    # never break a run. Written to store/scheduler/{DIAGNOSTICS_LATEST.txt,
    # batch_diagnostics.jsonl}.
    try:
        from .diagnostics import diagnose_batch, persist_batch_diagnostics
        stage_counts = {
            "generated": len(candidates),
            "dedup_dropped": len(dropped),
            "rejection_fastpath": len(unique) - len(final_candidates),
            "prescreen_in": len(final_candidates),
            "prescreened_out": len(final_candidates) - len(prescreened_data),
            "novelty_selected": len(kept),
            "vetted": len(dossiers),
        }
        _bd = diagnose_batch(dossiers, stage_counts=stage_counts, usage=usage, cfg=cfg)
        persist_batch_diagnostics(_bd, store)
        progress.note("📊 batch diagnostics → store/scheduler/DIAGNOSTICS_LATEST.txt")
        logger.info("batch diagnostics written", extra={"funnel": stage_counts,
                    "unverifiable_pct": _bd.get("unverifiable_pct"),
                    "decisions": _bd.get("decisions")})
    except Exception as _diag_exc:  # never let diagnostics break a run
        logger.warning(f"batch diagnostics failed (non-fatal): {_diag_exc}")

    return dossiers



# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _default_market(cfg: Config) -> str:
    """The market unmarked candidates and legacy catalogue rows belong to."""
    try:
        return cfg.active_market or cfg.default_market
    except AttributeError:  # Config predating Epic D
        return ""


def _guard_market_open(cfg: Config, args: argparse.Namespace) -> None:
    """Refuse to run against a market that has not passed its readiness probe.

    A market is CLOSED until a calibration probe demonstrates the engine can actually
    see it (specs/multi-market-dimension.md §4). Generating into an unproven market
    would mint dossiers whose grounding nobody has measured — the exact thing the gate
    exists to prevent. `--probe` is the one sanctioned way past this, and it is what
    `markets probe` uses to run the calibration itself.
    """
    if getattr(args, "probe", False):
        return
    status = cfg.market_status(cfg.active_market)
    if status != "open":
        code = cfg.active_market
        ref = cfg.market_config(code).get("readiness_ref") or f"store/markets/{code}/READINESS.json"
        print(f"error: market {code!r} is {status}, not open.\n"
              f"  Run the readiness probe first:\n"
              f"    python -m prospector.run markets probe --market {code} "
              f"--set markets/calibration/{code.split('-')[0]}.jsonl\n"
              f"  Then, if it passes: markets open {code}  (reads {ref})",
              file=sys.stderr)
        sys.exit(2)


def _build_config_and_overrides(args: argparse.Namespace) -> Config:
    """Load config and apply CLI overrides (operator, retrieval provider)."""
    cfg = load_config(args.config if args.config else None)

    if hasattr(args, "operator") and args.operator:
        cfg.operator = args.operator

    # If fixtures provided, switch retrieval provider to fixture mode
    if hasattr(args, "fixtures") and args.fixtures:
        cfg.retrieval.provider = "fixture"

    # Market override (Epic D): which JURISDICTION this run generates/vets for. Applied
    # BEFORE the lane because it is the outer context (the evidence terrain), and because
    # for_lane/for_profile/for_persona preserve active_market through dataclasses.replace.
    if getattr(args, "market", None):
        cfg = cfg.for_market(args.market)
    # Guard the EFFECTIVE market, not just an explicit --market. A closed market can
    # also arrive via `active_market:`/`markets.default:` in config.yaml, and that
    # route must not be the one way to mint dossiers into an unproven jurisdiction.
    # hasattr, not truthiness: only the market-aware commands own this dimension.
    if hasattr(args, "market"):
        _guard_market_open(cfg, args)

    # Ambition-lane override (config-pinned): judge against THIS lane's gates/thresholds
    # instead of the default. Applied last (returns a resolved copy). Empty => unchanged.
    if getattr(args, "lane", None):
        cfg = cfg.for_lane(args.lane)

    # Generation-profile override (Part 16): a targeted steering bundle (restricted forms +
    # focus directive). Applied after the lane so it composes over it (profile wins). Empty
    # => unchanged. for_lane re-applies it internally for per-tier multilane generation.
    if getattr(args, "profile", None):
        cfg = cfg.for_profile(args.profile)

    # Persona override (Part 16 principal upgrade): analytical multi-tenancy.
    # Applied after the profile so its biases (generation/verdict/adversarial) win.
    if getattr(args, "persona", None):
        cfg = cfg.for_persona(args.persona)

    # Founder-archetype override (generation-only). Applied last so it wins over lane
    # defaults; for_lane re-applies active_archetype for multi-lane fan-out.
    if getattr(args, "archetype", None):
        from .config import UnknownArchetypeError
        try:
            cfg = cfg.for_archetype(args.archetype)
        except UnknownArchetypeError as e:
            print(f"error: {e}", file=sys.stderr)
            sys.exit(2)

    return cfg


def _make_search(cfg: Config, args: argparse.Namespace) -> SearchProvider:
    """Build the SearchProvider, injecting fixtures when --fixtures is passed."""
    from .retrieval import make_provider

    fixtures = None
    if hasattr(args, "fixtures") and args.fixtures:
        with open(args.fixtures, encoding="utf-8") as fh:
            fixtures = json.load(fh)

    return make_provider(cfg, fixtures=fixtures)


def _add_market_args(p: argparse.ArgumentParser) -> None:
    """Attach the market flags shared by vet/signal/generate/discover."""
    p.add_argument("--market", metavar="CODE",
                   help="Jurisdiction to generate/vet for (e.g. uk, us, us-tx). "
                        "Default: config active_market, else markets.default. "
                        "A market that has not passed its readiness probe is refused.")
    p.add_argument("--probe", action="store_true",
                   help="Calibration run: permit a non-open market. Used by "
                        "`markets probe`; results never publish.")


def _add_archetype_arg(p: argparse.ArgumentParser) -> None:
    """Attach --archetype (generation-only founder-capacity pin)."""
    p.add_argument("--archetype", metavar="NAME",
                   help="Founder archetype for generation (solo_agent, small_team, "
                        "startup). Overrides the lane default. Generation-only — "
                        "never moves gates or thresholds.")


def _resolve_board(args: argparse.Namespace) -> Optional[list[str]]:
    if getattr(args, "board", False):
        return ["shark", "minimalist", "academic"]
    return None


def _cmd_vet(args: argparse.Namespace, log_path: Path) -> None:
    """Vet a single candidate or re-vet all moat-deferred candidates."""
    cfg = _build_config_and_overrides(args)

    from .operator import make_operator
    from .telemetry import reset_usage
    reset_usage()
    op = make_operator(cfg)
    fast_op = make_operator(cfg, fast=True)
    search = _make_search(cfg, args)
    store = Store(cfg)

    if getattr(args, "resume", False):
        _cmd_resume(args, cfg, op, fast_op, search, store, log_path)
        return

    cand = Candidate(
        title=args.title,
        one_liner=getattr(args, "one_liner", "") or "",
        why_now=getattr(args, "why_now", "") or "",
    )

    from . import progress
    progress.banner(f"Vetting: {cand.title!r}")
    progress.step("running kill-checks (kill-fast)…")

    d = vet_candidate(cand, op, search, cfg, store=store,
                      query_op=fast_op, publish=getattr(args, "publish", False),
                      show_checks=True,
                      board_personas=_resolve_board(args))
    progress.summary(
        n_pass=1 if d.decision == Decision.PASS else 0,
        n_kill=1 if d.decision == Decision.KILL else 0,
        n_defer=1 if d.decision == Decision.DEFER else 0)
    # The operator's own terminal is the ONE surface that keeps our grade: this is the
    # command you run to decide whether the engine ruled sensibly, and the composite plus
    # the six axis marks are the whole point of looking. The buyer's copy of the same
    # document (`bridge.py` -> QA_Report.md) takes the default and gets neither.
    print(render_markdown(d, include_our_grade=True))
    from .report import costs_report
    print(f"\n{costs_report(log_path or '')}")


def _cmd_replicate(args: argparse.Namespace, log_path: Path) -> None:
    """Re-vet proven PASSes from one market as candidates in another.

    The cheapest high-quality generation channel available: an idea that already cleared
    the bar somewhere is a better-than-random hypothesis elsewhere. What does NOT carry
    over is the evidence — every verdict, source and score is re-earned from scratch
    against the target market's own chain. A replicated PASS is a new PASS, or it is a
    KILL with its own cited reason.
    """
    from . import progress
    from .operator import make_operator
    from .telemetry import reset_usage

    source_market = args.source_market.lower()
    cfg = _build_config_and_overrides(args)  # --market is the TARGET (gate-checked)
    target_market = cfg.active_market or _default_market(cfg)
    if source_market == target_market:
        print(f"error: --from and --market are both {target_market!r}; nothing to replicate.",
              file=sys.stderr)
        sys.exit(2)

    store = Store(cfg)
    # The index carries `market`, so filter there rather than opening 1,000+ JSON files.
    rows = [r for r in store.all(decision=Decision.PASS.value)
            if (r.get("market") or "").lower() == source_market]
    min_composite = getattr(args, "min_composite", None)
    if min_composite is not None:
        rows = [r for r in rows
                if float(r.get("composite") or 0.0) >= min_composite]
    rows = sorted(rows, key=lambda r: float(r.get("composite") or 0.0), reverse=True)
    rows = rows[: (args.n or len(rows))]

    if not rows:
        print(f"No PASS dossiers in market {source_market!r} to replicate.")
        return

    print(f"Replicating {len(rows)} PASS candidate(s): {source_market} → {target_market}")
    clones: list[Candidate] = []
    for row in rows:
        full = store.get(row.get("candidate_id", "")) or {}
        if not full:
            continue
        src = Candidate.from_dict(full.get("candidate", {}))
        clone = Candidate(
            title=src.title, one_liner=src.one_liner, hypothesis=src.hypothesis,
            who_pays=src.who_pays, why_now=src.why_now,
            tags={**dict(src.tags or {}), "replicated_from": src.candidate_id,
                  "replicated_from_market": source_market},
            automatability=src.automatability,
            structural_form=src.structural_form, ambition_tier=src.ambition_tier,
            market=target_market)  # candidate_id left blank => re-derived WITH the market
        if clone.candidate_id == src.candidate_id:
            # Cannot happen once market participates in the hash, but if it ever did the
            # save would overwrite the source dossier — refuse rather than destroy it.
            print(f"error: clone of {src.candidate_id} collides with its source; aborting.",
                  file=sys.stderr)
            sys.exit(3)
        clones.append(clone)

    if getattr(args, "dry_run", False):
        for c in clones:
            print(f"  {c.candidate_id}  {c.title[:60]}")
        print("\nDRY RUN — nothing vetted. Drop --dry-run to run the full vet.")
        return

    reset_usage()
    op = make_operator(cfg)
    fast_op = make_operator(cfg, fast=True)
    search = _make_search(cfg, args)

    n_pass = n_kill = n_defer = 0
    for clone in clones:
        progress.banner(f"Replicating into {target_market}: {clone.title!r}")
        d = vet_candidate(clone, op, search, cfg, store=store, query_op=fast_op,
                          publish=getattr(args, "publish", False), show_checks=False)
        n_pass += d.decision == Decision.PASS
        n_kill += d.decision == Decision.KILL
        n_defer += d.decision == Decision.DEFER
        print(f"  {d.decision.value.upper():5s}  {clone.title[:56]}"
              f"{'  gate=' + d.gate_fired if d.gate_fired else ''}")

    progress.summary(n_pass=n_pass, n_kill=n_kill, n_defer=n_defer)
    from .report import costs_report
    print(f"\n{costs_report(log_path or '')}")


#: Populations `vet --resume --only` can restrict the drain to. "all" is the default and the
#: historical behaviour; the daemon never passes this flag, so its per-tick drain is unchanged.
RESUME_SELECTORS = ("all", "defer", "provisional", "provisional-pass", "provisional-kill")


def _resume_selects(row: dict, only: str) -> bool:
    """Does this backlog row belong to the `--only` population?

    WHY THIS EXISTS. The drain sorts DEFER and provisional rows together, oldest first
    (see the comment at the `sorted(...)` call below), which is right for fairness and wrong
    for targeting. Measured on the live index 2026-08-06: of the OLDEST 100 drainable rows,
    51 were provisional KILLs, 47 were DEFERs, 1 was a provisional DEFER — and exactly
    **1** was a provisional PASS. The 72 provisional PASSes (the only population that can
    become sellable inventory, because a re-vet that confirms them clears
    `run.py:422`'s `not dossier.provisional` publish gate) are spread from 2026-06-21 to
    2026-08-06, so oldest-first buries them. Draining them via `--limit` alone would need
    the whole ~351-row backlog, which at the live batch's ~5.5 min/candidate is ~32 hours.

    A row's `decision` and `provisional` both come from `SELECT *` (`store.provisional()`
    and `store.all()`), so both keys are present on every row.
    """
    decision = str(row.get("decision", "") or "").lower()
    provisional = bool(row.get("provisional", 0))
    if only == "defer":
        return decision == "defer"
    if only == "provisional":
        return provisional
    if only == "provisional-pass":
        return provisional and decision == "pass"
    if only == "provisional-kill":
        return provisional and decision == "kill"
    return True


#: Drain priority. The bound is spent from rank 0 down, so this is the ONLY thing that decides
#: what a tick's money buys.
_RANK_PROVISIONAL_PASS = 0
_RANK_DEFER = 1
_RANK_PROVISIONAL_KILL = 2
_RANK_NAMES = {_RANK_PROVISIONAL_PASS: "provisional-pass",
               _RANK_DEFER: "defer",
               _RANK_PROVISIONAL_KILL: "provisional-kill"}


def _drain_rank(row: dict) -> int:
    """Which population this backlog row belongs to, ordered by what a re-vet can produce.

    WHY RANK AND NOT JUST AGE. Oldest-first is fair and, on this backlog, expensive: the three
    populations have completely different expected values and the sort could not see it.

      0  provisional PASS — a real PASS that the publish gate refuses solely because an untrusted
         brain ruled it (`decision == PASS and not provisional`). One confirming re-vet turns it
         into sellable inventory. This is the population the drain was BUILT for.
      1  DEFER — no verdict was ever reached, so the idea is unjudged. A re-vet produces the
         first real answer, whatever it is.
      2  provisional KILL — already dead. A re-vet can only confirm the kill (changing nothing
         that can ever be sold) or, rarely, resurrect a wrongly-killed idea.

    Measured on the live index 2026-08-06, oldest-first put rank 2 FIRST: of the oldest 100
    drainable rows, 51 were provisional KILLs and exactly 1 was a provisional PASS, while the 72
    provisional PASSes were spread from 2026-06-21 to 2026-08-06. At the daemon's 3-per-tick
    bound, age order spends the budget almost entirely on rank 2. Rank order spends it on rank 0
    until there are none left, which is the whole point of running a drain at all.

    Age still breaks ties WITHIN a rank (`_cmd_resume`'s sort key), so nothing starves.
    """
    decision = str(row.get("decision", "") or "").lower()
    provisional = bool(row.get("provisional", 0))
    if provisional and decision == "pass":
        return _RANK_PROVISIONAL_PASS
    if decision == "defer":
        return _RANK_DEFER
    return _RANK_PROVISIONAL_KILL


class DrainSurvey(NamedTuple):
    """The backlog split into what a drain pass can move and what it provably cannot.

    `workable` is THE definition of "backlog" for every caller — the drain's bound is spent on
    it, and the scheduler's brake counts it. `orphaned`, `stalled` and `unpublishable` are the
    excluded rows, carried out by candidate_id so every caller can report them instead of
    absorbing them.
    """

    workable: list[dict]
    orphaned: list[str]
    stalled: list[str]
    unpublishable: list[str]


def drain_survey(store: Store, *, max_attempts: int = 0,
                 revet_provisional_kills: bool = True) -> DrainSurvey:
    """Split the DEFER + provisional population into workable rows and unmovable ones.

    Two populations need the moat to revisit them:
      1. DEFER — the moat was unavailable, so no verdict was reached at all.
      2. provisional — a real verdict WAS reached, but by the cheap emergency fallback tail
         (moat exhausted). Re-vet so the trusted moat overwrites the cheap ruling.
    De-duped by candidate_id (a dossier can't be both, but guard against overlap).

    Tombstoned rows are excluded from BOTH populations. A tombstone means the dossier is gone
    for good, so there is nothing to re-vet — and leaving them in inflated the backlog the
    operator reads (406 reported, 45 of them undrainable) and made the drain's ETA a fiction.
    They stay in the catalogue for history; they are just not work.

    THEN THREE EXCLUSIONS, all closing the same hole: a counted row the drain cannot move.

      * ORPHANED — an index row whose dossier JSON is not on disk. `store.get()` returns None
        and the drain can only print "dossier JSON missing, skipping". Measured 2026-08-06 on the
        live store: 46 of 406, with a leading unbroken run of 45 dated 2026-06-14..06-21, i.e.
        15 consecutive 3-row ticks (~1.2 days) of no-op drains reporting `attempted: 3`.
      * STALLED — a row that has absorbed `max_attempts` completed re-vets and is still
        drainable (`prospector/drain_state.py`). 0 disables this exclusion entirely.
      * UNPUBLISHABLE — a provisional row whose decision is already KILL, when
        `schedule.revet_provisional_kills` is False. The first two populations cannot be MOVED;
        this one moves fine and cannot PRODUCE, because a KILL never reaches the publish gate no
        matter which brain ruled it. Measured 2026-08-06: 161 of 318 drainable rows, ~$1.91 each,
        0 passes in the 15 drained that day — see `drain_state.revet_provisional_kills` for the
        full receipts. Excluding them is reversible config, not a tombstone: the rows keep their
        cited kill reason and `vet --resume --only provisional-kill` still reaches them.

    Why they belong HERE and not in `_cmd_resume`'s loop: the scheduler's backlog brake
    (`run_scheduled._backlog_size`) counts this same population to decide whether generation may
    run, and it releases itself when the count falls back under `schedule.backlog_cap`. Excluding
    unmovable rows only in the drain would leave the brake counting rows nothing can ever
    subtract — a generation freeze waiting on a number that cannot fall, with no human able to
    see why. One definition, or the rail deadlocks.

    A row that falls into more than one excluded class is reported once, in the order tested
    below; the lists are disjoint by construction, and either way the row is excluded.
    """
    deferred = [r for r in store.all(decision="defer") if not r.get("tombstone")]
    provisional = [r for r in store.provisional() if not r.get("tombstone")]
    seen_ids = {r.get("candidate_id", "") for r in deferred}
    rows = list(deferred) + [r for r in provisional
                             if r.get("candidate_id", "") not in seen_ids]

    attempts = drain_state.load(store.root) if max_attempts > 0 else {}
    workable: list[dict] = []
    orphaned: list[str] = []
    stalled: list[str] = []
    unpublishable: list[str] = []
    for row in rows:
        cid = str(row.get("candidate_id", "") or "")
        if max_attempts and attempts.get(cid, 0) >= max_attempts:
            stalled.append(cid)
        elif not store.has_dossier(cid):
            orphaned.append(cid)
        elif not revet_provisional_kills and _drain_rank(row) == _RANK_PROVISIONAL_KILL:
            # Tested AFTER the mechanical exclusions so a row that is both orphaned and
            # unpublishable is reported as orphaned — the older, load-bearing diagnosis.
            unpublishable.append(cid)
        else:
            workable.append(row)
    return DrainSurvey(workable, orphaned, stalled, unpublishable)


def drainable(store: Store, *, max_attempts: int = 0,
              revet_provisional_kills: bool = True) -> list[dict]:
    """The rows a re-vet pass can actually work on — `drain_survey(...).workable`.

    Kept as a name because callers and tests bind to it; see `drain_survey` for the definition
    and for why the exclusions live there rather than in the drain loop.
    """
    return drain_survey(store, max_attempts=max_attempts,
                        revet_provisional_kills=revet_provisional_kills).workable


def _with_exclusions(summary: dict, survey: DrainSurvey) -> dict:
    """Ride the excluded counts into the drain summary on EVERY return path.

    `orphaned` used to be attached on one path only — the one that actually ran a pass — so the
    tick that excluded every row returned a clean-looking `attempted: 0` and named no reason for
    it. The summary is what reaches `ticks.jsonl` and the state probe, so a count that is not in
    here is a count no operator will ever see.
    """
    if survey.orphaned:
        summary["orphaned"] = len(survey.orphaned)
    if survey.stalled:
        summary["stalled"] = len(survey.stalled)
    if survey.unpublishable:
        summary["unpublishable"] = len(survey.unpublishable)
    return summary


def _recover_orphans(args: argparse.Namespace, cfg: Config, op: Operator,
                     fast_op: Operator, search: SearchProvider, store: Store,
                     deadline_mono: Optional[float] = None,
                     artifact_time_budget_s: Optional[float] = None) -> dict:
    """Re-vet candidates whose vetting process died. This is how the engine heals itself.

    THE FAILURE THIS UNDOES. `vet_candidate` persists on its single return path, so a process
    killed mid-vet wrote no dossier and no index row: the candidate stopped existing. Measured
    2026-08-17 on the live store over four audit day-files — 12 candidates had a `candidate_start`
    and no `candidate_done` from a dead process, and 10 of the 12 had NO index row and NO dossier.
    `run.drainable()` works from index rows, so the ordinary drain could never see them. They were
    not backlogged; they were gone.

    THE LOOP. `inflight.open_` writes the candidate to disk before the vet begins and
    `inflight.close` removes it once a verdict exists, so a leftover record means exactly one
    thing: the process that owned it died. Every `vet --resume` — the CLI one and the daemon's
    own per-tick drain (`scheduler/run_scheduled.py`) — starts here, so recovery happens on the
    engine's normal cadence with no operator action and no new schedule.

    TWO OUTCOMES, BOTH SELF-CORRECTING. A record whose candidate is already in the store means
    the process died in the gap between `store.save` and `inflight.close`: the verdict exists, so
    the record is dropped and nothing is paid twice. Everything else is re-vetted, which writes
    the dossier and the index row the dead process never got to write.

    Bounded by the same `--limit` as the drain, and refused entirely when the moat is blind, for
    the same reason the drain is: a re-vet with no brain to rule only spends money to write DEFER.
    """
    from . import inflight, progress
    from .health import moat_blind_reason

    try:
        pending = inflight.orphans(store.root)
    except Exception as exc:  # noqa: BLE001 — recovery must never be what breaks a drain
        logger.warning("could not survey in-flight work", extra={"error": f"{exc}"})
        return {"orphans": None, "orphans_null_reason": f"in-flight survey failed: {exc}"}
    if not pending:
        return {}

    # SETTLED FIRST, AND IT IS FREE. Membership is one index read; re-vetting a candidate that
    # already has a verdict on disk would be the expensive way to learn nothing.
    known = {str(r.get("candidate_id") or "") for r in store.all()}
    settled, todo = 0, []
    for rec in pending:
        cid = str(rec.get("candidate_id") or "")
        if not cid:
            continue
        if cid in known or store.has_dossier(cid):
            inflight.close(store.root, cid)
            settled += 1
        else:
            todo.append(rec)

    out: dict = {"orphans": len(pending), "settled": settled, "recovered": 0,
                 "unrecoverable": 0}
    if not todo:
        if settled:
            print(f"Cleared {settled} in-flight record(s) whose verdict was already on disk.")
        return out

    blind = moat_blind_reason(cfg)
    if blind:
        print(f"{len(todo)} candidate(s) were abandoned by a dead process, but {blind}. "
              f"Leaving them for the next pass — they are on disk and cannot be lost again.")
        out["skipped"] = blind
        return out

    limit = getattr(args, "limit", None)
    if limit is not None and limit <= 0:
        out["skipped"] = f"limit={limit} disables this pass"
        return out
    if limit is not None:
        todo = todo[:limit]

    owner = _mint_lease_owner()
    print(f"Recovering {len(todo)} candidate(s) abandoned by a process that died mid-vet"
          + (f" ({settled} more already had a verdict on disk)." if settled else "."))
    for i, rec in enumerate(todo, 1):
        cid = str(rec.get("candidate_id") or "")
        cand = inflight.candidate_of(rec)
        if cand is None:
            # The record cannot rebuild its candidate, so nothing can vet it. Count it and leave
            # the file alone: deleting it would destroy the only remaining trace of the idea.
            out["unrecoverable"] += 1
            continue
        if not inflight.claim(store.root, cid, owner):
            continue  # another drain is already recovering it
        try:
            progress.banner(f"[recover {i}/{len(todo)}] {cand.title!r} "
                            f"({rec.get('why', 'its process is gone')})")
            _for_lane = getattr(cfg, "for_lane", None)
            vet_cfg = _for_lane(cand.ambition_tier) if callable(_for_lane) else cfg
            vet_candidate(cand, op, search, vet_cfg, store=store, query_op=fast_op,
                          publish=getattr(args, "publish", False), show_checks=True,
                          board_personas=_resolve_board(args),
                          artifact_time_budget_s=artifact_time_budget_s,
                          vet_deadline_mono=deadline_mono)
            out["recovered"] += 1
        except ProviderExhaustedError:
            # The moat went down DURING recovery. The record is still on disk, so the next pass
            # picks this candidate up again. Stop rather than burn the rest on a dead brain —
            # the same rule the drain follows.
            out["skipped"] = "the moat went blind during recovery"
            break
        except Exception as exc:  # noqa: BLE001
            logger.warning("could not recover abandoned candidate",
                           extra={"candidate_id": cid, "error": f"{exc}"})
            out["unrecoverable"] += 1
        finally:
            inflight.release_claim(store.root, cid)
    return out


def _cmd_resume(args: argparse.Namespace, cfg: Config, op: Operator,
                fast_op: Operator, search: SearchProvider, store: Store,
                log_path: Optional[Path] = None,
                deadline_mono: Optional[float] = None,
                artifact_time_budget_s: Optional[float] = None) -> dict:
    """Re-vet all moat-deferred candidates.

    Called when `vet --resume` is used or when the moat comes back online after an outage.
    Loads each deferred candidate, re-runs the full verification pipeline (not partial —
    the moat is now available, so we run everything), and overwrites the DEFER decision
    with the fresh verdict.  Candidates that were deferred due to a real retrieval
    outage (not moat exhaustion) are also retried.

    `args.limit` bounds one pass. The unattended daemon sets it (see
    `scheduler/run_scheduled.py::_default_generate`) because the spend guard is evaluated
    once per tick, BEFORE the tick runs — an unbounded drain of a large backlog would run
    entirely inside a single guard decision and could clear the daily cap in one tick.
    On the CLI it defaults to unbounded, which is the behaviour this command has always had.

    Returns a summary dict so a caller (the daemon) can record what the pass did; the CLI
    ignores the return and reads the printed report.
    """
    # PARSE `--only` BEFORE the survey, because it decides what the survey may exclude.
    # `getattr` default keeps `resume_deferred`'s Namespace (the daemon's entry point, which has
    # no `only` attribute) on the historical "all" behaviour.
    only = str(getattr(args, "only", "all") or "all")
    if only not in RESUME_SELECTORS:
        print(f"Unknown --only {only!r}; expected one of {', '.join(RESUME_SELECTORS)}.",
              file=sys.stderr)
        sys.exit(2)

    # SELF-HEAL BEFORE DRAINING. Work abandoned by a dead process is invisible to `drain_survey`
    # — it has no index row to survey — so it can only be found through the in-flight ledger, and
    # it has to be found FIRST: it is the population that is losing money right now, and it is
    # bounded and small (12 in four days, measured 2026-08-17) where the ordinary backlog is not.
    recovered = _recover_orphans(args, cfg, op, fast_op, search, store,
                                 deadline_mono=deadline_mono,
                                 artifact_time_budget_s=artifact_time_budget_s)

    max_att = drain_state.max_attempts(cfg)
    # An operator who NAMES the dead population gets it, whatever the config default says. The
    # exclusion exists to stop provisional KILLs silently eating the daemon's automatic bound;
    # it is not a lock on the rows, and `--only provisional-kill` is the documented way back in.
    revet_dead = (drain_state.revet_provisional_kills(cfg)
                  or only in ("provisional", "provisional-kill"))
    survey = drain_survey(store, max_attempts=max_att, revet_provisional_kills=revet_dead)

    def _done(summary: dict) -> dict:
        """Every return from here carries the recovery result AND the exclusions.

        Same rule as `_with_exclusions`, one cause over: this summary is what reaches
        `ticks.jsonl` and the ops console, so a recovery that is not in here is a recovery no
        operator will ever see — and the whole point of the ledger is that the loss becomes
        visible.
        """
        if recovered:
            summary["recovery"] = recovered
        return _with_exclusions(summary, survey)

    pending = survey.workable
    backlog = len(pending)
    excluded = ""
    if survey.orphaned or survey.stalled or survey.unpublishable:
        # NAMED, not absorbed. These rows are the reason a backlog count can stop falling, so the
        # one place an operator is looking (the drain's own output, and the summary that reaches
        # ticks.jsonl) has to say how many were set aside and where the reversal switch is.
        parts = []
        if survey.orphaned:
            parts.append(f"{len(survey.orphaned)} orphaned (index row, no dossier JSON on disk)")
        if survey.stalled:
            parts.append(f"{len(survey.stalled)} stalled (>= {max_att} unresolved re-vets; "
                         f"rm {drain_state.ledger_path(store.root)} to retry them)")
        if survey.unpublishable:
            parts.append(f"{len(survey.unpublishable)} provisional KILLs (already dead — a KILL "
                         f"never reaches the publish gate; set schedule.revet_provisional_kills: "
                         f"true, or run `vet --resume --only provisional-kill`, to work them)")
        excluded = " Excluded: " + "; ".join(parts) + "."
    if not pending:
        if excluded:
            print(f"No backlogged candidate the drain can work on.{excluded}")
        else:
            print("No deferred or provisional candidates to resume. Moat is healthy.")
        return _done({"backlog": 0, "attempted": 0, "resumed": 0,
                                 "passes": 0, "kills": 0, "defers": 0})

    # MOAT PREFLIGHT — never drain into a blind moat.
    #
    # `run_scheduled.py` gained this precondition for GENERATION on 2026-08-06 (392ce4c); the
    # drain never had one, and the standalone `vet --resume` invocation does not go through the
    # scheduler at all. Measured 2026-08-06 with `operator: [claude_cli]` — a ONE-brain moat —
    # marked dead for 3033s: the drain kept running and every re-vet raised
    # ProviderExhaustedError, which `verify.py` turns into retrieval_failed -> DEFER_GATE ->
    # Decision.DEFER. Over one 30-minute window that moved provisional -14 / defer +13: a net
    # backlog change of -1 for a full pass of CLI spend. The rows were relabelled, not resolved.
    #
    # Worse than useless: the drain competes for the same subscription CLI as the daemon, and
    # 392ce4c's own commit message records that the drain's load was implicated in the moat
    # flapping that minted the provisional rows in the first place. A drain that runs while the
    # brain is benched is helping to keep it benched.
    #
    # Deliberately no --force override: when no trusted brain can rule, there is no verdict to
    # be had, so "force" would only buy a more expensive way to write DEFER.
    from .health import moat_blind_reason
    blind = moat_blind_reason(cfg)
    if blind:
        print(f"Found {backlog} deferred + provisional candidate(s), but {blind}. "
              f"Re-vetting none — a drain into a blind moat only relabels rows "
              f"provisional->defer, and its own CLI load helps keep the brain benched.")
        return _done({"backlog": backlog, "attempted": 0, "resumed": 0,
                                 "passes": 0, "kills": 0, "defers": 0, "skipped": blind})

    # Restrict to one population BEFORE the priority sort and the `--limit` slice, so the
    # bound is spent on the rows the operator asked for. `backlog` keeps counting the whole
    # drainable population: the printed line then reads "Found 351 ... re-vetting 72 of them",
    # which is the truth. (`only` is parsed and validated at the top of this function, because
    # it also decides whether the survey may exclude the provisional-KILL population.)
    if only != "all":
        pending = [r for r in pending if _resume_selects(r, only)]
        if not pending:
            print(f"Found {backlog} deferred + provisional candidate(s), but none match "
                  f"--only {only}. Nothing to re-vet.{excluded}")
            return _done({"backlog": backlog, "attempted": 0, "resumed": 0,
                                     "passes": 0, "kills": 0, "defers": 0})

    limit = getattr(args, "limit", None)
    if limit is not None and limit <= 0:
        # 0 means "drain nothing" — NOT "drain everything". The old test was
        # `if limit is not None and limit > 0`, so a 0 fell through to the unsliced
        # `pending` and re-vetted the entire backlog (411 items on 2026-08-05) inside a
        # single guard decision. The daemon guards the call with `if n_resume:`, so it was
        # unreachable from there, but `schedule.resume_per_tick: 0` is documented as
        # "disables the drain entirely" (run_scheduled.py:83) and `_resume_per_tick` floors
        # negatives to 0 — one config edit or one direct call away from the exact unbounded
        # pass the spend rail exists to prevent. Only `None` (the CLI default) means
        # unbounded, which is what `vet --resume` has always done.
        print(f"Found {backlog} deferred + provisional candidate(s); limit={limit} "
              f"disables the drain — re-vetting none.{excluded}")
        return _done({"backlog": backlog, "attempted": 0, "resumed": 0,
                                 "passes": 0, "kills": 0, "defers": 0})
    # HIGHEST-VALUE POPULATION FIRST, then oldest first within it (`_drain_rank`).
    #
    # Age alone was the whole sort key until 2026-08-06, and on this backlog it inverted the
    # priority: of the oldest 100 drainable rows, 51 were provisional KILLs — rows that cannot
    # publish under any verdict — and exactly 1 was a provisional PASS, the population a single
    # confirming re-vet turns into sellable inventory. At the daemon's 3-per-tick bound the
    # budget went almost entirely to the rows with nothing to produce.
    #
    # Age still decides WITHIN a rank, which is what the old comment was protecting: `store.all`
    # returns catalogue order, this backlog reaches back to 2026-06-14, and newest-first would
    # starve the oldest rows forever at 3 per tick. Nothing starves; the ranks just get served
    # in the order of what they can produce.
    #
    # ATTEMPTS SIT BETWEEN RANK AND AGE (added 2026-08-15, with the producer/consumer split).
    # Under the tick, "oldest first within a rank" was the whole anti-starvation story and it was
    # enough, because generation and vetting shared one deadline: nothing new could arrive while
    # a pass ran. A producer that writes rows continuously breaks that, and the live index shows
    # exactly the shape it breaks on — a barbell, 62 DEFER rows from today and 45 from more than
    # 30 days ago, with NOTHING in between (measured 2026-08-15 on store/prospector.db). Pure age
    # hands every pass to the June cohort first: rows that have already been attempted repeatedly
    # and keep coming back. A fresh candidate then waits behind the least resolvable rows in the
    # store, which is head-of-line blocking by the one group least likely to produce anything.
    #
    # `attempts` is the number of unresolved re-vets `drain_state` has already recorded for a
    # candidate, so this is free — the ledger is a small JSON the survey already reads, and no
    # new state is introduced. A row that has never been tried goes first WITHIN its rank; one
    # that has burned three attempts goes last; `drain_state.max_attempts` retires it entirely.
    # Nothing starves, because attempts only rise when a row is actually worked.
    #
    # Rank stays FIRST, deliberately. Cross-rank starvation (a fresh DEFER behind a wall of
    # provisional PASSes) is the obvious thing to fix here and is NOT a condition this store can
    # be in: rank 0 measured ZERO rows, and provisional rows are minted only by a brain outside
    # `moat_primary()` (operator.py:1451) — today's roster has both brains inside it, so ranks 0
    # and 2 are legacy populations that drain to zero and never refill. Weighted fair share and
    # aging promotion are the right answers to that problem when it exists; building them now
    # would be pinning a policy to a condition no measurement shows.
    _attempts = drain_state.load(store.root)
    pending = sorted(pending, key=lambda r: (
        _drain_rank(r),
        _attempts.get(str(r.get("candidate_id", "") or ""), 0),
        str(r.get("created_at", "")),
    ))

    # UNMOVABLE ROWS MUST NOT CONSUME THE BOUNDED PASS — and `drain_survey` has already taken
    # them out, so this slice is a plain one.
    #
    # The exclusion used to happen HERE, inside the `limit` slice, and only for orphans. That was
    # right for the drain and wrong for the system: `run_scheduled._backlog_size` counts the same
    # population to decide whether generation may run, and it kept counting the rows this loop was
    # skipping — so the brake could sit engaged on a number no drain could ever reduce. Moving
    # both exclusions into `drain_survey` is what makes the brake self-releasing rather than a
    # freeze that outlives the reason for it.
    #
    # PROVEN on the live store 2026-08-06, first tick that ever ran the drain:
    #   ticks.jsonl result -> 'resumed': {'backlog': 406, 'attempted': 3, 'resumed': 0, ...}
    #   backlog 406, orphaned 46, leading unbroken run of orphans 45 (2026-06-14..06-21)
    # At 3 per tick that is 15 consecutive ticks — ~1.2 days — of no-op drains reporting
    # `attempted: 3` before the pass reaches its first real candidate.
    # A ROW SOMEONE ELSE IS HOLDING MUST NOT EAT THE BOUNDED SLICE EITHER — same rule as the
    # unmovable rows above, one cause over. `_revet` claims each row before it does any work and
    # skips it when the claim fails, which is correct and is not enough: the slice is taken from a
    # DETERMINISTIC rank sort, so the leased rows are the same rows at the front of the queue every
    # pass. The pass then spends its whole budget discovering the same 24 collisions, silently.
    #
    # MEASURED ON THE LIVE STORE 2026-08-16, which is why this is here: the consumer logged
    #   {"attempted": 24, "resumed": 0, "backlog": 317}
    # every ~10 seconds for 25 minutes, judging nothing, while 317 rows waited. All 24 leases
    # belonged to four SIGKILLed processes (pids 13217, 40647, 7563, 9536 — none alive), and
    # `schedule.lease_ttl_s` is 7200, so the queue was frozen for up to two hours by four dead
    # workers. Filtering here moves the pass on to row 25 instead.
    #
    # `backlog` is computed ABOVE this filter and is untouched: a leased row has not left the
    # queue, and the generation brake reads the same number it always did (store.py:560).
    pending, n_leased_skipped = _drop_leased(pending, store)
    if limit is not None:
        pending = pending[:limit]

    # NAME THE MIX, not just the count. A bounded pass that reports only "re-vetting 3 of them"
    # cannot be told apart from one spending its whole budget on rows that can never publish —
    # which is exactly what was happening before the rank sort, unnoticed, for six weeks.
    _ranks = [_drain_rank(r) for r in pending]
    mix = ", ".join(f"{_ranks.count(i)} {_RANK_NAMES[i]}"
                    for i in sorted(set(_ranks)))
    skipped_note = (f" Skipped {n_leased_skipped} row(s) another worker is holding."
                    if n_leased_skipped else "")
    print(f"Found {backlog} deferred + provisional candidate(s); re-vetting "
          f"{len(pending)} of them with the moat ({mix}; highest-value population "
          f"first)...{excluded}{skipped_note}")
    from concurrent.futures import CancelledError, ThreadPoolExecutor, as_completed

    from . import progress
    from .models import Candidate
    from .telemetry import get_usage_summary

    n_pass = n_kill = n_defer = 0
    n_unreached = 0
    n_leased = 0
    resumed_dossiers = []

    # THE DRAIN IS VETTING WITH A DIFFERENT INPUT FILTER — so it runs on the same pool, at the
    # same width, as the vetting batch in `run_signal` (run.py:1456). Until 2026-08-15 it was a
    # plain `for` calling `vet_candidate` synchronously while `run_signal` ran `_vet_workers(cfg)`
    # of them at once, and THAT ASYMMETRY IS THE BACKLOG. Measured on the daemon's own log:
    #   tick 13:23:07Z — drain row 1 alone took 4127s, and row 2 was still running at +5885s;
    #   tick 16:08:57Z — the vetting pool completed one candidate every ~251s at three workers.
    # Three rows a tick against a generator committing fifty is not a policy anyone chose; it is
    # one `for` loop. The 202-row backlog (oldest 2026-07-02) is that arithmetic, not an outage.
    #
    # NOTHING ABOUT THE DRAIN'S POLICY MOVES HERE. `pending` is already ranked and sliced above
    # (highest-value population first, oldest first within it, `--only` applied, `--limit`
    # applied), and the pool is fed in exactly that order — so a bounded pass still spends itself
    # on the same rows, in the same priority, as the serial loop did. What changes is only how
    # many are in flight at once.
    #
    # ALL BOOKKEEPING STAYS ON THIS THREAD. The workers do exactly one thing — load a row and call
    # `vet_candidate` — and every counter, every `drain_state` write and every summary field is
    # written in the completion loop below. `drain_state.record_unresolved` is itself safe to call
    # concurrently (it holds an `fcntl.flock`, drain_state.py:174), but it DEGRADES TO UNLOCKED and
    # merely logs when flock is unavailable (drain_state.py:204), and eight threads turn that
    # degraded path from a theoretical race into a live one. A lost attempt count means a stuck row
    # is never excluded from the backlog, which silently re-engages the generation freeze the
    # attempt cap exists to release. Keeping the increments on one thread costs nothing.
    workers = _vet_workers(cfg)
    total = len(pending)

    # WHO HOLDS A LEASE. Per-INVOCATION, not per-process: two `vet --resume` passes running
    # concurrently in one process would share a pid, and `Store.claim` deliberately lets an owner
    # re-take its own row so a long vet can renew. A shared owner string would turn that renewal
    # affordance into "both passes may hold the same row", which is the bug, not the feature.
    lease_owner = _mint_lease_owner()
    lease_ttl = _lease_ttl_s(cfg)

    def _revet(idx: int, row: dict):
        """Load and re-vet ONE backlog row. Runs on a worker; touches no shared counter.

        Returns `(candidate_id, dossier)`; `(candidate_id, None)` when the index row has no
        dossier JSON on disk; `(candidate_id, _LEASE_HELD)` when another worker already owns it.
        The caller distinguishes all three, because attributing a store inconsistency or a normal
        lease contention to the budget would blame a rail for something it had nothing to do with
        — the same confusion the serial loop avoided by counting off its loop index.
        """
        cid = row.get("candidate_id", "")
        # CLAIMED BEFORE ANY WORK, INCLUDING THE READ. Selection is a plain SELECT and always
        # was, so between `drainable()` and here a second consumer — another daemon, or an
        # operator running `vet --resume` by hand, which this repo treats as routine — can pick
        # the same row. Doing the work and discovering the collision afterwards would already
        # have paid for two vets and, on a PASS, raced two publishes into a Stripe mint that has
        # no lock of its own. The compare-and-swap is the whole defence, so nothing may precede
        # it.
        if not store.claim(cid, lease_owner, lease_ttl):
            return cid, _LEASE_HELD
        try:
            return cid, _revet_claimed(idx, row, cid)
        finally:
            # Released on EVERY path, including a raise: a row whose vet blew up belongs back in
            # the queue immediately, not parked for the remainder of a TTL sized for the worst
            # case. Scoped to this owner inside `release`, so a lease that already expired and
            # was legitimately re-taken is not stolen back on the way out.
            store.release(cid, lease_owner)

    def _revet_claimed(idx: int, row: dict, cid: str):
        """The re-vet itself, with this worker's lease already held. Returns a Dossier or None."""
        full = store.get(cid)
        if not full:
            return None
        cand_dict = full.get("candidate", {})
        cand = Candidate.from_dict(cand_dict)
        # Also restore ambition_tier and structural_form from the stored data.
        cand.ambition_tier = str(cand_dict.get("ambition_tier", "") or "")
        cand.structural_form = str(cand_dict.get("structural_form", "") or "")
        was_provisional = bool(row.get("provisional", 0))
        prior = ("provisional " + str(full.get("decision", "")).upper()
                 if was_provisional else "deferred")
        original_reason = full.get("reason", "")[:80]
        # The index rides in the banner because parallel re-vets interleave on stderr — the same
        # reason `run_signal` tags every vet with `_label(idx, total, title)` (run.py:1452).
        progress.banner(f"[resume {idx}/{total}] {cand.title!r} (was {prior}: {original_reason})")
        # THE ROW IS JUDGED ON ITS OWN LANE'S BAR. `run_signal` has resolved per-candidate config
        # since Part 14 (`vet_cfg = cfg.for_lane(cand.ambition_tier)`, run.py:1483); the drain
        # passed the GLOBAL cfg, so a row parked as DEFER came back graded against the default
        # lane's `hard_gates`, `thresholds` and `weights` instead of its own (config.py:697-727).
        # That is wrong in BOTH directions — a side_hustle idea held to a venture bar, a venture
        # idea waved through a cheaper one — in a dossier that reads as fully reasoned. It only
        # ever hit the rows a budget parked, which is why it survived; it is fixed here because
        # this pass now moves 8 rows at a time instead of 3, and because the queue this drain is
        # becoming will route EVERY candidate through this call site. `ambition_tier` is restored
        # from the stored candidate five lines up, and `for_lane` returns self unchanged on an
        # empty or unknown name, so an untagged row behaves exactly as before.
        #
        # Resolved defensively for the same reason `_vet_workers` reads its section defensively
        # (run.py:33): this drain's callers include `None` and `SimpleNamespace` configs from the
        # daemon's own tests, where the serial loop never asked anything of `cfg` and so never
        # noticed. A config that cannot describe lanes does not have any, and the error a bare
        # attribute access raises here is swallowed by the per-row `except Exception` below —
        # so it would have shown up as every row failing, not as a missing method.
        _for_lane = getattr(cfg, "for_lane", None)
        vet_cfg = _for_lane(cand.ambition_tier) if callable(_for_lane) else cfg
        return vet_candidate(
            cand, op, search, vet_cfg, store=store,
            query_op=fast_op,
            publish=getattr(args, "publish", False),
            show_checks=True,
            board_personas=_resolve_board(args),
            # THE TWO BUDGETS THE DRAIN NEVER RECEIVED. `run_signal` has passed both into every
            # vet since 2026-08-15; this call site was missed, so the one path that runs FIRST in
            # a tick was the one path with no ceiling on its most expensive phase. `vet_candidate`
            # clamps the artifact ceiling to `vet_deadline_mono` internally, so a single long row
            # can never outlive the drain's own wall.
            artifact_time_budget_s=artifact_time_budget_s,
            vet_deadline_mono=deadline_mono)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        fut_meta: dict = {}
        budget_stopped = False
        exhausted = False

        def _decline_remaining() -> int:
            """Cancel every un-started re-vet; return how many were NEWLY stopped.

            Counted as a before/after diff of the cancelled set rather than from `cancel()`'s
            return value, because `Future.cancel()` returns True for a future that was ALREADY
            cancelled. A raw sum therefore double-counts the moment two rails fire in one pass,
            and `unreached_budget` is the number an operator sizes `drain_budget_frac` from. This
            is the same trap `_defer_unstarted_candidates` takes an `already_cancelled` argument
            for (run.py:120).
            """
            before = {f for f in fut_meta if f.cancelled()}
            for f in fut_meta:
                f.cancel()
            return len({f for f in fut_meta if f.cancelled()} - before)

        # THE WALL IS CONSULTED BEFORE ANYTHING IS SUBMITTED, not only between completions. An
        # already-spent budget must start ZERO rows: the serial loop got that for free by testing
        # at the top of every iteration, whereas a pool that submits first would have `workers`
        # expensive vets in flight before its first completion could check anything. Asking
        # `_vet_budget_cancel` with nothing to cancel is the same "is the budget spent?" question —
        # one definition of spent, shared with the loop below and with the vetting batch.
        if _vet_budget_cancel(deadline_mono, ()) is not None:
            n_unreached = total
            progress.note(
                f"Drain budget already spent before the pass began: starting none of {total} "
                f"row(s). They keep their state and their place in the backlog.")
        else:
            fut_meta = {executor.submit(_revet, i, row): i
                        for i, row in enumerate(pending, start=1)}

        for future in as_completed(fut_meta):
            # THE DRAIN'S OWN WALL. Measured 2026-08-15 on the daemon's own log, and it is the
            # reason this exists: the drain ran BEFORE generation, inside the tick's hard-deadline
            # Timer, with no budget of any kind — and it ate the tick.
            #   tick 10:16:59Z — 3 rows took 4197s of a 10800s tick (39%) before generation began;
            #   tick 13:23:07Z — row 1 alone took 4127s and row 2 was still running at +5885s.
            # Per-row it is not the verdict that dominates but the CONTENT phase on a row that
            # passes: 1461s of row 1's 2844s (51%), 2331s of 4127s (56%). Hence both rails — this
            # wall, and `artifact_time_budget_s` above.
            #
            # STOPPING HERE IS LOSSLESS, which is what makes cancellation the right instrument. A
            # row not reached keeps the exact state it had: it is already a DEFER or provisional
            # row in the backlog, `drainable()` still counts it, and the next pass picks it up from
            # the same priority sort. Nothing was generated for it, nothing is discarded, and no
            # attempt is recorded against its cap — unlike the vetting batch, where a cancelled
            # candidate had already been paid for and must be parked deliberately
            # (`_defer_unstarted_candidates`, run.py:105). That asymmetry is why this rail needs no
            # parking step and that one does.
            #
            # Checked BEFORE banking each result rather than after, so a breach is acted on at the
            # first completion past the wall instead of one row later.
            if not budget_stopped and _vet_budget_cancel(deadline_mono, fut_meta) is not None:
                budget_stopped = True
                n_unreached += _decline_remaining()
                progress.note(
                    f"Drain budget spent: stopping after {len(resumed_dossiers)} of {total} "
                    f"row(s). The {n_unreached} not reached keep their state and their place in "
                    f"the backlog — nothing is discarded — and the tick gets its generation "
                    f"batch back.")
            try:
                cid, d = future.result()
            except CancelledError:
                # A re-vet this loop cancelled above — expected, not an error, and already counted
                # in `n_unreached`. Caught HERE because since 3.8 CancelledError derives from
                # BaseException, so the `except Exception` below cannot see it and it would escape
                # and kill the pass.
                continue
            except ProviderExhaustedError as e:
                # Moat still exhausted. The serial loop `break`s here; the pool declines to buy
                # more work instead, which is the same decision with the in-flight rows banked
                # rather than abandoned. Every un-started row keeps its prior state — deferred, or
                # its provisional verdict — exactly as the break left it, and spends no attempt.
                if not exhausted:
                    exhausted = True
                    n_unreached += _decline_remaining()
                    progress.note(f"Moat still exhausted ({e}). Remaining candidates keep their "
                                  f"prior state. Re-run `vet --resume` when moat recovers.")
                continue
            except Exception as e:  # noqa: BLE001 — one bad row must never cost the whole pass
                logger.error("ERROR re-vetting backlog row: %s", e, extra={"error": str(e)})
                progress.note(f"⚠ error re-vetting a backlog row: {e}")
                continue
            if d is _LEASE_HELD:
                # Someone else is working this row. Not an error and not a skip to investigate:
                # it is the queue doing its job. Counted so the summary can distinguish "the
                # pass did nothing because rows were contended" from "the pass did nothing
                # because the store is broken" — two very different mornings for an operator.
                n_leased += 1
                continue
            if d is None:
                print(f"  ⚠ {cid}: dossier JSON missing, skipping")
                continue

            if d.decision == Decision.PASS:
                n_pass += 1
            elif d.decision == Decision.KILL:
                n_kill += 1
            else:
                n_defer += 1

            # PER-ROW ATTEMPT ACCOUNTING. Only a COMPLETED re-vet with a verdict counts, and only
            # if that verdict left the row in the backlog — a DEFER, or a ruling that is
            # provisional again. The two outage paths never reach here (a blind moat returns before
            # the pool is built; a ProviderExhaustedError is handled above), which is the point:
            # the backlog exists because of outages, so an outage must not be able to spend a
            # row's budget.
            #
            # A resolved row is FORGOTTEN rather than left at its count, so if a later re-save puts
            # it back in the backlog it starts from a full budget instead of inheriting a spent one.
            if max_att:
                if d.decision == Decision.DEFER or bool(getattr(d, "provisional", False)):
                    n = drain_state.record_unresolved(store.root, cid)
                    if n >= max_att:
                        progress.note(
                            f"{cid}: {n} completed re-vets, still unresolved — no longer counted "
                            f"as backlog, so the generation brake can release. "
                            f"rm {drain_state.ledger_path(store.root)} to retry it.")
                else:
                    drain_state.forget(store.root, cid)
            resumed_dossiers.append(d)

    # Summary.
    print(f"\n{'='*60}")
    print(f"Resume complete: {len(resumed_dossiers)}/{len(pending)} re-vetted  "
          f"✅{n_pass}  🛑{n_kill}  ⏸️{n_defer}")
    if n_defer > 0:
        print(f"  {n_defer} still deferred — moat may still be recovering.")
    if n_pass > 0:
        print(f"  ✅ {n_pass} candidate(s) PASSED — see store/dossiers/")
    usage = get_usage_summary()
    from .report import costs_report
    print(f"\n{costs_report(log_path or '')}")
    summary = {"backlog": backlog, "attempted": len(pending), "resumed": len(resumed_dossiers),
               "passes": n_pass, "kills": n_kill, "defers": n_defer,
               # In the RETURN value, not just the print above. Under launchd this function's
               # stdout is fd 1 → store/scheduler/launchd.out.log (measured on pid 48771 via
               # lsof), which nothing reads and which Python block-buffers because it is a
               # file — so at 00:58 the tick's cost report was still sitting unflushed in the
               # process. The summary dict is the stream that survives: run_scheduled.py:190
               # logs it to stderr and it lands in the tick row.
               #
               # `metered_usd`, NOT `cost_usd`. This is billed money only — the figure
               # `daily_cap_usd` enforces. It is legitimately 0.00 for a drain that ran on the
               # Claude Code subscription, which is the moat's primary brain, so a key called
               # `cost_usd` reading 0.0 would say "the drain was free" when it in fact spent
               # subscription allowance. The other leg is already in the same tick row as
               # `today_subscription_usd` (scheduler/guard.py:161). Two legs, two names —
               # guard.py:21-45 has the full measurement of why they must never be added up.
               "metered_usd": round(usage.get("total_cost_usd", 0.0), 4)}
    if n_unreached:
        # NAMED in the tick row. A drain that stops on its budget otherwise reads exactly like
        # a drain that had less work than it was given — `attempted: 3, resumed: 1` with no
        # third number is the "counters lie" shape, and it would hide the one fact an operator
        # needs to size `drain_budget_frac`: that the wall is binding.
        summary["unreached_budget"] = n_unreached
    if n_leased:
        # Same argument, for the queue. A pass whose rows were all held by another consumer
        # reports `attempted: N, resumed: 0` — identical on its face to a pass that found N
        # broken rows. One is the queue working; the other is damage. An operator cannot be
        # asked to tell them apart from a number that does not exist.
        summary["leased_elsewhere"] = n_leased
    if n_leased_skipped:
        # The rows this pass DECLINED to take because someone else holds them, as opposed to
        # `leased_elsewhere`, which is the rows it tried and lost. Reported separately because
        # they answer different questions: this one says how much of the queue is parked, and a
        # number that stays high across passes is a dead worker holding rows to their TTL.
        summary["leased_skipped"] = n_leased_skipped
    # Excluded counts surfaced into the tick row, so a store inconsistency or an exhausted attempt
    # budget is visible in ticks.jsonl and the state probe instead of showing up as an
    # inexplicable `attempted: 3, resumed: 0` — or, once the brake is engaged, as a generation
    # freeze with nothing anywhere naming the rows that are holding it.
    return _done(summary)


def recover_abandoned(cfg: Config, *, limit: int | None = None,
                      publish: bool = False) -> dict:
    """Re-vet work abandoned by a process that died mid-vet, WITHOUT running the ordinary drain.

    WHY THIS IS A SEPARATE ENTRY POINT. `_cmd_resume` already recovers first, so `vet --resume`
    heals on its own. The daemon does not always reach it: `_drain_pass` returns early on
    `if not n_resume` (`scheduler/run_scheduled.py:793`), so `schedule.resume_per_tick: 0` — the
    documented way to switch the drain off — would also switch off recovery. That is the exact
    coupling the drain was pulled out of `_default_generate` on 2026-08-06 to break: one decision
    about the treadmill silently disabling the mechanism that pays the loss back.

    Recovery is not draining. Abandoned work has no index row, so no backlog policy is about it.
    """
    from .operator import make_operator
    from .telemetry import reset_usage

    reset_usage()
    args = argparse.Namespace(limit=limit, publish=publish, board=None,
                              fixtures=None, search=None)
    store = Store(cfg)
    return _recover_orphans(args, cfg, make_operator(cfg), make_operator(cfg, fast=True),
                            _make_search(cfg, args), store)


def resume_deferred(cfg: Config, *, limit: int | None = None,
                    publish: bool = False,
                    budget_s: float | None = None,
                    artifact_time_budget_s: float | None = None) -> dict:
    """Run one bounded re-vet pass over the DEFER + provisional backlog, in-process.

    THE GAP THIS CLOSES. `vet --resume` has always existed and always worked, but nothing
    ever called it. Measured 2026-08-05: 113 `*.defer.json` dossiers on disk, oldest
    2026-06-24, while `alerts.py:219` was telling the operator they "auto re-vet ... once
    the moat recovers". `grep -- --resume` over the repo found only log strings, the
    argparse flag, and docs — no scheduler path and none of the four launchd plists. So
    candidates that had already cost generation + prescreen sat unvetted for six weeks
    because a transient moat outage happened to catch them.

    Operators are built here the same way `_cmd_signal` builds them, so the daemon does not
    have to import the CLI's argparse plumbing.
    """
    from .operator import make_operator
    from .telemetry import reset_usage
    reset_usage()
    op = make_operator(cfg)
    fast_op = make_operator(cfg, fast=True)
    args = argparse.Namespace(limit=limit, publish=publish, board=None,
                              fixtures=None, search=None)
    search = _make_search(cfg, args)
    store = Store(cfg)
    # The same ledger `main()` passes for every CLI command (see the log_path it builds from
    # cfg.store_dir). Omitting it made the daemon's drain the one caller with no log path, so
    # its last line printed "No audit log at ." — the pass spends real money re-vetting and
    # the operator got no cost line for it, on the only run nobody is watching.
    # `budget_s` is a DURATION and becomes an absolute instant here, at the last moment before
    # the pass starts — the house pattern for a phase bound (see `_gen_deadline`/`_vet_deadline`
    # in `run_signal`). Taking the instant here rather than in the caller keeps the operator
    # construction above (which makes network calls) out of the drain's own budget.
    import time as _time
    deadline = (_time.monotonic() + budget_s) if budget_s else None
    return _cmd_resume(args, cfg, op, fast_op, search, store,
                       log_path=cfg.store_dir / "prospector.jsonl",
                       deadline_mono=deadline,
                       artifact_time_budget_s=artifact_time_budget_s)


def run_decay_sweep(cfg: Config, *, limit: int | None = None) -> dict:
    """Run one bounded decay sweep (re-vet PASSes past `reverify_due_at`), in-process.

    THE GAP THIS CLOSES — the same shape as `resume_deferred` above, one rail over.
    `decay.py::run_decay_loop` has always existed and always worked, and nothing ever called
    it: its only importer was `tests/sim/test_decay.py`. So `reverify_due_at` was stamped on
    every dossier and read by nothing, and a PASS minted under a superseded gate kept its
    ruling forever. Measured 2026-08-06: 29 of 83 live PASSes past SLA, and the 5 that fail
    today's `moat_ungrounded` gate were all minted on or before the day it landed (73ae976).

    Brains are built here exactly as `resume_deferred` builds them, so the daemon does not have
    to import the CLI's argparse plumbing.
    """
    from .decay import run_decay_loop
    from .operator import make_operator
    from .telemetry import get_usage_summary, reset_usage
    reset_usage()
    op = make_operator(cfg)
    args = argparse.Namespace(limit=limit, publish=False, board=None,
                              fixtures=None, search=None)
    search = _make_search(cfg, args)
    store = Store(cfg)
    out = run_decay_loop(store, op, search, cfg, limit=limit)
    usage = get_usage_summary()
    # `metered_usd`, NOT `cost_usd` — billed money only, the figure `daily_cap_usd` enforces.
    # A sweep run on the Claude Code subscription is legitimately 0.00 here while still
    # spending allowance; the subscription leg rides in the tick row as
    # `today_subscription_usd` (scheduler/guard.py:161). Two legs, two names, never summed.
    out["metered_usd"] = round(usage.get("total_cost_usd", 0.0), 4)
    return out


def _cmd_signal(args: argparse.Namespace, log_path: Path) -> None:
    """Run the full signal pipeline from text or file."""
    cfg = _build_config_and_overrides(args)

    if args.text is not None:  # "" is a valid blue-sky signal, not "missing"
        signal_text = args.text
    elif args.file:
        with open(args.file, encoding="utf-8") as fh:
            signal_text = fh.read()
    else:
        print("Error: --text or --file is required for the signal command.", file=sys.stderr)
        sys.exit(1)

    from .operator import make_operator
    op = make_operator(cfg)
    search = _make_search(cfg, args)
    store = Store(cfg)

    dossiers = run_signal(signal_text, cfg=cfg, op=op, search=search, store=store,
                          k=getattr(args, "count", None),
                          publish=getattr(args, "publish", False),
                          lanes=_resolve_lanes(cfg, args),
                          focus=getattr(args, "focus", None),
                          board_personas=_resolve_board(args))

    # Durable, human-readable result on stdout (stderr carried the live progress).
    print(f"\n=== Signal result: {len(dossiers)} candidate(s) vetted ===")
    for d in dossiers:
        glyph = {Decision.PASS: "PASS", Decision.KILL: "KILL",
                 Decision.DEFER: "DEFER"}.get(d.decision, d.decision.value.upper())
        if d.decision == Decision.DEFER:
            detail = "retrieval failed — re-vet (NOT a kill)"
        elif d.gate_fired:
            detail = f"gate={d.gate_fired}"
        else:
            detail = f"composite={d.score.composite:.2f}" if d.score else ""
        print(f"  [{glyph}] {d.candidate.title}  {detail}")
        print(f"         id={d.candidate.candidate_id}  (full dossier: store/dossiers/{d.candidate.candidate_id}.json)")
    from .report import costs_report
    print(f"\n{costs_report(log_path or '')}")


def _cmd_consume(args: argparse.Namespace) -> None:
    """`consume` — run the vetting consumer until stopped.

    Thin on purpose. Everything that decides anything lives in `consumer.run_consumer`
    (when to drain) and `_cmd_resume` (how), so this is argument plumbing and a summary.

    `--once` is `--max-passes 1` and is named separately because that is the question an
    operator actually asks — "does a pass work right now?" — and a flag they can remember is
    a rail they will use before starting a daemon.

    No `log_path` parameter, unlike its neighbours: each drain pass builds its own from
    `cfg.store_dir` inside `resume_deferred`, which is what made the daemon's drain the one
    caller whose costs were reported to nobody. A second path threaded from here would be a
    second answer to the same question.
    """
    from .consumer import StopFlag, run_consumer

    cfg = _build_config_and_overrides(args)
    max_passes = 1 if getattr(args, "once", False) else getattr(args, "max_passes", None)

    flag = StopFlag().install()
    try:
        out = run_consumer(cfg, batch=getattr(args, "batch", None),
                           publish=getattr(args, "publish", False),
                           max_passes=max_passes, stop=flag)
    finally:
        # Restore whatever handled SIGTERM before, always. A CLI that leaves its own handler
        # installed changes how the interpreter dies for everything that runs after it.
        flag.restore()

    print(f"\n=== Consumer stopped: {out['stopped_because']} ===")
    print(f"  passes    : {out['passes']}  ({out['idle']} idle, {out['blocked']} blocked, "
          f"{out['errors']} errored)")
    print(f"  rows      : {out['resumed']} resumed of {out['attempted']} attempted")
    if out["leased_elsewhere"]:
        # Never silently zero-summed into "attempted". Rows held by another worker are the
        # queue working correctly, and they read identically to broken rows without this line.
        print(f"  leased    : {out['leased_elsewhere']} row(s) held by another worker")


def _cmd_generate(args: argparse.Namespace, log_path: Path) -> None:
    """Blue-sky run: generate + vet candidates with NO signal (signal_text="").
    With --resume: re-run the full pipeline for all pending signals that failed due
    to generation chain exhaustion."""
    cfg = _build_config_and_overrides(args)

    # --- Handle --resume: re-run pipeline for pending signals ---
    if getattr(args, "resume", False):
        _cmd_generate_resume(args, cfg, log_path)
        return

    # `--no-vet --publish` is refused rather than quietly ignored. Producer mode returns
    # before a verdict exists, and publishing is gated on PASS, so the flag could only ever
    # be inert — and an operator who passed it would reasonably believe rows had shipped.
    # Silently dropping a flag the caller typed is the "no silent feature removal" defect.
    no_vet = bool(getattr(args, "no_vet", False))
    if no_vet and getattr(args, "publish", False):
        print("error: --no-vet queues candidates without ruling on them, so there is no PASS "
              "to publish.\n  Queue them, then publish from the consumer:\n"
              "    python -m prospector.run generate --no-vet\n"
              "    python -m prospector.run vet --resume --publish",
              file=sys.stderr)
        sys.exit(2)

    from .operator import make_operator
    op = make_operator(cfg)
    search = _make_search(cfg, args)
    store = Store(cfg)

    dossiers = run_signal("", cfg=cfg, op=op, search=search, store=store,
                          k=getattr(args, "candidates", None),
                          exploration=getattr(args, "exploration", None),
                          publish=getattr(args, "publish", False),
                          lanes=_resolve_lanes(cfg, args),
                          focus=getattr(args, "focus", None),
                          board_personas=_resolve_board(args),
                          vet=not no_vet)

    if no_vet:
        print(f"\n=== Queued {len(dossiers)} candidate(s) for vetting ===")
        for d in dossiers:
            print(f"  [QUEUED] {d.candidate.title}")
            print(f"         id={d.candidate.candidate_id}")
        print("\nDrain the queue with:  python -m prospector.run vet --resume")
        return

    print(f"\n=== Blue-sky result: {len(dossiers)} candidate(s) vetted ===")
    for d in dossiers:
        glyph = {Decision.PASS: "PASS", Decision.KILL: "KILL",
                 Decision.DEFER: "DEFER"}.get(d.decision, d.decision.value.upper())
        if d.decision == Decision.DEFER:
            detail = "retrieval failed — re-vet (NOT a kill)"
        elif d.gate_fired:
            detail = f"gate={d.gate_fired}"
        else:
            detail = f"composite={d.score.composite:.2f}" if d.score else ""
        print(f"  [{glyph}] {d.candidate.title}  {detail}")
        print(f"         id={d.candidate.candidate_id}  (full dossier: store/dossiers/{d.candidate.candidate_id}.json)")
    from .report import costs_report
    print(f"\n{costs_report(log_path or '')}")


def _cmd_generate_resume(args: argparse.Namespace, cfg: Config, log_path: Path) -> None:
    """Re-run the pipeline for all pending signals.

    Reads signals from signals/pending/ and re-runs the full signal pipeline
    (generate + vet) for each.  On success, removes the pending file.  On
    failure, leaves it so it can be retried again.
    Safe to re-run when the non-critical generation chain (DeepSeek/MiniMax/
    Gemini) recovers from quota depletion.
    """
    pending = _load_pending_signals()
    if not pending:
        print("No pending signals to resume. signals/pending/ is empty.")
        return

    from . import progress
    from .operator import make_operator
    from .telemetry import reset_usage

    reset_usage()
    op = make_operator(cfg)
    search = _make_search(cfg, args)
    store = Store(cfg)

    print(f"Found {len(pending)} pending signal(s). Re-running pipeline...")
    total_pass = total_kill = total_defer = 0
    for path, signal_text in pending:
        signal_key = path.stem
        progress.banner(f"[resume] {signal_key}: {signal_text[:60]!r}")
        dossiers = run_signal(signal_text, cfg=cfg, op=op, search=search, store=store,
                              k=getattr(args, "count", None),
                              publish=getattr(args, "publish", False),
                              lanes=_resolve_lanes(cfg, args))
        n_pass = sum(1 for d in dossiers if d.decision == Decision.PASS)
        n_kill = sum(1 for d in dossiers if d.decision == Decision.KILL)
        n_defer = sum(1 for d in dossiers if d.decision == Decision.DEFER)
        total_pass += n_pass
        total_kill += n_kill
        total_defer += n_defer

        if dossiers:
            # Generation succeeded — remove the pending file.
            path.unlink(missing_ok=True)
            print(f"  [{n_pass} pass / {n_kill} kill / {n_defer} defer] → pending file removed")
        else:
            # Generation still failing — leave the pending file for retry.
            print("  Generation still failing — pending file retained")

    print(f"\n=== Resume complete: {total_pass} pass / {total_kill} kill / {total_defer} defer ===")
    if total_defer > 0:
        print(f"  {total_defer} DEFERred — run `vet --resume` when moat recovers.")
    from .report import costs_report
    print(f"\n{costs_report(log_path or '')}")


def _cmd_report(args, cfg, log_path) -> None:
    """Render the catalogue / metrics / costs / generation quality / trend.
    Reads on-disk state only; no model calls."""
    from .diagnostics import calibration_alarms, render_alarms
    from .report import (
        catalogue_report,
        costs_report,
        full_report,
        generation_quality_report,
        metrics_report,
        trend_report,
    )
    from .store import Store
    store = Store(cfg)
    if args.full:
        print(full_report(store, log_path))
        print("\n" + "═" * 72)
        print("CALIBRATION SELF-WATCH")
        print("═" * 72)
        print(render_alarms(calibration_alarms(store, cfg)))
    elif args.metrics:
        print(metrics_report(store))
        print("\n  calibration self-watch:")
        print(render_alarms(calibration_alarms(store, cfg)))
    elif args.generation_quality:
        print(generation_quality_report(store))
    elif args.trend:
        windows = getattr(args, 'windows', (7, 30, 90))
        print(trend_report(store, windows=windows))
    elif args.costs:
        print(costs_report(log_path))
    else:  # default: catalogue
        print(catalogue_report(store, decision=args.decision))


def _cmd_diagnose(args, cfg, log_path) -> None:
    """Calibration self-diagnostics. Free catalogue alarms always; --deep also runs
    the golden set through the production brain chain against fixed evidence."""
    from .diagnostics import calibration_alarms, render_alarms, render_calibration, run_calibration
    from .store import Store
    store = Store(cfg)
    print("═" * 72)
    print("CALIBRATION SELF-WATCH (catalogue, no model calls)")
    print("═" * 72)
    print(render_alarms(calibration_alarms(store, cfg)))
    if getattr(args, "deep", False):
        print()
        report = run_calibration(cfg, floor=args.floor)
        print(render_calibration(report))
        if not report["ok"]:
            sys.exit(2)  # regression → non-zero so CI / scripts can gate on it


def _cmd_operators(args) -> None:
    """Probe every operator: latency, health, circuit breakers, chain state.

    Run this first whenever something feels wrong — it shows exactly which operators
    are alive, how fast they respond, and what the persisted health marks say.
    """
    import time

    from .config import load_config
    from .health import get_health
    from .operator import _build_operator

    SIMPLE_PROMPT = ("You are a helpful assistant. "
                      "Reply to the following with exactly three words: Hello, how are you?")

    print("=" * 72)
    print("OPERATOR DIAGNOSTICS")
    print("=" * 72)

    # ── 1. Persisted health (cross-run exhaustion marks) ───────────────────
    print("\n▸ Persisted health (store/provider_health.json)")
    try:
        health = get_health()
        pdata = health._load()
        if pdata:
            now = time.time()
            for name, entry in pdata.items():
                until = float(entry.get("dead_until", 0))
                remaining = max(0, until - now)
                print(f"  ✗ {name:55s}  dead for {int(remaining):>5}s more")
        else:
            print("  (clean — no exhausted operators)")
    except Exception as e:
        print(f"  (could not read: {e})")

    # ── 2. Individual operator probes ───────────────────────────────────────
    print("\n▸ Individual operator probes")
    available_ops = []  # list of (kind, op, elapsed_or_None)
    cfg = load_config(args.config if args.config else None)

    for kind in ("deepseek", "minimax", "claude_cli"):
        print(f"\n  {kind:15s}", end="", flush=True)
        try:
            op = _build_operator(kind, cfg, fast=True)
            print(f"  [{op.name}]", end="")

            t0 = time.monotonic()
            result = op._raw(SIMPLE_PROMPT, "", 0.1)
            elapsed = time.monotonic() - t0
            short = (result or "(empty)")[:60].replace("\n", " ")
            print(f"  ✓ {elapsed:6.1f}s  → {short!r}")
            available_ops.append((kind, op, elapsed))
        except RuntimeError as e:
            print(f"  ✗ unavailable: {e}")
            available_ops.append((kind, None, None))
        except Exception as e:
            print(f"  ✗ FAILED: {type(e).__name__}: {e}")
            available_ops.append((kind, None, None))

    # ── 3. Non-critical chain ordering (same logic as run_signal) ────────
    print("\n▸ Non-critical chain ordering")
    # These match the order in run_signal's _build_operator_chain calls.
    # gen_op: generation (creative, ~7000-char prompts)
    # fast_op: scoring + prescreen (0-5 axis, simple prompts)
    # Run `python -m prospector.run operators --gen` to measure and update these.
    try:
        def build_chain(order, fast_label):
            tiers = []
            for kind in order:
                try:
                    op = _build_operator(kind, cfg, fast=False)  # gen_op uses fast=False for reasoning
                    if fast_label:
                        # fast_op uses fast=True for scoring/prescreen
                        op = _build_operator(kind, cfg, fast=True)
                    tiers.append((kind, op))
                except RuntimeError:
                    pass
            if not tiers:
                return f"{fast_label or 'chain'}: (none available)"
            if len(tiers) == 1:
                return f"{fast_label}: {tiers[0][0]} (single)"
            return f"{fast_label}: {' → '.join(n for n, _ in tiers)}"

        _nc = _noncritical_order(cfg)
        print(f"  {build_chain(_nc, 'gen_op')}")
        print(f"  {build_chain(_nc, 'fast_op')}")
    except Exception as e:
        print(f"  ✗ could not build chains: {e}")

    # ── 4. Generation prompt probe (optional) ─────────────────────────────
    if getattr(args, "gen", False):
        print("\n▸ Generation prompt probe (~7000 chars)")
        from .prompts import market_kwargs, render
        # Market vars included so the probe measures the REAL prompt size and never
        # sends a literal {market_context} to a live operator below.
        sys_p, usr_p = render("generate",
                               signal_text="AI tools for small businesses",
                               sector="", strategy_lens="broaden",
                               exploration_level=0.5,
                               **market_kwargs(cfg))
        print(f"  Prompt size: {len(sys_p) + len(usr_p)} chars")
        # Probe the non-critical chain operators only
        gen_ops = [(k, o, b) for k, o, b in available_ops
                   if o is not None and k in _noncritical_order(cfg)]
        for kind, op, baseline in gen_ops:
            print(f"\n  {kind:15s} (baseline {baseline:.1f}s)...", end="", flush=True)
            t0 = time.monotonic()
            try:
                result = op._raw(sys_p, usr_p, 0.7)
                elapsed = time.monotonic() - t0
                short = str(result)[:80].replace("\n", " ")
                print(f"  {elapsed:6.1f}s  → {short!r}")
            except Exception as e:
                elapsed = time.monotonic() - t0
                print(f"  ✗ {elapsed:.1f}s: {type(e).__name__}: {e}")

    # ── 5. Summary ─────────────────────────────────────────────────────────
    print("\n▸ Summary")
    working = [(n, t) for n, _, t in available_ops if t is not None]
    slow = [(n, t) for n, _, t in available_ops if t is not None and t > 15]
    dead = [n for n, _, t in available_ops if t is None]

    if working:
        by_speed = sorted(working, key=lambda x: x[1])
        print(f"  Fastest : {by_speed[0][0]}({by_speed[0][1]:.1f}s)")
        print("  All     : " + ", ".join(f"{n}({t:.1f}s)" for n, t in by_speed))
    if slow:
        print("  Slow    : " + ", ".join(f"{n}({t:.1f}s)" for n, t in slow))
    if dead:
        print("  Dead    : " + ", ".join(dead))
    if not working and not dead:
        print("  (no operators probed — check network and API keys)")

    print("\n" + "=" * 72)



def _manage_lanes(action: str, lane_name: str | None, config_path: Path) -> None:
    """Manage ambition lanes in config.yaml via line-based editing.

    Actions:
      list   — print defined lanes + active_lane / active_lanes (no mutation)
      nix    — remove lane_name from active_lanes
      natch  — add lane_name to active_lanes
      set    — set active_lane to lane_name (single-lane pin; "" => unset)
      unset  — clear active_lane to "" (multi-lane mode)

    Uses regex-based line replacement to preserve YAML comments and structure.
    """
    import re

    text = config_path.read_text()

    # ------------------------------------------------------------------ list
    if action == "list":
        cfg = load_config(config_path)
        defined = list(cfg.lanes.keys()) if cfg.lanes else []
        print(f"Defined lanes: {', '.join(defined) if defined else '(none defined)'}")
        al = cfg.active_lane or ""
        als = cfg.active_lanes or []
        mode = "(single-lane mode)" if al else "(multi-lane mode)"
        print(f"active_lane: {al!r}  {mode}")
        print(f"active_lanes: [{', '.join(als)}]")
        return

    # ------------------------------------------------------------------ nix
    if action == "nix":
        # Parse the active_lanes line
        m = re.search(r"^active_lanes:\s*\[(.*?)\]\s*$", text, re.MULTILINE)
        if not m:
            print("error: active_lanes line not found in config.yaml", file=sys.stderr)
            sys.exit(1)
        current = [s.strip() for s in m.group(1).split(",") if s.strip()]
        if lane_name not in current:
            print(f"note: '{lane_name}' is not in active_lanes (no change).")
            print(f"active_lanes: [{', '.join(current)}]")
            return
        current.remove(lane_name)
        new_line = f"active_lanes: [{', '.join(current)}]"
        text = re.sub(r"^active_lanes:\s*\[.*?\]\s*$", new_line, text, flags=re.MULTILINE)
        config_path.write_text(text)
        print(f"nixed '{lane_name}' — active_lanes: [{', '.join(current)}]")
        return

    # ------------------------------------------------------------------ natch
    if action == "natch":
        m = re.search(r"^active_lanes:\s*\[(.*?)\]\s*$", text, re.MULTILINE)
        if not m:
            print("error: active_lanes line not found in config.yaml", file=sys.stderr)
            sys.exit(1)
        current = [s.strip() for s in m.group(1).split(",") if s.strip()]
        if lane_name in current:
            print(f"note: '{lane_name}' is already in active_lanes (no change).")
            print(f"active_lanes: [{', '.join(current)}]")
            return
        current.append(lane_name)
        new_line = f"active_lanes: [{', '.join(current)}]"
        text = re.sub(r"^active_lanes:\s*\[.*?\]\s*$", new_line, text, flags=re.MULTILINE)
        config_path.write_text(text)
        print(f"natched '{lane_name}' — active_lanes: [{', '.join(current)}]")
        return

    # ------------------------------------------------------------------ set
    if action == "set":
        lane_val = lane_name or ""
        new_active = f'active_lane: "{lane_val}"'
        if re.search(r"^active_lane:", text, re.MULTILINE):
            text = re.sub(r"^active_lane:\s*\".*?\"\s*$", new_active, text, flags=re.MULTILINE)
        else:
            print("error: active_lane line not found in config.yaml", file=sys.stderr)
            sys.exit(1)
        config_path.write_text(text)
        if lane_val:
            print(f"active_lane set to '{lane_val}' (single-lane mode)")
        else:
            print("active_lane unset (multi-lane mode)")
        return

    # ------------------------------------------------------------------ unset
    if action == "unset":
        text = re.sub(r"^active_lane:\s*\".*?\"\s*$", 'active_lane: ""', text, flags=re.MULTILINE)
        config_path.write_text(text)
        print("active_lane unset (multi-lane mode)")
        return

    print(f"error: unknown lanes action '{action}'", file=sys.stderr)
    sys.exit(1)


def _cmd_lanes(args: argparse.Namespace, log_path: Path) -> None:
    """Dispatch to _manage_lanes with args from the CLI."""
    from .config import REPO_ROOT
    action = getattr(args, "lanes_action", "list")
    lane_name = getattr(args, "lane", None)
    config_path = args.config if getattr(args, "config", None) else REPO_ROOT / "config.yaml"
    path = Path(config_path) if not isinstance(config_path, Path) else config_path
    if not path.exists():
        print(f"error: config file not found at {path}", file=sys.stderr)
        sys.exit(1)
    _manage_lanes(action, lane_name, path)


def _cmd_markets(args: argparse.Namespace, cfg: Config, log_path: Path) -> None:
    """list | show | probe | open | close — the Market-Readiness Gate."""
    from . import markets as mk

    action = getattr(args, "markets_action", "list") or "list"

    if action == "list":
        import sqlite3
        store = Store(cfg)
        counts_readable = True
        try:
            counts = store.markets_present()
        except (sqlite3.Error, OSError) as e:
            # Narrow: "a fresh install has no catalogue yet" is a missing/empty DB, not any
            # exception at all. `{}` prints a table of zero dossiers per market — a confident
            # number — so an unreadable catalogue now says so instead of reading as empty.
            logger.error(f"markets: catalogue unreadable, dossier counts unavailable: {e}",
                         extra={"error": str(e)})
            counts, counts_readable = {}, False
        if not counts_readable:
            print("warning: catalogue unreadable — dossier counts shown as '?', not 0",
                  file=sys.stderr)
        default = cfg.default_market
        print(f"{'code':<10}{'status':<10}{'dossiers':>9}  label")
        for code in sorted(c for c in (cfg.markets or {}) if c != "default"):
            block = cfg.market_config(code)
            flag = " (default)" if code == default else ""
            shown = counts.get(code, 0) if counts_readable else "?"
            print(f"{code:<10}{cfg.market_status(code):<10}{shown:>9}  "
                  f"{block.get('label', '')}{flag}")
        unknown = {m: n for m, n in counts.items() if m and m not in (cfg.markets or {})}
        if unknown:
            print(f"\nnot in config: {unknown}")
        if counts.get(""):
            print(f"\n{counts['']} dossier(s) predate the market dimension "
                  f"(market unset). See tools/backfill_market.py.")
        return

    market = getattr(args, "market", None) or cfg.default_market

    if action == "show":
        r = mk.load_readiness(cfg, market)
        if r is None:
            print(f"market {market!r}: status={cfg.market_status(market)}, "
                  f"no readiness probe recorded at {mk.readiness_path(cfg, market)}")
            return
        print(mk.format_readiness(r))
        current = mk.config_fingerprint(cfg, market)
        if current != r.config_fingerprint:
            print(f"\n  STALE: config has changed since this probe "
                  f"({r.config_fingerprint} → {current}). Re-probe before opening.")
        return

    if action == "probe":
        _run_market_probe(args, cfg, market, log_path)
        return

    if action == "open":
        r = mk.load_readiness(cfg, market)
        if r is None:
            print(f"error: cannot open {market!r} — no readiness probe at "
                  f"{mk.readiness_path(cfg, market)}. Run `markets probe` first.",
                  file=sys.stderr)
            sys.exit(2)
        if not r.ready:
            print(f"error: cannot open {market!r} — the probe says NOT READY:\n"
                  + "\n".join(f"  - {f}" for f in r.failures)
                  + "\n\nFix the evidence terrain (queries, authority domains, "
                    "calibration set). Do NOT lower the bar.", file=sys.stderr)
            sys.exit(2)
        current = mk.config_fingerprint(cfg, market)
        if current != r.config_fingerprint:
            print(f"error: cannot open {market!r} — the probe measured a different "
                  f"configuration ({r.config_fingerprint}, now {current}). Re-probe.",
                  file=sys.stderr)
            sys.exit(2)
        _set_market_status(args, market, "open")
        return

    if action == "close":
        _set_market_status(args, market, "closed")
        return

    print(f"error: unknown markets action {action!r}", file=sys.stderr)
    sys.exit(1)


def _set_market_status(args: argparse.Namespace, market: str, status: str) -> None:
    """Rewrite `status:` for one market in config.yaml, preserving comments."""
    import re

    from .config import REPO_ROOT

    path = Path(args.config) if getattr(args, "config", None) else REPO_ROOT / "config.yaml"
    text = path.read_text()
    # Match the market's own `status:` line: the key at 2-space indent inside `markets:`,
    # then its `status:` at 4-space indent. The body pattern only crosses lines that are
    # indented four or more (or blank), so it can never walk out of this market's block
    # and flip a SIBLING market's status — a market missing `status:` must fail loudly
    # below, not silently open the next market in the file.
    pattern = re.compile(
        rf"(^  {re.escape(market)}:\n(?:(?:[ \t]{{4,}}.*)?\n)*?    status:[ \t]*)(\S+)",
        re.MULTILINE)
    new_text, n = pattern.subn(rf"\g<1>{status}", text, count=1)
    if n != 1:
        print(f"error: could not find a `status:` line for market {market!r} in {path}. "
              f"Edit it by hand.", file=sys.stderr)
        sys.exit(1)
    path.write_text(new_text)
    print(f"market {market!r} is now {status} in {path}")


def _run_market_probe(args: argparse.Namespace, cfg: Config, market: str,
                      log_path: Path) -> None:
    """Run the calibration set through the real pipeline and record the measurement."""
    from . import markets as mk
    from . import progress
    from .operator import make_operator
    from .telemetry import reset_usage

    if not getattr(args, "set", None):
        print("error: --set PATH is required (a JSONL calibration set)", file=sys.stderr)
        sys.exit(2)
    entries = mk.load_calibration_set(args.set)

    # The probe is the ONE sanctioned way to run a closed market. Two containments keep
    # a calibration run from being mistaken for real output: publishing is refused, and
    # the dossiers land in an isolated store under the market's own probe directory
    # rather than the live catalogue. Without the second, a probe of a closed market
    # would write catalogue rows that the market_not_open alarm then flags as a breach.
    from dataclasses import replace as _replace

    args.probe = True
    # `real_cfg` keeps the live store dir so the READINESS artifact lands where the rest
    # of the engine looks for it; only the DOSSIER writes are diverted.
    real_cfg = _build_config_and_overrides(args).for_market(market)
    # Pack-shaped calibration ideas must be judged on the lane that matches them
    # (usually side_hustle). `--lane` already resolves gates via for_lane above; also
    # stamp ambition_tier on each candidate so dossiers/audit trail show the bar used,
    # and so any later for_lane(cand.ambition_tier) path cannot silently revert to the
    # venture default (which kills packs on incumbency — the wrong bar for £30 packs).
    lane = (getattr(args, "lane", None) or "").strip()
    probe_dir = Path(real_cfg.store_dir) / "markets" / market / "probe"
    probe_dir.mkdir(parents=True, exist_ok=True)
    probe_cfg = _replace(real_cfg, store={**real_cfg.store, "dir": str(probe_dir)})
    store = Store(probe_cfg)
    reset_usage()
    op = make_operator(probe_cfg)
    fast_op = make_operator(probe_cfg, fast=True)
    search = _make_search(probe_cfg, args)

    lane_note = f" lane={lane!r}" if lane else " (default lane — pack sets usually want --lane side_hustle)"
    print(f"Probing market {market!r} with {len(entries)} calibration candidate(s){lane_note}…")
    outcomes = []
    for entry in entries:
        # Entry-level ambition_tier/lane wins when present; else CLI --lane; else unset.
        entry_lane = (entry.get("ambition_tier") or entry.get("lane") or lane or "").strip()
        cand = Candidate(title=entry["title"], one_liner=entry.get("one_liner", ""),
                         why_now=entry.get("why_now", ""), market=market,
                         ambition_tier=entry_lane)
        progress.banner(f"[probe {market}] {cand.title!r}")
        vet_cfg = probe_cfg.for_lane(entry_lane) if entry_lane else probe_cfg
        d = vet_candidate(cand, op, search, vet_cfg, store=store, query_op=fast_op,
                          publish=False, show_checks=False)
        outcome = mk.outcome_from_dossier(entry["expected"], d)
        outcomes.append(outcome)
        print(f"  expected={outcome.expected:<5} actual={outcome.actual:<5} "
              f"grounded={outcome.grounded_checks}/{outcome.total_checks}  {cand.title[:44]}")

    # Fingerprint against the market-scoped config WITHOUT --lane applied.
    # `markets show|open` load config with no lane pin; hashing the lane-resolved
    # hard_gates/thresholds here made every successful `probe --lane side_hustle`
    # look STALE immediately. Outcomes still reflect the lane used for vetting.
    fp_cfg = load_config().for_market(market)
    readiness = mk.evaluate(fp_cfg, market, outcomes)
    path = mk.save_readiness(fp_cfg, readiness)
    print("\n" + mk.format_readiness(readiness))
    print(f"\nwritten: {path}")
    print(f"probe dossiers (not catalogue): {probe_dir}")
    if readiness.ready:
        print(f"\nThis market is ready. To open it:\n"
              f"  python -m prospector.run markets open --market {market}")
    else:
        print("\nNot ready. Improve the evidence terrain (authority domains, query "
              "exemplars in prompts/markets/<code>/), then re-probe. Never lower the bar.")


def _save_discovered_signals(signals: list[dict]) -> list[str]:
    """Persist discovered signals to signals/ as a re-runnable audit trail.

    Mirrors the spec's operator-pasted-signal convention (signals/, one per file):
    a discovered signal becomes a normal signal file the operator can re-vet or edit.
    """
    import re

    out_dir = "signals"
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.date.today().isoformat()
    paths: list[str] = []
    for s in signals:
        slug = re.sub(r"[^a-z0-9]+", "_", s.get("title", "").lower()).strip("_")[:50] or "signal"
        path = os.path.join(out_dir, f"discovered_{stamp}_{slug}.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(s["signal_text"].strip() + "\n")
        paths.append(path)
    return paths


def _cmd_discover(args: argparse.Namespace, log_path: Path) -> None:
    """Surface N diverse signals, then run the full pipeline on each (a sweep).

    NOTE: signal *discovery* is a deliberate extension BEYOND the original spec —
    the spec's model is operator-pasted signal files. This command lets the engine
    self-source a diverse, sector-spread portfolio of signals so generation ranges
    broadly instead of producing variations on one hand-written theme. It judges
    nothing; the same grounded moat downstream still vets and kills every candidate.
    """
    cfg = _build_config_and_overrides(args)

    from . import progress
    from .discover import discover_signals
    from .operator import make_operator

    op = make_operator(cfg)
    search = _make_search(cfg, args)
    store = Store(cfg)

    progress.banner(f"Signal discovery (spec extension): surfacing {args.signals} signal(s)")
    signals = discover_signals(op, cfg, n=args.signals,
                               sectors=getattr(args, "sectors", "") or "")
    if not signals:
        print("No signals discovered (model returned nothing usable).", file=sys.stderr)
        sys.exit(1)

    sectors = sorted({s.get("sector", "") for s in signals if s.get("sector")})
    progress.step(f"discovered {len(signals)} signal(s) across {len(sectors)} sector(s)")
    for s in signals:
        print(f"  • [{s.get('sector', '?')}] {s['title']}")

    if not getattr(args, "no_save", False):
        saved = _save_discovered_signals(signals)
        progress.note(f"saved {len(saved)} signal file(s) to signals/ (re-runnable audit trail)")

    if getattr(args, "dry_run", False):
        print("\n(dry-run) discovery only — no candidates generated or vetted.")
        return

    # --- Sweep: run the full grounded pipeline on each discovered signal ---
    all_dossiers: list[Dossier] = []
    board = _resolve_board(args)
    for i, s in enumerate(signals, start=1):
        progress.banner(f"[{i}/{len(signals)}] {s.get('sector', '?')}: {s['title']}")
        ds = run_signal(s["signal_text"], cfg=cfg, op=op, search=search, store=store,
                        k=getattr(args, "count", None),
                        publish=getattr(args, "publish", False),
                        lanes=_resolve_lanes(cfg, args),
                        board_personas=board)
        all_dossiers.extend(ds)

    # --- Cross-sweep summary ---
    n_pass = sum(1 for d in all_dossiers if d.decision == Decision.PASS)
    n_defer = sum(1 for d in all_dossiers if d.decision == Decision.DEFER)
    n_kill = len(all_dossiers) - n_pass - n_defer
    print(f"\n=== Discovery sweep complete: {len(signals)} signal(s) → "
          f"{len(all_dossiers)} candidate(s) vetted ===")
    print(f"    PASS={n_pass}  KILL={n_kill}  DEFER={n_defer}")
    for d in all_dossiers:
        if d.decision == Decision.PASS:
            comp = f"  composite={d.score.composite:.2f}" if d.score else ""
            print(f"  [PASS] {d.candidate.title}{comp}")
            print(f"         id={d.candidate.candidate_id}  "
                  f"(full dossier: store/dossiers/{d.candidate.candidate_id}.json)")
    if n_pass == 0:
        print("  (no PASS this sweep — per-signal verdicts in the catalogue / store/prospector.jsonl)")


def _load_dotenv() -> None:
    """Populate os.environ from env files, without adding a dependency (python-dotenv
    is not installed). Existing env vars ALWAYS WIN — a real shell (which sources
    ~/.config/llm/secrets.sh via ~/.zshrc) is authoritative; these files only fill gaps
    for non-shell launches (IDE run config, cron, a bare subprocess).

    Reads, in order (later files never override earlier or the live env):
      1. the gitignored repo-root .env        (project-specific overrides)
      2. ~/.config/llm/secrets.sh             (the canonical cross-tool key store)

    Both are simple KEY=VALUE; a leading `export ` is tolerated (so the SAME file can be
    sourced by zsh and parsed here — single source of truth). Blanks and #-comments are
    skipped; surrounding quotes stripped. Missing/malformed files are silently ignored.

    `PROSPECTOR_DISABLE_DOTENV` makes this a no-op, and it exists for exactly one reason.
    "Existing env vars always win" also means *absent* env vars always lose: a test fence
    that DELETES a credential from os.environ (tests/conftest.py
    `_no_live_payment_credentials`) leaves a gap, and this function's whole job is filling
    gaps. Proven by repro on 2026-08-07 — strip STRIPE_API_KEY and STRIPE_LIVE_API_KEY,
    call this once, and both come back from `.env`, live key included. The suite reaching
    real Stripe is the failure that fence was written for, so the fence has to cover the
    disk read too, not just the environment."""
    if os.environ.get("PROSPECTOR_DISABLE_DOTENV", "").strip() not in ("", "0", "false", "False"):
        return
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates = [
        os.path.join(repo_root, ".env"),
        os.path.expanduser("~/.config/llm/secrets.sh"),
    ]
    for path in candidates:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                lines = fh.readlines()
        except OSError:
            continue
        for raw in lines:
            line = raw.strip()
            if line.startswith("export "):
                line = line[len("export "):].strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val


def main() -> None:
    _load_dotenv()
    parser = argparse.ArgumentParser(
        prog="python -m prospector.run",
        description="Prospector opportunity vetting engine",
    )
    parser.add_argument("--config", metavar="PATH", help="Path to config.yaml")

    sub = parser.add_subparsers(dest="command", required=True)

    # ---- vet subcommand ----
    vet_p = sub.add_parser("vet", help="Vet a single candidate")
    # NOT `required=True`. `--resume` re-vets a backlog read from the store, so there is no
    # title to give — and argparse rejected the command before `_cmd_vet` (run.py:972) could
    # ever look at `args.resume`. RUN.md:97 has documented `python -m prospector.run vet
    # --resume` since the flag was added, and that exact command has never once run:
    #     python -m prospector.run vet --resume
    #     error: the following arguments are required: --title
    # It stayed invisible because the daemon's drain calls `resume_deferred()` in-process and
    # never touches this parser. Requiredness is enforced below instead, where it can be
    # conditional on the mode.
    vet_p.add_argument("--title", help="Opportunity title (required unless --resume)")
    vet_p.add_argument("--one-liner", dest="one_liner", default="",
                       help="One-liner description")
    vet_p.add_argument("--why-now", dest="why_now", default="",
                       help="Why this opportunity exists now")
    vet_p.add_argument("--operator", choices=["claude", "claude_cli", "minimax", "deepseek", "mock"],
                       help="Override operator from config")
    vet_p.add_argument("--lane", metavar="NAME",
                       help="Ambition lane to judge against (e.g. side_hustle, venture). "
                            "Default: config active_lane.")
    _add_market_args(vet_p)
    _add_archetype_arg(vet_p)
    vet_p.add_argument("--persona", metavar="NAME",
                       help="Analytical persona to 'tint' the run (e.g. shark, minimalist, academic). "
                            "Default: config active_persona.")
    vet_p.add_argument("--board", action="store_true",
                       help="Enable 'Advisory Board' mode: run multiple shadow personas (shark, minimalist, academic) "
                            "in parallel for deep critique.")
    vet_p.add_argument("--fixtures", metavar="PATH",
                       help="Path to fixtures JSON (uses FixtureProvider)")
    vet_p.add_argument("--publish", action="store_true",
                       help="Generate listing artifacts + publish on PASS (extra model calls)")
    vet_p.add_argument("--resume", action="store_true",
                       help="Re-vet all moat-deferred candidates (decision=defer).  "
                            "Uses the same operator/lane as the original run.  "
                            "Safe to re-run when the moat (Claude) comes back online.")
    vet_p.add_argument("--limit", type=int, metavar="N",
                       help="With --resume: re-vet only the N oldest deferred/provisional "
                            "candidates instead of the whole backlog. Default unbounded. "
                            "The daemon always passes a limit — the spend guard is evaluated "
                            "once per tick, so an unbounded drain would run inside a single "
                            "guard decision.")
    vet_p.add_argument("--only", choices=list(RESUME_SELECTORS), default="all",
                       help="With --resume: restrict the drain to one backlog population. "
                            "'provisional-pass' targets the only rows that can become "
                            "sellable inventory (a confirmed re-vet clears the "
                            "not-provisional publish gate); oldest-first ordering otherwise "
                            "buries them behind provisional KILLs and DEFERs. "
                            "Default 'all' = historical behaviour.")

    # ---- signal subcommand ----
    sig_p = sub.add_parser("signal", help="Run the full signal pipeline")
    sig_src = sig_p.add_mutually_exclusive_group(required=True)
    sig_src.add_argument("--text", metavar="TEXT", help="Signal text inline")
    sig_src.add_argument("--file", metavar="PATH", help="Path to signal text file")
    sig_p.add_argument("--operator", choices=["claude", "claude_cli", "minimax", "deepseek", "mock"],
                       help="Override operator from config")
    sig_p.add_argument("--count", type=int, default=None, metavar="N",
                       help="Number of candidates to generate (default: config candidates_per_signal)")
    sig_p.add_argument("--fixtures", metavar="PATH",
                       help="Path to fixtures JSON (uses FixtureProvider)")
    sig_p.add_argument("--publish", action="store_true",
                       help="Generate listing artifacts + publish PASSes (extra model calls)")
    sig_p.add_argument("--lane", metavar="NAME",
                       help="Ambition lane for generation + vetting (e.g. side_hustle, venture). "
                            "Default: config active_lane.")
    _add_market_args(sig_p)
    _add_archetype_arg(sig_p)
    sig_p.add_argument("--persona", metavar="NAME",
                       help="Analytical persona to 'tint' the run (e.g. shark, minimalist, academic). "
                            "Default: config active_persona.")
    sig_p.add_argument("--board", action="store_true",
                       help="Enable 'Advisory Board' mode: run multiple shadow personas (shark, minimalist, academic) "
                            "in parallel for deep critique.")
    sig_p.add_argument("--profile", metavar="NAME",
                       help="Generation profile: a reusable steering bundle (restricted forms + "
                            "focus directive) from config 'profiles' (e.g. online_autonomous_predator).")
    sig_p.add_argument("--focus", metavar="TEXT",
                       help="Free-text targeting constraint applied to THIS run's generation "
                            "(e.g. 'online only, fully automated, acute pain, makes money directly "
                            "online'). Overrides a profile's focus. Generation-only; never a gate.")

    # ---- generate subcommand (blue-sky: no signal) ----
    gen_p = sub.add_parser("generate", help="Blue-sky run: generate + vet candidates with no signal")
    gen_p.add_argument("--candidates", type=int, default=None, metavar="N",
                       help="Number of candidates to generate (default: config candidates_per_signal)")
    gen_p.add_argument("--exploration", type=float, default=None, metavar="X",
                       help="Override exploration level 0-1 (default: adaptive)")
    gen_p.add_argument("--operator", choices=["claude", "claude_cli", "minimax", "deepseek", "mock"],
                       help="Override operator from config")
    gen_p.add_argument("--fixtures", metavar="PATH",
                       help="Path to fixtures JSON (uses FixtureProvider)")
    gen_p.add_argument("--publish", action="store_true",
                       help="Generate listing artifacts + publish PASSes (extra model calls)")
    gen_p.add_argument("--no-vet", action="store_true", dest="no_vet",
                       help="PRODUCER MODE: generate, dedup, prescreen and select, then queue "
                            "every survivor as a DEFER row and exit without vetting any of "
                            "them. `vet --resume` is the consumer that drains the queue on "
                            "its own clock. Implies no publishing: a row with no verdict "
                            "cannot pass.")
    gen_p.add_argument("--lane", metavar="NAME",
                       help="Ambition lane for generation + vetting (e.g. side_hustle, venture). "
                            "Default: config active_lane.")
    _add_market_args(gen_p)
    _add_archetype_arg(gen_p)
    gen_p.add_argument("--persona", metavar="NAME",
                       help="Analytical persona to 'tint' the run (e.g. shark, minimalist, academic). "
                            "Default: config active_persona.")
    gen_p.add_argument("--profile", metavar="NAME",
                       help="Generation profile: a reusable steering bundle (restricted forms + "
                            "focus directive) from config 'profiles' (e.g. online_autonomous_predator).")
    gen_p.add_argument("--focus", metavar="TEXT",
                       help="Free-text targeting constraint applied to THIS run's generation "
                            "(e.g. 'online only, fully automated, acute pain, makes money directly "
                            "online'). Overrides a profile's focus. Generation-only; never a gate.")
    gen_p.add_argument("--resume", action="store_true",
                       help="Re-run generation for all pending signals that failed due to "
                            "generation chain exhaustion.  Reads signals from "
                            "signals/pending/ and re-runs the full pipeline (generate + vet). "
                            "Safe to re-run when the non-critical chain (DeepSeek/MiniMax) recovers.")

    # ---- replicate subcommand (Epic D: cross-market replication) ----
    rep_p = sub.add_parser(
        "replicate",
        help="Re-vet proven PASSes from one market as fresh candidates in another")
    rep_p.add_argument("--from", dest="source_market", required=True, metavar="CODE",
                       help="Source market to take PASS dossiers from (e.g. uk)")
    rep_p.add_argument("-n", type=int, default=None, metavar="N",
                       help="Max candidates to replicate (default: all)")
    rep_p.add_argument("--min-composite", dest="min_composite", type=float, default=None,
                       metavar="X", help="Only replicate PASSes scoring at or above X")
    rep_p.add_argument("--dry-run", dest="dry_run", action="store_true",
                       help="List what would be replicated; run no checks")
    rep_p.add_argument("--operator", choices=["claude", "claude_cli", "minimax", "deepseek", "mock"],
                       help="Override operator from config")
    rep_p.add_argument("--fixtures", metavar="PATH",
                       help="Path to fixtures JSON (uses FixtureProvider)")
    rep_p.add_argument("--publish", action="store_true",
                       help="Generate listing artifacts + publish on PASS")
    rep_p.add_argument("--lane", metavar="NAME", help="Ambition lane to judge against")
    rep_p.add_argument("--persona", metavar="NAME", help="Analytical persona")
    _add_market_args(rep_p)

    # ---- consume subcommand: the consumer half of the producer/consumer split ----
    con_p = sub.add_parser(
        "consume",
        help="Run the vetting CONSUMER: drain the queue continuously, on no deadline")
    con_p.add_argument("--batch", type=int, default=None, metavar="N",
                       help="Rows per drain pass before the rails are re-read "
                            "(default: config consumer.batch). Not a throughput limit — a "
                            "pass still runs retrieval.vet_workers rows in parallel.")
    con_p.add_argument("--publish", action="store_true",
                       help="Generate artifacts and publish PASSes as they are ruled")
    con_p.add_argument("--once", action="store_true",
                       help="Run exactly one drain pass and exit. The operator's dry run: "
                            "same code path, same rails, no loop.")
    con_p.add_argument("--max-passes", type=int, default=None, metavar="N", dest="max_passes",
                       help="Stop after N passes (default: never — this is a daemon)")

    # ---- discover subcommand (spec EXTENSION: self-sourced signals) ----
    disc_p = sub.add_parser("discover",
                            help="Self-source N diverse signals, then sweep the pipeline over each (beyond original spec)")
    disc_p.add_argument("--signals", type=int, default=10, metavar="N",
                        help="Number of diverse signals to surface (default 10)")
    disc_p.add_argument("--sectors", metavar="LIST",
                        help="Comma-separated sectors to spread across (default: built-in broad set)")
    disc_p.add_argument("--count", type=int, default=None, metavar="N",
                        help="Candidates to generate per signal (default: config candidates_per_signal)")
    disc_p.add_argument("--dry-run", dest="dry_run", action="store_true",
                        help="Only surface + save signals; do not generate or vet")
    disc_p.add_argument("--no-save", dest="no_save", action="store_true",
                        help="Do not write discovered signals to signals/")
    disc_p.add_argument("--operator", choices=["claude", "claude_cli", "minimax", "deepseek", "mock"],
                        help="Override operator from config")
    disc_p.add_argument("--lane", metavar="NAME",
                        help="Pin the sweep to a single ambition lane (default: multi-lane "
                             "across config active_lanes).")
    _add_market_args(disc_p)
    disc_p.add_argument("--persona", metavar="NAME",
                        help="Analytical persona to 'tint' the run (e.g. shark, minimalist, academic). "
                             "Default: config active_persona.")
    disc_p.add_argument("--fixtures", metavar="PATH",
                        help="Path to fixtures JSON (uses FixtureProvider)")
    disc_p.add_argument("--publish", action="store_true",
                        help="Generate listing artifacts + publish PASSes (extra model calls)")

    # ---- report subcommand ----
    rep_p = sub.add_parser("report", help="Read the catalogue, metrics, costs, generation quality, and trend (no model calls)")
    rep_view = rep_p.add_mutually_exclusive_group()
    rep_view.add_argument("--catalogue", action="store_true",
                          help="List vetted ideas grouped by decision + lane (default)")
    rep_view.add_argument("--metrics", action="store_true",
                          help="Truth-loop health: kill rate, per-lane breakdown, gate distribution")
    rep_view.add_argument("--costs", action="store_true",
                          help="Lifetime spend, tokens, slowest ops (errors excluded)")
    rep_view.add_argument("--generation-quality", dest="generation_quality", action="store_true",
                          help="Generation quality: form diversity, audience spread, prescreen rate")
    rep_view.add_argument("--trend", action="store_true",
                          help="Rolling 7/30/90d cohort trend: kill rate over time")
    rep_view.add_argument("--full", action="store_true",
                          help="All five views: catalogue + metrics + quality + trend + costs")
    rep_p.add_argument("--decision", choices=["pass", "kill", "defer"],
                       help="Filter the catalogue to one decision")

    # ---- diagnose subcommand ----
    diag_p = sub.add_parser("diagnose",
                            help="Calibration self-diagnostics (alarms; --deep runs the golden set)")
    diag_p.add_argument("--deep", action="store_true",
                        help="Run the golden set through the production brain chain (model calls)")
    diag_p.add_argument("--floor", type=float, default=0.75,
                        help="Min golden discrimination to count as OK (default 0.75)")

    # ---- operators subcommand ----
    op_p = sub.add_parser("operators",
                          help="Probe every operator: latency, health, circuit breakers, chain state")
    op_p.add_argument("--timeout", type=float, default=60.0,
                     help="Per-operator probe timeout in seconds (default: 60)")
    op_p.add_argument("--gen", action="store_true",
                     help="Also run a generation-prompt probe (tests full prompt size)")

    # ---- lanes subcommand ----
    lanes_p = sub.add_parser("lanes", help="Manage ambition lanes (list, nix, natch, set, unset)")
    lanes_act = lanes_p.add_subparsers(dest="lanes_action", required=True)

    lanes_act.add_parser("list", help="Show all defined lanes and active configuration")

    nix_p = lanes_act.add_parser("nix", help="Remove a lane from active_lanes")
    nix_p.add_argument("lane", help="Lane name to remove")

    natch_p = lanes_act.add_parser("natch", help="Add a lane to active_lanes")
    natch_p.add_argument("lane", help="Lane name to add")

    set_p = lanes_act.add_parser("set", help="Set active_lane (single-lane pin; empty = unset / multi-lane)")
    set_p.add_argument("lane", nargs="?", default="", help="Lane name (omit or empty to unset)")

    lanes_act.add_parser("unset", help="Clear active_lane (return to multi-lane mode)")

    # ---- markets subcommand (Epic D: the Market-Readiness Gate) ----
    markets_p = sub.add_parser(
        "markets", help="Manage jurisdictions (list, show, probe, open, close)")
    markets_act = markets_p.add_subparsers(dest="markets_action", required=True)

    markets_act.add_parser("list", help="Show defined markets, status and dossier counts")

    show_p = markets_act.add_parser("show", help="Show a market's readiness measurement")
    show_p.add_argument("--market", metavar="CODE", required=True)

    probe_p = markets_act.add_parser(
        "probe", help="Run the calibration set through the real pipeline and measure")
    probe_p.add_argument("--market", metavar="CODE", required=True)
    probe_p.add_argument("--set", metavar="PATH", required=True,
                         help="JSONL calibration set: one "
                              '{"title","one_liner","expected":"pass|kill"} per line')
    probe_p.add_argument("--operator", choices=["claude", "claude_cli", "minimax", "deepseek", "mock"])
    probe_p.add_argument("--fixtures", metavar="PATH",
                         help="Path to fixtures JSON (offline probe)")
    probe_p.add_argument("--lane", metavar="NAME")

    open_p = markets_act.add_parser(
        "open", help="Open a market — refused unless a current probe says READY")
    open_p.add_argument("--market", metavar="CODE", required=True)

    close_p = markets_act.add_parser("close", help="Close a market")
    close_p.add_argument("--market", metavar="CODE", required=True)

    args = parser.parse_args()

    # Keep the verbose JSON audit log out of the way (it goes to a tail-able file);
    # the console shows the human progress stream. PROSPECTOR_JSON_LOG=stderr opts out.
    cfg_for_log = load_config(args.config if args.config else None)
    from .telemetry import route_logs_to_file
    log_path = cfg_for_log.store_dir / "prospector.jsonl"
    route_logs_to_file(str(log_path))
    from . import progress
    progress.note(f"audit log → {log_path}")

    # THE KILL SWITCH APPLIES TO THIS PROCESS TOO. Until 2026-08-13 `PAUSE` was read only by
    # `scheduler/run_scheduled.py` — `rg -c PAUSE prospector/run.py` returned 0 — so the
    # documented way to stop the engine ("touch store/scheduler/PAUSE") stopped the daemon and
    # nothing else. A manual `generate` / `vet` / `signal` spends from the same rails, writes
    # the same dossiers and grows the same backlog, so a switch that misses them is a switch
    # that does not stop the engine.
    #
    # Only the model-calling, store-mutating commands are gated. `report` / `diagnose` /
    # `operators` / `lanes` / `markets` are how an operator finds out WHY it is paused, and a
    # kill switch that blinds you while it holds is worse than none.
    if args.command in {"vet", "signal", "generate", "discover", "replicate"}:
        from .scheduler.guard import pause_block_reason
        _paused = pause_block_reason(cfg_for_log)
        if _paused:
            print(f"Refusing: {_paused}", file=sys.stderr)
            sys.exit(3)

    if args.command == "vet":
        # Conditional requiredness — see the `--title` declaration for why argparse cannot
        # carry it. A single-candidate vet with no title is still a usage error, and it must
        # still exit 2 so scripts that check the code keep working.
        if not getattr(args, "resume", False) and not getattr(args, "title", None):
            print("Error: vet requires --title (or --resume to drain the backlog).",
                  file=sys.stderr)
            sys.exit(2)
        _cmd_vet(args, log_path)
    elif args.command == "signal":
        _cmd_signal(args, log_path)
    elif args.command == "generate":
        _cmd_generate(args, log_path)
    elif args.command == "consume":
        _cmd_consume(args)
    elif args.command == "discover":
        _cmd_discover(args, log_path)
    elif args.command == "report":
        _cmd_report(args, cfg_for_log, log_path)
    elif args.command == "diagnose":
        _cmd_diagnose(args, cfg_for_log, log_path)
    elif args.command == "operators":
        _cmd_operators(args)
    elif args.command == "lanes":
        _cmd_lanes(args, log_path)
    elif args.command == "markets":
        _cmd_markets(args, cfg_for_log, log_path)
    elif args.command == "replicate":
        _cmd_replicate(args, log_path)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
