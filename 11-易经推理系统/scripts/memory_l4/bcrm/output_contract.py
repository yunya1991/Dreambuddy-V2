"""
BCRM 输出契约定义。

遵循 QMM 铁律 0.1：只输出固定结论集，可审计、可追溯。
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


@dataclass
class ContradictionState:
    """矛盾状态：当前主导二元矛盾。"""
    thesis: str = ""
    antithesis: str = ""
    dominant_side: str = "EQUAL"    # BULL / BEAR / EQUAL
    tension: float = 0.5
    source_contradiction_id: str = ""
    philosophy_basis: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "thesis": self.thesis,
            "antithesis": self.antithesis,
            "dominant_side": self.dominant_side,
            "tension": round(self.tension, 4),
            "source_contradiction_id": self.source_contradiction_id,
            "philosophy_basis": self.philosophy_basis,
        }


@dataclass
class DialecticalStep:
    """正反合推理步。"""
    thesis: Dict = field(default_factory=dict)
    antithesis: Dict = field(default_factory=dict)
    synthesis: str = ""
    adjudication: Dict = field(default_factory=dict)
    evidence_refs: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "thesis": self.thesis,
            "antithesis": self.antithesis,
            "synthesis": self.synthesis,
            "adjudication": self.adjudication,
            "evidence_refs": self.evidence_refs,
        }


@dataclass
class NextState:
    """推演的下一行情状态。"""
    direction: str = "UNKNOWN"      # UP/DOWN/FLAT/TRANSITIONING/UNKNOWN
    confidence: float = 0.0
    horizon: str = "UNKNOWN"        # 短/中/长
    derivation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "direction": self.direction,
            "confidence": round(self.confidence, 4),
            "horizon": self.horizon,
            "derivation": self.derivation,
        }


@dataclass
class StrategyBranch:
    """策略分支。"""
    branch_id: str = ""
    condition: str = ""
    action: str = ""
    position_modifier: float = 1.0
    stop_condition: str = ""
    rationale: str = ""
    # ── 结构化风控字段 ──
    stop_loss_px: float = 0.0       # 止损价（0 表示不设置）
    take_profit_px: float = 0.0     # 止盈价（0 表示不设置）
    reduce_ratio: float = 0.0       # 减仓比例 0~1（0 表示不减仓）

    def to_dict(self) -> Dict[str, Any]:
        return {
            "branch_id": self.branch_id,
            "condition": self.condition,
            "action": self.action,
            "position_modifier": round(self.position_modifier, 4),
            "stop_condition": self.stop_condition,
            "rationale": self.rationale,
            "stop_loss_px": round(self.stop_loss_px, 2) if self.stop_loss_px else 0,
            "take_profit_px": round(self.take_profit_px, 2) if self.take_profit_px else 0,
            "reduce_ratio": round(self.reduce_ratio, 4),
        }


@dataclass
class PracticeDirective:
    """实践指令（知行合一）。"""
    action: str = ""
    verification_condition: str = ""
    feedback_loop: str = ""
    theory_practice_alignment_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "verification_condition": self.verification_condition,
            "feedback_loop": self.feedback_loop,
            "theory_practice_alignment_score": round(
                self.theory_practice_alignment_score, 4),
        }


@dataclass
class SpiralPosition:
    """否定之否定螺旋定位。"""
    phase: str = "UNKNOWN"
    negation_count: int = 0
    historical_analogy_ref: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "phase": self.phase,
            "negation_count": self.negation_count,
            "historical_analogy_ref": self.historical_analogy_ref,
        }


@dataclass
class TransformationTrigger:
    """量变→质变转化触发条件。"""
    condition: str = ""
    probability: str = "LOW"        # LOW/MODERATE/HIGH
    accumulation: float = 0.0
    threshold: float = 0.7
    monitoring_point: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "condition": self.condition,
            "probability": self.probability,
            "accumulation": round(self.accumulation, 4),
            "threshold": round(self.threshold, 4),
            "monitoring_point": self.monitoring_point,
        }


@dataclass
class HexagramResult:
    """六十四卦推理结果。"""
    hexagram_name: str = ""          # 卦名英文
    hexagram_name_cn: str = ""       # 卦名中文
    inner_gua: str = ""              # 内卦（下卦）
    outer_gua: str = ""              # 外卦（上卦）
    gua_ci: str = ""                 # 卦辞
    tuan_zhuan: str = ""             # 彖传
    xiang_zhuan: str = ""            # 象传
    yao_results: List[Dict] = field(default_factory=list)  # 六爻结果
    changing_yaos: List[int] = field(default_factory=list)  # 动爻位置（1-6）
    changed_hexagram: str = ""       # 变卦卦名
    changed_hexagram_cn: str = ""    # 变卦卦名中文
    overall_meaning: str = ""        # 整体含义
    direction_hint: str = ""         # 方向暗示
    confidence: float = 0.0          # 置信度

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hexagram_name": self.hexagram_name,
            "hexagram_name_cn": self.hexagram_name_cn,
            "inner_gua": self.inner_gua,
            "outer_gua": self.outer_gua,
            "gua_ci": self.gua_ci,
            "tuan_zhuan": self.tuan_zhuan,
            "xiang_zhuan": self.xiang_zhuan,
            "yao_results": self.yao_results,
            "changing_yaos": self.changing_yaos,
            "changed_hexagram": self.changed_hexagram,
            "changed_hexagram_cn": self.changed_hexagram_cn,
            "overall_meaning": self.overall_meaning,
            "direction_hint": self.direction_hint,
            "confidence": round(self.confidence, 4),
        }


@dataclass
class BCRMOutput:
    """BCRM 完整输出契约。"""
    snapshot_ts: str = ""

    # 版本三元组
    data_version: str = ""
    feature_def_version: str = ""
    bcrm_version: str = "bcrm-v0.2"

    # 核心推演结论
    contradiction_state: ContradictionState = field(
        default_factory=ContradictionState)
    dialectical_step: DialecticalStep = field(
        default_factory=DialecticalStep)
    next_state: NextState = field(default_factory=NextState)
    transformation_trigger: TransformationTrigger = field(
        default_factory=TransformationTrigger)
    strategy_branches: List[StrategyBranch] = field(default_factory=list)
    practice_directive: PracticeDirective = field(
        default_factory=PracticeDirective)

    # 易经六十四卦推理结果
    hexagram: HexagramResult = field(default_factory=HexagramResult)

    # 力学引擎结果（第一性原理层）
    force_result: Dict = field(default_factory=dict)

    # 两仪状态（宏观美林时钟×微观生命周期）
    liangyi_state: Dict = field(default_factory=dict)

    # 体量自适应参数（太极→两仪→四象 调整后）
    scale_params: Dict = field(default_factory=dict)

    # 元信息
    spiral_position: SpiralPosition = field(default_factory=SpiralPosition)
    uncertainty: float = 1.0
    reason_codes: List[str] = field(default_factory=list)
    evidence_refs: List[str] = field(default_factory=list)
    philosophy_basis: List[str] = field(default_factory=list)

    # 八卦相关（兼容 Phase 1）
    bagua: str = ""
    bagua_meaning: str = ""

    # A0 层级隔离声明（P0 决议#3）
    # fail-closed 状态不进入 A0 消费链路，A0 消费时跳过 UNKNOWN
    a0_consume_eligible: bool = True

    # 情景推演两路径（P1 决议#4）
    scenario_path_a: Dict = field(default_factory=dict)  # 量变延续
    scenario_path_b: Dict = field(default_factory=dict)  # 质变反转

    def fail_closed(self, reason_code: str, evidence: List[str] = None):
        """将输出标记为 fail-closed。"""
        self.next_state = NextState(
            direction="UNKNOWN",
            confidence=0.0,
            horizon="UNKNOWN",
            derivation="fail-closed",
        )
        self.uncertainty = 1.0
        # A0 层级隔离：fail-closed 状态不进入 A0 消费链路
        self.a0_consume_eligible = False
        if reason_code not in self.reason_codes:
            self.reason_codes.append(reason_code)
        if evidence:
            self.evidence_refs.extend(evidence)

    def is_fail_closed(self) -> bool:
        """判断是否为 fail-closed。"""
        return self.next_state.direction == "UNKNOWN"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_ts": self.snapshot_ts,
            "data_version": self.data_version,
            "feature_def_version": self.feature_def_version,
            "bcrm_version": self.bcrm_version,
            "contradiction_state": self.contradiction_state.to_dict(),
            "dialectical_step": self.dialectical_step.to_dict(),
            "next_state": self.next_state.to_dict(),
            "transformation_trigger": self.transformation_trigger.to_dict(),
            "strategy_branches": [b.to_dict() for b in self.strategy_branches],
            "practice_directive": self.practice_directive.to_dict(),
            "hexagram": self.hexagram.to_dict(),
            "force_result": self.force_result,
            "liangyi_state": self.liangyi_state,
            "scale_params": self.scale_params,
            "spiral_position": self.spiral_position.to_dict(),
            "uncertainty": round(self.uncertainty, 4),
            "reason_codes": self.reason_codes,
            "evidence_refs": self.evidence_refs,
            "philosophy_basis": self.philosophy_basis,
            "bagua": self.bagua,
            "bagua_meaning": self.bagua_meaning,
            "a0_consume_eligible": self.a0_consume_eligible,
            "scenario_path_a": self.scenario_path_a,
            "scenario_path_b": self.scenario_path_b,
        }
