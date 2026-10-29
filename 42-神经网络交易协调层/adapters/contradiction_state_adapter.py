#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""23 层 Publisher 适配器（42 层 registry.yaml 声明的接入点）。

职责（42 层 SPEC §2.3/§2.4 一期接入清单）：
- 只读 23 层产出物 contradiction_samples.json，不侵入 23 系统
- 将最新矛盾仲裁样本转换为统一 SignalSchema 信号发布到总线，source=23-contradiction
- direction/confidence 直接取样本值（矛盾仲裁结论，Bayesian 验证回流更新）
- risk_exposure_hint = market_weight（矛盾信号市场权重）
- horizon=hours（矛盾仲裁为短周期信号）；expires_at 24h
- 新鲜度预检：最新样本超过 24h 不发布（与总线 F1 过滤一致）
- fail-open：样本文件缺失/损坏/为空 → 返回 unavailable，不阻断总线

用法：python3 contradiction_state_adapter.py（独立运行时打印发布结果）
"""
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

# 23 层产出物路径
_23_SAMPLES_PATH = os.path.join(
    "/home/luke/dreambuddy/23-四层闭环自进化交易架构",
    "dreambuddy_evolution", "data", "contradiction_samples.json",
)

# 42 层 SignalBus 模块路径
_42_ROOT = "/home/luke/dreambuddy/42-神经网络交易协调层"

# 样本新鲜度上限（超过视为过期，不发布）
_MAX_AGE_SECONDS = 24 * 3600

_VALID_DIRECTIONS = ("long", "short", "neutral")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def load_latest_sample(path: str = _23_SAMPLES_PATH):
    """只读加载 23 层最新矛盾仲裁样本（fail-open）。返回 (sample, note)。"""
    try:
        if not os.path.exists(path):
            return None, "contradiction_samples.json 不存在（fail-open）"
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        samples = data.get("samples") if isinstance(data, dict) else None
        if not isinstance(samples, list) or not samples:
            return None, "samples 为空（fail-open）"
        valid = [
            s for s in samples
            if isinstance(s, dict) and s.get("direction") in _VALID_DIRECTIONS
        ]
        if not valid:
            return None, "无有效 direction 样本（fail-open）"
        latest = max(valid, key=lambda s: float(s.get("ts") or 0))
        return latest, None
    except Exception as exc:  # noqa: BLE001
        return None, "加载失败（fail-open）: {}".format(exc)


def build_signal(sample: dict) -> dict:
    """将最新矛盾仲裁样本转换为统一 SignalSchema 信号。"""
    now = _now()
    confidence = max(0.0, min(1.0, float(sample.get("confidence") or 0.0)))
    market_weight = max(0.0, min(1.0, float(sample.get("market_weight") or 0.0)))
    return {
        "signal_id": "sig_{}_{}".format(
            now.strftime("%Y%m%d"), uuid.uuid4().hex[:8]),
        "source": "23-contradiction",
        "ts": now.isoformat(),
        "symbol": "MACRO",  # 矛盾仲裁为组合级信号，非单标的
        "direction": sample.get("direction"),
        "confidence": confidence,
        "horizon": "hours",
        "risk_exposure_hint": market_weight,
        "expires_at": (now + timedelta(hours=24)).isoformat(),
        "payload": {
            "power": sample.get("power"),
            "consistency": sample.get("consistency"),
            "time": sample.get("time"),
            "actual_return": sample.get("actual_return"),
            "sample_ts": sample.get("ts"),
        },
    }


def main() -> int:
    if _42_ROOT not in sys.path:
        sys.path.insert(0, _42_ROOT)
    from signal_bus import SignalBus  # noqa: E402

    sample, note = load_latest_sample()
    if sample is None:
        print(json.dumps({"status": "unavailable", "reason": note}, ensure_ascii=False))
        return 1

    # 新鲜度预检：最新样本超过 24h 不发布
    sample_ts = float(sample.get("ts") or 0)
    age = (_now() - datetime.fromtimestamp(sample_ts, tz=timezone.utc)).total_seconds()
    if age > _MAX_AGE_SECONDS:
        print(json.dumps({
            "status": "stale",
            "reason": "最新矛盾仲裁样本超过 24h，不发布",
            "age_seconds": round(age, 1),
        }, ensure_ascii=False))
        return 1

    signal = build_signal(sample)
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
        "risk_exposure_hint": signal.get("risk_exposure_hint"),
        "sample_age_seconds": round(age, 1),
        "bus_signal_count": bus.snapshot()["signal_count"],
        "bus_sources": bus.snapshot()["sources"],
    }, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "accepted" else 1


if __name__ == "__main__":
    sys.exit(main())
