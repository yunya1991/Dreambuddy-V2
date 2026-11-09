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
from datetime import datetime, timedelta, timezone

# R-42-04/P1-03：DREAMBUDDY_ROOT 环境变量统一模块根路径；未设置时按 __file__ 推导（仓库内模块同级布局）
_DREAMBUDDY_ROOT = os.environ.get("DREAMBUDDY_ROOT") or os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

# 40 层产出物路径
_40_STATE_PATH = os.path.join(
    os.path.join(_DREAMBUDDY_ROOT, "40-周期神经网络系统"),
    "cycle_state.json",
)
_40_ROTATION_PATH = os.path.join(
    os.path.join(_DREAMBUDDY_ROOT, "40-周期神经网络系统"),
    "asset_rotation.json",
)
_40_RESONANCE_PATH = os.path.join(
    os.path.join(_DREAMBUDDY_ROOT, "40-周期神经网络系统"),
    "resonance_matrix.json",
)

# 42 层 SignalBus 模块路径
_42_ROOT = os.path.join(_DREAMBUDDY_ROOT, "42-神经网络交易协调层")

# confidence 映射（real_cycle.confidence → [0,1]）
_CONF_MAP = {"high": 0.8, "medium": 0.6, "low": 0.4}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def load_cycle_state(path: str = None) -> dict:
    """只读加载 40 层周期状态（fail-open 返回 {available: False}）。"""
    path = path or _40_STATE_PATH
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
        # P1-01：确定性 signal_id（同 source+symbol 当日重跑幂等替换，配合总线按 signal_id 合并）
        "signal_id": "sig_40-cycle_MACRO_{}".format(now.strftime("%Y%m%d")),
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


def load_asset_rotation(path: str = None) -> dict:
    """只读加载 40 层 asset_rotation.json（fail-open 返回 {}）。"""
    path = path or _40_ROTATION_PATH
    try:
        if not os.path.exists(path):
            return {}
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return data
    except Exception:  # noqa: BLE001
        return {}


def build_divergence_signal(rotation: dict) -> dict:
    """将 asset_rotation.divergence 转为 40-divergence 信号。

    - symbol=MACRO（宏观级别背离，非单标的）
    - confidence = 0.8 × (1 - n_divergent / n_scored)
    - direction：背离率 < 0.5 → long（时钟被印证）；>= 0.5 → short（时钟被打破）；
      无评分数据 → neutral
    - horizon=days
    """
    now = _now()
    divergence = rotation.get("divergence") if isinstance(rotation, dict) else None
    if not isinstance(divergence, dict):
        divergence = {}

    n_divergent = int(divergence.get("n_divergent") or 0)
    n_scored = int(divergence.get("n_scored") or 0)
    quadrant = divergence.get("quadrant")

    if n_scored <= 0:
        direction = "neutral"
        confidence = 0.0
    else:
        divergence_ratio = n_divergent / n_scored
        confidence = round(0.8 * (1.0 - divergence_ratio), 6)
        if divergence_ratio < 0.5:
            direction = "long"
        else:
            direction = "short"

    return {
        "signal_id": "sig_40-divergence_MACRO_{}".format(now.strftime("%Y%m%d")),
        "source": "40-divergence",
        "ts": now.isoformat(),
        "symbol": "MACRO",
        "direction": direction,
        "confidence": confidence,
        "horizon": "days",
        "risk_exposure_hint": 0.4,
        "expires_at": (now + timedelta(hours=24)).isoformat(),
        "payload": {
            "quadrant": quadrant,
            "n_divergent": n_divergent,
            "n_scored": n_scored,
            "state_generated_at": divergence.get("generated_at"),
        },
    }


def load_resonance_matrix(path: str = None) -> dict:
    """只读加载 40 层 resonance_matrix.json（fail-open 返回 {}）。

    M1（SPEC-M2 §1.2）：resonance_matrix 由 40 p3_resonance_matrix.py 日更产出，
    含每标的 R(s)={corr0, lag_profile, beta, down_corr} + granger_p。
    """
    path = path or _40_RESONANCE_PATH
    try:
        if not os.path.exists(path):
            return {}
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return data
    except Exception:  # noqa: BLE001
        return {}


def build_resonance_signal(matrix: dict) -> dict:
    """将 resonance_matrix 转为 40-resonance 信号（M1，SPEC-M2）。

    - symbol=MACRO（宏观共振级别，非单标的）
    - direction：龙头 BTC corr0 方向（corr0>0 → long，<0 → short，≈0 → neutral）
    - confidence：0.8 × |corr0| × granger_significant_ratio（Granger 显著标的占比）
    - horizon=days
    - payload：携带龙头 R(s)、granger 统计、state_generated_at
    - fail-open：matrix 为空 → confidence=0, direction=neutral
    """
    now = _now()
    assets = matrix.get("assets") if isinstance(matrix, dict) else None
    if not isinstance(assets, dict):
        assets = {}

    # 龙头 BTC 的 R(s) 作为方向锚
    btc = assets.get("BTC/USDT") or assets.get("BTC") or {}
    corr0 = float(btc.get("corr0") or 0.0)

    if corr0 > 0.1:
        direction = "long"
    elif corr0 < -0.1:
        direction = "short"
    else:
        direction = "neutral"

    # Granger 显著标的占比（p < 0.05）
    n_total = len(assets)
    n_granger_sig = sum(
        1
        for a in assets.values()
        if isinstance(a, dict) and (a.get("granger_p") is not None) and float(a["granger_p"]) < 0.05
    )
    granger_ratio = (n_granger_sig / n_total) if n_total > 0 else 0.0

    confidence = round(0.8 * abs(corr0) * granger_ratio, 6) if n_total > 0 else 0.0

    # fail-open 审计：样本不足或 Granger 全不显著 → degraded
    degraded = []
    if n_total == 0:
        degraded.append("resonance_matrix_empty")
    if granger_ratio == 0.0 and n_total > 0:
        degraded.append("granger_not_significant")

    return {
        "signal_id": "sig_40-resonance_MACRO_{}".format(now.strftime("%Y%m%d")),
        "source": "40-resonance",
        "ts": now.isoformat(),
        "symbol": "MACRO",
        "direction": direction,
        "confidence": confidence,
        "horizon": "days",
        "risk_exposure_hint": 0.3,  # 共振信号保守
        "expires_at": (now + timedelta(hours=24)).isoformat(),
        "payload": {
            "btc_corr0": corr0,
            "btc_beta": btc.get("beta"),
            "btc_lag_profile": btc.get("lag_profile"),
            "n_assets": n_total,
            "n_granger_significant": n_granger_sig,
            "granger_significant_ratio": granger_ratio,
            "state_generated_at": matrix.get("generated_at"),
            "degraded": degraded,
        },
    }


def main() -> int:
    if _42_ROOT not in sys.path:
        sys.path.insert(0, _42_ROOT)
    from signal_bus import SignalBus  # noqa: E402

    bus = SignalBus()
    results = []

    # ── 40-cycle 信号 ────────────────────────────────────────────
    state = load_cycle_state()
    if state.get("real_cycle"):
        assets = (state.get("technical_anchor") or {}).get("assets") or {}
        if assets:
            signal = build_signal(state)
            result = bus.publish(signal)
            results.append(
                {
                    "source": signal.get("source"),
                    "signal_id": signal.get("signal_id"),
                    "direction": signal.get("direction"),
                    "confidence": signal.get("confidence"),
                    "publish_result": result.get("status"),
                    "reason": result.get("reason"),
                }
            )
        else:
            results.append(
                {"source": "40-cycle", "publish_result": "skipped", "reason": "无技术锚资产数据"}
            )
    else:
        results.append(
            {"source": "40-cycle", "publish_result": "unavailable", "reason": state.get("note")}
        )

    # ── 40-divergence 信号（N4，独立于 cycle_state）──────────────
    rotation = load_asset_rotation()
    div_signal = build_divergence_signal(rotation)
    div_result = bus.publish(div_signal)
    results.append(
        {
            "source": div_signal.get("source"),
            "signal_id": div_signal.get("signal_id"),
            "direction": div_signal.get("direction"),
            "confidence": div_signal.get("confidence"),
            "publish_result": div_result.get("status"),
            "reason": div_result.get("reason"),
        }
    )

    # ── 40-resonance 信号（M1，SPEC-M2 宏观力传导）────────────────
    matrix = load_resonance_matrix()
    res_signal = build_resonance_signal(matrix)
    res_payload = res_signal.get("payload") or {}
    if res_payload.get("degraded") and "resonance_matrix_empty" in res_payload["degraded"]:
        results.append(
            {
                "source": "40-resonance",
                "publish_result": "skipped",
                "reason": "resonance_matrix.json 不存在或为空（fail-open）",
            }
        )
    else:
        res_result = bus.publish(res_signal)
        results.append(
            {
                "source": res_signal.get("source"),
                "signal_id": res_signal.get("signal_id"),
                "direction": res_signal.get("direction"),
                "confidence": res_signal.get("confidence"),
                "publish_result": res_result.get("status"),
                "reason": res_result.get("reason"),
            }
        )

    bus.flush()
    print(
        json.dumps(
            {
                "signals": results,
                "bus_signal_count": bus.snapshot()["signal_count"],
                "bus_sources": bus.snapshot()["sources"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    # 任一信号成功发布即返回 0（fail-open：不互相阻塞）
    return 0 if any(r.get("publish_result") == "accepted" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
