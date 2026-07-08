#!/usr/bin/env python3
"""
dream-strategy-designer v2.1 - 战略制定核心引擎
基于A1调研+A2分析，执行特征蒸馏、历史模式匹配，生成战略指令
支持多币种(BTC/ETH/SOL)和多工具(网格/马丁/DCA/做空/套利)
"""

import json
import yaml
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

# ============================================================
# 战略记忆库路径
# ============================================================

STRATEGY_LIBRARY_PATH = Path.home() / ".workbuddy" / "strategy-library"
TEMPLATES_FILE = STRATEGY_LIBRARY_PATH / "strategy_templates.yaml"
CASES_FILE = STRATEGY_LIBRARY_PATH / "historical_cases.yaml"
MASTERS_FILE = STRATEGY_LIBRARY_PATH / "master_playbooks.yaml"
TOOLS_FILE = STRATEGY_LIBRARY_PATH / "strategy_tools.yaml"  # 新增:交易工具库


class FeatureDistiller:
    """特征蒸馏引擎 - 从A1+A2输出中提炼市场特征"""
    
    @staticmethod
    def distill(a1_report: Dict, a2_analysis: Dict) -> Dict:
        """
        蒸馏市场特征向量
        
        Args:
            a1_report: A1调研报告
            a2_analysis: A2第一性原理分析
            
        Returns:
            feature_vector: 市场特征向量
        """
        # 1. 方向特征
        direction = a2_analysis.get("synthesis", {}).get("least_resistance_path", "NEUTRAL")
        direction_confidence = a2_analysis.get("synthesis", {}).get("path_confidence", 0.5)
        
        # 2. 动能特征
        trend_analysis = a2_analysis.get("trend_analysis", {})
        momentum = trend_analysis.get("trend_momentum", "stable")
        
        # 3. 阻力特征
        resistance = a2_analysis.get("resistance_analysis", {})
        resistance_path = resistance.get("resistance_minimum_path", "NEUTRAL")
        
        # 4. 波动特征
        market_state = a1_report.get("market_state", {})
        vol_regime = market_state.get("vol_regime", "unknown")
        vol_mapping = {"high": "HIGH", "low": "LOW", "unknown": "NORMAL"}
        volatility = vol_mapping.get(vol_regime, "NORMAL")
        
        # 5. 情绪特征
        sentiment_score = a1_report.get("market_state", {}).get("fear_greed", 50)
        sentiment_mapping = {
            range(0, 25): "EXTREME_FEAR",
            range(25, 45): "FEAR",
            range(45, 55): "NEUTRAL",
            range(55, 75): "GREED",
            range(75, 101): "EXTREME_GREED"
        }
        for r, label in sentiment_mapping.items():
            if sentiment_score in r:
                sentiment = label
                break
        else:
            sentiment = "NEUTRAL"
        
        # 6. 资金特征
        onchain = a1_report.get("onchain_signals", {})
        capital = onchain.get("prediction_bias", "neutral")
        
        # 7. 宏观特征
        macro = a1_report.get("macro_snapshot", {})
        macro_bias = macro.get("sentiment", "neutral")
        
        # 8. Regime
        regime = a2_analysis.get("market_regime_classification", {}).get("regime", "UNKNOWN")
        
        # 9. 主要矛盾
        brain = a2_analysis.get("brain_analysis", {})
        contradiction = brain.get("main_contradiction", {})
        primary_contradiction = contradiction.get("primary", "")
        contradiction_intensity = "LOW"
        if primary_contradiction:
            # 简化判断
            if "vs" in primary_contradiction:
                contradiction_intensity = "HIGH"
            else:
                contradiction_intensity = "MEDIUM"
        
        feature_vector = {
            "direction": direction,
            "direction_confidence": direction_confidence,
            "momentum": momentum.upper() if momentum else "STABLE",
            "resistance": resistance_path,
            "volatility": volatility,
            "sentiment": sentiment,
            "capital": capital.upper() if capital else "NEUTRAL",
            "macro": macro_bias.upper() if macro_bias else "NEUTRAL",
            "regime": regime,
            "contradiction": {
                "primary": primary_contradiction,
                "intensity": contradiction_intensity
            }
        }
        
        return feature_vector


class HistoricalMatcher:
    """历史模式匹配引擎 - 搜索战略记忆库"""

    def __init__(self):
        self.templates = self._load_templates()
        self.cases = self._load_cases()
        self.masters = self._load_masters()
        self.tools = self._load_tools()  # 新增:加载交易工具库

    def _load_templates(self) -> Dict:
        """加载战略模板"""
        if TEMPLATES_FILE.exists():
            with open(TEMPLATES_FILE, 'r') as f:
                return yaml.safe_load(f)
        return {"strategy_templates": [], "trend_strategies": [], "defensive_strategies": []}

    def _load_cases(self) -> Dict:
        """加载历史案例"""
        if CASES_FILE.exists():
            with open(CASES_FILE, 'r') as f:
                return yaml.safe_load(f)
        return {"historical_cases": []}

    def _load_masters(self) -> Dict:
        """加载大师模型"""
        if MASTERS_FILE.exists():
            with open(MASTERS_FILE, 'r') as f:
                return yaml.safe_load(f)
        return {"master_cognitive_models": {}, "master_selection_matrix": {}}

    def _load_tools(self) -> Dict:
        """加载战略交易工具库"""
        if TOOLS_FILE.exists():
            with open(TOOLS_FILE, 'r') as f:
                return yaml.safe_load(f)
        return {"trading_tools": {}, "coin_characteristics": {}, "tool_selection_matrix": {}}

    def find_similar_cases(self, feature_vector: Dict, limit: int = 3) -> List[Dict]:
        """
        查找相似的历史案例
        
        Args:
            feature_vector: 当前特征向量
            limit: 返回数量
            
        Returns:
            similar_cases: 相似案例列表
        """
        cases = self.cases.get("historical_cases", [])
        scored_cases = []
        
        for case in cases:
            score = 0
            case_fv = case.get("feature_vector", {})
            
            # Regime匹配 (最重要)
            if case_fv.get("regime") == feature_vector.get("regime"):
                score += 40
            
            # Direction匹配
            if case_fv.get("direction") == feature_vector.get("direction"):
                score += 25
            
            # Momentum匹配
            if case_fv.get("momentum") == feature_vector.get("momentum"):
                score += 15
            
            # Volatility匹配
            if case_fv.get("volatility") == feature_vector.get("volatility"):
                score += 10
            
            # Sentiment匹配
            if case_fv.get("sentiment") == feature_vector.get("sentiment"):
                score += 10
            
            scored_cases.append({
                "case_id": case.get("case_id"),
                "date": case.get("date"),
                "score": score / 100,
                "regime": case_fv.get("regime"),
                "direction": case_fv.get("direction"),
                "strategy": case.get("strategy_selected", {}).get("template_id"),
                "outcome": case.get("execution_result"),
                "pnl_pct": case.get("pnl_pct"),
                "lessons": case.get("lessons_learned", [])
            })
        
        # 按相似度排序
        scored_cases.sort(key=lambda x: x["score"], reverse=True)
        return scored_cases[:limit]
    
    def match_templates(self, feature_vector: Dict) -> List[Dict]:
        """
        匹配战略模板

        Args:
            feature_vector: 当前特征向量

        Returns:
            matched_templates: 匹配的战略模板
        """
        all_templates = []

        # 收集所有模板 - v2.1新增更多类别
        for cat in ["trend_strategies", "defensive_strategies", "breakout_strategies",
                    "risk_management_strategies", "contrarian_strategies",
                    "grid_strategies", "martingale_strategies", "dca_strategies",  # 新增
                    "short_strategies", "arbitrage_strategies", "swing_strategies",  # 新增
                    "trailing_strategies"]:  # 新增
            all_templates.extend(self.templates.get(cat, []))
        
        regime = feature_vector.get("regime")
        direction = feature_vector.get("direction")
        
        matched = []
        for template in all_templates:
            match_score = 0
            match_reasons = []
            
            # Regime匹配
            if regime in template.get("regime_applicability", []):
                match_score += 50
                match_reasons.append(f"regime_match:{regime}")
            
            # Direction匹配
            template_dir = template.get("direction_bias", "NEUTRAL")
            if template_dir == "BOTH" or template_dir == direction:
                match_score += 30
                match_reasons.append(f"direction_match:{direction}")
            
            # 检查排除条件
            exclusions = template.get("exclusion_conditions", [])
            excluded = False
            for excl in exclusions:
                excl_cond = excl.get("condition", "")
                excl_action = excl.get("action", "")
                # 简化检查
                if "EXTREME" in str(feature_vector.get("sentiment", "")) and "extreme" in excl_cond.lower():
                    excluded = True
                    break
            
            if not excluded and match_score > 0:
                matched.append({
                    "template_id": template.get("id"),
                    "name": template.get("name"),
                    "source": template.get("source"),
                    "match_score": match_score / 100,
                    "match_reasons": match_reasons,
                    "parameters": template.get("parameters", {}),
                    "execution_rhythm": template.get("execution_rhythm", {})
                })
        
        # 按匹配度排序
        matched.sort(key=lambda x: x["match_score"], reverse=True)
        return matched[:5]
    
    def get_master_recommendations(self, feature_vector: Dict) -> List[Dict]:
        """
        获取大师建议
        
        Args:
            feature_vector: 当前特征向量
            
        Returns:
            recommendations: 大师建议列表
        """
        regime = feature_vector.get("regime")
        masters = self.masters.get("master_cognitive_models", {})
        selection_matrix = self.masters.get("master_selection_matrix", {}).get("by_regime", {})
        
        if regime not in selection_matrix:
            return []
        
        selection = selection_matrix[regime]
        recommendations = []
        
        for master_id in [selection.get("primary_master"), selection.get("secondary_master")]:
            if master_id and master_id in masters:
                master = masters[master_id]
                recommendations.append({
                    "master_id": master_id,
                    "master_name": master.get("name"),
                    "regime_fit": master.get("regime_fits", {}).get(regime, 0),
                    "hard_bans": master.get("hard_bans", []),
                    "left_brain_rules": master.get("left_brain", {}).get("rules", [])[:3],
                    "right_brain_patterns": master.get("right_brain", {}).get("patterns", [])[:3]
                })
        
        return recommendations

    def recommend_coins(self, feature_vector: Dict) -> List[Dict]:
        """
        推荐适合当前市场的币种

        Args:
            feature_vector: 当前特征向量

        Returns:
            recommended_coins: 推荐的币种列表
        """
        regime = feature_vector.get("regime")
        volatility = feature_vector.get("volatility")
        coins = self.tools.get("coin_characteristics", {})
        
        recommendations = []
        for coin_id, coin_info in coins.items():
            score = 0
            best_regimes = coin_info.get("best_regimes", [])
            
            # Regime匹配
            if regime in best_regimes:
                score += 50
            
            # 波动率适配
            coin_vol_rank = coin_info.get("volatility_rank", 3)
            vol_mapping = {"HIGH": 4, "NORMAL": 3, "LOW": 1}
            target_vol = vol_mapping.get(volatility, 3)
            if abs(coin_vol_rank - target_vol) <= 1:
                score += 30
            
            if score > 0:
                recommendations.append({
                    "coin_id": coin_id,
                    "coin_name": coin_info.get("name"),
                    "score": score / 100,
                    "max_leverage": coin_info.get("max_leverage"),
                    "grid_spacing_min": coin_info.get("grid_spacing_min"),
                    "recommended_tools": coin_info.get("recommended_tools", [])
                })
        
        # 按评分排序
        recommendations.sort(key=lambda x: x["score"], reverse=True)
        return recommendations[:3]  # 最多推荐3个币种

    def recommend_tools(self, feature_vector: Dict, directive_bias: str) -> List[Dict]:
        """
        推荐适合当前市场状态的交易工具

        Args:
            feature_vector: 当前特征向量
            directive_bias: 指令方向

        Returns:
            recommended_tools: 推荐的工具列表
        """
        regime = feature_vector.get("regime")
        direction = feature_vector.get("direction")
        tools = self.tools.get("trading_tools", {})
        selection_matrix = self.tools.get("tool_selection_matrix", {}).get("by_regime", {})

        # 按regime获取推荐工具
        regime_recs = selection_matrix.get(regime, {})
        primary_tools = regime_recs.get("primary_tools", [])
        avoid_tools = regime_recs.get("avoid_tools", [])

        recommendations = []
        for tool_id in primary_tools:
            if tool_id in tools and tool_id not in avoid_tools:
                tool = tools[tool_id]
                # 检查方向匹配 - "适用条件"是一个列表
                conditions = tool.get("适用条件", [])
                tool_dir = "NEUTRAL"
                for cond in conditions:
                    if isinstance(cond, dict) and "direction" in cond:
                        tool_dir = cond.get("direction", "NEUTRAL")
                        break
                if tool_dir in ["BOTH", "NEUTRAL", directive_bias]:
                    recommendations.append({
                        "tool_id": tool_id,
                        "tool_name": tool.get("name"),
                        "category": tool.get("category"),
                        "parameters": tool.get("参数配置", {}),
                        "risk_control": tool.get("风险控制", []),
                        "supported_coins": tool.get("supported_coins", [])
                    })

        return recommendations[:3]  # 最多推荐3个工具


class StrategySynthesizer:
    """战略合成引擎 - 生成战略指令"""

    def __init__(self):
        self.matcher = HistoricalMatcher()
    
    def synthesize(
        self,
        a1_report: Dict,
        a2_analysis: Dict,
        feature_vector: Dict,
        similar_cases: List[Dict],
        matched_templates: List[Dict],
        master_recommendations: List[Dict],
        phase0_research: Optional[Dict] = None  # 新增:Phase0调研结果
    ) -> Dict:
        """
        合成战略指令

        Args:
            a1_report: A1调研报告
            a2_analysis: A2分析结果
            feature_vector: 特征向量
            similar_cases: 相似案例
            matched_templates: 匹配模板
            master_recommendations: 大师建议
            phase0_research: Phase0战略调研结果

        Returns:
            strategy_directive: 战略指令
        """
        # 1. 选择最佳模板
        primary_template = matched_templates[0] if matched_templates else None

        # 2. 确定指令方向
        regime = feature_vector.get("regime")
        direction = feature_vector.get("direction")
        contradiction_intensity = feature_vector.get("contradiction", {}).get("intensity", "LOW")

        # 矛盾处理
        if contradiction_intensity == "HIGH":
            directive_bias = "WAIT"
            position_modifier = 0.0
        elif contradiction_intensity == "MEDIUM":
            directive_bias = "REDUCE"
            position_modifier = 0.25
        else:
            # 正常决策
            directive_bias = self._determine_bias(regime, direction, feature_vector)
            position_modifier = self._determine_position_modifier(regime, direction, similar_cases)

        # 3. 杠杆上限
        leverage_cap = self._determine_leverage(regime, directive_bias, feature_vector)

        # 4. 推荐币种 ← 新增
        recommended_coins = self.matcher.recommend_coins(feature_vector)
        target_coins = [c["coin_id"] for c in recommended_coins[:2]]  # 最多2个币种

        # 5. 推荐工具 ← 新增
        recommended_tools = self.matcher.recommend_tools(feature_vector, directive_bias)

        # 6. 构建战略指令
        directive = {
            "directive_id": f"dir_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}",
            "directive_bias": directive_bias,
            "position_modifier": position_modifier,
            "leverage_cap": leverage_cap,
            "target_coins": target_coins,  # ← 新增:目标币种
            "recommended_tools": [  # ← 新增:推荐工具
                {
                    "tool_id": t["tool_id"],
                    "tool_name": t["tool_name"],
                    "allocation": 0.5 - i * 0.2,  # 递减分配
                    "parameters": t.get("parameters", {})
                }
                for i, t in enumerate(recommended_tools[:2])
            ],
            "matched_strategy": {
                "template_id": primary_template.get("template_id") if primary_template else None,
                "name": primary_template.get("name") if primary_template else "CUSTOM",
                "source": primary_template.get("source") if primary_template else "SYNTHESIZED",
                "match_confidence": primary_template.get("match_score", 0) if primary_template else 0,
                "adaptation_notes": self._generate_adaptation_notes(
                    primary_template, feature_vector, similar_cases
                )
            },
            "entry_conditions": self._extract_entry_conditions(primary_template),
            "exit_conditions": self._extract_exit_conditions(primary_template),
            "risk_rules": self._generate_risk_rules(directive_bias, regime),
            "timing_guidance": self._generate_timing_guidance(regime, feature_vector),
            "contradiction_handling": {
                "primary_contradiction": feature_vector.get("contradiction", {}).get("primary", ""),
                "strategic_response": f"强度{contradiction_intensity}时的战略响应"
            }
        }
        
        # 7. 证据链
        evidence_chain = {
            "phase0_research": phase0_research or {},  # ← 新增:战略调研
            "a1_inputs": {
                "research_summary": a1_report.get("research_report", {}).get("summary", ""),
                "key_findings": a1_report.get("research_report", {}).get("key_insights", [])[:3]
            },
            "a2_inputs": {
                "regime": a2_analysis.get("market_regime_classification", {}).get("regime", ""),
                "least_resistance_path": a2_analysis.get("synthesis", {}).get("least_resistance_path", ""),
                "main_contradiction": feature_vector.get("contradiction", {}).get("primary", "")
            },
            "feature_distillation": feature_vector,
            "historical_matches": {
                "strategy_matches": [t.get("template_id") for t in matched_templates[:3]],
                "master_recommendations": [m.get("master_name") for m in master_recommendations[:2]],
                "similar_cases": [c.get("case_id") for c in similar_cases[:3]],
                "coin_recommendations": [c.get("coin_id") for c in recommended_coins[:2]],  # ← 新增
                "tool_recommendations": [t.get("tool_id") for t in recommended_tools[:2]]  # ← 新增
            },
            "phase6_dream_output": {}  # ← 新增:战略做梦(待Phase6执行后填充)
        }
        
        # 6. 战略理由
        strategic_rationale = {
            "why_this_strategy": self._generate_why_statement(
                directive_bias, primary_template, similar_cases, feature_vector
            ),
            "adaptations_from_classic": self._generate_adaptations(
                primary_template, feature_vector
            ),
            "lessons_applied": self._extract_lessons(similar_cases),
            "contradictions_addressed": [feature_vector.get("contradiction", {}).get("primary", "")]
        }
        
        # 7. 记忆更新标记
        memory_update = {
            "case_to_archive": True,
            "template_updates": self._get_template_updates(directive_bias, similar_cases),
            "lessons_to_record": self._extract_lessons(similar_cases)
        }
        
        return {
            "strategy_directive": directive,
            "evidence_chain": evidence_chain,
            "strategic_rationale": strategic_rationale,
            "memory_update": memory_update,
            "meta": {
                "designer_version": "2.1.0",
                "timestamp": datetime.now().isoformat(),
                "phases_completed": ["调研", "验证", "蒸馏", "匹配", "合成", "归档", "做梦"],
                "processing_time_seconds": 0
            }
        }
    
    def _determine_bias(self, regime: str, direction: str, feature_vector: Dict) -> str:
        """确定指令方向"""
        # 基于regime和direction确定
        if regime in ["TREND_EXHAUSTION", "FALSE_BREAKOUT_RISK", "EXTREME"]:
            return "WAIT"
        elif regime == "RANGE_BOUND":
            return "WAIT"
        elif regime == "BREAKOUT_PENDING":
            if direction == "BULL":
                return "LONG"
            elif direction == "BEAR":
                return "SHORT"
            else:
                return "WAIT"
        elif regime == "TREND_STRONG":
            if direction == "BULL":
                return "LONG"
            elif direction == "BEAR":
                return "SHORT"
            else:
                return "WAIT"
        return "WAIT"
    
    def _determine_position_modifier(
        self, 
        regime: str, 
        direction: str, 
        similar_cases: List[Dict]
    ) -> float:
        """确定仓位修正系数"""
        # 从相似案例学习
        if similar_cases:
            avg_modifier = sum(
                c.get("pnl_pct", 0) > 0 and 0.75 or 0.5 
                for c in similar_cases
            ) / len(similar_cases)
            return avg_modifier
        
        # 默认值
        defaults = {
            "TREND_STRONG": 0.75,
            "BREAKOUT_PENDING": 0.5,
            "RANGE_BOUND": 0.25,
            "TREND_EXHAUSTION": 0.0,
            "FALSE_BREAKOUT_RISK": 0.25,
            "EXTREME": 0.0
        }
        return defaults.get(regime, 0.5)
    
    def _determine_leverage(
        self, 
        regime: str, 
        bias: str, 
        feature_vector: Dict
    ) -> int:
        """确定杠杆上限"""
        if bias in ["WAIT", "SKIP"]:
            return 1
        
        defaults = {
            "TREND_STRONG": 3,
            "BREAKOUT_PENDING": 2,
            "RANGE_BOUND": 2,
            "TREND_EXHAUSTION": 1,
            "FALSE_BREAKOUT_RISK": 1,
            "EXTREME": 1
        }
        return defaults.get(regime, 2)
    
    def _generate_adaptation_notes(
        self, 
        template: Optional[Dict], 
        feature_vector: Dict,
        similar_cases: List[Dict]
    ) -> str:
        """生成适配说明"""
        if not template:
            return "基于当前特征合成"
        
        notes = []
        if similar_cases:
            outcomes = [c.get("outcome") for c in similar_cases]
            if "PROFIT" in outcomes:
                notes.append("参考历史成功案例调整")
            elif "LOSS" in outcomes:
                notes.append("参考历史失败案例谨慎调整")
        
        if feature_vector.get("contradiction", {}).get("intensity") == "HIGH":
            notes.append("矛盾强度高，采用保守参数")
        
        return "; ".join(notes) if notes else "标准参数"
    
    def _extract_entry_conditions(self, template: Optional[Dict]) -> List[Dict]:
        """提取入场条件"""
        if not template:
            return [
                {"type": "trend", "condition": "MA排列确认", "priority": 1},
                {"type": "volume", "condition": "放量确认", "priority": 2}
            ]
        
        conditions = template.get("trigger_conditions", [])
        return [
            {"type": c.get("type", "other"), "condition": c.get("description", ""), "priority": i+1}
            for i, c in enumerate(conditions[:3])
        ]
    
    def _extract_exit_conditions(self, template: Optional[Dict]) -> List[Dict]:
        """提取出场条件"""
        return [
            {"type": "stop_loss", "trigger": "触及止损位", "action": "平仓"},
            {"type": "take_profit", "trigger": "达到目标位", "action": "分批止盈"},
            {"type": "time_stop", "trigger": "超过周期上限", "action": "强制平仓"}
        ]
    
    def _generate_risk_rules(self, bias: str, regime: str) -> List[Dict]:
        """生成风险规则"""
        rules = [
            {"rule": "最大亏损2%", "enforcement": "HARD"},
            {"rule": "杠杆不超过上限", "enforcement": "HARD"}
        ]
        
        if regime == "EXTREME":
            rules.append({"rule": "极端市场降仓50%", "enforcement": "HARD"})
        
        return rules
    
    def _generate_timing_guidance(self, regime: str, feature_vector: Dict) -> str:
        """生成时机指导"""
        timings = {
            "TREND_STRONG": "趋势确认后入场，让利润奔跑",
            "BREAKOUT_PENDING": "突破确认后回踩入场",
            "RANGE_BOUND": "区间上下沿反向操作",
            "TREND_EXHAUSTION": "动能衰竭，观望为主",
            "FALSE_BREAKOUT_RISK": "假突破识别，等待确认",
            "EXTREME": "极端市场，现金为王"
        }
        return timings.get(regime, "等待明确信号")
    
    def _generate_why_statement(
        self, 
        bias: str, 
        template: Optional[Dict],
        similar_cases: List[Dict],
        feature_vector: Dict
    ) -> str:
        """生成选择理由"""
        parts = [f"基于{feature_vector.get('regime')}regime判断"]
        
        if template:
            parts.append(f"适配{template.get('name')}({template.get('source')})")
        
        if similar_cases:
            outcomes = [c.get("outcome") for c in similar_cases]
            if "PROFIT" in outcomes:
                parts.append("参考历史成功案例")
        
        return "，".join(parts)
    
    def _generate_adaptations(
        self, 
        template: Optional[Dict], 
        feature_vector: Dict
    ) -> List[str]:
        """生成调整说明"""
        adaptations = []
        
        if template:
            adaptations.append(f"采用{template.get('source')}经典方法")
        
        if feature_vector.get("volatility") == "HIGH":
            adaptations.append("波动率高，收紧止损")
        
        if feature_vector.get("sentiment") in ["EXTREME_FEAR", "EXTREME_GREED"]:
            adaptations.append("情绪极端，降低仓位")
        
        return adaptations
    
    def _extract_lessons(self, similar_cases: List[Dict]) -> List[str]:
        """提取教训"""
        lessons = []
        for case in similar_cases[:2]:
            lessons.extend(case.get("lessons", [])[:2])
        return list(set(lessons))[:3]
    
    def _get_template_updates(
        self, 
        bias: str, 
        similar_cases: List[Dict]
    ) -> List[str]:
        """获取模板更新标记"""
        updates = []
        for case in similar_cases:
            if case.get("outcome") == "PROFIT":
                updates.append(f"SUCCESS:{case.get('strategy')}")
            elif case.get("outcome") == "LOSS":
                updates.append(f"FAILURE:{case.get('strategy')}")
        return updates


class StrategyDesigner:
    """战略制定主类 - 整合所有模块"""
    
    def __init__(self):
        self.distiller = FeatureDistiller()
        self.matcher = HistoricalMatcher()
        self.synthesizer = StrategySynthesizer()
        self.war_game_simulator = None  # 延迟加载
    
    def _get_war_game_simulator(self):
        """延迟加载沙盘推演模块"""
        if self.war_game_simulator is None:
            try:
                import sys
                sys.path.insert(0, str(Path(__file__).parent))
                from war_game_simulator import WarGameSimulator
                self.war_game_simulator = WarGameSimulator()
            except ImportError:
                self.war_game_simulator = None
        return self.war_game_simulator
    
    def design(
        self,
        a1_report: Dict,
        a2_analysis: Dict,
        run_phase7: bool = True  # 新增:是否执行Phase7
    ) -> Dict:
        """
        执行完整战略制定流程
        
        Args:
            a1_report: A1调研报告
            a2_analysis: A2第一性原理分析
            run_phase7: 是否执行Phase7沙盘推演(默认True)
            
        Returns:
            result: 包含战略指令和证据链的完整结果
        """
        start_time = datetime.now()
        
        # Phase 1: 验证输入
        validation = self._validate_inputs(a1_report, a2_analysis)
        if not validation["valid"]:
            return {
                "error": "输入验证失败",
                "missing_fields": validation["missing"]
            }
        
        # Phase 2: 特征蒸馏
        feature_vector = self.distiller.distill(a1_report, a2_analysis)
        
        # Phase 3: 历史模式匹配
        similar_cases = self.matcher.find_similar_cases(feature_vector)
        matched_templates = self.matcher.match_templates(feature_vector)
        master_recommendations = self.matcher.get_master_recommendations(feature_vector)
        
        # Phase 4: 战略合成
        result = self.synthesizer.synthesize(
            a1_report,
            a2_analysis,
            feature_vector,
            similar_cases,
            matched_templates,
            master_recommendations
        )
        
        # Phase 7: 战略沙盘推演 ← 新增
        if run_phase7:
            war_game_result = self._run_phase7_war_game(
                a1_report, a2_analysis, feature_vector, result.get("strategy_directive", {})
            )
            result["phase7_war_game"] = war_game_result
        
        # 计算处理时间
        processing_time = (datetime.now() - start_time).total_seconds()
        result["meta"]["processing_time_seconds"] = processing_time
        result["meta"]["designer_version"] = "2.2.0"  # 更新版本
        
        return result
    
    def _run_phase7_war_game(
        self,
        a1_report: Dict,
        a2_analysis: Dict,
        feature_vector: Dict,
        primary_directive: Dict
    ) -> Dict:
        """执行Phase7战略沙盘推演"""
        simulator = self._get_war_game_simulator()
        if simulator is None:
            return {"error": "沙盘推演模块不可用", "phase7_completed": False}
        
        # 提取关键参数
        market_state = a1_report.get("market_state", {})
        current_price = market_state.get("price", 74000)
        regime = feature_vector.get("regime", "UNKNOWN")
        direction = feature_vector.get("direction", "NEUTRAL")
        
        # 执行沙盘推演
        try:
            war_game_result = simulator.simulate(
                current_price=current_price,
                regime=regime,
                direction=direction,
                feature_vector=feature_vector,
                primary_directive=primary_directive
            )
            
            # 保存到库
            simulator.save_to_library(war_game_result)
            
            # 更新evidence_chain
            war_game_summary = {
                "phase7_completed": True,
                "war_game_id": war_game_result.get("war_game_id"),
                "total_scenarios": war_game_result.get("meta", {}).get("total_scenarios", 0),
                "plans_generated": war_game_result.get("meta", {}).get("plans_generated", 0),
                "probability_plans": [
                    {"plan_id": p.get("plan_id"), "name": p.get("name"), "probability": p.get("probability")}
                    for p in war_game_result.get("probability_plans", [])
                ],
                "black_swan_count": len(war_game_result.get("black_swan_scenarios", [])),
                "extreme_scenario_count": len(war_game_result.get("extreme_scenarios", []))
            }
            
            return war_game_summary
            
        except Exception as e:
            return {
                "phase7_completed": False,
                "error": str(e)
            }
    
    def _validate_inputs(
        self, 
        a1_report: Dict, 
        a2_analysis: Dict
    ) -> Dict:
        """验证输入"""
        required_a1 = ["research_report"]
        required_a2 = ["synthesis", "market_regime_classification", "brain_analysis"]
        
        missing = []
        
        for field in required_a1:
            if field not in a1_report:
                missing.append(f"A1.{field}")
        
        for field in required_a2:
            if field not in a2_analysis:
                missing.append(f"A2.{field}")
        
        return {
            "valid": len(missing) == 0,
            "missing": missing
        }
    
    def archive_case(
        self,
        strategy_directive: Dict,
        feature_vector: Dict,
        execution_result: Optional[Dict] = None
    ) -> bool:
        """
        将案例归档到战略记忆库

        Args:
            strategy_directive: 战略指令
            feature_vector: 特征向量
            execution_result: 执行结果

        Returns:
            success: 是否成功
        """
        case = {
            "case_id": f"EP{int(datetime.now().timestamp())}",
            "date": datetime.now().strftime("%Y-%m-%d"),
            "feature_vector": feature_vector,
            "regime": feature_vector.get("regime"),
            "strategy_selected": {
                "template_id": strategy_directive.get("matched_strategy", {}).get("template_id"),
                "rationale": strategy_directive.get("strategic_rationale", {}).get("why_this_strategy")
            },
            "directive_bias": strategy_directive.get("directive_bias"),
            "position_modifier": strategy_directive.get("position_modifier"),
            "leverage_cap": strategy_directive.get("leverage_cap"),
            "coins_targeted": strategy_directive.get("target_coins", []),  # ← 新增:目标币种
            "tools_used": [t.get("tool_id") for t in strategy_directive.get("recommended_tools", [])]  # ← 新增:使用工具
        }
        
        if execution_result:
            case["execution_result"] = execution_result.get("outcome")
            case["pnl_pct"] = execution_result.get("pnl_pct")
            case["lessons_learned"] = execution_result.get("lessons", [])
        
        # 追加到历史案例
        try:
            with open(CASES_FILE, 'r') as f:
                data = yaml.safe_load(f)
            
            if "historical_cases" not in data:
                data["historical_cases"] = []
            
            data["historical_cases"].insert(0, case)
            data["last_updated"] = datetime.now().isoformat()
            
            with open(CASES_FILE, 'w') as f:
                yaml.dump(data, f, allow_unicode=True)
            
            return True
        except Exception as e:
            print(f"归档失败: {e}")
            return False


def main():
    """测试入口"""
    # 模拟A1+A2输入
    a1_report = {
        "research_report": {
            "summary": "BTC在$74,000附近震荡，突破待确认",
            "key_insights": ["MA多头排列", "ETF净流出", "情绪偏中性"],
            "market_state": {
                "price": 74389.5,
                "regime": "BREAKOUT_PENDING",
                "fear_greed": 52,
                "vol_regime": "normal"
            },
            "macro_snapshot": {"sentiment": "neutral"},
            "onchain_signals": {"prediction_bias": "neutral"}
        }
    }
    
    a2_analysis = {
        "synthesis": {
            "least_resistance_path": "UP",
            "path_confidence": 0.65
        },
        "market_regime_classification": {
            "regime": "BREAKOUT_PENDING"
        },
        "trend_analysis": {
            "trend_momentum": "stable",
            "trend_direction": "BULL"
        },
        "resistance_analysis": {
            "resistance_minimum_path": "UP"
        },
        "brain_analysis": {
            "main_contradiction": {
                "primary": "技术面偏多 vs 宏观不确定",
                "intensity": "MEDIUM"
            }
        }
    }
    
    # 执行战略制定 (包含Phase7)
    print("=" * 60)
    print("执行 Dream-Strategy-Designer v2.2")
    print("包含 Phase7: 战略沙盘推演")
    print("=" * 60)
    
    designer = StrategyDesigner()
    result = designer.design(a1_report, a2_analysis, run_phase7=True)
    
    # 打印结果
    print("\n📋 战略指令:")
    print(json.dumps(result.get("strategy_directive", {}), indent=2, ensure_ascii=False))
    
    # 打印Phase7结果
    if "phase7_war_game" in result:
        phase7 = result["phase7_war_game"]
        print("\n🎯 Phase7 战略沙盘推演:")
        print(f"   推演ID: {phase7.get('war_game_id')}")
        print(f"   生成预案: {phase7.get('plans_generated')}套")
        print(f"   黑天鹅情景: {phase7.get('black_swan_count')}个")
        print(f"   极端情景: {phase7.get('extreme_scenario_count')}个")
        print("\n📊 概率情景预案:")
        for plan in phase7.get("probability_plans", []):
            print(f"   • {plan.get('plan_id')}: {plan.get('name')} ({plan.get('probability')*100}%)")
    else:
        print(f"\n⚠️ Phase7未执行: {result.get('phase7_war_game', {}).get('error')}")
    
    print("\n✅ 战略制定完成")
    print(f"版本: {result.get('meta', {}).get('designer_version')}")
    print(f"处理时间: {result.get('meta', {}).get('processing_time_seconds', 0):.2f}s")


if __name__ == "__main__":
    main()
