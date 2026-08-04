"""
DreamOS S层 — 规则识别器（零 Token）

基于本地数据和规则对每种意图类型打分：
    - 趋势跟随（TREND_FOLLOWING）：均线排列、24H涨跌幅、ADX
    - 均值回归（MEAN_REVERSION）：RSI、布林带位置、偏离度
    - 基本面驱动（FUNDAMENTAL_PLAY）：资金费率、新闻/资金流信号
    - 突破（BREAKOUT）：波动率、成交量比、高低位
    - 知识库匹配（KNOWLEDGE_MATCH）：历史模式匹配

设计原则:
    - 零 Token 消耗，纯本地计算
    - 可配置权重和阈值
    - 输出带理由，便于调试
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from .base import BaseRecognizer
from ..types import IntentInput, RecognizerResult, IntentType, get_intent_definition
from dreamos.shared.utils import Timer


class RuleBasedRecognizer(BaseRecognizer):
    """基于规则的零 Token 意图识别器

    输入:
        - market: 市场数据（price/rsi/ema/vol_ratio/funding/...）
        - user_message: 自然语言（可选，做关键词匹配）
        - signals: 外部信号（可选）
        - memory: 历史记忆（可选）

    输出:
        RecognizerResult: 得分最高的意图类型及置信度
    """

    name = "rule_based"
    level = "local"
    estimated_tokens = 0

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # 各意图的关键词（用于 NLP 打分）
        self._keyword_map = self._build_keyword_map()

    def recognize(self, _input: IntentInput) -> RecognizerResult:
        timer = Timer("rule_based")

        scores: Dict[str, float] = {}
        reasons: Dict[str, List[str]] = {}

        for it in IntentType.all_types():
            scores[it] = 0.0
            reasons[it] = []

        # 1. 市场数据打分（权重最高）
        if _input.market:
            mkt_scores, mkt_reasons = self._score_by_market(_input.market)
            for it, s in mkt_scores.items():
                scores[it] += s
                if it in mkt_reasons:
                    reasons[it].extend(mkt_reasons[it])

        # 2. NLP 关键词匹配（有用户输入时）
        if _input.user_message:
            nlp_scores, keywords = self._score_by_nlp(_input.user_message)
            for it, s in nlp_scores.items():
                scores[it] += s * 0.7  # NLP 权重
                if s > 0.2:
                    reasons[it].append(f"NLP关键词匹配: {', '.join(keywords.get(it, []))}")

        # 3. 外部信号
        if _input.signals:
            sig_scores = self._score_by_signals(_input.signals)
            for it, s in sig_scores.items():
                scores[it] += s * 0.3

        # 4. 知识库命中
        if _input.knowledge_hits:
            scores[IntentType.KNOWLEDGE_MATCH.value] += 0.4
            reasons[IntentType.KNOWLEDGE_MATCH.value].append(
                f"知识库命中 {len(_input.knowledge_hits)} 条"
            )

        # 归一化 & 选出最高分
        if not scores:
            return self._uncertain("无可用输入数据")

        best_type = max(scores, key=scores.get)
        best_score = scores[best_type]

        # 计算置信度（基于最高分与第二名的差距）
        sorted_scores = sorted(scores.values(), reverse=True)
        gap = sorted_scores[0] - (sorted_scores[1] if len(sorted_scores) > 1 else 0)
        confidence = min(best_score * 0.7 + gap * 0.3, 0.95)

        # 低置信度 → 不确定
        if best_score < 0.25:
            best_type = IntentType.UNCERTAIN.value
            confidence = best_score
            rationale = f"所有意图得分较低（最高 {best_score:.2f}），需要更多信息"
        elif gap < 0.05 and len(sorted_scores) > 1:
            # 差距太小，标记为需要澄清
            top_types = [t for t, s in sorted(scores.items(), key=lambda x: x[1], reverse=True)[:3] if s > 0.1]
            rationale = f"多意图接近（{', '.join(top_types)}），需要进一步确认"
        else:
            rationale = "; ".join(reasons.get(best_type, [])) or f"规则打分: {best_score:.2f}"

        # 构建推荐链路
        definition = get_intent_definition(best_type)
        base_chain = self._recommend_chain(best_type, definition)

        with timer:
            pass  # 已经在计时

        return RecognizerResult(
            recognizer=self.name,
            intent_type=best_type,
            confidence=round(confidence, 3),
            rationale=rationale,
            base_chain=base_chain,
            context={
                "scores": {k: round(v, 3) for k, v in scores.items()},
                "gap": round(gap, 3),
            },
            latency_ms=timer.elapsed_ms,
            tokens_used=0,
            level=self.level,
        )

    # ── 市场数据打分 ───────────────────────────────────

    def _score_by_market(self, market: Dict) -> Tuple[Dict[str, float], Dict[str, List[str]]]:
        """基于市场技术指标打分"""
        scores: Dict[str, float] = {}
        reasons: Dict[str, List[str]] = {t: [] for t in IntentType.all_types()}

        price = market.get("price", 0)
        ch24 = market.get("change_24h", 0)
        ch4h = market.get("change_4h", 0)
        rsi = market.get("rsi14", 50)
        vol_ratio = market.get("vol_ratio", 1.0)
        funding = market.get("funding_rate", 0)
        ema20 = market.get("ema20", price)
        ema50 = market.get("ema50", price)
        ema200 = market.get("ema200", price)
        adx = market.get("adx", 20)
        regime = market.get("regime", "UNKNOWN")

        # ── TREND_FOLLOWING 趋势跟随 ───────────────────
        tf = 0.0
        # 均线多头/空头排列
        if price > ema20 > ema50 > ema200:
            tf += 0.30; reasons["TREND_FOLLOWING"].append("均线多头排列")
        elif price < ema20 < ema50 < ema200:
            tf += 0.30; reasons["TREND_FOLLOWING"].append("均线空头排列")
        elif price > ema50 and ema20 > ema50:
            tf += 0.18; reasons["TREND_FOLLOWING"].append("中短期趋势向上")
        elif price < ema50 and ema20 < ema50:
            tf += 0.18; reasons["TREND_FOLLOWING"].append("中短期趋势向下")

        # 24H 涨跌幅
        if abs(ch24) > 5:
            tf += 0.25; reasons["TREND_FOLLOWING"].append(f"24H大幅变动 {ch24:+.1f}%")
        elif abs(ch24) > 3:
            tf += 0.15; reasons["TREND_FOLLOWING"].append(f"24H变动 {ch24:+.1f}%")
        elif abs(ch24) > 1.5:
            tf += 0.08

        # ADX 趋势强度
        if adx > 30:
            tf += 0.15; reasons["TREND_FOLLOWING"].append(f"ADX={adx} 趋势强")
        elif adx > 20:
            tf += 0.08

        scores["TREND_FOLLOWING"] = tf

        # ── MEAN_REVERSION 均值回归 ─────────────────────
        mr = 0.0
        # RSI 超买超卖
        if rsi > 75:
            mr += 0.30; reasons["MEAN_REVERSION"].append(f"RSI={rsi:.0f} 超买")
        elif rsi < 25:
            mr += 0.30; reasons["MEAN_REVERSION"].append(f"RSI={rsi:.0f} 超卖")
        elif rsi > 65:
            mr += 0.18; reasons["MEAN_REVERSION"].append(f"RSI={rsi:.0f} 偏强")
        elif rsi < 35:
            mr += 0.18; reasons["MEAN_REVERSION"].append(f"RSI={rsi:.0f} 偏弱")

        # 偏离均线程度
        if price > 0:
            deviation = abs(price - ema20) / price * 100 if ema20 else 0
            if deviation > 4:
                mr += 0.20; reasons["MEAN_REVERSION"].append(f"偏离EMA20 {deviation:.1f}%")
            elif deviation > 2:
                mr += 0.10

        # 低波动 → 回归概率高
        if vol_ratio < 0.7:
            mr += 0.12; reasons["MEAN_REVERSION"].append(f"成交量低 vol={vol_ratio:.2f}")

        scores["MEAN_REVERSION"] = mr

        # ── FUNDAMENTAL_PLAY 基本面驱动 ─────────────────
        fp = 0.0
        # 资金费率异常
        if abs(funding) > 0.01:
            fp += 0.25; reasons["FUNDAMENTAL_PLAY"].append(f"资金费率异常 {funding:+.3%}")
        elif abs(funding) > 0.005:
            fp += 0.15

        # regime 识别为基本面行情
        if regime and "fund" in regime.lower():
            fp += 0.20; reasons["FUNDAMENTAL_PLAY"].append(f"市场状态: {regime}")

        scores["FUNDAMENTAL_PLAY"] = fp

        # ── BREAKOUT 突破 ──────────────────────────────
        bo = 0.0
        # 成交量放大
        if vol_ratio > 2.0:
            bo += 0.25; reasons["BREAKOUT"].append(f"成交量放大 {vol_ratio:.1f}x")
        elif vol_ratio > 1.5:
            bo += 0.15

        # 短期大幅波动（可能是突破）
        if abs(ch4h) > 2:
            bo += 0.20; reasons["BREAKOUT"].append(f"4H波动 {ch4h:+.1f}%")
        elif abs(ch4h) > 1:
            bo += 0.10

        # 接近 24H 高低点
        high24 = market.get("high_24h", price * 1.05)
        low24 = market.get("low_24h", price * 0.95)
        if high24 > low24:
            range_pos = (price - low24) / (high24 - low24)
            if range_pos > 0.9:
                bo += 0.15; reasons["BREAKOUT"].append("接近24H高点")
            elif range_pos < 0.1:
                bo += 0.15; reasons["BREAKOUT"].append("接近24H低点")

        scores["BREAKOUT"] = bo

        # ── KNOWLEDGE_MATCH 知识库匹配 ──────────────────
        km = 0.0
        # 有历史 regime 记录时小幅加分
        if regime and regime != "UNKNOWN":
            km += 0.05
        scores["KNOWLEDGE_MATCH"] = km

        return scores, reasons

    # ── NLP 关键词匹配 ────────────────────────────────

    def _score_by_nlp(self, text: str) -> Tuple[Dict[str, float], Dict[str, List[str]]]:
        """通过关键词匹配做 NLP 意图识别"""
        text_lower = text.lower()
        scores: Dict[str, float] = {}
        matched_keywords: Dict[str, List[str]] = {}

        for it, kws in self._keyword_map.items():
            matched = [kw for kw in kws if kw.lower() in text_lower]
            if matched:
                # 匹配关键词数量加权
                score = min(0.3 + len(matched) * 0.15, 0.9)
                scores[it] = score
                matched_keywords[it] = matched

        return scores, matched_keywords

    def _build_keyword_map(self) -> Dict[str, List[str]]:
        """构建意图→关键词映射"""
        kw_map: Dict[str, List[str]] = {}
        for it in IntentType.all_types():
            defn = get_intent_definition(it)
            kw_map[it] = defn.get("keywords", [])
        return kw_map

    # ── 信号打分 ──────────────────────────────────────

    def _score_by_signals(self, signals: List[Dict]) -> Dict[str, float]:
        """基于外部信号打分"""
        scores: Dict[str, float] = {t: 0.0 for t in IntentType.all_types()}

        for sig in signals:
            sig_type = sig.get("type", "").upper()
            sig_strength = float(sig.get("strength", 0.5))

            if "TREND" in sig_type or "MA" in sig_type:
                scores["TREND_FOLLOWING"] += sig_strength * 0.2
            elif "REVERSAL" in sig_type or "RSI" in sig_type:
                scores["MEAN_REVERSION"] += sig_strength * 0.2
            elif "NEWS" in sig_type or "FUND" in sig_type:
                scores["FUNDAMENTAL_PLAY"] += sig_strength * 0.2
            elif "BREAKOUT" in sig_type:
                scores["BREAKOUT"] += sig_strength * 0.2

        return scores

    # ── 推荐链路 ──────────────────────────────────────

    def _recommend_chain(self, intent_type: str, definition: Dict) -> List[str]:
        """根据意图类型推荐主链节点

        对应规范中的六种意图到链路映射:
            TREND_FOLLOWING:  C1→F2/F3→A2→A4→A5→A9   (趋势跟随, A链精简)
            MEAN_REVERSION:   C1→F2/F3→A2→A4→A5→A9   (均值回归, A链精简)
            FUNDAMENTAL_PLAY: A1→F1→F5→A2→A4→A5→A9   (基本面驱动, F链)
            BREAKOUT:         C1→A2→C3→A4→A5→A9       (突破, C链)
            KNOWLEDGE_MATCH:  C3→A4→A5→A9              (知识库快捷路径)
            UNCERTAIN:        C1→A1→A2→A4→A5→A9       (不确定, A链完整)

        注意:
            - A0 矛盾论内置于 A2/A3, 不在链路中独立出现
            - A5 战术执行生成最终 trade_order, 必须包含
            - A9 离场策略记录止损止盈, 必须包含
        """
        chain_map = {
            "TREND_FOLLOWING":   ["C1", "F2", "F3", "A2", "A4", "A5", "A9"],
            "MEAN_REVERSION":    ["C1", "F2", "F3", "A2", "A4", "A5", "A9"],
            "FUNDAMENTAL_PLAY":  ["A1", "F1", "F5", "A2", "A4", "A5", "A9"],
            "BREAKOUT":          ["C1", "A2", "C3", "A4", "A5", "A9"],
            "KNOWLEDGE_MATCH":   ["C3", "A4", "A5", "A9"],
            "UNCERTAIN":         ["C1", "A1", "A2", "A4", "A5", "A9"],
        }
        return chain_map.get(intent_type, ["C1", "A1", "A2", "A4", "A5", "A9"])
