"""Phase 4.6 意图路由测试（纯确定性规则，零外部依赖）。

覆盖五分流 + 优先级冲突 + intent_type 覆盖 + 规则版本化。
"""

from __future__ import annotations

import sys
from pathlib import Path

ORCH_DIR = Path(__file__).resolve().parents[1]
if str(ORCH_DIR) not in sys.path:
    sys.path.insert(0, str(ORCH_DIR))

from router import ROUTE_RULES_VERSION, ROUTES, route  # noqa: E402

# ---------- ① 交易执行类 ----------


def test_trade_deny_with_action_and_quantity():
    result = route("帮我买入 100 股茅台")
    assert result["route"] == "trade_deny"
    assert "买入" in result["matched"]
    assert result["version"] == ROUTE_RULES_VERSION


def test_trade_action_without_target_is_not_denied():
    # 只有动作词、无标的/数量 → 不构成交易执行
    assert route("买入策略怎么复盘比较合适")["route"] != "trade_deny"


def test_trade_deny_from_dreamos_intent_type():
    result = route("看看当前行情", intent_type="TREND_FOLLOWING")
    assert result["route"] == "trade_deny"
    assert result["matched"] == ["intent_type=TREND_FOLLOWING"]
    assert "dreamos_intent" in result["reason"]


# ---------- ② 高风险 ----------


def test_high_risk_from_risk_flags():
    result = route("对比两个方案的收益", risk_flags=["杠杆"])
    assert result["route"] == "high_risk_human"
    assert "杠杆" in result["matched"]


def test_high_risk_from_text():
    result = route("要不要全仓押注这个方向")
    assert result["route"] == "high_risk_human"


# ---------- ③ 方案择优 ----------


def test_debate_with_signal_and_criteria():
    result = route("离场模块要不要加波动率自适应阈值，对比一下哪个更好，看回测和成本")
    assert result["route"] == "debate"
    assert "对比" in result["matched"]
    assert "回测" in result["matched"]


def test_debate_signal_without_criteria_falls_to_workers():
    # 有择优信号但无可判定标准 → 不构成 Debate
    assert route("这两个方案哪个更好")["route"] == "workers"


# ---------- ④ 直答 ----------


def test_direct_answer_short_fact_query():
    result = route("查询一下茅台是哪一年上市的")
    assert result["route"] == "direct_answer"
    assert "查询" in result["matched"] or "哪一年" in result["matched"]


def test_direct_answer_excluded_by_judgement_words():
    # 含「优化」判断类标记 → 不算短事实查询
    assert route("查询这个方案怎么优化")["route"] != "direct_answer"


def test_direct_answer_from_dreamos_knowledge_intent():
    result = route("这东西是什么", intent_type="KNOWLEDGE_MATCH")
    assert result["route"] == "direct_answer"
    assert result["matched"] == ["intent_type=KNOWLEDGE_MATCH"]


# ---------- ⑤ 兜底 workers ----------


def test_workers_default():
    result = route("帮我整理一下最近的工程改动")
    assert result["route"] == "workers"
    assert result["matched"] == []


def test_workers_for_unmapped_intent_type():
    assert route("随便聊聊最近的研究", intent_type="UNCERTAIN")["route"] == "workers"


# ---------- 优先级冲突 ----------


def test_priority_trade_beats_high_risk():
    result = route("加杠杆卖出 200 股", risk_flags=["杠杆"])
    assert result["route"] == "trade_deny"


def test_priority_high_risk_beats_debate():
    result = route("对比两个方案的杠杆收益，看回测指标", risk_flags=["全仓"])
    assert result["route"] == "high_risk_human"


def test_priority_high_risk_beats_mapped_query_intent():
    result = route("查询一下杠杆是什么", intent_type="KNOWLEDGE_MATCH")
    assert result["route"] == "high_risk_human"


def test_routes_are_versioned_and_complete():
    result = route("帮我整理一下最近的工程改动")
    assert set(ROUTES) == {
        "trade_deny",
        "high_risk_human",
        "debate",
        "workers",
        "direct_answer",
    }
    assert result["version"] == "r9-v1"
