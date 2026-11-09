"""NPE v0（R1 规则版）叙事命题抽取器 — SPEC-D1-NARRATIVE-PRIMITIVES §2.3。

定位：
  - R1 = 因果/条件触发词典召回候选 + 规则定边界/论元 → 逻辑命题
  - 同时充当 Snorkel 标注函数（D2），为 R2 弱监督聚合产数据
  - 召回优先于召回率：precision 目标 ≥0.8，漏抽可接受，错抽禁止
    → 发射条件 = 触发词 AND 方向词 同时命中（双判据，宁缺毋滥）

命题 schema（SPEC §2.3）：
  {proposition_id, condition_event, event_type, market_state_qualifier,
   conclusion{direction,target_scope,magnitude_hint}, time_window,
   confidence_in_text, evidence_spans, extractor_version}

FAIL-OPEN：任何输入异常 → 返回空列表。
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

logger = logging.getLogger("data_center.processing.npe_rules")

EXTRACTOR_VERSION = "npe-v0.1"

# ── 触发词典 ────────────────────────────────────────────────
# 因果触发词：连接条件与结论
_CAUSAL_TRIGGERS = [
    "导致",
    "因此",
    "所以",
    "因为",
    "意味着",
    "推动",
    "引发",
    "验证",
    "刺激",
    "提振",
    "拖累",
]
# 条件触发词：假设/条件句式
_CONDITIONAL_TRIGGERS = ["如果", "若", "一旦", "当"]

_ALL_TRIGGERS = _CAUSAL_TRIGGERS + _CONDITIONAL_TRIGGERS

# ── 方向词典 ────────────────────────────────────────────────
_BULLISH_KW = [
    "上涨",
    "走强",
    "利好",
    "反弹",
    "突破",
    "拉升",
    "估值提升",
    "新高",
    "看涨",
    "牛市",
    "上行",
]
_BEARISH_KW = [
    "下跌",
    "走弱",
    "利空",
    "回调",
    "抛压",
    "暴跌",
    "崩盘",
    "新低",
    "看跌",
    "熊市",
    "下行",
    "失速",
]

# ── 标的词典 ────────────────────────────────────────────────
_TARGET_MAP = {
    "BTC": ["BTC", "比特币"],
    "ETH": ["ETH", "以太坊"],
    "SOL": ["SOL", "Solana", "索拉纳"],
    "BNB": ["BNB", "币安币"],
    "XRP": ["XRP", "瑞波"],
    "DOGE": ["DOGE", "狗狗币"],
}

# ── 事件类型归类（对齐 SPEC §2.4 Top5 + other）──────────────
_EVENT_TYPE_RULES = [
    ("macro.rate", ["降息", "加息", "美联储", "FOMC", "利率"]),
    ("etf.regulation", ["ETF", "SEC", "监管", "获批", "审批"]),
    ("unlock.supply", ["解锁", "赔付", "释放", "流通盘"]),
    ("listing.exchange", ["上所", "上线", "首发", "listing"]),
    ("hack.security", ["黑客", "被盗", "攻击", "漏洞", "盗取"]),
    ("liquidity.derivatives", ["资金费率", "费率", "持仓量", "OI", "爆仓", "清算"]),
]

# ── 时间窗线索 ──────────────────────────────────────────────
_TIME_WINDOW_RULES = [
    ("日内", "T+24h"),
    ("短期", "T+7d"),
    ("本周", "T+7d"),
    ("中长期", "T+30d"),
    ("长期", "T+30d"),
]

# ── 对冲词（hedged 置信）────────────────────────────────────
_HEDGED_KW = ["可能", "或将", "或许", "有望", "大概率"]

_SENT_SPLIT_RE = re.compile(r"[^。！？；\n]+[。！？；]?")


def _norm(text: Any) -> str:
    return text if isinstance(text, str) else ""


def _detect_direction(sent: str) -> str:
    for kw in _BEARISH_KW:
        if kw in sent:
            return "bearish"
    for kw in _BULLISH_KW:
        if kw in sent:
            return "bullish"
    return ""


def _detect_targets(sent: str) -> list[str]:
    out = []
    for sym, aliases in _TARGET_MAP.items():
        if any(a in sent for a in aliases):
            out.append(sym)
    return out


def _detect_event_type(sent: str) -> str:
    for etype, kws in _EVENT_TYPE_RULES:
        if any(kw in sent for kw in kws):
            return etype
    return "other"


def _detect_time_window(sent: str) -> str:
    for kw, tw in _TIME_WINDOW_RULES:
        if kw in sent:
            return tw
    return ""


def _detect_confidence(sent: str) -> str:
    return "hedged" if any(kw in sent for kw in _HEDGED_KW) else "strong"


def _find_trigger(sent: str) -> str:
    """返回句中最先出现的触发词。"""
    best, best_pos = "", len(sent) + 1
    for tg in _ALL_TRIGGERS:
        pos = sent.find(tg)
        if 0 <= pos < best_pos:
            best, best_pos = tg, pos
    return best


def _extract_condition(sent: str, trigger: str) -> str:
    """条件事件：触发词左侧从句（条件/因果句式），'因为'类取右侧。"""
    pos = sent.find(trigger)
    if trigger == "因为":
        seg = sent[pos + len(trigger) :]
    elif trigger in _CONDITIONAL_TRIGGERS:
        # "如果X，那么Y" → 取触发词与"那么/则/,"之间
        seg = sent[pos + len(trigger) :]
        for sep in ("，那么", "那么", "，则", "则", "，"):
            sp = seg.find(sep)
            if sp > 0:
                seg = seg[:sp]
                break
    else:
        seg = sent[:pos]
    seg = seg.strip("，。；、： ")
    return seg[:120]


def extract_propositions(text: Any, doc_id: Any = "", **_: Any) -> list[dict]:
    """从正文抽取逻辑命题（R1 规则版）。

    FAIL-OPEN：任何异常返回 []。
    发射判据：触发词命中 AND 方向可判定（precision 优先）。
    """
    try:
        text_s = _norm(text)
        if not text_s.strip():
            return []
        doc_s = _norm(doc_id) or "unknown"

        props: list[dict] = []
        for m in _SENT_SPLIT_RE.finditer(text_s):
            sent = m.group(0).strip()
            if len(sent) < 6:
                continue
            trigger = _find_trigger(sent)
            if not trigger:
                continue
            direction = _detect_direction(sent)
            if not direction:
                continue  # 双判据：无方向词 → 不发射（防错抽）

            condition = _extract_condition(sent, trigger)
            if len(condition) < 4:
                continue  # precision 护栏：条件碎片化（"这"/"其冲"）不发射
            idx = len(props)
            pid_raw = f"{doc_s}:{m.start()}:{idx}"
            pid = "NP-" + hashlib.sha1(pid_raw.encode("utf-8")).hexdigest()[:12]

            props.append(
                {
                    "proposition_id": pid,
                    "condition_event": condition,
                    "event_type": _detect_event_type(sent),
                    "market_state_qualifier": "",
                    "conclusion": {
                        "direction": direction,
                        "target_scope": _detect_targets(sent),
                        "magnitude_hint": None,
                    },
                    "time_window": _detect_time_window(sent),
                    "confidence_in_text": _detect_confidence(sent),
                    "evidence_spans": [
                        {
                            "doc_id": doc_s,
                            "start": m.start(),
                            "end": m.end(),
                        }
                    ],
                    "extractor_version": EXTRACTOR_VERSION,
                }
            )
        return props
    except Exception as e:  # noqa: BLE003  FAIL-OPEN
        logger.warning("[FAIL-OPEN] npe_rules 异常 %s: %s", type(e).__name__, str(e)[:200])
        return []
