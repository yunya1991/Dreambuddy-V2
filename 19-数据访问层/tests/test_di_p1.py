"""
TDD: di.py 三后端激活 + Kill-Switch 物理文件测试
-------------------------------------------------
共 5 个单测：
 1. test_resolve_backend_kill_switch_forces_json_legacy：存在 DISABLE_DAL_NEW → 强制 json_legacy（无视 env/显式参数）
 2. test_db_backend_env_sqlite_unified_allowed：DB_BACKEND=sqlite_unified → 不抛 NotImplementedError
 3. test_factory_builds_sqlite_trade_risk：sqlite_unified 后端，6 个 repo 都能拿到实例（isinstance Protocol）
 4. test_dual_write_backend_smoke：dual_write 后端可用，repo 类型正确
 5. test_explicit_backend_param_overrides_env：显式传入 backend= 参数覆盖 DB_BACKEND env
"""
from __future__ import annotations

from dreambuddy_dal.protocols import (
    ConfigRepository,
    KnowledgeGraphRepository,
    MarketMacroRepository,
    PositionRepository,
    RiskRepository,
    TradeRepository,
)


# ---------------------------------------------------------------------------
# Kill-Switch 测试（用临时 DATA_DIR 避免污染真实数据）
# ---------------------------------------------------------------------------
def test_resolve_backend_kill_switch_forces_json_legacy(monkeypatch, tmp_path):
    """[1] 物理 Kill-Switch 存在 → 强制 json_legacy，哪怕显式传入 sqlite_unified 也没用。"""
    (tmp_path / "DISABLE_DAL_NEW").write_text("紧急熔断：2026-08-24 db_corrupted")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DB_BACKEND", "sqlite_unified")

    from dreambuddy_dal.di import (
        BACKEND_JSON_LEGACY,
        _resolve_backend,
    )
    # Kill-Switch 优先级最高
    assert _resolve_backend("sqlite_unified") == BACKEND_JSON_LEGACY
    assert _resolve_backend(None) == BACKEND_JSON_LEGACY


def test_db_backend_env_sqlite_unified_allowed(monkeypatch, tmp_path):
    """[2] DB_BACKEND=sqlite_unified 在 P1 启用后，不再抛 NotImplementedError。"""
    # 先确保无 Kill-Switch（新 tmp_path 空）
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DB_BACKEND", "sqlite_unified")

    from dreambuddy_dal.di import (
        BACKEND_SQLITE_UNIFIED,
        _resolve_backend,
    )
    assert _resolve_backend(None) == BACKEND_SQLITE_UNIFIED


def test_factory_builds_all_sqlite_repos(monkeypatch, tmp_path):
    """[3] sqlite_unified 后端：6 工厂拿到实例，均 isinstance 对应 Protocol。"""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DB_BACKEND", "sqlite_unified")

    # 把 sqlite db 路径也指到 tmp 下（避免污染运行态默认）
    monkeypatch.setenv("DREAMBUDDY_CORE_DB", str(tmp_path / "core.db"))

    # 清全局单例缓存（否则其他测试遗留下的 instance 会影响）
    import dreambuddy_dal.di as _di
    _di._INSTANCES.clear()

    from dreambuddy_dal.di import (
        get_config_repo,
        get_kg_repo,
        get_market_macro_repo,
        get_position_repo,
        get_risk_repo,
        get_trade_repo,
    )
    t = get_trade_repo()
    assert isinstance(t, TradeRepository)

    p = get_position_repo()
    assert isinstance(p, PositionRepository)

    mm = get_market_macro_repo()
    assert isinstance(mm, MarketMacroRepository)

    r = get_risk_repo()
    assert isinstance(r, RiskRepository)

    c = get_config_repo()
    assert isinstance(c, ConfigRepository)

    kg = get_kg_repo()
    assert isinstance(kg, KnowledgeGraphRepository)


def test_dual_write_backend_smoke(monkeypatch, tmp_path):
    """[4] dual_write 后端：工厂返回非 None；包装了 legacy + new 双写实例。"""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DREAMBUDDY_CORE_DB", str(tmp_path / "core.db"))

    import dreambuddy_dal.di as _di
    _di._INSTANCES.clear()

    from dreambuddy_dal.di import BACKEND_DUAL_WRITE, get_trade_repo
    repo = get_trade_repo(backend=BACKEND_DUAL_WRITE)
    assert repo is not None
    assert isinstance(repo, TradeRepository)


def test_explicit_backend_param_overrides_env(monkeypatch, tmp_path):
    """[5] 显式 backend= 参数优先级高于 DB_BACKEND env。"""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DB_BACKEND", "json_legacy")
    monkeypatch.setenv("DREAMBUDDY_CORE_DB", str(tmp_path / "core.db"))

    import dreambuddy_dal.di as _di
    _di._INSTANCES.clear()

    from dreambuddy_dal.di import (
        BACKEND_SQLITE_UNIFIED,
        _resolve_backend,
    )
    assert _resolve_backend(BACKEND_SQLITE_UNIFIED) == BACKEND_SQLITE_UNIFIED
