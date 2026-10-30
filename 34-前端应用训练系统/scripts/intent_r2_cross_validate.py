#!/usr/bin/env python3
"""R-2 三层架构逆向交叉验证（spec v0.5 §3.2/§9.2，P4）。

双输入交叉验证：
  ① 回放池发现树（执行轨迹，dt_*.json）→ 提取跨层执行路径
  ② 41 文件索引系统（能力地图）→ list_files/search 预过滤 + capability_refs 校验
产出：复杂意图库 complex_intent_library.jsonl（一般复杂意图链路模板，直接驱动完整链路）。

用法（stdin JSON → stdout JSON，FAIL-OPEN）：
  echo '{"cmd":"run"}' | python3 intent_r2_cross_validate.py
  echo '{"cmd":"stats"}' | python3 intent_r2_cross_validate.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path('/home/luke/dreambuddy')
REPLAY_POOL = REPO_ROOT / '33-REA逆向解析工程' / 'reflection_data' / 'replay_pool'
LIB_PATH = REPO_ROOT / '34-前端应用训练系统' / 'complex_intent_library.jsonl'
FIS_PY = '/home/ubuntu/fis-p0/.venv/bin/python'
FIS_CLI = '/home/ubuntu/fis-p0/scripts/search_cli.py'

# 关键词级缓存：相同关键词只检索一次（发现树 target/feature 重复率高）
_SEARCH_CACHE = {}


def fis_query(payload, timeout=30):
    """41 检索 CLI 查询（FAIL-OPEN：失败返回 None）。"""
    env = dict(os.environ)
    try:
        proc = subprocess.run(
            [FIS_PY, FIS_CLI],
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True, text=True, timeout=timeout, env=env,
        )
        if proc.returncode != 0:
            return None
        return json.loads(proc.stdout)
    except Exception:
        return None


def fis_search_cached(query, limit=3):
    """带缓存的 41 search（同关键词只发起一次子进程）。"""
    key = (query, limit)
    if key not in _SEARCH_CACHE:
        _SEARCH_CACHE[key] = fis_query({'cmd': 'search', 'query': query, 'limit': limit})
    return _SEARCH_CACHE[key]


def flatten_tree(tree):
    """发现树 → 扁平节点列表（含深度）。"""
    nodes = []

    def walk(node, depth):
        nodes.append((depth, node))
        for child in node.get('children_record') or []:
            walk(child, depth + 1)

    for root in tree.get('nodes') or []:
        walk(root, 0)
    return nodes


def extract_paths(tree):
    """发现树 → 跨层执行路径（analyzer 链 + 证据 + poe 均值）。"""
    nodes = flatten_tree(tree)
    if not nodes:
        return None
    chain = []
    chain_params = []
    evidence = []
    poe_scores = []
    for depth, node in nodes:
        action = node.get('action') or {}
        analyzer = action.get('analyzer') or 'unknown'
        chain.append(analyzer)
        chain_params.append(dict(action.get('params') or {}))
        poe_scores.append(float(node.get('poe_score') or 0.0))
        for ref in node.get('evidence_refs') or []:
            src = ref.get('source') or ''
            if src:
                evidence.append(src)
    if len(chain) < 2:
        return None
    return {
        'tree_id': tree.get('tree_id'),
        'target': (tree.get('task') or {}).get('target'),
        'task_type': (tree.get('task') or {}).get('task_type'),
        'feature': (tree.get('task') or {}).get('feature'),
        'chain': chain,
        'chain_params': chain_params,
        'chain_depth': max(d for d, _ in nodes) + 1,
        'evidence_sources': sorted(set(evidence)),
        'avg_poe': round(sum(poe_scores) / len(poe_scores), 3) if poe_scores else 0.0,
    }


def capability_refs_for(path_info, cap_map_ok):
    """路径 → capability_refs（41 命中 source，能力锚点可追溯，缓存检索）。"""
    refs = []
    keywords = [path_info.get('target') or '', path_info.get('feature') or '']
    for kw in [k for k in keywords if k]:
        hit = fis_search_cached(kw, 3)
        if hit and hit.get('success'):
            for h in (hit.get('hits') or [])[:3]:
                src = (h.get('source') or {}).get('path')
                if src:
                    refs.append({'query': kw, 'source': src, 'score': h.get('score')})
    # 41 不可用时 FAIL-OPEN：仅以发现树 target 作为弱引用
    if not refs and not cap_map_ok:
        refs = [{'query': path_info.get('target') or '', 'source': 'replay_pool:' + str(path_info.get('tree_id')), 'score': 0.0, 'degraded': True}]
    return refs[:6]


def cmd_run(args):
    pool_dir = Path(args.get('pool_dir') or REPLAY_POOL)
    limit = int(args.get('limit') or 0)
    # ① 41 能力地图（list_files 预过滤，FAIL-OPEN）
    cap_map = fis_query({'cmd': 'list_files', 'limit': 500})
    cap_map_ok = bool(cap_map and cap_map.get('success'))
    cap_count = cap_map.get('total') or len(cap_map.get('files') or []) if cap_map_ok else None
    # ② 发现树解析
    trees = sorted(pool_dir.glob('internal/dt_*.json'))
    if limit > 0:
        trees = trees[:limit]
    paths = []
    for tf in trees:
        try:
            tree = json.loads(tf.read_text(encoding='utf-8'))
            info = extract_paths(tree)
            if info:
                paths.append(info)
        except Exception:
            continue
    # ③ 交叉验证 + 复杂意图库产出（检索走缓存）
    entries = []
    for idx, info in enumerate(paths):
        refs = capability_refs_for(info, cap_map_ok)
        entry = {
            'schema_version': '0.5',
            'entry_id': 'cil_%s_%03d' % (info['tree_id'].replace('dt_', '')[:8], idx),
            'source': 'r2_cross_validate',
            'trigger': {
                'target': info['target'],
                'task_type': info['task_type'],
                'feature': info['feature'],
            },
            'chain_template': info['chain'],
            'chain_params': info['chain_params'],
            'chain_depth': info['chain_depth'],
            'avg_poe': info['avg_poe'],
            'evidence_sources': info['evidence_sources'],
            'capability_refs': refs,
            'capability_map_available': cap_map_ok,
            'status': 'active' if info['avg_poe'] >= 0.5 else 'candidate',
        }
        entries.append(entry)
    LIB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LIB_PATH, 'w', encoding='utf-8') as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + '\n')
    active = sum(1 for e in entries if e['status'] == 'active')
    return {
        'success': True,
        'trees_scanned': len(trees),
        'paths_extracted': len(paths),
        'library_entries': len(entries),
        'active_entries': active,
        'candidate_entries': len(entries) - active,
        'capability_map': {'available': cap_map_ok, 'files': cap_count},
        'distinct_search_keywords': len(_SEARCH_CACHE),
        'library_path': str(LIB_PATH),
    }


def cmd_stats(_args):
    if not LIB_PATH.exists():
        return {'success': True, 'library_entries': 0, 'note': 'library not built yet'}
    entries = []
    for line in LIB_PATH.read_text(encoding='utf-8').splitlines():
        if line.strip():
            try:
                entries.append(json.loads(line))
            except Exception:
                pass
    return {
        'success': True,
        'library_entries': len(entries),
        'active_entries': sum(1 for e in entries if e.get('status') == 'active'),
        'avg_chain_depth': round(sum(e.get('chain_depth', 0) for e in entries) / len(entries), 2) if entries else 0,
        'capability_anchored': sum(1 for e in entries if e.get('capability_refs')),
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
