#!/usr/bin/env python3
"""复杂意图链路模板执行器（spec v0.5 §4 L2，P4）。

复杂意图库命中后，按 chain_template 经 33-REA DSH_NODE_REGISTRY 直接驱动完整链路执行。
stdin JSON → stdout JSON，FAIL-OPEN：任一节点失败不阻断，返回已执行结果与降级标记。

用法：
  echo '{"cmd":"execute","entry_id":"...","message":"..."}' | python3 intent_chain_executor.py
  echo '{"cmd":"lookup","message":"..."}' | python3 intent_chain_executor.py
"""
import json
import sys
from pathlib import Path

REPO_ROOT = Path('/home/luke/dreambuddy')
LIB_PATH = REPO_ROOT / '34-前端应用训练系统' / 'complex_intent_library.jsonl'
REA_ROOT = REPO_ROOT / '33-REA逆向解析工程'

# 发现树通用 analyzer → 33-REA 节点映射（链路模板直接驱动）
ANALYZER_NODE_MAP = {
    'init': 's33_rea_analyze',
    'acceptance_gate': 's33_rea_audit',
    'code_commit': 's33_rea_trace',
    'doc_sync': 's33_rea_narrative',
    'cognitive_record': 's33_rea_reflect',
    'analyze': 's33_rea_analyze',
    'trace': 's33_rea_trace',
    'compare': 's33_rea_compare',
    'investigate': 's33_rea_investigate',
    'recover_decisions': 's33_rea_recover_decisions',
    'narrative': 's33_rea_narrative',
    'audit': 's33_rea_audit',
    'locate': 's33_rea_locate',
    'reflect': 's33_rea_reflect',
    'dream': 's33_rea_dream',
    'replay': 's33_rea_replay',
    'harvest': 's33_rea_harvest',
    'spec_enhance': 's33_rea_spec_enhance',
    'optimal_path': 's33_rea_optimal_path',
}


def load_library():
    """加载复杂意图库（FAIL-OPEN：不存在返回空）。"""
    entries = []
    if not LIB_PATH.exists():
        return entries
    for line in LIB_PATH.read_text(encoding='utf-8').splitlines():
        if line.strip():
            try:
                entries.append(json.loads(line))
            except Exception:
                continue
    return entries


def match_score(message, entry):
    """消息 → 库条目触发匹配分（target/feature/task_type 关键词命中计分）。"""
    if not message:
        return 0.0
    trigger = entry.get('trigger') or {}
    score = 0.0
    for field, weight in (('target', 0.5), ('feature', 0.3), ('task_type', 0.2)):
        kw = str(trigger.get(field) or '')
        if kw and kw in message:
            score += weight
    return score


def cmd_lookup(args):
    """库查询：消息 → 最佳匹配条目（无匹配返回 null，供前端判定走 SACG/DSH）。"""
    message = str(args.get('message') or '')
    entries = load_library()
    best, best_score = None, 0.0
    for e in entries:
        if e.get('status') != 'active':
            continue
        s = match_score(message, e)
        if s > best_score:
            best, best_score = e, s
    if best is None or best_score < 0.2:
        return {'success': True, 'matched': False, 'library_entries': len(entries)}
    return {
        'success': True,
        'matched': True,
        'match_score': best_score,
        'library_entries': len(entries),
        'entry': {
            'entry_id': best.get('entry_id'),
            'trigger': best.get('trigger'),
            'chain_template': best.get('chain_template'),
            'chain_depth': best.get('chain_depth'),
            'avg_poe': best.get('avg_poe'),
            'capability_refs': best.get('capability_refs'),
        },
    }


def cmd_execute(args):
    """链路执行：按 chain_template 逐节点经 33-REA dispatch 驱动（FAIL-OPEN）。"""
    message = str(args.get('message') or '')
    entry_id = str(args.get('entry_id') or '')
    entries = load_library()
    entry = next((e for e in entries if e.get('entry_id') == entry_id), None)
    if entry is None:
        return {'success': False, 'error': 'entry not found: %s' % entry_id}
    chain = entry.get('chain_template') or []
    chain_params = entry.get('chain_params') or []
    if not chain:
        return {'success': False, 'error': 'empty chain_template'}
    # 33-REA dispatch 导入（sys.path 注入）
    sys.path.insert(0, str(REA_ROOT))
    try:
        from dsh_nodes import dispatch  # noqa: E402
    except Exception as exc:
        return {'success': False, 'error': 'rea dispatch unavailable: %s' % exc, 'fail_open': True}
    executed = []
    failed = []
    last_report = None  # 链式传递：analyze 类节点结果 → reflect 类节点 report
    for step_idx, analyzer in enumerate(chain):
        # analyzer → s33_rea_* 节点映射（未映射的默认走 s33_rea_analyze）
        method = ANALYZER_NODE_MAP.get(str(analyzer), 's33_rea_analyze')
        # 按步合并节点参数模板（发现树原始 params，含 feature/commit/report 等）
        step_params = dict(chain_params[step_idx]) if step_idx < len(chain_params) else {}
        # 节点专属参数构造：target 解析为绝对路径；feature 取 trigger；reflect 类节点链式消费前序 analyze 结果
        trigger = entry.get('trigger') or {}
        raw_target = str(trigger.get('target') or '')
        abs_target = str(REPO_ROOT / raw_target) if raw_target and not raw_target.startswith('/') else raw_target
        params = {
            **step_params,
            'trace_id': '%s_s%d' % (entry_id, step_idx),
            'message': message,
            'target': abs_target,
        }
        if method in ('s33_rea_trace', 's33_rea_investigate', 's33_rea_compare'):
            params['feature'] = str(trigger.get('feature') or message)
        if method in ('s33_rea_reflect', 's33_rea_narrative', 's33_rea_audit') and last_report is not None:
            params['report'] = last_report
        try:
            result = dispatch(method, params)
            ok = bool(result.get('ok'))
            if ok and method in ('s33_rea_analyze', 's33_rea_trace', 's33_rea_investigate'):
                # analyze 类节点结果作为链式 report 供后续 reflect 类节点消费
                last_report = result.get('result') if isinstance(result.get('result'), dict) else {'summary': str(result.get('result'))}
            executed.append({'step': step_idx, 'analyzer': str(analyzer), 'node': method, 'ok': ok})
            if not ok:
                failed.append({'step': step_idx, 'analyzer': str(analyzer), 'node': method, 'error': result.get('error')})
        except Exception as exc:
            # FAIL-OPEN：单节点失败记录后继续
            executed.append({'step': step_idx, 'analyzer': str(analyzer), 'node': method, 'ok': False})
            failed.append({'step': step_idx, 'analyzer': str(analyzer), 'node': method, 'error': str(exc)})
    return {
        'success': True,
        'entry_id': entry_id,
        'chain_template': chain,
        'steps_executed': len(executed),
        'steps_failed': len(failed),
        'failed_steps': failed,
        'all_passed': len(failed) == 0,
        'executed': executed,
    }


def main():
    try:
        req = json.loads(sys.stdin.read() or '{}')
    except json.JSONDecodeError:
        print(json.dumps({'success': False, 'error': 'invalid json'}, ensure_ascii=False))
        return 1
    cmd = str(req.get('cmd', 'lookup'))
    try:
        if cmd == 'lookup':
            result = cmd_lookup(req)
        elif cmd == 'execute':
            result = cmd_execute(req)
        else:
            result = {'success': False, 'error': 'unknown cmd: %s' % cmd}
    except Exception as exc:  # FAIL-OPEN
        result = {'success': False, 'error': str(exc), 'fail_open': True}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get('success') else 1


if __name__ == '__main__':
    sys.exit(main())
