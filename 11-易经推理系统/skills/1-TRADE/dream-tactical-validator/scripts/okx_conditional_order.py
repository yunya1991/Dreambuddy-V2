#!/usr/bin/env python3
"""
OKX计划委托（Conditional Order）放置脚本
用途：当价格达到触发价时，自动下达委托单（开仓）

使用AlgoTradingClient放置计划委托（conditional order）
"""

import sys
import json
import time
import tomllib
from okx import AlgoTradingClient

# 读取配置
with open('/Users/zhangjiangtao/.okx/config.toml', 'rb') as f:
    config = tomllib.load(f)

profile = config['profiles']['dreamdemo']
API_KEY = profile['api_key']
SECRET_KEY = profile['secret_key']
PASSPHRASE = profile['passphrase']
IS_DEMO = profile.get('demo', True)  # demo账户

# 初始化Algo Trading客户端
client = AlgoTradingClient(API_KEY, SECRET_KEY, PASSPHRASE, IS_DEMO)

def place_conditional_order(inst_id, side, pos_side, trigger_px, order_px, size):
    """
    放置计划委托（Conditional Order）
    
    参数:
    - inst_id: 产品ID (e.g., "BTC-USDT-SWAP")
    - side: 买卖方向 ("buy" / "sell")
    - pos_side: 持仓方向 ("long" / "short" / "net")
    - trigger_px: 触发价格
    - order_px: 委托价格（如果= "-1" 则市价）
    - size: 委托数量
    """
    try:
        # 根据OKX API文档，计划委托的参数应该是：
        # ordType="conditional"
        # triggerPx: 触发价格
        # orderPx: 委托价格
        result = client.place_order(
            instId=inst_id,
            tdMode="isolated",  # 逐仓
            side=side,
            ordType="conditional",  # 计划委托
            triggerPx=str(trigger_px),
            orderPx=str(order_px),
            sz=str(size),
            posSide=pos_side,
            clOrdId=f"a4_verify_{int(time.time())}"
        )
        return result
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    # 测试：情景B - BTC跌破$75,500时追空
    print("=== 测试放置计划委托（情景B）===")
    
    result_b = place_conditional_order(
        inst_id="BTC-USDT-SWAP",
        side="sell",        # 做空
        pos_side="short",   # 空仓
        trigger_px=75500,   # 触发价：跌破$75,500
        order_px=75400,     # 委托价：$75,400
        size=0.01           # 极小验证仓
    )
    
    print(f"情景B结果: {json.dumps(result_b, indent=2, ensure_ascii=False)}")
    
    # 测试：情景C - BTC跌破$73,000时加速做空
    print("\n=== 测试放置计划委托（情景C）===")
    
    result_c = place_conditional_order(
        inst_id="BTC-USDT-SWAP",
        side="sell",        # 做空
        pos_side="short",   # 空仓
        trigger_px=73000,   # 触发价：跌破$73,000
        order_px=72800,     # 委托价：$72,800
        size=0.01           # 极小验证仓
    )
    
    print(f"情景C结果: {json.dumps(result_c, indent=2, ensure_ascii=False)}")
