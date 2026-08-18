#!/usr/bin/env python3
"""
认知会话包裹器测试 — TDD
验证会话生命周期、行动链记录、解决路径生成、事后校验
"""

import os
import sys
import time
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent))


def test_session_lifecycle():
    """会话生命周期：开始→活跃→结束"""
    from cognitive_session import CognitiveSession

    session = CognitiveSession()
    assert session.status == "active"
    assert session.end_time is None

    session.add_action("file_change", "modified test.py", file="test.py")
    assert len(session.action_chain) == 1

    session.end_time = time.time()
    session.status = "ended"
    assert session.status == "ended"
    assert session.duration_seconds > 0

    print("✅ test_session_lifecycle 通过")
    return True


def test_session_manager_new_session_on_inactivity():
    """10分钟无活动后开新会话"""
    from cognitive_session import CognitiveSessionManager, INACTIVITY_THRESHOLD

    tmpdir = tempfile.mkdtemp()
    try:
        mgr = CognitiveSessionManager(sessions_dir=tmpdir)

        # 第一次文件变更 → 新会话
        s1 = mgr.on_file_change("test.py", "added")
        assert s1 is not None
        assert s1.status == "active"
        assert len(s1.action_chain) == 1

        # 模拟10分钟后第二次变更 → 新会话
        mgr._last_activity = time.time() - INACTIVITY_THRESHOLD - 1
        s2 = mgr.on_file_change("other.py", "modified")
        assert s2.id != s1.id, "应开新会话"
        assert s1.status == "ended", "旧会话应已结束"

        # 同一会话内的变更 → 不开新会话
        s3 = mgr.on_file_change("third.py", "modified")
        assert s3.id == s2.id, "短时间内不应开新会话"

        print("✅ test_session_manager_new_session_on_inactivity 通过")
        return True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_action_chain_recording():
    """行动链记录：file_change + tool_call + git_commit"""
    from cognitive_session import CognitiveSessionManager

    tmpdir = tempfile.mkdtemp()
    try:
        mgr = CognitiveSessionManager(sessions_dir=tmpdir)

        session = mgr.on_file_change("main.py", "added")
        mgr.on_tool_call("recall", {"query": "test"}, "found 2 memories")
        mgr.on_tool_call("record", {"content": "test"}, "VM-001")

        commit_info = {
            "hash": "abc123",
            "message": "feat: add feature",
            "files": ["main.py"],
            "insertions": 10,
            "deletions": 0,
        }
        mgr.on_commit(commit_info)

        # 会话应已结束
        assert session.status == "ended"
        # 行动链应有4条：1 file_change + 2 tool_call + 1 git_commit
        assert len(session.action_chain) == 4, f"行动链应有4条: {len(session.action_chain)}"

        # 验证行动类型
        types = [a["action_type"] for a in session.action_chain]
        assert "file_change" in types
        assert "tool_call" in types
        assert "git_commit" in types

        print("✅ test_action_chain_recording 通过")
        return True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_infer_task_type():
    """任务类型推断"""
    from cognitive_session import infer_task_type

    # 基础场景
    assert infer_task_type(["4-MEMORY/test.py"]) == "memory-system"
    assert infer_task_type(["11-易经推理系统/test.py"]) == "strategy-execution"  # P0: .py 交易代码
    assert infer_task_type(["0-系统文档管理/test.md"]) == "documentation"
    assert infer_task_type(["unknown.py"]) == "python-development"
    assert infer_task_type(["unknown.md"]) == "documentation"
    assert infer_task_type([]) == "general"
    # 非 .py 的交易目录文件仍为 trading-system
    assert infer_task_type(["11-易经推理系统/README.md"]) == "trading-system"

    # P0: experiments/ab-trading/ 纳入交易目录
    assert infer_task_type(["experiments/ab-trading/core/nodes/a0_contradiction.py"]) == "strategy-execution"
    assert infer_task_type(["experiments/ab-trading/backtest/indicator_backtest.py"]) == "strategy-backtest"

    # P0: 6-TRADING 细粒度 task_type
    assert infer_task_type(["6-TRADING/skills/dream-strategy-research/SKILL.md"]) == "strategy-research"
    assert infer_task_type(["6-TRADING/docs/TRIGGER_PROMPTS.md"]) == "strategy-governance"
    assert infer_task_type(["6-TRADING/A系列研报/A1研报/report.json"]) == "trading-data"

    # P0: 11-易经推理系统 调度配置
    assert infer_task_type(["11-易经推理系统/.github/workflows/trading-a4-validation.yml"]) == "strategy-governance"

    # P0: 10-经典指标系统 改指标代码
    assert infer_task_type(["10-经典指标系统/indicators/rsi.py"]) == "strategy-execution"

    print("✅ test_infer_task_type 通过")
    return True


def test_generate_solution_path():
    """解决路径生成：从行动链推断问题→方案→结果"""
    from cognitive_session import CognitiveSession, generate_solution_path

    session = CognitiveSession()
    session.add_action("file_change", "modified bayesian.py", file="bayesian.py")
    session.add_action("tool_call", "recall('bayesian')", tool="recall")
    session.add_action("file_change", "modified test.py", file="test.py")
    session.files_touched = {"bayesian.py", "test.py"}

    commit_info = {
        "hash": "abc123",
        "message": "feat: add bayesian optimization",
        "files": ["bayesian.py", "test.py"],
    }

    path = generate_solution_path(session, commit_info)

    assert "problem" in path
    assert "approach" in path
    assert "outcome" in path
    assert "feat: add bayesian optimization" in path["problem"]
    assert path["outcome"]["success"] == True
    assert path["outcome"]["commit_hash"] == "abc123"
    assert "bayesian.py" in path["approach"]["files_touched"]
    assert "[解决路径]" in path["content"]

    print("✅ test_generate_solution_path 通过")
    return True


def test_post_hoc_verify_followed_success():
    """事后校验：遵循建议+成功 → 旧经验verify(success=True)"""
    from cognitive_session import CognitiveSession, post_hoc_verify

    session = CognitiveSession()
    session.recalled_memory_ids = ["VM-001"]
    session.add_action("file_change", "modified bayesian.py", file="bayesian.py")
    session.files_touched = {"bayesian.py"}

    solution_path = {
        "content": "[解决路径] test",
        "outcome": {"success": True},
        "approach": {"files_touched": ["bayesian.py"]},
    }

    with patch("cognitive_session.CognitiveLoopEntry") as MockCLE:
        mock_instance = MockCLE.return_value
        mock_instance.search.return_value = [
            {"id": "VM-001", "content": "bayesian.py needs Beta distribution"}
        ]
        mock_instance.verify.return_value = {"success": True}

        post_hoc_verify(mock_instance, session, solution_path, "SP-001")

        # 应该verify(success=True)
        mock_instance.verify.assert_called_with("VM-001", success=True)

        print("✅ test_post_hoc_verify_followed_success 通过")
        return True


def test_post_hoc_verify_not_followed_failure():
    """事后校验：未遵循+失败 → 旧经验verify(success=True)（间接验证）"""
    from cognitive_session import CognitiveSession, post_hoc_verify

    session = CognitiveSession()
    session.recalled_memory_ids = ["VM-001"]
    session.add_action("file_change", "modified completely_different.py", file="completely_different.py")
    session.files_touched = {"completely_different.py"}

    solution_path = {
        "content": "[解决路径] test",
        "outcome": {"success": False},
        "approach": {"files_touched": ["completely_different.py"]},
    }

    with patch("cognitive_session.CognitiveLoopEntry") as MockCLE:
        mock_instance = MockCLE.return_value
        mock_instance.search.return_value = [
            {"id": "VM-001", "content": "use_alpha_beta_optimization.py for this"}
        ]
        mock_instance.verify.return_value = {"success": True}

        post_hoc_verify(mock_instance, session, solution_path, "SP-001")

        # 未遵循+失败 → 旧经验更可信 → verify(success=True)
        mock_instance.verify.assert_called_with("VM-001", success=True)

        print("✅ test_post_hoc_verify_not_followed_failure 通过")
        return True


def test_post_hoc_verify_no_recall():
    """事后校验：无recall注入时不校验"""
    from cognitive_session import CognitiveSession, post_hoc_verify

    session = CognitiveSession()
    session.recalled_memory_ids = []  # 无recall

    solution_path = {
        "content": "test",
        "outcome": {"success": True},
        "approach": {"files_touched": []},
    }

    with patch("cognitive_session.CognitiveLoopEntry") as MockCLE:
        mock_instance = MockCLE.return_value

        post_hoc_verify(mock_instance, session, solution_path, "SP-001")

        # 不应调用verify
        mock_instance.verify.assert_not_called()

        print("✅ test_post_hoc_verify_no_recall 通过")
        return True


def test_find_similar_solutions():
    """路径对比：检索同一问题的不同解法"""
    from cognitive_session import find_similar_solutions

    with patch("cognitive_session.CognitiveLoopEntry") as MockCLE:
        mock_instance = MockCLE.return_value
        mock_instance.search.return_value = [
            {"id": "SP-001", "content": "[解决路径] A方案", "metadata": {"confidence": 0.8}},
            {"id": "SP-002", "content": "[解决路径] B方案", "metadata": {"confidence": 0.5}},
        ]

        results = find_similar_solutions("bayesian optimization", cle=mock_instance)

        assert len(results) == 2
        # 应按置信度降序排序
        assert results[0]["metadata"]["confidence"] >= results[1]["metadata"]["confidence"]

        print("✅ test_find_similar_solutions 通过")
        return True


def test_sp_deposit_threshold():
    """SP沉淀门槛：低活跃不沉淀，高活跃/有commit/多文件才沉淀"""
    from cognitive_session import (
        CognitiveSession,
        CognitiveSessionManager,
        SP_DEPOSIT_MIN_ACTIONS,
        SP_DEPOSIT_MIN_FILES,
    )

    tmpdir = tempfile.mkdtemp()
    try:
        mgr = CognitiveSessionManager(sessions_dir=tmpdir)

        # 场景1: 低活跃 (action=2, files=1, 无commit) -> 不沉淀
        s1 = CognitiveSession()
        s1.add_action("file_change", "modified a.py", file="a.py")
        s1.add_action("tool_call", "recall", tool="recall")
        s1.files_touched = {"a.py"}
        assert mgr._should_deposit_sp(s1, None) is False, "低活跃不应沉淀SP"

        # 场景2: 高活跃 (action >= 阈值) -> 沉淀
        s2 = CognitiveSession()
        for i in range(SP_DEPOSIT_MIN_ACTIONS):
            s2.add_action("file_change", "m f{}.py".format(i), file="f{}.py".format(i))
        assert mgr._should_deposit_sp(s2, None) is True, "action>=阈值应沉淀SP"

        # 场景3: 有 commit -> 沉淀（即使action很少）
        s3 = CognitiveSession()
        s3.add_action("file_change", "m a.py", file="a.py")
        assert mgr._should_deposit_sp(s3, {"hash": "abc"}) is True, "有commit应沉淀SP"

        # 场景4: 多文件 (files >= 阈值) -> 沉淀
        s4 = CognitiveSession()
        s4.add_action("file_change", "m a.py", file="a.py")
        s4.files_touched = {"a.py", "b.py", "c.py", "d.py", "e.py"}
        assert len(s4.files_touched) >= SP_DEPOSIT_MIN_FILES, "前置:文件数应达标"
        assert mgr._should_deposit_sp(s4, None) is True, "files>=阈值应沉淀SP"

        print("✅ test_sp_deposit_threshold 通过")
        return True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_session_persistence():
    """会话持久化：session.json + action_chain.jsonl"""
    from cognitive_session import CognitiveSessionManager

    tmpdir = tempfile.mkdtemp()
    try:
        mgr = CognitiveSessionManager(sessions_dir=tmpdir)

        session = mgr.on_file_change("test.py", "added")
        mgr.on_tool_call("recall", {"query": "test"}, "found memories")

        # 检查文件是否生成
        session_dir = Path(tmpdir) / session.id
        assert (session_dir / "session.json").exists(), "session.json应存在"
        assert (session_dir / "action_chain.jsonl").exists(), "action_chain.jsonl应存在"

        # 验证session.json内容
        import json
        meta = json.loads((session_dir / "session.json").read_text())
        assert meta["id"] == session.id
        assert meta["status"] == "active"
        assert meta["action_count"] == 2

        print("✅ test_session_persistence 通过")
        return True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    print("=" * 60)
    print("🧪 认知会话包裹器测试")
    print("=" * 60)

    tests = [
        ("test_session_lifecycle", test_session_lifecycle),
        ("test_session_manager_new_session_on_inactivity", test_session_manager_new_session_on_inactivity),
        ("test_action_chain_recording", test_action_chain_recording),
        ("test_infer_task_type", test_infer_task_type),
        ("test_generate_solution_path", test_generate_solution_path),
        ("test_post_hoc_verify_followed_success", test_post_hoc_verify_followed_success),
        ("test_post_hoc_verify_not_followed_failure", test_post_hoc_verify_not_followed_failure),
        ("test_post_hoc_verify_no_recall", test_post_hoc_verify_no_recall),
        ("test_find_similar_solutions", test_find_similar_solutions),
        ("test_sp_deposit_threshold", test_sp_deposit_threshold),
        ("test_session_persistence", test_session_persistence),
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
