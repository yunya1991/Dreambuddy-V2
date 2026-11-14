#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""兼容转发 shim：OKX 客户端实现已迁至 22 域执行引擎（Plan A）。

- 依赖方向：11 → 22，禁止 22 反向 import 11；
- 新代码请直接：``from executors.okx_client import OKXSimulatedClient``；
- 旧调用 ``from okx_simulated import OKXSimulatedClient`` 与
  ``python -m scripts.memory_l4.okx_simulated <command>`` 继续可用。

说明：交易所凭据只在 22 域加密凭据库，本模块不再读取 11/.env。
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_EXECUTORS_ROOT = _REPO_ROOT / "22-执行引擎中心"
if str(_EXECUTORS_ROOT) not in sys.path:
    sys.path.insert(0, str(_EXECUTORS_ROOT))

from executors.okx_client import *  # noqa: E402,F401,F403
from executors.okx_client import (  # noqa: E402
    cli,
)

if __name__ == "__main__":
    cli()
