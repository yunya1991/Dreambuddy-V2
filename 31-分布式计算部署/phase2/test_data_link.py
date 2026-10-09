#!/usr/bin/env python3
import json, urllib.request

print("═══════ 三屏趋势数据 ═══════")
try:
    with urllib.request.urlopen("http://127.0.0.1:8765/api/trend-screen?symbol=BTC", timeout=30) as r:
        d = json.loads(r.read())
    tf = d.get("timeframes", {})
    w = tf.get("weekly", {})
    day = tf.get("daily", {})
    print(f"周线趋势: {w.get('trend', 'N/A')}")
    print(f"日线趋势: {day.get('trend', 'N/A')}")
    print(f"BTC 价格: {d.get('price')}")
    print(f"三屏一致性: {d.get('trend_consistency')}")
except Exception as e:
    print(f"ERROR: {e}")

print("\n═══════ BDSM 快照数据 ═══════")
try:
    with urllib.request.urlopen("http://127.0.0.1:8765/api/bdsm/snapshot", timeout=15) as r:
        d = json.loads(r.read())
    print(f"快照时间: {str(d.get('timestamp','N/A'))[:19]}")
    coins = d.get("coins", {})
    if isinstance(coins, dict):
        print(f"监控币种数: {len(coins)}")
        for sym, data in list(coins.items())[:3]:
            score = data.get('score', 0) if isinstance(data, dict) else 'N/A'
            print(f"  {sym}: score={score}")
    else:
        print(f"coins 类型: {type(coins).__name__}, 长度: {len(coins) if hasattr(coins,'__len__') else 'N/A'}")
except Exception as e:
    print(f"ERROR: {e}")
