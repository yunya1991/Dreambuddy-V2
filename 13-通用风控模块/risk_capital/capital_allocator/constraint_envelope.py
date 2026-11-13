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

# N6（SPEC-M1 M11）：SSoT 总线版本戳校验。
# 16 约束包络的 SSoT 为 42 信号总线（source=43-strategic）；文件为本地镜像。
# 当文件 ts 与总线 ts 不一致时，取保守值（caps 取 min，net_bias 取 abs 更小）+ degraded。
DEFAULT_BUS_PATH = _PROJECT_DIR / "42-神经网络交易协调层" / "runtime" / "bus_state.json"
_BUS_SOURCE = "43-strategic"
_BUS_ASSET_CLASS = "crypto_usdt"

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
    # N6：额外与总线做版本戳校验，不一致时取保守值 + degraded=True。

    def __init__(
        self,
        signal_path: Optional[Path] = None,
        cache_ttl: int = 600,
        bus_path: Optional[Path] = None,
    ) -> None:
        self._signal_path = Path(signal_path) if signal_path else DEFAULT_SIGNAL_PATH
        self._bus_path = Path(bus_path) if bus_path else DEFAULT_BUS_PATH
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
        # N6：读取后与总线做版本戳校验，不一致时取保守值 + degraded=True。
        try:
            if not self._signal_path.exists():
                return None
            data = json.loads(self._signal_path.read_text(encoding="utf-8"))
            file_envelope, file_ts = self._extract_envelope(data)
            if file_envelope is None:
                return None

            # ── N6：总线版本戳校验 ──
            # 仅当文件与总线都有版本戳时才比对；文件无 ts → 直接用文件（旧格式/无版本信息）
            if file_ts is None:
                return file_envelope
            bus_envelope, bus_ts = self._read_bus_envelope()
            if bus_envelope is None or bus_ts is None:
                # 总线不可用 → 回退文件包络
                return file_envelope
            if file_ts == bus_ts:
                # 一致 → 直接用文件包络
                return file_envelope

            # 不一致 → 取保守值 + degraded
            return self._conservative_merge(file_envelope, bus_envelope)
        except (OSError, ValueError, AttributeError, TypeError):
            return None

    @staticmethod
    def _extract_envelope(data: Any) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
        """从信号 dict 提取 crypto_usdt 约束包络 + ts。返回 (envelope, ts)。"""
        if not isinstance(data, dict):
            return None, None
        ts = data.get("ts")
        payload = data.get("payload") or {}
        group = (payload.get("per_asset_class") or {}).get(_BUS_ASSET_CLASS)
        if not isinstance(group, dict):
            return None, None
        envelope: Dict[str, Any] = {"tier": group.get("tier")}
        for field in _CONSTRAINT_FIELDS:
            value = group.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return None, None  # 任一字段缺失/非法 -> 整体降级
            envelope[field] = value
        return envelope, ts

    def _read_bus_envelope(self) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
        """从 42 总线读取 43-strategic 的 crypto_usdt 约束包络 + ts。"""
        try:
            if not self._bus_path.exists():
                return None, None
            data = json.loads(self._bus_path.read_text(encoding="utf-8"))
            signals = data.get("signals") if isinstance(data, dict) else None
            if not isinstance(signals, list):
                return None, None
            for sig in signals:
                if not isinstance(sig, dict) or sig.get("source") != _BUS_SOURCE:
                    continue
                envelope, ts = self._extract_envelope(sig)
                if envelope is not None:
                    return envelope, ts
            return None, None
        except (OSError, ValueError, AttributeError, TypeError):
            return None, None

    @staticmethod
    def _conservative_merge(file_env: Dict[str, Any], bus_env: Dict[str, Any]) -> Dict[str, Any]:
        """文件与总线不一致时取保守值：caps 取 min，net_bias 取 abs 更小。"""
        merged: Dict[str, Any] = {"tier": file_env.get("tier")}
        for field in _CONSTRAINT_FIELDS:
            fv = file_env.get(field)
            bv = bus_env.get(field)
            if field == "net_bias":
                # 方向偏置：abs 更小 = 更保守（更接近中性）
                if fv is None:
                    merged[field] = bv
                elif bv is None:
                    merged[field] = fv
                else:
                    merged[field] = fv if abs(float(fv)) <= abs(float(bv)) else bv
            else:
                # 杠杆/数量上限：取 min = 更保守
                if fv is None:
                    merged[field] = bv
                elif bv is None:
                    merged[field] = fv
                else:
                    merged[field] = min(float(fv), float(bv))
        merged["degraded"] = True
        merged["version_mismatch"] = True
        return merged
