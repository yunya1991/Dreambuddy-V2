"""NPE v0（R1 规则版）叙事命题抽取器测试 — SPEC-D1-NARRATIVE-PRIMITIVES §2.3。

命题 schema：{proposition_id, condition_event, event_type, market_state_qualifier,
  conclusion{direction,target_scope,magnitude_hint}, time_window,
  confidence_in_text, evidence_spans, extractor_version}
"""

from data_center.processing.npe_rules import extract_propositions

# ── 样例文本 ────────────────────────────────────────────────

CAUSAL_TEXT = "美联储降息50bp将推动BTC和ETH上涨，因为流动性宽松意味着风险资产估值提升。"

CONDITIONAL_TEXT = (
    "如果资金费率超过0.1%且持仓量创新高，那么短期回调的概率较大，历史数据验证了这一规律。"
)

BEARISH_TEXT = "Mt.Gox赔付解锁大量BTC，抛压增加将导致价格下跌。"

HEDGED_TEXT = "ETF获批可能会刺激市场情绪，BTC或将走强。"

PLAIN_TEXT = "今日天气晴朗，公司召开年会，大家很开心。"


# ── 测试 ────────────────────────────────────────────────────


def test_causal_proposition_basic_fields():
    """因果命题：条件事件 + 方向 + 标的。"""
    props = extract_propositions(CAUSAL_TEXT, doc_id="odaily:t1")
    assert len(props) >= 1
    p = props[0]
    assert p["condition_event"]
    assert "降息" in p["condition_event"]
    assert p["conclusion"]["direction"] == "bullish"
    assert "BTC" in p["conclusion"]["target_scope"]
    assert p["extractor_version"].startswith("npe-v0")
    assert p["proposition_id"].startswith("NP-")


def test_conditional_pattern_bearish():
    """条件模式：触发词'如果/若' + bearish 方向。"""
    props = extract_propositions(CONDITIONAL_TEXT, doc_id="odaily:t2")
    assert len(props) >= 1
    p = props[0]
    assert p["conclusion"]["direction"] == "bearish"
    assert "费率" in p["condition_event"] or "持仓" in p["condition_event"]


def test_bearish_unlock_event():
    props = extract_propositions(BEARISH_TEXT, doc_id="odaily:t3")
    assert len(props) >= 1
    p = props[0]
    assert p["conclusion"]["direction"] == "bearish"
    assert "BTC" in p["conclusion"]["target_scope"]


def test_hedged_confidence():
    """含'可能/或将' → confidence_in_text = hedged。"""
    props = extract_propositions(HEDGED_TEXT, doc_id="odaily:t4")
    assert len(props) >= 1
    assert props[0]["confidence_in_text"] == "hedged"


def test_strong_confidence_default():
    """无对冲词 → strong。"""
    props = extract_propositions(CAUSAL_TEXT, doc_id="odaily:t5")
    assert props[0]["confidence_in_text"] == "strong"


def test_no_trigger_no_proposition():
    """无因果/条件触发词 → 空列表（召回优先，错抽禁止）。"""
    props = extract_propositions(PLAIN_TEXT, doc_id="odaily:t6")
    assert props == []


def test_evidence_spans_offsets():
    """evidence_spans 的 start/end 必须能切回原文子串。"""
    props = extract_propositions(CAUSAL_TEXT, doc_id="odaily:t7")
    p = props[0]
    assert p["evidence_spans"]
    sp = p["evidence_spans"][0]
    assert sp["doc_id"] == "odaily:t7"
    seg = CAUSAL_TEXT[sp["start"] : sp["end"]]
    assert len(seg) > 0
    assert "降息" in seg or "上涨" in seg


def test_schema_completeness():
    """命题包含 schema 全部必需字段。"""
    props = extract_propositions(CAUSAL_TEXT, doc_id="odaily:t8")
    p = props[0]
    for k in (
        "proposition_id",
        "condition_event",
        "event_type",
        "market_state_qualifier",
        "conclusion",
        "time_window",
        "confidence_in_text",
        "evidence_spans",
        "extractor_version",
    ):
        assert k in p, k
    for k in ("direction", "target_scope", "magnitude_hint"):
        assert k in p["conclusion"], k


def test_failopen_on_bad_input():
    """FAIL-OPEN：None/非字符串输入不抛异常，返回空列表。"""
    assert extract_propositions(None, doc_id="x") == []
    assert extract_propositions(12345, doc_id="x") == []
    assert extract_propositions("", doc_id="x") == []


def test_short_condition_filtered():
    """条件事件过短（如'这'/'其冲'碎片）→ 不发射，precision 护栏。"""
    junk = "这将导致下跌。其冲推动上涨。"
    assert extract_propositions(junk, doc_id="odaily:t10") == []


def test_time_window_extraction():
    """时间窗线索：'短期' → 非空 time_window。"""
    props = extract_propositions(CONDITIONAL_TEXT, doc_id="odaily:t9")
    assert props[0]["time_window"]
