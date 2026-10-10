"""test_cross_exam_highlights.py — MarketingExtractor CrossExamination 适配测试 (TDD RED→GREEN)

SPEC v2.0-rc3 第 4.5 节：从交叉质询中提取精彩 Q&A 作为营销素材。
"""
from __future__ import annotations

from datetime import datetime

import pytest

from core.models import Argument, CrossExamination, Turn
from core.marketing import MarketingExtractor


class TestExtractCrossExamHighlights:
    """_extract_cross_exam_highlights 方法。"""

    def test_no_cross_exam_returns_empty(self):
        """无 CrossExamination 时返回空列表。"""
        extractor = MarketingExtractor()
        transcript = [
            Turn(speaker="bull", round=1,
                 content=Argument(thesis="t", arguments=[], quote="", confidence=0.8, raw="")),
        ]
        result = extractor._extract_cross_exam_highlights(transcript)
        assert result == []

    def test_sharp_question_extracted(self):
        """犀利问题被提取。"""
        extractor = MarketingExtractor()
        ce = CrossExamination(
            questioner="bear", respondent="bull",
            questions=["你的数据来源是什么？"],
            answers=["来源是 CoinGecko 2024年Q3报告，数据经过交叉验证"],
            raw="",
        )
        transcript = [Turn(speaker="bear", round=2, content=ce)]
        result = extractor._extract_cross_exam_highlights(transcript)
        assert len(result) == 1
        assert "数据来源" in result[0]
        assert "Q:" in result[0]
        assert "A:" in result[0]

    def test_short_answer_extracted(self):
        """简短回答（<20字）被提取（被问倒）。"""
        extractor = MarketingExtractor()
        ce = CrossExamination(
            questioner="bear", respondent="bull",
            questions=["普通问题"],
            answers=["不知道"],  # <20 字
            raw="",
        )
        transcript = [Turn(speaker="bear", round=2, content=ce)]
        result = extractor._extract_cross_exam_highlights(transcript)
        assert len(result) == 1

    def test_normal_qa_not_extracted(self):
        """普通 Q&A 不被提取（非犀利且回答充分）。"""
        extractor = MarketingExtractor()
        ce = CrossExamination(
            questioner="bear", respondent="bull",
            questions=["普通问题"],
            answers=["这是一个详细的回答，超过二十个字，不会被提取"],
            raw="",
        )
        transcript = [Turn(speaker="bear", round=2, content=ce)]
        result = extractor._extract_cross_exam_highlights(transcript)
        assert result == []

    def test_bull_questioner_label(self):
        """bull 提问时标注"正方质询反方"。"""
        extractor = MarketingExtractor()
        ce = CrossExamination(
            questioner="bull", respondent="bear",
            questions=["数据来源是什么？"],
            answers=["来源可靠"],
            raw="",
        )
        transcript = [Turn(speaker="bull", round=2, content=ce)]
        result = extractor._extract_cross_exam_highlights(transcript)
        assert len(result) == 1
        assert "正方质询反方" in result[0]

    def test_bear_questioner_label(self):
        """bear 提问时标注"反方质询正方"。"""
        extractor = MarketingExtractor()
        ce = CrossExamination(
            questioner="bear", respondent="bull",
            questions=["数据来源是什么？"],
            answers=["来源可靠"],
            raw="",
        )
        transcript = [Turn(speaker="bear", round=2, content=ce)]
        result = extractor._extract_cross_exam_highlights(transcript)
        assert len(result) == 1
        assert "反方质询正方" in result[0]

    def test_multiple_cross_exams(self):
        """多条 CrossExamination 分别提取。"""
        extractor = MarketingExtractor()
        ce1 = CrossExamination(
            questioner="bear", respondent="bull",
            questions=["数据来源？", "如何解释矛盾？"],
            answers=["不知道", "无法解释"],
            raw="",
        )
        ce2 = CrossExamination(
            questioner="bull", respondent="bear",
            questions=["为什么？"],
            answers=["不知道"],
            raw="",
        )
        transcript = [
            Turn(speaker="bear", round=2, content=ce1),
            Turn(speaker="bull", round=2, content=ce2),
        ]
        result = extractor._extract_cross_exam_highlights(transcript)
        # ce1: 2 questions both sharp → 2 highlights
        # ce2: 1 question sharp → 1 highlight
        assert len(result) == 3
