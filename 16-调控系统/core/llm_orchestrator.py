#!/usr/bin/env python3
"""
Dream OS 大模型编排择优引擎（核心定位 ①）

核心定位：
  Dream OS 不直接"创造交易能力"，而是通过 OS 编排择优机制，
  在已注册的所有节点/子系统/策略能力中，通过大模型驱动做：
    1. 能力匹配：场景→节点的多维度路由
    2. 组合择优：多节点协同编排（加权/级联/并行）
    3. 动态权重：根据近期表现 + 市场状态调整节点权重
    4. 路由决策：最终交易动作由大模型综合所有节点输出决定

设计遵循 1-ARCHITECTURE/dreamos/ 架构：
  - 对接 NodeRegistry（节点注册表，单一真相源）
  - 对接 EvolutionEngine（进化引擎，用历史表现做择优依据）
  - 输出遵循 State/NodeResult 接口规范
  - 不创造新节点，只做已有能力的编排调度 + 择优推荐

用法：
    from llm_orchestrator import LLMOrchestrator
    orch = LLMOrchestrator(registry=my_registry)

    # 场景：BTC 震荡市，收到 A0/A1/A5/A8/A9/A10 六个节点输出
    decision, rationale = orch.orchestrate(
        market_context={"symbol": "BTC", "regime": "RANGING", "volatility": "MID"},
        node_results={
            "A0": {"direction": "LONG", "confidence": 0.72},
            "A1": {"direction": "LONG", "confidence": 0.60},
            "A5": {"direction": "SHORT", "confidence": 0.65},
            "A8": {"decision": "HOLD", "risk_level": 0.55},
            "A9": {"direction": "LONG", "confidence": 0.58},
            "A10": {"direction": "SHORT", "confidence": 0.70},
        },
        recent_performance={"A0": {"win_rate": 0.58, "last_10": 6}, ...},
    )
    # decision: {"action": "LONG/SHORT/HOLD/REDUCE/CLOSE", "confidence": 0.xx, "weights": {...}}
    # rationale: 各节点投票分析 + LLM 判断逻辑 + 权重分配说明
"""

from __future__ import annotations

import json
import re
import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)


# ── 数据模型 ──────────────────────────────────────────────────────────────

@dataclass
class NodeCapability:
    """节点能力画像（供 LLM 理解每个节点的专长）"""
    node_id: str
    name: str = ""
    chain: str = ""
    description: str = ""
    tags: List[str] = field(default_factory=list)
    # 场景专长：{regime: (best_worst_score -1 ~ +1)}
    regime_strengths: Dict[str, float] = field(default_factory=dict)
    # 历史表现
    avg_confidence: float = 0.0
    avg_win_rate: float = 0.0
    sample_n: int = 0


@dataclass
class OrchestrationResult:
    """编排择优结果"""
    action: str  # LONG / SHORT / HOLD / REDUCE / CLOSE
    confidence: float = 0.0
    # 各节点权重分配（总和=1.0）
    node_weights: Dict[str, float] = field(default_factory=dict)
    # 淘汰/忽略的节点及原因
    superseded: Dict[str, str] = field(default_factory=dict)
    # LLM 解释
    rationale: str = ""
    # 组合类型：weighted_vote / cascade / single_champion
    combo_type: str = "weighted_vote"


# ── 节点能力画像生成 ──────────────────────────────────────────────────────

def build_capability_profile(
    node_id: str,
    node_meta: Dict[str, Any] = None,
    historical_stats: Dict[str, Any] = None,
) -> NodeCapability:
    """
    根据注册表元信息 + 历史回测表现，生成节点能力画像
    （供 LLM 理解每个节点"擅长什么/不擅长什么"）
    """
    meta = node_meta or {}
    stats = historical_stats or {}

    profile = NodeCapability(
        node_id=node_id,
        name=meta.get("name", node_id),
        chain=meta.get("chain", ""),
        description=meta.get("description", ""),
        tags=meta.get("tags", []),
        avg_confidence=float(stats.get("avg_confidence", 0.5)),
        avg_win_rate=float(stats.get("win_rate", 0.5)),
        sample_n=int(stats.get("sample_n", 0)),
    )

    # 基于 tags 粗略推断 regime 专长（可被后续真实回测覆盖）
    tags_l = [t.lower() for t in profile.tags]
    tag_str = " ".join(tags_l + [profile.description.lower()])
    regime_hints = {
        "TREND": ["trend", "趋势", "follow", "ema", "ma", "breakout"],
        "RANGING": ["ranging", "震荡", "range", "reversal", "rsi", "mean_revert"],
        "VOL_HIGH": ["volatility", "高波", "atr", "garch", "spike"],
        "VOL_LOW": ["low_vol", "低波", "quiet", "stable"],
        "LIQ_CRISIS": ["liquidity", "流动性", "squeeze", "crash", "黑天鹅"],
        "MOMENTUM": ["momentum", "动量", "moment", "velocity", "speed"],
        "VALUE": ["value", "估值", "fundamental", "估值", "pe", "pb"],
        "SENTIMENT": ["sentiment", "情绪", "news", "social", "恐慌", "贪婪"],
    }
    for regime, keywords in regime_hints.items():
        score = 0.0
        for kw in keywords:
            if kw in tag_str:
                score += 0.2
        if score > 0:
            profile.regime_strengths[regime] = min(score, 1.0)

    return profile


# ── 大模型编排择优核心 ────────────────────────────────────────────────────

def _build_orchestration_prompt(
    market_context: Dict[str, Any],
    node_results: Dict[str, Dict[str, Any]],
    profiles: Dict[str, NodeCapability],
    recent_performance: Dict[str, Any],
) -> str:
    """构建编排择优 prompt"""
    symbol = market_context.get("symbol", "BTC")
    regime = market_context.get("regime", "UNKNOWN")
    volatility = market_context.get("volatility", "UNKNOWN")
    direction = market_context.get("current_position", "NONE")

    node_lines = []
    for nid, result in node_results.items():
        profile = profiles.get(nid, NodeCapability(node_id=nid))
        perf = recent_performance.get(nid, {})
        win_rate = perf.get("win_rate", profile.avg_win_rate)
        sample_n = perf.get("sample_n", profile.sample_n)
        n_direction = result.get("direction", result.get("decision", "?"))
        n_conf = result.get("confidence", 0.5)

        regime_scores = []
        for reg, s in profile.regime_strengths.items():
            if s > 0.3:
                regime_scores.append(f"{reg}={s:.0%}")
        regime_str = "; ".join(regime_scores) if regime_scores else "通用"

        node_lines.append(
            f"- [{nid}] {profile.name} (chain={profile.chain})\n"
            f"    输出: {n_direction}, 置信度={n_conf:.0%}\n"
            f"    能力: {profile.description or '（无描述）'}\n"
            f"    擅长场景: {regime_str}\n"
            f"    近期表现: 胜率={win_rate:.0%} (样本={sample_n})"
        )

    nodes_block = "\n".join(node_lines) if node_lines else "（无节点输出）"

    return f"""你是 Dream OS 交易操作系统的「编排择优引擎」。

你的职责是：基于所有节点/子系统的输出，结合每个节点的能力画像 + 近期表现 + 当前市场状态，给出最终交易决策和权重分配。

核心原则：
  1. Dream OS 不创造新能力，只做"择优"——在已有节点输出中做加权、组合、过滤、选择；
  2. 场景-能力匹配优先：当前 {regime} {volatility} 行情中，擅长该 regime 的节点权重更高，不擅长者降低；
  3. 历史表现加权：近期胜率稳定的节点赋予更高权重，样本过少(<5)的节点降权；
  4. 节点多样性：避免全部节点同方向时过度自信（群体信号过载惩罚）；
  5. 方向严重分歧时优先 HOLD，不要勉强做决策。

当前市场状态：
  交易对: {symbol}
  市场形态: {regime}（趋势/震荡/高波/低波/未知）
  波动率: {volatility}
  当前持仓: {direction}（LONG/SHORT/NONE）

所有节点输出及能力画像：
{nodes_block}

请严格按 JSON 输出，不要额外文字：
{{
  "action": "LONG/SHORT/HOLD/REDUCE/CLOSE（仅一个）",
  "confidence": 0.0-1.0,
  "combo_type": "weighted_vote/cascade/single_champion/parallel_combo",
  "node_weights": {{"A0": 0.xx, "A1": 0.xx, ...}},
  "superseded": {{"A5": "当前震荡市不擅长趋势", "A9": "样本太少<5暂降权"}},
  "rationale": "100字内：综合节点投票情况、场景匹配度、历史表现、分歧处理的决策逻辑"
}}"""


def call_llm_orchestrate(prompt: str) -> Dict[str, Any]:
    """调用千问 LLM 做编排择优"""
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).resolve().parent))
        import qwen_client

        if not qwen_client.is_available():
            return {"error": "LLM不可用", "fallback": True}

        result = qwen_client.chat_completion(
            messages=[
                {"role": "system", "content": "你是 Dream OS 编排择优引擎，只输出严格合法 JSON。"},
                {"role": "user", "content": prompt},
            ],
            max_tokens=600,
            temperature=0.1,
            timeout=45,
        )
        if not result.success:
            return {"error": f"LLM失败: {result.error[:80]}", "fallback": True}

        content = result.content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            m = re.search(r"\{[\s\S]*\}", content)
            if m:
                try:
                    parsed = json.loads(m.group(0))
                except json.JSONDecodeError:
                    return {"error": "JSON解析失败", "fallback": True}
            else:
                return {"error": "LLM格式错误", "fallback": True}
        return parsed

    except Exception as e:
        logger.warning(f"[LLMOrchestrator] 调用失败: {e}")
        return {"error": f"异常: {str(e)[:60]}", "fallback": True}


# ── 规则 fallback（LLM 不可用时） ────────────────────────────────────────

def _rule_fallback_orchestrate(
    market_context: Dict[str, Any],
    node_results: Dict[str, Dict[str, Any]],
    profiles: Dict[str, NodeCapability],
    recent_performance: Dict[str, Any],
) -> OrchestrationResult:
    """规则级 fallback：简单加权投票"""
    regime = market_context.get("regime", "UNKNOWN")

    long_score, short_score, hold_score = 0.0, 0.0, 0.0
    weights: Dict[str, float] = {}
    superseded: Dict[str, str] = {}

    total_w = 0.0
    for nid, result in node_results.items():
        profile = profiles.get(nid, NodeCapability(node_id=nid))
        perf = recent_performance.get(nid, {})
        n_dir = result.get("direction", result.get("decision", "")).upper()
        n_conf = max(0.01, float(result.get("confidence", 0.5)))
        n_win = max(0.01, float(perf.get("win_rate", profile.avg_win_rate)))
        n_sample = int(perf.get("sample_n", profile.sample_n))

        # 场景匹配加成
        regime_bonus = profile.regime_strengths.get(regime, 0.0)
        # 样本惩罚
        sample_penalty = 0.5 if n_sample < 5 else 1.0

        w = n_conf * n_win * (1.0 + regime_bonus) * sample_penalty
        if w <= 0:
            superseded[nid] = "权重为0"
            continue
        weights[nid] = w
        total_w += w

    # 归一化权重
    if total_w > 0:
        for nid in weights:
            weights[nid] = round(weights[nid] / total_w, 3)
    else:
        return OrchestrationResult(
            action="HOLD", confidence=0.0, node_weights={},
            superseded={k: "全部节点无有效权重" for k in node_results},
            rationale="规则 fallback：全部节点权重归零",
            combo_type="rule_fallback",
        )

    # 加权投票
    for nid, w in weights.items():
        result = node_results[nid]
        n_dir = result.get("direction", result.get("decision", "")).upper()
        if "LONG" in n_dir or n_dir == "BUY":
            long_score += w
        elif "SHORT" in n_dir or n_dir == "SELL":
            short_score += w
        elif "HOLD" in n_dir or n_dir == "PAUSE":
            hold_score += w

    threshold = 0.15  # 超过 15% 的方向差才做决策
    diff = abs(long_score - short_score)
    if max(long_score, short_score) < 0.30:
        action = "HOLD"
        confidence = round(max(long_score, short_score, hold_score), 2)
    elif diff < threshold:
        action = "HOLD"
        confidence = round(0.5 - diff, 2)
    elif long_score > short_score:
        action = "LONG"
        confidence = round(min(long_score, 0.98), 2)
    else:
        action = "SHORT"
        confidence = round(min(short_score, 0.98), 2)

    return OrchestrationResult(
        action=action,
        confidence=confidence,
        node_weights=weights,
        superseded=superseded,
        rationale=f"规则fallback加权投票：LONG={long_score:.0%} SHORT={short_score:.0%} HOLD={hold_score:.0%}",
        combo_type="weighted_vote_rule",
    )


# ── 主入口 ────────────────────────────────────────────────────────────────

def orchestrate(
    market_context: Dict[str, Any],
    node_results: Dict[str, Dict[str, Any]],
    node_metas: Optional[Dict[str, Dict[str, Any]]] = None,
    recent_performance: Optional[Dict[str, Any]] = None,
    use_llm: bool = True,
) -> Tuple[OrchestrationResult, Dict[str, Any]]:
    """
    Dream OS 大模型编排择优主入口

    Args:
        market_context: 市场上下文 {symbol, regime, volatility, current_position, ...}
        node_results:   各节点原始输出 {node_id: {direction/decision, confidence, ...}}
        node_metas:     节点注册表元信息（可选，缺省用默认）
        recent_performance: 近 30 笔各节点表现 {node_id: {win_rate, sample_n, avg_pnl}}
        use_llm:        是否调用千问 LLM（False=只用规则 fallback）

    Returns:
        (OrchestrationResult, debug_info)
    """
    perf = recent_performance or {}
    metas = node_metas or {}

    # Step 1: 为每个节点构建能力画像
    profiles: Dict[str, NodeCapability] = {}
    for nid in node_results:
        profiles[nid] = build_capability_profile(nid, metas.get(nid), perf.get(nid))

    debug = {
        "profiles": {k: {
            "name": v.name, "chain": v.chain, "tags": v.tags,
            "regime_strengths": v.regime_strengths, "avg_win_rate": v.avg_win_rate,
        } for k, v in profiles.items()},
        "llm_used": False,
    }

    # Step 2: LLM 编排择优
    parsed = None
    if use_llm:
        prompt = _build_orchestration_prompt(market_context, node_results, profiles, perf)
        parsed = call_llm_orchestrate(prompt)
        debug["llm_used"] = not parsed.get("fallback", False)
        debug["llm_error"] = parsed.get("error", "")

    # Step 3: LLM 结果解析成功 → 构建 OrchestrationResult；失败 → 规则 fallback
    if parsed and not parsed.get("fallback") and "action" in parsed:
        try:
            # 规范化权重
            raw_weights = parsed.get("node_weights", {}) or {}
            total_w = sum(max(0, float(v)) for v in raw_weights.values())
            if total_w > 0:
                norm_weights = {k: round(max(0, float(v)) / total_w, 3) for k, v in raw_weights.items()}
            else:
                norm_weights = {k: 1.0 / len(node_results) for k in node_results}

            result = OrchestrationResult(
                action=str(parsed["action"]).upper()[:6],
                confidence=max(0.0, min(1.0, float(parsed.get("confidence", 0.5)))),
                node_weights=norm_weights,
                superseded=dict(parsed.get("superseded", {}) or {}),
                rationale=str(parsed.get("rationale", ""))[:200],
                combo_type=str(parsed.get("combo_type", "weighted_vote")),
            )
            return result, debug
        except Exception as e:
            logger.warning(f"[LLMOrchestrator] LLM结果解析异常: {e}，降级到规则")

    # Step 4: 规则 fallback
    result = _rule_fallback_orchestrate(market_context, node_results, profiles, perf)
    return result, debug


# ── 批量择优（多场景） ────────────────────────────────────────────────────

def orchestrate_scenarios(
    scenarios: List[Dict[str, Any]],
    node_metas: Optional[Dict[str, Dict[str, Any]]] = None,
    recent_performance: Optional[Dict[str, Any]] = None,
    use_llm: bool = True,
) -> List[Tuple[OrchestrationResult, Dict[str, Any]]]:
    """对多组市场场景批量做编排择优"""
    results = []
    for sc in scenarios:
        result, debug = orchestrate(
            market_context=sc.get("market_context", {}),
            node_results=sc.get("node_results", {}),
            node_metas=node_metas,
            recent_performance=recent_performance,
            use_llm=use_llm,
        )
        results.append((result, debug))
    return results
