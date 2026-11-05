"""E3 coupling 反事实验证测试（SPEC-EMERGENCE-EVOLUTION v0.5 §4 E3）。

覆盖：
  - 真耦合合成数据 → coupled MAE 显著低于 ablated，verdict=e3_candidate
  - 无耦合数据 → verdict ∈ {inconclusive, falsified}
  - 错误方向耦合（β 原型教训回归）→ falsified（p<0.05 且方向为负）
  - 样本不足 / 方差退化 → insufficient_data（如实返回，不伪造）
  - retrain shadow：落盘 head+meta、不碰生产 static JSON / ckpt
"""

from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

import numpy as np
import pytest

_E3_DIR = Path(__file__).resolve().parents[1] / "experiments" / "e3_coupling"
if str(_E3_DIR) not in sys.path:
    sys.path.insert(0, str(_E3_DIR))

import coupling_counterfactual as cc  # noqa: E402
import retrain_head_shadow as rhs  # noqa: E402

DOMAINS = ["cognition", "rea", "search", "semantic", "data", "eval"]


# ---------- 基础工具 ----------


def test_pair_index_matches_itertools_order():
    """本地 PAIRS 顺序必须与 23 域 domain_coupling_head.PAIRS（itertools.combinations）一致。"""
    expected = list(itertools.combinations(DOMAINS, 2))
    assert list(cc.PAIRS) == expected
    assert cc.pair_index("rea", "data") == expected.index(("rea", "data"))
    # 反向查找等价
    assert cc.pair_index("data", "rea") == expected.index(("rea", "data"))


def test_load_series_orders_by_timestamp(tmp_path):
    p = tmp_path / "s.jsonl"
    rows = [
        {
            "timestamp": "2026-11-03T12:00:02+00:00",
            "input": {"domain_states": {d: {"psi": 0.2, "drift": "stable"} for d in DOMAINS}},
        },
        {
            "timestamp": "2026-11-03T12:00:01+00:00",
            "input": {"domain_states": {d: {"psi": 0.1, "drift": "stable"} for d in DOMAINS}},
        },
    ]
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    series = cc.load_domain_state_series([p])
    assert len(series) == 2
    assert series[0]["state"][0] == pytest.approx(0.1)  # 早的在前
    assert series[1]["state"][0] == pytest.approx(0.2)


def test_build_transition_pairs():
    rng = np.random.default_rng(0)
    series = [{"ts": str(i), "state": rng.normal(size=6)} for i in range(5)]
    X, Y = cc.build_transition_pairs(series)
    assert X.shape == (4, 6) and Y.shape == (4, 6)
    np.testing.assert_allclose(Y[0], series[1]["state"])


# ---------- 反事实评估核心 ----------


def _simulate(n: int, cross: float, seed: int = 7, noise: float = 0.02):
    """生成一阶马尔可夫域状态序列：x_{t+1} = A x_t + noise。

    A 对角 0.5、非对角 cross（对称块特征值 0.5±cross，cross=0.4 时 max=0.9<1 平稳；
    对角过高+对称耦合会非平稳爆炸）。
    信噪比必须 >1 置换检验才有功效（低信噪下 L1 误差被噪声主导，效应检不出）。
    """
    rng = np.random.default_rng(seed)
    A = np.eye(6) * 0.5
    # 对称互相影响：生产 static JSON 的 drift_coupling 是无向 "↔" 矩阵，
    # 反事实模型按对称方式注入跨域项，真值也必须是对称耦合，否则源域被
    # 反向噪声项污染（TDD 回归：方向性真值会让正确无向 c 反而判负）
    A[0, 1] = A[1, 0] = cross  # cognition ↔ rea
    A[2, 4] = A[4, 2] = cross  # search ↔ data
    A[3, 5] = A[5, 3] = cross  # semantic ↔ eval
    states = np.zeros((n + 1, 6))
    for t in range(n):
        states[t + 1] = A @ states[t] + rng.normal(scale=noise, size=6)
    X, Y = states[:-1], states[1:]
    coupling = np.zeros(15)
    for a, b in (("cognition", "rea"), ("data", "search"), ("eval", "semantic")):
        coupling[cc.pair_index(a, b)] = abs(cross)
    return X, Y, coupling


def test_evaluate_true_coupling_is_candidate():
    X, Y, coupling = _simulate(n=400, cross=0.4)
    res = cc.evaluate_counterfactual(X, Y, coupling, min_pairs=20, n_perm=2000, seed=1)
    assert res["verdict"] == "e3_candidate"
    assert res["direction_positive"] is True
    assert res["p_value"] < 0.05
    assert res["mae_coupled"] < res["mae_ablated"]
    assert res["median_improvement"] > 0


def test_evaluate_no_coupling_not_candidate():
    X, Y, _ = _simulate(n=400, cross=0.0)
    # 喂入非零 coupling（模型声称有耦合，但数据没有）
    coupling = np.full(15, 0.4)
    res = cc.evaluate_counterfactual(X, Y, coupling, min_pairs=20, n_perm=2000, seed=1)
    assert res["verdict"] in ("inconclusive", "falsified")
    if res["verdict"] == "falsified":
        assert res["direction_positive"] is False


def test_evaluate_wrong_direction_is_falsified():
    """β 原型教训回归：p 显著但方向为负必须判 falsified，不是 candidate。"""
    X, Y, coupling = _simulate(n=400, cross=0.4)
    bad = -coupling  # 方向全反
    res = cc.evaluate_counterfactual(X, Y, bad, min_pairs=20, n_perm=2000, seed=1)
    assert res["verdict"] == "falsified"
    assert res["direction_positive"] is False
    assert res["p_value"] < 0.05


def test_insufficient_data_few_pairs():
    rng = np.random.default_rng(0)
    X = rng.normal(size=(5, 6))
    Y = rng.normal(size=(5, 6))
    res = cc.evaluate_counterfactual(X, Y, np.full(15, 0.5), min_pairs=20)
    assert res["verdict"] == "insufficient_data"
    assert res["n_pairs"] == 5


def test_degenerate_variance_is_insufficient():
    """real JSONL 现状回归：psi 全常数 → 无信号，必须如实 insufficient_data。"""
    X = np.tile(np.array([0.0, 0.0, 1.0, 0.0, 0.444, 1.0]), (100, 1))
    Y = X.copy()
    res = cc.evaluate_counterfactual(X, Y, np.full(15, 0.5), min_pairs=20)
    assert res["verdict"] == "insufficient_data"
    assert "degenerate" in res.get("reason", "")


def test_evaluate_failopen_on_bad_input():
    res = cc.evaluate_counterfactual(None, None, None)
    assert res["verdict"] == "insufficient_data"


# ---------- E6 需求单联动 ----------


def test_insufficient_data_files_gap(tmp_path, monkeypatch):
    gaps_path = tmp_path / "capability_gaps.jsonl"
    import capability_gaps as cg

    monkeypatch.setattr(cg, "DEFAULT_GAPS_PATH", gaps_path)
    res = {"verdict": "insufficient_data", "n_pairs": 3, "reason": "n_pairs<20"}
    ok = cc.file_gap_if_insufficient(res, gaps_path=gaps_path)
    assert ok is True
    gaps = cg.load_gaps(gaps_path)
    assert len(gaps) == 1
    assert gaps[0]["gap_type"] == "data"
    assert gaps[0]["created_by"] == "e3_counterfactual"
    assert gaps[0]["status"] == "open"


def test_gap_not_filed_when_sufficient(tmp_path):
    res = {"verdict": "e3_candidate"}
    assert cc.file_gap_if_insufficient(res, gaps_path=tmp_path / "g.jsonl") is False


# ---------- retrain shadow ----------


class _FakeTensor:
    def __init__(self, vals):
        self._vals = list(vals)

    def tolist(self):
        return list(self._vals)


class _FakeHead:
    """模拟 DomainCouplingHead：state_dict / save 兼容。"""

    def __init__(self):
        self.saved_to: list[str] = []

    def state_dict(self):
        return {"net.0.weight": _FakeTensor([0.1, 0.2])}


def test_retrain_shadow_saves_head_and_meta(tmp_path, monkeypatch):
    art = tmp_path / "artifacts"
    fake_result = {
        "coupling_15d": [0.5] * 15,
        "final_loss": 0.004,
        "loss_curve": [0.1, 0.05, 0.004],
        "target_source": "phaseC_jsonl_150samples",
        "input_source": "real_btc_1h_36factors",
        "n_steps": 120,
        "pseudo_target_loaded": True,
        "inferred": True,
        "input_meta": {"regime_counts": {"0": 40, "1": 30, "2": 26}},
    }
    monkeypatch.setattr(rhs, "_train_and_infer", lambda **kw: (fake_result, _FakeHead()))
    out = rhs.retrain_shadow(artifacts_dir=art, n_steps=120, seed=42)
    assert out["status"] == "ok"
    assert (art / "coupling_head_e3_shadow.pt").exists()
    meta = json.loads((art / "retrain_meta.json").read_text(encoding="utf-8"))
    assert meta["n_steps"] == 120
    assert meta["shadow"] is True
    assert meta["target_source"] == "phaseC_jsonl_150samples"
    assert len(meta["coupling_15d"]) == 15


def test_retrain_shadow_never_touches_production(tmp_path, monkeypatch):
    """生产 static JSON 与 ckpt 的 mtime/内容在重训前后必须不变。"""
    static_json = tmp_path / "domain_transmission_static.json"
    static_json.write_text('{"domain_transmission": {"drift_coupling": {}}}', encoding="utf-8")
    before = static_json.read_bytes()
    monkeypatch.setattr(rhs, "STATIC_JSON", static_json)
    monkeypatch.setattr(
        rhs,
        "_train_and_infer",
        lambda **kw: (
            {"coupling_15d": [0.9] * 15, "final_loss": 0.001, "loss_curve": [0.001]},
            _FakeHead(),
        ),
    )
    rhs.retrain_shadow(artifacts_dir=tmp_path / "art")
    assert static_json.read_bytes() == before


def test_retrain_shadow_failopen_on_train_error(tmp_path, monkeypatch):
    def _boom(**kw):
        raise RuntimeError("ckpt missing")

    monkeypatch.setattr(rhs, "_train_and_infer", _boom)
    out = rhs.retrain_shadow(artifacts_dir=tmp_path / "art")
    assert out["status"] == "error"
    assert "ckpt missing" in out["reason"]
