#!/usr/bin/env python3
"""
目标提取器 (Objective Extractor)

位置: experiments/ab-trading/core/intent_engine/layer1_intent/objective_extractor.py

Layer 1: 收敛 —— 从混沌到单点
从用户自然语言、市场数据、信号等多源输入中，收敛出一个清晰的单点目标。
"""

import re
from typing import Dict, List, Optional, Any

from ..types import Objective
from .objective_types import OBJECTIVE_TYPES, search_objective_types


class ObjectiveExtractor:
    """
    目标提取器

    收敛算法：
    Phase 1: 信号收集（NLP解析 + 市场打分 + 上下文匹配）
    Phase 2: 多源融合（加权投票 + 冲突消解）
    Phase 3: 收敛决策（确认输出 / 发起澄清 / 拒绝）
    """

    def __init__(self):
        self.objective_types = OBJECTIVE_TYPES

    def extract(
        self,
        user_message: Optional[str] = None,
        mkt_data: Optional[Dict] = None,
        signals: Optional[List[Dict]] = None,
        context: Optional[Dict] = None,
    ) -> Objective:
        """
        从多源输入中提取目标

        Args:
            user_message: 用户自然语言输入
            mkt_data: 市场数据
            signals: 信号列表
            context: 上下文信息

        Returns:
            Objective（单点目标）
        """
        objective = Objective()
        objective.source = self._determine_source(user_message, mkt_data, signals)

        scores = {}

        if user_message:
            nl_scores, keywords = self._score_by_nlp(user_message)
            objective.extracted_keywords = keywords
            for obj_type, score in nl_scores.items():
                scores[obj_type] = scores.get(obj_type, 0) + score * 0.9

        if mkt_data:
            mkt_scores = self._score_by_market(mkt_data)
            for obj_type, score in mkt_scores.items():
                scores[obj_type] = scores.get(obj_type, 0) + score * 0.15

        if signals:
            sig_scores = self._score_by_signals(signals)
            for obj_type, score in sig_scores.items():
                scores[obj_type] = scores.get(obj_type, 0) + score * 0.05

        if not scores:
            objective.confidence = 0.0
            objective.clarify_needed = True
            objective.clarify_question = "请问您需要什么帮助？"
            return objective

        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        best_type, best_score = sorted_scores[0]

        second_score = sorted_scores[1][1] if len(sorted_scores) > 1 else 0
        score_gap = best_score - second_score

        objective.type = best_type
        objective.confidence = min(best_score, 1.0)

        obj_def = self.objective_types.get(best_type, {})
        objective.title = obj_def.get('name', best_type)
        objective.domain = obj_def.get('domain', '')
        objective.complexity = obj_def.get('complexity', 'standard')
        objective.priority = obj_def.get('priority', 5)
        objective.description = obj_def.get('description', '')

        if best_score < 0.25:
            objective.clarify_needed = True
            objective.clarify_question = f"您是想进行「{objective.title}」吗？"
            objective.clarify_options = [
                {'label': '是的', 'value': 'confirm'},
                {'label': '不是', 'value': 'reject'},
            ]
        elif score_gap < 0.03 and len(sorted_scores) > 1:
            top_types = [t for t, s in sorted_scores[:3]]
            objective.clarify_needed = True
            objective.clarify_question = "请问您的需求更接近以下哪个？"
            objective.clarify_options = [
                {'label': self.objective_types.get(t, {}).get('name', t), 'value': t}
                for t in top_types
            ]

        if obj_def.get('default_clarify_needed', False) and not objective.clarify_needed:
            objective.clarify_needed = True
            objective.clarify_question = "请问有什么具体要求吗？"

        return objective

    def _determine_source(
        self,
        user_message: Optional[str],
        mkt_data: Optional[Dict],
        signals: Optional[List[Dict]],
    ) -> str:
        if user_message:
            return 'nl'
        elif signals:
            return 'signal'
        elif mkt_data:
            return 'market'
        return 'context'

    def _score_by_nlp(self, text: str) -> tuple:
        """
        NLP解析：基于关键词匹配打分

        打分策略：
        - 只要有一个关键词匹配，就有基础分（0.5）
        - 匹配的关键词越多，分越高
        - 长关键词（更独特）权重更高
        - 唯一匹配关键词（只在一个类型出现）有额外加成

        Returns:
            (scores_dict, keywords_list)
        """
        scores = {}
        matched_keywords = []
        kw_match_count = {}

        text_lower = text.lower()

        # 第一轮：找出所有匹配的关键词，统计每个关键词被多少个类型匹配
        all_matches = {}
        for obj_type, obj_def in self.objective_types.items():
            keywords = obj_def.get('keywords', [])
            obj_matches = []
            for kw in keywords:
                kw_lower = kw.lower()
                if kw_lower in text_lower:
                    obj_matches.append(kw)
                    kw_match_count[kw_lower] = kw_match_count.get(kw_lower, 0) + 1
            if obj_matches:
                all_matches[obj_type] = obj_matches

        # 第二轮：计算得分，唯一关键词权重更高
        for obj_type, match_keywords in all_matches.items():
            match_count = len(match_keywords)
            match_weight = 0.0
            unique_count = 0
            max_kw_len = 0

            for kw in match_keywords:
                kw_lower = kw.lower()
                kw_len = len(kw_lower)
                is_unique = kw_match_count.get(kw_lower, 0) == 1

                if is_unique:
                    unique_count += 1
                    kw_weight = kw_len / 2.0
                else:
                    kw_weight = kw_len / 4.0

                match_weight += kw_weight
                if kw_len > max_kw_len:
                    max_kw_len = kw_len

            base_score = 0.5
            count_bonus = min(match_count * 0.08, 0.2)
            weight_bonus = min(match_weight * 0.06, 0.25)
            unique_bonus = min(unique_count * 0.1, 0.25)
            score = min(base_score + count_bonus + weight_bonus + unique_bonus, 1.0)

            scores[obj_type] = score
            matched_keywords.extend(match_keywords)

        matched_keywords = list(set(matched_keywords))
        return scores, matched_keywords

    def _score_by_market(self, mkt_data: Dict) -> Dict[str, float]:
        """
        市场数据打分：根据市场状态匹配合适的目标

        简单规则：
        - 价格大幅变动 → trend_analysis
        - 成交量异常 → deep_analysis
        """
        scores = {}

        price_change = mkt_data.get('price_change_pct', 0)
        volume_change = mkt_data.get('volume_change_pct', 0)

        if abs(price_change) > 5:
            scores['trend_analysis'] = 0.6
            if abs(price_change) > 10:
                scores['deep_analysis'] = 0.5

        if abs(volume_change) > 50:
            scores['deep_analysis'] = scores.get('deep_analysis', 0) + 0.3

        return scores

    def _score_by_signals(self, signals: List[Dict]) -> Dict[str, float]:
        """
        信号打分：根据信号类型匹配合适的目标
        """
        scores = {}

        for sig in signals:
            sig_type = sig.get('type', '')
            sig_strength = sig.get('strength', 0.5)

            if sig_type in ['technical_breakout', 'trend_change']:
                scores['trend_analysis'] = scores.get('trend_analysis', 0) + sig_strength * 0.3
            elif sig_type in ['rsi_oversold', 'rsi_overbought', 'macd_cross']:
                scores['trading_decision'] = scores.get('trading_decision', 0) + sig_strength * 0.4
            elif sig_type in ['risk_alert', 'stop_loss_trigger']:
                scores['risk_assessment'] = scores.get('risk_assessment', 0) + sig_strength * 0.5
                scores['exit_evaluation'] = scores.get('exit_evaluation', 0) + sig_strength * 0.4

        return scores
