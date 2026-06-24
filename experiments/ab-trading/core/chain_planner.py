#!/usr/bin/env python3
"""
链路规划器 (ChainPlanner) — 零Token，纯本地计算

职责：夹在 IntentGateway 和 ChainRouter 之间，
过一遍技能清单，基于四个维度规划最优动态思维链路径：
  1. Token预算过滤：剪掉超预算的高成本节点
  2. 知识库命中提升：有高分策略时升级为快速路径
  3. 历史表现过滤：当前Regime+标的组合的节点命中率
  4. 标的覆盖检查：小币/冷门标的标记可能无数据的节点

输出 PlanResult：最优节点序列 + 剪枝记录 + 规划理由
（规划理由会写入图压缩节点，确保链路可追溯）
"""
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

REGISTRY_PATH  = Path(__file__).parent.parent / "data" / "skill_registry.md"
MEMORY_PATH    = Path(__file__).parent.parent / "data" / "agent_b_memory.json"
GRAPH_LOG      = Path(__file__).parent.parent / "data" / "agent_b_graph.json"
KNOWLEDGE_DIR  = Path("/Users/luke.zhang/dream-v2/6-TRADING/knowledge")
REGIME_DIR     = Path("/Users/luke.zhang/dream-v2/6-TRADING/sessions/regime_patterns")

# ── 节点成本表（Token估算，规划时用于预算校验）──────────────────────────
def _llm_quota_ok(purpose: str) -> bool:
    """预检 LLM 配额（无配额时节点回退规则，Token成本视为0）"""
    try:
        from core.llm_client import llm_quota_ok
        return llm_quota_ok(purpose)
    except Exception:
        return False


NODE_COST = {
    # 零成本节点
    "C1_技术扫描":          0,
    "F2_资金流":            0,
    "F3_情绪":              0,
    "F3_情绪确认":          0,
    "C2_Regime识别":        50,
    # 低成本节点
    "A2_分析(含A0)":        800,
    "A4_门禁":              100,
    "A7_实践记录":          200,
    "C3_策略匹配":          300,
    "C4_回测验证":          800,
    # 中等成本节点
    "A1_调研(含A0)":        2000,
    "A3_策略设计(含A0)":    1200,
    "A8_知行合一":          1000,
    "F1_新闻":              500,
    "F4_链上":              400,
    "F5_宏观":              500,
    "做梦部":               800,
    "C5_参数优化":          1500,
    # 高成本
    "A1修正":               2000,
}

# ── 主流动性标的（有较好数据覆盖的 Tavily/链上数据）──────────────────────
LIQUID_COINS = {"BTC", "ETH", "SOL", "BNB", "AVAX", "LINK", "MATIC"}
# 资金费率极端时有价值的节点
FUNDING_SENSITIVE_NODES = {"F2_资金流", "F3_情绪", "F3_情绪确认"}


@dataclass
class PlanResult:
    """规划器输出：最优链路 + 分析过程"""
    planned_chain:  List[str]         # 最终推荐节点序列
    pruned_nodes:   List[str]         # 被剪掉的节点及原因
    added_nodes:    List[str]         # 规划器主动追加的节点
    budget_mode:    str               # "full" / "standard" / "lean"
    estimated_tokens: int             # 预计消耗 Token
    plan_rationale: str               # 规划理由（写入图节点）
    knowledge_hit:  Optional[Dict]    # 命中的知识库策略（如有）
    shortcut_taken: bool = False      # 是否走了快捷路径


class ChainPlanner:
    """
    零Token链路规划器
    调用方式：
        planner = ChainPlanner(token_budget=6000)
        plan = planner.plan(intent, mkt, memory)
        # 把 plan.planned_chain 传给 ChainRouter
    """

    def __init__(self, token_budget: int = 6000):
        self.token_budget = token_budget
        self._skill_costs = NODE_COST.copy()

    # ── 主入口 ────────────────────────────────────────────────────────────

    def plan(self, intent, mkt: Dict, memory: Dict) -> PlanResult:
        """
        四维规划：预算 → 知识库 → 历史表现 → 标的覆盖
        全部本地计算，零 Token 消耗
        """
        coin    = mkt.get("coin", "BTC").upper()
        regime  = mkt.get("regime", "UNKNOWN")
        funding = mkt.get("funding_rate", 0)

        pruned  = []
        added   = []
        rationale_parts = [
            f"[Planner] 意图={intent.intent_type} conf={intent.confidence:.0%} "
            f"标的={coin} Regime={regime} 预算={self.token_budget}t"
        ]

        # 从意图层拿到基础链和扩展池
        chain = list(intent.base_chain)
        extend_pool = list(intent.extend_nodes)

        # ── 维度1：知识库命中检查（最高优先级）──────────────────────────
        kb_hit = self._check_knowledge_base(regime, coin)
        if kb_hit:
            score = kb_hit.get("score", 0)
            if score >= 80:
                # 高分命中 → 升级为快速路径，跳过 A1 调研
                original_a1_nodes = [n for n in chain if "A1" in n]
                for n in original_a1_nodes:
                    chain.remove(n)
                    pruned.append(f"{n}（知识库高分命中score={score}，跳过调研）")
                if "C3_策略匹配" not in chain:
                    chain.insert(0, "C3_策略匹配")
                    added.append("C3_策略匹配（知识库命中，前置策略匹配）")
                rationale_parts.append(f"[KB命中] score={score}，快速路径激活")
            elif score >= 60:
                # 中分命中 → 提示，但不改变路径
                rationale_parts.append(f"[KB参考] score={score}，保持原路径但有参考策略")

        # ── 维度2：Token预算过滤 ────────────────────────────────────────
        budget_mode, chain, extend_pool, pruned_budget = \
            self._apply_budget_filter(chain, extend_pool)
        pruned.extend(pruned_budget)
        rationale_parts.append(f"[预算] 模式={budget_mode}")

        # ── 维度3：历史表现过滤 ─────────────────────────────────────────
        chain, pruned_perf = self._apply_performance_filter(
            chain, regime, coin, memory
        )
        pruned.extend(pruned_perf)
        if pruned_perf:
            rationale_parts.append(f"[历史] 剪枝{len(pruned_perf)}个低效节点")

        # ── 维度4：标的覆盖检查 ─────────────────────────────────────────
        chain, added_coverage, pruned_coverage = \
            self._apply_coverage_check(chain, extend_pool, coin, funding)
        added.extend(added_coverage)
        pruned.extend(pruned_coverage)
        if added_coverage:
            rationale_parts.append(f"[覆盖] 追加{added_coverage}")
        if pruned_coverage:
            rationale_parts.append(f"[覆盖] 跳过{[p.split('（')[0] for p in pruned_coverage]}")

        # ── 计算预估 Token（LLM 配额不足时，相关节点成本降为0）──────────
        purpose_map = {
            "A3_策略设计(含A0)": "a3_seminar",
            "S2_A3大师研讨":     "a3_seminar",
            "A1_调研(含A0)":     "a1_research",
            "S1_A1深度调研":     "a1_research",
        }
        estimated = 0
        for n in chain:
            cost = self._skill_costs.get(n, 300)
            p = purpose_map.get(n)
            if p and not _llm_quota_ok(p):
                cost = 0   # 配额耗尽，走规则降级，不消耗Token预算
            estimated += cost

        return PlanResult(
            planned_chain    = chain,
            pruned_nodes     = pruned,
            added_nodes      = added,
            budget_mode      = budget_mode,
            estimated_tokens = estimated,
            plan_rationale   = " | ".join(rationale_parts),
            knowledge_hit    = kb_hit,
            shortcut_taken   = bool(kb_hit and kb_hit.get("score", 0) >= 80),
        )

    # ── 维度1：知识库命中 ────────────────────────────────────────────────

    def _check_knowledge_base(self, regime: str, coin: str) -> Optional[Dict]:
        """零Token：本地文件检索 regime_patterns + knowledge/strategy_scores"""
        # 检查 regime_patterns
        if REGIME_DIR.exists():
            for f in REGIME_DIR.glob("*.json"):
                try:
                    with open(f) as fp:
                        d = json.load(fp)
                    if isinstance(d, dict) and regime.lower() in f.stem.lower():
                        return {"source": "regime_pattern", "key": f.stem,
                                "score": d.get("score", 65), "data": d}
                except Exception:
                    pass

        # 检查 strategy_scores
        score_dir = Path("/Users/luke.zhang/dream-v2/6-TRADING/sessions/strategy_scores")
        if score_dir.exists():
            for f in sorted(score_dir.glob("*.json"), reverse=True)[:3]:
                try:
                    with open(f) as fp:
                        d = json.load(fp)
                    if coin in str(d) or regime.lower() in str(d).lower():
                        score = d.get("total_score", d.get("score", 50))
                        if score >= 60:
                            return {"source": "strategy_scores", "key": f.stem,
                                    "score": score, "data": d}
                except Exception:
                    pass
        return None

    # ── 维度2：预算过滤 ──────────────────────────────────────────────────

    def _apply_budget_filter(
        self, chain: List[str], extend_pool: List[str]
    ) -> Tuple[str, List[str], List[str], List[str]]:
        """根据 token_budget 决定预算模式，剪掉超出预算的节点"""
        pruned = []

        if self.token_budget >= 8000:
            # full 模式：基础链 + 扩展池全部保留
            mode = "full"
            combined = chain + extend_pool
        elif self.token_budget >= 4000:
            # standard 模式：基础链 + 低成本扩展
            mode = "standard"
            affordable_extend = [
                n for n in extend_pool
                if self._skill_costs.get(n, 500) <= 800
            ]
            pruned += [f"{n}（预算standard，成本>{800}t）"
                       for n in extend_pool if n not in affordable_extend]
            combined = chain + affordable_extend
        else:
            # lean 模式：只保留零/低成本基础节点
            mode = "lean"
            lean_chain = [
                n for n in chain
                if self._skill_costs.get(n, 999) <= 800
            ]
            pruned += [f"{n}（预算lean，成本>{800}t）"
                       for n in chain if n not in lean_chain]
            # 确保 A4_门禁 在 lean 模式也保留
            if "A4_门禁" not in lean_chain:
                lean_chain.append("A4_门禁")
            combined = lean_chain
            extend_pool = []

        return mode, combined, extend_pool, pruned

    # ── 维度3：历史表现过滤 ──────────────────────────────────────────────

    def _apply_performance_filter(
        self, chain: List[str], regime: str, coin: str, memory: Dict
    ) -> Tuple[List[str], List[str]]:
        """
        基于历史 Episode 数据评估各节点的实际价值
        如果某节点在当前 Regime+标的 下历史置信度贡献为负，标记为可剪枝
        """
        pruned = []
        recent = memory.get("recent_decisions", [])[-10:]

        # 统计各节点在当前 Regime 下的贡献
        # 简化：如果近期相同 regime 下 HOLD 率 > 80%，说明链路效果差，不剪节点但记录
        hold_rate = sum(1 for d in recent if d.get("action") == "HOLD"
                        and d.get("regime", "") == regime) / max(len(recent), 1)

        if hold_rate > 0.8 and len(recent) >= 5:
            # 高 HOLD 率但不剪节点，改为追加做梦部
            if "做梦部" not in chain:
                chain = chain + ["做梦部"]
                pruned.append("做梦部（追加：当前Regime HOLD率过高，需潜意识分析）")

        # 历史中从未成功贡献的节点：C5_参数优化 在短线交易中基本无用
        if "C5_参数优化" in chain and len(recent) < 30:
            chain = [n for n in chain if n != "C5_参数优化"]
            pruned.append("C5_参数优化（样本不足30笔，参数优化无统计意义）")

        return chain, pruned

    # ── 维度4：标的覆盖检查 ──────────────────────────────────────────────

    def _apply_coverage_check(
        self, chain: List[str], extend_pool: List[str],
        coin: str, funding: float
    ) -> Tuple[List[str], List[str], List[str]]:
        """
        检查当前标的对各节点的数据覆盖情况
        小币/冷门标的：F1新闻可能无结果，标记跳过
        资金费率极端：强制保留情绪节点
        """
        added  = []
        pruned = []

        is_liquid = coin in LIQUID_COINS
        funding_extreme = abs(funding) > 0.0005  # 极端资金费率

        # 小币 F1 新闻覆盖差，降低优先级（不剪，但标记为低优先）
        if not is_liquid and "F1_新闻" in chain:
            # 移到链路末尾（低优先级），而不是直接删除
            chain = [n for n in chain if n != "F1_新闻"] + ["F1_新闻"]
            pruned.append(f"F1_新闻（{coin}非主流币，降至低优先级）")

        # 资金费率极端时，强制保留情绪节点（即使 lean 模式也保留）
        if funding_extreme:
            for n in ["F2_资金流", "F3_情绪"]:
                if n not in chain:
                    chain = [n] + chain  # 前置
                    added.append(f"{n}（资金费率极端{funding*100:.4f}%，前置强制）")

        # BTC/ETH 等主流币，链上数据更可靠，可以追加 F4_链上
        if is_liquid and "F4_链上" not in chain and "F4_链上" in extend_pool:
            # 只在非 lean 模式且扩展池里有时追加
            added.append("F4_链上（主流币，链上数据有参考价值）")
            chain.append("F4_链上")

        return chain, added, pruned


# ── 快速测试 ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from core.intent_gateway import IntentResult

    # 模拟 IntentResult
    mock_intent = IntentResult(
        intent_type  = "TREND_FOLLOWING",
        confidence   = 0.60,
        base_chain   = ["C1_技术扫描", "F2_资金流", "F3_情绪", "A2_分析(含A0)", "A4_门禁"],
        extend_nodes = ["A3_策略设计(含A0)", "F1_新闻"],
        rationale    = "24H上涨5%，Regime=TREND_UP",
        context      = {},
    )
    mock_mkt = {
        "coin": "SOL", "regime": "TREND_UP",
        "funding_rate": 0.0001, "change_24h": 5.0,
    }
    mock_memory = {"recent_decisions": [], "loss_streaks": 0}

    planner = ChainPlanner(token_budget=6000)
    plan    = planner.plan(mock_intent, mock_mkt, mock_memory)

    print(f"模式:   {plan.budget_mode}")
    print(f"链路:   {plan.planned_chain}")
    print(f"剪枝:   {plan.pruned_nodes}")
    print(f"追加:   {plan.added_nodes}")
    print(f"Token:  ~{plan.estimated_tokens}")
    print(f"理由:   {plan.plan_rationale}")
    print(f"知识库: {plan.knowledge_hit}")
    print(f"快捷:   {plan.shortcut_taken}")
