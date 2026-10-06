"""
C2 GREEN: Cross-Attention 外生注入组件

核心组件：
  - FactorEncoder: 将 N 个原始因子编码为 d_model 维 token 序列
  - MultiHeadCrossAttention: 标准多头交叉注意力
    Q 来自价格 signature（query：价格问"当前外生环境如何"）
    K, V 来自外生因子（key-value：因子提供上下文）

FAIL-OPEN:
  - factors=None → MultiHeadCrossAttention 返回零向量
  - 单因子 → 退化为直接投影
"""
from __future__ import annotations

import math
from typing import Optional

import torch
import torch.nn as nn
import torch.nn.functional as F


class FactorEncoder(nn.Module):
    """将 N 个原始因子编码为 d_model 维 token 序列。

    支持可变因子数 N（IC 筛选后动态调整）。

    Args:
        factor_dim: 每个因子的原始维度（通常为 1，标量因子）
        d_model: 编码后的维度
    """

    def __init__(self, factor_dim: int = 1, d_model: int = 32):
        super().__init__()
        self.factor_dim = int(factor_dim)
        self.d_model = int(d_model)
        self.proj = nn.Linear(self.factor_dim, self.d_model)
        self.norm = nn.LayerNorm(self.d_model)

    def forward(self, factors: torch.Tensor) -> torch.Tensor:
        """编码因子序列。

        Args:
            factors: (B, N, factor_dim) 因子张量

        Returns:
            (B, N, d_model) 编码后的因子 token
        """
        if factors.dim() == 2:
            factors = factors.unsqueeze(-1)
        return self.norm(self.proj(factors))


class MultiHeadCrossAttention(nn.Module):
    """多头交叉注意力。

    Q 来自价格 signature，K/V 来自外生因子。
    注意力权重自动学习"哪些因子在当前价格状态下重要"。

    Args:
        d_model: 模型维度
        n_heads: 注意力头数（d_model 必须能被 n_heads 整除）
        dropout: dropout 概率
        factor_head_mask: 可选维度对齐 mask，shape (n_heads, n_factors)，
                         0=允许注意力，-inf=屏蔽；也可在 forward 时传入覆盖
    """

    def __init__(
        self,
        d_model: int = 32,
        n_heads: int = 4,
        dropout: float = 0.1,
        factor_head_mask: Optional[torch.Tensor] = None,
    ):
        super().__init__()
        assert d_model % n_heads == 0, f"d_model={d_model} 必须能被 n_heads={n_heads} 整除"
        self.d_model = int(d_model)
        self.n_heads = int(n_heads)
        self.head_dim = self.d_model // self.n_heads

        self.q_proj = nn.Linear(self.d_model, self.d_model)
        self.k_proj = nn.Linear(self.d_model, self.d_model)
        self.v_proj = nn.Linear(self.d_model, self.d_model)
        self.out_proj = nn.Linear(self.d_model, self.d_model)
        self.dropout = nn.Dropout(dropout)

        # 维度对齐 mask: (n_heads, n_factors), 0=允许, -inf=屏蔽
        # 注册为 buffer 以便随模型保存/加载
        if factor_head_mask is not None:
            self.register_buffer("factor_head_mask", factor_head_mask)
        else:
            self.factor_head_mask = None

        # 暴露最近一次 attention weights 用于可解释性分析
        self.last_attn_weights: Optional[torch.Tensor] = None

    def forward(
        self,
        query: torch.Tensor,
        key: Optional[torch.Tensor],
        value: Optional[torch.Tensor],
        factor_head_mask: Optional[torch.Tensor] = None,
        head_multipliers: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        """计算交叉注意力。

        Args:
            query: (B, 1, d_model) 价格 signature 作为 query
            key: (B, N, d_model) 因子作为 key，None → 零输出
            value: (B, N, d_model) 因子作为 value，None → 零输出
            factor_head_mask: 可选覆盖构造时的 mask，shape (n_heads, N)
            head_multipliers: Phase 5 每 head 衰减系数，shape (n_heads,)
                              来自 ImpactMultiplier.get_multiplier(cycle_phase, dim)
                              每个 head 对应一个矛盾维度 (C1→head0, ..., news→head7)
                              None → 不衰减 (FAIL-OPEN)

        Returns:
            (B, d_model) context vector（squeeze 掉 query 的 seq 维）
        """
        B = query.size(0)

        # FAIL-OPEN: key/value 为 None → 返回零向量
        if key is None or value is None:
            self.last_attn_weights = None
            return torch.zeros(B, self.d_model, device=query.device)

        # 处理单因子情况（N=1）
        if key.dim() == 2:
            key = key.unsqueeze(1)
        if value.dim() == 2:
            value = value.unsqueeze(1)

        N = key.size(1)

        # 投影
        q = self.q_proj(query)   # (B, 1, d_model)
        k = self.k_proj(key)     # (B, N, d_model)
        v = self.v_proj(value)   # (B, N, d_model)

        # reshape 为多头: (B, n_heads, seq_len, head_dim)
        q = q.view(B, 1, self.n_heads, self.head_dim).transpose(1, 2)
        k = k.view(B, N, self.n_heads, self.head_dim).transpose(1, 2)
        v = v.view(B, N, self.n_heads, self.head_dim).transpose(1, 2)

        # 注意力分数: (B, n_heads, 1, N)
        scores = torch.matmul(q, k.transpose(-2, -1)) / math.sqrt(self.head_dim)

        # 维度对齐 mask: (n_heads, N) → broadcast 到 (B, n_heads, 1, N)
        mask = factor_head_mask if factor_head_mask is not None else self.factor_head_mask
        if mask is not None:
            scores = scores + mask.unsqueeze(0).unsqueeze(2)

        weights = F.softmax(scores, dim=-1)

        # Phase 5: per-head impact multiplier 耦合
        # 每个 head 的 attention weights 乘以该维度的衰减系数
        # head_multipliers shape: (n_heads,) → broadcast 到 (B, n_heads, 1, N)
        if head_multipliers is not None:
            # 验证长度匹配
            if head_multipliers.numel() == self.n_heads:
                mult = head_multipliers.view(1, self.n_heads, 1, 1).to(
                    device=weights.device, dtype=weights.dtype
                )
                weights = weights * mult
            else:
                # FAIL-OPEN: 长度不匹配则不衰减
                pass

        # 保存 attention weights（dropout 前的纯 softmax 概率，用于可解释性）
        self.last_attn_weights = weights.detach()

        weights = self.dropout(weights)

        # 加权求和: (B, n_heads, 1, head_dim)
        context = torch.matmul(weights, v)

        # 合并多头: (B, 1, d_model)
        context = context.transpose(1, 2).contiguous().view(B, 1, self.d_model)

        # 输出投影 + squeeze → (B, d_model)
        out = self.out_proj(context).squeeze(1)
        return out
