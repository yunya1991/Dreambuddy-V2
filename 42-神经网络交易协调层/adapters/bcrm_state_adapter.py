#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""11 层 Publisher 适配器（42 层 registry.yaml 声明的接入点）。

职责（42 层 SPEC §2.3/§2.4 一期接入清单）：
- 只读 11 层 BCRM2.0 战略层结构化产出物 five_domain_state.json
  （polling_trader 日级缓存，runtime/five_domain_state.json），不侵入 11 系统
- 按资产类别（crypto_usdt/precious_metal/us_stock）各发布一条统一 SignalSchema 信号，source=11-bcrm
- direction 映射：LONG_PREFER/LONG_ONLY→long；SHORT_PREFER/SHORT_ONLY→short；NEUTRAL/FREEZE→neutral
- confidence 映射：clip(0.3 + |direction_bias|/100, 0.3, 1.0)
  （direction_bias 为有符号偏置强度，线性映射并设 0.3 下限保证通过总线 F2 置信度过滤）
- risk_exposure_hint = aggregate_position_cap_pct[资产类别]（该类聚合仓位上限，真实数据）
- horizon=days（战略层日级状态）；expires_at 24h
- 新鲜度预检：_meta.updated_date 超过 48h 不发布
- fail-open：状态文件缺失/损坏/无方向数据 → 返回 unavailable，不阻断总线

用法：python3 bcrm_state_adapter.py（独立运行时打印发布结果）
"""
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

# 11 层 BCRM2.0 战略层产出物路径（polling_trader 日级缓存）
_11_STATE_PATH = os.path.join(
    "/home/luke/dreambuddy/11-易经推理系统", "scripts", "memory_l4",
    "runtime", "five_domain_state.json",
)

# 42 层 SignalBus 模块路径
_42_ROOT = "/home/luke/dreambuddy/42-神经网络交易协调层"

# 状态新鲜度上限（日级缓存，容忍 48h）
_MAX_AGE_HOURS = 48

# direction_state → SignalSchema direction
_DIR_MAP = {
    "LONG_PREFER": "long",
    "LONG_ONLY": "long",
    "SHORT_PREFER": "short",
    "SHORT_ONLY": "short",
    "NEUTRAL": "neutral",
    "FREEZE": "neutral",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def load_state(path: str = _11_STATE_PATH):
    """只读加载 11 层战略层状态（fail-open）。返回 (state, note)。"""
    try:
        if not os.path.exists(path):
            return None, "five_domain_state.json 不存在（fail-open）"
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
        if not isinstance(state, dict) or not isinstance(state.get("direction_state"), dict):
            return None, "five_domain_state 格式非法或无 direction_state（fail-open）"
        return state, None
    except Exception as exc:  # noqa: BLE001
        return None, "加载失败（fail-open）: {}".format(exc)


def _check_freshness(state: dict):
    """新鲜度预检：_meta.updated_date 超过 48h 返回 (False, age_hours)，否则 (True, 0)。"""
    meta = state.get("_meta") or {}
    updated_date = str(meta.get("updated_date") or "")
    try:
        updated = datetime.strptime(updated_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return False, -1  # 日期缺失/非法视为不新鲜
    age_hours = (_now() - updated).total_seconds() / 3600.0
    if age_hours > _MAX_AGE_HOURS:
        return False, age_hours
    return True, age_hours


def build_signals(state: dict):
    """将战略层状态按资产类别转换为统一 SignalSchema 信号列表。"""
    now = _now()
    dir_state = state.get("direction_state") or {}
    dir_bias = state.get("direction_bias") or {}
    cap_pct = state.get("aggregate_position_cap_pct") or {}
    five_scores = state.get("five_scores") or {}

    signals = []
    for asset_class, raw_dir in dir_state.items():
        direction = _DIR_MAP.get(str(raw_dir))
        if direction is None:
            continue  # 未知状态值跳过（fail-open）
        bias = dir_bias.get(asset_class)
        try:
            bias_val = abs(float(bias)) if bias is not None else 0.0
        except (TypeError, ValueError):
            bias_val = 0.0
        confidence = max(0.3, min(1.0, 0.3 + bias_val / 100.0))
        cap = cap_pct.get(asset_class)
        try:
            exposure = max(0.0, min(1.0, float(cap))) if cap is not None else 0.5
        except (TypeError, ValueError):
            exposure = 0.5
        signals.append({
            "signal_id": "sig_{}_{}".format(
                now.strftime("%Y%m%d"), uuid.uuid4().hex[:8]),
            "source": "11-bcrm",
            "ts": now.isoformat(),
            "symbol": str(asset_class),
            "direction": direction,
            "confidence": round(confidence, 4),
            "horizon": "days",
            "risk_exposure_hint": exposure,
            "expires_at": (now + timedelta(hours=24)).isoformat(),
            "payload": {
                "direction_state": raw_dir,
                "direction_bias": bias,
                "five_scores": five_scores.get(asset_class),
                "btc_regime": (state.get("btc_regime") or {}).get(asset_class),
                "state_updated_date": (state.get("_meta") or {}).get("updated_date"),
            },
        })
    return signals


def main() -> int:
    if _42_ROOT not in sys.path:
        sys.path.insert(0, _42_ROOT)
    from signal_bus import SignalBus  # noqa: E402

    state, note = load_state()
    if state is None:
        print(json.dumps({"status": "unavailable", "reason": note}, ensure_ascii=False))
        return 1

    fresh, age_hours = _check_freshness(state)
    if not fresh:
        print(json.dumps({
            "status": "stale",
            "reason": "战略层状态超过 48h 或日期非法，不发布",
            "age_hours": round(age_hours, 1) if age_hours >= 0 else None,
        }, ensure_ascii=False))
        return 1

    signals = build_signals(state)
    if not signals:
        print(json.dumps({"status": "unavailable", "reason": "无可发布资产类别信号（fail-open）"}, ensure_ascii=False))
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
        "published": len(results),
        "results": results,
        "bus_signal_count": bus.snapshot()["signal_count"],
        "bus_sources": bus.snapshot()["sources"],
    }, ensure_ascii=False, indent=2))
    return 0 if all(r["publish_result"] == "accepted" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
