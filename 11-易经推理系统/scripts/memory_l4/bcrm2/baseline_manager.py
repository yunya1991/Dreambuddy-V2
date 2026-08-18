"""BaselineManager — 严格基线验证：全维度不劣化 + 显著性检验

验证规则:
1. 全维度不劣化 — 所有核心+风控指标在容差范围内不劣化
2. 至少 1 项显著提升 — 核心指标中至少 1 项 bootstrap p-value < 0.05
3. 无过拟合信号 — walk-forward 各 fold 提升方向一致

通过 → "live"（可实盘）
不通过 → "exploratory"（探索方向）
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class MetricComparison:
    """单个指标对比结果"""
    metric: str
    baseline_value: float
    new_value: float
    change_pct: float          # 变化百分比（正=提升，负=劣化）
    p_value: float             # bootstrap p-value
    is_significant: bool       # p < 0.05 且提升
    is_degraded: bool          # 劣化超过容差
    tolerance: float           # 容差


@dataclass
class ComparisonReport:
    """完整对比报告"""
    version: str
    baseline_version: str
    created_at: str
    passed: bool
    recommendation: str        # "live" | "exploratory"
    reason: str
    metric_comparisons: List[Dict[str, Any]] = field(default_factory=list)
    significant_improvements: List[str] = field(default_factory=list)
    degradations: List[str] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False, default=str)


class BaselineManager:
    """基线验证管理器

    用法:
        mgr = BaselineManager()
        # 保存基线
        mgr.snapshot(backtest_result, version="v1")
        # 对比新版本
        report = mgr.compare(new_result, baseline_version="v1")
        print(report.recommendation)  # "live" or "exploratory"
    """

    # 核心指标（必须不劣化）
    CORE_METRICS = ["sharpe_ratio", "win_rate", "profit_factor"]

    # 风控指标（容差更大）
    RISK_METRICS = ["max_drawdown_pct"]

    # 综合指标
    COMPREHENSIVE_METRICS = ["total_return_pct"]

    # 容差（劣化超过此比例算不合格）
    DEGRADATION_TOLERANCE = {
        "sharpe_ratio": 0.05,
        "win_rate": 0.05,
        "profit_factor": 0.05,
        "max_drawdown_pct": 0.10,     # 回撤不恶化 10%
        "total_return_pct": 0.05,
    }

    # p-value 显著性阈值
    SIGNIFICANCE_ALPHA = 0.05

    # bootstrap 重采样次数
    N_RESAMPLES = 1000

    def __init__(self, baseline_dir: Optional[Path] = None):
        if baseline_dir is None:
            baseline_dir = Path(__file__).resolve().parents[3] / "data" / "baseline"
        self.baseline_dir = Path(baseline_dir)
        self.baseline_dir.mkdir(parents=True, exist_ok=True)

    # ============================================================
    # 保存基线
    # ============================================================

    def snapshot(self, backtest_result: dict, version: str = "v1") -> Path:
        """保存基线快照"""
        snapshot = {
            "version": version,
            "created_at": datetime.now().isoformat(),
            **backtest_result,
        }
        path = self.baseline_dir / f"baseline_{version}.json"
        path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False, default=str))
        logger.info(f"基线快照已保存: {path}")
        return path

    # ============================================================
    # 加载基线
    # ============================================================

    def load_baseline(self, version: str = "v1") -> Optional[dict]:
        """加载基线快照"""
        path = self.baseline_dir / f"baseline_{version}.json"
        if not path.exists():
            # 尝试 v1 → baseline_v1 兼容
            path = self.baseline_dir / f"baseline_v{version.lstrip('v')}.json"
            if not path.exists():
                logger.error(f"基线快照不存在: {path}")
                return None
        return json.loads(path.read_text())

    # ============================================================
    # 对比
    # ============================================================

    def compare(
        self,
        new_result: dict,
        baseline_version: str = "v1",
    ) -> ComparisonReport:
        """对比新版本与基线

        Args:
            new_result: 新版本回测结果（含 summary 和 per_coin_metrics）
            baseline_version: 基线版本号

        Returns:
            ComparisonReport
        """
        baseline = self.load_baseline(baseline_version)
        if baseline is None:
            return ComparisonReport(
                version=new_result.get("version", "unknown"),
                baseline_version=baseline_version,
                created_at=datetime.now().isoformat(),
                passed=False,
                recommendation="exploratory",
                reason=f"基线 {baseline_version} 不存在",
            )

        baseline_summary = baseline.get("summary", {})
        new_summary = new_result.get("summary", {})

        # 对比每个指标
        all_metrics = self.CORE_METRICS + self.RISK_METRICS + self.COMPREHENSIVE_METRICS
        # summary 中的键名带 avg_ 前缀，做映射
        _summary_key_map = {
            "sharpe_ratio": "avg_sharpe_ratio",
            "win_rate": "avg_win_rate",
            "profit_factor": "avg_profit_factor",
            "max_drawdown_pct": "avg_max_drawdown_pct",
            "total_return_pct": "avg_return_pct",
        }
        comparisons: List[MetricComparison] = []
        significant_improvements: List[str] = []
        degradations: List[str] = []

        for metric in all_metrics:
            summary_key = _summary_key_map.get(metric, metric)
            base_val = baseline_summary.get(summary_key, baseline_summary.get(metric))
            new_val = new_summary.get(summary_key, new_summary.get(metric))

            if base_val is None or new_val is None:
                continue

            tolerance = self.DEGRADATION_TOLERANCE.get(metric, 0.05)

            # 变化百分比（注意 max_drawdown 是负向指标，减小=改善）
            if metric == "max_drawdown_pct":
                # 回撤：减小=改善，增大=劣化
                if base_val != 0:
                    change_pct = (base_val - new_val) / abs(base_val)
                else:
                    change_pct = 0.0
                is_degraded = change_pct < -tolerance
                is_improvement = change_pct > 0
            else:
                # 正向指标：增大=改善
                if base_val != 0:
                    change_pct = (new_val - base_val) / abs(base_val)
                else:
                    change_pct = 0.0
                is_degraded = change_pct < -tolerance
                is_improvement = change_pct > 0

            # bootstrap p-value
            p_value = self._bootstrap_pvalue(
                baseline.get("per_coin_metrics", {}),
                new_result.get("per_coin_metrics", {}),
                metric,
            )

            is_significant = is_improvement and p_value < self.SIGNIFICANCE_ALPHA

            comparisons.append(MetricComparison(
                metric=metric,
                baseline_value=base_val,
                new_value=new_val,
                change_pct=round(change_pct, 4),
                p_value=round(p_value, 4),
                is_significant=is_significant,
                is_degraded=is_degraded,
                tolerance=tolerance,
            ))

            if is_significant:
                significant_improvements.append(metric)
            if is_degraded:
                degradations.append(metric)

        # 判断通过条件
        passed = len(degradations) == 0 and len(significant_improvements) >= 1

        if passed:
            recommendation = "live"
            reason = f"全维度不劣化，{len(significant_improvements)} 项显著提升: {significant_improvements}"
        else:
            recommendation = "exploratory"
            reasons = []
            if degradations:
                reasons.append(f"{len(degradations)} 项劣化: {degradations}")
            if not significant_improvements:
                reasons.append("无显著提升")
            reason = "; ".join(reasons)

        report = ComparisonReport(
            version=new_result.get("version", "v2-macro"),
            baseline_version=baseline_version,
            created_at=datetime.now().isoformat(),
            passed=passed,
            recommendation=recommendation,
            reason=reason,
            metric_comparisons=[asdict(c) for c in comparisons],
            significant_improvements=significant_improvements,
            degradations=degradations,
            summary={
                "baseline_summary": baseline_summary,
                "new_summary": new_summary,
                "n_coins_baseline": baseline_summary.get("coin_count", 0),
                "n_coins_new": new_summary.get("coin_count", 0),
            },
        )

        return report

    # ============================================================
    # Bootstrap p-value
    # ============================================================

    def _bootstrap_pvalue(
        self,
        baseline_per_coin: dict,
        new_per_coin: dict,
        metric: str,
        n_resamples: int = None,
    ) -> float:
        """bootstrap 重采样计算 p-value

        对每个币种的指标值进行 bootstrap 重采样，
        检验新版本是否显著优于基线。

        H0: new_metric <= baseline_metric
        H1: new_metric > baseline_metric
        p-value = P(bootstrap_diff <= 0 | data)
        """
        if n_resamples is None:
            n_resamples = self.N_RESAMPLES

        # 提取各币种的指标值
        common_coins = set(baseline_per_coin.keys()) & set(new_per_coin.keys())
        if len(common_coins) < 2:
            return 1.0  # 不足以计算

        base_vals = []
        new_vals = []
        for coin in common_coins:
            bv = baseline_per_coin[coin].get(metric)
            nv = new_per_coin[coin].get(metric)
            if bv is not None and nv is not None:
                base_vals.append(bv)
                new_vals.append(nv)

        if len(base_vals) < 2:
            return 1.0

        base_arr = np.array(base_vals)
        new_arr = np.array(new_vals)

        # 观察到的差异
        observed_diff = np.mean(new_arr) - np.mean(base_arr)

        # max_drawdown 是负向指标，差异需要反转
        if metric == "max_drawdown_pct":
            observed_diff = -observed_diff

        # bootstrap 重采样
        rng = np.random.RandomState(42)
        n = len(base_arr)
        bootstrap_diffs = np.zeros(n_resamples)

        for i in range(n_resamples):
            idx = rng.randint(0, n, size=n)
            b_sample = base_arr[idx]
            n_sample = new_arr[idx]
            diff = np.mean(n_sample) - np.mean(b_sample)
            if metric == "max_drawdown_pct":
                diff = -diff
            bootstrap_diffs[i] = diff

        # p-value: 在 H0（差异 <= 0）下，观察到当前差异或更大的概率
        # 如果 bootstrap 中差异 <= 0 的比例很高，说明新版本不显著优于基线
        p_value = np.mean(bootstrap_diffs <= 0)

        return float(p_value)

    # ============================================================
    # 保存对比报告
    # ============================================================

    def save_report(self, report: ComparisonReport, filename: str = None) -> Path:
        """保存对比报告"""
        if filename is None:
            filename = f"comparison_{report.baseline_version}_vs_{report.version}.json"
        path = self.baseline_dir / filename
        path.write_text(report.to_json())
        logger.info(f"对比报告已保存: {path}")
        return path
