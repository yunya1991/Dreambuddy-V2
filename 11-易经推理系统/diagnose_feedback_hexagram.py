"""诊断脚本：卦象分布 + 反馈闭环检查"""
import sys
import os
sys.path.insert(0, '.')

from collections import Counter
import numpy as np
import pandas as pd

print("=" * 60)
print("【诊断 1】卦象分布偏斜检查")
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

# 用适配器推理一批
hex_counter = Counter()
upper_counter = Counter()
lower_counter = Counter()
direction_counter = Counter()

# 取最后 100 根，每隔 2 根取一个，避免过采样
n_samples = 0
for i in range(max(0, len(df)-200), len(df), 2):
    result = adapter.infer(df.iloc[:i+1])
    if not result:
        continue
    hex_name = result.get('hexagram', {}).get('hexagram_name_cn', '?') if isinstance(result.get('hexagram'), dict) else str(result.get('hexagram', '?'))
    upper = result.get('hexagram', {}).get('upper_gua', {}).get('name', '?') if isinstance(result.get('hexagram'), dict) else '?'
    lower = result.get('hexagram', {}).get('lower_gua', {}).get('name', '?') if isinstance(result.get('hexagram'), dict) else '?'
    direction = result.get('next_state', {}).get('direction', '?') if isinstance(result.get('next_state'), dict) else str(result.get('direction', '?'))

    hex_counter[hex_name] += 1
    upper_counter[upper] += 1
    lower_counter[lower] += 1
    direction_counter[direction] += 1
    n_samples += 1

if n_samples > 0:
    print(f"\n最近 {n_samples} 次推理卦象分布 (Top 20):")
    for name, cnt in hex_counter.most_common(20):
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

    print(f"\n方向分布:")
    for name, cnt in direction_counter.most_common():
        pct = cnt / n_samples * 100
        print(f"  {name}: {cnt} ({pct:.1f}%)")

# 检查卦象生成逻辑：是否坤卦特征最多导致偏斜
print()
print("=" * 60)
print("【诊断 2】卦象偏斜根因分析")
print("=" * 60)

engine = adapter.engine
if hasattr(engine, 'hexagram_mapper'):
    hm = engine.hexagram_mapper
    from scripts.memory_l4.bcrm2.dialectical_ml_engine import GUA_DIMENSION_MAP

    # 各卦特征数量
    print("\n各卦维度特征数量:")
    gua_feat_counts = {}
    for gua, feats in hm.feature_names_by_gua.items():
        if gua in GUA_DIMENSION_MAP:
            name = GUA_DIMENSION_MAP[gua]['name']
            count = len(feats)
            gua_feat_counts[gua] = count
            print(f"  {name}({gua}): {count}个特征")

    # 关键检查：特征数最多的卦活跃度天然高？
    max_feat = max(gua_feat_counts.values())
    min_feat = min(gua_feat_counts.values())
    print(f"\n  特征数范围: {min_feat} ~ {max_feat} (差异 {max_feat/min_feat:.1f}x)")
    print("  ⚠️  如果特征数差异大，活跃度=平均绝对值也会偏斜")
    print("  💡 修复思路：对每个卦的活跃度做归一化（除以特征数或使用均值已做部分归一化）")

    # 检查当前使用的是均值还是总和
    print("\n活跃度计算方式: np.mean(vals) = 绝对值的平均")
    print("  问题：如果某卦特征数多，但每个特征的波动小，均值可能仍低")
    print("  反之，如果某卦特征本身波动就大，均值会天然偏高")

print()
print("=" * 60)
print("【诊断 3】实盘反馈闭环检查")
print("=" * 60)

# 检查 CBR 案例库
try:
    from scripts.memory_l4.cbr_engine import CBREngine
    cbr = CBREngine()
    if hasattr(cbr, 'get_stats'):
        stats = cbr.get_stats()
        print(f"\nCBR 案例库: {stats.get('total_cases', '?')} 个案例")
    elif hasattr(cbr, 'case_base') and hasattr(cbr.case_base, 'cases'):
        print(f"\nCBR 案例库: {len(cbr.case_base.cases)} 个案例")
    else:
        print("\nCBR 案例库: 加载成功")
except Exception as e:
    print(f"\nCBR 案例库检查失败: {e}")

# 检查增量学习数据库
try:
    from scripts.memory_l4.bcrm2.incremental_learner import IncrementalLearner
    learner = IncrementalLearner()
    if hasattr(learner, 'db'):
        db = learner.db
        if hasattr(db, 'get_total_trades'):
            total_trades = db.get_total_trades()
            print(f"增量学习数据库: {total_trades} 条交易记录")
        elif hasattr(db, 'trades'):
            print(f"增量学习数据库: {len(db.trades)} 条交易记录")
        else:
            print(f"增量学习数据库: 存在但无法统计")
except Exception as e:
    print(f"增量学习数据库检查失败: {e}")

# 检查 UnifiedCaseRegistry
try:
    from scripts.memory_l4.unified_case_registry import UnifiedCaseRegistry
    reg = UnifiedCaseRegistry()
    cases_dir = getattr(reg, 'cases_dir', None)
    if cases_dir:
        case_files = list(cases_dir.glob("*.json")) if hasattr(cases_dir, 'glob') else []
        print(f"UnifiedCaseRegistry: {len(case_files)} 个case文件 ({cases_dir})")
    else:
        print("UnifiedCaseRegistry: 存在（无cases_dir属性）")
except Exception as e:
    print(f"UnifiedCaseRegistry: 导入失败 {e}")

# 检查 polling_trader 中平仓逻辑
print()
print("【反馈闭环链路审查】")
print()

import ast
import inspect
from scripts.memory_l4 import polling_trader

# 检查 _close_position 方法
if hasattr(polling_trader, 'PollingTrader'):
    cls = polling_trader.PollingTrader
    if hasattr(cls, '_close_position'):
        src = inspect.getsource(cls._close_position)
        print("  _close_position 方法中的反馈调用:")
        for keyword in ['register_trade', 'save_case', 'incremental_learner', 'log_trade',
                       'trigger_retrain', 'update_calibration', 'knowledge_bridge']:
            if keyword in src:
                print(f"    ✅ {keyword}")
            else:
                print(f"    ❌ {keyword} (缺失)")
