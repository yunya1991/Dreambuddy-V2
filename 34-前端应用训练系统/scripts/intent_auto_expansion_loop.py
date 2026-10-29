#!/usr/bin/env python3
"""P6 自动扩展闭环编排（spec v0.5 §7 P6，ADR 对齐）。

闭环：新案例 → 提案 → 自动评审 → 回归测试 → 合入暂存（人工批准）→ 同步 → 决策记录。
- 全自动：提案/评审/测试/暂存/同步自动执行
- 人工保留：合入（merge approval）需人工批准，未批准条目停留 pending
- 决策记录：每步落 ADR 记录（adr_records.jsonl），可追溯可回滚

用法（stdin JSON → stdout JSON，FAIL-OPEN）：
  echo '{"cmd":"run"}' | python3 intent_auto_expansion_loop.py
  echo '{"cmd":"status"}' | python3 intent_auto_expansion_loop.py
  echo '{"cmd":"approve","entry_id":"..."}' | python3 intent_auto_expansion_loop.py
  echo '{"cmd":"rollback","adr_id":"..."}' | python3 intent_auto_expansion_loop.py
"""
import json
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path('/home/luke/dreambuddy')
SYS34 = REPO_ROOT / '34-前端应用训练系统'
PY = '/home/luke/venv-trading/bin/python'
PROPOSER = SYS34 / 'scripts' / 'intent_expansion_proposer.py'
REVIEWER = SYS34 / 'scripts' / 'review_proposals.py'
ADR_PATH = SYS34 / 'adr_records.jsonl'
STAGING_PATH = SYS34 / 'merge_staging.jsonl'


def _run_cli(script, payload):
    """执行 34 系统 CLI（stdin JSON → stdout JSON，FAIL-OPEN）。"""
    try:
        proc = subprocess.run(
            [PY, str(script)],
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True, text=True, timeout=120,
        )
        if proc.returncode != 0:
            return {'success': False, 'error': 'exit %d' % proc.returncode}
        return json.loads(proc.stdout)
    except Exception as exc:
        return {'success': False, 'error': str(exc)}


def _record_adr(step, decision, context, rollback_hint):
    """落 ADR 决策记录（可追溯可回滚）。"""
    adr = {
        'schema_version': '0.5',
        'adr_id': 'adr_%s_%s' % (int(time.time()), step),
        'recorded_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'step': step,
        'decision': decision,
        'context': context,
        'rollback_hint': rollback_hint,
    }
    with open(ADR_PATH, 'a', encoding='utf-8') as f:
        f.write(json.dumps(adr, ensure_ascii=False) + '\n')
    return adr


def _load_adrs():
    adrs = []
    if ADR_PATH.exists():
        for line in ADR_PATH.read_text(encoding='utf-8').splitlines():
            if line.strip():
                try:
                    adrs.append(json.loads(line))
                except Exception:
                    pass
    return adrs


def _load_staging():
    items = []
    if STAGING_PATH.exists():
        for line in STAGING_PATH.read_text(encoding='utf-8').splitlines():
            if line.strip():
                try:
                    items.append(json.loads(line))
                except Exception:
                    pass
    return items


def cmd_run(_args):
    """闭环执行：新案例 → 提案 → 自动评审 → 回归测试 → 合入暂存 → 同步 → 决策记录。"""
    steps = []

    # ---- 步骤 1：提案生成（R-1 提案器 full：发现 + 提案）----
    prop = _run_cli(PROPOSER, {'cmd': 'full'})
    steps.append({'step': 'propose', 'ok': bool(prop.get('success')), 'summary': {
        'clusters': (prop.get('discover') or {}).get('clusters') or prop.get('clusters') or [],
        'proposals': prop.get('proposals') or [],
    }})
    if not prop.get('success'):
        adr = _record_adr('propose', 'abort', {'error': prop.get('error')}, '无需回滚：提案失败前无状态变更')
        return {'success': False, 'steps': steps, 'adr_id': adr['adr_id'], 'error': 'propose failed'}
    adr1 = _record_adr('propose', 'proposals_generated', {
        'proposal_count': len(prop.get('proposals') or []),
    }, '删除 proposals/ 目录新生成文件即可回滚')

    # ---- 步骤 2：自动评审（质量门禁）----
    review = _run_cli(REVIEWER, {})
    steps.append({'step': 'review', 'ok': bool(review.get('success')), 'summary': review.get('summary') or {}})
    if not review.get('success'):
        adr2 = _record_adr('review', 'abort', {'error': review.get('error')}, '评审失败，提案停留 pending 状态')
        return {'success': False, 'steps': steps, 'adr_id': adr2['adr_id'], 'error': 'review failed'}
    adr2 = _record_adr('review', 'auto_reviewed', {
        'summary': review.get('summary'),
    }, '提案 review 字段已标记，可重跑评审脚本覆盖')

    # ---- 步骤 3：回归测试（逆向验证管线 conflict-detect 作为门禁）----
    verify = _run_cli(SYS34 / 'scripts' / 'intent_reverse_verify.py', {'cmd': 'conflict-detect'})
    conflicts = 0
    if verify.get('success'):
        findings = verify.get('findings') or []
        conflicts = len(findings)
    gate_passed = bool(verify.get('success')) and conflicts == 0
    steps.append({'step': 'regression_gate', 'ok': gate_passed, 'summary': {
        'conflict_findings': conflicts,
    }})
    adr3 = _record_adr('regression_gate', 'passed' if gate_passed else 'blocked', {
        'conflict_findings': conflicts,
    }, '门禁未通过时合入暂存不写入，无需回滚')
    if not gate_passed:
        return {'success': True, 'steps': steps, 'gate': 'blocked', 'adr_ids': [adr1['adr_id'], adr2['adr_id'], adr3['adr_id']],
                'note': '回归门禁未通过（存在冲突），闭环停在评审阶段，提案停留 pending'}

    # ---- 步骤 4：合入暂存（人工批准保留）----
    staging_entries = []
    prop_dir = SYS34 / 'proposals'
    for pf in sorted(prop_dir.glob('prop_*.json')):
        try:
            p = json.loads(pf.read_text(encoding='utf-8'))
        except Exception:
            continue
        rv = (p.get('review') or {})
        if rv.get('status') == 'reviewed' and rv.get('verdict') == 'recommend':
            staging_entries.append({
                'staging_id': 'stg_%s' % p.get('proposal_id'),
                'proposal_id': p.get('proposal_id'),
                'intent': p.get('intent'),
                'approval_status': 'pending_human_approval',
                'staged_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
            })
    if staging_entries:
        with open(STAGING_PATH, 'a', encoding='utf-8') as f:
            for e in staging_entries:
                f.write(json.dumps(e, ensure_ascii=False) + '\n')
    steps.append({'step': 'merge_staging', 'ok': True, 'summary': {
        'staged': len(staging_entries),
        'approval': 'pending_human_approval',
    }})
    adr4 = _record_adr('merge_staging', 'staged_pending_approval', {
        'staged_count': len(staging_entries),
    }, '删除 merge_staging.jsonl 对应行即可回滚')

    # ---- 步骤 5：同步（暂存条目状态同步至决策记录，合入待批准）----
    adr5 = _record_adr('sync', 'staged_synced', {
        'staged_count': len(staging_entries),
        'note': '合入需人工批准（approve 命令），批准后写入意图库',
    }, 'ADR 记录追加式，可按 adr_id 追溯')

    return {
        'success': True,
        'steps': steps,
        'adr_ids': [adr1['adr_id'], adr2['adr_id'], adr3['adr_id'], adr4['adr_id'], adr5['adr_id']],
        'staged_entries': len(staging_entries),
        'approval_status': 'pending_human_approval',
        'note': '闭环演示完成：新案例→提案→测试→合入暂存→同步全自动；合入保留人工批准',
    }


def cmd_status(_args):
    adrs = _load_adrs()
    staging = _load_staging()
    return {
        'success': True,
        'adr_records': len(adrs),
        'last_adr': adrs[-1] if adrs else None,
        'staging_entries': len(staging),
        'pending_approval': sum(1 for s in staging if s.get('approval_status') == 'pending_human_approval'),
    }


def cmd_approve(args):
    """人工批准合入：staging 条目 → approved（写入决策记录）。"""
    staging_id = str(args.get('staging_id') or args.get('entry_id') or '')
    staging = _load_staging()
    target = next((s for s in staging if s.get('staging_id') == staging_id), None)
    if target is None:
        return {'success': False, 'error': 'staging entry not found: %s' % staging_id}
    target['approval_status'] = 'approved'
    target['approved_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    # 重写暂存文件
    with open(STAGING_PATH, 'w', encoding='utf-8') as f:
        for s in staging:
            f.write(json.dumps(s, ensure_ascii=False) + '\n')
    adr = _record_adr('approve', 'human_approved', {
        'staging_id': staging_id,
        'proposal_id': target.get('proposal_id'),
    }, '重跑 approve 前状态可从 ADR 记录恢复')
    return {'success': True, 'staging_id': staging_id, 'adr_id': adr['adr_id'], 'status': 'approved'}


def cmd_rollback(args):
    """回滚：按 adr_id 追溯决策记录，输出回滚指引。"""
    adr_id = str(args.get('adr_id') or '')
    adrs = _load_adrs()
    target = next((a for a in adrs if a.get('adr_id') == adr_id), None)
    if target is None:
        return {'success': False, 'error': 'adr not found: %s' % adr_id}
    return {
        'success': True,
        'adr': target,
        'rollback_hint': target.get('rollback_hint'),
        'note': '按 rollback_hint 执行回滚操作',
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
        elif cmd == 'status':
            result = cmd_status(req)
        elif cmd == 'approve':
            result = cmd_approve(req)
        elif cmd == 'rollback':
            result = cmd_rollback(req)
        else:
            result = {'success': False, 'error': 'unknown cmd: %s' % cmd}
    except Exception as exc:  # FAIL-OPEN
        result = {'success': False, 'error': str(exc)}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get('success') else 1


if __name__ == '__main__':
    sys.exit(main())
