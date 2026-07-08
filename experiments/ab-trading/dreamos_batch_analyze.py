#!/usr/bin/env python3
import requests
import json
import time
import datetime

SYMBOLS = ["BTC", "ETH", "SOL", "AVAX", "LINK", "DOT", "MATIC", "BNB", "OP", "ARB"]
API_URL = "http://localhost:8765/api/dreamos/analyze"


def analyze_symbol(symbol: str) -> dict:
    try:
        print(f"⏳ 正在分析 {symbol}...")
        start = time.time()
        response = requests.get(f"{API_URL}?symbol={symbol}", timeout=120)
        elapsed = time.time() - start
        if response.status_code == 200:
            result = response.json()
            result["_elapsed_ms"] = int(elapsed * 1000)
            action = result.get("action", "UNKNOWN")
            confidence = result.get("confidence", 0)
            print(f"✅ {symbol} 分析完成 [{elapsed:.2f}s] -> {action} (置信度: {confidence:.3f})")
            return result
        else:
            print(f"❌ {symbol} 分析失败: HTTP {response.status_code}")
            return {"error": f"HTTP {response.status_code}", "symbol": symbol}
    except Exception as e:
        print(f"❌ {symbol} 分析异常: {str(e)}")
        return {"error": str(e), "symbol": symbol}


def main():
    print("=" * 60)
    print("Dream OS 批量分析任务启动")
    print(f"时间: {datetime.datetime.now().isoformat()}")
    print(f"币种列表: {', '.join(SYMBOLS)}")
    print("=" * 60)

    results = []
    for i, symbol in enumerate(SYMBOLS, 1):
        print(f"\n[{i}/{len(SYMBOLS)}]")
        result = analyze_symbol(symbol)
        results.append(result)
        time.sleep(2)

    print("\n" + "=" * 60)
    print("批量分析完成，汇总结果:")
    print("=" * 60)

    long_count = sum(1 for r in results if r.get("action") == "LONG")
    short_count = sum(1 for r in results if r.get("action") == "SHORT")
    hold_count = sum(1 for r in results if r.get("action") == "HOLD")
    error_count = sum(1 for r in results if "error" in r)

    for r in results:
        symbol = r.get("symbol", "UNKNOWN")
        action = r.get("action", "UNKNOWN")
        confidence = r.get("confidence", 0)
        elapsed = r.get("_elapsed_ms", 0)
        status = "✅" if action != "UNKNOWN" and "error" not in r else "❌"
        print(f"{status} {symbol:6s} -> {action:5s}  置信度: {confidence:.3f}  耗时: {elapsed}ms")

    print("\n📊 统计:")
    print(f"   LONG: {long_count}")
    print(f"   SHORT: {short_count}")
    print(f"   HOLD: {hold_count}")
    print(f"   ERROR: {error_count}")

    summary_file = f"/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/data/agent_c_b/batch_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(summary_file, "w") as f:
        json.dump({
            "timestamp": datetime.datetime.now().isoformat(),
            "symbols": SYMBOLS,
            "results": results,
            "summary": {
                "long": long_count,
                "short": short_count,
                "hold": hold_count,
                "error": error_count
            }
        }, f, indent=2, default=str)

    print(f"\n📁 汇总日志已保存: {summary_file}")


if __name__ == "__main__":
    main()