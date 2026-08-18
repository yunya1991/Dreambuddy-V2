#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
doc_coverage.py — DreamBuddy-V2 文档覆盖率统计与报告

用途：
    扫描项目根下所有 NN-*/ 子系统目录及 L3 辅助模块，检查 5 文档标准
    （README / ENGINEERING_INDEX / TECHNICAL_DESIGN / API_SPEC / CHANGELOG）
    的覆盖情况，输出覆盖率表格，对齐 INDEX.md 末尾的统计格式。

5 文档标准：
    - README.md                 （子系统根目录）
    - docs/ENGINEERING_INDEX.md
    - docs/TECHNICAL_DESIGN.md
    - docs/API_SPEC.md
    - docs/CHANGELOG.md

用法：
    python doc_coverage.py [--root 项目根路径] [--json 输出JSON文件]

示例：
    python doc_coverage.py
    python doc_coverage.py --root /path/to/dreambuddy-v2 --json coverage.json

退出码：
    0 = 统计完成
    2 = 项目根不存在或未识别
"""
import argparse
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DOC_MGMT_DIR = SCRIPT_DIR.parent
DEFAULT_ROOT = DOC_MGMT_DIR.parent

NN_DIR_RE = re.compile(r'^\d+-')

# L3 辅助模块（相对项目根的路径，与 INDEX.md / DOC_CLASSIFICATION.md 对齐）
L3_MODULES = [
    '3-EVOLUTION',
    '6-图结构上下文压缩',
    '7-产物中台',
    '15-监控告警系统',
    'experiments',
    '1-ARCHITECTURE/dreamos',
]

# 5 文档标准：(文件名, 所在子目录)  空串表示子系统根目录
REQUIRED_DOCS = [
    ('README.md', ''),
    ('ENGINEERING_INDEX.md', 'docs'),
    ('TECHNICAL_DESIGN.md', 'docs'),
    ('API_SPEC.md', 'docs'),
    ('CHANGELOG.md', 'docs'),
]


def find_project_root(start):
    """向上查找包含 0-系统文档管理 的目录作为项目根。"""
    p = Path(start).resolve()
    for cand in [p] + list(p.parents):
        if (cand / '0-系统文档管理').is_dir():
            return cand
    return None


def check_module(module_root):
    """检查单个模块的 5 文档覆盖情况，返回 (present, missing)。"""
    present = []
    missing = []
    for fname, subdir in REQUIRED_DOCS:
        path = module_root / subdir / fname if subdir else module_root / fname
        if path.exists():
            present.append(fname)
        else:
            missing.append(fname)
    return present, missing


def leading_number(name):
    """提取目录名前导数字，用于区分层级（项目约定：L2 子系统编号 >= 10）。"""
    m = re.match(r'^(\d+)', name)
    return int(m.group(1)) if m else -1


def collect_modules(root):
    """收集所有 L2 / L3 模块，返回 [(name, layer, path), ...]。

    层级判定依据 DOC_CLASSIFICATION.md：
      - L2 子系统：NN-* 编号 >= 10 且拥有 docs/ 目录（10-17 为正式交易子系统）
      - L3 辅助模块：显式列表（3-EVOLUTION / 6-图结构 / 7-产物中台 / 15-监控 / experiments / dreamos）
      - 编号 1-9 的 NN-* 目录属 L1 顶层架构或其他模块，不计入 L2/L3 覆盖率
    """
    modules = []
    l3_names = set(L3_MODULES)

    # L2：NN-* 子系统（编号 >= 10），拥有 docs/ 目录，且不在 L3 显式列表中
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        if not NN_DIR_RE.match(d.name):
            continue
        rel = d.relative_to(root).as_posix()
        if rel in l3_names:
            continue  # 交由 L3 段处理
        if leading_number(d.name) < 10:
            continue  # 1-9 为 L1 顶层架构 / 其他，不计入 L2
        if (d / 'docs').is_dir():
            modules.append((d.name, 'L2', d))

    # L3：显式列表（按定义顺序）
    for name in L3_MODULES:
        p = root / name
        if p.exists() and p.is_dir():
            modules.append((name, 'L3', p))
    return modules


def pct(numer, denom):
    if denom == 0:
        return '0%'
    return '{}%'.format(round(numer * 100 / denom))


def render(modules_data, root):
    """渲染覆盖率报告。"""
    lines = []
    lines.append('DreamBuddy-V2 文档覆盖率报告')
    lines.append('=' * 64)
    lines.append('')
    lines.append('项目根：{}'.format(root))
    lines.append('')

    # —— 模块明细表 ——
    lines.append('## 模块明细')
    lines.append('')
    lines.append('| 模块 | 层级 | 5文档齐全数 | 缺失文档列表 | 覆盖率 |')
    lines.append('|------|------|------------|-------------|--------|')
    for name, layer, present, missing in modules_data:
        cov = '{}/{}'.format(len(present), len(REQUIRED_DOCS))
        miss = '、'.join(missing) if missing else '—'
        lines.append('| {} | {} | {} | {} | {} |'.format(
            name, layer, cov, miss, pct(len(present), len(REQUIRED_DOCS))))
    lines.append('')

    # —— 汇总表（对齐 INDEX.md 末尾格式）——
    lines.append('## 覆盖率汇总')
    lines.append('')
    lines.append('| 层级 | 模块数 | 文档齐全 | 部分完整 | 缺失 | 覆盖率 |')
    lines.append('|------|--------|---------|---------|------|--------|')

    def tier_stats(layer):
        items = [m for m in modules_data if m[1] == layer]
        total_docs = len(REQUIRED_DOCS)
        complete = sum(1 for m in items if len(m[2]) == total_docs)
        missing_all = sum(1 for m in items if len(m[2]) == 0)
        partial = len(items) - complete - missing_all
        docs_present = sum(len(m[2]) for m in items)
        cov = pct(docs_present, total_docs * len(items)) if items else '0%'
        return len(items), complete, partial, missing_all, cov

    l2_count, l2_full, l2_part, l2_miss, l2_cov = tier_stats('L2')
    l3_count, l3_full, l3_part, l3_miss, l3_cov = tier_stats('L3')
    lines.append('| L2 子系统 | {} | {} | {} | {} | {} |'.format(
        l2_count, l2_full, l2_part, l2_miss, l2_cov))
    lines.append('| L3 辅助模块 | {} | {} | {} | {} | {} |'.format(
        l3_count, l3_full, l3_part, l3_miss, l3_cov))

    total_count = l2_count + l3_count
    total_full = l2_full + l3_full
    total_part = l2_part + l3_part
    total_miss = l2_miss + l3_miss
    total_docs_present = sum(len(m[2]) for m in modules_data)
    total_docs_expected = len(REQUIRED_DOCS) * total_count if total_count else 1
    total_cov = pct(total_docs_present, total_docs_expected)
    lines.append('| **合计** | **{}** | **{}** | **{}** | **{}** | **{}** |'.format(
        total_count, total_full, total_part, total_miss, total_cov))
    lines.append('')
    lines.append('> 覆盖率 = 现存文档数 / 应建文档数 × 100%')
    return '\n'.join(lines)


def build_json(modules_data, root):
    modules = []
    for name, layer, present, missing in modules_data:
        modules.append({
            'name': name,
            'layer': layer,
            'present': present,
            'missing': missing,
            'coverage': '{}/{}'.format(len(present), len(REQUIRED_DOCS)),
        })
    return {
        'project_root': str(root),
        'required_docs': [f for f, _ in REQUIRED_DOCS],
        'modules': modules,
        'summary': {
            'total_modules': len(modules_data),
            'total_docs_present': sum(len(m[2]) for m in modules_data),
            'total_docs_expected': len(REQUIRED_DOCS) * len(modules_data),
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='DreamBuddy-V2 文档覆盖率统计与报告')
    parser.add_argument('--root', help='项目根路径（默认自动识别）')
    parser.add_argument('--json', dest='json_out', help='输出 JSON 到指定文件')
    args = parser.parse_args(argv)

    if args.root:
        root = Path(args.root).resolve()
        if not root.exists():
            print('错误：项目根不存在：{}'.format(args.root), file=sys.stderr)
            return 2
    else:
        root = find_project_root(DEFAULT_ROOT)
        if root is None:
            print('错误：未识别到项目根（未找到 0-系统文档管理 目录）', file=sys.stderr)
            return 2

    modules = collect_modules(root)
    if not modules:
        print('警告：未扫描到任何模块', file=sys.stderr)

    data = []
    for name, layer, path in modules:
        present, missing = check_module(path)
        data.append((name, layer, present, missing))

    if args.json_out:
        payload = build_json(data, root)
        try:
            with open(args.json_out, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            print('JSON 已写入：{}'.format(args.json_out))
        except OSError as e:
            print('错误：写入 JSON 失败：{}'.format(e), file=sys.stderr)
            return 2

    print(render(data, root))
    return 0


if __name__ == '__main__':
    sys.exit(main())
