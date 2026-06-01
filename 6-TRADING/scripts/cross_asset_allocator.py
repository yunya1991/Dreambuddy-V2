#!/usr/bin/env python3
"""
跨资产宏观对冲配置器 v1.0
==========================
Dalio 全天候框架 × BTC 中心化适配

核心设计:
  借鉴 Bridgewater All-Weather 风险平价思想
  以美林时钟四象限为锚定，动态分配多空仓位
  BTC 在不同象限扮演不同角色（主力多头 / 轻仓多头 / 空头标的 / 左侧积累）

四象限:
  Recovery    (GDP↑ CPI↓) — Spring  → BTC 满仓多头，全力进攻
  Overheat    (GDP↑ CPI↑) — Summer  → 能源/黄金多 + 少量 BTC + 空 SPY
  Stagflation (GDP↓ CPI↑) — Autumn  → 防御商品多 + BTC/ETH 空头对冲
  Reflation   (GDP↓ CPI↓) — Winter  → 等待流动性拐点，左侧建仓 BTC

资产相关性:
  最佳对冲对:
    Stagflation: Long XLP + Short ETH  (相关 -0.10，最佳)
    Overheat:    Long XLE + Short SPY  (相关 0.40，方向差即利润)
    Recovery:    Long SOL + Long BTC   (相关 0.65，同向杠杆)
    Reflation:   Long SPY + Long GOLD  (相关 0.05，几乎独立)

外部依赖: 无
可独立运行: python cross_asset_allocator.py
"""

from typing import Dict, List, Optional, Tuple


# ==================== 马丁模式参数 ====================

MARTIN_MODES: Dict[str, Dict] = {
    "standard": {
        "vol_mult_adj":  1.0,
        "interval_pct":  8.0,
        "tp_pct":        4.0,
        "max_layers":    3,
        "single_layer":  False,
        "note":          "标准 V9 加密马丁",
    },
    "light": {
        "vol_mult_adj":  1.5,
        "interval_pct": 12.0,
        "tp_pct":        6.0,
        "max_layers":    2,
        "single_layer":  False,
        "note":          "宽间隔轻仓（Overheat BTC）",
    },
    "wide_interval": {
        "vol_mult_adj":  1.5,
        "interval_pct": 12.0,
        "tp_pct":        6.0,
        "max_layers":    3,
        "single_layer":  False,
        "note":          "宽间隔空头马丁（防逼空）",
    },
    "single_layer": {
        "vol_mult_adj":  1.0,
        "interval_pct":  0.0,
        "tp_pct":        5.0,
        "max_layers":    1,
        "single_layer":  True,
        "note":          "不加仓单层（高波动空头）",
    },
    "equity": {
        "vol_mult_adj":  0.65,
        "interval_pct":  4.0,
        "tp_pct":        2.0,
        "max_layers":    2,
        "single_layer":  False,
        "note":          "代币化股票/商品ETF标准",
    },
    "reflation_btc": {
        "vol_mult_adj":  1.5,
        "interval_pct": 12.0,
        "tp_pct":        8.0,
        "max_layers":    2,
        "single_layer":  False,
        "note":          "左侧建仓，宽止盈等待反转",
    },
}


# ==================== 资产相关性矩阵 ====================

CORRELATION_MATRIX: Dict[Tuple[str, str], float] = {
    ("BTC",  "ETH"):  0.75,
    ("BTC",  "SOL"):  0.65,
    ("BTC",  "GOLD"): -0.10,
    ("BTC",  "SPY"):  0.52,
    ("BTC",  "XLE"):  0.15,
    ("BTC",  "XLP"):  -0.05,
    ("ETH",  "SOL"):  0.80,
    ("ETH",  "GOLD"): -0.15,
    ("ETH",  "SPY"):  0.45,
    ("ETH",  "XLE"):  0.10,
    ("ETH",  "XLP"):  -0.10,
    ("SOL",  "GOLD"): -0.20,
    ("SOL",  "SPY"):  0.38,
    ("GOLD", "SPY"):  0.05,
    ("GOLD", "XLE"):  0.30,
    ("GOLD", "XLP"):  0.20,
    ("SPY",  "XLE"):  0.40,
    ("SPY",  "XLP"):  0.50,
    ("XLE",  "XLP"):  0.35,
}


def get_correlation(a: str, b: str) -> float:
    """查询两资产相关性（对称）."""
    return CORRELATION_MATRIX.get((a, b)) or CORRELATION_MATRIX.get((b, a), 0.0)


BEST_HEDGE_PAIRS = {
    "STAGFLATION":      ("XLP",  "ETH",  "相关 -0.10，最佳对冲对"),
    "STAGFLATION_LITE": ("XLP",  "ETH",  "相关 -0.10，最佳对冲对"),
    "OVERHEAT":         ("XLE",  "SPY",  "方向差即利润，相关 0.40"),
    "RECOVERY":         ("SOL",  "BTC",  "同向加杠杆，相关 0.65"),
    "REFLATION":        ("SPY",  "GOLD", "几乎独立，相关 0.05"),
}


# ==================== 四象限配置矩阵 ====================
# 权重为实际组合占比（多+空+现金 = 100%）
# 空头权重来自现金池支付保证金

_ALLOC = {

    # ── 象限1: Recovery（春天）—— BTC 最优，全力做多 ──────────────────────
    "RECOVERY": {
        "season":              "Spring",
        "position_multiplier": 1.0,
        "btc_role":            "high_beta_long",
        "strategy_note":       "BTC 满仓主力，高贝塔全线做多",
        "longs": [
            {"asset": "BTC",  "weight": 0.40, "martin_mode": "standard"},
            {"asset": "ETH",  "weight": 0.20, "martin_mode": "standard"},
            {"asset": "SOL",  "weight": 0.10, "martin_mode": "standard"},
            {"asset": "NVDA", "weight": 0.15, "martin_mode": "equity"},
            {"asset": "TSLA", "weight": 0.10, "martin_mode": "equity"},
        ],
        "shorts": [],
        "cash":   0.05,
        "stop_rule": "20% 组合回撤强制全平",
    },

    # ── 象限2: Overheat（夏天）—— 商品 > 股票 > BTC ──────────────────────
    "OVERHEAT": {
        "season":              "Summer",
        "position_multiplier": 0.6,
        "btc_role":            "light_long",
        "strategy_note":       "能源/黄金多 + 少量 BTC + 空 SPY 对冲股市",
        "longs": [
            {"asset": "XLE",  "weight": 0.25, "martin_mode": "equity"},
            {"asset": "GOLD", "weight": 0.15, "martin_mode": "equity"},
            {"asset": "BTC",  "weight": 0.20, "martin_mode": "light"},
        ],
        "shorts": [
            {"asset": "SPY",  "weight": 0.10, "martin_mode": "single_layer"},
        ],
        "cash":   0.30,
        "stop_rule": "15% 组合回撤止损",
    },

    # ── 象限3: Stagflation（秋天）—— 防御优先，空高贝塔 ← 当前 ──────────
    "STAGFLATION": {
        "season":              "Autumn",
        "position_multiplier": 0.4,
        "btc_role":            "high_beta_short",
        "strategy_note":       "防御商品多头 + BTC/ETH 空头马丁对冲",
        "longs": [
            {"asset": "XLP",  "weight": 0.25, "martin_mode": "equity"},
            {"asset": "XLE",  "weight": 0.20, "martin_mode": "equity"},
            {"asset": "GOLD", "weight": 0.15, "martin_mode": "equity"},
        ],
        "shorts": [
            {"asset": "BTC",  "weight": 0.10, "martin_mode": "wide_interval"},
            {"asset": "ETH",  "weight": 0.05, "martin_mode": "single_layer"},
        ],
        "cash":   0.25,
        "stop_rule": "10% 组合回撤止损（防御模式严格）",
    },

    # ── 象限4: Reflation（冬天）—— 等待拐点，左侧建仓 BTC ──────────────
    "REFLATION": {
        "season":              "Winter",
        "position_multiplier": 0.5,
        "btc_role":            "accumulation_lhs",
        "strategy_note":       "SPY/债券先行，BTC 宽间隔左侧布局，保留弹药",
        "longs": [
            {"asset": "SPY",  "weight": 0.30, "martin_mode": "equity"},
            {"asset": "BTC",  "weight": 0.20, "martin_mode": "reflation_btc"},
        ],
        "shorts": [],
        "cash":   0.50,
        "stop_rule": "15% 组合回撤止损",
    },
}

# Stagflation Lite = 同 Stagflation 策略，但 GDP 仍为正值（轻度滞胀）
_ALLOC["STAGFLATION_LITE"] = dict(_ALLOC["STAGFLATION"])
_ALLOC["STAGFLATION_LITE"] = {
    **_ALLOC["STAGFLATION"],
    "strategy_note": "Stagflation Lite (GDP 正增长 + CPI 顽固): 防御商品多 + BTC/ETH 空头",
}


# ==================== 象限切换触发规则 ====================

REGIME_TRIGGERS: Dict[str, Dict[str, str]] = {
    "STAGFLATION_LITE": {
        "to_recovery":    "CPI 连续 2 月 <2.5%  AND  10Y <4%  或  Fed 首次降息",
        "to_overheat":    "GDP >3%  AND  CPI >3%（增长超预期）",
        "to_reflation":   "GDP <0   AND  CPI <2%（滑入衰退 + 通胀回落）",
        "to_stagflation": "GDP 转负，维持高通胀（进入经典滞胀）",
    },
    "STAGFLATION": {
        "to_recovery":  "CPI 连续 2 月 <2.5%  AND  10Y <4%  或  Fed 首次降息",
        "to_overheat":  "GDP >3%  AND  CPI >3%（增长复苏但通胀未控制）",
        "to_reflation": "GDP <0   AND  CPI <2%（通缩式衰退）",
    },
    "RECOVERY": {
        "to_overheat":    "CPI 连续 2 月 >3%  AND  GDP >2%",
        "to_stagflation": "GDP <1%  AND  CPI >3%（紧急防御）",
        "to_reflation":   "GDP 快速下行至 <0",
    },
    "OVERHEAT": {
        "to_stagflation": "GDP 开始下行  AND  CPI 仍 >2%",
        "to_recovery":    "CPI 明显回落 <2%  AND  GDP >2%（软着陆）",
    },
    "REFLATION": {
        "to_recovery":    "GDP 触底反弹 >0  AND  CPI <2%（拐点确认）",
        "to_stagflation": "GDP 未反弹，CPI 再起（二次通胀路径）",
    },
}


# ==================== Phase 2 资产清单 ====================
# Phase 1 时这些多头权重转为现金；空头不受影响
_PHASE2_ASSETS = {"XLE", "XLP", "GOLD"}


# ==================== 主函数 ====================

def calc_cross_asset_allocation(
    clock_stage: Optional[str] = None,
    regime: Optional[str] = None,
    phase1_only: bool = False,
) -> Dict:
    """
    跨资产宏观对冲配置.

    参数:
      clock_stage — 美林时钟阶段（来自跨市场维度 annotation）
      regime      — Screen1 合成信号（STRONG_BULL/WEAK_BULL/...）
      phase1_only — True: XLE/XLP/GOLD 多头权重合并至现金

    返回:
    {
        "ml_clock_phase":      str,
        "btc_role":            str,
        "season":              str,
        "position_multiplier": float,
        "allocation": {
            "long":  [{asset, weight, direction, martin_mode, martin_params}],
            "short": [{asset, weight, direction, martin_mode, martin_params}],
            "cash":  float,
        },
        "total_deployed": float,       # long + short weights
        "regime_trigger": dict,
        "best_hedge_pair": dict,
        "excluded_phase2": [str],
        "strategy_note":   str,
        "stop_rule":       str,
    }
    """
    # 时钟阶段标准化
    cs = str(clock_stage).upper() if clock_stage else "STAGFLATION_LITE"
    if cs not in _ALLOC:
        cs = "STAGFLATION_LITE"

    quad     = _ALLOC[cs]
    longs    = [dict(x) for x in quad["longs"]]
    shorts   = [dict(x) for x in quad["shorts"]]
    cash     = quad["cash"]
    excluded = []

    # Phase 1 过滤（多头中的 Phase 2 资产 → 现金；空头不受影响）
    if phase1_only:
        filtered = []
        for item in longs:
            if item["asset"] in _PHASE2_ASSETS:
                excluded.append(item["asset"])
                cash = round(cash + item["weight"], 4)
            else:
                filtered.append(item)
        longs = filtered

    # 附加方向和完整 Martin 参数
    def enrich(items: List[Dict], direction: str) -> List[Dict]:
        result = []
        for item in items:
            e = dict(item)
            e["direction"]     = direction
            mode               = e.get("martin_mode", "standard")
            e["martin_params"] = dict(MARTIN_MODES.get(mode, MARTIN_MODES["standard"]))
            result.append(e)
        return result

    long_items  = enrich(longs,  "LONG")
    short_items = enrich(shorts, "SHORT")

    total_long  = sum(x["weight"] for x in long_items)
    total_short = sum(x["weight"] for x in short_items)
    total_deployed = round(total_long + total_short, 4)

    triggers   = dict(REGIME_TRIGGERS.get(cs, {}))
    hedge_info = BEST_HEDGE_PAIRS.get(cs, ("—", "—", "—"))

    return {
        "ml_clock_phase":      cs,
        "btc_role":            quad["btc_role"],
        "season":              quad["season"],
        "position_multiplier": quad["position_multiplier"],
        "allocation": {
            "long":  long_items,
            "short": short_items,
            "cash":  round(cash, 4),
        },
        "total_deployed":  total_deployed,
        "regime_trigger":  triggers,
        "best_hedge_pair": {
            "long_asset":  hedge_info[0],
            "short_asset": hedge_info[1],
            "note":        hedge_info[2],
        },
        "excluded_phase2": excluded,
        "strategy_note":   quad["strategy_note"],
        "stop_rule":       quad.get("stop_rule", ""),
    }


def get_btc_role_label(btc_role: str) -> str:
    """BTC 角色中文标签."""
    return {
        "high_beta_long":   "高贝塔多头主力",
        "light_long":       "轻仓多头（宽止损）",
        "high_beta_short":  "高贝塔空头对冲标的",
        "accumulation_lhs": "左侧积累建仓",
    }.get(btc_role, btc_role)


def format_screen1_a_summary(result: Dict) -> str:
    """格式化 Screen 1 A系列最终输出摘要."""
    clock  = result["ml_clock_phase"]
    season = result["season"]
    lines = [
        "=== Screen 1 A系列 跨资产多空配置 ===",
        f"象限定位:    {clock} ({season})",
        f"BTC 角色:    {get_btc_role_label(result['btc_role'])}",
        f"仓位乘数:    {result['position_multiplier']:.1f} "
        f"(总敞口 {result['total_deployed']*100:.0f}% | "
        f"现金 {result['allocation']['cash']*100:.0f}%)",
        f"止损规则:    {result['stop_rule']}",
        "─" * 55,
    ]

    longs  = result["allocation"]["long"]
    shorts = result["allocation"]["short"]

    if longs:
        lines.append("多头配置:")
        for item in longs:
            mp = item["martin_params"]
            tag = f"[间隔 {mp['interval_pct']:.0f}%×vm | TP {mp['tp_pct']:.0f}%×vm | L{mp['max_layers']}]"
            lines.append(f"  {item['asset']:5s}  {item['weight']*100:4.0f}%   {tag}  {mp['note']}")

    if shorts:
        lines.append("空头配置:")
        for item in shorts:
            mp = item["martin_params"]
            tag = f"[间隔 {mp['interval_pct']:.0f}%×vm | TP {mp['tp_pct']:.0f}%×vm | L{mp['max_layers']}]"
            lines.append(f"  {item['asset']:5s}  {item['weight']*100:4.0f}%   {tag}  {mp['note']}")

    if not longs and not shorts:
        lines.append("  全现金，等待信号")

    if result.get("excluded_phase2"):
        lines.append(f"Phase 2 跳过: {', '.join(result['excluded_phase2'])} → 合并现金")

    lines.append("─" * 55)
    hp = result["best_hedge_pair"]
    lines.append(f"最佳对冲对:  Long {hp['long_asset']} + Short {hp['short_asset']}  ({hp['note']})")

    lines.append("象限切换触发:")
    for k, v in result["regime_trigger"].items():
        arrow = k.replace("to_", "→ 转入 ")
        lines.append(f"  {arrow:20s}: {v}")

    return "\n".join(lines)


# ==================== 快速独立测试 ====================

if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    print("=" * 80)
    print("跨资产宏观对冲配置器 v1.0 -- 四象限验证")
    print("=" * 80)

    test_cases = [
        ("RECOVERY",         "STRONG_BULL",  "Recovery 春天（最优）"),
        ("OVERHEAT",         "WEAK_BULL",    "Overheat 夏天"),
        ("STAGFLATION_LITE", "STRONG_BEAR",  "Stagflation Lite 秋天（当前）"),
        ("STAGFLATION",      "STRONG_BEAR",  "Stagflation 经典"),
        ("REFLATION",        "WEAK_BEAR",    "Reflation 冬天"),
        (None,               "CONSOLIDATION","无时钟数据（默认防御）"),
    ]

    print(f"\n{'场景':30s}  {'乘数':6s}  {'多头':40s}  {'空头':25s}  {'现金':5s}")
    print("-" * 120)
    for clock, regime, label in test_cases:
        r  = calc_cross_asset_allocation(clock, regime, phase1_only=False)
        ls = " + ".join(f"{x['asset']} {x['weight']*100:.0f}%↑" for x in r["allocation"]["long"])  or "—"
        ss = " + ".join(f"{x['asset']} {x['weight']*100:.0f}%↓" for x in r["allocation"]["short"]) or "—"
        print(f"{label:30s}  {r['position_multiplier']:.1f}    {ls:40s}  {ss:25s}  {r['allocation']['cash']*100:.0f}%")

    print("\n" + "=" * 80)
    print("当前完整输出（STAGFLATION_LITE，Phase 2 开启）")
    print("=" * 80)
    r = calc_cross_asset_allocation("STAGFLATION_LITE", "STRONG_BEAR", phase1_only=False)
    print(format_screen1_a_summary(r))

    print("\n" + "=" * 80)
    print("当前完整输出（STAGFLATION_LITE，Phase 1 限制）")
    print("=" * 80)
    r1 = calc_cross_asset_allocation("STAGFLATION_LITE", "STRONG_BEAR", phase1_only=True)
    print(format_screen1_a_summary(r1))

    print("\n" + "=" * 80)
    print("资产相关性矩阵（最佳对冲对）")
    print("=" * 80)
    pairs = [
        ("XLP",  "ETH"),
        ("XLE",  "SPY"),
        ("SOL",  "BTC"),
        ("SPY",  "GOLD"),
        ("BTC",  "GOLD"),
    ]
    for a, b in pairs:
        corr = get_correlation(a, b)
        bar = "+" * int(abs(corr) * 20) if corr >= 0 else "-" * int(abs(corr) * 20)
        print(f"  {a:5s} vs {b:5s}: {corr:+.2f}  [{bar}]")
