#!/usr/bin/env python3
"""模块化系统验证脚本"""
import sys
sys.path.insert(0, '.')

print('=== 模块导入测试 ===')

# 1. 测试模块适配器层
try:
    from core.modules.classic_indicators import ClassicIndicatorsClient
    print('✅ core.modules.classic_indicators 导入成功')
except Exception as e:
    print('❌ core.modules.classic_indicators 失败:', e)

try:
    from core.modules.fundamental_api import FundamentalAPIClient
    print('✅ core.modules.fundamental_api 导入成功')
except Exception as e:
    print('❌ core.modules.fundamental_api 失败:', e)

try:
    from core.modules.skill_loader import SkillLoader, execute_skill
    print('✅ core.modules.skill_loader 导入成功')
except Exception as e:
    print('❌ core.modules.skill_loader 失败:', e)
    import traceback
    traceback.print_exc()

# 2. 测试节点层
print()
print('=== 节点层测试 ===')
try:
    from core.nodes import NODE_HANDLERS, list_nodes, node_exists
    print('✅ 节点注册表加载成功，共', len(NODE_HANDLERS), '个节点')
    print('   节点列表:', list_nodes())
except Exception as e:
    print('❌ 节点注册表失败:', e)
    import traceback
    traceback.print_exc()

# 3. 测试 SKILL 加载
print()
print('=== SKILL 加载测试 ===')
try:
    loader = SkillLoader()
    print('   project_root:', loader.project_root)
    for skill in ['dream-contradiction-theory', 'dream-first-principles']:
        available = loader.is_skill_available(skill)
        status = "✅可用" if available else "❌不可用"
        print('  ', skill, ':', status)
        if available:
            md = loader.load_skill_md(skill)
            phases = loader.parse_phases(md)
            print('     解析到', len(phases), '个阶段')
except Exception as e:
    print('❌ SKILL 加载失败:', e)
    import traceback
    traceback.print_exc()

# 4. 测试 SKILL 执行
print()
print('=== SKILL 执行测试 ===')
test_mkt = {
    'price': 59500,
    'rsi14': 29.7,
    'ema20': 59760,
    'ema50': 59510,
    'ema200': 59511,
    'atr14': 359,
    'funding_rate': 0.000125,
    'change_24h': 0.57,
    'vol_ratio': 1.02,
    'regime': 'RANGE',
    'coin': 'BTC',
}

try:
    result = execute_skill('dream-contradiction-theory', {'mkt': test_mkt, 'memory': {}, 'data': {}})
    print('✅ A0矛盾论执行成功')
    print('   方向:', result.direction, '| 置信度:', f"{result.confidence:.0%}")
    print('   SKILL版本: v' + result.version, '| 使用SKILL:', result.used_skill)
except Exception as e:
    print('❌ A0矛盾论失败:', e)
    import traceback
    traceback.print_exc()

try:
    a0 = {'dominant_force': 'BULL', 'confidence': 0.5, 'bull_count': 2, 'bear_count': 1}
    result = execute_skill('dream-first-principles', {'mkt': test_mkt, 'memory': {}, 'data': {}, 'a0': a0})
    print('✅ A2第一性原理执行成功')
    print('   方向:', result.direction, '| 置信度:', f"{result.confidence:.0%}")
    print('   SKILL版本: v' + result.version, '| 使用SKILL:', result.used_skill)
    lr = result.data.get('least_resistance', 'N/A')
    print('   阻力最小:', lr)
    trend_phase = result.data.get('trend', {}).get('phase', 'N/A')
    print('   趋势:', trend_phase)
except Exception as e:
    print('❌ A2第一性原理失败:', e)
    import traceback
    traceback.print_exc()

# 5. 测试节点执行
print()
print('=== 节点执行测试 ===')
from core.nodes import c1_execute, a0_execute, a2_execute, f2_execute, f3_execute

try:
    r = c1_execute(test_mkt, {}, {})
    src = r.get('source', 'unknown')
    print('✅ C1技术扫描:', r['direction'], '| conf=' + f"{r['confidence']:.0%}", '| source=' + src)
except Exception as e:
    print('❌ C1技术扫描失败:', e)

try:
    r = a0_execute(test_mkt, {}, {})
    ver = r.get('skill_version', 'unknown')
    used = r.get('skill_used', False)
    print('✅ A0矛盾论:', r['direction'], '| conf=' + f"{r['confidence']:.0%}", '| skill=' + ver, '| used=' + str(used))
except Exception as e:
    print('❌ A0矛盾论失败:', e)
    import traceback
    traceback.print_exc()

try:
    r = a2_execute(test_mkt, {}, {})
    ver = r.get('skill_version', 'unknown')
    used = r.get('skill_used', False)
    print('✅ A2第一性原理:', r['direction'], '| conf=' + f"{r['confidence']:.0%}", '| skill=' + ver, '| used=' + str(used))
except Exception as e:
    print('❌ A2第一性原理失败:', e)
    import traceback
    traceback.print_exc()

try:
    r = f2_execute(test_mkt, {}, {})
    src = r.get('source', 'unknown')
    print('✅ F2资金流:', r['direction'], '| conf=' + f"{r['confidence']:.0%}", '| source=' + src)
except Exception as e:
    print('❌ F2资金流失败:', e)

try:
    r = f3_execute(test_mkt, {}, {})
    src = r.get('source', 'unknown')
    print('✅ F3情绪:', r['direction'], '| conf=' + f"{r['confidence']:.0%}", '| source=' + src)
except Exception as e:
    print('❌ F3情绪失败:', e)

print()
print('=== 所有测试完成 ===')
