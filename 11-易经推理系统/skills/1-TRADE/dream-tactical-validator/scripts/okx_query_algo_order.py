#!/usr/bin/env python3
"""
查询OKX Algo订单状态
"""

import json
import hmac
import base64
import requests
from datetime import datetime, timezone
import tomllib

# 读取配置
with open('/Users/zhangjiangtao/.okx/config.toml', 'rb') as f:
    config = tomllib.load(f)

profile = config['profiles']['dreamdemo']
API_KEY = profile['api_key']
SECRET_KEY = profile['secret_key']
PASSPHRASE = profile['passphrase']

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

def get_algo_order(algo_id):
    """查询Algo订单详情"""
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
    method = 'GET'
    request_path = f'/api/v5/trade/order-algo?algoId={algo_id}&ordType=trigger'
    
    signature = sign_prehash(timestamp, method, request_path)
    
    headers = {
        "OK-ACCESS-KEY": API_KEY,
        "OK-ACCESS-SIGN": signature,
        "OK-ACCESS-TIMESTAMP": timestamp,
        "OK-ACCESS-PASSPHRASE": PASSPHRASE,
        "x-simulated-trading": "1"
    }
    
    url = "https://www.okx.com" + request_path
    
    try:
        response = requests.get(url, headers=headers)
        return response.json()
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    # 查询情景B的订单
    algo_id_b = "3522491990468366336"
    print(f"=== 查询情景B订单 (algoId: {algo_id_b}) ===")
    result_b = get_algo_order(algo_id_b)
    print(json.dumps(result_b, indent=2, ensure_ascii=False))
    
    # 查询情景C的订单
    algo_id_c = "3522492015231528960"
    print(f"\n=== 查询情景C订单 (algoId: {algo_id_c}) ===")
    result_c = get_algo_order(algo_id_c)
    print(json.dumps(result_c, indent=2, ensure_ascii=False))
