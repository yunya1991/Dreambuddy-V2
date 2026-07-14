#!/usr/bin/env python3
"""
V15 经典马丁策略 — 统一入口脚本

用法:
  python3 run.py signal [COIN]          查看单币种/全币种信号
  python3 run.py backtest [COIN] [N]    回测（默认BTC, 500根K线）
  python3 run.py trader                 启动自动交易器
  python3 run.py capital                查看资金管理状态
  python3 run.py test                   运行全部测试
  python3 run.py config                 查看当前配置
"""
import sys
import os
import json
import argparse
from pathlib import Path

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR / "lib"))
sys.path.insert(0, str(BASE_DIR / "core"))


def cmd_signal(args):
    """查看交易信号"""
    from v15_signal import v15_decision
    from config_loader import get_config_list
    from symbol_mapper import to_spot, is_supported

    coins = args.coins.split(",") if args.coins else get_config_list("V15_COINS", default=["BTC"])

    print("=" * 70)
    print("V15 经典马丁策略 — 信号决策")
    print("=" * 70)

    for coin in coins:
        coin = coin.strip().upper()
        if not is_supported(coin, "okx"):
            print(f"\n  {coin} | ⚠️  OKX 不支持此币种，跳过")
            continue
        inst = to_spot(coin)
        try:
            result = v15_decision(inst)
            action_icon = {
                "OPEN_BULL": "🟢 LONG",
                "OPEN_BEAR": "🔴 SHORT",
                "WAIT": "⏳ WAIT",
            }.get(result["action"], result["action"])

            print(f"\n{'─' * 50}")
            print(f"  {coin} | {action_icon} | 置信度: {result['confidence']}%")
            print(f"  位置: {result['position']} | RSI: {result.get('rsi', 'N/A')} | vol_mult: {result['vol_mult']}")
            if result.get("fib_zone"):
                print(f"  Fib区: {result['fib_zone']}")
            if result.get("boll_signal"):
                print(f"  布林信号: {result['boll_signal']}")
            if result.get("trend_signal"):
                print(f"  趋势信号: {result['trend_signal']}")
            print(f"  理由:")
            for r in result["reasons"]:
                print(f"    • {r}")
        except Exception as e:
            print(f"\n  {coin} | ❌ 错误: {e}")

    print(f"\n{'─' * 50}")


def cmd_backtest(args):
    """运行回测"""
    from v15_backtest import run_backtest

    coin = args.coin or "BTC"

    print("=" * 70)
    print(f"V15 经典马丁策略 — 回测 | {coin}")
    print("=" * 70)

    try:
        result = run_backtest(coin)
        if result:
            print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        else:
            print("回测完成（无返回值）")
    except Exception as e:
        print(f"回测失败: {e}")
        import traceback
        traceback.print_exc()


def cmd_trader(args):
    """启动自动交易器"""
    from v15_trader import main as trader_main
    print("=" * 70)
    print("V15 经典马丁策略 — 自动交易器")
    print("=" * 70)
    trader_main()


def cmd_poll_once(args):
    """单次执行轮询（用于定时调度）"""
    from v15_trader import run_poll_cycle
    run_poll_cycle()


def cmd_capital(args):
    """查看资金管理状态"""
    from capital_manager import calculate_capital_allocation, get_signal_trigger_status, calculate_single_position_cost

    print("=" * 70)
    print("V15 经典马丁策略 — 资金管理")
    print("=" * 70)

    try:
        cost = calculate_single_position_cost()
        print(f"\n单仓位成本:")
        print(f"  底仓: ${cost['base_usd']:.2f}")
        print(f"  总成本(含3次加仓): ${cost['total_cost_usd']:.2f}")
        print(f"  预算来源: {cost.get('budget_source', 'unknown')} (${cost.get('budget_value', 0):.2f})")
    except Exception as e:
        print(f"成本计算失败: {e}")

    try:
        alloc = calculate_capital_allocation()
        params = alloc.get('parameters', {})
        calcs = alloc.get('calculations', {})
        recs = alloc.get('recommendations', {})
        balance = alloc.get('balance', {})
        print(f"\n资金分配:")
        print(f"  总预算(动态): ${params.get('total_budget', 'N/A')}")
        print(f"  预算模式: {params.get('budget_mode', 'N/A')}")
        print(f"  账户余额: ${balance.get('total_eq', 'N/A')}")
        print(f"  可用余额: ${balance.get('avail_balance', 'N/A')}")
        print(f"  已用保证金: ${balance.get('used_margin', 'N/A')}")
        print(f"\n建议:")
        print(f"  允许开新仓: {recs.get('allow_open_new_position', 'N/A')}")
        print(f"  允许加仓: {recs.get('allow_addon', 'N/A')}")
        print(f"  风险等级: {recs.get('risk_level', 'N/A')}")
        print(f"  说明: {recs.get('advice', 'N/A')}")
    except Exception as e:
        print(f"资金分配计算失败: {e}")

    try:
        trigger = get_signal_trigger_status()
        print(f"\n信号触发状态:")
        for k, v in trigger.items():
            print(f"  {k}: {v}")
    except Exception as e:
        print(f"信号触发状态获取失败: {e}")


def cmd_capital_engine(args):
    """资金管理引擎（月度优化/状态/趋势/检查/API）"""
    from capital_manager_engine import CapitalManagerEngine
    import json

    engine = CapitalManagerEngine()

    if args.action == "monthly":
        coins = args.coins.split(",") if args.coins else None
        print("=" * 70)
        print("V15 经典马丁策略 — 资金管理引擎 · 月度优化")
        print("=" * 70)
        result = engine.run_monthly(coins)
        print("\n月度优化完成！")

    elif args.action == "status":
        status = engine.get_status()
        print("=" * 70)
        print("V15 经典马丁策略 — 资金管理引擎状态")
        print("=" * 70)
        print(json.dumps(status, indent=2, ensure_ascii=False))

    elif args.action == "trend":
        if not args.coin:
            print("请指定 --coin 参数")
            sys.exit(1)
        result = engine.check_trend(args.coin.upper())
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.action == "check":
        if not args.coin:
            print("请指定 --coin 参数")
            sys.exit(1)
        result = engine.check_open_permission(args.coin.upper())
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.action == "api":
        from capital_manager_engine import CapitalManagerAPI
        port = args.port or 8770
        CapitalManagerAPI.engine = engine
        from http.server import HTTPServer
        server = HTTPServer(("0.0.0.0", port), CapitalManagerAPI)
        print(f"资金管理API服务启动: http://localhost:{port}")
        print(f"  GET  /status          - 资金管理状态")
        print(f"  GET  /params          - 当前最优参数")
        print(f"  GET  /trend/<coin>    - 趋势过滤状态")
        print(f"  GET  /check/<coin>    - 开仓许可检查")
        print(f"  GET  /history         - 优化历史")
        print(f"  POST /optimize        - 触发手动优化")
        server.serve_forever()


def cmd_test(args):
    """运行测试"""
    import subprocess

    test_dir = BASE_DIR / "tests"
    test_files = [
        "test_v15_system.py",
        "test_v15_stress.py",
        "v15_stress_test.py",
    ]

    print("=" * 70)
    print("V15 经典马丁策略 — 测试套件")
    print("=" * 70)

    all_passed = True
    for tf in test_files:
        path = test_dir / tf
        if not path.exists():
            print(f"\n⚠️  {tf} 不存在，跳过")
            continue

        print(f"\n{'─' * 50}")
        print(f"运行: {tf}")
        print(f"{'─' * 50}")
        result = subprocess.run(
            [sys.executable, str(path)],
            capture_output=False,
            env={**os.environ, "PYTHONPATH": f"{BASE_DIR / 'lib'}:{BASE_DIR / 'core'}"},
        )
        if result.returncode != 0:
            all_passed = False

    print(f"\n{'=' * 70}")
    if all_passed:
        print("✅ 全部测试通过")
    else:
        print("❌ 存在测试失败")
    print(f"{'=' * 70}")


def cmd_config(args):
    """查看当前配置"""
    from config_loader import load_config, get_config, get_config_list

    print("=" * 70)
    print("V15 经典马丁策略 — 配置")
    print("=" * 70)

    config = load_config("v15")
    for k in sorted(config.keys()):
        v = config[k]
        if "KEY" in k or "SECRET" in k or "PASSPHRASE" in k:
            v = "***" if v else "(空)"
        print(f"  {k} = {v}")

    print(f"\n监控币种: {get_config_list('V15_COINS')}")


def cmd_api(args):
    """启动V15策略HTTP API服务（支持monitor.html调用）"""
    port = args.port or 8771
    from v15_api_server import V15APIHandler
    from http.server import HTTPServer

    server = HTTPServer(("0.0.0.0", port), V15APIHandler)
    print(f"=" * 70)
    print(f"V15经典马丁策略 HTTP API服务启动: http://localhost:{port}")
    print(f"=" * 70)
    print(f"  GET  /api/v15-ct/decision?coin=BTC - 单币种决策信号")
    print(f"  GET  /api/v15-ct/status - 策略状态")
    print(f"  GET  /api/v15-ct/backtest?coin=BTC - 回测结果")
    print(f"  GET  /api/v15-ct/decisions - 多币种决策")
    print(f"  GET  /api/capital/allocation - 资金分配")
    print(f"  GET  /api/capital/signal-trigger - 信号触发状态")
    print(f"  GET  /health - 健康检查")
    print(f"=" * 70)
    server.serve_forever()


def main():
    parser = argparse.ArgumentParser(
        description="V15 经典马丁策略 — 统一入口",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 run.py signal              # 查看全部币种信号
  python3 run.py signal BTC,ETH      # 查看指定币种信号
  python3 run.py backtest BTC 1000   # BTC回测，1000根K线
  python3 run.py trader              # 启动自动交易器
  python3 run.py capital             # 查看资金管理
  python3 run.py test                # 运行全部测试
  python3 run.py config              # 查看配置
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # signal
    p_signal = subparsers.add_parser("signal", help="查看交易信号")
    p_signal.add_argument("coins", nargs="?", default="", help="币种列表，逗号分隔 (如 BTC,ETH)")

    # backtest
    p_bt = subparsers.add_parser("backtest", help="运行回测")
    p_bt.add_argument("coin", nargs="?", default="BTC", help="币种 (默认BTC)")
    p_bt.add_argument("limit", nargs="?", type=int, default=500, help="K线数量 (默认500)")

    # trader
    subparsers.add_parser("trader", help="启动自动交易器")

    # poll_once
    subparsers.add_parser("poll_once", help="单次执行轮询（用于定时调度）")

    # capital
    subparsers.add_parser("capital", help="查看资金管理状态")

    # capital_engine
    p_ce = subparsers.add_parser("capital_engine", help="资金管理引擎（月度优化/状态/趋势/检查/API）")
    p_ce.add_argument("action", choices=["monthly", "status", "trend", "check", "api"], help="操作")
    p_ce.add_argument("--coin", type=str, default=None, help="币种（trend/check模式）")
    p_ce.add_argument("--coins", type=str, default=None, help="币种列表，逗号分隔（monthly模式）")
    p_ce.add_argument("--port", type=int, default=8770, help="API端口（api模式）")

    # test
    subparsers.add_parser("test", help="运行全部测试")

    # config
    subparsers.add_parser("config", help="查看当前配置")

    # api
    p_api = subparsers.add_parser("api", help="启动V15策略HTTP API服务（支持monitor.html调用）")
    p_api.add_argument("--port", type=int, default=8771, help="API端口（默认8771）")

    args = parser.parse_args()

    if args.command == "signal":
        cmd_signal(args)
    elif args.command == "backtest":
        cmd_backtest(args)
    elif args.command == "trader":
        cmd_trader(args)
    elif args.command == "poll_once":
        cmd_poll_once(args)
    elif args.command == "capital":
        cmd_capital(args)
    elif args.command == "capital_engine":
        cmd_capital_engine(args)
    elif args.command == "test":
        cmd_test(args)
    elif args.command == "config":
        cmd_config(args)
    elif args.command == "api":
        cmd_api(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
