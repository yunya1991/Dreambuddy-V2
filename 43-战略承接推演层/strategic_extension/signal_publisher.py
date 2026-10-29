# -*- coding: utf-8 -*-
"""43 层信号发布适配器（P4 正式接入，43 侧先行落地）。

按 42 层 SPEC §二 统一 SignalSchema 规范，将 43 层五维评分 + 四档决策 +
war_state 转换为 strategic_extension 信号，落盘为 JSON 产出物。

接入规范（42 层 SPEC §21.1/21.4）：
- source: strategic_extension（主网络侧路径，与 11 系统 bcrm 路径互不叠加权重）
- horizon: days/weeks（long 档，战略评估）
- 影子期标记 shadow: true（42 层 SignalBus 落地前不参与矛盾裁决权重）
- fail-open：任何异常返回保守默认信号（direction=neutral, confidence=0.0）

红线：只产建议不产交易信号；不绕过 13 系统风控。
"""

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from strategic_extension.five_domain_feature_computer import (
    ASSET_CLASSES,
    FiveDomainFeatureComputer,
)
from strategic_extension.strategic_elements_deriver import element_comparison
from strategic_extension.domain_semantics import (
    to_semantic_scores,
    semantic_total,
    semantic_descriptions,
)
from strategic_extension.sentiment_channel import compute_market_sentiment_score

# 信号产出物路径（43 模块 runtime 目录）
_SIGNAL_OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "runtime", "strategic_extension_signal.json",
)

# 四要素推演历史记录路径（JSONL，训练数据积累，SPEC §13.3 长期闭环）
_ELEMENTS_HISTORY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "runtime", "strategic_elements_history.jsonl",
)

# 五维权重（SPEC §二 预注册固定值）
_DOMAIN_WEIGHTS = {"dao": 0.30, "tian": 0.15, "di": 0.25, "jiang": 0.15, "fa": 0.15}

# 四档决策阈值（SPEC §三）
_TIER_ATTACK = 75
_TIER_DEFEND = 60
_TIER_LIGHT = 50


def _tier_of(total: int) -> Dict[str, Any]:
    """总分 → 四档决策（SPEC §三）。"""
    if total >= _TIER_ATTACK:
        return {"tier": "attack", "position_band": "80-100%", "war_state": "ACTIVE"}
    if total >= _TIER_DEFEND:
        return {"tier": "defend", "position_band": "20-50%", "war_state": "ACTIVE"}
    if total >= _TIER_LIGHT:
        return {"tier": "light_defense", "position_band": "0-20%", "war_state": "FREEZE"}
    return {"tier": "full_freeze", "position_band": "0%", "war_state": "FREEZE"}


def _direction_of(total: int, dao: int) -> str:
    """方向判定：总分偏移 + 道维一票否决（dao<40 → neutral）。"""
    if dao < 40:
        return "neutral"
    if total >= 65:
        return "long"
    if total <= 45:
        return "short"
    return "neutral"


def _confidence_of(total: int) -> float:
    """置信度：总分偏离 50 的程度归一（0.5 基准，±25 分打满）。"""
    return round(max(0.0, min(1.0, 0.5 + (total - 50) / 50.0)), 4)


def _risk_exposure_hint(tier: str) -> float:
    """风险敞口提示：四档 → [0,1]（仅建议，13 系统门禁兜底）。"""
    return {
        "attack": 0.8,
        "defend": 0.35,
        "light_defense": 0.1,
        "full_freeze": 0.0,
    }.get(tier, 0.0)


def build_signal(
    coin_data: Optional[Dict[str, Any]] = None,
    system_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """构建 strategic_extension 信号（统一 SignalSchema）。"""
    now = datetime.now(timezone.utc)
    try:
        computer = FiveDomainFeatureComputer()
        scores = computer.compute(coin_data, system_state)

        # P5 四要素推演 + 分支对比（fail-open：异常时 payload 中该字段缺失）
        strategic_elements = None
        try:
            strategic_elements = element_comparison(coin_data, system_state)
        except Exception:  # noqa: BLE001
            strategic_elements = None

        # v1.2 语义五维（交易市场语义命名 + 新权重总分）+ 自建情绪通道（fail-open）
        semantic_view = None
        try:
            main_scores = (scores.get("crypto_usdt") or {})
            semantic_view = {
                "scores": to_semantic_scores(main_scores),
                "total": semantic_total(main_scores),
                "weights": {"macro_policy": 0.20, "technical": 0.25, "capital_flow": 0.20, "market_sentiment": 0.15, "fundamental": 0.20},
                "descriptions": semantic_descriptions(),
                "sentiment_channel": compute_market_sentiment_score(),
            }
        except Exception:  # noqa: BLE001
            semantic_view = None

        per_class = {}
        for cls in ASSET_CLASSES:
            s = scores.get(cls) or {}
            total = int(round(sum(s.get(d, 50) * w for d, w in _DOMAIN_WEIGHTS.items())))
            tier_info = _tier_of(total)
            per_class[cls] = {
                "five_scores": s,
                "total": total,
                "tier": tier_info["tier"],
                "position_band": tier_info["position_band"],
                "war_state": tier_info["war_state"],
                "direction": _direction_of(total, s.get("dao", 50)),
                "confidence": _confidence_of(total),
                "risk_exposure_hint": _risk_exposure_hint(tier_info["tier"]),
            }

        # 主信号取 crypto_usdt 类（当前白名单仅 BTC）
        main = per_class.get("crypto_usdt") or {}
        signal = {
            "signal_id": "sig_{}_{}".format(
                now.strftime("%Y%m%d"), uuid.uuid4().hex[:8]
            ),
            "source": "strategic_extension",
            "ts": now.isoformat(),
            "symbol": "BTC/USDT",
            "direction": main.get("direction", "neutral"),
            "confidence": main.get("confidence", 0.0),
            "horizon": "days",
            "risk_exposure_hint": main.get("risk_exposure_hint", 0.0),
            "expires_at": (now + timedelta(hours=24)).isoformat(),
            "shadow": True,
            "payload": {
                "per_asset_class": per_class,
                "strategic_elements": strategic_elements,
                "semantic_view": semantic_view,
                "bridge_switch": bool(getattr(computer, "enable_cycle_state_bridge", False)),
                "disclaimer": "战略建议非交易信号；13 系统风控门禁兜底",
            },
        }
        return signal
    except Exception:  # noqa: BLE001  fail-open：保守默认信号
        return {
            "signal_id": "sig_{}_{}".format(
                now.strftime("%Y%m%d"), uuid.uuid4().hex[:8]
            ),
            "source": "strategic_extension",
            "ts": now.isoformat(),
            "symbol": "BTC/USDT",
            "direction": "neutral",
            "confidence": 0.0,
            "horizon": "days",
            "risk_exposure_hint": 0.0,
            "expires_at": (now + timedelta(hours=24)).isoformat(),
            "shadow": True,
            "payload": {"fail_open": True},
        }


def _append_elements_history(signal: Dict[str, Any]) -> None:
    """四要素推演历史记录追加落盘（JSONL，fail-open 不阻断发布）。

    记录字段：时间戳/信号ID/四要素推演结果/分支对比/分歧触发标记。
    用途：训练数据积累（SPEC §13.3 长期闭环：推演→执行→反馈→再训练）。
    """
    try:
        elements = (signal.get("payload") or {}).get("strategic_elements")
        if not elements:
            return
        record = {
            "ts": signal.get("ts"),
            "signal_id": signal.get("signal_id"),
            "direction": signal.get("direction"),
            "confidence": signal.get("confidence"),
            "strategic_elements": elements,
        }
        os.makedirs(os.path.dirname(_ELEMENTS_HISTORY_PATH), exist_ok=True)
        with open(_ELEMENTS_HISTORY_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001  历史记录失败不阻断发布
        pass


def publish(
    coin_data: Optional[Dict[str, Any]] = None,
    system_state: Optional[Dict[str, Any]] = None,
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    """构建信号并原子落盘（写临时文件后 rename）。"""
    signal = build_signal(coin_data, system_state)
    path = output_path or _SIGNAL_OUTPUT_PATH
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(signal, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:  # noqa: BLE001  落盘失败不阻断信号返回
        pass
    _append_elements_history(signal)
    return signal


if __name__ == "__main__":
    print(json.dumps(publish(), ensure_ascii=False, indent=2))
