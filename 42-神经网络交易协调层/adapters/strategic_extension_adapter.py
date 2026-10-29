#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""43 层 Publisher 适配器（42 层 registry.yaml 声明的接入点）。

职责（42 层 SPEC §2.3/§21.1）：
- 只读 43 层信号产出物 runtime/strategic_extension_signal.json，不侵入 43 系统
- 将信号发布到 SignalBus，source=strategic_extension（主网络侧路径）
- shadow 信号原样透传（shadow 标记由总线消费方处理，不参与矛盾裁决权重）
- fail-open：43 信号文件缺失/损坏 → 返回 unavailable，不阻断总线

用法：python3 strategic_extension_adapter.py（独立运行时打印发布结果）
"""

import json
import os
import sys

# 43 层信号产出物路径
_43_SIGNAL_PATH = os.path.join(
    "/home/luke/dreambuddy/43-战略承接推演层",
    "runtime", "strategic_extension_signal.json",
)

# 42 层 SignalBus 模块路径
_42_ROOT = "/home/luke/dreambuddy/42-神经网络交易协调层"


def load_43_signal(path: str = _43_SIGNAL_PATH) -> dict:
    """只读加载 43 层信号（fail-open 返回 {available: False}）。"""
    try:
        if not os.path.exists(path):
            return {"available": False, "note": "43 信号文件不存在（fail-open）"}
        with open(path, encoding="utf-8") as f:
            sig = json.load(f)
        if not isinstance(sig, dict) or sig.get("source") != "strategic_extension":
            return {"available": False, "note": "43 信号格式非法（fail-open）"}
        return sig
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "note": "加载失败（fail-open）: {}".format(exc)}


def publish_to_bus(bus, signal: dict) -> dict:
    """将 43 信号发布到总线实例。"""
    if not signal.get("source"):
        return {"status": "unavailable", "reason": signal.get("note", "信号不可用")}
    return bus.publish(signal)


def main() -> int:
    # 导入 42 层 SignalBus
    if _42_ROOT not in sys.path:
        sys.path.insert(0, _42_ROOT)
    from signal_bus import SignalBus  # noqa: E402

    signal = load_43_signal()
    if not signal.get("source"):
        print(json.dumps({"status": "unavailable", "reason": signal.get("note")}, ensure_ascii=False))
        return 1

    bus = SignalBus()
    result = publish_to_bus(bus, signal)
    state = bus.flush()
    print(json.dumps({
        "publish_result": result.get("status"),
        "reason": result.get("reason"),
        "bus_signal_count": state["signal_count"],
        "bus_sources": state["sources"],
        "signal_id": signal.get("signal_id"),
        "source": signal.get("source"),
        "shadow": signal.get("shadow"),
    }, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "accepted" else 1


if __name__ == "__main__":
    sys.exit(main())
