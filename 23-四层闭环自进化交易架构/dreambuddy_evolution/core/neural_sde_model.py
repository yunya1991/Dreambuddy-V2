"""
Phase 2.3: Neural SDE 模型 — 连续时间动态建模 (路径依赖 SDE 升级版)
SPEC-AGI升级蓝图.md §4.2.3 / HC-AGI-13 / spec neural-sde-architecture-upgrade

核心: dS = fθ(S,t, log_sig(history))dt + gφ(S,t)dW
  - drift_net fθ: 学习价格漂移趋势 (输入 = [S_t, sin(t), cos(t), log_signature])
  - diffusion_net gφ: 学习波动率（正值约束, 输入 = [S_t, sin(t), cos(t)]）

蓝本: Stable-Neural-SDEs (ICLR 2024) + Lyons 粗路径理论 (signature 是 SDE 解的结构性必需对象)

FAIL-OPEN (4 级 + 2.5/2.7 降级点):
  Level 1: torchsde.sdeint() + path-signature drift
  Level 2: 手写 Euler-Maruyama + path-signature drift
  Level 2.5: path-signature 计算失败 → log_sig pad zeros (退化马尔可夫), 仍走 EM
  Level 2.7: history 长度 < N_step → log_sig pad zeros, 退化马尔可夫
  Level 3: GARCH(1,1) (HC-AGI-13, 样本 < 1000)
  Level 4: GBM (最后兜底, 在 deep_reasoning_engine 中)

参考模式: exit_rl_policy.py CQLTrainer 的延迟导入 / _available 标志 / save-load
"""
from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)

# 延迟导入 torch（允许无 torch 时模块仍可加载）
try:
    import torch
    import torch.nn as nn

    # 修复: PyTorch OpenMP tanh_kernel 在 Apple Silicon 多线程下 SIGSEGV (Sleef_tanhf4_u10)
    # 设置单线程避免 OpenMP 并行冲突，不影响 Neural SDE 性能（路径采样本身已向量化）
    torch.set_num_threads(1)

    _TORCH_AVAILABLE = True
except ImportError:  # noqa: BLE001
    _TORCH_AVAILABLE = False
    logger.debug("[FO-AGI-03] torch 不可用, NeuralSDEModel 将降级")

# 尝试导入 torchsde（可选加速）
try:
    import torchsde  # type: ignore

    _TORCHSDE_AVAILABLE = True
except Exception:  # noqa: BLE001
    _TORCHSDE_AVAILABLE = False
    logger.debug("[FO-AGI-03] torchsde 不可用, 使用手写 Euler-Maruyama 积分")

# 从 SignatureEngine 导入三级降级签名计算 + 标志暴露 (TDD-004 monkeypatch 用)
try:
    from dreambuddy_evolution.core.signature_engine import (
        SignatureEngine,
        _SIGNATORY_AVAILABLE,
        _ESIG_AVAILABLE,
    )
except Exception:  # noqa: BLE001
    SignatureEngine = None  # type: ignore
    _SIGNATORY_AVAILABLE = False
    _ESIG_AVAILABLE = False
    logger.warning("[FO-AGI-02] SignatureEngine 不可用, log_sig 将 pad zeros")

# HC-AGI-13: 训练样本阈值
MIN_SAMPLES_FOR_ACTIVATION = 1000

# 模型超参默认值
DEFAULT_HIDDEN_DIM = 64
DEFAULT_DIFFUSION_HIDDEN = 32
DEFAULT_DRIFT_CLIP = 2.0
DEFAULT_DIFFUSION_FLOOR = 0.001

# 路径依赖 SDE 升级参数 (spec §3.2)
# SignatureEngine depth=3 实际输出维度取决于后端:
#   - numpy 降级: 6 维 (1+2+3)
#   - esig (当前环境): 15 维 (2D 增广 depth=3 几何级数 1+2+4+8)
#   - signatory logsignature: 9 维 (free Lie algebra)
# 不截断: DEFAULT_SIG_DIM 取上限 15, 兼容所有后端 (numpy 6 维时 pad zeros)
DEFAULT_SIG_DIM = 15      # log-signature 维度 (不截断 SignatureEngine 输出)
DEFAULT_N_STEP = 32       # 最近窗口长度
DEFAULT_SIG_DEPTH = 3     # 签名深度 (HC-AGI-11 ≤5)


class _DriftNet(nn.Module if _TORCH_AVAILABLE else object):
    """Drift 网络 fθ(S_t, t) → 标量漂移 (旧版, 马尔可夫 SDE, 保留向后兼容)."""

    def __init__(self, hidden_dim: int = DEFAULT_HIDDEN_DIM, clip: float = DEFAULT_DRIFT_CLIP):
        if not _TORCH_AVAILABLE:
            return
        super().__init__()
        # 输入: [S_t, sin(2πt/T), cos(2πt/T)] = 3维
        self.net = nn.Sequential(
            nn.Linear(3, hidden_dim),
            nn.Tanh(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.Tanh(),
            nn.Linear(hidden_dim, 1),
        )
        self.clip = clip

    def forward(self, t: "torch.Tensor", y: "torch.Tensor") -> "torch.Tensor":
        if not _TORCH_AVAILABLE:
            return torch.zeros(y.size(0), 1)
        # 时间特征
        t_batch = torch.full((y.size(0), 1), float(t), device=y.device)
        time_features = torch.cat([torch.sin(2 * math.pi * t_batch), torch.cos(2 * math.pi * t_batch)], dim=-1)
        x = torch.cat([y, time_features], dim=-1)
        out = self.net(x)
        return torch.tanh(out) * self.clip  # tanh 裁剪防爆炸


class _PathSignatureDriftNet(nn.Module if _TORCH_AVAILABLE else object):
    """路径依赖 SDE 的 Drift 网络 (TDD-001).

    输入: [S_t, sin(2πt/T), cos(2πt/T), log_signature(sig_dim)] = (3 + sig_dim) 维
    输出: 标量 drift, 经 tanh 裁剪防爆炸

    理论依据: Lyons 粗路径理论 — signature 是 SDE 解的结构性必需对象
    (跨学科 Agent-3, 公理级). log_sig=None 或 zeros 时退化到马尔可夫 (FAIL-OPEN).

    P1 集成 (PLAN-exogenous-integration.md §三):
      exogenous_dim (默认 0 = 关闭, 向后兼容): > 0 时 drift_net 输入追加
      exogenous_dim 维外生力量向量 (drift_net.forward(exogenous=...)).
      exogenous=None → pad zeros (FAIL-OPEN, 行为等价 exogenous_dim=0).
    """

    def __init__(
        self,
        hidden_dim: int = DEFAULT_HIDDEN_DIM,
        sig_dim: int = DEFAULT_SIG_DIM,
        clip: float = DEFAULT_DRIFT_CLIP,
        n_regimes: int = 3,
        n_transition: int = 0,
        dropout: float = 0.0,
        exogenous_dim: int = 0,
        use_cross_attention: bool = False,
        exogenous_factor_dim: int = 0,
        cross_attn_dim: int = 32,
        cross_attn_heads: int = 4,
        factor_head_mask: Optional["torch.Tensor"] = None,
    ):
        if not _TORCH_AVAILABLE:
            return
        super().__init__()
        self.sig_dim = int(sig_dim)
        self.clip = clip
        self.n_regimes = int(n_regimes)
        # P0.2: transition vector 维度 (Q[current_regime]), 0 = 旧模型无 transition
        self.n_transition = int(n_transition)
        # P3: dropout 概率 (0.0 = 旧模型无正则, 向后兼容)
        self.dropout = float(dropout)
        # P1: exogenous_dim 维外生力量向量 (0 = 关闭, 向后兼容; 9 = 标准 9 维)
        self.exogenous_dim = int(exogenous_dim)
        # P1+: Cross-Attention 外生因子注入
        self.use_cross_attention = bool(use_cross_attention)
        self.exogenous_factor_dim = int(exogenous_factor_dim) if self.use_cross_attention else 0
        self.cross_attn_dim = int(cross_attn_dim) if self.use_cross_attention else 0
        self.cross_attn_heads = int(cross_attn_heads) if self.use_cross_attention else 0

        if self.use_cross_attention and self.exogenous_factor_dim > 0:
            # 延迟导入 cross_attention 组件
            from dreambuddy_evolution.core.cross_attention import (
                FactorEncoder,
                MultiHeadCrossAttention,
            )
            self.factor_encoder = FactorEncoder(factor_dim=1, d_model=self.cross_attn_dim)
            self.cross_attn = MultiHeadCrossAttention(
                d_model=self.cross_attn_dim,
                n_heads=self.cross_attn_heads,
                factor_head_mask=factor_head_mask,
            )
            self.q_proj = nn.Linear(self.sig_dim, self.cross_attn_dim)
            # drift_net 输入: 3 (S_t + time) + cross_attn_dim + n_regimes + n_transition
            in_dim = 3 + self.cross_attn_dim + self.n_regimes + self.n_transition
        else:
            # 原路径: 3 (S_t + 时间特征) + sig_dim + n_regimes + n_transition + exogenous_dim
            in_dim = 3 + self.sig_dim + self.n_regimes + self.n_transition + self.exogenous_dim
        # P3: 隐藏层间加 Dropout (经验 1583511: 结构正则)
        layers = [
            nn.Linear(in_dim, hidden_dim),
            nn.Tanh(),
        ]
        if self.dropout > 0:
            layers.append(nn.Dropout(self.dropout))
        layers.extend([
            nn.Linear(hidden_dim, hidden_dim),
            nn.Tanh(),
        ])
        if self.dropout > 0:
            layers.append(nn.Dropout(self.dropout))
        layers.append(nn.Linear(hidden_dim, 1))
        self.net = nn.Sequential(*layers)

    def forward(
        self,
        t: "torch.Tensor",
        y: "torch.Tensor",
        log_sig: Optional["torch.Tensor"] = None,
        regime: Optional["torch.Tensor"] = None,
        transition: Optional["torch.Tensor"] = None,
        exogenous: Optional["torch.Tensor"] = None,
        exogenous_factors: Optional["torch.Tensor"] = None,
        head_multipliers: Optional["torch.Tensor"] = None,
    ) -> "torch.Tensor":
        """计算 drift.

        Args:
            t: 时间标量 (tensor)
            y: (B, 1) 状态 S_t
            log_sig: (B, sig_dim) log-signature, 或 None → pad zeros (FAIL-OPEN)
            regime: (B, n_regimes) one-hot, 或 None → pad zeros (FAIL-OPEN, 旧模型兼容)
            transition: (B, n_transition) transition vector (Q[current_regime]),
                        或 None → pad zeros (FAIL-OPEN, 旧模型兼容)
            exogenous: (B, exogenous_dim) 外生力量向量 (P1),
                       或 None → pad zeros (FAIL-OPEN, exogenous_dim=0 时无效果)
            exogenous_factors: (B, N, factor_dim) 外生因子张量 (P1+ Cross-Attention),
                               或 None → cross-attention context=0 (FAIL-OPEN)

        Returns:
            (B, 1) drift, 经 tanh 裁剪
        """
        if not _TORCH_AVAILABLE:
            return torch.zeros(y.size(0), 1)
        B = y.size(0)
        # 时间特征
        t_batch = torch.full((B, 1), float(t), device=y.device)
        time_features = torch.cat(
            [torch.sin(2 * math.pi * t_batch), torch.cos(2 * math.pi * t_batch)],
            dim=-1,
        )
        # log_sig: None 或 维度不匹配 → pad zeros (FAIL-OPEN Level 2.5)
        if log_sig is None:
            log_sig_t = torch.zeros(B, self.sig_dim, device=y.device)
        else:
            log_sig_t = log_sig
            # 维度对齐: 截断或 pad
            cur_dim = log_sig_t.size(-1) if log_sig_t.dim() > 1 else 0
            if log_sig_t.dim() == 1:
                log_sig_t = log_sig_t.unsqueeze(0).expand(B, -1)
                cur_dim = log_sig_t.size(-1)
            if cur_dim < self.sig_dim:
                pad = torch.zeros(B, self.sig_dim - cur_dim, device=y.device)
                log_sig_t = torch.cat([log_sig_t, pad], dim=-1)
            elif cur_dim > self.sig_dim:
                log_sig_t = log_sig_t[..., : self.sig_dim]
            if log_sig_t.size(0) != B:
                # broadcast (1, sig_dim) → (B, sig_dim)
                log_sig_t = log_sig_t[:1].expand(B, -1).contiguous()
        # regime: None 或 维度不匹配 → pad zeros (FAIL-OPEN, 向后兼容旧模型)
        if self.n_regimes <= 0:
            regime_t = torch.zeros(B, 0, device=y.device)
        elif regime is None:
            regime_t = torch.zeros(B, self.n_regimes, device=y.device)
        else:
            regime_t = regime
            if regime_t.dim() == 1:
                regime_t = regime_t.unsqueeze(0).expand(B, -1)
            cur_rdim = regime_t.size(-1) if regime_t.dim() > 1 else 0
            if cur_rdim < self.n_regimes:
                pad = torch.zeros(B, self.n_regimes - cur_rdim, device=y.device)
                regime_t = torch.cat([regime_t, pad], dim=-1)
            elif cur_rdim > self.n_regimes:
                regime_t = regime_t[..., : self.n_regimes]
            if regime_t.size(0) != B:
                regime_t = regime_t[:1].expand(B, -1).contiguous()
        # P0.2: transition vector: None → pad zeros (向后兼容)
        if self.n_transition <= 0:
            transition_t = torch.zeros(B, 0, device=y.device)
        elif transition is None:
            transition_t = torch.zeros(B, self.n_transition, device=y.device)
        else:
            transition_t = transition
            if transition_t.dim() == 1:
                transition_t = transition_t.unsqueeze(0).expand(B, -1)
            cur_tdim = transition_t.size(-1) if transition_t.dim() > 1 else 0
            if cur_tdim < self.n_transition:
                pad = torch.zeros(B, self.n_transition - cur_tdim, device=y.device)
                transition_t = torch.cat([transition_t, pad], dim=-1)
            elif cur_tdim > self.n_transition:
                transition_t = transition_t[..., : self.n_transition]
            if transition_t.size(0) != B:
                transition_t = transition_t[:1].expand(B, -1).contiguous()
        # P1: exogenous vector: None → pad zeros (FAIL-OPEN, exogenous_dim=0 时无效果)
        if self.exogenous_dim <= 0:
            exo_t = torch.zeros(B, 0, device=y.device)
        elif exogenous is None:
            exo_t = torch.zeros(B, self.exogenous_dim, device=y.device)
        else:
            exo_t = exogenous
            if exo_t.dim() == 1:
                exo_t = exo_t.unsqueeze(0).expand(B, -1)
            cur_edim = exo_t.size(-1) if exo_t.dim() > 1 else 0
            if cur_edim < self.exogenous_dim:
                pad = torch.zeros(B, self.exogenous_dim - cur_edim, device=y.device)
                exo_t = torch.cat([exo_t, pad], dim=-1)
            elif cur_edim > self.exogenous_dim:
                exo_t = exo_t[..., : self.exogenous_dim]
            if exo_t.size(0) != B:
                exo_t = exo_t[:1].expand(B, -1).contiguous()
        # P1+: Cross-Attention 外生因子注入
        if self.use_cross_attention and self.exogenous_factor_dim > 0:
            # Q 来自 log_sig (价格问"当前外生环境如何")
            q = self.q_proj(log_sig_t).unsqueeze(1)  # (B, 1, cross_attn_dim)
            # K, V 来自外生因子
            if exogenous_factors is not None:
                # exogenous_factors: (B, N, factor_dim)
                ef = exogenous_factors
                if ef.dim() == 2:
                    ef = ef.unsqueeze(-1)  # (B, N, 1)
                kv = self.factor_encoder(ef)  # (B, N, cross_attn_dim)
                # Phase 5: per-head impact multiplier 耦合
                # head_multipliers 来自 ImpactMultiplier.get_multiplier(cycle_phase, dim)
                ctx = self.cross_attn(q, kv, kv, head_multipliers=head_multipliers)  # (B, cross_attn_dim)
            else:
                # FAIL-OPEN: factors=None → zero context
                ctx = torch.zeros(B, self.cross_attn_dim, device=y.device)
            x = torch.cat(
                [y, time_features, ctx, regime_t, transition_t],
                dim=-1,
            )
        else:
            x = torch.cat(
                [y, time_features, log_sig_t, regime_t, transition_t, exo_t],
                dim=-1,
            )
        out = self.net(x)
        return torch.tanh(out) * self.clip


class _MoEDriftNet(nn.Module if _TORCH_AVAILABLE else object):
    """Mixture-of-Experts drift network (P2.1).

    每个 regime 一个独立 expert drift net, router 根据 regime + transition
    输出 softmax 权重, 加权求和各 expert 的 drift.

    架构:
      - experts: n_experts 个 _PathSignatureDriftNet (n_regimes=0, regime 由 router 处理)
      - router: Linear(regime_onehot + transition) → softmax 权重
      - soft routing: 加权求和 (可微, 平滑)
      - hard routing: argmax + straight-through (稀疏, 可解释)

    FAIL-OPEN:
      - regime=None → 均匀权重 (1/n_experts)
      - router 异常 → 均匀权重
      - 任何 expert 失败 → 跳过该 expert, 重新归一化
    """

    def __init__(
        self,
        n_experts: int = 3,
        hidden_dim: int = DEFAULT_HIDDEN_DIM,
        sig_dim: int = DEFAULT_SIG_DIM,
        clip: float = DEFAULT_DRIFT_CLIP,
        n_transition: int = 0,
        dropout: float = 0.0,
        routing: str = "soft",
        exogenous_dim: int = 0,
        use_cross_attention: bool = False,
        exogenous_factor_dim: int = 0,
        cross_attn_dim: int = 32,
        cross_attn_heads: int = 4,
        factor_head_mask: Optional["torch.Tensor"] = None,
    ):
        if not _TORCH_AVAILABLE:
            return
        super().__init__()
        self.n_experts = int(n_experts)
        self.n_transition = int(n_transition)
        self.routing = routing
        self.clip = clip
        self.sig_dim = int(sig_dim)
        self.exogenous_dim = int(exogenous_dim)
        # P1+: Cross-Attention
        self.use_cross_attention = bool(use_cross_attention)
        self.exogenous_factor_dim = int(exogenous_factor_dim) if self.use_cross_attention else 0
        # 每个 expert 独立 drift net, n_regimes=0 (regime 由 router 处理, 不拼到 expert 输入)
        self.experts = nn.ModuleList([
            _PathSignatureDriftNet(
                hidden_dim=hidden_dim, sig_dim=self.sig_dim, clip=clip,
                n_regimes=0, n_transition=self.n_transition, dropout=dropout,
                exogenous_dim=self.exogenous_dim,
                use_cross_attention=self.use_cross_attention,
                exogenous_factor_dim=self.exogenous_factor_dim,
                cross_attn_dim=cross_attn_dim,
                cross_attn_heads=cross_attn_heads,
                factor_head_mask=factor_head_mask,
            )
            for _ in range(self.n_experts)
        ])
        # router: regime one-hot (n_experts) + transition vector (n_transition) → 权重
        router_in = self.n_experts + self.n_transition
        self.router = nn.Sequential(
            nn.Linear(router_in, hidden_dim),
            nn.Tanh(),
            nn.Linear(hidden_dim, self.n_experts),
        )

    def _compute_weights(
        self,
        regime: Optional["torch.Tensor"],
        transition: Optional["torch.Tensor"] = None,
    ) -> "torch.Tensor":
        """计算 expert 权重.

        Args:
            regime: (B, n_experts) one-hot, 或 None → 均匀权重 (FAIL-OPEN)
            transition: (B, n_transition) transition vector, None → pad zeros

        Returns:
            (B, n_experts) 权重矩阵, 每行和为 1
        """
        if not _TORCH_AVAILABLE:
            return None
        device = next(self.router.parameters()).device
        # regime None → 均匀权重 (FAIL-OPEN)
        if regime is None:
            return torch.ones(1, self.n_experts, device=device) / self.n_experts
        B = regime.size(0)
        # 维度对齐 regime
        regime_t = regime
        if regime_t.dim() == 1:
            regime_t = regime_t.unsqueeze(0).expand(B, -1)
        cur_rdim = regime_t.size(-1)
        if cur_rdim < self.n_experts:
            pad = torch.zeros(B, self.n_experts - cur_rdim, device=regime_t.device)
            regime_t = torch.cat([regime_t, pad], dim=-1)
        elif cur_rdim > self.n_experts:
            regime_t = regime_t[..., : self.n_experts]
        if regime_t.size(0) != B:
            regime_t = regime_t[:1].expand(B, -1).contiguous()

        # P2.3: transition vector 维度对齐 (router 输入 = regime + transition)
        if self.n_transition <= 0:
            transition_t = torch.zeros(B, 0, device=device)
        elif transition is None:
            transition_t = torch.zeros(B, self.n_transition, device=device)
        else:
            transition_t = transition
            if transition_t.dim() == 1:
                transition_t = transition_t.unsqueeze(0).expand(B, -1)
            cur_tdim = transition_t.size(-1)
            if cur_tdim < self.n_transition:
                pad = torch.zeros(B, self.n_transition - cur_tdim, device=transition_t.device)
                transition_t = torch.cat([transition_t, pad], dim=-1)
            elif cur_tdim > self.n_transition:
                transition_t = transition_t[..., : self.n_transition]
            if transition_t.size(0) != B:
                transition_t = transition_t[:1].expand(B, -1).contiguous()

        # router 输入: regime one-hot + transition vector
        router_input = torch.cat([regime_t, transition_t], dim=-1)
        try:
            logits = self.router(router_input)  # (B, n_experts)
        except Exception:  # noqa: BLE001
            return torch.ones(B, self.n_experts, device=device) / self.n_experts

        if self.routing == "hard":
            # hard routing: argmax + straight-through estimator
            idx = logits.argmax(dim=-1)
            hard = torch.nn.functional.one_hot(idx, num_classes=self.n_experts).float()
            soft = torch.softmax(logits, dim=-1)
            return hard + soft - soft.detach()
        # soft routing
        return torch.softmax(logits, dim=-1)

    def forward(
        self,
        t: "torch.Tensor",
        y: "torch.Tensor",
        log_sig: Optional["torch.Tensor"] = None,
        regime: Optional["torch.Tensor"] = None,
        transition: Optional["torch.Tensor"] = None,
        exogenous: Optional["torch.Tensor"] = None,
        exogenous_factors: Optional["torch.Tensor"] = None,
        head_multipliers: Optional["torch.Tensor"] = None,
    ) -> "torch.Tensor":
        """计算 MoE drift.

        Args:
            t: 时间标量
            y: (B, 1) 状态 S_t
            log_sig: (B, sig_dim) log-signature, None → pad zeros
            regime: (B, n_experts) one-hot, None → 均匀权重
            transition: (B, n_transition) transition vector, None → pad zeros
            exogenous: (B, exogenous_dim) 外生力量向量 (P1), None → pad zeros
            exogenous_factors: (B, N, factor_dim) 外生因子张量 (P1+), None → FAIL-OPEN

        Returns:
            (B, 1) drift, 经 tanh 裁剪
        """
        if not _TORCH_AVAILABLE:
            return torch.zeros(y.size(0), 1)
        B = y.size(0)
        device = y.device
        # 各 expert drift (P1: 透传 exogenous; P1+: 透传 exogenous_factors)
        expert_drifts = []
        for expert in self.experts:
            d = expert(t, y, log_sig, None, transition, exogenous, exogenous_factors)
            expert_drifts.append(d)
        expert_drifts = torch.cat(expert_drifts, dim=-1)  # (B, n_experts)
        # 权重 (P2.3: router 接收 transition)
        weights = self._compute_weights(regime, transition).to(device)
        if weights.size(0) == 1 and B > 1:
            weights = weights.expand(B, -1)
        # 加权求和
        drift = (expert_drifts * weights).sum(dim=-1, keepdim=True)  # (B, 1)
        return torch.tanh(drift) * self.clip


class _DiffusionNet(nn.Module if _TORCH_AVAILABLE else object):
    """Diffusion 网络 gφ(S_t, t) → 正标量波动率."""

    def __init__(
        self,
        hidden_dim: int = DEFAULT_DIFFUSION_HIDDEN,
        floor: float = DEFAULT_DIFFUSION_FLOOR,
    ):
        if not _TORCH_AVAILABLE:
            return
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(3, hidden_dim),
            nn.Tanh(),
            nn.Linear(hidden_dim, 1),
        )
        self.floor = floor

    def forward(self, t: "torch.Tensor", y: "torch.Tensor") -> "torch.Tensor":
        if not _TORCH_AVAILABLE:
            return torch.ones(y.size(0), 1) * self.floor
        t_batch = torch.full((y.size(0), 1), float(t), device=y.device)
        time_features = torch.cat([torch.sin(2 * math.pi * t_batch), torch.cos(2 * math.pi * t_batch)], dim=-1)
        x = torch.cat([y, time_features], dim=-1)
        out = self.net(x)
        return torch.nn.functional.softplus(out) + self.floor  # 确保正值


class NeuralSDEModel:
    """Neural SDE 模型: drift + diffusion + 积分 + 持久化.

    遵循 CQLTrainer 模式:
      - 延迟导入 torch, _available 标志
      - save()/load() 权重持久化
      - maybe_activate() 样本阈值门禁 (HC-AGI-13)
    """

    def __init__(
        self,
        hidden_dim: int = DEFAULT_HIDDEN_DIM,
        diffusion_hidden: int = DEFAULT_DIFFUSION_HIDDEN,
        drift_clip: float = DEFAULT_DRIFT_CLIP,
        diffusion_floor: float = DEFAULT_DIFFUSION_FLOOR,
        sig_dim: int = DEFAULT_SIG_DIM,
        n_step: int = DEFAULT_N_STEP,
        sig_depth: int = DEFAULT_SIG_DEPTH,
        n_regimes: int = 3,
        use_transition: bool = False,
        dropout: float = 0.0,
        use_moe: bool = False,
        moe_routing: str = "soft",
        use_exogenous: bool = False,
        exogenous_dim: int = 9,
        use_cross_attention: bool = False,
        exogenous_factor_dim: int = 0,
        cross_attn_dim: int = 32,
        cross_attn_heads: int = 4,
        factor_head_mask: Optional["torch.Tensor"] = None,
        device: str = "cpu",
    ):
        self._available = _TORCH_AVAILABLE
        self._torchsde_available = _TORCHSDE_AVAILABLE
        self.device = device
        self.hidden_dim = hidden_dim
        self.diffusion_hidden = diffusion_hidden
        self.drift_clip = drift_clip
        self.diffusion_floor = diffusion_floor

        # 路径依赖 SDE 参数 (spec §3.2)
        self.sig_dim = int(sig_dim)
        self.n_step = int(n_step)
        self.sig_depth = int(sig_depth)
        # regime-conditional SDE 参数 (T2): n_regimes=3 (bull/chop/bear), 0 = 旧模型无 regime
        self.n_regimes = int(n_regimes)
        # P0.2: use_transition=True 时 drift_net 输入加 transition vector (Q[current_regime])
        # 默认 False (向后兼容旧模型)
        self.use_transition = bool(use_transition)
        self.n_transition = self.n_regimes if self.use_transition else 0
        # P3: dropout 概率 (drift_net 隐藏层间), 默认 0.0 (向后兼容)
        self.dropout = float(dropout)
        # P2.1: MoE-SDE 开关, 默认 False (向后兼容)
        self.use_moe = bool(use_moe)
        self.moe_routing = moe_routing  # "soft" or "hard"
        # P1: 外生力量接入 drift_net 开关, 默认 False (向后兼容)
        # use_exogenous=True 时 drift_net 输入追加 exogenous_dim 维外生向量
        self.use_exogenous = bool(use_exogenous)
        self.exogenous_dim = int(exogenous_dim) if self.use_exogenous else 0
        # P1+: Cross-Attention 外生因子注入
        self.use_cross_attention = bool(use_cross_attention)
        self.exogenous_factor_dim = int(exogenous_factor_dim) if self.use_cross_attention else 0
        self.cross_attn_dim = int(cross_attn_dim)
        self.cross_attn_heads = int(cross_attn_heads)
        # Phase 3+4: 维度对齐 mask, None = 无屏蔽 (向后兼容)
        self.factor_head_mask = factor_head_mask

        # 归一化参数
        self._price_mean = 0.0
        self._price_std = 1.0

        # log_sig z-score 归一化参数 (TDD-010 根因 1)
        # _log_sig_mean/std 在 prepare_data 中拟合, 推理时使用
        self._log_sig_mean: np.ndarray = np.zeros(self.sig_dim, dtype=np.float64)
        self._log_sig_std: np.ndarray = np.ones(self.sig_dim, dtype=np.float64)

        # 激活状态
        self._activated = False
        self._sample_count = 0

        # SignatureEngine 实例 (复用三级降级: signatory→esig→numpy)
        self._signature_engine = None
        if SignatureEngine is not None:
            try:
                self._signature_engine = SignatureEngine(depth=self.sig_depth)
            except Exception as e:  # noqa: BLE001
                logger.warning("[FO-AGI-02] SignatureEngine 初始化失败: %s", e)
                self._signature_engine = None

        # 当前 log_sig 上下文 (供 torchsde.sdeint 调用 f(t,y) 时读取)
        # 单线程下安全 (torch.set_num_threads(1))
        self._current_log_sig: Optional["torch.Tensor"] = None
        # T3: 当前 regime one-hot 上下文 (B, n_regimes), None → drift_net pad zeros
        self._current_regime: Optional["torch.Tensor"] = None
        # P0.2: 当前 transition vector 上下文 (B, n_transition), None → drift_net pad zeros
        self._current_transition: Optional["torch.Tensor"] = None
        # P1: 当前 exogenous 上下文 (B, exogenous_dim), None → drift_net pad zeros
        self._current_exogenous: Optional["torch.Tensor"] = None
        # P1+: 当前 exogenous_factors 上下文 (B, N, factor_dim), None → FAIL-OPEN
        self._current_exogenous_factors: Optional["torch.Tensor"] = None
        # Phase 5: 当前 head_multipliers (n_heads,), None → 不衰减
        self._current_head_multipliers: Optional["torch.Tensor"] = None

        if self._available:
            self._torch = torch
            self._nn = nn
            if self.use_moe and self.n_regimes > 0:
                # P2.1: MoE-SDE — 每 regime 独立 expert + router
                self.drift_net = _MoEDriftNet(
                    n_experts=self.n_regimes,
                    hidden_dim=hidden_dim, sig_dim=self.sig_dim, clip=drift_clip,
                    n_transition=self.n_transition, dropout=self.dropout,
                    routing=self.moe_routing,
                    exogenous_dim=self.exogenous_dim,
                    use_cross_attention=self.use_cross_attention,
                    exogenous_factor_dim=self.exogenous_factor_dim,
                    cross_attn_dim=self.cross_attn_dim,
                    cross_attn_heads=self.cross_attn_heads,
                    factor_head_mask=self.factor_head_mask,
                ).to(device)
            else:
                # 路径依赖 + regime one-hot T2 + transition P0.2 + exogenous P1
                self.drift_net = _PathSignatureDriftNet(
                    hidden_dim=hidden_dim, sig_dim=self.sig_dim, clip=drift_clip,
                    n_regimes=self.n_regimes, n_transition=self.n_transition,
                    dropout=self.dropout,
                    exogenous_dim=self.exogenous_dim,
                    use_cross_attention=self.use_cross_attention,
                    exogenous_factor_dim=self.exogenous_factor_dim,
                    cross_attn_dim=self.cross_attn_dim,
                    cross_attn_heads=self.cross_attn_heads,
                    factor_head_mask=self.factor_head_mask,
                ).to(device)
            self.diffusion_net = _DiffusionNet(diffusion_hidden, diffusion_floor).to(device)
        else:
            self._torch = None
            self.drift_net = None
            self.diffusion_net = None

    # ------------------------------------------------------------------
    # Path-Signature 计算 (FAIL-OPEN Level 2.5 / 2.7) + z-score 归一化 (TDD-010)
    # ------------------------------------------------------------------
    def _compute_log_sig_raw(self, history: np.ndarray) -> np.ndarray:
        """从 history 计算原始 log-signature (未归一化, TDD-010 拆分).

        FAIL-OPEN:
          - Level 2.5: SignatureEngine/signatory/esig 不可用 → pad zeros
          - Level 2.7: history 长度 < N_step → pad zeros (退化马尔可夫)
          - 任何异常 → pad zeros

        Returns:
            (sig_dim,) numpy 数组, 维度对齐到 self.sig_dim (pad zeros, 不截断)
        """
        zeros = np.zeros(self.sig_dim, dtype=np.float64)
        history = np.asarray(history, dtype=np.float64).ravel()

        # Level 2.7: history 不足
        if len(history) < self.n_step:
            logger.debug(
                "[FO-AGI-02] history 长度 %d < N_step %d, log_sig pad zeros (Level 2.7)",
                len(history), self.n_step,
            )
            return zeros

        # Level 2.5: SignatureEngine 不可用
        if self._signature_engine is None:
            logger.debug("[FO-AGI-02] SignatureEngine 不可用, log_sig pad zeros (Level 2.5)")
            return zeros

        try:
            window = history[-self.n_step:]
            log_sig = self._signature_engine.log_signature(window)
            log_sig = np.asarray(log_sig, dtype=np.float64).ravel()

            # 维度对齐: pad zeros 到 sig_dim (不截断, TDD-011)
            if len(log_sig) < self.sig_dim:
                log_sig = np.concatenate([log_sig, np.zeros(self.sig_dim - len(log_sig))])
            elif len(log_sig) > self.sig_dim:
                # 仅在超过 sig_dim 时截断 (sig_dim 已取上限 15, 一般不触发)
                log_sig = log_sig[: self.sig_dim]

            # NaN/Inf 检测 → pad zeros
            if not np.all(np.isfinite(log_sig)):
                logger.warning("[FO-AGI-02] log_sig 含 NaN/Inf, pad zeros")
                return zeros
            return log_sig
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-02] log_sig 计算失败, pad zeros: %s", e)
            return zeros

    def _fit_log_sig_normalization(self, raw_log_sigs: np.ndarray) -> None:
        """从一批 raw log_sig 拟合 z-score 归一化参数 (TDD-010).

        Args:
            raw_log_sigs: (N, sig_dim) numpy 数组, 来自 prepare_data 第一阶段
        """
        arr = np.asarray(raw_log_sigs, dtype=np.float64)
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)
        if arr.shape[0] == 0:
            return
        # 维度对齐 (防止 sig_dim 与 arr 列数不一致)
        if arr.shape[1] != self.sig_dim:
            if arr.shape[1] < self.sig_dim:
                pad = np.zeros((arr.shape[0], self.sig_dim - arr.shape[1]))
                arr = np.concatenate([arr, pad], axis=1)
            else:
                arr = arr[:, : self.sig_dim]

        mean = np.mean(arr, axis=0)
        std = np.std(arr, axis=0)
        # 避免 std=0 (常量分量) → 用 1.0 兜底
        std = np.where(std > 1e-8, std, 1.0)
        self._log_sig_mean = mean
        self._log_sig_std = std
        logger.debug(
            "[NeuralSDE] log_sig z-score 拟合: mean=%s std=%s",
            np.round(mean, 4), np.round(std, 4),
        )

    def _normalize_log_sig(self, raw_log_sig: np.ndarray) -> np.ndarray:
        """对 raw log_sig 做 z-score 归一化 (TDD-010).

        Args:
            raw_log_sig: (sig_dim,) raw log-signature

        Returns:
            (sig_dim,) 归一化 log_sig = (raw - mean) / max(std, 1e-8)
        """
        arr = np.asarray(raw_log_sig, dtype=np.float64).ravel()
        # 维度对齐
        if len(arr) < self.sig_dim:
            arr = np.concatenate([arr, np.zeros(self.sig_dim - len(arr))])
        elif len(arr) > self.sig_dim:
            arr = arr[: self.sig_dim]
        mean = self._log_sig_mean[: self.sig_dim] if len(self._log_sig_mean) >= self.sig_dim else self._log_sig_mean
        std = self._log_sig_std[: self.sig_dim] if len(self._log_sig_std) >= self.sig_dim else self._log_sig_std
        normed = (arr - mean) / np.maximum(std, 1e-8)
        return normed

    def _compute_log_sig(self, history: np.ndarray) -> np.ndarray:
        """从 history 计算归一化 log-signature (TDD-002/003/004/010).

        TDD-010: 调用 _compute_log_sig_raw + _normalize_log_sig 做 z-score 归一化.
        如果 _log_sig_mean/std 未拟合 (默认 0/1), 退化为 raw/std = raw (未归一化).

        Returns:
            (sig_dim,) numpy 数组, z-score 归一化后
        """
        raw = self._compute_log_sig_raw(history)
        return self._normalize_log_sig(raw)

    @property
    def is_available(self) -> bool:
        return self._available

    @property
    def is_activated(self) -> bool:
        return self._activated and self._available

    @property
    def torchsde_available(self) -> bool:
        return self._torchsde_available

    def record_sample(self, count: int = 1) -> None:
        """记录训练样本数."""
        self._sample_count += count
        if not self._activated and self._sample_count >= MIN_SAMPLES_FOR_ACTIVATION:
            self._activated = True
            logger.info(
                "[NeuralSDE] 自动激活: 样本 %d >= %d (HC-AGI-01)",
                self._sample_count, MIN_SAMPLES_FOR_ACTIVATION,
            )

    def maybe_activate(self, sample_count: int) -> bool:
        """HC-AGI-13: 样本 ≥ 1000 时自动激活."""
        if sample_count >= MIN_SAMPLES_FOR_ACTIVATION:
            self._activated = True
            self._sample_count = sample_count
            return True
        return False

    # ------------------------------------------------------------------
    # SDE 接口（兼容 torchsde.sdeint）
    # ------------------------------------------------------------------
    @property
    def sde_type(self) -> str:
        return "ito"

    @property
    def noise_type(self) -> str:
        return "diagonal"

    def f(self, t: "torch.Tensor", y: "torch.Tensor") -> "torch.Tensor":
        """Drift 函数 fθ(S_t, t, log_sig, regime, transition, exogenous, exogenous_factors).

        通过 self._current_log_sig / _current_regime / _current_transition /
        _current_exogenous / _current_exogenous_factors / _current_head_multipliers
        传递上下文 (单线程安全).
        兼容 torchsde.sdeint 的 f(t, y) 签名.
        """
        return self.drift_net(
            t, y, self._current_log_sig, self._current_regime,
            self._current_transition, self._current_exogenous,
            self._current_exogenous_factors,
            self._current_head_multipliers,
        )

    def g(self, t: "torch.Tensor", y: "torch.Tensor") -> "torch.Tensor":
        """Diffusion 函数 gφ(S_t, t)."""
        return self.diffusion_net(t, y)

    # ------------------------------------------------------------------
    # Level 1: torchsde 积分
    # ------------------------------------------------------------------
    def forecast_torchsde(
        self,
        state: np.ndarray,
        horizon: int,
        n_paths: int,
        log_sig: Optional[np.ndarray] = None,
        regime: Optional[int] = None,
        transition: Optional[np.ndarray] = None,
        exogenous_snapshot: Optional[np.ndarray] = None,
        exogenous_factors: Optional[np.ndarray] = None,
        head_multipliers: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        """Level 1: 使用 torchsde.sdeint() 生成路径 (路径依赖 + regime-conditional SDE).

        Args:
            state: [init_price, init_vol] 或 history (旧兼容)
            log_sig: (sig_dim,) log-signature, None 则 pad zeros
            regime: int regime 标签 (0=bull, 1=chop, 2=bear), None 则 pad zeros
            transition: (n_regimes,) transition vector Q[current_regime], None 则 pad zeros
            exogenous_snapshot: (exogenous_dim,) P1 外生力量快照, None 则 pad zeros
            exogenous_factors: (N, factor_dim) P1+ 外生因子张量, None 则 FAIL-OPEN (zero context)
            head_multipliers: (n_heads,) Phase 5 每 head 衰减系数, None 则不衰减

        Returns:
            shape (n_paths, horizon+1) numpy 数组
        """
        if not self._available or not self._torchsde_available:
            raise RuntimeError("torchsde not available")

        with self._torch.no_grad():
            init_price = float(state[0]) if len(state) > 0 else 100.0
            # 归一化初始状态
            s0 = (init_price - self._price_mean) / max(self._price_std, 1e-8)
            y0 = self._torch.full((n_paths, 1), float(s0), device=self.device)
            ts = self._torch.linspace(0, horizon, horizon + 1, device=self.device)

            # 设置 log_sig 上下文 (broadcast 到 n_paths)
            if log_sig is not None:
                log_sig_t = self._torch.tensor(
                    np.asarray(log_sig, dtype=np.float32).ravel()[: self.sig_dim],
                    device=self.device,
                )
                # pad 到 sig_dim
                if log_sig_t.size(0) < self.sig_dim:
                    pad = self._torch.zeros(self.sig_dim - log_sig_t.size(0), device=self.device)
                    log_sig_t = self._torch.cat([log_sig_t, pad])
                log_sig_t = log_sig_t.unsqueeze(0).expand(n_paths, -1).contiguous()
            else:
                log_sig_t = None

            # T4: 设置 regime one-hot 上下文 (broadcast 到 n_paths)
            regime_t = self._build_regime_onehot(regime, n_paths)
            # P0.2: 设置 transition vector 上下文 (broadcast 到 n_paths)
            transition_t = self._build_transition(transition, n_paths)
            # P1: 设置 exogenous 上下文 (broadcast 到 n_paths)
            exogenous_t = self._build_exogenous(exogenous_snapshot, n_paths)
            # P1+: 设置 exogenous_factors 上下文 (broadcast 到 n_paths)
            exogenous_factors_t = self._build_exogenous_factors(exogenous_factors, n_paths)

            # Phase 5: 设置 head_multipliers 上下文
            if head_multipliers is not None:
                head_mult_t = self._torch.tensor(
                    np.asarray(head_multipliers, dtype=np.float32).ravel(),
                    device=self.device,
                )
            else:
                head_mult_t = None

            # 设置上下文供 f(t,y) 读取
            self._current_log_sig = log_sig_t
            self._current_regime = regime_t
            self._current_transition = transition_t
            self._current_exogenous = exogenous_t
            self._current_exogenous_factors = exogenous_factors_t
            self._current_head_multipliers = head_mult_t

            # torchsde 积分
            z_t = torchsde.sdeint(
                sde=self,
                y0=y0,
                ts=ts,
                method="euler",
                dt=1.0,
            )
            # 清理上下文
            self._current_log_sig = None
            self._current_regime = None
            self._current_transition = None
            self._current_exogenous = None
            self._current_exogenous_factors = None
            self._current_head_multipliers = None

            # z_t: (horizon+1, n_paths, 1) → (n_paths, horizon+1)
            z_t = z_t.squeeze(-1).transpose(0, 1).cpu().numpy()

            # 反归一化 (转 float64 保证精度, TDD-002 起点断言)
            paths = (z_t * self._price_std + self._price_mean).astype(np.float64)
            paths[:, 0] = init_price  # 保证起点 (float64 精度)

        return paths

    def _build_regime_onehot(self, regime: Optional[int], n_paths: int):
        """T4: 把 int regime 标签转为 (n_paths, n_regimes) one-hot tensor.

        - regime=None → None (drift_net 内部 pad zeros, FAIL-OPEN)
        - regime=int → one-hot [1, 0, 0] (regime=0), [0, 1, 0] (regime=1) 等
        - regime 越界 → clamp 到 [0, n_regimes-1]
        """
        if self.n_regimes <= 0:
            return None
        if regime is None:
            return None  # drift_net pad zeros
        try:
            r = int(regime)
        except (TypeError, ValueError):
            return None
        r = max(0, min(r, self.n_regimes - 1))
        onehot = torch.zeros(n_paths, self.n_regimes, device=self.device)
        onehot[:, r] = 1.0
        return onehot

    def _build_transition(self, transition: Optional[np.ndarray], n_paths: int):
        """P0.2: 把 transition vector (n_regimes,) 转为 (n_paths, n_transition) tensor.

        - use_transition=False → None (drift_net 内部 pad zeros, 向后兼容)
        - transition=None → None (drift_net pad zeros, FAIL-OPEN)
        - transition=(n_regimes,) → broadcast 到 (n_paths, n_transition)
        """
        if self.n_transition <= 0:
            return None
        if transition is None:
            return None  # drift_net pad zeros
        try:
            trans = np.asarray(transition, dtype=np.float32).ravel()
        except Exception:
            return None
        if trans.size == 0:
            return None
        trans_t = torch.tensor(trans, device=self.device)
        # 对齐到 n_transition
        if trans_t.size(0) < self.n_transition:
            pad = torch.zeros(self.n_transition - trans_t.size(0), device=self.device)
            trans_t = torch.cat([trans_t, pad])
        elif trans_t.size(0) > self.n_transition:
            trans_t = trans_t[: self.n_transition]
        trans_t = trans_t.unsqueeze(0).expand(n_paths, -1).contiguous()
        return trans_t

    def _build_exogenous(self, exogenous_snapshot: Optional[np.ndarray], n_paths: int):
        """P1: 把 exogenous_snapshot (exogenous_dim,) 转为 (n_paths, exogenous_dim) tensor.

        - use_exogenous=False → None (drift_net 内部 pad zeros, 向后兼容)
        - exogenous_snapshot=None → None (drift_net pad zeros, FAIL-OPEN)
        - exogenous_snapshot=(exogenous_dim,) → broadcast 到 (n_paths, exogenous_dim)
        """
        if self.exogenous_dim <= 0:
            return None
        if exogenous_snapshot is None:
            return None  # drift_net pad zeros
        try:
            exo = np.asarray(exogenous_snapshot, dtype=np.float32).ravel()
        except Exception:
            return None
        if exo.size == 0:
            return None
        exo_t = torch.tensor(exo, device=self.device)
        # 对齐到 exogenous_dim
        if exo_t.size(0) < self.exogenous_dim:
            pad = torch.zeros(self.exogenous_dim - exo_t.size(0), device=self.device)
            exo_t = torch.cat([exo_t, pad])
        elif exo_t.size(0) > self.exogenous_dim:
            exo_t = exo_t[: self.exogenous_dim]
        exo_t = exo_t.unsqueeze(0).expand(n_paths, -1).contiguous()
        return exo_t

    def _build_exogenous_factors(
        self,
        exogenous_factors: Optional[np.ndarray],
        n_paths: int,
    ):
        """P1+: 把 exogenous_factors (N, factor_dim) 转为 (n_paths, N, factor_dim) tensor.

        - use_cross_attention=False → None (drift_net 不使用 cross-attention)
        - exogenous_factors=None → None (drift_net zero context, FAIL-OPEN)
        - exogenous_factors=(N, factor_dim) → broadcast 到 (n_paths, N, factor_dim)
        - exogenous_factors=(N,) → 自动 unsqueeze 为 (N, 1)
        """
        if not self.use_cross_attention or self.exogenous_factor_dim <= 0:
            return None
        if exogenous_factors is None:
            return None  # drift_net zero context (FAIL-OPEN)
        try:
            ef = np.asarray(exogenous_factors, dtype=np.float32)
            if ef.ndim == 1:
                ef = ef.reshape(-1, 1)  # (N,) → (N, 1)
            elif ef.ndim != 2:
                return None
            if ef.size == 0:
                return None
        except Exception:
            return None
        ef_t = torch.tensor(ef, device=self.device)  # (N, factor_dim)
        ef_t = ef_t.unsqueeze(0).expand(n_paths, -1, -1).contiguous()
        return ef_t

    # ------------------------------------------------------------------
    # Level 2: 手写 Euler-Maruyama 积分
    # ------------------------------------------------------------------
    def forecast_euler_maruyama(
        self,
        state: np.ndarray,
        horizon: int,
        n_paths: int,
        log_sig: Optional[np.ndarray] = None,
        regime: Optional[int] = None,
        transition: Optional[np.ndarray] = None,
        exogenous_snapshot: Optional[np.ndarray] = None,
        exogenous_factors: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        """Level 2: 手写 EM 离散积分（torchsde 不可用时, 路径依赖 + regime-conditional SDE）.

        Args:
            state: [init_price, init_vol] 或 history (旧兼容)
            log_sig: (sig_dim,) log-signature, None 则 pad zeros
            regime: int regime 标签 (0=bull, 1=chop, 2=bear), None 则 pad zeros
            transition: (n_regimes,) transition vector Q[current_regime], None 则 pad zeros
            exogenous_snapshot: (exogenous_dim,) P1 外生力量快照, None 则 pad zeros
            exogenous_factors: (N, factor_dim) P1+ 外生因子张量, None 则 FAIL-OPEN

        Euler-Maruyama:
          S_{t+1} = S_t + fθ(S_t, t, log_sig, regime, transition, exogenous)·dt
                     + gφ(S_t, t)·√dt · Z

        Returns:
            shape (n_paths, horizon+1) numpy 数组
        """
        if not self._available:
            raise RuntimeError("torch not available")

        with self._torch.no_grad():
            init_price = float(state[0]) if len(state) > 0 else 100.0
            s0 = (init_price - self._price_mean) / max(self._price_std, 1e-8)
            y = self._torch.full((n_paths, 1), float(s0), device=self.device)
            dt = 1.0
            paths = np.zeros((n_paths, horizon + 1), dtype=np.float64)
            paths[:, 0] = init_price

            # 设置 log_sig 上下文 (broadcast 到 n_paths)
            if log_sig is not None:
                log_sig_t = self._torch.tensor(
                    np.asarray(log_sig, dtype=np.float32).ravel()[: self.sig_dim],
                    device=self.device,
                )
                if log_sig_t.size(0) < self.sig_dim:
                    pad = self._torch.zeros(self.sig_dim - log_sig_t.size(0), device=self.device)
                    log_sig_t = self._torch.cat([log_sig_t, pad])
                log_sig_t = log_sig_t.unsqueeze(0).expand(n_paths, -1).contiguous()
            else:
                log_sig_t = None

            # T4: 设置 regime one-hot 上下文
            regime_t = self._build_regime_onehot(regime, n_paths)
            # P0.2: 设置 transition vector 上下文
            transition_t = self._build_transition(transition, n_paths)
            # P1: 设置 exogenous 上下文
            exogenous_t = self._build_exogenous(exogenous_snapshot, n_paths)
            # P1+: 设置 exogenous_factors 上下文
            exogenous_factors_t = self._build_exogenous_factors(exogenous_factors, n_paths)

            self._current_log_sig = log_sig_t
            self._current_regime = regime_t
            self._current_transition = transition_t
            self._current_exogenous = exogenous_t
            self._current_exogenous_factors = exogenous_factors_t

            for t_step in range(horizon):
                t_val = float(t_step)
                drift = self.f(t_val, y)
                diff = self.g(t_val, y)
                z = self._torch.randn_like(y)
                y = y + drift * dt + diff * math.sqrt(dt) * z
                # 反归一化
                price = y.squeeze(-1).cpu().numpy() * self._price_std + self._price_mean
                paths[:, t_step + 1] = price

            # 清理上下文
            self._current_log_sig = None
            self._current_regime = None
            self._current_transition = None
            self._current_exogenous = None
            self._current_exogenous_factors = None

        # NaN 检测
        if np.any(np.isnan(paths)) or np.any(np.isinf(paths)):
            raise RuntimeError("Euler-Maruyama 产生 NaN/Inf")

        return paths

    # ------------------------------------------------------------------
    # 统一入口 (路径依赖 SDE 升级版)
    # ------------------------------------------------------------------
    def forecast(
        self,
        history: np.ndarray,
        horizon: int,
        n_paths: int = 1000,
        state: Optional[np.ndarray] = None,
        regime: Optional[int] = None,
        transition: Optional[np.ndarray] = None,
        exogenous_snapshot: Optional[np.ndarray] = None,
        exogenous_factors: Optional[np.ndarray] = None,
    ) -> Optional[np.ndarray]:
        """统一预测入口 (路径依赖 + regime-conditional SDE,
        TDD-002/003/004/005 + T4 + P0.2 + P1 exogenous + P1+ Cross-Attention).

        Args:
            history: 最近 N 步 close 价格序列 (≥ N_step=32 用 path-signature,
                     < N_step 触发 Level 2.7 pad zeros 退化马尔可夫)
            horizon: 预测步数
            n_paths: 路径数
            state: 可选 [init_price, init_vol]; 不提供则从 history 推导
                    (history[-1] 作 init_price)
            regime: 可选 int regime 标签 (0=bull, 1=chop, 2=bear);
                    None → drift_net pad zeros (FAIL-OPEN, 兼容旧推理路径)
            transition: 可选 (n_regimes,) transition vector Q[current_regime];
                    None → drift_net pad zeros (FAIL-OPEN, 兼容旧推理路径)
            exogenous_snapshot: 可选 (exogenous_dim,) P1 外生力量快照;
                    None → drift_net pad zeros (FAIL-OPEN, 兼容旧推理路径)
            exogenous_factors: 可选 (N, factor_dim) P1+ 外生因子张量;
                    None → cross-attention zero context (FAIL-OPEN)

        Returns:
            shape (n_paths, horizon+1) numpy 数组, 或 None 表示不可用

        向后兼容: 旧 forecast(state=[init_price, init_vol], horizon, n_paths) 调用
        仍可用 (state 当作 history, 长度 2 < N_step → pad zeros 退化马尔可夫).
        """
        if not self.is_activated:
            return None

        history = np.asarray(history, dtype=np.float64).ravel()

        # 推导 init_price
        if state is not None and len(state) > 0:
            init_price = float(state[0])
        elif len(history) > 0:
            # 兼容旧调用: history=[init_price, init_vol] (长度 ≤ 2) → 用 history[0]
            # 路径依赖: history 是价格序列 (长度 > 2) → 用 history[-1] (最近价格)
            if len(history) <= 2:
                init_price = float(history[0])
            else:
                init_price = float(history[-1])
        else:
            init_price = 100.0

        # 计算路径签名 (Level 2.5/2.7 FAIL-OPEN 在 _compute_log_sig 内处理)
        log_sig = self._compute_log_sig(history)

        try:
            if self._torchsde_available:
                return self.forecast_torchsde(
                    np.array([init_price]), horizon, n_paths,
                    log_sig=log_sig, regime=regime, transition=transition,
                    exogenous_snapshot=exogenous_snapshot,
                    exogenous_factors=exogenous_factors,
                )
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-03] torchsde 积分失败, 降级 EM: %s", e)

        try:
            return self.forecast_euler_maruyama(
                np.array([init_price]), horizon, n_paths,
                log_sig=log_sig, regime=regime, transition=transition,
                exogenous_snapshot=exogenous_snapshot,
                exogenous_factors=exogenous_factors,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-03] EM 积分失败: %s", e)
            return None

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------
    def save(self, path: str) -> None:
        """保存模型权重 (参考 CQLTrainer.save)."""
        if not self._available:
            return
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._torch.save({
            "drift_net_state_dict": self.drift_net.state_dict(),
            "diffusion_net_state_dict": self.diffusion_net.state_dict(),
            "price_mean": self._price_mean,
            "price_std": self._price_std,
            "log_sig_mean": np.asarray(self._log_sig_mean, dtype=np.float64),
            "log_sig_std": np.asarray(self._log_sig_std, dtype=np.float64),
            "hidden_dim": self.hidden_dim,
            "diffusion_hidden": self.diffusion_hidden,
            "drift_clip": self.drift_clip,
            "diffusion_floor": self.diffusion_floor,
            "sig_dim": self.sig_dim,
            "n_step": self.n_step,
            "sig_depth": self.sig_depth,
            "n_regimes": self.n_regimes,  # T2: regime-conditional SDE
            "use_transition": self.use_transition,  # P0.2: transition-aware SDE
            "dropout": self.dropout,  # P3: drift_net dropout
            "use_moe": self.use_moe,  # P2.1: MoE-SDE
            "moe_routing": self.moe_routing,  # P2.1: soft/hard routing
            "use_exogenous": self.use_exogenous,  # P1: exogenous drift 输入
            "exogenous_dim": self.exogenous_dim,  # P1: 维度 (0 = 关闭)
            "use_cross_attention": self.use_cross_attention,  # P1+: Cross-Attention
            "cross_attn_dim": self.cross_attn_dim,  # P1+: cross-attention dim
            "cross_attn_heads": self.cross_attn_heads,  # P1+: cross-attention heads
            "exogenous_factor_dim": self.exogenous_factor_dim,  # P1+: 外生因子维度
            "factor_head_mask": self.factor_head_mask,  # Phase 3+4: 维度对齐 mask
            "sample_count": self._sample_count,
            "activated": self._activated,
        }, str(path))
        logger.info("[NeuralSDE] 模型保存到 %s", path)

    def load(self, path: str) -> bool:
        """加载模型权重 (参考 CQLTrainer.load).

        Returns:
            True if load succeeded.
        """
        if not self._available:
            return False
        path = Path(path)
        if not path.exists():
            logger.debug("[NeuralSDE] 权重文件不存在: %s", path)
            return False
        try:
            ckpt = self._torch.load(str(path), map_location=self.device, weights_only=False)
            # T2: 读取 ckpt 中的 n_regimes, 若与当前 drift_net 不同则重建 (兼容旧 v2 模型 n_regimes=0)
            ckpt_n_regimes = int(ckpt.get("n_regimes", 0))
            # P0.2: 读取 use_transition, 若不同则重建 drift_net
            ckpt_use_transition = bool(ckpt.get("use_transition", False))
            # P3: 读取 dropout, 若不同则重建 drift_net
            ckpt_dropout = float(ckpt.get("dropout", 0.0))
            # P2.1: 读取 use_moe / moe_routing
            ckpt_use_moe = bool(ckpt.get("use_moe", False))
            ckpt_moe_routing = ckpt.get("moe_routing", "soft")
            # P1: 读取 use_exogenous / exogenous_dim (旧 ckpt 默认 False/0)
            ckpt_use_exogenous = bool(ckpt.get("use_exogenous", False))
            ckpt_exogenous_dim = int(ckpt.get("exogenous_dim", 0))
            # P1+: 读取 cross-attention 配置 (旧 ckpt 默认 False/0)
            ckpt_use_cross_attn = bool(ckpt.get("use_cross_attention", False))
            ckpt_cross_attn_dim = int(ckpt.get("cross_attn_dim", 0))
            ckpt_cross_attn_heads = int(ckpt.get("cross_attn_heads", 0))
            ckpt_exog_factor_dim = int(ckpt.get("exogenous_factor_dim", 0))
            # Phase 3+4: 读取 factor_head_mask (旧 ckpt 默认 None)
            ckpt_factor_head_mask = ckpt.get("factor_head_mask", None)
            # mask 形状比较 (None vs None 不触发重建)
            mask_changed = not (
                (ckpt_factor_head_mask is None and self.factor_head_mask is None)
                or (
                    ckpt_factor_head_mask is not None
                    and self.factor_head_mask is not None
                    and ckpt_factor_head_mask.shape == self.factor_head_mask.shape
                )
            )
            need_rebuild = (
                ckpt_n_regimes != self.n_regimes
                or ckpt_use_transition != self.use_transition
                or ckpt_dropout != self.dropout
                or ckpt_use_moe != self.use_moe
                or ckpt_moe_routing != self.moe_routing
                or ckpt_use_exogenous != self.use_exogenous
                or ckpt_exogenous_dim != self.exogenous_dim
                or ckpt_use_cross_attn != self.use_cross_attention
                or ckpt_cross_attn_dim != self.cross_attn_dim
                or ckpt_cross_attn_heads != self.cross_attn_heads
                or ckpt_exog_factor_dim != self.exogenous_factor_dim
                or mask_changed
            )
            if need_rebuild:
                logger.debug(
                    "[NeuralSDE] load: drift_net config 不一致 (n_regimes ckpt=%d/cur=%d, "
                    "use_moe ckpt=%s/cur=%s, cross_attn ckpt=%s/cur=%s), 重建 drift_net",
                    ckpt_n_regimes, self.n_regimes,
                    ckpt_use_moe, self.use_moe,
                    ckpt_use_cross_attn, self.use_cross_attention,
                )
                self.n_regimes = ckpt_n_regimes
                self.use_transition = ckpt_use_transition
                self.n_transition = self.n_regimes if self.use_transition else 0
                self.dropout = ckpt_dropout
                self.use_moe = ckpt_use_moe
                self.moe_routing = ckpt_moe_routing
                self.use_exogenous = ckpt_use_exogenous
                self.exogenous_dim = ckpt_exogenous_dim if self.use_exogenous else 0
                self.use_cross_attention = ckpt_use_cross_attn
                self.cross_attn_dim = ckpt_cross_attn_dim if self.use_cross_attention else 0
                self.cross_attn_heads = ckpt_cross_attn_heads if self.use_cross_attention else 0
                self.exogenous_factor_dim = ckpt_exog_factor_dim if self.use_cross_attention else 0
                self.factor_head_mask = ckpt_factor_head_mask
                if self._available:
                    base_kwargs = dict(
                        hidden_dim=self.hidden_dim, sig_dim=self.sig_dim,
                        clip=self.drift_clip, n_transition=self.n_transition,
                        dropout=self.dropout, exogenous_dim=self.exogenous_dim,
                    )
                    if self.use_cross_attention and self.exogenous_factor_dim > 0:
                        base_kwargs.update(
                            use_cross_attention=True,
                            cross_attn_dim=self.cross_attn_dim,
                            cross_attn_heads=self.cross_attn_heads,
                            exogenous_factor_dim=self.exogenous_factor_dim,
                            factor_head_mask=self.factor_head_mask,
                        )
                    if self.use_moe and self.n_regimes > 0:
                        self.drift_net = _MoEDriftNet(
                            n_experts=self.n_regimes, routing=self.moe_routing,
                            **base_kwargs,
                        ).to(self.device)
                    else:
                        self.drift_net = _PathSignatureDriftNet(
                            n_regimes=self.n_regimes, **base_kwargs,
                        ).to(self.device)
            self.drift_net.load_state_dict(ckpt["drift_net_state_dict"])
            self.diffusion_net.load_state_dict(ckpt["diffusion_net_state_dict"])
            self._price_mean = float(ckpt.get("price_mean", 0.0))
            self._price_std = float(ckpt.get("price_std", 1.0))
            # TDD-010: 恢复 log_sig z-score 归一化参数
            log_sig_mean = ckpt.get("log_sig_mean")
            log_sig_std = ckpt.get("log_sig_std")
            if log_sig_mean is not None:
                self._log_sig_mean = np.asarray(log_sig_mean, dtype=np.float64).ravel()
            if log_sig_std is not None:
                self._log_sig_std = np.asarray(log_sig_std, dtype=np.float64).ravel()
            # 维度对齐到当前 sig_dim (兼容旧权重 sig_dim=4 → 新 sig_dim=15)
            if len(self._log_sig_mean) < self.sig_dim:
                pad = np.zeros(self.sig_dim - len(self._log_sig_mean))
                self._log_sig_mean = np.concatenate([self._log_sig_mean, pad])
                self._log_sig_std = np.concatenate([self._log_sig_std, np.ones(self.sig_dim - len(self._log_sig_std))])
            self._sample_count = int(ckpt.get("sample_count", 0))
            self._activated = bool(ckpt.get("activated", False))
            self.drift_net.eval()
            self.diffusion_net.eval()
            logger.info(
                "[NeuralSDE] 模型加载成功: %s (activated=%s, samples=%d, n_regimes=%d)",
                path, self._activated, self._sample_count, self.n_regimes,
            )
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-03] 模型加载失败: %s", e)
            return False

    def set_normalization(self, prices: np.ndarray) -> None:
        """从历史价格序列计算归一化参数."""
        prices = np.asarray(prices, dtype=np.float64).ravel()
        if len(prices) > 0:
            self._price_mean = float(np.mean(prices))
            self._price_std = float(np.std(prices)) if float(np.std(prices)) > 0 else 1.0


class NeuralSDETrainer:
    """Neural SDE 训练器.

    训练策略:
      1. 从历史 close 序列计算对数收益率
      2. 滑动窗口切分 (seq_len=64, horizon=20)
      3. 用 SDE 积分生成路径, MSE loss 对齐真实未来窗口
      4. Adam 优化器 (lr=1e-4)
    """

    def __init__(
        self,
        model: NeuralSDEModel,
        lr: float = 1e-4,
        seq_len: int = 64,
        horizon: int = 20,
        batch_size: int = 64,
        loss_type: str = "mse",
        weight_decay: float = 0.0,
        patience: Optional[int] = None,
        val_split: float = 0.0,
    ):
        """初始化训练器.

        Args:
            loss_type: "mse" (默认, 向后兼容), "qlike", "huber" (P3), "return_mse" (P3).
            weight_decay: AdamW L2 正则强度 (P3, 默认 0.0 = Adam, 向后兼容)
            patience: early stopping 耐心轮数 (P3, None = 不启用)
            val_split: 验证集比例 (P3, 0.0 = 不启用验证集)
        """
        self.model = model
        self.lr = lr
        self.seq_len = seq_len
        self.horizon = horizon
        self.batch_size = batch_size
        self.loss_type = loss_type  # TDD-012
        # P3: 正则化超参
        self.weight_decay = float(weight_decay)
        self.patience = patience
        self.val_split = float(val_split)
        # P0.2: 训练集上的 regime 转移矩阵 Q, use_transition=True 时在 train() 中估计
        self._transition_matrix: Optional[np.ndarray] = None

        self._torch = torch if self.model.is_available else None

        if self.model.is_available:
            params = (
                list(self.model.drift_net.parameters()) +
                list(self.model.diffusion_net.parameters())
            )
            # P3: weight_decay>0 用 AdamW (解耦权重衰减), 否则 Adam (向后兼容)
            if self.weight_decay > 0:
                self._optimizer = torch.optim.AdamW(
                    params, lr=lr, weight_decay=self.weight_decay,
                )
            else:
                self._optimizer = torch.optim.Adam(params, lr=lr)

    def prepare_data(
        self,
        closes: np.ndarray,
        max_windows: int = 3000,
        regime_labels: Optional[np.ndarray] = None,
        regime_balance: str = "balanced",
        exogenous_series: Optional[np.ndarray] = None,
        exogenous_factors: Optional[np.ndarray] = None,
    ) -> list[tuple]:
        """滑动窗口切分 (路径依赖 SDE + regime-conditional, T3 + P1 + P1+).

        两阶段流程 (TDD-010):
          1. 第一阶段: 用 _compute_log_sig_raw 累积所有窗口的 raw log_sig
          2. 调用 _fit_log_sig_normalization 拟合 z-score 归一化参数
          3. 第二阶段: 用 _compute_log_sig (归一化) 生成 windows

        T3 regime-aware 扩展:
          - regime_labels=None → 所有窗口 regime=0 (向后兼容, drift_net pad zeros)
          - regime_labels 给定 → 每个窗口 regime = regime_labels[start_idx]
          - regime_balance="balanced" (默认): 子采样按 regime 均衡
          - regime_balance="natural" (T3.7, Option D): 随机子采样保留自然分布
          - regime_balance="oversample" (P2.2): 少数派 regime 放回采样

        P1 exogenous 扩展 (PLAN-exogenous-integration.md §三):
          - exogenous_series=None → 窗口 exo = 零向量 (FAIL-OPEN, 行为等价当前)
          - exogenous_series=(N, 9) → 每窗口取末尾点 exo[start+seq_len-1]
            (与 regime 取法对齐: regime 取起点, exo 取窗口末尾, 反映"到该窗口
            末尾时观察到的最新外生状态")
          - exogenous_series 长度 < closes → 越界点 exo = 零向量 (FAIL-OPEN)
          - 窗口元组扩展为 5-tuple: (inp, tgt, log_sig, reg, exo_vec)

        P1+ cross-attention 扩展:
          - exogenous_factors=None → 窗口 factor_vec = None (drift_net zero context)
          - exogenous_factors=(N, n_factors) → 每窗口取末尾点 factor[start+seq_len-1]
          - 窗口元组扩展为 6-tuple: (inp, tgt, log_sig, reg, exo_vec, factor_vec)

        Args:
            closes: 历史 close 序列
            max_windows: 最大窗口数（子采样以控制训练时间）
            regime_labels: 与 closes 等长的 regime 标签 (None → 全 0 兜底)
            regime_balance: "balanced" (默认) / "natural" / "oversample"
            exogenous_series: 可选 (N, exo_dim) 外生力量时序, None → 零向量
            exogenous_factors: 可选 (N, n_factors) 外生因子时序, None → zero context

        Returns:
            list of tuples (inp, tgt, log_sig, regime_label, exo_vec[, factor_vec])
        """
        closes = np.asarray(closes, dtype=np.float64).ravel()
        n_closes = closes.size
        if n_closes < self.seq_len + self.horizon:
            return []

        # 价格归一化
        self.model.set_normalization(closes)
        normed = (closes - self.model._price_mean) / max(self.model._price_std, 1e-8)

        # P1: 外生时序预处理 (None → 空数组, 后续按零向量兜底)
        exo_dim = getattr(self.model, "exogenous_dim", 0)
        if exogenous_series is not None:
            exo_arr = np.asarray(exogenous_series, dtype=np.float64)
            if exo_arr.ndim == 1:
                # (N,) → 视为单维 exo, 广播到 (N, exo_dim) (若 exo_dim > 1) 或 (N, 1)
                if exo_dim > 1:
                    exo_arr = np.tile(exo_arr.reshape(-1, 1), (1, exo_dim))
                else:
                    exo_arr = exo_arr.reshape(-1, 1)
            # 维度对齐: exo_arr.shape[1] vs exo_dim
            if exo_arr.shape[1] < exo_dim:
                pad = np.full((exo_arr.shape[0], exo_dim - exo_arr.shape[1]), 0.5)
                exo_arr = np.concatenate([exo_arr, pad], axis=1)
            elif exo_arr.shape[1] > exo_dim:
                exo_arr = exo_arr[:, :exo_dim]
        else:
            exo_arr = None

        # P1+: 外生因子时序预处理 (None → None, drift_net zero context)
        factor_arr = None
        if exogenous_factors is not None:
            factor_arr = np.asarray(exogenous_factors, dtype=np.float64)
            if factor_arr.ndim == 1:
                factor_arr = factor_arr.reshape(-1, 1)

        n_windows_total = n_closes - self.seq_len - self.horizon + 1
        if n_windows_total <= 0:
            return []

        # T3: 构建每个窗口起点的 regime 标签 (兜底: regime_labels=None → 全 0)
        if regime_labels is None:
            per_window_regime = np.zeros(n_windows_total, dtype=int)
        else:
            regime_labels = np.asarray(regime_labels).ravel()
            # 短 regime_labels 兜底: 末段填 0
            if regime_labels.size < n_closes:
                pad = np.zeros(n_closes - regime_labels.size, dtype=int)
                regime_labels = np.concatenate([regime_labels, pad])
            elif regime_labels.size > n_closes:
                regime_labels = regime_labels[:n_closes]
            # 每个窗口起点 i 的 regime = regime_labels[i]
            per_window_regime = regime_labels[:n_windows_total].astype(int)

        # T3: 子采样 — 按 regime 均衡 (balanced / oversample) 或 自然分布 (natural)
        unique_regimes = np.unique(per_window_regime)
        use_balanced = (
            regime_balance == "balanced"
            and n_windows_total > max_windows
            and len(unique_regimes) > 1
        )
        use_oversample = (
            regime_balance == "oversample"
            and len(unique_regimes) > 1
        )
        if use_balanced:
            per_regime_quota = max(1, max_windows // len(unique_regimes))
            indices = []
            for k in unique_regimes:
                idx_in_regime = np.where(per_window_regime == k)[0]
                if idx_in_regime.size == 0:
                    continue
                take = min(per_regime_quota, idx_in_regime.size)
                sampled = np.random.choice(idx_in_regime, take, replace=False)
                indices.extend(sampled.tolist())
            if len(indices) < max_windows:
                remaining = np.setdiff1d(np.arange(n_windows_total), indices)
                extra = min(remaining.size, max_windows - len(indices))
                if extra > 0:
                    indices.extend(np.random.choice(remaining, extra, replace=False).tolist())
            indices = np.array(sorted(indices))
        elif use_oversample:
            per_regime_quota = max(1, max_windows // len(unique_regimes))
            indices = []
            for k in unique_regimes:
                idx_in_regime = np.where(per_window_regime == k)[0]
                if idx_in_regime.size == 0:
                    continue
                replace = idx_in_regime.size < per_regime_quota
                sampled = np.random.choice(idx_in_regime, per_regime_quota, replace=replace)
                indices.extend(sampled.tolist())
            indices = np.array(sorted(indices))
        else:
            if n_windows_total > max_windows:
                indices = np.random.choice(n_windows_total, max_windows, replace=False)
                indices.sort()
            else:
                indices = np.arange(n_windows_total)

        # 第一阶段: 累积 raw log_sig (TDD-010)
        raw_log_sigs = []
        for i in indices:
            raw_window = closes[i:i + self.seq_len]
            raw_log_sig = self.model._compute_log_sig_raw(raw_window)
            raw_log_sigs.append(raw_log_sig)

        # 拟合 z-score 归一化参数
        if raw_log_sigs:
            self.model._fit_log_sig_normalization(np.array(raw_log_sigs))

        # 第二阶段: 生成归一化 windows (5-tuple 含 regime_label + exo_vec)
        windows = []
        for idx, i in enumerate(indices):
            inp = normed[i:i + self.seq_len]
            tgt = normed[i + self.seq_len:i + self.seq_len + self.horizon]
            log_sig = self.model._normalize_log_sig(raw_log_sigs[idx])
            reg = int(per_window_regime[i])
            # P1+: 取窗口末尾点的外生因子向量
            end_idx = i + self.seq_len - 1
            factor_vec = None
            if factor_arr is not None:
                if end_idx < factor_arr.shape[0]:
                    factor_vec = factor_arr[end_idx].astype(np.float64)
                else:
                    factor_vec = np.zeros(factor_arr.shape[1], dtype=np.float64)

            # P1: 取窗口末尾点的外生向量 (对齐 regime 取法)
            # 末尾 idx = i + seq_len - 1; 越界 (exo_arr 太短) → 零向量
            # 向后兼容: exo_dim=0 时返回 4-tuple (T3 行为不变), exo_dim>0 时 5-tuple
            # P1+: 如果有 factor_vec, 扩展为 6-tuple
            if exo_dim > 0:
                if exo_arr is not None:
                    if end_idx < exo_arr.shape[0]:
                        exo_vec = exo_arr[end_idx].astype(np.float64)
                    else:
                        exo_vec = np.zeros(exo_dim, dtype=np.float64)
                else:
                    exo_vec = np.zeros(exo_dim, dtype=np.float64)
                if factor_vec is not None:
                    windows.append((inp, tgt, log_sig, reg, exo_vec, factor_vec))
                else:
                    windows.append((inp, tgt, log_sig, reg, exo_vec))
            else:
                if factor_vec is not None:
                    windows.append((inp, tgt, log_sig, reg, factor_vec))
                else:
                    windows.append((inp, tgt, log_sig, reg))

        return windows

    def train_epoch(self, windows: list[tuple[np.ndarray, np.ndarray, np.ndarray]]) -> float:
        """训练一个 epoch, 返回平均 loss (路径依赖 SDE).

        向量化: 整个 batch 同时积分, 而非逐窗口循环.
        训练时每个窗口的 log_sig 不同, batch 内为 (bs, sig_dim).
        """
        if not self.model.is_available:
            return 0.0

        self.model.drift_net.train()
        self.model.diffusion_net.train()
        np.random.shuffle(windows)
        total_loss = 0.0
        n_batches = 0
        dt = 1.0
        sqrt_dt = math.sqrt(dt)

        for i in range(0, len(windows), self.batch_size):
            batch = windows[i:i + self.batch_size]
            if not batch:
                continue
            bs = len(batch)

            # P1/P1+: 模型维度 (供 tuple 格式判断)
            exo_dim = getattr(self.model, "exogenous_dim", 0)

            # 兼容 3/4/5/6-tuple (P1 exogenous + P1+ cross-attention)
            sample = batch[0]
            n_fields = len(sample)
            has_regime = n_fields >= 4
            has_exo = n_fields >= 5 and not (n_fields == 5 and exo_dim == 0)
            # 6-tuple: (inp, tgt, log_sig, reg, exo_vec, factor_vec) — 有 exo + factors
            # 5-tuple with exo_dim>0: (inp, tgt, log_sig, reg, exo_vec) — 有 exo, 无 factors
            # 5-tuple with exo_dim==0: (inp, tgt, log_sig, reg, factor_vec) — 无 exo, 有 factors
            has_factors = n_fields >= 6 or (n_fields == 5 and exo_dim == 0)
            if n_fields >= 6:
                s0_arr = np.array([[inp[-1]] for inp, _, _, _, _, _ in batch], dtype=np.float32)
                tgt_arr = np.array([tgt for _, tgt, _, _, _, _ in batch], dtype=np.float32)
                log_sig_arr = np.array([ls for _, _, ls, _, _, _ in batch], dtype=np.float32)
                regime_arr = np.array([reg for _, _, _, reg, _, _ in batch], dtype=np.int64)
                exo_arr = np.array([exo for _, _, _, _, exo, _ in batch], dtype=np.float32)
                factor_arr = np.array([f for _, _, _, _, _, f in batch], dtype=np.float32)
            elif n_fields == 5 and exo_dim > 0:
                s0_arr = np.array([[inp[-1]] for inp, _, _, _, _ in batch], dtype=np.float32)
                tgt_arr = np.array([tgt for _, tgt, _, _, _ in batch], dtype=np.float32)
                log_sig_arr = np.array([ls for _, _, ls, _, _ in batch], dtype=np.float32)
                regime_arr = np.array([reg for _, _, _, reg, _ in batch], dtype=np.int64)
                exo_arr = np.array([exo for _, _, _, _, exo in batch], dtype=np.float32)
                factor_arr = None
            elif n_fields == 5 and exo_dim == 0:
                s0_arr = np.array([[inp[-1]] for inp, _, _, _, _ in batch], dtype=np.float32)
                tgt_arr = np.array([tgt for _, tgt, _, _, _ in batch], dtype=np.float32)
                log_sig_arr = np.array([ls for _, _, ls, _, _ in batch], dtype=np.float32)
                regime_arr = np.array([reg for _, _, _, reg, _ in batch], dtype=np.int64)
                exo_arr = None
                factor_arr = np.array([f for _, _, _, _, f in batch], dtype=np.float32)
            elif has_regime:
                s0_arr = np.array([[inp[-1]] for inp, _, _, _ in batch], dtype=np.float32)
                tgt_arr = np.array([tgt for _, tgt, _, _ in batch], dtype=np.float32)
                log_sig_arr = np.array([ls for _, _, ls, _ in batch], dtype=np.float32)
                regime_arr = np.array([reg for _, _, _, reg in batch], dtype=np.int64)
                exo_arr = None
                factor_arr = None
            else:
                s0_arr = np.array([[inp[-1]] for inp, _, _ in batch], dtype=np.float32)
                tgt_arr = np.array([tgt for _, tgt, _ in batch], dtype=np.float32)
                log_sig_arr = np.array([ls for _, _, ls in batch], dtype=np.float32)
                regime_arr = np.zeros(bs, dtype=np.int64)
                exo_arr = None
                factor_arr = None

            y = self._torch.tensor(s0_arr, device=self.model.device)  # (bs, 1)
            targets = self._torch.tensor(tgt_arr, device=self.model.device)  # (bs, horizon)
            log_sig_t = self._torch.tensor(log_sig_arr, device=self.model.device)  # (bs, sig_dim)

            # T3: 构建 regime one-hot (bs, n_regimes), 设为上下文
            n_regimes = getattr(self.model, "n_regimes", 3)
            if n_regimes > 0:
                regime_onehot = torch.zeros(bs, n_regimes, device=self.model.device)
                # 在线 one-hot: regime_arr[k] 应 ∈ [0, n_regimes), 否则 clamp
                regime_clamped = np.clip(regime_arr, 0, n_regimes - 1)
                regime_onehot.scatter_(1, torch.tensor(regime_clamped, device=self.model.device).unsqueeze(1), 1.0)
            else:
                regime_onehot = None

            # P0.2: 构建 transition vector (bs, n_regimes) = Q[regime_arr[k]]
            n_transition = getattr(self.model, "n_transition", 0)
            if n_transition > 0 and self._transition_matrix is not None:
                Q = self._transition_matrix
                # regime_clamped ∈ [0, n_regimes-1], 取 Q 对应行
                transition_vec = Q[regime_clamped]  # (bs, n_regimes)
                transition_t = torch.tensor(
                    transition_vec, dtype=torch.float32, device=self.model.device,
                )
            else:
                transition_t = None

            # P1: 构建 exogenous 上下文 (bs, exo_dim)
            if exo_dim > 0 and exo_arr is not None and exo_arr.size > 0:
                exo_t = torch.tensor(exo_arr, dtype=torch.float32, device=self.model.device)
                if exo_t.dim() == 1:
                    exo_t = exo_t.view(bs, -1)
                # 维度对齐
                if exo_t.size(-1) < exo_dim:
                    pad = torch.zeros(bs, exo_dim - exo_t.size(-1), device=self.model.device)
                    exo_t = torch.cat([exo_t, pad], dim=-1)
                elif exo_t.size(-1) > exo_dim:
                    exo_t = exo_t[..., :exo_dim]
            else:
                exo_t = None

            # P1+: 构建 exogenous_factors 上下文 (bs, n_factors, factor_dim)
            factor_t = None
            if factor_arr is not None and factor_arr.size > 0:
                # factor_arr shape: (bs, n_factors) → (bs, n_factors, 1)
                factor_t = torch.tensor(factor_arr, dtype=torch.float32, device=self.model.device)
                if factor_t.dim() == 1:
                    factor_t = factor_t.view(bs, -1)
                if factor_t.dim() == 2:
                    factor_t = factor_t.unsqueeze(-1)  # (bs, n_factors, 1)

            self._optimizer.zero_grad()

            # 设置上下文 (训练时每个窗口的 log_sig / regime / transition / exo / factors 不同)
            self.model._current_log_sig = log_sig_t
            self.model._current_regime = regime_onehot
            self.model._current_transition = transition_t
            self.model._current_exogenous = exo_t
            self.model._current_exogenous_factors = factor_t

            # 向量化 SDE 积分: 整个 batch 同时推进 horizon 步
            path = torch.zeros(bs, self.horizon, device=self.model.device)
            for t_step in range(self.horizon):
                t_val = float(t_step)
                drift = self.model.f(t_val, y)       # (bs, 1)
                diff = self.model.g(t_val, y)         # (bs, 1)
                z = self._torch.randn_like(y)         # (bs, 1)
                y = y + drift * dt + diff * sqrt_dt * z
                path[:, t_step] = y.squeeze(-1)

            # 清理上下文
            self.model._current_log_sig = None
            self.model._current_regime = None
            self.model._current_transition = None
            self.model._current_exogenous = None
            self.model._current_exogenous_factors = None

            # TDD-012: 根据 loss_type 选择 loss 函数
            batch_loss = self._compute_loss(path, targets)

            batch_loss.backward()
            self._optimizer.step()
            total_loss += float(batch_loss.item())
            n_batches += 1

        return total_loss / max(n_batches, 1)

    def _compute_loss(self, path: "torch.Tensor", targets: "torch.Tensor") -> "torch.Tensor":
        """根据 loss_type 计算 loss (TDD-012 multitask 扩展 TDD-013, P3 huber/return_mse).

        Args:
            path: (bs, horizon) 预测路径 (归一化价格)
            targets: (bs, horizon) 真实路径 (归一化价格)

        Returns:
            scalar loss tensor

        loss_type:
            - "mse": 价格路径 MSE (旧版, 向后兼容)
            - "qlike": 波动率 QLIKE quasi-likelihood
            - "multitask" (TDD-013): 0.7*MSE + 0.3*QLIKE
            - "huber" (P3): Huber loss, 抗异常值, delta=1.0
            - "return_mse" (P3): 在 diff (收益率) 域计算 MSE,
                关注收益率预测而非绝对价格水平
        """
        torch = self._torch
        if self.loss_type == "qlike":
            eps = 1e-8
            actual_returns = torch.diff(targets, dim=1)
            actual_var = actual_returns ** 2
            pred_returns = torch.diff(path, dim=1)
            pred_var = pred_returns ** 2
            qlike = torch.mean(torch.log(pred_var + eps) + actual_var / (pred_var + eps))
            return qlike
        if self.loss_type == "multitask":
            eps = 1e-8
            actual_returns = torch.diff(targets, dim=1)
            actual_var = actual_returns ** 2
            pred_returns = torch.diff(path, dim=1)
            pred_var = pred_returns ** 2
            qlike = torch.mean(torch.log(pred_var + eps) + actual_var / (pred_var + eps))
            mse = torch.nn.functional.mse_loss(path, targets)
            return 0.7 * mse + 0.3 * qlike
        if self.loss_type == "huber":
            # P3: Huber loss, 抗异常值 (delta=1.0)
            return torch.nn.functional.huber_loss(path, targets, delta=1.0)
        if self.loss_type == "return_mse":
            # P3: 在 diff (收益率) 域计算 MSE
            # path/targets 都是归一化价格, diff 后是归一化收益率
            pred_returns = torch.diff(path, dim=1)
            actual_returns = torch.diff(targets, dim=1)
            return torch.nn.functional.mse_loss(pred_returns, actual_returns)
        # 默认 MSE (向后兼容)
        return torch.nn.functional.mse_loss(path, targets)

    def train(
        self,
        closes: np.ndarray,
        epochs: int = 200,
        regime_labels: Optional[np.ndarray] = None,
        regime_balance: str = "balanced",
        exogenous_series: Optional[np.ndarray] = None,
        exogenous_factors: Optional[np.ndarray] = None,
    ) -> dict[str, Any]:
        """完整训练流程 (T5: regime-conditional + P1 exogenous + P1+ cross-attention).

        Args:
            closes: 历史 close 序列
            epochs: 训练轮数
            regime_labels: 可选 regime 标签 (None → 全 0 兜底, 旧行为)
            regime_balance: "balanced" (默认) 或 "natural" (T3.7)
            exogenous_series: 可选 (N, exo_dim) 外生力量时序 (P1),
                              None → 零向量 (FAIL-OPEN, 行为等价当前)
            exogenous_factors: 可选 (N, n_factors) 外生因子时序 (P1+ Cross-Attention),
                               None → zero context (FAIL-OPEN)

        Returns:
            training report dict
        """
        if not self.model.is_available:
            return {"status": "skipped", "reason": "torch not available"}

        # P0.2: 如果 use_transition=True 且有 regime_labels, 估计转移矩阵 Q
        if getattr(self.model, "use_transition", False) and regime_labels is not None:
            try:
                from dreambuddy_evolution.core.btc_regime_detector import BTCRegimeDetector
                detector = BTCRegimeDetector(n_regimes=self.model.n_regimes)
                self._transition_matrix = detector.estimate_transition_matrix(regime_labels)
                logger.info(
                    "[NeuralSDE] P0.2: 估计 regime 转移矩阵 Q (shape=%s)",
                    self._transition_matrix.shape,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("[NeuralSDE] P0.2: 转移矩阵估计失败, transition 降级: %s", e)
                self._transition_matrix = None
        else:
            self._transition_matrix = None

        windows = self.prepare_data(
            closes, regime_labels=regime_labels, regime_balance=regime_balance,
            exogenous_series=exogenous_series, exogenous_factors=exogenous_factors,
        )
        if len(windows) < MIN_SAMPLES_FOR_ACTIVATION:
            logger.warning(
                "[NeuralSDE] 训练样本 %d < %d, 无法激活 (HC-AGI-13)",
                len(windows), MIN_SAMPLES_FOR_ACTIVATION,
            )
            return {"status": "insufficient_samples", "n_windows": len(windows)}

        # P3: 验证集切分 (用于 early stopping)
        val_windows = []
        train_windows = windows
        if self.val_split > 0 and self.patience is not None:
            n_val = max(1, int(len(windows) * self.val_split))
            np.random.shuffle(windows)
            val_windows = windows[:n_val]
            train_windows = windows[n_val:]
            if len(train_windows) < MIN_SAMPLES_FOR_ACTIVATION:
                # 验证集太大导致训练集不足, 回退到全量训练
                train_windows = windows
                val_windows = []

        losses = []
        val_losses = []
        best_val_loss = float("inf")
        patience_counter = 0
        early_stopped = False
        epochs_run = 0

        for epoch in range(epochs):
            avg_loss = self.train_epoch(train_windows)
            losses.append(avg_loss)
            epochs_run = epoch + 1

            # P3: early stopping (基于验证集 loss)
            if val_windows and self.patience is not None:
                val_loss = self._eval_val(val_windows)
                val_losses.append(val_loss)
                if val_loss < best_val_loss:
                    best_val_loss = val_loss
                    patience_counter = 0
                else:
                    patience_counter += 1
                    if patience_counter >= self.patience:
                        logger.info(
                            "[NeuralSDE] Early stopping at epoch %d (val_loss=%.6f, patience=%d)",
                            epoch + 1, val_loss, self.patience,
                        )
                        early_stopped = True
                        break

            if (epoch + 1) % 10 == 0:
                log_msg = f"[NeuralSDE] epoch {epoch + 1}/{epochs} loss={avg_loss:.6f}"
                if val_losses:
                    log_msg += f" val_loss={val_losses[-1]:.6f}"
                logger.info(log_msg)

        # 激活模型
        self.model._sample_count = len(windows)
        self.model._activated = True

        return {
            "status": "ok",
            "epochs": epochs,
            "epochs_run": epochs_run,
            "early_stopped": early_stopped,
            "n_windows": len(windows),
            "final_loss": losses[-1] if losses else 0.0,
            "best_val_loss": best_val_loss if val_losses else None,
            "losses": losses,
            "val_losses": val_losses if val_losses else None,
            "loss_type": self.loss_type,  # TDD-012
            "sig_dim": self.model.sig_dim,  # TDD-011
        }

    def _eval_val(self, val_windows: list) -> float:
        """P3: 在验证集上计算 loss (不更新梯度)."""
        torch = self._torch
        if not val_windows:
            return 0.0

        self.model.drift_net.eval()
        self.model.diffusion_net.eval()
        total_loss = 0.0
        n_batches = 0
        bs = self.batch_size
        dt = 1.0
        sqrt_dt = math.sqrt(dt)

        with torch.no_grad():
            for i in range(0, len(val_windows), bs):
                batch = val_windows[i:i + bs]
                if not batch:
                    continue
                batch_size = len(batch)
                exo_dim = getattr(self.model, "exogenous_dim", 0)

                # 兼容 3/4/5/6-tuple (P1 exogenous + P1+ cross-attention)
                sample = batch[0]
                n_fields = len(sample)
                has_regime = n_fields >= 4
                factor_arr = None
                if n_fields >= 6:
                    s0_arr = np.array([[inp[-1]] for inp, _, _, _, _, _ in batch], dtype=np.float32)
                    tgt_arr = np.array([tgt for _, tgt, _, _, _, _ in batch], dtype=np.float32)
                    log_sig_arr = np.array([ls for _, _, ls, _, _, _ in batch], dtype=np.float32)
                    regime_arr = np.array([reg for _, _, _, reg, _, _ in batch], dtype=np.int64)
                    exo_arr = np.array([exo for _, _, _, _, exo, _ in batch], dtype=np.float32)
                    factor_arr = np.array([f for _, _, _, _, _, f in batch], dtype=np.float32)
                elif n_fields == 5 and exo_dim > 0:
                    s0_arr = np.array([[inp[-1]] for inp, _, _, _, _ in batch], dtype=np.float32)
                    tgt_arr = np.array([tgt for _, tgt, _, _, _ in batch], dtype=np.float32)
                    log_sig_arr = np.array([ls for _, _, ls, _, _ in batch], dtype=np.float32)
                    regime_arr = np.array([reg for _, _, _, reg, _ in batch], dtype=np.int64)
                    exo_arr = np.array([exo for _, _, _, _, exo in batch], dtype=np.float32)
                elif n_fields == 5 and exo_dim == 0:
                    s0_arr = np.array([[inp[-1]] for inp, _, _, _, _ in batch], dtype=np.float32)
                    tgt_arr = np.array([tgt for _, tgt, _, _, _ in batch], dtype=np.float32)
                    log_sig_arr = np.array([ls for _, _, ls, _, _ in batch], dtype=np.float32)
                    regime_arr = np.array([reg for _, _, _, reg, _ in batch], dtype=np.int64)
                    exo_arr = None
                    factor_arr = np.array([f for _, _, _, _, f in batch], dtype=np.float32)
                elif has_regime:
                    s0_arr = np.array([[inp[-1]] for inp, _, _, _ in batch], dtype=np.float32)
                    tgt_arr = np.array([tgt for _, tgt, _, _ in batch], dtype=np.float32)
                    log_sig_arr = np.array([ls for _, _, ls, _ in batch], dtype=np.float32)
                    regime_arr = np.array([reg for _, _, _, reg in batch], dtype=np.int64)
                    exo_arr = None
                else:
                    s0_arr = np.array([[inp[-1]] for inp, _, _ in batch], dtype=np.float32)
                    tgt_arr = np.array([tgt for _, tgt, _ in batch], dtype=np.float32)
                    log_sig_arr = np.array([ls for _, _, ls in batch], dtype=np.float32)
                    regime_arr = np.zeros(batch_size, dtype=np.int64)
                    exo_arr = None

                y = torch.tensor(s0_arr)
                targets = torch.tensor(tgt_arr)
                log_sig_t = torch.tensor(log_sig_arr)

                n_regimes = getattr(self.model, "n_regimes", 3)
                if n_regimes > 0:
                    regime_clamped = np.clip(regime_arr, 0, n_regimes - 1)
                    regime_onehot = torch.zeros(batch_size, n_regimes)
                    regime_onehot.scatter_(1, torch.tensor(regime_clamped).unsqueeze(1), 1.0)
                else:
                    regime_onehot = None

                n_transition = getattr(self.model, "n_transition", 0)
                if n_transition > 0 and self._transition_matrix is not None:
                    transition_vec = self._transition_matrix[regime_clamped]
                    transition_t = torch.tensor(transition_vec, dtype=torch.float32)
                else:
                    transition_t = None

                # P1: exogenous 上下文
                if exo_dim > 0 and exo_arr is not None and exo_arr.size > 0:
                    exo_t = torch.tensor(exo_arr, dtype=torch.float32)
                    if exo_t.dim() == 1:
                        exo_t = exo_t.view(batch_size, -1)
                    if exo_t.size(-1) < exo_dim:
                        pad = torch.zeros(batch_size, exo_dim - exo_t.size(-1))
                        exo_t = torch.cat([exo_t, pad], dim=-1)
                    elif exo_t.size(-1) > exo_dim:
                        exo_t = exo_t[..., :exo_dim]
                else:
                    exo_t = None

                # P1+: exogenous_factors 上下文 (batch_size, n_factors, 1)
                factor_t = None
                if factor_arr is not None and factor_arr.size > 0:
                    factor_t = torch.tensor(factor_arr, dtype=torch.float32)
                    if factor_t.dim() == 1:
                        factor_t = factor_t.view(batch_size, -1)
                    if factor_t.dim() == 2:
                        factor_t = factor_t.unsqueeze(-1)

                self.model._current_log_sig = log_sig_t
                self.model._current_regime = regime_onehot
                self.model._current_transition = transition_t
                self.model._current_exogenous = exo_t
                self.model._current_exogenous_factors = factor_t

                path = torch.zeros(batch_size, self.horizon)
                for t_step in range(self.horizon):
                    drift = self.model.f(float(t_step), y)
                    diff = self.model.g(float(t_step), y)
                    z = torch.randn_like(y)
                    y = y + drift * dt + diff * sqrt_dt * z
                    path[:, t_step] = y.squeeze(-1)

                self.model._current_log_sig = None
                self.model._current_regime = None
                self.model._current_transition = None
                self.model._current_exogenous = None
                self.model._current_exogenous_factors = None

                loss = self._compute_loss(path, targets)
                total_loss += float(loss.item())
                n_batches += 1

        self.model.drift_net.train()
        self.model.diffusion_net.train()
        return total_loss / max(n_batches, 1)
