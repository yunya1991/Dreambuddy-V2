# -*- coding: utf-8 -*-
"""45 门禁 shadow→硬门 误拦率统计与转正判据(T-DSH-P2 P2-2)。

依据: DESIGN-DSH-ARCH-UPGRADE v0.2 DD4(45 先 shadow,误拦率 <5% 转硬门)。

口径: 误拦率 = shadow 期间「若转硬门会被拦截」的占比
(would_block = verdict ∈ {BLOCK, INCONCLUSIVE, ERROR, TIMEOUT})。
只统计 shadow 模式记录;hard 期记录是真实拦截,不计入误拦口径。

硬约束:
  WORM 语义: 裁决记录只追加不修改
  FAIL-OPEN: 坏路径/坏记录/样本不足 → rate None / promote False(不贸然转硬门)
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

# shadow 期若转硬门会被拦截的裁决集合
WOULD_BLOCK_VERDICTS = ("BLOCK", "INCONCLUSIVE", "ERROR", "TIMEOUT")


def record_verdict(record: Any, path: Any) -> bool:
    """追加一条裁决记录到 jsonl(WORM)。非法输入 → False(FAIL-OPEN)。"""
    try:
        if not isinstance(record, dict) or not record.get("verdict"):
            return False
        if not path:
            return False
        os.makedirs(os.path.dirname(os.path.abspath(str(path))), exist_ok=True)
        with open(str(path), "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False


def load_verdicts(path: Any) -> List[Dict[str, Any]]:
    """读取裁决记录;路径缺失/坏行 → 跳过(FAIL-OPEN 返回已读部分)。"""
    try:
        if not path or not os.path.exists(str(path)):
            return []
        out = []
        with open(str(path), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if isinstance(row, dict):
                    out.append(row)
        return out
    except Exception:
        return []


def would_block_rate(records: Any) -> Optional[float]:
    """shadow 期误拦率: would_block / shadow_total。无 shadow 样本 → None。"""
    try:
        if not isinstance(records, list):
            return None
        shadow = [r for r in records if isinstance(r, dict) and r.get("mode") == "shadow"]
        if not shadow:
            return None
        blocked = sum(1 for r in shadow if r.get("verdict") in WOULD_BLOCK_VERDICTS)
        return blocked / len(shadow)
    except Exception:
        return None


def should_promote_to_hard(
    records: Any,
    threshold: float = 0.05,
    min_samples: int = 20,
) -> bool:
    """DD4 转正判据: shadow 样本 ≥ min_samples 且误拦率 < threshold。

    任何一项不满足或数据不可用 → False(不贸然转硬门,FAIL-OPEN)。
    """
    try:
        if not isinstance(records, list):
            return False
        shadow = [r for r in records if isinstance(r, dict) and r.get("mode") == "shadow"]
        if len(shadow) < int(min_samples):
            return False
        rate = would_block_rate(records)
        if rate is None:
            return False
        return rate < float(threshold)
    except Exception:
        return False
