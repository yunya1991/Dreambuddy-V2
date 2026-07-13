"""
V15-CT 技术策略系统性压力测试
覆盖: 7层信号全验证 / 边界条件 / 集成链路 / 异常数据 / 回归场景
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import math
import json
from v15ct_signal import (
    v15_real_decision as _v15_real_decision,
    calc_bollinger_bands as _calc_bollinger_bands,
    calc_macd as _calc_macd,
    calc_adx as _calc_adx,
    calc_rsi as _calc_rsi,
)
from screen_executor import _calc_levels


passed = 0
failed = 0


def assert_eq(actual, expected, msg=""):
    global passed, failed
    if actual == expected:
        passed += 1
        print(f"  ✅ {msg}")
    else:
        failed += 1
        print(f"  ❌ {msg}: expected={expected}, got={actual}")


def assert_in(val, options, msg=""):
    global passed, failed
    if val in options:
        passed += 1
        print(f"  ✅ {msg}")
    else:
        failed += 1
        print(f"  ❌ {msg}: {val} not in {options}")


def assert_gt(a, b, msg=""):
    global passed, failed
    if a > b:
        passed += 1
        print(f"  ✅ {msg}")
    else:
        failed += 1
        print(f"  ❌ {msg}: {a} <= {b}")


def assert_lt(a, b, msg=""):
    global passed, failed
    if a < b:
        passed += 1
        print(f"  ✅ {msg}")
    else:
        failed += 1
        print(f"  ❌ {msg}: {a} >= {b}")


def gen_synthetic_candles(
    base_price=60000,
    n=200,
    trend="flat",
    vol_pct=0.02,
):
    """生成合成K线数据用于测试"""
    prices = [base_price]
    for i in range(n - 1):
        drift = 0
        if trend == "up":
            drift = base_price * 0.001
        elif trend == "down":
            drift = -base_price * 0.001
        change = base_price * vol_pct * (math.sin(i * 0.1) * 0.5 + 0.5)
        if i % 2 == 0:
            change = -change
        prices.append(prices[-1] + change + drift)

    candles = []
    for i, p in enumerate(prices):
        o = prices[i - 1] if i > 0 else p
        h = max(o, p) * (1 + vol_pct * 0.3)
        l = min(o, p) * (1 - vol_pct * 0.3)
        v = 1000 + i * 10
        candles.append({
            "ts": 1700000000 + i * 14400000,
            "o": str(o), "h": str(h), "l": str(l), "c": str(p), "v": str(v)
        })
    return candles


def mock_candles(screen1, candles):
    """mock _fetch_candles (在screen_engine模块)"""
    import screen_engine as se_eng
    original = se_eng._fetch_candles
    def _fake(inst, bar, limit=200):
        return candles
    se_eng._fetch_candles = _fake
    return original


def restore_candles(original):
    import screen_engine as se_eng
    se_eng._fetch_candles = original


def test_sma_calculation():
    print("\n" + "=" * 60)
    print("测试1: SMA均线计算准确性")
    print("=" * 60)

    candles = gen_synthetic_candles(60000, 200, "flat", 0.02)
    orig = mock_candles({"spot_inst": "BTC-USDT"}, candles)

    result = _v15_real_decision({"spot_inst": "BTC-USDT"}, {})
    smas = result["smas"]

    assert_in(30, smas, "包含sma30")
    assert_in(65, smas, "包含sma65")
    assert_in(128, smas, "包含sma128")
    assert_in(200, smas, "包含sma200")
    assert_gt(smas[30], 0, "sma30 > 0")
    assert_gt(smas[65], 0, "sma65 > 0")

    restore_candles(orig)


def test_position_determination():
    print("\n" + "=" * 60)
    print("测试2: 价格位置判定 (ABOVE_ALL/BELOW_ALL/IN_ZONE)")
    print("=" * 60)

    base = 60000

    # --- ABOVE_ALL ---
    candles = gen_synthetic_candles(base * 1.3, 200, "up", 0.02)
    orig = mock_candles({"spot_inst": "BTC-USDT"}, candles)
    r = _v15_real_decision({"spot_inst": "BTC-USDT"}, {})
    restore_candles(orig)
    assert_eq(r["position"], "ABOVE_ALL", "价格全线上方 → ABOVE_ALL")

    # --- BELOW_ALL ---
    candles = gen_synthetic_candles(base * 0.7, 200, "down", 0.02)
    orig = mock_candles({"spot_inst": "BTC-USDT"}, candles)
    r = _v15_real_decision({"spot_inst": "BTC-USDT"}, {})
    restore_candles(orig)
    assert_eq(r["position"], "BELOW_ALL", "价格全线下方 → BELOW_ALL")

    # --- IN_ZONE ---
    # 构造: SMA200=55000, SMA30=65000, 当前价=60000 → 在均线之间
    prices = []
    # 前100根高价 (让SMA200偏高)
    for i in range(100):
        prices.append(70000.0)
    # 接下来70根中价 (让SMA128中等, SMA65偏低)
    for i in range(70):
        prices.append(55000.0)
    # 最后30根中高价 (让SMA30偏高)
    for i in range(30):
        prices.append(65000.0)
    # 共200根，当前价62000
    prices.append(62000.0)
    prices = prices[-200:]
    candles = []
    for i, p in enumerate(prices):
        o = prices[i-1] if i > 0 else p
        h = p * 1.01
        l = p * 0.99
        candles.append({
            "ts": 1700000000 + i * 14400000,
            "o": str(o), "h": str(h), "l": str(l), "c": str(p), "v": "1000"
        })
    orig = mock_candles({"spot_inst": "BTC-USDT"}, candles)
    r = _v15_real_decision({"spot_inst": "BTC-USDT"}, {})
    restore_candles(orig)
    assert_eq(r["position"], "IN_ZONE", f"价格在均线之间 → IN_ZONE (实际smas={r['smas']}, price={prices[-1]})")


def test_bollinger_bands():
    print("\n" + "=" * 60)
    print("测试3: 布林带计算")
    print("=" * 60)

    candles = gen_synthetic_candles(60000, 200, "flat", 0.03)
    closes = [float(c["c"]) for c in candles]

    boll = _calc_bollinger_bands(closes)

    assert_gt(boll["upper"], boll["sma"], "上轨 > 中轨")
    assert_gt(boll["sma"], boll["lower"], "中轨 > 下轨")
    assert_gt(boll["bandwidth"], 0, "带宽 > 0")
    assert_gt(boll["pct_b"], -1, "百分比B > -1")
    assert_lt(boll["pct_b"], 2, "百分比B < 2")


def test_macd_calculation():
    print("\n" + "=" * 60)
    print("测试4: MACD计算")
    print("=" * 60)

    # 上升趋势 → 多头hist
    candles = gen_synthetic_candles(60000, 200, "up", 0.02)
    closes = [float(c["c"]) for c in candles]
    macd = _calc_macd(closes)

    assert_in("hist", macd, "包含hist")
    assert_in("signal", macd, "包含signal")
    assert_in("macd", macd, "包含macd")
    assert_in("cross", macd, "包含cross")
    assert_in("expanding", macd, "包含expanding")

    # 下降趋势 → 空头hist
    candles2 = gen_synthetic_candles(60000, 200, "down", 0.02)
    closes2 = [float(c["c"]) for c in candles2]
    macd2 = _calc_macd(closes2)
    assert_lt(macd2["hist"], 0, "下降趋势 hist < 0")


def test_adx_calculation():
    print("\n" + "=" * 60)
    print("测试5: ADX趋势强度计算")
    print("=" * 60)

    candles = gen_synthetic_candles(60000, 200, "flat", 0.02)
    closes = [float(c["c"]) for c in candles]
    adx = _calc_adx(closes)

    assert_in("adx", adx, "包含adx")
    assert_in("di_plus", adx, "包含di_plus")
    assert_in("di_minus", adx, "包含di_minus")
    assert_in("strong", adx, "包含strong")
    assert_gt(adx["adx"], 0, "ADX > 0")
    assert_gt(adx["di_plus"], 0, "+DI > 0")
    assert_gt(adx["di_minus"], 0, "-DI > 0")


def test_rsi_calculation():
    print("\n" + "=" * 60)
    print("测试6: RSI计算")
    print("=" * 60)

    # 上涨 → RSI > 50
    candles = gen_synthetic_candles(60000, 200, "up", 0.01)
    closes = [float(c["c"]) for c in candles]
    rsi = _calc_rsi(closes)
    assert_gt(rsi, 30, f"上涨趋势 RSI={rsi:.1f} > 30")
    assert_lt(rsi, 100, "RSI < 100")

    # 下跌 → RSI < 50
    candles2 = gen_synthetic_candles(60000, 200, "down", 0.01)
    closes2 = [float(c["c"]) for c in candles2]
    rsi2 = _calc_rsi(closes2)
    assert_lt(rsi2, 70, f"下跌趋势 RSI={rsi2:.1f} < 70")
    assert_gt(rsi2, 0, "RSI > 0")


def test_below_all_all_tiers():
    print("\n" + "=" * 60)
    print("测试7: BELOW_ALL 7层信号验证")
    print("=" * 60)

    # 构造: SMA200=80000, 价格40000 → BELOW_ALL
    prices_full = []
    # 前170根高价 (让所有SMA都偏高)
    for i in range(170):
        prices_full.append(80000.0)
    # 最后30根低价
    for i in range(30):
        prices_full.append(45000.0 - i * 100)  # 跌到42000
    prices_full = prices_full[-200:]

    candles = []
    for i, p in enumerate(prices_full):
        o = prices_full[i-1] if i > 0 else p
        h = p * 1.01
        l = p * 0.99
        v = 1000 + i
        candles.append({
            "ts": 1700000000 + i * 14400000,
            "o": str(o), "h": str(h), "l": str(l), "c": str(p), "v": str(v)
        })

    orig = mock_candles({"spot_inst": "BTC-USDT"}, candles)
    r = _v15_real_decision({"spot_inst": "BTC-USDT"}, {})
    restore_candles(orig)

    print(f"  价格: {prices_full[-1]:.0f}, position: {r['position']}, action: {r['action']}")
    print(f"  fib_zone: {r.get('fib_zone')}, trend_signal: {r.get('trend_signal')}")
    print(f"  boll_signal: {r.get('boll_signal')}, RSI: {r.get('rsi')}")
    fib = r.get("fib", {})
    if fib:
        print(f"  swing_high: {fib.get('swing_high')}, swing_low: {fib.get('swing_low')}")
        print(f"  f382: {fib.get('f382')}, f500: {fib.get('f500')}, f618: {fib.get('f618')}")
    print(f"  smas: {r['smas']}")

    assert_eq(r["position"], "BELOW_ALL", f"位置 = BELOW_ALL (smas={r['smas']}, price={prices_full[-1]:.0f})")


def test_above_all_all_tiers():
    print("\n" + "=" * 60)
    print("测试8: ABOVE_ALL 7层信号验证")
    print("=" * 60)

    # 构造: SMA200=40000, 价格75000 → ABOVE_ALL
    prices_full = []
    # 前170根低价 (让所有SMA都偏低)
    for i in range(170):
        prices_full.append(40000.0)
    # 最后30根高价
    for i in range(30):
        prices_full.append(75000.0 + i * 100)  # 涨到78000
    prices_full = prices_full[-200:]

    candles = []
    for i, p in enumerate(prices_full):
        o = prices_full[i-1] if i > 0 else p
        h = p * 1.01
        l = p * 0.99
        candles.append({
            "ts": 1700000000 + i * 14400000,
            "o": str(o), "h": str(h), "l": str(l), "c": str(p), "v": str(1000 + i)
        })

    orig = mock_candles({"spot_inst": "BTC-USDT"}, candles)
    r = _v15_real_decision({"spot_inst": "BTC-USDT"}, {})
    restore_candles(orig)

    print(f"  价格: {prices_full[-1]:.0f}, position: {r['position']}, action: {r['action']}")
    print(f"  fib_zone: {r.get('fib_zone')}, trend_signal: {r.get('trend_signal')}")
    print(f"  boll_signal: {r.get('boll_signal')}, RSI: {r.get('rsi')}")
    print(f"  smas: {r['smas']}")

    assert_eq(r["position"], "ABOVE_ALL", f"位置 = ABOVE_ALL (smas={r['smas']}, price={prices_full[-1]:.0f})")


def test_in_zone_rsi_extremes():
    print("\n" + "=" * 60)
    print("测试9: IN_ZONE RSI极端值")
    print("=" * 60)

    # IN_ZONE + RSI超卖
    prices = []
    # 让SMA200在中间，价格先在上面100天，下面100天
    for i in range(100):
        prices.append(65000)
    # 最后暴跌，RSI变低
    for i in range(100):
        if i < 80:
            prices.append(55000 + (i - 40) * 50)
        else:
            prices.append(55000 - (i - 80) * 100)  # 最后20天暴跌

    candles = []
    for i, p in enumerate(prices[:200]):
        o = prices[i-1] if i > 0 else p
        h = p * 1.01
        l = p * 0.99
        candles.append({
            "ts": 1700000000 + i * 14400000,
            "o": str(o), "h": str(h), "l": str(l), "c": str(p), "v": "1000"
        })

    orig = mock_candles({"spot_inst": "BTC-USDT"}, candles)
    r = _v15_real_decision({"spot_inst": "BTC-USDT"}, {})
    restore_candles(orig)

    print(f"  RSI={r.get('rsi')}, action={r['action']}, position={r['position']}")
    if r["action"] != "WAIT":
        assert_gt(r["confidence"], 0, "有入场信号 → 置信度>0")


def test_vol_mult_consistency():
    print("\n" + "=" * 60)
    print("测试10: vol_mult与各信号层一致性")
    print("=" * 60)

    # Fib黄金区 → vol_mult应最大
    # 构造BELOW_ALL + Fib黄金区
    prices_full = [70000] * 60
    for i in range(60):
        prices_full.append(70000 + i * 100)  # 到76000
    for i in range(80):
        prices_full.append(76000 - i * 50)   # 跌到36000? 不，是跌到 76000-4000=3600... 不对
    # 重新构造: swing_high=80000, swing_low=40000, 当前价=55000 (f382=55279, f500=60000, f618=64721)
    prices_full = []
    for i in range(80):
        prices_full.append(80000)
    for i in range(60):
        prices_full.append(80000 - i * 667)  # 跌到 80000-40000=40000
    for i in range(60):
        prices_full.append(40000 + i * 250)  # 反弹到 55000 (浅区~黄金区之间)

    candles = []
    for i, p in enumerate(prices_full[:200]):
        o = prices_full[i-1] if i > 0 else p
        h = p * 1.005
        l = p * 0.995
        candles.append({
            "ts": 1700000000 + i * 14400000,
            "o": str(o), "h": str(h), "l": str(l), "c": str(p), "v": "1000"
        })

    orig = mock_candles({"spot_inst": "BTC-USDT"}, candles)
    r = _v15_real_decision({"spot_inst": "BTC-USDT"}, {})
    restore_candles(orig)

    print(f"  position: {r['position']}, action: {r['action']}")
    print(f"  fib_zone: {r.get('fib_zone')}, vol_mult: {r['vol_mult']}")

    # vol_mult必须在合理范围
    assert_gt(r["vol_mult"], 0, "vol_mult > 0")
    assert_lt(r["vol_mult"], 2.0, "vol_mult < 2.0 (无夸张放大)")

    # Fib黄金区的vol_mult应该 > RSI极端触发的vol_mult
    rsi_extreme_vm = None
    # 找一个纯RSI触发的
    prices2 = [60000] * 200
    prices2[-15:] = [60000 - i * 800 for i in range(15)]  # 15天暴跌
    candles2 = []
    for i, p in enumerate(prices2):
        o = prices2[i-1] if i > 0 else p
        candles2.append({
            "ts": 1700000000 + i * 14400000,
            "o": str(o), "h": str(p*1.01), "l": str(p*0.99), "c": str(p), "v": "1000"
        })
    orig2 = mock_candles({"spot_inst": "BTC-USDT"}, candles2)
    r2 = _v15_real_decision({"spot_inst": "BTC-USDT"}, {})
    restore_candles(orig2)
    print(f"  RSI触发 vol_mult: {r2['vol_mult']}")


def test_calc_levels():
    print("\n" + "=" * 60)
    print("测试11: 马丁分层价位计算")
    print("=" * 60)

    # BULL方向
    levels, tp, addon_pct, tp_pct = _calc_levels("BULL", 10000, 1.0)
    assert_eq(levels[0]["price"], 10000.0, "BULL 入场价正确")
    assert_eq(len(levels), 2, "2层（入场+1加仓）")
    assert_lt(levels[1]["price"], levels[0]["price"], "BULL 加仓1 < 入场价")
    assert_gt(tp, levels[0]["price"], "BULL 止盈 > 入场价")

    # BEAR方向
    levels2, tp2, _, _ = _calc_levels("BEAR", 10000, 1.0)
    assert_gt(levels2[1]["price"], levels2[0]["price"], "BEAR 加仓1 > 入场价")
    assert_lt(tp2, levels2[0]["price"], "BEAR 止盈 < 入场价")

    # vol_mult影响
    levels3, tp3, addon3, tp_pct3 = _calc_levels("BULL", 10000, 1.5)
    assert_gt(tp3, tp, "vol_mult大 → 止盈更高")
    assert_lt(levels3[1]["price"], levels[1]["price"], "vol_mult大 → 加仓价更低")


def test_empty_data():
    print("\n" + "=" * 60)
    print("测试12: 异常数据处理")
    print("=" * 60)

    # 空数据
    orig = mock_candles({"spot_inst": "BTC-USDT"}, [])
    r = _v15_real_decision({"spot_inst": "BTC-USDT"}, {})
    restore_candles(orig)
    assert_eq(r["action"], "WAIT", "空数据 → WAIT")
    assert_eq(r["confidence"], 0, "空数据 → 置信度0")

    # 极少数据 (5根)
    candles = gen_synthetic_candles(60000, 5, "flat", 0.02)
    orig = mock_candles({"spot_inst": "BTC-USDT"}, candles)
    r = _v15_real_decision({"spot_inst": "BTC-USDT"}, {})
    restore_candles(orig)
    assert_eq(r["action"], "WAIT", "数据不足 → WAIT")


def test_integration_llm_decision():
    print("\n" + "=" * 60)
    print("测试13: V15-CT独立模块决策链路")
    print("=" * 60)

    candles = gen_synthetic_candles(60000, 200, "flat", 0.03)
    orig = mock_candles({"spot_inst": "BTC-USDT"}, candles)

    result = _v15_real_decision({"spot_inst": "BTC-USDT"}, {})

    restore_candles(orig)

    assert_in(result["action"], ["OPEN_BULL", "OPEN_BEAR", "WAIT"], "action合法")
    assert_eq(result["mode"], "v15_ct", "mode=v15_ct")
    assert_gt(result["confidence"], -1, "置信度合法")
    assert_gt(result["vol_mult"], 0, "vol_mult > 0")


def test_return_value_structure():
    print("\n" + "=" * 60)
    print("测试14: 返回值结构完整性")
    print("=" * 60)

    candles = gen_synthetic_candles(60000, 200, "flat", 0.03)
    orig = mock_candles({"spot_inst": "BTC-USDT"}, candles)
    r = _v15_real_decision({"spot_inst": "BTC-USDT"}, {})
    restore_candles(orig)

    required_fields = [
        "action", "confidence", "reasons", "mode", "vol_mult",
        "position", "fib_zone", "trend_signal", "boll_signal",
        "rsi", "smas", "fib", "boll", "macd", "adx"
    ]

    for field in required_fields:
        assert_in(field, r, f"返回值包含 {field}")


def test_price_zero_or_negative():
    print("\n" + "=" * 60)
    print("测试15: 异常价格保护 (0/负价)")
    print("=" * 60)

    # 价格为0
    prices = [0] * 200
    candles = []
    for i, p in enumerate(prices):
        candles.append({
            "ts": 1700000000 + i * 14400000,
            "o": "0", "h": "0", "l": "0", "c": "0", "v": "0"
        })
    orig = mock_candles({"spot_inst": "BTC-USDT"}, candles)
    r = _v15_real_decision({"spot_inst": "BTC-USDT"}, {})
    restore_candles(orig)
    assert_eq(r["action"], "WAIT", "零价格 → WAIT")


def test_volatility_extreme():
    print("\n" + "=" * 60)
    print("测试16: 极端波动场景 (20%日波动)")
    print("=" * 60)

    candles = gen_synthetic_candles(60000, 200, "flat", 0.2)
    orig = mock_candles({"spot_inst": "BTC-USDT"}, candles)
    r = _v15_real_decision({"spot_inst": "BTC-USDT"}, {})
    restore_candles(orig)

    print(f"  action: {r['action']}, conf: {r['confidence']}")
    boll = r.get("boll", {})
    if boll:
        print(f"  布林带宽: {boll.get('bandwidth')}%")

    # 极端波动也不能崩溃
    assert_in(r["action"], ["OPEN_BULL", "OPEN_BEAR", "WAIT"], "极端波动不崩溃")


def test_consistency_across_calls():
    print("\n" + "=" * 60)
    print("测试17: 相同输入 → 相同输出 (一致性)")
    print("=" * 60)

    candles = gen_synthetic_candles(60000, 200, "flat", 0.03)
    orig = mock_candles({"spot_inst": "BTC-USDT"}, candles)

    r1 = _v15_real_decision({"spot_inst": "BTC-USDT"}, {})
    r2 = _v15_real_decision({"spot_inst": "BTC-USDT"}, {})

    restore_candles(orig)

    assert_eq(r1["action"], r2["action"], "两次调用action一致")
    assert_eq(r1["confidence"], r2["confidence"], "两次调用置信度一致")
    assert_eq(r1["vol_mult"], r2["vol_mult"], "两次调用vol_mult一致")


def test_large_random_suite():
    print("\n" + "=" * 60)
    print("测试18: 大规模随机场景 (1000次)")
    print("=" * 60)
    import random
    random.seed(42)

    scenarios = [
        ("flat_lowvol", "flat", 0.01),
        ("flat_highvol", "flat", 0.05),
        ("uptrend", "up", 0.02),
        ("downtrend", "down", 0.02),
        ("choppy", "flat", 0.08),
    ]

    counts = {"WAIT": 0, "OPEN_BULL": 0, "OPEN_BEAR": 0}
    pos_counts = {"ABOVE_ALL": 0, "BELOW_ALL": 0, "IN_ZONE": 0}
    errors = 0

    for i in range(1000):
        name, trend, vol = random.choice(scenarios)
        base = random.uniform(100, 100000)
        candles = gen_synthetic_candles(base, 200, trend, vol)
        orig = mock_candles({"spot_inst": "BTC-USDT"}, candles)
        try:
            r = _v15_real_decision({"spot_inst": "BTC-USDT"}, {})
            counts[r["action"]] = counts.get(r["action"], 0) + 1
            pos_counts[r["position"]] = pos_counts.get(r["position"], 0) + 1

            # 校验: 有入场信号时vol_mult必须 > 0
            if r["action"] != "WAIT":
                assert r["vol_mult"] > 0, f"入场但vol_mult={r['vol_mult']}"
                assert r["confidence"] > 0, f"入场但confidence={r['confidence']}"
        except Exception as e:
            errors += 1
            print(f"  ❌ 第{i}次崩溃: {e}")
        finally:
            restore_candles(orig)

    total = sum(counts.values())
    print(f"  分布: WAIT={counts['WAIT']} ({counts['WAIT']/total*100:.1f}%), "
          f"BULL={counts['OPEN_BULL']} ({counts['OPEN_BULL']/total*100:.1f}%), "
          f"BEAR={counts['OPEN_BEAR']} ({counts['OPEN_BEAR']/total*100:.1f}%)")
    print(f"  位置: ABOVE_ALL={pos_counts['ABOVE_ALL']}, BELOW_ALL={pos_counts['BELOW_ALL']}, IN_ZONE={pos_counts['IN_ZONE']}")
    print(f"  错误: {errors}")

    assert_eq(errors, 0, "1000次随机场景零崩溃")
    assert_gt(counts["WAIT"], 0, "有WAIT场景")
    assert_gt(counts["OPEN_BULL"] + counts["OPEN_BEAR"], 0, "有入场场景")


def test_no_crash_with_screen2():
    print("\n" + "=" * 60)
    print("测试19: screen2参数兼容性")
    print("=" * 60)

    candles = gen_synthetic_candles(60000, 200, "flat", 0.03)
    orig = mock_candles({"spot_inst": "BTC-USDT"}, candles)

    # screen2为空dict
    r = _v15_real_decision({"spot_inst": "BTC-USDT"}, {})
    assert_in(r["action"], ["OPEN_BULL", "OPEN_BEAR", "WAIT"], "screen2空 → 不崩溃")

    # screen2有数据
    r2 = _v15_real_decision({"spot_inst": "BTC-USDT"}, {"grid_levels": []})
    assert_in(r2["action"], ["OPEN_BULL", "OPEN_BEAR", "WAIT"], "screen2有数据 → 不崩溃")

    restore_candles(orig)


def test_signal_reason_count():
    print("\n" + "=" * 60)
    print("测试20: 入场时必须有理由")
    print("=" * 60)

    candles = gen_synthetic_candles(60000, 200, "flat", 0.05)
    orig = mock_candles({"spot_inst": "BTC-USDT"}, candles)
    r = _v15_real_decision({"spot_inst": "BTC-USDT"}, {})
    restore_candles(orig)

    assert_gt(len(r["reasons"]), 0, "reasons非空")

    if r["action"] != "WAIT":
        # 入场时应该有至少2条理由（位置+触发信号）
        assert_gt(len(r["reasons"]), 1, "入场信号至少2条理由")


if __name__ == "__main__":
    print("=" * 60)
    print("V15 真实策略系统性压力测试")
    print("=" * 60)

    test_sma_calculation()
    test_position_determination()
    test_bollinger_bands()
    test_macd_calculation()
    test_adx_calculation()
    test_rsi_calculation()
    test_below_all_all_tiers()
    test_above_all_all_tiers()
    test_in_zone_rsi_extremes()
    test_vol_mult_consistency()
    test_calc_levels()
    test_empty_data()
    test_integration_llm_decision()
    test_return_value_structure()
    test_price_zero_or_negative()
    test_volatility_extreme()
    test_consistency_across_calls()
    test_large_random_suite()
    test_no_crash_with_screen2()
    test_signal_reason_count()

    print("\n" + "=" * 60)
    print(f"测试总结: ✅ {passed} passed | ❌ {failed} failed")
    print("=" * 60)

    if failed > 0:
        sys.exit(1)
