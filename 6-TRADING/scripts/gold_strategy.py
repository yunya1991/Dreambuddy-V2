#!/usr/bin/env python3
"""
黄金（XAUUSD）交易策略信号计算器 v0.1
数据来源: Yahoo Finance（免费，无需API key）
输出: 七维牛熊评分 + 入场信号 + 仓位建议

独立运行: python3 scripts/gold_strategy.py
"""
import json, sys, io, argparse, os
from datetime import datetime, timezone, timedelta

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# ─── V9 马丁规则（黄金适配） ──────────────────────────────────
VOL_MULT = 0.8                # 黄金标准（vs BTC 1.0）
ADD_INTERVAL = 0.08 * VOL_MULT   # 6.4% 加仓间隔
TAKE_PROFIT = 0.04 * VOL_MULT    # 3.2% 止盈
MAX_ADDITIONS = 3               # V9 基线
SCORE_BULL_MIN = 60             # 牛市最低分（满分100）
SCORE_BEAR_MAX = -40            # 熊市最高分（满分-100）

# ─── 模拟数据（降级模式：当API不可用时使用） ──────────────────
MOCK_PRICES = {
    "close": [4210 + i * 2 for i in range(30)],  # 30日模拟收盘
    "ma200": 4050,   # MA200 位置
    "rsi_daily": 48,  # RSI 日线
    "dxy": 97.5,      # 美元指数
    "real_rate_10y": 0.8,  # 10Y 实际利率 %
    "gvz": 22,        # 黄金波动率指数
    "central_bank_buying": "positive",  # 央行购金趋势
    "inflation_be": 2.4,  # 盈亏平衡通胀率 %
}

def compute_gold_score(data: dict) -> dict:
    """七维牛熊评分引擎"""
    scores = {}
    details = []
    total = 0
    
    # 1. MA200 方向判定（权重30%）
    close_prices = data.get("close", MOCK_PRICES["close"])
    ma200 = data.get("ma200", MOCK_PRICES["ma200"])
    
    # 3日确认
    above = sum(1 for c in close_prices[-3:] if c > ma200)
    ma200_signal = 30 if above >= 2 else -30
    scores["ma200"] = ma200_signal
    details.append(f"MA200({'BULL' if above >= 2 else 'BEAR'}): {ma200_signal:+d}分 ({above}/3日确认)")
    total += ma200_signal
    
    # 2. RSI 月线（权重15%）
    rsi = data.get("rsi_daily", MOCK_PRICES["rsi_daily"])
    if rsi < 30:
        rsi_signal = 15  # 超卖 = 做多
    elif rsi > 70:
        rsi_signal = -15  # 超买 = 做空
    elif 40 <= rsi <= 55:
        rsi_signal = 10   # 中性偏多（趋势中回撤买入）
    else:
        rsi_signal = 0
    scores["rsi"] = rsi_signal
    details.append(f"RSI({rsi:.1f}): {rsi_signal:+d}分")
    total += rsi_signal
    
    # 3. 美元指数 DXY（权重15%）
    dxy = data.get("dxy", MOCK_PRICES["dxy"])
    if dxy < 98:
        dxy_signal = 15    # 弱美元 = 利好黄金
    elif dxy > 105:
        dxy_signal = -15   # 强美元 = 利空黄金
    else:
        dxy_signal = 5     # 中性略多
    scores["dxy"] = dxy_signal
    details.append(f"DXY({dxy:.1f}): {dxy_signal:+d}分")
    total += dxy_signal
    
    # 4. 实际利率（权重15%）
    real_rate = data.get("real_rate_10y", MOCK_PRICES["real_rate_10y"])
    if real_rate < 0.5:
        rate_signal = 15    # 低实际利率 = 利好黄金
    elif real_rate > 2.0:
        rate_signal = -15   # 高实际利率 = 利空
    else:
        rate_signal = 5
    scores["real_rate"] = rate_signal
    details.append(f"RealRate({real_rate:.1f}%): {rate_signal:+d}分")
    total += rate_signal
    
    # 5. 央行购金（权重10%）
    cb = data.get("central_bank_buying", MOCK_PRICES["central_bank_buying"])
    cb_signal = 10 if cb == "positive" else (-10 if cb == "negative" else 0)
    scores["central_bank"] = cb_signal
    details.append(f"央行购金({cb}): {cb_signal:+d}分")
    total += cb_signal
    
    # 6. 通胀预期（权重10%）
    be = data.get("inflation_be", MOCK_PRICES["inflation_be"])
    if be > 2.5:
        be_signal = 10     # 高通胀预期 = 利好黄金
    elif be < 1.5:
        be_signal = -10    # 低通胀预期 = 利空
    else:
        be_signal = 5
    scores["inflation_be"] = be_signal
    details.append(f"通胀BE({be:.1f}%): {be_signal:+d}分")
    total += be_signal
    
    # 7. GVZ 波动率（权重5%）
    gvz = data.get("gvz", MOCK_PRICES["gvz"])
    if gvz > 30:
        gvz_signal = 5     # 恐慌 = 买入机会
    else:
        gvz_signal = 2
    scores["gvz"] = gvz_signal
    details.append(f"GVZ({gvz}): {gvz_signal:+d}分")
    total += gvz_signal
    
    return {
        "total_score": total,
        "details": details,
        "direction": "bull" if total >= SCORE_BULL_MIN else ("bear" if total <= SCORE_BEAR_MAX else "neutral"),
        "confidence": abs(total) / 100,
    }

def entry_decision(score_result, data) -> dict:
    """入场决策引擎"""
    direction = score_result["direction"]
    rsi = data.get("rsi_daily", MOCK_PRICES["rsi_daily"])
    
    if direction == "bull":
        if 40 <= rsi <= 55:
            return {
                "action": "long",
                "position": 1.0,        # 标准仓位
                "take_profit": TAKE_PROFIT,
                "stop_loss": ADD_INTERVAL * (-1.5),  # 1.5倍加仓间隔
                "reason": f"牛市确认 + RSI回撤至{rsi:.0f}（买入区）",
            }
    elif direction == "bear":
        if 55 <= rsi <= 70:
            return {
                "action": "short",
                "position": 0.5,        # 半仓（熊市保守）
                "take_profit": TAKE_PROFIT,
                "stop_loss": ADD_INTERVAL * (-1.5),
                "reason": f"熊市确认 + RSI反弹至{rsi:.0f}（卖出区）",
            }
    
    return {
        "action": "hold",
        "position": 0,
        "take_profit": 0,
        "stop_loss": 0,
        "reason": "无入场信号（等待方向确认或RSI触发点）",
    }

def main():
    parser = argparse.ArgumentParser(description="黄金策略信号计算器")
    parser.add_argument("--mode", choices=["full", "score", "entry"], default="full",
                       help="full: 评分+入场, score: 仅评分, entry: 仅入场")
    parser.add_argument("--data", type=str, default=None,
                       help="JSON格式的数据覆盖文件路径")
    args = parser.parse_args()
    
    data = MOCK_PRICES.copy()
    if args.data:
        with open(args.data) as f:
            data.update(json.load(f))
    
    print(f"╔═══ 黄金（XAUUSD）策略信号 ═══╗")
    print(f"║ 时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"║ 模式: {args.mode}")
    print(f"║ V9: vol_mult={VOL_MULT}, 间隔={ADD_INTERVAL*100:.1f}%, 止盈={TAKE_PROFIT*100:.1f}%")
    print(f"╚══════════════════════════════╝")
    print()
    
    if args.mode in ("full", "score"):
        print("── 七维评分 ──")
        result = compute_gold_score(data)
        for d in result["details"]:
            print(f"  {d}")
        print(f"  ──────")
        print(f"  总分: {result['total_score']:+d} / 100")
        print(f"  方向: {result['direction'].upper()}")
        print(f"  置信度: {result['confidence']:.0%}")
        print()
    
    if args.mode in ("full", "entry"):
        score_result = compute_gold_score(data) if args.mode == "full" else data
        decision = entry_decision(score_result, data)
        print("── 入场决策 ──")
        print(f"  动作: {decision['action'].upper()}")
        print(f"  仓位: {decision['position']:.0%} ({'标准' if decision['position'] >= 1 else '半仓'})")
        print(f"  止盈: {decision['take_profit']*100:.1f}%")
        print(f"  止损: {abs(decision['stop_loss'])*100:.1f}%")
        print(f"  原因: {decision['reason']}")
        print()
    
    print("── 状态文件 ──")
    output = {
        "timestamp": datetime.now().isoformat(),
        "config": {"vol_mult": VOL_MULT, "add_interval": ADD_INTERVAL, "take_profit": TAKE_PROFIT},
        "score": result if args.mode in ("full", "score") else None,
        "decision": decision if args.mode in ("full", "entry") else None,
        "data_mode": "mock" if args.data is None else "custom",
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
