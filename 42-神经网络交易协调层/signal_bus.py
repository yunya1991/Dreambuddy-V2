#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""42 层信号汇聚总线 SignalBus（最小实现，路线 P1 只读汇聚阶段）。

对齐 42 层 SPEC §二：
- 统一 SignalSchema 校验（signal_id/source/ts/symbol/direction/confidence/
  horizon/risk_exposure_hint/expires_at/payload）
- 链式过滤器管道：F1 新鲜度 → F2 置信度 → F3 冲突检测 → F5 归一化
  （F4 数据健康校验暂缓，源数据健康指标待各子系统补齐）
- 纯只读汇聚：不下发任何参数，不修改子系统行为
- fail-open：单信号处理异常不阻断总线，标记 error 状态

Publisher 接入：适配器只读源文件发布信号（§2.3 即插即拔）。
"""

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# 总线状态落盘路径
_BUS_STATE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "runtime", "bus_state.json"
)

# 统一 Schema 必需字段（§2.1）
_REQUIRED_KEYS = (
    "signal_id",
    "source",
    "ts",
    "symbol",
    "direction",
    "confidence",
    "horizon",
    "risk_exposure_hint",
    "expires_at",
    "payload",
)

_VALID_DIRECTIONS = ("long", "short", "neutral")

# F2 置信度阈值：低于该值降级为 neutral（§2.2 默认 on）
_CONFIDENCE_FLOOR = 0.30

# P1-07：可观测性指标默认落盘路径
_METRICS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "runtime", "metrics.json")

# P1-07：TTL 观测窗口（临近过期阈值，秒）
_EXPIRING_SOON_SECONDS = 3600


def _parse_ts(value: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _is_live(signal: Dict[str, Any], now: datetime) -> bool:
    """信号未过期（expires_at 非法视为已过期，剪枝口径与 F1 一致）。"""
    exp = _parse_ts(signal.get("expires_at", ""))
    return exp is not None and now <= exp


class SignalBus:
    """信号汇聚总线（只读汇聚，链式过滤）。

    P1-01 持久化模式（SIGNAL_BUS_PERSIST=1，默认 0 保持旧整文件覆盖行为）：
    - 实例化时加载既有 bus_state.json（重启不丢，多 adapter 串行共存）
    - 加载与落盘时按 expires_at 剪除过期信号（TTL 剪枝）
    - publish 按 signal_id 合并：同 ID 替换，否则追加
    """

    def __init__(self, state_path: Optional[str] = None):
        self.state_path = state_path or _BUS_STATE_PATH
        self.signals: List[Dict[str, Any]] = []
        self.rejected: List[Dict[str, Any]] = []
        self._persist = os.environ.get("SIGNAL_BUS_PERSIST") == "1"
        if self._persist:
            self._load_persistent_state()

    # ── P1-01 持久化：加载既有状态（fail-open，损坏/缺失按空总线启动）──
    def _load_persistent_state(self) -> None:
        try:
            if not os.path.exists(self.state_path):
                return
            with open(self.state_path, encoding="utf-8") as f:
                state = json.load(f)
            signals = state.get("signals")
            if not isinstance(signals, list):
                return
            now = datetime.now(timezone.utc)
            for sig in signals:
                if isinstance(sig, dict) and _is_live(sig, now):
                    self.signals.append(sig)
        except Exception:  # noqa: BLE001
            self.signals = []
            self.rejected = []

    # ── P1-01 按 signal_id 合并：同 ID 替换（保持原位置），否则追加 ──
    def _upsert(self, signal: Dict[str, Any]) -> None:
        sid = signal.get("signal_id")
        for i, existing in enumerate(self.signals):
            if existing.get("signal_id") == sid:
                self.signals[i] = signal
                return
        self.signals.append(signal)

    # ── P1-01 TTL 剪枝：剔除已过期信号 ──
    def _prune_expired(self) -> None:
        now = datetime.now(timezone.utc)
        self.signals = [s for s in self.signals if _is_live(s, now)]

    # ── Schema 校验 ──
    def validate_schema(self, signal: Dict[str, Any]) -> Optional[str]:
        if not isinstance(signal, dict):
            return "signal 非对象"
        for key in _REQUIRED_KEYS:
            if key not in signal:
                return "缺少必需字段: {}".format(key)
        if signal.get("direction") not in _VALID_DIRECTIONS:
            return "direction 非法: {}".format(signal.get("direction"))
        conf = signal.get("confidence")
        if not isinstance(conf, (int, float)) or not (0.0 <= float(conf) <= 1.0):
            return "confidence 超出 [0,1]"
        if _parse_ts(signal.get("ts")) is None:
            return "ts 非法 ISO8601"
        if _parse_ts(signal.get("expires_at")) is None:
            return "expires_at 非法 ISO8601"
        return None

    # ── F1 新鲜度校验：超过 expires_at 的信号丢弃 ──
    def _f1_freshness(self, signal: Dict[str, Any]) -> bool:
        exp = _parse_ts(signal.get("expires_at"))
        return exp is not None and datetime.now(timezone.utc) <= exp

    # ── F2 置信度过滤：低于阈值降级为 neutral ──
    def _f2_confidence(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        conf = signal.get("confidence")
        if isinstance(conf, (int, float)) and float(conf) < _CONFIDENCE_FLOOR:
            signal = dict(signal)
            signal["direction"] = "neutral"
            signal["filter_notes"] = signal.get("filter_notes", []) + [
                "F2: confidence<{} 降级 neutral".format(_CONFIDENCE_FLOOR)
            ]
        return signal

    # ── F3 冲突检测：标记同标的多源信号方向冲突 ──
    def _f3_conflict(
        self, signal: Dict[str, Any], all_signals: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        conflicts = []
        for other in all_signals:
            if other is signal:
                continue
            if (
                other.get("symbol") == signal.get("symbol")
                and other.get("source") != signal.get("source")
                and other.get("direction") in ("long", "short")
                and signal.get("direction") in ("long", "short")
                and other.get("direction") != signal.get("direction")
            ):
                conflicts.append(
                    {
                        "vs_source": other.get("source"),
                        "vs_direction": other.get("direction"),
                    }
                )
        if conflicts:
            signal = dict(signal)
            signal["conflict_flags"] = conflicts
        return signal

    # ── F5 归一化输出：统一量纲与格式 ──
    def _f5_normalize(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(signal)
        out["confidence"] = round(float(out.get("confidence", 0.0)), 4)
        out["risk_exposure_hint"] = round(float(out.get("risk_exposure_hint", 0.0)), 4)
        out["shadow"] = bool(out.get("shadow", False))
        return out

    # ── 发布入口：Schema 校验 + 过滤链 ──
    def publish(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        """单信号入总线。返回处理结果 {status, signal?, reason?}。"""
        try:
            err = self.validate_schema(signal)
            if err:
                self.rejected.append({"signal_id": signal.get("signal_id"), "reason": err})
                return {"status": "rejected", "reason": err}
            if not self._f1_freshness(signal):
                self.rejected.append({"signal_id": signal.get("signal_id"), "reason": "F1 过期"})
                return {"status": "rejected", "reason": "F1 新鲜度校验未通过（过期）"}
            processed = self._f2_confidence(signal)
            processed = self._f3_conflict(processed, self.signals + [processed])
            processed = self._f5_normalize(processed)
            if self._persist:
                self._upsert(processed)
            else:
                self.signals.append(processed)
            return {"status": "accepted", "signal": processed}
        except Exception as exc:  # noqa: BLE001  fail-open：单信号异常不阻断总线
            self.rejected.append(
                {"signal_id": signal.get("signal_id"), "reason": "error: {}".format(exc)}
            )
            return {"status": "error", "reason": str(exc)}

    # ── 总线状态落盘（原子写入）──
    def snapshot(self) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        return {
            "bus_id": "bus_{}".format(uuid.uuid4().hex[:8]),
            "generated_at": now.isoformat(),
            "signal_count": len(self.signals),
            "rejected_count": len(self.rejected),
            "sources": sorted({s.get("source") for s in self.signals}),
            "signals": self.signals,
            "rejected": self.rejected,
            "note": "P1 只读汇聚：不下发参数；shadow 信号不参与矛盾裁决权重",
        }

    # ── P1-07 可观测性：源计数/丢弃/TTL/空 bus 告警（SIGNAL_BUS_METRICS=1）──
    def collect_metrics(self) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        source_counts: Dict[str, int] = {}
        expiring_soon = 0
        for sig in self.signals:
            src = sig.get("source")
            source_counts[src] = source_counts.get(src, 0) + 1
            exp = _parse_ts(sig.get("expires_at", ""))
            if exp is not None and 0 <= (exp - now).total_seconds() <= _EXPIRING_SOON_SECONDS:
                expiring_soon += 1
        return {
            "generated_at": now.isoformat(),
            "signal_count": len(self.signals),
            "rejected_count": len(self.rejected),
            "source_counts": source_counts,
            "rejected_reasons": [r.get("reason") for r in self.rejected],
            "expiring_within_1h": expiring_soon,
            "alert": {"empty_bus": len(self.signals) == 0},
        }

    def _write_metrics(self, metrics_path: Optional[str] = None) -> None:
        path = metrics_path or _METRICS_PATH
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.collect_metrics(), f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except Exception:  # noqa: BLE001  fail-open：指标失败不影响总线
            pass

    def flush(self, metrics_path: Optional[str] = None) -> Dict[str, Any]:
        """总线状态原子落盘（persist 模式先剪除已过期信号）。

        P1-07：SIGNAL_BUS_METRICS=1 时同步落盘指标文件（默认关闭=回滚路径）。
        """
        if self._persist:
            self._prune_expired()
        state = self.snapshot()
        try:
            os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
            tmp = self.state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.state_path)
        except Exception:  # noqa: BLE001
            pass
        if os.environ.get("SIGNAL_BUS_METRICS") == "1":
            self._write_metrics(metrics_path)
        return state


if __name__ == "__main__":
    print(json.dumps(SignalBus().snapshot(), ensure_ascii=False, indent=2))
