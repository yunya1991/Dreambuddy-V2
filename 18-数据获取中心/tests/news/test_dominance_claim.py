"""DominanceClaim（F3 主张提取）测试 — SPEC-D1-MULTIDIM-STATE §2.5.1 / D8。

F3 是主张提取，不是信号合成：
  - 输出 dominant_factor / dominant_dimension / direction / horizon
  - urgency（时间窗映射）/ impact（因素类先验）
  - salience_distribution（8 维软标签，和为 1）
"""

from __future__ import annotations

import pytest
from data_center.processing.factor_extractor import extract_dominance_claim

ALL_DIMS = {"D1", "D2", "D3", "D4", "C6", "C7", "C8", "NEWS"}

FLOW_DOMINANT = (
    "资金费率持续攀升至0.18%，资金费率处于极端高位，多头拥挤。"
    "资金费率高企意味着短期回调压力显著加大，本周需警惕去杠杆。"
    "技术面RSI同时显示超买。"
)

MACRO_DOMINANT = (
    "美联储本周宣布降息25个基点，流动性宽松推动风险资产走强。" "美联储的表态是本轮反弹的核心驱动。"
)


def test_claim_returns_required_fields():
    c = extract_dominance_claim(FLOW_DOMINANT, doc_id="doc-1")
    for k in (
        "claim_type",
        "dominant_factor",
        "dominant_dimension",
        "direction",
        "horizon",
        "confidence_in_text",
        "urgency",
        "impact",
        "salience_distribution",
        "supporting_factors",
        "opposing_factors",
        "evidence_spans",
    ):
        assert k in c
    assert c["claim_type"] == "dominance"
    assert c["doc_id"] == "doc-1"


def test_dominant_factor_is_flow_funding():
    c = extract_dominance_claim(FLOW_DOMINANT)
    assert c["dominant_factor"].startswith("flow.")
    assert c["dominant_dimension"] == "D2"
    assert c["direction"] == "bearish"


def test_macro_maps_to_d1():
    c = extract_dominance_claim(MACRO_DOMINANT)
    assert c["dominant_dimension"] == "D1"
    assert c["direction"] == "bullish"


def test_salience_distribution_sums_to_one():
    c = extract_dominance_claim(FLOW_DOMINANT)
    dist = c["salience_distribution"]
    assert set(dist) == ALL_DIMS
    assert abs(sum(dist.values()) - 1.0) < 1e-6


def test_urgency_from_time_window():
    c = extract_dominance_claim(FLOW_DOMINANT)  # "本周" → days
    assert c["horizon"] == "days"
    assert c["urgency"] == pytest.approx(0.6)

    intraday = "资金费率飙升，日内多头面临强平风险，可能快速下跌。"
    c2 = extract_dominance_claim(intraday)
    assert c2["horizon"] == "intraday"
    assert c2["urgency"] == pytest.approx(0.9)


def test_impact_from_category_prior():
    c = extract_dominance_claim(FLOW_DOMINANT)
    assert c["impact"] == pytest.approx(1.5)


def test_neutral_text_has_no_dominant():
    c = extract_dominance_claim("该公司今日发布公告，介绍了产品功能与团队背景，感谢用户支持。")
    assert c["dominant_factor"] is None
    assert c["dominant_dimension"] is None
    assert c["direction"] == "neutral"
    assert abs(sum(c["salience_distribution"].values())) < 1e-9


def test_fail_open_on_non_string():
    assert extract_dominance_claim(None)["dominant_factor"] is None
    assert extract_dominance_claim(123)["direction"] == "neutral"
