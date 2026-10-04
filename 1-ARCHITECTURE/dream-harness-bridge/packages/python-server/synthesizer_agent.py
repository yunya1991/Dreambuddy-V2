#!/usr/bin/env python3
"""SynthesizerAgent — 聚合层 LLM 综合器

将 aggregator 聚合结果经 LLM 综合重写为 insight/recommendation 卡片,
供前端 InsightCard.tsx + RecommendationCard.tsx 渲染。

设计原则:
  - FAIL-OPEN: 无 llm_fn → _rule_based_synthesis 规则降级; 异常 → 返回空列表
  - 认知闭环: cognitive_adapter.recall() 检索历史综合经验 → record() 记录新结果
  - signals_ref / charts_ref 引用已聚合数据, 不重新生成
  - 与 aggregator.py 解耦: synthesize(aggregated_dict) → List[SynthesizedCard]
"""
from __future__ import annotations

import json
import re
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


# ============================================================
# 数据结构
# ============================================================

@dataclass
class SynthesizedCard:
    """LLM 综合后的卡片 (insight | recommendation)

    card_type:
        - "insight": 洞察性结论 (信号共识 / 矛盾点 / 趋势观察)
        - "recommendation": 行动建议 (关注 / 规避 / 调整仓位)
    signals_ref / charts_ref: 引用聚合结果, 不重新生成原始数据
    """
    card_type: str  # "insight" | "recommendation"
    title: str
    content: str
    signals_ref: List[dict] = field(default_factory=list)
    charts_ref: List[dict] = field(default_factory=list)
    confidence: float = 0.0
    source_modules: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "card_type": self.card_type,
            "title": self.title,
            "content": self.content,
            "signals_ref": self.signals_ref,
            "charts_ref": self.charts_ref,
            "confidence": self.confidence,
            "source_modules": self.source_modules,
        }


# ============================================================
# SynthesizerAgent
# ============================================================

class SynthesizerAgent:
    """聚合层 LLM 综合器

    用法:
        agent = SynthesizerAgent(llm_fn=my_llm, cognitive_adapter=adapter)
        cards = agent.synthesize(aggregated_dict)
    """

    # LLM 返回 JSON 解析失败的降级阈值
    CONF_RULE_FALLBACK = 0.40

    def __init__(
        self,
        llm_fn: Optional[Callable[[str], str]] = None,
        cognitive_adapter: Optional[Any] = None,
    ):
        """初始化综合器

        Args:
            llm_fn: LLM 调用函数 (prompt: str) -> str, 返回 JSON 字符串.
                None 时走 _rule_based_synthesis 规则降级 (FAIL-OPEN).
            cognitive_adapter: 认知适配器, 需有 recall(context, top_k, min_quality)
                和 record(content, tags, quality_level). None 时跳过认知闭环.
        """
        self._llm_fn = llm_fn
        self._cognitive = cognitive_adapter

    # ── 主入口 ──────────────────────────────────────────

    def synthesize(self, aggregated: Dict[str, Any]) -> List[SynthesizedCard]:
        """综合聚合结果为卡片列表

        Args:
            aggregated: aggregator.aggregate_subagent_outputs() 返回值,
                包含 summaries / all_signals / all_charts / modules /
                consensus_direction / avg_confidence / top_signals

        Returns:
            List[SynthesizedCard]: insight + recommendation 卡片
        """
        if not aggregated or not aggregated.get("summaries"):
            return []

        # 认知闭环 Step 1: recall 检索历史综合经验 (FAIL-OPEN)
        recalled = self._recall(aggregated)

        # LLM 综合或规则降级
        if self._llm_fn is None:
            cards = self._rule_based_synthesis(aggregated, recalled)
        else:
            try:
                cards = self._llm_synthesis(aggregated, recalled)
            except Exception:  # noqa: BLE001 FAIL-OPEN
                cards = self._rule_based_synthesis(aggregated, recalled)

        # 认知闭环 Step 2: record 记录本次综合 (FAIL-OPEN)
        if cards:
            self._record_synthesis(aggregated, cards)

        return cards

    # ── LLM 路径 ────────────────────────────────────────

    def _llm_synthesis(
        self,
        aggregated: Dict[str, Any],
        recalled: List[Dict[str, Any]],
    ) -> List[SynthesizedCard]:
        """LLM 综合路径: 构建 prompt → 调用 LLM → 解析 JSON → SynthesizedCard"""
        prompt = self._build_prompt(aggregated, recalled)
        resp = self._llm_fn(prompt)  # type: ignore[misc]
        parsed = self._parse_llm_response(resp)
        return self._build_cards_from_parsed(parsed, aggregated)

    def _build_prompt(
        self,
        aggregated: Dict[str, Any],
        recalled: List[Dict[str, Any]],
    ) -> str:
        """构建 LLM prompt — 要求输出结构化深度分析报告"""
        summaries = aggregated.get("summaries", [])
        top_signals = aggregated.get("top_signals", [])
        consensus = aggregated.get("consensus_direction", "neutral")
        avg_conf = aggregated.get("avg_confidence", 0.0)
        modules = aggregated.get("modules", [])
        charts = aggregated.get("all_charts", [])
        raw_data = aggregated.get("raw_data_by_module", {})

        # 图表摘要 (供 LLM 引用)
        chart_titles = [c.get("title", "") for c in charts if c.get("title")]

        # 各模块原始指标数据 (LLM 深度分析的核心素材)
        raw_data_text = ""
        for mod, data in raw_data.items():
            if isinstance(data, dict) and data:
                indicators = data.get("indicators", data)
                raw_data_text += f"\n[{mod}模块原始数据]\n"
                raw_data_text += json.dumps(indicators, ensure_ascii=False, indent=2)[:1500]
                raw_data_text += "\n"

        recalled_text = ""
        if recalled:
            recalled_text = "\n历史经验参考:\n" + "\n".join(
                f"- {m.get('content', '')[:200]}" for m in recalled[:3]
            )

        return f"""你是一位资深加密货币分析师. 请基于以下多维度数据, 撰写一份结构化深度分析报告.

【输入摘要 (按模块)】
{chr(10).join(f'- [{m}] {s}' for m, s in zip(modules, summaries))}

【Top 信号 (按置信度降序)】
{json.dumps(top_signals, ensure_ascii=False, indent=2)}

【各模块原始指标数据】
{raw_data_text}

【共识方向】: {consensus} | 【平均置信度】: {avg_conf:.2f} | 【参与模块】: {modules}
【可用图表】: {chart_titles if chart_titles else '无'}
{recalled_text}

【输出要求】
输出严格 JSON 格式 (不要 markdown 代码块). 结构如下:
{{
  "insights": [
    {{
      "title": "报告章节标题",
      "content": "本章正文 (支持多段落, 用换行分隔)",
      "severity": "info|warning|critical"
    }}
  ],
  "recommendations": [
    {{
      "action": "行动建议标题",
      "reason": "建议理由",
      "priority": "low|medium|high"
    }}
  ]
}}

【报告章节建议 (insights, 按顺序输出)】
1. "最新数据概览" — 用表格或列表列出关键指标最新值 (价格/涨跌幅/成交量/市值/RSI/MVRV/恐惧贪婪等), 标注数据来源模块. 数据缺失的指标标注"数据不足".
2. "核心判定" — 一句话给出当前市场状态判定 (如"缩量洗盘+高位盘整"而非"弱势回调"), 并说明判定的核心逻辑.
3. "判定依据" — 分点列出支持判定的关键证据, 每个证据需引用具体数据 (如"成交量从X萎缩到Y, 缩量X%"). 覆盖: 技术面(趋势/动量/量能)、链上(算力/巨鲸/交易所储备)、资金流(ETF/聪明钱)、基本面(估值/催化剂)、情绪面(恐惧贪婪/新闻).
4. "风险提示" — 列出需要警惕的风险点, 每个风险需引用具体数据 (如"交易所储备创新高X枚, 潜在卖压扩大").
5. "关键价位" — 列出支撑位和阻力位及含义 (如"9.40-9.46 震荡下沿, 跌破则弱势信号增强").
6. "结论与展望" — 总结核心逻辑, 给出情景推演 (如"放量突破X则上攻概率提升; 跌破Y且放量则需重新评估").

【写作要求】
- 必须使用提供的原始数据中的具体数值, 禁止编造数据.
- 数据不足的维度明确标注"数据不足", 不要强行下结论.
- 正文用中文, 逻辑清晰, 论据充分, 每个论点都有数据支撑.
- insights 至少 3 条, 不超过 6 条; recommendations 1-2 条.
- 每条 content 控制在 500 字以内, 但要包含足够的数据细节.
"""

    def _parse_llm_response(self, resp: str) -> Dict[str, Any]:
        """解析 LLM 返回的 JSON

        容错处理:
        - 去除可能的 markdown 代码块包裹
        - 尝试提取首个 JSON 对象
        - 失败时返回空结构
        """
        text = resp.strip()
        # 去除 markdown 代码块
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        # 尝试解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # 尝试提取首个 JSON 对象
            match = re.search(r"\{[\s\S]*\}", text)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass
        return {"insights": [], "recommendations": []}

    def _build_cards_from_parsed(
        self,
        parsed: Dict[str, Any],
        aggregated: Dict[str, Any],
    ) -> List[SynthesizedCard]:
        """从解析后的 JSON 构建 SynthesizedCard 列表"""
        cards: List[SynthesizedCard] = []
        modules = aggregated.get("modules", [])
        top_signals = aggregated.get("top_signals", [])
        charts = aggregated.get("all_charts", [])
        avg_conf = aggregated.get("avg_confidence", 0.0)

        for ins in parsed.get("insights", []):
            cards.append(SynthesizedCard(
                card_type="insight",
                title=ins.get("title", "洞察"),
                content=ins.get("content", ""),
                signals_ref=top_signals,
                charts_ref=charts,
                confidence=avg_conf,
                source_modules=modules,
            ))

        for rec in parsed.get("recommendations", []):
            action = rec.get("action", "建议")
            reason = rec.get("reason", "")
            cards.append(SynthesizedCard(
                card_type="recommendation",
                title=action,
                content=reason,
                signals_ref=top_signals,
                charts_ref=charts,
                confidence=avg_conf,
                source_modules=modules,
            ))

        return cards

    # ── 规则降级路径 (FAIL-OPEN) ────────────────────────

    def _rule_based_synthesis(
        self,
        aggregated: Dict[str, Any],
        recalled: List[Dict[str, Any]],
    ) -> List[SynthesizedCard]:
        """规则降级综合 (无 LLM 或 LLM 异常时)

        基于 consensus_direction + top_signals 拼装模板卡片
        """
        summaries = aggregated.get("summaries", [])
        top_signals = aggregated.get("top_signals", [])
        charts = aggregated.get("all_charts", [])
        consensus = aggregated.get("consensus_direction", "neutral")
        avg_conf = aggregated.get("avg_confidence", 0.0)
        modules = aggregated.get("modules", [])
        long_count = aggregated.get("long_count", 0)
        short_count = aggregated.get("short_count", 0)

        cards: List[SynthesizedCard] = []

        # Insight 卡片: 共识方向观察
        if consensus == "long":
            insight_title = "多头共识信号"
            insight_content = (
                f"多源 subagent (modules={modules}) 共识偏多, "
                f"long 信号 {long_count} 条, short 信号 {short_count} 条. "
                f"平均置信度 {avg_conf:.2f}."
            )
        elif consensus == "short":
            insight_title = "空头共识信号"
            insight_content = (
                f"多源 subagent (modules={modules}) 共识偏空, "
                f"short 信号 {short_count} 条, long 信号 {long_count} 条. "
                f"平均置信度 {avg_conf:.2f}."
            )
        else:
            insight_title = "多空均衡观察"
            insight_content = (
                f"多源 subagent (modules={modules}) 信号多空均衡, "
                f"long={long_count}, short={short_count}. "
                f"平均置信度 {avg_conf:.2f}, 建议观望."
            )

        cards.append(SynthesizedCard(
            card_type="insight",
            title=insight_title,
            content=insight_content,
            signals_ref=top_signals,
            charts_ref=charts,
            confidence=avg_conf,
            source_modules=modules,
        ))

        # Recommendation 卡片: 基于 consensus 给出行动建议
        if consensus == "long":
            rec_action = "关注做多机会"
            rec_reason = "多源共识偏多, 可关注顺势做多机会"
        elif consensus == "short":
            rec_action = "关注做空机会"
            rec_reason = "多源共识偏空, 可关注顺势做空机会"
        else:
            rec_action = "保持观望"
            rec_reason = "多空信号均衡, 等待方向明确后再行动"

        cards.append(SynthesizedCard(
            card_type="recommendation",
            title=rec_action,
            content=rec_reason,
            signals_ref=top_signals,
            charts_ref=charts,
            confidence=avg_conf,
            source_modules=modules,
        ))

        return cards

    # ── 认知闭环 ────────────────────────────────────────

    def _recall(self, aggregated: Dict[str, Any]) -> List[Dict[str, Any]]:
        """检索历史综合经验 (FAIL-OPEN)"""
        if self._cognitive is None:
            return []
        try:
            consensus = aggregated.get("consensus_direction", "neutral")
            context = f"synthesizer,共识={consensus},聚合层综合"
            return self._cognitive.recall(
                context=context, top_k=5, min_quality="C"
            )
        except Exception:  # noqa: BLE001 FAIL-OPEN
            return []

    def _record_synthesis(
        self,
        aggregated: Dict[str, Any],
        cards: List[SynthesizedCard],
    ) -> None:
        """记录本次综合到认知库 (FAIL-OPEN)"""
        if self._cognitive is None:
            return
        try:
            consensus = aggregated.get("consensus_direction", "neutral")
            avg_conf = aggregated.get("avg_confidence", 0.0)
            card_types = [c.card_type for c in cards]
            content = (
                f"[聚合层综合] consensus={consensus}, "
                f"avg_conf={avg_conf:.2f}, "
                f"产出 {len(cards)} 卡片 (types={card_types}), "
                f"modules={aggregated.get('modules', [])}"
            )
            self._cognitive.record(
                content=content,
                tags="synthesizer,聚合层,综合",
                quality_level="C",
            )
        except Exception:  # noqa: BLE001 FAIL-OPEN
            pass


# ============================================================
# IPC handler (供 server.py 路由)
# ============================================================

def handle_synthesizer_agent(params: dict) -> dict:
    """IPC handler: synthesizer_agent 综合器

    参数:
        aggregated: 聚合结果 (aggregator.aggregate_subagent_outputs 返回值)

    返回:
        {ok: True, cards: [...]} 或 {ok: False, error: ...}
    """
    try:
        aggregated = params.get("aggregated", {})
        agent = SynthesizerAgent()  # 生产环境注入 llm_fn / cognitive_adapter
        cards = agent.synthesize(aggregated)
        return {
            "ok": True,
            "cards": [c.to_dict() for c in cards],
        }
    except Exception as e:
        stack = traceback.format_exc()
        return {"ok": False, "error": str(e), "stack": stack}
