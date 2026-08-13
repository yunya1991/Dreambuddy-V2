"""A系列选币层 — Hermes驱动大模型调用SKILL产出多空代币池

核心职责：
    1. 调用6-TRADING/skills中的asset-research和dream-attention-radar SKILL
    2. 融合多个SKILL输出，产出多头代币池和空头代币池
    3. 代币池作为整个系统的公共数据，写入共享State

调用方式：
    - 实盘：Hermes驱动大模型调用SKILL
    - 回测/测试：使用mock数据
"""
from __future__ import annotations

from typing import Any, Dict, List
from pathlib import Path


class CoinSelector:
    """多空代币池选择器

    通过融合多个SKILL的分析结果，产出最适合做多和做空的代币池。
    """

    # SKILL路径
    SKILL_BASE = Path(__file__).parent.parent.parent.parent / "6-TRADING" / "skills"
    ASSET_RESEARCH_SKILL = SKILL_BASE / "asset-research"
    ATTENTION_RADAR_SKILL = SKILL_BASE / "dream-attention-radar"

    def __init__(self, use_hermes: bool = True):
        """初始化选币器

        Args:
            use_hermes: 是否使用Hermes大模型调用SKILL（False=使用本地mock）
        """
        self.use_hermes = use_hermes
        self._skill_cache: Dict[str, Any] = {}

    def select(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """产出多空代币池

        Args:
            market_data: 市场数据，包含symbols列表、K线数据等

        Returns:
            {
                "long_pool": [{"symbol": "BTC", "score": 0.85, "reasons": [...]}],
                "short_pool": [{"symbol": "DOGE", "score": 0.72, "reasons": [...]}],
                "timestamp": "2026-08-14T02:00:00Z",
                "source": "hermes" | "mock"
            }
        """
        if self.use_hermes:
            return self._select_via_hermes(market_data)
        else:
            return self._select_mock(market_data)

    def _select_via_hermes(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """通过Hermes大模型调用SKILL进行选币

        Hermes调度流程：
            1. 调用asset-research SKILL → 资产调研结果
            2. 调用dream-attention-radar SKILL → 注意力排名
            3. 融合结果 → 多空代币池
        """
        # TODO: 接入Hermes API进行大模型SKILL调用
        # 当前阶段降级为mock，后续接入Hermes
        return self._select_mock(market_data)

    def _select_mock(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """Mock选币逻辑（用于测试和开发阶段）"""
        symbols = market_data.get("symbols", ["BTC", "ETH", "SOL"])
        long_pool = []
        short_pool = []

        for i, sym in enumerate(symbols):
            if i % 2 == 0:
                long_pool.append({
                    "symbol": sym,
                    "score": 0.85 - i * 0.05,
                    "reasons": ["mock: 趋势向上", "mock: 资金流入"],
                })
            else:
                short_pool.append({
                    "symbol": sym,
                    "score": 0.72 - i * 0.05,
                    "reasons": ["mock: 趋势向下", "mock: 资金流出"],
                })

        return {
            "long_pool": long_pool,
            "short_pool": short_pool,
            "timestamp": "2026-08-14T02:00:00Z",
            "source": "mock",
        }
