# pi extension audit + the Claude-Code-×-MiniMax workflow — 2026-08-05

Every claim below is backed by a command run on this machine today. Where I could not
prove something, it says so. Two of my own intermediate conclusions were wrong and are
corrected inline — they are kept because the *reason* they were wrong is the lesson.

`pi` = `@earendil-works/pi-coding-agent` v0.83.0, `/usr/local/bin/pi`.

---

## 1. The finding that matters most

**Every `delegate` job that has ever reported "done" shipped UNREVIEWED.**

`.agent/delegate-jobs/16390e57*/log.ndjson`, verbatim:

```
▶ Review by claude-max-cli …
  ✗ claude-max-cli unavailable (exit 1) — falling through.
▶ Review by claude-openrouter …
  ✗ claude-openrouter unavailable (exit 1) — falling through.
✓ done — unreviewed.
```

Both architect rungs failed, so the moat — the Claude review that is the entire point of
the ladder — silently never ran. 11 of 25 jobs are in state `done`. The builder's green
exit code was the only thing standing behind any of them.

### Root cause, proven

`ANTHROPIC_API_KEY` is set in the environment. The `claude` CLI prefers it over the
Claude Max OAuth session, and that API account is out of credit:

```
$ echo "reply with the single word OK" | claude -p
⚠ claude.ai connectors are disabled because ANTHROPIC_API_KEY or another auth source is set
Credit balance is too low
```

Strip the variable and the same command works:

```
$ echo "reply with the single word OK" | env -u ANTHROPIC_API_KEY claude -p
OK
```

So the Max subscription was healthy the whole time. One environment variable disabled the
review layer, and because the ladder is designed to fall through gracefully, it failed
*silently* — the job still said `✓ done`.

### Fix applied

`~/.pi/agent/extensions/pi-delegate/routing.json`, rung 1 is now
`["env","-u","ANTHROPIC_API_KEY","claude","-p"]`. Proven by replaying pi-delegate's own
acceptance condition (`r.exit === 0 && r.out.trim()`, `index.ts:919`):

```
rung: claude-max-cli argv: ['env','-u','ANTHROPIC_API_KEY','claude','-p']
exit: 0
stdout: 'VERDICT: APPROVE'
ACCEPTED BY pi-delegate? True
```

---

## 2. Live provider reality (probed today, not assumed)

Each row is `pi --model <id> -p "reply OK"`:

| Model | Result |
|---|---|
| `minimax/MiniMax-M3` | **OK** |
| `minimax/MiniMax-M2.7` | **OK** |
| `mistral/devstral-latest` | **OK** |
| `cerebras/gpt-oss-120b` | **OK** |
| `claude -p` (Max OAuth, key unset) | **OK** |
| `deepseek/deepseek-v4-pro` | `402 Insufficient Balance` |
| `anthropic/*` via pi | `400 credit balance is too low` |
| `openrouter/*` | `402` — balance covers ~413 tokens |
| `groq/*` | `401 Invalid API Key` |
| `google/gemini-*` | `429` (both 3-flash and 2.5-flash) |
| `cerebras/zai-glm-4.7` | empty response |

Two consequences:

**DeepSeek was the only builder that ever won a rung** — 9 of 11 `done` jobs were built by
`deepseek-v4-pro-direct`, 2 by `deepseek-v3.2`, zero by any MiniMax rung — and it is now
out of credit. The ladder's proven workhorse is dead.

**Claude is unreachable from inside pi.** With the key set it 400s; with it unset,
`No API key found for anthropic` — the installed `@cgaravitoq/pi-claude-code-auth`
extension is not supplying the OAuth token. Claude is reachable *only* as a `claude` CLI
subprocess. This is the single constraint that determines the whole architecture below.

---

## 3. The estate had three layers of config that did nothing

### 3a. `ultimate-code.workflow.json` never loaded — not once

Run through pi-agents' own parser:

```
WORKFLOWS LOADED: []
DIAGNOSTICS:
  ✗ ultimate-code.workflow.json -> Unsupported keys: budgets.
    Allowed keys: name, description, trigger, display, on, debounce, params, doc, flow, …
```

`budgets` is a **tool parameter**, not a workflow-file key (pi-agents README §Budgets). One
unsupported key voided the file. Corroborating evidence: every `~/.pi/workflows/projects/*/runs/`
directory is empty, going back to 3 Aug — no pi-agents workflow has ever run here.

Its `fallback_models` key — the basis of its "never fails because one model is out of
tokens" description — **does not exist in pi-agents at all** (zero matches in `src/`; the
agent option whitelist is `model, thinking, skills, tools, cwd, scope` at
`src/model/validate.ts:348-355`). The resilience it advertised was never implemented.

It also pointed at `google/gemini-3.0-flash`, which resolves to nothing under any provider
prefix. Repaired: valid schema, live models, and it now loads.

### 3b. The three agent profiles are invisible

`~/.pi/agent/agents/{claude-verifier,deepseek-coder,minimax-coder}.json` — pi-agents
discovers `.md` profiles, so:

```
AGENTS FOUND: []
DIAGS: []
```

Zero found, and **zero diagnostics** — a silent miss, which is worse than an error.

### 3c. `settings.json` invents keys pi never reads

`availableProviders` and `fallbackChain` appear **nowhere** in `docs/settings.md`, while
every real key (`defaultProvider`, `defaultModel`, `packages`, `theme`, …) does. So
`fallbackChain.verification: ["gemini","claude"]` — nominally the moat's routing — is
inert decoration. (Providers `gemini` and `claude` don't exist either; pi's provider list
is `anthropic cerebras deepseek google groq minimax mistral ollama openrouter`. Model
*patterns* like `claude/claude-sonnet-4-6` do fuzzy-resolve to `anthropic`, so that part
was fine — see the correction in §6.)

---

## 4. Extension inventory — 11 installed

| Extension | Verdict |
|---|---|
| **pi-delegate** (local) | **The crown jewel.** Keep. Only component with anti-fake-green protection. |
| **pi-governance** (local) | Inert — needs `.agent/governance.json`, which does not exist in this repo. |
| pi-agents | Keep — the workflow engine. Now has 3 loading workflows. |
| pi-subagents | Keep — used, artifacts in `.pi-subagents/`. |
| tomsej/pi-ext | Keep — ships `sem` (see §5) and 12 other extensions. |
| pi-web-access | Keep — `EXA_API_KEY` is set. |
| pi-context-prune | Keep — cheap, one tool (`context_tree_query`). |
| pi-llm-council | **Was broken by its own config** — see below. |
| pi-crew | Overlaps pi-agents/pi-subagents; large tool surface; prints on every run. Never used (`state/runs` empty). |
| pi-loop-mode, pi-codex-goal, pi-review-loop | Unused. Candidates for removal. |
| @cgaravitoq/pi-claude-code-auth | **Not working** — pi still reports `No API key found for anthropic`. |

### The council was three copies of one model

`~/.pi/council/config.json` listed `deepseek/deepseek-v4-pro` **three times**, with the
same model as synthesizer. A council of three identical models is one model asked three
times — the cross-validation it exists to provide is defeated by construction, and its
verdicts would correlate almost perfectly. It was also entirely dead (DeepSeek 402).

Replaced with three genuinely distinct, live-probed models: MiniMax M3, Mistral devstral,
Cerebras gpt-oss-120b.

### A hard tool-name collision (historical)

`.pi-subagents/artifacts/*_meta.json` records every reviewer subagent dying with:

```
Failed to load extension ".../pi-agent-extensions/extensions/workflow/index.ts":
Tool "workflow" conflicts with ".../pi-agents/src/index.ts"
```

That is the cause of the three `status:"error", exit:1` rows in `run-history.jsonl`.
`pi-agent-extensions` has since been uninstalled, so this is **resolved, not current** —
but it is the concrete demonstration that stacking overlapping orchestrators is not free.

### Extensions cost 5 seconds per pi invocation — and that broke pi-agents entirely

```
pi --offline -ne --list-models    1.60s
pi --offline    --list-models     6.64s
```

4.1× cold start. This is not merely a tax — it made every pi-agents workflow fail. See §10.

---

## 5. `sem` — registered, but its binary was missing

`sem_impact` / `sem_context` / `sem_entities` are real tools from `tomsej/pi-ext`. But the
CLI they shell out to was not installed, so every call returned:

```
sem command failed (exit 1). Install sem via: npm install @ataraxy-labs/sem
```

Installed `@ataraxy-labs/sem@0.21.0`. Proven working:

```
SUCCESS — first 3 entities: `_served_provider`, `_served_is_provisional`, `_coerce_verdict`
```

**Then running a workflow surfaced a second, separate bug.** Skill *names* are resolved at
runtime (tool names are not — pi silently accepts `-t definitely_not_a_tool`):

```
cannot start run: at $.body.branches.structure, unknown skill 'sem'
(cwd: …/prospector, scope: both). Available: none
```

pi-agents discovers skills from **directories only** (`src/catalog/paths.ts:125-139`) —
it never reads package-provided skills, so nothing in `tomsej/pi-ext/skills/` was visible.
Fixed by symlinking `~/.pi/agent/skills/sem` → the package's skill.

This is why validation is not proof. The workflow validated clean and still refused to start.

---

## 6. Two corrections to my own analysis

Kept deliberately — both were caused by proving something with too narrow a probe.

1. **I claimed `sem_*` were phantom tools.** Wrong. I had grepped only
   `~/.pi/agent/npm/node_modules` and missed the `git/` extension directory entirely. The
   tools were real; the *binary* was missing. Right symptom, wrong mechanism — and the
   wrong mechanism would have led to deleting working config.
2. **I suspected `claude/claude-sonnet-4-6` was an invalid provider.** Wrong — pi fuzzy-matches
   it to `anthropic`, proven with `pi --list-models "claude/claude-sonnet-4-6"`. Only
   `gemini-3.0-flash` was genuinely unresolvable.

---

## 7. The architecture the evidence forces

Three facts constrain the design, and together they leave exactly one shape:

1. Claude cannot be a pi model — only a CLI subprocess.
2. pi-agents has **no test-file protection**. It cannot stop a builder editing the test it
   must satisfy.
3. Builders demonstrably *try* to do exactly that. From two separate job logs:
   `⚠ deepseek-v4-pro-direct modified a protected verify/test file — reverted to founder snapshot`
   and the same line for `minimax-m3-direct`. **Both models, independently.** pi-delegate's
   snapshot-and-restore is not paranoia; it is load-bearing, and it fires routinely.

Therefore:

```
Claude Code (Max sub, this session)   ARCHITECT + REFEREE
   │  writes the spec + the failing test that defines "done"
   │
   ├─ workflow "recon"          → MiniMax ×3, READ-ONLY, returns conclusions
   │                              (keeps the expensive session from re-reading the tree)
   │
   ├─ delegate tool             → THE ONLY PATH THAT MUTATES FILES
   │    ladder: MiniMax M3 → Mistral devstral → DeepSeek (when funded)
   │    protected paths snapshotted + restored before every verify
   │    success = verify exit 0, run by the TOOL, never self-reported
   │    review  = env -u ANTHROPIC_API_KEY claude -p   ← fixed today
   │
   └─ workflow "review-fanout"  → 4 lenses, READ-ONLY, model-diverse
                                  feeds Claude a ranked, deduped verdict
```

**The rule that falls out of it:** mutations go through `delegate`, never through a
pi-agents workflow. Workflows are for read-only work — recon and review — where the worst
case is a wasted token, not a fake green. That is not a stylistic preference; it is the
only division consistent with fact 2 and fact 3.

**Why MiniMax is the right builder now** — but with an honest caveat. It is live, it has a
1M context and 128K output, and DeepSeek is out of credit. But the record does not show
MiniMax succeeding: zero rung wins, and in the one fully logged head-to-head it **timed
out after 1800s** and failed verify with exit 2 where DeepSeek had at least produced a
diff. That is a single observation, not a pattern — I have not run enough jobs to claim
MiniMax is or isn't a capable builder. **The check that would settle it:** run the next
5 delegate jobs and compare `builder` in `status.json` against rung order. Until then,
treat MiniMax-as-builder as unproven, which is precisely why the exit-code gate and the
restored Claude review matter more than the model choice.

---

## 8. What changed on disk

| File | Change |
|---|---|
| `pi-delegate/routing.json` | architect rung strips `ANTHROPIC_API_KEY`; ladder reordered to live models; `verifyCommand` → `.venv/bin/python -m pytest -q` |
| `~/.pi/agent/workflows/ultimate-code.workflow.json` | repaired: loads, live models, integrity lens added |
| `~/.pi/agent/workflows/recon.yaml` | new — read-only parallel recon |
| `~/.pi/agent/workflows/review-fanout.yaml` | new — 4-lens model-diverse review |
| `~/.pi/council/config.json` | 3 identical dead models → 3 distinct live ones |
| `~/.pi/agent/skills/sem` | symlink making the skill discoverable |
| global npm | `@ataraxy-labs/sem@0.21.0` installed |

Backups: `routing.json.pre-2026-08-05`, `council/config.json.pre-2026-08-05`.

### The `verifyCommand` fix, proven

It was `pytest -q`, which resolves to `/usr/local/bin/pytest` → system Python 3.14:

```
$ python3       -c "import ddgs"   → ModuleNotFoundError
$ .venv/bin/python -c "import ddgs" → .venv/lib/python3.14/site-packages/ddgs/__init__.py
```

Builders were being judged against an interpreter that cannot import the project's
dependencies. This is the `ddgs` split-brain already recorded in memory, resurfacing in a
new place.

---

## 10. Why no pi-agents workflow had ever run — the RPC handshake

Repairing the workflow files was necessary but not sufficient. Every run still died:

```
Failed to initialize delegated pi RPC process: … Cause: Timed out waiting for
pi RPC 'set_steering_mode' response
```

pi-agents blames the pi version ("run `pi update pi`", `subprocess.ts:854`). That is a
guess, and it is wrong — pi 0.83.0 implements the handler at
`dist/modes/rpc/rpc-mode.js:404`.

**The real cause, measured.** pi-agents spawns each agent as `pi --mode rpc` and waits
`CONTROL_RESPONSE_TIMEOUT_MS = 30_000` (`subprocess.ts:34`) for the handshake. Timing that
exact handshake, 3 runs each:

```
with 11 extensions   12.20s  13.69s  23.58s     ← budget is 30s
with -ne              3.05s   3.43s   3.79s
```

One child alone can consume 79% of the budget. pi-agents runs branches concurrently, so
two or three contending children exceed 30s and the whole run fails. This explains the
otherwise baffling history: recon succeeded once when the machine was quiet and never
again.

**Things I ruled out along the way**, each with a probe:

- *Model-specific?* No — two M3 branches failed identically to devstral.
- *Parallel-spawn race?* No — a single solo agent failed the same way.
- *A wedged leftover `pi` process?* No — killed it, failure persisted.
- *stdout corruption by chatty extensions?* No. In `--mode rpc` extensions emit
  well-formed `extension_ui_request` JSON, and `set_steering_mode` returns
  `success:true`. The channel is clean; it is merely slow.
- *Package count?* No, and this is the interesting one — pruning 11 packages to 5 barely
  moved the ceiling (23.49s vs 23.58s). The cost is not proportional to package count.
- *`PI_OFFLINE=1` / `PI_SKIP_VERSION_CHECK=1`?* No. `PI_OFFLINE=1` made it **worse**
  (34.97s — already over budget on its own).

**Correction to my own earlier numbers.** I first measured cold start with
`pi --offline -p "x"` and reported 12–24s. That is wrong: `-p` still performs a model
call, so I was timing MiniMax's latency, not startup. `PI_STARTUP_BENCHMARK=1` puts
pi's own framework init at **680ms**. The handshake timings above are the honest ones,
because they measure precisely what the 30s budget governs.

**Fix applied** — a local, opt-in patch to `pi-agents/src/engine/subprocess.ts` (just
after the `args` array is built at :381). With the env unset, behaviour is identical to
upstream:

```ts
if (process.env.PI_AGENTS_CHILD_NO_EXTENSIONS === "1") {
  args.push("-ne");
  for (const ext of (process.env.PI_AGENTS_CHILD_EXTENSIONS ?? "").split(",")…)
    args.push("-e", ext);
}
```

`-ne` disables *discovery*; explicit `-e` still loads, so `sem` survives by path. Run
workflows with:

```sh
export PI_AGENTS_CHILD_NO_EXTENSIONS=1
export PI_AGENTS_CHILD_EXTENSIONS=/Users/chidionyema/.pi/agent/git/github.com/tomsej/pi-ext/extensions/pi-sem/index.ts
```

**Process risk:** this patch lives inside `node_modules` and will be erased by
`pi update`. It is not a fix to depend on silently — the durable version is an upstream
flag. Re-apply after any pi/pi-agents update.

### Two further bugs the working engine then exposed

1. **`mistral/devstral-latest` runs away on open-ended search.** It blew the 100-turn
   budget on recon's `tests` branch twice, while completing a bounded task
   (`{"count":70,"model":"devstral"}`) fine. The aggregate read "11 turns" because a
   cut-off agent's usage never merges — which is why the error looks self-contradictory.
   Moved that branch to M3 and gave every branch an explicit tool-call ceiling.
2. **A single bad control character fails the entire run.** The `behaviour` branch
   emitted a literal newline inside a JSON string (position 9251) and the run died.
   Every branch now carries an explicit JSON discipline block (no raw newlines/tabs/
   backticks, strings under 300 chars).

### Proof it now works

```
$ pi -p "Run the saved workflow named 'recon' … kill_decay.py …"
{"summary":"# kill_decay.py — what it is\n\n**4-function library at
 prospector/kill_decay.py:1-277** …", "confidence":"medium",
 "verify_command":".venv/bin/python -m pytest tests/test_kill_decay.py -q", …}
```

Its central finding — that `kill_decay.py` is unwired — I checked independently rather
than trusting it:

```
$ grep -rn 'kill_decay\|get_active_steers' prospector/ --include='*.py' \
    | grep -v test_ | grep -v '^prospector/kill_decay.py'
(no hits)
$ .venv/bin/python -m pytest tests/test_kill_decay.py -q
10 passed, 1 warning in 0.15s
```

Correct on the substance. It did claim "11 tests" where there are 10 — a reminder that
the fan-out's output is a lead to verify, not a verdict, exactly as its own `"confidence":
"medium"` implies.

---

## 9. Open, not done

- **`@cgaravitoq/pi-claude-code-auth` does not work.** If fixed, Claude becomes available
  as a pi model and could serve as a workflow reduce-node — a materially better review
  layer than MiniMax-reviewing-MiniMax. Not diagnosed; the CLI subprocess path works, so
  this was not on the critical path.
- **`pi-governance` is inert.** It enforces "exit code is the only authority" structurally
  — blocking unverified mutations — which is the doctrine this repo already runs on. It
  needs `.agent/governance.json`. Worth enabling; not done, as it changes tool-call
  gating globally and that deserves a deliberate decision.
- **MiniMax-as-builder is unproven** — see §7 for the exact check.
- **Extension pruning not done.** pi-crew, pi-loop-mode, pi-codex-goal and pi-review-loop
  show no usage. Removing them would cut into the 5s startup tax, but "no state on disk"
  is weaker evidence than it looks, so I did not remove another agent's tools unasked.
