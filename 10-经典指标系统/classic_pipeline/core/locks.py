"""全局锁集中管理（从 ml_trade_service.py 抽取）

所有 threading.Lock/Semaphore/local 实例集中于此，
各阶段模块通过 `from classic_pipeline.core.locks import XXX` 引用同一实例。
命名保持与 ml_trade_service.py 原定义一致（含下划线前缀），避免修改 187K 行中的引用。
"""

import threading

# === 排他锁（原名保持一致） ===
_CHARACTERIZATION_EXCLUSIVE_LOCK = threading.Lock()
SIGNAL_DEDUP_LOCK = threading.Lock()
UNIVERSE_BUILD_LOCK = threading.Lock()
CARRY_UNIVERSE_LOCK = threading.Lock()
CACHE_MAINT_LOCK = threading.Lock()
PARAMOPT_LOCK = threading.Lock()
_THREE_SCREEN_BACKFILL_LOCK = threading.Lock()
EXIT_MONITOR_EVAL_LOCK = threading.Lock()
REGIME_SMOOTH_LOCK = threading.Lock()
GATE_RESERVE_LOCK = threading.Lock()
_ENV_RELOAD_LOCK = threading.Lock()
_DATA_INDEX_LOCK = threading.Lock()
_PERP_AUTOFILL_GUARD = threading.Lock()
_BACKTEST_DATA_LOCK = threading.Lock()
_SANDBOX_STATE_LOCK = threading.Lock()
_TRADE_MONITOR_LOCK = threading.Lock()
_FUNDAMENTAL_NEWS_LOCK = threading.Lock()
_FUNDAMENTAL_FLOWS_LOCK = threading.Lock()
_FUNDAMENTAL_NARRATIVE_LOCK = threading.Lock()
_FUNDAMENTAL_NEWS_BRIEF_HTTP_CACHE_LOCK = threading.Lock()

# === ID 锁 ===
_ID_LOCK = threading.Lock()

# === 运行时上下文（线程局部） ===
_RUNTIME_CTX = threading.local()


__all__ = [
    "_CHARACTERIZATION_EXCLUSIVE_LOCK",
    "SIGNAL_DEDUP_LOCK",
    "UNIVERSE_BUILD_LOCK",
    "CARRY_UNIVERSE_LOCK",
    "CACHE_MAINT_LOCK",
    "PARAMOPT_LOCK",
    "_THREE_SCREEN_BACKFILL_LOCK",
    "EXIT_MONITOR_EVAL_LOCK",
    "REGIME_SMOOTH_LOCK",
    "GATE_RESERVE_LOCK",
    "_ENV_RELOAD_LOCK",
    "_DATA_INDEX_LOCK",
    "_PERP_AUTOFILL_GUARD",
    "_BACKTEST_DATA_LOCK",
    "_SANDBOX_STATE_LOCK",
    "_TRADE_MONITOR_LOCK",
    "_FUNDAMENTAL_NEWS_LOCK",
    "_FUNDAMENTAL_FLOWS_LOCK",
    "_FUNDAMENTAL_NARRATIVE_LOCK",
    "_FUNDAMENTAL_NEWS_BRIEF_HTTP_CACHE_LOCK",
    "_ID_LOCK",
    "_RUNTIME_CTX",
]
