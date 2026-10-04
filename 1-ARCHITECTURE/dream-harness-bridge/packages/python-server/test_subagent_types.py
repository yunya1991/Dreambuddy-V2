"""
L2 自检测: DSH Subagent 共享类型单测
覆盖: Signal / ChartSpec / SubagentOutput 的 to_dict 和字段契约
"""

import sys
from pathlib import Path

import pytest

PYTHON_SERVER = Path(__file__).resolve().parent
sys.path.insert(0, str(PYTHON_SERVER))

from subagent_types import Signal, ChartSpec, SubagentOutput


class TestSignal:
    """Signal 信号类型测试"""

    def test_signal_to_dict(self):
        """Signal.to_dict 输出完整字段"""
        s = Signal(name="RSI14", value=35, direction="long", confidence=0.65)
        d = s.to_dict()
        assert d["name"] == "RSI14"
        assert d["value"] == 35
        assert d["direction"] == "long"
        assert d["confidence"] == 0.65

    def test_signal_all_directions(self):
        """支持 long/short/neutral 三种方向"""
        for direction in ["long", "short", "neutral"]:
            s = Signal(name="test", value=1, direction=direction, confidence=0.5)
            assert s.direction == direction


class TestChartSpec:
    """ChartSpec 图表配置测试"""

    def test_chart_to_dict(self):
        """ChartSpec.to_dict 输出完整字段"""
        c = ChartSpec(type="line", title="测试", data=[1, 2, 3], config={"x": 1})
        d = c.to_dict()
        assert d["type"] == "line"
        assert d["title"] == "测试"
        assert d["data"] == [1, 2, 3]
        assert d["config"] == {"x": 1}

    def test_chart_config_optional(self):
        """config 可选，默认 None"""
        c = ChartSpec(type="bar", title="t", data=[])
        assert c.config is None
        assert c.to_dict()["config"] is None

    def test_chart_all_types(self):
        """支持所有图表类型"""
        for t in ["candlestick", "line", "bar", "gauge", "scatter", "heatmap", "pie", "sankey"]:
            c = ChartSpec(type=t, title="t", data=[])
            assert c.type == t


class TestSubagentOutput:
    """SubagentOutput 输出契约测试"""

    def test_to_dict_includes_all_fields(self):
        """to_dict 包含所有 D1 新增字段"""
        out = SubagentOutput(
            module="technical",
            summary="测试摘要",
            signals=[Signal("RSI", 30, "long", 0.6)],
            charts=[ChartSpec("line", "t", [])],
            raw_data={"k": "v"},
            confidence=0.75,
            reasoning_chain="step1→step2",
            evidence_refs=["ref1", "ref2"],
            artifact_uri="artifact://test/00001",
        )
        d = out.to_dict()
        assert d["module"] == "technical"
        assert d["summary"] == "测试摘要"
        assert len(d["signals"]) == 1
        assert len(d["charts"]) == 1
        assert d["raw_data"] == {"k": "v"}
        assert d["confidence"] == 0.75
        assert d["reasoning_chain"] == "step1→step2"
        assert d["evidence_refs"] == ["ref1", "ref2"]
        assert d["artifact_uri"] == "artifact://test/00001"

    def test_default_values(self):
        """默认值符合契约"""
        out = SubagentOutput(module="test", summary="s")
        assert out.signals == []
        assert out.charts == []
        assert out.raw_data is None
        assert out.confidence == 0.5
        assert out.reasoning_chain == ""
        assert out.evidence_refs == []
        assert out.artifact_uri is None

    def test_to_dict_signals_are_dicts(self):
        """signals 序列化为 dict 列表"""
        out = SubagentOutput(
            module="m",
            summary="s",
            signals=[Signal("a", 1, "long", 0.5), Signal("b", 2, "short", 0.6)],
        )
        d = out.to_dict()
        assert all(isinstance(s, dict) for s in d["signals"])
        assert d["signals"][0]["name"] == "a"
        assert d["signals"][1]["name"] == "b"

    def test_to_dict_charts_are_dicts(self):
        """charts 序列化为 dict 列表"""
        out = SubagentOutput(
            module="m",
            summary="s",
            charts=[ChartSpec("line", "t1", []), ChartSpec("bar", "t2", [])],
        )
        d = out.to_dict()
        assert all(isinstance(c, dict) for c in d["charts"])
