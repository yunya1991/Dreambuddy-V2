#!/usr/bin/env python3
"""
Phase 7: 战略沙盘推演引擎 (War-Game Simulator)
基于黑天鹅事件、极端情景、概率情景进行战略推演
为战术SKILL生成至少3套战略预案

Version: v1.0.0
Updated: 2026-04-21
"""

import json
import yaml
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict

# ============================================================
# 战略参考库路径
# ============================================================

STRATEGY_LIB_PATH = Path.home() / ".workbuddy" / "strategy-library"
CONTINGENCY_FILE = STRATEGY_LIB_PATH / "strategy_contingency_library.yaml"


@dataclass
class ContingencyPlan:
    """应急预案结构"""
    plan_id: str
    name: str
    category: str
    probability: float
    severity: str
    trigger_conditions: List[Dict]
    tactical_response: Dict
    position_management: Dict
    recovery_plan: List[str]
    recommended_tools: List[str]
    avoid_tools: List[str]


@dataclass
class WarGameScenario:
    """沙盘推演情景"""
    scenario_id: str
    name: str
    probability: float
    market_conditions: Dict
    price_range: str
    expected_outcome: Dict
    risk_factors: List[str]
    contingency_plan: Optional[Dict] = None


class BlackSwanSimulator:
    """黑天鹅事件模拟器"""
    
    BLACK_SWAN_TEMPLATES = {
        "BS_001": {
            "name": "交易所系统性风险",
            "price_impact": -0.25,  # -25%
            "recovery_weeks": 3,
            "volatility_surge": 3.0
        },
        "BS_002": {
            "name": "重大监管政策",
            "price_impact": -0.20,
            "recovery_weeks": 4,
            "volatility_surge": 2.5
        },
        "BS_003": {
            "name": "全球金融危机",
            "price_impact": -0.40,
            "recovery_weeks": 12,
            "volatility_surge": 4.0
        },
        "BS_004": {
            "name": "DeFi协议漏洞",
            "price_impact": -0.15,
            "recovery_weeks": 2,
            "volatility_surge": 2.0
        },
        "BS_005": {
            "name": "交易所技术故障",
            "price_impact": -0.10,
            "recovery_weeks": 1,
            "volatility_surge": 1.5
        }
    }
    
    def simulate(self, current_price: float, current_regime: str) -> List[WarGameScenario]:
        """模拟黑天鹅情景"""
        scenarios = []
        
        for bs_id, template in self.BLACK_SWAN_TEMPLATES.items():
            scenario = WarGameScenario(
                scenario_id=bs_id,
                name=template["name"],
                probability=0.02,  # 默认2%
                market_conditions={
                    "regime": "EXTREME",
                    "volatility": "EXTREME",
                    "sentiment": "EXTREME_FEAR"
                },
                price_range=f"${current_price * (1 + template['price_impact']):,.0f} - ${current_price:,.0f}",
                expected_outcome={
                    "max_drop_pct": template["price_impact"] * 100,
                    "recovery_weeks": template["recovery_weeks"],
                    "liquidity": "LOW"
                },
                risk_factors=[
                    "流动性枯竭",
                    "连环爆仓",
                    "止损失效"
                ],
                contingency_plan=self._generate_contingency(bs_id, template)
            )
            scenarios.append(scenario)
        
        return scenarios
    
    def _generate_contingency(self, bs_id: str, template: Dict) -> Dict:
        """生成应急预案"""
        return {
            "immediate_actions": [
                {"action": "立即平仓所有仓位", "priority": 1},
                {"action": "将资金转至安全位置", "priority": 2},
                {"action": "等待24小时观察", "priority": 3}
            ],
            "recovery_strategy": f"等待{template['recovery_weeks']}周后评估",
            "initial_position": "10-15%正常仓位",
            "tools": ["spot_limit_order"],
            "avoid_tools": ["futures_grid", "martingale", "short_strategy"]
        }


class ExtremeScenarioSimulator:
    """极端情景模拟器"""
    
    EXTREME_TEMPLATES = {
        "EXT_001": {
            "name": "瀑布暴跌",
            "trigger": "价格1小时下跌>15%",
            "price_impact_range": [-0.20, -0.15],
            "duration_hours": 24
        },
        "EXT_002": {
            "name": "暴涨逼空",
            "trigger": "价格1小时上涨>10%",
            "price_impact_range": [0.10, 0.20],
            "duration_hours": 12
        },
        "EXT_003": {
            "name": "长期横盘",
            "trigger": "ATR<1%持续7天+",
            "price_impact_range": [-0.03, 0.03],
            "duration_hours": 168
        }
    }
    
    def simulate(self, current_price: float, regime: str) -> List[WarGameScenario]:
        """模拟极端情景"""
        scenarios = []
        
        for ext_id, template in self.EXTREME_TEMPLATES.items():
            impact_range = template["price_impact_range"]
            avg_impact = sum(impact_range) / 2
            
            scenario = WarGameScenario(
                scenario_id=ext_id,
                name=template["name"],
                probability=0.15,  # 15%
                market_conditions={
                    "regime": regime,
                    "trigger": template["trigger"]
                },
                price_range=f"${current_price * (1 + impact_range[0]):,.0f} - ${current_price * (1 + impact_range[1]):,.0f}",
                expected_outcome={
                    "avg_impact_pct": avg_impact * 100,
                    "duration_hours": template["duration_hours"],
                    "recommended_action": self._get_action(ext_id)
                },
                risk_factors=self._get_risks(ext_id),
                contingency_plan=self._generate_contingency(ext_id, template)
            )
            scenarios.append(scenario)
        
        return scenarios
    
    def _get_action(self, ext_id: str) -> str:
        actions = {
            "EXT_001": "分批建仓，等待底部确认",
            "EXT_002": "禁止追多，等待回踩",
            "EXT_003": "使用网格/套利策略"
        }
        return actions.get(ext_id, "观望")
    
    def _get_risks(self, ext_id: str) -> List[str]:
        risks = {
            "EXT_001": ["流动性枯竭", "杠杆连环爆仓"],
            "EXT_002": ["追高被套", "止损触发"],
            "EXT_003": ["网格被套", "无波动收益低"]
        }
        return risks.get(ext_id, [])
    
    def _generate_contingency(self, ext_id: str, template: Dict) -> Dict:
        """生成极端情景预案"""
        contingencies = {
            "EXT_001": {
                "immediate_actions": [
                    {"action": "如有持仓，止损设在-8%", "priority": 1},
                    {"action": "不抄底，等待RSI<25确认", "priority": 2},
                    {"action": "分批建仓，每次10%", "priority": 3}
                ],
                "recovery_strategy": "48小时后可考虑测试建仓",
                "initial_position": "最多30%仓位"
            },
            "EXT_002": {
                "immediate_actions": [
                    {"action": "如有空单，立即平仓", "priority": 1},
                    {"action": "禁止追多", "priority": 2},
                    {"action": "等待回踩EMA20", "priority": 3}
                ],
                "recovery_strategy": "回踩确认后再入场",
                "initial_position": "回踩后最多50%仓位"
            },
            "EXT_003": {
                "immediate_actions": [
                    {"action": "不做趋势策略", "priority": 1},
                    {"action": "使用网格策略", "priority": 2},
                    {"action": "资金费率套利", "priority": 3}
                ],
                "recovery_strategy": "突破横盘区间后切换策略",
                "initial_position": "20-30%仓位"
            }
        }
        return contingencies.get(ext_id, {})


class ProbabilityScenarioGenerator:
    """概率情景生成器 - 生成3套基础战略预案"""
    
    def __init__(self, current_price: float, regime: str, direction: str):
        self.current_price = current_price
        self.regime = regime
        self.direction = direction
    
    def generate_plans(self, feature_vector: Dict) -> List[Dict]:
        """生成3套战略预案"""
        plans = []
        
        # 预案A: 基准情景 (50%)
        plans.append(self._generate_plan_a(feature_vector))
        
        # 预案B: 乐观情景 (25%)
        plans.append(self._generate_plan_b(feature_vector))
        
        # 预案C: 悲观情景 (25%)
        plans.append(self._generate_plan_c(feature_vector))
        
        return plans
    
    def _generate_plan_a(self, fv: Dict) -> Dict:
        """预案A: 基准情景"""
        return {
            "plan_id": "PLAN_A",
            "name": "基准情景",
            "probability": 0.50,
            "description": "市场按当前趋势平稳运行",
            
            "trigger_conditions": [
                "当前regime持续",
                "无重大宏观事件",
                "情绪维持中性"
            ],
            
            "strategic_response": {
                "primary_strategy": f"保持当前{self.regime}战略",
                "position_modifier": fv.get("position_modifier", 0.5),
                "leverage_cap": fv.get("leverage_cap", 2),
                "entry_conditions": "按原计划执行"
            },
            
            "tactical_adjustments": {
                "entry_timing": "分批入场",
                "stop_loss": "±3%",
                "take_profit": "+6%",
                "trailing_stop": "启动"
            },
            
            "exit_conditions": [
                "触及止损",
                "regime发生变化",
                "达到目标位"
            ]
        }
    
    def _generate_plan_b(self, fv: Dict) -> Dict:
        """预案B: 乐观情景"""
        bullish_actions = {
            "LONG": "趋势追踪",
            "SHORT": "趋势反转做空",
            "WAIT": "观望等待机会"
        }
        
        return {
            "plan_id": "PLAN_B",
            "name": "乐观情景",
            "probability": 0.25,
            "description": "出现明确趋势信号，突破确认",
            
            "trigger_conditions": [
                "放量突破关键阻力",
                "MA多头排列形成",
                "ETF净流入加速",
                "机构宣布增持"
            ],
            
            "strategic_response": {
                "primary_strategy": bullish_actions.get(self.direction, "趋势追踪"),
                "position_modifier": min(fv.get("position_modifier", 0.5) + 0.25, 1.0),
                "leverage_cap": min(fv.get("leverage_cap", 2) + 1, 5),
                "entry_conditions": "回踩确认后入场"
            },
            
            "tactical_adjustments": {
                "entry_timing": "突破确认后",
                "add_position": "金字塔加仓≤3次",
                "stop_loss": "±5%",
                "take_profit": "分批止盈",
                "trailing_stop": "启动"
            },
            
            "exit_conditions": [
                "均线死叉",
                "动能衰竭",
                "达到分批目标位"
            ]
        }
    
    def _generate_plan_c(self, fv: Dict) -> Dict:
        """预案C: 悲观情景"""
        bearish_actions = {
            "LONG": "止损或观望",
            "SHORT": "做空策略",
            "WAIT": "继续观望"
        }
        
        return {
            "plan_id": "PLAN_C",
            "name": "悲观情景",
            "probability": 0.25,
            "description": "趋势反转或深度回调",
            
            "trigger_conditions": [
                "放量跌破关键支撑",
                "MA死叉形成",
                "ETF净流出",
                "宏观数据恶化"
            ],
            
            "strategic_response": {
                "primary_strategy": bearish_actions.get(self.direction, "观望"),
                "position_modifier": max(fv.get("position_modifier", 0.5) * 0.5, 0.0),
                "leverage_cap": 1,
                "entry_conditions": "等待反弹做空或底部确认"
            },
            
            "tactical_adjustments": {
                "existing_position": "止损或追踪止损收紧至3%",
                "new_short": "轻仓试探，止损3%",
                "new_long": "禁止抄底",
                "take_profit": "-5%, -10%"
            },
            
            "exit_conditions": [
                "触及止损",
                "趋势确认反转",
                "超卖信号"
            ]
        }


class WarGameSimulator:
    """战略沙盘推演主引擎"""
    
    def __init__(self):
        self.black_swan_sim = BlackSwanSimulator()
        self.extreme_sim = ExtremeScenarioSimulator()
    
    def simulate(
        self,
        current_price: float,
        regime: str,
        direction: str,
        feature_vector: Dict,
        primary_directive: Dict
    ) -> Dict:
        """
        执行完整战略沙盘推演
        
        Args:
            current_price: 当前价格
            regime: 当前regime
            direction: 方向
            feature_vector: 特征向量
            primary_directive: 主要战略指令
            
        Returns:
            war_game_result: 沙盘推演结果
        """
        results = {
            "war_game_id": f"WG_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "timestamp": datetime.now().isoformat(),
            
            # 1. 黑天鹅情景模拟
            "black_swan_scenarios": self._simulate_black_swans(current_price, regime),
            
            # 2. 极端情景模拟
            "extreme_scenarios": self._simulate_extremes(current_price, regime),
            
            # 3. 概率情景预案 (3套)
            "probability_plans": self._generate_probability_plans(
                current_price, regime, direction, feature_vector
            ),
            
            # 4. 综合应急预案
            "contingency_recommendations": self._generate_contingency_recommendations(
                primary_directive
            ),
            
            # 5. 背离检测配置
            "deviation_detection": self._generate_deviation_config(),
            
            # 6. 战术SKILL调用接口
            "tactical_interface": self._generate_tactical_interface(primary_directive),
            
            # 7. 执行统计
            "meta": {
                "simulator_version": "1.0.0",
                "total_scenarios": 11,  # 5黑天鹅 + 3极端 + 3概率
                "plans_generated": 3
            }
        }
        
        return results
    
    def _simulate_black_swans(self, price: float, regime: str) -> List[Dict]:
        """模拟黑天鹅情景"""
        scenarios = self.black_swan_sim.simulate(price, regime)
        return [asdict(s) for s in scenarios]
    
    def _simulate_extremes(self, price: float, regime: str) -> List[Dict]:
        """模拟极端情景"""
        scenarios = self.extreme_sim.simulate(price, regime)
        return [asdict(s) for s in scenarios]
    
    def _generate_probability_plans(
        self,
        price: float,
        regime: str,
        direction: str,
        feature_vector: Dict
    ) -> List[Dict]:
        """生成概率情景预案"""
        generator = ProbabilityScenarioGenerator(price, regime, direction)
        return generator.generate_plans(feature_vector)
    
    def _generate_contingency_recommendations(self, directive: Dict) -> Dict:
        """生成应急预案建议"""
        return {
            "contingency_activated": False,
            "active_contingency_id": None,
            "override_authority": "NONE",
            "recommendations": [
                {
                    "priority": 1,
                    "category": "immediate",
                    "action": "保持当前战略指令",
                    "rationale": "未检测到触发条件"
                }
            ],
            "backup_strategies": [
                {
                    "plan_id": "PLAN_C",
                    "name": "悲观情景预案",
                    "activate_when": "价格跌破关键支撑"
                }
            ]
        }
    
    def _generate_deviation_config(self) -> Dict:
        """生成背离检测配置"""
        return {
            "enabled": True,
            "check_interval": "每轮决策前",
            "dimensions": [
                {"name": "价格背离", "weight": 0.3},
                {"name": "情绪背离", "weight": 0.25},
                {"name": "宏观背离", "weight": 0.25},
                {"name": "技术背离", "weight": 0.2}
            ],
            "thresholds": {
                "minor": 0.3,
                "moderate": 0.5,
                "major": 0.7
            }
        }
    
    def _generate_tactical_interface(self, directive: Dict) -> Dict:
        """生成战术SKILL接口"""
        return {
            "input_schema": {
                "current_directive": directive,
                "market_state": "实时市场状态",
                "deviation_score": 0.0
            },
            "output_schema": {
                "active_plan": "PLAN_A|B|C",
                "tactical_adjustments": {},
                "override_required": False
            },
            "fallback_rules": {
                "if_deviation_major": "切换至对应应急预案",
                "if_black_swan": "激活BS_xxx应急预案",
                "if_extreme": "激活EXT_xxx应急预案"
            }
        }
    
    def save_to_library(self, results: Dict) -> bool:
        """保存到战略参考库"""
        try:
            # 创建存档目录
            archive_dir = STRATEGY_LIB_PATH / "war_game_archive"
            archive_dir.mkdir(parents=True, exist_ok=True)
            
            # 存档文件名
            archive_file = archive_dir / f"war_game_{results['war_game_id']}.json"
            
            with open(archive_file, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=2, ensure_ascii=False)
            
            return True
        except Exception as e:
            print(f"存档失败: {e}")
            return False


def load_contingency_library() -> Dict:
    """加载战略参考库"""
    if CONTINGENCY_FILE.exists():
        with open(CONTINGENCY_FILE, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    return {}


def main():
    """测试入口"""
    # 模拟输入
    current_price = 74500.0
    regime = "BREAKOUT_PENDING"
    direction = "UP"
    
    feature_vector = {
        "position_modifier": 0.5,
        "leverage_cap": 2
    }
    
    primary_directive = {
        "directive_bias": "LONG",
        "position_modifier": 0.5,
        "leverage_cap": 2
    }
    
    # 执行沙盘推演
    simulator = WarGameSimulator()
    results = simulator.simulate(
        current_price=current_price,
        regime=regime,
        direction=direction,
        feature_vector=feature_vector,
        primary_directive=primary_directive
    )
    
    # 打印结果
    print(json.dumps(results, indent=2, ensure_ascii=False))
    
    # 存档
    simulator.save_to_library(results)
    print(f"\n✅ 沙盘推演完成，已生成3套战略预案")
    print(f"📁 存档位置: {STRATEGY_LIB_PATH / 'war_game_archive'}")


if __name__ == "__main__":
    main()
