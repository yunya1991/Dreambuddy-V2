"""P0-F 回归测试：中文模型（finbert-tone-chinese）label 映射 + 禁止跨语言 fallback。

缺陷背景：finbert-tone-chinese 只输出 LABEL_0/1/2，而旧 FINBERT_ZH_LABEL_MAP 无任何
LABEL_* 键 → label_map.get() 全落空 → 每条中文 return None → 静默回退 27 关键词规则引擎。
本测试用 fake pipeline 锁定：映射正确、无跨语言 fallback、with_meta=False 保持四键字节兼容。
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engines.sentiment_engine import (  # noqa: E402
    FINBERT_ZH_LABEL_CONTRACTS,
    SentimentEngine,
)

ZH_MODEL_ID = "yiyanghkust/finbert-tone-chinese"


class FakePipe:
    """模拟 transformers text-classification pipeline（tone-chinese 输出 LABEL_0/1/2）。"""

    def __init__(self, label: str, score: float = 0.95):
        self.label = label
        self.confidence = score
        self.calls = []
        self.model = SimpleNamespace(
            config=SimpleNamespace(id2label={0: "LABEL_0", 1: "LABEL_1", 2: "LABEL_2"})
        )

    def __call__(self, text):
        self.calls.append(text)
        return [{"label": self.label, "score": self.confidence}]


def _engine_with_zh(pipe: FakePipe) -> SentimentEngine:
    """注入 fake 中文 pipeline，避免真实下载模型。"""
    engine = SentimentEngine()
    engine._eng_ready = True
    engine._zh_pipe = pipe
    engine._zh_model_id = ZH_MODEL_ID
    engine._zh_label_map.update(engine._build_label_map_from_pipe(pipe, ZH_MODEL_ID))
    return engine


# --------------------------------------------------------------------------
# 1. label 契约：LABEL_0/1/2 必须可解析（缺陷根因）
# --------------------------------------------------------------------------
def test_label_contract_defines_all_three_tone_labels():
    contract = FINBERT_ZH_LABEL_CONTRACTS["finbert-tone-chinese"]
    assert contract == {"LABEL_0": 0.0, "LABEL_1": +1.0, "LABEL_2": -1.0}


def test_label_map_resolves_generic_labels_from_contract():
    engine = SentimentEngine()
    mapping = engine._build_label_map_from_pipe(FakePipe("LABEL_1"), ZH_MODEL_ID)
    assert mapping["LABEL_0"] == 0.0
    assert mapping["LABEL_1"] == +1.0
    assert mapping["LABEL_2"] == -1.0


def test_label_map_warns_when_model_unknown_and_no_contract():
    engine = SentimentEngine()
    with pytest.warns(RuntimeWarning, match="未映射"):
        engine._build_label_map_from_pipe(FakePipe("LABEL_1"), "some-unknown-zh-model")


# --------------------------------------------------------------------------
# 2. 三条已知极性中文句（用 fake 模型输出模拟真实推理）
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("label", "expect_sign", "expect_sentiment"),
    [
        ("LABEL_1", 1, "positive"),  # 利好
        ("LABEL_2", -1, "negative"),  # 利空
        ("LABEL_0", 0, "neutral"),  # 中性
    ],
)
def test_zh_sentences_score_by_model_label(label, expect_sign, expect_sentiment):
    pipe = FakePipe(label, score=0.95)
    engine = _engine_with_zh(pipe)
    text = "宁德时代上半年实现出口约2GWh，同比增加200%以上"
    result = engine.analyze_text(text, with_meta=True)

    if expect_sign > 0:
        assert result["score"] > 0
    elif expect_sign < 0:
        assert result["score"] < 0
    else:
        assert result["score"] == 0.0
    assert result["sentiment"] == expect_sentiment
    assert result["model"] == ZH_MODEL_ID
    assert pipe.calls == [text], "中文文本必须真正进入中文模型"


# --------------------------------------------------------------------------
# 3. 禁止跨语言 fallback：中文模型缺失时回规则，不得调用英文模型
# --------------------------------------------------------------------------
def test_no_cross_language_fallback_when_zh_missing():
    engine = SentimentEngine()
    engine._eng_ready = True
    engine._zh_pipe = None
    en_pipe = FakePipe("POSITIVE", score=0.99)
    engine._en_pipe = en_pipe
    engine._en_model_id = "ProsusAI/finbert"

    result = engine.analyze_text("贝莱德比特币现货ETF单日净流入10亿美元创历史新高", with_meta=True)

    assert en_pipe.calls == [], "中文文本不得被送入英文模型"
    assert result["model"] == "rule_fallback"


# --------------------------------------------------------------------------
# 4. 字节兼容：with_meta=False 仍只返回四键
# --------------------------------------------------------------------------
def test_default_output_keeps_legacy_four_keys():
    engine = _engine_with_zh(FakePipe("LABEL_1"))
    result = engine.analyze_text("公司利润大幅增长，业绩超预期")
    assert set(result) == {"score", "sentiment", "categories", "matches"}


def test_with_meta_adds_model_and_confidence_keys():
    engine = _engine_with_zh(FakePipe("LABEL_2"))
    result = engine.analyze_text("公司因财务造假被立案调查", with_meta=True)
    assert set(result) == {"score", "sentiment", "categories", "matches", "model", "confidence"}
    assert result["model"] == "yiyanghkust/finbert-tone-chinese"
    assert 0.0 <= result["confidence"] <= 1.0
