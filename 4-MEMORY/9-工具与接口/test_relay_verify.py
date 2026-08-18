#!/usr/bin/env python3
"""
接力机制测试 — TDD红阶段
验证git hook搜索daemon记忆并verify的接力闭环
"""

import os
import sys
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent))


def test_relay_find_daemon_memories():
    """接力：根据commit涉及的文件列表，找到daemon记录的同类记忆"""
    from cognitive_hook import find_daemon_memories_for_files

    # commit涉及的文件
    commit_files = ["4-MEMORY/bayesian_memory_updater.py", "4-MEMORY/test.py"]

    with patch("cognitive_hook.CognitiveLoopEntry") as MockCLE:
        mock_instance = MockCLE.return_value
        # 模拟search返回daemon记录的记忆（source在metadata内）
        mock_instance.search.return_value = [
            {
                "id": "VM-DAEMON-001",
                "content": "[文件变更] 1个文件变更 | 修改(1): bayesian_memory_updater.py",
                "metadata": {
                    "source": "cognitive-daemon",
                    "confidence": 0.2,
                    "verify_count": 0,
                },
            }
        ]

        results = find_daemon_memories_for_files(commit_files)

        # 应该调用了search
        assert mock_instance.search.called, "search()应被调用"
        # 应该返回daemon记忆
        assert len(results) > 0, "应找到daemon记忆"
        assert results[0]["id"] == "VM-DAEMON-001"
        assert results[0]["metadata"]["source"] == "cognitive-daemon"

        print("✅ test_relay_find_daemon_memories 通过")
        return True


def test_relay_filter_non_daemon():
    """接力：只返回source=cognitive-daemon的记忆，排除其他来源"""
    from cognitive_hook import find_daemon_memories_for_files

    commit_files = ["some_file.py"]

    with patch("cognitive_hook.CognitiveLoopEntry") as MockCLE:
        mock_instance = MockCLE.return_value
        mock_instance.search.return_value = [
            {
                "id": "VM-DAEMON-001",
                "content": "[文件变更] bayesian_memory_updater.py",
                "metadata": {"source": "cognitive-daemon", "confidence": 0.2, "verify_count": 0},
            },
            {
                "id": "VM-GIT-001",
                "content": "[新功能] some commit",
                "metadata": {"source": "git-post-commit", "confidence": 0.3, "verify_count": 1},
            },
        ]

        results = find_daemon_memories_for_files(commit_files)

        # 只应返回1条daemon记忆
        assert len(results) == 1, f"应过滤掉非daemon记忆: {len(results)}"
        assert results[0]["metadata"]["source"] == "cognitive-daemon"

        print("✅ test_relay_filter_non_daemon 通过")
        return True


def test_relay_verify_daemon_memories():
    """接力：对找到的daemon记忆执行verify(success=True)"""
    from cognitive_hook import relay_verify_daemon_memories

    daemon_memories = [
        {
            "id": "VM-DAEMON-001",
            "content": "[文件变更] bayesian_memory_updater.py",
            "metadata": {"source": "cognitive-daemon", "confidence": 0.2, "verify_count": 0},
        },
        {
            "id": "VM-DAEMON-002",
            "content": "[文件变更] test.py",
            "metadata": {"source": "cognitive-daemon", "confidence": 0.2, "verify_count": 0},
        },
    ]

    with patch("cognitive_hook.CognitiveLoopEntry") as MockCLE:
        mock_instance = MockCLE.return_value
        mock_instance.verify.return_value = {
            "memory_id": "VM-DAEMON-001",
            "success": True,
            "new_confidence": 0.35,
            "new_quality": "C",
        }

        result = relay_verify_daemon_memories(daemon_memories)

        # verify应该被调用2次（每条daemon记忆一次）
        assert mock_instance.verify.call_count == 2, f"verify应调用2次: {mock_instance.verify.call_count}"
        # 返回结果应包含verified数量
        assert result["verified_count"] == 2
        assert result["memory_ids"] == ["VM-DAEMON-001", "VM-DAEMON-002"]

        print("✅ test_relay_verify_daemon_memories 通过")
        return True


def test_relay_verify_empty_list():
    """接力：空列表不调用verify"""
    from cognitive_hook import relay_verify_daemon_memories

    with patch("cognitive_hook.CognitiveLoopEntry") as MockCLE:
        mock_instance = MockCLE.return_value

        result = relay_verify_daemon_memories([])

        assert not mock_instance.verify.called, "空列表不应调用verify"
        assert result["verified_count"] == 0

        print("✅ test_relay_verify_empty_list 通过")
        return True


def test_relay_verify_skips_already_verified():
    """接力：跳过已经verify过的记忆（verify_count > 0）"""
    from cognitive_hook import relay_verify_daemon_memories

    daemon_memories = [
        {
            "id": "VM-DAEMON-001",
            "content": "[文件变更] new.py",
            "metadata": {"source": "cognitive-daemon", "confidence": 0.2, "verify_count": 0},
        },
        {
            "id": "VM-DAEMON-002",
            "content": "[文件变更] old.py",
            "metadata": {"source": "cognitive-daemon", "confidence": 0.5, "verify_count": 3},
        },
    ]

    with patch("cognitive_hook.CognitiveLoopEntry") as MockCLE:
        mock_instance = MockCLE.return_value
        mock_instance.verify.return_value = {"success": True}

        result = relay_verify_daemon_memories(daemon_memories)

        # 只应verify 1次（跳过verify_count=3的）
        assert mock_instance.verify.call_count == 1, f"应只verify 1次: {mock_instance.verify.call_count}"
        assert result["verified_count"] == 1
        assert result["skipped_count"] == 1

        print("✅ test_relay_verify_skips_already_verified 通过")
        return True


def test_relay_integration_in_trigger_loop():
    """接力：trigger_cognitive_loop中集成接力verify"""
    from cognitive_hook import trigger_cognitive_loop

    commit_info = {
        "hash": "abc123",
        "message": "feat: add bayesian optimization",
        "files": ["bayesian_memory_updater.py"],
        "insertions": 50,
        "deletions": 10,
    }

    with patch("cognitive_hook.CognitiveLoopEntry") as MockCLE:
        mock_instance = MockCLE.return_value
        # record返回记忆ID
        mock_instance.record.return_value = "VM-GIT-001"
        # verify返回更新结果
        mock_instance.verify.return_value = {"success": True, "new_confidence": 0.4}
        # search返回daemon记忆（source在metadata内）
        mock_instance.search.return_value = [
            {
                "id": "VM-DAEMON-001",
                "content": "[文件变更] bayesian_memory_updater.py",
                "metadata": {"source": "cognitive-daemon", "confidence": 0.2, "verify_count": 0},
            }
        ]

        result = trigger_cognitive_loop(commit_info, dry_run=False, verbose=True)

        # 应该record了自己的记忆
        assert mock_instance.record.called, "应record git hook记忆"
        # 应该verify了自己的记忆
        assert mock_instance.verify.called, "应verify"
        # 应该search了daemon记忆（接力）
        assert mock_instance.search.called, "应search daemon记忆"

        # 结果中应包含relay信息
        assert "relay_verified" in result, f"结果应包含relay_verified: {result}"
        assert result["relay_verified"] >= 0

        print("✅ test_relay_integration_in_trigger_loop 通过")
        return True


if __name__ == "__main__":
    print("=" * 60)
    print("🔴 TDD RED 阶段：接力机制测试（期望失败）")
    print("=" * 60)

    tests = [
        ("test_relay_find_daemon_memories", test_relay_find_daemon_memories),
        ("test_relay_filter_non_daemon", test_relay_filter_non_daemon),
        ("test_relay_verify_daemon_memories", test_relay_verify_daemon_memories),
        ("test_relay_verify_empty_list", test_relay_verify_empty_list),
        ("test_relay_verify_skips_already_verified", test_relay_verify_skips_already_verified),
        ("test_relay_integration_in_trigger_loop", test_relay_integration_in_trigger_loop),
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

    print("\n" + "=" * 60)
    print(f"📊 结果: 通过 {passed} / {len(tests)}, 失败 {failed}")
    if failures:
        for n, r in failures:
            print(f"  - {n}: {r}")
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)
