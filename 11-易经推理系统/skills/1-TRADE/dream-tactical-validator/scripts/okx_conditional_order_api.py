#!/usr/bin/env python3
"""
OKX计划委托（Conditional Order）放置脚本
通过直接调用OKX REST API实现
"""

import sys
import json
import time
import hmac
import base64
import requests
from datetime import datetime, timezone

# 读取配置
import tomllib
with open('/Users/zhangjiangtao/.okx/config.toml', 'rb') as f:
    config = tomllib.load(f)

profile = config['profiles']['dreamdemo']
API_KEY = profile['api_key']
SECRET_KEY = profile['secret_key']
PASSPHRASE = profile['passphrase']
IS_DEMO = profile.get('demo', True)

# OKX API 基础URL
BASE_URL = "https://www.okx.com" if not IS_DEMO else "https://www.okx.com"

def sign_prehash(timestamp, method, request_path, body=''):
    """生成OKX API签名"""
    if body:
        prehash = timestamp + method + request_path + body
    else:
        prehash = timestamp + method + request_path
    
    secret_bytes = SECRET_KEY.encode('utf-8')
    message = prehash.encode('utf-8')
    h = hmac.new(secret_bytes, message, digestmod='sha256')
    signature = base64.b64encode(h.digest()).decode('utf-8')
    return signature

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
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
    method = 'POST'
    request_path = '/api/v5/trade/order-algo'
    
    body_dict = {
        "instId": inst_id,
        "tdMode": "isolated",  # 逐仓
        "side": side,
        "ordType": "trigger",  # 计划委托（独立订单）
        "triggerPx": str(trigger_px),
        "orderPx": str(order_px),
        "sz": str(size),
        "posSide": pos_side
    }
    
    body = json.dumps(body_dict)
    
    signature = sign_prehash(timestamp, method, request_path, body)
    
    headers = {
        "OK-ACCESS-KEY": API_KEY,
        "OK-ACCESS-SIGN": signature,
        "OK-ACCESS-TIMESTAMP": timestamp,
        "OK-ACCESS-PASSPHRASE": PASSPHRASE,
        "Content-Type": "application/json",
        "x-simulated-trading": "1"  # Demo账户标记
    }
    
    url = BASE_URL + request_path
    
    try:
        response = requests.post(url, headers=headers, data=body)
        return response.json()
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
