"""千问知识工具 knowledge.ask：把 consult 通道的文本答案标准化为只读结构化知识。

纪律：
- 只读（`side_effect="none"`）：不返回可执行动作，不触碰支付/提交；
- 可引用：从答案中提取来源链接与依据原文；
- 可判可信：给出 0~1 置信度，无引用时封顶 0.6；
- 可缓存：按 (app, question) 指纹做 TTL 缓存，避免同问题反复占用手机。

传输层复用 `mra._consult_sync`（app=qianwen），本模块只做「提问模板 + 解析 + 缓存 + 安全」。
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone

SCHEMA = "knowledge.v1"
DEFAULT_TTL_SECONDS = 7 * 86400
NO_CITATION_CAP = 0.6
UNSAFE_CAP = 0.3
CONFIDENCE_RANGE = (0.05, 0.95)

CN_TZ = timezone(timedelta(hours=8))

# 出现即视为「答案含可执行支付/提交动作」——知识工具不得输出这些
UNSAFE_MARKERS = (
    "提交订单", "立即支付", "确认支付", "去支付", "支付密码", "代付", "锁座", "占座",
)
UNCERTAIN_MARKERS = ("不确定", "可能", "也许", "建议咨询官方", "以官方为准", "猜测")

_URL_RE = re.compile(r"https?://[^\s，。；、）)】\"']+")
_SECTION_RE = re.compile(r"^[ \t]*(结论|依据|置信度)[ \t]*[:：][ \t]*(.*)$", re.M)
_EVIDENCE_SPLIT_RE = re.compile(r"[\n；;]+")
_NUMERIC_RE = re.compile(r"(?<!\d)(0?\.\d+|1(?:\.0+)?)(?!\d)")
_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_BULLET_RE = re.compile(r"^[\s\-*·•\d.、)）]+")


def normalize_question(question: str) -> str:
    return re.sub(r"\s+", " ", str(question or "")).strip()


def cache_key(question: str, app: str = "") -> str:
    raw = "{}|{}".format(str(app or "").strip().lower(), normalize_question(question).lower())
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def build_prompt(question: str, app: str = "") -> str:
    """固定三段式提问模板：结论 / 依据 / 置信度，并声明只读、不要可执行步骤。"""
    scope = "（平台：{}）".format(app) if app else ""
    return (
        "{}{}\n\n"
        "请只回答平台规则与事实，不要给可执行的操作步骤，不要建议支付或提交订单。"
        "严格按以下格式输出：\n"
        "结论：一句话结论\n"
        "依据：引用原文或来源链接，多条用分号分隔\n"
        "置信度：高/中/低（或 0~1 的小数）"
    ).format(normalize_question(question), scope)


def _sections(text: str) -> dict[str, str]:
    matches = list(_SECTION_RE.finditer(text))
    if not matches:
        return {}
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        value = text[match.end():end].strip() or match.group(2).strip()
        sections[match.group(1)] = value
    return sections


def extract_citations(text: str, include_quotes: bool = True) -> list[dict]:
    """从文本提取引用：URL 优先，其次按行/分号切分的依据原文。"""
    out: list[dict] = []
    seen: set[str] = set()
    for url in _URL_RE.findall(text or ""):
        if url in seen:
            continue
        seen.add(url)
        out.append({"type": "url", "value": url})
    if not include_quotes:
        return out
    for item in _EVIDENCE_SPLIT_RE.split(text or ""):
        quote = _BULLET_RE.sub("", item).strip()
        if len(quote) < 4 or quote in seen:
            continue
        if quote.startswith(("结论", "置信度")):
            continue
        seen.add(quote)
        out.append({"type": "quote", "value": quote[:200]})
    return out


def _parse_confidence(raw: str, answer: str, citations: list[dict]) -> float:
    value: float | None = None
    raw = (raw or "").strip()
    if raw:
        percent = _PERCENT_RE.search(raw)
        numeric = _NUMERIC_RE.search(raw.replace("%", " "))
        if percent:
            value = float(percent.group(1)) / 100.0
        elif numeric:
            value = float(numeric.group(1))
        elif "高" in raw:
            value = 0.9
        elif "中" in raw:
            value = 0.65
        elif "低" in raw:
            value = 0.4
    if value is None:
        value = 0.7 if citations else 0.5
    if not citations:
        value = min(value, NO_CITATION_CAP)
    if any(marker in (answer or "") for marker in UNCERTAIN_MARKERS):
        value -= 0.1
    low, high = CONFIDENCE_RANGE
    return round(max(low, min(high, value)), 2)


def sanitize_answer(answer: str) -> tuple[str, bool]:
    """遮蔽含支付/提交动作的行，返回 (清洗后文本, 是否命中)。"""
    hit = False
    lines = []
    for line in (answer or "").splitlines():
        if any(marker in line for marker in UNSAFE_MARKERS):
            hit = True
            lines.append("[已拦截：涉及支付/提交类指令]")
            continue
        lines.append(line)
    return "\n".join(lines).strip(), hit


def parse_answer(text: str) -> dict:
    """把千问原始回答解析为 {answer, citations, confidence, unsafe_actions_detected}。"""
    raw = (text or "").strip()
    sections = _sections(raw)
    conclusion = sections.get("结论", "").strip()
    evidence = sections.get("依据", "").strip()
    if conclusion:
        body = conclusion
        citations = extract_citations(evidence)
    else:
        body = raw
        citations = extract_citations(raw, include_quotes=False)
    confidence = _parse_confidence(sections.get("置信度", ""), body, citations)
    answer, unsafe = sanitize_answer(body)
    if unsafe:
        confidence = min(confidence, UNSAFE_CAP)
    deduped = []
    seen = set()
    for item in citations:
        if item["value"] in seen:
            continue
        seen.add(item["value"])
        deduped.append(item)
    return {
        "answer": answer,
        "citations": deduped[:5],
        "confidence": round(confidence, 2),
        "unsafe_actions_detected": unsafe,
    }


def build_envelope(
    question: str,
    raw_answer: str,
    app: str = "",
    source: str = "qianwen-app",
    cached: bool = False,
) -> dict:
    parsed = parse_answer(raw_answer)
    return {
        "schema": SCHEMA,
        "question": normalize_question(question),
        "app": str(app or "").strip(),
        "answer": parsed["answer"],
        "citations": parsed["citations"],
        "confidence": parsed["confidence"],
        "side_effect": "none",
        "source": source,
        "cached": bool(cached),
        "unsafe_actions_detected": parsed["unsafe_actions_detected"],
        "asked_at": datetime.now(CN_TZ).isoformat(timespec="seconds"),
    }
