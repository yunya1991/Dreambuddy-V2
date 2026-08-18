"""
BCRM 回测门禁引擎。

用 walk-forward 回测验证模型胜率，决定是否通过门禁。
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict
from itertools import product

from .engine import BCRMEngine
from .walk_forward import (
    run_bcrm_backtest, generate_synthetic_data,
    WalkForwardResult,
)
from ._constants import (
    is_zhishi_gua, is_qushi_gua,
    get_gua_yin_yang,
    QUALITATIVE_PNL_REVERSAL_THRESHOLD,
    QUALITATIVE_LABEL_WINDOW,
    QUALITATIVE_THRESHOLD_PERCENTILE,
    QUALITATIVE_THRESHOLD_MIN,
    QUALITATIVE_THRESHOLD_MAX,
    QUALITATIVE_THRESHOLD_DEFAULT,
    CONSISTENCY_WEIGHT_OPPOSITION,
    CONSISTENCY_WEIGHT_QUANTITATIVE,
    CONSISTENCY_WEIGHT_NEGATION,
    CONSISTENCY_THRESHOLD,
    SPIRAL_FIRST_AFFIRMATION, SPIRAL_FIRST_NEGATION,
    SPIRAL_SECOND_NEGATION, SPIRAL_UNKNOWN,
    DIR_UP, DIR_DOWN, DIR_FLAT, DIR_TRANSITIONING,
)


@dataclass
class BacktestMetrics:
    """回测指标。"""
    total_bars: int = 0
    valid_predictions: int = 0
    fail_closed_count: int = 0
    correct_predictions: int = 0
    wrong_predictions: int = 0
    direction_accuracy: float = 0.0
    avg_confidence: float = 0.0
    pnl_simulation: float = 0.0
    win_rate: float = 0.0
    gua_stats: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    regime_stats: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    phase_stats: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    hexagram_stats: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    dialectical_consistency: float = 0.0
    consistency_samples: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_bars": self.total_bars,
            "valid_predictions": self.valid_predictions,
            "fail_closed_count": self.fail_closed_count,
            "correct_predictions": self.correct_predictions,
            "wrong_predictions": self.wrong_predictions,
            "direction_accuracy": round(self.direction_accuracy, 4),
            "avg_confidence": round(self.avg_confidence, 4),
            "pnl_simulation": round(self.pnl_simulation, 4),
            "win_rate": round(self.win_rate, 4),
            "gua_stats": self.gua_stats,
            "regime_stats": self.regime_stats,
            "phase_stats": self.phase_stats,
            "hexagram_stats": self.hexagram_stats,
            "dialectical_consistency": round(self.dialectical_consistency, 4),
            "consistency_samples": self.consistency_samples,
        }


@dataclass
class GateResult:
    """门禁结果。"""
    passed: bool
    overall_accuracy: float
    threshold: float
    regime_stability: bool
    metrics: BacktestMetrics
    report: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "overall_accuracy": round(self.overall_accuracy, 4),
            "threshold": self.threshold,
            "regime_stability": self.regime_stability,
            "metrics": self.metrics.to_dict(),
            "report": self.report,
        }

    def to_json(self, indent: int = 2) -> str:
        import json
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


class BacktestGateEngine:
    """
    BCRM 回测门禁引擎。
    """

    def __init__(self,
                 engine: BCRMEngine = None,
                 memory_adapter=None,
                 knowledge_base=None,
                 accuracy_threshold: float = 0.55):
        self.engine = engine or BCRMEngine()
        self.memory_adapter = memory_adapter
        self.knowledge_base = knowledge_base
        self.accuracy_threshold = accuracy_threshold

    def run_backtest(self,
                     data: List[Dict] = None,
                     train_window_size: int = 50,
                     test_window_size: int = 10,
                     step_size: int = 10,
                     use_walk_forward: bool = True) -> BacktestMetrics:
        """运行回测。"""
        if data is None:
            data = generate_synthetic_data(num_bars=300, seed=42)

        if use_walk_forward:
            wf_result = run_bcrm_backtest(
                self.engine,
                data=data,
                train_window_size=train_window_size,
                test_window_size=test_window_size,
                step_size=step_size,
                memory_adapter=self.memory_adapter,
                knowledge_base=self.knowledge_base,
            )
            return self._compute_metrics(wf_result, data)
        else:
            return BacktestMetrics()

    def _compute_metrics(self,
                         wf_result: WalkForwardResult,
                         data: List[Dict]) -> BacktestMetrics:
        """从 WalkForwardResult 计算详细指标。"""
        metrics = BacktestMetrics()
        metrics.total_bars = wf_result.total_bars
        metrics.correct_predictions = wf_result.correct_predictions
        metrics.wrong_predictions = wf_result.wrong_predictions
        metrics.direction_accuracy = wf_result.direction_accuracy
        metrics.fail_closed_count = wf_result.fail_closed_count
        metrics.avg_confidence = wf_result.avg_confidence
        metrics.win_rate = wf_result.direction_accuracy
        metrics.valid_predictions = (
            wf_result.correct_predictions + wf_result.wrong_predictions)

        gua_counts = defaultdict(lambda: {"total": 0, "correct": 0})
        regime_counts = defaultdict(lambda: {"total": 0, "correct": 0})
        hex_counts = defaultdict(lambda: {"total": 0, "correct": 0})
        total_consistency = 0.0
        consistency_samples = 0

        for window_result in wf_result.per_window_results:
            predictions = window_result.get("predictions", [])
            for pred in predictions:
                if pred.get("fail_closed", False):
                    continue

                gua = pred.get("bagua", "unknown")
                correct = pred.get("is_correct", False)
                gua_counts[gua]["total"] += 1
                if correct:
                    gua_counts[gua]["correct"] += 1

                regime = pred.get("regime", "unknown")
                regime_counts[regime]["total"] += 1
                if correct:
                    regime_counts[regime]["correct"] += 1

                hexagram = pred.get("hexagram", "")
                if hexagram:
                    hex_counts[hexagram]["total"] += 1
                    if correct:
                        hex_counts[hexagram]["correct"] += 1

                # 辩证一致性度量
                bcrm_output_dict = pred.get("bcrm_output", {})
                actual_outcome = pred.get("actual_outcome", {})
                if bcrm_output_dict and actual_outcome:
                    consistency = compute_dialectical_consistency(
                        bcrm_output_dict, actual_outcome)
                    total_consistency += consistency
                    consistency_samples += 1

        for gua, stats in gua_counts.items():
            metrics.gua_stats[gua] = {
                "total": stats["total"],
                "correct": stats["correct"],
                "accuracy": stats["correct"] / stats["total"] if stats["total"] > 0 else 0.0,
            }

        for regime, stats in regime_counts.items():
            metrics.regime_stats[regime] = {
                "total": stats["total"],
                "correct": stats["correct"],
                "accuracy": stats["correct"] / stats["total"] if stats["total"] > 0 else 0.0,
            }

        for hexagram, stats in hex_counts.items():
            metrics.hexagram_stats[hexagram] = {
                "total": stats["total"],
                "correct": stats["correct"],
                "accuracy": stats["correct"] / stats["total"] if stats["total"] > 0 else 0.0,
            }

        # 辩证一致性度量
        metrics.consistency_samples = consistency_samples
        if consistency_samples > 0:
            metrics.dialectical_consistency = total_consistency / consistency_samples

        return metrics

    def check_gate(self,
                   metrics: BacktestMetrics = None,
                   data: List[Dict] = None,
                   **backtest_kwargs) -> GateResult:
        """门禁检查。"""
        if metrics is None:
            metrics = self.run_backtest(data=data, **backtest_kwargs)

        accuracy_pass = metrics.direction_accuracy >= self.accuracy_threshold
        regime_stable = self._check_regime_stability(metrics)

        fail_rate = (metrics.fail_closed_count / metrics.total_bars
                     if metrics.total_bars > 0 else 1.0)
        fail_rate_pass = fail_rate < 0.3

        passed = accuracy_pass and regime_stable and fail_rate_pass

        report = self._generate_report(
            metrics, passed, accuracy_pass, regime_stable, fail_rate_pass)

        return GateResult(
            passed=passed,
            overall_accuracy=metrics.direction_accuracy,
            threshold=self.accuracy_threshold,
            regime_stability=regime_stable,
            metrics=metrics,
            report=report,
        )

    def _check_regime_stability(self, metrics: BacktestMetrics) -> bool:
        """检查跨 regime 稳定性。"""
        if not metrics.regime_stats:
            return True

        regimes_with_enough = {
            k: v for k, v in metrics.regime_stats.items()
            if v["total"] >= 5
        }

        if len(regimes_with_enough) < 2:
            return True

        min_acc = min(v["accuracy"] for v in regimes_with_enough.values())
        return min_acc >= 0.5

    def _generate_report(self,
                         metrics: BacktestMetrics,
                         passed: bool,
                         accuracy_pass: bool,
                         regime_stable: bool,
                         fail_rate_pass: bool) -> str:
        """生成报告。"""
        lines = []
        lines.append("=" * 60)
        lines.append("BCRM 回测门禁报告")
        lines.append("=" * 60)
        lines.append("")

        status = "✅ 通过" if passed else "❌ 未通过"
        lines.append(f"门禁结果: {status}")
        lines.append("")

        lines.append("--- 整体指标 ---")
        lines.append(f"总 bar 数: {metrics.total_bars}")
        lines.append(f"有效预测: {metrics.valid_predictions}")
        lines.append(f"Fail-closed: {metrics.fail_closed_count}")
        lines.append(f"方向准确率: {metrics.direction_accuracy:.2%}")
        lines.append(f"平均置信度: {metrics.avg_confidence:.2%}")
        lines.append("")

        lines.append("--- 门禁条件 ---")
        acc_status = "✅" if accuracy_pass else "❌"
        lines.append(f"{acc_status} 方向准确率 >= {self.accuracy_threshold:.0%}")
        reg_status = "✅" if regime_stable else "❌"
        lines.append(f"{reg_status} 跨 regime 稳定性")
        fr_status = "✅" if fail_rate_pass else "❌"
        lines.append(f"{fr_status} Fail-closed 率 < 30%")
        lines.append("")

        if metrics.gua_stats:
            lines.append("--- 分卦象统计 ---")
            for gua, stats in sorted(metrics.gua_stats.items(),
                                     key=lambda x: -x[1]["accuracy"]):
                lines.append(
                    f"  {gua:6s}: 准确率={stats['accuracy']:.2%}, "
                    f"样本数={stats['total']}")
            lines.append("")

        lines.append("=" * 60)
        return "\n".join(lines)

    def run_parameter_sweep(self,
                             data: List[Dict] = None,
                             param_ranges: Dict[str, List] = None,
                             metric_key: str = "direction_accuracy"
                             ) -> List[Tuple[Dict, float]]:
        """参数扫描。"""
        if data is None:
            data = generate_synthetic_data(num_bars=300, seed=42)

        if param_ranges is None:
            param_ranges = {
                "min_confidence_threshold": [0.5, 0.6, 0.7],
            }

        results = []
        keys = list(param_ranges.keys())
        value_lists = [param_ranges[k] for k in keys]

        for combo in product(*value_lists):
            params = dict(zip(keys, combo))

            test_engine = BCRMEngine(**params)
            gate = BacktestGateEngine(engine=test_engine)
            metrics = gate.run_backtest(
                data=data,
                train_window_size=80,
                test_window_size=20,
                step_size=30,
            )

            accuracy = metrics.direction_accuracy
            coverage = metrics.valid_predictions / metrics.total_bars if metrics.total_bars > 0 else 0

            coverage_penalty = 0
            if coverage < 0.5:
                coverage_penalty = (0.5 - coverage) * 0.5

            score = accuracy - coverage_penalty

            full_params = {**params, "coverage": coverage, "accuracy": accuracy}
            results.append((full_params, score))

        results.sort(key=lambda x: x[1], reverse=True)
        return results


def default_backtest_gate() -> BacktestGateEngine:
    """获取默认回测门禁引擎。"""
    return BacktestGateEngine()


# ============================================================
# 质变阈值回测校准（双标签法 + 25 分位数）
# ============================================================

def label_qualitative_change(cases: List[Dict],
                              window: int = QUALITATIVE_LABEL_WINDOW) -> List[Dict]:
    """
    在 L4 历史 cases 上标注"质变已发生"的样本。

    双标签法:
      主标签: 卦象从蓄势（艮/兑）切换到趋势（乾/坤）
      辅标签: 切换后 window 个 bar 内 PnL 反转幅度 > 3%

    只有同时满足主+辅标签，才视为"真质变"。
    """
    labeled = []
    for i in range(len(cases) - window):
        case = cases[i]
        future_cases = cases[i + 1: i + 1 + window]

        # 主标签：蓄势 → 趋势
        pre_gua = case.get("bagua", "")
        post_guas = [c.get("bagua", "") for c in future_cases]
        zhishi_to_qushi = (
            is_zhishi_gua(pre_gua) and
            any(is_qushi_gua(g) for g in post_guas if g)
        )

        # 辅标签：PnL 反转
        pre_pnl = case.get("pnl", case.get("price_change", 0))
        future_pnls = [c.get("pnl", c.get("price_change", 0))
                       for c in future_cases]
        if future_pnls:
            max_reversal = max(abs(p - pre_pnl) for p in future_pnls)
            pnl_reversed = max_reversal > QUALITATIVE_PNL_REVERSAL_THRESHOLD
        else:
            pnl_reversed = False

        # 真质变：主+辅同时满足
        is_real = zhishi_to_qushi and pnl_reversed

        labeled.append({
            **case,
            "pre_gua": pre_gua,
            "zhishi_to_qushi": zhishi_to_qushi,
            "pnl_reversed": pnl_reversed,
            "is_real_qualitative_change": is_real,
            "accumulation_at_trigger": case.get("accumulation", 0.5),
        })

    return labeled


def calibrate_threshold(labeled_cases: List[Dict]) -> float:
    """
    从标注样本中校准质变 threshold。

    方法:
      1. 取所有"真质变"样本的 accumulation_at_trigger
      2. 取 25 分位数作为 threshold（保守策略）

    保守策略理由:
      - 宁可错过质变（false negative），不可错判（false positive）
      - 错过质变只是少赚，错判质变可能亏损
      - 25 分位数意味着 75% 的真质变会被触发，同时过滤 25% 的低累积度噪声
    """
    real_changes = [c for c in labeled_cases
                    if c.get("is_real_qualitative_change")]
    accumulations = [c["accumulation_at_trigger"] for c in real_changes
                     if "accumulation_at_trigger" in c]

    if not accumulations:
        return QUALITATIVE_THRESHOLD_DEFAULT

    # 手动计算百分位数（避免 numpy 依赖）
    accumulations.sort()
    n = len(accumulations)
    rank = (QUALITATIVE_THRESHOLD_PERCENTILE / 100) * (n - 1)
    lower = int(rank)
    upper = min(lower + 1, n - 1)
    frac = rank - lower
    threshold = accumulations[lower] * (1 - frac) + accumulations[upper] * frac

    # 边界约束：threshold 必须在 [0.5, 0.9] 之间
    threshold = max(QUALITATIVE_THRESHOLD_MIN,
                    min(QUALITATIVE_THRESHOLD_MAX, threshold))

    return threshold


def calibrate_engine_threshold(engine: BCRMEngine,
                                cases: List[Dict] = None,
                                data: List[Dict] = None) -> float:
    """
    便捷函数：从回测数据中校准引擎的质变阈值。

    如果没有现成的 cases，则从回测数据中提取。
    """
    if cases is None:
        if data is None:
            data = generate_synthetic_data(num_bars=300, seed=42)
        cases = _extract_cases_from_data(data)

    if len(cases) < QUALITATIVE_LABEL_WINDOW + 1:
        return QUALITATIVE_THRESHOLD_DEFAULT

    labeled = label_qualitative_change(cases)
    threshold = calibrate_threshold(labeled)

    # 更新引擎阈值
    engine.qualitative_threshold = threshold

    return threshold


def _extract_cases_from_data(data: List[Dict]) -> List[Dict]:
    """从回测数据中提取 cases 格式（供双标签法使用）。"""
    from .yijing_engine import YijingEngine

    engine = YijingEngine()
    cases = []

    for i, bar in enumerate(data):
        sd = bar.get("supply_demand_score", 0.5)
        tech = bar.get("technical_score", 0.5)
        cf = bar.get("capital_flow_score", 0.5)
        sent = bar.get("sentiment_score", 0.5)

        yijing_result = engine.infer(
            supply_demand_score=sd,
            technical_score=tech,
            capital_flow_score=cf,
            sentiment_score=sent,
            trend_strength=bar.get("trend_strength", 0.5),
            volatility=bar.get("volatility", 0.5),
            volume_ratio=bar.get("volume_ratio", 1.0),
            price_position=bar.get("price_position", 0.5),
        )

        # PnL：与前一 bar 的价格变化
        pnl = 0.0
        if i > 0:
            prev_price = data[i - 1].get("close",
                                          data[i - 1].get("price", 0))
            cur_price = bar.get("close", bar.get("price", 0))
            if prev_price > 0:
                pnl = (cur_price - prev_price) / prev_price

        cases.append({
            "bagua": yijing_result.outer_gua,
            "pnl": pnl,
            "price_change": pnl,
            "accumulation": bar.get("trend_strength", 0.5),
        })

    return cases


# ============================================================
# 辩证一致性度量（三子维度加权）
# ============================================================

def compute_dialectical_consistency(bcrm_output: Dict,
                                     actual_outcome: Dict) -> float:
    """
    辩证一致性度量（参考 SIEV ΔDS）。

    三子维度:
      1. 对立一致性（40%）：主矛盾和主要方面是否正确识别
      2. 量变一致性（30%）：accumulation 和 threshold 是否符合历史规律
      3. 否定一致性（30%）：螺旋阶段判定是否符合实际反转

    返回: 0.0 ~ 1.0，> 0.7 视为一致
    """
    # 1. 对立一致性
    predicted_contradiction = bcrm_output.get(
        "contradiction_state", {}).get("dominant_side", "EQUAL")
    actual_contradiction = _infer_actual_contradiction(actual_outcome)
    opposition_consistency = (
        1.0 if predicted_contradiction == actual_contradiction else 0.5
    )

    # 2. 量变一致性
    predicted_transformation = bcrm_output.get(
        "transformation_trigger", {}).get("probability", "LOW")
    actual_transformation = _detect_actual_transformation(actual_outcome)
    quantitative_consistency = (
        1.0 if predicted_transformation == actual_transformation else 0.3
    )

    # 3. 否定一致性
    predicted_spiral = bcrm_output.get(
        "spiral_position", {}).get("phase", "UNKNOWN")
    actual_spiral = _detect_actual_spiral(actual_outcome)
    negation_consistency = (
        1.0 if predicted_spiral == actual_spiral else 0.3
    )

    # 加权
    total = (opposition_consistency * CONSISTENCY_WEIGHT_OPPOSITION +
             quantitative_consistency * CONSISTENCY_WEIGHT_QUANTITATIVE +
             negation_consistency * CONSISTENCY_WEIGHT_NEGATION)

    return round(total, 4)


def _infer_actual_contradiction(actual_outcome: Dict) -> str:
    """从实际结果推断主矛盾主导方。"""
    price_change = actual_outcome.get("price_change", 0)
    if price_change > 0.001:
        return "THESIS"
    elif price_change < -0.001:
        return "ANTITHESIS"
    return "EQUAL"


def _detect_actual_transformation(actual_outcome: Dict) -> str:
    """从实际结果检测质变是否发生。"""
    reversal = abs(actual_outcome.get("price_change", 0))
    if reversal > QUALITATIVE_PNL_REVERSAL_THRESHOLD:
        return "HIGH"
    elif reversal > 0.015:
        return "MODERATE"
    return "LOW"


def _detect_actual_spiral(actual_outcome: Dict) -> str:
    """从实际结果检测螺旋阶段。"""
    price_change = actual_outcome.get("price_change", 0)
    direction_changed = actual_outcome.get("direction_changed", False)
    negation_count = actual_outcome.get("negation_count", 0)

    if direction_changed and negation_count >= 2:
        return SPIRAL_SECOND_NEGATION
    elif direction_changed or negation_count == 1:
        return SPIRAL_FIRST_NEGATION
    elif negation_count == 0:
        return SPIRAL_FIRST_AFFIRMATION
    return SPIRAL_UNKNOWN
