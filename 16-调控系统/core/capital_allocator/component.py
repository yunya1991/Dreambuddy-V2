"""CapitalAllocatorComponent 主组件（PACA）
==========================================

对外暴露的唯一入口（对齐 capital_control 五方法模式）：
- evaluate(coins=None) -> AllocationSnapshot
- get_allocation_advice(coin, source_tag, equity) -> Dict
- get_global_expansion_mult() -> float
- get_coin_kelly_mult(coin) -> float
- get_snapshot() -> Optional[AllocationSnapshot]
- health_check() -> Dict

设计约束（对齐 CAPITAL_CONTROL_DESIGN.md §1.4）：
  * 建议制原则：输出 position_pct 建议，不直接拦截开仓
  * 缓存复用原则：绩效数据缓存 1h，避免重复读取 all_trades.jsonl
  * 降级回退原则：任何异常 → DEFAULT_PCT=0.10 + expansion_mult=1.0
  * 零侵入原则：SHADOW 模式不修改开仓路径，仅记录对比
"""

from __future__ import annotations

import json
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

_ALLOC_DIR = Path(__file__).resolve().parent          # capital_allocator
_16_CORE_DIR = _ALLOC_DIR.parent                       # 16-调控系统/core
_16_DIR = _16_CORE_DIR.parent                           # 16-调控系统
_PROJECT_DIR = _16_DIR.parent                            # dreambuddy-v2
_TRADES_FILE = _PROJECT_DIR / "11-易经推理系统" / ".workbuddy" / "memory_l4" / "stats" / "all_trades.jsonl"
_CACHE_FILE = _PROJECT_DIR / "11-易经推理系统" / "runtime" / "paca_performance_cache.json"

for _p in (_16_CORE_DIR,):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from .types import (  # noqa: E402
    AllocatorMode,
    AllocationResult,
    AllocationSnapshot,
    HealthLevel,
    now_iso,
)
from .layers.performance_tracker import PerformanceTracker  # noqa: E402
from .layers.kelly_sizer import KellySizer  # noqa: E402
from .layers.hierarchical_allocator import HierarchicalAllocator  # noqa: E402
from .layers.expansion_gate import GlobalExpansionGate  # noqa: E402


_DEFAULT_CONFIG: Dict[str, Any] = {
    "version": "1.0",
    "mode": "shadow",
    "cache_ttl_sec": 3600,
    "trades_file": str(_TRADES_FILE),
    # Layer 1
    "shrinkage_prior_strength": 30,
    "shrinkage_threshold": 30,
    # Layer 2
    "kelly_fraction": 0.5,
    "min_position_pct": 0.03,
    "max_position_pct": 0.25,
    "default_pct": 0.10,
    "cold_start_min_trades": 5,
    # Layer 3
    "subpool_weights": {
        "bdsm": 0.25, "bcrm": 0.40, "evolution": 0.20, "strategy": 0.15,
    },
    "min_subpool_weight": 0.10,
    # Layer 4
    "expansion_window": 30,
    "expansion_ladder": [
        {"w_l_ratio_min": 2.0, "position_pct_mult": 1.5},
        {"w_l_ratio_min": 1.0, "position_pct_mult": 1.2},
        {"w_l_ratio_min": 0.5, "position_pct_mult": 1.0},
        {"w_l_ratio_min": 0.0, "position_pct_mult": 0.7},
    ],
    "max_total_exposure": 0.80,
    "min_total_exposure": 0.10,
    "expansion_cooldown_hours": 6,
}


class CapitalAllocatorComponent:
    """绩效自适应资金调配组件（PACA）。"""

    def __init__(
        self,
        mode: Optional[AllocatorMode] = None,
        config_path: Optional[Path] = None,
        cache_ttl: Optional[int] = None,
    ):
        # 1) 配置加载（对齐 capital_control 模式）
        if config_path is None:
            config_path = _16_DIR / "config" / "capital_allocator.json"
        self._config_path: Path = Path(config_path)
        self._config: Dict[str, Any] = self._load_config(self._config_path)

        # 2) 模式
        if mode is not None:
            self._mode = mode
        else:
            mode_str = str(self._config.get("mode", "shadow")).lower()
            self._mode = AllocatorMode.ACTIVE if mode_str == "active" else AllocatorMode.SHADOW

        # 3) 缓存 TTL
        self._cache_ttl = int(cache_ttl or self._config.get("cache_ttl_sec", 3600))

        # 4) 初始化四层
        trades_file_str = self._config.get("trades_file", str(_TRADES_FILE))
        trades_file = Path(trades_file_str)
        # 相对路径 → 基于项目根目录解析（防止 CWD 不同导致路径错误）
        if not trades_file.is_absolute():
            trades_file = _PROJECT_DIR / trades_file
        self._tracker = PerformanceTracker(
            trades_file=trades_file,
            cache_file=_CACHE_FILE,
            shrinkage_prior_strength=self._config.get("shrinkage_prior_strength", 30),
            shrinkage_threshold=self._config.get("shrinkage_threshold", 30),
            cache_ttl=self._cache_ttl,
        )
        self._kelly = KellySizer(
            kelly_fraction=self._config.get("kelly_fraction", 0.5),
            min_pct=self._config.get("min_position_pct", 0.03),
            max_pct=self._config.get("max_position_pct", 0.25),
            default_pct=self._config.get("default_pct", 0.10),
            cold_start_min_trades=self._config.get("cold_start_min_trades", 5),
        )
        self._allocator = HierarchicalAllocator(
            subpool_weights=self._config.get("subpool_weights", {}),
            min_subpool_weight=self._config.get("min_subpool_weight", 0.10),
        )
        self._gate = GlobalExpansionGate(
            window=self._config.get("expansion_window", 30),
            ladder=self._config.get("expansion_ladder", []),
            max_exposure=self._config.get("max_total_exposure", 0.80),
            min_exposure=self._config.get("min_total_exposure", 0.10),
            cooldown_hours=self._config.get("expansion_cooldown_hours", 6),
        )

        # 5) 缓存
        self._lock = threading.RLock()
        self._last_snapshot: Optional[AllocationSnapshot] = None
        self._last_eval_ts: float = 0.0

    # ------------------------------------------------------------------
    # 初始化工具
    # ------------------------------------------------------------------

    @staticmethod
    def _load_config(path: Path) -> Dict[str, Any]:
        cfg = dict(_DEFAULT_CONFIG)
        try:
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    file_cfg = json.load(f)
                if isinstance(file_cfg, dict):
                    for k, v in file_cfg.items():
                        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                            new_dict = dict(cfg[k])
                            new_dict.update(v)
                            cfg[k] = new_dict
                        else:
                            cfg[k] = v
        except (OSError, json.JSONDecodeError):
            pass  # 文件损坏时使用默认配置
        return cfg

    # ------------------------------------------------------------------
    # 公开 API（对齐 capital_control 五方法模式）
    # ------------------------------------------------------------------

    def evaluate(self, coins: Optional[List[str]] = None) -> AllocationSnapshot:
        """执行资金调配评估。

        流程：
          1. 如距离上次 evaluate < cache_ttl 秒，直接返回缓存快照。
          2. Layer 1: PerformanceTracker 读取 all_trades.jsonl
          3. Layer 2: KellySizer 计算 per-coin 仓位
          4. Layer 3: HierarchicalAllocator 分层分配
          5. Layer 4: GlobalExpansionGate 全局扩张乘数
          6. 聚合为 AllocationSnapshot
        """
        with self._lock:
            now_ts = time.time()
            if (
                self._last_snapshot is not None
                and (now_ts - self._last_eval_ts) < self._cache_ttl
                and coins is None
            ):
                return self._last_snapshot

            snapshot = self._do_evaluate(coins=coins)
            self._last_snapshot = snapshot
            self._last_eval_ts = time.time()
            return snapshot

    def get_allocation_advice(self, coin: str, source_tag: str, equity: float) -> Dict[str, Any]:
        """获取单币资金调配建议（开仓时调用）。

        返回结构（稳定，向后兼容）::

            {
              "position_pct": float,        # 建议仓位比例
              "expansion_mult": float,      # 全局扩张乘数
              "final_position_pct": float,   # position_pct * expansion_mult
              "position_usdt": float,       # equity * final_position_pct
              "kelly_f": float,
              "mode": "shadow" | "active",
              "fallback_used": bool,
              "reason": str,
            }
        """
        try:
            snap = self._last_snapshot or self.evaluate()
            result = snap.by_coin.get(coin)
            default_pct = self._config.get("default_pct", 0.10)
            if result is None:
                exp_mult = snap.expansion_mult
                return {
                    "position_pct": default_pct,
                    "expansion_mult": exp_mult,
                    "final_position_pct": round(default_pct * exp_mult, 6),
                    "position_usdt": round(equity * default_pct * exp_mult, 2),
                    "kelly_f": 0.0,
                    "mode": self._mode.value,
                    "fallback_used": True,
                    "reason": "coin_not_in_cache_cold_start",
                }
            return {
                "position_pct": result.position_pct,
                "expansion_mult": result.expansion_mult,
                "final_position_pct": result.final_position_pct,
                "position_usdt": round(equity * result.final_position_pct, 2),
                "kelly_f": result.kelly_f,
                "mode": self._mode.value,
                "fallback_used": result.fallback_used,
                "reason": result.fallback_reason or "ok",
            }
        except Exception as exc:
            default_pct = self._config.get("default_pct", 0.10)
            return {
                "position_pct": default_pct,
                "expansion_mult": 1.0,
                "final_position_pct": default_pct,
                "position_usdt": round(equity * default_pct, 2),
                "kelly_f": 0.0,
                "mode": self._mode.value,
                "fallback_used": True,
                "reason": f"paca_exception:{exc}",
            }

    def get_global_expansion_mult(self) -> float:
        """获取全局扩张乘数（供 capital_control 叠加用）。"""
        try:
            snap = self._last_snapshot or self.evaluate()
            return snap.expansion_mult
        except Exception:
            return 1.0

    def get_coin_kelly_mult(self, coin: str) -> float:
        """获取单币 Kelly 乘数（供 BDSM 预算动态调整用）。

        映射：half_kelly_f ∈ [0, 1] → mult ∈ [0, 2.0]
        """
        try:
            snap = self._last_snapshot or self.evaluate()
            result = snap.by_coin.get(coin)
            if result is None:
                return 1.0
            return self._kelly.get_kelly_mult(result.half_kelly_f)
        except Exception:
            return 1.0

    def get_snapshot(self) -> Optional[AllocationSnapshot]:
        """返回最近一次 evaluate() 的快照缓存。"""
        return self._last_snapshot

    def health_check(self) -> Dict[str, Any]:
        """组件健康检查——用于 16-调控系统统一健康监控。"""
        snap = self._last_snapshot
        if snap is None:
            try:
                snap = self.evaluate()
            except Exception as exc:
                return {
                    "ok": False,
                    "error": f"evaluate_failed: {exc}",
                    "mode": self._mode.value,
                    "config_path": str(self._config_path),
                }
        return {
            "ok": True,
            "evaluated": True,
            "health": snap.health.value if snap else HealthLevel.CRITICAL.value,
            "mode": self._mode.value,
            "total_coins": len(snap.by_coin) if snap else 0,
            "global_w_l_ratio": round(snap.global_w_l_ratio, 4) if snap else 0.0,
            "expansion_mult": round(snap.expansion_mult, 4) if snap else 1.0,
            "total_trades_analyzed": snap.total_trades_analyzed if snap else 0,
            "config_path": str(self._config_path),
            "cache_ttl_sec": self._cache_ttl,
        }

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _do_evaluate(self, coins: Optional[List[str]] = None) -> AllocationSnapshot:
        """实际执行四层评估。"""
        # Layer 1: 绩效追踪
        perf_data = self._tracker.get_performance(coins=coins)
        global_stats = self._tracker.get_global_stats()

        # Layer 2: Kelly 仓位
        coin_kelly: Dict[str, tuple] = {}
        for coin, perf in perf_data.items():
            kelly_f = KellySizer.kelly_fraction_fn(perf.shrunk_win_rate, perf.shrunk_w_l_ratio)
            half_f = self._kelly.half_kelly(kelly_f)
            pos_pct = self._kelly.kelly_to_position(half_f, perf.n_trades)
            coin_kelly[coin] = (perf, kelly_f, half_f, pos_pct)

        # Layer 3: 分层分配
        subpool_budgets = self._allocator.allocate_subpools(
            total_budget=1.0,  # 归一化，实际由 equity 缩放
            coin_kelly=coin_kelly,
        )

        # Layer 4: 扩张门控
        expansion_mult = self._gate.get_expansion_multiplier(global_stats)

        # 聚合
        by_coin: Dict[str, AllocationResult] = {}
        for coin, (perf, kelly_f, half_f, pos_pct) in coin_kelly.items():
            source_tag = self._infer_source_tag(coin)
            subpool_w = subpool_budgets.get(source_tag, 0.0)
            final_pct = pos_pct * expansion_mult
            # 安全约束：final_pct 不超过 max_position_pct
            max_pct = self._config.get("max_position_pct", 0.25)
            final_pct = min(final_pct, max_pct)
            by_coin[coin] = AllocationResult(
                coin=coin,
                source_tag=source_tag,
                kelly_f=kelly_f,
                half_kelly_f=half_f,
                position_pct=pos_pct,
                subpool_budget=subpool_w,
                subpool_weight=subpool_w,
                expansion_mult=expansion_mult,
                final_position_pct=final_pct,
                timestamp=now_iso(),
            )

        health = self._assess_health(global_stats, len(perf_data))

        return AllocationSnapshot(
            timestamp=now_iso(),
            mode=self._mode,
            health=health,
            global_win_rate=global_stats.get("win_rate", 0.0),
            global_w_l_ratio=global_stats.get("w_l_ratio", 0.0),
            expansion_mult=expansion_mult,
            by_coin=by_coin,
            by_subpool=subpool_budgets,
            total_trades_analyzed=global_stats.get("n_trades", 0),
        )

    def _assess_health(self, global_stats: Dict[str, Any], n_coins: int) -> HealthLevel:
        """健康等级判定（对齐 capital_control assess_health）。"""
        try:
            w_l = float(global_stats.get("w_l_ratio", 0.0))
            n_trades = int(global_stats.get("n_trades", 0))

            if n_trades == 0:
                return HealthLevel.CRITICAL  # 无数据
            if w_l < 0.5 or n_trades < 10:
                return HealthLevel.WARNING   # 样本不足或绩效差
            return HealthLevel.HEALTHY
        except Exception:
            return HealthLevel.CRITICAL

    @staticmethod
    def _infer_source_tag(coin: str) -> str:
        """推断币种所属子池。

        默认归 bcrm 池。实际运行时由 polling_trader 传入 source_tag 覆盖。
        """
        return "bcrm"
