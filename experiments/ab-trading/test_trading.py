#!/usr/bin/env python3
"""交易功能测试脚本 - 模拟模式，不实际下单"""

from execution.aster_spot import HyperliquidClient

def test_trading(agent_id):
    print('='*60)
    print(f'交易功能测试 - Agent {agent_id.upper()} (模拟模式)')
    print('='*60)

    client = HyperliquidClient(agent_id)

    print(f'\n[1] 获取账户状态')
    acct = client.get_account()
    print(f'    权益: ${acct["equity"]:.2f} USDC')
    print(f'    可用: ${acct["avail"]:.2f} USDC')
    print(f'    模式: {acct["mode"]}')
    print(f'    持仓: {list(acct["positions"].keys())}')

    print(f'\n[2] 获取市场价格')
    mids = client.get_all_mids()
    for coin in ['BTC', 'ETH', 'SOL', 'HYPE', 'AVAX']:
        print(f'    {coin}: ${mids.get(coin, 0):,.2f}')

    print(f'\n[3] 获取挂单')
    orders = client.get_open_orders()
    print(f'    挂单数量: {len(orders)}')
    for o in orders:
        print(f'    - {o.get("coin")}: oid={o.get("oid")}')

    print(f'\n[4] 设置杠杆测试 (BTC, 3x)')
    try:
        result = client.set_leverage('BTC', 3)
        print(f'    结果: {result.get("status")}')
    except Exception as e:
        print(f'    错误: {e}')

    print(f'\n[5] 开仓参数计算测试')
    px = mids.get('BTC', 0)
    usdt_amount = 3.0
    leverage = 3
    sz = usdt_amount * leverage / px
    min_sz = 11 / px
    print(f'    BTC价格: ${px:,.2f}')
    print(f'    名义金额: ${usdt_amount:.2f} USDT')
    print(f'    杠杆: {leverage}x')
    print(f'    计算数量: {sz:.6f}')
    print(f'    最小数量: {min_sz:.6f}')
    print(f'    实际数量: {max(sz, min_sz):.6f}')

    print(f'\n[6] 现货余额查询')
    spot = client.get_spot_balance()
    print(f'    USDC可用: ${spot.get("usdc_avail", 0):.2f}')
    for coin, bal in spot.get('balances', {}).items():
        print(f'    {coin}: total={bal["total"]:.4f}, avail={bal["avail"]:.4f}')

    print(f'\n[7] 机会扫描')
    opps = client.scan_opportunities()
    for o in opps[:5]:
        fr = o['funding'] * 100
        signal = f"→{o['funding_dir']}" if o['funding_signal'] else ""
        print(f'    {o["coin"]:6s} ${o["price"]:>12,.2f}  资金费率:{fr:+.4f}% {signal}')

    print(f'\n' + '='*60)
    print(f'✅ Agent {agent_id.upper()} 交易功能测试完成（模拟模式）')
    print('='*60)

if __name__ == '__main__':
    test_trading('a')
    print()
    test_trading('b')