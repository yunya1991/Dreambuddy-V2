"""
EvolutionPipeline — 四层闭环进化架构编排器
蓝图: 四层闭环进化架构-最小阻力路径总览.md §一 闭环动作流

完整进化闭环：
  L1 状态空间 → 高阶因子阻力调制 → 路径发现层(多路径竞争→寻优) → 依据最优路径 argmin 最小阻力
  → 统计验证 → 决策 → L3 Shadow-RL → L4 Bellman V(s) → 回馈 → 进化寻优

路径来源：
  1. 现有路径: L2基因库/BCRM2.0/BDSM/战略层已知的交易路径
  2. 基于现有计算新的: DeepReasoningEngine 蒙特卡洛+路径积分生成新路径
  3. 自进化涌现: StrategySynthesizer/TransferLearner 生成全新策略基因

AGI 阶段4增强点（只读，FAIL-OPEN）:
- F: 路径发现 → DeepReasoningEngine 深度推理（签名+SDE+蒙特卡洛+最小阻力）
- G: 路径发现 → StrategySynthesizer 策略合成（新基因验证+冷启动仓位）
- H: L3记录后 → TransferLearner 跨资产迁移（原型网络+MAML+反事实）
- I: L3记录后 → CounterfactualEvaluator 反事实评估（合成控制法+alpha归因）
"""
import sys
import json
import math
import logging
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent


class EvolutionPipeline:
    """
    四层闭环 pipeline.
    MVP: L1→Level0→L2→决策 + L3/L4 骨架追踪.
    AGI 阶段4: + DeepReasoning + StrategySynthesizer + TransferLearner + Counterfactual
    """

    # 单例引用 — 供 TradeSettlementBridge 等外部组件访问
    _instance: "EvolutionPipeline | None" = None

    # 按维度独立维护的矛盾权重持久化路径
    _WF_PERSIST_PATH = REPO_ROOT / "dreambuddy_evolution" / "data" / "weight_factors.json"

    def __init__(self, gene_root: Path | str | None = None, trader: Any = None):
        self.gene_root = Path(gene_root) if gene_root else (
            REPO_ROOT / "dreambuddy_evolution" / "gene_data"
        )

        # L3/L4 初始化
        from dreambuddy_evolution.core.shadow_rl import ShadowRLTracker
        from dreambuddy_evolution.core.bellman_tracker import BellmanVTracker
        # D方案: ShadowRL 样本 JSONL 持久化，用绝对路径避免工作目录依赖
        _rl_persist = REPO_ROOT / "dreambuddy_evolution" / "gene_data" / "shadow_rl_samples.jsonl"
        self.shadow_rl = ShadowRLTracker(persist_path=_rl_persist)
        self.shadow_rl.load_from_disk()  # 启动加载历史样本
        self.bellman = BellmanVTracker(alpha=0.1, gamma=0.95)

        # Fix 3: 按维度独立的矛盾权重字典 + 持久化
        self._contradiction_weight_factors: dict[str, float] = {}
        self._load_weight_factors()

        # 注册单例 — 供 TradeSettlementBridge 访问
        EvolutionPipeline._instance = self

        # ShadowRLTrainer 初始化（REINFORCE 训练 + Thompson 采样）
        try:
            from dreambuddy_evolution.core.shadow_rl_trainer import ShadowRLTrainer
            self.shadow_rl_trainer = ShadowRLTrainer()
        except Exception as e:
            logger.debug("[FO] ShadowRLTrainer init fail: %s", e)
            self.shadow_rl_trainer = None

        # RegimeGateSwitch 初始化（市场状态路由）
        try:
            from dreambuddy_evolution.engines.regime_gate import RegimeGateSwitch
            self._regime_gate = RegimeGateSwitch()
        except Exception as e:
            logger.debug("[FO] RegimeGateSwitch init fail: %s", e)
            self._regime_gate = None

        # L2 library cache
        self._library = None

        # ---- Phase 1-3 组件初始化（开关控制，FAIL-OPEN） ----
        self._exogenous_evaluator = None
        self._structural_break_detector = None
        self._shift_accumulator = None
        self._elastic_resolver = None
        self._reflexivity_monitor = None
        self._last_structural_break: dict | None = None
        self._last_shift_result: dict | None = None
        self._last_elastic_result: dict | None = None

        # 高阶基因因子桥接器（BCRM2.0/BDSM/战略层 → 阻力调制）
        try:
            from dreambuddy_evolution.adapters.subsystem_bridge import SubSystemBridge
            self._bridge = SubSystemBridge(trader) if trader else None
        except Exception:
            self._bridge = None

        # AGI 阶段4模块懒初始化标志（None=未初始化, False=不可用, 实例=可用）
        self._deep_reasoning: Any = None
        self._strategy_synth: Any = None
        self._transfer_learner: Any = None
        self._counterfactual: Any = None

    # ============ AGI 阶段4: 统一增强入口 ============

    def _agi_enhance(self, switch: str, fn: Any, fallback: Any, **kw: Any) -> Any:
        """AGI 增强统一入口：开关检查 + FAIL-OPEN."""
        try:
            from dreambuddy_evolution.agi_config import is_enabled
            if not is_enabled(switch):
                return fallback
        except Exception:
            return fallback
        try:
            return fn(**kw)
        except Exception as e:
            logger.warning("[FO-AGI-Pipeline][%s] crash: %s", switch, e)
            return fallback

    def _get_deep_reasoning(self) -> Any:
        """懒初始化 DeepReasoningEngine"""
        if self._deep_reasoning is None:
            try:
                from dreambuddy_evolution.engines.deep_reasoning_engine import DeepReasoningEngine
                self._deep_reasoning = DeepReasoningEngine(signature_depth=3)
            except Exception as e:
                logger.debug("[FO-AGI] DeepReasoningEngine init fail: %s", e)
                self._deep_reasoning = False
        return self._deep_reasoning or None

    def _get_strategy_synth(self) -> Any:
        """懒初始化 StrategySynthesizer"""
        if self._strategy_synth is None:
            try:
                from dreambuddy_evolution.core.strategy_synthesizer import StrategySynthesizer
                self._strategy_synth = StrategySynthesizer(gene_root=self.gene_root)
            except Exception as e:
                logger.debug("[FO-AGI] StrategySynthesizer init fail: %s", e)
                self._strategy_synth = False
        return self._strategy_synth or None

    def _get_transfer_learner(self) -> Any:
        """懒初始化 TransferLearner"""
        if self._transfer_learner is None:
            try:
                from dreambuddy_evolution.core.transfer_learner import TransferLearner
                self._transfer_learner = TransferLearner()
            except Exception as e:
                logger.debug("[FO-AGI] TransferLearner init fail: %s", e)
                self._transfer_learner = False
        return self._transfer_learner or None

    def _get_counterfactual(self) -> Any:
        """懒初始化 CounterfactualEvaluator"""
        if self._counterfactual is None:
            try:
                from dreambuddy_evolution.core.counterfactual_evaluator import CounterfactualEvaluator
                self._counterfactual = CounterfactualEvaluator()
            except Exception as e:
                logger.debug("[FO-AGI] CounterfactualEvaluator init fail: %s", e)
                self._counterfactual = False
        return self._counterfactual or None

    # ============ P3: AGI 模块懒初始化 ============

    def _get_causal_engine(self) -> Any:
        """P3 懒初始化 CausalEngine"""
        from dreambuddy_evolution.agi_config import is_enabled
        if not is_enabled("enable_causal_engine"):
            return None
        if getattr(self, "_causal_engine", None) is None:
            try:
                from dreambuddy_evolution.core.causal_engine import CausalEngine
                self._causal_engine = CausalEngine()
            except Exception as e:
                logger.debug("[FO-AGI] CausalEngine init fail: %s", e)
                self._causal_engine = False
        return self._causal_engine or None

    # ============ Fix 3: 按维度独立的矛盾权重持久化 ============

    def _load_weight_factors(self) -> None:
        """从 JSON 加载按维度独立的矛盾权重。FAIL-OPEN: 文件不存在或解析失败 → 空 dict。"""
        try:
            if self._WF_PERSIST_PATH.exists():
                import json
                data = json.loads(self._WF_PERSIST_PATH.read_text(encoding="utf-8"))
                self._contradiction_weight_factors = {
                    str(k): max(0.3, min(1.5, float(v)))
                    for k, v in data.items()
                }
                logger.debug("[WF] 加载 %d 个维度权重: %s",
                             len(self._contradiction_weight_factors),
                             list(self._contradiction_weight_factors.keys()))
        except Exception as e:
            logger.debug("[FO] _load_weight_factors crash: %s", e)
            self._contradiction_weight_factors = {}

    def _save_weight_factors(self) -> None:
        """持久化矛盾权重到 JSON。FAIL-OPEN: 写入失败不阻断。"""
        try:
            import json
            self._WF_PERSIST_PATH.parent.mkdir(parents=True, exist_ok=True)
            self._WF_PERSIST_PATH.write_text(
                json.dumps(self._contradiction_weight_factors, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.debug("[FO] _save_weight_factors crash: %s", e)

    def _get_wf_for_dim(self, dim: str) -> float:
        """获取指定维度的权重因子，默认 1.0。"""
        return self._contradiction_weight_factors.get(dim, 1.0)

    def _get_contradiction_feedback(self) -> Any:
        """P3.5 懒初始化 ContradictionFeedback"""
        from dreambuddy_evolution.agi_config import is_enabled
        if not is_enabled("enable_contradiction_feedback"):
            return None
        if getattr(self, "_contradiction_feedback", None) is None:
            try:
                from dreambuddy_evolution.core.contradiction_feedback import ContradictionFeedback
                self._contradiction_feedback = ContradictionFeedback()
            except Exception as e:
                logger.debug("[FO-AGI] ContradictionFeedback init fail: %s", e)
                self._contradiction_feedback = False
        return self._contradiction_feedback or None

    def _get_exogenous_evaluator(self) -> Any:
        """Phase 1: 外生力量度量器（懒初始化）"""
        from dreambuddy_evolution.agi_config import get_switch as _gs
        if not _gs("enable_exogenous_strength", False):
            return None
        if self._exogenous_evaluator is None:
            try:
                from dreambuddy_evolution.core.exogenous_strength_evaluator import ExogenousStrengthEvaluator
                self._exogenous_evaluator = ExogenousStrengthEvaluator()
            except Exception as e:
                logger.debug("[FO-Phase1] ExogenousStrengthEvaluator init fail: %s", e)
                self._exogenous_evaluator = False
        return self._exogenous_evaluator or None

    def _get_structural_break_detector(self) -> Any:
        """Phase 2: 结构断裂检测器（懒初始化）"""
        from dreambuddy_evolution.agi_config import get_switch as _gs
        if not _gs("enable_structural_break_detection", False):
            return None
        if self._structural_break_detector is None:
            try:
                from dreambuddy_evolution.core.structural_break_detector import StructuralBreakDetector
                self._structural_break_detector = StructuralBreakDetector()
            except Exception as e:
                logger.debug("[FO-Phase2] StructuralBreakDetector init fail: %s", e)
                self._structural_break_detector = False
        return self._structural_break_detector or None

    def _get_shift_accumulator(self) -> Any:
        """Phase 2: 矛盾转化积累器（懒初始化）"""
        from dreambuddy_evolution.agi_config import get_switch as _gs
        if not _gs("enable_contradiction_shift_detection", False):
            return None
        if self._shift_accumulator is None:
            try:
                from dreambuddy_evolution.core.contradiction_shift_accumulator import ContradictionShiftAccumulator
                self._shift_accumulator = ContradictionShiftAccumulator()
            except Exception as e:
                logger.debug("[FO-Phase2] ShiftAccumulator init fail: %s", e)
                self._shift_accumulator = False
        return self._shift_accumulator or None

    def _get_elastic_resolver(self) -> Any:
        """Phase 3: 弹性约束解析器（懒初始化）"""
        from dreambuddy_evolution.agi_config import get_switch as _gs
        if not _gs("enable_elastic_constraint", False):
            return None
        if self._elastic_resolver is None:
            try:
                from dreambuddy_evolution.core.elastic_constraint_resolver import ElasticConstraintResolver
                self._elastic_resolver = ElasticConstraintResolver()
            except Exception as e:
                logger.debug("[FO-Phase3] ElasticConstraintResolver init fail: %s", e)
                self._elastic_resolver = False
        return self._elastic_resolver or None

    def _get_reflexivity_monitor(self) -> Any:
        """Phase 3: 反身性监测器（懒初始化）"""
        from dreambuddy_evolution.agi_config import get_switch as _gs
        if not _gs("enable_reflexivity_monitor", False):
            return None
        if self._reflexivity_monitor is None:
            try:
                from dreambuddy_evolution.core.reflexivity_monitor import ReflexivityMonitor
                self._reflexivity_monitor = ReflexivityMonitor()
            except Exception as e:
                logger.debug("[FO-Phase3] ReflexivityMonitor init fail: %s", e)
                self._reflexivity_monitor = False
        return self._reflexivity_monitor or None

    def _get_signature_engine(self) -> Any:
        """P3 懒初始化 SignatureEngine"""
        if getattr(self, "_signature_engine", None) is None:
            try:
                from dreambuddy_evolution.core.signature_engine import SignatureEngine
                self._signature_engine = SignatureEngine()
            except Exception as e:
                logger.debug("[FO-AGI] SignatureEngine init fail: %s", e)
                self._signature_engine = False
        return self._signature_engine or None

    def _get_path_integral(self) -> Any:
        """P3 懒初始化 PathIntegralEngine"""
        if getattr(self, "_path_integral", None) is None:
            try:
                from dreambuddy_evolution.core.path_integral import PathIntegralEngine
                self._path_integral = PathIntegralEngine()
            except Exception as e:
                logger.debug("[FO-AGI] PathIntegralEngine init fail: %s", e)
                self._path_integral = False
        return self._path_integral or None

    def _get_uncertainty_quantifier(self) -> Any:
        """P3 懒初始化 UncertaintyQuantifier"""
        if getattr(self, "_uncertainty_quant", None) is None:
            try:
                from dreambuddy_evolution.core.uncertainty_quantifier import UncertaintyQuantifier
                self._uncertainty_quant = UncertaintyQuantifier()
            except Exception as e:
                logger.debug("[FO-AGI] UncertaintyQuantifier init fail: %s", e)
                self._uncertainty_quant = False
        return self._uncertainty_quant or None

    def _get_meta_cognition_gate(self) -> Any:
        """P3 懒初始化 MetaCognitionGate"""
        if getattr(self, "_meta_cognition", None) is None:
            try:
                from dreambuddy_evolution.engines.meta_cognition_gate import MetaCognitionGate
                self._meta_cognition = MetaCognitionGate()
            except Exception as e:
                logger.debug("[FO-AGI] MetaCognitionGate init fail: %s", e)
                self._meta_cognition = False
        return self._meta_cognition or None

    # ============ 高阶基因因子阻力调制 ============

    def _apply_high_order_factors(self, r_out: dict, symbol: str) -> dict:
        """高阶基因因子（BCRM/BDSM/战略层）调制 R 向量阻力值.

        数学模型：
          R_up(调制后)  = R_up  × f_bcrm(long) × f_bdsm(long) × f_strategic
          R_down(调制后) = R_down × f_bcrm(short) × f_bdsm(short) × f_strategic
          R_wait(调制后) = R_smooth × R_refl × f_strategic

        各因子为 [0.5, 2.0] 区间的乘数：
          - 1.0 = 中性（无影响）
          - <1.0 = 降低阻力（顺风）
          - >1.0 = 增加阻力（逆风）
          - 2.0 = 强逆风（最大阻力倍增）

        BCRM 方向因子:
          BCRM=UP + d*=long → f=1-α (顺风降阻)
          BCRM=UP + d*=short → f=1+α (逆风增阻)
          BCRM=DOWN + d*=short → f=1-α
          BCRM=DOWN + d*=long → f=1+α
          α = confidence × 0.5（最大 50% 调制）

        BDSM 估值因子:
          valuation > 0.7（高估） → f_long=1+β, f_short=1-β
          valuation < 0.3（低估） → f_long=1-β, f_short=1+β
          β = |val-0.5| × 0.6

        战略层 war_state 因子:
          ALLOW → f=1.0
          COOLDOWN → f=1.2
          RESTRICT → f=1.5
          FREEZE → f=2.0（最大阻力倍增）

        FAIL-OPEN: bridge 不可用 → 原值返回.
        """
        if self._bridge is None:
            return r_out

        try:
            R_up = float(r_out.get("R_up", 0.5))
            R_down = float(r_out.get("R_down", 0.5))
            R_smooth = float(r_out.get("R_smooth", 0.5))
            R_refl = float(r_out.get("R_reflexivity", 0.5))

            # 1. BCRM 方向因子
            bcrm_dir = self._bridge.get_bcrm_direction()  # "long"/"short"/""
            bcrm_conf = self._bridge.get_bcrm_confidence()  # [0,1]
            alpha = bcrm_conf * 0.5  # 最大 50% 调制

            f_bcrm_long = 1.0
            f_bcrm_short = 1.0
            if bcrm_dir == "long":
                f_bcrm_long = 1.0 - alpha   # BCRM看多 → 做多顺风
                f_bcrm_short = 1.0 + alpha  # 做空逆风
            elif bcrm_dir == "short":
                f_bcrm_short = 1.0 - alpha
                f_bcrm_long = 1.0 + alpha

            # 2. BDSM 估值因子
            bdsm_val = self._bridge.get_bdsm_valuation()  # [0,1]
            beta = abs(bdsm_val - 0.5) * 0.6  # 最大 30% 调制

            f_bdsm_long = 1.0
            f_bdsm_short = 1.0
            if bdsm_val > 0.7:  # 高估 → 做多逆风，做空顺风
                f_bdsm_long = 1.0 + beta
                f_bdsm_short = 1.0 - beta
            elif bdsm_val < 0.3:  # 低估 → 做多顺风，做空逆风
                f_bdsm_long = 1.0 - beta
                f_bdsm_short = 1.0 + beta

            # 3. 战略层 war_state 因子
            war_state = self._bridge.get_war_state()
            f_strategic = {
                "ALLOW": 1.0,
                "COOLDOWN": 1.2,
                "RESTRICT": 1.5,
                "FREEZE": 2.0,
            }.get(war_state, 1.0)

            # 4. 战略层 direction_state 约束（更强力）
            dir_state = self._bridge.get_direction_state()
            if dir_state == "LONG_ONLY":
                f_bcrm_short *= 1.5  # 禁空 → 做空阻力更大
            elif dir_state == "SHORT_ONLY":
                f_bcrm_long *= 1.5   # 禁多 → 做多阻力更大
            elif dir_state == "FREEZE":
                f_strategic *= 1.5   # 冻结 → 全局阻力更大

            # 5. 调制后的阻力值（clamp [0.01, 1.0]）
            R_up_mod = max(0.01, min(1.0, R_up * f_bcrm_long * f_bdsm_long * f_strategic))
            R_down_mod = max(0.01, min(1.0, R_down * f_bcrm_short * f_bdsm_short * f_strategic))
            R_smooth_mod = max(0.01, min(1.0, R_smooth * f_strategic))
            R_refl_mod = max(0.01, min(1.0, R_refl * f_strategic))

            r_out = dict(r_out)  # 不修改原始
            r_out["R_up"] = round(R_up_mod, 6)
            r_out["R_down"] = round(R_down_mod, 6)
            r_out["R_smooth"] = round(R_smooth_mod, 6)
            r_out["R_reflexivity"] = round(R_refl_mod, 6)

            # 记录调制因子供日志
            r_out["high_order_factors"] = {
                "bcrm_dir": bcrm_dir,
                "bcrm_conf": round(bcrm_conf, 4),
                "f_bcrm_long": round(f_bcrm_long, 4),
                "f_bcrm_short": round(f_bcrm_short, 4),
                "bdsm_val": round(bdsm_val, 4),
                "f_bdsm_long": round(f_bdsm_long, 4),
                "f_bdsm_short": round(f_bdsm_short, 4),
                "war_state": war_state,
                "f_strategic": f_strategic,
                "dir_state": dir_state,
                "R_up_raw": round(R_up, 6),
                "R_up_mod": round(R_up_mod, 6),
                "R_down_raw": round(R_down, 6),
                "R_down_mod": round(R_down_mod, 6),
            }

            return r_out
        except Exception as e:
            logger.debug("[FO] high_order_factors fail: %s", e)
            return r_out

    # ============ 路径发现层：多路径竞争 → 寻优 → argmin ============

    def _discover_paths(self, r_out: dict, market_data: dict, symbol: str) -> list[dict]:
        """路径发现层：收集所有候选交易路径.

        路径来源：
          1. 现有路径: L2基因库/BCRM2.0/BDSM/战略层已知的交易路径
          2. 基于现有计算新的: DeepReasoningEngine 蒙特卡洛+路径积分
          3. 自进化涌现: StrategySynthesizer 生成全新策略基因

        每个路径返回:
          {
            "path_id": str,
            "source": "l2_gene" | "bcrm" | "bdsm" | "strategic" | "deep_reasoning" | "synthesized",
            "direction": "long" | "short" | "neutral",
            "expected_return": float,  # 期望收益（年化）
            "confidence": float,       # 置信度 [0,1]
            "resistance": float,       # 预期阻力 [0,1]
            "metadata": dict,          # 路径元数据
          }
        """
        paths = []

        # ---- 1. L2 基因库路径 ----
        try:
            library = self._load_library()
            from dreambuddy_evolution.core import strategy_gene as sgs
            top_combos = sgs.top_combinations_by_ess(library, min_sample=0)
            for i, combo in enumerate(top_combos[:3]):  # 取 top-3
                resolved_dir = self._resolve_action_direction(combo.get("action_ids", []))
                ess = float(combo.get("ess", 0.5))
                paths.append({
                    "path_id": f"l2_gene_{i}",
                    "source": "l2_gene",
                    "direction": resolved_dir,
                    "expected_return": ess * 0.3,  # ESS 越高期望收益越高
                    "confidence": min(1.0, ess),
                    "resistance": 1.0 - ess,  # ESS 高 = 阻力低
                    "metadata": {"combo_id": combo.get("combo_id", ""), "ess": ess, "n": combo.get("n", 0)},
                })
        except Exception as e:
            logger.debug("[FO] l2_gene path fail: %s", e)

        # ---- 1b. RegimeGate 策略路由路径（趋势跟踪/网格） ----
        try:
            if self._regime_gate is not None:
                kline_data = market_data.get("kline_data", {})
                regime = self._regime_gate.detect_regime(kline_data)
                route = self._regime_gate.route_strategy(regime, kline_data, market_data)
                engine = route.get("engine", "")
                if engine == "trend_following":
                    # 趋势跟踪路径
                    direction = route.get("direction", "long")
                    conf = route.get("confidence", 0.5)
                    paths.append({
                        "path_id": "regime_trend",
                        "source": "trend_following",
                        "direction": direction,
                        "expected_return": conf * 0.4,
                        "confidence": conf,
                        "resistance": 1.0 - conf,
                        "metadata": {"regime": regime, "engine": "trend_following"},
                    })
                elif engine in ("v15_grid", "grid"):
                    # 网格交易路径
                    paths.append({
                        "path_id": "regime_grid",
                        "source": "grid_trading",
                        "direction": "neutral",  # 网格多空双向
                        "expected_return": 0.15,  # 网格收益稳健但不高
                        "confidence": 0.6,
                        "resistance": 0.4,
                        "metadata": {"regime": regime, "engine": "grid_trading"},
                    })
                # CRISIS → pause，不添加路径
        except Exception as e:
            logger.debug("[FO] regime_gate path fail: %s", e)

        # ---- 2. BCRM2.0 路径（技术面入场信号） ----
        try:
            if self._bridge is not None:
                bcrm_dir = self._bridge.get_bcrm_direction()
                bcrm_conf = self._bridge.get_bcrm_confidence()
                if bcrm_dir in ("long", "short"):
                    paths.append({
                        "path_id": "bcrm_technical",
                        "source": "bcrm",
                        "direction": bcrm_dir,
                        "expected_return": bcrm_conf * 0.2,
                        "confidence": bcrm_conf,
                        "resistance": 1.0 - bcrm_conf,
                        "metadata": {"bcrm_confidence": bcrm_conf},
                    })
        except Exception as e:
            logger.debug("[FO] bcrm path fail: %s", e)

        # ---- 3. BDSM 路径（基本面约束，部分代币可能不存在） ----
        try:
            if self._bridge is not None:
                bdsm_val = self._bridge.get_bdsm_valuation()
                # BDSM > 0.7 高估 → 做空路径；< 0.3 低估 → 做多路径
                if bdsm_val > 0.7:
                    paths.append({
                        "path_id": "bdsm_fundamental_short",
                        "source": "bdsm",
                        "direction": "short",
                        "expected_return": (bdsm_val - 0.5) * 0.4,
                        "confidence": (bdsm_val - 0.5) * 2,
                        "resistance": 1.0 - (bdsm_val - 0.5),
                        "metadata": {"bdsm_valuation": bdsm_val, "signal": "overvalued"},
                    })
                elif bdsm_val < 0.3:
                    paths.append({
                        "path_id": "bdsm_fundamental_long",
                        "source": "bdsm",
                        "direction": "long",
                        "expected_return": (0.5 - bdsm_val) * 0.4,
                        "confidence": (0.5 - bdsm_val) * 2,
                        "resistance": 1.0 - (0.5 - bdsm_val),
                        "metadata": {"bdsm_valuation": bdsm_val, "signal": "undervalued"},
                    })
        except Exception as e:
            logger.debug("[FO] bdsm path fail: %s", e)

        # ---- 4. 战略层路径（宏观方向过滤） ----
        try:
            if self._bridge is not None:
                dir_state = self._bridge.get_direction_state()
                war_state = self._bridge.get_war_state()
                logger.info("[PathDiscovery] bridge: war=%s dir=%s bcrm_dir='%s' bdsm=%.2f",
                             war_state, dir_state,
                             self._bridge.get_bcrm_direction(),
                             self._bridge.get_bdsm_valuation())
                if war_state == "ALLOW" and dir_state in ("LONG_ONLY", "LONG_PREFER"):
                    paths.append({
                        "path_id": "strategic_macro_long",
                        "source": "strategic",
                        "direction": "long",
                        "expected_return": 0.15,
                        "confidence": 0.6,
                        "resistance": 0.4,
                        "metadata": {"war_state": war_state, "dir_state": dir_state},
                    })
                elif war_state == "ALLOW" and dir_state in ("SHORT_ONLY", "SHORT_PREFER"):
                    paths.append({
                        "path_id": "strategic_macro_short",
                        "source": "strategic",
                        "direction": "short",
                        "expected_return": 0.15,
                        "confidence": 0.6,
                        "resistance": 0.4,
                        "metadata": {"war_state": war_state, "dir_state": dir_state},
                    })
                elif war_state == "FREEZE":
                    # FREEZE 双候选竞争：short + neutral，由矛盾识别和 HJB 评分决定
                    paths.append({
                        "path_id": "strategic_freeze_defensive_short",
                        "source": "strategic",
                        "direction": "short",
                        "expected_return": -0.05,
                        "confidence": 0.55,
                        "resistance": 0.6,
                        "metadata": {"war_state": war_state, "dir_state": dir_state,
                                     "signal": "freeze_defensive"},
                    })
                    paths.append({
                        "path_id": "strategic_freeze_neutral",
                        "source": "strategic",
                        "direction": "neutral",
                        "expected_return": 0.0,
                        "confidence": 0.50,
                        "resistance": 0.4,
                        "metadata": {"war_state": war_state, "dir_state": dir_state,
                                     "signal": "freeze_neutral"},
                    })
        except Exception as e:
            logger.debug("[FO] strategic path fail: %s", e)

        # ---- 5. DeepReasoningEngine 路径（基于现有计算新的） ----
        try:
            closes_raw = market_data.get("close", [])
            if isinstance(closes_raw, (list, np.ndarray)) and len(closes_raw) >= 10:
                dr_engine = self._get_deep_reasoning()
                if dr_engine is not None:
                    price_path = np.array(closes_raw, dtype=float)
                    dr_result = self._agi_enhance(
                        "enable_deep_reasoning",
                        fn=dr_engine.reason,
                        fallback=None,
                        price_path=price_path,
                        horizon=20,
                        n_paths=500,
                    )
                    if dr_result is not None:
                        forecast = dr_result.get("forecast", [])
                        min_res = float(dr_result.get("min_resistance", 0.5))
                        current_price = float(np.asarray(price_path[-1]).item())
                        if isinstance(forecast, (list, np.ndarray)) and len(forecast) > 0:
                            end_price = float(np.asarray(forecast[-1]).item())
                            expected_move = (end_price - current_price) / current_price
                            dr_dir = "long" if expected_move > 0.01 else ("short" if expected_move < -0.01 else "neutral")
                            paths.append({
                                "path_id": "deep_reasoning_mc",
                                "source": "deep_reasoning",
                                "direction": dr_dir,
                                "expected_return": abs(expected_move),
                                "confidence": max(0.0, min(1.0, 1.0 - min_res)),
                                "resistance": max(0.01, min(1.0, min_res)),
                                "metadata": {
                                    "forecast_end": end_price,
                                    "n_paths": 500,
                                    "min_resistance": min_res,
                                },
                            })
        except Exception as e:
            logger.debug("[FO] deep_reasoning path fail: %s", e)

        # ---- 6. StrategySynthesizer 路径（自进化涌现新路径） ----
        try:
            synth = self._get_strategy_synth()
            if synth is not None and paths:
                # 用 top-1 路径作为候选基因验证
                best_existing = max(paths, key=lambda p: p["expected_return"])
                # 从 L2 基因库路径提取真实 action_ids
                candidate_action_ids = []
                if best_existing["source"] == "l2_gene":
                    combo_meta = best_existing.get("metadata", {})
                    combo_id = combo_meta.get("combo_id", "")
                    # 从 library 查找 combo 的 action_ids
                    library = self._load_library()
                    for cb in library.get("combinations", []):
                        if cb.get("combo_id") == combo_id:
                            candidate_action_ids = cb.get("action_ids", [])
                            break
                if not candidate_action_ids:
                    candidate_action_ids = ["CD-DONCHIAN-20-BREAK", "AC-LONG-3SL-6TP-H1"]
                synth_result = self._agi_enhance(
                    "enable_strategy_synthesizer",
                    fn=synth.validate_and_integrate,
                    fallback=None,
                    candidate={"action_ids": candidate_action_ids},
                    price_data=np.array(market_data.get("close", [100.0]), dtype=float) if isinstance(market_data.get("close"), list) else None,
                    top_gene_sharpe=best_existing.get("confidence", 1.0),
                )
                if synth_result and synth_result.get("integrated"):
                    paths.append({
                        "path_id": "synthesized_new_gene",
                        "source": "synthesized",
                        "direction": best_existing["direction"],
                        "expected_return": best_existing["expected_return"] * 0.5,  # 冷启动折扣
                        "confidence": 0.3,  # 冷启动低置信度
                        "resistance": 0.8,  # 新路径高阻力（未验证）
                        "metadata": {
                            "gene_id": synth_result.get("gene_id", ""),
                            "cold_start_position": synth_result.get("cold_start_position", 0.05),
                        },
                    })
        except Exception as e:
            logger.debug("[FO] synthesized path fail: %s", e)

        return paths

    def _select_optimal_path_debug(self, paths: list[dict], symbol: str) -> None:
        """调试日志：打印所有发现的路径。"""
        try:
            _sources = [f"{p.get('source','?')}:{p.get('direction','?')}" for p in paths]
            logger.info("[PathDiscovery] %s 发现 %d 条路径: %s",
                        symbol, len(paths), ", ".join(_sources))
        except Exception:
            pass

    def _select_optimal_path(
        self,
        paths: list[dict],
        r_out: dict,
        market_data: dict | None = None,
    ) -> dict:
        """路径寻优：多路径竞争 → 选最优路径.

        评分公式（v3.0 扩展）：
          base_score = expected_return × confidence × (1 - resistance)
          hjb_adjust = × (0.7 + 0.3 × v_adjust)          # HJB 值函数 30% 权重
          contradiction_adjust = × (1 + 0.2 × strength)  # 对齐主要矛盾加分
                                   × (1 - 0.3 × strength)  # 逆向减分
          continuation_adjust = × (0.8 + 0.4 × cont)      # 趋势延续性增强

        统计验证：
          - 最优路径 score 必须超过阈值 0.05（否则 WAIT）
          - 最优路径与次优路径 score 差距 < 0.02 → 低确信度 → 降仓

        返回:
          {
            "optimal_path": dict | None,
            "all_paths": list[dict],
            "path_scores": list[dict],
            "statistical_validation": dict,
            "hjb_policy": dict | None,
            "primary_contradiction": dict | None,  # Phase 3.4 新增
          }
        """
        if not paths:
            return {
                "optimal_path": None,
                "all_paths": [],
                "path_scores": [],
                "statistical_validation": {"validated": False, "reason": "no_paths"},
                "hjb_policy": None,
                "primary_contradiction": None,
                "exogenous_pc": None,
                "structural_break": None,
                "shift_result": None,
                "elastic_result": None,
            }

        # 调试日志：打印所有发现的路径
        try:
            _sources = [f"{p.get('source','?')}:{p.get('direction','?')}" for p in paths]
            logger.info("[PathDiscovery] 发现 %d 条路径: %s", len(paths), ", ".join(_sources))
        except Exception:
            pass

        # === Phase 3.4: 主要矛盾识别（开关 + FAIL-OPEN）— 先于 HJB ===
        primary_contradiction = None
        try:
            from dreambuddy_evolution.agi_config import get_switch
            if get_switch("enable_contradiction_identifier", True):
                from dreambuddy_evolution.core.contradiction_identifier import (
                    PrimaryContradictionIdentifier,
                )
                identifier = PrimaryContradictionIdentifier()
                # Fix 3: 按维度独立取权重，传入 dict 供 identify 按维度调制
                _wfs = getattr(self, "_contradiction_weight_factors", {})
                primary_contradiction = identifier.identify(
                    paths, market_data or {}, r_out,
                    weight_factor=_wfs,
                )
        except Exception as e:  # noqa: BLE001  HC-AGI-18
            logger.debug("[FO-AGI-Pipeline][Contradiction] fail: %s", e)

        # === Phase 3.2: TrendContinuationScorer 接入 — 填充 continuation_score ===
        try:
            from dreambuddy_evolution.agi_config import get_switch as _gs
            if _gs("enable_trend_continuation", True) and market_data:
                from dreambuddy_evolution.core.trend_continuation import (
                    TrendContinuationScorer,
                )
                _tcs = TrendContinuationScorer()
                for _p in paths:
                    if "continuation_score" not in _p:
                        _dir = _p.get("direction", "long")
                        _ts = _tcs.score(market_data, _dir)
                        _p["continuation_score"] = _ts.get("continuation_score", 0.5)
                        _p.setdefault("cause_score", _ts.get("cause_score", 0.5))
                        _p.setdefault("effort_result", _ts.get("effort_result", 0.5))
        except Exception as _e:  # noqa: BLE001  HC-AGI-20
            logger.debug("[FO-AGI-Pipeline][TrendCont] fail: %s", _e)

        # === Phase 1: 外生力量度量增强 primary_contradiction ===
        _exogenous_pc = None
        try:
            _eval = self._get_exogenous_evaluator()
            if _eval is not None and market_data:
                _exogenous_pc = _eval.get_primary_contradiction(market_data)
                if _exogenous_pc is not None:
                    # 外生度量优先：替换或增强原有矛盾识别
                    primary_contradiction = _exogenous_pc
        except Exception as _e:  # noqa: BLE001
            logger.debug("[FO-Phase1][Exogenous] fail: %s", _e)

        # === Phase 2: 结构断裂检测 + 矛盾转化积累 ===
        try:
            _sbd = self._get_structural_break_detector()
            if _sbd is not None and market_data:
                _price_key = "_last_price"
                _prices = market_data.get("close") or market_data.get("kline_close")
                if _prices is not None:
                    import numpy as _np
                    _price_arr = _np.asarray(_prices, dtype=float) if isinstance(_prices, list) else _np.array([float(_prices)])
                    self._last_structural_break = _sbd.detect_all(_price_arr)
        except Exception as _e:  # noqa: BLE001
            logger.debug("[FO-Phase2][StructBreak] fail: %s", _e)

        try:
            _acc = self._get_shift_accumulator()
            if _acc is not None and primary_contradiction is not None:
                # 记录当前矛盾矩阵快照
                _all_evals = primary_contradiction.get("all_contradictions", {})
                _flat = []
                for _dim, _tfs in _all_evals.items():
                    for _tf, _val in _tfs.items():
                        _flat.append({
                            "dimension": _dim, "timeframe": _tf,
                            "direction": "bull" if _val > 0.55 else ("bear" if _val < 0.45 else "neutral"),
                            "normalized_strength": _val,
                        })
                if _flat:
                    _acc.record(_flat)
                    self._last_shift_result = _acc.detect_shift(self._last_structural_break)
        except Exception as _e:  # noqa: BLE001
            logger.debug("[FO-Phase2][ShiftAcc] fail: %s", _e)

        # === Phase 3: 弹性约束 → 仓位倍数调整 ===
        try:
            _elastic = self._get_elastic_resolver()
            if _elastic is not None and primary_contradiction is not None:
                _all_evals = primary_contradiction.get("all_contradictions", {})
                # 找力量最强的两个矛盾
                _candidates = []
                for _dim, _tfs in _all_evals.items():
                    for _tf, _val in _tfs.items():
                        _candidates.append({"dimension": _dim, "timeframe": _tf,
                                           "direction": primary_contradiction.get("direction", "neutral"),
                                           "strength": abs(_val - 0.5) * 2.0})
                if len(_candidates) >= 2:
                    # §15 层级加权排序：tier_bonus 加权
                    TIER_WEIGHT = {"short": 0.2, "medium": 0.3, "long": 0.5}
                    _candidates.sort(
                        key=lambda c: c["strength"] + TIER_WEIGHT.get(c["timeframe"], 0.2) * 0.3,
                        reverse=True,
                    )
                    # §20 分层弹性约束：传入 timeframe
                    self._last_elastic_result = _elastic.resolve(
                        _candidates[0], _candidates[1],
                        primary_tf=_candidates[0].get("timeframe", "medium"),
                        secondary_tf=_candidates[1].get("timeframe", "medium"),
                    )
        except Exception as _e:  # noqa: BLE001
            logger.debug("[FO-Phase3][Elastic] fail: %s", _e)

        # === HJB 值函数增强（矛盾调制传入）— 在矛盾识别之后 ===
        hjb_policy = None
        reflexivity_fuel = None  # 初始化，确保开关关闭时返回语句可访问
        try:
            from dreambuddy_evolution.agi_config import get_switch
            if get_switch("enable_hjb_solver", True):
                from dreambuddy_evolution.core.hjb_solver import HJBPathSolver
                start_price = float(r_out.get("_last_price", 100.0))
                vol = float(r_out.get("_last_vol", 0.02))
                solver = HJBPathSolver()

                # §14 反身性燃料偏移：从 ReflexivityMonitor 构造 fuel dict
                reflexivity_fuel = None
                try:
                    refl_monitor = self._get_reflexivity_monitor()
                    if refl_monitor is not None:
                        refl_result = refl_monitor.check_self_influence()
                        # 兼容两种字段名
                        detected = refl_result.get("self_influence_detected",
                                    refl_result.get("detected", False))
                        lambda_val = float(refl_result.get("influence_coefficient",
                                            refl_result.get("lambda", 0.0)))
                        if detected and lambda_val > 0.02:
                                reflexivity_fuel = {
                                    "type": "leverage",  # P1 先行：默认杠杆型
                                    "intensity": min(1.0, lambda_val),
                                }
                except Exception:
                    reflexivity_fuel = None  # FAIL-OPEN

                # §18 质变驱动路径切换：从 ContradictionShiftAccumulator 构造 shift_points
                shift_points = None
                try:
                    shift_acc = getattr(self, "_shift_accumulator", None)
                    if shift_acc is not None:
                        shift_result = getattr(shift_acc, "_last_shift_result", None)
                        if shift_result is not None and shift_result.get("shift_detected", False):
                            t_shift = int(shift_result.get("shift_time", 0))
                            new_primary = shift_result.get("new_primary")
                            if new_primary is not None:
                                shift_points = [(t_shift, new_primary)]
                except Exception:
                    shift_points = None  # FAIL-OPEN

                hjb_policy = solver.solve(
                    start_price=start_price,
                    horizon=20,
                    volatility=vol,
                    r_vector=r_out,
                    primary_contradiction=primary_contradiction,
                    reflexivity_fuel=reflexivity_fuel,
                    shift_points=shift_points,
                )
        except Exception as e:  # noqa: BLE001
            logger.debug("[FO-AGI-Pipeline][HJB] fail: %s", e)

        # === §19 认知函数：价格信息流更新认知状态 ===
        cognition_result = None
        try:
            # 直接使用 CognitiveFunction（不依赖 enable_reflexivity_monitor 开关）
            if not hasattr(self, "_cognitive_fn"):
                from dreambuddy_evolution.core.cognitive_function import CognitiveFunction
                self._cognitive_fn = CognitiveFunction()
            if self._cognitive_fn is not None:
                last_price = float(r_out.get("_last_price", 100.0))
                # 从 r_out 中提取前收盘价作为 prev_price
                _closes = r_out.get("close") or r_out.get("kline_close") or r_out.get("closes")
                prev_price = last_price
                if _closes is not None:
                    if isinstance(_closes, (list, tuple)) and len(_closes) >= 2:
                        prev_price = float(_closes[-2])
                    elif isinstance(_closes, (int, float)):
                        prev_price = float(_closes)
                # 价格信号: 涨→>0.5 利多, 跌→<0.5 利空
                if prev_price > 1e-6:
                    price_signal = 0.5 + min(0.5, max(-0.5, (last_price - prev_price) / prev_price))
                else:
                    price_signal = 0.5
                info_signals = [{"type": "price", "signal": price_signal, "weight": 1.0}]
                _prev_belief = self._cognitive_fn.get_cognition()
                _new_belief = self._cognitive_fn.update(price_signal, 1.0)
                cognition_result = {
                    "cognition": _new_belief,
                    "cognition_delta": _new_belief - _prev_belief,
                    "reflexivity_loop_active": True,
                }
        except Exception:
            cognition_result = None  # FAIL-OPEN

        # 计算评分（v3.0 扩展：HJB + 矛盾强度 + 趋势延续性）
        scored = []
        for p in paths:
            score = (
                float(p["expected_return"])
                * float(p["confidence"])
                * (1.0 - float(p["resistance"]))
            )
            # HJB 增强: 值函数 V(start,0) 调整 score
            # 默认 30% 权重; enable_hjb_dominant=True 时 70% 权重
            if hjb_policy is not None:
                v_adjust = max(0.0, 1.0 - hjb_policy["total_cost"])
                hjb_weight = 0.70 if get_switch("enable_hjb_dominant", False) else 0.30
                score = score * ((1.0 - hjb_weight) + hjb_weight * v_adjust)

            # 矛盾强度增强: 对齐主要矛盾 → 加分, 逆向 → 减分
            if primary_contradiction is not None:
                pc_dir = primary_contradiction.get("direction", "neutral")
                pc_strength = float(primary_contradiction.get("strength", 0.0))
                if p.get("direction") == pc_dir and pc_dir != "neutral":
                    score = score * (1.0 + 0.2 * pc_strength)  # 对齐加分
                elif p.get("direction") != "neutral" and p.get("direction") != pc_dir:
                    score = score * (1.0 - 0.3 * pc_strength)  # 逆向减分

            # 趋势延续性增强: 延续性高 → 加分
            cont = float(p.get("continuation_score", 0.5))  # HC-AGI-20: 缺失取 0.5
            score = score * (0.8 + 0.4 * cont)

            scored.append({**p, "score": round(score, 6)})

        # 按评分降序
        scored.sort(key=lambda x: x["score"], reverse=True)

        best = scored[0]
        second = scored[1] if len(scored) > 1 else None

        # 统计验证
        validated = best["score"] > 0.05
        low_conviction = second is not None and (best["score"] - second["score"]) < 0.02

        # Phase 3.5: 存储识别结果供 get_feedback() 回流使用
        self._last_primary_contradiction = primary_contradiction

        return {
            "optimal_path": best if validated else None,
            "all_paths": scored,
            "path_scores": [{"path_id": p["path_id"], "source": p["source"],
                             "direction": p["direction"], "score": p["score"]} for p in scored],
            "statistical_validation": {
                "validated": validated,
                "best_score": best["score"],
                "second_score": second["score"] if second else 0.0,
                "score_gap": best["score"] - (second["score"] if second else 0.0),
                "low_conviction": low_conviction,
                "reason": "validated" if validated else "score_below_threshold",
            },
            "hjb_policy": {
                "total_cost": hjb_policy["total_cost"],
                "converged": hjb_policy["converged"],
                "backend": hjb_policy["backend"],
            } if hjb_policy is not None else None,
            "primary_contradiction": primary_contradiction,
            # Phase 1-3 新增返回字段
            "exogenous_pc": _exogenous_pc,
            "structural_break": self._last_structural_break,
            "shift_result": self._last_shift_result,
            "elastic_result": self._last_elastic_result,
            # §14+§19 新增：反身性燃料+认知函数
            "reflexivity_fuel": reflexivity_fuel,
            "cognition_result": cognition_result,
        }

    def _load_library(self):
        if self._library is None:
            from dreambuddy_evolution.core import strategy_gene as sgs
            self._library = sgs.load_gene_library(self.gene_root)
        return self._library

    def _resolve_action_direction(self, action_ids: list[str]) -> str:
        """从 action gene 解析方向 (long/short/both/neutral)."""
        try:
            act_dir = self.gene_root / "strategy_genes" / "actions"
            directions = []
            for aid in action_ids:
                f = act_dir / f"{aid}.json"
                if f.exists():
                    g = json.loads(f.read_text(encoding="utf-8"))
                    d = g.get("direction", "neutral")
                    if d != "both":
                        directions.append(d)
            # 优先取非 both 方向
            for d in directions:
                if d in ("long", "short"):
                    return d
            return directions[0] if directions else "neutral"
        except Exception as e:
            logger.warning("[FO] action direction resolve fail: %s", e)
            return "neutral"

    def run_symbol(self, symbol: str, market_data: dict, rv=None) -> dict[str, Any]:
        """
        单 symbol 全 pipeline 运行.
        完整进化闭环: L1→高阶调制→路径发现→寻优→argmin→统计验证→决策→L3/L4

        返回: {l1_r_vector, path_discovery, level0_d_star, action, l3_sample, l4_v, ...}
        """
        from dreambuddy_evolution.core.resistance_vector import ResistanceVector
        from dreambuddy_evolution.core.level0_path_cost import compute_g_diag, compute_d_star
        from dreambuddy_evolution.core import strategy_gene as sgs

        # ============ L1: 状态空间层 ============
        if rv is None:
            rv = ResistanceVector()
        r_out = rv.calculate(symbol, market_data)

        # ============ 高阶基因因子阻力调制 ============
        r_out = self._apply_high_order_factors(r_out, symbol)

        # ============ 路径发现层：多路径竞争 ============
        paths = self._discover_paths(r_out, market_data, symbol)

        # ============ Regime 检测（供返回） ============
        regime = "UNKNOWN"
        try:
            if self._regime_gate is not None:
                kline_data = market_data.get("kline_data", {})
                regime = self._regime_gate.detect_regime(kline_data)
        except Exception:
            pass  # FAIL-OPEN

        # ============ 路径寻优 → 统计验证 ============
        self._select_optimal_path_debug(paths, symbol)  # 调试日志
        path_selection = self._select_optimal_path(paths, r_out, market_data)
        optimal_path = path_selection["optimal_path"]
        stat_val = path_selection["statistical_validation"]

        # ============ 依据最优路径计算 argmin 最小阻力 ============
        d_star_result = compute_d_star(r_out)
        if optimal_path is not None:
            # 用最优路径方向作为 d* 的先验
            d_star = d_star_result["d_star"]
            optimal_dir = optimal_path["direction"]

            # 对齐检查：d* 与最优路径方向是否一致
            if d_star in ("long", "short") and optimal_dir == d_star:
                aligned = True
            elif d_star == "WAIT" and optimal_dir in ("long", "short"):
                # R 向量 WAIT 但路径发现有力 → 轻仓
                aligned = False
                d_star = optimal_dir  # 采用路径发现方向
            elif d_star in ("long", "short") and optimal_dir != d_star and optimal_dir != "neutral":
                # 方向冲突 → 降仓
                aligned = False
            else:
                aligned = False
        else:
            # 无最优路径通过统计验证 → WAIT
            d_star = "WAIT"
            aligned = False

        # ============ 决策输出 ============
        if aligned and d_star == "long":
            action = "long"
        elif aligned and d_star == "short":
            action = "short"
        elif d_star in ("long", "short") and not aligned:
            action = f"light_{d_star}"  # 轻仓
        else:
            action = "WAIT"

        # 统计验证低确信度 → 降仓
        if stat_val.get("low_conviction") and action in ("long", "short"):
            action = f"light_{d_star}"

        # ============ L2: 基因库 top_combo（保留兼容） ============
        library = self._load_library()
        top_combos = sgs.top_combinations_by_ess(library, min_sample=0)
        top_combo = top_combos[0] if top_combos else None
        if top_combo:
            resolved_dir = self._resolve_action_direction(top_combo.get("action_ids", []))
            top_combo["resolved_direction"] = resolved_dir

        # ============ AGI 增强点 G: StrategySynthesizer（只读，已在路径发现中调用） ============
        agi_strategy_synth = None
        for p in paths:
            if p["source"] == "synthesized":
                agi_strategy_synth = p.get("metadata", {})
                agi_strategy_synth["integrated"] = True
                break

        # ============ AGI 增强点 F: DeepReasoningEngine（只读，已在路径发现中调用） ============
        agi_deep_reasoning = None
        for p in paths:
            if p["source"] == "deep_reasoning":
                agi_deep_reasoning = p.get("metadata", {})
                break

        # ============ L3: Shadow-RL 记录 ============
        # Fix 1: 不再用 quality_score 作为 reward（数据质量≠方向正确性）
        # 真实 PnL reward 由 TradeSettlementBridge._record_real_pnl_reward 在平仓时注入
        self.shadow_rl.record(
            symbol=symbol,
            state={"R_up": r_out["R_up"], "R_down": r_out["R_down"],
                   "R_smooth": r_out["R_smooth"], "R_flow": r_out["R_flow"],
                   "R_reflexivity": r_out["R_reflexivity"],
                   "quality_score": r_out.get("quality_score", 0.5)},
            action=action,
            reward=0.0,  # Fix 1: 占位，真实 reward 由平仓事件注入
            next_state={},
        )

        # ============ AGI 增强点 H: TransferLearner 跨资产迁移（只读） ============
        agi_transfer = None
        try:
            tl = self._get_transfer_learner()
            if tl is not None:
                # 用 market_data 中的收益率作为源/目标资产数据
                source_rets = market_data.get("source_returns", [])
                target_rets = market_data.get("target_returns", [])
                control_rets = market_data.get("control_returns", [])
                source_sym = market_data.get("source_asset", "BTC")
                target_sym = symbol
                if source_rets and target_rets and control_rets:
                    agi_transfer = self._agi_enhance(
                        "enable_transfer_learning",
                        fn=tl.transfer_pattern,
                        fallback=None,
                        source_asset=source_sym,
                        target_asset=target_sym,
                        source_returns=np.array(source_rets, dtype=float),
                        target_returns=np.array(target_rets, dtype=float),
                        control_returns=np.array(control_rets, dtype=float),
                    )
                    if agi_transfer and agi_transfer.get("valid"):
                        logger.info(
                            "[AGI-H] %s transfer: valid=%s sim=%.3f alpha=%.4f",
                            symbol,
                            agi_transfer.get("valid"),
                            agi_transfer.get("similarity", 0),
                            agi_transfer.get("counterfactual_alpha", 0),
                        )
        except Exception as e:
            logger.debug("[FO-AGI-H] transfer fail: %s", e)

        # ============ AGI 增强点 I: CounterfactualEvaluator 反事实评估（只读） ============
        agi_counterfactual = None
        try:
            cf = self._get_counterfactual()
            if cf is not None:
                target_rets = market_data.get("target_returns", [])
                control_rets = market_data.get("control_returns", [])
                actual_pnl = market_data.get("actual_pnl", 0.0)
                if target_rets and control_rets:
                    agi_counterfactual = self._agi_enhance(
                        "enable_counterfactual",
                        fn=cf.what_if_no_trade,
                        fallback=None,
                        target_returns=np.array(target_rets, dtype=float),
                        control_returns=np.array(control_rets, dtype=float),
                        actual_pnl=actual_pnl,
                    )
                    if agi_counterfactual:
                        logger.debug(
                            "[AGI-I] %s CF: alpha=%.4f beta=%.4f",
                            symbol,
                            agi_counterfactual.get("alpha", 0),
                            agi_counterfactual.get("beta", 0),
                        )
        except Exception as e:
            logger.debug("[FO-AGI-I] counterfactual fail: %s", e)

        # ============ L4: Bellman V(s) 更新 ============
        # Bellman V(s) 跟踪状态价值，quality_score 作为状态质量信号仍合理
        # 注意：ShadowRL 的 reward 已改为 0.0 占位（真实 PnL 由平仓事件注入），
        # 但 Bellman 的 V(s) 是状态价值函数，与策略反馈不同，保留 quality_score 信号
        _bellman_reward = float(r_out.get("quality_score", 0.5)) - 0.5
        self.bellman.td_update(symbol, reward=_bellman_reward, next_symbol=symbol)

        return {
            "symbol": symbol,
            "regime": regime,
            "l1_r_vector": r_out,
            # 路径发现层（含 path_info: primary/fuel/cognition/elastic/hjb）
            "path_discovery": {
                "all_paths": path_selection["all_paths"],
                "path_scores": path_selection["path_scores"],
                "optimal_path": optimal_path,
                "path_info": path_selection.get("path_info", {}),
                "statistical_validation": stat_val,
                "n_paths": len(paths),
            },
            "level0_d_star": d_star,
            "level0_confidence": d_star_result["confidence"],
            "level0_costs": d_star_result["costs"],
            "l2_top_combo": top_combo,
            "aligned": aligned,
            "action": action,
            "l3_sample_count": self.shadow_rl.sample_count(),
            "l4_v": self.bellman.get_v(symbol),
            # AGI 阶段4 只读增强字段
            "agi_deep_reasoning": agi_deep_reasoning,
            "agi_strategy_synth": agi_strategy_synth,
            "agi_transfer": agi_transfer,
            "agi_counterfactual": agi_counterfactual,
        }

    def run_batch(self, symbols_data: dict[str, dict], rv=None) -> dict[str, dict]:
        """批量多 symbol pipeline."""
        results = {}
        for sym, data in symbols_data.items():
            try:
                results[sym] = self.run_symbol(sym, data, rv=rv)
            except Exception as e:  # FO-3 FAIL-OPEN
                logger.error("[FO-3] pipeline crash for %s: %s", sym, e)
                results[sym] = {
                    "symbol": sym,
                    "action": "WAIT",
                    "error": str(e),
                    "l1_r_vector": {},
                    "path_discovery": {"all_paths": [], "optimal_path": None, "statistical_validation": {"validated": False}},
                    "level0_d_star": "WAIT",
                    "l2_top_combo": None,
                    "aligned": False,
                    "agi_deep_reasoning": None,
                    "agi_strategy_synth": None,
                    "agi_transfer": None,
                    "agi_counterfactual": None,
                }
        return results

    def get_feedback(self) -> dict[str, Any]:
        """L3/L4 回馈摘要 → L2 ESS 调整 + L1 权重校准."""
        rl_stats = self.shadow_rl.get_stats()
        v_all = self.bellman.get_all_v()
        ess_adjusts = {sym: self.bellman.get_ess_adjustment(sym) for sym in v_all}

        # Phase 3.5: 矛盾反馈 — 用 L3 统计作为 outcome 调整矛盾权重
        contradiction_feedback_result = None
        try:
            _cf = self._get_contradiction_feedback()
            if _cf is not None and self.shadow_rl.sample_count() > 0:
                # Fix 2: 从 ShadowRL 样本反向计算真实 fail_streak
                _fail_streak = 0
                try:
                    _rewards = [s.get("reward", 0.0) for s in self.shadow_rl._samples]
                    for _r in reversed(_rewards):
                        if _r < 0:
                            _fail_streak += 1
                        else:
                            break
                except Exception:
                    _fail_streak = 0

                _outcome = {
                    "success": rl_stats.get("mean_reward", 0) > 0,
                    "pnl": rl_stats.get("mean_reward", 0),
                    "n_trials": rl_stats.get("sample_count", 0),
                    "fail_streak": _fail_streak,
                }
                _pc = getattr(self, "_last_primary_contradiction", None) or {}
                contradiction_feedback_result = _cf.adjust_weight(_pc, _outcome)
                # Fix 3: 按维度存储权重因子 + 持久化
                _wf_info = (contradiction_feedback_result or {}).get("weight_adjustment", {})
                _dim = _pc.get("dimension", "unknown")
                # Fix B: dimension 为 unknown 时跳过，避免污染权重字典
                if _dim != "unknown":
                    _new_wf = _wf_info.get("weight_factor", 1.0)
                    self._contradiction_weight_factors[_dim] = max(0.3, min(1.5, float(_new_wf)))
                    self._save_weight_factors()
        except Exception as _e:
            logger.debug("[FO] contradiction_feedback crash: %s", _e)

        return {
            "l3_stats": rl_stats,
            "l4_v_all": v_all,
            "l4_ess_adjustments": ess_adjusts,
            "contradiction_feedback": contradiction_feedback_result,
        }

    def _incremental_feedback(self, pc: dict, aligned: bool, pct: float) -> None:
        """Fix 6: K线级增量反馈 — EWMA 式更新按维度矛盾权重。

        Args:
            pc: 上次主要矛盾识别结果
            aligned: 当前K线涨跌是否验证了矛盾方向
            pct: 当前K线涨跌幅
        """
        try:
            _dim = pc.get("dimension", "unknown")
            # Fix B: dimension 为 unknown 时不写入，避免污染权重字典
            if _dim == "unknown":
                return
            _wf = self._contradiction_weight_factors.get(_dim, 1.0)
            _alpha = 0.05  # EWMA 学习率
            if aligned:
                _new_wf = _wf + _alpha * (1.1 - _wf)
            else:
                _new_wf = _wf + _alpha * (0.8 - _wf)
            self._contradiction_weight_factors[_dim] = max(0.3, min(1.5, _new_wf))
            # 持久化到 weight_factors.json，避免重启后K线级学习结果丢失
            self._save_weight_factors()
        except Exception:
            pass  # FAIL-OPEN
