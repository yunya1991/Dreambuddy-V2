"""
DreamOS S层 — 问题复杂度分级器 (PROP-20260829D Phase 1)

职责:
    对已完成意图识别的问题，做确定性复杂度分级（T0-T3），
    供 A 层渐进式编排（phase 参数）与 T0 快速回答短路使用。

设计原则:
    - 纯规则、零 Token、毫秒级（规则优先；无命中时保守落档）
    - 宁浅勿深：模糊时倾向更浅的档，避免过度编排浪费
    - 不改变意图类型，只附加复杂度维度

分级定义:
    T0  简单查询      价格/仓位/余额等数据点查询 → 零编排直答
    T1  单域问题      单一领域决策问题（默认档）→ 完整单链
    T2  多域/战略     跨多个领域或要求制定策略 → 多链编排
    T3  深度研究      A系列深度分析任务 → 委托 Hermes

典型例子:
    "BTC多少钱"                          → T0
    "BTC 现在能做多吗"                    → T1
    "综合评估本周行情并制定策略"           → T2
    "对这波回调做深度分析"                → T3
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ============================================================
# 分级常量
# ============================================================

TIER_T0 = "T0"   # 简单查询
TIER_T1 = "T1"   # 单域问题（默认）
TIER_T2 = "T2"   # 多域/战略
TIER_T3 = "T3"   # 深度研究

ALL_TIERS = (TIER_T0, TIER_T1, TIER_T2, TIER_T3)

TIER_DESCRIPTIONS = {
    TIER_T0: "简单查询（零编排直答）",
    TIER_T1: "单域问题（完整单链）",
    TIER_T2: "多域/战略问题（多链编排）",
    TIER_T3: "深度研究（委托 Hermes 深度分析）",
}


@dataclass
class ComplexityDecision:
    """复杂度分级结果"""
    tier: str = TIER_T1
    rationale: str = ""            # 分级理由（含命中规则）
    rule_hit: str = "default"      # 命中的规则名
    domain_signals: List[str] = field(default_factory=list)  # 检出的领域信号

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tier": self.tier,
            "rationale": self.rationale,
            "rule_hit": self.rule_hit,
            "domain_signals": self.domain_signals,
        }


# ── 影子观测（PROP-20260829D Phase 4）────────────────────────────
# 分级决策落 JSONL，供灰度期统计分布与误判回溯；任何失败静默忽略，
# 绝不影响主链路。路径可用环境变量 DREAMOS_PHASED_SHADOW_LOG 覆盖。

def log_shadow_event(user_message: Optional[str],
                     decision: ComplexityDecision,
                     intent_type: str = "") -> None:
    """追加一条分级影子记录（best-effort，不抛异常）"""
    try:
        import json
        import time as _time
        path = os.environ.get(
            "DREAMOS_PHASED_SHADOW_LOG",
            os.path.join(os.path.expanduser("~"), ".dreamos",
                         "phased_shadow.jsonl"),
        )
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": _time.strftime("%Y-%m-%dT%H:%M:%S"),
                "tier": decision.tier,
                "rule_hit": decision.rule_hit,
                "intent_type": intent_type,
                "msg_len": len(user_message or ""),
            }, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 — 影子日志必须静默
        pass


# ============================================================
# 规则词表
# ============================================================

# T3：深度研究触发词（最高优先级，匹配即深档）
_T3_KEYWORDS = [
    "深度分析", "深度调研", "深度报告", "调研报告", "战略分析", "战略研究",
    "全面深度", "矛盾论", "第一性原理", "六因子", "a系列", "a链",
]
# A0-A3 编号单独用词边界匹配，避免误伤（如 "a3纸"）
_T3_CODE_PATTERN = re.compile(r"\ba[0-3]\b", re.IGNORECASE)

# T0：数据查询词
_T0_QUERY_WORDS = [
    "多少钱", "价格", "现价", "价位", "多少", "几个点",
    "查一下", "查下", "看看", "查询",
    "仓位", "持仓", "余额", "保证金", "未实现盈亏",
    "资金费率", "费率", "爆仓价", "强平价",
]

# 决策动词：出现即排除 T0（有决策诉求就不是纯查询）
_DECISION_VERBS = [
    "做多", "做空", "买入", "卖出", "开仓", "平仓", "加仓", "减仓",
    "抄底", "逃顶", "止损", "止盈", "入场", "出场", "建仓", "补仓",
    "该不该", "能不能", "可以吗", "适合", "值得", "要不要", "怎么办",
]

# 分析任务动词：出现即排除 T0（要的是分析产出，不是数据点）
_TASK_WORDS = [
    "评估", "分析", "制定", "给出", "建议", "方案", "策略", "规划",
    "总结", "复盘", "预测", "判断",
]

# T2：战略/多域触发词
_T2_KEYWORDS = [
    "全面评估", "综合评估", "多维度", "多维度分析", "多維度", "综合分析",
    "整体策略", "本周策略", "交易策略", "策略制定", "制定策略", "战略",
    "对比分析", "系统评估", "系统性", "风险敞口", "仓位调整方案",
    "所有币", "各个币", "多个标的", "组合",
]

# 领域词（用于多域枚举检测）
_DOMAIN_WORDS = {
    "技术面": ["技术面", "技术", "指标", "均线", "rsi", "macd", "k线", "趋势线"],
    "宏观": ["宏观", "美联储", "利率", "降息", "加息", "cpi", "美元指数"],
    "链上": ["链上", "链上数据", "巨鲸", "onchain", "活跃地址"],
    "情绪": ["情绪", "恐慌", "贪婪", "恐贪指数", "舆论"],
    "资金": ["资金", "资金流", "资金费率", "成交量", "持仓量", "oi"],
    "基本面": ["基本面", "新闻", "消息面", "公告", "项目进展"],
}


# ============================================================
# 分级主函数
# ============================================================

def classify_complexity(user_message: Optional[str],
                        intent_type: str = "",
                        context: Optional[Dict[str, Any]] = None) -> ComplexityDecision:
    """对问题做复杂度分级（纯规则，零 Token）

    优先级: T3（深度触发词）> T0（纯查询）> T2（战略/多域）> T1（默认）

    Args:
        user_message: 用户自然语言输入
        intent_type: S 层已识别的意图类型（DEEP_ANALYSIS 直接判 T3）
        context: 额外上下文（预留，暂未使用）

    Returns:
        ComplexityDecision: 分级结果
    """
    msg = (user_message or "").strip()

    # 空输入 → 默认档（交给澄清逻辑处理）
    if not msg:
        return ComplexityDecision(
            tier=TIER_T1, rationale="空输入，默认档", rule_hit="empty_input")

    lower = msg.lower()

    # ── 规则 1: T3 深度研究 ────────────────────────
    if intent_type == "DEEP_ANALYSIS":
        return ComplexityDecision(
            tier=TIER_T3, rationale="意图类型 DEEP_ANALYSIS → 深度研究",
            rule_hit="intent_deep_analysis")
    for kw in _T3_KEYWORDS:
        if kw in lower:
            return ComplexityDecision(
                tier=TIER_T3, rationale=f"命中深度触发词「{kw}」",
                rule_hit="t3_keyword")
    if _T3_CODE_PATTERN.search(lower):
        return ComplexityDecision(
            tier=TIER_T3, rationale="命中 A0-A3 编号触发词",
            rule_hit="t3_code")

    has_decision_verb = any(v in lower for v in _DECISION_VERBS)
    has_task_word = any(w in lower for w in _TASK_WORDS)

    # ── 规则 2: T0 简单查询 ────────────────────────
    # 条件：含查询词 + 无决策动词 + 无分析任务词 + 短句（≤30字符）
    # 宁浅勿深：长句/含分析诉求的查询多半是"查了还要分析"，不落 T0
    if not has_decision_verb and not has_task_word and len(msg) <= 30:
        hit_query = next((w for w in _T0_QUERY_WORDS if w in lower), None)
        if hit_query:
            return ComplexityDecision(
                tier=TIER_T0, rationale=f"纯查询「{hit_query}」，无决策动词",
                rule_hit="t0_query")

    # ── 规则 3: T2 多域/战略 ───────────────────────
    for kw in _T2_KEYWORDS:
        if kw in lower:
            return ComplexityDecision(
                tier=TIER_T2, rationale=f"命中战略触发词「{kw}」",
                rule_hit="t2_keyword")

    # 多域枚举：显式提及 ≥2 个领域
    domains = _detect_domains(lower)
    if len(domains) >= 2:
        return ComplexityDecision(
            tier=TIER_T2, rationale=f"多域枚举（{'+'.join(domains)}）",
            rule_hit="t2_multi_domain", domain_signals=domains)

    # ── 默认: T1 单域问题 ──────────────────────────
    return ComplexityDecision(
        tier=TIER_T1,
        rationale="未命中 T0/T2/T3 规则，默认单域档",
        rule_hit="default",
        domain_signals=domains,
    )


def _detect_domains(lower_msg: str) -> List[str]:
    """检测消息中显式提及的领域"""
    found = []
    for domain, words in _DOMAIN_WORDS.items():
        if any(w in lower_msg for w in words):
            found.append(domain)
    return found


# ============================================================
# 档位 → 编排建议映射（供 A 层参考，非强制）
# ============================================================

def tier_orchestration_hint(tier: str) -> Dict[str, Any]:
    """返回档位的编排建议（A 层可据此决定 phase 起点）

    T0 → 零编排直答
    T1 → phase=1 起步（必要节点），可深化
    T2 → 完整编排（全节点）
    T3 → 委托 Hermes 深度分析
    """
    hints = {
        TIER_T0: {"mode": "direct_answer", "phase": None,
                  "desc": "零编排直答（≤2s）"},
        TIER_T1: {"mode": "phased", "phase": 1,
                  "desc": "渐进式：phase=1 起步，追问深化"},
        TIER_T2: {"mode": "full", "phase": None,
                  "desc": "完整多链编排"},
        TIER_T3: {"mode": "delegate_hermes", "phase": None,
                  "desc": "委托 Hermes A 系列深度分析"},
    }
    return hints.get(tier, hints[TIER_T1])
