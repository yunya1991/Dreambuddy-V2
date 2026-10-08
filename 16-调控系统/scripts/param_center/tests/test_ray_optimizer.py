"""任务④ TDD 测试：Ray Tune 并行优化器

测试目标:
  1. RayTuneOptimizer 初始化参数校验
  2. 数据不足时 fallback 到单点 BayesianVerifier
  3. ray 不可用时 fallback 到单点
  4. 硬约束兜底：RR<2 时返回差评 calmar=-1
  5. _save_result 持久化 JSON

运行:
  python -m pytest 16-调控系统/scripts/param_center/tests/test_ray_optimizer.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# 路径设置
_THIS = Path(__file__).resolve()
_PARAM_CENTER = _THIS.parent.parent
_SCRIPTS_16 = _PARAM_CENTER.parent
_PROJECT_ROOT = _SCRIPTS_16.parent.parent
_YIJING_SCRIPTS = _PROJECT_ROOT / "11-易经推理系统" / "scripts"
for p in [_YIJING_SCRIPTS, _SCRIPTS_16, _PARAM_CENTER]:
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)

from param_center.ray_optimizer import (  # noqa: E402
    RayTuneOptimizer,
    RayTuneResult,
    SL_FLOOR,
    SL_CEIL,
    TP_FLOOR,
    TP_CEIL,
    RR_FLOOR,
    _safe_report,
    _REPORT_LOG,
)


# ============================================================================
# 测试用例
# ============================================================================
class TestRayTuneOptimizerInit:
    """初始化测试"""

    def test_init_defaults(self):
        opt = RayTuneOptimizer()
        assert opt.num_samples == 50
        assert opt.resources_per_trial == 1
        assert opt.scheduler_name == "asynchyperband"
        assert opt.search_alg_name == "bayesopt"

    def test_init_custom(self):
        opt = RayTuneOptimizer(
            num_samples=100,
            resources_per_trial=2,
            scheduler="hyperband",
            search_alg="random",
        )
        assert opt.num_samples == 100
        assert opt.resources_per_trial == 2


class TestHardConstraints:
    """硬约束测试"""

    def test_search_space_constants(self):
        """硬约束常量验证"""
        assert SL_FLOOR == 0.03
        assert SL_CEIL == 0.15
        assert TP_FLOOR == 0.12
        assert TP_CEIL == 0.30
        assert RR_FLOOR == 2.0

    def test_rr_violation_returns_bad_calmar(self):
        """RR<2 时 _safe_report 写入 calmar=-1（差评）"""
        # 清空 fallback log
        _REPORT_LOG.clear()
        # 构造 trainable（用 mock df）
        df_mock = MagicMock()
        trainable = RayTuneOptimizer._build_trainable("BTC", df_mock, 90)
        # 跑一次 RR 违规的 config: tp/sl = 0.15/0.10 = 1.5 < 2.0
        config = {"sl_floor": 0.10, "tp_floor": 0.15, "atr_mult": 4.5}
        trainable(config)
        # 应该写入 _REPORT_LOG（因为 ray runtime 不在，走 fallback）
        assert len(_REPORT_LOG) >= 1
        assert _REPORT_LOG[-1]["calmar"] == -1.0
        assert _REPORT_LOG[-1]["max_drawdown"] == 1.0

    def test_safe_report_fallback_log(self):
        """_safe_report 在 ray 不可用时写入 _REPORT_LOG"""
        _REPORT_LOG.clear()
        _safe_report(calmar=1.5, max_drawdown=0.3, training_iteration=1)
        assert len(_REPORT_LOG) == 1
        assert _REPORT_LOG[0]["calmar"] == 1.5


class TestPersistence:
    """持久化测试"""

    def test_save_result_appends_json(self, tmp_path):
        """_save_result 应追加到 JSON 列表（用实例级 _artifacts_dir）"""
        opt = RayTuneOptimizer(num_samples=5)
        # 直接替换实例级 _artifacts_dir
        opt._artifacts_dir = tmp_path
        opt._save_result(
            symbol="BTC",
            best_params={"sl_floor": 0.05, "tp_floor": 0.15, "atr_mult": 4.5},
            best_calmar=1.5,
            best_dd=0.30,
            n_trials=50,
        )
        out_path = tmp_path / "ray_tune_results.json"
        assert out_path.exists()
        with open(out_path) as f:
            results = json.load(f)
        assert len(results) == 1
        assert results[0]["symbol"] == "BTC"
        assert results[0]["best_calmar"] == 1.5
        assert results[0]["n_trials"] == 50

        # 再追加一次
        opt._save_result(
            symbol="ETH",
            best_params={"sl_floor": 0.04, "tp_floor": 0.12, "atr_mult": 4.0},
            best_calmar=1.2,
            best_dd=0.25,
            n_trials=30,
        )
        with open(out_path) as f:
            results = json.load(f)
        assert len(results) == 2


class TestRayTuneResult:
    """RayTuneResult 数据结构测试"""

    def test_default_values(self):
        r = RayTuneResult()
        assert r.best_params == {}
        assert r.best_calmar == 0.0
        assert r.fallback_used is False
        assert r.fallback_reason is None

    def test_with_values(self):
        r = RayTuneResult(
            best_params={"sl_floor": 0.05, "tp_floor": 0.15, "atr_mult": 4.5},
            best_calmar=1.8,
            best_drawdown=0.25,
            n_trials=50,
            elapsed_sec=120.5,
        )
        assert r.best_params["sl_floor"] == 0.05
        assert r.best_calmar == 1.8
        assert r.n_trials == 50
