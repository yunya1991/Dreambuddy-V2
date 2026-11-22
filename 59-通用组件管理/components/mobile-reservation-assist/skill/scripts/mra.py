#!/usr/bin/env python3
"""59 域代理壳：转发到手机 AGENT 主仓 mra.py（实现与状态只一份）。

解析顺序：MOBILE_AGENT_CLI → ~/.config/dreambuddy/mobile_agent.path → 默认路径。
本文件由 tools/sync_mobile.py 生成，请勿手改。
"""

import os
import sys
from pathlib import Path

PROXY_MARKER = "59 域代理壳"
DEFAULT_CLI = Path.home() / "Documents" / "顺风车业务" / "mobile-reservation-assist" / "skill" / "scripts" / "mra.py"


if __name__ != "__main__":
    # 被组件单测 import 时不 exec 主仓 CLI，交给 unittest 跳过整个用例模块
    import unittest

    raise unittest.SkipTest("59 域副本：mra 为代理壳，真实实现与用例在主仓执行")


def _resolve():
    env = os.environ.get("MOBILE_AGENT_CLI")
    if env:
        return Path(env).expanduser()
    cfg = Path.home() / ".config" / "dreambuddy" / "mobile_agent.path"
    if cfg.is_file():
        try:
            candidate = Path(cfg.read_text(encoding="utf-8").strip()).expanduser()
        except OSError:
            candidate = None
        if candidate and candidate.is_file():
            return candidate
    return DEFAULT_CLI


cli = _resolve()
if not cli.is_file():
    sys.stderr.write("E_CLI：未找到手机 AGENT 主仓 mra.py：{}\n".format(cli))
    raise SystemExit(2)

os.execv(sys.executable, [sys.executable, str(cli), *sys.argv[1:]])
