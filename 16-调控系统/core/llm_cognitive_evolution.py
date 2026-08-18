#!/usr/bin/env python3
"""
Dream OS 大模型认知进化引擎（核心定位 ②）

认知-理论-实践闭环：
  1. 认知反思（Cognitive Reflection）：千问 LLM 回顾交易记录、episode、反刍发现
  2. 理论构建（Theory Building）：从经验中抽象出一般性规律，更新知识库
  3. 策略补丁（Strategy Patch）：将理论转化为可执行的参数调整/策略增补
  4. 流程完善（Process Improvement）：识别流程漏洞、缺失步骤，优化执行链路
  5. 写入记忆（Memory Write-back）：把认知产物落地到 4-MEMORY/ 对应层级

设计遵循 4-MEMORY 认知架构：
  - 0-元记忆 / 1-事实库 / 2-案例库 / 3-策略库 / 4-理论库 / 5-模型库 分层存储
  - 对接 RuminationEngine（反刍引擎）产出
  - 对接 self_evolution_engine.py 的 Lesson / Proposal 结构
  - 所有修改建议必须：可回溯（溯源到哪笔交易/哪个认知盲区）+ 需验证（回测门控）

用法：
    from llm_cognitive_evolution import CognitiveEvolutionEngine
    engine = CognitiveEvolutionEngine(memory_root="/path/to/4-MEMORY")

    report = engine.evolve(
        recent_trades=[...],         # 近期交易记录
        rumination_findings=[...],   # 反刍引擎发现
        a8_governance_report={...},  # A8 理论与实践偏差
        cognitive_health={...},      # 认知系统状态
    )
    # report.reflection_insights → 认知洞察（来自经验）
    # report.theory_updates → 知识库更新建议
    # report.strategy_patches → 策略补丁（参数/增删/门控）
    # report.process_tweaks → 流程优化建议
    # report.memory_diffs → 建议写入 4-MEMORY 的记忆条目
"""

from __future__ import annotations

import json
import re
import logging
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_MEMORY_ROOT = Path(__file__).resolve().parent.parent.parent / "4-MEMORY"


# ── 数据模型 ──────────────────────────────────────────────────────────────

@dataclass
class ReflectionInsight:
    """认知洞察 — 来自经验回顾"""
    insight_id: str
    category: str          # 认知盲区 / 强迫性重复 / 情绪干扰 / 数据缺失 / 理论矛盾
    severity: str          # HIGH / MEDIUM / LOW
    description: str       # 洞察描述（发生了什么）
    root_cause: str        # 根因（为什么）
    evidence_trade_ids: List[str] = field(default_factory=list)
    sample_count: int = 0
    confidence: float = 0.0


@dataclass
class TheoryUpdate:
    """知识库更新建议"""
    theory_id: str
    layer: str             # fact / case / strategy / theory / model / meta
    operation: str         # CREATE / UPDATE / REPLACE / DELETE
    target_path: str       # 相对 4-MEMORY 的路径
    title: str
    proposed_content: str  # 建议的新内容（自然语言）
    rationale: str         # 为什么要改（溯源到哪个 insight）
    confidence: float = 0.0


@dataclass
class StrategyPatch:
    """策略补丁 — 可执行的参数/逻辑调整"""
    patch_id: str
    patch_type: str        # PARAMETER / ADD_NODE / REMOVE_NODE / ADD_GATE / REMOVE_GATE / WEIGHT_TWEAK
    target_module: str     # 受影响的模块
    target_param: Optional[str] = None
    old_value: Optional[Any] = None
    new_value: Optional[Any] = None
    node_spec: Optional[Dict[str, Any]] = None
    backtest_requirement: str = "P0 回测门禁：win_rate > 0.42 且 max_drawdown < 15%"
    rationale: str = ""
    risk_level: str = "MEDIUM"
    confidence: float = 0.0


@dataclass
class ProcessTweak:
    """流程完善建议"""
    tweak_id: str
    category: str          # PRE-TRADE / DURING-TRADE / POST-TRADE / RUMINATION / META
    current_issue: str
    proposed_flow: str     # 建议的新流程（逐步）
    affected_stakeholders: List[str] = field(default_factory=list)  # G层 / 调控 / 做梦部 / 记忆
    verification_signal: str = ""  # 如何验证流程生效（可量化指标）
    rationale: str = ""
    confidence: float = 0.0


@dataclass
class MemoryEntry:
    """写入 4-MEMORY 的记忆条目（建议格式）"""
    memory_type: str       # memory_unit / cognitive_unit / strategy_unit / meta_note
    memory_id: str
    memory_level: str      # L0-L5
    title: str
    content: str
    tags: List[str] = field(default_factory=list)
    confidence: float = 0.0
    generated_at: str = ""


@dataclass
class EvolutionReport:
    """进化报告"""
    generated_at: str = ""
    reflection_insights: List[ReflectionInsight] = field(default_factory=list)
    theory_updates: List[TheoryUpdate] = field(default_factory=list)
    strategy_patches: List[StrategyPatch] = field(default_factory=list)
    process_tweaks: List[ProcessTweak] = field(default_factory=list)
    memory_entries: List[MemoryEntry] = field(default_factory=list)
    execution_errors: List[str] = field(default_factory=list)


# ── Prompt 构建 ──────────────────────────────────────────────────────────

def _build_evolution_prompt(
    recent_trades: List[Dict[str, Any]],
    rumination_findings: List[Dict[str, Any]],
    a8_report: Dict[str, Any],
    cognitive_health: Dict[str, Any],
    current_params: Dict[str, Any],
) -> str:
    """构建认知进化 prompt（大模型反思闭环）"""

    # 交易摘要（避免过多 token）
    trade_summaries = []
    for i, t in enumerate(recent_trades[-30:]):  # 只取最近30笔
        pnl = t.get("pnl_pct") or t.get("profit_pct") or 0
        dr = t.get("direction", "?")
        sym = t.get("symbol", "?")
        exit_ = t.get("exit_reason", "")[:30]
        trade_summaries.append(f"  #{i+1} {sym} {dr} pnl={pnl:+.1f}% exit={exit_}")
    trade_block = "\n".join(trade_summaries) if trade_summaries else "  （无近期交易）"

    # 反刍发现摘要
    rumi_summaries = []
    for i, f in enumerate(rumination_findings[:15]):
        pk = f.get("pattern_key", "?")
        obs = f.get("observed_rate", 0)
        base = f.get("baseline_rate", 0)
        samp = f.get("sample_n", 0)
        txt = f.get("finding_text", "")[:60]
        rumi_summaries.append(f"  [{pk}] observed={obs:.0%} baseline={base:.0%} n={samp}: {txt}")
    rumi_block = "\n".join(rumi_summaries) if rumi_summaries else "  （无反刍发现）"

    # A8 报告摘要
    a8_insights = a8_report.get("insights", []) or []
    a8_gaps = a8_report.get("gaps", []) or []
    a8_block = "  洞察:\n" + "\n".join(f"    - {str(x)[:80]}" for x in a8_insights[:5]) if a8_insights else "  洞察:（无）"
    a8_block += "\n  知行差距:\n" + "\n".join(f"    - {str(x)[:80]}" for x in a8_gaps[:5]) if a8_gaps else "\n  知行差距:（无）"

    # 认知健康状态
    cog_summary = json.dumps(cognitive_health, ensure_ascii=False, indent=4) if cognitive_health else "{}"
    # 截断
    if len(cog_summary) > 800:
        cog_summary = cog_summary[:800] + "\n...(截断)"

    params_block = json.dumps(dict(list(current_params.items())[:20]), ensure_ascii=False, indent=2)

    return f"""你是 Dream OS 交易操作系统的「认知进化引擎」。

你的职责是：运行认知-理论-实践闭环，从近期交易经验中吸取教训，输出可落地的进化产物。

Dream OS 的核心原则（必须牢记）：
  - Dream OS 不创造交易能力，只"调用 + 编排 + 择优 + 进化"已有的子系统能力；
  - 所有策略补丁必须通过回测门控才能上线；
  - 每一个理论更新都必须溯源到具体证据（某笔交易/某个模式）。

认知-理论-实践闭环四步：
  1. 认知反思 — 识别认知盲区、强迫性重复、情绪干扰
  2. 理论构建 — 更新知识库（事实/案例/策略/理论/元记忆）
  3. 策略补丁 — 转化为可执行的参数调整/增删节点/门控
  4. 流程完善 — 优化执行链路、检查清单、门控时机

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【输入数据】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

近期交易（最近30笔）:
{trade_block}

反刍引擎发现（偏离基线的模式）:
{rumi_block}

A8 理论与实践一致性检查:
{a8_block}

认知系统健康状态:
```
{cog_summary}
```

当前策略关键参数:
```
{params_block}
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【输出格式】严格 JSON，不要额外文字
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{{
  "reflection_insights": [
    {{
      "insight_id": "R{{序号}}-{{简短标签}}",
      "category": "认知盲区/强迫性重复/情绪干扰/数据缺失/理论矛盾",
      "severity": "HIGH/MEDIUM/LOW",
      "description": "不超过50字，发生了什么",
      "root_cause": "不超过50字，为什么",
      "evidence_trade_ids": ["#1", "#7", ...],
      "sample_count": 数量,
      "confidence": 0.0-1.0
    }}
  ],
  "theory_updates": [
    {{
      "theory_id": "T{{序号}}-{{简短标签}}",
      "layer": "fact/case/strategy/theory/model/meta",
      "operation": "CREATE/UPDATE/REPLACE/DELETE",
      "target_path": "例如 4-MEMORY/3-策略库/离场保护期.md 或 4-MEMORY/4-理论库/震荡市判断原则.md",
      "title": "简短标题",
      "proposed_content": "不超过150字的新知识内容",
      "rationale": "溯源到 insight_id，不超过50字",
      "confidence": 0.0-1.0
    }}
  ],
  "strategy_patches": [
    {{
      "patch_id": "S{{序号}}-{{简短标签}}",
      "patch_type": "PARAMETER/ADD_NODE/REMOVE_NODE/ADD_GATE/REMOVE_GATE/WEIGHT_TWEAK",
      "target_module": "例如 polling_trader / yijing_exit_system / classic_exit_system / llm_orchestrator",
      "target_param": "例如 force_close_risk_threshold（PARAMETER 必填）",
      "old_value": "原值（PARAMETER 必填）",
      "new_value": "新值（PARAMETER 必填）",
      "backtest_requirement": "回测门禁条件",
      "rationale": "溯源到 insight_id 或 theory_id，不超过60字",
      "risk_level": "HIGH/MEDIUM/LOW",
      "confidence": 0.0-1.0
    }}
  ],
  "process_tweaks": [
    {{
      "tweak_id": "P{{序号}}-{{简短标签}}",
      "category": "PRE-TRADE/DURING-TRADE/POST-TRADE/RUMINATION/META",
      "current_issue": "当前流程的问题，不超过60字",
      "proposed_flow": "建议的新流程，分步写，不超过100字",
      "affected_stakeholders": ["G层/调控/做梦部/记忆/反刍"],
      "verification_signal": "验证指标：例如\"A8偏差率从X%降到Y%\"或\"认知反思HIGH项下降\"",
      "rationale": "溯源，不超过50字",
      "confidence": 0.0-1.0
    }}
  ],
  "memory_entries": [
    {{
      "memory_type": "memory_unit/cognitive_unit/strategy_unit/meta_note",
      "memory_id": "M{{序号}}-{{标签}}",
      "memory_level": "L0/L1/L2/L3/L4/L5",
      "title": "记忆标题",
      "content": "不超过100字的记忆内容",
      "tags": ["标签1", "标签2"],
      "confidence": 0.0-1.0
    }}
  ]
}}
"""


# ── LLM 调用 ──────────────────────────────────────────────────────────────

def _call_llm_evolution(prompt: str) -> Dict[str, Any]:
    """调用千问 LLM 做认知进化分析"""
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).resolve().parent))
        import qwen_client

        if not qwen_client.is_available():
            return {"error": "LLM不可用", "fallback": True}

        result = qwen_client.chat_completion(
            messages=[
                {"role": "system", "content": "你是 Dream OS 认知进化引擎，是一位严谨的认知科学家和量化交易研究员。只输出严格合法 JSON。"},
                {"role": "user", "content": prompt},
            ],
            max_tokens=2000,
            temperature=0.2,
            timeout=60,
        )
        if not result.success:
            return {"error": f"LLM失败: {result.error[:100]}", "fallback": True}

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
                    return {"error": "JSON解析失败（LLM输出格式不符）", "fallback": True}
            else:
                return {"error": "LLM无JSON输出", "fallback": True}
        return parsed

    except Exception as e:
        logger.warning(f"[CognitiveEvolution] LLM调用异常: {e}")
        return {"error": f"异常: {str(e)[:100]}", "fallback": True}


# ── 规则 fallback（LLM 不可用时的最小进化） ─────────────────────────────

def _rule_fallback_evolution(
    recent_trades: List[Dict[str, Any]],
    rumination_findings: List[Dict[str, Any]],
    a8_report: Dict[str, Any],
    current_params: Dict[str, Any],
) -> EvolutionReport:
    """规则级 fallback：基于简单统计给出最小进化产物"""
    rep = EvolutionReport(generated_at=datetime.now(timezone.utc).isoformat())
    rep.execution_errors.append("[规则 fallback] LLM 不可用，仅基于统计给出有限建议")

    # 1. 简单胜率/亏损分析 → 认知洞察
    wins = [t for t in recent_trades if (t.get("pnl_pct") or t.get("profit_pct") or 0) > 0]
    losses = [t for t in recent_trades if (t.get("pnl_pct") or t.get("profit_pct") or 0) <= 0]
    win_rate = len(wins) / len(recent_trades) if recent_trades else 0

    if recent_trades and win_rate < 0.40:
        rep.reflection_insights.append(ReflectionInsight(
            insight_id="R1-LowWinRate",
            category="数据缺失",
            severity="HIGH",
            description=f"最近{len(recent_trades)}笔胜率仅{win_rate:.0%}，低于40%基线",
            root_cause="入场信号/离场时机与当前行情不匹配",
            sample_count=len(recent_trades),
            confidence=0.6,
        ))
    if len(losses) >= 3:
        avg_loss = sum((t.get("pnl_pct") or t.get("profit_pct") or 0) for t in losses) / len(losses)
        rep.reflection_insights.append(ReflectionInsight(
            insight_id="R2-SizeableLoss",
            category="理论矛盾",
            severity="MEDIUM",
            description=f"{len(losses)}笔亏损平均{avg_loss:.1f}%，单笔亏损偏大",
            root_cause="止损不及时或离场保护期设置不足",
            sample_count=len(losses),
            confidence=0.55,
        ))

    # 2. 反刍发现 → 理论更新
    for f in rumination_findings[:3]:
        pk = f.get("pattern_key", "PAT")
        dev = f.get("deviation_pct", 0)
        if dev > 0:
            rep.theory_updates.append(TheoryUpdate(
                theory_id=f"T-{pk.replace('|', '_')}",
                layer="case",
                operation="CREATE",
                target_path=f"4-MEMORY/2-案例库/pattern_{pk.replace('|', '_')}.md",
                title=f"模式 {pk} 胜率显著高于基线 +{dev*100:.0f}%",
                proposed_content=f"在 {pk} 场景下，观察胜率 {f.get('observed_rate',0):.0%} vs 基线 {f.get('baseline_rate',0):.0%}，样本 n={f.get('sample_n',0)}。建议在该场景下提升权重。",
                rationale=f"反刍引擎发现，偏离基线{dev*100:.0f}%",
                confidence=0.5,
            ))

    # 3. 默认策略补丁（离场保护期偏短）
    mh = current_params.get("min_hold_bars", 0)
    if mh and int(mh) <= 6:
        rep.strategy_patches.append(StrategyPatch(
            patch_id="S1-HoldPeriodExtend",
            patch_type="PARAMETER",
            target_module="classic_exit_system / polling_trader",
            target_param="min_hold_bars",
            old_value=mh,
            new_value=max(8, int(mh) + 2),
            rationale="近期胜率偏低 → 延长保护期减少被洗出概率（规则建议，需回测验证）",
            risk_level="LOW",
            confidence=0.5,
        ))

    # 4. 流程建议（A8 偏差大时补流程）
    a8_gaps = a8_report.get("gaps", []) or []
    if len(a8_gaps) >= 1:
        rep.process_tweaks.append(ProcessTweak(
            tweak_id="P1-A8PreCheck",
            category="PRE-TRADE",
            current_issue="A8知行偏差未在入场前检查，导致实践偏离理论",
            proposed_flow="1. 每笔入场前自动跑A8偏差快照 2. 偏差>=1项时G层要求人工确认 3. 偏差>=3项时直接拦截",
            affected_stakeholders=["G层", "调控"],
            verification_signal="A8偏差拦截率在入场阶段>70%",
            rationale=f"当前发现 {len(a8_gaps)} 项知行差距",
            confidence=0.5,
        ))

    return rep


# ── 结果解析 ──────────────────────────────────────────────────────────────

def _parse_llm_evolution(parsed: Dict[str, Any]) -> EvolutionReport:
    """把 LLM JSON 输出解析成 EvolutionReport"""
    rep = EvolutionReport(generated_at=datetime.now(timezone.utc).isoformat())

    for item in (parsed.get("reflection_insights") or []):
        try:
            rep.reflection_insights.append(ReflectionInsight(
                insight_id=str(item.get("insight_id", "")),
                category=str(item.get("category", "")),
                severity=str(item.get("severity", "MEDIUM")),
                description=str(item.get("description", ""))[:200],
                root_cause=str(item.get("root_cause", ""))[:200],
                evidence_trade_ids=[str(x) for x in (item.get("evidence_trade_ids") or [])],
                sample_count=int(item.get("sample_count", 0) or 0),
                confidence=float(item.get("confidence", 0.5) or 0.5),
            ))
        except Exception as e:
            rep.execution_errors.append(f"reflection parse fail: {e}")

    for item in (parsed.get("theory_updates") or []):
        try:
            rep.theory_updates.append(TheoryUpdate(
                theory_id=str(item.get("theory_id", "")),
                layer=str(item.get("layer", "")),
                operation=str(item.get("operation", "UPDATE")),
                target_path=str(item.get("target_path", "")),
                title=str(item.get("title", "")),
                proposed_content=str(item.get("proposed_content", ""))[:400],
                rationale=str(item.get("rationale", ""))[:200],
                confidence=float(item.get("confidence", 0.5) or 0.5),
            ))
        except Exception as e:
            rep.execution_errors.append(f"theory parse fail: {e}")

    for item in (parsed.get("strategy_patches") or []):
        try:
            rep.strategy_patches.append(StrategyPatch(
                patch_id=str(item.get("patch_id", "")),
                patch_type=str(item.get("patch_type", "PARAMETER")),
                target_module=str(item.get("target_module", "")),
                target_param=item.get("target_param"),
                old_value=item.get("old_value"),
                new_value=item.get("new_value"),
                node_spec=item.get("node_spec"),
                backtest_requirement=str(item.get("backtest_requirement", ""))[:200],
                rationale=str(item.get("rationale", ""))[:200],
                risk_level=str(item.get("risk_level", "MEDIUM")),
                confidence=float(item.get("confidence", 0.5) or 0.5),
            ))
        except Exception as e:
            rep.execution_errors.append(f"patch parse fail: {e}")

    for item in (parsed.get("process_tweaks") or []):
        try:
            rep.process_tweaks.append(ProcessTweak(
                tweak_id=str(item.get("tweak_id", "")),
                category=str(item.get("category", "")),
                current_issue=str(item.get("current_issue", ""))[:300],
                proposed_flow=str(item.get("proposed_flow", ""))[:300],
                affected_stakeholders=[str(x) for x in (item.get("affected_stakeholders") or [])],
                verification_signal=str(item.get("verification_signal", ""))[:200],
                rationale=str(item.get("rationale", ""))[:200],
                confidence=float(item.get("confidence", 0.5) or 0.5),
            ))
        except Exception as e:
            rep.execution_errors.append(f"tweak parse fail: {e}")

    for item in (parsed.get("memory_entries") or []):
        try:
            rep.memory_entries.append(MemoryEntry(
                memory_type=str(item.get("memory_type", "")),
                memory_id=str(item.get("memory_id", "")),
                memory_level=str(item.get("memory_level", "L2")),
                title=str(item.get("title", "")),
                content=str(item.get("content", ""))[:300],
                tags=[str(x) for x in (item.get("tags") or [])],
                confidence=float(item.get("confidence", 0.5) or 0.5),
                generated_at=datetime.now(timezone.utc).isoformat(),
            ))
        except Exception as e:
            rep.execution_errors.append(f"memory parse fail: {e}")

    return rep


# ── 写入记忆（可选落地到 4-MEMORY） ───────────────────────────────────────

def persist_memory_entries(
    entries: List[MemoryEntry],
    memory_root: Optional[str] = None,
    write_flag: str = "dry_run",   # "dry_run" / "proposal_only" / "apply"
) -> Tuple[List[str], List[Dict[str, Any]]]:
    """
    把建议的记忆条目落到 4-MEMORY/ 文件系统

    write_flag:
      - dry_run:     只返回计划，不写文件
      - proposal_only: 写入 proposal 子目录（待人工/回测确认）
      - apply:       直接写入对应层级目录（高风险）
    """
    root = Path(memory_root) if memory_root else DEFAULT_MEMORY_ROOT
    planned: List[Dict[str, Any]] = []
    errors: List[str] = []

    level_map = {
        "L0": "0-元记忆",
        "L1": "1-事实库",
        "L2": "2-案例库",
        "L3": "3-策略库",
        "L4": "4-理论库",
        "L5": "5-模型库",
    }

    for e in entries:
        try:
            level_folder = level_map.get(e.memory_level, "3-策略库")
            folder = root / level_folder

            if write_flag == "proposal_only":
                folder = folder / "_proposals"

            folder.mkdir(parents=True, exist_ok=True)

            # 生成文件名：{memory_id}_{slug}.md
            safe_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", e.memory_id)
            slug = re.sub(r"[^a-zA-Z0-9_\-]", "_", e.title[:20]) or "untitled"
            filename = f"{safe_id}_{slug}.md"
            fpath = folder / filename

            md = f"""---
memory_id: {e.memory_id}
memory_level: {e.memory_level}
memory_type: {e.memory_type}
confidence: {e.confidence:.2f}
tags: {json.dumps(e.tags, ensure_ascii=False)}
generated_at: {e.generated_at or datetime.now(timezone.utc).isoformat()}
---

# {e.title}

{e.content}
"""
            planned.append({"path": str(fpath), "content": md})
            if write_flag == "apply" or write_flag == "proposal_only":
                try:
                    fpath.write_text(md, encoding="utf-8")
                    logger.info(f"[CognitiveEvolution] 写入记忆: {fpath}")
                except Exception as e2:
                    errors.append(f"写文件失败 {fpath}: {e2}")
        except Exception as e:
            errors.append(f"计划写入失败 {e.memory_id}: {e}")

    return errors, planned


# ── 主入口 ────────────────────────────────────────────────────────────────

def evolve(
    recent_trades: Optional[List[Dict[str, Any]]] = None,
    rumination_findings: Optional[List[Dict[str, Any]]] = None,
    a8_governance_report: Optional[Dict[str, Any]] = None,
    cognitive_health: Optional[Dict[str, Any]] = None,
    current_params: Optional[Dict[str, Any]] = None,
    memory_root: Optional[str] = None,
    write_flag: str = "dry_run",
    use_llm: bool = True,
) -> Tuple[EvolutionReport, Dict[str, Any]]:
    """
    认知-理论-实践闭环主入口

    Args:
        recent_trades:         近期交易记录（每笔至少含 pnl_pct/direction/symbol/exit_reason）
        rumination_findings:   反刍引擎输出（pattern_key/observed_rate/baseline_rate/finding_text）
        a8_governance_report:  A8 治理报告 {insights, gaps, proposals}
        cognitive_health:      认知系统状态 {memory_count, quality_distribution, ...}
        current_params:        当前策略关键参数
        memory_root:           4-MEMORY 根目录（默认自动推断）
        write_flag:            dry_run / proposal_only / apply
        use_llm:               是否用千问 LLM

    Returns:
        (EvolutionReport, debug_info)
    """
    recent_trades = recent_trades or []
    rumination_findings = rumination_findings or []
    a8_governance_report = a8_governance_report or {}
    cognitive_health = cognitive_health or {}
    current_params = current_params or {}

    debug = {"llm_used": False, "write_flag": write_flag, "memory_entries_planned": []}

    # Step 1: 调用 LLM 或规则
    parsed = None
    if use_llm:
        prompt = _build_evolution_prompt(
            recent_trades, rumination_findings, a8_governance_report,
            cognitive_health, current_params,
        )
        parsed = _call_llm_evolution(prompt)
        debug["llm_used"] = not parsed.get("fallback", False)
        if parsed.get("error"):
            debug["llm_error"] = parsed["error"]

    if parsed and not parsed.get("fallback"):
        try:
            report = _parse_llm_evolution(parsed)
        except Exception as e:
            logger.warning(f"[CognitiveEvolution] LLM解析异常，降级到规则: {e}")
            report = _rule_fallback_evolution(
                recent_trades, rumination_findings, a8_governance_report, current_params,
            )
    else:
        report = _rule_fallback_evolution(
            recent_trades, rumination_findings, a8_governance_report, current_params,
        )

    # Step 2: 写入记忆（根据 write_flag）
    if report.memory_entries:
        write_errors, planned = persist_memory_entries(
            report.memory_entries, memory_root=memory_root, write_flag=write_flag,
        )
        report.execution_errors.extend(write_errors)
        debug["memory_entries_planned"] = [
            {"path": p["path"], "level": m.memory_level, "title": m.title}
            for p, m in zip(planned, report.memory_entries)
        ]

    return report, debug
