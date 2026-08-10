"""
Phase D 模型定义（PyTorch）

1) BiLSTMAttentionBust：
   - 输入: (B, 60, 5) 4H OHLCV + (B, 7) 标量特征
   - 结构: 双向 LSTM → additive attention → concat scalar → MLP → sigmoid
   - 输出: (B, 1) P_bust ∈[0,1]

2) PatchTSTForDrawdown（按 PatchTST A Time Series is Worth 64 Words 实现，简化单变量预测头）
   - 输入: (B, 120, 5) 1H OHLCV
   - 切 patch: patch_len=12 stride=6 → num_patches = (120-12)/6 + 1 = 19
   - 每个 patch 线性映射到 d_model，加可学习位置编码
   - 若干层标准 Transformer Encoder
   - 取 CLS token / mean pooling → 线性 head 回归 (B, 1) 预测 max_drawdown
"""

from __future__ import annotations

import math
from typing import Tuple

import torch
import torch.nn.functional as F
from torch import Tensor, nn


# ================================================================
# BiLSTM + Additive Attention 爆仓预测器
# ================================================================
class AdditiveAttention(nn.Module):
    def __init__(self, hidden: int):
        super().__init__()
        self.W = nn.Linear(hidden, hidden, bias=True)
        self.v = nn.Linear(hidden, 1, bias=False)

    def forward(self, h: Tensor) -> Tuple[Tensor, Tensor]:
        """h: (B, T, H) → 输出 (B, H) 加权和, (B, T, 1) 注意力权重"""
        e = self.v(torch.tanh(self.W(h)))  # (B,T,1)
        a = F.softmax(e, dim=1)            # (B,T,1)
        return (a * h).sum(dim=1), a


class BiLSTMAttentionBust(nn.Module):
    def __init__(
        self,
        ohlcv_len: int = 60,
        n_channels: int = 5,
        n_scalar: int = 7,
        hidden: int = 48,
        n_layers: int = 2,
        dropout: float = 0.20,
    ) -> None:
        super().__init__()
        self.ohlcv_len = int(ohlcv_len)
        self.n_channels = int(n_channels)
        self.n_scalar = int(n_scalar)
        self.hidden = int(hidden)
        self.n_layers = int(n_layers)

        self.lstm = nn.LSTM(
            input_size=self.n_channels,
            hidden_size=self.hidden,
            num_layers=self.n_layers,
            batch_first=True,
            bidirectional=True,
            dropout=dropout if n_layers > 1 else 0.0,
        )
        self.attn = AdditiveAttention(self.hidden * 2)  # bidir → 2x hidden
        total_dim = self.hidden * 2 + self.n_scalar
        self.head = nn.Sequential(
            nn.Linear(total_dim, total_dim // 2),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(total_dim // 2, 1),
            nn.Sigmoid(),  # P_bust ∈ [0,1]
        )

    def forward(self, ohlcv: Tensor, scalar: Tensor) -> Tensor:
        """
        ohlcv:  (B, ohlcv_len, n_channels)
        scalar: (B, n_scalar)
        Returns: (B, 1)
        """
        h, _ = self.lstm(ohlcv)  # (B, T, H*2)
        ctx, _ = self.attn(h)    # (B, H*2)
        z = torch.cat([ctx, scalar], dim=-1)
        return self.head(z)


# ================================================================
# PatchTST（回归：未来 24 根 1H K 线的 max drawdown ∈ [-1,0]）
# ================================================================
class PatchEmbedding(nn.Module):
    def __init__(self, c_in: int, patch_len: int, d_model: int):
        super().__init__()
        self.patch_len = int(patch_len)
        self.c_in = int(c_in)
        self.proj = nn.Linear(self.c_in * self.patch_len, d_model)

    def forward(self, x: Tensor) -> Tensor:
        """x: (B, num_patches, patch_len, c_in) 4D patch windows → (B, num_patches, d_model)"""
        if x.ndim == 4:
            B, N, P, C = x.shape
            x = x.flatten(start_dim=2)  # (B, N, P*C)
        else:
            # 兼容 (B, T, C) 当作单个 patch：仅防御性 fallback
            B, T, C = x.shape
            P = T
            N = 1
            x = x.flatten(start_dim=1).unsqueeze(1)
        return self.proj(x)


def _to_patch_windows(x: Tensor, patch_len: int, stride: int) -> Tensor:
    """用 unfold 做滑窗切 patch
    x: (B, T, C) → (B, num_patches, patch_len, C)
    num_patches = (T - patch_len) // stride + 1
    """
    B, T, C = x.shape
    # unfold 要求在 T 维度上：将 (B, C, T) unfold 在最后一维 → (B, C, patch_len, num_patches)
    xbc = x.transpose(1, 2).contiguous()  # (B, C, T)
    patches = xbc.unfold(dimension=2, size=patch_len, step=stride)  # (B,C,num_patches,patch_len)
    patches = patches.permute(0, 2, 3, 1).contiguous()  # (B,num_patches,patch_len,C)
    return patches


class TransformerEncoderLayer(nn.Module):
    def __init__(self, d_model: int, n_heads: int, d_ff: int, dropout: float = 0.1):
        super().__init__()
        self.self_attn = nn.MultiheadAttention(
            embed_dim=d_model, num_heads=n_heads, dropout=dropout, batch_first=True
        )
        self.ff = nn.Sequential(
            nn.Linear(d_model, d_ff),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(d_ff, d_model),
        )
        self.norm1 = nn.LayerNorm(d_model)
        self.norm2 = nn.LayerNorm(d_model)
        self.drop1 = nn.Dropout(dropout)
        self.drop2 = nn.Dropout(dropout)

    def forward(self, x: Tensor) -> Tensor:
        a, _ = self.self_attn(x, x, x, need_weights=False)
        x = self.norm1(x + self.drop1(a))
        x = self.norm2(x + self.drop2(self.ff(x)))
        return x


class PatchTSTForDrawdown(nn.Module):
    def __init__(
        self,
        c_in: int = 5,
        seq_len: int = 120,
        patch_len: int = 12,
        stride: int = 6,
        d_model: int = 32,
        n_layers: int = 2,
        n_heads: int = 4,
        d_ff: int = 64,
        dropout: float = 0.10,
    ) -> None:
        super().__init__()
        self.c_in = c_in
        self.seq_len = seq_len
        self.patch_len = patch_len
        self.stride = stride
        self.num_patches = (seq_len - patch_len) // stride + 1
        self.d_model = d_model

        self.patch_embed = PatchEmbedding(c_in=c_in, patch_len=patch_len, d_model=d_model)
        self.pos_embed = nn.Parameter(torch.randn(1, self.num_patches, d_model) * 0.02)
        self.cls = nn.Parameter(torch.zeros(1, 1, d_model))
        self.layers = nn.ModuleList([
            TransformerEncoderLayer(d_model, n_heads, d_ff, dropout) for _ in range(n_layers)
        ])
        self.norm = nn.LayerNorm(d_model)
        self.head = nn.Sequential(
            nn.Linear(d_model, d_model // 2),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(d_model // 2, 1),
        )

    def forward(self, x: Tensor) -> Tensor:
        """x: (B, seq_len=120, c_in=5) → (B, 1) 负回撤比例（回归，无 sigmoid/tanh 钳制，训练时靠 MSE 即可）"""
        B = x.shape[0]
        pw = _to_patch_windows(x, self.patch_len, self.stride)  # (B,N,patch_len,C)
        N = pw.shape[1]
        # 若由于 seq_len 不同导致 N 与预期不同，重新计算 position embedding （防御性）
        if N != self.num_patches:
            pos = F.interpolate(
                self.pos_embed.transpose(1, 2), size=N, mode="linear", align_corners=False
            ).transpose(1, 2)
        else:
            pos = self.pos_embed
        z = self.patch_embed(pw) + pos  # (B, N, d_model)
        cls = self.cls.expand(B, -1, -1)
        z = torch.cat([cls, z], dim=1)  # (B, N+1, d_model)
        for layer in self.layers:
            z = layer(z)
        z = self.norm(z[:, 0])  # 取 CLS token
        return self.head(z)  # (B, 1)
