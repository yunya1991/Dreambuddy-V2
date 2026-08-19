#!/usr/bin/env python3
"""Phase D Model Definitions — 单点入口（Thin Wrapper）.

v15-ab-fix: SSOT = ai_trainers/phase_d_models.py；本文件仅转发 + 工厂函数。
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Optional

_THIS_DIR = Path(__file__).resolve().parent
_V15_ROOT = _THIS_DIR.parent
_AI_TRAINERS_DIR = str(_V15_ROOT / "ai_trainers")

if _AI_TRAINERS_DIR not in sys.path:
    sys.path.insert(0, _AI_TRAINERS_DIR)

_phase_d_trainer_module = importlib.import_module("phase_d_models")

BiLSTMAttentionBust = _phase_d_trainer_module.BiLSTMAttentionBust
PatchTSTForDrawdown = _phase_d_trainer_module.PatchTSTForDrawdown

__all__ = [
    "BiLSTMAttentionBust",
    "PatchTSTForDrawdown",
    "create_bilstm_model",
    "create_patchtst_model",
]


def create_bilstm_model(
    ohlcv_len: int = 60,
    n_channels: int = 5,
    n_scalar: int = 7,
    hidden: int = 48,
    n_layers: int = 2,
    dropout: Optional[float] = None,
):
    kwargs = dict(ohlcv_len=ohlcv_len, n_channels=n_channels, n_scalar=n_scalar,
                  hidden=hidden, n_layers=n_layers)
    if dropout is not None:
        kwargs["dropout"] = dropout
    return BiLSTMAttentionBust(**kwargs)


def create_patchtst_model(
    c_in: int = 5, seq_len: int = 120, patch_len: int = 12, stride: int = 6,
    d_model: int = 32, n_layers: int = 2, n_heads: int = 4, d_ff: int = 64,
    dropout: Optional[float] = None,
):
    kwargs = dict(c_in=c_in, seq_len=seq_len, patch_len=patch_len, stride=stride,
                  d_model=d_model, n_layers=n_layers, n_heads=n_heads, d_ff=d_ff)
    if dropout is not None:
        kwargs["dropout"] = dropout
    return PatchTSTForDrawdown(**kwargs)


if __name__ == "__main__":
    import torch
    print("=== Phase D SSOT Wrapper Test ===")
    print(f"  ai_trainers 源: {_phase_d_trainer_module.__file__}")

    print("[1] BiLSTM...", end=" ")
    m1 = create_bilstm_model(ohlcv_len=60, n_channels=5, n_scalar=7, hidden=48, n_layers=2)
    ohlcv = torch.randn(4, 60, 5); scalar = torch.randn(4, 7)
    p = m1(ohlcv, scalar)
    assert p.shape == (4, 1) and 0 <= p.min().item() <= p.max().item() <= 1
    print(f"OK shape={tuple(p.shape)} params={sum(x.numel() for x in m1.parameters())}")

    print("[2] PatchTST...", end=" ")
    m2 = create_patchtst_model(c_in=5, seq_len=120, patch_len=12, stride=6, d_model=32, n_layers=2, n_heads=4, d_ff=64)
    s = torch.randn(4, 120, 5)
    d = m2(s)
    assert d.shape == (4, 1)
    print(f"OK shape={tuple(d.shape)} params={sum(x.numel() for x in m2.parameters())}")

    print("[3] SSOT 类身份一致性...", end=" ")
    assert BiLSTMAttentionBust is _phase_d_trainer_module.BiLSTMAttentionBust
    assert PatchTSTForDrawdown is _phase_d_trainer_module.PatchTSTForDrawdown
    print("PASS")
    print("All passed!")
