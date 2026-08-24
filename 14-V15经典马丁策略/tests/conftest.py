"""conftest.py — V15 测试套件共享 fixtures & helpers.

合并自 test_ab_comparator.py / test_incremental_trainer.py / test_dual_baseline_framework.py
的公共基础设施，消除 3 份文件中的重复 import 和 fixture 定义。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# 路径设置 — 确保 V15 root 在 sys.path
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent
_V15_ROOT = _HERE.parent
if str(_V15_ROOT) not in sys.path:
    sys.path.insert(0, str(_V15_ROOT))

# ---------------------------------------------------------------------------
# 共享导入
# ---------------------------------------------------------------------------

from ab_shadow_comparator import (  # noqa: E402
    ABShadowComparator,
    ABComparatorState,
    DecisionRecord,
    STATE_SHADOW,
    STATE_LIVE,
    STATE_DISABLED,
    MIN_SAMPLES_FOR_TEST,
    SHADOW_TO_LIVE_MIN_GAIN,
    SHADOW_TO_LIVE_PVALUE,
    LIVE_TO_SHADOW_PVALUE,
    LIVE_TO_SHADOW_MAX_LOSS,
    EVALUATION_WINDOW_DAYS,
    LIVE_EVALUATION_WINDOW_DAYS,
)

from incremental_trainer import (  # noqa: E402
    ModelVersionManager,
    IncrementalTrainer,
    IncrementalTrainerState,
    DEFAULT_WINDOW_DAYS,
    DEFAULT_MIN_NEW_TRADES,
)

# ---------------------------------------------------------------------------
# 共享 Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fresh_comp(tmp_path):
    """每次测试创建全新的 ABShadowComparator。"""
    return ABShadowComparator(state_file=str(tmp_path / "ab.json"))


@pytest.fixture
def fresh_state(tmp_path):
    """创建 ABShadowComparator 并强制 SHADOW 状态。"""
    f = tmp_path / "ab_state.json"
    comp = ABShadowComparator(state_file=str(f))
    comp.force_state(STATE_SHADOW)
    return comp, f


@pytest.fixture
def mgr(tmp_path):
    """创建 ModelVersionManager。"""
    base = tmp_path / "phase_d_models"
    state = tmp_path / "inc_state.json"
    base.mkdir(parents=True, exist_ok=True)
    return ModelVersionManager(base_dir=str(base), state_file=str(state))


# ---------------------------------------------------------------------------
# 共享 Helpers
# ---------------------------------------------------------------------------


def _fake_pt_file(path, size=8):
    """生成占位 .pt 文件（小体积，用于版本管理测试）。"""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"\0" * size)
    return str(path)


def _make_pt_file(path: Path):
    """生成占位 .pt 文件（双基线框架测试用）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x50\x54\x46\x21")
    return str(path)


def _mock_metrics(pnl=1.0, win_rate=0.60, mdd=0.10, trades=10, wins=6):
    """生成回测指标 mock 数据。"""
    return {
        'total_pnl': pnl,
        'total_trades': trades,
        'win_trades': wins,
        'win_rate': win_rate,
        'max_drawdown': mdd,
        'label': '',
    }


def _ts(hours_offset: int) -> str:
    """返回 N 小时前的 UTC ISO（带 Z）。"""
    dt = datetime.utcnow() - timedelta(hours=hours_offset)
    return dt.isoformat() + "Z"


def _make_fake_bilstm_file(path: Path):
    """生成能被 BiLSTMAttentionBust 加载的 state_dict 文件。"""
    import torch
    ai_dir = str(_V15_ROOT / "ai_trainers")
    if ai_dir not in sys.path:
        sys.path.insert(0, ai_dir)
    from phase_d_models import BiLSTMAttentionBust

    m1 = BiLSTMAttentionBust(ohlcv_len=60, n_channels=5, n_scalar=7, hidden=48, n_layers=2)
    payload = {
        "meta": {"ohlcv_len": 60, "n_channels": 5, "n_scalar": 7, "hidden": 48, "n_layers": 2},
        "state_dict": m1.state_dict(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(payload, str(path))
    return str(path)


def _make_fake_patchtst_file(path: Path):
    """生成能被 PatchTSTForDrawdown 加载的 state_dict 文件。"""
    import torch
    ai_dir = str(_V15_ROOT / "ai_trainers")
    if ai_dir not in sys.path:
        sys.path.insert(0, ai_dir)
    from phase_d_models import PatchTSTForDrawdown

    m2 = PatchTSTForDrawdown(c_in=5, seq_len=120, patch_len=12, stride=6,
                             d_model=32, n_layers=2, n_heads=4, d_ff=64)
    payload = {
        "meta": {"c_in": 5, "seq_len": 120, "patch_len": 12, "stride": 6,
                 "d_model": 32, "n_layers": 2, "n_heads": 4, "d_ff": 64},
        "state_dict": m2.state_dict(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(payload, str(path))
    return str(path)
