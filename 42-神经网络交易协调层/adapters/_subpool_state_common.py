#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P1-04/DEC-08：11 子池状态文件只读适配器公共逻辑。

11 层 polling_trader 将被执行权限拦截的子池候选信号落盘为
scripts/memory_l4/runtime/subpool_state/<source_tag>_state.json：
  {source_tag, updated_at, signals: {coin: {direction, confidence, price, ts, reason}}}

本模块提供加载/TTL/信号构建/发布主流程，供 washout/event_arbitrage 两个
薄适配器复用。无跨进程内存耦合（纯文件只读）；fail-open 不阻断总线。

开关：ENABLE_11_STATE_ADAPTER=1 才发布（默认关闭=回滚路径）。
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

_42_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_DIR_MAP = {"UP": "long", "DOWN": "short"}


def _now():
    return datetime.now(timezone.utc)


def load_state(path):
    """只读加载子池状态文件（fail-open）。返回 (state, note)。"""
    try:
        if not os.path.exists(path):
            return None, "状态文件不存在（fail-open）: {}".format(path)
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
        if not isinstance(state, dict) or not isinstance(state.get("signals"), dict):
            return None, "状态文件格式非法或无 signals（fail-open）"
        return state, None
    except Exception as exc:  # noqa: BLE001
        return None, "加载失败（fail-open）: {}".format(exc)


def is_fresh(state, max_age_hours):
    """TTL 新鲜度预检：updated_at 超龄返回 (False, age_hours)。"""
    try:
        updated = datetime.fromisoformat(str(state.get("updated_at") or ""))
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
    except Exception:
        return False, -1
    age_hours = (_now() - updated).total_seconds() / 3600.0
    if age_hours > max_age_hours:
        return False, age_hours
    return True, age_hours


def build_signals(state, source, horizon, ttl_hours):
    """子池状态 → 统一 SignalSchema 信号列表（每币一条）。"""
    now = _now()
    signals = []
    for coin, rec in sorted((state.get("signals") or {}).items()):
        if not isinstance(rec, dict):
            continue
        raw_dir = str(rec.get("direction") or "").upper()
        direction = _DIR_MAP.get(raw_dir, "neutral")
        try:
            confidence = max(0.0, min(1.0, float(rec.get("confidence", 0.0))))
        except (TypeError, ValueError):
            confidence = 0.0
        signals.append(
            {
                "signal_id": "sig_{}_{}_{}".format(source, coin, now.strftime("%Y%m%d")),
                "source": source,
                "ts": now.isoformat(),
                "symbol": coin,
                "direction": direction,
                "confidence": round(confidence, 4),
                "horizon": horizon,
                "risk_exposure_hint": round(confidence, 4),
                "expires_at": (now + timedelta(hours=ttl_hours)).isoformat(),
                "payload": {
                    "price": rec.get("price"),
                    "reason": rec.get("reason"),
                    "signal_ts": rec.get("ts"),
                    "state_updated_at": state.get("updated_at"),
                },
            }
        )
    return signals


def run(source, state_path, horizon, ttl_hours, max_age_hours, bus_state_path=None):
    """适配器主流程。返回退出码（0=成功/disabled，1=不可用/过期/失败）。"""
    if os.environ.get("ENABLE_11_STATE_ADAPTER") != "1":
        print(
            json.dumps(
                {
                    "status": "disabled",
                    "reason": "ENABLE_11_STATE_ADAPTER 未设置为 1（回滚路径，不发布）",
                    "source": source,
                },
                ensure_ascii=False,
            )
        )
        return 0

    if _42_ROOT not in sys.path:
        sys.path.insert(0, _42_ROOT)
    from signal_bus import SignalBus  # noqa: E402

    state, note = load_state(state_path)
    if state is None:
        print(json.dumps({"status": "unavailable", "reason": note}, ensure_ascii=False))
        return 1

    fresh, age_hours = is_fresh(state, max_age_hours)
    if not fresh:
        print(
            json.dumps(
                {
                    "status": "stale",
                    "reason": "状态超过 {}h TTL，不发布".format(max_age_hours),
                    "age_hours": round(age_hours, 1) if age_hours >= 0 else None,
                },
                ensure_ascii=False,
            )
        )
        return 1

    signals = build_signals(state, source=source, horizon=horizon, ttl_hours=ttl_hours)
    if not signals:
        print(
            json.dumps(
                {"status": "unavailable", "reason": "无可发布信号（fail-open）"},
                ensure_ascii=False,
            )
        )
        return 1

    bus = SignalBus(state_path=bus_state_path) if bus_state_path else SignalBus()
    results = []
    for signal in signals:
        r = bus.publish(signal)
        results.append(
            {
                "symbol": signal["symbol"],
                "direction": signal["direction"],
                "confidence": signal["confidence"],
                "publish_result": r.get("status"),
                "reason": r.get("reason"),
            }
        )
    snap = bus.flush()
    print(
        json.dumps(
            {
                "publish_result": (
                    "accepted"
                    if all(r["publish_result"] == "accepted" for r in results)
                    else "partial"
                ),
                "published": len(results),
                "results": results,
                "bus_signal_count": snap["signal_count"],
                "bus_sources": snap["sources"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if all(r["publish_result"] == "accepted" for r in results) else 1
