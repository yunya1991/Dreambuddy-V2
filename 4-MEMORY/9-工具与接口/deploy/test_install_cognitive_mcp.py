"""安装器配置生成测试：跨宿主的 env / 只读 / 共享库 / print-config。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import install_cognitive_mcp as inst  # noqa: E402


def test_build_mcp_config_default_write_env():
    cfg = inst.build_mcp_config("python")
    env = cfg["env"]
    assert env["PYTHONUTF8"] == "1"
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["COGNITIVE_MCP_WRITE_ENABLED"] == "true"
    assert env["COGNITIVE_MCP_DEFAULT_PRINCIPAL"] == "admin"
    assert env["COGNITIVE_MCP_MODE"] == "ssh"
    assert "COGNITIVE_MCP_DB_PATH" not in env


def test_build_mcp_config_read_only():
    cfg = inst.build_mcp_config("python", read_only=True)
    env = cfg["env"]
    assert env["COGNITIVE_MCP_MODE"] == "local"
    assert env["COGNITIVE_MCP_WRITE_ENABLED"] == "false"
    assert env["COGNITIVE_MCP_DEFAULT_PRINCIPAL"] == "worker"


def test_build_mcp_config_shared_db():
    cfg = inst.build_mcp_config("python", db_path="C:/tmp/shared.db")
    assert cfg["env"]["COGNITIVE_MCP_DB_PATH"] == "C:/tmp/shared.db"


def test_remote_config_write_env():
    cfg = inst.build_remote_ssh_config("dreambuddy-remote")
    cmd = " ".join(cfg["args"])
    assert "PYTHONUTF8=1" in cmd
    assert "COGNITIVE_MCP_WRITE_ENABLED=true" in cmd
    assert "COGNITIVE_MCP_DEFAULT_PRINCIPAL=admin" in cmd


def test_remote_config_read_only():
    cfg = inst.build_remote_ssh_config("dreambuddy-remote", read_only=True)
    cmd = " ".join(cfg["args"])
    assert "COGNITIVE_MCP_WRITE_ENABLED" not in cmd


def test_print_config_outputs_valid_json(capsys, monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["install_cognitive_mcp.py", "--print-config", "--target", "claude"],
    )
    inst.main()
    data = json.loads(capsys.readouterr().out)
    assert data["mcpServers"]["cognitive"]["env"]["PYTHONUTF8"] == "1"
