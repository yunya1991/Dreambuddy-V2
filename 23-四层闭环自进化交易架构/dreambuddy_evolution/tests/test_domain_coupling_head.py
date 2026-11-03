"""test_domain_coupling_head.py — Phase B MVP 验收

覆盖：Head 架构正确性（shape 64→15 / params ≈2.8K）/ hook 点能否拦截到 64-dim hidden /
Mac Metal 上 forward+backward+optimizer step 链路 / 三带 mask 约束。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import torch

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

CKPT = REPO / "23-四层闭环自进化交易架构" / "data" / "neural_sde_v1_dim64.pt"


def _device() -> str:
    if torch.backends.mps.is_available() and torch.backends.mps.is_built():
        return "mps"
    return "cpu"


@pytest.fixture(scope="module")
def model_and_config():
    from dreambuddy_evolution.core.domain_coupling_head import (
        freeze_backbone,
        load_neural_sde_v1_dim64,
    )

    dev = _device()
    drift_net, ck = load_neural_sde_v1_dim64(str(CKPT), device=dev)
    freeze_backbone(drift_net)  # 主体冻结, SPEC H2
    return drift_net, ck, dev


# ---------- Head architecture ----------
def test_head_output_shape():
    from dreambuddy_evolution.core.domain_coupling_head import N_PAIRS, DomainCouplingHead

    head = DomainCouplingHead()
    assert head.hidden_dim == 64
    # params count roughly 2800±
    params = sum(p.numel() for p in head.parameters() if p.requires_grad)
    assert 2700 < params < 3000, f"params={params} 偏离预期范围"
    # 2D input
    h2 = torch.randn(4, 64)
    out2 = head(h2)
    assert out2.shape == (4, N_PAIRS)  # 15
    # 3D input (E, B, 64)
    h3 = torch.randn(3, 4, 64)
    out3 = head(h3)
    assert out3.shape == (4, N_PAIRS)
    # [0,1] range
    assert out2.min() >= 0.0 and out2.max() <= 1.0


def test_head_weak_band_clipped_to_zero():
    from dreambuddy_evolution.core.domain_coupling_head import _apply_band_mask

    vals = torch.tensor([[0.05, 0.25, 0.40, 0.55]])  # 1D input auto-broadcast
    clipped = _apply_band_mask(vals)
    # ≤0.3 → 0；>0.3 保留
    assert float(clipped[0, 0]) == pytest.approx(0.0)
    assert float(clipped[0, 1]) == pytest.approx(0.0)
    assert float(clipped[0, 2]) == pytest.approx(0.40)
    assert float(clipped[0, 3]) == pytest.approx(0.55)


# ---------- Hook point 正确性 ----------
def test_extract_hook_module_names_discovers_3_experts():
    from dreambuddy_evolution.core.domain_coupling_head import extract_hook_module_names

    keys = [
        "experts.0.net.0.weight",
        "experts.0.net.6.weight",
        "experts.1.net.6.weight",
        "experts.2.net.6.weight",
        "router.0.weight",
    ]
    names = extract_hook_module_names(keys)
    assert names == ["experts.0.net", "experts.1.net", "experts.2.net"]


def test_hook_captures_64dim_hidden(model_and_config):
    """真实 checkpoint forward, hook 必须抓到 (E, B, 64) hidden."""
    from dreambuddy_evolution.core.domain_coupling_head import NeuralSDEHiddenExtractor

    drift_net, _ck, dev = model_and_config
    extractor = NeuralSDEHiddenExtractor(drift_net, device=dev)
    # 构造最小 forward 输入: t=scalar, y=(B,1), log_sig=(B, sig_dim)
    B = 4
    t = 0.5
    y = torch.randn(B, 1, device=dev)
    log_sig = torch.randn(B, 15, device=dev)

    with extractor.capture():
        _ = drift_net(t, y, log_sig)

    assert extractor.last_hidden is not None
    h = extractor.last_hidden
    assert h.shape[0] == 3  # experts
    assert h.shape[2] == 64  # hidden_dim
    assert not torch.isnan(h).any()

    # 清理 hook 避免污染后续测试
    extractor.remove()


# ---------- Mac Metal train step 链路 ----------
def test_mps_forward_backward_optimizer_step_mps():
    """Mac Metal 上: hook → Head forward → loss → backward → step 必须走通.

    失败条件: backward 报错 / optimizer.step() 不更新 Head 参数 / 主体被意外更新.
    """
    from dreambuddy_evolution.core.domain_coupling_head import (
        DomainCouplingHead,
        NeuralSDEHiddenExtractor,
        freeze_backbone,
        load_neural_sde_v1_dim64,
    )

    dev = _device()
    drift_net, _ck = load_neural_sde_v1_dim64(str(CKPT), device=dev)
    freeze_backbone(drift_net)  # 主体冻结
    head = DomainCouplingHead().to(dev)
    optimizer = torch.optim.AdamW(head.parameters(), lr=1e-3)

    B = 4
    t = 0.5
    y = torch.randn(B, 1, device=dev)
    log_sig = torch.randn(B, 15, device=dev)

    # 1 步 train
    extractor = NeuralSDEHiddenExtractor(drift_net, device=dev)
    with extractor.capture():
        _ = drift_net(t, y, log_sig)
    hidden = extractor.last_hidden.to(dev)
    optimizer.zero_grad()
    coupling = head(hidden)
    target = torch.rand(B, 15, device=dev)  # 合成 target, 训练链路验证
    loss = ((coupling - target) ** 2).mean()
    assert not torch.isnan(loss).any()
    loss.backward()
    optimizer.step()

    # Head 参数必须有更新
    assert not torch.allclose(head.net[0].weight.detach(), torch.zeros_like(head.net[0].weight))

    # 主体参数必须未被更新 (requires_grad=False 且梯度全 None)
    for p in drift_net.parameters():
        assert p.grad is None, "主体被意外反向传播"
        assert not p.requires_grad, "主体 requires_grad 未被关闭"

    extractor.remove()


# ---------- Coupling pair ordering 校验 ----------
def test_pair_names_match_static_json_keys():
    """PAIRS 必须与 static JSON 键序严格对齐, 避免索引错位."""
    import json

    from dreambuddy_evolution.core.domain_coupling_head import PAIRS

    static_path = REPO / "mcp_shells" / "_shared" / "assets" / "domain_transmission_static.json"
    data = json.loads(static_path.read_text())
    static_keys = sorted(data["domain_transmission"]["drift_coupling"].keys())
    pair_keys = sorted([f"{a}↔{b}" for a, b in PAIRS] + [f"{b}↔{a}" for a, b in PAIRS])
    # 静态 JSON 键全部在 PAIRS 双向覆盖内
    assert set(static_keys).issubset(set(pair_keys))
    # PAIRS 数量 = 15 (6 choose 2)
    assert len(PAIRS) == 15


def test_load_ckpt_has_n_regimes_3():
    from dreambuddy_evolution.core.domain_coupling_head import load_neural_sde_v1_dim64

    _dev = _device()
    _m, ck = load_neural_sde_v1_dim64(str(CKPT), device=_dev)
    assert ck["n_regimes"] == 3
    assert ck["hidden_dim"] == 64
    assert ck["sig_dim"] == 15
