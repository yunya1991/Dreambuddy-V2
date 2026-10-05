"""
Walk-Forward 样本外验证器（P1-4 改进）

P1-4: 对 promote 的基因做 walk-forward 验证

流程:
  1. 将样本按时间顺序分割为训练集（前 train_ratio）+ 测试集（后 1-train_ratio）
  2. 训练集上跑 check_promotion_with_stats → promote 决策
  3. 如果训练集 promote=True，在测试集上验证统计显著性
  4. oos_pass = train_promote=True AND test_set p<0.05 AND test_set win_rate>0.5

防过拟合: 训练集优化的基因必须在未见样本上保持统计显著才算通过。
参考: dream-science-hypothesis-verification SKILL（样本外验证章节）
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# 延迟导入避免循环依赖
def _import_check():
    from dreambuddy_evolution.core.gene_promotion_stats import (
        check_promotion_with_stats,
        binomial_test_pvalue,
        cohens_d,
        win_rate_ci,
        MIN_PROMOTION_SAMPLES,
    )
    return check_promotion_with_stats, binomial_test_pvalue, cohens_d, win_rate_ci, MIN_PROMOTION_SAMPLES


class WalkForwardResult(dict):
    """walk-forward 验证结果（dict 子类方便字段访问）."""
    pass


class WalkForwardValidator:
    """Walk-Forward 样本外验证器.

    用法:
        v = WalkForwardValidator()
        result = v.validate(samples, train_ratio=0.7)
        if result["oos_pass"]:
            print("基因通过样本外验证")
    """

    DEFAULT_TRAIN_RATIO = 0.7
    P_VALUE_SIG = 0.05
    MIN_WIN_RATE = 0.50

    def __init__(self) -> None:
        try:
            (self._check, self._pval, self._d, self._ci,
             self._min_n) = _import_check()
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[P1-4] 导入 gene_promotion_stats 失败: {exc}")
            self._check = None
            self._min_n = 30

    def validate(self, samples: list[dict[str, Any]],
                 train_ratio: float = 0.7) -> dict[str, Any]:
        """执行 walk-forward 样本外验证.

        Args:
            samples: [{"pnl_pct": float, ...}, ...] 按时间顺序
            train_ratio: 训练集占比 (默认 0.7)

        Returns:
            {
              "train_ratio": float,
              "n_train": int,
              "n_test": int,
              "train_decision": dict,  # check_promotion_with_stats 结果
              "test_stats": dict,     # 测试集统计
              "oos_pass": bool,
              "reason": str,
            }
        """
        # FAIL-OPEN: 空样本
        if not samples:
            return WalkForwardResult({
                "train_ratio": train_ratio,
                "n_train": 0, "n_test": 0,
                "train_decision": {"promote": False},
                "test_stats": {},
                "oos_pass": False,
                "reason": "insufficient samples (empty)",
            })

        # clamp train_ratio 到合理范围
        train_ratio = max(0.5, min(0.9, float(train_ratio)))

        n = len(samples)
        n_train = int(n * train_ratio)
        n_test = n - n_train

        # 样本不足：需要训练集和测试集都满足统计检验最低要求
        min_required = self._min_n * 2  # 训练+测试各需 ≥30
        if n < min_required or n_train < self._min_n or n_test < 5:
            return WalkForwardResult({
                "train_ratio": train_ratio,
                "n_train": n_train, "n_test": n_test,
                "train_decision": {"promote": False, "reason": f"N={n} < {min_required}"},
                "test_stats": {},
                "oos_pass": False,
                "reason": f"insufficient samples (need {min_required}, got {n})",
            })

        train_samples = samples[:n_train]
        test_samples = samples[n_train:]

        # 训练集决策
        if self._check is None:
            return WalkForwardResult({
                "train_ratio": train_ratio,
                "n_train": n_train, "n_test": n_test,
                "train_decision": {"promote": False, "reason": "check_promotion_with_stats unavailable"},
                "test_stats": {},
                "oos_pass": False,
                "reason": "FAIL-OPEN: stats module unavailable",
            })

        train_decision = self._check(train_samples)

        # 训练集未 promote → 直接不通过
        if not train_decision.get("promote"):
            return WalkForwardResult({
                "train_ratio": train_ratio,
                "n_train": n_train, "n_test": n_test,
                "train_decision": train_decision,
                "test_stats": {},
                "oos_pass": False,
                "reason": f"train not promoted: {train_decision.get('reason')}",
            })

        # 测试集统计
        test_stats = self._compute_test_stats(test_samples)

        # oos_pass = 测试集统计显著 + 胜率>50% + avg_pnl>0
        oos_pass = (
            test_stats["p_value"] < self.P_VALUE_SIG
            and test_stats["win_rate"] > self.MIN_WIN_RATE
            and test_stats["avg_pnl"] > 0
        )

        reason = (
            f"train promote + test p={test_stats['p_value']:.4f} "
            f"wr={test_stats['win_rate']:.0%} d={test_stats['effect_size']:.3f} "
            f"CI=[{test_stats['ci_lower']:.2f},{test_stats['ci_upper']:.2f}]"
        )

        return WalkForwardResult({
            "train_ratio": train_ratio,
            "n_train": n_train, "n_test": n_test,
            "train_decision": train_decision,
            "test_stats": test_stats,
            "oos_pass": oos_pass,
            "reason": reason,
        })

    def _compute_test_stats(self, test_samples: list[dict[str, Any]]) -> dict[str, Any]:
        """计算测试集统计（复用 gene_promotion_stats 原语）."""
        n = len(test_samples)
        pnl_values = [float(s.get("pnl_pct", 0.0)) for s in test_samples]
        wins = sum(1 for p in pnl_values if p > 0)
        win_rate = wins / n if n > 0 else 0.0
        avg_pnl = sum(pnl_values) / n if n > 0 else 0.0
        p_value = self._pval(wins, n, p_h0=0.5)
        d = self._d(pnl_values)
        ci_low, ci_high = self._ci(wins, n, conf=0.95)

        return {
            "n": n,
            "win_rate": round(win_rate, 4),
            "avg_pnl": round(avg_pnl, 6),
            "p_value": round(p_value, 6),
            "effect_size": round(d, 4),
            "ci_lower": round(ci_low, 4),
            "ci_upper": round(ci_high, 4),
        }
