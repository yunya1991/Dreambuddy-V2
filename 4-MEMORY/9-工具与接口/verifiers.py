"""验证器模块 — cycle_consistency / factuality / applicability。

设计原则：
- 每个验证器独立，FAIL-OPEN（异常→abstain）
- 启发式实现，不依赖 LLM 调用（零成本）
- 输出 VerificationSignal，可直接喂给 verify(signals=...)
- 可配置开关，默认全部启用

三个验证器：
1. CycleConsistencyVerifier: 检测记忆内容自相矛盾（反义词对、数值冲突）
2. FactualityVerifier: 检查事实声明可信度（版本号、数值合理性）
3. ApplicabilityVerifier: 计算记忆与 context 的关键词重叠度
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from verification_record import VerificationSignal


# ---------------------------------------------------------------------------
# BaseVerifier
# ---------------------------------------------------------------------------

class BaseVerifier:
    """验证器抽象基类。

    子类实现 _verify() 返回 verdict 字符串 ("pass"/"fail"/"abstain")。
    verify() 包装 FAIL-OPEN：空内容/异常 → abstain。
    """
    stage: str = "base"
    verifier_id: str = "base_verifier"

    def verify(self, content: str, context: Optional[str] = None, **kwargs: Any) -> VerificationSignal:
        """执行验证，返回 VerificationSignal。FAIL-OPEN。"""
        try:
            if not content or not str(content).strip():
                return VerificationSignal(
                    stage=self.stage, verdict="abstain", verifier_id=self.verifier_id,
                )
            verdict = self._verify(str(content), context=context, **kwargs)
            if verdict not in ("pass", "fail", "abstain"):
                verdict = "abstain"
            return VerificationSignal(
                stage=self.stage, verdict=verdict, verifier_id=self.verifier_id,
            )
        except Exception:
            return VerificationSignal(
                stage=self.stage, verdict="abstain", verifier_id=self.verifier_id,
            )

    def _verify(self, content: str, context: Optional[str] = None, **kwargs: Any) -> str:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# CycleConsistencyVerifier
# ---------------------------------------------------------------------------

# 反义词对（中文 + 英文），用于矛盾检测
_OPPOSITE_PAIRS = [
    ("上升", "下降"), ("上涨", "下跌"), ("增加", "减少"), ("提高", "降低"),
    ("开启", "关闭"), ("启用", "禁用"), ("应该", "不要"), ("必须", "禁止"),
    ("正确", "错误"), ("成功", "失败"), ("真", "假"), ("是", "否"),
    ("up", "down"), ("increase", "decrease"), ("enable", "disable"),
    ("true", "false"), ("yes", "no"), ("on", "off"), ("pass", "fail"),
]


class CycleConsistencyVerifier(BaseVerifier):
    """循环一致性验证器：检测内容中的自相矛盾。

    策略：
    - 内容极短（< 15 字符）→ fail（不可能是有意义的经验）
    - 内容较短（15-30 字符）→ abstain
    - 扫描反义词对，若同一对的两个词都出现 → fail
    - 否则 → pass
    """
    stage = "cycle_consistency"
    verifier_id = "cycle_consistency_v1"
    _FAIL_LENGTH = 15   # < 15 字符 → fail
    _ABSTAIN_LENGTH = 30  # 15-30 字符 → abstain

    def _verify(self, content: str, context: Optional[str] = None, **kwargs: Any) -> str:
        text = content.lower()
        length = len(content.strip())
        if length < self._FAIL_LENGTH:
            return "fail"
        if length < self._ABSTAIN_LENGTH:
            return "abstain"

        # 检测反义词对同时出现
        for word_a, word_b in _OPPOSITE_PAIRS:
            if word_a in text and word_b in text:
                return "fail"

        return "pass"


# ---------------------------------------------------------------------------
# FactualityVerifier
# ---------------------------------------------------------------------------

# 已知不合理的版本号模式
_INVALID_VERSION_PATTERNS = [
    re.compile(r"python\s+(\d+)\.(\d+)", re.IGNORECASE),
]


class FactualityVerifier(BaseVerifier):
    """事实性验证器：检查事实声明的可信度。

    策略：
    - 自动生成内容（[RAG检索] 等）→ fail（非人工 curated 经验）
    - 检测到明显不合理的数值（如 Python 版本 > 4.0）→ fail
    - 无事实声明（无数字/版本号）→ abstain
    - 否则 → pass（信任记忆来源）
    """
    stage = "factuality"
    verifier_id = "factuality_v1"

    # Python 主版本合理范围
    _PYTHON_MAJOR_MAX = 4
    _PYTHON_MINOR_MAX = 13

    # 自动生成内容前缀（非人工经验）
    _AUTO_GEN_PREFIXES = ("[RAG检索]", "[rag检索]", "[RAG]")

    def _verify(self, content: str, context: Optional[str] = None, **kwargs: Any) -> str:
        text = content.strip()

        # 自动生成的 RAG 检索片段 → 非 curated 经验 → fail
        for prefix in self._AUTO_GEN_PREFIXES:
            if text.startswith(prefix):
                return "fail"

        # 检测 Python 版本号
        py_matches = re.findall(r"python\s+(\d+)\.(\d+)", text, re.IGNORECASE)
        for major, minor in py_matches:
            major_i, minor_i = int(major), int(minor)
            if major_i > self._PYTHON_MAJOR_MAX or minor_i > self._PYTHON_MINOR_MAX:
                return "fail"

        # 检测其他不合理的大数字版本（如 99.0）
        big_version = re.findall(r"(\d{2,})\.\d+", text)
        for v in big_version:
            if int(v) > 50:
                return "fail"

        # 检查是否有事实声明（数字）
        has_factual = bool(re.search(r"\d+", text))
        if not has_factual:
            return "abstain"  # 无事实声明，无法验证

        return "pass"


# ---------------------------------------------------------------------------
# ApplicabilityVerifier
# ---------------------------------------------------------------------------

# 停用词（不参与重叠计算）
_STOPWORDS = frozenset({
    "的", "了", "是", "在", "和", "与", "或", "等", "中", "上", "下",
    "有", "无", "不", "也", "都", "就", "而", "及", "这", "那",
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "to", "of", "in", "on", "at", "by", "for", "with", "from", "as",
    "and", "or", "not", "no", "yes", "but", "if", "then", "else",
})


def _tokenize(text: str) -> List[str]:
    """分词：中文按单字切分，英文按单词切分，过滤停用词和短词。"""
    tokens: List[str] = []
    # 英文单词
    for m in re.findall(r"[a-zA-Z][a-zA-Z0-9_]*", text.lower()):
        if m not in _STOPWORDS and len(m) > 1:
            tokens.append(m)
    # 中文字符（单字）
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff":
            if ch not in _STOPWORDS:
                tokens.append(ch)
    return tokens


class ApplicabilityVerifier(BaseVerifier):
    """适用性验证器：检查记忆是否适用于当前上下文。

    策略：
    - 无 context → abstain
    - 计算记忆 token 与 context token 的重叠比例
    - 重叠比例 >= 阈值 → pass，否则 → fail
    """
    stage = "applicability"
    verifier_id = "applicability_v1"
    _THRESHOLD = 0.3  # 重叠比例阈值

    def _verify(self, content: str, context: Optional[str] = None, **kwargs: Any) -> str:
        if not context or not str(context).strip():
            return "abstain"

        content_tokens = set(_tokenize(content))
        context_tokens = set(_tokenize(context))

        if not content_tokens or not context_tokens:
            return "abstain"

        overlap = content_tokens & context_tokens
        ratio = len(overlap) / len(context_tokens) if context_tokens else 0.0

        if ratio >= self._THRESHOLD:
            return "pass"
        return "fail"


# ---------------------------------------------------------------------------
# 注册表 & 便捷函数
# ---------------------------------------------------------------------------

def get_default_verifiers() -> List[BaseVerifier]:
    """获取默认验证器列表（三个全开）。"""
    return [
        CycleConsistencyVerifier(),
        FactualityVerifier(),
        ApplicabilityVerifier(),
    ]


def run_all_verifiers(
    content: str,
    context: Optional[str] = None,
    verifiers: Optional[List[BaseVerifier]] = None,
) -> List[VerificationSignal]:
    """运行所有验证器，返回 signals 列表。

    可直接传给 verify(signals=signals)。
    """
    if verifiers is None:
        verifiers = get_default_verifiers()
    return [v.verify(content, context=context) for v in verifiers]
