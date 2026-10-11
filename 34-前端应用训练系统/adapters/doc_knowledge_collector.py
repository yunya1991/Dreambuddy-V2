"""文档知识库采集器。

解析 0-系统文档管理/INDEX.md 中的文档索引表格，
实现 TrainingDataProvider 协议，为主动训练采集器提供背景知识数据。

设计:
  - 解析 INDEX.md markdown 表格（无 IPC 开销）
  - 质量门控: 文档条目直接采集（结构化数据）
  - 增量采集: 基于 INDEX.md 文件修改时间（mtime）
  - FAIL-OPEN: 文件不存在或解析失败时返回空列表

字段映射 (SPEC §2.2: domain_knowledge → G层, knowledge_context → LLM层):
  - 文档名 → intent
  - 职责/描述 → outcome_text + learned
  - 路径 → metadata["path"]
  - 分节标题 → metadata["section"]
  - layer_tags = ["G", "LLM"] (背景知识层 + LLM上下文层)
  - quality = "B"
  - source = "doc"
"""
import os
import re
import sys
from typing import List, Optional

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_34_DIR = os.path.dirname(_THIS_DIR)
_PROJECT_ROOT = os.path.dirname(_34_DIR)

from interfaces.training_data_provider import TrainingDataProvider, TrainingCase

# 默认 INDEX.md 路径
_DEFAULT_INDEX_PATH = os.path.join(
    _PROJECT_ROOT, "0-系统文档管理", "INDEX.md"
)


class DocKnowledgeCollector(TrainingDataProvider):
    """文档知识库采集器。

    从 INDEX.md 解析文档索引表格，转换为 TrainingCase。
    domain_knowledge 作为 G 层背景，knowledge_context 作为 LLM 层上下文。
    """

    def __init__(self, index_path: str = "", quality_threshold: str = "B"):
        self._index_path = index_path or _DEFAULT_INDEX_PATH
        self._quality_threshold = quality_threshold

    def get_source_name(self) -> str:
        return "doc"

    def get_quality_threshold(self) -> str:
        return self._quality_threshold

    def fetch_cases(
        self, limit: int = 100, since: Optional[str] = None
    ) -> List[TrainingCase]:
        """从 INDEX.md 批量获取文档知识条目。

        Args:
            limit: 最大返回数量
            since: 增量采集时间戳(ms)，如果 INDEX.md mtime <= since 则返回空

        Returns:
            训练案例列表（FAIL-OPEN：文件不可用时返回空列表）
        """
        if not os.path.exists(self._index_path):
            return []

        try:
            # 增量采集: 检查 mtime
            mtime = os.path.getmtime(self._index_path)
            mtime_ms = int(mtime * 1000)

            if since:
                since_ts = int(since)
                if mtime_ms <= since_ts:
                    return []  # 无新数据

            with open(self._index_path, "r", encoding="utf-8") as f:
                content = f.read()

            entries = self._parse_markdown_tables(content)
            return entries[:limit]
        except Exception:
            return []

    @staticmethod
    def _parse_markdown_tables(content: str) -> List[TrainingCase]:
        """解析 INDEX.md 中的 markdown 表格，提取文档条目。

        表格格式:
          | 文档 | 路径 | 职责 |
          |------|------|------|
          | 名称 | [link](path) | 描述 |
        """
        cases = []
        current_section = ""

        for line in content.split("\n"):
            line = line.strip()

            # 检测分节标题 (## L0, ## L1, etc.)
            if line.startswith("## "):
                current_section = line[3:].strip()
                continue

            # 跳过分隔行和表头
            if not line.startswith("|"):
                continue
            if "---" in line or "文档" in line and "路径" in line:
                continue

            # 解析表格行
            cells = [c.strip() for c in line.split("|")]
            # 去掉首尾空元素（split 产生的）
            cells = [c for c in cells if c]

            if len(cells) < 3:
                continue

            doc_name = cells[0]
            path_cell = cells[1]
            responsibility = cells[2]

            # 提取 markdown 链接中的路径
            link_match = re.search(r"\[([^\]]+)\]\(([^)]+)\)", path_cell)
            doc_path = link_match.group(2) if link_match else path_cell

            # 跳过表头行
            if doc_name in ("文档", "Document") or "---" in doc_name:
                continue

            cases.append(
                TrainingCase(
                    intent=doc_name,
                    actions=[],
                    outcome_text=responsibility,
                    learned=[responsibility] if responsibility else [],
                    layer_tags=["G", "LLM"],
                    quality="B",
                    confidence=0.3,
                    source="doc",
                    metadata={
                        "path": doc_path,
                        "section": current_section,
                        "status": cells[3] if len(cells) > 3 else "",
                    },
                )
            )

        return cases
