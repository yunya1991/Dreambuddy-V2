"""验证脚本：卦象分布 + 反馈闭环修复验证"""
import sys
import os
sys.path.insert(0, '.')

from collections import Counter
import numpy as np
import pandas as pd

print("=" * 60)
print("【验证 1】卦象分布均衡性（修复后）")
print("=" * 60)

from scripts.memory_l4.bcrm2_adapter import BCRM2Adapter
from scripts.memory_l4.okx_simulated import OKXSimulatedClient

okx = OKXSimulatedClient({})
resp = okx.get_kline("BTC-USDT-SWAP", bar="1H", limit=300)
candles = resp.get("candles", [])
df = pd.DataFrame([{
    'open': float(c['o']), 'high': float(c['h']), 'low': float(c['l']),
    'close': float(c['c']), 'volume': float(c.get('vol', c.get('v', 0))),
    'timestamp': c.get('ts', ''),
} for c in candles])
print(f"K线数据: {len(df)}根")

adapter = BCRM2Adapter('BTC', '1H')

# 验证 hexagram_mapper 是否有二次归一化统计
engine = adapter.engine
if hasattr(engine, 'hexagram_mapper'):
    hm = engine.hexagram_mapper
    if hasattr(hm, '_gua_activity_stats') and hm._gua_activity_stats is not None:
        print("\n✅ 二次归一化统计已加载")
        print("\n各卦活跃度历史均值:")
        from scripts.memory_l4.bcrm2.dialectical_ml_engine import GUA_DIMENSION_MAP
        stats = hm._gua_activity_stats
        sorted_guas = sorted(stats['mean'].items(), key=lambda x: -x[1])
        for gua, mean in sorted_guas:
            if gua in GUA_DIMENSION_MAP:
                name = GUA_DIMENSION_MAP[gua]['name']
                std = stats['std'].get(gua, 0)
                print(f"  {name}({gua}): 均值={mean:.4f}  std={std:.4f}")
    else:
        print("❌ 二次归一化统计未加载（可能模型未训练）")
else:
    print("⚠️ 无 hexagram_mapper")

# 统计卦象分布
print()
print("统计卦象分布中...")
hex_counter = Counter()
upper_counter = Counter()
lower_counter = Counter()
n_samples = 0

# 每隔5根取一个，加速
step = 5
for i in range(max(0, len(df)-200), len(df), step):
    result = adapter.infer(df.iloc[:i+1])
    if not result or result.get('fail_closed_reason'):
        continue

    hex_info = result.get('hexagram', {})
    if isinstance(hex_info, dict):
        hex_name = hex_info.get('hexagram_name_cn', '?')
        upper = hex_info.get('upper_gua', {}).get('name', '?')
        lower = hex_info.get('lower_gua', {}).get('name', '?')
    else:
        hex_name = str(hex_info)
        upper = '?'
        lower = '?'

    hex_counter[hex_name] += 1
    upper_counter[upper] += 1
    lower_counter[lower] += 1
    n_samples += 1

if n_samples > 0:
    print(f"\n最近 {n_samples} 次推理卦象分布 (Top 15):")
    for name, cnt in hex_counter.most_common(15):
        pct = cnt / n_samples * 100
        bar = '█' * int(pct / 2)
        print(f"  {name:10s} {cnt:3d} ({pct:5.1f}%) {bar}")

    print(f"\n上卦(外卦)分布:")
    for name, cnt in upper_counter.most_common():
        pct = cnt / n_samples * 100
        bar = '█' * int(pct / 3)
        print(f"  {name:6s}: {cnt:3d} ({pct:5.1f}%) {bar}")

    print(f"\n下卦(内卦)分布:")
    for name, cnt in lower_counter.most_common():
        pct = cnt / n_samples * 100
        bar = '█' * int(pct / 3)
        print(f"  {name:6s}: {cnt:3d} ({pct:5.1f}%) {bar}")

    # 计算分布均匀度（基尼系数近似）
    upper_pcts = np.array([c / n_samples for c in upper_counter.values()])
    expected = 1.0 / 8  # 8个卦均匀分布
    max_deviation = max(abs(p - expected) for p in upper_pcts) if len(upper_pcts) > 0 else 1.0
    print(f"\n上卦分布偏差度: {max_deviation:.2%} (越低越均匀，0%=完全均匀)")
    if max_deviation < 0.15:
        print("✅ 卦象分布均衡性良好")
    elif max_deviation < 0.25:
        print("⚠️ 卦象分布有一定偏斜")
    else:
        print("❌ 卦象分布偏斜严重")

print()
print("=" * 60)
print("【验证 2】反馈闭环修复验证")
print("=" * 60)

# 检查 _trigger_bcrm2_retrain 方法是否存在
from scripts.memory_l4.polling_trader import PollingTrader
if hasattr(PollingTrader, '_trigger_bcrm2_retrain'):
    print("✅ _trigger_bcrm2_retrain 方法已添加")
else:
    print("❌ _trigger_bcrm2_retrain 方法缺失")

# 检查 close_position 中是否调用
import inspect
src = inspect.getsource(PollingTrader._close_position)
if '_trigger_bcrm2_retrain' in src:
    print("✅ _close_position 中已调用 _trigger_bcrm2_retrain")
else:
    print("❌ _close_position 中未调用 _trigger_bcrm2_retrain")

print()
print("反馈闭环完整链路（修复后）:")
print("  平仓 → register_trade_to_l4() → UnifiedCaseRegistry (case沉淀)")
print("       → incremental_learner.log_trades_batch() (交易记录DB)")
print("       → incremental_learner.should_retrain() (判断阈值)")
print("       → _trigger_bcrm2_retrain() ← 【修复点：之前只打日志】")
print("       → adapter.train(force_retrain=True) (模型重训)")
print("       → version_manager.save_version() (版本管理)")
print("       → learning_scheduler.trigger_retrain() (BCRM1.0两仪重训)")
print("       → ranging_enhancer.update_calibration() (置信度校准)")
print("       → _trigger_l4_pipeline_for_trade() (L4 M1-M4全链路)")
