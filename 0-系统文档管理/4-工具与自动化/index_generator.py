#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
index_generator.py — 自动生成目录树索引

用途：
    递归生成指定目录的目录树（markdown 代码块格式），用于辅助维护 INDEX.md
    的目录结构段。支持深度限制、仅目录、忽略常见噪音目录。

用法：
    python index_generator.py [目标目录] [--max-depth N] [--dirs-only] [--output FILE]

示例：
    python index_generator.py 0-系统文档管理 --max-depth 2
    python index_generator.py 14-V15经典马丁策略 --dirs-only -o tree.txt

退出码：
    0 = 成功
    2 = 目录不存在
"""
import argparse
import sys
from pathlib import Path

# 忽略的目录/文件名
IGNORED = {'.git', 'node_modules', '__pycache__', '.venv', 'dist', 'build',
           '.pytest_cache', '.cognitive', '.run', '.trae', '.claude',
           '.DS_Store', 'site-packages', '.workbuddy', '.mypy_cache', '.cache'}


def build_tree(root, prefix='', level=1, max_depth=None, dirs_only=False, lines=None):
    """递归构建目录树行列表。level 从 1 开始（root 的直接子项为第 1 层）。"""
    if lines is None:
        lines = []
    if max_depth is not None and level > max_depth:
        return lines
    try:
        entries = sorted(root.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError:
        return lines
    entries = [e for e in entries if e.name not in IGNORED]
    if dirs_only:
        entries = [e for e in entries if e.is_dir()]
    entries = [e for e in entries if not (e.is_file() and e.suffix == '.pyc')]

    for i, entry in enumerate(entries):
        last = (i == len(entries) - 1)
        connector = '└── ' if last else '├── '
        if entry.is_dir():
            lines.append('{}{}{}/'.format(prefix, connector, entry.name))
            extension = '    ' if last else '│   '
            build_tree(entry, prefix + extension, level + 1, max_depth, dirs_only, lines)
        else:
            lines.append('{}{}{}'.format(prefix, connector, entry.name))
    return lines


def generate(target, max_depth=None, dirs_only=False):
    lines = build_tree(target, max_depth=max_depth, dirs_only=dirs_only)
    body = '\n'.join([target.name + '/'] + lines)
    return '```\n{}\n```'.format(body)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='自动生成目录树索引（markdown 代码块格式）')
    parser.add_argument('target', nargs='?', default='.',
                        help='目标目录（默认当前目录）')
    parser.add_argument('--max-depth', type=int, default=None,
                        help='最大递归深度（1=仅直接子项）')
    parser.add_argument('--dirs-only', action='store_true',
                        help='只显示目录，不显示文件')
    parser.add_argument('--include-files', action='store_true', default=True,
                        help='包含文件（默认开启，与 --dirs-only 互斥时以 --dirs-only 为准）')
    parser.add_argument('--output', '-o', default=None,
                        help='输出到文件（默认输出到 stdout）')
    args = parser.parse_args(argv)

    root = Path(args.target).resolve()
    if not root.exists() or not root.is_dir():
        print('错误：目录不存在：{}'.format(args.target), file=sys.stderr)
        return 2

    output = generate(root, max_depth=args.max_depth, dirs_only=args.dirs_only)
    if args.output:
        try:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(output + '\n')
            print('目录树已写入：{}'.format(args.output))
        except OSError as e:
            print('错误：写入文件失败：{}'.format(e), file=sys.stderr)
            return 2
    else:
        print(output)
    return 0


if __name__ == '__main__':
    sys.exit(main())
