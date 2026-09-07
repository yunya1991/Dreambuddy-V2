# -*- coding: utf-8 -*-
"""调研内容检测器：从对话文本中确定性识别金融 / GitHub / 技术调研内容。

检测原则：
- 确定性：纯关键词匹配（非 LLM），相同输入恒定输出，便于回归测试；
- 三类内容：finance（传统金融）/ github（开源仓库）/ technical（技术方案）；
- 分类映射：匹配关键词 → 7-EXTERNAL-RESEARCH 目录结构的子分类。
"""

import re
from typing import Dict, List, Optional

# === 关键词 → 子分类映射（对应 7-EXTERNAL-RESEARCH 目录结构） ===

# 传统金融：WebSearch 常见关键词
FINANCE_KEYWORDS: Dict[str, List[str]] = {
    "quant-methods": ["量化", "Kalman", "PCA", "IC", "Sharpe", "回测",
                      "贝叶斯", "蒙特卡洛", "Black-Scholes", "Greeks", "定价"],
    "risk-models": ["风控", "对冲", "止损", "止盈", "仓位",
                    "波动率", "风险中性", "套利"],
    "market-structure": ["做市", "订单簿", "流动性", "资金费率", "基差",
                         "期限结构", "收益率曲线", "相关系数"],
    "trading-psychology": ["交易心理", "行为金融", "决策偏差",
                           "情绪交易", "过度自信", "损失厌恶"],
}

# 技术方案：架构 / 算法 / 测试
TECHNICAL_KEYWORDS: Dict[str, List[str]] = {
    "architecture": ["架构", "设计模式", "微服务", "消息队列", "缓存策略",
                     "RAG", "知识图谱", "Fail-Open", "Shadow模式"],
    "algorithms": ["算法", "分块", "索引", "检索", "排序", "过滤",
                   "分词", "向量化", "embedding"],
    "testing": ["TDD", "单元测试", "集成测试", "回归测试",
                "测试覆盖", "mock", "fixture"],
}

# GitHub 仓库名关键词 → 子分类推断
GITHUB_REPO_KEYWORDS: Dict[str, List[str]] = {
    "ml-frameworks": ["langchain", "llama", "transformers", "pytorch",
                      "tensorflow", "scikit", "sklearn", "xgboost", "huggingface"],
    "trading-systems": ["backtrader", "vnpy", "freqtrade", "zipline",
                        "ccxt", "quantconnect"],
    "data-engineering": ["airflow", "spark", "kafka", "pandas", "polars", "duckdb"],
    "infra-tools": ["docker", "kubernetes", "k8s", "terraform", "nginx", "redis"],
}

# github.com 仓库 URL 正则
_GITHUB_URL_RE = re.compile(r"github\.com/[\w\-]+/[\w\-\.]+", re.IGNORECASE)

# 判断关键词是否含非 ASCII（中文）字符
_CJK_RE = re.compile(r"[^\x00-\x7f]")


def _has_cjk(s: str) -> bool:
    """判断字符串是否含中文等非 ASCII 字符。"""
    return bool(_CJK_RE.search(s))


def _find_pos(keyword: str, content: str) -> int:
    """返回关键词在 content 中首次出现的位置，未匹配返回 -1。

    中文关键词：子串匹配；英文关键词：两侧不允许紧邻 ASCII 字母，
    避免 IC 命中 specification、RAG 命中 garbage 等误报，
    同时允许英文关键词后接中文（如 RAG架构、Fail-Open原则）。
    """
    if not keyword:
        return -1
    if _has_cjk(keyword):
        return content.find(keyword)
    pattern = r"(?<![A-Za-z])" + re.escape(keyword) + r"(?![A-Za-z])"
    m = re.search(pattern, content, re.IGNORECASE)
    return m.start() if m else -1


def _make_tags(keywords: List[str]) -> List[str]:
    """从匹配关键词生成 #标签（小写、空格/斜杠转连字符）。"""
    tags = []
    for kw in keywords:
        tag = "#" + kw.lower().replace(" ", "-").replace("/", "-")
        tags.append(tag)
    return tags


def _build_detection(det_type: str, category: str, subcategory: str,
                    keywords_matched: List[str], first_pos: int,
                    content: str) -> Dict:
    """构建单条检测结果字典。"""
    start = max(0, first_pos - 100)
    end = min(len(content), first_pos + 100)
    excerpt = content[start:end]
    return {
        "type": det_type,
        "category": category,
        "subcategory": subcategory,
        "suggested_path": f"{category}/{subcategory}",
        "tags": _make_tags(keywords_matched),
        "keywords_matched": keywords_matched,
        "excerpt": excerpt,
    }


def _detect_by_keyword_map(content: str, keyword_map: Dict[str, List[str]],
                          det_type: str, category: str) -> Optional[Dict]:
    """通用关键词检测：选出匹配最多的子分类，构建检测结果。

    同数匹配时按字典序保留首个（Python 3.7+ 保序，结果确定性）。
    """
    best_sub: Optional[str] = None
    best_matched: List[str] = []
    best_pos: int = -1

    for sub, keywords in keyword_map.items():
        matched: List[str] = []
        first_pos = -1
        for kw in keywords:
            pos = _find_pos(kw, content)
            if pos >= 0:
                matched.append(kw)
                if first_pos < 0 or pos < first_pos:
                    first_pos = pos
        if len(matched) > len(best_matched):
            best_sub = sub
            best_matched = matched
            best_pos = first_pos

    if best_sub is None or not best_matched:
        return None
    return _build_detection(det_type, category, best_sub, best_matched,
                           best_pos, content)


def _detect_github(content: str) -> Optional[Dict]:
    """GitHub 仓库检测：github.com URL 或 repo/仓库关键词触发，
    子分类由仓库名/内容关键词推断。"""
    url_match = _GITHUB_URL_RE.search(content)
    content_low = content.lower()

    repo_pos = -1
    if "仓库" in content:
        repo_pos = content.find("仓库")
    else:
        m = re.search(r"(?<![a-z])repo(?![a-z])", content_low)
        repo_pos = m.start() if m else -1

    if not url_match and repo_pos < 0:
        return None

    # 从 URL 提取仓库名，用于子分类推断
    repo_name = ""
    if url_match:
        repo_name = url_match.group(0).split("/")[-1].lower()

    best_sub: Optional[str] = None
    best_matched: List[str] = []
    for sub, keywords in GITHUB_REPO_KEYWORDS.items():
        matched: List[str] = []
        for kw in keywords:
            kw_low = kw.lower()
            if kw_low in content_low or kw_low in repo_name:
                matched.append(kw)
        if len(matched) > len(best_matched):
            best_sub = sub
            best_matched = matched

    if best_sub is None:
        # 无明确子分类匹配，默认归档到基础设施工具
        best_sub = "infra-tools"
        best_matched = [repo_name] if repo_name else ["github"]

    # 摘要位置：优先 URL，其次 repo/仓库
    first_pos = url_match.start() if url_match else (repo_pos if repo_pos >= 0 else 0)
    return _build_detection("github", "github", best_sub, best_matched,
                           first_pos, content)


def detect_research(content: str) -> List[Dict]:
    """检测文本中的调研内容，返回检测结果列表（每类最多一条）。

    Args:
        content: 对话文本。

    Returns:
        检测结果列表，每项含 type/category/subcategory/suggested_path/
        tags/keywords_matched/excerpt。无匹配时返回空列表。
    """
    if not content:
        return []

    results: List[Dict] = []
    fin = _detect_by_keyword_map(content, FINANCE_KEYWORDS, "finance", "finance")
    if fin:
        results.append(fin)
    git = _detect_github(content)
    if git:
        results.append(git)
    tech = _detect_by_keyword_map(content, TECHNICAL_KEYWORDS, "technical", "technical")
    if tech:
        results.append(tech)
    return results
