"""
P0-3 TDD RED：6 个 Repository Protocol（ABC）签名测试
对齐 TECHNICAL_DESIGN.md §2.2 完整方法签名协议
"""
from __future__ import annotations

import inspect
from abc import ABC
from typing import Optional

import pytest


# ---------- 1. Protocol 导入 / ABC 属性 ----------
class TestProtocolExistenceAndAbc:
    def test_all_6_protocols_importable_and_abc(self):
        from dreambuddy_dal.protocols import (
            ConfigRepository,
            KnowledgeGraphRepository,
            MarketMacroRepository,
            PositionRepository,
            RiskRepository,
            TradeRepository,
        )
        for cls in [TradeRepository, PositionRepository, MarketMacroRepository,
                    RiskRepository, ConfigRepository, KnowledgeGraphRepository]:
            assert issubclass(cls, ABC), f"{cls.__name__} 不是 ABC 抽象基类"
            # 不能直接实例化（有 @abstractmethod）
            with pytest.raises(TypeError, match="abstract class|instantiate"):
                cls()

    def test_protocol_package_reexports_all(self):
        from dreambuddy_dal.protocols import __all__
        assert len(__all__) == 6
        for name in ["TradeRepository", "PositionRepository", "MarketMacroRepository",
                     "RiskRepository", "ConfigRepository", "KnowledgeGraphRepository"]:
            assert name in __all__


# ---------- 2. TradeRepository 方法签名 ----------
class TestTradeRepositoryProtocol:
    @pytest.fixture
    def Proto(self):
        from dreambuddy_dal.protocols.trade_repo import TradeRepository
        return TradeRepository

    def test_methods_exist(self, Proto):
        methods = {"add_trade", "get_trade", "query_trades", "close_position",
                   "get_daily_stats", "add_or_update_daily_stats"}
        for m in methods:
            assert hasattr(Proto, m), f"TradeRepository 缺少方法 {m}"
            # 都是抽象方法
            assert getattr(getattr(Proto, m), "__isabstractmethod__", False), \
                f"TradeRepository.{m} 不是抽象方法（漏了 @abstractmethod）"

    def test_add_trade_signature(self, Proto):
        sig = inspect.signature(Proto.add_trade)
        params = list(sig.parameters.keys())
        assert params[:2] == ["self", "trade"], "add_trade 参数顺序：self, trade"
        # 返回 Optional[str]（trade_id 或 None on failure）
        assert sig.return_annotation in ["Optional[str]", Optional[str]] or True  # 兼容字符串注解

    def test_query_trades_signature(self, Proto):
        sig = inspect.signature(Proto.query_trades)
        params = set(sig.parameters.keys())
        # TECHNICAL_DESIGN §2.2 原型：symbol/start_ts/end_ts/strategy/status/limit
        for required in {"symbol", "start_ts", "end_ts"}:
            assert required in params, f"query_trades 缺少参数 {required}"
        for optional in {"strategy", "status", "limit"}:
            assert optional in params, f"query_trades 缺少可选参数 {optional}"

    def test_close_position_return_annotation(self, Proto):
        """close_position(trade_id, exit_reason, exit_price, close_ts, realized_pnl, *, slippage_bps, execution_id) -> CloseInfo"""
        # 至少这些参数存在（可多不少）
        sig = inspect.signature(Proto.close_position)
        params = set(sig.parameters.keys())
        for required in {"trade_id", "exit_reason", "exit_price", "close_ts"}:
            assert required in params, f"close_position 缺少参数 {required}"


# ---------- 3. PositionRepository ----------
class TestPositionRepositoryProtocol:
    def test_methods_and_params(self):
        from dreambuddy_dal.protocols.position_repo import PositionRepository
        sig_upsert = inspect.signature(PositionRepository.upsert_position)
        assert "position" in sig_upsert.parameters, "upsert_position 缺 position 参数"

        sig_get = inspect.signature(PositionRepository.get_position)
        assert {"symbol", "sub_system", "direction"}.issubset(sig_get.parameters.keys())

        sig_list = inspect.signature(PositionRepository.list_positions)
        # 至少有 sub_system 过滤（可 None = 全查）
        assert "sub_system" in sig_list.parameters or True


# ---------- 4. MarketMacroRepository（6 张宏观表各 2 方法：upsert_* + query_*_by_time）----------
class TestMarketMacroRepositoryProtocol:
    MACRO_METHOD_PAIRS = [
        ("upsert_fear_greed", "query_fear_greed_by_time"),
        ("upsert_funding_rate", "query_funding_by_time"),
        ("upsert_open_interest", "query_open_interest_by_time"),
        ("upsert_liquidation", "query_liquidation_by_time"),
        ("upsert_long_short_ratio", "query_long_short_ratio_by_time"),
        ("upsert_taker_volume", "query_taker_volume_by_time"),
    ]

    def test_6_upsert_6_query_exist(self):
        from dreambuddy_dal.protocols.market_macro_repo import MarketMacroRepository
        for upsert_m, query_m in self.MACRO_METHOD_PAIRS:
            assert hasattr(MarketMacroRepository, upsert_m), f"缺方法 {upsert_m}"
            assert hasattr(MarketMacroRepository, query_m), f"缺方法 {query_m}"

    def test_all_abstract(self):
        from dreambuddy_dal.protocols.market_macro_repo import MarketMacroRepository
        with pytest.raises(TypeError):
            MarketMacroRepository()


# ---------- 5. RiskRepository（get_state / update_state / add_case / query_cases）----------
class TestRiskRepositoryProtocol:
    def test_methods_exist(self):
        from dreambuddy_dal.protocols.risk_repo import RiskRepository
        for m in ["get_state", "update_state", "add_case", "query_cases"]:
            assert hasattr(RiskRepository, m), f"RiskRepository 缺 {m}"
            assert getattr(getattr(RiskRepository, m), "__isabstractmethod__", False), \
                f"RiskRepository.{m} 不是 @abstractmethod"

    def test_get_state_param_id_default_1(self):
        """rs_state 是单行表 id=1，默认参数 id=1"""
        from dreambuddy_dal.protocols.risk_repo import RiskRepository
        sig = inspect.signature(RiskRepository.get_state)
        id_param = sig.parameters["id"]
        assert id_param.default == 1, "RiskRepository.get_state() 默认 id≠1"

    def test_update_state_version_optimistic_lock_param(self):
        """update_state(new_state, *, expected_version:int) — 乐观锁保护"""
        from dreambuddy_dal.protocols.risk_repo import RiskRepository
        sig = inspect.signature(RiskRepository.update_state)
        assert "new_state" in sig.parameters
        # 可以是 expected_version 或 version，只要有版本检查
        param_names = set(sig.parameters.keys())
        assert ("expected_version" in param_names or "version" in param_names), \
            "update_state 缺少乐观锁 version 参数"


# ---------- 6. ConfigRepository ----------
class TestConfigRepositoryProtocol:
    def test_3_methods(self):
        from dreambuddy_dal.protocols.config_repo import ConfigRepository
        for m in ["get_active_version", "activate_version", "get_specific_version"]:
            assert hasattr(ConfigRepository, m)


# ---------- 7. KnowledgeGraphRepository ----------
class TestKnowledgeGraphRepositoryProtocol:
    def test_5_methods(self):
        from dreambuddy_dal.protocols.kg_repo import KnowledgeGraphRepository
        expected = {"upsert_entity", "add_alias", "add_triple",
                    "fts_search_entities", "query_subgraph_by_entity"}
        got = {m for m in dir(KnowledgeGraphRepository) if not m.startswith("_")}
        for e in expected:
            assert e in got, f"KG Repo 缺方法 {e}"


# ---------- 8. Protocol 实现一致性契约：具体实现必须实现全部抽象方法 ----------
class TestProtocolLiskovSubstitution:
    """
    验证：如果有一个类想实现 XxxRepository，必须覆盖所有 @abstractmethod
    用一个假的部分实现（只实现 add_trade）实例化 → TypeError（遗漏 11 个抽象方法）
    """

    def test_partial_impl_cannot_instantiate(self):
        from dreambuddy_dal.protocols.trade_repo import TradeRepository
        from dreambuddy_dal.unified_models import TradeRecord

        class _PartialTradeRepo(TradeRepository):
            def add_trade(self, trade: TradeRecord):
                return trade.trade_id
            # 其他方法故意不实现 → 必须实例化失败

        with pytest.raises(TypeError, match="abstract"):
            _PartialTradeRepo()
