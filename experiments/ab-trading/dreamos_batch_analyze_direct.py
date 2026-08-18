#!/usr/bin/env python3
import json
import time
import datetime
import sys
from pathlib import Path

sys.path.insert(0, "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE")
sys.path.insert(0, "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2")
from experiments.agent_c.agent_c import AgentC

SYMBOLS = ["BTC", "ETH", "SOL", "AVAX", "LINK", "DOT", "MATIC", "BNB", "OP", "ARB"]


def analyze_symbol(agent, symbol: str) -> dict:
    try:
        print(f"⏳ 正在分析 {symbol}...")
        start = time.time()
        mkt_data = agent.fetch_market_data(symbol)
        if not mkt_data:
            elapsed = time.time() - start
            print(f"❌ {symbol} 获取市场数据失败")
            return {"error": "无法获取市场数据", "symbol": symbol, "_elapsed_ms": int(elapsed * 1000)}
        
        decision = agent.analyze(symbol, mkt_data)
        elapsed = time.time() - start
        decision["_elapsed_ms"] = int(elapsed * 1000)
        
        action = decision.get("action", "UNKNOWN")
        confidence = decision.get("confidence", 0)
        print(f"✅ {symbol} 分析完成 [{elapsed:.2f}s] -> {action} (置信度: {confidence:.3f})")
        
        return decision
    except Exception as e:
        print(f"❌ {symbol} 分析异常: {str(e)}")
        return {"error": str(e), "symbol": symbol}


def main():
    print("=" * 60)
    print("Dream OS 批量分析任务启动 (直接调用AgentC)")
    print(f"时间: {datetime.datetime.now().isoformat()}")
    print(f"币种列表: {', '.join(SYMBOLS)}")
    print("=" * 60)

    agent = AgentC(agent_id='b')
    
    results = []
    for i, symbol in enumerate(SYMBOLS, 1):
        print(f"\n[{i}/{len(SYMBOLS)}]")
        result = analyze_symbol(agent, symbol)
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

    history_dir = Path(__file__).parent / "data" / "agent_c_b"
    history_dir.mkdir(parents=True, exist_ok=True)
    summary_file = history_dir / f"batch_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
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
