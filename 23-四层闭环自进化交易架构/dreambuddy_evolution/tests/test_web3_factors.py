"""Web3 链上小币因子的注册约束测试。

背景：drift_net 的 cross-attention 因子投影宽度由 ckpt 的 exogenous_factor_dim
决定（当前 36）。Web3 因子默认关闭，避免因子矩阵 (N,46) 与 ckpt q_proj 宽度不一致。
开启开关 EVO_WEB3_FACTORS=1 后才追加，且训练/推理两侧必须同步。
"""

from __future__ import annotations

import importlib

MOD = "dreambuddy_evolution.core.exogenous_data_bridge"


def test_default_registry_stays_36():
    """默认不改变既有 36 因子注册（ckpt 兼容）。"""
    from dreambuddy_evolution.core import exogenous_data_bridge as m

    assert m.web3_factors_enabled() is False
    assert len(m.CROSS_ATTENTION_FACTOR_METRICS) == 36


def test_web3_factor_names_unique_and_dimensions_known():
    from dreambuddy_evolution.core import exogenous_data_bridge as m

    assert len(m.WEB3_FACTOR_METRICS) == 6
    names = [entry[2] for entry in m.WEB3_FACTOR_METRICS]
    assert len(names) == len(set(names))
    base_names = {entry[2] for entry in m.CROSS_ATTENTION_FACTOR_METRICS}
    assert not (set(names) & base_names)
    # 只落在既有维度，避免 head 数量变化
    assert {entry[3] for entry in m.WEB3_FACTOR_METRICS} <= {"C1", "C2", "C3", "C7"}
    # 全部来自 18 域聚合条
    assert {entry[0] for entry in m.WEB3_FACTOR_METRICS} == {"web3_market"}


def test_enabled_appends_without_changing_dimension_order(monkeypatch):
    monkeypatch.setenv("EVO_WEB3_FACTORS", "1")
    from dreambuddy_evolution.core import exogenous_data_bridge as m

    base_dims = m.get_factor_dimensions()
    try:
        m2 = importlib.reload(m)
        assert len(m2.CROSS_ATTENTION_FACTOR_METRICS) == 42
        assert m2.web3_factors_enabled() is True
        # 维度顺序不变 → factor_head_mask 的 head 语义不漂移
        assert m2.get_factor_dimensions() == base_dims
        mask = m2.build_factor_head_mask(override_path="/tmp/_no_override_web3_test.json")
        assert mask.shape == (len(base_dims), 42)
    finally:
        monkeypatch.delenv("EVO_WEB3_FACTORS", raising=False)
        importlib.reload(m)
