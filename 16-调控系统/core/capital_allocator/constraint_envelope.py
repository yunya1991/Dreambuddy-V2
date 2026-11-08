# R1b: 约束包络读取器（43 层 strategic_extension 信号 -> 四档约束钳位）。
#
# 设计约束（对齐 component.py 设计约束）：
#   * 建议制：约束只钳位 position_pct 建议，不拦截开仓
#   * 降级回退：文件缺失/损坏/字段缺失 -> 返回 None（不钳位，保持现有行为）
#   * 缓存复用：信号文件读取缓存（默认 600s），避免高频读盘
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

_ALLOC_DIR = Path(__file__).resolve().parent  # capital_allocator
_PROJECT_DIR = _ALLOC_DIR.parent.parent.parent  # dreambuddy-v2

DEFAULT_SIGNAL_PATH = (
    _PROJECT_DIR / "43-战略承接推演层" / "runtime" / "strategic_extension_signal.json"
)

# 约束包络五字段（与 43 层 signal_publisher / 50 层 constraint_loader 口径一致）
_CONSTRAINT_FIELDS = (
    "leverage_cap",
    "asset_count_cap",
    "long_count_cap",
    "short_count_cap",
    "net_bias",
)

# 杠杆基准档：attack 档 leverage_cap=5 -> 不额外钳位
_LEVERAGE_BASE = 5.0


class ConstraintEnvelopeReader:
    # 读取 43 层信号主类（crypto_usdt）的四档约束包络。
    # 降级语义：任何异常/缺失 -> get_envelope() 返回 None，调用方保持现有行为。

    def __init__(
        self,
        signal_path: Optional[Path] = None,
        cache_ttl: int = 600,
    ) -> None:
        self._signal_path = Path(signal_path) if signal_path else DEFAULT_SIGNAL_PATH
        self._cache_ttl = int(cache_ttl)
        self._lock = threading.Lock()
        self._cached: Optional[Dict[str, Any]] = None
        self._cached_ts: float = 0.0

    def get_envelope(self) -> Optional[Dict[str, Any]]:
        # 返回当前约束包络（tier + 5 字段）；降级时返回 None。
        with self._lock:
            now_ts = time.time()
            if self._cached is not None and (now_ts - self._cached_ts) < self._cache_ttl:
                return self._cached
            envelope = self._read_signal()
            if envelope is not None:
                self._cached = envelope
                self._cached_ts = now_ts
            return envelope

    def leverage_pct_cap(self, max_pct: float) -> Optional[float]:
        # 杠杆钳位映射：pct_cap = max_pct * leverage_cap / 5（attack=5 -> 不额外限）。
        # 降级（无包络/字段非法）返回 None，调用方不钳位。
        env = self.get_envelope()
        if env is None:
            return None
        leverage_cap = env.get("leverage_cap")
        if isinstance(leverage_cap, bool) or not isinstance(leverage_cap, (int, float)):
            return None
        if float(leverage_cap) <= 0:
            return None
        return max_pct * float(leverage_cap) / _LEVERAGE_BASE

    def _read_signal(self) -> Optional[Dict[str, Any]]:
        # 读取 43 层信号文件，提取 crypto_usdt 主类约束包络。
        try:
            if not self._signal_path.exists():
                return None
            data = json.loads(self._signal_path.read_text(encoding="utf-8"))
            payload = data.get("payload") or {}
            group = (payload.get("per_asset_class") or {}).get("crypto_usdt")
            if not isinstance(group, dict):
                return None
            envelope: Dict[str, Any] = {"tier": group.get("tier")}
            for field in _CONSTRAINT_FIELDS:
                value = group.get(field)
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    return None  # 任一字段缺失/非法 -> 整体降级
                envelope[field] = value
            return envelope
        except (OSError, ValueError, AttributeError, TypeError):
            return None
