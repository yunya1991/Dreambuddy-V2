# -*- coding: utf-8 -*-
"""战略要素推演模块（P5 阶段，SPEC §十二）。

定位：43 层承接 40 大周期特征（季/周），基于日周期特征推演四个交易要素，
作为战略承接层的结构化输出：
- asset_allocation：资产类别配比（资金在哪种资产上更容易赚钱）
- direction_bias：多空方向配比（在哪种资产上做多/做空更容易盈利）
- capital_posture：资金投入比例（当下市场环境激进/适中/保守）
- target_ranking：标的选择（哪种标的从技术面洗盘/资金面/情绪面更具备潜力）

分支对比（element_comparison）：43 战略层四要素 vs 分支视角（40 承接数据推导），
标注分歧点，作为矛盾系统介入的触发依据（SPEC §11.3/§12.2）。

红线：只产建议不产交易信号；fail-open：任何异常返回保守默认；
四要素是聚合输出而非模型直出（模型管判别，战略层管聚合，23 管门禁）。
"""

import json
import os
from typing import Any, Dict, List, Optional

from strategic_extension.five_domain_feature_computer import (
    ASSET_CLASSES,
    FiveDomainFeatureComputer,
)
from strategic_extension import cycle_state_adapter as csa

# 四档决策阈值（SPEC §三）
_TIER_ATTACK = 75
_TIER_DEFEND = 60
_TIER_LIGHT = 50


def _safe_div(a: float, b: float, default: float = 0.0) -> float:
    try:
        return a / b if b else default
    except Exception:
        return default


# ────────────────────────────────────────────────
# 要素1：资产类别配比（五维总分横向归一）
# ────────────────────────────────────────────────
def derive_asset_allocation(five_scores_by_class: Dict[str, Dict[str, int]]) -> Dict[str, Any]:
    """三类资产总分横向归一 → 配比建议（softmax 温和版，总分差 → 配比差）。"""
    try:
        totals = {}
        for cls in ASSET_CLASSES:
            s = five_scores_by_class.get(cls) or {}
            totals[cls] = int(round(sum(s.get(d, 50) * w for d, w in {
                "dao": 0.30, "tian": 0.15, "di": 0.25, "jiang": 0.15, "fa": 0.15,
            }.items())))
        # 总分 → 权重：50 分基准，每高 10 分权重 ×1.5（温和放大差异）
        raw = {cls: max(0.01, 1.5 ** ((t - 50) / 10.0)) for cls, t in totals.items()}
        total_raw = sum(raw.values())
        allocation = {cls: round(v / total_raw, 4) for cls, v in raw.items()}
        leader = max(allocation, key=allocation.get) if allocation else None
        return {
            "totals": totals,
            "allocation": allocation,
            "leader": leader,
            "note": "资金在哪种资产上更容易赚钱：配比基于五维总分横向归一",
        }
    except Exception:  # noqa: BLE001
        return {"allocation": {cls: round(1.0 / len(ASSET_CLASSES), 4) for cls in ASSET_CLASSES},
                "leader": None, "fail_open": True}


# ────────────────────────────────────────────────
# 要素2：多空方向配比（道天维方向分 + 总分偏移）
# ────────────────────────────────────────────────
def derive_direction_bias(five_scores_by_class: Dict[str, Dict[str, int]]) -> Dict[str, Any]:
    """每类资产多空配比：总分偏移 → long/short/neutral 权重。"""
    try:
        per_class = {}
        for cls in ASSET_CLASSES:
            s = five_scores_by_class.get(cls) or {}
            total = int(round(sum(s.get(d, 50) * w for d, w in {
                "dao": 0.30, "tian": 0.15, "di": 0.25, "jiang": 0.15, "fa": 0.15,
            }.items())))
            # 总分 50 中性；65+ 全多；45- 全空；线性过渡
            long_w = max(0.0, min(1.0, (total - 50) / 15.0))
            short_w = max(0.0, min(1.0, (50 - total) / 15.0))
            neutral_w = max(0.0, 1.0 - long_w - short_w)
            # 道维一票否决：dao<40 → 全 neutral
            if s.get("dao", 50) < 40:
                long_w, short_w, neutral_w = 0.0, 0.0, 1.0
            per_class[cls] = {
                "long": round(long_w, 4), "short": round(short_w, 4),
                "neutral": round(neutral_w, 4),
                "dominant": "long" if long_w > max(short_w, neutral_w) else (
                    "short" if short_w > max(long_w, neutral_w) else "neutral"),
            }
        return {"per_class": per_class, "note": "在哪种资产上做多/做空更容易盈利"}
    except Exception:  # noqa: BLE001
        return {"per_class": {cls: {"long": 0.0, "short": 0.0, "neutral": 1.0, "dominant": "neutral"}
                               for cls in ASSET_CLASSES}, "fail_open": True}


# ────────────────────────────────────────────────
# 要素3：资金投入比例（大周期相位 + MA200 锚 + 四档融合）
# ────────────────────────────────────────────────
def derive_capital_posture(
    five_scores_by_class: Dict[str, Dict[str, int]],
    bridge_inputs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """激进/适中/保守：大周期相位（美林时钟）+ MA200 锚 + 四档决策融合。"""
    try:
        bi = bridge_inputs or {}
        # 大周期相位分：RECOVERY 70 / OVERHEAT 60 / STAGFLATION 40 / REFLATION 30（对齐美林评分表）
        phase_scores = {"RECOVERY": 70, "OVERHEAT": 60, "STAGFLATION": 40, "REFLATION": 30}
        phase = bi.get("merrill_phase")
        phase_score = phase_scores.get(phase, 50) if phase else 50
        # MA200 锚分：分位 [0,1] → 0-100
        ma200_pct = bi.get("ma200_distance_percentile")
        ma200_score = int(round(ma200_pct * 100)) if isinstance(ma200_pct, (int, float)) else 50
        # crypto_usdt 总分四档
        s = five_scores_by_class.get("crypto_usdt") or {}
        total = int(round(sum(s.get(d, 50) * w for d, w in {
            "dao": 0.30, "tian": 0.15, "di": 0.25, "jiang": 0.15, "fa": 0.15,
        }.items())))
        # 三因子等权融合
        fused = (phase_score + ma200_score + total) / 3.0
        if fused >= 65:
            posture, exposure = "aggressive", 0.8
        elif fused >= 55:
            posture, exposure = "moderate", 0.5
        elif fused >= 45:
            posture, exposure = "conservative", 0.25
        else:
            posture, exposure = "defensive", 0.1
        return {
            "posture": posture,
            "exposure_hint": exposure,
            "factors": {
                "cycle_phase": {"phase": phase, "score": phase_score},
                "ma200_anchor": {"percentile": ma200_pct, "score": ma200_score},
                "five_domain_total": total,
            },
            "fused": round(fused, 2),
            "note": "当下市场环境激进/适中/保守（仅建议，13 系统门禁兜底）",
        }
    except Exception:  # noqa: BLE001
        return {"posture": "defensive", "exposure_hint": 0.1, "fail_open": True}


# ────────────────────────────────────────────────
# 要素4：标的选择（洗盘判定 + L1-L4 轮动 + 情绪聚合，仅 crypto_usdt）
# ────────────────────────────────────────────────
def derive_target_ranking(bridge_inputs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """标的潜力排序：技术面洗盘 + 资金面轮动 + 情绪面聚合。"""
    try:
        bi = bridge_inputs or {}
        candidates: Dict[str, Dict[str, Any]] = {}

        # 技术面：洗盘判定（washout=洗盘持有潜力，weakness=真弱势排除）
        wv = csa.load_washout_verdicts()
        verdicts = (wv.get("verdicts") or {}) if wv else {}
        for symbol, v in verdicts.items():
            label = (v or {}).get("label")
            if label == "washout":
                candidates.setdefault(symbol, {})["tech_score"] = 75
            elif label == "weakness":
                candidates.setdefault(symbol, {})["tech_score"] = 20
            # unknown（含未触发触发门）不注入

        # 资金面：L1-L4 板块轮动（龙头动量 + 层级中位动量）
        ff = csa.load_fund_flow()
        layers = (((ff or {}).get("intra_sector_flow") or {}).get("layers") or {})
        for layer_name, layer in layers.items():
            if not isinstance(layer, dict):
                continue
            leader = layer.get("leader") or {}
            sym = leader.get("symbol")
            mom = leader.get("momentum_pct")
            if sym and isinstance(mom, (int, float)):
                entry = candidates.setdefault(sym, {})
                entry["fund_score"] = int(round(max(0.0, min(100.0, 50 + mom * 2.0))))
                entry["layer"] = layer_name

        # 情绪面：CFTC 投机情绪（全局，应用到全部候选）
        sentiment = bi.get("policy_sentiment_score")
        sent_score = int(round(sentiment * 100)) if isinstance(sentiment, (int, float)) else 50

        # 聚合排序：tech 40% + fund 40% + sentiment 20%（缺失因子回退 50）
        ranking: List[Dict[str, Any]] = []
        for sym, entry in candidates.items():
            tech = entry.get("tech_score", 50)
            fund = entry.get("fund_score", 50)
            composite = tech * 0.40 + fund * 0.40 + sent_score * 0.20
            ranking.append({
                "symbol": sym,
                "composite": round(composite, 2),
                "tech_score": tech,
                "fund_score": fund,
                "sentiment_score": sent_score,
                "layer": entry.get("layer"),
            })
        ranking.sort(key=lambda x: x["composite"], reverse=True)
        return {
            "ranking": ranking[:10],
            "note": "标的潜力排序（技术面洗盘+资金面轮动+情绪面聚合，仅 crypto_usdt 类）",
            "data_available": bool(candidates),
        }
    except Exception:  # noqa: BLE001
        return {"ranking": [], "data_available": False, "fail_open": True}


# ────────────────────────────────────────────────
# 主入口：四要素推演
# ────────────────────────────────────────────────
def derive_strategic_elements(
    coin_data: Optional[Dict[str, Any]] = None,
    system_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """推演战略四要素（主入口）。"""
    computer = FiveDomainFeatureComputer()
    five_scores = computer.compute(coin_data, system_state)
    bridge_inputs = csa.build_bridge_inputs(asset_class="crypto_usdt")
    return {
        "asset_allocation": derive_asset_allocation(five_scores),
        "direction_bias": derive_direction_bias(five_scores),
        "capital_posture": derive_capital_posture(five_scores, bridge_inputs),
        "target_ranking": derive_target_ranking(bridge_inputs),
    }


# ────────────────────────────────────────────────
# 分支对比：43 战略层四要素 vs 分支视角（40 承接数据推导）
# ────────────────────────────────────────────────
def element_comparison(
    coin_data: Optional[Dict[str, Any]] = None,
    system_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """43 战略层四要素 vs 分支视角对比，标注分歧点（矛盾系统介入触发依据）。"""
    try:
        strategic = derive_strategic_elements(coin_data, system_state)
        bi = csa.build_bridge_inputs(asset_class="crypto_usdt")

        # 分支视角：直接由 40 承接数据推导（大周期相位 + MA200 + 资金流）
        phase_scores = {"RECOVERY": 70, "OVERHEAT": 60, "STAGFLATION": 40, "REFLATION": 30}
        phase = bi.get("merrill_phase")
        branch_phase_score = phase_scores.get(phase, 50) if phase else 50
        ma200_pct = bi.get("ma200_distance_percentile")
        branch_ma200_score = int(round(ma200_pct * 100)) if isinstance(ma200_pct, (int, float)) else 50
        liquidity = bi.get("liquidity_score")
        branch_liquidity_score = int(round(liquidity * 100)) if isinstance(liquidity, (int, float)) else 50
        branch_fused = (branch_phase_score + branch_ma200_score + branch_liquidity_score) / 3.0
        if branch_fused >= 65:
            branch_posture = "aggressive"
        elif branch_fused >= 55:
            branch_posture = "moderate"
        elif branch_fused >= 45:
            branch_posture = "conservative"
        else:
            branch_posture = "defensive"

        branch_view = {
            "posture": branch_posture,
            "fused": round(branch_fused, 2),
            "factors": {
                "cycle_phase": {"phase": phase, "score": branch_phase_score},
                "ma200_anchor": {"percentile": ma200_pct, "score": branch_ma200_score},
                "liquidity": {"value": liquidity, "score": branch_liquidity_score},
            },
            "note": "分支视角：40 承接数据直接推导（周期相位+MA200+流动性）",
        }

        # 分歧检测：资金投入姿态不一致 → 矛盾系统介入触发依据
        strategic_posture = (strategic.get("capital_posture") or {}).get("posture")
        divergences = []
        if strategic_posture and branch_posture and strategic_posture != branch_posture:
            divergences.append({
                "element": "capital_posture",
                "strategic": strategic_posture,
                "branch": branch_posture,
                "severity": "high" if {strategic_posture, branch_posture} >= {"aggressive", "defensive"} else "medium",
            })

        return {
            "strategic_view": strategic,
            "branch_view": branch_view,
            "divergences": divergences,
            "contradiction_trigger": bool(divergences),
            "note": "分歧即是否需要矛盾系统介入的触发依据（SPEC §12.2）",
        }
    except Exception:  # noqa: BLE001
        return {"strategic_view": None, "branch_view": None, "divergences": [],
                "contradiction_trigger": False, "fail_open": True}


if __name__ == "__main__":
    print(json.dumps(element_comparison(), ensure_ascii=False, indent=2))
