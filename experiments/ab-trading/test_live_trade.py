#!/usr/bin/env python3
"""实盘交易测试脚本 - 小额测试"""

import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from execution.aster_spot import HyperliquidClient
from execution.onchain_tpsl import ensure_tpsl, get_position_tpsl_status

def test_live_trade(agent_id):
    print('='*60)
    print(f'实盘交易测试 - Agent {agent_id.upper()}')
    print('='*60)

    client = HyperliquidClient(agent_id)

    # 1. 查看账户状态
    print('\n[1] 账户状态')
    acct = client.get_account()
    print(f'    权益: ${acct["equity"]:.2f} USDC')
    print(f'    可用: ${acct["avail"]:.2f} USDC')
    print(f'    持仓: {list(acct["positions"].keys()) or "无"}')

    # 2. 获取BTC价格
    print('\n[2] 获取BTC价格')
    px = client.get_mid_price('BTC')
    print(f'    BTC: ${px:,.2f}')

    # 3. 设置杠杆
    print('\n[3] 设置杠杆 BTC 3x')
    lev_result = client.set_leverage('BTC', 3)
    print(f'    结果: {lev_result.get("status")}')

    # 4. 开多 BTC - 小额测试（$3 USDT名义价值，3x杠杆）
    print('\n[4] 开多 BTC (小额测试: $3 USDT, 3x杠杆)')
    usdt_amount = 3.0
    leverage = 3
    print(f'    名义金额: ${usdt_amount * leverage:.2f}')
    print(f'    预估数量: {usdt_amount * leverage / px:.6f} BTC')

    result = client.open_long('BTC', usdt_amount, leverage, tag=f'test_{agent_id}')
    print(f'    交易结果: ok={result.get("ok")}')
    print(f'    币种: {result.get("coin")}')
    print(f'    方向: {result.get("side")}')
    print(f'    数量: {result.get("sz")}')
    print(f'    杠杆: {result.get("leverage")}x')

    filled = result.get('filled', {})
    if filled:
        if 'filled' in filled:
            f = filled['filled']
            print(f'    成交价: ${float(f.get("avgPx", 0)):,.2f}')
            print(f'    成交量: {f.get("totalSz", "")}')
        elif 'resting' in filled:
            print(f'    挂单中: oid={filled["resting"].get("oid")}')
        elif 'error' in filled:
            print(f'    错误: {filled["error"]}')

    if not result.get('ok'):
        print(f'    原始响应: {result.get("raw", {})}')
        return None

    # 5. 等待成交确认
    print('\n[5] 等待2秒确认成交...')
    time.sleep(2)

    # 6. 查看持仓
    print('\n[6] 查看持仓')
    acct2 = client.get_account()
    print(f'    权益: ${acct2["equity"]:.2f} USDC')
    print(f'    可用: ${acct2["avail"]:.2f} USDC')
    for coin, pos in acct2["positions"].items():
        print(f'    仓位 {coin}: sz={pos["size"]}, entry=${pos["entry_px"]:.2f}, '
              f'upnl=${pos["upnl"]:.2f}, lev={pos["leverage"]}x')

    # 7. 设置止盈止损
    if 'BTC' in acct2["positions"]:
        print('\n[7] 设置止盈止损')
        entry_px = acct2["positions"]["BTC"]["entry_px"]
        sl_price = round(entry_px * 0.96, 1)  # 4%止损
        tp_price = round(entry_px * 1.08, 1)  # 8%止盈
        print(f'    入场价: ${entry_px:.2f}')
        print(f'    止损价: ${sl_price:.2f} (-4%)')
        print(f'    止盈价: ${tp_price:.2f} (+8%)')

        tpsl_result = ensure_tpsl(client, 'BTC', sl_price, tp_price)
        print(f'    TP/SL结果: {tpsl_result.get("action")} ok={tpsl_result.get("ok")}')
        if tpsl_result.get('error'):
            print(f'    错误: {tpsl_result["error"]}')

    # 8. 查看最终状态
    print('\n[8] 最终账户状态')
    acct3 = client.get_account()
    print(f'    权益: ${acct3["equity"]:.2f} USDC')
    print(f'    可用: ${acct3["avail"]:.2f} USDC')
    print(f'    持仓: {list(acct3["positions"].keys()) or "无"}')

    # 9. 查看挂单（含TP/SL条件单）
    print('\n[9] 查看挂单')
    orders = client.get_open_orders()
    print(f'    挂单数: {len(orders)}')
    for o in orders:
        print(f'    - {o.get("coin")}: oid={o.get("oid")}, '
              f'px={o.get("limitPx")}, side={"买" if o.get("side")=="B" else "卖"}, '
              f'reduceOnly={o.get("reduceOnly")}')

    print('\n' + '='*60)
    print(f'✅ Agent {agent_id.upper()} 实盘交易测试完成')
    print('='*60)
    return result

if __name__ == '__main__':
    # 先测试Agent B
    test_live_trade('b')
