#!/usr/bin/env python3
"""认知壳双模（D5 / M3⑧）单测 — V7 验收。

覆盖：
  - 默认模式（ssh 云端）：写工具正常受理（不拒绝）
  - local 模式：record/verify 写工具明确拒绝（ok=false + error_code=conflict），非静默
  依赖 COGNITIVE_MCP_MODE 环境变量在模块导入时生效，故用子进程隔离两种模式
"""

import json
import os
import subprocess
import sys
from pathlib import Path

_PARENT = Path(__file__).resolve().parent.parent


def _call_handler(mode: str, tool: str, args: dict) -> dict:
    """以指定模式拉起子进程调用写工具，返回解析后的信封。"""
    code = (
        "import json, sys; sys.path.insert(0, r'%s');\n"
        "import cognitive_mcp_server as s;\n"
        "r = s._handle_%s(%s);\n"
        "print(json.dumps(json.loads(r)))"
    ) % (str(_PARENT), tool, repr(args))
    env = dict(os.environ)
    env["COGNITIVE_MCP_MODE"] = mode
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    lines = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()]
    assert lines, f"no stdout; stderr={proc.stderr}"
    return json.loads(lines[-1])


def test_local_mode_record_denied():
    """V7：local 模式 record 写工具明确拒绝（非静默）。"""
    env = _call_handler("local", "record", {"content": "test"})
    assert env["ok"] is False
    assert env["error_code"] == "conflict"
    assert "readonly" in json.dumps(env).lower() or "local" in json.dumps(env).lower()


def test_local_mode_verify_denied():
    """V7：local 模式 verify 写工具明确拒绝。"""
    env = _call_handler("local", "verify", {"memory_id": "VM-test", "success": True})
    assert env["ok"] is False
    assert env["error_code"] == "conflict"


def test_default_ssh_mode_write_allowed():
    """默认模式（ssh）：写工具正常受理（不因模式被拒绝）。"""
    env = _call_handler("ssh", "record", {"content": "dual-mode-test", "quality_level": "C"})
    # ssh 模式下 record 不被模式门禁拒绝（业务错误不算，只验证不是 conflict/readonly 拒绝）
    assert not (
        env["ok"] is False and env.get("error_code") == "conflict"
    ), f"ssh mode record should not be mode-denied: {env}"
