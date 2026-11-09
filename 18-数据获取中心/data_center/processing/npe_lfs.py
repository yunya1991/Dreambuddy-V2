"""NPE R1 规则的 Snorkel 标注函数（LF）层 — SPEC-D1 §5 D2 决策。

定位：
  - 每条 R1 规则族 = 一个标注函数（labeling function），输出 {-1, 0, 1}：
      1  = 该句含逻辑命题（弱标签正例）
      -1 = 该句不含命题（弱标签反例）
      0  = 弃权
  - aggregate() 多数投票聚合（abstain 不计票），冲突/无票 → 0，
    供用户仲裁（D2：用户只仲裁分歧与模糊样本 ~100-150 条）
  - 产出 = R2（FinBERT2 微调）的弱监督训练标签

LF 清单（8 个，全部来自 R1 词典，零额外开发）：
  lf_causal_trigger     因果触发词命中
  lf_conditional_trigger 条件触发词命中
  lf_direction_kw       方向词命中（bullish/bearish 任一）
  lf_event_type         事件类型可归类（非 other）
  lf_target             标的可识别
  lf_hedged             含对冲词（弱信号，单发不判正）
  lf_time_window        含时间窗线索（弱信号，单发不判正）
  lf_no_trigger         无任何触发词 → -1（反例 LF）

聚合口径（预注册，防事后调整）：
  正票 > 负票 且 正票 ≥ 3 → 1
  负票 > 正票             → -1
  其他（平票/无票）        → 0（进仲裁队列）
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from data_center.processing import npe_rules as _r

logger = logging.getLogger("data_center.processing.npe_lfs")

LABEL_POS, LABEL_NEG, LABEL_ABSTAIN = 1, -1, 0


def _s(text: Any) -> str:
    return text if isinstance(text, str) else ""


def lf_causal_trigger(text: Any) -> int:
    t = _s(text)
    return LABEL_POS if any(k in t for k in _r._CAUSAL_TRIGGERS) else LABEL_ABSTAIN


def lf_conditional_trigger(text: Any) -> int:
    t = _s(text)
    return LABEL_POS if any(k in t for k in _r._CONDITIONAL_TRIGGERS) else LABEL_ABSTAIN


def lf_direction_kw(text: Any) -> int:
    t = _s(text)
    has_bear = any(k in t for k in _r._BEARISH_KW)
    has_bull = any(k in t for k in _r._BULLISH_KW)
    return LABEL_POS if (has_bear or has_bull) else LABEL_ABSTAIN


def lf_event_type(text: Any) -> int:
    return LABEL_POS if _r._detect_event_type(_s(text)) != "other" else LABEL_ABSTAIN


def lf_target(text: Any) -> int:
    return LABEL_POS if _r._detect_targets(_s(text)) else LABEL_ABSTAIN


def lf_hedged(text: Any) -> int:
    # 弱信号：对冲词常见于分析句式，但单独不构成命题
    t = _s(text)
    if not any(k in t for k in _r._HEDGED_KW):
        return LABEL_ABSTAIN
    has_dir = any(k in t for k in (_r._BULLISH_KW + _r._BEARISH_KW))
    return LABEL_POS if has_dir else LABEL_ABSTAIN


def lf_time_window(text: Any) -> int:
    # 弱信号：时间窗 + 方向词共现才算命题候选
    t = _s(text)
    if not _r._detect_time_window(t):
        return LABEL_ABSTAIN
    has_dir = any(k in t for k in (_r._BULLISH_KW + _r._BEARISH_KW))
    return LABEL_POS if has_dir else LABEL_ABSTAIN


def lf_no_trigger(text: Any) -> int:
    t = _s(text)
    if not t.strip():
        return LABEL_ABSTAIN
    return LABEL_NEG if not any(k in t for k in _r._ALL_TRIGGERS) else LABEL_ABSTAIN


LABELING_FUNCTIONS: list[Callable[[Any], int]] = [
    lf_causal_trigger,
    lf_conditional_trigger,
    lf_direction_kw,
    lf_event_type,
    lf_target,
    lf_hedged,
    lf_time_window,
    lf_no_trigger,
]

MIN_POS_VOTES = 3  # 预注册：正票下限


def apply_lfs(text: Any) -> list[int]:
    """逐 LF 打票，返回标签向量。FAIL-OPEN：异常 → 全弃权。"""
    try:
        return [lf(text) for lf in LABELING_FUNCTIONS]
    except Exception as e:  # noqa: BLE003
        logger.warning("[FAIL-OPEN] apply_lfs 异常 %s: %s", type(e).__name__, str(e)[:200])
        return [LABEL_ABSTAIN] * len(LABELING_FUNCTIONS)


def aggregate(votes: list[int]) -> int:
    """多数投票聚合（预注册口径）。"""
    pos = sum(1 for v in votes if v == LABEL_POS)
    neg = sum(1 for v in votes if v == LABEL_NEG)
    if pos > neg and pos >= MIN_POS_VOTES:
        return LABEL_POS
    if neg > pos:
        return LABEL_NEG
    return LABEL_ABSTAIN


def weak_label_sentence(text: Any) -> dict:
    """单句弱标注：{votes, label, needs_arbitration}。"""
    votes = apply_lfs(text)
    label = aggregate(votes)
    return {
        "votes": votes,
        "label": label,
        # 平票/全弃权/正票不足 → 用户仲裁队列（D2）
        "needs_arbitration": label == LABEL_ABSTAIN and any(v != LABEL_ABSTAIN for v in votes),
    }
