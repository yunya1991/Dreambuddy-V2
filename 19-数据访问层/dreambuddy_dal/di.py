"""
dreambuddy_dal.di — 依赖注入入口（三后端选 + Kill-Switch 物理双保险）
业务代码唯一入口：
    from dreambuddy_dal import (
        get_trade_repo, get_position_repo, get_market_macro_repo,
        get_risk_repo, get_config_repo, get_kg_repo,
    )

选择优先级（由高到低）：
    1. $DATA_DIR/DISABLE_DAL_NEW 物理文件存在 → 强制 json_legacy（任何 env/参数忽略）
    2. backend= 参数（显式传入）
    3. DB_BACKEND 环境变量（默认 json_legacy）

可选后端：
    json_legacy   → JsonLegacy*Repository（25+ JSON / 18 散库薄适配）
    dual_write    → DualWrite*Repository（旧写优先 + 新写防御性 catch，读走 legacy）
    sqlite_unified→ Sqlite*Repository（dreambuddy_core.db 单库）
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Callable, Optional, TypeVar

from dreambuddy_dal.protocols import (
    ConfigRepository,
    KnowledgeGraphRepository,
    MarketMacroRepository,
    PositionRepository,
    RiskRepository,
    TradeRepository,
)

# 三后端类型常量
BACKEND_JSON_LEGACY = "json_legacy"
BACKEND_DUAL_WRITE = "dual_write"
BACKEND_SQLITE_UNIFIED = "sqlite_unified"
_VALID_BACKENDS = {BACKEND_JSON_LEGACY, BACKEND_DUAL_WRITE, BACKEND_SQLITE_UNIFIED}

# 单例锁（线程安全 lazy init）
_lock = threading.RLock()
_INSTANCES: dict[tuple, object] = {}  # (backend_key, repo_type) → Repository 实例

# 单库全局初始化 once 锁（按 db_path 维度，支持多 tmp_path 单元测试）
_sqlite_schema_inited_paths: set = set()
_sqlite_schema_lock = threading.Lock()

_log = logging.getLogger(__name__)

T = TypeVar("T")


# ---------------------------------------------------------------------------
# 0. Sqlite 单库 schema 初始化（once）
# ---------------------------------------------------------------------------
def _ensure_sqlite_schema_inited(db_path: str) -> None:
    # 绝对路径归一化（避免不同相对路径重复 init）
    import os as _os
    key = _os.path.abspath(db_path)
    if key in _sqlite_schema_inited_paths:
        return
    with _sqlite_schema_lock:
        if key in _sqlite_schema_inited_paths:
            return
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        from dreambuddy_dal.connection import get_sqlite_connection
        from dreambuddy_dal.implementations.sqlite_unified import init_db_schema
        with get_sqlite_connection(db_path) as conn:
            init_db_schema(conn)
        _sqlite_schema_inited_paths.add(key)


def _sqlite_db_path() -> str:
    return os.environ.get(
        "DAL_DB_PATH",
        os.path.join(os.environ.get("DATA_DIR", "./data"), "dreambuddy_core.db"),
    )


# ---------------------------------------------------------------------------
# 1. 解析最终后端（Kill-Switch 最高优先级）
# ---------------------------------------------------------------------------
def _resolve_backend(explicit: Optional[str]) -> str:
    """按优先级 1/2/3 解析最终 backend"""
    data_dir = os.environ.get("DATA_DIR", "./data")
    kill_switch = Path(data_dir) / "DISABLE_DAL_NEW"
    if kill_switch.exists():
        # ⚠️ 优先级 1：物理 Kill-Switch 存在 → 无视任何其它参数，强制 json_legacy
        return BACKEND_JSON_LEGACY

    if explicit is not None:
        backend = explicit.strip()
    else:
        backend = os.environ.get("DB_BACKEND", BACKEND_JSON_LEGACY).strip()

    if backend not in _VALID_BACKENDS:
        raise ValueError(
            f"无效的 DB_BACKEND={backend!r}；合法值：{sorted(_VALID_BACKENDS)}"
        )
    # P1 已激活所有三后端，不再拦截
    return backend


# ---------------------------------------------------------------------------
# 2. DualWrite 薄包装器（写两份：legacy 主 + sqlite 次；读走 legacy；新写失败不阻塞）
# ---------------------------------------------------------------------------
def _make_dual_write(legacy_repo: T, new_repo: T, repo_name: str) -> T:
    """
    动态代理：所有 method 调用 → 先 legacy 执行 → 再 new 执行（写方法）；
    读方法直接 return legacy 结果。

    P2 新增：
    - READ_SOURCE=shadow → 读方法额外调 new + 比对 + 写 ma_migration_audit(category='shadow_read')
    - READ_SOURCE=next_gen → 读方法直接走 new 库（不再走 legacy）
    """
    WRITE_PREFIXES = (
        "add_", "upsert_", "close_", "create_", "activate_", "update_",
        "insert_", "delete_", "remove_", "set_", "save_", "refresh_",
    )
    READ_PREFIXES = ("get_", "query_", "list_", "has_", "check_", "fts_")

    def _get_read_source() -> str:
        return os.environ.get("READ_SOURCE", "").strip().lower()

    def _get_sqlite_db_path() -> str:
        return os.environ.get(
            "DAL_DB_PATH",
            os.path.join(os.environ.get("DATA_DIR", "./data"), "dreambuddy_core.db"),
        )

    def _write_shadow_audit(entity_key: str, result: str, details: dict) -> None:
        try:
            from dreambuddy_dal.connection import get_sqlite_connection
            import json as _json
            dbp = _get_sqlite_db_path()
            with get_sqlite_connection(dbp) as conn:
                conn.execute(
                    """
                    INSERT INTO ma_migration_audit
                        (category, event_name, entity_key, result, severity, details, latency_ms)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("shadow_read", repo_name, entity_key, result,
                     1 if result == "DIFF" else 0,
                     _json.dumps(details, default=str, ensure_ascii=False), 0),
                )
        except Exception:
            pass  # 审计写入失败不影响主流程

    def _compare_results(legacy_val, new_val) -> str:
        """浅比对：None/空列表/基本类型 ==；dataclass 比 __dict__；其余 str() 比。"""
        if legacy_val is None and new_val is None:
            return "MATCH"
        if legacy_val is None or new_val is None:
            return "DIFF"
        # dataclass
        if hasattr(legacy_val, "__dict__") and hasattr(new_val, "__dict__"):
            try:
                if str(legacy_val.__dict__) == str(new_val.__dict__):
                    return "MATCH"
            except Exception:
                pass
            return "DIFF"
        # list
        if isinstance(legacy_val, list) and isinstance(new_val, list):
            return "MATCH" if len(legacy_val) == len(new_val) else "DIFF"
        # 基本类型
        try:
            return "MATCH" if legacy_val == new_val else "DIFF"
        except Exception:
            return "DIFF"

    class _DualWrapper:
        def __init__(self, leg, new_, name):
            object.__setattr__(self, "_leg", leg)
            object.__setattr__(self, "_new", new_)
            object.__setattr__(self, "_name", name)

        def __getattr__(self, item):
            if item.startswith("_"):
                raise AttributeError(item)
            leg_fn = getattr(object.__getattribute__(self, "_leg"), item, None)
            new_fn = getattr(object.__getattribute__(self, "_new"), item, None)
            if leg_fn is None:
                raise AttributeError(f"DualWrite[{object.__getattribute__(self, '_name')}] 没有属性 {item}")

            name = object.__getattribute__(self, "_name")

            if callable(leg_fn):
                is_write = any(item.startswith(p) for p in WRITE_PREFIXES)
                is_read = any(item.startswith(p) for p in READ_PREFIXES)

                def _dual_fn(*args, **kwargs):
                    read_source = _get_read_source()

                    # ── READ_SOURCE=next_gen → 读走新库 ──
                    if is_read and read_source == "next_gen" and new_fn is not None:
                        return new_fn(*args, **kwargs)

                    # ── 先 legacy 主执行（写失败即抛：主流程不能被新库拖死）──
                    result = leg_fn(*args, **kwargs)

                    if is_write:
                        # 写方法：新库 secondary 防御性执行
                        if new_fn is not None:
                            try:
                                new_fn(*args, **kwargs)
                            except Exception as exc:
                                _log.warning(
                                    "DualWrite[%s].%s 新库写失败：%r",
                                    name, item, exc,
                                )
                        return result

                    if is_read:
                        # 读方法：shadow read 比对
                        if read_source == "shadow" and new_fn is not None:
                            try:
                                new_result = new_fn(*args, **kwargs)
                                cmp = _compare_results(result, new_result)
                                entity_key = f"{item}#{str(args)[:60]}"
                                _write_shadow_audit(
                                    entity_key=entity_key,
                                    result=cmp,
                                    details={"method": item, "args": str(args)[:200]},
                                )
                            except Exception as exc:
                                _log.warning(
                                    "DualWrite[%s].%s shadow read 新库读失败：%r",
                                    name, item, exc,
                                )
                        return result

                    # 非读非写（罕见）：返回 legacy
                    return result

                return _dual_fn
            return leg_fn

        def __repr__(self):
            n = object.__getattribute__(self, "_name")
            return f"<DualWrite[{n}]>"

    wrapper = _DualWrapper(legacy_repo, new_repo, repo_name)
    # 注册为 Protocol ABC 虚拟子类，让 isinstance(x, Protocol) 返回 True（鸭子类型认证）
    if repo_name == "trade":
        TradeRepository.register(_DualWrapper)
    elif repo_name == "position":
        PositionRepository.register(_DualWrapper)
    elif repo_name == "market_macro":
        MarketMacroRepository.register(_DualWrapper)
    elif repo_name == "risk":
        RiskRepository.register(_DualWrapper)
    elif repo_name == "config":
        ConfigRepository.register(_DualWrapper)
    elif repo_name == "kg":
        KnowledgeGraphRepository.register(_DualWrapper)
    return wrapper  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# 3. 单例工厂
# ---------------------------------------------------------------------------
def _get_instance(backend: str, repo_type: str, factory: Callable[[], object]):
    key = (backend, repo_type)
    if key not in _INSTANCES:
        with _lock:
            if key not in _INSTANCES:
                _INSTANCES[key] = factory()
    return _INSTANCES[key]


def _build_legacy_trade() -> TradeRepository:
    from dreambuddy_dal.implementations.json_legacy.trade_impl import JsonLegacyTradeRepository
    return JsonLegacyTradeRepository()


def _build_legacy_position() -> PositionRepository:
    from dreambuddy_dal.implementations.json_legacy.position_impl import (
        JsonLegacyPositionRepository,
    )
    return JsonLegacyPositionRepository()


def _build_legacy_mm() -> MarketMacroRepository:
    from dreambuddy_dal.implementations.json_legacy.market_macro_impl import (
        JsonLegacyMarketMacroRepository,
    )
    return JsonLegacyMarketMacroRepository()


def _build_legacy_risk() -> RiskRepository:
    from dreambuddy_dal.implementations.json_legacy.risk_impl import JsonLegacyRiskRepository
    return JsonLegacyRiskRepository()


def _build_legacy_config() -> ConfigRepository:
    from dreambuddy_dal.implementations.json_legacy.config_impl import (
        JsonLegacyConfigRepository,
    )
    return JsonLegacyConfigRepository()


def _build_legacy_kg() -> KnowledgeGraphRepository:
    from dreambuddy_dal.implementations.json_legacy.kg_impl import (
        JsonLegacyKnowledgeGraphRepository,
    )
    return JsonLegacyKnowledgeGraphRepository()


def _build_sqlite_trade() -> TradeRepository:
    from dreambuddy_dal.implementations.sqlite_unified import SqliteTradeRepository
    dbp = _sqlite_db_path()
    _ensure_sqlite_schema_inited(dbp)
    return SqliteTradeRepository(dbp)


def _build_sqlite_position() -> PositionRepository:
    from dreambuddy_dal.implementations.sqlite_unified import SqlitePositionRepository
    dbp = _sqlite_db_path()
    _ensure_sqlite_schema_inited(dbp)
    return SqlitePositionRepository(dbp)


def _build_sqlite_mm() -> MarketMacroRepository:
    from dreambuddy_dal.implementations.sqlite_unified import SqliteMarketMacroRepository
    dbp = _sqlite_db_path()
    _ensure_sqlite_schema_inited(dbp)
    return SqliteMarketMacroRepository(dbp)


def _build_sqlite_risk() -> RiskRepository:
    from dreambuddy_dal.implementations.sqlite_unified import SqliteRiskRepository
    dbp = _sqlite_db_path()
    _ensure_sqlite_schema_inited(dbp)
    return SqliteRiskRepository(dbp)


def _build_sqlite_config() -> ConfigRepository:
    from dreambuddy_dal.implementations.sqlite_unified import SqliteConfigRepository
    dbp = _sqlite_db_path()
    _ensure_sqlite_schema_inited(dbp)
    return SqliteConfigRepository(dbp)


def _build_sqlite_kg() -> KnowledgeGraphRepository:
    from dreambuddy_dal.implementations.sqlite_unified import SqliteKnowledgeGraphRepository
    dbp = _sqlite_db_path()
    _ensure_sqlite_schema_inited(dbp)
    return SqliteKnowledgeGraphRepository(dbp)


# ------------------------------------------------------------ repo_type → 工厂
def _build_trade(backend: str) -> TradeRepository:
    if backend == BACKEND_JSON_LEGACY:
        return _build_legacy_trade()
    if backend == BACKEND_SQLITE_UNIFIED:
        return _build_sqlite_trade()
    if backend == BACKEND_DUAL_WRITE:
        return _make_dual_write(_build_legacy_trade(), _build_sqlite_trade(), "trade")
    raise ValueError(backend)


def _build_position(backend: str) -> PositionRepository:
    if backend == BACKEND_JSON_LEGACY:
        return _build_legacy_position()
    if backend == BACKEND_SQLITE_UNIFIED:
        return _build_sqlite_position()
    if backend == BACKEND_DUAL_WRITE:
        return _make_dual_write(_build_legacy_position(), _build_sqlite_position(), "position")
    raise ValueError(backend)


def _build_market_macro(backend: str) -> MarketMacroRepository:
    if backend == BACKEND_JSON_LEGACY:
        return _build_legacy_mm()
    if backend == BACKEND_SQLITE_UNIFIED:
        return _build_sqlite_mm()
    if backend == BACKEND_DUAL_WRITE:
        return _make_dual_write(_build_legacy_mm(), _build_sqlite_mm(), "market_macro")
    raise ValueError(backend)


def _build_risk(backend: str) -> RiskRepository:
    if backend == BACKEND_JSON_LEGACY:
        return _build_legacy_risk()
    if backend == BACKEND_SQLITE_UNIFIED:
        return _build_sqlite_risk()
    if backend == BACKEND_DUAL_WRITE:
        return _make_dual_write(_build_legacy_risk(), _build_sqlite_risk(), "risk")
    raise ValueError(backend)


def _build_config(backend: str) -> ConfigRepository:
    if backend == BACKEND_JSON_LEGACY:
        return _build_legacy_config()
    if backend == BACKEND_SQLITE_UNIFIED:
        return _build_sqlite_config()
    if backend == BACKEND_DUAL_WRITE:
        return _make_dual_write(_build_legacy_config(), _build_sqlite_config(), "config")
    raise ValueError(backend)


def _build_kg(backend: str) -> KnowledgeGraphRepository:
    if backend == BACKEND_JSON_LEGACY:
        return _build_legacy_kg()
    if backend == BACKEND_SQLITE_UNIFIED:
        return _build_sqlite_kg()
    if backend == BACKEND_DUAL_WRITE:
        return _make_dual_write(_build_legacy_kg(), _build_sqlite_kg(), "kg")
    raise ValueError(backend)


# ---------------------------------------------------------------------------
# 4. 对外 6 个工厂函数（消费方唯一入口）
# ---------------------------------------------------------------------------
def get_trade_repo(backend: Optional[str] = None) -> TradeRepository:
    b = _resolve_backend(backend)
    return _get_instance(b, "trade", lambda: _build_trade(b))  # type: ignore[return-value]


def get_position_repo(backend: Optional[str] = None) -> PositionRepository:
    b = _resolve_backend(backend)
    return _get_instance(b, "position", lambda: _build_position(b))  # type: ignore[return-value]


def get_market_macro_repo(backend: Optional[str] = None) -> MarketMacroRepository:
    b = _resolve_backend(backend)
    return _get_instance(b, "market_macro", lambda: _build_market_macro(b))  # type: ignore[return-value]


def get_risk_repo(backend: Optional[str] = None) -> RiskRepository:
    b = _resolve_backend(backend)
    return _get_instance(b, "risk", lambda: _build_risk(b))  # type: ignore[return-value]


def get_config_repo(backend: Optional[str] = None) -> ConfigRepository:
    b = _resolve_backend(backend)
    return _get_instance(b, "config", lambda: _build_config(b))  # type: ignore[return-value]


def get_kg_repo(backend: Optional[str] = None) -> KnowledgeGraphRepository:
    b = _resolve_backend(backend)
    return _get_instance(b, "kg", lambda: _build_kg(b))  # type: ignore[return-value]


__all__ = [
    # 常量
    "BACKEND_JSON_LEGACY", "BACKEND_DUAL_WRITE", "BACKEND_SQLITE_UNIFIED",
    # 解析
    "_resolve_backend", "_INSTANCES",
    # 对外工厂
    "get_trade_repo", "get_position_repo", "get_market_macro_repo",
    "get_risk_repo", "get_config_repo", "get_kg_repo",
]
