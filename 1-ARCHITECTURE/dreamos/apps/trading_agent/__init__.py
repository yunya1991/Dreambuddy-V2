"""
Dreambuddy OS — Trading Agent 应用

基于 Dreambuddy OS 内核（S-A-C-G 四层架构）实现的交易 Agent。

核心流程:
    user_input + market_data
        → S 层（IntentEngine）  识别交易意图
        → A 层（GraphPlanner）  动态选节点编排执行图
        → C 层（GraphExecutor） 执行节点+反射+聚合
        → G 层（GraphStore）    持久化状态与历史
        → 返回 {action, confidence, rationale, ...}

快速上手:
    from dreamos.apps.trading_agent import TradingAgent

    agent = TradingAgent()
    result = agent.run(
        user_input="BTC 现在能做多吗？",
        market_data={"price": 65000, "rsi14": 45, "ema20": 64000},
    )
    print(f"{result['action']} @ {result['confidence']:.1%}")
"""

from .agent import TradingAgent

__all__ = ["TradingAgent"]
