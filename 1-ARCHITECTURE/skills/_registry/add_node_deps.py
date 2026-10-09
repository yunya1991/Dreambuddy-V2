#!/usr/bin/env python3
"""
为 registry.json 中的 trading-domain SKILL 补全 node_dependencies 字段。

映射规则（SPEC §3.1 node_id → DSH Subagent 映射表）:
  C1/C2/C3 → DSH_TECHNICAL (技术指标)
  F1 → DSH_SENTIMENT (情绪面)
  F5 → DSH_MACRO (宏观面)
  F2 → DSH_FLOW (资金面)
  F3 → DSH_VALUATION (估值面)
  F4 → DSH_ONCHAIN (链上面)
  A0-A9 / G1-G2 → 无对应 Subagent，node_dependencies 为空（走 LLM 兜底，SPEC §448-451）

只处理 trading-domain 的 SKILL（第 1 批：有明确系统节点对应关系的 SKILL）。
A 链方法论 SKILL 的 node_dependencies 保持为空 []。
"""
import json
import os
import sys

REGISTRY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'registry.json')

# SKILL name → node_dependencies 映射（基于 SPEC §3.1 + §1153 分批策略第 1 批）
# 只补全 trading-domain 且有明确系统节点对应关系的 SKILL
SKILL_NODE_DEPS = {
    # 技术面 SKILL → C1/C2/C3 (DSH_TECHNICAL)
    'dream-backtest':                   ['C3'],            # 回测验证，技术指标
    'dream-screen1-first':              ['C1', 'C2'],      # Screen1 选币技术筛选
    'dream-screen2-second':              ['C1', 'C2'],      # Screen2 日线技术筛选
    'dream-screen3-third':               ['C1', 'C2'],      # Screen3 技术筛选
    'dream-regime-detector':            ['C1', 'C2', 'C3'],  # 市场状态识别，技术指标
    'screen1-trigger':                  ['C1', 'C2'],      # 触发器依赖技术指标
    'screen2-trigger':                  ['C1', 'C2'],
    'screen3-trigger':                  ['C1', 'C2'],
    'agent-collab-screen1':             ['C1', 'C2'],      # 协作筛选
    '6-trading-screen1-framework':      ['C1', 'C2', 'C3', 'F1', 'F5', 'F4'],  # 七维牛熊检测

    # 多面调研 SKILL → 多节点
    'asset-research':                   ['C1', 'C2', 'C3', 'F1', 'F5', 'F4'],  # 资产标的调研，多面分析

    # A 链方法论 SKILL → node_dependencies 为空（走 LLM 兜底，SPEC §448-451）
    # A7-practice-theory, dream-strategy-designer 等保持空 []
}


def main():
    with open(REGISTRY_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)

    skills = data.get('skills', [])
    updated = 0
    skipped = 0

    for skill in skills:
        name = skill.get('name', '')
        domain = (skill.get('facets') or {}).get('domain', '')

        # 只处理 trading-domain 的 SKILL
        if domain != 'trading':
            continue

        if name in SKILL_NODE_DEPS:
            # 补全 node_dependencies 字段
            old_deps = skill.get('node_dependencies')
            new_deps = SKILL_NODE_DEPS[name]
            if old_deps != new_deps:
                skill['node_dependencies'] = new_deps
                updated += 1
                print(f'  ✓ {name}: node_dependencies = {new_deps}')
            else:
                skipped += 1
        else:
            # A 链方法论或其他 trading SKILL → node_dependencies 为空（已存在则跳过）
            if 'node_dependencies' not in skill:
                skill['node_dependencies'] = []
                # 不计入 updated，因为这只是声明空字段
                # 但也不计入 skipped，因为这是新增声明
                print(f'  · {name}: node_dependencies = [] (A 链方法论/无对应 Subagent, 走 LLM 兜底)')

    # 写回 registry.json（保持格式）
    with open(REGISTRY_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')

    print(f'\nDone: {updated} SKILL updated, {skipped} unchanged')
    print(f'Registry path: {REGISTRY_PATH}')


if __name__ == '__main__':
    main()
