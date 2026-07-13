#!/usr/bin/env python3
"""比特币今日预测分析报告"""

import sys
sys.path.insert(0, '.')

from scripts.memory_l4.polling_trader import PollingTrader, _load_kline_from_okx
from scripts.memory_l4.bcrm2.anomaly_detector import HybridAnomalyDetector
import pandas as pd


def main():
    print('=' * 80)
    print('  比特币今日预测分析报告')
    print('=' * 80)
    print()

    trader = PollingTrader(
        interval=3600,
        coins=['BTC'],
        bar='1H',
        confidence_threshold=0.35,
        max_positions=1,
    )

    print('[1] BCRM推理引擎预测')
    print('-' * 60)
    inference = trader._fetch_and_infer('BTC')
    if inference.get('ok'):
        print(f'  当前价格: ${inference["price"]:,.2f}')
        direction = "做多" if inference["direction"] == "UP" else "做空"
        print(f'  预测方向: {direction}')
        print(f'  置信度: {inference["confidence"]:.2%}')
        print(f'  卦象: {inference["hexagram"]}')
        print(f'  波动率: {inference.get("volatility", 0):.4f}')
        print(f'  止损: ${inference["stop_loss_px"]:,.2f}')
        print(f'  止盈: ${inference["take_profit_px"]:,.2f}')
        print(f'  盈亏比: {inference.get("risk_reward", "N/A")}:1')
        print()

        print('[2] 八卦分析')
        print('-' * 60)
        hexagram_info = inference.get('hexagram_info', {})
        if hexagram_info:
            print(f'  上卦: {hexagram_info.get("upper_gua", "N/A")}')
            print(f'  下卦: {hexagram_info.get("lower_gua", "N/A")}')
            print(f'  变卦: {hexagram_info.get("change_gua", "N/A")}')
            print(f'  互卦: {hexagram_info.get("inter_gua", "N/A")}')
            print(f'  卦辞: {hexagram_info.get("hexagram_text", "N/A")}')
            print(f'  爻辞: {hexagram_info.get("yao_text", "N/A")}')
        print()

        print('[3] 市场状态')
        print('-' * 60)
        market_state = inference.get('market_state', {})
        if market_state:
            print(f'  市态: {market_state.get("market_mode", "N/A")}')
            print(f'  趋势强度: {market_state.get("trend_strength", "N/A")}')
            print(f'  震荡等级: {market_state.get("oscillation_level", "N/A")}')
        print()

        print('[4] 技术指标')
        print('-' * 60)
        indicators = inference.get('indicators', {})
        if indicators:
            print(f'  RSI: {indicators.get("rsi", "N/A")}')
            print(f'  MACD: {indicators.get("macd", "N/A")}')
            print(f'  ATR: {indicators.get("atr", "N/A")}')
            print(f'  Bollinger: {indicators.get("bb_position", "N/A")}')
        print()

        print('[5] 异常检测')
        print('-' * 60)
        detector = HybridAnomalyDetector()
        kline_data = _load_kline_from_okx('BTC-USDT-SWAP', '1H', 200)
        if kline_data:
            df = pd.DataFrame(kline_data)
            df['timestamp'] = pd.to_datetime(df['ts'], unit='ms')
            df.set_index('timestamp', inplace=True)
            df.rename(columns={'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume'}, inplace=True)
            summary = detector.get_summary(df, 'BTC')
            print(f'  异常数: {summary["anomaly_count"]} / {summary["total_bars"]}')
            print(f'  异常率: {summary["anomaly_rate"]*100:.2f}%')
            if summary['latest_anomaly']:
                latest = summary['latest_anomaly']
                print(f'  最新异常: {latest["type"]} ({latest["severity"]})')
        print()

        print('[6] 交易建议')
        print('-' * 60)
        if inference['confidence'] >= trader.confidence_threshold:
            print(f'  建议: 执行{direction}')
            print(f'  入场价: ${inference["price"]:,.2f}')
            print(f'  止损: ${inference["stop_loss_px"]:,.2f}')
            print(f'  止盈: ${inference["take_profit_px"]:,.2f}')
        else:
            print(f'  建议: 等待更好机会')
            print(f'  当前置信度 {inference["confidence"]:.2%} < 阈值 {trader.confidence_threshold:.2%}')
        print()

        print('[7] 当前持仓')
        print('-' * 60)
        open_pos = trader.position_tracker.all_open_positions()
        if open_pos:
            for pos in open_pos:
                print(f'  {pos.coin}: {pos.direction.upper()} @ ${pos.entry_price:,.2f}')
        else:
            print('  无持仓')
        print()

        print('[8] 增量学习状态')
        print('-' * 60)
        dashboard = trader.incremental_learner.get_dashboard_data('BTC')
        print(f'  总交易数: {dashboard.get("total_trades", 0)}')
        perf = dashboard.get('recent_performance', {})
        if perf:
            print(f'  胜率: {perf.get("win_rate", 0):.1f}%')
            print(f'  平均收益: {perf.get("avg_pnl", 0):.3f}%')
            print(f'  夏普比率: {perf.get("sharpe_ratio", 0):.2f}')

    else:
        print(f'  推理失败: {inference.get("error")}')

    print()
    print('=' * 80)
    print('  分析报告生成完成')
    print('=' * 80)


if __name__ == '__main__':
    main()
