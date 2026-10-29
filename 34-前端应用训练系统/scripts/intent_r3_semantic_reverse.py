#!/usr/bin/env python3
"""R-3 三层金融语义推理逆向（spec v0.5 §3.2/§9.2，P5）。

消费 39 系统 reasoning_trace.jsonl（推理过程记录，P5 前置 M3 采集），
产出语义推理路径案例（原子事件→复杂语义→三层综合的推理链），沉淀训练案例。

用法（stdin JSON → stdout JSON，FAIL-OPEN）：
  echo '{"cmd":"run"}' | python3 intent_r3_semantic_reverse.py
  echo '{"cmd":"stats"}' | python3 intent_r3_semantic_reverse.py
"""
import json
import sys
from pathlib import Path

REPO_ROOT = Path('/home/luke/dreambuddy')
TRACE_PATH = REPO_ROOT / '39-金融语义蒸馏系统' / 'reasoning_trace.jsonl'
OUT_PATH = REPO_ROOT / '34-前端应用训练系统' / 'semantic_reasoning_cases.jsonl'


def load_traces():
    """加载推理过程记录（FAIL-OPEN：不存在返回空）。"""
    traces = []
    if not TRACE_PATH.exists():
        return traces
    for line in TRACE_PATH.read_text(encoding='utf-8').splitlines():
        if line.strip():
            try:
                traces.append(json.loads(line))
            except Exception:
                continue
    return traces


def trace_to_case(trace, idx):
    """单条推理记录 → 语义推理路径案例。

    推理链三层映射：
      L1 原子层：查询输入（term/message）
      L2 语义层：各层语义命中（entity/term_domain/匹配方式）
      L3 综合层：综合结论（symbol/type/domain）
    """
    hits = trace.get('semantic_hits') or []
    conclusion = trace.get('conclusion') or {}
    # 推理链路：输入 → 命中层序列 → 结论
    chain = ['input:' + str(list((trace.get('input') or {}).values())[0] if trace.get('input') else '')]
    for h in hits:
        chain.append('%s:%s' % (h.get('layer'), h.get('value')))
    chain.append('conclusion:%s' % (conclusion.get('symbol') or conclusion.get('type') or conclusion.get('error') or 'unknown'))
    # 质量评估：命中层数多、结论明确、耗时低为优
    hit_layers = len(hits)
    resolved = bool(conclusion.get('symbol') or conclusion.get('type') == 'term')
    fast = float(trace.get('elapsed_ms') or 0) < 100
    quality = 'good' if (resolved and hit_layers >= 1) else ('degraded' if hit_layers else 'poor')
    return {
        'schema_version': '0.5',
        'case_id': 'r3_%s_%03d' % (trace.get('tool', 'unknown'), idx),
        'source': 'r3_semantic_reverse',
        'tool': trace.get('tool'),
        'reasoning_layers': {
            'l1_atomic': trace.get('input'),
            'l2_semantic_hits': hits,
            'l3_synthesis': conclusion,
        },
        'reasoning_chain': chain,
        'elapsed_ms': trace.get('elapsed_ms'),
        'llm_involved': trace.get('llm_involved'),
        'resolved': resolved,
        'quality': quality,
        'fast': fast,
    }


def cmd_run(_args):
    traces = load_traces()
    cases = []
    for idx, trace in enumerate(traces):
        cases.append(trace_to_case(trace, idx))
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        for c in cases:
            f.write(json.dumps(c, ensure_ascii=False) + '\n')
    resolved = sum(1 for c in cases if c['resolved'])
    return {
        'success': True,
        'traces_consumed': len(traces),
        'cases_produced': len(cases),
        'resolved_cases': resolved,
        'unresolved_cases': len(cases) - resolved,
        'quality_dist': {
            'good': sum(1 for c in cases if c['quality'] == 'good'),
            'degraded': sum(1 for c in cases if c['quality'] == 'degraded'),
            'poor': sum(1 for c in cases if c['quality'] == 'poor'),
        },
        'llm_involved_cases': sum(1 for c in cases if c.get('llm_involved')),
        'output_path': str(OUT_PATH),
    }


def cmd_stats(_args):
    if not OUT_PATH.exists():
        return {'success': True, 'cases': 0, 'note': 'cases not built yet'}
    cases = []
    for line in OUT_PATH.read_text(encoding='utf-8').splitlines():
        if line.strip():
            try:
                cases.append(json.loads(line))
            except Exception:
                pass
    return {
        'success': True,
        'cases': len(cases),
        'resolved': sum(1 for c in cases if c.get('resolved')),
        'tools': sorted(set(c.get('tool') for c in cases)),
    }


def main():
    try:
        req = json.loads(sys.stdin.read() or '{}')
    except json.JSONDecodeError:
        print(json.dumps({'success': False, 'error': 'invalid json'}, ensure_ascii=False))
        return 1
    cmd = str(req.get('cmd', 'run'))
    try:
        if cmd == 'run':
            result = cmd_run(req)
        elif cmd == 'stats':
            result = cmd_stats(req)
        else:
            result = {'success': False, 'error': 'unknown cmd: %s' % cmd}
    except Exception as exc:  # FAIL-OPEN
        result = {'success': False, 'error': str(exc)}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get('success') else 1


if __name__ == '__main__':
    sys.exit(main())
