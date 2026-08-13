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
        """Mock选币逻辑（用于测试和开发阶段）

        Mock模式下仍然走融合流程：
            1. 调用 _call_asset_research（mock返回）
            2. 调用 _call_attention_radar（mock返回）
            3. 调用 _fuse_results 融合产出多空代币池
        """
        symbols = market_data.get("symbols", ["BTC", "ETH", "SOL"])

        # 调用 mock SKILL
        asset_research = self._call_asset_research(region="global")
        attention_radar = self._call_attention_radar(symbols=symbols)

        # 融合产出多空代币池
        fused = self._fuse_results(asset_research, attention_radar)

        return {
            "long_pool": fused["long_pool"],
            "short_pool": fused["short_pool"],
            "timestamp": "2026-08-14T02:00:00Z",
            "source": "mock",
        }

    # ---- Task 2: SKILL 调用与融合 ----

    def _call_asset_research(self, region: str = "global") -> Dict[str, Any]:
        """调用asset-research SKILL进行资产调研

        Args:
            region: 调研区域，如 global / asia / americas

        Returns:
            {
                "engineName": "AssetResearch",
                "region": "global",
                "phase": "discovery",
                "priority_assets": [{"symbol": "BTC", "score": 0.9, "reason": "..."}],
                "source": "hermes" | "mock"
            }
        """
        if self.use_hermes:
            # TODO: 通过Hermes调用asset-research SKILL
            pass

        # Mock 返回
        return {
            "engineName": "AssetResearch",
            "region": region,
            "phase": "discovery",
            "priority_assets": [
                {"symbol": "BTC", "score": 0.9, "reason": "strong trend"},
                {"symbol": "ETH", "score": 0.8, "reason": "volume surge"},
                {"symbol": "SOL", "score": 0.75, "reason": "ecosystem growth"},
            ],
            "source": "mock",
        }

    def _call_attention_radar(self, symbols: List[str]) -> Dict[str, Any]:
        """调用dream-attention-radar SKILL获取注意力排名

        Args:
            symbols: 待排名的代币符号列表

        Returns:
            {
                "long_top": [{"symbol": "BTC", "score": 0.85, "reason": "..."}],
                "short_top": [{"symbol": "DOGE", "score": 0.65, "reason": "..."}],
                "source": "hermes" | "mock"
            }
        """
        if self.use_hermes:
            # TODO: 通过Hermes调用dream-attention-radar SKILL
            pass

        # Mock 返回
        long_top = []
        short_top = []
        for i, sym in enumerate(symbols):
            if i % 2 == 0:
                long_top.append({
                    "symbol": sym,
                    "score": 0.85 - i * 0.05,
                    "reason": "attention high",
                })
            else:
                short_top.append({
                    "symbol": sym,
                    "score": 0.65 - i * 0.05,
                    "reason": "attention low",
                })

        return {
            "long_top": long_top,
            "short_top": short_top,
            "source": "mock",
        }

    def _fuse_results(
        self,
        asset_research: Dict[str, Any],
        attention_radar: Dict[str, Any],
    ) -> Dict[str, Any]:
        """融合asset-research和attention-radar结果，产出多空代币池

        融合策略：
            1. 从asset_research的priority_assets中提取候选
            2. 与attention_radar的long_top/short_top做交集匹配
            3. 同时出现在两个来源的代币获得加权得分
            4. 仅出现在一个来源的代币降权保留

        Args:
            asset_research: _call_asset_research 的返回结果
            attention_radar: _call_attention_radar 的返回结果

        Returns:
            {
                "long_pool": [{"symbol": "...", "score": 0.0, "reasons": [...]}],
                "short_pool": [{"symbol": "...", "score": 0.0, "reasons": [...]}],
            }
        """
        # 构建 attention_radar 查找索引
        long_map: Dict[str, Dict[str, Any]] = {
            item["symbol"]: item for item in attention_radar.get("long_top", [])
        }
        short_map: Dict[str, Dict[str, Any]] = {
            item["symbol"]: item for item in attention_radar.get("short_top", [])
        }

        # 构建 asset_research 查找索引
        asset_map: Dict[str, Dict[str, Any]] = {
            item["symbol"]: item
            for item in asset_research.get("priority_assets", [])
        }

        long_pool: List[Dict[str, Any]] = []
        short_pool: List[Dict[str, Any]] = []

        # 处理 long_top：与 asset_research 交集优先，应用 crypto_priority
        for item in attention_radar.get("long_top", []):
            sym = item["symbol"]
            reasons = [item.get("reason", "attention signal")]
            if sym in asset_map:
                base_score = (item.get("score", 0.5) + asset_map[sym].get("score", 0.5)) / 2
                reasons.append(asset_map[sym].get("reason", "asset research"))
            else:
                base_score = item.get("score", 0.5) * 0.8  # 降权
            # crypto_priority: priority=1.0 保持原分，priority=0.5 降权
            crypto_priority = asset_map.get(sym, {}).get("priority", 1.0)
            score = base_score * crypto_priority
            long_pool.append({
                "symbol": sym,
                "score": round(score, 4),
                "reasons": reasons,
            })

        # 处理 short_top
        for item in attention_radar.get("short_top", []):
            sym = item["symbol"]
            reasons = [item.get("reason", "attention signal")]
            if sym in asset_map:
                base_score = (item.get("score", 0.5) + asset_map[sym].get("score", 0.5)) / 2
                reasons.append(asset_map[sym].get("reason", "asset research"))
            else:
                base_score = item.get("score", 0.5) * 0.8
            crypto_priority = asset_map.get(sym, {}).get("priority", 1.0)
            score = base_score * crypto_priority
            short_pool.append({
                "symbol": sym,
                "score": round(score, 4),
                "reasons": reasons,
            })

        # 补充仅出现在 asset_research 但不在 attention_radar 中的代币
        for item in asset_research.get("priority_assets", []):
            sym = item["symbol"]
            if sym not in long_map and sym not in short_map:
                crypto_priority = item.get("priority", 1.0)
                long_pool.append({
                    "symbol": sym,
                    "score": round(item.get("score", 0.5) * 0.7 * crypto_priority, 4),
                    "reasons": [item.get("reason", "asset research only")],
                })

        return {
            "long_pool": long_pool,
            "short_pool": short_pool,
        }


# ---- Task 4: CoinSelectorNode ----

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult, NodeStatus


class CoinSelectorNode(BaseNode):
    """CoinSelector node wrapper for DreamOS orchestration.

    Wraps CoinSelector into a BaseNode-compatible node,
    enabling it to participate in the DreamOS execution graph.
    """

    node_id: str = "COIN_SELECTOR"
    name: str = "Coin Selector"
    description: str = "Select long/short token pools via SKILL fusion"
    chain: str = "A"
    tags: list = ["trading", "selection"]

    def __init__(self, use_hermes: bool = False, **kwargs):
        super().__init__(**kwargs)
        self._selector = CoinSelector(use_hermes=use_hermes)

    def execute_core(self, state: State) -> NodeResult:
        """Execute coin selection and return NodeResult with pools.

        Reads market data from state.market, calls CoinSelector.select(),
        and wraps the result into a NodeResult.
        """
        market_data = state.market or {"symbols": ["BTC", "ETH", "SOL"]}

        pools = self._selector.select(market_data=market_data)

        long_count = len(pools.get("long_pool", []))
        short_count = len(pools.get("short_pool", []))
        total = long_count + short_count

        confidence = min(1.0, total / 10.0) if total > 0 else 0.0

        return NodeResult(
            node_id=self.node_id,
            status=NodeStatus.SUCCESS,
            confidence=confidence,
            outputs={
                "long_pool": pools.get("long_pool", []),
                "short_pool": pools.get("short_pool", []),
                "timestamp": pools.get("timestamp", ""),
                "source": pools.get("source", "mock"),
            },
        )
