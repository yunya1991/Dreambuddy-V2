"""test_interfaces.py — 窄接口边界单元测试（D4: ds4 窄接口借鉴）

SPEC: SPEC-ds4架构借鉴与系统增强.md §3.2 Dimension 4
哲学: ds4.h 只暴露 engine + session 两个抽象——窄接口边界。
映射: 定义核心窄接口（Protocol），引擎只依赖这些接口，不依赖具体实现。

核心接口:
  - StrategyGene: 策略基因标准表示
  - TradeSession: 一次交易的完整时间线
  - MarketState: 市场状态快照
  - PathCandidate: 候选交易路径

覆盖:
  - Protocol 定义完整性（字段存在）
  - runtime_checkable 结构子类型检查
  - 现有 dict-based 对象兼容（不强制改造）
"""
from __future__ import annotations

from typing import Any

import pytest

from dreambuddy_evolution.core.interfaces import (
    StrategyGene,
    TradeSession,
    MarketState,
    PathCandidate,
)


# ==============================================================================
# 1. StrategyGene 接口
# ==============================================================================
class TestStrategyGene:
    """D4: 策略基因窄接口"""

    def test_valid_gene_passes_isinstance(self):
        """符合 StrategyGene 结构的对象通过 isinstance 检查"""

        class MyGene:
            gene_id: str = "gene_001"
            action_ids: list[str] = ["a1", "a2"]
            ess: float = 0.75
            n_samples: int = 150

        assert isinstance(MyGene(), StrategyGene)

    def test_invalid_gene_fails_isinstance(self):
        """缺少必需字段的对象不通过 isinstance 检查"""

        class BadGene:
            gene_id: str = "gene_002"
            # 缺少 action_ids, ess, n_samples

        assert not isinstance(BadGene(), StrategyGene)

    def test_dict_not_a_protocol(self):
        """普通 dict 不满足 Protocol（无属性访问）"""
        gene_dict = {"gene_id": "g1", "action_ids": [], "ess": 0.5, "n_samples": 0}
        assert not isinstance(gene_dict, StrategyGene)


# ==============================================================================
# 2. TradeSession 接口
# ==============================================================================
class TestTradeSession:
    """D4: 交易会话窄接口"""

    def test_valid_session_passes(self):
        """符合 TradeSession 结构的对象通过检查"""

        class Session:
            session_id: str = "sess_001"
            symbol: str = "BTC"
            entry_time: float = 1700000000.0
            exit_time: float | None = None
            entry_price: float = 50000.0
            exit_price: float | None = None
            direction: str = "long"

        assert isinstance(Session(), TradeSession)

    def test_missing_symbol_fails(self):
        """缺少 symbol 的会话不通过"""

        class BadSession:
            session_id: str = "s"
            entry_time: float = 0.0

        assert not isinstance(BadSession(), TradeSession)


# ==============================================================================
# 3. MarketState 接口
# ==============================================================================
class TestMarketState:
    """D4: 市场状态窄接口"""

    def test_valid_market_state_passes(self):
        """符合 MarketState 结构的对象通过检查"""

        class Market:
            symbol: str = "BTC"
            price: float = 50000.0
            volatility: float = 0.02
            timestamp: float = 1700000000.0

        assert isinstance(Market(), MarketState)

    def test_missing_price_fails(self):
        """缺少 price 的市场状态不通过"""

        class BadMarket:
            symbol: str = "BTC"
            volatility: float = 0.02

        assert not isinstance(BadMarket(), MarketState)


# ==============================================================================
# 4. PathCandidate 接口
# ==============================================================================
class TestPathCandidate:
    """D4: 候选路径窄接口"""

    def test_valid_path_passes(self):
        """符合 PathCandidate 结构的对象通过检查"""

        class Path:
            path_id: str = "p1"
            source: str = "deep_reasoning"
            direction: str = "long"
            expected_return: float = 0.15
            confidence: float = 0.8
            resistance: float = 0.2

        assert isinstance(Path(), PathCandidate)

    def test_missing_confidence_fails(self):
        """缺少 confidence 的路径不通过"""

        class BadPath:
            path_id: str = "p1"
            direction: str = "long"
            expected_return: float = 0.1

        assert not isinstance(BadPath(), PathCandidate)


# ==============================================================================
# 5. 渐进式兼容性
# ==============================================================================
class TestProgressiveCompatibility:
    """D4: 窄接口不破坏现有 dict-based 代码"""

    def test_existing_dict_paths_still_work(self):
        """现有 dict-based 路径不满足 Protocol（设计如此，渐进式）"""
        path_dict = {
            "path_id": "deep_reasoning_mc",
            "source": "deep_reasoning",
            "direction": "long",
            "expected_return": 0.1,
            "confidence": 0.7,
            "resistance": 0.3,
        }
        # dict 不是 Protocol 实例，但业务逻辑仍可正常使用 dict
        assert not isinstance(path_dict, PathCandidate)
        # 验证 dict 业务逻辑不受影响
        assert path_dict["direction"] == "long"

    def test_interfaces_are_importable(self):
        """所有 4 个接口可正常导入"""
        from dreambuddy_evolution.core import interfaces

        assert hasattr(interfaces, "StrategyGene")
        assert hasattr(interfaces, "TradeSession")
        assert hasattr(interfaces, "MarketState")
        assert hasattr(interfaces, "PathCandidate")
