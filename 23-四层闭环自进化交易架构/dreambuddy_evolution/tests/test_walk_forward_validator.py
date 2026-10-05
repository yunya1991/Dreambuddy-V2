"""
P1-4 RED 测试集 — Walk-Forward 样本外验证器

P1-4: 对 promote 的基因做 walk-forward 验证
  - 训练集（前 70%）跑 check_promotion_with_stats → promote 决策
  - 测试集（后 30%）验证 promote 的基因是否仍统计显著
  - 返回样本外验证报告（OOS p 值/胜率/效应量）

参考: dream-science-hypothesis-verification SKILL（样本外验证章节）
      architecture-evaluation-23.md P1 改进建议 #4
"""
from __future__ import annotations

import pytest


# --------------------------------------------------------------------------------
# RED: 模块尚未创建
# --------------------------------------------------------------------------------
def test_module_importable():
    from dreambuddy_evolution.core.walk_forward_validator import (  # noqa: F401
        WalkForwardValidator,
        WalkForwardResult,
    )


# --------------------------------------------------------------------------------
# Walk-Forward 验证逻辑
# --------------------------------------------------------------------------------
class TestWalkForwardValidator:
    def _strong_samples(self, n=80):
        """强信号样本: 75% 胜率, 交错排列 [W,W,W,L] 重复（避免时序偏差）."""
        # 每 4 个一组: 3 胜 1 负 → 75% 胜率
        result = []
        for i in range(n):
            if i % 4 < 3:
                result.append({"pnl_pct": 0.03})
            else:
                result.append({"pnl_pct": -0.01})
        return result

    def _weak_samples(self, n=80):
        """弱信号样本: 50% 胜率, 交错排列 [W,L] 重复."""
        result = []
        for i in range(n):
            if i % 2 == 0:
                result.append({"pnl_pct": 0.02})
            else:
                result.append({"pnl_pct": -0.02})
        return result

    def test_returns_result_with_required_fields(self):
        """验证结果必须包含 train/test 双侧统计字段."""
        from dreambuddy_evolution.core.walk_forward_validator import WalkForwardValidator
        v = WalkForwardValidator()
        result = v.validate(self._strong_samples(80), train_ratio=0.7)
        for key in ("train_decision", "test_stats", "oos_pass", "train_ratio"):
            assert key in result, f"结果缺少字段: {key}"

    def test_strong_signal_oos_pass(self):
        """强信号样本应通过 walk-forward（训练 promote, 测试仍显著）."""
        from dreambuddy_evolution.core.walk_forward_validator import WalkForwardValidator
        v = WalkForwardValidator()
        result = v.validate(self._strong_samples(80), train_ratio=0.7)
        # 80 样本: 56 训练 + 24 测试
        assert result["train_decision"]["promote"] is True
        assert result["oos_pass"] is True

    def test_weak_signal_oos_fail(self):
        """弱信号样本应不通过 walk-forward（训练不 promote 或测试不显著）."""
        from dreambuddy_evolution.core.walk_forward_validator import WalkForwardValidator
        v = WalkForwardValidator()
        result = v.validate(self._weak_samples(80), train_ratio=0.7)
        assert result["oos_pass"] is False

    def test_insufficient_samples_returns_oos_fail(self):
        """样本不足（<2*MIN_PROMOTION_SAMPLES）应直接 oos_pass=False."""
        from dreambuddy_evolution.core.walk_forward_validator import WalkForwardValidator
        v = WalkForwardValidator()
        result = v.validate([{"pnl_pct": 0.05}] * 20, train_ratio=0.7)
        assert result["oos_pass"] is False
        assert "insufficient" in result.get("reason", "").lower() or "sample" in result.get("reason", "").lower()

    def test_test_stats_includes_p_value_and_win_rate(self):
        """测试集统计必须包含 p_value, win_rate, effect_size, ci."""
        from dreambuddy_evolution.core.walk_forward_validator import WalkForwardValidator
        v = WalkForwardValidator()
        result = v.validate(self._strong_samples(80), train_ratio=0.7)
        ts = result["test_stats"]
        for key in ("p_value", "win_rate", "effect_size", "ci_lower", "ci_upper"):
            assert key in ts, f"test_stats 缺少字段: {key}"

    def test_train_ratio_clamped_to_valid_range(self):
        """train_ratio 超出 (0,1) 应被 clamp 或 FAIL-OPEN."""
        from dreambuddy_evolution.core.walk_forward_validator import WalkForwardValidator
        v = WalkForwardValidator()
        # 极端 ratio 不应 crash
        r1 = v.validate(self._strong_samples(80), train_ratio=0.99)
        r2 = v.validate(self._strong_samples(80), train_ratio=0.01)
        assert isinstance(r1["oos_pass"], bool)
        assert isinstance(r2["oos_pass"], bool)

    def test_fail_open_on_empty_samples(self):
        """空样本应 FAIL-OPEN 返回 oos_pass=False."""
        from dreambuddy_evolution.core.walk_forward_validator import WalkForwardValidator
        v = WalkForwardValidator()
        result = v.validate([], train_ratio=0.7)
        assert result["oos_pass"] is False

    def test_oos_pass_requires_train_promote_and_test_significant(self):
        """oos_pass=True 必须同时满足: 训练 promote=True 且 测试集 p<0.05."""
        from dreambuddy_evolution.core.walk_forward_validator import WalkForwardValidator
        v = WalkForwardValidator()
        # 构造: 训练集强(42样本 75%胜率 promote) + 测试集弱(18样本 50%胜率)
        # 60 样本满足 MIN_REQUIRED=60, train_ratio=0.7 → 42 train + 18 test
        train = []
        for i in range(42):
            train.append({"pnl_pct": 0.03 if i % 4 < 3 else -0.005})
        test = []
        for i in range(18):
            test.append({"pnl_pct": 0.02 if i % 2 == 0 else -0.02})
        samples = train + test
        result = v.validate(samples, train_ratio=0.7)
        # 训练 promote，但测试集 50% 胜率不显著 → oos_pass=False
        assert result["oos_pass"] is False


class TestWalkForwardResultDataclass:
    def test_result_is_dict_compatible(self):
        """结果对象应可作 dict 访问（或本身是 dict）."""
        from dreambuddy_evolution.core.walk_forward_validator import WalkForwardValidator
        v = WalkForwardValidator()
        # 构造强信号样本
        samples = [{"pnl_pct": 0.03 if i % 4 < 3 else -0.01} for i in range(80)]
        result = v.validate(samples, train_ratio=0.7)
        # dict 或 dataclass → asdict 都可，关键是字段可访问
        assert result["oos_pass"] in (True, False)
