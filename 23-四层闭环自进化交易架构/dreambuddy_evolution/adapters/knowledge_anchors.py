"""
knowledge_anchors — 金融知识锚点库

首批对齐锚点（7 理论 + 4 经验案例）:
  理论锚点来自传统金融和加密社区的成熟理论
  经验锚点来自我们自身的实盘经验（如 UNI 手续费传导）

每个锚点包含:
  - anchor_id: 唯一标识
  - name: 名称
  - origin: 来源
  - causal_pattern: 因果模式描述（用于结构化匹配）
  - keywords: 关键词（用于语义匹配）
  - associated_genes: 关联的基因类型（用于语义匹配）
  - step_type_sequence: 典型步骤类型序列（如 ["condition", "inference", "condition", "action"]）
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class KnowledgeAnchor:
    anchor_id: str
    name: str
    origin: str
    causal_pattern: str
    keywords: list[str] = field(default_factory=list)
    associated_genes: list[str] = field(default_factory=list)
    step_type_sequence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ─── 7 个理论锚点 ───────────────────────────────────────────────

THEORY_ANCHORS: list[KnowledgeAnchor] = [
    KnowledgeAnchor(
        anchor_id="T-CAPITAL-ROTATION",
        name="资金轮动",
        origin="加密社区 · 板块轮动理论",
        causal_pattern="弱势币失血 → 强势币吸金 → 跟随强势方向",
        keywords=["轮动", "资金流", "板块", "竞品", "吸血", "强势", "弱势"],
        associated_genes=["CD-CAPITAL-ROTATION", "CD-COMPETITOR-WEAK", "AC-LONG", "AC-SHORT"],
        step_type_sequence=["condition", "inference", "condition", "action"],
    ),
    KnowledgeAnchor(
        anchor_id="T-MOMENTUM-BREAKOUT",
        name="动量突破",
        origin="传统金融 · 趋势跟随 (Jegadeesh & Titman 1993)",
        causal_pattern="放量突破 → 趋势延续 → 跟随突破方向",
        keywords=["突破", "动量", "放量", "趋势", "MA20", "ADX", "新高"],
        associated_genes=["CD-VOL-SURGE", "CD-PRICE-BREAKOUT", "CD-ADX-STRONG", "AC-LONG"],
        step_type_sequence=["condition", "inference", "condition", "action"],
    ),
    KnowledgeAnchor(
        anchor_id="T-MEAN-REVERSION",
        name="均值回归",
        origin="传统金融 · 统计套利 (Ornstein-Uhlenbeck)",
        causal_pattern="价格偏离均值过远 → 回归均值 → 反向交易",
        keywords=["均值回归", "z_score", "震荡", "偏离", "超买", "超卖", "回归"],
        associated_genes=["CD-ZSCORE-EXTREME", "CD-REGIME-RANGING", "AC-LONG", "AC-SHORT"],
        step_type_sequence=["condition", "inference", "action"],
    ),
    KnowledgeAnchor(
        anchor_id="T-REFLEXIVITY",
        name="反身性",
        origin="传统金融 · Soros 金融炼金术",
        causal_pattern="认知↔事态正反馈 → 极端 → 反转",
        keywords=["反身性", "正反馈", "极端", "反转", "OI背离", "费率", "情绪极端"],
        associated_genes=["CD-OI-DIVERGENCE", "CD-FUNDING-EXTREME", "CD-SENTIMENT-EXTREME"],
        step_type_sequence=["condition", "inference", "inference", "action"],
    ),
    KnowledgeAnchor(
        anchor_id="T-VALUE-CAPTURE",
        name="价值捕获",
        origin="加密社区 · 协议代币经济学",
        causal_pattern="协议收入↑ → 回购/销毁↑ → 代币价值↑",
        keywords=["价值捕获", "协议收入", "回购", "销毁", "手续费", "代币经济", "收入"],
        associated_genes=["CD-PROTOCOL-REVENUE", "CD-VOL-SURGE", "AC-LONG"],
        step_type_sequence=["condition", "inference", "condition", "action"],
    ),
    KnowledgeAnchor(
        anchor_id="T-FUNDING-ARB",
        name="费率套利",
        origin="加密社区 · 永续合约机制",
        causal_pattern="费率极端 → 反向开仓赚费率 → 费率回归平仓",
        keywords=["费率", "套利", "永续", "资金费率", "极端费率", "反向"],
        associated_genes=["CD-FUNDING-EXTREME", "AC-LONG", "AC-SHORT"],
        step_type_sequence=["condition", "inference", "action"],
    ),
    KnowledgeAnchor(
        anchor_id="T-WYCKOFF-EFFORT",
        name="Wyckoff 努力-结果",
        origin="传统金融 · Wyckoff 三定律",
        causal_pattern="努力(量)与结果(价)不符 → 趋势衰竭 → 反转",
        keywords=["Wyckoff", "努力", "结果", "量价背离", "放量不涨", "缩量下跌", "衰竭"],
        associated_genes=["CD-VOL-PRICE-DIVERGENCE", "CD-R_FLOW_ANOMALY", "AC-SHORT", "AC-LONG"],
        step_type_sequence=["condition", "inference", "action"],
    ),
]


# ─── 4 个经验锚点 ───────────────────────────────────────────────

EXPERIENCE_ANCHORS: list[KnowledgeAnchor] = [
    KnowledgeAnchor(
        anchor_id="E-UNI-FEE-ROTATION",
        name="UNI 手续费传导→竞品轮动",
        origin="实盘经验 · UNI 案例",
        causal_pattern="链上手续费↑ → 资金流入 → UNI/ARB涨 → Meme轮动 → PUMP跌",
        keywords=["手续费", "UNI", "ARB", "传导", "Meme", "PUMP", "轮动", "竞品"],
        associated_genes=["CD-PROTOCOL-REVENUE", "CD-CAPITAL-ROTATION", "AC-LONG", "AC-SHORT-COMPETITOR"],
        step_type_sequence=["condition", "inference", "condition", "action", "inference", "action"],
    ),
    KnowledgeAnchor(
        anchor_id="E-PUMP-MEME-SEASON",
        name="PUMP Meme 季节吸血",
        origin="实盘经验 · PUMP 案例",
        causal_pattern="Meme爆发 → PUMP收入↑ → PUMP涨 → 其他板块失血",
        keywords=["Meme", "PUMP", "季节", "吸血", "爆发", "板块失血"],
        associated_genes=["CD-VOL-SURGE", "CD-CAPITAL-ROTATION", "AC-LONG", "AC-SHORT"],
        step_type_sequence=["condition", "inference", "action", "condition", "action"],
    ),
    KnowledgeAnchor(
        anchor_id="E-BNB-EXCHANGE-CYCLE",
        name="BNB 交易所币周期",
        origin="实盘经验 · BNB 案例",
        causal_pattern="交易量↑ → 手续费收入↑ → 回购销毁↑ → BNB涨",
        keywords=["BNB", "交易所", "交易量", "回购", "销毁", "手续费", "周期"],
        associated_genes=["CD-VOL-SURGE", "CD-PROTOCOL-REVENUE", "AC-LONG"],
        step_type_sequence=["condition", "inference", "inference", "action"],
    ),
    KnowledgeAnchor(
        anchor_id="E-BTC-ETF-AMPLIFICATION",
        name="BTC ETF 传导",
        origin="实盘经验 · ETF 案例",
        causal_pattern="ETF净流入 → BTC需求↑ → COIN/MSTR等概念股受益",
        keywords=["ETF", "BTC", "净流入", "传导", "概念股", "COIN", "MSTR"],
        associated_genes=["CD-CAPITAL-INFLOW", "CD-VOL-SURGE", "AC-LONG"],
        step_type_sequence=["condition", "inference", "action"],
    ),
]


def get_all_anchors() -> list[KnowledgeAnchor]:
    """返回所有知识锚点（理论 + 经验）"""
    return THEORY_ANCHORS + EXPERIENCE_ANCHORS


def get_anchor_by_id(anchor_id: str) -> Optional[KnowledgeAnchor]:
    for a in get_all_anchors():
        if a.anchor_id == anchor_id:
            return a
    return None
