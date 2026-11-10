"""文章因素抽象抽取器测试 — SPEC-D1-MULTIDIM-STATE §2.5（P0.5 前置门禁）。

三层流水线：
  F1 因素识别：6 大类 → 约 60 细类，输出证据 span
  F2 单因素方向：证据句 ± 上下文窗口内判多空
  F3 多因素合成：按 9 域模块权重加权

验收判据（§7 P0.5）：
  ①文章覆盖率 ≥95% ②平均因素数 ≥3 ③方向可判文章 ≥65%
  ④人工抽查 30 篇准确率 ≥85% ⑤未命中类占比 ≤10%
  本单测覆盖 ①②③⑤ 的机制保证，④ 由人工复核脚本承担。
"""

from data_center.processing.factor_extractor import (
    CATEGORY_WEIGHTS,
    FACTOR_ONTOLOGY,
    extract_article_factors,
    extract_factors,
)

# ── 样例文本 ────────────────────────────────────────────────

FUNDING_TEXT = "当前资金费率已升至0.15%，处于历史高位，多头拥挤，短期回调风险加大。"

MACRO_TEXT = "美联储宣布降息25个基点，流动性宽松有望推动风险资产走强。"

WHALE_TEXT = "链上监测显示巨鲸地址大额转账至交易所，可能带来抛压。"

MULTI_TEXT = "美联储降息叠加ETF净流入，但资金费率过高，技术面RSI出现超买信号。"

NEUTRAL_TEXT = "公司今日发布公告，介绍了产品的功能与团队背景，感谢用户长期支持。"


# ── 本体结构 ────────────────────────────────────────────────


def test_ontology_has_six_categories():
    """本体必须覆盖 6 大类（技术/资金流/链上/宏观/事件/情绪）。"""
    assert set(FACTOR_ONTOLOGY) == {
        "technical",
        "flow",
        "onchain",
        "macro",
        "event",
        "sentiment",
    }


def test_ontology_size_at_least_50_subtypes():
    """细类总数 ≥50（目标 60），每类 ≥8。"""
    total = sum(len(v) for v in FACTOR_ONTOLOGY.values())
    assert total >= 50, f"细类总数不足: {total}"
    for cat, subs in FACTOR_ONTOLOGY.items():
        assert len(subs) >= 8, f"{cat} 细类不足: {len(subs)}"


def test_ontology_every_subtype_has_two_aliases():
    """每个细类 ≥2 个别名，且别名非空字符串。"""
    for cat, subs in FACTOR_ONTOLOGY.items():
        for sub, aliases in subs.items():
            assert len(aliases) >= 2, f"{cat}.{sub} 别名不足: {aliases}"
            assert all(isinstance(a, str) and a.strip() for a in aliases)


def test_factor_id_format():
    """factor_id 格式为 `category.subtype`。"""
    for hit in extract_factors(MACRO_TEXT):
        cat, _, sub = hit["factor_id"].partition(".")
        assert cat in FACTOR_ONTOLOGY and sub, hit["factor_id"]


# ── F1 因素识别 ─────────────────────────────────────────────


def test_extract_funding_factor():
    """资金费率文本 → flow.funding。"""
    ids = {h["factor_id"] for h in extract_factors(FUNDING_TEXT)}
    assert "flow.funding" in ids


def test_extract_macro_rate():
    """美联储降息 → macro.rate。"""
    ids = {h["factor_id"] for h in extract_factors(MACRO_TEXT)}
    assert "macro.rate" in ids


def test_extract_whale():
    """巨鲸大额转账 → flow.whale。"""
    ids = {h["factor_id"] for h in extract_factors(WHALE_TEXT)}
    assert "flow.whale" in ids


def test_multi_factor_cross_categories():
    """多因素文本至少命中 3 个不同大类。"""
    hits = extract_factors(MULTI_TEXT)
    cats = {h["category"] for h in hits}
    assert len(cats) >= 3, f"仅命中类: {cats}"


def test_evidence_span_contains_alias():
    """证据 span 的文本必须包含该细类的某个别名。"""
    for hit in extract_factors(MACRO_TEXT):
        aliases = FACTOR_ONTOLOGY[hit["category"]][hit["factor_id"].split(".", 1)[1]]
        for ev in hit["evidence"]:
            assert any(a in ev["text"] for a in aliases), ev["text"]


def test_longest_alias_wins_no_double_count():
    """长别名优先：'资金费率' 命中后不应再被短别名 '费率' 重复计入其他细类。"""
    hits = extract_factors(FUNDING_TEXT)
    ids = [h["factor_id"] for h in hits]
    assert len(ids) == len(set(ids)), f"factor_id 重复: {ids}"
    # 资金费率整体归属 flow.funding
    assert "flow.funding" in ids


def test_neutral_text_no_factor():
    """无金融因素的文本 → 空列表（不误报）。"""
    assert extract_factors(NEUTRAL_TEXT) == []


# ── F2 方向判定 ─────────────────────────────────────────────


def test_direction_bullish():
    """'降息...走强' → macro.rate 判 bullish。"""
    hits = {h["factor_id"]: h for h in extract_factors(MACRO_TEXT)}
    assert hits["macro.rate"]["direction"] == "bullish"


def test_direction_bearish():
    """'资金费率高位...回调风险' → flow.funding 判 bearish。"""
    hits = {h["factor_id"]: h for h in extract_factors(FUNDING_TEXT)}
    assert hits["flow.funding"]["direction"] == "bearish"


def test_direction_neutral_when_no_direction_word():
    """仅陈述因素无方向词 → neutral。"""
    hits = extract_factors("今日资金费率数据已更新。")
    assert hits and all(h["direction"] == "neutral" for h in hits)


def test_strength_hedged():
    """含 '可能' → strength 为 hedged。"""
    hits = {h["factor_id"]: h for h in extract_factors(WHALE_TEXT)}
    assert hits["flow.whale"]["strength"] == "hedged"


# ── F3 合成 ─────────────────────────────────────────────────


def test_category_weights_cover_all():
    """合成权重覆盖全部 6 大类。"""
    assert set(CATEGORY_WEIGHTS) == set(FACTOR_ONTOLOGY)


def test_article_composite_score_range():
    """合成 score ∈ [-1, 1]，direction 合法。"""
    out = extract_article_factors(MULTI_TEXT, doc_id="odaily:test")
    comp = out["composite"]
    assert -1.0 <= comp["score"] <= 1.0
    assert comp["direction"] in {"bullish", "bearish", "neutral"}
    assert out["doc_id"] == "odaily:test"
    assert out["n_factors"] == len(out["factors"])


def test_article_empty_text():
    """空文本 → 0 因素，direction neutral。"""
    out = extract_article_factors("", doc_id="odaily:empty")
    assert out["n_factors"] == 0
    assert out["composite"]["direction"] == "neutral"


# ── FAIL-OPEN ───────────────────────────────────────────────


def test_non_string_input_no_raise():
    """非字符串输入 FAIL-OPEN 返回空，不抛异常。"""
    assert extract_factors(None) == []
    assert extract_factors(123) == []
    assert extract_factors(["a"]) == []
    out = extract_article_factors(None, doc_id="bad")
    assert out["n_factors"] == 0
