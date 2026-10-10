"""test_interactive_ipc.py — InteractiveRunner IPC 调 C-Drive recall/record 测试 (TDD)

SPEC v2.0-rc3 第 6.4 节：外部辩论流程中 Trae 通过 IPC 调 C-Drive 认知能力。
"""
from __future__ import annotations

import json
from datetime import datetime

import pytest

from core.interactive_runner import InteractiveRunner
from core.models import Argument, Turn
from core.telegram_bot import TelegramDualBot


class MockBot:
    async def send_message(self, chat_id, text):
        return {"message_id": 1}


def make_runner(ipc_fn=None):
    dual = TelegramDualBot(MockBot(), MockBot(), MockBot(),
                           send_delay=0, retry_delay=0)
    return InteractiveRunner(dual, "BTC 是数字黄金", -100,
                             max_rounds=2, judge_enabled=True,
                             ipc_fn=ipc_fn)


pytestmark = pytest.mark.asyncio


class TestRecallMemories:
    """recall_memories: IPC 调 C-Drive recall。"""

    async def test_recall_calls_ipc(self):
        """recall_memories 调用 ipc_fn。"""
        called = {}
        def ipc_fn(params):
            called.update(params)
            return {"ok": True, "memories": [{"content": '{"thesis": "BTC稀缺"}',
                                              "quality": "B"}]}
        runner = make_runner(ipc_fn=ipc_fn)
        memories = await runner.recall_memories("BTC 多空辩论论据")
        assert called["action"] == "recall"
        assert "BTC" in called["context"]
        assert len(memories) == 1

    async def test_recall_no_ipc_returns_empty(self):
        """无 ipc_fn 时返回空列表（向后兼容）。"""
        runner = make_runner(ipc_fn=None)
        memories = await runner.recall_memories("BTC 辩论")
        assert memories == []

    async def test_recall_fail_open(self):
        """IPC 异常时 FAIL-OPEN 返回空列表。"""
        def bad_ipc(params):
            raise Exception("IPC error")
        runner = make_runner(ipc_fn=bad_ipc)
        memories = await runner.recall_memories("BTC 辩论")
        assert memories == []


class TestRecordArgument:
    """record_argument: IPC 调 C-Drive record。"""

    async def test_record_calls_ipc(self):
        """record_argument 调用 ipc_fn。"""
        called = {}
        def ipc_fn(params):
            called.update(params)
            return {"ok": True, "memory_id": "VM-001"}
        runner = make_runner(ipc_fn=ipc_fn)
        # 先发送一轮正方
        await runner.send_bull("BTC稀缺性", ["2100万枚"], "金句", 0.85)
        # record
        mid = await runner.record_argument(
            topic="BTC 是数字黄金",
            side="bull",
            thesis="BTC稀缺性",
            arguments=["2100万枚"],
            quote="金句",
            confidence=0.85,
            persona="加密老兵",
            round=1,
        )
        assert called["action"] == "record"
        assert "BTC" in called["tags"]
        assert "debate" in called["tags"]
        # content 是结构化 JSON
        content = json.loads(called["content"])
        assert content["thesis"] == "BTC稀缺性"
        assert content["side"] == "bull"
        assert content["persona"] == "加密老兵"

    async def test_record_no_ipc_noop(self):
        """无 ipc_fn 时 record 是 no-op（向后兼容）。"""
        runner = make_runner(ipc_fn=None)
        mid = await runner.record_argument(
            topic="测试", side="bull", thesis="t",
            arguments=[], quote="", confidence=0.5,
            persona="", round=1,
        )
        assert mid is None

    async def test_record_structured_content(self):
        """record content 是结构化 JSON（SPEC 6.4 要求）。"""
        called = {}
        def ipc_fn(params):
            called.update(params)
            return {"ok": True, "memory_id": "VM-002"}
        runner = make_runner(ipc_fn=ipc_fn)
        await runner.record_argument(
            topic="BTC 是数字黄金",
            side="bear",
            thesis="BTC 波动性远超黄金",
            arguments=["单日波动20%", "与风险资产高相关"],
            quote="黄金一天跌20%就不是黄金了",
            confidence=0.72,
            persona="传统金融人",
            round=1,
        )
        content = json.loads(called["content"])
        assert content["type"] == "argument"
        assert content["subtype"] == "argument-pattern"
        assert content["topic"] == "BTC 是数字黄金"
        assert content["side"] == "bear"
        assert content["confidence"] == 0.72
        assert content["persona"] == "传统金融人"

    async def test_record_tags_dual_dimension(self):
        """tags 同时包含辩论维度和交易维度。"""
        called = {}
        def ipc_fn(params):
            called.update(params)
            return {"ok": True, "memory_id": "VM-003"}
        runner = make_runner(ipc_fn=ipc_fn)
        await runner.record_argument(
            topic="BTC 是数字黄金",
            side="bull", thesis="t", arguments=[],
            quote="", confidence=0.8, persona="加密老兵", round=1,
        )
        tags = called["tags"]
        # 辩论维度
        assert "debate" in tags
        assert "argument-pattern" in tags
        # 交易维度
        assert "BTC" in tags
