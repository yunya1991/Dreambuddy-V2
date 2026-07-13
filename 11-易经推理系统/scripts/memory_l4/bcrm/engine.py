"""
BCRM 核心引擎 — 二元矛盾推理模型。

三层架构：
- 数据层：供需/技术/资金/情绪 四维评分
- 哲学层：唯物辩证法三规律 + 矛盾论 + 黑格尔正反合
- 算法层：易经六十四卦推理算法

七步推理循环：
1. 矛盾识别（矛盾论）
2. 张力量化（对立统一）
3. 质变判定（量变质变）
4. 正反合裁决（黑格尔 + 易经）
5. 螺旋定位（否定之否定）
6. 策略分支生成
7. 实践指令（知行合一）
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from datetime import datetime

from ._constants import (
    BCRM_VERSION, FEATURE_DEF_VERSION,
    DIR_UP, DIR_DOWN, DIR_FLAT, DIR_TRANSITIONING, DIR_UNKNOWN,
    SPIRAL_FIRST_AFFIRMATION, SPIRAL_FIRST_NEGATION,
    SPIRAL_SECOND_NEGATION, SPIRAL_UNKNOWN,
    REASON_HIGH_UNCERTAINTY, REASON_NO_CONTRADICTION_DATA,
    REASON_CONTRADICTION_UNRESOLVED, REASON_INSUFFICIENT_MEMORY,
    REASON_AMBIGUOUS_SCENARIO, REASON_COLD_START_THRESHOLD,
    REASON_LOW_CONFIDENCE,
    PHIL_MAO_CONTRADICTION, PHIL_MATERIALIST_DIALECTIC,
    PHIL_HEGELIAN, PHIL_YIJING,
    DEFAULT_QUALITATIVE_THRESHOLD, DEFAULT_MIN_CONFIDENCE_THRESHOLD,
    DEFAULT_HIGH_UNCERTAINTY, DEFAULT_MIN_MEMORY_CASES,
    TENSION_HIGH_THRESHOLD, TENSION_MEDIUM_THRESHOLD,
    GUA_NAMES_CN,
    get_gua_yin_yang,
    SPIRAL_WEIGHT_PRICE, SPIRAL_WEIGHT_CONTRADICTION, SPIRAL_WEIGHT_GUA,
    SPIRAL_NEGATION_THRESHOLD, SPIRAL_PRICE_REVERSAL_FULL,
)
from .output_contract import (
    BCRMOutput, ContradictionState, DialecticalStep,
    NextState, StrategyBranch, PracticeDirective,
    SpiralPosition, TransformationTrigger, HexagramResult,
)
from .yijing_engine import YijingEngine
from .force_engine import ForceEngine
from .scale_engine import ScaleEngine, ScaleParams
from .liangyi_engine import LiangyiEngine


@dataclass
class BCRMEngine:
    """
    BCRM 推理引擎。

    第一性原理：市场沿阻力最小方向运动 = 力的合成。
    架构：力学引擎（核心）+ 易经引擎（符号解释层）。

    Step4 核心由力学引擎决定方向和强度，
    易经引擎负责把物理结果翻译成卦象符号。
    """

    min_confidence_threshold: float = 0.25   # P1修复: 原0.36过高，tanh修正后有效范围降至0.2-0.8
    qualitative_threshold: float = DEFAULT_QUALITATIVE_THRESHOLD
    sixiang_weights: Dict[str, float] = field(default_factory=dict)

    def __post_init__(self):
        self.yijing = YijingEngine()
        self.force_engine = ForceEngine()
        self.scale_engine = ScaleEngine()
        self.liangyi_engine = LiangyiEngine()
        if not self.sixiang_weights:
            self.sixiang_weights = {
                "supply_demand": 0.3,
                "technical": 0.25,
                "capital_flow": 0.25,
                "market_sentiment": 0.2,
            }

    def infer(self,
              market_snapshot: Dict[str, Any],
              contradiction_list: List[Dict] = None,
              memory_cases: List[Dict] = None,
              qmm_output: Dict = None,
              knowledge_base: Any = None) -> BCRMOutput:
        """
        运行 BCRM 推理。

        Args:
            market_snapshot: 市场快照
            contradiction_list: A0 矛盾列表
            memory_cases: L4 历史记忆案例
            qmm_output: QMM 输出
            knowledge_base: 知识库

        Returns:
            BCRMOutput
        """
        output = BCRMOutput(
            bcrm_version=BCRM_VERSION,
            feature_def_version=FEATURE_DEF_VERSION,
            snapshot_ts=market_snapshot.get("snapshot_ts",
                                            datetime.now().isoformat()),
        )

        # P0 修复: 自动预处理行情数据，解决 ForceEngine 信号断层
        from .market_preprocessor import normalize_snapshot
        market_snapshot = normalize_snapshot(market_snapshot)

        # P1 修复: 集成 Guardrail 输入验证
        from .guardrail import default_guardrail
        guard = default_guardrail()
        guard_result = guard.validate(
            market_snapshot=market_snapshot,
            contradiction_list=contradiction_list,
            qmm_output=qmm_output,
        )
        if not guard_result.passed:
            output.fail_closed(f"Guardrail验证失败: {'; '.join(guard_result.fail_reasons)}")
            return output

        # Bug Y1 修复: 无矛盾列表时自动从市场快照推导，而非直接 fail_closed
        if not contradiction_list:
            contradiction_list = self._auto_generate_contradictions(market_snapshot)

        # 提取四维评分
        sd_score = market_snapshot.get("supply_demand_score", 0.5)
        tech_score = market_snapshot.get("technical_score", 0.5)
        cf_score = market_snapshot.get("capital_flow_score", 0.5)
        sent_score = market_snapshot.get("sentiment_score", 0.5)
        trend_strength = market_snapshot.get("trend_strength", 0.5)
        volatility = market_snapshot.get("volatility", 0.5)
        volume_ratio = market_snapshot.get("volume_ratio", 1.0)
        price_position = market_snapshot.get("price_position", 0.5)

        # Step 1: 矛盾识别
        contrad_state = self._step1_identify_contradiction(
            contradiction_list, market_snapshot)
        output.contradiction_state = contrad_state

        # Step 2: 张力量化
        tension, accumulation = self._step2_quantify_tension(
            contrad_state, market_snapshot, memory_cases)
        output.contradiction_state.tension = tension

        # Step 3: 质变判定
        is_qualitative_change, trigger = self._step3_qualitative_change(
            tension, accumulation, memory_cases)
        output.transformation_trigger = trigger

        # Step 4: 力学引擎推理（第一性原理）+ 易经符号解释
        # 4.1 太极（体量）→ 基础参数
        scale = self.scale_engine.compute_scale(market_snapshot)
        scale_params = self.scale_engine.get_params(scale)
        # 调整市场快照（波动率等）
        market_snapshot, scale_params = self.scale_engine.adapt_snapshot(
            market_snapshot, scale)

        # 4.2 两仪（宏观×微观）→ 参数偏置
        # 两仪生四象：美林时钟+生命周期 影响时空表里参数
        scale_params, liangyi_state = self.liangyi_engine.adapt(
            market_snapshot, scale_params)

        # 4.3 力学引擎决定方向和强度（核心）— 传入两仪调整后的参数
        force_result = self.force_engine.infer(
            market_snapshot, scale_params=scale_params)

        # 易经引擎翻译卦象（符号解释层）
        yijing_result = self.yijing.interpret_force(
            force_result,
            supply_demand_score=sd_score,
            technical_score=tech_score,
            capital_flow_score=cf_score,
            sentiment_score=sent_score,
            volatility=volatility,
            volume_ratio=volume_ratio,
            price_position=price_position,
            trend_strength=trend_strength,
        )

        # 保存力学结果 + 两仪状态 + 调整后参数
        output.force_result = force_result.to_dict()
        output.liangyi_state = liangyi_state.to_dict()
        output.scale_params = scale_params.to_dict()

        # 转换为 HexagramResult
        hex_result = self._yijing_to_hexagram_result(yijing_result)
        output.hexagram = hex_result

        # 八卦兼容（取外卦）
        output.bagua = yijing_result.outer_gua
        output.bagua_meaning = GUA_NAMES_CN.get(
            yijing_result.outer_gua, "")

        # 正反合
        dialectical = self._step4_synthesis(
            contrad_state, is_qualitative_change, yijing_result, memory_cases)
        output.dialectical_step = dialectical

        # 下一状态：以力学结果为准
        next_state = self._determine_next_state_from_force(
            force_result, is_qualitative_change, tension)
        output.next_state = next_state

        # 置信度分层处理（借鉴 LEAN 的信号强度分级）
        # 硬门槛（绝对不处理）: min_confidence_threshold * 0.7
        # 软门槛（轻仓试探）:    min_confidence_threshold
        # 正常门槛（标准仓位）:  scale_params.confidence_threshold * 0.8
        hard_threshold = self.min_confidence_threshold * 0.7   # ~0.175
        soft_threshold = self.min_confidence_threshold          # 0.25
        if next_state.direction == DIR_FLAT:
            hard_threshold *= 0.3
            soft_threshold *= 0.3

        if next_state.confidence < hard_threshold:
            # 完全无信号，fail_closed
            output.fail_closed(REASON_LOW_CONFIDENCE)
            return output
        elif next_state.confidence < soft_threshold:
            # 弱信号：标记为低置信度，继续执行但后续策略分支会生成轻仓版本
            output.reason_codes = output.reason_codes or []
            output.reason_codes.append("WEAK_SIGNAL_LIGHT_POSITION")
            # 不 return，继续走完流程

        # Step 5: 螺旋定位
        spiral = self._step5_spiral_position(
            memory_cases, yijing_result, price_position,
            market_snapshot=market_snapshot,
            contradiction_state=contrad_state)
        output.spiral_position = spiral

        # Step 5.5: 情景推演两路径（量变延续 vs 质变反转）
        output.scenario_path_a, output.scenario_path_b = (
            self._step55_scenario_paths(
                next_state, trigger, spiral, yijing_result))

        # Step 6: 策略分支
        is_weak_signal = bool(output.reason_codes and
                              "WEAK_SIGNAL_LIGHT_POSITION" in output.reason_codes)
        branches = self._step6_strategy_branches(
            next_state, trigger, spiral, yijing_result,
            price=market_snapshot.get("price", 0),
            volatility=volatility,
            confidence=next_state.confidence,
            is_weak_signal=is_weak_signal)

        # Step 6.5: 多样性扩展（借鉴 LEAN 多策略组合）
        # 当 B1 占比 > 80% 时自动补充互补策略
        try:
            from .strategy_diversity import StrategyDiversityManager
            sdm = StrategyDiversityManager()
            diversity_report = sdm.check_and_expand(market_snapshot, branches)
            if diversity_report.triggered and diversity_report.new_branches:
                for nb in diversity_report.new_branches:
                    from .output_contract import StrategyBranch
                    extra = StrategyBranch(
                        branch_id=nb["branch_id"],
                        condition=nb["condition"],
                        action=nb["action"],
                        position_modifier=nb.get("position_modifier", 0.3),
                        stop_condition=nb["stop_condition"],
                        rationale=nb["rationale"],
                        stop_loss_px=nb.get("stop_loss_px", 0),
                        take_profit_px=nb.get("take_profit_px", 0),
                        reduce_ratio=nb.get("reduce_ratio", 0),
                    )
                    branches.append(extra)
                output.bagua_meaning = (
                    output.bagua_meaning or ""
                ) + f" [多样性扩展: {[b['branch_id'] for b in diversity_report.new_branches]}]"
        except Exception:
            pass  # 多样性模块失败不影响主流程

        output.strategy_branches = branches

        # Step 7: 实践指令
        practice = self._step7_practice_directive(branches)
        output.practice_directive = practice

        # 设置哲学依据
        output.philosophy_basis = [
            PHIL_MAO_CONTRADICTION,
            PHIL_MATERIALIST_DIALECTIC,
            PHIL_HEGELIAN,
            PHIL_YIJING,
        ]

        # 不确定性
        output.uncertainty = 1.0 - next_state.confidence

        return output

    def _auto_generate_contradictions(self, market_snapshot: Dict[str, Any]) -> list:
        """从市场快照自动推导矛盾列表（Bug Y1 修复）。
        当调用方未提供 A0 矛盾列表时，从价格/RSI/资金费率等自动生成。
        """
        contras = []
        pct     = float(market_snapshot.get("price_change_pct", market_snapshot.get("ch24", 0)) or 0)
        rsi     = float(market_snapshot.get("rsi", market_snapshot.get("rsi14", 50)) or 50)
        funding = float(market_snapshot.get("funding_rate", 0) or 0)
        vol     = float(market_snapshot.get("volume_ratio", 1.0) or 1.0)

        if abs(pct) > 2:
            contras.append({"id": "AUTO_C1", "type": "trend_countertrend",
                            "dominant_side": "BULL" if pct > 0 else "BEAR",
                            "tension": min(abs(pct) / 20.0, 1.0)})
        if rsi > 70 or rsi < 30:
            contras.append({"id": "AUTO_C2", "type": "sentiment_fear_greed",
                            "dominant_side": "BEAR" if rsi > 70 else "BULL",
                            "tension": abs(rsi - 50) / 50.0})
        if abs(funding) > 0.0001:
            contras.append({"id": "AUTO_C3", "type": "supply_demand",
                            "dominant_side": "BEAR" if funding > 0 else "BULL",
                            "tension": min(abs(funding) * 5000, 1.0)})
        if vol > 1.5 and abs(pct) > 1:
            contras.append({"id": "AUTO_C4", "type": "volume_price",
                            "dominant_side": "BULL" if pct > 0 else "BEAR",
                            "tension": min(vol / 3.0, 1.0)})
        if not contras:
            contras.append({"id": "AUTO_C0", "type": "supply_demand",
                            "dominant_side": "EQUAL", "tension": 0.3})
        return contras

    def infer_with_adapter(self,
                           market_snapshot: Dict[str, Any],
                           contradiction_list: List[Dict] = None,
                           top_k: int = 5) -> BCRMOutput:
        """带记忆适配器的推理（简化版）。"""
        memory_cases = []
        # 这里可以接入 memory_adapter
        return self.infer(market_snapshot, contradiction_list, memory_cases)

    # ============================================================
    # Step 1: 矛盾识别
    # ============================================================
    def _step1_identify_contradiction(self,
                                      contradiction_list: List[Dict],
                                      market_snapshot: Dict) -> ContradictionState:
        """识别主要矛盾。"""
        primary = contradiction_list[0] if contradiction_list else {}

        primary_type = primary.get("type", primary.get("contradiction_type", "unknown"))
        primary_severity = primary.get("tension", primary.get("severity", 0.5))
        dominant_side = primary.get("dominant_side", "EQUAL")

        # 正题和反题
        thesis, antithesis = self._get_thesis_antithesis(
            primary_type, market_snapshot)

        return ContradictionState(
            thesis=thesis,
            antithesis=antithesis,
            dominant_side=dominant_side,
            tension=primary_severity,
            source_contradiction_id=primary.get("id", primary.get("contradiction_id", "")),
            philosophy_basis=[PHIL_MAO_CONTRADICTION],
        )

    def _get_thesis_antithesis(self,
                               contradiction_type: str,
                               market_snapshot: Dict) -> tuple:
        """获取正题和反题描述。"""
        thesis_map = {
            "supply_demand": ("需求旺盛，买方主导", "供应过剩，卖方主导"),
            "trend_countertrend": ("趋势延续，顺势者胜", "趋势反转，逆势者胜"),
            "sentiment_fear_greed": ("贪婪情绪主导，追涨", "恐惧情绪主导，杀跌"),
            "volume_price": ("量价配合，趋势健康", "量价背离，趋势存疑"),
        }
        return thesis_map.get(contradiction_type,
                              ("多方力量占优", "空方力量占优"))

    # ============================================================
    # Step 2: 张力量化
    # ============================================================
    def _step2_quantify_tension(self,
                                 contrad_state: ContradictionState,
                                 market_snapshot: Dict,
                                 memory_cases: List[Dict]) -> tuple:
        """量化矛盾张力和积累度。"""
        # 基础张力
        base_tension = contrad_state.tension

        # 从四维评分计算一致性
        sd = market_snapshot.get("supply_demand_score", 0.5)
        tech = market_snapshot.get("technical_score", 0.5)
        cf = market_snapshot.get("capital_flow_score", 0.5)
        sent = market_snapshot.get("sentiment_score", 0.5)

        scores = [sd, tech, cf, sent]
        avg_score = sum(scores) / len(scores)

        # 一致性 = 1 - 标准差
        variance = sum((s - avg_score) ** 2 for s in scores) / len(scores)
        consistency = 1.0 - min(variance, 1.0)

        # 张力 = 基础张力 * 一致性
        tension = base_tension * (0.5 + 0.5 * consistency)
        tension = max(0.0, min(1.0, tension))

        # 积累度：从记忆案例中计算
        accumulation = 0.5
        if memory_cases:
            # 将 dominant_side 映射为 direction 以便比较
            target_directions = set()
            if contrad_state.dominant_side == "BULL":
                target_directions = {"UP", "BULL", "BULLISH"}
            elif contrad_state.dominant_side == "BEAR":
                target_directions = {"DOWN", "BEAR", "BEARISH"}
            # 历史同向案例比例作为积累度
            same_dir_count = sum(
                1 for c in memory_cases
                if c.get("direction", "").upper() in target_directions
            )
            accumulation = same_dir_count / len(memory_cases)

        return tension, accumulation

    # ============================================================
    # Step 3: 质变判定
    # ============================================================
    def _step3_qualitative_change(self,
                                    tension: float,
                                    accumulation: float,
                                    memory_cases: List[Dict]) -> tuple:
        """判定是否发生质变。"""
        threshold = self.qualitative_threshold

        # 质变条件：高张力 + 高积累
        is_qualitative = (tension > TENSION_HIGH_THRESHOLD and accumulation > threshold)

        # 概率评估
        if is_qualitative:
            probability = "HIGH"
        elif tension > TENSION_MEDIUM_THRESHOLD or accumulation > threshold:
            probability = "MODERATE"
        else:
            probability = "LOW"

        trigger = TransformationTrigger(
            condition=f"张力>{tension:.2f} 且 积累度>{threshold:.2f}",
            probability=probability,
            accumulation=accumulation,
            threshold=threshold,
            monitoring_point="供需平衡 + 资金流向 + 成交量变化",
        )

        return is_qualitative, trigger

    # ============================================================
    # Step 4: 正反合裁决
    # ============================================================
    def _step4_synthesis(self,
                          contrad_state: ContradictionState,
                          is_qualitative_change: bool,
                          yijing_result,
                          memory_cases: List[Dict]) -> DialecticalStep:
        """正反合推理。"""
        thesis = {
            "side": "THESIS",
            "description": contrad_state.thesis,
            "strength": contrad_state.tension,
        }
        antithesis = {
            "side": "ANTITHESIS",
            "description": contrad_state.antithesis,
            "strength": 1.0 - contrad_state.tension,
        }

        # 合题
        if is_qualitative_change:
            synthesis = f"质变发生，矛盾转向：{yijing_result.overall_meaning[:50]}"
            adjudication = {
                "quantitative_change": False,
                "qualitative_change": True,
                "basis": "高张力 + 高积累 → 质变触发",
            }
        else:
            synthesis = f"量变延续，主导方保持：{yijing_result.overall_meaning[:50]}"
            adjudication = {
                "quantitative_change": True,
                "qualitative_change": False,
                "basis": "张力未达阈值 → 量变持续",
            }

        evidence = []
        if memory_cases:
            evidence = [c.get("case_id", "") for c in memory_cases[:3]]

        return DialecticalStep(
            thesis=thesis,
            antithesis=antithesis,
            synthesis=synthesis,
            adjudication=adjudication,
            evidence_refs=evidence,
        )

    def _yijing_to_hexagram_result(self, yijing_result) -> HexagramResult:
        """将 YijingResult 转换为 HexagramResult。"""
        yao_results = [y.to_dict() for y in yijing_result.yaos]

        return HexagramResult(
            hexagram_name=yijing_result.hexagram_name,
            hexagram_name_cn=yijing_result.hexagram_name_cn,
            inner_gua=yijing_result.inner_gua,
            outer_gua=yijing_result.outer_gua,
            gua_ci=yijing_result.gua_ci,
            tuan_zhuan="",
            xiang_zhuan=yijing_result.xiang_zhuan,
            yao_results=yao_results,
            changing_yaos=yijing_result.changing_yaos,
            changed_hexagram=yijing_result.changed_hexagram_name,
            changed_hexagram_cn=yijing_result.changed_hexagram_name_cn,
            overall_meaning=yijing_result.overall_meaning,
            direction_hint=yijing_result.direction_hint,
            confidence=yijing_result.confidence,
        )

    # ============================================================
    # 下一状态判定
    # ============================================================
    def _determine_next_state_from_force(self,
                                          force_result,
                                          is_qualitative_change: bool,
                                          tension: float) -> NextState:
        """
        从力学结果确定下一状态。

        第一性原理：方向 = sign(速度)，强度 = |速度|
        """
        direction = force_result.direction
        confidence = force_result.confidence

        # 质变时降低置信度
        if is_qualitative_change:
            confidence *= 0.9

        # 转折预警时降低置信度
        if force_result.reversal_warning:
            confidence *= 0.85

        # 推导说明（力学 + 卦象）
        direction_cn = {"UP": "上行", "DOWN": "下行",
                        "FLAT": "震荡", "TRANSITIONING": "转折中",
                        "UNKNOWN": "未知"}.get(direction, "未知")
        derivation = (
            f"力学推理：合力 {force_result.net_force.direction:+.2f}，"
            f"速度 {force_result.velocity:+.4f}，"
            f"加速度 {force_result.acceleration:+.4f} → "
            f"趋势{direction_cn}（强度 {force_result.trend_strength:.2f}）"
        )

        if force_result.reversal_warning:
            derivation += f"；转折预警：减速 {force_result.reversal_strength:.2f}"

        if is_qualitative_change:
            derivation += "；质变触发，趋势可能反转"

        # 时间跨度：从合力时间轴推断
        time_horizon = force_result.net_force.time_horizon
        if time_horizon > 0.8:
            horizon = "长期"
        elif time_horizon > 0.45:
            horizon = "中期"
        else:
            horizon = "短期"

        return NextState(
            direction=direction,
            confidence=max(0.0, min(1.0, confidence)),
            horizon=horizon,
            derivation=derivation,
        )

    # ============================================================
    # Step 5.5: 情景推演两路径（量变延续 vs 质变反转）
    # ============================================================
    def _step55_scenario_paths(self, next_state, trigger,
                                 spiral, yijing_result) -> tuple:
        """
        情景推演两路径（辩证阶段分叉）。

        路径 A（量变延续）：accumulation 继续积累，不达到 threshold，
                          当前趋势延续
        路径 B（质变反转）：accumulation 达到 threshold，发生质变，
                          趋势反转
        """
        is_qualitative = trigger.probability == "HIGH"
        accumulation = trigger.accumulation
        threshold = trigger.threshold

        # 路径 A：量变延续
        path_a = {
            "path_id": "A_QUANTITATIVE_CONTINUATION",
            "condition": f"accumulation < threshold ({accumulation:.2f} < {threshold:.2f})",
            "expected_direction": next_state.direction,
            "expected_horizon": next_state.horizon,
            "position_modifier": 1.0,
            "rationale": (
                f"量变延续：当前趋势（{next_state.direction}）保持，"
                f"卦象 {yijing_result.hexagram_name_cn} 支持延续。"
                f"积累度 {accumulation:.2f} 尚未达到阈值 {threshold:.2f}。"
            ),
            "monitoring_point": f"accumulation 达到 {threshold:.2f}",
            "probability": 1.0 - (accumulation / threshold) if threshold > 0 else 0.5,
        }

        # 路径 B：质变反转
        reverse_direction = self._reverse_direction(next_state.direction)
        path_b = {
            "path_id": "B_QUALITATIVE_REVERSAL",
            "condition": f"accumulation >= threshold ({accumulation:.2f} >= {threshold:.2f})",
            "expected_direction": reverse_direction,
            "expected_horizon": "短期" if is_qualitative else "中期",
            "position_modifier": 0.5,
            "rationale": (
                f"质变反转：趋势从 {next_state.direction} 转为 {reverse_direction}，"
                f"卦象 {yijing_result.hexagram_name_cn} 的变卦 "
                f"{yijing_result.changed_hexagram_name_cn} 预示反转。"
                f"积累度 {accumulation:.2f} {'已达' if is_qualitative else '接近'}阈值 {threshold:.2f}。"
            ),
            "monitoring_point": "卦象切换确认 + PnL 反转 3%",
            "probability": (accumulation / threshold) if threshold > 0 else 0.5,
        }

        return path_a, path_b

    def _reverse_direction(self, direction: str) -> str:
        """获取反向。"""
        if direction == DIR_UP:
            return DIR_DOWN
        elif direction == DIR_DOWN:
            return DIR_UP
        elif direction == DIR_FLAT:
            return DIR_TRANSITIONING
        return DIR_UNKNOWN

    # ============================================================
    # Step 5: 螺旋定位（三维度综合判据）
    # ============================================================
    def _step5_spiral_position(self,
                                memory_cases: List[Dict],
                                yijing_result,
                                price_position: float,
                                market_snapshot: Dict = None,
                                contradiction_state: ContradictionState = None) -> SpiralPosition:
        """
        否定之否定螺旋定位 — 三维度综合判据。

        三维度:
          1. 价格反转（40%）：从最近转折点反转幅度
          2. 矛盾主导方反转（35%）：主矛盾的主要方面切换
          3. 卦象翻转（25%）：八卦状态从阳卦翻转到阴卦或反之

        阈值 0.6：必须至少两个维度同时反转才能触发否定
        """
        # 记忆不足时降级
        if not memory_cases or len(memory_cases) < DEFAULT_MIN_MEMORY_CASES:
            return SpiralPosition(
                phase=SPIRAL_UNKNOWN,
                negation_count=0,
                historical_analogy_ref="",
            )

        # 从记忆案例中构建历史转折点
        last_turning_point = self._find_last_turning_point(memory_cases)

        if last_turning_point is None:
            # 无历史转折点，用 price_position 简化判定
            return self._spiral_fallback(price_position, memory_cases)

        # 三维度否定判定
        is_negation, negation_score = self._detect_negation(
            current_snapshot=market_snapshot or {},
            current_gua=yijing_result.outer_gua,
            current_dominant_side=(
                contradiction_state.dominant_side
                if contradiction_state else "EQUAL"
            ),
            last_turning_point=last_turning_point,
        )

        # 累计否定次数
        prev_negation_count = last_turning_point.get("negation_count", 0)
        if is_negation:
            negation_count = prev_negation_count + 1
        else:
            negation_count = prev_negation_count

        # 螺旋阶段判定
        phase = self._determine_spiral_stage(negation_count)

        historical_ref = ""
        if memory_cases:
            historical_ref = memory_cases[0].get("case_id", "")

        return SpiralPosition(
            phase=phase,
            negation_count=negation_count,
            historical_analogy_ref=historical_ref,
        )

    def _detect_negation(self,
                         current_snapshot: Dict,
                         current_gua: str,
                         current_dominant_side: str,
                         last_turning_point: Dict) -> tuple:
        """
        否定判定：综合三个维度判定是否发生"否定"。

        返回: (是否否定, 综合得分)
        """
        # 维度 1：价格反转（40%）
        cur_price = current_snapshot.get("price",
                                          current_snapshot.get("close", 0))
        prev_price = last_turning_point.get("price",
                                             last_turning_point.get("close", 0))
        if prev_price > 0:
            price_reversal = abs(cur_price - prev_price) / prev_price
            price_score = min(1.0, price_reversal / SPIRAL_PRICE_REVERSAL_FULL)
        else:
            price_score = 0.0
        price_score *= SPIRAL_WEIGHT_PRICE

        # 维度 2：矛盾主导方反转（35%）
        prev_dominant = last_turning_point.get("dominant_side", "EQUAL")
        contradiction_reversed = (current_dominant_side != prev_dominant
                                   and current_dominant_side != "EQUAL"
                                   and prev_dominant != "EQUAL")
        contradiction_score = (1.0 if contradiction_reversed else 0.0)
        contradiction_score *= SPIRAL_WEIGHT_CONTRADICTION

        # 维度 3：卦象翻转（25%）
        prev_gua = last_turning_point.get("bagua", "")
        cur_yin_yang = get_gua_yin_yang(current_gua) if current_gua else ""
        prev_yin_yang = get_gua_yin_yang(prev_gua) if prev_gua else ""
        gua_flipped = (cur_yin_yang != prev_yin_yang
                        and cur_yin_yang and prev_yin_yang)
        gua_score = (1.0 if gua_flipped else 0.0)
        gua_score *= SPIRAL_WEIGHT_GUA

        # 综合得分
        total_score = price_score + contradiction_score + gua_score
        is_negation = total_score >= SPIRAL_NEGATION_THRESHOLD

        return is_negation, total_score

    def _determine_spiral_stage(self, negation_count: int) -> str:
        """
        螺旋阶段判定（否定之否定规律）。

        阶段定义:
          FIRST_AFFIRMATION（正题）: 否定次数=0
          FIRST_NEGATION（反题）  : 否定次数=1
          SECOND_NEGATION（合题） : 否定次数=2

        超过 2 次: 重置，从 FIRST_AFFIRMATION 重新开始（螺旋下一圈）
        """
        if negation_count == 0:
            return SPIRAL_FIRST_AFFIRMATION
        elif negation_count == 1:
            return SPIRAL_FIRST_NEGATION
        elif negation_count == 2:
            return SPIRAL_SECOND_NEGATION
        else:
            return SPIRAL_FIRST_AFFIRMATION  # 螺旋下一圈

    def _find_last_turning_point(self, memory_cases: List[Dict]) -> Optional[Dict]:
        """从记忆案例中找到最近的转折点。"""
        for case in memory_cases:
            if case.get("dominant_side_switched") or case.get("gua_flipped"):
                return case
        return None

    def _spiral_fallback(self, price_position: float,
                          memory_cases: List[Dict]) -> SpiralPosition:
        """无历史转折点时的降级判定。"""
        if price_position < 0.3:
            phase = SPIRAL_FIRST_AFFIRMATION
            negation_count = 0
        elif price_position < 0.6:
            phase = SPIRAL_FIRST_NEGATION
            negation_count = 1
        else:
            phase = SPIRAL_SECOND_NEGATION
            negation_count = 2

        historical_ref = ""
        if memory_cases:
            historical_ref = memory_cases[0].get("case_id", "")

        return SpiralPosition(
            phase=phase,
            negation_count=negation_count,
            historical_analogy_ref=historical_ref,
        )

    # ============================================================
    # Step 6: 策略分支
    # ============================================================
    def _step6_strategy_branches(self,
                                  next_state: NextState,
                                  trigger: TransformationTrigger,
                                  spiral: SpiralPosition,
                                  yijing_result,
                                  price: float = 0,
                                  volatility: float = 0.5,
                                  confidence: float = 0.0,
                                  is_weak_signal: bool = False) -> List[StrategyBranch]:
        """生成策略分支（含结构化止损/止盈/减仓）。"""
        branches = []
        direction = next_state.direction
        vol = max(volatility, 0.01)

        # ── 根据方向和波动率计算止损止盈 ──
        # 止损幅度：波动率 × 系数（低波动更紧凑，高波动更宽松）
        sl_pct = min(vol * 2.0, 0.08)   # 止损最多 8%
        tp_pct = min(vol * 3.5, 0.15)   # 止盈最多 15%（盈亏比 ~1:1.75）

        # 置信度调整：低置信度更紧止损
        if confidence < 0.5:
            sl_pct *= 0.7
            tp_pct *= 0.8

        # P3修复: 弱信号时主路径轻仓（置信度分层传递到策略层）
        main_position_modifier = 0.5 if is_weak_signal else 1.0

        if direction == DIR_UP:
            sl_px = price * (1 - sl_pct) if price else 0
            tp_px = price * (1 + tp_pct) if price else 0
        elif direction == DIR_DOWN:
            sl_px = price * (1 + sl_pct) if price else 0
            tp_px = price * (1 - tp_pct) if price else 0
        else:
            sl_px = 0
            tp_px = 0

        # 主路径
        main_action = self._direction_to_action(direction)
        branches.append(StrategyBranch(
            branch_id="B1",
            condition="主趋势延续，质变未触发",
            action=main_action,
            position_modifier=main_position_modifier,
            stop_condition=f"质变触发（积累度>{trigger.threshold:.0%}）",
            rationale="顺势而为，沿主趋势操作",
            stop_loss_px=sl_px,
            take_profit_px=tp_px,
            reduce_ratio=0.0,
        ))

        # 对冲路径（质变触发）
        hedge_direction = DIR_DOWN if direction == DIR_UP else DIR_UP
        hedge_action = self._direction_to_action(hedge_direction)
        # B2 减仓 50%，止损更紧
        b2_sl_pct = sl_pct * 0.6  # 减仓后止损收紧
        if direction == DIR_UP:
            b2_sl_px = price * (1 - b2_sl_pct) if price else 0
        elif direction == DIR_DOWN:
            b2_sl_px = price * (1 + b2_sl_pct) if price else 0
        else:
            b2_sl_px = 0
        branches.append(StrategyBranch(
            branch_id="B2",
            condition=f"质变触发（积累度>{trigger.threshold:.0%}）",
            action=f"减仓50%，启动{hedge_action}对冲",
            position_modifier=0.5,
            stop_condition="趋势确认反转",
            rationale="质变发生 → 否定之否定启动，需对冲风险",
            stop_loss_px=b2_sl_px,
            take_profit_px=tp_px,  # 止盈不变
            reduce_ratio=0.5,
        ))

        # 螺旋路径（第二否定阶段）
        if spiral.phase == SPIRAL_SECOND_NEGATION:
            # B3 大幅减仓 70%，止损最紧
            b3_sl_pct = sl_pct * 0.4
            if direction == DIR_UP:
                b3_sl_px = price * (1 - b3_sl_pct) if price else 0
            elif direction == DIR_DOWN:
                b3_sl_px = price * (1 + b3_sl_pct) if price else 0
            else:
                b3_sl_px = 0
            branches.append(StrategyBranch(
                branch_id="B3",
                condition="螺旋第二否定阶段",
                action="警惕趋势加速反转，止损上移，减仓70%",
                position_modifier=0.3,
                stop_condition="破位止损",
                rationale="否定之否定第二环 → 螺旋将完成，变盘在即",
                stop_loss_px=b3_sl_px,
                take_profit_px=tp_px,
                reduce_ratio=0.7,
            ))

        return branches

    def _direction_to_action(self, direction: str) -> str:
        """方向转换为操作描述。"""
        action_map = {
            DIR_UP: "顺势做多",
            DIR_DOWN: "顺势做空",
            DIR_FLAT: "观望等待",
            DIR_TRANSITIONING: "轻仓试错",
            DIR_UNKNOWN: "观望",
        }
        return action_map.get(direction, "观望")

    # ============================================================
    # Step 7: 实践指令
    # ============================================================
    def _step7_practice_directive(self,
                                   branches: List[StrategyBranch]) -> PracticeDirective:
        """实践指令。"""
        main_branch = branches[0] if branches else StrategyBranch()

        return PracticeDirective(
            action=f"执行 {main_branch.branch_id} 主路径：{main_branch.action}",
            verification_condition="持仓24h内PnL波动不超过预期范围",
            feedback_loop="实践结果回写L4为新case，形成闭环",
            theory_practice_alignment_score=0.0,
        )


def default_engine() -> BCRMEngine:
    """获取默认引擎实例。"""
    return BCRMEngine()
