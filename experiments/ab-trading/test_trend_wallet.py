#!/usr/bin/env python3
"""测试趋势策略 Aster 钱包连接"""
import requests

HL_INFO = "https://api.hyperliquid.xyz/info"

def test_clearinghouse(addr, label):
    print(f"\n{'='*60}")
    print(f"测试 {label}")
    print(f"  地址: {addr}")
    print(f"{'='*60}")
    try:
        payload = {"type": "clearinghouseState", "user": addr}
        r = requests.post(HL_INFO, json=payload, timeout=15)
        print(f"  HTTP 状态: {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            margin = data.get("marginSummary", {})
            equity = margin.get("accountValue", "N/A")
            positions = data.get("assetPositions", [])
            print(f"  ✅ 连接成功！")
            print(f"     账户权益: {equity} USDC")
            print(f"     持仓数量: {len(positions)}")
            for p in positions:
                pos = p.get("position", {})
                print(f"       - {pos.get('coin')}: size={pos.get('szi')}, entry={pos.get('entryPx')}, upnl={pos.get('unrealizedPnl')}")
            return True
        else:
            print(f"  ❌ 失败: {r.status_code} - {r.text[:200]}")
            return False
    except Exception as e:
        print(f"  ❌ 异常: {e}")
        return False

if __name__ == "__main__":
    test_clearinghouse("0x6632da9c91A959eEBf1343f8AFAbf2807414004A", "趋势策略 Aster 钱包")
