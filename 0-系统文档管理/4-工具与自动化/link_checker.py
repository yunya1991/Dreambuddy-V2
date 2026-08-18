#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
link_checker.py — 跨文档 Markdown 链接校验

用途：
    扫描指定目录下所有 .md 文件的 markdown 链接 [text](path)，校验相对路径
    目标是否存在。跳过外部 URL（http/https/mailto/ftp）与纯锚点（#xxx）。
    链接中的锚点（path#section）只校验 path 是否存在，不强制校验锚点。

用法：
    python link_checker.py [目标目录] [--root 项目根] [--summary]

示例：
    python link_checker.py 0-系统文档管理
    python link_checker.py 14-V15经典马丁策略 --summary

退出码：
    0 = 无断链
    1 = 存在断链
    2 = 目录不存在
"""
import argparse
import os
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DOC_MGMT_DIR = SCRIPT_DIR.parent
DEFAULT_ROOT = DOC_MGMT_DIR.parent

IGNORED_DIRS = {'.git', 'node_modules', '__pycache__', '.venv', 'dist', 'build',
                '.pytest_cache', '.cognitive', '.run', '.trae', '.claude',
                'site-packages', '.workbuddy', 'TEMPLATES'}

# 匹配 [text](target)，target 内不含换行与右括号
LINK_RE = re.compile(r'\[([^\]]*)\]\(([^)]+)\)')
EXTERNAL_RE = re.compile(r'^(https?:|mailto:|ftp:|tel:)', re.IGNORECASE)
# 链接 target 末尾的可选 title：[text](path "title")
TITLE_RE = re.compile(r'\s+"[^"]*"$')
# 内联代码 span：`...`（在链接提取前剥离，避免把代码示例里的 [text](path) 误判为链接）
INLINE_CODE_RE = re.compile(r'`[^`]*`')


def find_project_root(start):
    """向上查找包含 0-系统文档管理 的目录作为项目根。"""
    p = Path(start).resolve()
    for cand in [p] + list(p.parents):
        if (cand / '0-系统文档管理').is_dir():
            return cand
    return None


def iter_md_files(target):
    """遍历目标目录下所有 .md 文件（忽略噪音目录）。"""
    for dirpath, dirnames, filenames in os.walk(target):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]
        for fn in filenames:
            if fn.endswith('.md'):
                yield Path(dirpath) / fn


def extract_links(md_path):
    """提取一个 .md 文件中的 markdown 链接，跳过代码块。"""
    try:
        with open(md_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except OSError:
        return
    in_fence = False
    for i, line in enumerate(lines, 1):
        stripped = line.lstrip()
        if stripped.startswith('```'):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        # 剥离内联代码 span，避免代码示例里的 [text](path) 被误判为链接
        line_clean = INLINE_CODE_RE.sub('', line)
        for m in LINK_RE.finditer(line_clean):
            text = m.group(1)
            target = m.group(2).strip()
            # 去掉结尾 title
            target = TITLE_RE.sub('', target)
            # 去掉尖括号包裹 <path>
            if target.startswith('<') and target.endswith('>'):
                target = target[1:-1]
            yield i, text, target


def is_external(target):
    return bool(EXTERNAL_RE.match(target))


def resolve_target(md_path, target):
    """返回相对链接解析后的绝对 Path；外部链接/纯锚点返回 None（跳过）。"""
    if not target:
        return None
    if is_external(target):
        return None
    if target.startswith('#'):
        return None  # 纯锚点
    # 剥离锚点与查询串
    path_part = target.split('#', 1)[0].split('?', 1)[0].strip()
    if not path_part:
        return None
    base = md_path.parent
    return (base / path_part).resolve()


def check(target, root):
    """扫描 target，返回 (broken_list, total_relative_links)。"""
    broken = []
    total = 0
    for md in iter_md_files(target):
        for lineno, text, tgt in extract_links(md):
            resolved = resolve_target(md, tgt)
            if resolved is None:
                continue
            total += 1
            if not resolved.exists():
                broken.append((md, lineno, text, tgt))
    return broken, total


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='跨文档 Markdown 链接校验工具')
    parser.add_argument('target', nargs='?',
                        help='目标目录（默认 0-系统文档管理）')
    parser.add_argument('--root', help='项目根路径（用于显示相对路径，默认自动识别）')
    parser.add_argument('--summary', action='store_true',
                        help='只输出统计信息')
    args = parser.parse_args(argv)

    if args.root:
        root = Path(args.root).resolve()
        if not root.exists():
            print('错误：项目根不存在：{}'.format(args.root), file=sys.stderr)
            return 2
    else:
        root = find_project_root(DEFAULT_ROOT)
        if root is None:
            root = Path.cwd()

    if args.target:
        target = Path(args.target).resolve()
    else:
        target = root / '0-系统文档管理'
    if not target.exists() or not target.is_dir():
        print('错误：目录不存在：{}'.format(args.target or target), file=sys.stderr)
        return 2

    broken, total = check(target, root)

    if args.summary:
        print('扫描链接数：{}'.format(total))
        print('断链数：{}'.format(len(broken)))
    else:
        if not broken:
            print('✅ 链接校验通过，共 {} 个相对链接，无断链。'.format(total))
        else:
            print('共发现 {} 个断链：\n'.format(len(broken)))
            for src, lineno, text, tgt in broken:
                try:
                    rel = src.relative_to(root)
                except ValueError:
                    rel = src
                print('{}:{}  [{}]  →  {}'.format(rel, lineno, text, tgt))
            print('\n断链统计：{} / {}'.format(len(broken), total))
    return 1 if broken else 0


if __name__ == '__main__':
    sys.exit(main())
