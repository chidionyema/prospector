# Platform — progress notes

Founder, 2026-08-19: **"ry to unblock yourself, keep notes onn progress"** and **"and get it
done"**. This is that log. One accountable owner for the whole platform (§1a of
`PLATFORM_PORTABILITY_AUDIT.md`), so this file is where the state of play lives between sessions.

**Rules for this file.** Newest first. Every entry says what was measured or changed and carries
the evidence. No entry claims a thing works without the command that showed it. When a claim here
is disproved, the entry is corrected in place with a note — never quietly deleted.

---

## 2026-08-19

**Done**

- **Backup grading shipped.** `ops/automations/offsite_backup.py` now grades the newest object
  under `ledger/`, `db/` and `repo/` instead of trusting the writer's exit code. 10 new tests,
  suite `40 passed`. Commit `7d905dd7`. Closes the class where an exit code proved the job ran but
  not that bytes landed.
- **Deep audit written.** `docs/PLATFORM_PORTABILITY_AUDIT.md` — 10 findings, all measured, all
  dated, with every option laid out before any decision, per *"i need justifications alo outputted
  before final decsion"* and *"ssorry i need tosee all solutions proposed"*.

**Measured this session**

| Fact | Value |
|---|---|
| Hand-maintained ops artifacts | 199 |
| Bespoke ops code | 16,637 lines |
| …of which works around CI | **6,505 lines / 16 files / 39%** |
| `main` CI concluded green, 48h | 23 of 42 = **55%** |
| Reproducible-env files at repo root | **0 of 13** |
| launchd plists installed vs tracked | **36 vs 30** — 6 untracked |
| Log aggregation configured | **none, anywhere** |
| `~/.hermes/logs` | 71 MB, 2,013 files, backed up nowhere |
| Secret stores | 4+ |
| Staging environments | **0** |
| Failing laptop jobs nobody was told about | `backup` exit 78, `process-audit` exit 2 |

**The thesis the numbers produced.** Three separate incidents this estate has already had —
`web_calls=0` (2026-06-24), launchd exits nobody reads, backups graded by exit code — are one
class: **a signal was emitted and nothing consumed it.** Now `PLATFORM_MANIFESTO.md` L12.

**Open, in priority order**

1. **F9 observability** — no central log view. Hard blocker on the bar itself: a cutover nobody can
   watch cannot be proved. Founder assigned it here explicitly.
2. **F4 the six untracked launchd jobs** — identify them. An estate you have not finished listing
   cannot be migrated.
3. **F1 staging** — precondition for every drill; a drill against production is not a drill.
4. **State replication (7f Litestream)** — what makes cutover a switch instead of a copy.
5. Push `7d905dd7`; follow PR #445 to merged.

**Blocked on the founder, not on me** (§10 of the audit): custody of the age key; the GitHub plan
tier, which is the cheapest item in the audit and deletes four of the sixteen guards.

**Not touching:** the pipeline, per *"forget the pipipeline for now"* — owned here now, but not
worked this turn. The `tie-*` Fly apps. `verify.mjs`.
