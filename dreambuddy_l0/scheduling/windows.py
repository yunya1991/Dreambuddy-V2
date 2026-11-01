"""UTC 逻辑窗口 math（C9）。

口径：
  - 窗口编号 = floor(epoch_sec / window_sec)，与 UTC 整点对齐；
  - 迟到容忍 5min：窗口结束后再等 300s 才判定 closed（避免误报 missed_run）；
  - 跨窗 run 按窗口边界拆成多段，每段一个逻辑窗口。
"""

from __future__ import annotations

from typing import List, Tuple

DEFAULT_LATE_TOLERANCE_SEC = 300

Segment = Tuple[int, float, float]


def window_index(ts: float, window_sec: int) -> int:
    if window_sec <= 0:
        raise ValueError("window_sec 必须 > 0")
    return int(ts // window_sec)


def window_start(index: int, window_sec: int) -> float:
    return float(index * window_sec)


def is_window_closed(
    now_ts: float,
    start_ts: float,
    window_sec: int,
    tolerance_sec: int = DEFAULT_LATE_TOLERANCE_SEC,
) -> bool:
    """窗口是否已过「结束 + 迟到容忍」，可以判定 missed_run。"""
    return now_ts >= start_ts + window_sec + tolerance_sec


def split_segments(start_ts: float, end_ts: float, window_sec: int) -> List[Segment]:
    """把一次跨窗执行拆成 (window_index, seg_start, seg_end) 序列。"""
    if window_sec <= 0:
        raise ValueError("window_sec 必须 > 0")
    end_ts = max(float(end_ts), float(start_ts))
    segments: List[Segment] = []
    cursor = float(start_ts)
    while True:
        idx = window_index(cursor, window_sec)
        boundary = window_start(idx + 1, window_sec)
        seg_end = min(float(end_ts), boundary)
        segments.append((idx, cursor, seg_end))
        if seg_end >= end_ts:
            break
        cursor = seg_end
    return segments
