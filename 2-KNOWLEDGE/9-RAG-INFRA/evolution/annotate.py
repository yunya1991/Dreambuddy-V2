# -*- coding: utf-8 -*-
"""自动标注（阶段3·持续进化）：对检索分块自动补充元数据标注。

标注内容：
- 域分类：从 source_file 路径推断所属域；
- 标签抽取：从内容中提取 # 开头的内联标签；
- 质量评分：完整性 + 准确性 + 时效性（各 0~1，取均值）。
"""

import re
from typing import Dict, List

# 内联标签正则（与 chunker 一致）
_TAG_RE = re.compile(r"(?<![#\w])#([A-Za-z0-9_\u4e00-\u9fa5][\w\u4e00-\u9fa5\-]*)")
# 日期模式（2020-2026 年份）
_DATE_RE = re.compile(r"20[2-3]\d")
# 数字/参数模式
_PARAM_RE = re.compile(r"\d+\.?\d*")


def _classify_domain(source_file: str) -> str:
    """从 source_file 路径推断所属域（第一级目录名）。"""
    if not source_file:
        return "root"
    parts = source_file.replace("\\", "/").split("/")
    if len(parts) > 1:
        return parts[0]
    return "root"


def _extract_tags(content: str) -> List[str]:
    """从内容中提取 # 开头的内联标签（去重，保持顺序）。"""
    seen = set()
    tags: List[str] = []
    for m in _TAG_RE.findall(content):
        key = m.lower()
        if key not in seen:
            seen.add(key)
            tags.append(m)
    return tags


def _completeness(content: str, heading: str) -> float:
    """完整性评分：基于内容长度与标题存在性。

    - 有标题且内容充实（≥200 字符）：1.0
    - 有标题且内容适中（≥50 字符）：0.7
    - 有内容但较短：0.4
    - 内容极少：0.2
    """
    length = len(content.strip())
    if heading and length >= 200:
        return 1.0
    elif heading and length >= 50:
        return 0.7
    elif length >= 20:
        return 0.4
    else:
        return 0.2


def _accuracy(content: str) -> float:
    """准确性评分：基于内容中数值/参数与引用的丰富度。

    - 含数值参数 + URL/引用：1.0
    - 含数值参数或 URL：0.8
    - 纯文本但结构完整：0.6
    - 内容稀疏：0.4
    """
    has_numbers = bool(_PARAM_RE.search(content))
    has_url = "http" in content or "https" in content
    has_table = "|" in content and "-" in content

    if has_numbers and (has_url or has_table):
        return 1.0
    elif has_numbers or has_url or has_table:
        return 0.8
    elif len(content.strip()) >= 50:
        return 0.6
    else:
        return 0.4


def _timeliness(content: str) -> float:
    """时效性评分：基于内容中是否包含近期日期。

    - 含 2024-2026 日期：1.0
    - 含 2020-2023 日期：0.7
    - 无日期：0.5
    """
    dates = _DATE_RE.findall(content)
    if not dates:
        return 0.5
    recent = [d for d in dates if int(d) >= 2024]
    if recent:
        return 1.0
    return 0.7


def _quality_score(content: str, heading: str) -> Dict[str, float]:
    """计算质量评分：完整性 + 准确性 + 时效性。"""
    completeness = _completeness(content, heading)
    accuracy = _accuracy(content)
    timeliness = _timeliness(content)
    overall = round((completeness + accuracy + timeliness) / 3, 4)
    return {
        "completeness": round(completeness, 4),
        "accuracy": round(accuracy, 4),
        "timeliness": round(timeliness, 4),
        "overall": overall,
    }


def annotate_chunk(chunk: Dict) -> Dict:
    """对检索分块自动补充标注信息。

    Args:
        chunk: 分块字典，应含 content / source_file 等字段。

    Returns:
        补充了 annotation 字段的 chunk 字典，包含：
        - domain: 推断的域
        - tags: 提取的标签列表
        - quality: 质量评分（completeness / accuracy / timeliness / overall）
    """
    content = chunk.get("content", "")
    source_file = chunk.get("source_file", "")
    heading = chunk.get("heading", "")

    # 域分类：优先使用已有 domain，否则从路径推断
    domain = chunk.get("domain", "")
    if not domain or domain == "root":
        domain = _classify_domain(source_file)

    # 标签抽取
    tags = _extract_tags(content)

    # 质量评分
    quality = _quality_score(content, heading)

    chunk["annotation"] = {
        "domain": domain,
        "tags": tags,
        "quality": quality,
    }
    return chunk
