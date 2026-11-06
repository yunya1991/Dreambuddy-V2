#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""11-washout 子池 Publisher 适配器（42 层 registry.yaml 声明的接入点）。

P1-04/DEC-08：只读 11 层子池状态文件
scripts/memory_l4/runtime/subpool_state/washout_entry_state.json
（polling_trader 影子信号落盘，无内存耦合），发布 source=11-washout。
- horizon=hours；expires_at 24h；TTL 预检 24h
- 开关 ENABLE_11_STATE_ADAPTER=1（默认关闭=回滚路径）
- fail-open：状态文件缺失/损坏/过期 → 不发布，不阻断总线

用法：python3 washout_state_adapter.py（独立运行时打印发布结果）
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _subpool_state_common import run  # noqa: E402

_DREAMBUDDY_ROOT = os.environ.get("DREAMBUDDY_ROOT") or os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

_STATE_PATH = os.path.join(
    _DREAMBUDDY_ROOT,
    "11-易经推理系统",
    "scripts",
    "memory_l4",
    "runtime",
    "subpool_state",
    "washout_entry_state.json",
)


def main() -> int:
    return run(
        source="11-washout",
        state_path=_STATE_PATH,
        horizon="hours",
        ttl_hours=24,
        max_age_hours=24,
    )


if __name__ == "__main__":
    sys.exit(main())
