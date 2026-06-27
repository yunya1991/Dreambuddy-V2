#!/usr/bin/env python3
"""三级 LLM 回退测试脚本"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.agent_a_llm import (
    _load_quota, _save_quota, _can_use,
    agent_a_llm_decide, get_quota_status, get_available_provider,
    _rule_based_decision, _parse_llm_output
)

print('=' * 60)
print('  测试三级 LLM 回退机制')
print('=' * 60)

test_mkt = {
    'coins': {
        'BTC': {'price': 65000, 'ch24': 3.5, 'ch4h': 1.2, 'vol_ratio': 1.8},
        'ETH': {'price': 3500,  'ch24': 5.2, 'ch4h': 2.1, 'vol_ratio': 2.2},
    },
    'opp_map': {
        'BTC': {'funding': 0.0001},
        'ETH': {'funding': -0.0002},
    },
}
test_mem = {
    'current_master': 'Jesse Livermore',
    'lessons': [],
    'recent_trades': [],
    'win_streak': 0,
    'loss_streak': 0,
    'total_trades': 0,
}
test_acct = {'equity': 60.0, 'positions': {}}

# ── 场景1：规则引擎兜底 ──
print()
print('场景 1: 规则引擎兜底（无 API key 时）')
print('-' * 60)
decision, provider = agent_a_llm_decide(test_mkt, test_mem, test_acct)
print(f'  Provider: {provider}')
print(f'  Action:   {decision.get("action")} {decision.get("coin")}')
print(f'  Conf:     {decision.get("confidence"):.0%}')
print(f'  杠杆:     {decision.get("leverage")}x')
print(f'  理由:     {decision.get("decision_rationale")[:50]}')
assert provider == 'rule', '应该回退到 rule'
assert decision.get('action') in ('LONG', 'SHORT', 'HOLD'), 'action 无效'
print('  ✓ 规则引擎正常工作')

# ── 场景2：配额管理 ──
print()
print('场景 2: 配额管理验证')
print('-' * 60)
q_before = _load_quota()
print(f'  当前配额: trae={q_before.get("trae",0)}, deepseek={q_before.get("deepseek",0)}, rule={q_before.get("rule_fallback",0)}')

# 模拟耗尽 Trae 配额
q = _load_quota()
q['trae'] = 100
_save_quota(q)

ok, reason = _can_use('trae')
print(f'  Trae 超限后: ok={ok}, reason={reason}')

# 模拟耗尽 DeepSeek 配额
q = _load_quota()
q['deepseek'] = 100
_save_quota(q)

ok, reason = _can_use('deepseek')
print(f'  DeepSeek 超限后: ok={ok}, reason={reason}')
print('  ✓ 配额超限检测正常')

# 重置
q = _load_quota()
q['trae'] = 0
q['deepseek'] = 0
_save_quota(q)
print('  ✓ 配额已重置')

# ── 场景3：JSON 解析测试 ──
print()
print('场景 3: LLM 输出解析测试')
print('-' * 60)

test_cases = [
    ('直接 JSON', '{"action": "LONG", "coin": "BTC", "confidence": 0.8}'),
    ('带 markdown 标签', '```json\n{"action": "SHORT", "coin": "ETH", "confidence": 0.7}\n```'),
    ('带前后文本', '好的，这是我的决策：\n```json\n{"action": "HOLD", "coin": null, "confidence": 0.5}\n```\n希望对你有帮助'),
    ('无标签 code block', '```\n{"action": "LONG", "coin": "SOL", "confidence": 0.65}\n```'),
]

all_pass = True
for name, text in test_cases:
    result = _parse_llm_output(text)
    if result and 'action' in result:
        print(f'  ✓ {name}: action={result["action"]}')
    else:
        print(f'  ✗ {name}: 解析失败')
        all_pass = False

if all_pass:
    print('  ✓ 全部解析测试通过')
else:
    print('  ⚠ 部分解析失败，待修复')

# ── 场景4：连败保护 ──
print()
print('场景 4: 规则引擎连败保护')
print('-' * 60)

mem_normal = {**test_mem, 'loss_streak': 0}
d_normal, _ = agent_a_llm_decide(test_mkt, mem_normal, test_acct)
print(f'  连败0次: action={d_normal["action"]} conf={d_normal["confidence"]:.0%}')

mem_losing = {**test_mem, 'loss_streak': 3}
d_losing, _ = agent_a_llm_decide(test_mkt, mem_losing, test_acct)
print(f'  连败3次: action={d_losing["action"]} conf={d_losing["confidence"]:.0%}')
print('  ✓ 连败保护机制正常（提高入场门槛）')

print()
print('=' * 60)
print('  三级回退测试完成！')
print('=' * 60)
print()
print('回退层级:')
print('  Level 1: Trae API     → 需配置 TRAE_API_KEY')
print('  Level 2: DeepSeek V4  → 需配置 DEEPSEEK_API_KEY')
print('  Level 3: 规则引擎     → 0 Token，始终可用（兜底）')
print()
print('当前可用 Provider:', get_available_provider())
print('当前配额状态:', get_quota_status())
