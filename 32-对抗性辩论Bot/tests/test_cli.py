"""test_cli.py — cli.py 单元测试（TDD RED phase）

测试 P1：CLI 调试入口，手动触发辩论（不依赖 Telegram）。

cli.py 功能：
- argparse 解析参数：topic, --rounds, --background, --judge/--no-judge, --config, --output
- 构建 orchestrator（复用 main.build_app 的组件但不启动 listener）
- 运行辩论并打印 transcript + marketing + quality
- --output 将 DebateResult 保存为 JSON
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import cli


# ─── argparse 测试 ───────────────────────────────────────────────

class TestArgParse:

    def test_topic_required(self):
        """topic 是必填参数。"""
        with pytest.raises(SystemExit):
            cli.parse_args([])

    def test_topic_parsed(self):
        """topic 被正确解析。"""
        args = cli.parse_args(["BTC 是数字黄金"])
        assert args.topic == "BTC 是数字黄金"

    def test_default_rounds_2(self):
        """默认 rounds=2。"""
        args = cli.parse_args(["测试"])
        assert args.rounds == 2

    def test_custom_rounds(self):
        """--rounds 自定义轮次。"""
        args = cli.parse_args(["测试", "--rounds", "3"])
        assert args.rounds == 3

    def test_default_judge_enabled(self):
        """默认启用 judge。"""
        args = cli.parse_args(["测试"])
        assert args.judge is True

    def test_no_judge_flag(self):
        """--no-judge 禁用 judge。"""
        args = cli.parse_args(["测试", "--no-judge"])
        assert args.judge is False

    def test_background_optional(self):
        """--background 可选，默认空。"""
        args = cli.parse_args(["测试"])
        assert args.background == ""
        args2 = cli.parse_args(["测试", "--background", "背景材料"])
        assert args2.background == "背景材料"

    def test_output_optional(self):
        """--output 可选。"""
        args = cli.parse_args(["测试"])
        assert args.output is None
        args2 = cli.parse_args(["测试", "--output", "result.json"])
        assert args2.output == "result.json"


# ─── run_cli 行为测试 ────────────────────────────────────────────

class TestRunCli:

    def test_run_cli_returns_debate_result(self, monkeypatch, tmp_path):
        """run_cli 执行辩论并返回 DebateResult。"""
        import main

        # mock create_llm_adapter，避免真实 API
        monkeypatch.setattr(
            main, "create_llm_adapter",
            lambda config=None, model_name=None: _FakeLLM(),
        )
        result = cli.run_cli(topic="测试话题", rounds=1, background="",
                             judge=True, output=None)
        assert result.topic == "测试话题"
        assert result.status == "completed"
        assert len(result.transcript) >= 2  # 至少 bull + bear

    def test_run_cli_no_judge(self, monkeypatch):
        """--no-judge 时 verdict 为 None。"""
        import main

        monkeypatch.setattr(
            main, "create_llm_adapter",
            lambda config=None, model_name=None: _FakeLLM(),
        )
        result = cli.run_cli(topic="测试", rounds=1, background="",
                             judge=False, output=None)
        assert result.verdict is None

    def test_run_cli_output_saves_json(self, monkeypatch, tmp_path):
        """--output 将结果保存为 JSON 文件。"""
        import main

        monkeypatch.setattr(
            main, "create_llm_adapter",
            lambda config=None, model_name=None: _FakeLLM(),
        )
        output_path = tmp_path / "result.json"
        cli.run_cli(topic="测试", rounds=1, background="",
                    judge=True, output=str(output_path))
        assert output_path.exists()
        data = json.loads(output_path.read_text(encoding="utf-8"))
        assert data["topic"] == "测试"
        assert data["status"] == "completed"
        assert "transcript" in data
        assert "material" in data
        assert "quality_score" in data


# ─── 辅助 ────────────────────────────────────────────────────────

class _FakeLLM:
    """模拟 LLMAdapter。"""

    async def chat(self, system_prompt: str, user_prompt: str,
                   max_tokens: int = 600) -> str:
        # 根据 prompt 内容返回不同的 JSON
        if "正方" in system_prompt:
            return json.dumps({
                "thesis": "正方论点", "arguments": ["论据1"],
                "quote": "正方金句", "confidence": 0.8,
            })
        if "反方" in system_prompt:
            return json.dumps({
                "thesis": "反方论点", "arguments": ["反驳1"],
                "quote": "反方金句", "confidence": 0.7,
            })
        if "裁判" in system_prompt or "综合" in system_prompt:
            return json.dumps({
                "summary": "综合裁决", "winner": "bull",
                "key_insights": ["洞察"], "topic_angle": "升华",
            })
        if "营销" in system_prompt:
            return json.dumps({
                "copies": ["文案1"], "title": "辩论标题",
            })
        # 质量评估
        return json.dumps({
            "conflict_intensity": 7.0, "topic_elevation": 6.0,
            "copy_convertibility": 8.0, "highlights": ["亮点"],
            "suggestions": [],
        })
