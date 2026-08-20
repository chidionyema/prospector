"""The two tier tables, in a module that imports nothing.

WHY THEY LIVE HERE AND NOT IN `operator.py`. These are plain tuples of strings with no
dependencies at all, and they were the only thing `prospector.ops.console_api` wanted from
`prospector.operator`. Importing operator to read them cost ~1.0s of import on this laptop
(it pulls `prospector.telemetry`, which pulls the config machinery), and the console spawns a
fresh Python process for every one of its 36 views, so all 36 paid that price to build a table
of dropdown choices that only the config page ever renders.

`prospector.operator` re-exports both names, so `from prospector.operator import
BUILDABLE_TIERS` keeps working everywhere it is already written. New callers should import
from here.
"""
from __future__ import annotations

#: The tier names `_build_operator` can actually construct, in the order it tries them.
#:
#: THIS EXISTS SO A UI CANNOT OFFER A TIER THAT DOES NOT EXIST. The Control Center's operator
#: selector offered `["", "mock", "claude"]` — one blank, one test double, and one adapter that
#: was DELETED on 2026-08-15 and now raises here. The live value (`[minimax, claude_cli]`) was in
#: none of them, so the widget fell to index 0 and staged the empty string on every render, with
#: no interaction required. Any list of tier names written somewhere else drifts from this
#: function; read this instead. Removed tiers stay absent deliberately — they raise below with
#: the reason and the date, which is the message an operator needs.
BUILDABLE_TIERS: tuple[str, ...] = (
    "claude_cli", "minimax", "minimax_m27", "deepseek", "ollama", "openrouter", "mock",
)


#: The parts of the engine that can carry their own model pin.
#:
#: Each name is a chain that ALREADY exists as its own config roster, so this adds no new concept
#: — it gives each roster a model to go with its provider list. `moat` is the verdict chain
#: (`operator:`/`moat_primary:`), `noncritical` the cheap tail (`noncritical_operator:`),
#: `artifact` the prose of the £49 deliverable (`artifact_operator:`), `marketing` the shelf copy
#: (`marketing_operator:`), `grounding` the retrieval brain.
#:
#: WHY THIS EXISTS. Until 2026-08-19 there was one estate-wide `model:` and one `model_fast:`,
#: and a name-prefix heuristic guessed which provider they were "for". Measured that day: the
#: guess reached exactly one construction site (`ollama`), where its prefix table was empty, so
#: the match was always False and the value always `None`. Setting `cfg.model` to a MiniMax name,
#: a Claude name or an Ollama name changed the model of nothing. Both knobs are editable in the
#: ops console, so an operator could set them, watch the write succeed, read the history row, and
#: get no change at all. `tests/unit/test_component_models.py` fails if a pin stops arriving.
COMPONENTS: tuple[str, ...] = ("moat", "noncritical", "artifact", "marketing", "grounding")
