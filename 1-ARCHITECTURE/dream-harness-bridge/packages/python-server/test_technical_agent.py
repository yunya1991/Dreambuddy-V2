"""
L2 自检测: TechnicalAgent 技术面 subagent 单测
覆盖: 信号提取/摘要生成/图表生成/LLM 回退/IPC handler
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PYTHON_SERVER = Path(__file__).resolve().parent
sys.path.insert(0, str(PYTHON_SERVER))

from subagent_types import Signal, ChartSpec, SubagentOutput
from technical_agent import TechnicalAgent, handle_technical_agent


class TestTechnicalAgentSignals:
    """信号提取测试"""

    def test_ema_bullish_alignment(self):
        """价格 > EMA20 > EMA50 → long 信号"""
        agent = TechnicalAgent()
        signals = agent._extract_signals({
            "price": 110, "ema20": 105, "ema50": 100,
            "rsi14": 50, "macd": 0,
        })
        ema_signal = next(s for s in signals if s.name == "EMA排列")
        assert ema_signal.direction == "long"
        assert ema_signal.confidence == 0.7

    def test_ema_bearish_alignment(self):
        """价格 < EMA20 < EMA50 → short 信号"""
        agent = TechnicalAgent()
        signals = agent._extract_signals({
            "price": 90, "ema20": 95, "ema50": 100,
            "rsi14": 50, "macd": 0,
        })
        ema_signal = next(s for s in signals if s.name == "EMA排列")
        assert ema_signal.direction == "short"

    def test_rsi_oversold(self):
        """RSI < 30 → long 信号"""
        agent = TechnicalAgent()
        signals = agent._extract_signals({"price": 100, "rsi14": 25, "macd": 0})
        rsi = next(s for s in signals if s.name == "RSI14")
        assert rsi.direction == "long"
        assert rsi.confidence == 0.65

    def test_rsi_overbought(self):
        """RSI > 70 → short 信号"""
        agent = TechnicalAgent()
        signals = agent._extract_signals({"price": 100, "rsi14": 75, "macd": 0})
        rsi = next(s for s in signals if s.name == "RSI14")
        assert rsi.direction == "short"

    def test_rsi_neutral(self):
        """30 <= RSI <= 70 → neutral 信号"""
        agent = TechnicalAgent()
        signals = agent._extract_signals({"price": 100, "rsi14": 50, "macd": 0})
        rsi = next(s for s in signals if s.name == "RSI14")
        assert rsi.direction == "neutral"
        assert rsi.confidence == 0.4

    def test_macd_positive(self):
        """MACD > 0 → long 信号"""
        agent = TechnicalAgent()
        signals = agent._extract_signals({"price": 100, "rsi14": 50, "macd": 0.5})
        macd = next(s for s in signals if s.name == "MACD")
        assert macd.direction == "long"

    def test_macd_negative(self):
        """MACD < 0 → short 信号"""
        agent = TechnicalAgent()
        signals = agent._extract_signals({"price": 100, "rsi14": 50, "macd": -0.5})
        macd = next(s for s in signals if s.name == "MACD")
        assert macd.direction == "short"

    def test_no_ema_signal_when_mixed(self):
        """EMA 排列混乱时无 EMA 信号"""
        agent = TechnicalAgent()
        signals = agent._extract_signals({
            "price": 100, "ema20": 105, "ema50": 95,
            "rsi14": 50, "macd": 0,
        })
        assert not any(s.name == "EMA排列" for s in signals)


class TestTechnicalAgentSummary:
    """摘要生成测试"""

    def test_rule_based_summary(self):
        """无 LLM 时规则生成摘要"""
        agent = TechnicalAgent()
        signals = [Signal("RSI", 30, "long", 0.6), Signal("MACD", 0.5, "long", 0.6)]
        summary = agent._generate_summary(signals, [], "LONG", 0.7)
        assert "LONG" in summary
        assert "70%" in summary
        assert "多信号2" in summary

    def test_llm_summary(self):
        """LLM 可用时调用 LLM"""
        mock_llm = MagicMock(return_value="LLM 生成的摘要" * 10)
        agent = TechnicalAgent(llm_fn=mock_llm)
        summary = agent._generate_summary([], [], "LONG", 0.7)
        mock_llm.assert_called_once()
        assert "LLM" in summary

    def test_llm_exception_fallback_to_rule(self):
        """LLM 异常时回退到规则生成"""
        mock_llm = MagicMock(side_effect=RuntimeError("LLM down"))
        agent = TechnicalAgent(llm_fn=mock_llm)
        summary = agent._generate_summary([], [], "SHORT", 0.6)
        assert "SHORT" in summary  # 规则生成


class TestTechnicalAgentCharts:
    """图表生成测试"""

    def test_chart_generated_when_ema_present(self):
        """有 EMA 数据时生成图表"""
        agent = TechnicalAgent()
        charts = agent._generate_charts({"price": 100, "ema20": 105, "ema50": 95})
        assert len(charts) == 1
        assert charts[0].type == "line"
        assert "ema20" in charts[0].data

    def test_no_chart_when_no_ema(self):
        """无 EMA 数据时不生成图表"""
        agent = TechnicalAgent()
        charts = agent._generate_charts({"price": 100, "rsi14": 50})
        assert len(charts) == 0


class TestTechnicalAgentExecute:
    """execute 集成测试"""

    def test_execute_returns_subagent_output(self):
        """execute 返回 SubagentOutput"""
        agent = TechnicalAgent()
        output = agent.execute({
            "indicators": {"price": 110, "ema20": 105, "ema50": 100, "rsi14": 50, "macd": 0.5},
            "rationale": ["趋势向上"],
            "direction": "LONG",
            "confidence": 0.75,
        })
        assert isinstance(output, SubagentOutput)
        assert output.module == "technical"
        assert output.confidence == 0.75
        assert len(output.signals) > 0
        assert len(output.charts) > 0
        assert output.reasoning_chain == "趋势向上"
        assert len(output.evidence_refs) > 0
        assert output.artifact_uri is not None

    def test_execute_empty_input(self):
        """空输入不崩溃 (FAIL-OPEN)"""
        agent = TechnicalAgent()
        output = agent.execute({})
        assert isinstance(output, SubagentOutput)
        assert output.module == "technical"
        assert output.artifact_uri is None

    def test_execute_default_confidence(self):
        """无 confidence 时默认 0.5"""
        agent = TechnicalAgent()
        output = agent.execute({"indicators": {}})
        assert output.confidence == 0.5


class TestHandleTechnicalAgent:
    """IPC handler 测试"""

    def test_success(self):
        """正常执行返回 ok=True"""
        result = handle_technical_agent({
            "node_output": {"indicators": {"price": 100, "rsi14": 50}}
        })
        assert result["ok"] is True
        assert "output" in result
        assert result["output"]["module"] == "technical"

    def test_exception_returns_ok_false(self):
        """异常时返回 ok=False"""
        result = handle_technical_agent({})  # 无 node_output
        assert result["ok"] is True  # execute 内部容错
