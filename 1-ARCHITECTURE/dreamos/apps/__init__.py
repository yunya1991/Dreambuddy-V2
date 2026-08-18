"""
Dreambuddy OS — 应用层

基于 S-A-C-G 四层内核构建的应用:

    trading_agent/    交易 Agent（串联 S-A-C-G 全链路）
    api_server.py     HTTP REST API（Flask）
    cli.py            命令行工具（CLI / REPL）

快速上手:
    # Python API
    from dreamos.apps.trading_agent import TradingAgent
    agent = TradingAgent()
    result = agent.run(user_input="BTC 趋势？", market_data={...})

    # HTTP API
    python -m dreamos.apps.api_server

    # CLI
    python -m dreamos.apps.cli repl
    python -m dreamos.apps.cli analyze --price 65000 --rsi 55
"""

from .trading_agent import TradingAgent
from .api_server import create_app

__all__ = [
    "TradingAgent",
    "create_app",
]
