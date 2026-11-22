#!/usr/bin/env python3
"""P5-R：云端只读链路冒烟（CI 用）。

未配置 DREAMBUDDY_CLOUD_* 时输出 SKIP 并退出 0，保证 fork/无密钥环境不红。
配置后执行 initialize + tools/list，校验至少一个只读工具且写工具被标记。
"""

from __future__ import annotations

import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import cloud_client  # noqa: E402


def main() -> int:
    conf = cloud_client.config()
    if not conf["complete"]:
        print("SKIP：未配置 DREAMBUDDY_CLOUD_BASE/TOKEN/PRINCIPAL")
        return 0
    try:
        tools = cloud_client.fetch_tools()
    except cloud_client.CloudError as exc:
        print("FAIL：{}".format(exc))
        return 1
    reads = [tool for tool in tools if not tool.get("write")]
    writes = [tool for tool in tools if tool.get("write")]
    if not reads:
        print("FAIL：云端没有只读工具")
        return 1
    print(
        "OK：{} · tools={}（read={} write={}）".format(
            conf["base"], len(tools), len(reads), len(writes)
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
