#!/usr/bin/env python3
"""R-1 提案批量评审（遗留评审项 1，spec v0.5 ⑤ 扩展）。

逐份分析 22 份自动生成提案的质量维度，产出评审报告：
  - 案例数（case_count：≥3 充分，1-2 不足）
  - 关键词噪声率（n-gram 碎片词占比：含非完整语义词）
  - 与现有 15 种意图边界重叠（关键词与既有规则冲突）
  - 描述完备性（description 是否为模板占位）
结论：recommend（建议合入）/ hold（建议搁置观察）/ reject（建议拒绝）。
评审结果写回各提案 review 字段（status: reviewed + 结论），汇总报告落盘。
注意：本脚本只做评审标记，不合入任何意图（合入保留人工批准）。
"""
import json
import re
from pathlib import Path

PROP_DIR = Path('/home/luke/dreambuddy/34-前端应用训练系统/proposals')
REPORT_PATH = PROP_DIR / 'review_report_20261025.json'

# 现有 15 种意图的代表性关键词（边界重叠检测，取自 fallback-engine 硬编码规则核心词）
EXISTING_INTENT_KEYWORDS = {
    'market_query': ['价格', '什么价', '行情', '现在', '走势', '多少钱'],
    'credits_query': ['余额', '多少', '充值', '额度'],
    'deep_analysis': ['深度分析', '深入分析', '技术分析', '走势分析', '全面分析'],
    'scenario_sim': ['情景推演', '情景分析', '假设', '推演', '模拟', '压力测试'],
    'strategy_verify': ['策略验证', '回测', '验证策略', '策略回测', 'backtest'],
    'execute_trade': ['开仓', '下单', '买入', '卖出', '做多', '做空', '平仓'],
    'developer': ['部署', '构建', '测试', '修复', '日志'],
    'data_query': ['查询', '数据', '记录', '统计'],
    'simple_qa': ['什么是', '是什么', '解释', '定义'],
    'need_clarification': [],
}


def keyword_noise_ratio(keywords):
    """n-gram 碎片词占比：非完整语义词（长度≤2 或为长词子串）视为噪声。"""
    if not keywords:
        return 0.0
    noise = 0
    all_kw = [k for k in keywords if k]
    for kw in all_kw:
        # 碎片词特征：长度≤2，或是其他更长关键词的子串
        is_fragment = len(kw) <= 2 or any(kw != other and kw in other for other in all_kw if len(other) > len(kw))
        if is_fragment:
            noise += 1
    return round(noise / len(all_kw), 3)


def overlap_with_existing(keywords):
    """与现有意图关键词重叠检测。"""
    overlaps = []
    for kw in keywords:
        for intent, existing_kws in EXISTING_INTENT_KEYWORDS.items():
            for ekw in existing_kws:
                if kw == ekw or (len(kw) >= 3 and kw in ekw) or (len(ekw) >= 3 and ekw in kw):
                    overlaps.append({'keyword': kw, 'existing_intent': intent, 'existing_keyword': ekw})
    return overlaps


def review_one(prop):
    """单份提案评审 → 结论与理由。"""
    intent = prop.get('intent') or {}
    evidence = prop.get('evidence') or {}
    keywords = intent.get('keywords') or []
    case_count = int(evidence.get('case_count') or 0)
    desc = str(intent.get('description') or '')
    reasons = []

    # 维度 1：案例数
    case_ok = case_count >= 3
    if not case_ok:
        reasons.append(f'案例数不足（{case_count} < 3，证据薄弱）')
    else:
        reasons.append(f'案例数充分（{case_count}）')

    # 维度 2：关键词噪声
    noise = keyword_noise_ratio(keywords)
    noise_ok = noise <= 0.3
    if not noise_ok:
        reasons.append(f'关键词噪声率高（{noise:.0%}，n-gram 碎片词）')
    else:
        reasons.append(f'关键词噪声率低（{noise:.0%}）')

    # 维度 3：边界重叠
    overlaps = overlap_with_existing(keywords)
    overlap_ok = len(overlaps) == 0
    if not overlap_ok:
        overlap_intents = sorted(set(o['existing_intent'] for o in overlaps))
        reasons.append(f'与现有意图重叠（{", ".join(overlap_intents)}）')
    else:
        reasons.append('与现有意图无边界重叠')

    # 维度 4：描述完备性
    desc_ok = '待人工评审补充' not in desc and len(desc) >= 10
    if not desc_ok:
        reasons.append('描述为模板占位，不完备')
    else:
        reasons.append('描述完备')

    # 综合结论
    if case_ok and noise_ok and overlap_ok and desc_ok:
        verdict = 'recommend'
    elif overlap_ok and case_ok and (noise_ok or desc_ok):
        verdict = 'hold'
    else:
        verdict = 'reject'
    return {
        'verdict': verdict,
        'reasons': reasons,
        'metrics': {
            'case_count': case_count,
            'noise_ratio': noise,
            'overlap_count': len(overlaps),
            'overlaps': overlaps[:5],
            'desc_complete': desc_ok,
        },
    }


def main():
    props = sorted(PROP_DIR.glob('prop_*.json'))
    results = []
    for pf in props:
        try:
            prop = json.loads(pf.read_text(encoding='utf-8'))
        except Exception as exc:
            results.append({'file': pf.name, 'error': str(exc)})
            continue
        review = review_one(prop)
        # 评审结果写回提案 review 字段（仅标记，不合入）
        prop.setdefault('review', {})
        prop['review']['status'] = 'reviewed'
        prop['review']['reviewed_at'] = '2026-10-25T00:30:00'
        prop['review']['verdict'] = review['verdict']
        prop['review']['reasons'] = review['reasons']
        prop['review']['metrics'] = review['metrics']
        pf.write_text(json.dumps(prop, ensure_ascii=False, indent=2), encoding='utf-8')
        results.append({
            'file': pf.name,
            'intent_id': (prop.get('intent') or {}).get('id'),
            'intent_name': (prop.get('intent') or {}).get('name'),
            'verdict': review['verdict'],
            'case_count': review['metrics']['case_count'],
            'noise_ratio': review['metrics']['noise_ratio'],
            'overlap_count': review['metrics']['overlap_count'],
        })
    summary = {
        'total': len(results),
        'recommend': sum(1 for r in results if r.get('verdict') == 'recommend'),
        'hold': sum(1 for r in results if r.get('verdict') == 'hold'),
        'reject': sum(1 for r in results if r.get('verdict') == 'reject'),
    }
    report = {'generated_at': '2026-10-25T00:30:00', 'summary': summary, 'details': results}
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'success': True, 'summary': summary, 'report_path': str(REPORT_PATH)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
