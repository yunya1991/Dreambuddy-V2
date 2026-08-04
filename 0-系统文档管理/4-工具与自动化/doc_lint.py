#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
doc_lint.py — DreamBuddy-V2 文档命名/格式/规范检查工具

用途：
    扫描指定目录下的 Markdown 文件，依据 DOC_STANDARD.md 与 DOC_CLASSIFICATION.md
    检查文档命名、版本头、目录规范，输出违规项列表。

检查项：
    1. docs/ 目录下 .md 文件名是否符合「大写+下划线」规范（不符合报 warning）
    2. 禁止命名检测（技术文档*.md / 新技术文档.md / 最终版文档.md / doc1.md /
       temp.md / 含主观形容词的命名）
    3. L0/L2 文档头部是否包含 **版本** 与 **更新日期** 版本头
    4. 同一目录下 README.md 与 INDEX.md 并存检测（L2 用 README，L1 用 INDEX）

用法：
    python doc_lint.py [目标目录...] [--quiet]

示例：
    python doc_lint.py 0-系统文档管理
    python doc_lint.py 10-经典指标系统 16-调控系统 --quiet

退出码：
    0 = 全部通过
    1 = 存在违规
    2 = 目录不存在或参数错误
"""
import argparse
import os
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DOC_MGMT_DIR = SCRIPT_DIR.parent              # 0-系统文档管理
PROJECT_ROOT = DOC_MGMT_DIR.parent            # dreambuddy-v2

# 版本头检查时跳过的子目录（工具目录、模板目录）
VERSION_HEADER_SKIP_DIRS = {'4-工具与自动化', 'TEMPLATES'}

# 扫描时忽略的目录
IGNORED_DIRS = {'.git', 'node_modules', '__pycache__', '.venv', 'dist', 'build',
                '.pytest_cache', '.cognitive', '.run', '.trae', '.claude',
                'site-packages', '.workbuddy'}

# 禁止命名（精确匹配，大小写不敏感）
FORBIDDEN_EXACT = {'新技术文档.md', '最终版文档.md', 'doc1.md', 'temp.md'}
# 禁止命名（正则匹配）
FORBIDDEN_REGEX = [re.compile(r'^技术文档.*\.md$', re.IGNORECASE)]
# 主观形容词 token（出现在文件名中即报 warning）
SUBJECTIVE_TOKENS = [
    '最终', '最新', '临时', '草稿', '正式版', '完整版', '精简版',
    '修改版', '修正版', '备份', '最终版',
]

UPPER_UNDERSCORE_RE = re.compile(r'^[A-Z][A-Z0-9_]*$')
NN_DIR_RE = re.compile(r'^\d+-')
VERSION_KEYS = ['**版本**', '**更新日期**']


class Violation:
    """一条违规记录。"""

    def __init__(self, path, vtype, message):
        self.path = path
        self.vtype = vtype
        self.message = message

    def format(self, root):
        try:
            rel = str(Path(self.path).relative_to(root))
        except ValueError:
            rel = str(self.path)
        return "[WARN] {vtype:<22} {rel} — {msg}".format(vtype=self.vtype, rel=rel, msg=self.message)


def walk_dir(target):
    """os.walk 封装，原地修剪忽略目录。"""
    for dirpath, dirnames, filenames in os.walk(target):
        dirnames[:] = sorted(d for d in dirnames if d not in IGNORED_DIRS)
        yield dirpath, dirnames, filenames


def default_targets():
    """默认扫描范围：0-系统文档管理 + 各 NN-子系统目录。"""
    targets = [DOC_MGMT_DIR]
    for d in sorted(PROJECT_ROOT.iterdir()):
        if d.is_dir() and NN_DIR_RE.match(d.name):
            targets.append(d)
    return targets


def is_version_check_target(md_path):
    """判断 .md 文件是否属于 L0/L2 文档（需检查版本头）。"""
    # L0：0-系统文档管理 下（路径任意层级命中跳过目录即跳过：工具目录、模板目录）
    try:
        rel = md_path.relative_to(DOC_MGMT_DIR)
        parts = rel.parts
        if any(p in VERSION_HEADER_SKIP_DIRS for p in parts):
            return False
        return True
    except ValueError:
        pass
    # L2：PROJECT_ROOT/NN-*/docs/ 下
    try:
        rel = md_path.relative_to(PROJECT_ROOT)
    except ValueError:
        return False
    parts = rel.parts
    if len(parts) >= 2 and NN_DIR_RE.match(parts[0]) and parts[1] == 'docs':
        return True
    return False


def check_naming(md_path, violations):
    """检查文件名规范：禁止命名 + docs/ 下大写+下划线。"""
    name = md_path.name
    stem = md_path.stem

    # 禁止命名（精确）
    if name.lower() in {n.lower() for n in FORBIDDEN_EXACT}:
        violations.append(Violation(md_path, 'NAMING_FORBIDDEN', '禁止命名：{}'.format(name)))
        return
    for rx in FORBIDDEN_REGEX:
        if rx.match(name):
            violations.append(Violation(md_path, 'NAMING_FORBIDDEN', '禁止命名：{}'.format(name)))
            return
    # 主观形容词
    for token in SUBJECTIVE_TOKENS:
        if token in name:
            violations.append(Violation(md_path, 'NAMING_FORBIDDEN',
                                        '含主观形容词「{}」：{}'.format(token, name)))
            return

    # docs/ 下文件必须大写+下划线
    if md_path.parent.name == 'docs' and not UPPER_UNDERSCORE_RE.match(stem):
        violations.append(Violation(md_path, 'NAMING_CASE',
                                    'docs/ 下文件应使用大写+下划线命名：{}'.format(name)))


def check_version_header(md_path, violations):
    """检查 L0/L2 文档头部是否包含版本头。"""
    if not is_version_check_target(md_path):
        return
    try:
        with open(md_path, 'r', encoding='utf-8') as f:
            head = ''.join(f.readline() for _ in range(30))
    except OSError:
        return
    missing = [k for k in VERSION_KEYS if k not in head]
    if missing:
        violations.append(Violation(md_path, 'VERSION_HEADER_MISSING',
                                    '缺少版本头：{}'.format('、'.join(missing))))


def scan(target, violations):
    """扫描单个目标目录。"""
    for dirpath, dirnames, filenames in walk_dir(target):
        # README.md 与 INDEX.md 并存检测
        if 'README.md' in filenames and 'INDEX.md' in filenames:
            conflict_path = Path(dirpath) / 'README.md'
            violations.append(Violation(conflict_path, 'README_INDEX_CONFLICT',
                                        '同目录并存 README.md 与 INDEX.md（L2 用 README，L1 用 INDEX）'))
        for fn in filenames:
            if fn.endswith('.md'):
                md = Path(dirpath) / fn
                check_naming(md, violations)
                check_version_header(md, violations)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='DreamBuddy-V2 文档命名/格式/规范检查工具')
    parser.add_argument('targets', nargs='*',
                        help='目标目录（默认：0-系统文档管理 + 各 NN-子系统）')
    parser.add_argument('--quiet', '-q', action='store_true',
                        help='只输出违规数')
    args = parser.parse_args(argv)

    targets = args.targets if args.targets else default_targets()
    resolved = []
    for t in targets:
        p = Path(t).resolve()
        if not p.exists():
            print('错误：目录不存在：{}'.format(t), file=sys.stderr)
            return 2
        resolved.append(p)

    violations = []
    for t in resolved:
        scan(t, violations)
    violations.sort(key=lambda v: (str(v.path), v.vtype))

    if args.quiet:
        print(len(violations))
    else:
        if not violations:
            print('✅ 文档规范检查通过，未发现违规项。')
        else:
            print('共发现 {} 项违规：\n'.format(len(violations)))
            for v in violations:
                print(v.format(PROJECT_ROOT))
            print('\n违规统计：{} 项'.format(len(violations)))
    return 1 if violations else 0


if __name__ == '__main__':
    sys.exit(main())
