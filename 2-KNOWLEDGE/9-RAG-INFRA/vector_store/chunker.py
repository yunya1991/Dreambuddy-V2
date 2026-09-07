# -*- coding: utf-8 -*-
"""语义分块器：将 Markdown 文档按标题层级切分为语义块。

分块规则：
- 按一级/二级/三级标题（#/##/###）划分区块；
- 代码块（``` ... ```）与表格（| ... |）整块保留，不拆分；
- 普通段落超过 MAX_CHUNK_TOKENS 时按句号（。！？\n）切分；
- 每个块附带元数据：source_file / domain / chunk_type / heading /
  heading_level / position / tags；
- tags 从块内容中提取以 # 开头的内联标签（不与标题混淆）。
"""

import re
from typing import Dict, List

try:
    from .config import MAX_CHUNK_TOKENS
except ImportError:  # 直接以脚本运行时
    from config import MAX_CHUNK_TOKENS

# 标题行：^#{1,6} 空格 标题文本
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
# 代码围栏起始：``` 或 ```lang
_CODE_FENCE_RE = re.compile(r"^```")
# 表格行起始：以 | 开头
_TABLE_RE = re.compile(r"^\|")
# 内联标签：# 紧跟非空白词字符，且 # 前面不是 # 或词字符（排除标题/井号连写）
_TAG_RE = re.compile(r"(?<![#\w])#([A-Za-z0-9_\u4e00-\u9fa5][\w\u4e00-\u9fa5\-]*)")
# 中文+ASCII 词 token（中文按字、英文/数字按连续串，用于 token 估算与 TF-IDF 回退分词）
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[\u4e00-\u9fa5]")


def _estimate_tokens(text: str) -> int:
    """粗略估算 token 数：中文字符按 1 计，英文/数字连续串按 1 计。"""
    return len(_TOKEN_RE.findall(text))


def _extract_tags(text: str) -> List[str]:
    """从文本中提取 # 开头的内联标签（去重，保持顺序）。"""
    seen = set()
    tags: List[str] = []
    for m in _TAG_RE.findall(text):
        key = m.lower()
        if key not in seen:
            seen.add(key)
            tags.append(m)
    return tags


def _split_long_text(text: str, max_tokens: int = MAX_CHUNK_TOKENS) -> List[str]:
    """将超长文本按句号切分，尽量使每块不超过 max_tokens。"""
    if _estimate_tokens(text) <= max_tokens:
        return [text] if text.strip() else []
    # 按中文句末标点或换行切分
    parts = re.split(r"(?<=[。！？\n])", text)
    chunks: List[str] = []
    buf = ""
    for part in parts:
        if not part.strip():
            continue
        if _estimate_tokens(buf + part) > max_tokens and buf.strip():
            chunks.append(buf.strip())
            buf = part
        else:
            buf += part
        # 单句仍超长，按 token 硬切
        while _estimate_tokens(buf) > max_tokens:
            tokens = _TOKEN_RE.findall(buf)
            cut_tokens = tokens[:max_tokens]
            # 用原文本前缀匹配硬切长度
            cut_len = 0
            count = 0
            for mt in _TOKEN_RE.finditer(buf):
                if count >= len(cut_tokens):
                    break
                cut_len = mt.end()
                count += 1
            chunks.append(buf[:cut_len].strip())
            buf = buf[cut_len:]
    if buf.strip():
        chunks.append(buf.strip())
    return [c for c in chunks if c]


def _make_chunk(content: str, source_file: str, domain: str,
                chunk_type: str, heading: str, heading_level: int,
                position: int) -> Dict:
    """构造单个分块字典（含元数据与 tags）。"""
    return {
        "content": content,
        "metadata": {
            "source_file": source_file,
            "domain": domain,
            "chunk_type": chunk_type,
            "heading": heading,
            "heading_level": heading_level,
            "position": position,
            "tags": _extract_tags(content),
        },
    }


def chunk_markdown(text: str, source_file: str, domain: str) -> List[Dict]:
    """将 Markdown 文本切分为带元数据的语义块列表。

    Args:
        text: Markdown 原文。
        source_file: 源文件相对路径（相对知识库根目录）。
        domain: 所属域（如 1-TRADING）。

    Returns:
        分块字典列表，每项含 content 与 metadata。
    """
    chunks: List[Dict] = []
    lines = text.split("\n")
    i = 0
    position = 0
    heading = ""
    heading_level = 0
    para_buf: List[str] = []

    def flush_para() -> None:
        nonlocal position, para_buf
        if not para_buf:
            return
        content = "\n".join(para_buf).strip()
        para_buf = []
        if not content:
            return
        for sub in _split_long_text(content, MAX_CHUNK_TOKENS):
            chunks.append(_make_chunk(sub, source_file, domain, "text",
                                      heading, heading_level, position))
            position += 1

    while i < len(lines):
        line = lines[i]
        m = _HEADING_RE.match(line)
        if m:
            flush_para()
            heading_level = len(m.group(1))
            heading = m.group(2).strip()
            i += 1
            continue
        # 代码块：整块保留
        if _CODE_FENCE_RE.match(line.strip()):
            flush_para()
            code_lines = [line]
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            if i < len(lines):
                code_lines.append(lines[i])  # 闭合围栏
                i += 1
            content = "\n".join(code_lines).strip()
            chunks.append(_make_chunk(content, source_file, domain, "code",
                                      heading, heading_level, position))
            position += 1
            continue
        # 表格：连续 | 行整块保留
        if _TABLE_RE.match(line.strip()):
            flush_para()
            table_lines = [line]
            i += 1
            while i < len(lines) and _TABLE_RE.match(lines[i].strip()):
                table_lines.append(lines[i])
                i += 1
            content = "\n".join(table_lines).strip()
            chunks.append(_make_chunk(content, source_file, domain, "table",
                                      heading, heading_level, position))
            position += 1
            continue
        # 空行作为段落边界
        if line.strip() == "":
            flush_para()
            i += 1
            continue
        # 普通文本行
        para_buf.append(line)
        i += 1

    flush_para()
    return chunks
