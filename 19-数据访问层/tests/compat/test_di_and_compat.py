"""
P0-5/P0-6/P0-7 TDD RED：
  - di.py：get_*_repo 依赖注入（按 DB_BACKEND 选三后端 + Kill-Switch 优先级最高）
  - compat：5 处旧 TradeRecord 独立定义 DeprecationWarning 兼容导入
  - JsonLegacyImpl × 6：薄适配器 override 所有抽象方法（否则实例化 TypeError）
"""
from __future__ import annotations

import os
import warnings
from datetime import datetime, timezone
from decimal import Decimal

import pytest


# ---------- 1. di.py 功能 ----------
class TestDependencyInjection:
    def test_6_factory_functions_importable(self):
        from dreambuddy_dal.di import (
            get_config_repo,
            get_kg_repo,
            get_market_macro_repo,
            get_position_repo,
            get_risk_repo,
            get_trade_repo,
        )
        for fn in [get_trade_repo, get_position_repo, get_market_macro_repo,
                   get_risk_repo, get_config_repo, get_kg_repo]:
            assert callable(fn)

    def test_default_backend_is_json_legacy_from_env(self, monkeypatch):
        """默认 DB_BACKEND=json_legacy 返回 JsonLegacyImpl"""
        monkeypatch.setenv("DB_BACKEND", "json_legacy")
        # 删除 Kill-Switch 文件
        import os as _os
        ks = os.path.join(os.environ["DATA_DIR"], "DISABLE_DAL_NEW")
        if _os.path.exists(ks):
            _os.unlink(ks)

        from dreambuddy_dal.di import get_trade_repo
        from dreambuddy_dal.protocols import TradeRepository
        repo = get_trade_repo()
        assert isinstance(repo, TradeRepository)
        # 类名里带 JsonLegacy
        assert "JsonLegacy" in type(repo).__name__, \
            f"默认后端返回的不是 JsonLegacy：{type(repo).__name__}"

    def test_backend_parameter_overrides_env(self):
        """显式 backend='json_legacy' 参数优先于环境变量"""
        from dreambuddy_dal.di import get_position_repo
        from dreambuddy_dal.protocols import PositionRepository
        repo = get_position_repo(backend="json_legacy")
        assert isinstance(repo, PositionRepository)
        assert "JsonLegacy" in type(repo).__name__

    def test_invalid_backend_raises_value_error(self):
        """backend='postgres' 目前未实现 → ValueError"""
        from dreambuddy_dal.di import get_risk_repo
        with pytest.raises(ValueError, match="DB_BACKEND"):
            get_risk_repo(backend="postgres_not_exists")

    def test_kill_switch_forces_json_legacy_even_when_env_sqlite(self, monkeypatch, tmp_path):
        """
        Kill-Switch = $DATA_DIR/DISABLE_DAL_NEW 物理文件存在
        → 强制 json_legacy，无视 DB_BACKEND=sqlite
        """
        ks_path = os.path.join(os.environ["DATA_DIR"], "DISABLE_DAL_NEW")
        # 创建 Kill-Switch 文件
        with open(ks_path, "w") as f:
            f.write("manual rollback @ 2026-08-24 11:00 UTC")
        try:
            # 环境变量写 sqlite，但 Kill-Switch 在 → 仍返回 JsonLegacy
            monkeypatch.setenv("DB_BACKEND", "sqlite_unified")
            from dreambuddy_dal.di import get_config_repo
            repo = get_config_repo()
            assert "JsonLegacy" in type(repo).__name__, \
                f"Kill-Switch 不生效：实际返回 {type(repo).__name__}"
        finally:
            os.unlink(ks_path)


# ---------- 2. 兼容导入：5 处旧定义保留 DeprecationWarning ----------
class TestCompatDeprecation:
    def test_old_trading_utils_import_warns(self):
        """
        经验 698940：旧路径 `from dreambuddy_dal.compat import TradeRecord`
        应抛出 DeprecationWarning，并指向 dreambuddy_dal.unified_models。
        P0 兼容：旧位置符号保留薄 aliases（不炸，只是警告），类型 == SSoT
        """
        # 强制重置「已警告」集合（避免其他测试先触发过影响）
        import dreambuddy_dal.compat as _compat_mod
        from dreambuddy_dal import unified_models as _new
        _compat_mod._warned.clear()

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            # 懒访问触发 compat.__getattr__（模块加载 → 真正属性查找 → 警告）
            import dreambuddy_dal.compat
            _LegacyAlias = dreambuddy_dal.compat.TradeRecord
            # 验证别名 == 真正的类（不是山寨的）
            assert _LegacyAlias is _new.TradeRecord
            # 验证 LEGACY_TRADE_RECORD_SYMBOLS 表至少 1 条
            assert len(dreambuddy_dal.compat.LEGACY_TRADE_RECORD_SYMBOLS) >= 1
            # 验证触发了 DeprecationWarning
            deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(deprecation_warnings) >= 1, "旧别名 import 未触发 DeprecationWarning"


# ---------- 3. JsonLegacyImpl 6 个类都能实例化（覆盖所有 abstractmethod）----------
class TestJsonLegacyImplInstantiation:
    @pytest.mark.parametrize("factory,backend,protocol", [
        ("get_trade_repo", "json_legacy", "TradeRepository"),
        ("get_position_repo", "json_legacy", "PositionRepository"),
        ("get_market_macro_repo", "json_legacy", "MarketMacroRepository"),
        ("get_risk_repo", "json_legacy", "RiskRepository"),
        ("get_config_repo", "json_legacy", "ConfigRepository"),
        ("get_kg_repo", "json_legacy", "KnowledgeGraphRepository"),
    ])
    def test_each_json_legacy_impl_instantiates(self, factory, backend, protocol):
        """任何 JsonLegacyXxxImpl 实例化不抛 TypeError（证明所有 abstractmethod 被覆盖）"""
        import dreambuddy_dal.di as di_mod
        import dreambuddy_dal.protocols as proto_pkg
        fn = getattr(di_mod, factory)
        repo = fn(backend=backend)
        proto_cls = getattr(proto_pkg, protocol)
        assert isinstance(repo, proto_cls)

    def test_add_trade_round_trip(self):
        """JsonLegacyTradeRepo.add_trade(t) 返回 trade_id，get_trade 查得回来（薄适配器）"""
        from dreambuddy_dal.di import get_trade_repo
        from dreambuddy_dal.unified_models import (
            TradeDirection,
            TradeRecord,
            TradeStatus,
            TrialStatus,
        )
        repo = get_trade_repo(backend="json_legacy")
        t = TradeRecord(
            trade_id=f"T-P0-{datetime.now(timezone.utc).strftime('%H%M%S%f')}",
            sub_system="TEST", strategy_name="p0_smoke", symbol="XAGUSDT",
            direction=TradeDirection.LONG, entry_price=Decimal("25.5"), quantity=Decimal("0.1"),
            entry_ts=datetime.now(timezone.utc),
            stop_loss=Decimal("25.3"), take_profit=Decimal("26.1"),
            risk_level_cn="低风险",
            is_trial=True, trial_status=TrialStatus.TICKING,
            trial_open_ts=datetime.now(timezone.utc),
        )
        tid = repo.add_trade(t)
        assert tid == t.trade_id
        # get_trade 查得回来
        got = repo.get_trade(t.trade_id)
        assert got is not None
        assert got.entry_price == t.entry_price
        assert got.status == TradeStatus.OPEN
