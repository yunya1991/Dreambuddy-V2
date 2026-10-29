#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BDSM 子交易系统 Publisher 适配器（42 层 registry.yaml 声明的接入点）。

职责（42 层 SPEC §2.3 即插即拔接入）：
- 只读 BDSM 每日快照（11 层 .workbuddy/bdsm/bdsm_snapshot_YYYYMMDD.json），不侵入 BDSM 系统
- 按币种各发布一条统一 SignalSchema 信号，source=bdsm
- direction 映射：direction_constraint LONG_ONLY/LONG_PREFER→long；SHORT_ONLY/SHORT_PREFER→short；NEUTRAL/FREEZE→neutral
- confidence = 币种 confidence（数据不足 0.0 的信号由总线 F2 置信度过滤自然降级为 neutral）
- risk_exposure_hint = cap_multiplier（BDSM 仓位乘数，真实数据）
- horizon=days（日级快照）；expires_at 24h
- 新鲜度预检：快照日期超过 48h 不发布
- fail-open：快照缺失/损坏/无币种数据 → 返回 unavailable，不阻断总线

用法：python3 bdsm_state_adapter.py（独立运行时打印发布结果）
"""
import glob
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

# BDSM 快照目录（每日一份）
_BDSM_DIR = os.path.join(
    "/home/luke/dreambuddy/11-易经推理系统", ".workbuddy", "bdsm",
)

# 42 层 SignalBus 模块路径
_42_ROOT = "/home/luke/dreambuddy/42-神经网络交易协调层"

# 快照新鲜度上限（日级快照，容忍 48h）
_MAX_AGE_HOURS = 48

# direction_constraint → SignalSchema direction
_DIR_MAP = {
    "LONG_ONLY": "long",
    "LONG_PREFER": "long",
    "SHORT_ONLY": "short",
    "SHORT_PREFER": "short",
    "NEUTRAL": "neutral",
    "FREEZE": "neutral",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def load_latest_snapshot():
    """定位并只读加载最新 BDSM 快照（fail-open）。返回 (snapshot, path, note)。"""
    try:
        if not os.path.isdir(_BDSM_DIR):
            return None, None, "bdsm 快照目录不存在（fail-open）"
        paths = sorted(glob.glob(os.path.join(_BDSM_DIR, "bdsm_snapshot_*.json")))
        if not paths:
            return None, None, "无 bdsm_snapshot_*.json 快照（fail-open）"
        path = paths[-1]
        with open(path, encoding="utf-8") as f:
            snapshot = json.load(f)
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("coins"), dict):
            return None, None, "快照格式非法或无 coins（fail-open）"
        return snapshot, path, None
    except Exception as exc:  # noqa: BLE001
        return None, None, "加载失败（fail-open）: {}".format(exc)


def _check_freshness(snapshot):
    """新鲜度预检：snapshot_date 超过 48h 返回 (False, age_hours)，否则 (True, 0)。"""
    snap_date = str(snapshot.get("snapshot_date") or "")
    try:
        updated = datetime.strptime(snap_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return False, -1  # 日期缺失/非法视为不新鲜
    age_hours = (_now() - updated).total_seconds() / 3600.0
    if age_hours > _MAX_AGE_HOURS:
        return False, age_hours
    return True, age_hours


def build_signals(snapshot):
    """将 BDSM 快照按币种转换为统一 SignalSchema 信号列表。"""
    now = _now()
    coins = snapshot.get("coins") or {}

    signals = []
    for symbol, coin in coins.items():
        if not isinstance(coin, dict) or not coin.get("available"):
            continue  # 不可用币种跳过（fail-open）
        direction = _DIR_MAP.get(str(coin.get("direction_constraint")))
        if direction is None:
            continue  # 未知约束值跳过
        try:
            confidence = max(0.0, min(1.0, float(coin.get("confidence") or 0.0)))
        except (TypeError, ValueError):
            confidence = 0.0
        try:
            cap_mult = max(0.0, min(1.0, float(coin.get("cap_multiplier") or 0.0)))
        except (TypeError, ValueError):
            cap_mult = 0.0
        signals.append({
            "signal_id": "sig_{}_{}".format(
                now.strftime("%Y%m%d"), uuid.uuid4().hex[:8]),
            "source": "bdsm",
            "ts": now.isoformat(),
            "symbol": str(symbol),
            "direction": direction,
            "confidence": round(confidence, 4),
            "horizon": "days",
            "risk_exposure_hint": cap_mult,
            "expires_at": (now + timedelta(hours=24)).isoformat(),
            "payload": {
                "direction_constraint": coin.get("direction_constraint"),
                "score": coin.get("score"),
                "rank": coin.get("rank"),
                "phase": coin.get("phase"),
                "phase_confidence": coin.get("phase_confidence"),
                "valuation_percentile": coin.get("valuation_percentile"),
                "exit_action": coin.get("exit_action"),
                "data_quality": coin.get("data_quality"),
                "snapshot_date": snapshot.get("snapshot_date"),
            },
        })
    return signals


def main() -> int:
    if _42_ROOT not in sys.path:
        sys.path.insert(0, _42_ROOT)
    from signal_bus import SignalBus  # noqa: E402

    snapshot, path, note = load_latest_snapshot()
    if snapshot is None:
        print(json.dumps({"status": "unavailable", "reason": note}, ensure_ascii=False))
        return 1

    fresh, age_hours = _check_freshness(snapshot)
    if not fresh:
        print(json.dumps({
            "status": "stale",
            "reason": "BDSM 快照超过 48h 或日期非法，不发布",
            "age_hours": round(age_hours, 1) if age_hours >= 0 else None,
        }, ensure_ascii=False))
        return 1

    signals = build_signals(snapshot)
    if not signals:
        print(json.dumps({"status": "unavailable", "reason": "无可发布币种信号（fail-open）"}, ensure_ascii=False))
        return 1

    bus = SignalBus()
    results = []
    for signal in signals:
        result = bus.publish(signal)
        results.append({
            "symbol": signal["symbol"],
            "direction": signal["direction"],
            "confidence": signal["confidence"],
            "risk_exposure_hint": signal["risk_exposure_hint"],
            "publish_result": result.get("status"),
            "reason": result.get("reason"),
        })
    bus.flush()
    print(json.dumps({
        "snapshot": os.path.basename(path) if path else None,
        "published": len(results),
        "results": results,
        "bus_signal_count": bus.snapshot()["signal_count"],
        "bus_sources": bus.snapshot()["sources"],
    }, ensure_ascii=False, indent=2))
    return 0 if all(r["publish_result"] == "accepted" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
