"""Automated safety backstop for the always-on generation daemon.

The daemon runs unattended (founder decision, 2026-06-20), so these two automated rails REPLACE
human supervision; neither is optional:

  1. A hard **daily spend ceiling** (config `spend.daily_cap_usd`). Computed from the persistent
     audit ledger `store/prospector.jsonl`, summing today's `spend` events. When today's spend is
     at or above the cap, no new batch starts until the calendar day rolls over.
  2. A filesystem **kill switch**: the presence of `store/scheduler/PAUSE` halts all batches. The
     daemon keeps looping and re-checking, so `rm`-ing the file resumes it with no restart.

Why the ledger and not in-process telemetry: the daemon (and any per-tick subprocess) may be a
fresh process whose in-process counter is ~0, which would make the cap never fire. Reading the
on-disk ledger is correct across restarts. The ledger only accrues spend if generation routes its
telemetry there — `run_scheduled` calls `route_logs_to_file(<store>/prospector.jsonl)` to ensure
exactly that.

The ceiling is a pre-run check, so a single in-flight batch can overshoot by at most one batch's
worth of spend — bounded by `schedule.batch_size`. That is the intended, acceptable slack.

WHAT `daily_cap_usd` DOES AND DOES NOT COVER (measured 2026-08-05)
-----------------------------------------------------------------
It counts ONLY ledger rows tagged `event: "spend"`. Those are emitted by `telemetry.py:225`,
and only when the provider has a non-zero entry in the pricing table — i.e. metered API
providers billed in real dollars (minimax, deepseek).

The Claude Code CLI is not one of them. `claude_cli.py:_record_claude_usage` logs the CLI's own
billed figure under `cost_usd` on a row with **no `event` key at all**, so the loop below skips
every one. On 2026-08-05 that gap was:

    event=="spend" rows (what the rail sees) : $1.6400   (370 rows, all minimax)
    "Claude CLI usage" rows (invisible)      : $71.9393  (315 rows)

so the rail bounded 2% of the day's model consumption and the probe printed "$1.64 of $20.00".

That is NOT a broken liability rail: CLI usage runs inside the Claude Code subscription
(CLAUDE.md: "no hosted service / no API-key calls beyond this repo"), so `cost_usd` there is an
API-equivalent estimate, not billed money. Folding it into `daily_cap_usd` would halt the daemon
within about two hours of every day for spend that is never invoiced.

What was actually wrong is that a number covering 2% of consumption was reported as if it
covered all of it. So the guard now measures BOTH and reports both, and the subscription leg gets
its own OPTIONAL ceiling (`spend.daily_subscription_cap_usd`, default 0 = disabled). Arming it is
a deliberate config act about the Max plan's usage allowance — the thing CLAUDE.md means by "run
bounded batches inside the usage allowance" — not a silent change to what is legal today.

CALENDAR DAY IS LOCAL, NOT UTC. `date.today()` is local and ledger timestamps are local asctime,
so the two agree — but the day rolls at local midnight. On 2026-08-05 this read as a bug: the
spend figure fell $1.64 -> $0.13 at 23:00 UTC, which looked like a daemon restart resetting the
counter (a restart would defeat the rail entirely). It was the local day rolling over, one hour
before the UTC day. `day_str` is reported on the decision so the figure is never read against the
wrong calendar again.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from prospector.scheduler import paths

PAUSE_FILENAME = "PAUSE"

#: Incremental-scan checkpoint for `SchedulerGuard._scan`, written beside the PAUSE switch.
#: See `_scan` for why re-reading the whole ledger every tick stopped being viable.
SCAN_CACHE_FILENAME = "spend_scan.cache.json"

#: Bump when the cached shape changes; a mismatch forces a full re-scan rather than a wrong sum.
_SCAN_CACHE_VERSION = 1

#: How many calendar days of per-day totals the checkpoint retains. Only today's bucket is ever
#: queried; the rest are kept so a day boundary crossed mid-file needs no re-scan.
_SCAN_CACHE_DAYS = 30

#: Bytes of the ledger head that identify the file. If these change, the ledger was rotated or
#: rewritten and every cached byte offset is meaningless — reset and re-scan from zero.
_HEAD_PROBE_BYTES = 4096

#: Escape hatch: set to 1 to bypass the checkpoint entirely and re-read the whole ledger. This is
#: a money rail, so there is always a way to get the uncached figure without editing code.
_FULL_SCAN_ENV = "PROSPECTOR_GUARD_FULL_SCAN"

#: A ledger timestamp whose leading 10 chars are a zero-padded ISO date. Anchored, so a row with
#: a free-text timestamp contributes nothing to the clock bound rather than a garbage maximum.
_DAY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


@dataclass(frozen=True)
class GuardDecision:
    can_run: bool
    reason: str
    today_spend_usd: float
    daily_cap_usd: float
    paused: bool
    # Subscription-equivalent burn (Claude Code CLI `total_cost_usd`) for the same local day.
    # Reported always; enforced only when `daily_subscription_cap_usd` is > 0.
    today_subscription_usd: float = 0.0
    daily_subscription_cap_usd: float = 0.0
    # The local calendar day both figures were summed over. Present so a reader never has to
    # guess whether a figure is UTC-day or local-day (that guess cost a wrong verdict once).
    day: str = ""
    # Ledger lines for `day` that could not be parsed. Every one of them may have been a spend
    # row, so `today_spend_usd` is a LOWER BOUND whenever this is > 0 and the cap has that much
    # less room than it appears to. Measured 2026-08-21 20:30 on ledger/prospector-2026-08-21
    # .jsonl.gz in R2: 1,503,024 records, 54 unparseable, 48 of them runs of NUL bytes, 94,453
    # NUL bytes in total. The first is at 2026-08-18 08:47:09Z and the last at 18:57:05Z, one
    # minute after the v90 cutover SIGKILLed a process still running the un-fsynced code. Until
    # 2026-08-18 this counter would have read 0 for the file's whole history, which is why
    # nobody had one.
    today_ledger_holes: int = 0


class SchedulerGuard:
    """Decides whether the daemon may start another generation batch right now."""

    def __init__(self, store_dir: str | Path, daily_cap_usd: float, *, today: str | None = None,
                 daily_subscription_cap_usd: float = 0.0):
        self.store_dir = Path(store_dir)
        self.daily_cap_usd = float(daily_cap_usd)
        self.daily_subscription_cap_usd = float(daily_subscription_cap_usd or 0.0)
        self._today_override = today  # 'YYYY-MM-DD' injection point for tests
        # The per-day accumulator `_scan` already builds, kept instead of discarded so that a
        # caller wanting spend over a WINDOW does not have to parse the ledger a second time.
        # See `spend_by_day`.
        self._days: dict[str, list[float]] = {}
        self._holes: dict[str, int] = {}
        self._holes_this_pass = 0

    @property
    def scheduler_dir(self) -> Path:
        return self.store_dir / "scheduler"

    @property
    def pause_file(self) -> Path:
        return self.scheduler_dir / PAUSE_FILENAME

    @property
    def ledger_path(self) -> Path:
        return self.store_dir / "prospector.jsonl"

    def _today_str(self) -> str:
        return self._today_override or _dt.date.today().isoformat()

    def is_paused(self) -> bool:
        return self.pause_file.exists()

    def scan_today(self) -> tuple[float, float]:
        """Today's (metered_usd, subscription_usd). See `_scan` — this drops the clock signal."""
        metered, subscription, _ = self._scan()
        return metered, subscription

    def spend_by_day(self) -> dict[str, tuple[float, float]]:
        """Every day this scan covers, as {'YYYY-MM-DD': (metered_usd, subscription_usd)}.

        WHY THIS IS A METHOD ON THE GUARD and not arithmetic in the caller: memory
        `never-hand-parse-the-spend-ledger`. A hand-rolled sum over `store/prospector.jsonl`
        returns a confident **$0.00 on a day with real spend**, because the rows are keyed
        `timestamp` (not `date`) and the metered leg is `event: "spend"` + `amount_usd` — a
        wrong key matches nothing, raises nothing, and fails in the safe-LOOKING direction.
        Anything reporting spend over a WINDOW rather than today (a batch receipt, a weekly
        $/vetted) had no reader and would have written that second parse. `_scan` already
        accumulates this exact mapping in the single pass it makes for the cap, so this hands
        it back rather than throwing it away and there is still only ONE parser in the repo.

        BOTH LEGS, ALWAYS, and callers must print both: `metered` is billed money and is what
        `daily_cap_usd` enforces; `subscription` is Claude Code CLI burn (`cost_usd`, no `event`
        key), API-equivalent and not invoiced. They differ by orders of magnitude — $2.71 vs
        $340 on 2026-08-06 — so reporting metered alone reads as total consumption.

        HORIZON, which a caller MUST state rather than assume: the incremental scan resumes from
        a checkpoint that keeps only the newest `_SCAN_CACHE_DAYS` (30) days, so days older than
        that are absent after a resume even though the ledger still holds their rows. Absent is
        not zero. For a full history set `PROSPECTOR_GUARD_FULL_SCAN=1`, which forces the
        uncached pass over the whole file (measured 108s on the 157 MB ledger).
        """
        if not self.ledger_path.exists():
            return {}
        self._scan()
        return {day: (round(v[0], 6), round(v[1], 6)) for day, v in self._days.items()}

    @property
    def scan_cache_path(self) -> Path:
        return self.scheduler_dir / SCAN_CACHE_FILENAME

    @staticmethod
    def _head_sig(p: Path) -> str:
        """Identity of the ledger's first bytes — changes iff the file was rotated/rewritten."""
        try:
            with p.open("rb") as f:
                return hashlib.sha1(f.read(_HEAD_PROBE_BYTES), usedforsecurity=False).hexdigest()
        except OSError:
            return ""

    def _load_scan_cache(self, p: Path, head_sig: str) -> tuple[int, str, dict, dict]:
        """Return (offset, newest, days, holes) to resume from, or empties for a full re-scan.

        `holes` is deliberately NOT part of the version gate. It was added on 2026-08-21 to a
        cache format already in production, and bumping `_SCAN_CACHE_VERSION` to carry it would
        have rejected every live checkpoint and forced one full re-scan. That scan is the exact
        thing this cache exists to prevent: 71 s at 158 MB when it was written, against
        `prospector-run.sh`'s 110 s timeout, and the ledger is 456 MB today. So a cache written
        before this change loads with no holes recorded and keeps its offset, and a cache
        written after it is still read by code that predates it.

        Every rejection path is a full re-scan, never a partial sum: a checkpoint that cannot be
        proven to describe THIS file is worth less than the seconds it saves, because the figure
        it feeds is a spend ceiling.
        """
        if os.environ.get(_FULL_SCAN_ENV) == "1":
            return 0, "", {}, {}
        try:
            raw = json.loads(self.scan_cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return 0, "", {}, {}
        if not isinstance(raw, dict) or raw.get("version") != _SCAN_CACHE_VERSION:
            return 0, "", {}, {}
        if raw.get("head_sig") != head_sig or not head_sig:
            return 0, "", {}, {}      # rotated, rewritten, or unreadable head
        try:
            offset = int(raw.get("offset", 0))
            size = p.stat().st_size
        except (TypeError, ValueError, OSError):
            return 0, "", {}, {}
        if offset < 0 or offset > size:
            return 0, "", {}, {}      # truncated behind us
        days_raw = raw.get("days")
        newest = raw.get("newest")
        if not isinstance(days_raw, dict) or not isinstance(newest, str):
            return 0, "", {}, {}
        days: dict[str, list[float]] = {}
        for k, v in days_raw.items():
            try:
                days[str(k)] = [float(v[0]), float(v[1])]
            except (TypeError, ValueError, IndexError, KeyError):
                return 0, "", {}, {}
        holes: dict[str, int] = {}
        for k, v in (raw.get("holes") or {}).items():
            # A malformed holes map costs the count, never the offset. Rejecting the whole
            # checkpoint here would trade a 456 MB re-scan for a number that is only a warning.
            try:
                holes[str(k)] = int(v)
            except (TypeError, ValueError):
                continue
        return offset, newest, days, holes

    def _save_scan_cache(self, *, offset: int, newest: str, days: dict, head_sig: str,
                         holes: dict | None = None) -> None:
        """Persist the checkpoint. Best-effort: a failure costs speed, never correctness."""
        if os.environ.get(_FULL_SCAN_ENV) == "1" or not head_sig:
            return
        kept = dict(sorted(days.items(), reverse=True)[:_SCAN_CACHE_DAYS])
        payload = {"version": _SCAN_CACHE_VERSION, "head_sig": head_sig,
                   "offset": int(offset), "newest": newest, "days": kept}
        if holes:
            # Same 30-day window as `days`, so the checkpoint cannot grow without bound.
            payload["holes"] = {k: v for k, v in sorted(holes.items(), reverse=True)[:_SCAN_CACHE_DAYS]}
        path = self.scan_cache_path
        tmp = path.with_suffix(path.suffix + f".tmp{os.getpid()}")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            # Whole-file state, so tmp+rename is correct here (unlike the append-only tick log):
            # a racing writer can only replace it with another self-consistent snapshot.
            os.replace(tmp, path)
        except OSError:
            try:
                tmp.unlink()
            except OSError:
                pass

    def _scan(self) -> tuple[float, float, str]:
        """Return (metered_usd, subscription_usd, newest_day_in_ledger) from the persistent ledger.

        INCREMENTAL SINCE 2026-08-10. The pass below is identical in arithmetic to the full-file
        loop it replaces, but it resumes from a byte offset checkpointed in `spend_scan.cache.json`
        instead of re-parsing the whole ledger on every tick. The full scan had become the reason
        the hourly cron guard probe failed: measured on this machine, `store/prospector.jsonl` is
        158 MB / 560,057 rows, `json.loads` was called 560,017 times per probe, and one
        `--dry-run` guard eval took 71 s against `prospector-run.sh`'s 110 s `timeout` — so the
        job died with rc=124 and "prospector: guard probe timed out after 110s" as soon as load or
        ledger growth pushed it over. Cost per tick is now O(rows appended since last tick).

        Correctness is preserved by construction, not by assumption:
          * per-day buckets, not a today-only sum, so a day boundary crossed between ticks needs
            no re-scan and the answer does not depend on WHEN the checkpoint was taken;
          * `newest` is still a max over every row ever scanned (cached max ∨ new rows), never the
            last row — the clock-fault gate this feeds must survive out-of-order timestamps;
          * a row without a terminating newline is a partially-written append: it is not counted
            and the offset does not advance past it, so it is counted exactly once when complete;
          * any doubt about the checkpoint's provenance (version bump, ledger rotated, file
            truncated behind the offset, unparseable cache) falls back to a full re-scan.
        Set PROSPECTOR_GUARD_FULL_SCAN=1 to force the uncached figure.

        One pass, two accumulators, because both figures are read on every tick:

          * metered      — rows tagged `event: "spend"`, summing `amount_usd`. Real billed money
                           from metered API providers. This is what `daily_cap_usd` enforces.
          * subscription — rows carrying `cost_usd` and NO `event` key: the Claude Code CLI's own
                           `total_cost_usd` (claude_cli.py:82). API-equivalent, not invoiced.

        The `event` test is what separates them, and it is deliberately exclusive: a future
        provider that emits both keys on one row must not be double-counted.

        Unparseable lines are skipped AND COUNTED, per day, into `holes`. That sentence used to
        end at "are skipped" and read as robustness, which it was while the only unparseable line
        was a half-written last append. It stopped being true on 2026-08-18 08:47:09: the engine
        began taking SIGKILL five seconds into shutdown, so `flush()`-only writes died in the page
        cache and the filesystem returned the recorded length as NUL bytes. 50 such runs are in
        the R2 snapshot of the live ledger. Every one may have hidden a spend row, so a skip is
        under-counted money, and money that is not counted is cap room that does not exist.
        The count does not repair the sum. It stops the loss being invisible to whoever reads the
        cap. `prospector/telemetry.py` (DurableFileHandler) is what stops new holes appearing.

        Timestamps are matched by their `YYYY-MM-DD` date prefix, which holds for ISO and asctime.

        The third value is the newest day any ledger row claims, folded into this same pass
        because the file is ~350k lines and is already read on every tick. It is NOT read from
        the last line: the ledger is appended in wall-clock order, so under the very clock fault
        it exists to detect, the last row is the OLDEST. Only a full max is correct.
        """
        p = self.ledger_path
        if not p.exists():
            return 0.0, 0.0, ""
        day = self._today_str()
        head_sig = self._head_sig(p)
        offset, newest, days, holes = self._load_scan_cache(p, head_sig)
        holes_before = sum(holes.values())
        try:
            with p.open("rb") as f:
                f.seek(offset)
                for raw in f:
                    if not raw.endswith(b"\n"):
                        break  # partial append in flight — count it when it is complete
                    offset += len(raw)
                    line = raw.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except Exception:
                        # `newest` and not `day`: attribute the hole to the newest day the ledger
                        # has actually shown us, because a torn line carries no readable timestamp
                        # of its own. On an empty cache that is "", so fall back to today rather
                        # than lose the count to a key no reader will look up.
                        key = newest or day
                        holes[key] = holes.get(key, 0) + 1
                        continue
                    if not isinstance(d, dict):
                        continue
                    ts = str(d.get("timestamp") or d.get("asctime") or "")
                    if not _DAY_RE.match(ts):
                        # No zero-padded ISO date prefix: it can bound neither the clock nor a
                        # calendar day, exactly as before.
                        continue
                    # String max is a date max only because the prefix is zero-padded ISO.
                    row_day = ts[:10]
                    newest = max(newest, row_day)
                    if d.get("event") == "spend":
                        try:
                            amount = float(d.get("amount_usd", 0) or 0)
                        except (TypeError, ValueError):
                            continue
                        idx = 0
                    elif d.get("cost_usd") is not None:
                        try:
                            amount = float(d.get("cost_usd") or 0)
                        except (TypeError, ValueError):
                            continue
                        idx = 1
                    else:
                        continue
                    bucket = days.setdefault(row_day, [0.0, 0.0])
                    bucket[idx] += amount
        except OSError:
            return 0.0, 0.0, ""
        self._save_scan_cache(offset=offset, newest=newest, days=days, head_sig=head_sig,
                              holes=holes)
        self._days = days
        self._holes = holes
        self._holes_this_pass = sum(holes.values()) - holes_before
        metered, subscription = days.get(day, (0.0, 0.0))
        return round(metered, 6), round(subscription, 6), newest

    def today_spend_usd(self) -> float:
        """Today's metered (billed) spend — the figure `daily_cap_usd` enforces."""
        return self.scan_today()[0]

    def today_subscription_usd(self) -> float:
        """Today's subscription-equivalent burn — reported always, capped only if configured."""
        return self.scan_today()[1]

    def evaluate(self) -> GuardDecision:
        paused = self.is_paused()
        spend, subscription, newest = self._scan()
        sub_cap = self.daily_subscription_cap_usd
        today = self._today_str()

        def _decide(can_run: bool, reason: str, paused: bool = False) -> GuardDecision:
            return GuardDecision(
                can_run=can_run,
                reason=reason,
                today_spend_usd=spend,
                daily_cap_usd=self.daily_cap_usd,
                paused=paused,
                today_subscription_usd=subscription,
                daily_subscription_cap_usd=sub_cap,
                day=self._today_str(),
                today_ledger_holes=self._holes.get(today, 0),
            )

        if paused:
            return _decide(False, f"paused: {self.pause_file} present", paused=True)
        if newest and today < newest:
            # The clock has gone BACKWARDS past an event this machine already recorded, so the
            # cap is summing a day the ledger cannot have rows for and reads $0.00 no matter
            # what was really spent. That is not a degraded cap, it is no cap: measured on the
            # live ledger, today=2026-08-06 gives $1.1680 and today=1970-01-01 gives $0.0000
            # with can_run=True. CLAUDE.md makes the daily cap one of the two automated rails
            # that stand in for a human, and forbids unattended generation without them — so
            # the honest answer when the rail cannot function is to stop, not to spend.
            #
            # This has happened: store/scheduler/ticks.jsonl carries 110 ticks spanning
            # 1970-01-01..03, all reporting "$0.0000 of $20.00 spent today".
            #
            # Only backwards skew is detectable from local state. A clock set FORWARD zeroes the
            # window just as effectively, and nothing on this machine can refute it — the ledger
            # bounds "now" from below only. Fixing that needs a trusted time source; this gate
            # deliberately does not pretend to cover it.
            return _decide(
                False,
                f"clock is behind the ledger: today reads {today} but this store already has "
                f"rows dated {newest}. The daily cap sums by calendar day, so it would report "
                f"$0.00 spent and enforce nothing. Fix the system clock (or pass today=) before "
                f"generating.")
        if spend >= self.daily_cap_usd:
            return _decide(
                False, f"daily cap reached: ${spend:.4f} >= ${self.daily_cap_usd:.2f}")
        if sub_cap > 0 and subscription >= sub_cap:
            # Only reachable when the operator armed it. Named distinctly from the metered cap
            # so a halt is never misread as "we spent real money".
            return _decide(
                False,
                f"daily subscription cap reached: ${subscription:.4f} >= ${sub_cap:.2f} "
                f"(subscription-equivalent, not billed)")
        # Both legs in one line. The metered figure alone read as total consumption for weeks.
        return _decide(
            True,
            f"ok: ${spend:.4f} of ${self.daily_cap_usd:.2f} spent today "
            f"(+${subscription:.4f} subscription-equivalent"
            f"{f' of ${sub_cap:.2f}' if sub_cap > 0 else ', uncapped'})")


def _store_dir(cfg) -> Path:
    # Delegates so the "which store?" answer has ONE definition. It used to default to the
    # relative literal "store", which resolves against the cwd — see prospector/scheduler/
    # paths.py for the 110 fabricated rows that put in the live tick log.
    return paths.store_dir(cfg)


def _daily_cap(cfg) -> float:
    spend = getattr(cfg, "spend", None)
    return float(getattr(spend, "daily_cap_usd", 0.0) or 0.0)


def _daily_subscription_cap(cfg) -> float:
    spend = getattr(cfg, "spend", None)
    return float(getattr(spend, "daily_subscription_cap_usd", 0.0) or 0.0)


def guard_from_config(cfg, *, today: str | None = None) -> SchedulerGuard:
    return SchedulerGuard(_store_dir(cfg), _daily_cap(cfg), today=today,
                          daily_subscription_cap_usd=_daily_subscription_cap(cfg))


def guard_check(cfg) -> tuple[bool, str]:
    """Compatibility wrapper: (allowed, reason) for callers that don't need the full decision.

    A non-positive `daily_cap_usd` means "no cap configured" — the spend rail is then disabled and
    only the PAUSE kill switch applies. Configure `spend.daily_cap_usd` to arm the ceiling.
    """
    guard = guard_from_config(cfg)
    if guard.is_paused():
        return False, f"paused: {guard.pause_file} present"
    if guard.daily_cap_usd <= 0:
        return True, "no daily cap configured (spend rail disabled; PAUSE switch still applies)"
    decision = guard.evaluate()
    return decision.can_run, decision.reason


def pause_block_reason(cfg) -> str | None:
    """The kill switch alone, for callers that are not the daemon. `None` == not paused.

    WHY NOT `guard_check`: it also evaluates the daily ceiling, which re-scans
    `store/prospector.jsonl`. That ledger reached 157 MB and `evaluate()` measured 108s on
    it — a preflight that slow in front of every manual command would be removed by the
    first person it inconvenienced, and a rail nobody keeps is not a rail. The kill switch
    is a single `stat`, so it can sit in front of everything unconditionally.

    WHY NO OVERRIDE FLAG: CLAUDE.md — "PAUSE is the liability rail: it halts the ENTIRE
    tick, generation and re-vet drain together, because a rail with exceptions is not a
    rail." The half-stops that deliberately leave the drain running are separate files
    (`PAUSE_GENERATION`, and the automatic backlog brake), not a flag on this one.
    """
    guard = guard_from_config(cfg)
    if not guard.is_paused():
        return None
    return (f"PAUSED — {guard.pause_file} is present, so this command will not run.\n"
            f"        The kill switch halts manual runs as well as the daemon: a batch "
            f"started by hand spends from the same rails and writes to the same store.\n"
            f"        Resume with:  rm {guard.pause_file}")
