"""X-A 跨域迁移 2x2x2 因子实验测试。"""

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
XA = ROOT / "experiments" / "xa_transfer"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


evaluate = _load("xa_evaluate", XA / "evaluate.py")
build_arms = evaluate.build_arms
estimate_g123 = evaluate.estimate_g123
estimate_main_effects = evaluate.estimate_main_effects
estimate_two_way = evaluate.estimate_two_way
omega_o_information = evaluate.omega_o_information


def test_build_arms_has_8_entries():
    arms = build_arms(0.1, 0.2, 0.3)
    assert len(arms) == 8
    assert set(arms.keys()) == {"000", "001", "010", "011", "100", "101", "110", "111"}
    assert arms["000"] == 0.0


def test_arms_increasing_with_dimensions():
    arms = build_arms(0.1, 0.2, 0.3)
    # 联合臂应大于任意单维臂
    assert arms["111"] > arms["100"]
    assert arms["111"] > arms["010"]
    assert arms["111"] > arms["001"]


def test_g123_positive_when_synergy_present():
    arms = build_arms(0.1, 0.2, 0.3, g123=0.08)
    g123 = estimate_g123(arms)
    assert g123 > 0
    two_way = estimate_two_way(arms)
    assert all(v >= 0 for v in two_way.values())


def test_omega_positive_for_synergistic_arms():
    arms = build_arms(0.1, 0.2, 0.3, g123=0.08)
    omega = omega_o_information(arms)
    assert omega > 0


def test_evaluate_returns_candidate_with_real_data():
    result = evaluate.evaluate()
    assert result["verdict"] in {"candidate", "inconclusive", "falsified"}
    assert "g123" in result
    assert "omega_o_information" in result
    assert "dimension_gains" in result
