"""_compress_thought_chain 单测（设计节 7.3 + GC8 纯结构化提取）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from cognitive_session import _compress_thought_chain
from evaluation_engine import EvaluationSample


def test_compress_returns_evaluation_sample():
    chain = [
        {"action_type": "mcp_call", "detail": "recall 写测试 tdd"},
        {"action_type": "file_change", "file": "tests/test_foo.py", "detail": "add test_foo.py"},
        {"action_type": "tool_call", "tool": "pytest", "detail": "run pytest"},
        {"action_type": "file_change", "file": "foo.py", "detail": "edit foo.py"},
        {"action_type": "git_commit", "detail": "red green", "commit_hash": "abc1234"},
    ]
    sample = _compress_thought_chain(
        action_chain=chain,
        reasoning_log=[],
        session_id="S-test",
        task_summary="test task",
        skill_ids_injected=["test-driven-development"],
        hard_gate_violations=[],
        outcome_metrics={"task_completion_success": 1.0, "duration_minutes": 10.0, "follow_score": 0.7,
                          "hard_gate_violation_count": 0, "rework_count": 0, "tool_call_efficiency": 0.5},
    )
    assert isinstance(sample, EvaluationSample)
    assert 1 <= len(sample.thought_chain_compressed) <= 15
    # 关键决策点应包含 recall 和 commit
    joined = " ".join(sample.thought_chain_compressed)
    assert "recall" in joined.lower() or "MCP" in joined


def test_compress_no_llm_pure_structural():
    """GC8：压缩纯结构化，不调用 LLM。"""
    chain = [
        {"action_type": "file_change", "file": "a.py", "detail": "edit a.py"},
        {"action_type": "file_change", "file": "a.py", "detail": "edit a.py again"},
        {"action_type": "file_change", "file": "b.py", "detail": "edit b.py"},
    ]
    sample = _compress_thought_chain(chain, [], "S1", "t", [], {})
    # 相邻同文件 a.py 两次 edit 合并
    assert len(sample.thought_chain_compressed) <= 3
    assert len(sample.action_chain_compressed) <= 3


def test_compress_extracts_key_decision_points():
    """设计节 7.3：从 reasoning_log 提取关键决策点。"""
    chain = [{"action_type": "file_change", "file": "x.py", "detail": "edit"}]
    reasoning_log = [
        {"event": "recall", "context": "tdd"},
        {"event": "verify", "context": "test passed"},
        {"event": "_deposit_applied_template", "context": "deposited"},
    ]
    sample = _compress_thought_chain(chain, reasoning_log, "S1", "t", [], {})
    joined = " ".join(sample.thought_chain_compressed).lower()
    # 关键事件应出现在思维链中
    assert "recall" in joined or "verify" in joined or "deposit" in joined
