"""P0-1-S1: meaningful_types 白名单扩展验证

验证 HC-11 边界守护：
- 5 个新事件类型（algorithm.decision/shadow.review/training.dataset/model.update/agent.takeover）不被过滤
- file_edit/shell_command 仍被过滤
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# 将 python-server 目录加入 sys.path
_SERVER_DIR = str(Path(__file__).resolve().parent.parent / "packages" / "python-server")
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)


def test_new_event_types_not_filtered():
    """验证 5 个新事件类型不被 meaningful_types 过滤"""
    from server import _trigger_cognitive_record

    new_types = [
        "algorithm.decision",
        "shadow.review",
        "training.dataset",
        "model.update",
        "agent.takeover",
    ]

    for event_type in new_types:
        event_entry = {
            "event_type": event_type,
            "session_id": "test-session",
            "event_data": {"key": "value"},
        }

        with patch("subprocess.Popen") as mock_popen, patch("server._try_mcp_record") as mock_mcp:
            _trigger_cognitive_record(event_entry)
            # 如果事件类型通过过滤，会尝试调用 subprocess.Popen
            assert mock_popen.called or mock_mcp.called, (
                f"事件类型 '{event_type}' 被过滤了（不应被过滤）"
            )


def test_noise_events_still_filtered():
    """验证 file_edit/shell_command 仍被过滤（HC-11）"""
    from server import _trigger_cognitive_record

    noise_types = ["file_edit", "shell_command", "unknown_event", ""]

    for event_type in noise_types:
        event_entry = {
            "event_type": event_type,
            "session_id": "test-session",
            "event_data": {"key": "value"},
        }

        with patch("subprocess.Popen") as mock_popen, patch("server._try_mcp_record") as mock_mcp:
            _trigger_cognitive_record(event_entry)
            # 噪音事件应该被过滤，不调用 subprocess.Popen
            assert not mock_popen.called, (
                f"事件类型 '{event_type}' 未被过滤（应被过滤）"
            )
            assert not mock_mcp.called, (
                f"事件类型 '{event_type}' 未被过滤（应被过滤）"
            )


def test_existing_events_still_pass():
    """验证原有 3 个事件类型仍不被过滤"""
    from server import _trigger_cognitive_record

    existing_types = ["intent_gate", "node_result", "graph_node"]

    for event_type in existing_types:
        event_entry = {
            "event_type": event_type,
            "session_id": "test-session",
            "event_data": {"key": "value"},
        }

        with patch("subprocess.Popen") as mock_popen, patch("server._try_mcp_record") as mock_mcp:
            _trigger_cognitive_record(event_entry)
            assert mock_popen.called or mock_mcp.called, (
                f"原有事件类型 '{event_type}' 被过滤了（不应被过滤）"
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
