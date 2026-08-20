# Model pinning: which model version each part of the estate runs

**What this answers.** Which model version a given brain uses, who may change it, and how a change
is proved to have taken effect. Read this before touching `operator._build_operator`, the
`component_models` block in `config.yaml`, or the `models` knob group in the ops console.

Founder request, 2026-08-19: *"we have a feature to pin model down, in ops dashboard but not user
friendly and also cannot add new provider, need both and proof it works, also need to set provider
model version and not couple to agent and engine, so I can have different one for hermes, and the
engine has different parts that use different models"*.

---

## 1. The three measurements this design is built on

Each was obtained by executing code, not by reading it.

**1. `cfg.model` and `cfg.model_fast` were completely inert.** They were editable console knobs.
A write succeeded, a history row was recorded, the new value read back, and nothing changed.
Setting either to a MiniMax name, a Claude name or an Ollama name and then rebuilding every
provider left every model identical. The cause: the computed value reached exactly one
construction site (`ollama`), guarded by a `_PROVIDER_MODEL_PREFIX` table whose tuple for that
provider was empty, so the match was always False and the model always `None`.

The founder said the pin was "not user friendly". It was worse than that. It did nothing.

**2. `OpenRouterOperator` had no construction site.** About 300 lines with per-model circuit
breakers, health marking, `Retry-After` handling and priority rotation, and
`_build_operator("openrouter", ...)` raised `ValueError: unknown operator`. Nothing else in the
repo constructed it. The `cfg.model_defaults.openrouter` field its own docstring named did not
exist on the dataclass. This is why "cannot add new provider" was true: the one provider that
fronts many vendors was unreachable.

**3. `tests/unit/test_model_config.py` asserted the opposite of its own docstring.**
`TestConfigOverridesHardcodedDefault` branches on `if kind in ("deepseek", "minimax")` — both of
its parametrised providers — into an assertion that the pin is *ignored*. The branch that tests
the documented invariant was unreachable. A green suite was reporting that pinning worked.

## 2. The design

Two layers, and the console edits both.

**Layer 1, `model_defaults` — the version a provider runs when nobody has said otherwise.**
One entry per provider tier. `minimax: MiniMax-M3`, `deepseek: deepseek-chat`, and so on. Change
one line here and every chain using that provider moves together. This is the layer you want when
a vendor ships a new version and you are adopting it everywhere.

**Layer 2, `component_models` — the override for one chain.** A two-level table, component then
provider:

```yaml
component_models:
  moat:
    claude_cli:  ""
    minimax:     ""
  noncritical:
    minimax:     ""
    deepseek:    ""
    openrouter:  ""
```

A non-blank cell wins over `model_defaults` for that chain only. A blank cell means "use the
default", which is byte-for-byte the old behaviour. This is the decoupling the founder asked for:
`grounding` can run Sonnet while `moat` stays on Haiku, and neither moves the other.

The five components are `moat`, `noncritical`, `artifact`, `marketing` and `grounding`. They are
the chains that already existed as separate rosters in `config.yaml`; this adds the model version
to the split that was already there, it does not invent a new taxonomy.

**Resolution order, in `operator.resolve_model`:** component pin, then `model_defaults.<tier>_fast`
when the caller asked for fast, then `model_defaults.<tier>`, then the provider's own built-in
default. One function, so no two call sites can disagree about precedence.

**Every construction site takes the pin.** That is the whole difference from the old design. The
`_PROVIDER_MODEL_PREFIX` heuristic is deleted. `claude_cli`, `minimax`, `minimax_m27`, `deepseek`,
`ollama` and `openrouter` each read `component_pin(...)` first.

## 3. Adding a provider

A tier is buildable when its name is in `operator.BUILDABLE_TIERS` and `_build_operator` has a
branch for it. `openrouter` is now both, which makes it the cheap answer to most "add a provider"
requests: it fronts many vendors behind one OpenAI-compatible endpoint and one key, so a new
vendor is a model name in `model_defaults.openrouter`, not a new adapter.

A genuinely new adapter is still code: a class, a branch in `_build_operator`, a name in
`BUILDABLE_TIERS`, an entry in the console's `_CHAIN_PROVIDERS` table. The console cannot conjure
an adapter, and it should not pretend to.

Removed tiers (`claude`, `standardcompute`, `cursor_cli`) still raise an explicit `ValueError`
naming the removal, so a stale config fails loudly at startup rather than silently building a
shorter chain.

## 4. What the console does, and what it refuses

The `models` group in the ops console config page carries every model knob: the `model_defaults`
rows and the twelve per-component pins, generated from `operator.COMPONENTS` crossed with the
providers each chain can name. Generating them means a new component or a new provider appears in
the console without anyone remembering to add it.

The write path is unchanged and is deliberately strict. `yaml_surgery.rewrite` edits the file
line for line, preserves every comment, and **never adds a key**. That is why the
`component_models` block ships pre-declared with blank values: a key that is not already in the
file cannot be edited from the console at all.

Every write needs a `reason`. The `moat` pins are marked `high_blast`, so they additionally need
`acknowledge_moat: true` — the moat is what rules verdicts, and changing its model changes what
publishes. An apply also needs a matching file mtime, so two sessions editing at once get a
refusal rather than a silent overwrite.

## 5. The boundary: a pin does not buy a separate health identity

Dead marks and circuit breakers are keyed on the **tier name**, not the model. Pinning
`noncritical.minimax` to one version and `moat.minimax` to another does not give them separate
failure accounting. If MiniMax returns 429 to one chain, the mark benches MiniMax for both.

This is deliberate. The mark records that a vendor account is out of allowance, and the allowance
is per account, not per model. Making health per model would make an exhausted key look alive to
every chain that had not yet tried it.

## 6. Proving a change took effect

```bash
.venv/bin/python scripts/model_pin_probe.py          # table
.venv/bin/python scripts/model_pin_probe.py --json   # same, for the console
```

The probe builds each operator and asks the object what model it actually holds, then prints the
component, the provider, the model and which layer supplied it. It reports "no credential"
explicitly rather than omitting a row, because a missing key and a missing pin look identical in a
table that drops both.

This is the answer to "prove it works". A console history row proves a write happened. Only the
probe proves a call changed.

## 7. The guard

`tests/unit/test_component_models.py::test_no_model_knob_is_inert` is the mechanism that stops
this recurring. For every knob in the `models` group it builds an operator twice, once with a
sentinel value written to that key, and fails if the built object is unchanged. A knob whose path
shape the test does not recognise also fails, with a message saying so: a new model knob ships
with the proof that setting it changes a call, or it does not ship.

Mutation-checked 2026-08-20. Re-adding a `{"path": ["model"]}` knob to `KNOBS` makes both this
test and `test_the_two_knobs_that_did_nothing_are_gone` fail. Removing the mutant makes them pass.

The class of failure it closes: **a control that writes a config key nothing reads.** The write
succeeds, the audit trail is complete, the value reads back, and the system ignores it. Nothing in
a config editor can detect this on its own, because from the editor's side a dead key and a live
key are the same string in the same file.
