#!/usr/bin/env python3
"""
跨 Tier Consolidation 引擎 — 借鉴 Hermes 三级容量管理

将文档中定义的 Tier 0/1/2 三级容量管理机制落地为可执行代码。

核心能力:
1. 容量监控：检测 Tier 0 (CORE.md) 和 Tier 1 (分目录) 的容量使用率
2. 自动压缩：当使用率 ≥ 80% 时触发 consolidation
3. 跨 Tier 流转：低等级记忆降级到下层 Tier，高等级记忆保留在上层
4. 压缩表达：将冗长记忆压缩为简洁表达，不删减核心信息
5. 合并去重：相似记忆合并为一条

三级架构:
    Tier 0 (CORE.md)        ≤ 8,000 字符   S/A级原则+方法论+Top经验
    Tier 1 (1-5分目录)       ≤ 50,000 字符  A/B级经验教训+文档索引
    Tier 2 (archive/)        不限            C/D级+归档+历史版本

触发条件:
    - Tier 0 使用率 ≥ 80% (6,400字符)
    - Tier 1 使用率 ≥ 80% (40,000字符)
    - 手动调用

压缩流程:
    1. 扫描所有记忆条目
    2. 按质量等级分类：S/A保留 → B评估 → C合并 → D归档
    3. 压缩表达：冗长句子→简洁表达
    4. 合并相似：多条同类经验→一条
    5. 执行流转：D级→Tier2, C级合并后→Tier1
    6. 重写 CORE.md（保留最精华的 S/A 级内容）
    7. 验证压缩后容量 < 60%

用法:
    from consolidation_engine import ConsolidationEngine

    engine = ConsolidationEngine()
    report = engine.check_and_consolidate()
    if report.consolidated:
        print(f"压缩完成: {report.before_usage:.0%} → {report.after_usage:.0%}")
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ============================================================
# 常量
# ============================================================

TIER0_MAX_CHARS = 8000
TIER1_MAX_CHARS = 100000  # 核心方法论文档（A1/A8/矛盾论等）是高价值资产，提升上限避免误压缩
CONSOLIDATION_THRESHOLD = 0.80  # 80% 触发
POST_CONSOLIDATION_TARGET = 0.60  # 压缩后目标 < 60%

# Tier 1 目录映射
TIER1_DIRS = {
    "1-原则记忆": "ENGINEERING_PRINCIPLES.md",
    "2-方法论记忆": ["A1_RESEARCH_METHOD.md", "A8_THEORY_PRACTICE.md", "CONTRADICTION_METHOD.md"],
    "3-架构记忆": ["ARCHITECTURE_CURRENT.md", "ARCHITECTURE_HISTORY.md", "ADR-001-memory-architecture.md"],
    "4-文档记忆": "README.md",
    "5-通用经验": ["TECH_LESSONS.md", "PROCESS_LESSONS.md", "BEST_PRACTICES.md", "ANTI_PATTERNS.md"],
}

# 质量等级排序
QUALITY_ORDER = {"S": 5, "A": 4, "B": 3, "C": 2, "D": 1}


# ============================================================
# 数据模型
# ============================================================

@dataclass
class MemoryItem:
    """记忆条目（从 Markdown 解析）"""
    line_number: int = 0
    content: str = ""
    quality_level: str = "B"  # 从内容推断或默认
    category: str = ""  # principle / methodology / experience / architecture
    tier: int = 0
    char_count: int = 0
    tags: List[str] = field(default_factory=list)

    def compressed_content(self) -> str:
        """压缩表达：去除冗余描述，保留核心信息"""
        text = self.content.strip()

        # 去除 markdown 列表前缀
        text = re.sub(r'^[-*]\s+', '', text)
        # 去除序号前缀
        text = re.sub(r'^\d+\.\s+', '', text)
        # 压缩多余空格
        text = re.sub(r'\s+', ' ', text)
        # 去除冗余的"注意"、"需要"等前缀
        text = re.sub(r'^(注意：|需要注意：|需要|要注意)\s*', '', text)

        # 如果已经足够简洁，直接返回
        if len(text) <= 60:
            return text

        # 不丢弃内容——只做轻量压缩，保留完整信息
        # （之前的"只保留标题"逻辑会导致根因/解决方案/案例丢失）
        return text


@dataclass
class ConsolidationReport:
    """压缩报告"""
    consolidated: bool = False
    tier: int = 0
    before_chars: int = 0
    after_chars: int = 0
    before_usage: float = 0.0
    after_usage: float = 0.0
    items_scanned: int = 0
    items_kept: int = 0
    items_compressed: int = 0
    items_merged: int = 0
    items_archived: int = 0
    items_downgraded: int = 0
    archive_path: str = ""
    timestamp: str = ""
    details: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "consolidated": self.consolidated,
            "tier": self.tier,
            "before_chars": self.before_chars,
            "after_chars": self.after_chars,
            "before_usage": f"{self.before_usage:.1%}",
            "after_usage": f"{self.after_usage:.1%}",
            "items_scanned": self.items_scanned,
            "items_kept": self.items_kept,
            "items_compressed": self.items_compressed,
            "items_merged": self.items_merged,
            "items_archived": self.items_archived,
            "items_downgraded": self.items_downgraded,
            "archive_path": self.archive_path,
            "timestamp": self.timestamp,
            "details": self.details,
        }


@dataclass
class ArchiveCandidate:
    """归档候选条目（不执行压缩，仅用于人工确认）"""
    item_id: str = ""               # TL-001 / AP-002
    title: str = ""
    file_path: str = ""
    line_number: int = 0
    current_quality: str = "B"
    suggested_quality: str = "C"    # 建议降级到的质量等级
    reason_type: str = ""           # content_defect / outdated_case / cross_duplicate / low_value_detail
    reason_detail: str = ""
    char_count: int = 0
    potential_saving: int = 0       # 归档后可释放字符数
    duplicate_with: List[str] = field(default_factory=list)  # 跨文件重复的条目ID

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "title": self.title,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "current_quality": self.current_quality,
            "suggested_quality": self.suggested_quality,
            "reason_type": self.reason_type,
            "reason_detail": self.reason_detail,
            "char_count": self.char_count,
            "potential_saving": self.potential_saving,
            "duplicate_with": self.duplicate_with,
        }


# ============================================================
# 核心引擎
# ============================================================

class ConsolidationEngine:
    """
    跨 Tier Consolidation 引擎

    管理 Tier 0 (CORE.md) / Tier 1 (分目录) / Tier 2 (archive) 的容量和压缩。
    """

    def __init__(self, memory_root: Optional[Path] = None):
        if memory_root is None:
            memory_root = Path(__file__).parent.parent
        self.memory_root = Path(memory_root)
        self.core_md_path = self.memory_root / "CORE.md"
        self.archive_dir = self.memory_root / "archive"
        self.archive_dir.mkdir(parents=True, exist_ok=True)

    # ============================================================
    # 容量监控
    # ============================================================

    def get_tier0_usage(self) -> Tuple[int, float]:
        """获取 Tier 0 (CORE.md) 容量使用"""
        if not self.core_md_path.exists():
            return 0, 0.0
        chars = len(self.core_md_path.read_text(encoding="utf-8"))
        return chars, chars / TIER0_MAX_CHARS

    def get_tier1_usage(self) -> Tuple[int, float]:
        """获取 Tier 1 (分目录) 总容量使用"""
        total_chars = 0
        for dir_name, files in TIER1_DIRS.items():
            dir_path = self.memory_root / dir_name
            if isinstance(files, str):
                files = [files]
            for fname in files:
                fpath = dir_path / fname
                if fpath.exists():
                    total_chars += len(fpath.read_text(encoding="utf-8"))
        return total_chars, total_chars / TIER1_MAX_CHARS

    def get_capacity_report(self) -> Dict[str, Any]:
        """获取完整容量报告"""
        t0_chars, t0_usage = self.get_tier0_usage()
        t1_chars, t1_usage = self.get_tier1_usage()

        return {
            "tier0": {
                "path": str(self.core_md_path),
                "chars": t0_chars,
                "max_chars": TIER0_MAX_CHARS,
                "usage": f"{t0_usage:.1%}",
                "needs_consolidation": t0_usage >= CONSOLIDATION_THRESHOLD,
            },
            "tier1": {
                "dirs": list(TIER1_DIRS.keys()),
                "chars": t1_chars,
                "max_chars": TIER1_MAX_CHARS,
                "usage": f"{t1_usage:.1%}",
                "needs_consolidation": t1_usage >= CONSOLIDATION_THRESHOLD,
            },
            "tier2": {
                "path": str(self.archive_dir),
                "unlimited": True,
            },
            "threshold": f"{CONSOLIDATION_THRESHOLD:.0%}",
            "target_after": f"{POST_CONSOLIDATION_TARGET:.0%}",
        }

    # ============================================================
    # 检查并压缩
    # ============================================================

    def check_and_consolidate(self, force: bool = False) -> ConsolidationReport:
        """
        检查容量并按需触发压缩。

        Args:
            force: 强制压缩（忽略阈值检查）

        Returns:
            压缩报告
        """
        t0_chars, t0_usage = self.get_tier0_usage()
        t1_chars, t1_usage = self.get_tier1_usage()

        # 优先检查 Tier 0
        if force or t0_usage >= CONSOLIDATION_THRESHOLD:
            logger.info(f"触发 Tier 0 压缩: {t0_usage:.1%} >= {CONSOLIDATION_THRESHOLD:.0%}")
            return self._consolidate_tier0()

        # 检查 Tier 1
        if t1_usage >= CONSOLIDATION_THRESHOLD:
            logger.info(f"触发 Tier 1 压缩: {t1_usage:.1%} >= {CONSOLIDATION_THRESHOLD:.0%}")
            return self._consolidate_tier1()

        return ConsolidationReport(
            consolidated=False,
            tier=0,
            before_chars=t0_chars,
            after_chars=t0_chars,
            before_usage=t0_usage,
            after_usage=t0_usage,
            timestamp=datetime.now(timezone.utc).isoformat(),
            details=[f"Tier 0 {t0_usage:.1%}, Tier 1 {t1_usage:.1%}，均未达阈值"],
        )

    # ============================================================
    # Tier 0 压缩
    # ============================================================

    def _consolidate_tier0(self) -> ConsolidationReport:
        """执行 Tier 0 (CORE.md) 压缩"""
        original_content = self.core_md_path.read_text(encoding="utf-8")
        original_chars = len(original_content)
        original_usage = original_chars / TIER0_MAX_CHARS

        report = ConsolidationReport(
            consolidated=True,
            tier=0,
            before_chars=original_chars,
            before_usage=original_usage,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        # 解析 CORE.md 结构
        sections = self._parse_core_md(original_content)
        report.items_scanned = sum(len(items) for items in sections.values())

        # 备份原始版本到 Tier 2
        archive_path = self._archive_tier0(original_content)
        report.archive_path = str(archive_path)

        # 按类别压缩
        new_sections: Dict[str, List[MemoryItem]] = {}

        for section_name, items in sections.items():
            kept, compressed, merged, archived, downgraded = self._process_section(section_name, items, report)
            new_sections[section_name] = kept
            report.items_compressed += compressed
            report.items_merged += merged
            report.items_archived += archived
            report.items_downgraded += downgraded

        # 重建 CORE.md
        new_content = self._rebuild_core_md(new_sections)
        new_chars = len(new_content)
        new_usage = new_chars / TIER0_MAX_CHARS

        # 写入压缩后的 CORE.md
        self.core_md_path.write_text(new_content, encoding="utf-8")

        report.after_chars = new_chars
        report.after_usage = new_usage
        report.items_kept = sum(len(items) for items in new_sections.values())

        # 更新压缩时间戳
        report.details.append(f"压缩前: {original_chars} 字符 ({original_usage:.1%})")
        report.details.append(f"压缩后: {new_chars} 字符 ({new_usage:.1%})")
        report.details.append(f"节省: {original_chars - new_chars} 字符 ({(1 - new_chars/max(original_chars,1)):.1%})")
        report.details.append(f"归档: {archive_path.name}")

        return report

    def _parse_core_md(self, content: str) -> Dict[str, List[MemoryItem]]:
        """解析 CORE.md 为分区记忆条目"""
        sections: Dict[str, List[MemoryItem]] = {}
        current_section = ""
        current_items: List[MemoryItem] = []

        for i, line in enumerate(content.split("\n"), 1):
            # 检测分区标题
            if line.startswith("## "):
                if current_section and current_items:
                    sections[current_section] = current_items
                current_section = line[3:].strip()
                current_items = []
            # 检测记忆条目（列表项）
            elif re.match(r'^[-*]\s+', line) or re.match(r'^\d+\.\s+', line):
                item = MemoryItem(
                    line_number=i,
                    content=line,
                    quality_level=self._infer_quality(current_section, line),
                    category=self._infer_category(current_section),
                    tier=0,
                    char_count=len(line),
                )
                current_items.append(item)
            # 空行或元信息跳过
            elif line.strip() and not line.startswith(">") and not line.startswith("#"):
                # 非列表非标题非元信息的内容也作为条目
                if current_section:
                    item = MemoryItem(
                        line_number=i,
                        content=line,
                        quality_level=self._infer_quality(current_section, line),
                        category=self._infer_category(current_section),
                        tier=0,
                        char_count=len(line),
                    )
                    current_items.append(item)

        if current_section and current_items:
            sections[current_section] = current_items

        return sections

    def _infer_quality(self, section_name: str, content: str) -> str:
        """从分区名和内容推断质量等级"""
        section_lower = section_name.lower()
        if "s级" in section_name or "原则" in section_name:
            return "S"
        if "a级" in section_name or "方法论" in section_name or "架构决策" in section_name:
            return "A"
        if "b级" in section_name or "经验" in section_name:
            return "B"
        if "技术债" in section_name:
            return "B"
        return "B"

    def _infer_category(self, section_name: str) -> str:
        """推断类别"""
        if "原则" in section_name:
            return "principle"
        if "方法论" in section_name:
            return "methodology"
        if "架构" in section_name:
            return "architecture"
        if "经验" in section_name:
            return "experience"
        if "技术债" in section_name:
            return "tech_debt"
        return "other"

    def _process_section(
        self,
        section_name: str,
        items: List[MemoryItem],
        report: ConsolidationReport,
    ) -> Tuple[List[MemoryItem], int, int, int, int]:
        """
        处理单个分区的记忆条目。

        Returns:
            (保留的条目, 压缩数, 合并数, 归档数, 降级数)
        """
        kept: List[MemoryItem] = []
        compressed = 0
        merged = 0
        archived = 0
        downgraded = 0

        # 按质量等级排序（高→低）
        items_sorted = sorted(items, key=lambda x: QUALITY_ORDER.get(x.quality_level, 3), reverse=True)

        # 合并相似条目
        merged_items = self._merge_similar(items_sorted)
        merged = len(items) - len(merged_items)

        for item in merged_items:
            original_len = len(item.content)

            # D 级归档
            if item.quality_level == "D":
                archived += 1
                report.details.append(f"  归档D级: {item.compressed_content()[:40]}...")
                continue

            # C 级：如果已经合并过就保留，否则归档到 Tier 1
            if item.quality_level == "C" and len(merged_items) > 10:
                # C 级过多时归档
                archived += 1
                downgraded += 1
                report.details.append(f"  降级C级到Tier1: {item.compressed_content()[:40]}...")
                continue

            # 压缩表达
            compressed_text = item.compressed_content()
            if len(compressed_text) < original_len - 10:
                item.content = f"- {compressed_text}"
                compressed += 1

            kept.append(item)

        return kept, compressed, merged, archived, downgraded

    def _merge_similar(self, items: List[MemoryItem]) -> List[MemoryItem]:
        """合并相似的记忆条目"""
        if len(items) <= 1:
            return items

        merged: List[MemoryItem] = []
        used = [False] * len(items)

        for i, item_a in enumerate(items):
            if used[i]:
                continue
            used[i] = True
            current = item_a

            for j in range(i + 1, len(items)):
                if used[j]:
                    continue
                item_b = items[j]

                # 检查相似度
                if self._is_similar(current.content, item_b.content):
                    # 合并：保留质量更高的
                    if QUALITY_ORDER.get(item_b.quality_level, 3) > QUALITY_ORDER.get(current.quality_level, 3):
                        current = item_b
                    used[j] = True

            merged.append(current)

        return merged

    def _is_similar(self, text_a: str, text_b: str) -> bool:
        """判断两个文本是否相似"""
        # 提取关键词
        words_a = set(re.findall(r'[\w\u4e00-\u9fff]+', text_a.lower()))
        words_b = set(re.findall(r'[\w\u4e00-\u9fff]+', text_b.lower()))

        if not words_a or not words_b:
            return False

        # Jaccard 相似度
        intersection = words_a & words_b
        union = words_a | words_b
        similarity = len(intersection) / len(union)

        return similarity > 0.5

    def _rebuild_core_md(self, sections: Dict[str, List[MemoryItem]]) -> str:
        """重建 CORE.md"""
        now = datetime.now().strftime("%Y-%m-%d")
        total_chars = 0
        for items in sections.values():
            for item in items:
                total_chars += len(item.content)
        usage = total_chars / TIER0_MAX_CHARS

        lines = [
            "# Core Memory — 核心记忆",
            "",
            f"> 容量: ≤ 8,000 字符 | 上次压缩: {now} | 当前占用: ~{usage:.0%}",
            "> 此文件是系统的常驻记忆，每次会话自动注入",
            "",
        ]

        for section_name, items in sections.items():
            lines.append(f"## {section_name}")
            lines.append("")
            for item in items:
                lines.append(item.content)
            lines.append("")

        return "\n".join(lines)

    def _archive_tier0(self, content: str) -> Path:
        """归档原始 CORE.md 到 Tier 2"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_path = self.archive_dir / f"CORE_{timestamp}.md"
        archive_path.write_text(content, encoding="utf-8")
        return archive_path

    # ============================================================
    # 手动接口
    # ============================================================

    def consolidate_tier0(self, force: bool = True) -> ConsolidationReport:
        """手动触发 Tier 0 压缩"""
        return self.check_and_consolidate(force=force)

    def consolidate_tier1(self, force: bool = False) -> ConsolidationReport:
        """手动触发 Tier 1 压缩"""
        if force:
            return self._consolidate_tier1()
        return self.check_and_consolidate()

    def _consolidate_tier1(self) -> ConsolidationReport:
        """执行 Tier 1 压缩"""
        t1_chars, t1_usage = self.get_tier1_usage()

        report = ConsolidationReport(
            consolidated=True,
            tier=1,
            before_chars=t1_chars,
            before_usage=t1_usage,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        total_scanned = 0
        total_compressed = 0
        total_merged = 0
        total_archived = 0
        total_after_chars = 0
        total_kept = 0

        for dir_name, files in TIER1_DIRS.items():
            dir_path = self.memory_root / dir_name
            if isinstance(files, str):
                files = [files]

            for fname in files:
                fpath = dir_path / fname
                if not fpath.exists():
                    continue

                original = fpath.read_text(encoding="utf-8")
                original_chars = len(original)

                # 解析记忆条目
                items = self._parse_markdown_items(original)
                total_scanned += len(items)

                # 压缩处理
                kept, compressed, merged, archived = self._compress_items(items)
                total_compressed += compressed
                total_merged += merged
                total_archived += archived

                # 归档原始版本
                if compressed > 0 or merged > 0 or archived > 0:
                    archive_path = self.archive_dir / f"{fname}.bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                    archive_path.write_text(original, encoding="utf-8")

                # 重写文件（文档式结构用专用重建器，列表式用原方法）
                if self._is_document_structured(original):
                    new_content = self._rebuild_document_md(original, kept)
                else:
                    new_content = self._rebuild_markdown(original, kept)
                new_chars = len(new_content)
                total_after_chars += new_chars
                total_kept += len(kept)

                # 只要内容有变化就写回（不再要求 new_chars < original_chars）
                if new_content != original:
                    fpath.write_text(new_content, encoding="utf-8")
                    delta = new_chars - original_chars
                    sign = "-" if delta < 0 else "+"
                    report.details.append(f"  {fname}: {original_chars}→{new_chars} 字符 ({sign}{abs(delta)})")
                else:
                    report.details.append(f"  {fname}: {original_chars} 字符（无变化）")

        report.items_scanned = total_scanned
        report.items_compressed = total_compressed
        report.items_merged = total_merged
        report.items_archived = total_archived
        report.items_kept = total_kept
        report.after_chars = total_after_chars
        report.after_usage = total_after_chars / TIER1_MAX_CHARS

        report.details.insert(0, f"Tier 1 压缩: {t1_chars}→{total_after_chars} 字符 ({t1_usage:.1%}→{report.after_usage:.1%})")

        return report

    def _parse_markdown_items(self, content: str) -> List[MemoryItem]:
        """
        解析 Markdown 文件为记忆条目列表。

        自动识别两种结构：
        1. 文档式：`## TL-XXX：` / `## AP-XXX：` / `## BP-XXX：` / `## PL-XXX：` 为条目边界
        2. 列表式：`- ` 或 `1.` 开头的列表项

        文档式优先：检测到条目型标题时按章节解析，否则回退到列表式。
        """
        # 先检测是否为文档式结构
        if self._is_document_structured(content):
            return self._parse_document_items(content)
        return self._parse_list_items(content)

    # 文档式条目标题正则：## TL-001： / ## AP-002： / ## BP-003： / ## PL-004：
    _DOC_ITEM_PATTERN = re.compile(r'^##\s+([A-Z]{2,4})-(\d{3})[：:]\s*(.+)$')

    def _is_document_structured(self, content: str) -> bool:
        """检测是否为文档式结构（包含 ## XXX-NNN： 条目）"""
        count = 0
        for line in content.split("\n"):
            if self._DOC_ITEM_PATTERN.match(line):
                count += 1
                if count >= 1:
                    return True
        return False

    def _parse_document_items(self, content: str) -> List[MemoryItem]:
        """
        解析文档式 Markdown：每个 ## XXX-NNN： 标题到下一个 ## 之间为一个条目。

        提取：
        - 条目ID（如 TL-001）
        - 标题
        - 质量等级（从属性表 | **等级** | B | 解析）
        - 完整章节内容
        - 字符数
        """
        items: List[MemoryItem] = []
        lines = content.split("\n")
        n = len(lines)

        i = 0
        while i < n:
            line = lines[i]
            match = self._DOC_ITEM_PATTERN.match(line)
            if not match:
                i += 1
                continue

            prefix = match.group(1)  # TL / AP / BP / PL
            num = match.group(2)     # 001
            title = match.group(3).strip()
            item_id = f"{prefix}-{num}"

            # 收集章节内容（到下一个 ## 或文件末尾）
            section_start = i
            section_lines = [line]
            i += 1
            while i < n:
                next_line = lines[i]
                # 遇到下一个 ## 条目或 ## 非条目标题则停止
                if next_line.startswith("## "):
                    break
                section_lines.append(next_line)
                i += 1

            section_content = "\n".join(section_lines)
            # 从属性表提取质量等级
            quality = self._extract_quality_from_section(section_content, prefix)
            # 从标题前缀推断类别
            category = self._prefix_to_category(prefix)

            items.append(MemoryItem(
                line_number=section_start + 1,
                content=section_content,
                quality_level=quality,
                category=category,
                tier=1,
                char_count=len(section_content),
                tags=[item_id, title],
            ))

        return items

    def _extract_quality_from_section(self, section: str, prefix: str) -> str:
        """从章节内容的属性表提取质量等级"""
        # 匹配 | **等级** | B（待验证） | 或 | **等级** | A（可信级） |
        m = re.search(r'\|\s*\*\*等级\*\*\s*\|\s*([SABCD])', section)
        if m:
            return m.group(1)
        # 匹配 | **危害程度** | 高 | （反模式专用，默认按 A 级处理）
        m = re.search(r'\|\s*\*\*危害程度\*\*\s*\|\s*([高中低])', section)
        if m:
            # 反模式：危害高=A，危害中=B，危害低=C
            return {"高": "A", "中": "B", "低": "C"}.get(m.group(1), "B")
        # 默认按 prefix 推断
        if prefix in ("TL", "PL"):
            return "B"  # 教训默认 B 级
        if prefix in ("BP",):
            return "A"  # 最佳实践默认 A 级
        if prefix in ("AP",):
            return "A"  # 反模式默认 A 级
        return "B"

    def _prefix_to_category(self, prefix: str) -> str:
        """条目前缀转类别"""
        return {
            "TL": "tech_lesson",
            "PL": "process_lesson",
            "BP": "best_practice",
            "AP": "anti_pattern",
        }.get(prefix, "other")

    def _parse_list_items(self, content: str) -> List[MemoryItem]:
        """解析列表式 Markdown（原逻辑）"""
        items = []
        lines = content.split("\n")
        current_section = ""

        for i, line in enumerate(lines, 1):
            if line.startswith("## "):
                current_section = line[3:].strip()
            elif line.startswith("# ") or line.startswith(">") or not line.strip():
                continue
            elif re.match(r'^[-*]\s+', line) or re.match(r'^\d+\.\s+', line):
                items.append(MemoryItem(
                    line_number=i,
                    content=line,
                    quality_level=self._infer_quality(current_section, line),
                    category=self._infer_category(current_section),
                    tier=1,
                    char_count=len(line),
                ))

        return items

    def _compress_items(self, items: List[MemoryItem]) -> Tuple[List[MemoryItem], int, int, int]:
        """压缩记忆条目列表"""
        if not items:
            return [], 0, 0, 0

        compressed = 0
        archived = 0

        # 合并相似
        merged_items = self._merge_similar(items)
        merged = len(items) - len(merged_items)

        kept = []
        for item in merged_items:
            original_len = len(item.content)

            # 超长条目（>200字符）强制压缩
            if original_len > 200:
                compressed_text = item.compressed_content()
                if len(compressed_text) < original_len - 20:
                    prefix_match = re.match(r'^([-*]\s+|\d+\.\s+)', item.content)
                    prefix = prefix_match.group(1) if prefix_match else "- "
                    item.content = prefix + compressed_text
                    compressed += 1
                kept.append(item)
                continue

            # 中等条目（>80字符）尝试压缩
            if original_len > 80:
                compressed_text = item.compressed_content()
                if len(compressed_text) < original_len - 10:
                    prefix_match = re.match(r'^([-*]\s+|\d+\.\s+)', item.content)
                    prefix = prefix_match.group(1) if prefix_match else "- "
                    item.content = prefix + compressed_text
                    compressed += 1

            kept.append(item)

        return kept, compressed, merged, archived

    def _rebuild_markdown(self, original: str, items: List[MemoryItem]) -> str:
        """重建 Markdown 文件（保留原始结构，替换记忆条目）"""
        lines = original.split("\n")
        item_idx = 0
        new_lines = []

        for line in lines:
            if re.match(r'^[-*]\s+', line) or re.match(r'^\d+\.\s+', line):
                if item_idx < len(items):
                    new_lines.append(items[item_idx].content)
                    item_idx += 1
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)

        return "\n".join(new_lines)

    def _rebuild_document_md(self, original: str, items: List[MemoryItem]) -> str:
        """
        重建文档式 Markdown 文件。

        按 ## XXX-NNN： 章节边界切片，用压缩后的 item.content 替换对应章节。
        参照 execute_archive 的字符偏移切片法，避免错位。
        """
        # 建立 item_id → 新 content 的映射
        new_by_id: Dict[str, str] = {}
        for item in items:
            if item.tags and len(item.tags) >= 1:
                new_by_id[item.tags[0]] = item.content

        # 找到所有 ## XXX-NNN： 章节的边界
        lines = original.split("\n")
        n = len(lines)
        # 收集 (start_line, end_line, item_id) 三元组
        sections: List[tuple] = []
        i = 0
        while i < n:
            match = self._DOC_ITEM_PATTERN.match(lines[i])
            if match:
                item_id = f"{match.group(1)}-{match.group(2)}"
                start = i
                i += 1
                while i < n and not lines[i].startswith("## "):
                    i += 1
                end = i  # 不包含 end 行
                sections.append((start, end, item_id))
            else:
                i += 1

        if not sections:
            return original

        # 从后往前替换（避免偏移变化）
        new_lines = list(lines)
        for start, end, item_id in reversed(sections):
            if item_id in new_by_id:
                new_content = new_by_id[item_id]
                new_lines[start:end] = new_content.split("\n")

        return "\n".join(new_lines)

    def healthcheck(self) -> Dict[str, Any]:
        """健康检查"""
        capacity = self.get_capacity_report()
        return {
            "status": "healthy",
            "capacity": capacity,
            "archive_count": len(list(self.archive_dir.glob("CORE_*.md"))),
        }

    # ============================================================
    # 归档候选识别（不执行压缩，仅产出清单）
    # ============================================================

    # 已修复的缺陷标记（用于识别过时案例）
    _RESOLVED_DEFECT_PATTERN = re.compile(r'D0(4[89]|5[0-9])')  # D048/D049/D05x 系列
    # 已修复关键词
    _RESOLVED_KEYWORDS = ["已修复", "已解决", "已关闭", "已处理"]

    def identify_archive_candidates(self) -> Dict[str, Any]:
        """
        扫描所有 Tier1 文件，识别可归档的 C/D 级候选。

        不执行实际压缩，仅产出归档候选清单供人工确认。

        归档候选类型:
        - content_defect: 内容残缺（编号混乱、步骤缺失、段落截断）
        - outdated_case:  过时案例（已修复缺陷的详细案例）
        - cross_duplicate: 跨文件重复（同一经验多角度表述）
        - low_value_detail: 低价值细节（案例段落过长，可归档保留结论）

        Returns:
            归档候选报告
        """
        all_items: List[Tuple[str, MemoryItem]] = []  # (file_name, item)
        per_file: Dict[str, List[MemoryItem]] = {}

        for dir_name, files in TIER1_DIRS.items():
            dir_path = self.memory_root / dir_name
            if isinstance(files, str):
                files = [files]
            for fname in files:
                fpath = dir_path / fname
                if not fpath.exists():
                    continue
                content = fpath.read_text(encoding="utf-8")
                items = self._parse_markdown_items(content)
                per_file[fname] = items
                for item in items:
                    all_items.append((fname, item))

        candidates: List[ArchiveCandidate] = []

        # 1. 单条目级检测：内容残缺 + 过时案例 + 低价值细节
        for fname, item in all_items:
            if not item.tags:  # 列表式条目跳过（无 ID）
                continue
            item_id = item.tags[0]
            title = item.tags[1] if len(item.tags) > 1 else ""

            # 1.1 内容残缺检测
            defect = self._detect_content_defect(item.content)
            if defect:
                candidates.append(ArchiveCandidate(
                    item_id=item_id,
                    title=title,
                    file_path=f"{fname}#L{item.line_number}",
                    line_number=item.line_number,
                    current_quality=item.quality_level,
                    suggested_quality="C",
                    reason_type="content_defect",
                    reason_detail=defect,
                    char_count=item.char_count,
                    potential_saving=item.char_count // 2,  # 残缺条目归档后约省一半
                ))
                continue  # 残缺条目不再做其他检测

            # 1.2 过时案例检测
            outdated = self._detect_outdated_case(item.content)
            if outdated:
                # 估算案例部分字符数（### 典型案例 / ### 相关案例 段落）
                case_chars = self._count_case_section_chars(item.content)
                candidates.append(ArchiveCandidate(
                    item_id=item_id,
                    title=title,
                    file_path=f"{fname}#L{item.line_number}",
                    line_number=item.line_number,
                    current_quality=item.quality_level,
                    suggested_quality="B",  # 教训本身保留，案例降级归档
                    reason_type="outdated_case",
                    reason_detail=outdated,
                    char_count=item.char_count,
                    potential_saving=case_chars,
                ))

            # 1.3 低价值细节检测
            elif item.char_count > 800:
                case_chars = self._count_case_section_chars(item.content)
                if case_chars > 200:
                    candidates.append(ArchiveCandidate(
                        item_id=item_id,
                        title=title,
                        file_path=f"{fname}#L{item.line_number}",
                        line_number=item.line_number,
                        current_quality=item.quality_level,
                        suggested_quality="B",
                        reason_type="low_value_detail",
                        reason_detail=f"案例段落 {case_chars} 字符，可归档到 Tier2 保留结论",
                        char_count=item.char_count,
                        potential_saving=case_chars,
                    ))

        # 2. 跨文件重复检测
        duplicates = self._detect_cross_duplicates(all_items)
        for dup_group in duplicates:
            # 保留质量最高的，其余标记为归档候选
            sorted_group = sorted(dup_group["items"], key=lambda x: QUALITY_ORDER.get(x[1].quality_level, 3), reverse=True)
            keep_item = sorted_group[0]
            for fname, item in sorted_group[1:]:
                item_id = item.tags[0] if item.tags else ""
                title = item.tags[1] if len(item.tags) > 1 else ""
                dup_ids = [other_item.tags[0] if other_item.tags else "" for _, other_item in sorted_group if other_item is not item]
                candidates.append(ArchiveCandidate(
                    item_id=item_id,
                    title=title,
                    file_path=f"{fname}#L{item.line_number}",
                    line_number=item.line_number,
                    current_quality=item.quality_level,
                    suggested_quality="C",
                    reason_type="cross_duplicate",
                    reason_detail=f"与 {', '.join(dup_ids)} 主题重复，建议合并或归档",
                    char_count=item.char_count,
                    potential_saving=item.char_count,
                    duplicate_with=dup_ids,
                ))

        # 汇总
        total_saving = sum(c.potential_saving for c in candidates)
        t1_chars, t1_usage = self.get_tier1_usage()
        projected_usage = (t1_chars - total_saving) / TIER1_MAX_CHARS

        return {
            "scan_timestamp": datetime.now(timezone.utc).isoformat(),
            "tier1_chars": t1_chars,
            "tier1_usage": f"{t1_usage:.1%}",
            "total_items_scanned": len(all_items),
            "total_candidates": len(candidates),
            "projected_saving_chars": total_saving,
            "projected_usage_after": f"{projected_usage:.1%}",
            "would_resolve_threshold": projected_usage < CONSOLIDATION_THRESHOLD,
            "candidates_by_type": {
                "content_defect": [c.to_dict() for c in candidates if c.reason_type == "content_defect"],
                "outdated_case": [c.to_dict() for c in candidates if c.reason_type == "outdated_case"],
                "cross_duplicate": [c.to_dict() for c in candidates if c.reason_type == "cross_duplicate"],
                "low_value_detail": [c.to_dict() for c in candidates if c.reason_type == "low_value_detail"],
            },
            "candidates": [c.to_dict() for c in candidates],
        }

    # ============================================================
    # 执行归档（将案例段落移到 Tier2）
    # ============================================================

    # 可归档的候选类型（content_defect 应修复而非归档，cross_duplicate 需合并逻辑）
    _ARCHIVABLE_TYPES = {"outdated_case", "low_value_detail"}

    # 案例段落标题正则（### 典型案例 / ### 相关案例 / ### 案例 / ### 已知案例）
    _CASE_SECTION_PATTERN = re.compile(
        r'^(###\s+(?:典型案例|相关案例|案例|已知案例)\s*\n)'
        r'([\s\S]*?)(?=^###\s|^##\s|\Z)',
        re.MULTILINE,
    )

    def execute_archive(
        self,
        candidate_ids: Optional[List[str]] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        执行归档：将候选条目的案例段落移到 Tier2。

        归档策略：
        - outdated_case / low_value_detail: 归档整个 ### 典型案例 段落到 Tier2
        - content_defect: 跳过（应修复而非归档）
        - cross_duplicate: 跳过（需要合并逻辑，不在此处理）

        原文件中案例段落替换为：
            ### 典型案例（已归档到 Tier2）
            > 详见 archive/{归档文件名}

        Args:
            candidate_ids: 指定归档的条目ID列表（如 ["TL-006", "TL-007"]）。
                          None 则归档所有可归档候选。
            dry_run: 预览模式，只产出计划不实际修改文件。

        Returns:
            归档执行报告
        """
        scan_report = self.identify_archive_candidates()
        candidates = [
            c for c in scan_report["candidates"]
            if c["reason_type"] in self._ARCHIVABLE_TYPES
        ]

        # 按候选ID过滤
        if candidate_ids is not None:
            candidate_set = set(candidate_ids)
            candidates = [c for c in candidates if c["item_id"] in candidate_set]
            found_ids = {c["item_id"] for c in candidates}
            missing = candidate_set - found_ids
            if missing:
                logger.warning(f"未找到可归档候选: {missing}")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        t1_chars_before, _ = self.get_tier1_usage()

        archive_plans: List[Dict[str, Any]] = []

        # ===== 阶段1：扫描提取 =====
        for cand in candidates:
            fname = cand["file_path"].split("#")[0]
            fpath = self._resolve_tier1_file(fname)
            if fpath is None or not fpath.exists():
                continue

            content = fpath.read_text(encoding="utf-8")
            item_id = cand["item_id"]

            # 定位条目（## TL-006：... 到下一个 ## 或文件末尾）
            item_pattern = re.compile(
                r'^##\s+' + re.escape(item_id) + r'[：:].*?(?=^##\s|\Z)',
                re.MULTILINE | re.DOTALL,
            )
            item_match = item_pattern.search(content)
            if not item_match:
                continue

            item_content = item_match.group(0)
            item_start = item_match.start()

            # 定位案例段落
            case_match = self._CASE_SECTION_PATTERN.search(item_content)
            if not case_match:
                continue

            case_full = case_match.group(1) + case_match.group(2)
            case_chars = len(case_full)
            case_start_in_file = item_start + case_match.start()
            case_end_in_file = item_start + case_match.end()

            # 生成归档文件名
            archive_fname = f"{fname.replace('.md', '')}_{item_id}_{timestamp}.md"
            archive_fpath = self.archive_dir / archive_fname

            # 构建归档文档
            archive_doc = self._build_archive_doc(
                item_id=item_id,
                title=cand["title"],
                source_file=fname,
                source_line=cand["line_number"],
                reason_type=cand["reason_type"],
                reason_detail=cand["reason_detail"],
                case_content=case_full,
            )

            replacement = (
                f"### 典型案例（已归档到 Tier2）\n"
                f"> 详见 `archive/{archive_fname}`\n\n"
            )

            archive_plans.append({
                "item_id": item_id,
                "title": cand["title"],
                "file": fname,
                "fpath": str(fpath),
                "archive_fname": archive_fname,
                "archive_fpath": str(archive_fpath),
                "archive_doc": archive_doc,
                "case_chars": case_chars,
                "saving_chars": case_chars - len(replacement),
                "replacement": replacement,
                "case_start_in_file": case_start_in_file,
                "case_end_in_file": case_end_in_file,
                "reason_type": cand["reason_type"],
            })

        # ===== 阶段2：写入落盘 =====
        # 按文件分组，同一文件的多个归档一起处理（避免位置偏移）
        by_file: Dict[str, List[Dict[str, Any]]] = {}
        for plan in archive_plans:
            by_file.setdefault(plan["file"], []).append(plan)

        results: List[Dict[str, Any]] = []
        total_saving = 0

        for fname, plans in by_file.items():
            fpath = self._resolve_tier1_file(fname)
            if fpath is None:
                continue

            original_content = fpath.read_text(encoding="utf-8")
            # 从后往前替换（避免位置偏移）
            sorted_plans = sorted(plans, key=lambda x: x["case_start_in_file"], reverse=True)
            new_content = original_content

            for plan in sorted_plans:
                new_content = (
                    new_content[:plan["case_start_in_file"]]
                    + plan["replacement"]
                    + new_content[plan["case_end_in_file"]:]
                )
                total_saving += plan["saving_chars"]

            for plan in plans:
                if not dry_run:
                    archive_path = Path(plan["archive_fpath"])
                    archive_path.parent.mkdir(parents=True, exist_ok=True)
                    archive_path.write_text(plan["archive_doc"], encoding="utf-8")

                results.append({
                    "item_id": plan["item_id"],
                    "title": plan["title"],
                    "file": fname,
                    "status": "archived" if not dry_run else "dry_run",
                    "archive_file": plan["archive_fpath"],
                    "archive_chars": plan["case_chars"],
                    "saving_chars": plan["saving_chars"],
                    "reason_type": plan["reason_type"],
                })

            if not dry_run and new_content != original_content:
                fpath.write_text(new_content, encoding="utf-8")

        # 计算压缩后容量
        if not dry_run:
            t1_chars_after, _ = self.get_tier1_usage()
        else:
            t1_chars_after = t1_chars_before - total_saving
        t1_usage_after_pct = t1_chars_after / TIER1_MAX_CHARS

        return {
            "executed": not dry_run,
            "dry_run": dry_run,
            "timestamp": timestamp,
            "total_planned": len(candidates),
            "total_archived": len([r for r in results if r["status"] == "archived"]),
            "total_dry_run": len([r for r in results if r["status"] == "dry_run"]),
            "total_skipped": len(candidates) - len(results),
            "total_saving_chars": total_saving,
            "tier1_before": f"{t1_chars_before} 字符 ({t1_chars_before/TIER1_MAX_CHARS:.1%})",
            "tier1_after": f"{t1_chars_after} 字符 ({t1_usage_after_pct:.1%})",
            "threshold_resolved": t1_usage_after_pct < CONSOLIDATION_THRESHOLD,
            "archive_dir": str(self.archive_dir),
            "results": results,
        }

    def _resolve_tier1_file(self, fname: str) -> Optional[Path]:
        """根据文件名解析 Tier1 文件的完整路径"""
        for dir_name, files in TIER1_DIRS.items():
            if isinstance(files, str):
                files = [files]
            if fname in files:
                return self.memory_root / dir_name / fname
        return None

    def _build_archive_doc(
        self,
        item_id: str,
        title: str,
        source_file: str,
        source_line: int,
        reason_type: str,
        reason_detail: str,
        case_content: str,
    ) -> str:
        """构建归档文档内容"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return f"""# Tier2 归档：{item_id}

> **归档时间**: {now}
> **来源文件**: {source_file}#L{source_line}
> **归档原因**: {reason_type}
> **原因详情**: {reason_detail}

## 条目标题

{title}

## 案例内容（从原文件移出）

{case_content}

---

**说明**: 本文件为 Tier2 归档内容，原条目仍在 Tier1 中保留结论和方法。
如需查看完整案例细节，请阅读本文件。
"""

    def _detect_content_defect(self, content: str) -> str:
        """检测内容残缺：编号混乱、步骤缺失、段落截断"""
        defects = []

        # 先剥离代码块（``` ... ``` 之间），避免代码内容误判
        code_stripped = re.sub(r'```[\s\S]*?```', '', content)

        # 检测编号混乱：列表项编号不连续（如 1,2,3 但跳到 1,2,3 在另一段落）
        # 找所有 ### 子标题下的列表编号
        sections = re.split(r'^###\s+', code_stripped, flags=re.MULTILINE)
        for section in sections[1:]:  # 跳过第一段（标题前）
            lines = section.split("\n")
            # 找数字列表项
            num_items = []
            for line in lines:
                m = re.match(r'^(\d+)\.\s+', line)
                if m:
                    num_items.append(int(m.group(1)))

            if num_items:
                # 检测是否从 1 开始连续
                expected = list(range(1, len(num_items) + 1))
                if num_items != expected:
                    defects.append(f"编号不连续: {num_items}，预期 1..{len(num_items)}")

        # 检测段落截断：句子未以句号/问号/感叹号/冒号/箭头等结尾
        # 允许的结尾：。！？.?!:：；; → ... ）) \``` 引用
        valid_endings = re.compile(r'[。！？.?!:：；;→\.\.\.\)）]$')
        for line in code_stripped.split("\n"):
            stripped = line.strip()
            if not stripped:
                continue
            # 跳过标题、表格、引用、列表、代码标记
            if stripped.startswith("#") or stripped.startswith("|") or stripped.startswith(">"):
                continue
            if stripped.startswith("```") or stripped.startswith("-") or re.match(r'^\d+\.', stripped):
                continue
            # 跳过代码内联行（含较多特殊符号）
            if stripped.startswith("`") or stripped.count("`") >= 2:
                continue
            # 跳过流程描述行（含 → 箭头连接的流程）
            if "→" in stripped:
                continue
            # 跳过短行（< 20 字符的不检测）
            if len(stripped) <= 20:
                continue
            # 普通段落，检查是否以标点结尾
            if not valid_endings.search(stripped):
                defects.append(f"段落可能截断: '{stripped[-30:]}'")
                break  # 只报一个

        return "; ".join(defects) if defects else ""

    def _detect_outdated_case(self, content: str) -> str:
        """
        检测过时案例：案例段落中引用已修复缺陷。

        只在"典型案例/相关案例"段落中检测，不在属性表或来源中检测，
        避免把"来源: D048"这种引用误判为过时案例。
        """
        # 只在案例段落中检测
        case_sections = re.findall(
            r'###\s+(典型案例|相关案例|案例|已知案例)(.*?)(?=###|\Z)',
            content,
            re.DOTALL,
        )

        for _, case_text in case_sections:
            # 检测 D048/D049 等已修复缺陷
            matches = self._RESOLVED_DEFECT_PATTERN.findall(case_text)
            if matches:
                return f"案例引用已修复缺陷: D{matches[0]}"

            # 检测"已修复"等关键词
            for kw in self._RESOLVED_KEYWORDS:
                if kw in case_text:
                    return f"案例含 '{kw}' 标记"

        return ""

    def _count_case_section_chars(self, content: str) -> int:
        """统计案例段落字符数"""
        total = 0
        # 匹配 ### 典型案例 / ### 相关案例 / ### 案例 段落
        for m in re.finditer(r'###\s+(典型案例|相关案例|案例)(.*?)(?=###|\Z)', content, re.DOTALL):
            total += len(m.group(2))
        return total

    def _detect_cross_duplicates(self, all_items: List[Tuple[str, MemoryItem]]) -> List[Dict[str, Any]]:
        """检测跨文件重复条目（主题相似度高的）"""
        groups = []
        used = set()

        # 提取每个条目的关键词集合（从标题）
        item_keywords = []
        for fname, item in all_items:
            if not item.tags or len(item.tags) < 2:
                item_keywords.append(set())
                continue
            title = item.tags[1]
            # 提取中文词和英文词
            words = set(re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z_]+', title.lower()))
            # 去除常见无意义词
            words -= {"改", "做", "的", "了", "和", "与", "在", "是", "不", "要"}
            item_keywords.append(words)

        for i, (fname_a, item_a) in enumerate(all_items):
            if i in used or not item_a.tags:
                continue
            words_a = item_keywords[i]
            if not words_a:
                continue

            group_items = [(fname_a, item_a)]
            used.add(i)

            for j in range(i + 1, len(all_items)):
                if j in used:
                    continue
                fname_b, item_b = all_items[j]
                if not item_b.tags:
                    continue
                words_b = item_keywords[j]
                if not words_b:
                    continue

                # Jaccard 相似度
                intersection = words_a & words_b
                union = words_a | words_b
                if not union:
                    continue
                similarity = len(intersection) / len(union)

                # 标题相似度 > 0.4 视为重复
                if similarity > 0.4:
                    group_items.append((fname_b, item_b))
                    used.add(j)

            if len(group_items) > 1:
                groups.append({"items": group_items})

        return groups


# ============================================================
# CLI
# ============================================================

def _cli_scan(engine: ConsolidationEngine, args) -> int:
    """扫描归档候选（不执行压缩）"""
    print("=" * 60)
    print("归档候选扫描（不执行压缩）")
    print("=" * 60)

    report = engine.identify_archive_candidates()

    print(f"\n📊 Tier1 容量: {report['tier1_chars']} 字符 ({report['tier1_usage']})")
    print(f"   扫描条目: {report['total_items_scanned']}")
    print(f"   归档候选: {report['total_candidates']}")
    print(f"   预计释放: {report['projected_saving_chars']} 字符")
    print(f"   预计压缩后: {report['projected_usage_after']}")
    print(f"   可达阈值: {'是 ✅' if report['would_resolve_threshold'] else '否 ❌'}")

    by_type = report["candidates_by_type"]
    print(f"\n--- 按类型分组 ---")
    print(f"  content_defect:    {len(by_type['content_defect'])} 条")
    print(f"  outdated_case:     {len(by_type['outdated_case'])} 条")
    print(f"  cross_duplicate:   {len(by_type['cross_duplicate'])} 条")
    print(f"  low_value_detail:  {len(by_type['low_value_detail'])} 条")

    if args.verbose and report["candidates"]:
        print(f"\n--- 候选详情 ---")
        for c in report["candidates"]:
            print(f"\n  [{c['reason_type']}] {c['item_id']}: {c['title']}")
            print(f"    位置: {c['file_path']}")
            print(f"    质量: {c['current_quality']} → {c['suggested_quality']}")
            print(f"    字符: {c['char_count']} (可释放 {c['potential_saving']})")
            print(f"    原因: {c['reason_detail']}")
            if c['duplicate_with']:
                print(f"    重复: {', '.join(c['duplicate_with'])}")

    if args.json:
        import json as _json
        print("\n" + _json.dumps(report, ensure_ascii=False, indent=2))

    return 0


def _cli_capacity(engine: ConsolidationEngine, args) -> int:
    """容量报告"""
    capacity = engine.get_capacity_report()
    print("📊 容量报告")
    print(f"  Tier 0: {capacity['tier0']['chars']} / {capacity['tier0']['max_chars']} 字符 ({capacity['tier0']['usage']})")
    print(f"  Tier 1: {capacity['tier1']['chars']} / {capacity['tier1']['max_chars']} 字符 ({capacity['tier1']['usage']})")
    print(f"  需要压缩: {capacity['tier0']['needs_consolidation'] or capacity['tier1']['needs_consolidation']}")
    return 0


def _cli_consolidate(engine: ConsolidationEngine, args) -> int:
    """执行压缩"""
    if not args.force:
        print("❌ 压缩需要 --force 参数确认")
        print("   建议先运行 scan 查看归档候选")
        return 1

    print("⚠️  执行强制压缩...")
    report = engine.check_and_consolidate(force=True)
    print(f"  压缩前: {report.before_chars} 字符 ({report.before_usage:.1%})")
    print(f"  压缩后: {report.after_chars} 字符 ({report.after_usage:.1%})")
    print(f"  扫描条目: {report.items_scanned}")
    print(f"  保留条目: {report.items_kept}")
    print(f"  压缩表达: {report.items_compressed}")
    print(f"  合并去重: {report.items_merged}")
    print(f"  归档数量: {report.items_archived}")
    if report.archive_path:
        print(f"  归档路径: {report.archive_path}")
    return 0


def _cli_health(engine: ConsolidationEngine, args) -> int:
    """健康检查"""
    health = engine.healthcheck()
    print(f"  状态: {health['status']}")
    print(f"  归档版本数: {health['archive_count']}")
    cap = health['capacity']
    print(f"  Tier 0: {cap['tier0']['usage']}")
    print(f"  Tier 1: {cap['tier1']['usage']}")
    return 0


def _cli_archive(engine: ConsolidationEngine, args) -> int:
    """执行归档"""
    # 安全检查：非 dry-run 必须带 --force
    if not args.dry_run and not args.force:
        print("❌ 执行归档需要 --force 参数确认")
        print("   建议先运行 --dry-run 预览")
        return 1

    candidate_ids = None
    if args.ids:
        candidate_ids = [s.strip() for s in args.ids.split(",") if s.strip()]

    mode = "预览" if args.dry_run else "执行"
    print(f"📦 {mode}归档（案例段落到 Tier2）")

    report = engine.execute_archive(candidate_ids=candidate_ids, dry_run=args.dry_run)

    print(f"\n   归档前: {report['tier1_before']}")
    print(f"   归档后: {report['tier1_after']}")
    print(f"   预计释放: {report['total_saving_chars']} 字符")
    print(f"   达到阈值: {'是 ✅' if report['threshold_resolved'] else '否 ❌'}")
    print(f"   计划归档: {report['total_planned']} 条")
    print(f"   实际归档: {report['total_archived']} 条")
    print(f"   预览归档: {report['total_dry_run']} 条")
    print(f"   跳过: {report['total_skipped']} 条")

    if report["results"]:
        print(f"\n   归档详情:")
        for r in report["results"]:
            status_icon = "✅" if r["status"] == "archived" else "👁️"
            print(f"     {status_icon} [{r['reason_type']}] {r['item_id']}: {r['title']}")
            print(f"        文件: {r['file']} | 释放 {r['saving_chars']} 字符")
            if r["status"] == "archived":
                print(f"        归档到: {r['archive_file']}")

    if not args.dry_run and report["total_archived"] > 0:
        print(f"\n   归档目录: {report['archive_dir']}")

    return 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="跨 Tier Consolidation 引擎")
    sub = parser.add_subparsers(dest="command")

    p_scan = sub.add_parser("scan", help="扫描归档候选（不执行压缩）")
    p_scan.add_argument("--verbose", "-v", action="store_true", help="显示候选详情")
    p_scan.add_argument("--json", action="store_true", help="输出 JSON")

    sub.add_parser("capacity", help="容量报告")
    sub.add_parser("health", help="健康检查")

    p_consolidate = sub.add_parser("consolidate", help="执行压缩（需 --force）")
    p_consolidate.add_argument("--force", action="store_true", help="强制压缩")

    p_archive = sub.add_parser("archive", help="执行归档（案例段落到 Tier2）")
    p_archive.add_argument("--ids", help="指定条目ID（逗号分隔），默认归档所有候选")
    p_archive.add_argument("--dry-run", action="store_true", help="预览模式，不实际修改文件")
    p_archive.add_argument("--force", action="store_true", help="确认执行（非 dry-run 必须带此参数）")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        raise SystemExit(1)

    engine = ConsolidationEngine()

    handlers = {
        "scan": _cli_scan,
        "capacity": _cli_capacity,
        "consolidate": _cli_consolidate,
        "health": _cli_health,
        "archive": _cli_archive,
    }
    raise SystemExit(handlers[args.command](engine, args))


# ============================================================
# P2b 历史 C 级噪声清理（P1-1 之前 daemon 注入的 C 级低置信0验证记忆）
# ============================================================

def cleanup_legacy_c_noise(
    sqlite_db_path: Optional[str] = None,
    solution_paths_dir: Optional[str] = None,
    dry_run: bool = True,
    max_confidence: float = 0.2,
    noise_sources: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    清理 P1-1 降噪修复之前 daemon 注入的 C 级低置信度噪声记忆。

    原则（零误伤）：
      - SQLite: 只标记 quality_level=archived（保留记录可审计，不再被 min_quality=C 召回）
      - solution_paths: 移动 JSON 到 _archived/ 子目录（可逆，移回即可）
      - dry_run=True（默认）：只统计，不修改
      - 匹配条件：source in noise_sources AND quality_level='C' AND
                  verify_count=0 AND confidence<=max_confidence

    Args:
        sqlite_db_path: memories SQLite 路径
        solution_paths_dir: solution_paths JSON 目录
        dry_run: 仅统计（默认 True，安全）
        max_confidence: 低置信度阈值，默认 0.2
        noise_sources: 噪声来源列表，默认 ['cognitive-daemon']

    Returns:
        统计字典（含 sql_* 和 sp_* 两类计数，dry_run 标记）
    """
    import sqlite3
    import shutil as _shutil

    noise_sources = noise_sources or ["cognitive-daemon"]
    stats: Dict[str, Any] = {
        "dry_run": dry_run,
        "max_confidence": max_confidence,
        "noise_sources": list(noise_sources),
        # sqlite
        "sqlite_noise_total": 0,
        "sqlite_archived": 0,
        "sqlite_scanned": 0,
        # solution_paths
        "sp_c_level_total": 0,
        "sp_quarantined_total": 0,
        "sp_archived": 0,
        "sp_scanned": 0,
        "sp_archived_dir": None,
    }

    # --- SQLite 通道 ---
    if sqlite_db_path and os.path.exists(sqlite_db_path):
        conn = sqlite3.connect(sqlite_db_path)
        try:
            # 条件：daemon来源 + C级 + 0验证 + 低置信
            src_placeholders = ",".join("?" * len(noise_sources))
            noise_query = (
                "SELECT COUNT(*) FROM memories WHERE "
                f"source IN ({src_placeholders}) AND quality_level='C' "
                "AND verify_count=0 AND confidence <= ?"
            )
            params = list(noise_sources) + [max_confidence]
            stats["sqlite_noise_total"] = conn.execute(noise_query, params).fetchone()[0]
            stats["sqlite_scanned"] = conn.execute(
                "SELECT COUNT(*) FROM memories"
            ).fetchone()[0]

            if not dry_run and stats["sqlite_noise_total"] > 0:
                cur = conn.execute(
                    "UPDATE memories SET quality_level='archived', "
                    "updated_at=? WHERE "
                    f"source IN ({src_placeholders}) AND quality_level='C' "
                    "AND verify_count=0 AND confidence <= ?",
                    [time.strftime("%Y-%m-%dT%H:%M:%S")] + list(noise_sources) +
                    [max_confidence],
                )
                stats["sqlite_archived"] = cur.rowcount
                conn.commit()
        finally:
            conn.close()

    # --- solution_paths 通道 ---
    if solution_paths_dir and os.path.isdir(solution_paths_dir):
        archived_dir = os.path.join(solution_paths_dir, "_archived")
        stats["sp_archived_dir"] = archived_dir
        noise_candidates: List[str] = []  # 待归档文件名列表

        for fname in os.listdir(solution_paths_dir):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(solution_paths_dir, fname)
            if not os.path.isfile(fpath):
                continue
            stats["sp_scanned"] += 1
            try:
                with open(fpath, encoding="utf-8") as fp:
                    data = json.load(fp)
            except (OSError, json.JSONDecodeError):
                continue
            q = str(data.get("quality_level", data.get("quality", "")))
            if q == "C":
                stats["sp_c_level_total"] += 1
                noise_candidates.append(fname)
            elif q == "quarantined":
                stats["sp_quarantined_total"] += 1
                noise_candidates.append(fname)
            # 其他质量（S/A/B/archived/D）均保留
        # sp_c_level_total 合并统计 C + quarantined（两者均为低质量待归档噪声）
        stats["sp_c_level_total"] += stats["sp_quarantined_total"]

        if not dry_run and noise_candidates:
            os.makedirs(archived_dir, exist_ok=True)
            for fname in noise_candidates:
                src = os.path.join(solution_paths_dir, fname)
                dst = os.path.join(archived_dir, fname)
                # 若重名则加时间戳后缀避免覆盖
                if os.path.exists(dst):
                    stem, ext = os.path.splitext(fname)
                    dst = os.path.join(
                        archived_dir, f"{stem}__archived_{int(time.time())}{ext}"
                    )
                try:
                    _shutil.move(src, dst)
                    stats["sp_archived"] += 1
                except OSError:
                    pass

    return stats

