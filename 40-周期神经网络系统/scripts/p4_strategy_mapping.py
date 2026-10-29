#!/usr/bin/env python3
"""P4 策略映射模块（L5 层）：周期判定 → 策略映射建议。

输入：cycle_state / asset_rotation / sector_transmission / stovall_breadth /
      fund_flow / washout_verdicts / meme_platform 产出物
输出：strategy_mapping.json + stagflation_correction_table.json

映射逻辑（预注册）：
  主因子：美林时钟象限（reflation/recovery/overheat/stagflation）
  修正因子1：传导状态（sector_transmission.state）
  修正因子2：市场广度（stovall_breadth.breadth_pct）
  修正因子3：象限置信度（divergence 降级后）
  滞胀修正表：象限=stagflation 或 通胀>阈值 且 增长<阈值 时的独立映射

红线：只产建议不产交易信号（SPEC 边界红线）；所有仓位为建议区间，
交易决策归 23 系统三步门禁。
"""
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from risk_guards import apply_guards

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def load_json(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return json.load(f)


def dump_json(name, obj):
    with open(os.path.join(ROOT, name), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


# ── 预注册映射表 ──────────────────────────────────────────────
# 象限 → 基础策略建议（板块偏好来自 Stovall 映射，加密层类比）
QUADRANT_BASE = {
    "reflation": {
        "stance": "进攻",
        "position_band_pct": [50, 80],
        "crypto_focus": ["L1_anchor", "L2_major"],
        "equity_preference": ["金融", "可选消费", "工业"],
        "rationale": "再通胀：增长回升+通胀回落，风险资产受益",
    },
    "recovery": {
        "stance": "进攻",
        "position_band_pct": [50, 80],
        "crypto_focus": ["L1_anchor", "L2_major", "L3_growth"],
        "equity_preference": ["科技", "工业", "非必需消费"],
        "rationale": "复苏：增长回升+通胀低位，周期敏感板块领先",
    },
    "overheat": {
        "stance": "防御性进攻",
        "position_band_pct": [30, 60],
        "crypto_focus": ["L1_anchor", "L2_major"],
        "equity_preference": ["能源", "材料", "工业"],
        "rationale": "过热：增长与通胀同步上行，受益于价格与产能的板块领先",
    },
    "stagflation": {
        "stance": "防御",
        "position_band_pct": [0, 30],
        "crypto_focus": ["L1_anchor"],
        "equity_preference": ["必需消费", "医疗", "公用事业"],
        "rationale": "滞胀：增长回落+通胀高企，防御板块与现金为王",
    },
}

# 传导状态修正（对 stance/仓位的调整）
TRANSMISSION_ADJUST = {
    "risk_on": {"stance_shift": 1, "position_shift": 10},
    "neutral": {"stance_shift": 0, "position_shift": 0},
    "risk_off": {"stance_shift": -1, "position_shift": -10},
}

# 广度修正
BREADTH_ADJUST = {
    "strong": {"position_shift": 5},   # >=75
    "mixed": {"position_shift": 0},    # 50-75
    "weak": {"position_shift": -10},   # <50
}

# 置信度修正
CONFIDENCE_ADJUST = {
    "high": {"position_shift": 0},
    "medium": {"position_shift": -5},
    "low": {"position_shift": -10},
}

STANCE_ORDER = ["观望", "防御", "防御性进攻", "进攻"]


def clamp_band(band):
    lo, hi = band
    return [max(0, min(100, lo)), max(0, min(100, hi))]


def shift_stance(stance, shift):
    if stance not in STANCE_ORDER:
        return stance
    i = STANCE_ORDER.index(stance) + shift
    return STANCE_ORDER[max(0, min(len(STANCE_ORDER) - 1, i))]


def main():
    cycle = load_json("cycle_state.json")
    rotation = load_json("asset_rotation.json")
    transmission = load_json("sector_transmission.json")
    stovall = load_json("stovall_breadth.json")
    fund_flow = load_json("fund_flow.json")
    washout = load_json("washout_verdicts.json")

    mc = rotation.get("merrill_clock", {})
    quadrant = mc.get("quadrant", "recovery")
    quadrant_conf = mc.get("confidence", "medium")
    # 风险缓解机制（P4 汇聚点统一应用）
    guards = apply_guards(cycle, rotation, transmission, stovall, fund_flow, washout)
    effective_conf = guards.get("effective_confidence", quadrant_conf)
    event_frozen = guards.get("event_window", {}).get("in_window", False)
    clock_degraded = guards.get("clock_degradation", {}).get("clock_degraded", False)
    growth = mc.get("growth_yoy_pct")
    inflation = mc.get("inflation_yoy_pct")
    thresholds = mc.get("thresholds", {})

    # 滞胀修正表（预注册）：象限=stagflation 或 增长/通胀双条件触发
    stagflation_table = {
        "generated_at": now_iso(),
        "trigger_rules": {
            "rule_1": "美林时钟象限 == stagflation",
            "rule_2": "增长 < 增长阈值 且 通胀 > 通胀阈值（独立复核，防象限误判）",
        },
        "growth_threshold": thresholds.get("growth", 1.5),
        "inflation_threshold": thresholds.get("inflation", 2.5),
        "current": {
            "quadrant": quadrant,
            "growth_yoy_pct": growth,
            "inflation_yoy_pct": inflation,
        },
        "correction_active": False,
        "corrected_mapping": None,
        "note": "滞胀修正：时钟失效降级时的独立映射，触发时覆盖象限基础映射",
    }
    rule1 = quadrant == "stagflation"
    rule2 = (growth is not None and inflation is not None
             and growth < thresholds.get("growth", 1.5)
             and inflation > thresholds.get("inflation", 2.5))
    if rule1 or rule2:
        stagflation_table["correction_active"] = True
        stagflation_table["corrected_mapping"] = QUADRANT_BASE["stagflation"]
        quadrant = "stagflation"  # 修正后象限

    base = QUADRANT_BASE[quadrant]
    stance = base["stance"]
    band = list(base["position_band_pct"])

    # 修正因子叠加
    t_state = transmission.get("state", "neutral")
    t_adj = TRANSMISSION_ADJUST.get(t_state, TRANSMISSION_ADJUST["neutral"])
    stance = shift_stance(stance, t_adj["stance_shift"])
    band[0] += t_adj["position_shift"]
    band[1] += t_adj["position_shift"]

    b_state = stovall.get("market_breadth", {}).get("state", "mixed")
    b_adj = BREADTH_ADJUST.get(b_state, BREADTH_ADJUST["mixed"])
    band[0] += b_adj["position_shift"]
    band[1] += b_adj["position_shift"]

    # 事件窗口冻结或时钟降级时，置信度再降一档
    if event_frozen or clock_degraded:
        effective_conf = "low" if effective_conf in ("high", "medium") else effective_conf
    c_adj = CONFIDENCE_ADJUST.get(effective_conf, CONFIDENCE_ADJUST["medium"])
    band[0] += c_adj["position_shift"]
    band[1] += c_adj["position_shift"]
    band = clamp_band(band)

    # 洗盘信号（washout=洗盘持有 → 支持持有；weakness=真弱势 → 减仓提示）
    washout_summary = {}
    for sym, v in washout.get("verdicts", {}).items():
        label = v.get("label", "unknown")
        if label in ("washout", "weakness"):
            washout_summary[sym] = label

    # 聪明钱张力（CFTC 净多 vs 稳定币供应）
    smart = fund_flow.get("smart_money", {})

    mapping = {
        "generated_at": now_iso(),
        "module": "P4 策略映射（L5）",
        "inputs": {
            "quadrant": quadrant,
            "quadrant_confidence": quadrant_conf,
            "transmission_state": t_state,
            "breadth_state": b_state,
            "breadth_pct": stovall.get("market_breadth", {}).get("breadth_pct"),
            "stagflation_correction_active": stagflation_table["correction_active"],
            "effective_confidence": effective_conf,
            "event_window_frozen": event_frozen,
            "clock_degraded": clock_degraded,
        },
        "strategy_suggestion": {
            "stance": stance,
            "position_band_pct": band,
            "crypto_layer_focus": base["crypto_focus"],
            "equity_sector_preference": base["equity_preference"],
            "rationale": base["rationale"],
        },
        "adjustments_applied": {
            "transmission": {"state": t_state, **t_adj},
            "breadth": {"state": b_state, **b_adj},
            "confidence": {"level": quadrant_conf, **c_adj},
        },
        "risk_notes": [],
        "risk_guards": guards,
        "red_line": "只产建议不产交易信号；仓位为建议区间，交易决策归 23 系统三步门禁",
    }

    # 风险提示组装
    notes = mapping["risk_notes"]
    if quadrant_conf != "high":
        notes.append(f"象限置信度 {quadrant_conf}（背离降级），建议降权使用")
    if b_state == "strong":
        lb = stovall.get("market_breadth", {}).get("layer_breadth", {})
        l4 = lb.get("L4_meme", {})
        if l4 and l4.get("breadth_pct", 100) < 75:
            notes.append(f"L4 meme 层广度 {l4.get('breadth_pct')}% 为最弱层，传导末端不健康")
    if washout_summary:
        notes.append(f"洗盘/弱势信号：{washout_summary}")
    if smart:
        notes.append("聪明钱张力：CFTC 投机净多 vs 稳定币供应收缩并存，资金面内部矛盾")
    if event_frozen:
        ev = guards.get("event_window", {})
        notes.append("事件窗口冻结：" + str(ev.get("event")) + " 事件 ±2 日内，周期判定不更新")
    if clock_degraded:
        notes.append("美林时钟失效降级：" + str(guards.get("clock_degradation", {}).get("reasons")))
    if guards.get("guard_errors"):
        notes.append("风险机制部分异常（fail-open）：" + str(guards["guard_errors"]))

    dump_json("strategy_mapping.json", mapping)
    dump_json("stagflation_correction_table.json", stagflation_table)
    print(json.dumps({
        "stance": stance,
        "position_band_pct": band,
        "quadrant": quadrant,
        "stagflation_correction": stagflation_table["correction_active"],
        "risk_notes": len(notes),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
