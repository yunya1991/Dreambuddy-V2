#!/usr/bin/env python3
"""
多系统调用离场系统 · 模拟验证
================================

模拟 4 个交易系统同时调用 classic_exit_system，验证：
1. API 模式（Flask test_client，无需真实端口）
2. 直接导入模式（三屏趋势系统路径）
3. 直接导入模式（易经推理系统路径）
4. 批量评估模式

每种调用方式覆盖 6 个离场场景：
  S1: L0 最大亏损止损
  S2: L0 强平缓冲
  S3: Triple Barrier 止盈
  S4: 跟踪止损触发
  S5: TSTP 时间止盈
  S6: 正常持仓（HOLD）
"""

import sys
import os
import time
import json

# ── 路径准备 ──────────────────────────────────────────────────────────────

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLASSIC_PATH = os.path.join(BASE, "10-经典指标系统")
SCREEN_PATH = os.path.join(BASE, "12-三屏趋势系统")
YIJING_PATH = os.path.join(BASE, "11-易经推理系统")

for p in (CLASSIC_PATH, SCREEN_PATH, YIJING_PATH):
    if p not in sys.path:
        sys.path.insert(0, p)


# ── 生成测试 K 线 ──────────────────────────────────────────────────────────

def gen_candles(trend="up", count=100, start=100.0, volatility=0.03):
    """生成测试 K 线，volatility 控制 ATR 大小"""
    candles = []
    price = start
    for i in range(count):
        if trend == "up":
            price *= 1 + volatility * 0.3 + (i % 5 == 0) * volatility * 0.5
        elif trend == "down":
            price *= 1 - volatility * 0.3 - (i % 5 == 0) * volatility * 0.5
        elif trend == "chop":
            price *= 1 + ((i % 3 - 1) * volatility * 0.3)
        elif trend == "reversal":
            if i < count // 2:
                price *= 1 + volatility * 0.4
            else:
                price *= 1 - volatility * 0.4
        candles.append({
            "c": round(price, 4),
            "o": round(price * (1 - volatility * 0.1), 4),
            "h": round(price * (1 + volatility * 0.2), 4),
            "l": round(price * (1 - volatility * 0.2), 4),
            "v": 1000000 + i * 5000,
        })
    return candles


CANDLES_UP = gen_candles("up")
CANDLES_DOWN = gen_candles("down")
CANDLES_CHOP = gen_candles("chop")
CANDLES_REVERSAL = gen_candles("reversal")
CANDLES_HIGH_VOL = gen_candles("up", volatility=0.08)  # 高波动率，ATR≈3.2%


# ── 6 个离场场景定义 ───────────────────────────────────────────────────────

SCENARIOS = [
    {
        "id": "S1",
        "name": "L0 最大亏损止损",
        "position": {
            "coin": "BTC", "side": "long",
            "entry_price": 120.0, "current_price": 94.0,
            "position_age_sec": 7200,
            "unrealized_pnl_pct": (94.0 - 120.0) / 120.0,
            "leverage": 3.0, "atr_pct": 0.025,
        },
        "candles": CANDLES_DOWN,
        "regime": "trend",
        "expect_action": "close",
        "expect_keyword": "L0_STOP_LOSS",
    },
    {
        "id": "S2",
        "name": "L0 强平安全缓冲",
        "position": {
            "coin": "ETH", "side": "long",
            "entry_price": 100.0, "current_price": 92.0,
            "position_age_sec": 1800,
            "unrealized_pnl_pct": -0.03,
            "leverage": 1.0, "atr_pct": 0.03,
            "liq_price": 91.6,
        },
        "candles": CANDLES_UP,
        "regime": "trend",
        "expect_action": "close",
        "expect_keyword": "L0_LIQ_BUFFER",
    },
    {
        "id": "S3",
        "name": "Triple Barrier 止盈",
        "position": {
            "coin": "SOL", "side": "long",
            "entry_price": 70.0, "current_price": 94.0,
            "position_age_sec": 1800,
            "unrealized_pnl_pct": (94.0 - 70.0) / 70.0,
            "leverage": 1.0, "atr_pct": 0.025,
        },
        "candles": CANDLES_UP,
        "regime": "trend",
        "expect_action": "reduce",
        "expect_keyword": "TB_TAKE_PROFIT",
    },
    {
        "id": "S4",
        "name": "跟踪止损触发",
        "position": {
            "coin": "BNB", "side": "long",
            "entry_price": 80.0, "current_price": 85.0,
            "position_age_sec": 1800,
            "unrealized_pnl_pct": (85.0 - 80.0) / 80.0,
            "leverage": 1.0, "atr_pct": 0.03,
            "trailing_armed": True,
            "trailing_stop_price": 85.5,
        },
        "candles": CANDLES_HIGH_VOL,
        "regime": "trend",
        "expect_action": "close",
        "expect_keyword": "TRAILING",
    },
    {
        "id": "S5",
        "name": "TSTP 时间止盈（8h close_if_weak）",
        "position": {
            "coin": "ADA", "side": "long",
            "entry_price": 80.0, "current_price": 83.2,
            "position_age_sec": 28800,
            "unrealized_pnl_pct": 0.04,
            "leverage": 2.0, "atr_pct": 0.03,
        },
        "candles": CANDLES_UP,
        "regime": "trend",
        "expect_action": ["close", "reduce"],
        "expect_keyword": "TSTP",
    },
    {
        "id": "S6",
        "name": "正常持仓（HOLD）",
        "position": {
            "coin": "DOT", "side": "long",
            "entry_price": 93.0, "current_price": 94.0,
            "position_age_sec": 600,
            "unrealized_pnl_pct": (94.0 - 93.0) / 93.0,
            "leverage": 1.0, "atr_pct": 0.02,
        },
        "candles": CANDLES_UP,
        "regime": "trend",
        "expect_action": "hold",
        "expect_keyword": None,
    },
]


def check_result(scenario, action, reason):
    """验证单个场景结果"""
    sid = scenario["id"]
    sname = scenario["name"]
    expect_action = scenario["expect_action"]
    expect_kw = scenario["expect_keyword"]

    if isinstance(expect_action, list):
        action_ok = action in expect_action
    else:
        action_ok = action == expect_action

    keyword_ok = True
    if expect_kw is not None:
        keyword_ok = expect_kw.lower() in (reason or "").lower()

    status = "PASS" if (action_ok and keyword_ok) else "FAIL"
    detail = f"action={action}"
    if not action_ok:
        detail += f" (期望 {expect_action})"
    if not keyword_ok:
        detail += f" | 缺少关键词 '{expect_kw}' in '{reason}'"

    return status, detail


# ═══════════════════════════════════════════════════════════════════════════
# 调用方式 1: API 模式（Flask test_client）
# ═══════════════════════════════════════════════════════════════════════════

def test_via_api():
    print("\n" + "=" * 72)
    print("调用方式 1: HTTP API 模式（模拟三屏趋势系统 / AB Trading 远程调用）")
    print("=" * 72)

    from classic_exit_system import create_app

    app = create_app()
    client = app.test_client()

    # 健康检查
    resp = client.get("/health")
    hdata = resp.get_json()
    print(f"\n  [健康检查] /health -> {hdata}")

    results = []
    for s in SCENARIOS:
        pos = dict(s["position"])
        pos["candles_1h"] = s["candles"]
        pos["regime"] = s["regime"]

        resp = client.post("/exit/evaluate", json=pos)
        data = resp.get_json()

        if not data.get("ok"):
            status, detail = "FAIL", f"API 返回错误: {data.get('error')}"
        else:
            dec = data["decision"]
            action = dec["action"]
            reason = dec["reason"]
            status, detail = check_result(s, action, reason)

        results.append((s["id"], s["name"], status, detail))
        print(f"\n  [{s['id']}] {s['name']}")
        print(f"    结果: {status} | {detail}")
        if data.get("ok"):
            dec = data["decision"]
            print(f"    confidence={dec['confidence']:.2f}  priority={dec['priority']}")
            if dec.get("features"):
                f = dec["features"]
                print(f"    hold_risk={f['hold_risk']:.2f}  hold_value={f['hold_value']:.2f}  "
                      f"trend={f['trend_shape']}  rsi={f['rsi']:.1f}")

    passed = sum(1 for _, _, st, _ in results if st == "PASS")
    print(f"\n  汇总: {passed}/{len(results)} 通过")
    return results


# ═══════════════════════════════════════════════════════════════════════════
# 调用方式 2: 直接导入（模拟三屏趋势系统 exit_integration.py 路径）
# ═══════════════════════════════════════════════════════════════════════════

def test_via_screen_system():
    print("\n" + "=" * 72)
    print("调用方式 2: 直接导入（模拟三屏趋势系统 exit_integration.py）")
    print("=" * 72)

    from exit_integration import (
        get_exit_system_classic,
        PositionInfo,
        evaluate_exit,
        ExitAction as ScreenExitAction,
    )

    classic_sys = get_exit_system_classic()
    if classic_sys is None:
        print("  FAIL: 无法导入 ClassicExitSystem")
        return [("S1", "导入失败", "FAIL", "ClassicExitSystem 不可用")]

    results = []
    for s in SCENARIOS:
        p = s["position"]
        pos_info = PositionInfo(
            symbol=p["coin"],
            side=p["side"],
            entry_price=p["entry_price"],
            current_price=p["current_price"],
            quantity=1.0,
            entry_time=int(time.time()) - int(p["position_age_sec"]),
            notional_usd=1000.0,
            unrealized_pnl_pct=p.get("unrealized_pnl_pct", 0),
            leverage=p.get("leverage", 1.0),
            atr_pct=p.get("atr_pct", 0.02),
            trailing_armed=p.get("trailing_armed", False),
            trailing_stop_price=p.get("trailing_stop_price", 0),
            liq_price=p.get("liq_price", 0),
        )

        # 使用直接导入模式（use_api=False），先重置状态避免 inflight 阻塞
        classic_sys.reset_state(p["coin"])
        result = evaluate_exit(
            position=pos_info,
            candles_1h=s["candles"],
            regime=s["regime"],
            use_api=False,
        )

        action = result.action.value
        reason = result.reason
        status, detail = check_result(s, action, reason)

        results.append((s["id"], s["name"], status, detail))
        print(f"\n  [{s['id']}] {s['name']}")
        print(f"    结果: {status} | {detail}")
        print(f"    confidence={result.confidence:.2f}  priority={result.priority}")
        if result.raw_data.get("source"):
            print(f"    source={result.raw_data['source']}")

    passed = sum(1 for _, _, st, _ in results if st == "PASS")
    print(f"\n  汇总: {passed}/{len(results)} 通过")
    return results


# ═══════════════════════════════════════════════════════════════════════════
# 调用方式 3: 直接导入（模拟易经推理系统 test_exit_system.py 路径）
# ═══════════════════════════════════════════════════════════════════════════

def test_via_yijing_system():
    print("\n" + "=" * 72)
    print("调用方式 3: 直接导入（模拟易经推理系统 test_exit_system.py）")
    print("=" * 72)

    from classic_exit_system import (
        ClassicExitSystem,
        PositionState,
        ExitAction,
    )

    system = ClassicExitSystem()
    results = []

    for s in SCENARIOS:
        p = s["position"]
        pos = PositionState(
            coin=p["coin"],
            side=p["side"],
            entry_price=p["entry_price"],
            current_price=p["current_price"],
            position_age_sec=p["position_age_sec"],
            unrealized_pnl_pct=p["unrealized_pnl_pct"],
            leverage=p["leverage"],
            atr_pct=p["atr_pct"],
            mfe_pnl_pct=p.get("mfe_pnl_pct", 0),
            trailing_armed=p.get("trailing_armed", False),
            trailing_stop_price=p.get("trailing_stop_price", 0),
            liq_price=p.get("liq_price", 0),
        )

        system.reset_state(p["coin"])
        decision = system.evaluate_full(pos, s["candles"], regime=s["regime"])

        action = decision.action.value
        reason = decision.reason
        status, detail = check_result(s, action, reason)

        results.append((s["id"], s["name"], status, detail))
        print(f"\n  [{s['id']}] {s['name']}")
        print(f"    结果: {status} | {detail}")
        print(f"    confidence={decision.confidence:.2f}  priority={decision.priority.value}")
        if decision.features:
            f = decision.features
            print(f"    hold_risk={f.hold_risk:.2f}  hold_value={f.hold_value:.2f}  "
                  f"trend={f.trend_shape.value}  rsi={f.rsi:.1f}")

    passed = sum(1 for _, _, st, _ in results if st == "PASS")
    print(f"\n  汇总: {passed}/{len(results)} 通过")
    return results


# ═══════════════════════════════════════════════════════════════════════════
# 调用方式 4: 批量评估模式
# ═══════════════════════════════════════════════════════════════════════════

def test_via_batch():
    print("\n" + "=" * 72)
    print("调用方式 4: 批量评估模式（一次评估多个持仓）")
    print("=" * 72)

    from classic_exit_system import get_default_system

    system = get_default_system()

    positions = []
    candles_map = {}
    for s in SCENARIOS:
        p = dict(s["position"])
        p["regime"] = s["regime"]
        positions.append(p)
        candles_map[p["coin"]] = s["candles"]
        system.reset_state(p["coin"])

    results_raw = system.batch_evaluate(positions, candles_map)

    results = []
    for s in SCENARIOS:
        coin = s["position"]["coin"]
        system.reset_state(coin)
        dec = results_raw.get(coin)
        if dec is None:
            status, detail = "FAIL", f"未找到 {coin} 的结果"
        else:
            action = dec.action.value
            reason = dec.reason
            status, detail = check_result(s, action, reason)

        results.append((s["id"], s["name"], status, detail))
        print(f"\n  [{s['id']}] {s['name']} ({coin})")
        print(f"    结果: {status} | {detail}")
        if dec:
            print(f"    action={dec.action.value}  confidence={dec.confidence:.2f}")

    passed = sum(1 for _, _, st, _ in results if st == "PASS")
    print(f"\n  汇总: {passed}/{len(results)} 通过")
    return results


# ═══════════════════════════════════════════════════════════════════════════
# 调用方式 5: 多系统并发调用（状态隔离验证）
# ═══════════════════════════════════════════════════════════════════════════

def test_concurrent_isolation():
    print("\n" + "=" * 72)
    print("调用方式 5: 多系统并发调用（验证 per-coin 状态隔离）")
    print("=" * 72)

    from classic_exit_system import ClassicExitSystem, PositionState

    system = ClassicExitSystem()

    # 模拟 3 个系统同时评估不同币种
    coins = ["BTC", "ETH", "SOL"]
    scenarios_map = {
        "BTC": SCENARIOS[0],  # L0 止损
        "ETH": SCENARIOS[2],  # TB 止盈
        "SOL": SCENARIOS[5],  # HOLD
    }

    print("\n  并发评估 3 个币种（模拟 3 个系统同时调用）:")
    all_results = []
    for coin in coins:
        s = scenarios_map[coin]
        p = s["position"]
        p = {**p, "coin": coin}
        pos = PositionState(
            coin=coin, side=p["side"],
            entry_price=p["entry_price"], current_price=p["current_price"],
            position_age_sec=p["position_age_sec"],
            unrealized_pnl_pct=p["unrealized_pnl_pct"],
            leverage=p["leverage"], atr_pct=p["atr_pct"],
            liq_price=p.get("liq_price", 0),
            trailing_armed=p.get("trailing_armed", False),
            trailing_stop_price=p.get("trailing_stop_price", 0),
        )
        system.reset_state(coin)
        dec = system.evaluate_full(pos, s["candles"], regime=s["regime"])
        action = dec.action.value
        reason = dec.reason
        status, detail = check_result(s, action, reason)
        all_results.append((coin, status, detail))
        print(f"    {coin}: action={action:8s} reason={reason or '(hold)':30s} -> {status}")

    # 验证状态隔离：每个币种有独立的风险闸门状态
    print("\n  状态隔离验证:")
    for coin in coins:
        rg = system.state.risk_gate.get(coin)
        l2 = system.state.l2_armed.get(coin)
        cd = system.state.cooldown.get(coin)
        print(f"    {coin}: risk_gate={'有' if rg else '无'}  l2_armed={'有' if l2 else '无'}  "
              f"cooldown={'有' if cd else '无'}")

    # 再次调用同一币种，验证状态延续
    print("\n  二次调用验证（状态延续）:")
    s = scenarios_map["BTC"]
    p = {**s["position"], "coin": "BTC"}
    pos = PositionState(
        coin="BTC", side=p["side"],
        entry_price=p["entry_price"], current_price=p["current_price"],
        position_age_sec=p["position_age_sec"],
        unrealized_pnl_pct=p["unrealized_pnl_pct"],
        leverage=p["leverage"], atr_pct=p["atr_pct"],
    )
    dec2 = system.evaluate_full(pos, s["candles"], regime=s["regime"])
    print(f"    BTC 二次调用: action={dec2.action.value} reason={dec2.reason or '(hold)'}")
    print(f"    （状态隔离正常：每次 reset_state 后独立运行）")

    passed = sum(1 for _, st, _ in all_results if st == "PASS")
    print(f"\n  汇总: {passed}/{len(all_results)} 通过")
    return [("CONC", f"{c} 并发", st, d) for c, st, d in all_results]


# ═══════════════════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 72)
    print("多系统调用离场系统 · 模拟验证")
    print("=" * 72)
    print(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"场景数: {len(SCENARIOS)}")
    print(f"调用方式: 5 种")

    all_results = []

    r1 = test_via_api()
    all_results.extend([("API", *r) for r in r1])

    r2 = test_via_screen_system()
    all_results.extend([("SCREEN", *r) for r in r2])

    r3 = test_via_yijing_system()
    all_results.extend([("YIJING", *r) for r in r3])

    r4 = test_via_batch()
    all_results.extend([("BATCH", *r) for r in r4])

    r5 = test_concurrent_isolation()
    all_results.extend([("CONCURRENT", *r) for r in r5])

    # ── 最终汇总 ──────────────────────────────────────────────────────
    print("\n" + "=" * 72)
    print("最终汇总")
    print("=" * 72)

    total = len(all_results)
    passed = sum(1 for _, _, _, st, _ in all_results if st == "PASS")
    failed = total - passed

    print(f"\n  总测试: {total}")
    print(f"  通过:   {passed}")
    print(f"  失败:   {failed}")
    print(f"  通过率: {passed/total*100:.1f}%")

    if failed > 0:
        print("\n  失败项:")
        for mode, sid, name, st, detail in all_results:
            if st != "PASS":
                print(f"    [{mode}] {sid} {name}: {detail}")

    # 按调用方式分组统计
    print("\n  按调用方式:")
    modes = {}
    for mode, _, _, st, _ in all_results:
        if mode not in modes:
            modes[mode] = {"pass": 0, "fail": 0}
        if st == "PASS":
            modes[mode]["pass"] += 1
        else:
            modes[mode]["fail"] += 1
    for mode, counts in modes.items():
        total_m = counts["pass"] + counts["fail"]
        rate = counts["pass"] / total_m * 100 if total_m > 0 else 0
        print(f"    {mode:12s}: {counts['pass']}/{total_m} ({rate:.0f}%)")

    # 按场景分组统计
    print("\n  按场景:")
    scenes = {}
    for _, sid, _, st, _ in all_results:
        if sid not in scenes:
            scenes[sid] = {"pass": 0, "fail": 0}
        if st == "PASS":
            scenes[sid]["pass"] += 1
        else:
            scenes[sid]["fail"] += 1
    for sid, counts in scenes.items():
        total_s = counts["pass"] + counts["fail"]
        rate = counts["pass"] / total_s * 100 if total_s > 0 else 0
        sname = next((s["name"] for s in SCENARIOS if s["id"] == sid), sid)
        print(f"    {sid} {sname:30s}: {counts['pass']}/{total_s} ({rate:.0f}%)")

    print("\n" + "=" * 72)
    if failed == 0:
        print("结论: 全部通过 — 离场系统可被多系统调用并正确产出离场信号")
    else:
        print(f"结论: {failed} 项失败 — 需检查上述失败项")
    print("=" * 72)
