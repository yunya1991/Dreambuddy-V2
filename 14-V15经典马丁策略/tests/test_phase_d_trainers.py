"""
Phase D 模型训练脚本最小行为测试 (TDD RED/GREEN)

T8 · BiLSTM-Attention 模型：
  - 输入 (B, 60, 5) OHLCV + (B, 7) scalar → 输出 (B, 1) sigmoid 概率
  - forward 输出值必须 ∈[0,1]
  - train 脚本必须支持从 phase_d_meta.json 读维度，训练 1 epoch 不报错 & 保存权重

T9 · PatchTST 模型：
  - 输入 (B, 120, 5) OHLCV；patch_len=12, stride=6；patch 数 N 必须正确
  - 输出 (B, 1) 回归（负的 max drawdown）
  - train 脚本：WF 切分跑 5 个 split，评估打印 AUC/MSE

T10 · 训练脚本 CLI 冒烟：--n-epochs=1 --quick-smoke 下，两个脚本都能完整跑完并落盘权重且尺寸 > 0
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pytest

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "ai_trainers"))
sys.path.insert(0, str(BASE_DIR / "core"))
sys.path.insert(0, str(BASE_DIR / "lib"))


# ---------------------------------------------------------------- T8
class TestBiLSTMAttention:
    def test_model_forward_shape_and_value_range(self):
        from phase_d_models import BiLSTMAttentionBust

        import torch

        m = BiLSTMAttentionBust(ohlcv_len=60, n_scalar=7, hidden=48, n_layers=2)
        ohlcv = torch.randn(3, 60, 5)
        scal = torch.randn(3, 7)
        y = m(ohlcv, scal)
        assert y.shape == (3, 1)
        # sigmoid: all must ∈ [0,1]
        with torch.no_grad():
            assert float(y.min()) >= 0.0
            assert float(y.max()) <= 1.0

    def test_train_script_runs_smoke(self, tmp_path: Path):
        """--epochs 1 --quick-smoke 必须不报错，保存 .pt 文件且 size>0"""
        from subprocess import check_call

        ds_dir = tmp_path / "ds"
        ds_dir.mkdir()
        (ds_dir / "phase_d_train_all.npz").write_bytes(b"dummy")
        out_dir = tmp_path / "models"
        check_call(
            [
                sys.executable,
                str(BASE_DIR / "phase_d_train_bilstm.py"),
                "--data",
                str(ds_dir / "phase_d_train_all.npz"),
                "--epochs",
                "1",
                "--quick-smoke",
                "--out",
                str(out_dir / "bilstm.pt"),
            ],
            cwd=str(BASE_DIR),
        )
        assert (out_dir / "bilstm.pt").is_file()
        assert (out_dir / "bilstm.pt").stat().st_size > 0


# ---------------------------------------------------------------- T9
class TestPatchTST:
    def test_patch_slicing_and_out_shape(self):
        from phase_d_models import PatchTSTForDrawdown

        import torch

        m = PatchTSTForDrawdown(c_in=5, seq_len=120, patch_len=12, stride=6, d_model=32)
        x = torch.randn(4, 120, 5)
        y = m(x)
        assert y.shape == (4, 1)

    def test_patch_count_formula(self):
        """patch_len=12 stride=6 seq_len=120 → 必须 (120-12)/6 + 1 = 19 patch"""
        from phase_d_models import PatchTSTForDrawdown

        m = PatchTSTForDrawdown(c_in=5, seq_len=120, patch_len=12, stride=6, d_model=16)
        assert m.num_patches == 19

    def test_train_script_smoke(self, tmp_path: Path):
        """PatchTST 训练 CLI --quick-smoke 不报错且权重落盘"""
        from subprocess import check_call

        out = tmp_path / "patch.pt"
        check_call(
            [
                sys.executable,
                str(BASE_DIR / "phase_d_train_patchtst.py"),
                "--epochs",
                "1",
                "--quick-smoke",
                "--out",
                str(out),
            ],
            cwd=str(BASE_DIR),
        )
        assert out.is_file() and out.stat().st_size > 0


# ---------------------------------------------------------------- T10
class TestTrainingOutputs:
    def test_phase_d_trainers_import_paths_exist(self):
        """根目录必须包含 2 个训练脚本文件（存在性）"""
        assert (BASE_DIR / "phase_d_train_bilstm.py").is_file()
        assert (BASE_DIR / "phase_d_train_patchtst.py").is_file()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-header", "-x"])
