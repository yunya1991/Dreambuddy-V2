#!/usr/bin/env python3
"""portfolio-agent — 组合面 subagent (新建域, Spec §3.2 扩展)

数据源: 仓位/再平衡指标已验证输出 (HC-1: LLM 不生成原始数据)
输出: SubagentOutput (summary + signals + charts)
图表: pie(饼图) + bar(柱状)
"""
from __future__ import annotations

import traceback
from typing import Any, Callable, Dict, List, Optional

from subagent_types import ChartSpec, Signal, SubagentOutput


class PortfolioAgent:
    """组合面 subagent: 仓位/再平衡指标 → SubagentOutput"""

    # D3: 风控夹断层默认参数
    DEFAULT_RISK_CONFIG = {
        "max_position_pct": 0.30,       # 单标的最大仓位占总权益 30%
        "max_single_order_pct": 0.10,   # 单笔最大订单占总权益 10%
        "max_leverage": 3.0,            # 最大杠杆 3x
        "min_order_value": 10.0,        # 最小订单名义价值 (USD)
    }

    def __init__(self, llm_fn: Optional[Callable[[str], str]] = None):
        self._llm_fn = llm_fn

    def execute(self, node_output: dict) -> SubagentOutput:
        indicators = node_output.get("indicators", {})
        rationale = node_output.get("rationale", [])
        direction = node_output.get("direction", "NEUTRAL")
        confidence = float(node_output.get("confidence", 0.5))

        signals = self._extract_signals(indicators)
        summary = self._generate_summary(signals, rationale, direction, confidence)
        charts = self._generate_charts(indicators)

        # D3: 填充 reasoning_chain + evidence_refs + artifact_uri
        reasoning_chain = " | ".join(rationale) if rationale else ""
        evidence_refs = [f"indicator:{k}" for k in indicators.keys()]
        artifact_uri = f"artifact://portfolio/{hash(str(indicators)) % 100000:05d}" if indicators else None

        return SubagentOutput(
            module="portfolio",
            summary=summary,
            signals=signals,
            charts=charts,
            raw_data=node_output,
            confidence=confidence,
            reasoning_chain=reasoning_chain,
            evidence_refs=evidence_refs,
            artifact_uri=artifact_uri,
        )

    # ── D3: compute_allowed_actions 确定性夹断层 ──

    @staticmethod
    def compute_allowed_actions(
        proposed_action: Dict[str, Any],
        portfolio_state: Dict[str, Any],
        risk_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """确定性夹断层: 将 LLM 提议的动作夹断到 risk-approved 上限

        即使 LLM 输出 10000 股, 硬数学夹断到风控允许的上限。
        纯函数, 不调 LLM, 不抛异常 (FAIL-OPEN)。

        Args:
            proposed_action: LLM 提议的动作
                {action: "buy"|"sell"|"hold", symbol: str, quantity: float, price: float}
            portfolio_state: 当前持仓状态
                {positions: [{symbol, weight, value}], total_equity: float, available_balance: float}
            risk_config: 风控参数, None 时用 DEFAULT_RISK_CONFIG

        Returns:
            {
                "action": 夹断后动作,
                "symbol": str,
                "quantity": 夹断后数量,
                "price": float,
                "notional": 夹断后名义价值,
                "clamped": bool,  # 是否被夹断
                "clamp_reasons": List[str],  # 夹断原因
            }
        """
        cfg = {**PortfolioAgent.DEFAULT_RISK_CONFIG, **(risk_config or {})}
        action = str(proposed_action.get("action", "hold")).lower()
        symbol = str(proposed_action.get("symbol", ""))
        quantity = float(proposed_action.get("quantity", 0))
        price = float(proposed_action.get("price", 0))

        result = {
            "action": action,
            "symbol": symbol,
            "quantity": 0.0,
            "price": price,
            "notional": 0.0,
            "clamped": False,
            "clamp_reasons": [],
        }

        # hold 直接返回
        if action == "hold" or quantity <= 0 or price <= 0:
            result["quantity"] = max(0.0, quantity)
            result["notional"] = result["quantity"] * price
            return result

        total_equity = float(portfolio_state.get("total_equity", 0))
        available_balance = float(portfolio_state.get("available_balance", total_equity))
        positions = portfolio_state.get("positions", [])

        # 当前该标的持仓名义价值
        current_symbol_value = 0.0
        current_total_exposure = 0.0
        for pos in positions:
            pos_val = float(pos.get("value", 0))
            current_total_exposure += pos_val
            if pos.get("symbol") == symbol:
                current_symbol_value += pos_val

        proposed_notional = quantity * price
        clamp_reasons: List[str] = []

        # 约束 1: 单笔订单上限
        max_single = total_equity * cfg["max_single_order_pct"]
        if proposed_notional > max_single:
            clamp_reasons.append(
                f"单笔订单 {proposed_notional:.0f} 超过上限 {max_single:.0f} "
                f"({cfg['max_single_order_pct']:.0%} 权益)"
            )

        # 约束 2: 单标的总仓位上限 (仅 buy)
        max_symbol_position = total_equity * cfg["max_position_pct"]
        if action == "buy":
            remaining_symbol_cap = max_symbol_position - current_symbol_value
            if remaining_symbol_cap < proposed_notional:
                clamp_reasons.append(
                    f"标的 {symbol} 加仓后仓位将超过上限 {max_symbol_position:.0f} "
                    f"(当前 {current_symbol_value:.0f})"
                )

        # 约束 3: 可用余额 (仅 buy)
        if action == "buy" and proposed_notional > available_balance:
            clamp_reasons.append(
                f"订单 {proposed_notional:.0f} 超过可用余额 {available_balance:.0f}"
            )

        # 约束 4: 杠杆上限 (总暴露)
        max_total_exposure = total_equity * cfg["max_leverage"]
        if action == "buy":
            remaining_leverage = max_total_exposure - current_total_exposure
            if remaining_leverage < proposed_notional:
                clamp_reasons.append(
                    f"加仓后总暴露将超过杠杆上限 {max_total_exposure:.0f} "
                    f"(当前 {current_total_exposure:.0f})"
                )

        # 计算允许的最大名义价值
        max_allowed_notional = proposed_notional
        if action == "buy":
            caps = [max_single]
            if action == "buy":
                caps.append(max(0.0, max_symbol_position - current_symbol_value))
                caps.append(available_balance)
                caps.append(max(0.0, max_total_exposure - current_total_exposure))
            max_allowed_notional = min(caps) if caps else proposed_notional

        # 卖出不受仓位/余额限制, 只受单笔上限和持仓量限制
        if action == "sell":
            max_sell_value = current_symbol_value
            max_allowed_notional = min(max_single, max_sell_value)

        # 夹断
        clamped = proposed_notional > max_allowed_notional
        final_notional = min(proposed_notional, max_allowed_notional)

        # 最小订单价值检查
        if final_notional < cfg["min_order_value"] and final_notional > 0:
            clamp_reasons.append(
                f"夹断后订单 {final_notional:.2f} 低于最小订单价值 "
                f"{cfg['min_order_value']:.0f}, 降级为 hold"
            )
            result["action"] = "hold"
            result["quantity"] = 0.0
            result["notional"] = 0.0
            result["clamped"] = True
            result["clamp_reasons"] = clamp_reasons
            return result

        result["quantity"] = final_notional / price if price > 0 else 0.0
        result["notional"] = final_notional
        result["clamped"] = clamped
        result["clamp_reasons"] = clamp_reasons
        return result

    def _extract_signals(self, indicators: Dict[str, Any]) -> List[Signal]:
        """从组合指标提取标准化信号 (HC-1)"""
        signals: List[Signal] = []
        positions = indicators.get("positions", [])
        drift = indicators.get("drift", 0)
        rebalance = indicators.get("rebalance_needed", False)
        total_weight = indicators.get("total_weight", 0)

        # 漂移度信号
        if drift > 0.03:
            signals.append(Signal("漂移度", drift, "short", 0.6))
        elif drift < 0.01:
            signals.append(Signal("漂移度", drift, "neutral", 0.4))
        else:
            signals.append(Signal("漂移度", drift, "neutral", 0.45))

        # 再平衡需求信号
        if rebalance:
            signals.append(Signal("再平衡需求", True, "short", 0.55))
        else:
            signals.append(Signal("再平衡需求", False, "long", 0.5))

        # 总仓位信号
        if total_weight > 0.9:
            signals.append(Signal("总仓位", total_weight, "short", 0.5))
        elif total_weight < 0.5:
            signals.append(Signal("总仓位", total_weight, "long", 0.5))
        else:
            signals.append(Signal("总仓位", total_weight, "neutral", 0.4))

        # 个别仓位超配信号
        for pos in positions[:3]:
            symbol = pos.get("symbol", "")
            weight = pos.get("weight", 0)
            pnl = pos.get("pnl_pct", 0)
            if weight > 0.4:
                signals.append(Signal(f"{symbol}仓位", weight, "short", 0.55))
            if pnl < -0.05:
                signals.append(Signal(f"{symbol}盈亏", pnl, "short", 0.6))
            elif pnl > 0.05:
                signals.append(Signal(f"{symbol}盈亏", pnl, "long", 0.55))

        return signals

    def _generate_summary(self, signals: List[Signal], rationale: List[str],
                          direction: str, confidence: float) -> str:
        if self._llm_fn is not None:
            try:
                prompt = (
                    f"组合分析摘要: 方向={direction}, 置信度={confidence:.2f}, "
                    f"信号={[s.to_dict() for s in signals]}, "
                    f"理由={rationale[:3]}"
                )
                return self._llm_fn(prompt)[:300]
            except Exception:  # noqa: BLE001 FAIL-OPEN
                pass
        long_count = sum(1 for s in signals if s.direction == "long")
        short_count = sum(1 for s in signals if s.direction == "short")
        return (f"组合面{direction}({confidence:.0%}), "
                f"多信号{long_count}/空信号{short_count}")

    def _generate_charts(self, indicators: Dict[str, Any]) -> List[ChartSpec]:
        charts: List[ChartSpec] = []

        positions = indicators.get("positions", [])
        target = indicators.get("target_weight", {})

        # 饼图: 当前仓位分布
        pie_data = [{"name": p.get("symbol", ""), "value": p.get("weight", 0)}
                     for p in positions]
        charts.append(ChartSpec(
            type="pie",
            title="仓位分布",
            data=pie_data,
            config={"radius": ["40%", "70%"]},
        ))

        # 柱状图: 当前 vs 目标权重对比
        bar_names = [p.get("symbol", "") for p in positions]
        bar_current = [p.get("weight", 0) for p in positions]
        bar_target = [target.get(s, 0) for s in bar_names]
        charts.append(ChartSpec(
            type="bar",
            title="当前 vs 目标权重",
            data={"current": bar_current, "target": bar_target},
            config={
                "xAxis": {"type": "category", "data": bar_names},
                "yAxis": {"type": "value", "name": "权重"},
                "series": [
                    {"name": "当前", "type": "bar", "data": bar_current},
                    {"name": "目标", "type": "bar", "data": bar_target},
                ],
            },
        ))

        return charts


def handle_portfolio_agent(params: dict) -> dict:
    """IPC handler: portfolio-agent"""
    try:
        from subagent_registry import get_handler_llm_fn
        agent = PortfolioAgent(llm_fn=get_handler_llm_fn())
        output = agent.execute(params.get("node_output", {}))
        return {"ok": True, "output": output.to_dict()}
    except Exception as e:
        return {"ok": False, "error": str(e), "stack": traceback.format_exc()}
