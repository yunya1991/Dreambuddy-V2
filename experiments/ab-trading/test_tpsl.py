#!/usr/bin/env python3
"""止盈止损功能测试脚本 - 模拟模式"""

from execution.aster_spot import HyperliquidClient
from execution.onchain_tpsl import get_position_tpsl_status, ensure_tpsl, remove_tpsl

def test_tpsl(agent_id):
    print('='*60)
    print(f'止盈止损功能测试 - Agent {agent_id.upper()}')
    print('='*60)

    client = HyperliquidClient(agent_id)

    print(f'\n[1] 查询仓位 TP/SL 状态')
    status = get_position_tpsl_status(client, 'BTC')
    print(f'    有仓位: {status["has_position"]}')
    print(f'    SL价格: {status["sl_price"]}')
    print(f'    TP价格: {status["tp_price"]}')
    print(f'    条件单数: {status["count"]}')

    print(f'\n[2] 获取账户状态')
    acct = client.get_account()
    print(f'    权益: ${acct["equity"]:.2f} USDC')
    print(f'    持仓: {list(acct["positions"].keys())}')

    if acct["positions"]:
        print(f'\n[3] 测试 TP/SL 状态查询（有持仓）')
        for coin in acct["positions"].keys():
            pos = acct["positions"][coin]
            print(f'    仓位 {coin}: sz={pos["size"]}, entry={pos["entry_px"]:.2f}')
            status = get_position_tpsl_status(client, coin)
            print(f'        SL: {status["sl_price"]}, TP: {status["tp_price"]}')
    else:
        print(f'\n[3] 无持仓，跳过 TP/SL 设置测试')
        print(f'    提示: 开仓后才能设置止盈止损')

    print(f'\n[4] 获取所有挂单')
    all_orders = client.get_open_orders()
    print(f'    总挂单数: {len(all_orders)}')
    for o in all_orders:
        o_type = "限价单"
        if o.get("trigger"):
            o_type = "条件单(TP/SL)"
        print(f'    - {o.get("coin")}: oid={o.get("oid")}, type={o_type}')

    print(f'\n' + '='*60)
    print(f'✅ Agent {agent_id.upper()} TP/SL 功能测试完成')
    print('='*60)

if __name__ == '__main__':
    test_tpsl('a')
    print()
    test_tpsl('b')