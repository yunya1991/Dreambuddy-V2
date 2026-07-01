#!/usr/bin/env python3
"""
意图识别层 (Intent Gateway)
读取：市场数据 + 本地记忆 + 知识库命中 + 外部信号
输出：IntentResult（意图类型 + 推荐链路 + 置信度 + 上下文）

意图类型与 skill_registry.md 的映射保持一致
"""
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

REGISTRY_PATH = Path(__file__).parent.parent / "data" / "skill_registry.md"
MEMORY_PATH   = Path(__file__).parent.parent / "data" / "agent_b_memory.json"
GRAPH_LOG     = Path(__file__).parent.parent / "data" / "agent_b_graph.json"


@dataclass
class IntentResult:
    intent_type: str          # TREND_FOLLOWING / MEAN_REVERSION / FUNDAMENTAL_PLAY / BREAKOUT / UNCERTAIN / KNOWLEDGE_MATCH
    confidence: float         # 0-1，意图识别本身的置信度
    base_chain: List[str]     # 必走节点，e.g. ["S2_A0", "S2_A2", "S4_A7", "S5"]
    extend_nodes: List[str]   # 按需追加节点
    rationale: str            # 为什么识别为这个意图
    context: Dict = field(default_factory=dict)  # 传递给链路的上下文（知识库命中、历史教训等）


def _load_memory() -> Dict:
    if MEMORY_PATH.exists():
        try:
            with open(MEMORY_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    return {"lessons": [], "recent_decisions": [], "loss_streaks": 0, "last_regime": None}


def _load_graph_context() -> List[Dict]:
    """读取最近图压缩记录，提取历史意图和执行结果"""
    if not GRAPH_LOG.exists():
        return []
    try:
        with open(GRAPH_LOG) as f:
            entries = json.load(f)
        return entries[-5:]  # 最近5轮
    except Exception:
        return []


def _check_knowledge_match(market_regime: str, coin: str) -> Optional[Dict]:
    """
    零Token：查本地知识库和regime_patterns是否有高分匹配策略
    返回匹配到的策略信息，或 None
    """
    regime_dir = Path("/Users/luke.zhang/dream-v2/6-TRADING/sessions/regime_patterns")
    knowledge_dir = Path("/Users/luke.zhang/dream-v2/6-TRADING/knowledge")

    # 简单文件匹配（无需 Token）
    patterns = {}
    if regime_dir.exists():
        for f in regime_dir.glob("*.json"):
            try:
                with open(f) as fp:
                    d = json.load(fp)
                    if isinstance(d, dict):
                        patterns[f.stem] = d
            except Exception:
                pass

    # 如果有当前 Regime 的历史记录
    for key, val in patterns.items():
        if market_regime.lower() in key.lower():
            return {"source": "regime_pattern", "key": key, "score": 75, "data": val}

    return None


def _score_intent(mkt: Dict, memory: Dict, graph_ctx: List[Dict]) -> List[Tuple[str, float, str]]:
    """
    对每种意图类型打分，返回 [(intent_type, score, rationale)]
    全部基于本地数据，零Token消耗
    """
    scores = []
    price     = mkt.get("price", 0)
    ch24      = mkt.get("change_24h", 0)
    ch4h      = mkt.get("change_4h", 0)
    rsi       = mkt.get("rsi14", 50)
    vol_ratio = mkt.get("vol_ratio", 1.0)
    funding   = mkt.get("funding_rate", 0)
    ema20     = mkt.get("ema20", price)
    ema50     = mkt.get("ema50", price)
    ema200    = mkt.get("ema200", price)
    regime    = mkt.get("regime", "UNKNOWN")

    # ── TREND_FOLLOWING ────────────────────────────────────────────────────
    tf_score = 0.0
    tf_reasons = []
    if abs(ch24) > 3:
        tf_score += 0.25; tf_reasons.append(f"24H大幅变动{ch24:+.1f}%")
    if abs(ch4h) > 1.5:
        tf_score += 0.15; tf_reasons.append(f"4H方向确认{ch4h:+.1f}%")
    if ch24 > 0 and price > ema20 > ema50:
        tf_score += 0.20; tf_reasons.append("EMA多头排列")
    elif ch24 < 0 and price < ema20 < ema50:
        tf_score += 0.20; tf_reasons.append("EMA空头排列")
    if "TREND" in regime.upper():
        tf_score += 0.20; tf_reasons.append(f"Regime={regime}")
    if vol_ratio > 1.3:
        tf_score += 0.10; tf_reasons.append(f"量比{vol_ratio:.1f}x支撑")
    scores.append(("TREND_FOLLOWING", min(tf_score, 1.0),
                   "趋势跟踪：" + " + ".join(tf_reasons) if tf_reasons else "无趋势信号"))

    # ── MEAN_REVERSION ─────────────────────────────────────────────────────
    mr_score = 0.0
    mr_reasons = []
    if rsi < 25:
        mr_score += 0.35; mr_reasons.append(f"RSI超卖={rsi:.0f}")
    elif rsi > 75:
        mr_score += 0.35; mr_reasons.append(f"RSI超买={rsi:.0f}")
    if abs(funding) > 0.0003:
        mr_score += 0.30; mr_reasons.append(f"资金费率极端{funding*100:.4f}%")
    if abs(ch24) < 1.5 and abs(ch4h) < 0.8:
        mr_score += 0.15; mr_reasons.append("价格横盘震荡")
    if "RANGE" in regime.upper():
        mr_score += 0.20; mr_reasons.append("Regime=震荡")
    scores.append(("MEAN_REVERSION", min(mr_score, 1.0),
                   "均值回归：" + " + ".join(mr_reasons) if mr_reasons else "无回归信号"))

    # ── BREAKOUT ───────────────────────────────────────────────────────────
    bo_score = 0.0
    bo_reasons = []
    if vol_ratio > 2.0:
        bo_score += 0.35; bo_reasons.append(f"成交量暴增{vol_ratio:.1f}x")
    if abs(ch4h) > 2.0:
        bo_score += 0.25; bo_reasons.append(f"4H急速变动{ch4h:+.1f}%")
    if "BREAK" in regime.upper():
        bo_score += 0.25; bo_reasons.append("Regime=突破")
    if abs(ch24) > 5 and vol_ratio > 1.5:
        bo_score += 0.15; bo_reasons.append("量价齐飞")
    scores.append(("BREAKOUT", min(bo_score, 1.0),
                   "突破追势：" + " + ".join(bo_reasons) if bo_reasons else "无突破信号"))

    # ── FUNDAMENTAL_PLAY ───────────────────────────────────────────────────
    # 主要靠记忆中的宏观事件缓存，当前轮默认较低
    fp_score = 0.10  # 基础分
    fp_reasons = ["等待Tavily事件缓存"]
    # 从记忆里找最近是否有宏观事件触发记录
    for dec in memory.get("recent_decisions", [])[-3:]:
        if dec.get("regime") == "FUNDAMENTAL":
            fp_score += 0.2; fp_reasons.append("近期有基本面触发记录")
            break
    scores.append(("FUNDAMENTAL_PLAY", min(fp_score, 1.0),
                   "基本面驱动：" + " + ".join(fp_reasons)))

    # ── KNOWLEDGE_MATCH ────────────────────────────────────────────────────
    km_score = 0.0
    km_reasons = []
    km = _check_knowledge_match(regime, mkt.get("coin", "BTC"))
    if km:
        km_score = km.get("score", 0) / 100
        km_reasons.append(f"知识库命中: {km['key']} (score={km['score']})")
    scores.append(("KNOWLEDGE_MATCH", km_score,
                   "知识库匹配：" + " + ".join(km_reasons) if km_reasons else "知识库无命中"))

    # ── UNCERTAIN ──────────────────────────────────────────────────────────
    # 当其他意图最高分 < 0.4，或信号互相冲突时
    max_other = max(s for _, s, _ in scores if _ != "UNCERTAIN")
    uc_score = max(0, 0.5 - max_other) if max_other < 0.4 else 0.1
    scores.append(("UNCERTAIN", uc_score, "信号不明确，需要深度调研"))

    return sorted(scores, key=lambda x: x[1], reverse=True)


def _build_chain(intent_type: str, confidence: float,
                 memory: Dict, context: Dict,
                 active_positions: Optional[Dict] = None) -> Tuple[List[str], List[str]]:
    """
    根据意图类型和置信度，从 skill_registry 构建 base_chain + extend_nodes
    base_chain: 必走（低成本）
    extend_nodes: 置信度不足时追加
    """
    loss_streaks = memory.get("loss_streaks", 0)
    has_positions = bool(active_positions) and len(active_positions) > 0

    # ── 基础链（执行环最小闭环，遵循三环架构）────────────────────────────
    # A0矛盾Skill内置于A2/A3，节点名带"(含A0)"标识
    # chain_router._run_node 会自动在 A2/A3 内调用 A0 矛盾逻辑
    # 有持仓时，A9 离场评估插入在 A4 门禁之前（先评估离场再开新仓）
    BASE_CHAINS = {
        # 趋势跟踪：技术+情绪零成本验证，再进A2(含A0内置)
        "TREND_FOLLOWING":  ["C1_技术扫描", "F2_资金流", "F3_情绪", "A2_分析(含A0)", "A4_门禁"],
        # 均值回归：情绪极值驱动，A2分析
        "MEAN_REVERSION":   ["C1_技术扫描", "F2_资金流", "F3_情绪", "A2_分析(含A0)", "A4_门禁"],
        # 基本面驱动：必须A1深度调研（含A0矛盾检测）
        "FUNDAMENTAL_PLAY": ["A1_调研(含A0)", "F1_新闻", "F5_宏观", "A2_分析(含A0)", "A4_门禁"],
        # 突破：技术信号+A2+策略匹配
        "BREAKOUT":         ["C1_技术扫描", "A2_分析(含A0)", "C3_策略匹配", "A4_门禁"],
        # 知识库命中：跳过研究，直接策略
        "KNOWLEDGE_MATCH":  ["C3_策略匹配", "A4_门禁"],
        # 不确定：完整A1调研
        "UNCERTAIN":        ["C1_技术扫描", "A1_调研(含A0)", "A2_分析(含A0)", "A4_门禁"],
    }

    # ── 扩展节点（"一生二"——置信度不足时类情报环L1.5/L3驱动）──────────
    EXTEND_RULES = {
        "TREND_FOLLOWING":  {
            (0.65, 0.75): ["A3_策略设计(含A0)"],
            (0.50, 0.65): ["A3_策略设计(含A0)", "F1_新闻"],
            (0.00, 0.50): ["A1_调研(含A0)", "A3_策略设计(含A0)", "F1_新闻"],
        },
        "MEAN_REVERSION":   {
            (0.65, 0.75): ["A3_策略设计(含A0)"],
            (0.50, 0.65): ["A3_策略设计(含A0)", "F2_资金流"],
            (0.00, 0.50): ["A1_调研(含A0)", "A3_策略设计(含A0)"],
        },
        "FUNDAMENTAL_PLAY": {
            (0.65, 0.75): ["A3_策略设计(含A0)"],
            (0.50, 0.65): ["A3_策略设计(含A0)", "F5_宏观"],
            (0.00, 0.50): ["A3_策略设计(含A0)", "F5_宏观", "F1_新闻"],
        },
        "BREAKOUT":         {
            (0.65, 0.75): ["A3_策略设计(含A0)"],
            (0.50, 0.65): ["C4_回测验证", "A3_策略设计(含A0)"],
            (0.00, 0.50): ["A1_调研(含A0)", "C4_回测验证"],
        },
        "KNOWLEDGE_MATCH":  {
            (0.65, 1.00): [],
            (0.00, 0.65): ["A2_分析(含A0)", "A3_策略设计(含A0)"],
        },
        "UNCERTAIN":        {
            (0.00, 1.00): ["A3_策略设计(含A0)", "F1_新闻"],
        },
    }

    base = list(BASE_CHAINS.get(intent_type, BASE_CHAINS["UNCERTAIN"]))

    # 有持仓时，在 A4 门禁之前插入 A9 离场评估节点
    if has_positions and "A9_离场评估" not in base:
        try:
            idx = base.index("A4_门禁")
            base.insert(idx, "A9_离场评估")
        except ValueError:
            base.append("A9_离场评估")
    extend = []

    rules = EXTEND_RULES.get(intent_type, {})
    for (low, high), nodes in rules.items():
        if low <= confidence < high:
            extend = nodes
            break

    # 连败保护：追加反思节点
    if loss_streaks >= 2:
        if "S2_A3大师研讨" not in extend:
            extend.append("S2_A3大师研讨")
        if loss_streaks >= 3:
            extend.append("S2_A8理论验证")

    return base, extend


def detect_intent(mkt: Dict, memory: Optional[Dict] = None,
                  active_positions: Optional[Dict] = None) -> IntentResult:
    """
    主入口：综合市场数据+记忆+图上下文，识别意图并构建链路
    """
    if memory is None:
        memory = _load_memory()
    graph_ctx = _load_graph_context()

    # 1. 打分，取最高意图
    scores = _score_intent(mkt, memory, graph_ctx)
    top_intent, top_score, rationale = scores[0]

    # 2. 检查意图切换（与上次不同 → 降低置信度）
    last_regime = memory.get("last_regime", "")
    if last_regime and "TREND" in last_regime and top_intent == "MEAN_REVERSION":
        top_score *= 0.85
        rationale += " [意图切换，置信度折扣]"

    # 3. 构建链路
    base_chain, extend_nodes = _build_chain(top_intent, top_score, memory, {}, active_positions)

    # 4. 附加上下文（传给链路各节点使用）
    context = {
        "intent_scores": [(t, round(s, 3)) for t, s, _ in scores[:3]],
        "last_regime":   last_regime,
        "loss_streaks":  memory.get("loss_streaks", 0),
        "lessons":       memory.get("lessons", [])[-2:],
        "graph_recent":  [
            {"intent": e.get("B_layer", {}).get("regime"), "action": e.get("C_layer", {}).get("action")}
            for e in graph_ctx
        ],
    }

    return IntentResult(
        intent_type   = top_intent,
        confidence    = round(top_score, 3),
        base_chain    = base_chain,
        extend_nodes  = extend_nodes,
        rationale     = rationale,
        context       = context,
    )


if __name__ == "__main__":
    # 快速测试
    test_mkt = {
        "price": 69.0, "change_24h": -0.8, "change_4h": -0.3,
        "rsi14": 22, "vol_ratio": 1.1, "funding_rate": -0.0006,
        "ema20": 70.5, "ema50": 69.0, "ema200": 69.0,
        "regime": "RANGE", "coin": "SOL",
    }
    result = detect_intent(test_mkt)
    print(f"意图: {result.intent_type} ({result.confidence:.0%})")
    print(f"依据: {result.rationale}")
    print(f"基础链: {result.base_chain}")
    print(f"扩展节点: {result.extend_nodes}")
    print(f"上下文: {result.context}")
