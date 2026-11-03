"""test_real_market_features.py — Phase D 真实市场输入 + 状态敏感性验收.

覆盖:
  T1 批次形状 / 归一化 / regime one-hot / 资金流覆盖度 (合成数据, 秒级)
  T2 regime 分层抽样保证三制度都有样本
  T3 数据缺失 FAIL-OPEN 返回 None
  T4 真实 ckpt + 真实 BTC 1h: hidden 随真实 regime 变化 (输入侧状态因果)
  T5 export_coupling_json 向后兼容 (15 对 + lags_min 保留 + 新增字段)

不触发 HMM (T1/T2 显式传 regime_labels; T4 允许回退全 0 但仍验证 hidden 变化).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

DATA_DIR = REPO / "23-四层闭环自进化交易架构" / "data"
CKPT = DATA_DIR / "neural_sde_v1_dim64.pt"
CLOSES = DATA_DIR / "btc_closes_1h.json"
FACTORS = DATA_DIR / "exogenous_factors_36.json"


def _fake_meta(sig_dim: int = 15) -> dict:
    return {
        "price_mean": 100.0,
        "price_std": 5.0,
        "log_sig_mean": np.zeros(sig_dim),
        "log_sig_std": np.ones(sig_dim),
        "sig_dim": sig_dim,
        "n_regimes": 3,
        "n_step": 32,
        "sig_depth": 3,
        "seq_len": 64,
        # 仅用于推导 log_sig_input_dim (q_proj 输入宽度)
        "drift_net_state_dict": {"experts.0.q_proj.weight": np.zeros((64, sig_dim))},
    }


def _write_inputs(tmp_path: Path, n: int = 400) -> tuple[Path, Path]:
    closes = 100.0 + 5.0 * np.sin(np.linspace(0, 6, n)) + np.linspace(0, 2, n)
    factors = np.zeros((n, 36), dtype=float)
    factors[-100:, 0] = np.linspace(-1, 1, 100)  # etf_total_flow
    factors[-100:, 1] = np.linspace(-0.01, 0.01, 100)  # funding_rate
    factors[-100:, 4] = np.linspace(-100, 100, 100)  # exchange_inflow_24h
    closes_path = tmp_path / "closes.json"
    factors_path = tmp_path / "factors.json"
    closes_path.write_text(json.dumps(closes.tolist()))
    factors_path.write_text(json.dumps(factors.tolist()))
    return closes_path, factors_path


def _segment_labels(n: int) -> np.ndarray:
    labels = np.zeros(n, dtype=int)
    labels[n // 3 : 2 * n // 3] = 1
    labels[2 * n // 3 :] = 2
    return labels


def test_batch_shape_and_normalization(tmp_path):
    from dreambuddy_evolution.core.real_market_features import build_real_market_batch

    closes_path, factors_path = _write_inputs(tmp_path)
    batch = build_real_market_batch(
        ckpt_meta=_fake_meta(),
        closes_path=closes_path,
        factors_path=factors_path,
        n_windows=30,
        regime_labels=_segment_labels(400),
        seed=7,
    )
    assert batch is not None
    assert batch.n_samples == 30
    assert batch.y.shape == (30, 1)
    assert batch.log_sig.shape[1] == 15
    assert batch.regime.shape == (30, 3)
    assert np.allclose(batch.regime.sum(axis=1), 1.0)
    assert batch.factors.shape == (30, 36)
    # price z-score 与 ckpt 统计一致
    assert abs(batch.meta["price_z_range"][1] - float(batch.y.max())) < 1e-3
    # 资金流列只在最后 100 行非零 → 覆盖度 0.25
    for name in ("etf_total_flow", "funding_rate", "exchange_inflow_24h"):
        assert batch.meta["flow_factor_coverage"][name] == pytest.approx(0.25, abs=0.01)
    assert set(batch.state_buckets()) == {"regime", "vol", "flow"}


def test_stratified_selection_covers_all_regimes(tmp_path):
    from dreambuddy_evolution.core.real_market_features import build_real_market_batch

    closes_path, factors_path = _write_inputs(tmp_path)
    batch = build_real_market_batch(
        ckpt_meta=_fake_meta(),
        closes_path=closes_path,
        factors_path=factors_path,
        n_windows=30,
        regime_labels=_segment_labels(400),
        seed=7,
    )
    assert set(np.unique(batch.regime_label).tolist()) == {0, 1, 2}
    counts = np.bincount(batch.regime_label, minlength=3)
    assert counts.tolist() == [10, 10, 10]


def test_missing_closes_returns_none(tmp_path):
    from dreambuddy_evolution.core.real_market_features import build_real_market_batch

    assert (
        build_real_market_batch(ckpt_meta=_fake_meta(), closes_path=tmp_path / "nope.json") is None
    )


@pytest.mark.skipif(not (CKPT.exists() and CLOSES.exists()), reason="真实 ckpt / BTC 1h 数据缺失")
def test_hidden_varies_with_real_regime():
    """真实市场输入下 hidden 随 regime 变化 (输入侧状态因果成立)."""
    import torch

    from dreambuddy_evolution.core.domain_coupling_head import (
        NeuralSDEHiddenExtractor,
        load_neural_sde_v1_dim64,
    )
    from dreambuddy_evolution.core.real_market_features import build_real_market_batch

    drift_net, ck = load_neural_sde_v1_dim64(str(CKPT), device="cpu")
    batch = build_real_market_batch(ckpt_meta=ck, closes_path=CLOSES, n_windows=48, seed=42)
    assert batch is not None
    # 与训练分布同源: log_sig z-score 不应发散
    assert batch.meta["log_sig_z_abs_max"] < 8.0

    y = torch.tensor(batch.y, dtype=torch.float32)
    ls = torch.tensor(batch.log_sig, dtype=torch.float32)
    rg = torch.tensor(batch.regime, dtype=torch.float32)
    fc = torch.tensor(batch.factors[:, :, None], dtype=torch.float32)
    extractor = NeuralSDEHiddenExtractor(drift_net, device="cpu")
    with extractor.capture():
        _ = drift_net(0.5, y, ls, rg, None, None, fc)
    hidden = extractor.last_hidden.mean(dim=0).detach().numpy()  # (N, 64)
    extractor.remove()

    # 1) 不同窗口 hidden 不是常量
    assert float(hidden.std(axis=0).mean()) > 1e-4
    # 2) 跨 regime 质心距离显著大于 0
    labels = batch.regime_label
    centroids = [hidden[labels == r].mean(axis=0) for r in np.unique(labels)]
    if len(centroids) > 1:
        max_l2 = max(
            float(np.linalg.norm(a - b))
            for i, a in enumerate(centroids)
            for b in centroids[i + 1 :]
        )
        assert max_l2 > 1e-3, f"跨 regime hidden 质心距离过小: {max_l2}"


def test_export_json_backward_compatible(tmp_path):
    from dreambuddy_evolution.core.domain_coupling_head import PAIRS
    from dreambuddy_evolution.core.train_and_export_coupling import export_coupling_json

    tmp_json = tmp_path / "domain_transmission_static.json"
    old_pairs = {f"{a}↔{b}": {"coupling": 0.5, "lags_min": 30} for a, b in PAIRS}
    first_key = f"{PAIRS[0][0]}↔{PAIRS[0][1]}"
    old_pairs[first_key]["lags_min"] = 45  # 验证 lags_min 保留
    tmp_json.write_text(
        json.dumps(
            {
                "domain_transmission": {"drift_coupling": old_pairs},
                "note": "old",
            }
        )
    )

    result = {
        "coupling_15d": [0.2] * 15,
        "n_steps": 10,
        "final_loss": 0.01,
        "inferred": True,
        "pseudo_target_loaded": True,
        "target_source": "phaseC_jsonl_85samples",
        "target_n_samples": 85,
        "input_source": "real_btc_1h_36factors",
        "input_meta": {"n_windows": 48, "regime_counts": {"0": 16, "1": 16, "2": 16}},
        "regime_conditional": {"bull": [0.2] * 15},
        "state_sensitivity": {"regime": {"mean_abs_delta": 0.001}},
    }
    export_coupling_json(result, static_json=tmp_json)

    data = json.loads(tmp_json.read_text())
    pairs = data["domain_transmission"]["drift_coupling"]
    assert len(pairs) == 15
    assert pairs[first_key]["lags_min"] == 45
    assert all("coupling" in v and "lags_min" in v for v in pairs.values())
    assert data["input_source"] == "real_btc_1h_36factors"
    assert data["input_stats"]["n_windows"] == 48
    assert data["regime_conditional_coupling"]["bull"][0] == 0.2
    assert data["state_sensitivity"]["regime"]["mean_abs_delta"] == 0.001
    assert data["head_training"]["input_source"] == "real_btc_1h_36factors"
    assert data["head_training"]["n_input_windows"] == 48
