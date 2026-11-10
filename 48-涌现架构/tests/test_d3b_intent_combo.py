"""D3-B 意图知识组合测试。"""

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
D3B = ROOT / "experiments" / "d3b_intent_combo"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


combo = _load("combo", D3B / "combo.py")
evaluate = _load("d3b_evaluate", D3B / "evaluate.py")
IntentKnowledgeCombo = combo.IntentKnowledgeCombo
build_combos = combo.build_combos
_session_metrics = evaluate._session_metrics
evaluate_fn = evaluate.evaluate


def test_build_combos_groups_by_intent_proxy():
    sessions = [
        {
            "intent_proxy": "a",
            "recalled_memory_ids": ["m1", "m2"],
            "recalled_skills": ["s1"],
            "intent_signals": {"file_domains": ["d1"]},
        },
        {
            "intent_proxy": "a",
            "recalled_memory_ids": ["m1", "m3"],
            "recalled_skills": ["s1", "s2"],
            "intent_signals": {"file_domains": ["d1", "d2"]},
        },
        {
            "intent_proxy": "b",
            "recalled_memory_ids": ["m4"],
            "recalled_skills": ["s3"],
            "intent_signals": {"file_domains": ["d3"]},
        },
    ]
    combos = build_combos(sessions, min_support=1, top_memory=5, top_skills=5, top_domains=5)
    assert "a" in combos
    assert "m1" in combos["a"].memory_ids
    assert combos["a"].support == 2


def test_session_metrics_with_combo_reduces_steps():
    sess = {
        "session_id": "s1",
        "intent_proxy": "a",
        "recalled_memory_ids": ["m1", "m2", "m3"],
        "recalled_skills": ["s1"],
        "intent_signals": {"file_domains": ["d1"]},
        "correction_count": 0,
        "ts": 1000.0,
        "end_ts": 2000.0,
    }
    c = IntentKnowledgeCombo("a", memory_ids=["m1", "m5"], skills=["s1"], file_domains=["d1"])
    m = _session_metrics(sess, c)
    assert m.actual_recall_steps == 4
    assert m.combo_recall_steps == 1
    assert m.delta_recall_steps == 3.0
    assert m.hit_rate == 3 / 4


def test_session_metrics_without_combo():
    sess = {
        "session_id": "s2",
        "intent_proxy": "z",
        "recalled_memory_ids": ["m1"],
        "recalled_skills": [],
        "intent_signals": {},
        "correction_count": 0,
        "ts": 1000.0,
        "end_ts": 1500.0,
    }
    m = _session_metrics(sess, None)
    assert m.combo_recall_steps == m.actual_recall_steps
    assert m.delta_recall_steps == 0.0


def test_evaluate_returns_candidate_when_delta_positive():
    sessions = [
        {
            "session_id": f"s{i}",
            "intent_proxy": "a",
            "recalled_memory_ids": [f"m{i}", f"m{i+1}"],
            "recalled_skills": ["s1"],
            "intent_signals": {"file_domains": ["d1"]},
            "correction_count": 0,
            "ts": float(i),
            "end_ts": float(i + 10),
        }
        for i in range(20)
    ]
    c = IntentKnowledgeCombo("a", memory_ids=["m1", "m5"], skills=["s1"], file_domains=["d1"])
    result = evaluate_fn(sessions, {"a": c}, min_combo_size=1)
    assert result["verdict"] == "candidate"
    assert result["delta_ci_low"] > 0
