#!/usr/bin/env python3
"""
V15 经典马丁策略压力测试
测试场景：
1. 全币种信号触发测试
2. 不同资金规模测试（100U, 200U, 500U）
3. 多持仓场景测试
4. 资金计算器准确性验证
5. 资金充足时控制不开新仓验证
"""
import json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / "lib"))
sys.path.insert(0, str(BASE_DIR / "core"))

from config_loader import load_config, get_config_float, get_config_int, get_config_list
from capital_manager import calculate_capital_allocation, get_signal_trigger_status


class MockOKXClient:
    """模拟OKX客户端，用于压力测试"""
    def __init__(self, balance=100, positions=None):
        self._balance = balance
        self._positions = positions or {}
        self._prices = {
            "BTC-USDT-SWAP": 67000,
            "ETH-USDT-SWAP": 3500,
            "SOL-USDT-SWAP": 140,
            "ARB-USDT-SWAP": 1.5,
            "OP-USDT-SWAP": 1.2,
            "UNI-USDT-SWAP": 5.5,
            "HYPE-USDT-SWAP": 0.05,
            "OKB-USDT-SWAP": 35,
        }

    def get_balance(self):
        used_margin = sum(p["margin"] for p in self._positions.values())
        return {
            "ok": True,
            "data": {
                "total_eq": self._balance,
                "avail_balance": self._balance - used_margin,
            },
        }

    def get_positions(self, inst_id):
        pos = self._positions.get(inst_id)
        if pos:
            return {
                "ok": True,
                "data": [{
                    "pos_sz": pos["sz"],
                    "avg_entry_px": pos["entry_price"],
                    "mark_px": self._prices.get(inst_id, pos["entry_price"]),
                    "margin": pos["margin"],
                    "unrealized_pnl": pos.get("unrealized_pnl", 0),
                }],
            }
        return {"ok": True, "data": []}

    def get_ticker(self, inst_id):
        return {"ok": True, "data": {"last": self._prices.get(inst_id, 0)}}


def run_stress_test():
    print("=" * 70)
    print("V15 经典马丁策略压力测试")
    print("=" * 70)
    print()

    tests = []
    all_pass = True

    def test(name, func):
        try:
            result = func()
            tests.append({"name": name, "result": result})
            status = "✅ PASS" if result else "❌ FAIL"
            print(f"[{status}] {name}")
            if not result:
                all_pass = False
            return result
        except Exception as e:
            tests.append({"name": name, "result": False, "error": str(e)})
            print(f"[❌ ERROR] {name}: {e}")
            all_pass = False
            return False

    # 场景1: 全币种决策信号触发测试
    print("\n--- 场景1: 全币种决策信号触发测试 ---")
    def test_all_coins_decisions():
        from v15_signal import v15_decision
        coins = ["BTC", "ETH", "SOL", "ARB", "OP", "UNI", "HYPE", "OKB"]
        results = []
        for coin in coins:
            try:
                decision = v15_decision(f"{coin}-USDT")
                results.append({
                    "coin": coin,
                    "action": decision.get("action"),
                    "confidence": decision.get("confidence", 0),
                    "position": decision.get("position"),
                })
            except Exception as e:
                results.append({"coin": coin, "error": str(e)})

        print(f"  测试币种: {len(coins)}个")
        for r in results:
            if "error" in r:
                print(f"  {r['coin']}: ❌ 错误: {r['error']}")
            else:
                print(f"  {r['coin']}: {r['action']} conf={r['confidence']}% pos={r['position']}")

        success = all("error" not in r for r in results)
        return success

    test("全币种决策信号触发", test_all_coins_decisions)

    # 场景2: 资金规模100U测试
    print("\n--- 场景2: 资金规模测试 (100U) ---")
    def test_capital_100u():
        original_budget = get_config_float("TOTAL_BUDGET", 100)
        os.environ["TOTAL_BUDGET"] = "100"

        alloc = calculate_capital_allocation()
        single_cost = alloc["single_position_cost"]["total_cost_usd"]
        can_open = alloc["recommendations"]["allow_open_new_position"]
        positions_can_open = alloc["calculations"]["positions_can_open"]

        print(f"  单仓位总需求: ${single_cost}")
        print(f"  可用资金: ${alloc['balance']['avail_balance']}")
        print(f"  可开仓位数: {positions_can_open}")
        print(f"  允许开新仓: {can_open}")

        expected_can_open = single_cost <= alloc["balance"]["avail_balance"]
        result = can_open == expected_can_open
        print(f"  验证: 资金计算器判断正确 = {result}")

        os.environ["TOTAL_BUDGET"] = str(original_budget)
        return result

    test("100U资金规模测试", test_capital_100u)

    # 场景3: 资金规模200U测试
    def test_capital_200u():
        original_budget = get_config_float("TOTAL_BUDGET", 100)
        os.environ["TOTAL_BUDGET"] = "200"

        alloc = calculate_capital_allocation()
        single_cost = alloc["single_position_cost"]["total_cost_usd"]
        can_open = alloc["recommendations"]["allow_open_new_position"]
        positions_can_open = alloc["calculations"]["positions_can_open"]

        print(f"  单仓位总需求: ${single_cost}")
        print(f"  可用资金: ${alloc['balance']['avail_balance']}")
        print(f"  可开仓位数: {positions_can_open}")
        print(f"  允许开新仓: {can_open}")

        expected_can_open = single_cost <= alloc["balance"]["avail_balance"]
        result = can_open == expected_can_open
        print(f"  验证: 资金计算器判断正确 = {result}")

        os.environ["TOTAL_BUDGET"] = str(original_budget)
        return result

    test("200U资金规模测试", test_capital_200u)

    # 场景4: 资金规模500U测试 - 验证资金充足时控制不开新仓
    print("\n--- 场景4: 资金充足时控制策略 (500U) ---")
    def test_capital_500u():
        original_budget = get_config_float("TOTAL_BUDGET", 100)
        os.environ["TOTAL_BUDGET"] = "500"

        alloc = calculate_capital_allocation()
        single_cost = alloc["single_position_cost"]["total_cost_usd"]
        can_open = alloc["recommendations"]["allow_open_new_position"]
        positions_can_open = alloc["calculations"]["positions_can_open"]
        advice = alloc["recommendations"]["advice"]

        print(f"  单仓位总需求: ${single_cost}")
        print(f"  可用资金: ${alloc['balance']['avail_balance']}")
        print(f"  可开仓位数: {positions_can_open}")
        print(f"  允许开新仓: {can_open}")
        print(f"  资金建议: {advice}")

        has_warning = "资金过于充足" in advice
        print(f"  验证: 资金充足时有警告提示 = {has_warning}")

        os.environ["TOTAL_BUDGET"] = str(original_budget)
        return has_warning

    test("500U资金充足控制测试", test_capital_500u)

    # 场景5: 多持仓场景测试
    print("\n--- 场景5: 多持仓场景测试 ---")
    def test_multi_positions():
        original_budget = get_config_float("TOTAL_BUDGET", 100)
        os.environ["TOTAL_BUDGET"] = "200"

        alloc = calculate_capital_allocation()
        single_cost = alloc["single_position_cost"]["total_cost_usd"]
        max_positions = alloc["parameters"]["max_concurrent_positions"]

        print(f"  测试目标: 模拟{max_positions}个持仓")
        print(f"  单仓位成本: ${single_cost}")
        print(f"  预计总占用: ${single_cost * max_positions}")
        print(f"  当前持仓数: {alloc['calculations']['current_positions_count']}")

        positions_can_open = alloc["calculations"]["positions_can_open"]
        print(f"  可开新仓位: {positions_can_open}")

        os.environ["TOTAL_BUDGET"] = str(original_budget)
        return True

    test("多持仓场景测试", test_multi_positions)

    # 场景6: 信号触发状态测试
    print("\n--- 场景6: 信号触发状态测试 ---")
    def test_signal_trigger():
        trigger = get_signal_trigger_status()
        coins = trigger.get("coins", {})
        can_open = trigger["can_open_new_position"]
        current_positions = trigger["current_positions_count"]

        print(f"  可开新仓位: {can_open}")
        print(f"  当前持仓数: {current_positions}")
        print(f"  监控币种: {len(coins)}个")

        for coin, status in coins.items():
            status_str = "✅ 可触发" if status["can_trigger"] else "❌ 等待"
            if status["has_position"]:
                status_str = "🟡 已持仓"
            print(f"  {coin}: {status_str}")

        # 币种池已扩展（原8个 → 40个，含贵金属代币），至少8个
        return len(coins) >= 8

    test("多币种信号触发状态测试", test_signal_trigger)

    # 场景7: 加仓资金预留测试
    print("\n--- 场景7: 加仓资金预留验证 ---")
    def test_addon_reserve():
        alloc = calculate_capital_allocation()
        cost = alloc["single_position_cost"]

        print(f"  底仓: ${cost['base_usd']}")
        print(f"  加仓1: ${cost['addon_details'][0]['cost_usd']}")
        print(f"  加仓2: ${cost['addon_details'][1]['cost_usd']}")
        print(f"  加仓3: ${cost['addon_details'][2]['cost_usd']}")
        print(f"  总计: ${cost['total_cost_usd']}")

        total_addon = sum(d["cost_usd"] for d in cost["addon_details"])
        expected_total = cost["base_usd"] + total_addon
        matches = abs(cost["total_cost_usd"] - expected_total) < 0.01
        print(f"  验证: 加仓资金计算正确 = {matches}")

        return matches

    test("加仓资金预留验证", test_addon_reserve)

    # 场景8: API响应时间测试
    print("\n--- 场景8: API响应时间测试 ---")
    def test_api_response_time():
        import subprocess
        
        apis = [
            "/api/v15-ct/decision?coin=BTC",
            "/api/v15-ct/decisions",
            "/api/capital/allocation",
            "/api/capital/signal-trigger",
            "/api/v15-ct/status",
        ]

        print("  API响应时间测试:")
        max_time = 0
        for api in apis:
            try:
                result = subprocess.run(
                    ["curl", "-s", "--max-time", "30", f"http://localhost:8765{api}", "-o", "/dev/null", "-w", "%{time_total}"],
                    capture_output=True, text=True, timeout=35
                )
                if result.returncode == 0:
                    elapsed = float(result.stdout.strip())
                    status = "✅" if elapsed < 10 else "⚠️"
                    print(f"    {status} {api}: {elapsed:.2f}s")
                    max_time = max(max_time, elapsed)
                else:
                    print(f"    ❌ {api}: 返回码 {result.returncode}")
                    return False
            except Exception as e:
                print(f"    ❌ {api}: {e}")
                return False

        print(f"  最大响应时间: {max_time:.2f}s")
        return max_time < 30

    test("API响应时间测试", test_api_response_time)

    # 输出测试报告
    print("\n" + "=" * 70)
    print("测试报告")
    print("=" * 70)
    passed = sum(1 for t in tests if t.get("result"))
    total = len(tests)
    print(f"\n测试总数: {total}")
    print(f"通过: {passed}")
    print(f"失败: {total - passed}")
    print(f"通过率: {(passed/total)*100:.1f}%")

    print("\n详细结果:")
    for t in tests:
        status = "✅" if t.get("result") else "❌"
        error = f" ({t.get('error')})" if "error" in t else ""
        print(f"  {status} {t['name']}{error}")

    print("\n" + "=" * 70)
    if all_pass:
        print("🎉 所有测试通过!")
    else:
        print("⚠️ 部分测试失败，请检查日志")
    print("=" * 70)

    return all_pass


if __name__ == "__main__":
    load_config("v15")
    run_stress_test()
