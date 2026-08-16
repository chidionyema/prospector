"""T0-1…T0-6 — the six defects in the Control Center's config Save path.

Each test names the defect it pins and would have FAILED before the fix. They are here together
because they are one failure with six faces: **Save was destructive, and every fence that should
have caught it was keyed to something other than what it was checking.** `validate_config` checked
that `hard_gates` was "a list of dicts" while the keys were gone; the moat fence was keyed to three
top-level paths that do not exist in config.yaml; the writer round-tripped the data and dropped
1,173 comment lines; and `config.yaml` is inside the daemon's redeploy fingerprint, so all of it
shipped into the running engine at the next tick with no human step in between (T0-4).
"""
from __future__ import annotations

import json

import pytest
import yaml

from prospector.control_center import config_editor as ce
from prospector.control_center import yaml_surgery as surgery
from prospector.control_center.pages import _parameters as P

# A config with the file's real shapes, and comments that must survive a Save.
_CONFIG = """\
# Top-of-file rationale that must survive every save.
operator: [minimax, claude_cli]     # the verdict chain
moat_primary: [minimax, claude_cli]

thresholds:
  # WHY 0.4: measured, see E11.
  confidence_floor: 0.4
  min_composite_to_pass: 3.0

hard_gates:                          # evaluated kill-fast in this order
  # A KILL must be grounded in CITED disconfirming evidence.
  - value_durability: [refuted]
  - incumbency: [refuted]
  - legality: [refuted]
  - adversarial_decisive: false

weights:
  pain_acuity: 0.5
  money_provability: 0.5

spend:
  daily_cap_usd: 100.0               # raised 2026-08-15
  warn_at_usd: 75.0
"""


@pytest.fixture
def cfg_file(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text(_CONFIG, encoding="utf-8")
    monkeypatch.setattr(ce, "CONFIG_PATH", path)
    monkeypatch.setattr(ce, "_CC_DIR", tmp_path / "cc")
    return path


def _loaded(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# T0-1 — Saving Parameters destroyed the kill filter
# --------------------------------------------------------------------------- #
def test_t0_1_toggling_gates_preserves_every_gate_name_and_verdict_list():
    """The defect staged `[{"k": True}] * 6` — `k` was a string literal, not the loop variable.
    Every gate name and every failing-verdict list was replaced by one meaningless key."""
    cfg = yaml.safe_load(_CONFIG)
    staged = P._stage_hard_gates(cfg, {"value_durability": True, "incumbency": True,
                                       "legality": True})

    assert staged == cfg["hard_gates"], "an all-ticked toggle must be a no-op"
    assert {list(g)[0] for g in staged} == {"value_durability", "incumbency", "legality",
                                            "adversarial_decisive"}
    assert all(list(g.values())[0] == ["refuted"]
               for g in staged if list(g)[0] != "adversarial_decisive")


def test_t0_1_unticking_drops_only_that_gate():
    cfg = yaml.safe_load(_CONFIG)
    staged = P._stage_hard_gates(cfg, {"value_durability": True, "incumbency": False,
                                       "legality": True})
    names = [list(g)[0] for g in staged]

    assert "incumbency" not in names
    assert names == ["value_durability", "legality", "adversarial_decisive"]


def test_t0_1_an_entry_the_checkboxes_do_not_describe_is_never_dropped():
    """`adversarial_decisive` is not a check and has no checkbox. The old code deleted it simply
    by not knowing about it."""
    cfg = yaml.safe_load(_CONFIG)
    staged = P._stage_hard_gates(cfg, {"value_durability": True})
    assert {"adversarial_decisive": False} in staged


def test_t0_1_validation_rejects_gates_whose_names_are_not_checks(cfg_file):
    """The fence that waved the corruption through. "A list, of dicts" is true of
    `[{"k": True}]`, which matches no check name and therefore never fires."""
    bad = yaml.safe_load(_CONFIG)
    bad["hard_gates"] = [{"k": True} for _ in range(6)]

    ok, errs = ce.validate_config(bad)
    assert not ok
    assert any("not a check name" in e for e in errs), errs

    ok2, _ = ce.write_config(bad, moat_affecting=True, orig_mtime=ce.get_config_mtime())
    assert ok2 is False
    assert _loaded(cfg_file)["hard_gates"] == yaml.safe_load(_CONFIG)["hard_gates"]


# --------------------------------------------------------------------------- #
# T0-2 — Saving Parameters blanked the operator chain
# --------------------------------------------------------------------------- #
def test_t0_2_the_selector_offers_only_tiers_that_can_be_built():
    """It offered `["", "mock", "claude"]`. `claude` was deleted on 2026-08-15 and now raises
    in `_build_operator`; the live value is a list that was in none of the options, so the widget
    fell to index 0 and staged `""` on every render with no interaction."""
    from prospector.operator import BUILDABLE_TIERS, _build_operator

    assert "claude" not in BUILDABLE_TIERS and "cursor_cli" not in BUILDABLE_TIERS
    assert "" not in BUILDABLE_TIERS
    for removed in ("claude", "cursor_cli", "standardcompute"):
        with pytest.raises(ValueError):
            _build_operator(removed, None, False)


def test_t0_2_the_live_chain_is_representable_in_the_selector():
    """The regression in one line: whatever config.yaml names must be selectable, or the widget
    silently proposes something else."""
    from prospector.operator import BUILDABLE_TIERS
    live = yaml.safe_load(open("config.yaml", encoding="utf-8").read())["operator"]
    assert all(t in BUILDABLE_TIERS for t in live), live


def test_t0_2_writing_an_empty_operator_is_refused(cfg_file):
    blanked = yaml.safe_load(_CONFIG)
    blanked["operator"] = ""
    ok, msg = ce.write_config(blanked, moat_affecting=True, orig_mtime=ce.get_config_mtime())

    assert ok is False, msg
    assert _loaded(cfg_file)["operator"] == ["minimax", "claude_cli"]


# --------------------------------------------------------------------------- #
# T0-3 — Saving deleted 58% of config.yaml
# --------------------------------------------------------------------------- #
def test_t0_3_a_save_preserves_every_comment_line(cfg_file):
    before = cfg_file.read_text(encoding="utf-8")
    n_comments = sum(1 for line in before.splitlines() if line.strip().startswith("#"))
    assert n_comments >= 3

    new = yaml.safe_load(_CONFIG)
    new["spend"]["daily_cap_usd"] = 123.0
    ok, msg = ce.write_config(new, moat_affecting=False, orig_mtime=ce.get_config_mtime())
    after = cfg_file.read_text(encoding="utf-8")

    assert ok, msg
    assert sum(1 for line in after.splitlines() if line.strip().startswith("#")) == n_comments
    assert _loaded(cfg_file)["spend"]["daily_cap_usd"] == 123.0
    assert len(after.splitlines()) == len(before.splitlines())


def test_t0_3_only_the_changed_line_is_rewritten(cfg_file):
    before = cfg_file.read_text(encoding="utf-8").splitlines()
    new = yaml.safe_load(_CONFIG)
    new["thresholds"]["confidence_floor"] = 0.42
    ce.write_config(new, moat_affecting=True, orig_mtime=ce.get_config_mtime())
    after = cfg_file.read_text(encoding="utf-8").splitlines()

    differing = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
    assert len(differing) == 1, [(before[i], after[i]) for i in differing]
    assert "confidence_floor: 0.42" in after[differing[0]]


def test_t0_3_the_inline_comment_on_an_edited_line_survives(cfg_file):
    new = yaml.safe_load(_CONFIG)
    new["spend"]["daily_cap_usd"] = 55.0
    ce.write_config(new, moat_affecting=False, orig_mtime=ce.get_config_mtime())

    line = next(ln for ln in cfg_file.read_text(encoding="utf-8").splitlines()
                if "daily_cap_usd" in ln)
    assert "# raised 2026-08-15" in line


def test_t0_3_a_hash_inside_a_quoted_value_is_not_treated_as_a_comment():
    text = 'url: "https://example.test/x#frag"   # real comment\n'
    out, unapplied = surgery.apply_edits(text, {("url",): "https://example.test/y#frag"})
    assert not unapplied
    assert out.strip() == 'url: "https://example.test/y#frag"   # real comment'


def test_t0_3_a_new_key_is_refused_rather_than_guessed_into_place(cfg_file):
    """Guessing where a new key belongs in an annotated file means guessing which comment block
    it falls under. A key filed under the wrong rationale is worse than one added by hand."""
    new = yaml.safe_load(_CONFIG)
    new["brand_new_key"] = 1
    ok, msg = ce.write_config(new, moat_affecting=False, orig_mtime=ce.get_config_mtime())

    assert ok is False and "cannot add a new key" in msg
    assert "brand_new_key" not in cfg_file.read_text(encoding="utf-8")


def test_t0_3_the_writer_fails_safe_if_the_edit_does_not_reparse(monkeypatch):
    """The surgeon producing VALID YAML with the WRONG value is the failure mode line editing
    has and a serialiser does not. `rewrite` re-parses and refuses on mismatch."""
    monkeypatch.setattr(surgery, "apply_edits", lambda text, e, r=(): (text, []))
    old = yaml.safe_load(_CONFIG)
    new = yaml.safe_load(_CONFIG)
    new["spend"]["daily_cap_usd"] = 7.0

    _, problems = surgery.rewrite(_CONFIG, old, new)
    assert problems and "does not re-parse" in problems[0]


# --------------------------------------------------------------------------- #
# T0-4 — the amplifier: a corrupt Save auto-deploys itself
# --------------------------------------------------------------------------- #
def test_t0_4_a_corrupt_save_never_reaches_disk_so_it_cannot_be_redeployed(cfg_file):
    """config.yaml is inside the daemon's redeploy fingerprint
    (`scheduler/run_scheduled.py::code_fingerprint`), so a bad file is a bad file IN PRODUCTION
    within one tick. There is no human step after Save — which makes refusing at the writer the
    only place a fence can stand."""
    from prospector.scheduler.run_scheduled import code_fingerprint

    fp_before = code_fingerprint(str(cfg_file))
    for corrupt in ({"hard_gates": [{"k": True}]}, {"operator": ""}, {}):
        bad = yaml.safe_load(_CONFIG) | corrupt if corrupt else {}
        ok, _ = ce.write_config(bad, moat_affecting=True, orig_mtime=ce.get_config_mtime())
        assert ok is False, corrupt

    assert code_fingerprint(str(cfg_file)) == fp_before, "a refused save still moved the file"


# --------------------------------------------------------------------------- #
# T0-5 — the change ledger was YAML in a file named .jsonl
# --------------------------------------------------------------------------- #
def test_t0_5_history_is_written_as_one_json_object_per_line(cfg_file):
    new = yaml.safe_load(_CONFIG)
    new["spend"]["warn_at_usd"] = 60.0
    ok, msg = ce.write_config(new, moat_affecting=False, orig_mtime=ce.get_config_mtime())
    assert ok, msg

    lines = [ln for ln in ce._config_history().read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert lines and all(isinstance(json.loads(ln), dict) for ln in lines)


def test_t0_5_the_reader_still_parses_the_233_legacy_yaml_records(cfg_file):
    """Legacy records are real history and are not being rewritten, so the reader takes both.
    A reader that only handled the new format would report the change log as empty."""
    hist = ce._config_history()
    hist.parent.mkdir(parents=True, exist_ok=True)
    hist.write_text(
        "backup: /tmp/a\nhash: aaa\nmoat_affecting: false\nts: '2026-06-16T13:33:55+00:00'\n"
        "backup: /tmp/b\nhash: bbb\nmoat_affecting: true\nts: '2026-06-17T13:33:55+00:00'\n"
        + json.dumps({"hash": "ccc", "moat_affecting": False, "ts": "2026-08-16T00:00:00+00:00"})
        + "\n", encoding="utf-8")

    records = ce.read_history()
    assert [r["hash"] for r in records] == ["aaa", "bbb", "ccc"]


# --------------------------------------------------------------------------- #
# T0-6 — the certification fence was keyed to keys that do not exist
# --------------------------------------------------------------------------- #
def test_t0_6_every_moat_affecting_key_exists_in_the_real_config():
    """The fence named `moat_order`, `adversarial_decisive` and `adversarial` as TOP-LEVEL paths.
    None is a top-level key, which is why `moat_affecting` fired 0 times in 233 saves."""
    live = yaml.safe_load(open("config.yaml", encoding="utf-8").read())
    for path in ce.MOAT_AFFECTING_KEYS:
        node = live
        for part in path:
            assert isinstance(node, dict) and part in node, (
                f"MOAT_AFFECTING_KEYS names {'.'.join(path)}, which is not in config.yaml — "
                "a fence keyed to an absent path reads as protection and is inert")
            node = node[part]


def test_t0_6_changing_what_may_be_sold_is_flagged_moat_affecting():
    live = yaml.safe_load(open("config.yaml", encoding="utf-8").read())
    for path, value in (
        (("moat_primary",), ["minimax"]),
        (("hard_gates",), [{"legality": ["refuted"]}]),
        (("weights",), {"pain_acuity": 1.0}),
        (("thresholds",), {"confidence_floor": 0.9}),
        (("listing", "pricing"), {"changed": True}),
        (("schedule",), {"batch_size": 1}),
    ):
        changed = json.loads(json.dumps(live, default=str))
        node = changed
        for part in path[:-1]:
            node = node[part]
        node[path[-1]] = value
        assert ce.is_moat_affecting(live, changed), f"{'.'.join(path)} must flag the config"


def test_t0_6_an_unrelated_change_is_not_flagged():
    """The before-state guard: a fence that flags everything is as useless as one that flags
    nothing, and would leave the golden gate permanently uncertified."""
    live = yaml.safe_load(open("config.yaml", encoding="utf-8").read())
    changed = json.loads(json.dumps(live, default=str))
    changed.setdefault("spend", {})["warn_at_usd"] = 1.0
    assert ce.is_moat_affecting(live, changed) is False
