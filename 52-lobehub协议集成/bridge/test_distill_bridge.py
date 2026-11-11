"""52-LobeHub Phase 3 蒸馏桥测试。

覆盖：①R6 映射表正确性 ②必填字段 fail-closed 校验 ③R3 工具白名单断言
④游标幂等（重跑不重复写入）。
DB 写入类测试全部走 FakeShell mock stdio 层，不污染真实认知库。
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from distill_bridge import (  # noqa: E402
    ALLOWED_TOOLS,
    CONTENT_MAX_CHARS,
    R6_QUALITY_MAP,
    BridgeValidationError,
    StdioMcpShell,
    build_record_arguments,
    process_outbox,
    validate_entry,
)


def make_entry(**overrides):
    base = {
        "type": "session_summary",
        "content": "会话摘要：用户询问 52 协议集成进度",
        "tags": ["protocol-bridge", "52-lobehub"],
        "source_ref": "msg-001",
        "bridge_ts": "2026-11-11T12:00:00.000Z",
    }
    base.update(overrides)
    return base


class FakeShell:
    """mock stdio 层：记录全部 call_tool 调用，不真实 spawn。"""

    def __init__(self):
        self.calls = []
        self.closed = False

    def call_tool(self, name, arguments):
        assert name in ALLOWED_TOOLS
        self.calls.append((name, arguments))
        return {"content": [{"type": "text", "text": '{"ok":true}'}]}

    def close(self):
        self.closed = True


# ---------- ① R6 映射表 ----------


def test_r6_quality_map_exact():
    assert R6_QUALITY_MAP == {
        "expertise_canon": "B",
        "expertise_candidate": "C",
        "debate_winner": "B",
        "debate_loser": "D",
        "brainstorm_winner": "B",
        "brainstorm_loser": "D",
        "session_summary": "C",
    }


@pytest.mark.parametrize(
    "etype,quality",
    [
        ("expertise_canon", "B"),
        ("expertise_candidate", "C"),
        ("debate_winner", "B"),
        ("debate_loser", "D"),
        ("brainstorm_winner", "B"),
        ("brainstorm_loser", "D"),
        ("session_summary", "C"),
    ],
)
def test_build_record_arguments_maps_quality(etype, quality):
    entry = validate_entry(make_entry(type=etype))
    args = build_record_arguments(entry)
    assert args["quality_level"] == quality
    assert args["source"] == "protocol-bridge"
    assert "protocol-bridge" in args["tags"]


# ---------- ② 必填字段校验（fail-closed） ----------


def test_validate_accepts_valid_entry():
    entry = validate_entry(make_entry())
    assert entry["type"] == "session_summary"
    assert entry["source_ref"] == "msg-001"


def test_validate_rejects_missing_source_ref():
    with pytest.raises(BridgeValidationError, match="source_ref"):
        validate_entry(make_entry(source_ref=""))


def test_validate_rejects_overlong_content():
    with pytest.raises(BridgeValidationError, match="content_too_long"):
        validate_entry(make_entry(content="x" * (CONTENT_MAX_CHARS + 1)))


def test_validate_accepts_max_content():
    entry = validate_entry(make_entry(content="x" * CONTENT_MAX_CHARS))
    assert len(entry["content"]) == CONTENT_MAX_CHARS


def test_validate_rejects_missing_protocol_bridge_tag():
    with pytest.raises(BridgeValidationError, match="protocol_bridge"):
        validate_entry(make_entry(tags=["52-lobehub"]))


def test_validate_rejects_unknown_type():
    with pytest.raises(BridgeValidationError, match="unknown_type"):
        validate_entry(make_entry(type="session_trace"))


def test_validate_rejects_missing_bridge_ts():
    with pytest.raises(BridgeValidationError, match="bridge_ts"):
        validate_entry(make_entry(bridge_ts=""))


# ---------- ③ R3 工具白名单断言 ----------


def test_allowlist_is_record_and_verify_only():
    assert ALLOWED_TOOLS == frozenset({"record", "verify"})


def test_call_tool_rejects_non_allowlisted_before_spawn():
    shell = StdioMcpShell(command="/nonexistent/python3", args=[])
    # 白名单断言发生在 spawn 之前：非 record/verify 直接 AssertionError
    with pytest.raises(AssertionError, match="tool_not_allowed"):
        shell.call_tool("recall", {"context": "x"})
    with pytest.raises(AssertionError, match="tool_not_allowed"):
        shell.call_tool("unified_search", {"query": "x"})
    assert shell._proc is None  # 未 spawn 任何进程


# ---------- ④ 游标幂等 ----------


def test_cursor_idempotent_no_rewrite(tmp_path):
    outbox = tmp_path / "outbox.jsonl"
    cursor = tmp_path / ".cursor"
    lines = [
        json.dumps(make_entry(source_ref=f"msg-{i:03d}"), ensure_ascii=False) for i in range(3)
    ]
    outbox.write_text("\n".join(lines) + "\n", encoding="utf-8")

    shell = FakeShell()
    stats = process_outbox(outbox, cursor, shell_factory=lambda: shell)
    assert stats == {"processed": 3, "written": 3, "skipped": 0, "errors": 0}
    assert len(shell.calls) == 3
    assert cursor.read_text().strip() == "3"

    # 重跑：游标已覆盖，0 次新调用
    shell2 = FakeShell()
    stats2 = process_outbox(outbox, cursor, shell_factory=lambda: shell2)
    assert stats2["processed"] == 0
    assert len(shell2.calls) == 0

    # 追加新行：只处理新增部分
    with outbox.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(make_entry(source_ref="msg-004"), ensure_ascii=False) + "\n")
    shell3 = FakeShell()
    stats3 = process_outbox(outbox, cursor, shell_factory=lambda: shell3)
    assert stats3 == {"processed": 1, "written": 1, "skipped": 0, "errors": 0}
    assert [c[1]["external_id"] for c in shell3.calls] == ["bridge:msg-004"]


def test_invalid_entries_skipped_without_blocking(tmp_path):
    outbox = tmp_path / "outbox.jsonl"
    cursor = tmp_path / ".cursor"
    rows = [
        json.dumps(make_entry(tags=["no-bridge"])),  # 缺 protocol-bridge → 跳过
        "not-json{{{",  # 非法 JSON → 跳过
        json.dumps(make_entry(source_ref="ok-1"), ensure_ascii=False),  # 合法 → 写入
    ]
    outbox.write_text("\n".join(rows) + "\n", encoding="utf-8")
    shell = FakeShell()
    stats = process_outbox(outbox, cursor, shell_factory=lambda: shell)
    assert stats["written"] == 1
    assert stats["skipped"] == 2
    assert cursor.read_text().strip() == "3"  # 毒丸不阻塞，游标照常推进
    assert len(shell.calls) == 1


def test_duplicate_content_deduped_across_batches(tmp_path):
    """内容指纹去重：同意图重复胜/负记录只写一次，游标照常推进。"""
    outbox = tmp_path / "outbox.jsonl"
    cursor = tmp_path / ".cursor"
    seen = tmp_path / ".seen"
    first = make_entry(content="[脑暴胜出][X] plancard=pc-1 score=0.9 steps=2")
    dup = make_entry(content="[脑暴胜出][X] plancard=pc-2 score=0.8 steps=2")
    other = make_entry(content="会话摘要：另一个意图", source_ref="msg-002")
    outbox.write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in (first, dup, other)) + "\n",
        encoding="utf-8",
    )
    shell = FakeShell()
    stats = process_outbox(outbox, cursor, shell_factory=lambda: shell, seen_path=seen)
    assert stats == {"processed": 3, "written": 2, "skipped": 1, "errors": 0}
    assert len(shell.calls) == 2
    assert cursor.read_text().strip() == "3"
    assert len(seen.read_text(encoding="utf-8").splitlines()) == 2

    # 游标回退模拟重跑：已见过的内容全部跳过，不重复写壳
    cursor.write_text("0\n", encoding="utf-8")
    shell2 = FakeShell()
    stats2 = process_outbox(outbox, cursor, shell_factory=lambda: shell2, seen_path=seen)
    assert stats2 == {"processed": 3, "written": 0, "skipped": 3, "errors": 0}
    assert shell2.calls == []
