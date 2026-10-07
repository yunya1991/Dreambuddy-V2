"""任务④: Ray Tune 大规模并行优化器

依赖: ray[tune] (ray-2.59.0+ 已安装)
扩展: BayesianVerifier 的单点回测 → Ray Tune 大规模并行搜索

设计：
  - 优化目标：最大化 Calmar Ratio（年化收益/最大回撤）
  - 搜索空间：sl_floor ∈ [0.04, 0.15], tp_floor ∈ [0.12, 0.30], atr_mult ∈ [2.0, 6.0]
  - 调度器：AsyncHyperBandScheduler（早停差试验，资源高效）
  - 算法：BayesOptSearch (贝叶斯优化) 或 RandomSearch (兜底)
  - 并行度：num_samples × resources_per_trial

关键特性：
  1. FAIL-OPEN: ray 不可用时 fallback 到 BayesianVerifier 单点验证
  2. 硬约束兜底：试验结果违例时返回差评（不抛异常）
  3. 持久化：试验结果写入 artifacts/param_center/ray_tune_results.json
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ============================================================================
# 路径设置
# ============================================================================
_THIS = Path(__file__).resolve()
_SCRIPTS_16 = _THIS.parent.parent
_PROJECT_ROOT = _SCRIPTS_16.parent.parent
_YIJING_SCRIPTS = _PROJECT_ROOT / "11-易经推理系统" / "scripts"
if str(_YIJING_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_YIJING_SCRIPTS))

# 默认结果存储路径
_ARTIFACTS_DIR = _SCRIPTS_16 / "artifacts" / "param_center"


# ============================================================================
# 硬约束常量（与 verifier.py 一致）
# ============================================================================
SL_FLOOR = 0.04
SL_CEIL = 0.15
TP_FLOOR = 0.12
TP_CEIL = 0.30
ATR_MULT_MIN = 2.0
ATR_MULT_MAX = 6.0
RR_FLOOR = 2.0


# ============================================================================
# _safe_report: 安全引用 ray.tune.report（运行期+测试期兼容）
# ============================================================================
def _safe_report(**kwargs):
    """安全调用 ray.tune.report。

    在 Ray Tune runtime 内会被 ray 调用，在测试/独立调用时
    会写入模块级 _REPORT_LOG 列表，便于测试断言。
    ray 2.59 中 tune.report() 在 runtime 外只 warn 不 raise，
    所以必须主动检查 ray.is_initialized()。
    """
    try:
        import ray
        from ray import tune
        # ray runtime 未初始化时，写入 fallback log（不调用 tune.report）
        if not ray.is_initialized():
            _REPORT_LOG.append(dict(kwargs))
            return
        tune.report(**kwargs)
    except Exception:
        # ray 不可用 → 写入 fallback log
        _REPORT_LOG.append(dict(kwargs))


# fallback report log（测试期断言用）
_REPORT_LOG: list = []


# ============================================================================
# 数据结构
# ============================================================================
@dataclass
class RayTuneResult:
    """Ray Tune 优化结果"""
    best_params: Dict[str, float] = field(default_factory=dict)
    best_calmar: float = 0.0
    best_drawdown: float = 0.0
    n_trials: int = 0
    elapsed_sec: float = 0.0
    fallback_used: bool = False  # True 表示未用 Ray，用单点 fallback
    fallback_reason: Optional[str] = None


# ============================================================================
# RayTuneOptimizer
# ============================================================================
class RayTuneOptimizer:
    """Ray Tune 大规模并行参数优化器。

    Args:
        num_samples: 试验次数（默认 50）
        resources_per_trial: 每个试验占用的 CPU（默认 1）
        scheduler: "asynchyperband" | "hyperband" | "fifo"
        search_alg: "bayesopt" | "random" | "ax"
    """

    def __init__(
        self,
        num_samples: int = 50,
        resources_per_trial: int = 1,
        scheduler: str = "asynchyperband",
        search_alg: str = "bayesopt",
    ) -> None:
        self.num_samples = num_samples
        self.resources_per_trial = resources_per_trial
        self.scheduler_name = scheduler
        self.search_alg_name = search_alg
        self._artifacts_dir = _ARTIFACTS_DIR
        self._artifacts_dir.mkdir(parents=True, exist_ok=True)

    # ----------------------------------------------------------------------
    # 对外主接口
    # ----------------------------------------------------------------------
    def optimize(
        self,
        symbol: str,
        history_days: int = 90,
    ) -> RayTuneResult:
        """对指定 symbol 跑大规模并行优化。

        Args:
            symbol: 交易对
            history_days: 回测历史窗口

        Returns:
            RayTuneResult: 最优参数 + Calmar + 元数据
        """
        start_ts = time.time()
        # 检查 ray 是否可用
        try:
            import ray  # noqa: F401
            from ray import tune
            from ray.tune.schedulers import AsyncHyperBandScheduler
        except ImportError as exc:
            logger.warning("ray 不可用，fallback 到单点验证: %s", exc)
            return self._fallback_single_point(symbol, history_days, str(exc))

        # 定义搜索空间
        search_space = self._build_search_space()

        # 加载数据一次（避免每个 worker 重复加载）
        try:
            from memory_l4.bcrm2.sltp_bayesian_optimizer import load_klines
            df = load_klines(symbol)
            if df is None or len(df) < 200:
                logger.warning("%s 数据不足，fallback 到单点", symbol)
                return self._fallback_single_point(symbol, history_days, "data_insufficient")
        except Exception as exc:
            logger.warning("load_klines 失败: %s, fallback 到单点", exc)
            return self._fallback_single_point(symbol, history_days, str(exc))

        # 调度器
        scheduler = self._build_scheduler()

        # 搜索算法
        search_alg = self._build_search_alg()

        # 用 ray.tune.run 跑大规模并行优化
        try:
            analysis = tune.run(
                self._build_trainable(symbol, df, history_days),
                name=f"param_opt_{symbol}_{int(time.time())}",
                num_samples=self.num_samples,
                search_alg=search_alg,
                scheduler=scheduler,
                resources_per_trial={"cpu": self.resources_per_trial},
                config=search_space,
                verbose=1,
                storage_path=str(self._artifacts_dir / f"ray_results_{symbol}"),
                fail_fast=False,
            )

            # 取最优
            best_trial = analysis.get_best_trial(
                metric="calmar", scope="last", mode="max",
            )
            if best_trial is None:
                return RayTuneResult(
                    n_trials=len(analysis.trials),
                    elapsed_sec=time.time() - start_ts,
                    fallback_used=True,
                    fallback_reason="no_valid_trial",
                )

            best_params = {
                "sl_floor": float(best_trial.config["sl_floor"]),
                "tp_floor": float(best_trial.config["tp_floor"]),
                "atr_mult": float(best_trial.config["atr_mult"]),
            }
            best_calmar = float(best_trial.last_result.get("calmar", 0.0))
            best_dd = float(best_trial.last_result.get("max_drawdown", 0.0))

            # 持久化
            self._save_result(symbol, best_params, best_calmar, best_dd,
                              len(analysis.trials))

            return RayTuneResult(
                best_params=best_params,
                best_calmar=best_calmar,
                best_drawdown=best_dd,
                n_trials=len(analysis.trials),
                elapsed_sec=time.time() - start_ts,
            )
        except Exception as exc:
            logger.error("Ray Tune run 失败: %s, fallback 到单点", exc)
            return self._fallback_single_point(symbol, history_days, str(exc))

    # ----------------------------------------------------------------------
    # 内部方法
    # ----------------------------------------------------------------------
    @staticmethod
    def _build_search_space() -> dict:
        """搜索空间：sl_floor/tp_floor/atr_mult 在硬约束内"""
        return {
            "sl_floor": tune.uniform(SL_FLOOR, SL_CEIL),       # [0.04, 0.15]
            "tp_floor": tune.uniform(TP_FLOOR, TP_CEIL),        # [0.12, 0.30]
            "atr_mult": tune.uniform(ATR_MULT_MIN, ATR_MULT_MAX),  # [2.0, 6.0]
        }

    def _build_scheduler(self):
        """调度器"""
        from ray.tune.schedulers import AsyncHyperBandScheduler
        return AsyncHyperBandScheduler(
            time_attr="training_iteration",
            metric="calmar",
            mode="max",
            max_t=100,
            grace_period=5,
        )

    def _build_search_alg(self):
        """搜索算法（贝叶斯优化优先，fallback 到 random）"""
        try:
            from ray.tune.search.bayesopt import BayesOptSearch
            return BayesOptSearch(
                metric="calmar",
                mode="max",
            )
        except Exception:
            # Fallback: random search
            from ray.tune.search.basic_variant import BasicVariantGenerator
            return BasicVariantGenerator()

    @staticmethod
    def _build_trainable(symbol: str, df, history_days: int):
        """构造 Ray Tune trainable 函数（每个试验跑一次回测）

        内部用 _safe_report 安全引用 ray.tune.report，
        在 ray runtime 外被调用时也能正常测试。
        """
        def _trainable(config):
            # 硬约束兜底
            sl = config["sl_floor"]
            tp = config["tp_floor"]
            atr = config["atr_mult"]
            # RR 检查
            if tp / sl < RR_FLOOR:
                _safe_report(calmar=-1.0, max_drawdown=1.0, training_iteration=1)
                return

            try:
                from memory_l4.bcrm2.sltp_bayesian_optimizer import run_backtest
                bt = run_backtest(df, symbol, sl_floor=sl, tp_floor=tp, atr_mult=atr)
                calmar = float(getattr(bt, "calmar", 0.0))
                dd = abs(float(getattr(bt, "max_drawdown", 1.0)))
                _safe_report(calmar=calmar, max_drawdown=dd, training_iteration=1)
            except Exception as exc:
                logger.warning("trainable 异常: %s", exc)
                _safe_report(calmar=-1.0, max_drawdown=1.0, training_iteration=1)

        return _trainable

    def _fallback_single_point(
        self,
        symbol: str,
        history_days: int,
        reason: str,
    ) -> RayTuneResult:
        """单点 fallback：用默认参数跑一次 BayesianVerifier"""
        try:
            from .verifier import BayesianVerifier
            from .aggregator import ParamProposal
            # 默认参数
            default_params = {
                "sl_floor": SL_FLOOR,
                "tp_floor": TP_FLOOR,
                "atr_mult": 4.5,
            }
            verifier = BayesianVerifier()
            proposal = ParamProposal(params=default_params, confidence=0.5)
            ver = verifier.verify_and_upgrade(proposal, symbol, history_days)
            return RayTuneResult(
                best_params=default_params,
                best_calmar=ver.new_calmar,
                best_drawdown=ver.new_drawdown,
                n_trials=1,
                elapsed_sec=0.0,
                fallback_used=True,
                fallback_reason=reason,
            )
        except Exception as exc:
            logger.error("fallback 单点也失败: %s", exc)
            return RayTuneResult(
                fallback_used=True,
                fallback_reason=f"{reason}; fallback_failed: {exc}",
            )

    def _save_result(
        self,
        symbol: str,
        best_params: Dict[str, float],
        best_calmar: float,
        best_dd: float,
        n_trials: int,
    ) -> None:
        """持久化结果到 artifacts/param_center/ray_tune_results.json"""
        result = {
            "symbol": symbol,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "best_params": best_params,
            "best_calmar": best_calmar,
            "best_drawdown": best_dd,
            "n_trials": n_trials,
        }
        out_path = self._artifacts_dir / "ray_tune_results.json"
        # 追加到结果列表
        results_list = []
        try:
            if out_path.exists():
                with open(out_path, "r", encoding="utf-8") as f:
                    results_list = json.load(f)
        except Exception:
            pass
        results_list.append(result)
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(results_list, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.warning("持久化失败: %s", exc)


# ============================================================================
# 便捷函数
# ============================================================================
def run_optimization(symbol: str, num_samples: int = 50) -> RayTuneResult:
    """模块级便捷接口：对指定 symbol 跑 Ray Tune 优化"""
    optimizer = RayTuneOptimizer(num_samples=num_samples)
    return optimizer.optimize(symbol)
