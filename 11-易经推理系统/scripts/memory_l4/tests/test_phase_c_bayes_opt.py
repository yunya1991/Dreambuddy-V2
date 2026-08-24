"""T_C4 验收测试：贝叶斯优化（phase_c_bayes_opt.py）

位置: scripts/memory_l4/tests/test_phase_c_bayes_opt.py
运行: cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4 && python -m pytest tests/test_phase_c_bayes_opt.py -v

对应 Plan §T_C4: 贝叶斯优化。

核心验证：
  • PhaseCBayesianOptimizer 类可实例化
  • optimize 方法存在
  • 参数空间包含 4 个参数（alpha_blend, fft_learning_rate, hermite_m0, hermite_m1）
  • 目标函数返回 float
  • mock Optuna 验证 optimize 返回 best_params 结构
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add bcrm2 to sys.path
THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))


# ================================================================
# T_C4: 贝叶斯优化
# ================================================================

class TestPhaseCBayesianOptimizer:
    """验证 PhaseCBayesianOptimizer 类。"""

    def test_class_importable(self):
        """T_C4.1: PhaseCBayesianOptimizer 类可实例化。"""
        from bcrm2.scripts.phase_c_bayes_opt import PhaseCBayesianOptimizer
        opt = PhaseCBayesianOptimizer(n_trials=10, n_folds=2)
        assert opt is not None
        assert opt.n_trials == 10
        assert opt.n_folds == 2

    def test_optimize_method_exists(self):
        """T_C4.2: optimize 方法存在。"""
        from bcrm2.scripts.phase_c_bayes_opt import PhaseCBayesianOptimizer
        opt = PhaseCBayesianOptimizer()
        assert hasattr(opt, "optimize")
        assert callable(opt.optimize)

    def test_param_space_has_four_params(self):
        """T_C4.3: 参数空间包含 4 个参数。"""
        from bcrm2.scripts.phase_c_bayes_opt import PhaseCBayesianOptimizer
        opt = PhaseCBayesianOptimizer()
        # 参数空间定义在类属性或实例属性
        space = getattr(opt, "param_space", None) or getattr(opt, "PARAM_SPACE", None)
        assert space is not None
        assert "alpha_blend" in space
        assert "fft_learning_rate" in space
        assert "hermite_m0" in space
        assert "hermite_m1" in space
        # alpha_blend 范围 [0, 0.5]
        lo, hi = space["alpha_blend"]
        assert lo == 0.0
        assert hi == 0.5

    def test_objective_returns_float(self):
        """T_C4.4: 目标函数返回 float。"""
        from bcrm2.scripts.phase_c_bayes_opt import PhaseCBayesianOptimizer

        opt = PhaseCBayesianOptimizer(n_trials=5, n_folds=1)

        # mock trial
        mock_trial = MagicMock()
        mock_trial.suggest_float.return_value = 0.2

        # mock run_alpha_blend_comparison + Path.exists
        with patch("bcrm2.scripts.phase_c_bayes_opt.run_alpha_blend_comparison") as mock_run, \
             patch("pathlib.Path.exists", return_value=True):
            mock_run.return_value = {
                "alpha_results": {"0.2": {"sharpe": 1.5}},
            }
            result = opt._objective(mock_trial, "BTCUSDT", Path("fake.csv"))

        assert isinstance(result, float)
        assert result == 1.5

    def test_optimize_returns_best_params(self):
        """T_C4.5: mock Optuna 验证 optimize 返回 best_params 结构。"""
        from bcrm2.scripts.phase_c_bayes_opt import PhaseCBayesianOptimizer

        opt = PhaseCBayesianOptimizer(n_trials=5, n_folds=1)

        # mock Optuna study
        mock_study = MagicMock()
        mock_study.best_params = {
            "alpha_blend": 0.3,
            "fft_learning_rate": 0.1,
            "hermite_m0": 1.0,
            "hermite_m1": 0.5,
        }
        mock_study.best_value = 1.8

        with patch("bcrm2.scripts.phase_c_bayes_opt.optuna") as mock_optuna_mod, \
             patch("bcrm2.scripts.phase_c_bayes_opt.run_alpha_blend_comparison"):
            mock_optuna_mod.create_study.return_value = mock_study
            result = opt.optimize(symbol="BTCUSDT", csv_path=Path("fake.csv"))

        assert "best_params" in result
        assert "best_value" in result
        assert "n_trials" in result
        assert result["best_params"]["alpha_blend"] == 0.3
        assert result["best_value"] == 1.8
        assert result["n_trials"] == 5

    def test_alpha_blend_max_constraint(self):
        """T_C4.6: alpha_blend 参数范围受 ALPHA_BLEND_MAX=0.5 约束。"""
        from bcrm2.scripts.phase_c_bayes_opt import PhaseCBayesianOptimizer
        from bcrm2.parameter_mapper import ALPHA_BLEND_MAX

        opt = PhaseCBayesianOptimizer()
        space = getattr(opt, "param_space", None) or getattr(opt, "PARAM_SPACE", None)
        lo, hi = space["alpha_blend"]
        assert hi <= ALPHA_BLEND_MAX
