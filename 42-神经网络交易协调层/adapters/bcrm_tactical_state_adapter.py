#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""11 层 Publisher 适配器（42 层 registry.yaml 声明的接入点）。

R0-07：每币 BCRM2 技术层信号（source=11-bcrm-tactical）。

职责（50 层 SPEC §D3 数据源 / 42 层接入清单）：
- 只读 11 层每币 BCRM2 快照 polling_trader 产出物
  （scripts/memory_l4/runtime/bcrm2_tactical_state.json），不侵入 11 系统
- 按币各发布一条统一 SignalSchema 信号，source=11-bcrm-tactical
- direction 映射：UP→long；DOWN→short；其余→flat
- confidence：直接取 BCRM2 next_state.confidence（clip 到 [0,1]）
- horizon=hours（技术层小时级）；expires_at 2h（与快照一致）
- 新鲜度预检：单币 updated_at 超过 2h 不发布该币
- fail-open：快照文件缺失/损坏/无币数据 → 返回 unavailable，不阻断总线；
  无源时 50 层 D3=neutral（降级可观测），不得用资产类 11-bcrm 冒充

用法：python3 bcrm_tactical_state_adapter.py（独立运行时打印发布结果）
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

_DREAMBUDDY_ROOT = os.environ.get("DREAMBUDDY_ROOT") or os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

# 11 层每币 BCRM2 快照路径（polling_trader _persist_bcrm2_tactical_state 产出）
_11_STATE_PATH = os.path.join(
    os.path.join(_DREAMBUDDY_ROOT, "11-易经推理系统"),
    "scripts",
    "memory_l4",
    "runtime",
    "bcrm2_tactical_state.json",
)

_42_ROOT = os.path.join(_DREAMBUDDY_ROOT, "42-神经网络交易协调层")

# 单币新鲜度上限（与快照 expires_at 2h 一致）
_MAX_AGE_HOURS = 2

_DIR_MAP = {"UP": "long", "DOWN": "short"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def load_state(path: str = _11_STATE_PATH):
    """只读加载 11 层每币 BCRM2 快照（fail-open）。返回 (state, note)。"""
    try:
        if not os.path.exists(path):
            return None, "bcrm2_tactical_state.json 不存在（fail-open）"
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
        if not isinstance(state, dict) or not isinstance(state.get("coins"), dict):
            return None, "bcrm2_tactical_state 格式非法或无 coins（fail-open）"
        return state, None
    except Exception as exc:  # noqa: BLE001
        return None, "加载失败（fail-open）: {}".format(exc)


def _parse_iso(ts: str):
    try:
        return datetime.fromisoformat(str(ts))
    except (TypeError, ValueError):
        return None


def build_signals(state: dict):
    """将每币 BCRM2 快照转换为统一 SignalSchema 信号列表（逐币新鲜度过滤）。"""
    now = _now()
    signals = []
    for coin, snap in (state.get("coins") or {}).items():
        if not isinstance(snap, dict):
            continue
        updated = _parse_iso(snap.get("updated_at"))
        if updated is None:
            continue
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        age_hours = (now - updated).total_seconds() / 3600.0
        if age_hours > _MAX_AGE_HOURS:
            continue  # 单币过期跳过（fail-open，不发布）
        direction = _DIR_MAP.get(str(snap.get("raw_direction")))
        if direction is None:
            direction = "flat"
        try:
            confidence = max(0.0, min(1.0, float(snap.get("confidence", 0.0) or 0.0)))
        except (TypeError, ValueError):
            confidence = 0.0
        signals.append(
            {
                "signal_id": "sig_11-bcrm-tactical_{}_{}".format(
                    re.sub(r"[^A-Za-z0-9]+", "_", str(coin)), now.strftime("%Y%m%d%H")
                ),
                "source": "11-bcrm-tactical",
                "ts": now.isoformat(),
                "symbol": str(coin),
                "direction": direction,
                "confidence": round(confidence, 4),
                "horizon": "hours",
                "risk_exposure_hint": 0.5,
                "expires_at": (now + timedelta(hours=2)).isoformat(),
                "payload": {
                    "raw_direction": snap.get("raw_direction"),
                    "pattern": snap.get("pattern"),
                    "state_updated_at": snap.get("updated_at"),
                },
            }
        )
    return signals


def main() -> int:
    if _42_ROOT not in sys.path:
        sys.path.insert(0, _42_ROOT)
    from signal_bus import SignalBus  # noqa: E402

    state, note = load_state()
    if state is None:
        print(json.dumps({"status": "unavailable", "reason": note}, ensure_ascii=False))
        return 1

    signals = build_signals(state)
    if not signals:
        print(
            json.dumps(
                {"status": "unavailable", "reason": "无可发布每币信号（fail-open）"},
                ensure_ascii=False,
            )
        )
        return 1

    bus = SignalBus()
    results = []
    for signal in signals:
        result = bus.publish(signal)
        results.append(
            {
                "symbol": signal["symbol"],
                "direction": signal["direction"],
                "confidence": signal["confidence"],
                "publish_result": result.get("status"),
                "reason": result.get("reason"),
            }
        )
    bus.flush()
    print(
        json.dumps(
            {
                "published": len(results),
                "results": results,
                "bus_signal_count": bus.snapshot()["signal_count"],
                "bus_sources": bus.snapshot()["sources"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if all(r["publish_result"] == "accepted" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
