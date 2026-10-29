"""
tokenizer.py — 分词器
======================
SPEC-41-文件索引系统 v0.6 §2.2（v0.4 闭环 C1）
职责：
  1. 中文分词：jieba 精确模式（默认）
  2. 英文处理：空白分隔 + 驼峰拆分（camelCase / PascalCase）
  3. 归一化：全小写 / 全角半角统一 / 停用词过滤（中英文停用词表）
  4. 接口可替换：Tokenizer 协议 + HanLP 适配位预留
位置: 41-文件索引系统/core/tokenizer.py
"""
from __future__ import annotations
import re
from typing import List, Protocol

import jieba

# 全角 → 半角（ASCII 可见字符区间）
_FULLWIDTH_RE = re.compile(r"[\uff01-\uff5e]")

# 驼峰拆分：camelCase / PascalCase / snake_case 统一处理
_CAMEL_RE = re.compile(
    r"(?<=[a-z0-9])(?=[A-Z])"          # camel 边界
    r"|(?<=[A-Z])(?=[A-Z][a-z])"        # PascalCase 缩写边界（HTTPServer → HTTP/Server）
)

# 词元清理：仅保留中英文与数字
_TOKEN_RE = re.compile(r"^[\u4e00-\u9fffA-Za-z0-9_-]+$")

# 停用词表（内置中英文常用，SPEC §2.2）
STOPWORDS = {
    # 英文
    "the", "a", "an", "and", "or", "not", "is", "are", "was", "were",
    "in", "on", "at", "to", "for", "of", "with", "by", "from", "as",
    "this", "that", "these", "those", "it", "its", "be", "been", "if",
    "then", "else", "when", "what", "which", "who", "how", "why", "all",
    "any", "can", "do", "does", "did", "will", "would", "should", "may",
    # 中文
    "的", "了", "和", "是", "就", "都", "而", "与", "及", "或",
    "在", "中", "对", "为", "被", "把", "让", "从", "到", "由",
    "这", "那", "也", "还", "又", "很", "有", "无", "不", "没",
    "我们", "你们", "他们", "它们", "一个", "一些", "什么", "怎么", "如何",
}


def _to_halfwidth(text: str) -> str:
    """全角字符转半角（SPEC §2.2 归一化）。"""
    return _FULLWIDTH_RE.sub(lambda m: chr(ord(m.group(0)) - 0xFEE0), text)


def _split_english(word: str) -> List[str]:
    """英文词驼峰拆分 + snake/kebab 拆分。"""
    parts: List[str] = []
    for seg in re.split(r"[_\-]+", word):
        if not seg:
            continue
        parts.extend(s.lower() for s in _CAMEL_RE.split(seg) if s)
    return parts


class Tokenizer(Protocol):
    """分词器协议（接口可替换，预留 HanLP 适配位，SPEC §2.2）。"""

    def tokenize(self, text: str) -> List[str]: ...


class JiebaTokenizer:
    """默认分词器：jieba 精确模式 + 英文驼峰拆分 + 停用词过滤。"""

    def __init__(self, stopwords: set | None = None) -> None:
        self.stopwords = stopwords if stopwords is not None else STOPWORDS

    def tokenize(self, text: str) -> List[str]:
        if not text:
            return []
        text = _to_halfwidth(text)
        tokens: List[str] = []
        for raw in jieba.cut(text, cut_all=False):  # 精确模式
            raw = raw.strip()
            if not raw:
                continue
            # 英文/数字词：驼峰与分隔符拆分
            if re.fullmatch(r"[A-Za-z0-9_\-]+", raw):
                for sub in _split_english(raw):
                    if sub and sub not in self.stopwords and len(sub) > 1:
                        tokens.append(sub)
                continue
            # 中文词或混合词
            for seg in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", raw):
                if re.fullmatch(r"[A-Za-z0-9]+", seg):
                    for sub in _split_english(seg):
                        if sub and sub not in self.stopwords and len(sub) > 1:
                            tokens.append(sub)
                else:
                    if seg not in self.stopwords and len(seg) > 1:
                        tokens.append(seg)
        return tokens


# 进程级默认实例（jieba 词典加载一次）
_default_tokenizer: Tokenizer | None = None


def tokenize(text: str) -> List[str]:
    """模块级便捷入口（searcher/indexer 共用）。"""
    global _default_tokenizer
    if _default_tokenizer is None:
        _default_tokenizer = JiebaTokenizer()
    return _default_tokenizer.tokenize(text)
