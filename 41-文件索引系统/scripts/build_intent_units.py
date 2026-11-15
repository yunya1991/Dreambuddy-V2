#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_intent_units.py — 从 golden set 生成 intent_units 目录（P0）

读取 34-前端应用训练系统/l1_intent_golden.jsonl，按意图分组写入：
  intent_units/{intent}/intent.yaml
  intent_units/{intent}/examples_zh.jsonl
  intent_units/{intent}/negatives_zh.jsonl  （unknown OOS 反例 + 其他意图正例，上限 80）

意图元数据（category/keywords）从 l1-intent-registry.ts 解析或使用默认值。
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_INDEX_ROOT = _HERE.parent
_GOLDEN = _INDEX_ROOT.parent / "34-前端应用训练系统" / "l1_intent_golden.jsonl"
_UNITS_DIR = _INDEX_ROOT / "intent_units"

# 每个意图反例上限：unknown OOS（≤40）+ 跨意图正例，共 80 条
NEGATIVE_CAP = 80

# 意图类别与关键词（与 l1-intent-registry.ts 对齐）
INTENT_META = {
    "data_query": ("data", "数据查询,最新值,原始数据"),
    "data_insight": ("insight", "洞察,分析,解读,趋势"),
    "doc_search": ("search", "文档,搜索,查找,资料"),
    "price_query": ("data", "价格,现价,多少钱,报价"),
    "metric_series": ("data", "指标,序列,走势,历史"),
    "stat_query": ("deterministic", "统计,算法,回撤,波动率"),
    "technical_indicator": ("deterministic", "技术指标,MACD,RSI,均线"),
    "technical_analysis": ("analysis", "技术分析,K线,形态"),
    "fundamental_valuation": ("analysis", "估值,基本面,PE,PB"),
    "leader_compare": ("deterministic", "龙头,对比,比较"),
    "top_correlation": ("deterministic", "相关性,联动,相关"),
    "persistence_strength": ("deterministic", "持续性,Hurst,强度"),
    "whale_flow": ("deterministic", "巨鲸,大资金,流向"),
    "calendar_event": ("deterministic", "日历,事件,议息,FOMC"),
    "event_line_query": ("analysis", "事件线,时间线,大事"),
    "event_analysis": ("analysis", "事件分析,影响,解读"),
    "path_insight": ("insight", "路径,推演,情景"),
    "contradiction_insight": ("insight", "矛盾,背离,冲突"),
    "asset_class_trend": ("analysis", "大类资产,趋势,配置"),
    "risk_control": ("analysis", "风控,止损,仓位,风险"),
    "event_listing": ("data", "事件,快讯,新闻,动态"),
}

# 执行器规范与边界条件。文档由本脚本生成，查询时由 IntentDocRetriever 按需加载。
EXECUTOR_SPECS = {
    "data_query": (
        "exec_data_query",
        "L0 datacenter.record",
        "无法识别数据源时请求澄清；source_missing 或读取异常时降级。",
    ),
    "data_insight": (
        "exec_data_insight",
        "INSIGHT_KNOWLEDGE",
        "仅解释已登记指标与变化模式；无知识命中时明确返回暂无解读。",
    ),
    "doc_search": (
        "L1 无执行器，交 41 检索链路",
        "41 L1/L2/L3 混合召回",
        "doc_search 不在 l1_route_signal 直接执行；检索失败不得阻塞 L2 交接。",
    ),
    "price_query": (
        "exec_price_query",
        "L0 market.ticker，失败后回查 18 中心",
        "无法识别标的时请求澄清；不得静默默认 BTC；行情异常时降级。",
    ),
    "metric_series": (
        "exec_metric_series",
        "L0 datacenter.series",
        "仅查询 54 序列注册表可解析指标；无序列或数据不足时如实返回。",
    ),
    "stat_query": (
        "exec_stat_query",
        "54 l1agg.capabilities.run_capability",
        "沿用能力层 min_n 与 quality 门禁；样本不足不得伪造统计结论。",
    ),
    "technical_indicator": (
        "exec_technical_indicator",
        "L0 market.candles → 54 l1agg.technical.analyze",
        "OHLC 不全或样本不足时返回 gate；不得伪造高低点和指标值。",
    ),
    "technical_analysis": (
        "exec_technical_analysis",
        "L0 yijing.bcrm2",
        "无汇总或标的无法解析时请求澄清；快照读取失败时降级。",
    ),
    "fundamental_valuation": (
        "exec_fundamental_valuation",
        "L0 yijing.bdsm",
        "仅使用 available 的币种快照；无快照时不生成估值结论。",
    ),
    "leader_compare": (
        "exec_leader_compare",
        "_leader_gap",
        "至少识别一个资产，否则请求澄清；关系/对齐/价格异常时降级。",
    ),
    "top_correlation": (
        "exec_top_correlation",
        "_top_correlated",
        "至少识别一个资产，否则请求澄清；沿用 Pearson + BH-FDR 与样本门禁。",
    ),
    "persistence_strength": (
        "exec_persistence_strength",
        "_persistence_strength",
        "至少识别一个资产，否则请求澄清；数据关系异常时不输出强度结论。",
    ),
    "whale_flow": (
        "exec_whale_flow",
        "L0 datacenter.series",
        "仅输出已解析巨鲸指标；数据不可用或为空时明确降级。",
    ),
    "calendar_event": (
        "exec_calendar_event",
        "L0 datacenter.events",
        "仅返回事件日程；事件源不可用或为空时不得编造日期。",
    ),
    "event_line_query": (
        "L1 无执行器，交 L2",
        "事件线数据由下游链路消费",
        "保留 intent hint；不得复用 event_analysis 冒充时间线执行器。",
    ),
    "event_analysis": (
        "exec_event_analysis",
        "L0 event.state",
        "无事件驱动信号时明确返回；状态读取失败时降级。",
    ),
    "path_insight": (
        "exec_path_insight",
        "L0 evolution.snapshot",
        "快照为空或标的无法解析时请求澄清；不得猜测最小阻力路径。",
    ),
    "contradiction_insight": (
        "exec_contradiction_insight",
        "L0 evolution.contradiction",
        "仅解读日志已记录维度；无矛盾记录或读取失败时如实返回。",
    ),
    "asset_class_trend": (
        "exec_asset_class_trend",
        "L0 yijing.strategic",
        "仅输出战略层日志中的资产状态；无记录时不生成趋势结论。",
    ),
    "risk_control": (
        "exec_risk_control",
        "L0 riskcontrol.trailing",
        "仅输出最新持仓风控状态；无日志或评估记录时不得给出风控指令。",
    ),
    "event_listing": (
        "L1 无执行器，交 L2",
        "事件/快讯列表由下游链路消费",
        "保留 intent hint；不得复用 calendar_event 冒充新闻罗列。",
    ),
}


def _executor_doc(intent_id: str) -> str:
    entry, source, boundary = EXECUTOR_SPECS[intent_id]
    return (
        f"# {intent_id} 执行器规范\n\n"
        f"- 执行入口：`{entry}`。\n"
        f"- 数据/能力链路：{source}。\n\n"
        "## 边界条件\n\n"
        f"- {boundary}\n"
        "- 执行异常与数据缺失遵循现有执行器 FAIL-OPEN，不阻塞 L1 路由。\n"
        "- 完整正例/反例位于同目录 JSONL，仅在本单元被 retrieve 时加载。\n"
    )


def main():
    if not _GOLDEN.exists():
        print(f"golden set 不存在: {_GOLDEN}", file=sys.stderr)
        sys.exit(1)

    # 读取 golden set
    examples = defaultdict(list)
    with open(_GOLDEN, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            intent = obj.get("intent", "")
            msg = obj.get("message", "").strip()
            if intent and msg:
                examples[intent].append(msg)

    _UNITS_DIR.mkdir(parents=True, exist_ok=True)
    total = 0
    registered_intents = set(INTENT_META) | (set(examples) - {"unknown"})
    for intent in sorted(registered_intents):
        msgs = examples.get(intent, [])
        intent_dir = _UNITS_DIR / intent
        intent_dir.mkdir(parents=True, exist_ok=True)

        # intent.yaml
        category, keywords = INTENT_META.get(intent, ("general", ""))
        (intent_dir / "intent.yaml").write_text(
            f"id: {intent}\ncategory: {category}\nkeywords: {keywords}\n",
            encoding="utf-8",
        )
        (intent_dir / "executor.md").write_text(_executor_doc(intent), encoding="utf-8")

        # examples_zh.jsonl
        with open(intent_dir / "examples_zh.jsonl", "w", encoding="utf-8") as f:
            for msg in msgs:
                f.write(json.dumps({"message": msg}, ensure_ascii=False) + "\n")

        # negatives_zh.jsonl: 反例 = unknown OOS 示例（不应命中任何 L1 意图）
        #           + 其他意图的正例（跨意图区分）。
        # unknown 反例优先级最高（true L2-bound query），全部纳入；
        # 跨意图正例补足至 NEGATIVE_CAP 条。
        unknown_msgs = examples.get("unknown", [])
        cross_intent = []
        for other_intent, other_msgs in examples.items():
            if other_intent == intent or other_intent == "unknown":
                continue
            cross_intent.extend(other_msgs)
        negatives = list(unknown_msgs) + cross_intent
        negatives = negatives[:NEGATIVE_CAP]
        with open(intent_dir / "negatives_zh.jsonl", "w", encoding="utf-8") as f:
            for msg in negatives:
                f.write(json.dumps({"message": msg}, ensure_ascii=False) + "\n")

        print(f"  {intent:30s} examples={len(msgs):3d} negatives={len(negatives):3d}")
        total += 1

    print(f"\n共生成 {total} 个意图目录 → {_UNITS_DIR}")


if __name__ == "__main__":
    main()
