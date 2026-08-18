#!/usr/bin/env python3
"""Phase D Model Definitions — BiLSTM-Attention 爆仓预警 + PatchTST 回撤预测.

This module defines the two Phase D deep learning models:
  1. BiLSTMAttentionBust  — predicts martingale bust probability (P_bust)
  2. PatchTSTForDrawdown  — predicts 24h max drawdown depth

Both models are designed for CPU inference (lightweight architecture)
and follow the interface expected by phase_d_gateway.py.

Architecture references:
  - BiLSTM-Attention: houzhaohan martingale bust warning paper
  - PatchTST: "A Time Series is Worth 64 Words" (ICLR 2023)

Author: Dreambuddy-V2 DreamOS
Version: 1.0.0
Date: 2026-08-18
"""
from __future__ import annotations

import math
from typing import Optional, Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F


class BiLSTMAttentionBust(nn.Module):
    """BiLSTM-Attention model for martingale bust probability prediction.

    Input:
      - ohlcv: (batch, ohlcv_len, n_channels)  — OHLCV price sequence
      - scalar: (batch, n_scalar)              — 7-dim scalar features

    Output:
      - p_bust: (batch, 1)  — bust probability in [0, 1] (sigmoid)

    Architecture:
      BiLSTM(n_channels -> hidden, bidirectional, n_layers)
      → Attention pooling (learned weights)
      → Concat with scalar features
      → MLP(hidden*2 + n_scalar -> hidden -> 1)
      → Sigmoid
    """

    def __init__(
        self,
        ohlcv_len: int = 60,
        n_channels: int = 5,
        n_scalar: int = 7,
        hidden: int = 48,
        n_layers: int = 2,
        dropout: float = 0.1,
    ):
        super().__init__()
        self.ohlcv_len = ohlcv_len
        self.n_channels = n_channels
        self.n_scalar = n_scalar
        self.hidden = hidden
        self.n_layers = n_layers

        # Input normalization (learnable, per-channel)
        self.input_norm = nn.LayerNorm(n_channels)

        # BiLSTM encoder
        self.lstm = nn.LSTM(
            input_size=n_channels,
            hidden_size=hidden,
            num_layers=n_layers,
            batch_first=True,
            bidirectional=True,
            dropout=dropout if n_layers > 1 else 0.0,
        )

        # Attention mechanism (additive attention)
        self.attn_w = nn.Linear(hidden * 2, 1, bias=True)

        # Scalar feature projection
        self.scalar_proj = nn.Linear(n_scalar, hidden)

        # Fusion MLP
        self.mlp = nn.Sequential(
            nn.Linear(hidden * 2 + hidden, hidden),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden, hidden // 2),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden // 2, 1),
        )

    def forward(
        self,
        ohlcv: torch.Tensor,
        scalar: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        """Forward pass.

        Args:
            ohlcv:  (batch, ohlcv_len, n_channels)
            scalar: (batch, n_scalar) or None

        Returns:
            p_bust: (batch, 1) in [0, 1]
        """
        batch_size = ohlcv.size(0)

        # Normalize input
        x = self.input_norm(ohlcv)

        # BiLSTM encoding
        lstm_out, _ = self.lstm(x)  # (batch, seq, hidden*2)

        # Attention pooling
        attn_scores = self.attn_w(lstm_out)  # (batch, seq, 1)
        attn_weights = F.softmax(attn_scores, dim=1)  # (batch, seq, 1)
        context = (lstm_out * attn_weights).sum(dim=1)  # (batch, hidden*2)

        # Scalar features
        if scalar is not None:
            scalar_emb = self.scalar_proj(scalar)  # (batch, hidden)
        else:
            scalar_emb = torch.zeros(batch_size, self.hidden, device=ohlcv.device)

        # Fusion
        fused = torch.cat([context, scalar_emb], dim=-1)  # (batch, hidden*2 + hidden)
        logits = self.mlp(fused)  # (batch, 1)
        p_bust = torch.sigmoid(logits)

        return p_bust


class PatchTSTForDrawdown(nn.Module):
    """PatchTST model for 24h max drawdown prediction.

    Input:
      - series: (batch, c_in, seq_len)  — multivariate time series (OHLCV)

    Output:
      - drawdown: (batch, 1)  — predicted max drawdown depth (negative value, e.g. -0.15 = -15%)

    Architecture (PatchTST — channel-independent):
      1. Patch embedding: divide sequence into patches
      2. Linear projection to d_model
      3. Transformer encoder (n_layers, n_heads)
      4. Pooling + MLP head → drawdown prediction

    Reference: "A Time Series is Worth 64 Words: Long-term Forecasting with Transformers" (ICLR 2023)
    """

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
        dropout: float = 0.1,
    ):
        super().__init__()
        self.c_in = c_in
        self.seq_len = seq_len
        self.patch_len = patch_len
        self.stride = stride
        self.d_model = d_model

        # Calculate number of patches
        self.num_patches = (seq_len - patch_len) // stride + 1
        if self.num_patches < 1:
            self.num_patches = 1

        # Patch embedding (channel-independent: each channel processed separately)
        self.patch_proj = nn.Linear(patch_len, d_model)

        # Positional encoding (learnable)
        self.pos_embed = nn.Parameter(torch.randn(1, self.num_patches, d_model) * 0.02)

        # Transformer encoder
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=n_heads,
            dim_feedforward=d_ff,
            dropout=dropout,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)

        # Output head: predict drawdown
        self.head = nn.Sequential(
            nn.Linear(d_model, d_ff),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(d_ff, d_ff // 2),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(d_ff // 2, 1),
        )

        # Input normalization (per-channel, learnable)
        self.input_norm = nn.LayerNorm(c_in)

    def _create_patches(self, x: torch.Tensor) -> torch.Tensor:
        """Create patches from time series (channel-independent).

        Args:
            x: (batch, c_in, seq_len)

        Returns:
            patches: (batch * c_in, num_patches, patch_len)
        """
        batch, c_in, seq_len = x.shape

        # Unfold to create patches: (batch, c_in, num_patches, patch_len)
        patches = x.unfold(dimension=-1, size=self.patch_len, step=self.stride)
        # Shape: (batch, c_in, num_patches, patch_len)

        # Channel-independent: merge batch and channel dims
        patches = patches.reshape(batch * c_in, self.num_patches, self.patch_len)

        return patches

    def forward(self, series: torch.Tensor) -> torch.Tensor:
        """Forward pass.

        Args:
            series: (batch, c_in, seq_len) — OHLCV multivariate series

        Returns:
            drawdown: (batch, 1) — predicted max drawdown (negative value)
        """
        batch = series.size(0)

        # Normalize input: LayerNorm over last dim (c_in=5)
        # Input: (batch, c_in, seq_len) → transpose to (batch, seq_len, c_in) for LayerNorm
        x = series.transpose(1, 2)  # (batch, seq_len, c_in)
        x = self.input_norm(x)       # LayerNorm over c_in dim
        x = x.transpose(1, 2)        # back to (batch, c_in, seq_len)

        # Create patches (channel-independent)
        patches = self._create_patches(x)  # (batch*c_in, num_patches, patch_len)

        # Project patches to d_model
        patch_emb = self.patch_proj(patches)  # (batch*c_in, num_patches, d_model)

        # Add positional encoding
        patch_emb = patch_emb + self.pos_embed  # broadcast

        # Transformer encoding
        encoded = self.transformer(patch_emb)  # (batch*c_in, num_patches, d_model)

        # Pooling: mean over patches
        pooled = encoded.mean(dim=1)  # (batch*c_in, d_model)

        # Channel-independent prediction: average across channels
        pooled = pooled.reshape(batch, self.c_in, self.d_model)
        pooled = pooled.mean(dim=1)  # (batch, d_model)

        # Output head
        drawdown = self.head(pooled)  # (batch, 1)

        return drawdown


# ── Model factory functions ───────────────────────────────────────────────────

def create_bilstm_model(
    ohlcv_len: int = 60,
    n_channels: int = 5,
    n_scalar: int = 7,
    hidden: int = 48,
    n_layers: int = 2,
) -> BiLSTMAttentionBust:
    """Create a BiLSTMAttentionBust model with default parameters."""
    return BiLSTMAttentionBust(
        ohlcv_len=ohlcv_len,
        n_channels=n_channels,
        n_scalar=n_scalar,
        hidden=hidden,
        n_layers=n_layers,
    )


def create_patchtst_model(
    c_in: int = 5,
    seq_len: int = 120,
    patch_len: int = 12,
    stride: int = 6,
    d_model: int = 32,
    n_layers: int = 2,
    n_heads: int = 4,
    d_ff: int = 64,
) -> PatchTSTForDrawdown:
    """Create a PatchTSTForDrawdown model with default parameters."""
    return PatchTSTForDrawdown(
        c_in=c_in,
        seq_len=seq_len,
        patch_len=patch_len,
        stride=stride,
        d_model=d_model,
        n_layers=n_layers,
        n_heads=n_heads,
        d_ff=d_ff,
    )


# ── Self-test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== Phase D Model Definitions Test ===")
    print()

    # Test BiLSTMAttentionBust
    print("[1] BiLSTMAttentionBust test...")
    model1 = BiLSTMAttentionBust(ohlcv_len=60, n_channels=5, n_scalar=7, hidden=48, n_layers=2)
    ohlcv = torch.randn(4, 60, 5)  # batch=4, seq=60, channels=5
    scalar = torch.randn(4, 7)      # batch=4, n_scalar=7
    p_bust = model1(ohlcv, scalar)
    print("  Input ohlcv:", ohlcv.shape)
    print("  Input scalar:", scalar.shape)
    print("  Output p_bust:", p_bust.shape, "range=[", p_bust.min().item(), ",", p_bust.max().item(), "]")
    n_params1 = sum(p.numel() for p in model1.parameters())
    print("  Parameters:", n_params1)
    assert p_bust.shape == (4, 1), "Output shape should be (4, 1)"
    assert 0 <= p_bust.min().item() <= p_bust.max().item() <= 1, "Output should be in [0, 1]"
    print("  OK")
    print()

    # Test PatchTSTForDrawdown
    print("[2] PatchTSTForDrawdown test...")
    model2 = PatchTSTForDrawdown(c_in=5, seq_len=120, patch_len=12, stride=6, d_model=32, n_layers=2, n_heads=4, d_ff=64)
    series = torch.randn(4, 5, 120)  # batch=4, channels=5, seq_len=120
    drawdown = model2(series)
    print("  Input series:", series.shape)
    print("  Output drawdown:", drawdown.shape, "values=", drawdown.squeeze().tolist())
    n_params2 = sum(p.numel() for p in model2.parameters())
    print("  Parameters:", n_params2)
    assert drawdown.shape == (4, 1), "Output shape should be (4, 1)"
    print("  OK")
    print()

    print("Total parameters: BiLSTM=", n_params1, " PatchTST=", n_params2)
    print("All tests passed!")
