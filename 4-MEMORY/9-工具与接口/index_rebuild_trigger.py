"""41 索引增量重建触发器 —— 去抖（SPEC-L0 评审 P0-11）。

背景：认知 `record()` 每写一条记忆就 `Popen` 一次 41 增量索引重建，高频写入
（调度完成回调、批量采集）会反复抢 CPU 拖慢实盘。本模块把触发收敛为
"同一时间窗内只触发一次"，其余请求自然合并到下一次。

约束：
- FAIL-OPEN：任何异常都不阻断调用方，触发失败只影响索引新鲜度；
- G0-2 配置外置：`fis-p0` 路径经 `FIS_P0_HOME` 环境变量读取，禁止硬编码；
- G0-8：与幂等无关——重复 record 仍可能触发，但触发本身已被去抖。
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from typing import Callable, Optional

_DEFAULT_MIN_INTERVAL = 60.0
_last_trigger_ts: Optional[float] = None


def min_interval() -> float:
    """触发窗口（秒），可由 `L0_INDEX_REBUILD_MIN_INTERVAL` 覆盖。"""
    try:
        return float(os.environ.get("L0_INDEX_REBUILD_MIN_INTERVAL", _DEFAULT_MIN_INTERVAL))
    except (TypeError, ValueError):
        return _DEFAULT_MIN_INTERVAL


def should_trigger(now: Optional[float] = None, interval: Optional[float] = None) -> bool:
    """当前时刻是否允许触发（窗口内已触发过则 False）。"""
    now = time.monotonic() if now is None else now
    interval = min_interval() if interval is None else interval
    if _last_trigger_ts is not None and now - _last_trigger_ts < interval:
        return False
    return True


def _default_runner() -> None:
    """实际起 41 索引重建子进程（非阻塞，读 stdin 指令）。"""
    home = os.environ.get("FIS_P0_HOME", "/home/ubuntu/fis-p0")
    proc = subprocess.Popen(
        [
            os.path.join(home, ".venv", "bin", "python"),
            os.path.join(home, "scripts", "search_cli.py"),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={**os.environ, "FIS_PG_PASSWORD": os.environ.get("FIS_PG_PASSWORD")},
    )
    proc.stdin.write(json.dumps({"cmd": "update"}).encode("utf-8"))
    proc.stdin.close()


def trigger(
    runner: Optional[Callable[[], None]] = None,
    *,
    now: Optional[float] = None,
    interval: Optional[float] = None,
) -> bool:
    """去抖触发，返回是否真正执行。异常一律吞掉（FAIL-OPEN）。"""
    global _last_trigger_ts
    try:
        if not should_trigger(now=now, interval=interval):
            return False
        _last_trigger_ts = time.monotonic() if now is None else now
        (runner or _default_runner)()
        return True
    except Exception:
        return False


def reset() -> None:
    """清空去抖窗口（测试用）。"""
    global _last_trigger_ts
    _last_trigger_ts = None
