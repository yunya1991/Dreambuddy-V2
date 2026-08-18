"""历史数据获取测试

测试OKX history-candles接口能否获取2-3年的历史数据。
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from data.market_data import fetch_historical_candles


def main():
    print("=" * 60)
    print("  OKX 历史数据获取测试")
    print("=" * 60)

    symbols = [
        ("BTC-USDT", "BTC"),
        ("ETH-USDT", "ETH"),
        ("SOL-USDT", "SOL"),
        ("UNI-USDT", "UNI"),
    ]

    for inst_id, name in symbols:
        print(f"\n{'='*50}")
        print(f"  {name}")
        print(f"{'='*50}")

        candles = fetch_historical_candles(inst_id, bar="1D", days=730)

        if candles:
            import datetime
            start_dt = datetime.datetime.fromtimestamp(candles[0]["ts"] / 1000)
            end_dt = datetime.datetime.fromtimestamp(candles[-1]["ts"] / 1000)
            duration_days = (end_dt - start_dt).days

            print(f"\n  结果:")
            print(f"    数据条数: {len(candles)}")
            print(f"    时间范围: {start_dt.strftime('%Y-%m-%d')} ~ {end_dt.strftime('%Y-%m-%d')}")
            print(f"    跨度: {duration_days} 天")
            print(f"    最新价格: {candles[-1]['c']:.2f} USDT")

            # 检查数据连续性
            gaps = 0
            for i in range(1, len(candles)):
                expected_gap = 24 * 60 * 60 * 1000  # 1天
                actual_gap = candles[i]["ts"] - candles[i-1]["ts"]
                if actual_gap > expected_gap * 1.5:
                    gaps += 1
                    if gaps <= 5:
                        prev_dt = datetime.datetime.fromtimestamp(candles[i-1]["ts"] / 1000)
                        curr_dt = datetime.datetime.fromtimestamp(candles[i]["ts"] / 1000)
                        print(f"    缺口: {prev_dt.strftime('%Y-%m-%d')} -> {curr_dt.strftime('%Y-%m-%d')}")

            if gaps > 0:
                print(f"    总缺口数: {gaps}")
            else:
                print(f"    数据连续性: 良好")

            # 保存数据
            save_path = f"data/historical/{name}_1D_730d.json"
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            import json
            with open(save_path, "w") as f:
                json.dump(candles, f)
            print(f"    数据已保存: {save_path}")
        else:
            print(f"    数据获取失败")


if __name__ == "__main__":
    main()
