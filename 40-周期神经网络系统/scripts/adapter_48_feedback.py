"""adapter_48_feedback.py — 40 侧 48 反馈适配器（P0 网关消费端）。

纪律（SPEC-NN-FEEDBACK-GATEWAY §3.1）：
  - 双读并行，`ENABLE_40_VIA_48` 默认关；
  - 只读 48 输出，不改变 40 encoder 维度/权重；
  - 文件缺失/解析失败一律 FAIL-OPEN 返回 None，40 继续直读 39/9。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FEEDBACK = _REPO_ROOT / "48-涌现架构" / "events" / "nn_feedback" / "40_feedback.json"


def enabled() -> bool:
    return os.getenv("ENABLE_40_VIA_48", "0").strip().lower() in {"1", "true", "yes", "on"}


def load_48_feedback(path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    if not enabled():
        return None
    target = Path(path) if path else DEFAULT_FEEDBACK
    try:
        if target.exists():
            obj = json.loads(target.read_text(encoding="utf-8"))
            return obj if isinstance(obj, dict) else None
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        logger.warning("48 feedback 读取失败（降级直读）: %s", exc)
    return None


def attach_to_payload(payload: Dict[str, Any], path: Optional[Path] = None) -> Dict[str, Any]:
    """把 48 反馈挂到 40 payload 的 `_feedback_48`，供双读校验与审计。"""
    fb = load_48_feedback(path)
    if fb is not None:
        payload["_feedback_48"] = fb
    return payload
