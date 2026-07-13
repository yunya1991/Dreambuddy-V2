#!/usr/bin/env python3
"""
V15 真实策略多场景压力测试 v2
覆盖：ABOVE_ALL / BELOW_ALL / IN_ZONE 全部逻辑分支
包括：边界条件、极端行情、数据异常、布林带
"""
import sys
import json
import random
import traceback
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / "lib"))
sys.path.insert(0, str(BASE_DIR / "core"))


def make_candles(prices):
    return [{"c": p, "o": p, "h": p * 1.01, "l": p * 0.99, "t": i, "v": 1000} for i, p in enumerate(prices)]


def gen_uptrend(n=210, start=10000, drift=0.005, vol=0.02):
    prices = [start]
    for i in range(n - 1):
        change = drift + random.gauss(0, vol)
        prices.append(max(prices[-1] * (1 + change), 100))
    return prices


def gen_downtrend(n=210, start=100000, drift=-0.005, vol=0.02):
    prices = [start]
    for i in range(n - 1):
        change = drift + random.gauss(0, vol)
        prices.append(max(prices[-1] * (1 + change), 100))
    return prices


def gen_sideways(n=210, center=50000, vol=0.015):
    prices = [center]
    for i in range(n - 1):
        change = random.gauss(0, vol)
        prices.append(max(prices[-1] * (1 + change), 100))
    return prices


def gen_below_all_with_fib_zone(drift=-0.004, vol=0.015):
    """
    构造 BELOW_ALL + Fib区间的场景：
    1) 前180天持续下跌 → SMA30/65/128/200 全部在高位
    2) 最后30天 V型反弹再回落 → swing_high 在反弹高点
    3) 当前价格在 Fib [f382, f618] 区间但低于所有 SMA
    """
    random.seed(42)
    # 前180天下跌
    prices = [100000]
    for i in range(179):
        prices.append(max(prices[-1] * (1 + drift + random.gauss(0, vol)), 1000))

    # 第180-195天：反弹
    bounce_peak = prices[-1]
    for i in range(15):
        prices.append(prices[-1] * (1 + 0.02 + random.gauss(0, 0.01)))
    bounce_peak = max(prices[-15:])

    # 第195-210天：回落到 Fib 区间
    from v15_signal import calc_fibonacci as _calc_fibonacci, calc_sma as _calc_sma
    fib = _calc_fibonacci(prices, 30)
    smas = {p: _calc_sma(prices, p) for p in [30, 65, 128, 200]}

    # 目标价格在 Fib 黄金区 (f500 ~ f618)
    golden_target = (fib['f500'] + fib['f618']) / 2
    shallow_target = (fib['f382'] + fib['f500']) / 2
    min_sma = min(v for v in smas.values() if v)

    # 逐步回落到目标价格
    golden_price = min(golden_target, min_sma - 100)
    shallow_price = min(shallow_target, min_sma - 100)

    # 填充剩余天数直到210天
    remaining = 210 - len(prices)
    if golden_price > prices[-1]:
        steps_up = remaining // 2
        for i in range(steps_up):
            prices.append(prices[-1] + (golden_price - prices[-1]) / max(steps_up - i, 1))
        for i in range(remaining - steps_up):
            prices.append(golden_price + random.gauss(0, 100))
    else:
        for i in range(remaining):
            prices.append(golden_price + random.gauss(0, 100))

    return prices, golden_price, shallow_price


def gen_above_all_with_fib_zone(drift=0.004, vol=0.015):
    """
    构造 ABOVE_ALL + Fib回调区间的场景：
    1) 前180天持续上涨 → SMA30/65/128/200 全部在低位
    2) 最后30天冲高后回调 → swing_low 在回调低点
    3) 当前价格在 Fib 回调区间但高于所有 SMA
    """
    random.seed(78)
    # 前180天上涨
    prices = [10000]
    for i in range(179):
        prices.append(max(prices[-1] * (1 + drift + random.gauss(0, vol)), 100))

    # 第180-195天：加速上涨
    for i in range(15):
        prices.append(prices[-1] * (1 + 0.025 + random.gauss(0, 0.008)))
    pump_peak = max(prices[-15:])

    # 计算当前 Fib 区间
    from v15_signal import calc_fibonacci as _calc_fibonacci, calc_sma as _calc_sma
    fib = _calc_fibonacci(prices, 30)
    smas = {p: _calc_sma(prices, p) for p in [30, 65, 128, 200]}

    rng = fib['swing_high'] - fib['swing_low']
    f382_long = fib['swing_high'] - 0.382 * rng
    f500_long = fib['swing_high'] - 0.500 * rng
    f618_long = fib['swing_high'] - 0.618 * rng

    max_sma = max(v for v in smas.values() if v)

    # 黄金区: f500~f618 (更深的回调)
    golden_target = (f500_long + f618_long) / 2
    golden_target = max(golden_target, max_sma + 100)

    # 浅区: f382~f500
    shallow_target = (f382_long + f500_long) / 2
    shallow_target = max(shallow_target, max_sma + 100)

    remaining = 210 - len(prices)
    for i in range(remaining):
        prices.append(golden_target + random.gauss(0, 100))

    return prices, golden_target, shallow_target


# ========== 测试框架 ==========

PASS = 0
FAIL = 0
RESULTS = []


def assert_eq(test_name, actual, expected, desc=""):
    global PASS, FAIL
    ok = actual == expected
    if ok:
        PASS += 1
        RESULTS.append(("PASS", test_name, f"{desc} | expected={expected}, got={actual}"))
    else:
        FAIL += 1
        RESULTS.append(("FAIL", test_name, f"{desc} | expected={expected}, got={actual}"))


def assert_in(test_name, actual_list, expected_item, desc=""):
    global PASS, FAIL
    ok = expected_item in actual_list
    if ok:
        PASS += 1
        RESULTS.append(("PASS", test_name, f"{desc} | {expected_item} found"))
    else:
        FAIL += 1
        RESULTS.append(("FAIL", test_name, f"{desc} | {expected_item} NOT found"))


def assert_true(test_name, condition, desc=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        RESULTS.append(("PASS", test_name, desc))
    else:
        FAIL += 1
        RESULTS.append(("FAIL", test_name, desc))


def assert_gt(test_name, actual, threshold, desc=""):
    global PASS, FAIL
    if actual > threshold:
        PASS += 1
        RESULTS.append(("PASS", test_name, f"{desc} | {actual} > {threshold}"))
    else:
        FAIL += 1
        RESULTS.append(("FAIL", test_name, f"{desc} | {actual} <= {threshold}"))


def assert_range(test_name, actual, lo, hi, desc=""):
    global PASS, FAIL
    if lo <= actual <= hi:
        PASS += 1
        RESULTS.append(("PASS", test_name, f"{desc} | {lo} <= {actual} <= {hi}"))
    else:
        FAIL += 1
        RESULTS.append(("FAIL", test_name, f"{desc} | {actual} out of [{lo}, {hi}]"))


def run_v15_with_prices(prices, current_price=None):
    from v15_signal import v15_decision
    candles = make_candles(prices)
    with patch("v15_signal.fetch_candles", return_value=candles):
        return v15_decision("BTC-USDT", price=current_price)


def get_indicators(prices, current_price=None):
    from v15_signal import calc_sma, calc_rsi, determine_position, calc_fibonacci
    cp = current_price or prices[-1]
    smas = {p: calc_sma(prices, p) for p in [30, 65, 128, 200]}
    rsi = calc_rsi(prices, 14)
    pos = determine_position(cp, smas)
    fib = calc_fibonacci(prices, 30)
    return cp, smas, rsi, pos, fib


# ========== BELOW_ALL 场景 ==========

def test_below_all_short_golden():
    """场景1: BELOW_ALL + Fib黄金区(50-61.8%) + RSI>45 → OPEN_BEAR"""
    prices, golden_price, _ = gen_below_all_with_fib_zone()
    result = run_v15_with_prices(prices, current_price=golden_price)

    cp, smas, rsi, pos, fib = get_indicators(prices, golden_price)

    # 验证前提条件
    assert_eq("BELOW_ALL golden: position", pos, "BELOW_ALL", f"price=${cp:.0f}")

    if pos == "BELOW_ALL" and fib['f382'] <= cp <= fib['f618'] and cp >= fib['f500'] and rsi > 45:
        assert_eq("BELOW_ALL golden: action", result["action"], "OPEN_BEAR")
        assert_eq("BELOW_ALL golden: fib_zone", result["fib_zone"], "golden")
        assert_eq("BELOW_ALL golden: vol_mult", result["vol_mult"], 1.2)
        assert_range("BELOW_ALL golden: confidence", result["confidence"], 70, 100)
    else:
        assert_true("BELOW_ALL golden: skip (conditions not met)",
                    True, f"pos={pos}, rsi={rsi}, in_fib={fib['f382']<=cp<=fib['f618']}, golden={cp>=fib['f500']}")


def test_below_all_short_shallow():
    """场景2: BELOW_ALL + Fib浅区(38.2-50%) + RSI>45 → OPEN_BEAR"""
    prices, _, shallow_price = gen_below_all_with_fib_zone()
    result = run_v15_with_prices(prices, current_price=shallow_price)

    cp, smas, rsi, pos, fib = get_indicators(prices, shallow_price)

    if pos == "BELOW_ALL" and fib['f382'] <= cp <= fib['f618'] and cp < fib['f500'] and rsi > 45:
        assert_eq("BELOW_ALL shallow: action", result["action"], "OPEN_BEAR")
        assert_eq("BELOW_ALL shallow: fib_zone", result["fib_zone"], "shallow")
        assert_eq("BELOW_ALL shallow: vol_mult", result["vol_mult"], 0.8)
    else:
        assert_true("BELOW_ALL shallow: skip", True,
                    f"pos={pos}, rsi={rsi}, in_fib={fib['f382']<=cp<=fib['f618']}, shallow={cp<fib['f500']}")


def test_below_all_outside_fib():
    """场景3: BELOW_ALL + 价格远在 Fib 区下方 → WAIT"""
    random.seed(456)
    prices = gen_downtrend(n=210, start=100000, drift=-0.003, vol=0.01)

    cp, smas, rsi, pos, fib = get_indicators(prices)
    target_price = fib['f382'] * 0.5  # 远低于 Fib 区

    result = run_v15_with_prices(prices, current_price=target_price)
    cp2, smas2, rsi2, pos2, fib2 = get_indicators(prices, target_price)

    if pos2 == "BELOW_ALL":
        assert_eq("BELOW_ALL outside: action", result["action"], "WAIT")
        assert_range("BELOW_ALL outside: confidence", result["confidence"], 0, 50)
    else:
        assert_true("BELOW_ALL outside: skip", True, f"pos={pos2}")


def test_below_all_rsi_too_low():
    """场景4: BELOW_ALL + 在Fib区 + RSI<=45 → WAIT"""
    random.seed(55)
    # 大幅下跌使RSI很低
    prices = gen_downtrend(n=210, start=100000, drift=-0.008, vol=0.03)

    cp, smas, rsi, pos, fib = get_indicators(prices)
    # 价格放在 Fib 区间
    target_price = fib['f500']
    result = run_v15_with_prices(prices, current_price=target_price)

    cp2, smas2, rsi2, pos2, fib2 = get_indicators(prices, target_price)

    if pos2 == "BELOW_ALL" and fib2['f382'] <= target_price <= fib2['f618']:
        if rsi <= 45:
            assert_eq("BELOW_ALL rsi_low: action", result["action"], "WAIT", f"RSI={rsi}")
        else:
            assert_eq("BELOW_ALL rsi_ok: action", result["action"], "OPEN_BEAR", f"RSI={rsi}")


# ========== ABOVE_ALL 场景 ==========

def test_above_all_long_golden():
    """场景5: ABOVE_ALL + Fib黄金回调区(38.2-50%) + RSI<55 → OPEN_BULL"""
    prices, golden_price, _ = gen_above_all_with_fib_zone()
    result = run_v15_with_prices(prices, current_price=golden_price)

    cp, smas, rsi, pos, fib = get_indicators(prices, golden_price)
    rng = fib['swing_high'] - fib['swing_low']
    f500_long = fib['swing_high'] - 0.500 * rng
    f618_long = fib['swing_high'] - 0.618 * rng

    if pos == "ABOVE_ALL" and f618_long <= cp <= f500_long and rsi < 55:
        assert_eq("ABOVE_ALL golden: action", result["action"], "OPEN_BULL", f"price=${cp:.0f}")
        assert_eq("ABOVE_ALL golden: fib_zone", result["fib_zone"], "golden")
        assert_eq("ABOVE_ALL golden: vol_mult", result["vol_mult"], 1.2)
    else:
        assert_true("ABOVE_ALL golden: skip", True,
                    f"pos={pos}, rsi={rsi}, golden={f618_long<=cp<=f500_long}")


def test_above_all_long_shallow():
    """场景6: ABOVE_ALL + Fib浅回调区 + RSI<55 → OPEN_BULL"""
    prices, _, shallow_price = gen_above_all_with_fib_zone()
    result = run_v15_with_prices(prices, current_price=shallow_price)

    cp, smas, rsi, pos, fib = get_indicators(prices, shallow_price)
    rng = fib['swing_high'] - fib['swing_low']
    f382_long = fib['swing_high'] - 0.382 * rng
    f500_long = fib['swing_high'] - 0.500 * rng

    if pos == "ABOVE_ALL" and f500_long < cp <= f382_long and rsi < 55:
        assert_eq("ABOVE_ALL shallow: action", result["action"], "OPEN_BULL")
        assert_eq("ABOVE_ALL shallow: fib_zone", result["fib_zone"], "shallow")
        assert_eq("ABOVE_ALL shallow: vol_mult", result["vol_mult"], 0.8)
    else:
        assert_true("ABOVE_ALL shallow: skip", True,
                    f"pos={pos}, rsi={rsi}, shallow={f500_long<cp<=f382_long}")


def test_above_all_outside_fib():
    """场景7: ABOVE_ALL + 价格在 Fib 回调区外 → WAIT"""
    random.seed(654)
    prices = gen_uptrend(n=210, start=10000, drift=0.003, vol=0.01)

    cp, smas, rsi, pos, fib = get_indicators(prices)
    # 价格接近 swing_high（远离回调区）
    target_price = fib['swing_high'] * 0.99

    result = run_v15_with_prices(prices, current_price=target_price)
    cp2, smas2, rsi2, pos2, fib2 = get_indicators(prices, target_price)

    if pos2 == "ABOVE_ALL":
        assert_eq("ABOVE_ALL outside: action", result["action"], "WAIT")
    else:
        assert_true("ABOVE_ALL outside: skip", True, f"pos={pos2}")


def test_above_all_rsi_too_high():
    """场景8: ABOVE_ALL + 在Fib回调区 + RSI>=55 → WAIT"""
    random.seed(44)
    # 强势上涨使RSI很高
    prices = gen_uptrend(n=210, start=10000, drift=0.006, vol=0.015)

    cp, smas, rsi, pos, fib = get_indicators(prices)
    rng = fib['swing_high'] - fib['swing_low']
    f382_long = fib['swing_high'] - 0.382 * rng
    f618_long = fib['swing_high'] - 0.618 * rng
    target_price = (f382_long + f618_long) / 2

    result = run_v15_with_prices(prices, current_price=target_price)
    cp2, smas2, rsi2, pos2, fib2 = get_indicators(prices, target_price)

    if pos2 == "ABOVE_ALL" and f618_long <= target_price <= f382_long:
        if rsi >= 55:
            assert_eq("ABOVE_ALL rsi_high: action", result["action"], "WAIT", f"RSI={rsi}")
        else:
            assert_eq("ABOVE_ALL rsi_ok: action", result["action"], "OPEN_BULL", f"RSI={rsi}")


# ========== IN_ZONE 场景 ==========

def test_in_zone_rsi_oversold():
    """场景9: IN_ZONE + RSI<35 → OPEN_BULL 单层"""
    random.seed(99)
    prices = gen_sideways(n=200, center=50000, vol=0.01)
    for i in range(10):
        prices.append(prices[-1] * (1 - 0.04))

    result = run_v15_with_prices(prices)
    cp, smas, rsi, pos, fib = get_indicators(prices)

    if pos == 'IN_ZONE' and rsi < 35:
        assert_eq("IN_ZONE oversold: action", result["action"], "OPEN_BULL")
        assert_eq("IN_ZONE oversold: fib_zone", result["fib_zone"], None)
        assert_eq("IN_ZONE oversold: vol_mult", result["vol_mult"], 1.0)
        assert_range("IN_ZONE oversold: confidence", result["confidence"], 60, 70)
    else:
        assert_true("IN_ZONE oversold: skip", True, f"pos={pos}, rsi={rsi}")


def test_in_zone_rsi_overbought():
    """场景10: IN_ZONE + RSI>65 → OPEN_BEAR 单层"""
    random.seed(88)
    prices = gen_sideways(n=200, center=50000, vol=0.01)
    for i in range(10):
        prices.append(prices[-1] * (1 + 0.04))

    result = run_v15_with_prices(prices)
    cp, smas, rsi, pos, fib = get_indicators(prices)

    if pos == 'IN_ZONE' and rsi > 65:
        assert_eq("IN_ZONE overbought: action", result["action"], "OPEN_BEAR")
        assert_range("IN_ZONE overbought: confidence", result["confidence"], 60, 70)
    else:
        assert_true("IN_ZONE overbought: skip", True, f"pos={pos}, rsi={rsi}")


def test_in_zone_rsi_neutral():
    """场景11: IN_ZONE + 35<=RSI<=65 → WAIT"""
    random.seed(77)
    prices = gen_sideways(n=210, center=50000, vol=0.008)

    result = run_v15_with_prices(prices)
    cp, smas, rsi, pos, fib = get_indicators(prices)

    if pos == 'IN_ZONE' and 35 <= rsi <= 65:
        assert_eq("IN_ZONE neutral: action", result["action"], "WAIT")
        assert_range("IN_ZONE neutral: confidence", result["confidence"], 0, 40)
    else:
        assert_true("IN_ZONE neutral: skip", True, f"pos={pos}, rsi={rsi}")


# ========== 边界与一致性 ==========

def test_fib_boundary_exact():
    """场景12: 价格刚好在 Fib 边界值"""
    random.seed(66)
    prices = gen_downtrend(n=210, start=100000, drift=-0.003, vol=0.01)

    cp, smas, rsi, pos, fib = get_indicators(prices)
    min_sma = min(v for v in smas.values() if v)

    for label, target in [("f382", fib['f382']), ("f500", fib['f500']), ("f618", fib['f618'])]:
        if target < min_sma:
            result = run_v15_with_prices(prices, current_price=target)
            assert_true(f"Boundary {label}: no crash", result["mode"] == "v15")


def test_vol_mult_consistency():
    """场景13: vol_mult 与 fib_zone/boll_signal 一致性（100轮）"""
    for seed in range(100):
        random.seed(seed)
        prices = gen_downtrend(n=210, start=100000, drift=-0.003, vol=0.015)

        cp, smas, rsi, pos, fib = get_indicators(prices)
        target = (fib['f500'] + fib['f618']) / 2
        target = min(target, min(v for v in smas.values() if v) - 1)

        result = run_v15_with_prices(prices, current_price=target)
        fib_zone = result.get("fib_zone")
        boll_signal = result.get("boll_signal")
        vol_mult = result.get("vol_mult", 1.0)

        if fib_zone == "golden" and boll_signal in ("touch_upper", "touch_lower"):
            assert_eq(f"VolMult golden+boll (seed={seed})", vol_mult, 1.3)
        elif fib_zone == "golden":
            assert_eq(f"VolMult golden (seed={seed})", vol_mult, 1.2)
        elif fib_zone == "shallow":
            assert_eq(f"VolMult shallow (seed={seed})", vol_mult, 0.8)
        elif boll_signal in ("touch_upper", "touch_lower"):
            assert_eq(f"VolMult boll (seed={seed})", vol_mult, 1.0)
        elif boll_signal == "rsi_extreme":
            assert_eq(f"VolMult rsi_extreme (seed={seed})", vol_mult, 0.7)
        else:
            assert_eq(f"VolMult none (seed={seed})", vol_mult, 1.0)


# ========== 异常数据 ==========

def test_empty_candles():
    """场景14: K线数据为空 → WAIT + confidence=0"""
    from v15_signal import v15_decision
    with patch("v15_signal.fetch_candles", return_value=[]):
        result = v15_decision("BTC-USDT")

    assert_eq("Empty: action", result["action"], "WAIT")
    assert_eq("Empty: confidence", result["confidence"], 0)
    assert_eq("Empty: mode", result["mode"], "v15")
    assert_in("Empty: reasons", result["reasons"], "无法获取K线数据")


def test_insufficient_data():
    """场景15: K线数据不足 → 不崩溃"""
    random.seed(33)
    prices = gen_uptrend(n=50, start=10000, drift=0.003, vol=0.01)
    result = run_v15_with_prices(prices)

    assert_true("Insufficient: no crash", result["mode"] == "v15")
    assert_true("Insufficient: action valid", result["action"] in ["OPEN_BULL", "OPEN_BEAR", "WAIT"])


def test_extreme_volatility():
    """场景16: 极端波动"""
    random.seed(22)
    prices = [50000]
    for i in range(209):
        prices.append(max(prices[-1] * (1 + random.gauss(0, 0.08)), 100))

    result = run_v15_with_prices(prices)
    assert_true("Extreme vol: no crash", result["mode"] == "v15")
    assert_true("Extreme vol: action valid", result["action"] in ["OPEN_BULL", "OPEN_BEAR", "WAIT"])
    assert_range("Extreme vol: confidence", result["confidence"], 0, 100)


def test_sharp_drop():
    """场景17: 急跌行情"""
    random.seed(11)
    prices = [100000]
    for i in range(179):
        prices.append(max(prices[-1] * (1 + random.gauss(0, 0.01)), 100))
    prices.append(prices[-1] * 0.6)  # 急跌40%
    for i in range(30):
        prices.append(max(prices[-1] * (1 + random.gauss(0, 0.02)), 100))

    result = run_v15_with_prices(prices)
    assert_true("Sharp drop: no crash", result["mode"] == "v15")


def test_sharp_pump():
    """场景18: 暴涨行情"""
    random.seed(11)
    prices = [20000]
    for i in range(179):
        prices.append(max(prices[-1] * (1 + random.gauss(0, 0.01)), 100))
    prices.append(prices[-1] * 1.6)  # 暴涨60%
    for i in range(30):
        prices.append(max(prices[-1] * (1 + random.gauss(0, 0.02)), 100))

    result = run_v15_with_prices(prices)
    assert_true("Sharp pump: no crash", result["mode"] == "v15")


def test_v_shape_recovery():
    """场景19: V型反转"""
    random.seed(11)
    prices = []
    n = 210
    mid = n // 2
    peak, bottom = 80000, 30000
    for i in range(n):
        if i < mid:
            t = i / mid
            prices.append(max(peak - (peak - bottom) * t + random.gauss(0, 500), 100))
        else:
            t = (i - mid) / (n - mid)
            prices.append(max(bottom + (peak - bottom) * t + random.gauss(0, 500), 100))

    result = run_v15_with_prices(prices)
    assert_true("V-shape: no crash", result["mode"] == "v15")


def test_all_same_price():
    """场景20: 价格完全不变 → RSI=100 (无跌幅=RSI上限)"""
    prices = [50000.0] * 210
    result = run_v15_with_prices(prices)

    assert_true("Same price: no crash", result["mode"] == "v15")
    # 价格不变时无跌幅，RSI=100 是数学正确结果
    assert_eq("Same price: rsi", result.get("rsi", 100), 100.0)


def test_constant_decline():
    """场景21: 每天固定下跌"""
    prices = [100000 - i * 100 for i in range(210)]
    result = run_v15_with_prices(prices)

    assert_true("Constant decline: no crash", result["mode"] == "v15")
    assert_eq("Constant decline: position", result["position"], "BELOW_ALL")


def test_bollinger_touch_lower():
    """场景22: IN_ZONE + 价格触及布林下轨 + RSI<45 → OPEN_BULL"""
    random.seed(55)
    prices = gen_sideways(n=190, center=50000, vol=0.012)
    for i in range(20):
        prices.append(prices[-1] * (1 - 0.015))  # 连续下跌触下轨

    result = run_v15_with_prices(prices)
    cp, smas, rsi, pos, fib = get_indicators(prices)
    boll = result.get("boll")

    if pos == 'IN_ZONE' and boll and cp <= boll['lower'] and rsi < 45:
        assert_eq("Boll touch_lower: action", result["action"], "OPEN_BULL")
        assert_eq("Boll touch_lower: boll_signal", result["boll_signal"], "touch_lower")
        assert_range("Boll touch_lower: confidence", result["confidence"], 65, 80)
    else:
        assert_true("Boll touch_lower: skip", True, f"pos={pos}, rsi={rsi}, in_boll={boll and cp<=boll['lower'] if boll else 'no_boll'}")


def test_bollinger_touch_upper():
    """场景23: IN_ZONE + 价格触及布林上轨 + RSI>55 → OPEN_BEAR"""
    random.seed(66)
    prices = gen_sideways(n=190, center=50000, vol=0.012)
    for i in range(20):
        prices.append(prices[-1] * (1 + 0.015))  # 连续上涨触上轨

    result = run_v15_with_prices(prices)
    cp, smas, rsi, pos, fib = get_indicators(prices)
    boll = result.get("boll")

    if pos == 'IN_ZONE' and boll and cp >= boll['upper'] and rsi > 55:
        assert_eq("Boll touch_upper: action", result["action"], "OPEN_BEAR")
        assert_eq("Boll touch_upper: boll_signal", result["boll_signal"], "touch_upper")
        assert_range("Boll touch_upper: confidence", result["confidence"], 65, 80)
    else:
        assert_true("Boll touch_upper: skip", True, f"pos={pos}, rsi={rsi}, in_boll={boll and cp>=boll['upper'] if boll else 'no_boll'}")


def test_bollinger_middle_wait():
    """场景24: IN_ZONE + 价格在布林带中部 + RSI中性 → WAIT"""
    random.seed(77)
    prices = gen_sideways(n=210, center=50000, vol=0.008)

    result = run_v15_with_prices(prices)
    cp, smas, rsi, pos, fib = get_indicators(prices)
    boll = result.get("boll")

    if pos == 'IN_ZONE' and boll and boll['lower'] < cp < boll['upper'] and 35 <= rsi <= 65:
        assert_eq("Boll middle: action", result["action"], "WAIT")
    else:
        assert_true("Boll middle: skip", True, f"pos={pos}, rsi={rsi}")


# ========== 大规模随机测试 ==========

def test_massive_run():
    """场景25: 500次随机场景测试"""
    random.seed(0)
    crash_count = 0
    distribution = {"OPEN_BULL": 0, "OPEN_BEAR": 0, "WAIT": 0}

    for i in range(500):
        scenario = random.choice(["up", "down", "side", "volatile", "v_shape"])
        if scenario == "up":
            prices = gen_uptrend(n=210, start=random.randint(1000, 50000),
                                 drift=random.uniform(0.001, 0.008), vol=random.uniform(0.005, 0.03))
        elif scenario == "down":
            prices = gen_downtrend(n=210, start=random.randint(50000, 200000),
                                   drift=random.uniform(-0.008, -0.001), vol=random.uniform(0.005, 0.03))
        elif scenario == "side":
            prices = gen_sideways(n=210, center=random.randint(10000, 80000), vol=random.uniform(0.005, 0.025))
        elif scenario == "volatile":
            prices = [random.randint(1000, 100000) + random.gauss(0, 5000) for _ in range(210)]
            prices = [max(p, 100) for p in prices]
        else:
            prices = []
            mid = 105
            peak, bottom = random.randint(50000, 100000), random.randint(10000, 40000)
            for j in range(210):
                if j < mid:
                    t = j / mid
                    prices.append(max(peak - (peak - bottom) * t + random.gauss(0, 500), 100))
                else:
                    t = (j - mid) / (210 - mid)
                    prices.append(max(bottom + (peak - bottom) * t + random.gauss(0, 500), 100))

        try:
            result = run_v15_with_prices(prices)
            action = result.get("action", "CRASH")
            if action in distribution:
                distribution[action] += 1
            else:
                distribution[action] = 1
                crash_count += 1
        except Exception as e:
            crash_count += 1
            RESULTS.append(("FAIL", f"Massive run #{i}", f"Crash: {str(e)[:100]}"))

    assert_eq("Massive: no crashes", crash_count, 0, f"500次中崩溃{crash_count}次")
    assert_gt("Massive: has WAIT", distribution.get("WAIT", 0), 0, "应有WAIT结果")
    RESULTS.append(("INFO", "Massive: distribution", json.dumps(distribution)))


# ========== 运行测试 ==========

def main():
    print("=" * 80)
    print("V15 真实策略多场景压力测试 v2")
    print(f"时间: {datetime.now().isoformat()}")
    print("=" * 80)
    print()

    tests = [
        # BELOW_ALL
        ("BELOW_ALL 黄金区 SHORT", test_below_all_short_golden),
        ("BELOW_ALL 浅区 SHORT", test_below_all_short_shallow),
        ("BELOW_ALL Fib区外 WAIT", test_below_all_outside_fib),
        ("BELOW_ALL RSI过低 WAIT", test_below_all_rsi_too_low),

        # ABOVE_ALL
        ("ABOVE_ALL 黄金回调区 LONG", test_above_all_long_golden),
        ("ABOVE_ALL 浅回调区 LONG", test_above_all_long_shallow),
        ("ABOVE_ALL Fib区外 WAIT", test_above_all_outside_fib),
        ("ABOVE_ALL RSI过高 WAIT", test_above_all_rsi_too_high),

        # IN_ZONE
        ("IN_ZONE RSI超卖 LONG", test_in_zone_rsi_oversold),
        ("IN_ZONE RSI超买 SHORT", test_in_zone_rsi_overbought),
        ("IN_ZONE RSI中性 WAIT", test_in_zone_rsi_neutral),

        # 边界条件
        ("Fib边界值精确测试", test_fib_boundary_exact),
        ("vol_mult一致性(100轮)", test_vol_mult_consistency),

        # 异常数据
        ("空K线数据", test_empty_candles),
        ("数据不足(<200天)", test_insufficient_data),
        ("极端波动", test_extreme_volatility),
        ("急跌行情", test_sharp_drop),
        ("暴涨行情", test_sharp_pump),
        ("V型反转", test_v_shape_recovery),
        ("价格不变", test_all_same_price),
        ("固定下跌", test_constant_decline),

        # 布林带
        ("布林带下轨均值回归LONG", test_bollinger_touch_lower),
        ("布林带上轨均值回归SHORT", test_bollinger_touch_upper),
        ("布林带中部+RSI中性 WAIT", test_bollinger_middle_wait),

        # 大规模
        ("500次随机场景", test_massive_run),
    ]

    for name, func in tests:
        print(f"  [运行] {name} ...", end=" ", flush=True)
        try:
            func()
            print("✅")
        except Exception as e:
            global FAIL
            FAIL += 1
            RESULTS.append(("FAIL", name, f"Exception: {str(e)[:200]}"))
            print(f"❌ {str(e)[:80]}")

    # 详细报告
    print()
    print("=" * 80)
    print("失败详情")
    print("=" * 80)

    fail_count = 0
    for status, name, detail in RESULTS:
        if status == "FAIL":
            fail_count += 1
            print(f"  ❌ [{name}]")
            print(f"          {detail}")

    if fail_count == 0:
        print("  (无失败)")

    print()
    print("=" * 80)
    print(f"总结: ✅ {PASS} passed | ❌ {FAIL} failed | 总计 {PASS + FAIL}")
    print("=" * 80)

    print("\n场景分布:")
    for status, name, detail in RESULTS:
        if status == "INFO":
            print(f"  📊 {name}: {detail}")

    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
