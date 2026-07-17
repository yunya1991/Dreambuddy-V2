"""三屏趋势系统 — 核心算法单元测试

使用模拟数据验证五大算法的基本功能。
不依赖外部数据源。
"""

import sys
import os
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import (
    calc_indicator_dynamics,
    calc_trend_direction_static,
    calc_trend_direction_dynamic,
    calc_trend_consistency,
    calc_dynamic_weights,
    calc_bayesian_confidence,
    fuse_technical_fundamental,
    SCREEN1_INDICATORS,
    SCREEN2_INDICATORS,
    CompositePredictor,
    create_composite_predictor,
    predict_from_dataframes,
    compute_least_resistance,
    calc_price_resistance,
    calc_volume_resistance,
    calc_momentum_resistance,
    calc_trend_resistance,
)
from engine import (
    confidence_to_position,
    five_algo_decision,
    compute_trend_signal_from_dataframes,
)


def _generate_synthetic_data(n_days: int = 250, trend: str = "bull") -> pd.DataFrame:
    """生成合成K线数据用于测试"""
    np.random.seed(42)
    base_price = 60000
    if trend == "bull":
        returns = np.random.normal(0.003, 0.02, n_days)
    elif trend == "bear":
        returns = np.random.normal(-0.003, 0.02, n_days)
    else:
        returns = np.random.normal(0.0, 0.02, n_days)

    prices = base_price * np.cumprod(1 + returns)
    highs = prices * (1 + np.abs(np.random.normal(0, 0.01, n_days)))
    lows = prices * (1 - np.abs(np.random.normal(0, 0.01, n_days)))
    opens = np.concatenate([[base_price], prices[:-1]])
    volumes = np.random.uniform(1000, 5000, n_days)

    return pd.DataFrame({
        "open": opens,
        "high": highs,
        "low": lows,
        "close": prices,
        "volume": volumes,
    })


def test_confidence_to_position():
    """测试置信度到仓位映射"""
    print("\n=== 测试: confidence_to_position ===")
    test_cases = [
        (90, "heavy"),
        (80, "medium"),
        (70, "moderate"),
        (60, "light"),
        (50, "trial"),
        (40, "none"),
    ]
    for conf, expected_tier in test_cases:
        result = confidence_to_position(conf)
        status = "✓" if result["tier"] == expected_tier else "✗"
        print(f"  {status} 置信度{conf}% → 档位: {result['tier']} (期望: {expected_tier}), 仓位: {result['position_pct']:.0%}")


def test_five_algo_decision():
    """测试五大算法决策"""
    print("\n=== 测试: five_algo_decision ===")

    cases = [
        (True, "BULL", 75, "ENTER_LONG", "高置信度多头"),
        (True, "BEAR", 70, "ENTER_SHORT", "高置信度空头"),
        (True, "BULL", 50, "ENTER_LONG", "轻仓试探多头"),
        (False, "BULL", 80, "WAIT", "趋势不一致"),
        (True, "NEUTRAL", 60, "WAIT", "方向中性"),
        (True, "BULL", 40, "WAIT", "低置信度观望"),
    ]

    for consistent, direction, conf, expected_action, desc in cases:
        result = five_algo_decision(consistent, direction, conf)
        status = "✓" if result["action"] == expected_action else "✗"
        print(f"  {status} {desc}: action={result['action']} (期望: {expected_action})")


def test_trend_consistency():
    """测试趋势一致性计算"""
    print("\n=== 测试: calc_trend_consistency ===")
    print(f"  Screen1 指标: {SCREEN1_INDICATORS}")
    print(f"  Screen2 指标: {SCREEN2_INDICATORS}")

    daily_df = _generate_synthetic_data(250, "bull")
    weekly_df = _generate_synthetic_data(210, "bull")

    result = calc_trend_consistency(weekly_df, daily_df)
    print(f"  周线方向: {result['weekly']['core_direction']} (置信度: {result['weekly']['confidence']}%)")
    print(f"  日线方向: {result['daily']['core_direction']} (置信度: {result['daily']['confidence']}%)")
    print(f"  趋势一致: {result['consistent']}")
    print(f"  综合方向: {result['overall_direction']}")
    print(f"  一致性置信度: {result['consistency_confidence']}%")
    print(f"  周线逆转分数: {result['weekly']['reversal_score']}%")
    print(f"  周线平均速度: {result['weekly']['avg_speed']}, 加速度: {result['weekly']['avg_acceleration']}")


def test_bayesian_confidence():
    """测试贝叶斯置信度计算"""
    print("\n=== 测试: calc_bayesian_confidence ===")

    daily_df = _generate_synthetic_data(250, "bull")
    weekly_df = _generate_synthetic_data(210, "bull")

    result = calc_bayesian_confidence(weekly_df, daily_df)
    print(f"  贝叶斯方向: {result['direction']}")
    print(f"  置信度: {result['confidence']}%")
    print(f"  多头概率: {result['bull_probability']:.2%}")
    print(f"  空头概率: {result['bear_probability']:.2%}")
    print(f"  周线指标排名: {result['weekly_weights']['sorted_indicators'][:3]}...")


def test_fusion():
    """测试技术面+基本面撮合"""
    print("\n=== 测试: fuse_technical_fundamental ===")

    cases = [
        ({"direction": "BULL", "confidence": 70}, {"direction": "BULL", "confidence": 60}, "一致看多"),
        ({"direction": "BULL", "confidence": 70}, {"direction": "NEUTRAL", "confidence": 0}, "基本面中性"),
        ({"direction": "BULL", "confidence": 70}, {"direction": "BEAR", "confidence": 65}, "多空矛盾"),
    ]

    for tech, fund, desc in cases:
        result = fuse_technical_fundamental(tech, fund)
        print(f"  {desc}:")
        print(f"    技术面: {tech['direction']} {tech['confidence']}%")
        print(f"    基本面: {fund['direction']} {fund['confidence']}%")
        print(f"    最终方向: {result['final_direction']}")
        print(f"    最终置信度: {result['final_confidence']}%")
        print(f"    一致: {result['consistent']}, 矛盾等级: {result['conflict_level']}%")


def test_full_signal():
    """测试完整信号计算"""
    print("\n=== 测试: compute_trend_signal_from_dataframes ===")

    daily_df = _generate_synthetic_data(250, "bull")
    weekly_df = _generate_synthetic_data(210, "bull")

    result = compute_trend_signal_from_dataframes(
        weekly_df=weekly_df,
        daily_df=daily_df,
        symbol="BTC",
    )

    print(f"  币种: {result['symbol']}")
    print(f"  价格: ${result['price']:,.2f}")
    print(f"  趋势一致: {result['final_signal']['trend_consistent']}")
    print(f"  撮合一致: {result['final_signal']['fusion_consistent']}")
    print(f"  最终方向: {result['final_signal']['direction']}")
    print(f"  最终置信度: {result['final_signal']['confidence']}%")
    print(f"  交易动作: {result['final_signal']['action']}")
    print(f"  仓位档位: {result['final_signal']['position']['tier']} ({result['final_signal']['position']['position_pct']:.0%})")
    print(f"  决策原因: {result['final_signal']['decision_reason']}")

    print("\n  --- 加入 Freqtrade 同向信号（来自经典系统） ---")
    freqtrade_signals = {
        "1h": {"signal": "BUY", "confidence": 75},
        "4h": {"signal": "BUY", "confidence": 80},
    }
    result_with_ft = compute_trend_signal_from_dataframes(
        weekly_df=weekly_df,
        daily_df=daily_df,
        symbol="BTC",
        freqtrade_signals=freqtrade_signals,
    )
    print(f"  Freqtrade一致: {result_with_ft['final_signal']['freqtrade_consistent']}")
    print(f"  调整后置信度: {result_with_ft['final_signal']['confidence']}%")
    print(f"  原置信度: {result['final_signal']['confidence']}%")
    print(f"  置信度变化: +{result_with_ft['final_signal']['confidence'] - result['final_signal']['confidence']:.1f}%")

    print("\n  --- 加入 Freqtrade 反向信号 ---")
    freqtrade_signals_bear = {
        "1h": {"signal": "SELL", "confidence": 70},
    }
    result_with_bear_ft = compute_trend_signal_from_dataframes(
        weekly_df=weekly_df,
        daily_df=daily_df,
        symbol="BTC",
        freqtrade_signals=freqtrade_signals_bear,
    )
    print(f"  Freqtrade一致: {result_with_bear_ft['final_signal']['freqtrade_consistent']}")
    print(f"  调整后置信度: {result_with_bear_ft['final_signal']['confidence']}%")
    print(f"  原置信度: {result['final_signal']['confidence']}%")
    print(f"  置信度变化: {result_with_bear_ft['final_signal']['confidence'] - result['final_signal']['confidence']:.1f}%")


def test_fundamental_data():
    """测试基本面数据读取（A系列研报）"""
    print("\n=== 测试: fetch_fundamental_data (A系列研报) ===")

    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from data.fundamental_data import fetch_fundamental_data, fetch_fundamental_by_timeframe

    result = fetch_fundamental_data("BTC")
    print(f"  基本面方向: {result['direction']}")
    print(f"  基本面置信度: {result['confidence']}%")
    print(f"  研报总数: {result['total_reports']}")
    print(f"  多头: {result['bull_count']}, 空头: {result['bear_count']}")

    if result.get("weekly"):
        w = result["weekly"]
        print(f"\n  --- 周报 (周线基本面) ---")
        print(f"  日期: {w['date']}")
        print(f"  方向: {w['direction']}")
        print(f"  置信度: {w['confidence']}%")
        print(f"  Regime: {w['regime']}")
        print(f"  评分: {w['score']}/100")
        print(f"  文件: {w['source_file']}")

    if result.get("daily"):
        d = result["daily"]
        print(f"\n  --- A1日报 (日线基本面) ---")
        print(f"  日期: {d['date']}")
        print(f"  方向: {d['direction']}")
        print(f"  置信度: {d['confidence']}%")
        print(f"  Regime: {d['regime']}")
        print(f"  文件: {d['source_file']}")

    # 测试分层获取
    tf_result = fetch_fundamental_by_timeframe("BTC")
    print(f"\n  --- 分层基本面 ---")
    print(f"  周线: {tf_result['weekly']['direction'] if tf_result['weekly'] else 'N/A'}")
    print(f"  日线: {tf_result['daily']['direction'] if tf_result['daily'] else 'N/A'}")

    # 测试基本面+技术面撮合
    print(f"\n  --- 基本面+技术面撮合 ---")
    tech = {"direction": "BULL", "confidence": 70}
    fund = {"direction": result["direction"], "confidence": result["confidence"]}
    fusion = fuse_technical_fundamental(tech, fund)
    print(f"  技术面: {tech['direction']} {tech['confidence']}%")
    print(f"  基本面: {fund['direction']} {fund['confidence']}%")
    print(f"  撮合方向: {fusion['final_direction']}")
    print(f"  撮合置信度: {fusion['final_confidence']}%")
    print(f"  一致: {fusion['consistent']}, 矛盾等级: {fusion['conflict_level']}%")


def test_composite_predictor():
    """测试综合预测引擎（技术基线 + 基本面三维度调节）"""
    print("\n=== 测试: CompositePredictor ===")

    predictor = create_composite_predictor()
    print(f"  预测引擎创建成功: {type(predictor).__name__}")
    print(f"  权重配置: {predictor.weights}")

    tech_result = {"direction": "BULL", "confidence": 70.0}

    fundamental_data_bull = {
        "score": 65,
        "direction": "BULL",
        "confidence": 75,
        "dimensions": {
            "mining": {"available": True, "score": 70},
            "onchain": {"available": True, "score": 60},
            "macro": {"available": True, "score": 55},
            "crossmarket": {"available": True, "score": 65},
        },
    }

    result_bull = predictor.predict(tech_result, fundamental_data_bull)
    print(f"\n  --- 技术面BULL + 基本面BULL（一致） ---")
    print(f"  技术方向: {result_bull['technical']['direction']}")
    print(f"  技术置信度: {result_bull['technical']['confidence']}%")
    print(f"  基本面三维度可用: {result_bull['fundamental']['3d']['available']}")
    print(f"  基本面方向: {result_bull['fundamental']['3d']['direction']}")
    print(f"  基本面速度: {result_bull['fundamental']['3d']['velocity']:.3f}")
    print(f"  基本面加速度: {result_bull['fundamental']['3d']['acceleration']:.3f}")
    print(f"  调节类型: {result_bull['fundamental']['adjustment']['adjustment_type']}")
    print(f"  调节因子: {result_bull['fundamental']['adjustment']['adjustment']:.4f}")
    print(f"  调节原因: {result_bull['fundamental']['adjustment']['reason']}")
    print(f"  最终方向: {result_bull['direction']}")
    print(f"  最终置信度: {result_bull['confidence']}%")

    fundamental_data_bear = {
        "score": 35,
        "direction": "BEAR",
        "confidence": 70,
        "dimensions": {
            "mining": {"available": True, "score": 30},
            "onchain": {"available": True, "score": 40},
            "macro": {"available": True, "score": 35},
            "crossmarket": {"available": True, "score": 45},
        },
    }

    result_bear = predictor.predict(tech_result, fundamental_data_bear)
    print(f"\n  --- 技术面BULL + 基本面BEAR（矛盾） ---")
    print(f"  技术方向: {result_bear['technical']['direction']}")
    print(f"  技术置信度: {result_bear['technical']['confidence']}%")
    print(f"  基本面方向: {result_bear['fundamental']['3d']['direction']}")
    print(f"  调节类型: {result_bear['fundamental']['adjustment']['adjustment_type']}")
    print(f"  调节因子: {result_bear['fundamental']['adjustment']['adjustment']:.4f}")
    print(f"  调节原因: {result_bear['fundamental']['adjustment']['reason']}")
    print(f"  最终方向: {result_bear['direction']}")
    print(f"  最终置信度: {result_bear['confidence']}%")

    fundamental_data_neutral = {
        "score": 50,
        "direction": "NEUTRAL",
        "confidence": 50,
    }

    result_neutral = predictor.predict(tech_result, fundamental_data_neutral)
    print(f"\n  --- 技术面BULL + 基本面NEUTRAL（中性） ---")
    print(f"  调节类型: {result_neutral['fundamental']['adjustment']['adjustment_type']}")
    print(f"  调节因子: {result_neutral['fundamental']['adjustment']['adjustment']:.4f}")
    print(f"  最终置信度: {result_neutral['confidence']}%")

    print("\n  --- 便捷函数 predict_from_dataframes 测试 ---")
    daily_df = _generate_synthetic_data(250, "bull")
    weekly_df = _generate_synthetic_data(210, "bull")
    df_result = predict_from_dataframes(
        weekly_df=weekly_df,
        daily_df=daily_df,
        fundamental_data=fundamental_data_bull,
    )
    print(f"  趋势方向: {df_result['direction']}")
    print(f"  综合置信度: {df_result['confidence']}%")
    print(f"  调节类型: {df_result['fundamental']['adjustment']['adjustment_type']}")


def test_least_resistance():
    """测试最小阻力方向引擎（第一性原理）"""
    print("\n=== 测试: 最小阻力方向引擎 ===")

    bull_df = _generate_synthetic_data(250, "bull")
    bear_df = _generate_synthetic_data(250, "bear")
    neutral_df = _generate_synthetic_data(250, "neutral")

    print("\n  --- 牛市行情 ---")
    bull_lr = compute_least_resistance(bull_df)
    print(f"  方向: {bull_lr['direction']}")
    print(f"  置信度: {bull_lr['confidence']}%")
    print(f"  多方阻力: {bull_lr['bull_resistance']:.4f}")
    print(f"  空方阻力: {bull_lr['bear_resistance']:.4f}")
    print(f"  阻力差: {bull_lr['resistance_diff']:.4f}")
    print(f"  速度: {bull_lr['velocity']:.4f}, 加速度: {bull_lr['acceleration']:.4f}")
    print(f"  价格维度 - 多方阻力: {bull_lr['dimensions']['price']['bull_resistance']:.4f}, "
          f"空方阻力: {bull_lr['dimensions']['price']['bear_resistance']:.4f}")
    print(f"  量能维度 - 多方阻力: {bull_lr['dimensions']['volume']['bull_resistance']:.4f}, "
          f"空方阻力: {bull_lr['dimensions']['volume']['bear_resistance']:.4f}")
    print(f"  动量维度 - 多方阻力: {bull_lr['dimensions']['momentum']['bull_resistance']:.4f}, "
          f"空方阻力: {bull_lr['dimensions']['momentum']['bear_resistance']:.4f}")
    print(f"  趋势维度 - 多方阻力: {bull_lr['dimensions']['trend']['bull_resistance']:.4f}, "
          f"空方阻力: {bull_lr['dimensions']['trend']['bear_resistance']:.4f}")
    print(f"  总结: {bull_lr['summary']}")

    print("\n  --- 熊市行情 ---")
    bear_lr = compute_least_resistance(bear_df)
    print(f"  方向: {bear_lr['direction']}")
    print(f"  置信度: {bear_lr['confidence']}%")
    print(f"  多方阻力: {bear_lr['bull_resistance']:.4f}")
    print(f"  空方阻力: {bear_lr['bear_resistance']:.4f}")
    print(f"  阻力差: {bear_lr['resistance_diff']:.4f}")
    print(f"  总结: {bear_lr['summary']}")

    print("\n  --- 震荡行情 ---")
    neutral_lr = compute_least_resistance(neutral_df)
    print(f"  方向: {neutral_lr['direction']}")
    print(f"  置信度: {neutral_lr['confidence']}%")
    print(f"  多方阻力: {neutral_lr['bull_resistance']:.4f}")
    print(f"  空方阻力: {neutral_lr['bear_resistance']:.4f}")
    print(f"  阻力差: {neutral_lr['resistance_diff']:.4f}")
    print(f"  总结: {neutral_lr['summary']}")

    print("\n  --- 基本面阻力测试 ---")
    fund_data_bull = {
        "score": 70,
        "direction": "BULL",
        "confidence": 75,
        "dimensions": {
            "mining": {"available": True, "score": 70},
            "onchain": {"available": True, "score": 65},
        },
    }
    fund_lr = compute_least_resistance(bull_df, fundamental_data=fund_data_bull)
    print(f"  加入基本面后方向: {fund_lr['direction']}")
    print(f"  加入基本面后置信度: {fund_lr['confidence']}%")
    print(f"  基本面维度可用: {fund_lr['dimensions']['fundamental'].get('available', False)}")
    print(f"  基本面评分: {fund_lr['dimensions']['fundamental'].get('fund_score', 0)}")
    print(f"  权重分布: {fund_lr['weights']}")

    print("\n  --- 趋势一致性 + 最小阻力融合测试 ---")
    weekly_df = _generate_synthetic_data(210, "bull")
    daily_df = _generate_synthetic_data(250, "bull")
    tc = calc_trend_consistency(weekly_df, daily_df)
    print(f"  趋势一致: {tc['consistent']}")
    print(f"  一致性级别: {tc['consistency_level']}")
    print(f"  综合方向: {tc['overall_direction']}")
    print(f"  一致性置信度: {tc['consistency_confidence']}%")
    print(f"  最小阻力引擎启用: {tc.get('least_resistance') is not None}")
    if tc.get('least_resistance'):
        lr = tc['least_resistance']
        print(f"  最小阻力方向: {lr['overall_direction']}")
        print(f"  最小阻力置信度: {lr['consistency_confidence']}%")
        print(f"  周线最小阻力: {lr['weekly']['direction']} ({lr['weekly']['confidence']}%)")
        print(f"  日线最小阻力: {lr['daily']['direction']} ({lr['daily']['confidence']}%)")


def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("三屏趋势系统 — 核心算法单元测试")
    print("=" * 60)

    test_confidence_to_position()
    test_five_algo_decision()
    test_trend_consistency()
    test_bayesian_confidence()
    test_fusion()
    test_full_signal()
    test_fundamental_data()
    test_composite_predictor()
    test_least_resistance()

    print("\n" + "=" * 60)
    print("所有测试完成")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()
