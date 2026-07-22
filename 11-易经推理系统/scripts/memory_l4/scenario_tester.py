"""
易经推理模型多场景模拟测试

测试场景：
1. 趋势行情（上升/下降）
2. 震荡行情（横盘整理）
3. 突破行情（向上/向下突破）
4. 高波动行情（波动率 > 5%）
5. 低波动行情（波动率 < 1%）
6. 不同卦象场景（吉/凶/平）
7. 反转行情（趋势反转）

每个场景模拟 K 线数据 → 构造 market_snapshot → 调用 BCRM 推理 → 验证输出合理性
"""

import json
import random
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Tuple, Optional
from pathlib import Path

warnings.filterwarnings("ignore")

try:
    from scripts.memory_l4.bcrm2_adapter import BCRM2Adapter
    from scripts.memory_l4.cbr_adapter import CBRToBCRMBridge
    from scripts.memory_l4.kg_query import KGQueryEngine
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from bcrm2_adapter import BCRM2Adapter
    from cbr_adapter import CBRToBCRMBridge
    from kg_query import KGQueryEngine


@dataclass
class TestScenario:
    """测试场景定义"""
    name: str = ""
    description: str = ""
    trend_direction: str = "neutral"  # up/down/neutral
    volatility_level: str = "normal"  # high/normal/low
    market_regime: str = ""
    expected_direction: Optional[str] = None  # 预期方向 up/down/flat
    expected_confidence_range: Tuple[float, float] = (0.4, 0.9)
    kline_count: int = 600


@dataclass
class TestResult:
    """测试结果"""
    scenario: TestScenario
    direction: str = ""
    confidence: float = 0.0
    hexagram: str = ""
    hexagram_cn: str = ""
    pass_flag: bool = False
    reason: str = ""
    full_output: Dict = field(default_factory=dict)


def generate_simulated_klines(scenario: TestScenario) -> List[Dict]:
    """根据场景生成模拟 K 线数据

    确保趋势方向正确：
    - 趋势因子根据波动率调整，确保不被噪声淹没
    - 价格围绕趋势线波动，避免指数级发散
    """
    klines = []
    base_price = 60000.0
    volatility = {
        "high": 0.05,
        "normal": 0.02,
        "low": 0.008,
    }[scenario.volatility_level]

    # 趋势因子：根据波动率调整，确保趋势方向正确
    base_trend = {
        "up": 0.003,
        "down": -0.003,
        "neutral": 0.0,
    }[scenario.trend_direction]
    
    # 高波动场景下放大趋势因子，确保趋势方向不被噪声淹没
    if scenario.volatility_level == "high":
        trend_factor = base_trend * 2.0
    elif scenario.volatility_level == "low":
        trend_factor = base_trend * 0.8
    else:
        trend_factor = base_trend

    now = datetime.now(timezone.utc)
    current_price = base_price
    
    for i in range(scenario.kline_count):
        ts = now - timedelta(hours=i)
        ts_ms = int(ts.timestamp() * 1000)
        
        # 趋势 + 随机噪声
        noise = random.gauss(0, volatility)
        move = trend_factor + noise
        
        current_price *= (1 + move)
        
        # 价格回归机制：防止价格过度偏离基准价格
        # 当价格偏离超过50%时，引入回归力
        deviation = (current_price - base_price) / base_price
        if abs(deviation) > 0.5:
            regression = -deviation * 0.001
            current_price *= (1 + regression)
        
        # 防止价格变为负数
        current_price = max(current_price, base_price * 0.01)
        
        open_p = current_price * (1 + random.gauss(0, volatility * 0.3))
        close_p = current_price
        high_p = max(open_p, close_p) * (1 + random.uniform(0, volatility * 0.5))
        low_p = min(open_p, close_p) * (1 - random.uniform(0, volatility * 0.5))
        
        # 趋势行情成交量更大
        vol_base = 15000 if scenario.trend_direction != "neutral" else 10000
        volume = random.uniform(vol_base * 0.5, vol_base * 1.5)
        
        klines.append({
            "ts": ts_ms,
            "ts_str": ts.isoformat(),
            "o": round(open_p, 2),
            "h": round(high_p, 2),
            "l": round(low_p, 2),
            "c": round(close_p, 2),
            "v": round(volume, 2),
        })

    return klines


def build_market_snapshot(klines: List[Dict], idx: int = 0) -> Dict:
    """从 K 线数据构建 market_snapshot"""
    if not klines or idx >= len(klines):
        return {}
    
    current = klines[idx]
    price = current["c"]
    
    lookback_short = min(5, len(klines) - idx)
    lookback_med = min(20, len(klines) - idx)
    lookback_long = min(60, len(klines) - idx)
    
    closes_short = [klines[i]["c"] for i in range(idx, idx + lookback_short)]
    closes_med = [klines[i]["c"] for i in range(idx, idx + lookback_med)]
    closes_long = [klines[i]["c"] for i in range(idx, idx + lookback_long)]
    highs = [klines[i]["h"] for i in range(idx, idx + lookback_med)]
    lows = [klines[i]["l"] for i in range(idx, idx + lookback_med)]
    volumes = [float(klines[i]["v"]) for i in range(idx, idx + lookback_short)]
    
    high = max(highs)
    low = min(lows)
    
    ma_short = sum(closes_short) / len(closes_short) if closes_short else price
    ma_med = sum(closes_med) / len(closes_med) if closes_med else price
    ma_long = sum(closes_long) / len(closes_long) if closes_long else price
    
    prev_close = klines[idx + 1]["c"] if idx + 1 < len(klines) else price
    change_pct = (price - prev_close) / prev_close if prev_close else 0
    
    med_change = (price - closes_med[-1]) / closes_med[-1] if closes_med[-1] else 0
    
    atr_vals = []
    for i in range(idx, idx + min(14, len(klines) - idx)):
        k = klines[i]
        prev_c = klines[i+1]["c"] if i+1 < len(klines) else k["c"]
        tr = max(k["h"] - k["l"], abs(k["h"] - prev_c), abs(k["l"] - prev_c))
        if k["c"]:
            atr_vals.append(tr / k["c"])
    volatility = sum(atr_vals) / len(atr_vals) if atr_vals else 0.02
    
    price_position = (price - low) / (high - low) if high > low else 0.5
    
    avg_vol = sum(volumes) / len(volumes) if volumes else 1
    cur_vol = float(current["v"])
    volume_ratio = cur_vol / avg_vol if avg_vol else 1.0
    
    ma_dev = abs(price - ma_med) / ma_med if ma_med else 0
    trend_strength = min(ma_dev * 10 + volatility * 3, 0.9)
    trend_strength = max(0.1, trend_strength)
    
    long_return = (price - ma_long) / ma_long if ma_long else 0
    gdp_growth = max(-0.02, min(long_return * 2, 0.10))
    
    cpi = max(0.0, min(volatility * 5, 0.06))
    
    if price_position > 0.6 and trend_strength > 0.3:
        interest_rate = 0.03 + (price_position - 0.6) * 0.05
    elif price_position < 0.3 and trend_strength < 0.2:
        interest_rate = 0.005 + price_position * 0.02
    else:
        interest_rate = 0.02
    interest_rate = max(0.005, min(interest_rate, 0.055))
    
    return {
        "snapshot_ts": current.get("ts_str", datetime.now(timezone.utc).isoformat()),
        "price": price,
        "symbol": "BTC-USDT-SWAP",
        "market_scale": 0.7,
        "trend_strength": trend_strength,
        "volatility": volatility,
        "volume_ratio": volume_ratio,
        "price_position": price_position,
        "change_pct": change_pct,
        "med_change_pct": med_change,
        "high": high,
        "low": low,
        "ma_short": ma_short,
        "ma_med": ma_med,
        "ma_long": ma_long,
        "gdp_growth": gdp_growth,
        "cpi": cpi,
        "interest_rate": interest_rate,
    }


def run_scenario_test(scenario: TestScenario) -> TestResult:
    """运行单个场景测试"""
    klines = generate_simulated_klines(scenario)
    
    try:
        import pandas as pd
        df = pd.DataFrame([{
            'open': k['o'],
            'high': k['h'],
            'low': k['l'],
            'close': k['c'],
            'volume': k['v'],
        } for k in klines])
        df['timestamp'] = pd.to_datetime([k['ts_str'] for k in klines])
        df = df.set_index('timestamp')
        
        adapter = BCRM2Adapter(
            symbol="BTC", 
            timeframe="4H",
            train_bars=scenario.kline_count,
        )
        adapter._train_interval = 0
        bcrm_result = adapter.infer(df)
        
        if not bcrm_result.get("ok"):
            return TestResult(
                scenario=scenario,
                direction="FLAT",
                confidence=0.0,
                hexagram="",
                hexagram_cn="",
                pass_flag=False,
                reason="推理失败: " + bcrm_result.get("fail_closed_reason", "未知"),
                full_output=bcrm_result,
            )
        
        direction = bcrm_result["next_state"]["direction"]
        confidence = bcrm_result["next_state"]["confidence"]
        hex_cn = bcrm_result["hexagram"].get("hexagram_name_cn", "未知")
        hex_name = bcrm_result["hexagram"].get("hexagram_name", "未知")
        
        pass_flag = True
        reason = ""
        
        if scenario.expected_direction:
            expected = scenario.expected_direction.upper()
            if direction != expected:
                pass_flag = False
                reason += f"方向不符: 预期={expected}, 实际={direction}; "
        
        conf_min, conf_max = scenario.expected_confidence_range
        if confidence < conf_min or confidence > conf_max:
            pass_flag = False
            reason += f"置信度超出范围: {confidence:.2f} 不在 [{conf_min},{conf_max}]; "
        
        if not reason:
            reason = "通过"
        
        return TestResult(
            scenario=scenario,
            direction=direction,
            confidence=confidence,
            hexagram=hex_name,
            hexagram_cn=hex_cn,
            pass_flag=pass_flag,
            reason=reason,
            full_output=bcrm_result,
        )
    
    except Exception as e:
        return TestResult(
            scenario=scenario,
            direction="ERROR",
            confidence=0.0,
            hexagram="",
            hexagram_cn="",
            pass_flag=False,
            reason=f"推理失败: {str(e)}",
            full_output={},
        )


def run_cbr_enhancement_test(scenario: TestScenario) -> Dict:
    """测试 CBR 案例检索增强"""
    klines = generate_simulated_klines(scenario)
    
    try:
        import pandas as pd
        df = pd.DataFrame([{
            'open': k['o'],
            'high': k['h'],
            'low': k['l'],
            'close': k['c'],
            'volume': k['v'],
        } for k in klines])
        df['timestamp'] = pd.to_datetime([k['ts_str'] for k in klines])
        df = df.set_index('timestamp')
        
        adapter = BCRM2Adapter(symbol="BTC", timeframe="4H")
        bcrm_result = adapter.infer(df)
        
        if not bcrm_result.get("ok"):
            return {
                "scenario": scenario.name,
                "error": bcrm_result.get("fail_closed_reason", "推理失败"),
            }
        
        direction = bcrm_result["next_state"]["direction"]
        confidence = bcrm_result["next_state"]["confidence"]
        hex_cn = bcrm_result["hexagram"].get("hexagram_name_cn", "")
        liangyi = bcrm_result.get("liangyi_state", {}) or {}
        regime = liangyi.get("macro_phase", "")
        
        snapshot = build_market_snapshot(klines)
        
        cbr_bridge = CBRToBCRMBridge()
        cbr_bridge.initialize()
        
        bcrm_output = {
            "inst_id": "BTC-USDT-SWAP",
            "direction": "long" if direction == "UP" else ("short" if direction == "DOWN" else "flat"),
            "confidence": confidence,
            "current_price": snapshot.get("price", 60000),
            "regime": regime,
            "volatility": snapshot.get("volatility", 0.02),
            "hexagram": hex_cn,
        }
        
        enhanced = cbr_bridge.enhance_bcrm_signal(bcrm_output)
        
        return {
            "scenario": scenario.name,
            "bcrm_direction": direction,
            "bcrm_confidence": confidence,
            "cbr_fusion_method": enhanced.get("cbr_fusion_method"),
            "cbr_confidence": enhanced.get("confidence"),
            "cbr_historical_win_rate": enhanced.get("cbr_historical_win_rate"),
            "cbr_similarity_top1": enhanced.get("cbr_similarity_top1"),
            "cbr_risk_notes": enhanced.get("cbr_risk_notes", []),
            "confidence_change": round(enhanced.get("confidence", confidence) - confidence, 4),
        }
    
    except Exception as e:
        return {
            "scenario": scenario.name,
            "error": str(e),
        }


def run_kg_recommendation_test(scenario: TestScenario) -> Dict:
    """测试 KG 策略推荐"""
    klines = generate_simulated_klines(scenario)
    
    try:
        import pandas as pd
        df = pd.DataFrame([{
            'open': k['o'],
            'high': k['h'],
            'low': k['l'],
            'close': k['c'],
            'volume': k['v'],
        } for k in klines])
        df['timestamp'] = pd.to_datetime([k['ts_str'] for k in klines])
        df = df.set_index('timestamp')
        
        adapter = BCRM2Adapter(symbol="BTC", timeframe="4H")
        bcrm_result = adapter.infer(df)
        
        if not bcrm_result.get("ok"):
            return {
                "scenario": scenario.name,
                "error": bcrm_result.get("fail_closed_reason", "推理失败"),
            }
        
        hex_cn = bcrm_result["hexagram"].get("hexagram_name_cn", "")
        liangyi = bcrm_result.get("liangyi_state", {}) or {}
        regime = liangyi.get("macro_phase", "")
        
        kg_engine = KGQueryEngine()
        recommendations = kg_engine.recommend_strategy(
            inst_id="BTC-USDT-SWAP",
            regime=regime,
            hexagram=hex_cn,
        )
        
        return {
            "scenario": scenario.name,
            "hexagram": hex_cn,
            "regime": regime,
            "recommendations": recommendations[:3],
            "recommendation_count": len(recommendations),
        }
    
    except Exception as e:
        return {
            "scenario": scenario.name,
            "error": str(e),
        }


def main() -> None:
    """运行所有场景测试"""
    scenarios = [
        TestScenario(
            name="上升趋势",
            description="价格持续上涨，均线多头排列",
            trend_direction="up",
            volatility_level="normal",
            market_regime="recovery|sprout",
            expected_direction="UP",
            expected_confidence_range=(0.5, 1.0),
        ),
        TestScenario(
            name="下降趋势",
            description="价格持续下跌，均线空头排列",
            trend_direction="down",
            volatility_level="normal",
            market_regime="bear|winter",
            expected_direction="DOWN",
            expected_confidence_range=(0.5, 1.0),
        ),
        TestScenario(
            name="横盘震荡",
            description="价格在窄幅区间内波动，二分类允许UP/DOWN，置信度较低",
            trend_direction="neutral",
            volatility_level="low",
            market_regime="consolidation|sideways",
            expected_direction=None,
            expected_confidence_range=(0.3, 0.7),
        ),
        TestScenario(
            name="高波动上升",
            description="高波动率下的上升趋势",
            trend_direction="up",
            volatility_level="high",
            market_regime="fomo|expansion",
            expected_direction="UP",
            expected_confidence_range=(0.5, 1.0),
        ),
        TestScenario(
            name="高波动下跌",
            description="高波动率下的下跌趋势",
            trend_direction="down",
            volatility_level="high",
            market_regime="panic|contraction",
            expected_direction="DOWN",
            expected_confidence_range=(0.5, 1.0),
        ),
        TestScenario(
            name="低波动横盘",
            description="极低波动率的横盘整理，二分类允许UP/DOWN，置信度较低",
            trend_direction="neutral",
            volatility_level="low",
            market_regime="quiet|range",
            expected_direction=None,
            expected_confidence_range=(0.3, 0.7),
        ),
        TestScenario(
            name="突破前蓄势",
            description="价格接近历史高点，即将突破",
            trend_direction="up",
            volatility_level="normal",
            market_regime="breakout_prepare",
            expected_direction="UP",
            expected_confidence_range=(0.5, 1.0),
        ),
        TestScenario(
            name="破位下跌",
            description="价格跌破关键支撑位",
            trend_direction="down",
            volatility_level="high",
            market_regime="breakdown",
            expected_direction="DOWN",
            expected_confidence_range=(0.5, 1.0),
        ),
    ]
    
    print("=" * 80)
    print("易经推理模型多场景模拟测试")
    print("=" * 80)
    
    # 测试 1: BCRM 基础推理
    print("\n--- 测试 1: BCRM 基础推理 ---")
    results = []
    for scenario in scenarios:
        result = run_scenario_test(scenario)
        results.append(result)
        status = "✅" if result.pass_flag else "❌"
        print(f"{status} {scenario.name}: {result.direction} | 置信度={result.confidence:.2f} | 卦象={result.hexagram_cn} | {result.reason}")
    
    passed = sum(1 for r in results if r.pass_flag)
    print(f"\nBCRM 基础推理: {passed}/{len(results)} 通过")
    
    # 测试 2: CBR 案例检索增强
    print("\n--- 测试 2: CBR 案例检索增强 ---")
    cbr_results = []
    for scenario in scenarios:
        result = run_cbr_enhancement_test(scenario)
        cbr_results.append(result)
        if "error" in result:
            print(f"❌ {result['scenario']}: {result['error']}")
        else:
            change = result["confidence_change"]
            change_mark = "↑" if change > 0 else "↓" if change < 0 else "→"
            print(f"✅ {result['scenario']}: CBR={result['cbr_fusion_method']} | 置信度变化={change_mark}{abs(change):.2%} | 历史胜率={result.get('cbr_historical_win_rate', 0):.1%}")
    
    # 测试 3: KG 策略推荐
    print("\n--- 测试 3: KG 策略推荐 ---")
    kg_results = []
    for scenario in scenarios:
        result = run_kg_recommendation_test(scenario)
        kg_results.append(result)
        if "error" in result:
            print(f"❌ {result['scenario']}: {result['error']}")
        else:
            recs = result.get("recommendations", [])
            if recs:
                top = recs[0]
                print(f"✅ {result['scenario']}: 卦象={result['hexagram']} | 市态={result['regime']} | 推荐策略={top['strategy']} (胜率={top['win_rate']:.1%})")
            else:
                print(f"⚠️ {result['scenario']}: 卦象={result['hexagram']} | 无推荐策略")
    
    # 输出详细报告
    report = {
        "test_time": datetime.now(timezone.utc).isoformat(),
        "total_scenarios": len(scenarios),
        "bcrm_passed": passed,
        "bcrm_results": [
            {
                "scenario": r.scenario.name,
                "direction": r.direction,
                "confidence": r.confidence,
                "hexagram": r.hexagram_cn,
                "passed": r.pass_flag,
                "reason": r.reason,
            }
            for r in results
        ],
        "cbr_results": cbr_results,
        "kg_results": kg_results,
    }
    
    report_path = Path("artifacts/scenario_test_report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    
    print(f"\n测试报告已保存: {report_path}")
    print("=" * 80)


if __name__ == "__main__":
    main()
