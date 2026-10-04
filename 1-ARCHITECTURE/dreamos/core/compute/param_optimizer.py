"""
L4 自迭代: 参数自优化
=====================
贝叶斯优化（交易策略参数）+ cost_ms 自适应（调度）

设计原则:
    - 过拟合防护: walk-forward 验证, 3-5 参数以内, 稳定区间 > 精确最优
    - FAIL-OPEN: 优化失败不影响业务
    - 渐进式: 仅在性能持续改进时落地

用法:
    optimizer = ParamOptimizer(param_space={
        "tp_ratio": (0.01, 0.05),
        "sl_ratio": (0.01, 0.03),
    })
    result = optimizer.optimize(objective_fn=backtest_fn, n_trials=50)
    if result.should_apply:
        apply_params(result.best_params)
"""

import logging
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── 过拟合防护阈值 ──────────────────────────────────────
MAX_PARAMS = 5                  # 最多 5 个参数
MIN_TRIALS = 10                 # 最少试验次数
WALK_FORWARD_SPLITS = 3         # walk-forward 分割数
IMPROVEMENT_THRESHOLD = 0.02    # 改进 ≥2% 才落地
STABILITY_RATIO = 0.7           # 稳定区间: 最优 70% 以内的参数都接受


class OptimizationStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    SKIPPED = "skipped"          # 参数过多/试验不足
    FAILED = "failed"


class ApplyDecision(str, Enum):
    APPLY = "apply"              # 改进显著, 建议落地
    HOLD = "hold"                # 改进不显著, 保持现状
    REJECT = "reject"            # 过拟合风险, 拒绝


@dataclass
class TrialResult:
    """单次试验结果"""
    params: Dict[str, float]
    score: float                 # 目标函数值 (越高越好)
    train_score: Optional[float] = None
    val_scores: List[float] = field(default_factory=list)  # walk-forward 验证分数

    @property
    def val_mean(self) -> float:
        return sum(self.val_scores) / len(self.val_scores) if self.val_scores else 0.0

    @property
    def val_std(self) -> float:
        if len(self.val_scores) < 2:
            return 0.0
        m = self.val_mean
        var = sum((x - m) ** 2 for x in self.val_scores) / len(self.val_scores)
        return math.sqrt(var)

    @property
    def stability_score(self) -> float:
        """稳定度 = val_mean / (1 + val_std) — 高均值低方差得高分"""
        if not self.val_scores:
            return self.score
        return self.val_mean / (1 + self.val_std)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "params": self.params,
            "score": self.score,
            "train_score": self.train_score,
            "val_scores": self.val_scores,
            "val_mean": self.val_mean,
            "val_std": self.val_std,
            "stability_score": self.stability_score,
        }


@dataclass
class OptimizationResult:
    """优化结果"""
    status: OptimizationStatus
    best_trial: Optional[TrialResult] = None
    baseline_score: float = 0.0
    improvement: float = 0.0     # 相对改进比例
    should_apply: bool = False
    apply_decision: ApplyDecision = ApplyDecision.HOLD
    reason: str = ""
    n_trials: int = 0
    all_trials: List[TrialResult] = field(default_factory=list)
    optimized_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat() + "Z"
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "best_trial": self.best_trial.to_dict() if self.best_trial else None,
            "baseline_score": self.baseline_score,
            "improvement": self.improvement,
            "should_apply": self.should_apply,
            "apply_decision": self.apply_decision.value,
            "reason": self.reason,
            "n_trials": self.n_trials,
            "optimized_at": self.optimized_at,
        }


class ParamOptimizer:
    """参数自优化引擎

    使用简化版贝叶斯优化:
        1. 随机采样初始点 (warm-start)
        2. 基于 EI (Expected Improvement) 采集函数选下一组参数
        3. walk-forward 验证防过拟合

    用法:
        optimizer = ParamOptimizer(
            param_space={"tp_ratio": (0.01, 0.05), "sl_ratio": (0.01, 0.03)},
        )
        result = optimizer.optimize(
            objective_fn=lambda params: backtest(params),
            baseline_score=0.15,
            n_trials=50,
        )
    """

    def __init__(self, param_space: Dict[str, Tuple[float, float]]):
        if len(param_space) > MAX_PARAMS:
            raise ValueError(
                f"参数数量 {len(param_space)} 超过上限 {MAX_PARAMS} "
                f"(过拟合防护)"
            )
        self._param_space = param_space
        self._trials: List[TrialResult] = []
        self._status = OptimizationStatus.PENDING

    @property
    def status(self) -> OptimizationStatus:
        return self._status

    @property
    def trials(self) -> List[TrialResult]:
        return list(self._trials)

    def _sample_random(self) -> Dict[str, float]:
        """从参数空间随机采样"""
        return {
            name: random.uniform(lo, hi)
            for name, (lo, hi) in self._param_space.items()
        }

    def _sample_gaussian(self, center: Dict[str, float], sigma: float = 0.1) -> Dict[str, float]:
        """在 center 附近高斯采样"""
        result = {}
        for name, (lo, hi) in self._param_space.items():
            mu = center.get(name, (lo + hi) / 2)
            val = random.gauss(mu, (hi - lo) * sigma)
            result[name] = max(lo, min(hi, val))
        return result

    def _expected_improvement(
        self, candidate: Dict[str, float], best_score: float, kappa: float = 2.0
    ) -> float:
        """简化版 EI 采集函数

        用最近试验的均值和方差估计 candidate 的期望改进
        """
        if len(self._trials) < 2:
            return random.random()

        # 找最近的 K 个试验, 按参数距离加权
        k = min(len(self._trials), 5)
        recent = self._trials[-k:]

        weights = []
        scores = []
        for trial in recent:
            # 参数距离 (归一化欧氏距离)
            dist = 0.0
            for name, (lo, hi) in self._param_space.items():
                p_val = candidate.get(name, (lo + hi) / 2)
                t_val = trial.params.get(name, (lo + hi) / 2)
                rng = hi - lo if hi > lo else 1.0
                dist += ((p_val - t_val) / rng) ** 2
            dist = math.sqrt(dist / len(self._param_space))

            # 权重: 距离越近权重越高 (高斯核)
            w = math.exp(-2 * dist ** 2)
            weights.append(w)
            scores.append(trial.score)

        total_w = sum(weights)
        if total_w == 0:
            return random.random()

        # 加权均值和方差
        mean = sum(w * s for w, s in zip(weights, scores)) / total_w
        variance = sum(w * (s - mean) ** 2 for w, s in zip(weights, scores)) / total_w
        std = math.sqrt(variance) if variance > 0 else 0.01

        # EI = (mean - best) * CDF(z) + std * PDF(z)
        # 简化: 用 UCB (Upper Confidence Bound) 代替
        ucb = mean + kappa * std
        return ucb

    def _select_next_params(self, n_candidates: int = 20) -> Dict[str, float]:
        """选择下一组参数 (EI 最大化)"""
        if len(self._trials) < MIN_TRIALS:
            return self._sample_random()

        best_score = max(t.score for t in self._trials)

        # 生成候选, 选 EI 最高的
        best_ei = -1.0
        best_params = self._sample_random()

        # 在当前最优附近高斯采样 + 随机探索
        best_trial = max(self._trials, key=lambda t: t.score)
        for _ in range(n_candidates):
            if random.random() < 0.3:
                candidate = self._sample_random()  # 探索
            else:
                candidate = self._sample_gaussian(best_trial.params, sigma=0.15)  # 利用

            ei = self._expected_improvement(candidate, best_score)
            if ei > best_ei:
                best_ei = ei
                best_params = candidate

        return best_params

    def optimize(
        self,
        objective_fn: Callable[[Dict[str, float]], float],
        baseline_score: float = 0.0,
        n_trials: int = 30,
        walk_forward_fn: Optional[Callable[[Dict[str, float]], List[float]]] = None,
    ) -> OptimizationResult:
        """执行参数优化

        Args:
            objective_fn: 目标函数 (params → score, 越高越好)
            baseline_score: 当前基线分数
            n_trials: 试验次数
            walk_forward_fn: walk-forward 验证函数 (params → list of scores)

        Returns:
            OptimizationResult
        """
        if n_trials < MIN_TRIALS:
            return OptimizationResult(
                status=OptimizationStatus.SKIPPED,
                reason=f"试验次数 {n_trials} < 最低 {MIN_TRIALS}",
            )

        self._status = OptimizationStatus.RUNNING
        self._trials = []

        try:
            for i in range(n_trials):
                # 选参数
                params = self._select_next_params()

                # 评估
                try:
                    score = float(objective_fn(params))
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[optimizer] trial {i} 失败: {e}")
                    score = 0.0

                trial = TrialResult(params=params, score=score)

                # walk-forward 验证
                if walk_forward_fn:
                    try:
                        val_scores = walk_forward_fn(params)
                        trial.val_scores = [float(s) for s in val_scores]
                        trial.train_score = score
                        # 用验证集均值作为最终分数
                        if trial.val_scores:
                            score = trial.val_mean
                            trial.score = score
                    except Exception as e:  # noqa: BLE001
                        logger.warning(f"[optimizer] walk-forward 失败: {e}")

                self._trials.append(trial)

            self._status = OptimizationStatus.COMPLETED

        except Exception as e:  # noqa: BLE001
            self._status = OptimizationStatus.FAILED
            return OptimizationResult(
                status=OptimizationStatus.FAILED,
                reason=str(e),
                n_trials=len(self._trials),
            )

        # 选择最优 (按稳定度排序)
        if not self._trials:
            return OptimizationResult(
                status=OptimizationStatus.SKIPPED,
                reason="无有效试验结果",
            )

        # 优先选择有 walk-forward 验证且稳定度高的
        validated = [t for t in self._trials if t.val_scores]
        if validated:
            best_trial = max(validated, key=lambda t: t.stability_score)
        else:
            best_trial = max(self._trials, key=lambda t: t.score)

        # 计算改进
        improvement = 0.0
        if baseline_score > 0:
            improvement = (best_trial.score - baseline_score) / abs(baseline_score)

        # 决策是否落地
        should_apply = False
        decision = ApplyDecision.HOLD
        reason = ""

        if improvement >= IMPROVEMENT_THRESHOLD:
            # 检查稳定度
            if best_trial.val_std > 0 and best_trial.val_mean > 0:
                cv = best_trial.val_std / best_trial.val_mean  # 变异系数
                if cv > 0.5:
                    decision = ApplyDecision.REJECT
                    reason = f"变异系数 {cv:.2f} 过高, 过拟合风险"
                else:
                    should_apply = True
                    decision = ApplyDecision.APPLY
                    reason = (
                        f"改进 {improvement:.1%} ≥ {IMPROVEMENT_THRESHOLD:.0%}, "
                        f"变异系数 {cv:.2f}, 建议落地"
                    )
            else:
                should_apply = True
                decision = ApplyDecision.APPLY
                reason = f"改进 {improvement:.1%} ≥ 阈值, 建议落地"
        else:
            decision = ApplyDecision.HOLD
            reason = f"改进 {improvement:.1%} < 阈值 {IMPROVEMENT_THRESHOLD:.0%}, 保持现状"

        return OptimizationResult(
            status=self._status,
            best_trial=best_trial,
            baseline_score=baseline_score,
            improvement=improvement,
            should_apply=should_apply,
            apply_decision=decision,
            reason=reason,
            n_trials=len(self._trials),
        )


class CostAdaptiveScheduler:
    """cost_ms 自适应调度

    根据历史执行耗时自适应调整调度间隔:
        - 节点连续 N 次耗时 > 阈值 → 增加间隔
        - 节点连续 N 次耗时 < 阈值 → 缩短间隔 (不低于下限)
    """

    def __init__(
        self,
        default_interval_ms: int = 5000,
        min_interval_ms: int = 1000,
        max_interval_ms: int = 60000,
        cost_threshold_ms: float = 3000,
        adjust_window: int = 5,
    ):
        self._default = default_interval_ms
        self._min = min_interval_ms
        self._max = max_interval_ms
        self._threshold = cost_threshold_ms
        self._window = adjust_window
        self._history: Dict[str, List[float]] = {}  # node_id → [durations]

    def record_cost(self, node_id: str, duration_ms: float) -> None:
        """记录节点执行耗时"""
        hist = self._history.setdefault(node_id, [])
        hist.append(duration_ms)
        if len(hist) > self._window * 2:
            hist = hist[-self._window * 2:]
            self._history[node_id] = hist

    def get_interval(self, node_id: str) -> int:
        """获取自适应调度间隔 (ms)"""
        hist = self._history.get(node_id, [])
        if len(hist) < self._window:
            return self._default

        recent = hist[-self._window:]
        avg_cost = sum(recent) / len(recent)

        if avg_cost > self._threshold:
            # 耗时高 → 增加间隔 (按比例放大)
            ratio = avg_cost / self._threshold
            interval = int(self._default * ratio)
        elif avg_cost < self._threshold * 0.5:
            # 耗时低 → 缩短间隔
            interval = int(self._default * 0.7)
        else:
            interval = self._default

        return max(self._min, min(self._max, interval))

    def status(self) -> Dict[str, Any]:
        """调度状态摘要"""
        return {
            node_id: {
                "avg_cost_ms": sum(h[-self._window:]) / max(len(h[-self._window:]), 1),
                "interval_ms": self.get_interval(node_id),
                "samples": len(h),
            }
            for node_id, h in self._history.items()
            if h
        }
