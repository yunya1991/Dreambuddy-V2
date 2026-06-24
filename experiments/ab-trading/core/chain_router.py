#!/usr/bin/env python3
"""
动态思维链调度器 (Chain Router)
接收 IntentResult，按节点序列逐步执行，每步评估置信度
支持"一生二"：节点执行后置信度不足，动态插入扩展节点

核心原则：
- 框架（S链骨架）不变
- 内部实现（每个节点调用什么 SKILL）由此调度器动态决定
- 图压缩模块集成链骨架，记录 B/A/C 三层
"""
import json, time, requests, warnings
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path
from dataclasses import dataclass, field

warnings.filterwarnings("ignore")

GRAPH_LOG = Path(__file__).parent.parent / "data" / "agent_b_graph.json"
# 能力清单（节点注册表，可动态扩展，不修改代码）
REGISTRY  = Path(__file__).parent.parent / "data" / "skill_registry.md"
# 官方完整清单（PR #48，包含43个SKILL + 经典指标 + 基本面系统）
FULL_CHECKLIST = Path(__file__).parent.parent / "data" / "THREE_CHAIN_DISPATCH_CHECKLIST.md"


@dataclass
class NodeResult:
    node_id:    str
    confidence: float
    direction:  str        # LONG / SHORT / HOLD
    reasoning:  List[str]
    data:       Dict = field(default_factory=dict)
    skipped:    bool = False
    skip_reason: str = ""


@dataclass
class ChainResult:
    intent_type:  str
    final_action: str         # LONG / SHORT / HOLD
    final_confidence: float
    coin:         str
    leverage:     int
    node_trace:   List[NodeResult]
    gate_passed:  bool
    gate_reason:  str
    position_size_usdt: float
    stop_loss:    Optional[float]
    take_profit:  Optional[float]
    dynamic_nodes_added: List[str]   # 记录哪些节点是动态追加的


class ChainRouter:
    """
    动态思维链执行引擎
    根据 IntentResult 的 base_chain + extend_nodes，逐节点执行
    每个节点执行后判断是否需要继续追加（"一生二，二而三"）
    """

    def __init__(self, client, mkt: Dict, memory: Dict,
                 intent, budget_usdc: float = 60.0):
        self.client        = client
        self.mkt           = mkt
        self.memory        = memory
        self.intent        = intent
        self.budget_usdc   = budget_usdc
        self.node_trace:   List[NodeResult] = []
        self.dynamic_added: List[str] = []
        self._current_conf  = intent.confidence
        self._direction     = "HOLD"
        self._coin          = mkt.get("coin", "BTC")
        self._tavily_used   = 0   # Tavily 调用次数限制

    # ── 节点执行分发 ─────────────────────────────────────────────────────────

    def _run_node(self, node_id: str) -> NodeResult:
        """根据节点ID分发到对应的实现函数"""
        handlers = {
            # 技术/量化节点
            "C1_技术扫描":         self._node_c1_technical,
            "C2_Regime识别":       self._node_c2_regime,
            "C3_策略匹配":         self._node_c3_strategy,
            "C4_回测验证":         self._node_c4_backtest,
            # 执行环节点（A0内置于A2/A3，遵循三环架构）
            "A1_调研(含A0)":       self._node_a1_with_a0,   # A1深度调研 + A0矛盾检测
            "A2_分析(含A0)":       self._node_a2_with_a0,   # A2第一性原理 + A0矛盾排序
            "A3_策略设计(含A0)":   self._node_a3_with_a0,   # A3策略设计 + A0矛盾验证
            "A4_门禁":             self._node_a7_gate,       # A4战术验证门禁
            # 基本面节点
            "F2_资金流":           self._node_f2_fund_flow,
            "F3_情绪":             self._node_f3_sentiment,
            "F3_情绪确认":         self._node_f3_sentiment,
            "F1_新闻":             self._node_f1_news,
            "S1_F1新闻":           self._node_f1_news,
            "F5_宏观":             self._node_f5_macro,
            "S1_F5宏观":           self._node_f5_macro,
            # 治理环专用节点
            "A7_实践记录":         self._node_a7_gate,
            "A8_知行合一":         self._node_a8_verify,
            "做梦部":              self._node_oneirology,
            # 旧节点兼容（渐进迁移）
            "S2_A0矛盾":           self._node_a0_contradiction,
            "S2_A2原理":           self._node_a2_first_principles,
            "S2_A3大师研讨":       self._node_a3_seminar,
            "S4_A7门禁":           self._node_a7_gate,
            "S1_A1深度调研":       self._node_a1_research,
            "S2_A8理论验证":       self._node_a8_verify,
        }
        handler = handlers.get(node_id)
        if handler is None:
            return NodeResult(node_id, self._current_conf, self._direction,
                              [f"节点 {node_id} 未实现，跳过"], skipped=True,
                              skip_reason="未实现")
        return handler(node_id)

    # ── 主执行流程 ────────────────────────────────────────────────────────────

    def execute(self) -> ChainResult:
        """执行完整链路，返回最终决策"""
        nodes_to_run = list(self.intent.base_chain)
        extend_pool  = list(self.intent.extend_nodes)
        extend_injected = False

        for node_id in nodes_to_run:
            result = self._run_node(node_id)
            self.node_trace.append(result)
            self._current_conf = result.confidence
            if result.direction != "HOLD":
                self._direction = result.direction

            # "一生二"：置信度不足，且扩展节点未注入 → 动态插入
            if (not extend_injected and result.confidence < 0.65
                    and extend_pool and node_id != "S4_A7门禁"):
                inject = extend_pool[:2]  # 最多插入2个
                idx = nodes_to_run.index(node_id) + 1
                for n in reversed(inject):
                    if n not in nodes_to_run:
                        nodes_to_run.insert(idx, n)
                        self.dynamic_added.append(n)
                extend_injected = True

        # 读取 A7 门禁结果
        gate_result = next((r for r in reversed(self.node_trace)
                            if "A7" in r.node_id or "A4_门禁" in r.node_id), None)
        gate_passed = gate_result.data.get("gate_passed", False) if gate_result else False
        gate_reason = gate_result.data.get("reason", "未执行A7") if gate_result else "未执行A7"

        # 仓位计算
        pos_usdt = 0.0
        sl = tp = None
        if gate_passed:
            equity = min(self.budget_usdc, 60.0)
            pos_usdt = max(round(equity * 0.05, 2), 5.0)
            px = self.mkt.get("price", 0)
            if self._direction == "LONG":
                sl = round(px * 0.96, 4)
                tp = round(px * 1.08, 4)
            elif self._direction == "SHORT":
                sl = round(px * 1.04, 4)
                tp = round(px * 0.92, 4)

        leverage = min(5, max(1, int(self._current_conf * 5)))

        # 记录图压缩节点
        self._record_graph(gate_passed, pos_usdt)

        return ChainResult(
            intent_type       = self.intent.intent_type,
            final_action      = self._direction if gate_passed else "HOLD",
            final_confidence  = round(self._current_conf, 3),
            coin              = self._coin,
            leverage          = leverage,
            node_trace        = self.node_trace,
            gate_passed       = gate_passed,
            gate_reason       = gate_reason,
            position_size_usdt= pos_usdt,
            stop_loss         = sl,
            take_profit       = tp,
            dynamic_nodes_added = self.dynamic_added,
        )

    # ── 节点实现 ─────────────────────────────────────────────────────────────

    # ── 三环架构节点（A0内置版）─────────────────────────────────────────

    def _node_a1_with_a0(self, node_id: str) -> NodeResult:
        """A1深度调研 + A0矛盾检测内置（执行环入口节点）"""
        # Step1: A0矛盾检测（内置）
        a0_result = self._node_a0_contradiction("A0内置@A1")
        reasoning = [f"[A1-A0内置] 矛盾检测: {a0_result.direction} conf={a0_result.confidence:.0%}"]
        # Step2: A1调研（Tavily，按预算）
        a1_result = self._node_a1_research(node_id)
        if not a1_result.skipped:
            # A0矛盾方向与A1调研方向融合
            if a0_result.direction != "HOLD" and a1_result.direction != "HOLD":
                merged_dir = a0_result.direction if a0_result.confidence > a1_result.confidence else a1_result.direction
                merged_conf = round((a0_result.confidence + a1_result.confidence) / 2, 3)
            else:
                merged_dir  = a1_result.direction if a1_result.direction != "HOLD" else a0_result.direction
                merged_conf = max(a0_result.confidence, a1_result.confidence)
            reasoning += a1_result.reasoning
        else:
            merged_dir  = a0_result.direction
            merged_conf = a0_result.confidence
            reasoning.append("[A1跳过，使用A0矛盾结论]")
        self._coin = self.mkt.get("coin", self._coin)
        return NodeResult(node_id, merged_conf, merged_dir, reasoning,
                          {"a0": a0_result.data.get("a0", {}), "a1_skipped": a1_result.skipped})

    def _node_a2_with_a0(self, node_id: str) -> NodeResult:
        """A2第一性原理 + A0矛盾排序内置（执行环核心分析节点）"""
        # Step1: A0矛盾排序（内置，使用前序A0数据或重新计算）
        a0_data = next(
            (r.data.get("a0", {}) for r in self.node_trace if "A0" in r.node_id or "A1" in r.node_id),
            None
        )
        if a0_data is None:
            a0_result = self._node_a0_contradiction("A0内置@A2")
            a0_data   = a0_result.data.get("a0", {})
            a0_dir    = a0_result.direction
        else:
            a0_dir = "LONG" if a0_data.get("dominant_force") == "BULL" else \
                     "SHORT" if a0_data.get("dominant_force") == "BEAR" else "HOLD"
        # Step2: A2第一性原理（阻力最小路径）
        a2_result = self._node_a2_first_principles(node_id)
        # 融合：A0矛盾方向 + A2阻力分析
        if a0_dir != "HOLD" and a2_result.direction != "HOLD":
            if a0_dir == a2_result.direction:
                # 同向：置信度加成
                final_conf = min(a2_result.confidence + 0.05, 0.90)
                reasoning  = [f"[A2-A0内置] 矛盾方向与阻力方向一致: {a0_dir}，置信度加成"] + a2_result.reasoning
            else:
                # 冲突：降低置信度
                final_conf = max(a2_result.confidence - 0.08, 0.30)
                reasoning  = [f"[A2-A0内置] ⚠️ 矛盾({a0_dir}) vs 阻力({a2_result.direction}) 冲突，降低置信度"] + a2_result.reasoning
        else:
            final_conf = a2_result.confidence
            reasoning  = [f"[A2-A0内置] A0={a0_dir}"] + a2_result.reasoning
        return NodeResult(node_id, final_conf, a2_result.direction, reasoning,
                          {"a0": a0_data, "a2": a2_result.data.get("a2", {})})

    def _node_a3_with_a0(self, node_id: str) -> NodeResult:
        """A3策略设计 + A0矛盾验证内置（策略一致性检查）"""
        # Step1: 运行A3大师研讨
        a3_result = self._node_a3_seminar(node_id)
        # Step2: A0矛盾一致性校验（内置）
        a0_data = next(
            (r.data.get("a0", {}) for r in self.node_trace if "A0" in r.node_id or "A2" in r.node_id),
            {}
        )
        dom = a0_data.get("dominant_force", "NEUTRAL")
        direction = a3_result.direction
        # 策略方向与矛盾主导方向一致性检查
        consistent = (dom == "BULL" and direction in ("LONG", "BUY")) or \
                     (dom == "BEAR" and direction in ("SHORT", "SELL")) or \
                     dom == "NEUTRAL" or direction == "HOLD"
        if consistent:
            adj_conf = a3_result.confidence
            note = f"[A3-A0校验] 策略{direction}与矛盾{dom}一致 ✓"
        else:
            adj_conf = round(a3_result.confidence * 0.85, 3)
            note = f"[A3-A0校验] ⚠️ 策略{direction}与矛盾{dom}不一致，置信度折扣"
        return NodeResult(node_id, adj_conf, direction,
                          [note] + a3_result.reasoning,
                          {"a3": a3_result.data.get("a3", {}), "consistent": consistent})

    # ── 原始单节点实现（供兼容和内部调用）────────────────────────────────

    def _node_c1_technical(self, node_id: str) -> NodeResult:
        """C1：本地技术扫描（零Token）"""
        mkt = self.mkt
        price  = mkt.get("price", 0)
        ema20  = mkt.get("ema20", price)
        ema50  = mkt.get("ema50", price)
        ema200 = mkt.get("ema200", price)
        rsi    = mkt.get("rsi14", 50)
        ch24   = mkt.get("change_24h", 0)
        ch4h   = mkt.get("change_4h", 0)
        vr     = mkt.get("vol_ratio", 1.0)

        reasoning = [f"C1技术扫描: price={price:.2f} RSI={rsi:.1f} vol={vr:.1f}x"]

        # EMA排列判断
        if price > ema20 > ema50 > ema200:
            direction = "LONG"; conf = 0.65; reasoning.append("EMA强多排列")
        elif price < ema20 < ema50 < ema200:
            direction = "SHORT"; conf = 0.65; reasoning.append("EMA强空排列")
        elif price > ema200:
            direction = "LONG"; conf = 0.55; reasoning.append("价格在MA200上方")
        elif price < ema200:
            direction = "SHORT"; conf = 0.55; reasoning.append("价格在MA200下方")
        else:
            direction = "HOLD"; conf = 0.45; reasoning.append("技术面方向不明")

        # 量比修正
        if vr > 1.5 and direction != "HOLD":
            conf = min(conf + 0.05, 0.85); reasoning.append(f"量比{vr:.1f}x加成")

        self._coin = self.mkt.get("coin", "BTC")
        return NodeResult(node_id, conf, direction, reasoning,
                          {"ema20": ema20, "ema50": ema50, "rsi": rsi})

    def _node_c2_regime(self, node_id: str) -> NodeResult:
        """C2：市场状态识别（低Token）"""
        regime = self.mkt.get("regime", "UNKNOWN")
        ch24   = self.mkt.get("change_24h", 0)
        rsi    = self.mkt.get("rsi14", 50)

        if "TREND" in regime or abs(ch24) > 3:
            direction = "LONG" if ch24 > 0 else "SHORT"
            conf = 0.65
        elif "RANGE" in regime or abs(ch24) < 1.5:
            direction = "HOLD"; conf = 0.50
        else:
            direction = "HOLD"; conf = 0.45

        return NodeResult(node_id, conf, direction,
                          [f"C2 Regime={regime}, 24H={ch24:+.1f}%"],
                          {"regime": regime})

    def _node_c3_strategy(self, node_id: str) -> NodeResult:
        """C3：知识库策略匹配（零Token）"""
        from core.intent_gateway import _check_knowledge_match
        regime = self.mkt.get("regime", "UNKNOWN")
        km = _check_knowledge_match(regime, self._coin)
        if km and km.get("score", 0) >= 70:
            conf = km["score"] / 100
            return NodeResult(node_id, conf, self._direction,
                              [f"C3 知识库命中: {km['key']} score={km['score']}"],
                              {"match": km})
        return NodeResult(node_id, self._current_conf, self._direction,
                          ["C3 知识库无高分匹配，沿用当前方向"])

    def _node_c4_backtest(self, node_id: str) -> NodeResult:
        """C4：简化回测验证（本地历史数据）"""
        # 简化：检查本地 sessions/strategy_scores
        scores_dir = Path("/Users/luke.zhang/dream-v2/6-TRADING/sessions/strategy_scores")
        if scores_dir.exists():
            files = list(scores_dir.glob("*.json"))
            if files:
                try:
                    with open(files[-1]) as f:
                        data = json.load(f)
                    score = data.get("total_score", 50)
                    conf = score / 100
                    return NodeResult(node_id, conf, self._direction,
                                      [f"C4 历史评分={score}"], {"score": score})
                except Exception:
                    pass
        return NodeResult(node_id, self._current_conf, self._direction,
                          ["C4 无回测数据，维持当前置信度"])

    def _node_a0_contradiction(self, node_id: str) -> NodeResult:
        """A0：7维矛盾识别（内置逻辑，低Token）"""
        from agents.agent_b_runner import a0_contradiction_analysis
        a0 = a0_contradiction_analysis(self.mkt, self.memory)
        dom = a0.get("dominant_force", "NEUTRAL")
        bull = a0.get("bull_count", 0)
        bear = a0.get("bear_count", 0)
        primary = a0.get("primary_contradiction", {})

        if dom == "BULL":
            direction = "LONG"; conf = 0.55 + min(bull * 0.05, 0.20)
        elif dom == "BEAR":
            direction = "SHORT"; conf = 0.55 + min(bear * 0.05, 0.20)
        else:
            direction = "HOLD"; conf = 0.45

        reasoning = [
            f"A0矛盾论: {dom} 多{bull}空{bear}冲突{a0.get('conflict_count',0)}",
            f"主要矛盾: {primary.get('dim','?')}({primary.get('name','?')})"
        ]
        return NodeResult(node_id, conf, direction, reasoning,
                          {"a0": a0, "dominant": dom})

    def _node_a2_first_principles(self, node_id: str) -> NodeResult:
        """A2：第一性原理（阻力最小路径，低Token）"""
        from agents.agent_b_runner import a2_first_principles
        a0_data = next(
            (r.data.get("a0", {}) for r in self.node_trace if "A0" in r.node_id), {}
        )
        if not a0_data:
            # A0未运行，构造简单替代
            a0_data = {"dominant_force": "NEUTRAL", "bull_count": 0,
                       "bear_count": 0, "conflict_count": 0, "contradictions": []}

        a2 = a2_first_principles(self.mkt, a0_data)
        direction = a2.get("direction", "HOLD")
        conf      = a2.get("confidence", 0.5)
        trend     = a2.get("trend", "RANGE")

        reasoning = a2.get("reasoning", [])[:4]
        reasoning.insert(0, f"A2原理: {direction} conf={conf:.0%} trend={trend}")
        return NodeResult(node_id, conf, direction, reasoning,
                          {"a2": a2, "trend": trend})

    def _node_a3_seminar(self, node_id: str) -> NodeResult:
        """A3：大师研讨（三视角投票，中Token）"""
        from agents.agent_b_runner import a3_master_seminar
        # 取前序 A0/A2 数据
        a0_data = next(
            (r.data.get("a0", {}) for r in self.node_trace if "A0" in r.node_id),
            {"dominant_force": "NEUTRAL", "bull_count": 0, "bear_count": 0,
             "conflict_count": 0, "contradictions": []}
        )
        a2_data = next(
            (r.data.get("a2", {}) for r in self.node_trace if "A2" in r.node_id),
            {"direction": self._direction, "confidence": self._current_conf,
             "trend": "RANGE", "trend_score": 0.5}
        )
        a3 = a3_master_seminar(self.mkt, a0_data, a2_data)
        verdict  = a3.get("verdict", "HOLD")
        conf_adj = a3.get("confidence_adj", 0)
        new_conf = round(min(max(self._current_conf + conf_adj, 0), 1), 3)

        action = verdict if verdict != "HOLD" else self._direction
        votes = f"多{a3['buy_votes']}/空{a3['sell_votes']}/观望{a3['hold_votes']}"
        return NodeResult(node_id, new_conf, action,
                          [f"A3大师研讨: {verdict} 投票={votes} 修正{conf_adj:+.0%}"],
                          {"a3": a3, "conf_adj": conf_adj})

    def _node_a7_gate(self, node_id: str) -> NodeResult:
        """A7：置信度门禁（极低Token）"""
        from agents.agent_b_runner import a7_gate, apply_lessons
        gate_threshold = apply_lessons(self.memory)
        gate_pass, reason = a7_gate(self._current_conf, self._direction,
                                    gate_threshold, self.memory)
        if not gate_pass:
            return NodeResult(node_id, self._current_conf, "HOLD",
                              [f"A7门禁: ❌ {reason}"],
                              {"gate_passed": False, "reason": reason})
        return NodeResult(node_id, self._current_conf, self._direction,
                          [f"A7门禁: ✅ {reason}"],
                          {"gate_passed": True, "reason": reason})

    def _node_a8_verify(self, node_id: str) -> NodeResult:
        """A8：知行合一验证（治理环核心）
        计算 gap_score，路由后续修正深度
        """
        loss_streaks = self.memory.get("loss_streaks", 0)
        lessons      = self.memory.get("lessons", [])
        recent       = self.memory.get("recent_decisions", [])[-5:]
        reasoning    = [f"A8知行合一: 连败={loss_streaks} lessons={len(lessons)}"]

        # gap_score：理论预期 vs 实际结果的偏差程度
        # 简化计算：连败轮次+置信度偏差
        gap_score = min(loss_streaks * 0.15, 0.80)
        if gap_score >= 0.5:
            route = "A1重启调研"
        elif gap_score >= 0.3:
            route = "A2更新分析"
        elif gap_score >= 0.1:
            route = "A3优化策略"
        else:
            route = "继续"
        reasoning.append(f"gap_score={gap_score:.2f} → 路由: {route}")

        # 连败惩罚
        penalty  = min(loss_streaks * 0.05, 0.20)
        new_conf = round(self._current_conf - penalty, 3)
        return NodeResult(node_id, new_conf, self._direction, reasoning,
                          {"penalty": penalty, "gap_score": gap_score, "route": route})

    def _node_oneirology(self, node_id: str) -> NodeResult:
        """做梦部：弗洛伊德梦的解析，潜意识分析（每日1次/连败≥3触发）
        不受门禁约束，专门发现系统"不敢说的判断"
        Token成本：中等，但产出高价值反思
        """
        loss_streaks  = self.memory.get("loss_streaks", 0)
        recent        = self.memory.get("recent_decisions", [])[-10:]
        reasoning     = ["[做梦部] 弗洛伊德梦的解析启动"]

        # 强迫性重复检测：连续HOLD且同原因
        hold_streak = sum(1 for d in recent if d.get("action") == "HOLD")
        if hold_streak >= 3:
            reasoning.append(f"⚠️ [强迫性重复] 连续{hold_streak}次HOLD，系统在回避什么？")
            # 反事实推演：如果门禁不存在会怎样
            reasoning.append(f"[反事实] 若A7门禁不存在，系统会: {self._direction}（当前置信度{self._current_conf:.0%}）")
            # 检测移置：是否一直引用相同原因
            reasons = [d.get("decision_rationale", "")[:30] for d in recent[-3:]]
            if len(set(reasons)) == 1 and reasons[0]:
                reasoning.append(f"[移置检测] ⚠️ 连续引用同一原因: '{reasons[0]}'，可能存在恐惧移置")

        # 凝缩检测：从最近决策提取被压制的维度
        if self._current_conf > 0.55 and self._direction != "HOLD":
            reasoning.append(f"[潜意识信号] 系统有{self._current_conf:.0%}置信度但被门禁压制")
            reasoning.append(f"[做梦部建议] 当前方向{self._direction}可能值得关注，建议降低门槛至60%试探")
            # 做梦部可以轻微提升置信度（它代表被压制的判断）
            boosted = min(self._current_conf + 0.05, 0.80)
            return NodeResult(node_id, boosted, self._direction, reasoning,
                              {"oneirology": True, "hold_streak": hold_streak,
                               "boosted": boosted - self._current_conf})

        reasoning.append(f"[做梦部] 无强烈潜意识信号，系统判断基本自洽")
        return NodeResult(node_id, self._current_conf, self._direction, reasoning,
                          {"oneirology": True, "hold_streak": hold_streak})

    def _node_f2_fund_flow(self, node_id: str) -> NodeResult:
        """F2：资金费率+链上资金流（零Token，API读取）"""
        funding = self.mkt.get("funding_rate", 0)
        reasoning = [f"F2资金流: 资金费率={funding*100:.4f}%"]
        conf = self._current_conf

        if funding > 0.0003:
            reasoning.append("多头拥挤，警惕逆向"); conf = min(conf, 0.60)
        elif funding < -0.0003:
            reasoning.append("空头拥挤，关注做多机会"); conf = min(conf + 0.05, 0.85)
        else:
            reasoning.append("资金费率中性")

        return NodeResult(node_id, conf, self._direction, reasoning,
                          {"funding": funding})

    def _node_f3_sentiment(self, node_id: str) -> NodeResult:
        """F3：情绪面（资金费率+RSI综合，零Token）"""
        rsi     = self.mkt.get("rsi14", 50)
        funding = self.mkt.get("funding_rate", 0)
        conf    = self._current_conf
        reasoning = [f"F3情绪: RSI={rsi:.1f} 资金费率={funding*100:.4f}%"]

        if rsi < 25 and funding < -0.0001:
            reasoning.append("双重超卖：强反弹信号")
            conf = min(conf + 0.10, 0.85)
            direction = "LONG"
        elif rsi > 75 and funding > 0.0003:
            reasoning.append("双重超买：注意回调")
            conf = min(conf, 0.55)
            direction = "SHORT"
        else:
            direction = self._direction

        return NodeResult(node_id, conf, direction, reasoning)

    def _node_f1_news(self, node_id: str) -> NodeResult:
        """F1：Tavily新闻搜索（有Token成本，限2次/轮）"""
        if self._tavily_used >= 2:
            return NodeResult(node_id, self._current_conf, self._direction,
                              ["F1新闻: Tavily预算已用完，跳过"],
                              skipped=True, skip_reason="budget_exceeded")

        import os
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent.parent / "config" / ".env")
        api_key = os.environ.get("TAVILY_API_KEY", "")
        if not api_key:
            return NodeResult(node_id, self._current_conf, self._direction,
                              ["F1新闻: 未配置TAVILY_API_KEY"],
                              skipped=True, skip_reason="no_api_key")
        try:
            s = requests.Session(); s.trust_env = False
            r = s.post("https://api.tavily.com/search", json={
                "api_key": api_key,
                "query":   f"crypto {self._coin} news today market",
                "search_depth": "basic", "max_results": 3,
            }, timeout=10)
            results = r.json().get("results", [])
            self._tavily_used += 1
            summaries = [res.get("title", "")[:60] for res in results[:2]]
            return NodeResult(node_id, self._current_conf, self._direction,
                              [f"F1新闻({self._coin}): " + " | ".join(summaries) if summaries else "F1: 无重要新闻"],
                              {"news": summaries})
        except Exception as e:
            return NodeResult(node_id, self._current_conf, self._direction,
                              [f"F1新闻: 查询失败 {e}"], skipped=True, skip_reason=str(e))

    def _node_f5_macro(self, node_id: str) -> NodeResult:
        """F5：宏观扫描（Tavily，限用）"""
        if self._tavily_used >= 2:
            return NodeResult(node_id, self._current_conf, self._direction,
                              ["F5宏观: Tavily预算已用完，跳过"],
                              skipped=True, skip_reason="budget_exceeded")

        import os
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent.parent / "config" / ".env")
        api_key = os.environ.get("TAVILY_API_KEY", "")
        if not api_key:
            return NodeResult(node_id, self._current_conf, self._direction,
                              ["F5宏观: 未配置API"], skipped=True, skip_reason="no_api_key")
        try:
            s = requests.Session(); s.trust_env = False
            r = s.post("https://api.tavily.com/search", json={
                "api_key": api_key,
                "query":   "Fed interest rate DXY crypto impact today",
                "search_depth": "basic", "max_results": 2,
            }, timeout=10)
            results = r.json().get("results", [])
            self._tavily_used += 1
            summaries = [res.get("title", "")[:60] for res in results[:2]]
            return NodeResult(node_id, self._current_conf, self._direction,
                              ["F5宏观: " + " | ".join(summaries) if summaries else "F5宏观: 无重大宏观事件"],
                              {"macro": summaries})
        except Exception as e:
            return NodeResult(node_id, self._current_conf, self._direction,
                              [f"F5宏观: {e}"], skipped=True, skip_reason=str(e))

    def _node_a1_research(self, node_id: str) -> NodeResult:
        """A1：深度市场调研（Tavily，高成本，仅UNCERTAIN时用）"""
        if self._tavily_used >= 2:
            return NodeResult(node_id, self._current_conf, self._direction,
                              ["A1调研: Tavily预算已用完，跳过"],
                              skipped=True, skip_reason="budget_exceeded")

        import os
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent.parent / "config" / ".env")
        api_key = os.environ.get("TAVILY_API_KEY", "")
        if not api_key:
            return NodeResult(node_id, self._current_conf, self._direction,
                              ["A1调研: 未配置API"], skipped=True, skip_reason="no_api_key")
        try:
            s = requests.Session(); s.trust_env = False
            r = s.post("https://api.tavily.com/search", json={
                "api_key": api_key,
                "query":   f"{self._coin} crypto market analysis trend 2026",
                "search_depth": "advanced", "max_results": 5,
            }, timeout=12)
            results = r.json().get("results", [])
            self._tavily_used += 1
            summaries = [res.get("title", "")[:60] for res in results[:3]]
            # 简单情感判断（标题中有利好/利空词）
            bullish_kw = ["rally", "surge", "bullish", "up", "gain", "break"]
            bearish_kw = ["drop", "fall", "bearish", "down", "crash", "dump"]
            bull_cnt = sum(1 for t in summaries for w in bullish_kw if w in t.lower())
            bear_cnt = sum(1 for t in summaries for w in bearish_kw if w in t.lower())
            if bull_cnt > bear_cnt:
                new_conf = min(self._current_conf + 0.08, 0.85)
                direction = "LONG"
                note = f"新闻偏多({bull_cnt}多/{bear_cnt}空)"
            elif bear_cnt > bull_cnt:
                new_conf = min(self._current_conf + 0.08, 0.85)
                direction = "SHORT"
                note = f"新闻偏空({bear_cnt}空/{bull_cnt}多)"
            else:
                new_conf = self._current_conf
                direction = self._direction
                note = "新闻中性"
            return NodeResult(node_id, new_conf, direction,
                              [f"A1深度调研({self._coin}): {note}"] + summaries[:2],
                              {"news": summaries, "bull": bull_cnt, "bear": bear_cnt})
        except Exception as e:
            return NodeResult(node_id, self._current_conf, self._direction,
                              [f"A1调研: {e}"], skipped=True, skip_reason=str(e))

    # ── 图压缩记录 ───────────────────────────────────────────────────────────

    def _record_graph(self, gate_passed: bool, pos_usdt: float):
        """B/A/C 三层图节点写入"""
        existing = []
        if GRAPH_LOG.exists():
            try:
                with open(GRAPH_LOG) as f:
                    existing = json.load(f)
            except Exception:
                pass

        entry = {
            "ts":      __import__("datetime").datetime.utcnow().isoformat(),
            "B_layer": {
                "objective":    f"{self.intent.intent_type} @ {self._coin}",
                "regime":       self.mkt.get("regime", "?"),
                "intent_conf":  self.intent.confidence,
            },
            "A_layer": [
                {"node": r.node_id, "conf": r.confidence, "dir": r.direction,
                 "skipped": r.skipped}
                for r in self.node_trace
            ],
            "C_layer": {
                "action":     self._direction if gate_passed else "HOLD",
                "confidence": self._current_conf,
                "gate_passed": gate_passed,
                "pos_usdt":   pos_usdt,
                "dynamic_added": self.dynamic_added,
            },
        }

        existing.append(entry)
        existing = existing[-50:]
        GRAPH_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(GRAPH_LOG, "w") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
