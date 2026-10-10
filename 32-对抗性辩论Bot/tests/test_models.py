"""test_models.py — 数据模型单元测试（TDD RED phase）

测试 SPEC 中定义的全部数据模型：
- Argument: 辩手结构化输出
- Turn: 单轮发言记录
- Verdict: 裁判裁决
- MarketingMaterial: 营销素材
- DebateQualityScore: 质量评分
- DebateResult: 辩论完整结果
"""
from __future__ import annotations

from datetime import datetime

import pytest

from core.models import (
    Argument,
    Turn,
    Verdict,
    MarketingMaterial,
    DebateQualityScore,
    DebateResult,
)


# ─── Argument ──────────────────────────────────────────────────────

class TestArgument:
    """辩手结构化输出契约。"""

    def test_create_basic(self):
        arg = Argument(
            thesis="BTC 是数字黄金",
            arguments=["稀缺性 2100万枚", "机构持续买入"],
            quote="数字时代的诺克斯堡",
            confidence=0.85,
            raw='{"thesis": "BTC 是数字黄金", ...}',
        )
        assert arg.thesis == "BTC 是数字黄金"
        assert len(arg.arguments) == 2
        assert arg.quote == "数字时代的诺克斯堡"
        assert arg.confidence == 0.85
        assert "thesis" in arg.raw

    def test_confidence_range(self):
        """confidence 应在 0-1 范围。"""
        arg = Argument(thesis="t", arguments=[], quote="q", confidence=0.0, raw="")
        assert arg.confidence == 0.0

        arg2 = Argument(thesis="t", arguments=[], quote="q", confidence=1.0, raw="")
        assert arg2.confidence == 1.0

    def test_fallback_argument(self):
        """FAIL-OPEN 兜底 Argument：空字段 + confidence=0。"""
        arg = Argument.fallback()
        assert arg.thesis != ""  # 有提示文本
        assert arg.arguments == []
        assert arg.quote == ""
        assert arg.confidence == 0.0
        assert arg.raw == ""


# ─── Turn ──────────────────────────────────────────────────────────

class TestTurn:
    """单轮发言记录。"""

    def test_create_bull_turn(self):
        arg = Argument(thesis="多", arguments=["a"], quote="q", confidence=0.8, raw="r")
        turn = Turn(speaker="bull", round=1, content=arg)
        assert turn.speaker == "bull"
        assert turn.round == 1
        assert isinstance(turn.content, Argument)
        assert isinstance(turn.timestamp, datetime)

    def test_create_inject_turn(self):
        """inject 的 content 是纯文本 str。"""
        turn = Turn(speaker="inject", round=0, content="群主注入的观点")
        assert turn.speaker == "inject"
        assert turn.round == 0
        assert turn.content == "群主注入的观点"
        assert isinstance(turn.content, str)

    def test_timestamp_auto(self):
        """未传 timestamp 时自动填充当前时间。"""
        before = datetime.now()
        turn = Turn(speaker="bull", round=1, content="test")
        after = datetime.now()
        assert before <= turn.timestamp <= after

    def test_timestamp_explicit(self):
        ts = datetime(2026, 1, 1, 12, 0, 0)
        turn = Turn(speaker="bear", round=2, content="test", timestamp=ts)
        assert turn.timestamp == ts


# ─── Verdict ──────────────────────────────────────────────────────

class TestVerdict:
    """裁判裁决。"""

    def test_create_with_winner(self):
        v = Verdict(
            summary="正方论据更充分",
            winner="bull",
            key_insights=["稀缺性是核心", "机构入场趋势明确"],
            topic_angle="从货币属性看数字资产",
        )
        assert v.winner == "bull"
        assert len(v.key_insights) == 2

    def test_draw(self):
        """平局：winner=None。"""
        v = Verdict(summary="势均力敌", winner=None, key_insights=[], topic_angle="")
        assert v.winner is None


# ─── MarketingMaterial ────────────────────────────────────────────

class TestMarketingMaterial:
    """营销素材。"""

    def test_create_full(self):
        m = MarketingMaterial(
            quotes=["数字黄金", "泡沫终将破灭"],
            hashtags=["#BTC", "#数字黄金", "#加密货币"],
            highlight_paragraph="正方认为 BTC 是数字黄金……",
            short_copy=["BTC 是数字黄金？两位 AI 辩手给出截然不同的答案", "稀缺性 vs 泡沫"],
            debate_title="BTC 数字黄金之争",
        )
        assert len(m.quotes) == 2
        assert len(m.hashtags) == 3
        assert "BTC" in m.highlight_paragraph
        assert len(m.short_copy) == 2

    def test_empty(self):
        m = MarketingMaterial(
            quotes=[], hashtags=[], highlight_paragraph="",
            short_copy=[], debate_title="",
        )
        assert m.quotes == []
        assert m.debate_title == ""


# ─── DebateQualityScore ──────────────────────────────────────────

class TestDebateQualityScore:
    """质量评分。"""

    def test_create_s_grade(self):
        s = DebateQualityScore(
            overall=8.5,
            grade="S",
            dimensions={
                "金句密度": 8.0,
                "观点多样性": 7.5,
                "冲突强度": 9.0,
                "话题升华度": 8.5,
                "文案可转化度": 9.5,
            },
            rule_score=7.75,
            llm_score=9.0,
            highlights=["金句密度高", "冲突激烈"],
            suggestions=[],
        )
        assert s.grade == "S"
        assert s.overall == 8.5
        assert s.rule_score == 7.75
        assert s.llm_score == 9.0

    def test_create_c_grade(self):
        s = DebateQualityScore(
            overall=3.0,
            grade="C",
            dimensions={},
            rule_score=3.0,
            llm_score=3.0,
            highlights=[],
            suggestions=["加强立场锁定", "提升金句质量"],
        )
        assert s.grade == "C"
        assert len(s.suggestions) == 2

    @pytest.mark.parametrize("overall,expected_grade", [
        (8.0, "S"), (7.9, "A"), (6.0, "A"), (5.9, "B"),
        (4.0, "B"), (3.9, "C"), (0.0, "C"), (10.0, "S"),
    ])
    def test_grade_from_score(self, overall, expected_grade):
        """grade_from_score 静态方法正确分级。"""
        assert DebateQualityScore.grade_from_score(overall) == expected_grade


# ─── DebateResult ────────────────────────────────────────────────

class TestDebateResult:
    """辩论完整结果。"""

    def test_create_completed(self):
        arg = Argument(thesis="t", arguments=["a"], quote="q", confidence=0.5, raw="r")
        transcript = [
            Turn(speaker="bull", round=1, content=arg),
            Turn(speaker="bear", round=1, content=arg),
        ]
        verdict = Verdict(summary="s", winner="bull", key_insights=[], topic_angle="a")
        material = MarketingMaterial(
            quotes=["q"], hashtags=["#t"], highlight_paragraph="h",
            short_copy=["c"], debate_title="d",
        )
        quality = DebateQualityScore(
            overall=7.0, grade="A", dimensions={},
            rule_score=7.0, llm_score=7.0, highlights=[], suggestions=[],
        )
        result = DebateResult(
            topic="BTC 是数字黄金吗？",
            transcript=transcript,
            verdict=verdict,
            material=material,
            quality_score=quality,
            status="completed",
        )
        assert result.topic == "BTC 是数字黄金吗？"
        assert len(result.transcript) == 2
        assert result.verdict is not None
        assert result.status == "completed"

    def test_create_stopped(self):
        """/stop 导致的提前结束：status='stopped'。"""
        result = DebateResult(
            topic="t",
            transcript=[],
            verdict=None,
            material=MarketingMaterial(
                quotes=[], hashtags=[], highlight_paragraph="",
                short_copy=[], debate_title="",
            ),
            quality_score=DebateQualityScore(
                overall=0.0, grade="C", dimensions={},
                rule_score=0.0, llm_score=0.0, highlights=[], suggestions=[],
            ),
            status="stopped",
        )
        assert result.status == "stopped"
        assert result.verdict is None

    def test_to_dict_serializable(self):
        """to_dict 可序列化为 JSON 安全的字典。"""
        result = DebateResult(
            topic="t",
            transcript=[Turn(speaker="bull", round=1, content="text")],
            verdict=None,
            material=MarketingMaterial(
                quotes=[], hashtags=[], highlight_paragraph="",
                short_copy=[], debate_title="",
            ),
            quality_score=DebateQualityScore(
                overall=5.0, grade="B", dimensions={},
                rule_score=5.0, llm_score=5.0, highlights=[], suggestions=[],
            ),
            status="completed",
        )
        d = result.to_dict()
        assert isinstance(d, dict)
        assert d["topic"] == "t"
        assert d["status"] == "completed"
        assert isinstance(d["transcript"], list)
