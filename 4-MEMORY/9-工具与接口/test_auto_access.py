#!/usr/bin/env python3
"""
自动接入层测试 — TDD红阶段
覆盖三层：触发层(cognitive_hook) + 协议层(cognitive_mcp_server)
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

sys.path.insert(0, str(Path(__file__).parent))


# ============================================================
# 触发层测试：cognitive_hook.py
# ============================================================

def test_hook_extract_commit_info():
    """触发层：从git commit提取信息（message, files, diff stats）"""
    from cognitive_hook import extract_commit_info

    # 用真实git仓库测试
    tmpdir = tempfile.mkdtemp()
    try:
        os.chdir(tmpdir)
        subprocess.run(["git", "init", "-q"], check=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], check=True)
        subprocess.run(["git", "config", "user.name", "Test"], check=True)
        Path("file1.py").write_text("print('hello')")
        Path("file2.md").write_text("# Doc")
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-q", "-m", "feat: add hello world and docs"], check=True)

        info = extract_commit_info()

        assert "message" in info, "缺少 message"
        assert "feat" in info["message"], f"message应包含commit内容: {info['message']}"
        assert "files" in info, "缺少 files"
        assert len(info["files"]) >= 2, f"应至少2个文件: {info['files']}"
        assert any("file1.py" in f for f in info["files"]), f"应包含file1.py: {info['files']}"
        assert "insertions" in info, "缺少 insertions"
        assert info["insertions"] > 0, "应有新增行数"
        assert "commit_hash" in info, "缺少 commit_hash"
        assert len(info["commit_hash"]) >= 7, f"hash应至少7字符: {info['commit_hash']}"

        print("✅ test_hook_extract_commit_info 通过")
        return True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_hook_classify_change_type():
    """触发层：根据commit message分类变更类型"""
    from cognitive_hook import classify_change_type

    assert classify_change_type("feat: add new function") == "feature"
    assert classify_change_type("fix: resolve crash bug") == "bugfix"
    assert classify_change_type("refactor: restructure module") == "refactor"
    assert classify_change_type("docs: update README") == "docs"
    assert classify_change_type("test: add unit tests") == "test"
    assert classify_change_type("chore: update deps") == "chore"
    assert classify_change_type("random message") == "other"
    # 中文message
    assert classify_change_type("修复: 解决崩溃问题") == "bugfix"
    assert classify_change_type("新增: 添加功能") == "feature"

    print("✅ test_hook_classify_change_type 通过")
    return True


def test_hook_generate_experience():
    """触发层：从commit信息生成结构化经验描述"""
    from cognitive_hook import generate_experience_description

    commit_info = {
        "message": "feat: 实现严格贝叶斯优化，Beta分布替代固定似然度",
        "files": ["bayesian_memory_updater.py", "test_rigorous_bayesian.py"],
        "insertions": 200,
        "deletions": 50,
        "commit_hash": "abc1234",
    }
    desc = generate_experience_description(commit_info)

    assert "贝叶斯" in desc or "bayesian" in desc.lower(), f"经验应包含关键词: {desc}"
    assert "bayesian_memory_updater.py" in desc, f"应包含变更文件: {desc}"
    assert len(desc) > 20, f"经验描述太短: {desc}"
    assert isinstance(desc, str)

    print("✅ test_hook_generate_experience 通过")
    return True


def test_hook_trigger_cognitive_loop():
    """触发层：触发认知闭环（record + verify），用mock验证调用"""
    from cognitive_hook import trigger_cognitive_loop

    commit_info = {
        "message": "fix: 修复贝叶斯3次成功就冲A级的过拟合bug",
        "files": ["bayesian_memory_updater.py"],
        "insertions": 100,
        "deletions": 30,
        "commit_hash": "abc1234",
    }

    # Mock CognitiveLoopEntry 验证 record + verify 被调用
    with patch("cognitive_hook.CognitiveLoopEntry") as MockCLE:
        mock_instance = MockCLE.return_value
        mock_instance.record.return_value = "VM-AUTO-001"
        mock_instance.verify.return_value = {"memory_id": "VM-AUTO-001", "success": True}

        result = trigger_cognitive_loop(commit_info, dry_run=False)

        # 验证 record 被调用
        assert mock_instance.record.called, "record() 应被调用"
        record_args = mock_instance.record.call_args
        assert "贝叶斯" in str(record_args), f"record内容应包含关键词: {record_args}"

        # 验证 verify 被调用
        assert mock_instance.verify.called, "verify() 应被调用"
        verify_args = mock_instance.verify.call_args
        assert verify_args[1].get("success", True) or verify_args[0][1] == True, "verify应标记成功"

        # 验证返回结构
        assert "memory_id" in result, f"返回应含memory_id: {result}"
        assert "recorded" in result, f"返回应含recorded状态: {result}"

        print("✅ test_hook_trigger_cognitive_loop 通过")
        return True


def test_hook_dry_run_no_side_effects():
    """触发层：dry_run模式不产生任何副作用"""
    from cognitive_hook import trigger_cognitive_loop

    commit_info = {
        "message": "test: dry run test",
        "files": ["test.py"],
        "insertions": 1,
        "deletions": 0,
        "commit_hash": "dry0001",
    }

    with patch("cognitive_hook.CognitiveLoopEntry") as MockCLE:
        mock_instance = MockCLE.return_value
        result = trigger_cognitive_loop(commit_info, dry_run=True)

        # dry_run 不应调用 record/verify
        assert not mock_instance.record.called, "dry_run不应调用record"
        assert not mock_instance.verify.called, "dry_run不应调用verify"
        assert result.get("dry_run") == True, "返回应标记dry_run"

        print("✅ test_hook_dry_run_no_side_effects 通过")
        return True


# ============================================================
# 协议层测试：cognitive_mcp_server.py
# ============================================================

def test_mcp_initialize_handshake():
    """协议层：MCP initialize握手返回正确协议信息"""
    from cognitive_mcp_server import handle_jsonrpc

    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1.0"},
        },
    }
    response = handle_jsonrpc(request)

    assert response["jsonrpc"] == "2.0", "应返回jsonrpc 2.0"
    assert response["id"] == 1, "应返回匹配的id"
    assert "result" in response, "应返回result"
    result = response["result"]
    assert "protocolVersion" in result, "应返回协议版本"
    assert "serverInfo" in result, "应返回server信息"
    assert "cognitive" in result["serverInfo"]["name"].lower(), "服务器名应包含cognitive"


    print("✅ test_mcp_initialize_handshake 通过")
    return True


def test_mcp_tools_list():
    """协议层：tools/list返回5个标准认知工具"""
    from cognitive_mcp_server import handle_jsonrpc

    request = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    response = handle_jsonrpc(request)

    assert "result" in response
    tools = response["result"]["tools"]
    tool_names = [t["name"] for t in tools]

    assert "recall" in tool_names, f"缺少recall工具: {tool_names}"
    assert "record" in tool_names, f"缺少record工具: {tool_names}"
    assert "verify" in tool_names, f"缺少verify工具: {tool_names}"
    assert "stats" in tool_names, f"缺少stats工具: {tool_names}"
    assert "health" in tool_names, f"缺少health工具: {tool_names}"

    # 每个工具应有 inputSchema
    for t in tools:
        assert "inputSchema" in t, f"工具{t['name']}缺少inputSchema"
        assert "description" in t, f"工具{t['name']}缺少description"

    print("✅ test_mcp_tools_list 通过")
    return True


def test_mcp_tool_call_recall():
    """协议层：tools/call recall 返回记忆列表"""
    from cognitive_mcp_server import handle_jsonrpc

    request = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "recall",
            "arguments": {"context": "贝叶斯优化", "top_k": 3},
        },
    }

    with patch("cognitive_mcp_server.CognitiveLoopEntry") as MockCLE:
        mock_instance = MockCLE.return_value
        mock_instance.recall.return_value = [
            {"memory_id": "VM-001", "content": "贝叶斯经验", "quality_level": "B"}
        ]

        response = handle_jsonrpc(request)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 3
        assert "result" in response
        # MCP tools/call 返回 content 数组
        assert "content" in response["result"]
        content_text = response["result"]["content"][0]["text"]
        assert "贝叶斯" in content_text, f"返回内容应包含贝叶斯: {content_text}"

        # 验证 recall 被正确调用
        mock_instance.recall.assert_called_with("贝叶斯优化", top_k=3, min_quality="C")

        print("✅ test_mcp_tool_call_recall 通过")
        return True


def test_mcp_tool_call_record():
    """协议层：tools/call record 写入新经验"""
    from cognitive_mcp_server import handle_jsonrpc, _reset_cle

    _reset_cle()  # 重置单例，确保mock生效

    request = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "record",
            "arguments": {
                "content": "v1固定似然度导致过拟合",
                "quality_level": "B",
                "tags": "贝叶斯,过拟合",
            },
        },
    }

    with patch("cognitive_mcp_server.CognitiveLoopEntry") as MockCLE:
        mock_instance = MockCLE.return_value
        mock_instance.record.return_value = "VM-NEW-001"

        response = handle_jsonrpc(request)

        assert "result" in response
        content_text = response["result"]["content"][0]["text"]
        assert "VM-NEW-001" in content_text, f"应返回memory_id: {content_text}"

        # 验证 record 被正确调用
        mock_instance.record.assert_called_once()
        call_kwargs = mock_instance.record.call_args[1]
        assert call_kwargs["content"] == "v1固定似然度导致过拟合"

        print("✅ test_mcp_tool_call_record 通过")
        return True


def test_mcp_tool_call_stats():
    """协议层：tools/call stats 返回统计信息"""
    from cognitive_mcp_server import handle_jsonrpc, _reset_cle

    _reset_cle()  # 重置单例，确保mock生效

    request = {
        "jsonrpc": "2.0",
        "id": 5,
        "method": "tools/call",
        "params": {"name": "stats", "arguments": {}},
    }

    with patch("cognitive_mcp_server.CognitiveLoopEntry") as MockCLE:
        mock_instance = MockCLE.return_value
        mock_instance.stats.return_value = {"total": 10, "by_quality": {"A": 2, "B": 8}}

        response = handle_jsonrpc(request)

        assert "result" in response
        content_text = response["result"]["content"][0]["text"]
        stats = json.loads(content_text)
        assert stats["total"] == 10, f"统计应返回total=10: {stats}"

        print("✅ test_mcp_tool_call_stats 通过")
        return True


def test_mcp_unknown_method_error():
    """协议层：未知方法返回JSON-RPC错误"""
    from cognitive_mcp_server import handle_jsonrpc

    request = {"jsonrpc": "2.0", "id": 99, "method": "unknown/method", "params": {}}
    response = handle_jsonrpc(request)

    assert "error" in response, "未知方法应返回error"
    assert response["error"]["code"] == -32601, f"应返回method not found错误码: {response['error']}"
    assert "id" in response

    print("✅ test_mcp_unknown_method_error 通过")
    return True


def test_mcp_unknown_tool_error():
    """协议层：调用不存在的tool返回错误"""
    from cognitive_mcp_server import handle_jsonrpc

    request = {
        "jsonrpc": "2.0",
        "id": 100,
        "method": "tools/call",
        "params": {"name": "nonexistent_tool", "arguments": {}},
    }
    response = handle_jsonrpc(request)

    assert "error" in response, "不存在的tool应返回error"

    print("✅ test_mcp_unknown_tool_error 通过")
    return True


if __name__ == "__main__":
    print("=" * 70)
    print("🔴 TDD RED 阶段：自动接入层测试（期望失败）")
    print("=" * 70)

    tests = [
        # 触发层
        ("test_hook_extract_commit_info", test_hook_extract_commit_info),
        ("test_hook_classify_change_type", test_hook_classify_change_type),
        ("test_hook_generate_experience", test_hook_generate_experience),
        ("test_hook_trigger_cognitive_loop", test_hook_trigger_cognitive_loop),
        ("test_hook_dry_run_no_side_effects", test_hook_dry_run_no_side_effects),
        # 协议层
        ("test_mcp_initialize_handshake", test_mcp_initialize_handshake),
        ("test_mcp_tools_list", test_mcp_tools_list),
        ("test_mcp_tool_call_recall", test_mcp_tool_call_recall),
        ("test_mcp_tool_call_record", test_mcp_tool_call_record),
        ("test_mcp_tool_call_stats", test_mcp_tool_call_stats),
        ("test_mcp_unknown_method_error", test_mcp_unknown_method_error),
        ("test_mcp_unknown_tool_error", test_mcp_unknown_tool_error),
    ]

    passed = 0
    failed = 0
    failures = []

    for name, fn in tests:
        print(f"\n▶ 运行: {name}")
        try:
            if fn():
                passed += 1
        except Exception as ex:
            failed += 1
            failures.append((name, f"{type(ex).__name__}: {ex}"))
            print(f"   ❌ {type(ex).__name__}: {ex}")

    print("\n" + "=" * 70)
    print(f"📊 结果: 通过 {passed} / {len(tests)}, 失败 {failed}")
    if failures:
        for n, r in failures:
            print(f"  - {n}: {r}")
    print("=" * 70)
    sys.exit(0 if failed == 0 else 1)
