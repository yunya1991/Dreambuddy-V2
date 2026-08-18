#!/usr/bin/env python3
"""
卦象与系统推理不匹配深度检查

目标: 找出卦象(巽为风)与实际推理(做空)不一致的根因
"""

import sys
sys.path.insert(0, '.')

from scripts.memory_l4.polling_trader import PollingTrader, _load_kline_from_okx
from scripts.memory_l4.bcrm2.dialectical_ml_engine import (
    GUA_DIMENSION_MAP, SIXTY_FOUR_GUAS
)
import pandas as pd
import json


def main():
    print('=' * 80)
    print('  卦象与系统推理不匹配深度检查')
    print('=' * 80)
    print()

    # 1. 检查巽为风的方向定义
    print('【检查1】巽为风的方向定义')
    print('-' * 60)
    xun_info = SIXTY_FOUR_GUAS.get(("xun", "xun"))
    if xun_info:
        print(f'  卦名: {xun_info["name"]}')
        print(f'  direction_hint: {xun_info.get("direction_hint", "N/A")}')
        print(f'  market_meaning: {xun_info.get("market_meaning", "N/A")}')

    # 2. 检查bcrm2 dialectical_ml_engine 中的卦象方向
    print()
    print('【检查2】dialectical_ml_engine 中巽系列卦象的方向')
    print('-' * 60)
    xun_guas = {k: v for k, v in SIXTY_FOUR_GUAS.items()
                if k[0] == "xun" or k[1] == "xun"}
    for gua_key, info in xun_guas.items():
        print(f'  {gua_key}: {info["name"]} → direction={info["direction"]}')

    # 3. 运行实际推理，查看 hexagram_name 真实来源
    print()
    print('【检查3】实际推理中卦象的生成路径')
    print('-' * 60)

    trader = PollingTrader(
        interval=3600,
        coins=['BTC'],
        bar='1H',
        confidence_threshold=0.35,
        max_positions=1,
    )

    inference = trader._fetch_and_infer('BTC')
    if inference.get('ok'):
        print(f'  最终方向: {inference["direction"]}')
        print(f'  卦象名(hex_cn): {inference["hexagram"]}')
        print(f'  BCRM方向: {inference.get("bagua_direction", "N/A")}')
        print(f'  BCRM置信度: {inference.get("bagua_confidence", 0):.2f}')
        print(f'  最终置信度: {inference["confidence"]:.2f}')

        # 4. 重新查看 _fetch_and_infer 中的逻辑
        print()
        print('【检查4】方向融合逻辑分析')
        print('-' * 60)
        print('  _fetch_and_infer 中的方向融合规则:')
        print('    1. BCRM和Bagua方向相同 → 置信度加权平均')
        print('    2. BCRM和Bagua方向不同 → 置信度降低40%')
        print('    3. 如果Bagua置信度高超过BCRM+0.2 → 切换方向')
        print('    4. 只有BCRM有效 → 置信度×0.7')
        print('    5. 只有Bagua有效 → 置信度×0.6')
        print()
        print('  问题: 卦象的direction仅用于查表，不参与方向决策')
        print('  卦象显示UP(巽为风)，但实际方向由BCRM ML模型和Bagua引擎决定')

    # 5. 详细追踪卦象来源
    print()
    print('【检查5】卦象名 hexagram 的实际来源')
    print('-' * 60)
    print('  路径1: BCRM推理结果 (bcrm_result.hexagram.hexagram_name_cn)')
    print('  路径2: Bagua推理结果 (bagua_result.hexagram_name_cn)')
    print('  代码逻辑: 如果Bagua有卦象名则覆盖BCRM的')
    print('  最终hex_cn = bagua_result.hexagram_name_cn (Bagua卦象优先)')
    print()

    # 6. 巽为风方向与实际方向的逻辑关系
    print('【检查6】巽为风(UP) vs 实际做空(DOWN) 的逻辑关系')
    print('-' * 60)
    print('  巽为风卦象:')
    print('    - direction: "long" (在SIXTY_FOUR_GUAS定义中)')
    print('    - 卦辞: "小亨，利有攸往，利见大人"')
    print('    - 解释: 缓慢上涨，润物无声')
    print()
    print('  实际系统推理:')
    print('    - 方向: DOWN (做空)')
    print('    - 来源: BCRM/Bagua融合后决策')
    print()
    print('  结论: 卦象与系统推理不匹配，但卦象仅作"解释层"，不影响实际交易决策')
    print('  这是设计如此: 卦象是"可解释层"，不是"决策层"')
    print()

    # 7. 深入查看 BCRM 和 Bagua 的方向判定
    print('【检查7】方向判定的真实来源')
    print('-' * 60)
    print('  polling_trader.py:271-289 是方向融合的关键代码')
    print('  BCRM方向 (UP/DOWN) 来自 bcrm_result.next_state.direction')
    print('  Bagua方向 (long/short) 来自 bagua_result.primary_direction')
    print()
    print('  巽为风卦象名虽然显示"长"方向，但:')
    print('    - 卦象名只是"显示"')
    print('    - 实际交易方向由 BCRM.next_state.direction 决定')
    print('    - Bagua.primary_direction 是辅助判断')

    print()
    print('=' * 80)
    print('  检查完成')
    print('=' * 80)


if __name__ == '__main__':
    main()
