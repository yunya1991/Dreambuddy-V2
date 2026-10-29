#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""40 层 Publisher 适配器（42 层 registry.yaml 声明的接入点）。

职责（42 层 SPEC §2.3/§2.4 一期接入清单）：
- 只读 40 层产出物 cycle_state.json，不侵入 40 系统
- 将周期状态转换为统一 SignalSchema 信号发布到总线，source=40-cycle
- direction 映射：technical_anchor MA200 多数资产 above → long；多数 below → short；无数据 → neutral
- confidence 映射：real_cycle.confidence high=0.8 / medium=0.6 / low=0.4
- horizon=days（周期级信号）；expires_at 24h（周期状态日级更新）
- fail-open：cycle_state.json 缺失/损坏 → 返回 unavailable，不阻断总线

用法：python3 cycle_state_adapter.py（独立运行时打印发布结果）
"""
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

# 40 层产出物路径
_40_STATE_PATH = os.path.join(
    "/home/luke/dreambuddy/40-周期神经网络系统", "cycle_state.json",
)

# 42 层 SignalBus 模块路径
_42_ROOT = "/home/luke/dreambuddy/42-神经网络交易协调层"

# confidence 映射（real_cycle.confidence → [0,1]）
_CONF_MAP = {"high": 0.8, "medium": 0.6, "low": 0.4}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def load_cycle_state(path: str = _40_STATE_PATH) -> dict:
    """只读加载 40 层周期状态（fail-open 返回 {available: False}）。"""
    try:
        if not os.path.exists(path):
            return {"available": False, "note": "cycle_state.json 不存在（fail-open）"}
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
        if not isinstance(state, dict) or "real_cycle" not in state:
            return {"available": False, "note": "cycle_state 格式非法（fail-open）"}
        return state
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "note": "加载失败（fail-open）: {}".format(exc)}


def build_signal(state: dict) -> dict:
    """将周期状态转换为统一 SignalSchema 信号。"""
    now = _now()
    real_cycle = state.get("real_cycle") or {}
    anchor = state.get("technical_anchor") or {}
    assets = anchor.get("assets") or {}

    # direction：MA200 多数资产 above → long；多数 below → short；无数据 → neutral
    above_n = sum(1 for a in assets.values() if isinstance(a, dict) and a.get("above"))
    below_n = sum(1 for a in assets.values() if isinstance(a, dict) and a.get("above") is False)
    if assets and above_n > below_n:
        direction = "long"
    elif assets and below_n > above_n:
        direction = "short"
    else:
        direction = "neutral"

    # confidence：real_cycle.confidence 映射；无周期置信度时降级 0.4
    conf = _CONF_MAP.get(str(real_cycle.get("confidence", "")).lower(), 0.4)

    return {
        "signal_id": "sig_{}_{}".format(
            now.strftime("%Y%m%d"), uuid.uuid4().hex[:8]),
        "source": "40-cycle",
        "ts": now.isoformat(),
        "symbol": "MACRO",  # 周期级宏观信号，非单标的
        "direction": direction,
        "confidence": conf,
        "horizon": "days",
        "risk_exposure_hint": 0.5,  # 周期信号保守默认
        "expires_at": (now + timedelta(hours=24)).isoformat(),
        "payload": {
            "real_cycle": real_cycle,
            "technical_anchor_summary": {
                "assets_total": len(assets),
                "above_ma200": above_n,
                "below_ma200": below_n,
            },
            "state_generated_at": state.get("generated_at"),
        },
    }


def main() -> int:
    if _42_ROOT not in sys.path:
        sys.path.insert(0, _42_ROOT)
    from signal_bus import SignalBus  # noqa: E402

    state = load_cycle_state()
    if not state.get("real_cycle"):
        print(json.dumps({"status": "unavailable", "reason": state.get("note")}, ensure_ascii=False))
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
        "direction": signal.get("direction"),
        "confidence": signal.get("confidence"),
        "bus_signal_count": bus.snapshot()["signal_count"],
        "bus_sources": bus.snapshot()["sources"],
    }, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "accepted" else 1


if __name__ == "__main__":
    sys.exit(main())
