"""
chunker.py — 语义分块器
=======================
SPEC-41-文件索引系统 v0.6 §2.2（v0.5 闭环 A2，三级兜底策略）
分块边界优先级：
  1. 标题层级（首选）：markdown 标题（#/##/###）作为块边界
  2. 空行段落（次选）：无标题文档按连续空行分隔的段落切分
  3. 固定行数窗口（兜底）：无结构文本按 256 行窗口切分，窗口间重叠 16 行
代码文件分块：按函数/类定义行切分（def/class/function/export/const xxx = (）；
  单块超过 512 行时再按 256 行窗口二次切分。
禁止固定 token 长度机械切分（中信建投 15 万文档规模验证经验，SPEC §7.7）。
位置: 41-文件索引系统/core/chunker.py
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

# markdown 标题行（#/##/###...，允许至多 3 空格缩进）
_HEADING_RE = re.compile(r"^ {0,3}(#{1,6})\s+(.+)$")

# 代码定义行（函数/类/导出，SPEC §2.2）
_CODE_DEF_RE = re.compile(
    r"^\s*"
    r"(?:def\s+\w+"                      # Python def
    r"|class\s+\w+"                      # Python/JS class
    r"|function\s+\w+"                   # JS function
    r"|export\s+"                        # JS export
    r"|const\s+\w+\s*=\s*\("           # const xxx = (
    r")"
)

# 代码文件扩展名
CODE_EXTS = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".sh", ".java", ".c", ".cpp"}

# 窗口参数（SPEC §2.2）
WINDOW_LINES = 256      # 兜底窗口行数
WINDOW_OVERLAP = 16    # 窗口重叠行数
MAX_CODE_CHUNK = 512   # 代码单块上限，超过二次切分


@dataclass(frozen=True)
class Chunk:
    """语义分块结果（chunks 表行，boundary_kind 对齐 SPEC §4.1）。"""
    heading: str                 # 所属标题（可空串）
    position: int                # 块序号（从 0 起）
    boundary_kind: str          # heading / paragraph / window / code
    content: str                 # 块原文


class Chunker:
    """语义分块器。

    用法::
        chunker = Chunker()
        chunks = chunker.chunk(Path("doc.md"))
    """

    def chunk(self, path: Path, text: Optional[str] = None) -> List[Chunk]:
        """对单个文件分块。text 为 None 时从 path 读取。"""
        if text is None:
            text = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix.lower() in CODE_EXTS:
            return self._chunk_code(text)
        lines = text.splitlines()
        if any(_HEADING_RE.match(l) for l in lines):
            return self._chunk_by_heading(text)
        if self._has_paragraphs(text):
            return self._chunk_by_paragraph(text)
        return self._chunk_by_window(lines)

    # ---------- 一级：标题层级 ----------

    def _chunk_by_heading(self, text: str) -> List[Chunk]:
        chunks: List[Chunk] = []
        current_heading = ""
        buf: List[str] = []

        def flush() -> None:
            content = "\n".join(buf).strip()
            if content:
                chunks.append(Chunk(
                    heading=current_heading,
                    position=len(chunks),
                    boundary_kind="heading",
                    content=content,
                ))
            buf.clear()

        for line in text.splitlines():
            m = _HEADING_RE.match(line)
            if m:
                flush()
                current_heading = m.group(2).strip()
                buf.append(line)
            else:
                buf.append(line)
        flush()
        return chunks

    # ---------- 二级：空行段落 ----------

    @staticmethod
    def _has_paragraphs(text: str) -> bool:
        """存在连续空行分隔的段落（≥2 段且非全空行）。"""
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        return len(paragraphs) >= 2

    def _chunk_by_paragraph(self, text: str) -> List[Chunk]:
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        return [
            Chunk(heading="", position=i, boundary_kind="paragraph", content=p)
            for i, p in enumerate(paragraphs)
        ]

    # ---------- 三级：固定行数窗口（兜底） ----------

    def _chunk_by_window(self, lines: List[str]) -> List[Chunk]:
        if not lines:
            return []
        chunks: List[Chunk] = []
        start = 0
        while start < len(lines):
            end = min(start + WINDOW_LINES, len(lines))
            chunks.append(Chunk(
                heading="",
                position=len(chunks),
                boundary_kind="window",
                content="\n".join(lines[start:end]),
            ))
            if end >= len(lines):
                break
            start = end - WINDOW_OVERLAP  # 窗口重叠 16 行，保证跨窗口语义连续
        return chunks

    # ---------- 代码分块（SPEC §2.2） ----------

    def _chunk_code(self, text: str) -> List[Chunk]:
        lines = text.splitlines()
        chunks: List[Chunk] = []
        buf: List[str] = []

        def flush() -> None:
            content = "\n".join(buf)
            if content.strip():
                if len(buf) > MAX_CODE_CHUNK:  # 超 512 行二次切分
                    for w in self._chunk_by_window(buf):
                        chunks.append(Chunk(
                            heading="",
                            position=len(chunks),
                            boundary_kind="code",
                            content=w.content,
                        ))
                else:
                    chunks.append(Chunk(
                        heading="",
                        position=len(chunks),
                        boundary_kind="code",
                        content=content,
                    ))
            buf.clear()

        for line in lines:
            if _CODE_DEF_RE.match(line) and buf:
                flush()
            buf.append(line)
        flush()
        return chunks
