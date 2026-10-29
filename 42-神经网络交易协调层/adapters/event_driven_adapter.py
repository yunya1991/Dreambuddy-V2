#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""29 层 Publisher 适配器（42 层 registry.yaml 声明的接入点）。

职责（42 层 SPEC §2.3/§2.4 一期接入清单）：
- 只读 29 层事件驱动策略影子模式状态 event_driven_state.json，不侵入 29 系统
- 信号来源：23 层 kline_event_handler 调用 29 层 EventDrivenStrategy.evaluate()
  评估后写入（跨进程 JSON 通信，11 层 data_server 仅读取供前端展示）
- 将事件驱动信号转换为统一 SignalSchema 信号发布到总线，source=29-event
- direction = signal.signal（long/short/neutral）
- confidence = signal.strength（事件冲击强度，区分度优于数据完整度 confidence）
- risk_exposure_hint = signal.elasticity（弹性系数，取绝对值）
- horizon=hours（事件驱动短周期信号）；expires_at 4h（事件窗口时效）
- 新鲜度预检：状态超过 4h 不发布（与信号时效一致）
- fail-open：状态文件缺失/损坏/无信号 → 返回 unavailable，不阻断总线

用法：python3 event_driven_adapter.py（独立运行时打印发布结果）
"""
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

# 29 层影子模式状态文件路径（由 23 层 kline_event_handler 写入）
_29_STATE_PATH = os.path.join(
    "/home/luke/dreambuddy/11-易经推理系统", "data", "event_driven_state.json",
)

# 42 层 SignalBus 模块路径
_42_ROOT = "/home/luke/dreambuddy/42-神经网络交易协调层"

# 状态新鲜度上限（事件驱动信号时效 4h）
_MAX_AGE_SECONDS = 4 * 3600

_VALID_DIRECTIONS = ("long", "short", "neutral")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value):
    """解析 ISO 时间戳（容忍无时区写法，按 UTC 处理）。"""
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(str(value))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts
    except (TypeError, ValueError):
        return None


def load_state(path: str = _29_STATE_PATH):
    """只读加载 29 层事件驱动影子状态（fail-open）。返回 (state, note)。"""
    try:
        if not os.path.exists(path):
            return None, "event_driven_state.json 不存在（fail-open）"
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
        if not isinstance(state, dict):
            return None, "event_driven_state 格式非法（fail-open）"
        return state, None
    except Exception as exc:  # noqa: BLE001
        return None, "加载失败（fail-open）: {}".format(exc)


def build_signal(state: dict) -> dict:
    """将 29 层事件驱动影子状态转换为统一 SignalSchema 信号。"""
    now = _now()
    sig = state.get("signal") or {}
    main_chain = state.get("main_chain") or {}

    direction = str(sig.get("signal") or "neutral")
    if direction not in _VALID_DIRECTIONS:
        direction = "neutral"

    confidence = max(0.0, min(1.0, float(sig.get("strength") or 0.0)))
    elasticity = abs(max(-1.0, min(1.0, float(sig.get("elasticity") or 0.0))))

    return {
        "signal_id": "sig_{}_{}".format(
            now.strftime("%Y%m%d"), uuid.uuid4().hex[:8]),
        "source": "29-event",
        "ts": now.isoformat(),
        "symbol": str(state.get("symbol") or "MACRO"),
        "direction": direction,
        "confidence": confidence,
        "horizon": "hours",
        "risk_exposure_hint": elasticity,
        "expires_at": (now + timedelta(hours=4)).isoformat(),
        "payload": {
            "event_type": sig.get("event_type"),
            "event_phase": sig.get("event_phase"),
            "data_completeness": sig.get("confidence"),
            "scores": sig.get("scores"),
            "reason": sig.get("reason"),
            "forward_guidance": sig.get("forward_guidance"),
            "mode": sig.get("mode"),
            "main_chain_d_star": main_chain.get("d_star"),
            "main_chain_action": main_chain.get("action"),
            "main_chain_regime": main_chain.get("regime"),
            "state_mode": state.get("mode"),
            "state_updated_at": state.get("updated_at"),
        },
    }


def main() -> int:
    if _42_ROOT not in sys.path:
        sys.path.insert(0, _42_ROOT)
    from signal_bus import SignalBus  # noqa: E402

    state, note = load_state()
    if state is None:
        print(json.dumps({"status": "unavailable", "reason": note}, ensure_ascii=False))
        return 1

    sig = state.get("signal") or {}
    if sig.get("signal") not in _VALID_DIRECTIONS:
        print(json.dumps({"status": "unavailable", "reason": "无有效事件驱动信号（fail-open）"}, ensure_ascii=False))
        return 1

    # 新鲜度预检：状态超过 4h 不发布
    updated = _parse_ts(state.get("updated_at"))
    if updated is not None:
        age = (_now() - updated).total_seconds()
        if age > _MAX_AGE_SECONDS:
            print(json.dumps({
                "status": "stale",
                "reason": "事件驱动状态超过 4h，不发布",
                "age_seconds": round(age, 1),
            }, ensure_ascii=False))
            return 1

    signal = build_signal(state)
    bus = SignalBus()
    result = bus.publish(signal)
    bus.flush()
    print(json.dumps({
        "publish_result": result.get("status"),
        "reason": result.get("reason"),
        "signal_id": signal.get("signal_id"),
        "source": signal.get("source"),
        "symbol": signal.get("symbol"),
        "direction": signal.get("direction"),
        "confidence": signal.get("confidence"),
        "risk_exposure_hint": signal.get("risk_exposure_hint"),
        "bus_signal_count": bus.snapshot()["signal_count"],
        "bus_sources": bus.snapshot()["sources"],
    }, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "accepted" else 1


if __name__ == "__main__":
    sys.exit(main())
