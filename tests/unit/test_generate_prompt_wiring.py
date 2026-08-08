"""Anti-'write-only field' tests for the G2 + G4 generation directives.

A directive that is computed but never appended is a silent no-op, which is a defect
class this repo has shipped before. These tests pin the wiring: with the gates ON,
the directive MUST appear in the captured user prompt; with the gates OFF, the
prompt MUST NOT carry the directive. The typicality self-report is also pinned to
land in Candidate.tags so the diversity meter can observe it."""
from __future__ import annotations

from prospector.config import load_config
from prospector.generate import generate


class _CapturingOp:
    """Records the user prompt of every call so we can assert what reached the model."""

    model_version = "stub"

    def __init__(self, items: list[dict] | None = None):
        self.calls = 0
        self.prompts: list[str] = []
        self._items = items

    def complete_json(self, system, user, temperature=0.0):
        self.calls += 1
        self.prompts.append(user)
        if self._items is not None:
            return self._items
        return [{"title": f"Fresh idea {self.calls}-{i}", "one_liner": "x",
                 "why_now": "y", "tags": {"sector": "s"}} for i in range(6)]


def test_landscape_brief_reaches_the_prompt(monkeypatch):
    """With G2 ON and a non-empty topic, the rendered prompt must carry the brief.

    The conftest fence stubs `_fetch_brief` to ""; this test installs a stronger stub
    that returns a sentinel and is applied after the autouse fixture, so it wins.
    The autouse `_isolate_generation_artifacts` already points the cache at tmp_path."""
    cfg = load_config()
    cfg.generation["refinement_enabled"] = False

    from prospector import landscape
    monkeypatch.setattr(landscape, "_fetch_brief",
                        lambda cfg, icfg, topic: "SENTINEL-LANDSCAPE")

    op = _CapturingOp()
    generate(op, cfg, signal_text="veterinary invoicing", sector="veterinary", k=6)

    assert op.prompts, "generate() should have made at least one call"
    assert all("SENTINEL-LANDSCAPE" in p for p in op.prompts)


def test_blue_sky_run_still_gets_a_landscape_brief(monkeypatch):
    """The regression that pins the audience fallback (landscape._topic rung 3).

    The daemon's own call is `run_signal("", ...)` (scheduler/run_scheduled.py:724) —
    EMPTY signal and no sector — which is the majority of all generation. With only the
    signal/sector rungs, `_topic()` returned "" and this whole feature was inert on that
    path. Assert the brief still reaches the prompt, and that the topic it fetched on is a
    real audience persona (underscores expanded) rather than a guess."""
    cfg = load_config()
    cfg.generation["refinement_enabled"] = False

    from prospector import landscape
    topics: list[str] = []

    def _stub(cfg, icfg, topic):
        topics.append(topic)
        return f"SENTINEL-BLUESKY[{topic}]"

    monkeypatch.setattr(landscape, "_fetch_brief", _stub)

    op = _CapturingOp()
    generate(op, cfg, signal_text="", sector="", k=6)

    assert op.prompts, "generate() should have made at least one call"
    assert all("SENTINEL-BLUESKY" in p for p in op.prompts)
    assert topics, "the fallback must have produced a non-empty topic to fetch on"
    personas = {str(a).replace("_", " ").strip()
                for a in (cfg.generation.get("audience_forms") or [])}
    assert personas, "config must carry audience_forms for this path to exist"
    for t in topics:
        assert t in personas, (t, sorted(personas))


def test_typicality_directive_reaches_the_prompt():
    """With G4 ON, every captured prompt must carry the Verbalized Sampling directive."""
    cfg = load_config()
    cfg.generation["refinement_enabled"] = False

    op = _CapturingOp()
    generate(op, cfg, signal_text="veterinary invoicing", sector="veterinary", k=6)

    assert op.prompts, "generate() should have made at least one call"
    assert all("VERBALIZED SAMPLING" in p for p in op.prompts)


def test_both_gates_off_leaves_the_prompt_clean():
    """With both gates explicitly OFF, the directives MUST NOT appear in the prompt."""
    cfg = load_config()
    cfg.generation["refinement_enabled"] = False
    cfg.generation["incumbent_seed"] = {"enabled": False}
    cfg.generation["verbalized_sampling"] = {"enabled": False}

    op = _CapturingOp()
    generate(op, cfg, signal_text="veterinary invoicing", sector="veterinary", k=6)

    assert op.prompts, "generate() should have made at least one call"
    for p in op.prompts:
        assert "INCUMBENT LANDSCAPE" not in p
        assert "VERBALIZED SAMPLING" not in p


def test_typicality_lands_in_tags():
    """The model's self-reported typicality is carried into Candidate.tags so the
    diversity meter (diversity.batch_report) can observe it. setdefault semantics:
    a value the model already put in its own tags dict wins."""
    cfg = load_config()
    cfg.generation["refinement_enabled"] = False

    items = [{"title": f"Idea {i}", "one_liner": "x",
              "why_now": "y", "typicality": 0.15,
              "tags": {"sector": "s"}} for i in range(6)]
    op = _CapturingOp(items=items)
    out = generate(op, cfg, signal_text="x", sector="", k=6)

    assert len(out) == 6
    for c in out:
        assert c.tags["typicality"] == 0.15
