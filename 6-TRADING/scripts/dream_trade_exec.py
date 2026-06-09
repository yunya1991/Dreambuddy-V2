#!/usr/bin/env python3
"""Dream-MultiSkill 交易执行 - Step 4 & 5"""
import requests, json, time, hmac, base64, hashlib

api_key = "f9d0221c-b26a-48eb-b248-88b3d600eccd"
secret_key = "05912564EBA86936B3E799138A5DA502"
passphrase = "Zjt@199107293419"
base_url = "https://www.okx.com"

def get_headers(method, path, body=""):
    ts = time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime())
    msg = ts + method + path + body
    mac = hmac.new(secret_key.encode('utf-8'), msg.encode('utf-8'), hashlib.sha256)
    sign = base64.b64encode(mac.digest()).decode('utf-8')
    return {
        'OK-ACCESS-KEY': api_key, 'OK-ACCESS-SIGN': sign,
        'OK-ACCESS-TIMESTAMP': ts, 'OK-ACCESS-PASSPHRASE': passphrase,
        'Content-Type': 'application/json'
    }

def okx_get(path, params=None):
    sign_path = path
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        sign_path = path + "?" + qs
    headers = get_headers("GET", sign_path)
    resp = requests.get(base_url + path, params=params, headers=headers, timeout=15)
    return resp.json()

def okx_post(path, body_dict):
    body = json.dumps(body_dict)
    headers = get_headers("POST", path, body)
    resp = requests.post(base_url + path, data=body, headers=headers, timeout=15)
    return resp.json()

def main():
    # 1. 账户状态
    print("=== 账户状态 ===")
    bal = okx_get("/api/v5/account/balance")
    if bal.get('code') != '0':
        print(f"Error: {bal}")
        return
    acct = bal['data'][0]
    total_eq = float(acct['totalEq'])
    print(f"总权益: {total_eq:.2f} USDT")

    usdt_detail = None
    for d in acct.get('details', []):
        if d.get('ccy') == 'USDT':
            usdt_detail = d
            break
    if usdt_detail:
        avail = float(usdt_detail.get('availBal', 0))
        print(f"USDT可用: {avail:.2f}")
    
    # 2. 当前持仓
    print("\n=== 当前持仓 ===")
    pos = okx_get("/api/v5/account/positions", {"instType": "SWAP"})
    has_pos = False
    if pos.get('data'):
        for p in pos['data']:
            if float(p.get('pos', 0)) > 0:
                has_pos = True
                print(f"  {p['instId']} | {p['posSide']} | qty:{p['pos']} | avgPx:{p['avgPx']} | upl:{p['upl']}")
    if not has_pos:
        print("  无持仓")

    # 3. 检查杠杆设置
    inst_id = "BTC-USDT-SWAP"
    print(f"\n=== {inst_id} 杠杆设置 ===")
    lever = okx_get("/api/v5/account/leverage-info", {"instId": inst_id, "mgnMode": "isolated"})
    if lever.get('data'):
        for l in lever['data']:
            print(f"  posSide:{l.get('posSide')} | lever:{l.get('lever')}")
    
    # 4. 设置杠杆
    print("\n=== 设置杠杆 ===")
    # 先设为3x多仓
    set_lev = okx_post("/api/v5/account/set-leverage", {
        "instId": inst_id,
        "lever": "3",
        "mgnMode": "isolated",
        "posSide": "long"
    })
    print(f"  设置3x多仓杠杆: code={set_lev.get('code')} msg={set_lev.get('msg')}")

    # 5. 下单
    if not has_pos and avail and avail > 200:
        print("\n=== 下单做多 ===")
        # 1张 BTC-USDT-SWAP = 0.01 BTC, 面值约 771.5 USDT
        # 3x杠杆, 保证金约 257 USDT
        sz = "1"  # 1张
        order = okx_post("/api/v5/trade/order", {
            "instId": inst_id,
            "tdMode": "isolated",
            "side": "buy",
            "ordType": "market",
            "sz": sz,
            "posSide": "long"
        })
        print(f"  下单结果: code={order.get('code')} msg={order.get('msg')}")
        if order.get('data'):
            for o in order['data']:
                print(f"  订单ID: {o.get('ordId')}")
                print(f"  状态: {o.get('sCode')} - {o.get('sMsg')}")
                ord_id = o.get('ordId')
        
        # 6. 设置止损
        if ord_id:
            print("\n=== 设置止损 (Algo) ===")
            sl_price = "76294"  # ATR-based
            sl_algo = okx_post("/api/v5/trade/order-algo", {
                "instId": inst_id,
                "tdMode": "isolated",
                "side": "sell",
                "ordType": "conditional",
                "sz": sz,
                "posSide": "long",
                "slTriggerPx": sl_price,
                "slOrdPx": "-1",  # 市价
                "slTriggerPxType": "mark"
            })
            print(f"  止损: code={sl_algo.get('code')} msg={sl_algo.get('msg')}")
            if sl_algo.get('data'):
                for a in sl_algo['data']:
                    print(f"  Algo ID: {a.get('algoId')}")

            # 7. 设置止盈
            print("\n=== 设置止盈 (Algo) ===")
            tp_price = "79716"
            tp_algo = okx_post("/api/v5/trade/order-algo", {
                "instId": inst_id,
                "tdMode": "isolated",
                "side": "sell",
                "ordType": "conditional",
                "sz": sz,
                "posSide": "long",
                "tpTriggerPx": tp_price,
                "tpOrdPx": "-1",
                "tpTriggerPxType": "mark"
            })
            print(f"  止盈: code={tp_algo.get('code')} msg={tp_algo.get('msg')}")
            if tp_algo.get('data'):
                for a in tp_algo['data']:
                    print(f"  Algo ID: {a.get('algoId')}")

        print("\n=== 完成 ===")
    elif has_pos:
        print("\n=== 已有持仓，不重复开仓 ===")
    else:
        print("\n=== 可用余额不足 ===")

if __name__ == "__main__":
    main()
