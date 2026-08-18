#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dream Pretrade Gatekeeper - 交易前门禁最小实现
Version: v2.0 MVP
"""

import json
from typing import Dict, Any, List, Optional


class PretradeGatekeeper:
    """
    交易前门禁检查器
    
    职责:
    1. 数据完整性检查 (fail-closed)
    2. 杠杆门禁检查 (P003)
    3. 战略门禁检查 (P0)
    4. 评分门禁检查
    5. 执行风险门禁检查
    6. 收益-风险-成本统一判定
    7. 账户层门禁检查
    """
    
    def __init__(self, policy: Optional[Dict[str, Any]] = None):
        """
        初始化交易前门禁
        
        Args:
            policy: 策略配置字典
        """
        self.policy = policy or self._default_policy()
        
    def _default_policy(self) -> Dict[str, Any]:
        """默认策略配置"""
        return {
            "min_dim_score": 3,
            "min_total_score": 12,
            "max_worst_slippage_bps": 60,
            "lambda_risk": 1.0,
            "edge_min_bps": 0,
            "execution_blackout_windows": []
        }
    
    def check(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行交易前门禁检查
        
        Args:
            input_data: 输入数据字典，包含：
                - strategy_directive: 战略指令
                - data_health: 数据健康状态
                - scores_result: 评分结果
                - position_result: 仓位结果
                - execution_cost_result: 执行成本结果
                - validation_result: 验证结果 (可选)
                - regime_result: 市场状态 (可选)
                - account_snapshot: 账户快照 (可选)
                - policy: 策略配置 (可选)
                
        Returns:
            Dict: {
                "decision": "PASS" | "SKIP",
                "reason_codes": List[str],
                "degradations": List[str],
                "edge_eval": Dict[str, float]
            }
        """
        # 更新策略配置
        if "policy" in input_data:
            self.policy.update(input_data["policy"])
        
        reason_codes = []
        degradations = []
        edge_eval = {
            "expected_return_bps": 0.0,
            "costs_bps": 0.0,
            "risk_bps": 0.0,
            "lambda_risk": self.policy["lambda_risk"],
            "edge_bps": 0.0
        }
        
        # === 门禁检查顺序 ===
        
        # 1. 数据完整性检查 (最高优先级)
        data_check = self._check_data_health(input_data.get("data_health", {}))
        if data_check["result"] == "FAIL":
            return self._build_response("SKIP", data_check["reason_codes"], [], edge_eval)
        
        # 2. 杠杆门禁检查 (P003 - 在评分门禁之前)
        lever_check = self._check_leverage(input_data)
        if lever_check["result"] == "FAIL":
            reason_codes.extend(lever_check["reason_codes"])
            return self._build_response("SKIP", reason_codes, degradations, edge_eval)
        elif lever_check.get("warning"):
            reason_codes.append(lever_check["warning"])
        
        # 3. 战略门禁检查 (P0 - 在评分门禁之前)
        strategy_check = self._check_strategy(input_data.get("strategy_directive", {}))
        if strategy_check["result"] == "FAIL":
            reason_codes.extend(strategy_check["reason_codes"])
            return self._build_response("SKIP", reason_codes, degradations, edge_eval)
        elif strategy_check.get("degradations"):
            degradations.extend(strategy_check["degradations"])
        
        # 4. 评分门禁检查
        score_check = self._check_scores(input_data.get("scores_result", {}))
        if score_check["result"] == "FAIL":
            reason_codes.extend(score_check["reason_codes"])
            return self._build_response("SKIP", reason_codes, degradations, edge_eval)
        
        # 5. 执行风险门禁检查
        execution_check = self._check_execution_cost(input_data.get("execution_cost_result", {}))
        if execution_check["result"] == "FAIL":
            reason_codes.extend(execution_check["reason_codes"])
            return self._build_response("SKIP", reason_codes, degradations, edge_eval)
        
        # 6. 收益-风险-成本统一判定
        edge_check = self._check_edge(input_data, edge_eval)
        if edge_check["result"] == "FAIL":
            reason_codes.extend(edge_check["reason_codes"])
            return self._build_response("SKIP", reason_codes, degradations, edge_eval)
        edge_eval.update(edge_check.get("edge_eval", {}))
        
        # 7. 账户层门禁检查
        account_check = self._check_account(input_data.get("account_snapshot", {}))
        if account_check["result"] == "FAIL":
            reason_codes.extend(account_check["reason_codes"])
            return self._build_response("SKIP", reason_codes, degradations, edge_eval)
        
        # 8. 事件黑窗门禁检查
        blackout_check = self._check_blackout_window(input_data.get("policy", {}))
        if blackout_check["result"] == "FAIL":
            reason_codes.extend(blackout_check["reason_codes"])
            return self._build_response("SKIP", reason_codes, degradations, edge_eval)
        
        # 9. Dream Mode 降级检查 (不阻断，只降级)
        dream_check = self._check_dream_mode(input_data.get("account_snapshot", {}))
        if dream_check.get("degradation"):
            degradations.extend(dream_check["degradations"])
        
        # 10. 统计与 Regime 降级检查 (不阻断，只降级)
        validation_check = self._check_validation(input_data.get("validation_result", {}))
        if validation_check.get("degradation"):
            degradations.extend(validation_check["degradations"])
        
        # 所有检查通过
        return self._build_response("PASS", reason_codes, degradations, edge_eval)
    
    def _check_data_health(self, data_health: Dict[str, Any]) -> Dict[str, Any]:
        """检查数据完整性"""
        if not data_health.get("candles_ok", True):
            return {
                "result": "FAIL",
                "reason_codes": ["HARD_FAIL_MISSING_CORE_DATA:candles"]
            }
        if not data_health.get("funding_ok", True):
            return {
                "result": "FAIL",
                "reason_codes": ["HARD_FAIL_MISSING_CORE_DATA:funding"]
            }
        if not data_health.get("oi_ok", True):
            return {
                "result": "FAIL",
                "reason_codes": ["HARD_FAIL_MISSING_CORE_DATA:oi"]
            }
        if not data_health.get("macro_ok", True):
            return {
                "result": "FAIL",
                "reason_codes": ["HARD_FAIL_MISSING_CORE_DATA:macro"]
            }
        
        return {"result": "PASS", "reason_codes": []}
    
    def _check_leverage(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """检查杠杆门禁 (P003)"""
        position_result = input_data.get("position_result", {})
        position = position_result.get("position", {})
        
        # 计算实际杠杆
        notional_value = position.get("notional_usdt", 0)
        total_equity = input_data.get("total_equity", 10000)  # 默认值
        actual_lever = notional_value / total_equity if total_equity > 0 else 0
        
        # 检查杠杆上限
        leverage_cap = input_data.get("strategy_directive", {}).get("leverage_cap")
        max_lever = leverage_cap if leverage_cap else 2.0
        
        if actual_lever > max_lever:
            return {
                "result": "FAIL",
                "reason_codes": [f"HARD_FAIL_LEVERAGE_EXCEEDS_CAP:{actual_lever:.2f}>{max_lever}"]
            }
        
        # 检查 OKX 显示杠杆 vs 实际杠杆
        okx_display_lever = position.get("lever", 0)
        if okx_display_lever > 0 and actual_lever > 0:
            diff_rate = abs(actual_lever - okx_display_lever) / actual_lever
            if diff_rate > 0.2:
                return {
                    "result": "PASS",
                    "reason_codes": [],
                    "warning": f"HARD_FAIL_LEVERAGE_MISMATCH:diff_rate={diff_rate:.2%}"
                }
        
        return {"result": "PASS", "reason_codes": []}
    
    def _check_strategy(self, strategy_directive: Dict[str, Any]) -> Dict[str, Any]:
        """检查战略门禁 (P0)"""
        if not strategy_directive:
            return {
                "result": "FAIL",
                "reason_codes": ["HARD_FAIL_NO_STRATEGY_EXTREME_REGIME:strategy_directive is null"]
            }
        
        # 检查排除条件
        exclusion_conditions = strategy_directive.get("exclusion_conditions_checked", [])
        if exclusion_conditions:
            return {
                "result": "FAIL",
                "reason_codes": [f"HARD_FAIL_STRATEGY_EXCLUDED:{','.join(exclusion_conditions)}"]
            }
        
        directive_bias = strategy_directive.get("directive_bias")
        degradations = []
        
        # REDUCE: 允许通过但强制降级
        if directive_bias == "REDUCE":
            position_modifier = strategy_directive.get("position_modifier", 0.5)
            degradations.append(f"DEGRADE_STRATEGY_REDUCED_RISK:modifier={position_modifier}")
            return {
                "result": "PASS",
                "reason_codes": [],
                "degradations": degradations
            }
        
        # WAIT: 允许通过但警告
        if directive_bias == "WAIT":
            degradations.append("SOFT_WARN_STRATEGY_DIRECTS_WAIT:strong_signal_can_override")
            return {
                "result": "PASS",
                "reason_codes": [],
                "degradations": degradations
            }
        
        # LONG/SHORT: 需要在调用时检查方向匹配
        # 这里只做基本检查，方向匹配由调用者负责
        
        return {"result": "PASS", "reason_codes": [], "degradations": []}
    
    def _check_scores(self, scores_result: Dict[str, Any]) -> Dict[str, Any]:
        """检查评分门禁"""
        if not scores_result:
            return {
                "result": "FAIL",
                "reason_codes": ["HARD_FAIL_LOW_TOTAL_SCORE:scores_result is missing"]
            }
        
        # 检查维度评分
        scores = scores_result.get("scores", {})
        min_dim_score = self.policy["min_dim_score"]
        
        low_dims = []
        for dim, score in scores.items():
            if dim != "total" and isinstance(score, (int, float)) and score < min_dim_score:
                low_dims.append(f"{dim}:{score}")
        
        if low_dims:
            return {
                "result": "FAIL",
                "reason_codes": [f"HARD_FAIL_LOW_DIM_SCORE:{','.join(low_dims)}"]
            }
        
        # 检查总分
        total_score = scores.get("total", 0)
        if total_score < self.policy["min_total_score"]:
            return {
                "result": "FAIL",
                "reason_codes": [f"HARD_FAIL_LOW_TOTAL_SCORE:{total_score}<{self.policy['min_total_score']}"]
            }
        
        # 检查 gates.pass
        gates = scores_result.get("gates", {})
        if not gates.get("pass", True):
            reason_codes = gates.get("reason_codes", ["unknown"])
            return {
                "result": "FAIL",
                "reason_codes": [f"HARD_FAIL_SCORES_GATE:{','.join(reason_codes)}"]
            }
        
        return {"result": "PASS", "reason_codes": []}
    
    def _check_execution_cost(self, execution_cost_result: Dict[str, Any]) -> Dict[str, Any]:
        """检查执行风险门禁"""
        if not execution_cost_result:
            return {"result": "PASS", "reason_codes": []}  # 可选字段，缺失不阻断
        
        if not execution_cost_result.get("pass", True):
            reason_codes = execution_cost_result.get("reason_codes", ["unknown"])
            return {
                "result": "FAIL",
                "reason_codes": [f"HARD_FAIL_EXECUTION_COST:{','.join(reason_codes)}"]
            }
        
        # 检查最坏滑点
        costs = execution_cost_result.get("costs", {})
        worst_slippage = costs.get("worst_case_slippage_bps", 0)
        if worst_slippage > self.policy["max_worst_slippage_bps"]:
            return {
                "result": "FAIL",
                "reason_codes": [f"HARD_FAIL_WORST_SLIPPAGE_TOO_HIGH:{worst_slippage}>{self.policy['max_worst_slippage_bps']}"]
            }
        
        return {"result": "PASS", "reason_codes": []}
    
    def _check_edge(self, input_data: Dict[str, Any], edge_eval: Dict[str, float]) -> Dict[str, Any]:
        """检查收益-风险-成本统一判定"""
        scores_result = input_data.get("scores_result", {})
        execution_cost_result = input_data.get("execution_cost_result", {})
        
        # 计算 E[R]_bps
        expected_return = scores_result.get("expected_return", {})
        e_r_bps = expected_return.get("expected_return_bps", 0)
        
        # 计算 Costs_bps
        costs = execution_cost_result.get("costs", {}) if execution_cost_result else {}
        costs_bps = costs.get("total_cost_bps_est", 0)
        
        # 计算 Risk_bps (风险占本金的百分比，转换为 bps)
        position_result = input_data.get("position_result", {})
        position = position_result.get("position", {})
        notional_usdt = position.get("notional_usdt", 0)
        total_equity = input_data.get("total_equity", 10000)
        stop_loss_pct = input_data.get("stop_loss_pct", 0.02)  # 默认 2%
        
        # 风险金额 / 本金 = 风险百分比
        risk_amount = notional_usdt * stop_loss_pct
        risk_pct = risk_amount / total_equity if total_equity > 0 else 0
        risk_bps = risk_pct * 10000  # 转换为 bps
        
        # 计算 edge_bps (所有值都是 bps 单位)
        lambda_risk = self.policy["lambda_risk"]
        edge_bps = e_r_bps - costs_bps - lambda_risk * (risk_bps / 10000)  # risk_bps 转回百分比
        
        edge_eval.update({
            "expected_return_bps": e_r_bps,
            "costs_bps": costs_bps,
            "risk_bps": risk_bps,
            "edge_bps": edge_bps
        })
        
        if edge_bps <= self.policy["edge_min_bps"]:
            return {
                "result": "FAIL",
                "reason_codes": [f"HARD_FAIL_NEGATIVE_EDGE:{edge_bps:.2f}<={self.policy['edge_min_bps']}"],
                "edge_eval": edge_eval
            }
        
        return {"result": "PASS", "reason_codes": [], "edge_eval": edge_eval}
    
    def _check_account(self, account_snapshot: Dict[str, Any]) -> Dict[str, Any]:
        """检查账户层门禁"""
        if not account_snapshot:
            return {"result": "PASS", "reason_codes": []}  # 可选字段
        
        # 检查当日回撤熔断
        today_drawdown_pct = account_snapshot.get("today_drawdown_pct", 0)
        if today_drawdown_pct < -0.05:  # 回撤超过 5%
            return {
                "result": "FAIL",
                "reason_codes": [f"HARD_FAIL_ACCOUNT_DRAWDOWN:{today_drawdown_pct:.2%}"]
            }
        
        return {"result": "PASS", "reason_codes": []}
    
    def _check_blackout_window(self, policy: Dict[str, Any]) -> Dict[str, Any]:
        """检查事件黑窗门禁"""
        # TODO: 实现当前时段检查
        # 当前简化版：假设不在黑窗期
        return {"result": "PASS", "reason_codes": []}
    
    def _check_dream_mode(self, account_snapshot: Dict[str, Any]) -> Dict[str, Any]:
        """检查 Dream Mode 降级"""
        if not account_snapshot:
            return {"degradation": False}
        
        if account_snapshot.get("dream_mode_active", False):
            return {
                "degradation": True,
                "degradations": ["DEGRADE_DREAM_MODE_RISK_REDUCTION:leverage_limit=1.0x"]
            }
        
        return {"degradation": False}
    
    def _check_validation(self, validation_result: Dict[str, Any]) -> Dict[str, Any]:
        """检查统计与 Regime 降级"""
        if not validation_result:
            return {"degradation": False}
        
        degradations = []
        
        # 检查稳定性
        stability_flag = validation_result.get("stability_flag", "unknown")
        if stability_flag == "unstable":
            degradations.append("DEGRADE_VALIDATION_WEAK:stability=unstable")
        
        # 检查 profit_factor
        profit_factor = validation_result.get("profit_factor_rolling", None)
        if profit_factor and profit_factor < 1.5:
            degradations.append(f"DEGRADE_VALIDATION_WEAK:profit_factor={profit_factor:.2f}<1.5")
        
        if degradations:
            return {"degradation": True, "degradations": degradations}
        
        return {"degradation": False}
    
    def _build_response(
        self,
        decision: str,
        reason_codes: List[str],
        degradations: List[str],
        edge_eval: Dict[str, float]
    ) -> Dict[str, Any]:
        """构建响应"""
        return {
            "decision": decision,
            "reason_codes": reason_codes,
            "degradations": degradations,
            "edge_eval": edge_eval
        }


def main():
    """命令行测试入口"""
    import sys
    
    if len(sys.argv) < 2:
        print("用法: python pretrade_gatekeeper.py <input.json>")
        sys.exit(1)
    
    input_path = sys.argv[1]
    
    # 读取输入
    with open(input_path, 'r', encoding='utf-8') as f:
        input_data = json.load(f)
    
    # 创建门禁检查器
    gatekeeper = PretradeGatekeeper()
    
    # 执行检查
    result = gatekeeper.check(input_data)
    
    # 输出结果
    print("="*60)
    print("交易前门禁检查结果:")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("="*60)
    
    # 保存结果
    output_path = input_path.replace(".json", "_gatekeeper_result.json")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"\n结果已保存到: {output_path}")


if __name__ == "__main__":
    main()
