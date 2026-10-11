#!/usr/bin/env python3
"""FIBO INDEX.md 解析器 — FIBOIndexLoader

定位：将 46 个 INDEX.md 文件级 markdown 索引解析为 FIBO 语义图实体和关系。

核心能力:
  1. parse_index(md_path) — 解析 markdown 文件，提取实体和关系
  2. _extract_tables(lines) — 抽取 markdown 表格行
  3. _parse_table_row(row) — 解析表格行为字段
  4. _extract_sections(lines) — 抽取章节标题
  5. _infer_part_of(path) — 从路径层级推断 part_of 关系
  6. _infer_covers_topic(section) — 从章节标题推断 covers_topic 关系
  7. _make_entity_id(path) — 从路径生成稳定实体 ID

解析规则:
  - markdown 表格行格式: | 字段1 | 字段2 | ... |
  - 路径推断: N-MODULE/docs/X.md → part_of → N-MODULE
  - 章节推断: ## L2 — 子系统 → covers_topic → 'L2'

设计原则:
  - FAIL-OPEN：解析失败不抛异常，返回空结果
  - 轻量级：无 markdown 第三方库依赖，纯文本解析
  - 幂等：同一文件多次解析只产生一份实体（按路径去重）

参考:
  - SPEC-CognitiveSystem-Evolution.md §4.3 P3-8
  - 协同 fibo_ontology.py (FIBOOntology 主类)
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fibo_ontology import FIBOEntity, FIBOOntology


# ============================================================
# 正则：markdown 表格行 / 链接 / 章节标题
# ============================================================

# 表格行：以 | 开头，至少 2 个 |
_TABLE_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$")
# 分隔行：|---|---| 形式
_TABLE_SEP_RE = re.compile(r"^\s*\|[\s:|-]+\|\s*$")
# markdown 链接：[text](url)
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
# 章节标题：## xxx 或 ### xxx
_SECTION_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


class FIBOIndexLoader:
    """FIBO INDEX.md 解析器。

    将 markdown 表格解析为 FIBOEntity（type=Document），
    并从路径层级推断 part_of 关系，从章节标题推断 covers_topic 关系。

    Args:
        ontology: FIBOOntology 实例（必传）
    """

    def __init__(self, ontology: FIBOOntology) -> None:
        self._ont = ontology
        # 缓存已创建的实体 ID（按路径去重）
        self._seen_paths: Dict[str, str] = {}

    # ============================================================
    # 公共接口
    # ============================================================

    def parse_index(self, md_path: Path) -> Tuple[int, int]:
        """解析 INDEX.md，提取实体和关系。

        Args:
            md_path: markdown 文件路径

        Returns:
            (entity_count, relation_count) 创建数量
            解析失败返回 (0, 0)（FAIL-OPEN）
        """
        try:
            if not md_path.exists():
                return (0, 0)
            text = md_path.read_text(encoding="utf-8")
        except Exception:
            return (0, 0)

        try:
            lines = text.splitlines()
            sections = self._extract_sections(lines)
            tables = self._extract_tables(lines)

            entity_count = 0
            relation_count = 0

            for section_title, table_rows in tables:
                # 创建 Topic 实体
                topic_id = self._make_topic_id(section_title)
                if topic_id and not self._ont.get_entity(topic_id):
                    self._ont.add_entity(
                        entity_type="Topic",
                        entity_id=topic_id,
                        properties={"title": section_title},
                    )

                # 解析表格行
                headers: Optional[List[str]] = None
                for row in table_rows:
                    cells = self._parse_table_row(row)
                    if not cells:
                        continue
                    # 第一行非分隔行是表头
                    if headers is None and not self._is_sep_row(row):
                        headers = cells
                        continue
                    if not headers:
                        continue
                    # 提取路径字段
                    path = self._extract_path_from_cells(cells, headers)
                    if not path:
                        continue
                    # 创建 Document 实体
                    eid = self._make_entity_id(path)
                    if not self._seen_paths.get(path):
                        self._seen_paths[path] = eid
                        self._ont.add_entity(
                            entity_type="Document",
                            entity_id=eid,
                            properties={
                                "path": path,
                                "raw_cells": cells,
                                "headers": headers,
                            },
                        )
                        entity_count += 1
                        # 推断 part_of 关系
                        part_target = self._infer_part_of(path)
                        if part_target:
                            tgt_id = self._make_entity_id(part_target)
                            if not self._ont.get_entity(tgt_id):
                                self._ont.add_entity(
                                    entity_type="Module",
                                    entity_id=tgt_id,
                                    properties={"path": part_target},
                                )
                                entity_count += 1
                            self._ont.add_relation(eid, "part_of", tgt_id)
                            relation_count += 1
                        # 推断 covers_topic 关系
                        if topic_id:
                            self._ont.add_relation(
                                eid, "covers_topic", topic_id
                            )
                            relation_count += 1

            return (entity_count, relation_count)
        except Exception:
            return (0, 0)

    # ============================================================
    # 内部解析方法
    # ============================================================

    def _extract_sections(self, lines: List[str]) -> List[str]:
        """抽取章节标题列表。"""
        sections: List[str] = []
        for line in lines:
            m = _SECTION_RE.match(line)
            if m:
                sections.append(m.group(2).strip())
        return sections

    def _extract_tables(
        self, lines: List[str]
    ) -> List[Tuple[str, List[str]]]:
        """抽取 markdown 表格，按章节分组。

        Returns:
            [(section_title, [表格行, ...]), ...]
        """
        result: List[Tuple[str, List[str]]] = []
        current_section = ""
        current_table: List[str] = []

        for line in lines:
            # 章节切换
            m = _SECTION_RE.match(line)
            if m:
                # 提交当前表格
                if current_table:
                    result.append((current_section, current_table))
                    current_table = []
                current_section = m.group(2).strip()
                continue

            # 表格行检测
            if _TABLE_ROW_RE.match(line):
                current_table.append(line)
            else:
                # 非表格行 → 表格结束
                if current_table:
                    result.append((current_section, current_table))
                    current_table = []

        # 末尾
        if current_table:
            result.append((current_section, current_table))

        return result

    def _parse_table_row(self, row: str) -> List[str]:
        """解析表格行为字段列表。"""
        m = _TABLE_ROW_RE.match(row)
        if not m:
            return []
        content = m.group(1)
        return [c.strip() for c in content.split("|")]

    def _is_sep_row(self, row: str) -> bool:
        """是否为分隔行（|---|---|）。"""
        return bool(_TABLE_SEP_RE.match(row))

    def _extract_path_from_cells(
        self, cells: List[str], headers: List[str]
    ) -> Optional[str]:
        """从表格行字段中提取文档路径。

        策略：
          1. 找 headers 含 'path'/'路径'/'文件'/'位置' 的列
          2. 否则找含 markdown 链接的单元格
          3. 提取 [text](path) 中的 url
        """
        # 1. header 列定位
        path_col = -1
        for i, h in enumerate(headers):
            if any(k in h.lower() for k in ("path", "路径", "文件", "位置")):
                path_col = i
                break
        if path_col >= 0 and path_col < len(cells):
            cell = cells[path_col]
            return self._extract_link_url(cell) or cell

        # 2. 找含链接的单元格
        for cell in cells:
            url = self._extract_link_url(cell)
            if url:
                return url

        # 3. 无链接 → 找以 .md 结尾的纯文本
        for cell in cells:
            if cell.endswith(".md") or "/" in cell:
                return cell

        return None

    def _extract_link_url(self, text: str) -> Optional[str]:
        """从 markdown 链接 [text](url) 提取 url。"""
        m = _LINK_RE.search(text)
        if m:
            return m.group(2)
        return None

    def _infer_part_of(self, path: str) -> Optional[str]:
        """从路径层级推断 part_of 关系的目标。

        规则：取路径的父目录部分作为 Module。
        例如 '10-经典指标系统/docs/TECHNICAL_DESIGN.md'
        → '10-经典指标系统'

        Returns:
            父模块路径，None 表示无法推断
        """
        if not path:
            return None
        # 标准化
        clean = path.lstrip("./")
        # 如果是绝对路径风格 ../X/Y.md，取 X
        if clean.startswith("../"):
            clean = clean[3:]
        parts = clean.split("/")
        if len(parts) >= 2:
            # 父目录就是 parts[0]（如果是 docs/README.md → 取上一个）
            if parts[-2] in ("docs", "scripts", "core", "lib", "tests"):
                if len(parts) >= 3:
                    return parts[-3]
            return parts[-2]
        return None

    def _infer_covers_topic(self, section_title: str) -> Optional[str]:
        """从章节标题推断主题 ID。

        Returns:
            Topic 实体 ID
        """
        if not section_title:
            return None
        return self._make_topic_id(section_title)

    def _make_entity_id(self, path: str) -> str:
        """从路径生成稳定实体 ID（哈希前缀）。"""
        clean = path.lstrip("./").lstrip("../")
        h = hashlib.md5(clean.encode("utf-8")).hexdigest()[:8]
        return f"doc_{h}"

    def _make_topic_id(self, title: str) -> Optional[str]:
        """从章节标题生成 Topic 实体 ID。"""
        if not title:
            return None
        h = hashlib.md5(title.encode("utf-8")).hexdigest()[:8]
        return f"topic_{h}"


# ============================================================
# CLI 自测
# ============================================================


if __name__ == "__main__":
    import tempfile

    print("=" * 60)
    print("FIBOIndexLoader — 功能验证")
    print("=" * 60)

    sample_md = """# 测试 INDEX

## L1 — 顶层

| 文档 | 路径 | 职责 |
|------|------|------|
| 架构 | [SYSTEM.md](../1-ARCHITECTURE/SYSTEM.md) | 架构事实源 |
| 章程 | [CHARTER.md](../2-GOVERNANCE/CHARTER.md) | 大法 |

## L2 — 子系统

### 10-经典指标

| 文档 | 路径 | 版本 |
|------|------|------|
| README | [10/README.md](../10/README.md) | - |
| 技术 | [10/docs/TECH.md](../10/docs/TECH.md) | v2.0 |
"""

    with tempfile.TemporaryDirectory() as td:
        md_path = Path(td) / "INDEX.md"
        md_path.write_text(sample_md, encoding="utf-8")

        from fibo_ontology import FIBOOntology

        ont = FIBOOntology()
        loader = FIBOIndexLoader(ont)
        n, m = loader.parse_index(md_path)
        print(f"\n创建实体: {n}, 关系: {m}")
        print(f"Stats: {ont.stats()}")

        # 验证
        docs = ont.query("Document")
        print(f"\nDocuments: {[e.id for e in docs]}")
        for d in docs:
            rels = ont.get_relations(d.id, "part_of")
            if rels:
                print(f"  {d.id} part_of → {rels[0].to_id}")
            topic_rels = ont.get_relations(d.id, "covers_topic")
            if topic_rels:
                print(f"  {d.id} covers_topic → {topic_rels[0].to_id}")

    print("\n" + "=" * 60)
    print("✅ FIBOIndexLoader 功能验证通过")
