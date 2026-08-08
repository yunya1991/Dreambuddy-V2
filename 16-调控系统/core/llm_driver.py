#!/usr/bin/env python3
"""
Dream OS 大模型驱动器 — 千问 3.8 MAX 驱动系统编排/进化/修复

核心定位（用户明确要求）：
  - Dream OS 交易操作系统只负责编排，不创造新能力
  - 大模型是驱动力，驱动 OS 的编排、进化、修复调整
  - 系统进化不局限于参数调优，包括 A8 治理、做梦部进化、认知系统等

四大驱动入口：
  1. drive_a8_governance()     — A8 理论与实践验证：检测策略偏差，生成修复提案
  2. drive_dream_evolution()   — 做梦部进化：潜意识探测，发现被压制的策略方向
  3. drive_cognitive_reflection() — 认知系统反思：系统级自省，记忆/经验复盘
  4. drive_parameter_tuning()  — 参数调优：基于回测结果的参数优化建议

接入方式：
  - 作为 self_evolution_engine 的 llm_client（签名兼容）
  - 作为 llm_bridge.py 的 provider（优先级最高）
  - 各子系统的独立调用入口

模块归属：16-调控系统（跨系统调控与 LLM 驱动中枢）
"""

import json
import logging
import time
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# 同目录导入
try:
    from . import qwen_client
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import qwen_client

logger = logging.getLogger(__name__)

_BASE_DIR = Path(__file__).resolve().parent.parent.parent


# ── 驱动结果 ──────────────────────────────────────────────────────────────

@dataclass
class DriveResult:
    """驱动结果"""
    success: bool
    purpose: str
    content: str = ""
    proposals: List[Dict[str, Any]] = field(default_factory=list)
    insights: List[str] = field(default_factory=list)
    raw: str = ""
    error: str = ""
    model: str = ""
    latency_ms: float = 0.0
    tokens: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "purpose": self.purpose,
            "content": self.content[:500],
            "proposals": self.proposals,
            "insights": self.insights,
            "error": self.error,
            "model": self.model,
            "latency_ms": self.latency_ms,
            "ts": datetime.now(timezone.utc).isoformat(),
        }


# ── 系统提示词模板 ────────────────────────────────────────────────────────

_SYS_A8 = """你是 Dream OS 的 A8 理论与实践验证引擎。
你的职责：分析交易系统的实际表现与理论框架之间的偏差，输出可执行的修复提案。

输出格式（严格 JSON）：
{
  "gaps": [
    {"type": "偏差类型", "desc": "30字内描述", "severity": "high/medium/low"}
  ],
  "proposals": [
    {"title": "提案标题", "action": "具体动作", "rationale": "理由"}
  ]
}
只输出 JSON，不要其他内容。"""

_SYS_DREAM = """你是 Dream OS 做梦部，基于弗洛伊德精神分析框架分析交易系统的潜意识。
你的职责：发现系统被压制的判断、强迫性重复模式、投射性归因，提出打破僵局的进化方向。

输出格式（严格 JSON）：
{
  "subconscious_signals": ["信号1", "信号2"],
  "suppressed_judgment": "系统最深层的被压制判断（20字内）",
  "proposals": [
    {"title": "进化方向", "action": "具体动作", "rationale": "理由"}
  ]
}
只输出 JSON，不要其他内容。"""

_SYS_COGNITIVE = """你是 Dream OS 认知系统反思引擎。
你的职责：对系统的记忆、经验、决策模式进行元认知反思，发现认知盲区和学习障碍。

输出格式（严格 JSON）：
{
  "cognitive_blind_spots": ["盲区1", "盲区2"],
  "learning_barriers": ["障碍1"],
  "memory_quality_issues": ["问题1"],
  "proposals": [
    {"title": "认知改进", "action": "具体动作", "rationale": "理由"}
  ]
}
只输出 JSON，不要其他内容。"""

_SYS_PARAM = """你是 Dream OS 参数调优引擎。
你的职责：基于回测统计和实盘表现，分析参数优化的方向，给出可验证的参数调整建议。

输出格式（严格 JSON）：
{
  "analysis": "总体分析（50字内）",
  "param_suggestions": [
    {"param_key": "参数名", "current": "当前值", "suggested": "建议值", "rationale": "理由"}
  ],
  "risk_warnings": ["风险提示1"]
}
只输出 JSON，不要其他内容。"""


# ── JSON 解析工具 ─────────────────────────────────────────────────────────

def _parse_json(content: str) -> Optional[Dict[str, Any]]:
    """解析 LLM 输出中的 JSON（容错：去除 markdown 代码块标记）"""
    import re
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
    content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", content)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    return None


# ── 四大驱动入口 ──────────────────────────────────────────────────────────

def drive_a8_governance(
    stats: Dict[str, Any],
    decisions: List[Dict[str, Any]],
    max_tokens: int = 800,
) -> DriveResult:
    """
    驱动入口 1：A8 理论与实践验证

    分析交易系统实际表现与理论框架的偏差，生成修复提案。
    驱动 A8 治理节点的深度分析，替代/增强纯规则检测。

    Args:
        stats: 系统统计（win_rate, hold_rate, top_hexagrams 等）
        decisions: 最近交易决策列表

    Returns:
        DriveResult（含 gaps + proposals）
    """
    start = time.time()

    # 构建上下文
    recent = decisions[-5:] if len(decisions) > 5 else decisions
    context = json.dumps({
        "win_rate": stats.get("win_rate", "?"),
        "hold_rate": stats.get("hold_rate", "?"),
        "total_trades": stats.get("total_trades", 0),
        "top_hexagrams": stats.get("top_hexagrams", {}),
        "accuracy_trend": stats.get("accuracy_trend", []),
        "recent_decisions": [
            {"action": d.get("action"), "result": d.get("result"), "reason": d.get("reason", "")[:50]}
            for d in recent
        ],
    }, ensure_ascii=False, indent=2)

    prompt = f"以下是交易系统近期表现数据，请分析理论与实践的偏差：\n\n{context}"

    result = qwen_client.chat_completion(
        messages=[
            {"role": "system", "content": _SYS_A8},
            {"role": "user", "content": prompt},
        ],
        max_tokens=max_tokens,
        temperature=0.3,
    )

    latency = (time.time() - start) * 1000

    if not result.success:
        return DriveResult(
            success=False, purpose="a8_governance",
            error=result.error, latency_ms=latency,
        )

    parsed = _parse_json(result.content)
    proposals = parsed.get("proposals", []) if parsed else []
    gaps = parsed.get("gaps", []) if parsed else []

    return DriveResult(
        success=True,
        purpose="a8_governance",
        content=result.content,
        proposals=proposals,
        insights=[g.get("desc", str(g)) for g in gaps],
        model=result.model,
        latency_ms=latency,
        tokens=result.tokens_input + result.tokens_output,
    )


def drive_dream_evolution(
    stats: Dict[str, Any],
    signals: List[str],
    a8_gaps: List[Dict[str, Any]] = None,
    max_tokens: int = 600,
) -> DriveResult:
    """
    驱动入口 2：做梦部进化

    基于弗洛伊德五大机制，分析系统潜意识层面的被压制判断，
    驱动策略进化方向的探索。

    Args:
        stats: 系统统计
        signals: 已检测到的潜意识信号列表
        a8_gaps: A8 层发现的偏差（提供上下文）

    Returns:
        DriveResult（含 subconscious_signals + proposals）
    """
    start = time.time()

    context = json.dumps({
        "win_rate": stats.get("win_rate", "?"),
        "hold_rate": stats.get("hold_rate", "?"),
        "hold_streak": stats.get("hold_streak", 0),
        "detected_signals": signals[:5],
        "a8_gaps": [{"type": g.get("type"), "desc": g.get("desc")} for g in (a8_gaps or [])[:3]],
    }, ensure_ascii=False, indent=2)

    prompt = f"以下是交易系统的表现和已检测信号，请进行潜意识分析：\n\n{context}"

    result = qwen_client.chat_completion(
        messages=[
            {"role": "system", "content": _SYS_DREAM},
            {"role": "user", "content": prompt},
        ],
        max_tokens=max_tokens,
        temperature=0.5,
    )

    latency = (time.time() - start) * 1000

    if not result.success:
        return DriveResult(
            success=False, purpose="dream_evolution",
            error=result.error, latency_ms=latency,
        )

    parsed = _parse_json(result.content)
    proposals = parsed.get("proposals", []) if parsed else []
    sub_signals = parsed.get("subconscious_signals", []) if parsed else []
    suppressed = parsed.get("suppressed_judgment", "") if parsed else ""

    insights = sub_signals[:]
    if suppressed:
        insights.append(f"被压制判断: {suppressed}")

    return DriveResult(
        success=True,
        purpose="dream_evolution",
        content=result.content,
        proposals=proposals,
        insights=insights,
        model=result.model,
        latency_ms=latency,
    )


def drive_cognitive_reflection(
    memory_stats: Dict[str, Any],
    recent_learnings: List[Dict[str, Any]] = None,
    max_tokens: int = 800,
) -> DriveResult:
    """
    驱动入口 3：认知系统反思

    对系统的记忆质量、经验积累、决策模式进行元认知反思，
    发现认知盲区和学习障碍，驱动认知系统进化。

    Args:
        memory_stats: 记忆系统统计（memory_count, quality_distribution 等）
        recent_learnings: 近期学习记录

    Returns:
        DriveResult（含 cognitive_blind_spots + proposals）
    """
    start = time.time()

    context = json.dumps({
        "memory_count": memory_stats.get("memory_count", 0),
        "quality_distribution": memory_stats.get("quality_distribution", {}),
        "recent_accuracy": memory_stats.get("recent_accuracy", "?"),
        "stagnation_indicators": memory_stats.get("stagnation_indicators", []),
        "recent_learnings": [
            {"type": l.get("type"), "outcome": l.get("outcome")}
            for l in (recent_learnings or [])[-5:]
        ],
    }, ensure_ascii=False, indent=2)

    prompt = f"以下是系统认知和记忆的统计数据，请进行元认知反思：\n\n{context}"

    result = qwen_client.chat_completion(
        messages=[
            {"role": "system", "content": _SYS_COGNITIVE},
            {"role": "user", "content": prompt},
        ],
        max_tokens=max_tokens,
        temperature=0.4,
    )

    latency = (time.time() - start) * 1000

    if not result.success:
        return DriveResult(
            success=False, purpose="cognitive_reflection",
            error=result.error, latency_ms=latency,
        )

    parsed = _parse_json(result.content)
    proposals = parsed.get("proposals", []) if parsed else []
    blind_spots = parsed.get("cognitive_blind_spots", []) if parsed else []
    barriers = parsed.get("learning_barriers", []) if parsed else []
    memory_issues = parsed.get("memory_quality_issues", []) if parsed else []

    insights = blind_spots + barriers + memory_issues

    return DriveResult(
        success=True,
        purpose="cognitive_reflection",
        content=result.content,
        proposals=proposals,
        insights=insights,
        model=result.model,
        latency_ms=latency,
    )


def drive_parameter_tuning(
    backtest_stats: Dict[str, Any],
    current_params: Dict[str, Any],
    max_tokens: int = 800,
) -> DriveResult:
    """
    驱动入口 4：参数调优

    基于回测统计和当前参数，分析优化方向，给出可验证的参数调整建议。
    注意：只提供建议，不直接修改参数——参数变更需通过回测验证后由 OS 编排执行。

    Args:
        backtest_stats: 回测统计（win_rate, avg_pnl, max_dd, sharpe 等）
        current_params: 当前参数快照

    Returns:
        DriveResult（含 param_suggestions + risk_warnings）
    """
    start = time.time()

    context = json.dumps({
        "backtest": {
            "win_rate": backtest_stats.get("win_rate", "?"),
            "avg_pnl": backtest_stats.get("avg_pnl", "?"),
            "max_drawdown": backtest_stats.get("max_drawdown", "?"),
            "sharpe": backtest_stats.get("sharpe", "?"),
            "total_trades": backtest_stats.get("total_trades", 0),
            "avg_hold_hours": backtest_stats.get("avg_hold_hours", "?"),
        },
        "current_params": current_params,
    }, ensure_ascii=False, indent=2)

    prompt = f"以下是回测统计和当前参数，请分析优化方向：\n\n{context}"

    result = qwen_client.chat_completion(
        messages=[
            {"role": "system", "content": _SYS_PARAM},
            {"role": "user", "content": prompt},
        ],
        max_tokens=max_tokens,
        temperature=0.2,
    )

    latency = (time.time() - start) * 1000

    if not result.success:
        return DriveResult(
            success=False, purpose="parameter_tuning",
            error=result.error, latency_ms=latency,
        )

    parsed = _parse_json(result.content)
    proposals = parsed.get("param_suggestions", []) if parsed else []
    warnings = parsed.get("risk_warnings", []) if parsed else []
    analysis = parsed.get("analysis", "") if parsed else ""

    return DriveResult(
        success=True,
        purpose="parameter_tuning",
        content=result.content,
        proposals=proposals,
        insights=warnings,
        model=result.model,
        latency_ms=latency,
    )


# ── 兼容 self_evolution_engine 的 callable 接口 ──────────────────────────

def llm_call(
    prompt: str,
    max_tokens: int = 200,
    purpose: str = "general",
) -> str:
    """
    兼容 self_evolution_engine.llm_client 签名的调用入口

    用法:
        from core.llm_driver import llm_call
        engine = SelfEvolutionEngine(llm_client=llm_call)

    这是 drive_*() 系列的简化版，用于 self_evolution_engine 中
    对 llm_client(prompt, max_tokens, purpose) 的直接调用场景。
    """
    return qwen_client.call(
        prompt=prompt,
        max_tokens=max_tokens,
        purpose=purpose,
    )


# ── 统一驱动入口 ──────────────────────────────────────────────────────────

def drive_all(
    stats: Dict[str, Any],
    decisions: List[Dict[str, Any]],
    memory_stats: Dict[str, Any] = None,
    current_params: Dict[str, Any] = None,
    backtest_stats: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """
    完整驱动周期：依次执行四大驱动入口

    对应 self_evolution_engine.run_full_cycle() 的 LLM 增强版。
    每层结果作为下一层的上下文输入，形成渐进式深度分析。

    Returns:
        {
            "a8_governance": DriveResult,
            "dream_evolution": DriveResult,
            "cognitive_reflection": DriveResult,
            "parameter_tuning": DriveResult,
            "all_proposals": [...],
        }
    """
    ts = datetime.now(timezone.utc).isoformat()
    logger.info(f"[DreamLLM] 启动完整驱动周期 {ts}")

    results: Dict[str, Any] = {"ts": ts}

    # 1. A8 治理
    a8 = drive_a8_governance(stats, decisions)
    results["a8_governance"] = a8.to_dict()
    logger.info(f"  [A8] success={a8.success} proposals={len(a8.proposals)} latency={a8.latency_ms}ms")

    # 2. 做梦部进化（传入 A8 的 gaps 作为上下文）
    a8_gaps = [{"type": "llm_detected", "desc": g} for g in a8.insights] if a8.success else []
    dream_signals = stats.get("detected_signals", [])
    dream = drive_dream_evolution(stats, dream_signals, a8_gaps)
    results["dream_evolution"] = dream.to_dict()
    logger.info(f"  [Dream] success={dream.success} proposals={len(dream.proposals)} latency={dream.latency_ms}ms")

    # 3. 认知系统反思
    cognitive = drive_cognitive_reflection(
        memory_stats or stats,
        recent_learnings=decisions,
    )
    results["cognitive_reflection"] = cognitive.to_dict()
    logger.info(f"  [Cognitive] success={cognitive.success} proposals={len(cognitive.proposals)} latency={cognitive.latency_ms}ms")

    # 4. 参数调优
    param = drive_parameter_tuning(
        backtest_stats or stats,
        current_params or {},
    )
    results["parameter_tuning"] = param.to_dict()
    logger.info(f"  [Param] success={param.success} proposals={len(param.proposals)} latency={param.latency_ms}ms")

    # 汇总所有提案
    all_proposals = []
    for layer in [a8, dream, cognitive, param]:
        all_proposals.extend(layer.proposals)
    results["all_proposals"] = all_proposals
    results["total_proposals"] = len(all_proposals)

    logger.info(f"[DreamLLM] 驱动周期完成，共 {len(all_proposals)} 个提案")
    return results


def get_status() -> Dict[str, Any]:
    """获取 LLM 驱动器状态"""
    return {
        "qwen_available": qwen_client.is_available(),
        "qwen_config": qwen_client.get_config_info(),
        "driver_entries": [
            "drive_a8_governance",
            "drive_dream_evolution",
            "drive_cognitive_reflection",
            "drive_parameter_tuning",
        ],
    }
