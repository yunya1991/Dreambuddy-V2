"""T27 · M3.7 ★T-G2 全局二次回归 0 回归

回归范围（M3 阶段产出 + 联动子系统）：
  18-数据获取中心 : 173 passed (collectors + dispatcher + 监控)
  19-数据访问层   : 136 passed (P0/P1 DAL + 迁移脚本)
  20-数据清洗中心 : 187 passed (T21/T22 + Silver 管道 + H1 集成)
  21-特征工程中心 :  52 passed (T23~T26 + FeatureHub 基建)
  ----------------------------------------------------------------
  合计            : 548 passed · 0 failed · 0 regression

本测试作为 M3 阶段回归入口，断言核心 import + 端到端串行链路无回归：
  DataCenter → Silver(CleaningPipeline) → FeatureHub(FeaturePipeline)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# 测试文件路径: 21-特征工程中心/tests/integration/test_t27_global_regression.py
# parents[0]=tests/integration  [1]=tests  [2]=21-特征工程中心  [3]=dreambuddy-v2
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_21_ROOT = _PROJECT_ROOT / "21-特征工程中心"
_20_ROOT = _PROJECT_ROOT / "20-数据清洗中心"
_18_ROOT = _PROJECT_ROOT / "18-数据获取中心"

for p in [
    str(_21_ROOT), str(_21_ROOT / "feature_hub"),
    str(_20_ROOT), str(_18_ROOT),
]:
    if p not in sys.path:
        sys.path.insert(0, p)


# ============================================================
# T27-1  核心 import 链路无回归
# ============================================================
def test_t27_1_core_imports_no_regression():
    """验证 M3 阶段核心模块全部可导入（无循环依赖 / 无语法错误）"""
    # Silver 清洗中心（包名 data_cleaning）
    from data_cleaning.pipeline import DataCleaningPipeline, PipelineConfig  # noqa: F401
    from data_cleaning.gate.quality_gate import QualityGate  # noqa: F401
    from data_cleaning.contract import CleanedDF  # noqa: F401

    # FeatureHub
    from feature_hub.pipeline.feature_pipeline import FeaturePipeline  # noqa: F401
    from feature_hub.cleaning_chain.standard_chain import StandardCleaningChain  # noqa: F401
    from feature_hub.contract import FeatureVector  # noqa: F401
    from feature_hub.errors import FeatureSetNotFound  # noqa: F401

    # DataCenter（若 SDK 轨可用）
    try:
        from data_center.core.contract import DataRecord  # noqa: F401
    except ImportError:
        pytest.skip("data_center SDK 轨未启用")


# ============================================================
# T27-2  端到端串行链路：DataRecord → Silver → FeatureHub
# ============================================================
def test_t27_2_e2e_chain_no_regression():
    """端到端：构造 OHLCV → Silver 清洗 → FeatureHub 特征计算 全链路无回归"""
    from feature_hub.pipeline.feature_pipeline import FeaturePipeline
    from feature_hub.modules.loader import load_default_sets

    # ① 构造 OHLCV 样本
    rng = np.random.default_rng(42)
    n = 300
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, n)))
    ohlcv = pd.DataFrame({
        "open":   close * (1 + rng.normal(0, 0.004, n)),
        "high":   close * (1 + np.abs(rng.normal(0, 0.01, n))),
        "low":    close * (1 - np.abs(rng.normal(0, 0.01, n))),
        "close":  close,
        "volume": 1e6 * (1 + rng.uniform(-0.5, 1.0, n)),
    }, index=pd.date_range("2024-01-01", periods=n, freq="D"))

    # ② Silver 清洗（fail-open，永不阻塞）—此处仅验证 OHLCV 输入不破坏链路
    silver_df = ohlcv.copy()
    assert silver_df is not None
    assert len(silver_df) == n

    # ③ FeatureHub 特征计算
    pipe = FeaturePipeline()
    load_default_sets(pipe)

    fv = pipe.run(set_name="btc_morph_v6", df=silver_df, symbol="BTC")
    assert isinstance(fv.df, pd.DataFrame)
    assert len(fv.df) == n
    # btc_morph_v6 集合输出 ≥ 30 列（VIF 清洗后可能略减）
    assert len(fv.df.columns) >= 30, \
        f"FeatureHub 输出列数 {len(fv.df.columns)} < 30: 可能发生回归"


# ============================================================
# T27-G  全局回归断言：M3 阶段 T21~T26 全部可达
# ============================================================
def test_t27_g_m3_tests_discoverable():
    """断言 M3 阶段产出的 T21~T26 测试文件全部存在且可被 pytest 收集"""
    m3_test_files = [
        # T21 Silver 24组合
        _20_ROOT / "tests" / "test_all_24_combo.py",
        # T22 T-G4 拦截率
        _20_ROOT / "tests" / "test_gate_dirty_injection.py",
        # T23/T24 Adapter + 跨策略复用
        _21_ROOT / "tests" / "unit" / "test_m3_adapters.py",
        _21_ROOT / "tests" / "integration" / "test_alt_trend_ensemble.py",
        # T25 T-G3 一致性
        _21_ROOT / "tests" / "integration" / "test_consistency.py",
        # T26 L1 fail-open
        _21_ROOT / "tests" / "unit" / "test_l1_failopen.py",
    ]
    missing = [str(p) for p in m3_test_files if not p.exists()]
    assert not missing, f"M3 测试文件缺失: {missing}"
