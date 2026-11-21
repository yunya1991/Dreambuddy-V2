"""确定性文本证据：实体识别、分词、双语与跨字段重复词。

设计约束：不联网、不调用模型、同一输入多次运行结果完全一致。
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Mapping

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
ASCII_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_\-]{1,}")
TOKEN_SPLIT_RE = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff]+")

ASCII_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "you",
    "your",
    "use",
    "using",
    "api",
    "json",
    "skill",
    "data",
}
CJK_STOPWORDS = {
    "用户",
    "使用",
    "支持",
    "可以",
    "当前",
    "一个",
    "我们",
    "你的",
    "这个",
    "如果",
    "以及",
    "进行",
    "通过",
    "相关",
    "需要",
    "提供",
    "输出",
    "查询",
    "数据",
}


def as_text(value: object) -> str:
    """把 list / None / 标量统一成可分析的文本。"""
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return " ".join(as_text(item) for item in value)
    if isinstance(value, Mapping):
        return " ".join("{} {}".format(key, as_text(item)) for key, item in value.items())
    return str(value)


def count_cjk(text: str) -> int:
    return len(CJK_RE.findall(text or ""))


def ascii_tokens(text: str) -> List[str]:
    return [token.lower() for token in ASCII_WORD_RE.findall(text or "")]


def match_entities(text: str, lexicon: Mapping[str, Iterable[str]]) -> List[str]:
    """返回文本命中的实体词（去重、保持词表顺序）。"""
    content = text or ""
    lowered = content.lower()
    matched: List[str] = []
    for terms in (lexicon or {}).values():
        for term in terms or []:
            term_text = str(term)
            if term_text in matched:
                continue
            if CJK_RE.search(term_text):
                if term_text in content:
                    matched.append(term_text)
                continue
            # 纯 ASCII 实体（代码、表单、指标）按词边界匹配，避免 NVDA 命中 ANVDA
            pattern = r"(?<![0-9A-Za-z]){}(?![0-9A-Za-z])".format(re.escape(term_text.lower()))
            if re.search(pattern, lowered):
                matched.append(term_text)
    return matched


def bilingual_counts(tags: object) -> Dict[str, int]:
    text = as_text(tags)
    cjk = list(CJK_RE.findall(text))
    words = [word for word in ascii_tokens(text) if word not in ASCII_STOPWORDS]
    return {"cjk_chars": len(cjk), "ascii_words": len(words)}


def cjk_vocabulary(lexicon: Mapping[str, Iterable[str]] | None) -> List[str]:
    """把实体词表里的中文词摊平成去重词表（用于按词比对，而不是按字滑窗）。"""
    terms: List[str] = []
    for values in (lexicon or {}).values():
        for term in values or []:
            text = str(term)
            if CJK_RE.search(text) and text not in terms:
                terms.append(text)
    return terms


def _terms(text: str, vocabulary: Iterable[str] | None = None) -> List[str]:
    """英文按词；中文优先按给定词表整词匹配，无词表时回退 2 字滑窗。"""
    content = text or ""
    terms: List[str] = []
    for word in ascii_tokens(content):
        if len(word) < 3 or word in ASCII_STOPWORDS or word.isdigit():
            continue
        terms.append(word)
    vocab = [str(item) for item in (vocabulary or []) if item]
    if vocab:
        # 只认词表内的整词，避免把「据服」「件上」这类跨词碎片算成重复词
        for term in vocab:
            if term in content:
                terms.append(term)
        return terms
    cleaned = TOKEN_SPLIT_RE.sub(" ", content)
    for chunk in cleaned.split():
        if not CJK_RE.search(chunk):
            continue
        if len(chunk) == 2:
            if chunk not in CJK_STOPWORDS:
                terms.append(chunk)
            continue
        for index in range(len(chunk) - 1):
            gram = chunk[index : index + 2]
            if gram in CJK_STOPWORDS or all(char.isdigit() for char in gram):
                continue
            if CJK_RE.search(gram):
                terms.append(gram)
    return terms


def shared_terms(
    fields: Mapping[str, object],
    whitelist: Iterable[str] | None = None,
    lexicon: Mapping[str, Iterable[str]] | None = None,
) -> List[Dict[str, object]]:
    """跨字段重复词：返回 [{term, fields}]，按字段数降序、词字典序。

    给定 lexicon 时中文只按整词比对，避免 2 字滑窗把跨词碎片误判为重复词。
    """
    allowed = {str(item).lower() for item in (whitelist or [])}
    vocabulary = cjk_vocabulary(lexicon)
    owners: Dict[str, List[str]] = {}
    for name, value in fields.items():
        seen = set()
        for term in _terms(as_text(value), vocabulary):
            if term in allowed or term in seen:
                continue
            seen.add(term)
            owners.setdefault(term, []).append(name)
    duplicated = [
        {"term": term, "fields": sorted(names)} for term, names in owners.items() if len(names) >= 2
    ]
    duplicated.sort(key=lambda item: (-len(item["fields"]), item["term"]))
    return duplicated


def name_tokens(name: str) -> List[str]:
    """工具名切词：a_share_quote → a / share / quote，过滤 a / the 等虚词。"""
    return [
        token
        for token in re.split(r"[^0-9A-Za-z]+", name or "")
        if token and token.lower() not in {"a", "an", "the", "of", "for", "to"}
    ]
