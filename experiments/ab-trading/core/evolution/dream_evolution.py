#!/usr/bin/env python3
"""
做梦部外部反思进化模块
基于dream-oneirology技能的潜意识层外部视角
通过梦境解析、潜意识探测、反事实推演等方式发现被系统忽视的机会
"""
import json, os, time
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timezone

from .evolution_engine import EvolutionEngine, EvolutionSource
from .backtest_engine import SimpleBacktestEngine

BASE_DIR = Path(__file__).parent.parent.parent


class DreamOneirologyEvolution:
    """
    做梦部外部反思进化 - 潜意识层外部视角

    核心机制：
    1. 梦境解析：分析决策中的"潜在内容"，发现被压制的判断
    2. 潜意识探测：提取系统"想说但没说"的判断
    3. 反事实推演：对过去决策的替代路径推演
    4. 四象限情景预言：乐观/中性/悲观/被忽视情景分析
    """

    def __init__(self, engine: EvolutionEngine):
        self.engine = engine
        self.backtest = SimpleBacktestEngine()
        self.dream_log = BASE_DIR / "data" / "evolution" / "dream_journal.json"
        self.dream_log.parent.mkdir(parents=True, exist_ok=True)

    def run_dream_analysis(self, memory: Dict, recent_decisions: List[Dict]) -> Dict:
        """
        执行做梦部分析流程

        Args:
            memory: 当前记忆数据
            recent_decisions: 近期决策记录

        Returns:
            梦境分析报告
        """
        print("[做梦部进化] 开始潜意识层分析...")

        report = {
            "dream_id": f"dream_{int(time.time())}",
            "timestamp": self._now_iso(),
            "manifest_content": self._extract_manifest_content(recent_decisions),
            "latent_content": {},
            "subconscious_snapshot": {},
            "counterfactual_analysis": [],
            "four_quadrant_prophecy": {},
            "evolution_proposals": [],
        }

        report["latent_content"] = self._analyze_latent_content(recent_decisions, memory)

        report["subconscious_snapshot"] = self._probe_subconscious(recent_decisions, memory)

        report["counterfactual_analysis"] = self._counterfactual_reasoning(recent_decisions, memory)

        report["four_quadrant_prophecy"] = self._generate_four_quadrant_prophecy(memory)

        proposals = self._generate_dream_proposals(report, memory)
        report["evolution_proposals"] = proposals

        self._save_dream(report)

        print(f"[做梦部进化] 分析完成: 发现{len(proposals)}个进化提议")
        return report

    def _extract_manifest_content(self, decisions: List[Dict]) -> Dict:
        """提取显性内容（决策的表面理由）"""
        if not decisions:
            return {"total_decisions": 0, "action_distribution": {}}

        actions = {}
        reasons = []
        for d in decisions:
            action = d.get("action", "HOLD")
            actions[action] = actions.get(action, 0) + 1
            rationale = d.get("decision_rationale", "")
            if rationale:
                reasons.append(rationale[:100])

        return {
            "total_decisions": len(decisions),
            "action_distribution": actions,
            "common_reasons": reasons[:5],
        }

    def _analyze_latent_content(self, decisions: List[Dict], memory: Dict) -> Dict:
        """
        分析潜在内容（被压制的判断）
        应用弗洛伊德五种梦的工作机制：凝缩、移置、象征、二次修正、投射
        """
        latent = {
            "condensation": [],
            "displacement": [],
            "symbolism": [],
            "secondary_revision": [],
            "projection": [],
        }

        if not decisions:
            return latent

        hold_decisions = [d for d in decisions if d.get("action") == "HOLD"]
        hold_ratio = len(hold_decisions) / len(decisions) if decisions else 0

        if hold_ratio > 0.7:
            latent["condensation"].append(
                "过度凝缩：多维分析被压缩为单一的'观望'结论，丢失了维度间的张力"
            )

        reasons = [d.get("decision_rationale", "") for d in hold_decisions]
        volume_related = sum(1 for r in reasons if "量" in r or "vol" in r.lower())
        if volume_related / len(reasons) > 0.5 if reasons else False:
            latent["displacement"].append(
                "移置效应：对亏损的恐惧被移置为'成交量不足'的理由，真正的焦虑是怕亏损"
            )

        rsi_based = sum(1 for d in decisions if "RSI" in d.get("decision_rationale", ""))
        if rsi_based > 0:
            latent["symbolism"].append(
                "象征作用：RSI指标被当作市场状态的象征，但可能只是表象而非本质"
            )

        external_attribution = sum(
            1 for r in reasons
            if "市场" in r or "外部" in r or "等待" in r
        )
        if external_attribution / len(reasons) > 0.6 if reasons else False:
            latent["projection"].append(
                "投射机制：将内部的不确定性投射为'市场不好'，真正的问题是系统缺乏信心"
            )

        if len(hold_decisions) >= 3:
            latent["compulsive_repetition"] = (
                "强迫性重复：连续HOLD可能不是理性判断，而是创伤性重复（之前亏损的阴影）"
            )

        return latent

    def _probe_subconscious(self, decisions: List[Dict], memory: Dict) -> Dict:
        """
        潜意识探测 - 提取系统"想说但没说"的判断
        """
        subconscious = {
            "suppressed_signals": [],
            "dimensions_conflict": [],
            "true_reason_guess": "",
        }

        if not decisions:
            return subconscious

        for d in decisions:
            scores = d.get("per_coin_scores", {})
            if scores:
                high_score_coins = [
                    coin for coin, info in scores.items()
                    if info.get("score", 0) > 55 and info.get("direction") != "HOLD"
                ]
                if high_score_coins and d.get("action") == "HOLD":
                    subconscious["suppressed_signals"].append({
                        "cycle": d.get("cycle_id", "unknown"),
                        "suppressed_coins": high_score_coins,
                        "final_action": "HOLD",
                    })

        hold_streak = memory.get("hold_streak", 0)
        if hold_streak >= 5:
            subconscious["true_reason_guess"] = (
                f"连续{hold_streak}轮HOLD，可能不是市场没有机会，"
                "而是系统被恐惧情绪控制，不敢承担任何风险"
            )

        return subconscious

    def _counterfactual_reasoning(self, decisions: List[Dict], memory: Dict) -> List[Dict]:
        """
        反事实推演 - 对过去决策的替代路径分析
        """
        results = []

        if not decisions:
            return results

        hold_decisions = [d for d in decisions if d.get("action") == "HOLD"][:5]

        for d in hold_decisions:
            scores = d.get("per_coin_scores", {})
            if not scores:
                continue

            best_coin = max(
                scores.keys(),
                key=lambda k: scores[k].get("score", 0),
                default=None,
            )
            if not best_coin:
                continue

            best_info = scores[best_coin]
            if best_info.get("score", 0) < 50:
                continue

            results.append({
                "cycle": d.get("cycle_id", "unknown"),
                "actual_decision": "HOLD",
                "counterfactual_choice": best_coin,
                "counterfactual_direction": best_info.get("direction", "LONG"),
                "counterfactual_score": best_info.get("score", 0),
                "potential_gain_loss": "UNKNOWN",
                "reflection": f"如果当时选择{best_coin} {best_info.get('direction')}，结果会怎样？",
            })

        return results

    def _generate_four_quadrant_prophecy(self, memory: Dict) -> Dict:
        """
        四象限情景预言矩阵
        乐观/中性/悲观/被忽视
        """
        prophecy = {
            "optimistic": {
                "probability": 0.10,
                "trigger": "BTC放量突破$70,000，市场情绪转向狂热",
                "expected_move": "+15% ~ +25%",
                "system_action": "加仓追击，移动止损锁定利润",
            },
            "neutral": {
                "probability": 0.35,
                "trigger": "BTC在$60,000-$68,000区间震荡，成交量维持低位",
                "expected_move": "-5% ~ +5%",
                "system_action": "区间操作，高抛低吸",
            },
            "pessimistic": {
                "probability": 0.35,
                "trigger": "宏观利空或大型持有者抛售，BTC跌破$58,000支撑",
                "expected_move": "-10% ~ -20%",
                "system_action": "做空或持币观望，严格止损",
            },
            "neglected": {
                "probability": 0.20,
                "trigger": "山寨币独立行情，BTC横盘但小币种暴涨50%+",
                "expected_move": "BTC ±5%, 山寨 +30% ~ +100%",
                "system_action": "配置小币种，捕捉Beta行情",
            },
        }
        return prophecy

    def _generate_dream_proposals(self, report: Dict, memory: Dict) -> List[Dict]:
        """从梦境分析生成进化提议"""
        proposals = []

        latent = report.get("latent_content", {})
        hold_streak = memory.get("hold_streak", 0)

        if latent.get("compulsive_repetition") or hold_streak >= 7:
            proposals.append(
                self.engine.propose_evolution(
                    source=EvolutionSource.DREAM_ONEIROLOGY,
                    title="强制打破强迫性重复 - 提高RSI信号权重",
                    description="系统陷入连续HOLD的强迫性重复，需要改变决策权重。建议提高RSI超买超卖信号的权重，当RSI<35或>65时强制入场。",
                    strategy_params={
                        "rsi_oversold": 35,
                        "rsi_overbought": 65,
                    },
                    rationale="潜意识分析显示连续HOLD是创伤性重复，需要打破这种模式。RSI极值信号是客观的入场依据。",
                    priority="high",
                )
            )

        if len(latent.get("displacement", [])) > 0:
            proposals.append(
                self.engine.propose_evolution(
                    source=EvolutionSource.DREAM_ONEIROLOGY,
                    title="降低量比要求 - 克服量能焦虑",
                    description="对成交量的过度重视可能是对亏损恐惧的移置。建议将量比阈值从1.2降至0.9，不再将成交量作为必要条件。",
                    strategy_params={"volume_threshold": 0.9},
                    rationale="移置效应：恐惧被移置为'成交量不足'。纯价格行为也可以产生有效信号。",
                    priority="medium",
                )
            )

        prophecy = report.get("four_quadrant_prophecy", {})
        if prophecy.get("neglected", {}).get("probability", 0) >= 0.15:
            proposals.append(
                self.engine.propose_evolution(
                    source=EvolutionSource.DREAM_ONEIROLOGY,
                    title="扩大山寨币配置 - 捕捉被忽视的机会",
                    description="被忽视情景（山寨币独立行情）概率20%，但当前系统主要关注BTC/ETH。建议扩大交易币种范围，增加小币种权重。",
                    strategy_params={"use_ema_cross": True},
                    rationale="四象限分析显示被忽视情景值得重视，山寨币行情往往在BTC横盘时发生",
                    priority="medium",
                )
            )

        return proposals

    def get_dream_history(self, limit: int = 10) -> List[Dict]:
        """获取梦境历史"""
        try:
            if self.dream_log.exists():
                with open(self.dream_log) as f:
                    log = json.load(f)
                return log.get("dreams", [])[-limit:]
        except Exception:
            pass
        return []

    def _save_dream(self, report: Dict):
        """保存梦境报告"""
        try:
            log = {"dreams": []}
            if self.dream_log.exists():
                with open(self.dream_log) as f:
                    log = json.load(f)
            log["dreams"].append(report)
            if len(log["dreams"]) > 50:
                log["dreams"] = log["dreams"][-50:]
            with open(self.dream_log, "w") as f:
                json.dump(log, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()
