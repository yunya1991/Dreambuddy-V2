"""路径 B/C 预热单测（设计节 3.1 + 3.4）。"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_session_start_hook_command_contains_process_warmup():
    """设计节 3.4：SessionStart hook 命令含 process 预热。"""
    from cognitive_install import get_claude_hooks_config
    config = get_claude_hooks_config()
    session_start_hooks = config["hooks"]["SessionStart"]
    cmd = session_start_hooks[0]["hooks"][0]["command"]
    assert "warmup_process" in cmd, f"SessionStart hook 缺少 process 预热: {cmd}"
    assert "2>/dev/null" in cmd or "&" in cmd or "true" in cmd


def test_daemon_has_on_new_session_created():
    """设计节 3.1 路径 C：daemon 有 on_new_session_created 预热方法。"""
    from cognitive_daemon import CognitiveDaemon
    daemon = CognitiveDaemon.__new__(CognitiveDaemon)
    assert hasattr(daemon, "on_new_session_created"), "CognitiveDaemon 缺少 on_new_session_created"


def test_daemon_warmup_skips_if_process_block_nonempty():
    """设计节改 6：process_block 已非空时跳过（与路径 B 去重）。"""
    from cognitive_daemon import CognitiveDaemon
    daemon = CognitiveDaemon.__new__(CognitiveDaemon)
    daemon.verbose = False
    fake_wm = MagicMock()
    fake_wm.process_block = {"P-meta-tdd": "already here"}
    result = daemon.on_new_session_created("CS-test", "fix bug", working_memory=fake_wm)
    assert result["skipped"] is True
    assert "nonempty" in result["reason"]


def test_daemon_warmup_writes_process_block_when_empty():
    """设计节 3.1：process_block 为空时写入预热结果。"""
    from cognitive_daemon import CognitiveDaemon
    daemon = CognitiveDaemon.__new__(CognitiveDaemon)
    daemon.verbose = False
    fake_wm = MagicMock()
    fake_wm.process_block = {}
    with patch("cognitive_daemon._get_skill_loader") as mock_loader:
        mock_loader.return_value.retrieve.return_value = {
            "meta": [{"skill_id": "tdd", "injection": "HARD-GATE..."}],
            "applied": [],
            "process_block_markdown": "## 流程建议\ntdd content",
        }
        result = daemon.on_new_session_created("CS-test", "write test", working_memory=fake_wm)
    assert result["skipped"] is False
    assert result["injected_count"] >= 1
    fake_wm.load_process_block.assert_called_once()
