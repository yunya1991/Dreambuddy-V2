"""MultiIntentDetector test suite — RED phase (expects ImportError).

验证三层多意图检测:
    Layer 1: 连接词拆分 (migrated from classifier.py:127 `_detect_multi_intent`)
    Layer 2: 标的级拆分 (text contains multiple stocks → split per target)
    Layer 3: 复合意图 ("深度分析并买入" → [deep_analysis, buy])

TDD RED: 本测试在 multi_intent.py 落地前应全部失败（ImportError）。
"""
import pytest
from pathlib import Path
import sys

# 1-ARCHITECTURE/ → sys.path
BASE = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(BASE))

from dreamos.core.sense.dialogue_intent.multi_intent import MultiIntentDetector


# ============================================================
# 1. 模块/类存在性
# ============================================================

def test_import_module():
    """multi_intent 模块可被导入。"""
    from dreamos.core.sense.dialogue_intent import multi_intent
    assert hasattr(multi_intent, "MultiIntentDetector")


def test_detector_init():
    """MultiIntentDetector 可实例化且暴露 detect 方法。"""
    detector = MultiIntentDetector()
    assert detector is not None
    assert callable(getattr(detector, "detect", None))


def test_detect_signature_returns_list_of_str():
    """detect 返回 List[str]。"""
    detector = MultiIntentDetector()
    result = detector.detect("查询BTC价格")
    assert isinstance(result, list)
    for item in result:
        assert isinstance(item, str)


# ============================================================
# 2. Layer 1: 连接词拆分（迁移自 classifier.py:127）
# ============================================================

def test_detect_single_intent():
    """单意图文本返回单元素列表。"""
    detector = MultiIntentDetector()
    result = detector.detect("查询BTC价格")
    assert result == ["market_query"]


def test_detect_conjunction_split_还有():
    """连接词 '还有' 拆分两个意图。"""
    detector = MultiIntentDetector()
    result = detector.detect("查询BTC价格 还有 分析ETH走势")
    assert len(result) == 2
    assert "market_query" in result
    assert "technical_analysis" in result


def test_detect_all_seven_conjunctions():
    """全部 7 个连接词均能拆分。"""
    detector = MultiIntentDetector()
    conjunctions = ["还有", "顺便", "另外", "以及", "并且", "同时", "再帮我"]
    for conj in conjunctions:
        result = detector.detect(f"查询BTC价格 {conj} 分析ETH走势")
        assert len(result) == 2, f"连接词 '{conj}' 拆分失败: {result}"
        assert "market_query" in result
        assert "technical_analysis" in result


def test_detect_three_way_conjunction_split():
    """三段连接词拆分。"""
    detector = MultiIntentDetector()
    result = detector.detect("查询BTC价格 还有 分析ETH走势 另外 推荐一只股票")
    assert len(result) == 3
    assert "market_query" in result
    assert "technical_analysis" in result
    assert "stock_recommendation" in result


# ============================================================
# 3. Layer 2: 标的级拆分（多 stock 文本）
# ============================================================

def test_detect_target_level_split_multi_stock():
    """文本含多个标的时按标的拆分意图。"""
    detector = MultiIntentDetector()
    # 两个标的 + 两类意图，"和" 作为软分隔符触发 Layer 2 切分
    # "分析BTC走势" 命中 technical_analysis 关键词 "走势"
    # "ETH的买入机会" 命中 buy 关键词 "买入"
    result = detector.detect("分析BTC走势 和 ETH的买入机会")
    assert isinstance(result, list)
    assert "technical_analysis" in result
    assert "buy" in result


def test_detect_target_level_split_with_slots():
    """detect 接受可选 slots 参数（含多 stock 时辅助标的级拆分）。"""
    detector = MultiIntentDetector()
    slots = {"stocks": ["BTC", "ETH"]}
    result = detector.detect("分析走势", slots=slots)
    assert isinstance(result, list)


# ============================================================
# 4. Layer 3: 复合意图（单段文本含多意图）
# ============================================================

def test_detect_compound_analysis_and_buy():
    """复合意图: '深度分析并买入' → [deep_analysis, buy]。"""
    detector = MultiIntentDetector()
    result = detector.detect("深度分析BTC并买入")
    assert "deep_analysis" in result
    assert "buy" in result
    assert len(result) >= 2


def test_detect_compound_recommendation_and_buy():
    """复合意图: '推荐并买入' → [stock_recommendation, buy]。"""
    detector = MultiIntentDetector()
    result = detector.detect("推荐一只股票并买入")
    assert "stock_recommendation" in result
    assert "buy" in result


def test_detect_compound_screen_and_buy():
    """复合意图: '筛选并买入' → [factor_screen, buy]。"""
    detector = MultiIntentDetector()
    result = detector.detect("筛选低市盈率股票并买入")
    assert "factor_screen" in result
    assert "buy" in result


# ============================================================
# 5. 去重保序 / 边界条件
# ============================================================

def test_detect_dedup_preserve_order():
    """重复意图去重并保留首次出现顺序。"""
    detector = MultiIntentDetector()
    # 两段都是 market_query
    result = detector.detect("查询BTC价格 还有 查询ETH价格")
    assert result == ["market_query"]


def test_detect_dedup_with_compound():
    """复合 + 连接词组合去重。"""
    detector = MultiIntentDetector()
    result = detector.detect("深度分析BTC并买入 并且 深度分析ETH")
    # deep_analysis 应只出现一次
    assert result.count("deep_analysis") == 1


def test_detect_empty_input():
    """空输入返回空列表。"""
    detector = MultiIntentDetector()
    assert detector.detect("") == []
    assert detector.detect("   ") == []


def test_detect_no_intent_matched():
    """无匹配意图返回空列表（非 None）。"""
    detector = MultiIntentDetector()
    result = detector.detect("abcd1234随机字符")
    assert isinstance(result, list)
    assert result == []


def test_detect_whitespace_only_segments_filtered():
    """空白段被过滤。"""
    detector = MultiIntentDetector()
    # 连接词拆分后产生空段应被过滤
    result = detector.detect("查询BTC价格 还有    ")
    assert result == ["market_query"]
