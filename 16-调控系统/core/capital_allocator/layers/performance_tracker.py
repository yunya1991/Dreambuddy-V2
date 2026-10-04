"""Layer 1: PerformanceTracker
============================

职责：从 all_trades.jsonl 读取交易历史，按币种聚合统计，应用 Bayesian Shrinkage。

数据流：
  all_trades.jsonl → 按币种聚合 → Bayesian Shrinkage → CoinPerformance

Bayesian Shrinkage 公式：
  θ' = (n·θ + α·θ₀) / (n + α)
  θ = 币种胜率, θ₀ = 全局胜率, α = 先验强度, n = 交易笔数
  当 n < threshold 时启动收缩（小样本向全局均值靠拢）
"""

from __future__ import annotations

import json
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..types import CoinPerformance


class PerformanceTracker:
    """Per-coin 绩效追踪 + Bayesian Shrinkage。"""

    def __init__(
        self,
        trades_file: Path,
        cache_file: Optional[Path] = None,
        shrinkage_prior_strength: int = 30,
        shrinkage_threshold: int = 30,
        cache_ttl: int = 3600,
    ):
        self._trades_file = Path(trades_file)
        self._cache_file = Path(cache_file) if cache_file else None
        self._prior_strength = shrinkage_prior_strength
        self._threshold = shrinkage_threshold
        self._cache_ttl = cache_ttl

        self._lock = __import__("threading").RLock()
        self._perf_cache: Dict[str, CoinPerformance] = {}
        self._global_cache: Dict[str, Any] = {}
        self._last_load_ts: float = 0.0

    # ── 公开 API ──

    def get_performance(self, coins: Optional[List[str]] = None) -> Dict[str, CoinPerformance]:
        """获取 per-coin 绩效（含 Bayesian Shrinkage）。

        Args:
            coins: 指定币种子集；None 则返回全部
        """
        with self._lock:
            self._ensure_loaded()
            if coins is None:
                return dict(self._perf_cache)
            return {c: self._perf_cache[c] for c in coins if c in self._perf_cache}

    def get_global_stats(self) -> Dict[str, Any]:
        """获取全局聚合统计（作为 Shrinkage 先验）。"""
        with self._lock:
            self._ensure_loaded()
            return dict(self._global_cache)

    # ── 内部 ──

    def _ensure_loaded(self) -> None:
        """懒加载 + 缓存：cache_ttl 内复用。"""
        now_ts = time.time()
        if self._perf_cache and (now_ts - self._last_load_ts) < self._cache_ttl:
            return

        # 先尝试磁盘缓存
        if self._cache_file and self._cache_file.exists():
            try:
                mtime = self._cache_file.stat().st_mtime
                if (now_ts - mtime) < self._cache_ttl:
                    self._load_from_disk_cache()
                    return
            except Exception:
                pass

        # 读 all_trades.jsonl
        self._load_from_trades_file()

    def _load_from_disk_cache(self) -> None:
        try:
            with open(self._cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._perf_cache = {
                k: CoinPerformance(**v) for k, v in data.get("by_coin", {}).items()
            }
            self._global_cache = data.get("global", {})
            self._last_load_ts = time.time()
        except Exception:
            # 磁盘缓存损坏 → 回退到读 trades file
            self._load_from_trades_file()

    def _load_from_trades_file(self) -> None:
        """读取 all_trades.jsonl，按币种聚合统计。"""
        trades: List[Dict[str, Any]] = []
        try:
            if not self._trades_file.exists():
                self._set_empty()
                return
            with open(self._trades_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        trades.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except Exception:
            self._set_empty()
            return

        if not trades:
            self._set_empty()
            return

        # 按币种聚合
        coin_agg: Dict[str, Dict[str, Any]] = {}
        for t in trades:
            coin = t.get("coin") or t.get("symbol") or ""
            if not coin:
                continue
            # 归一化币种名（去 USDT-SWAP 后缀等）
            coin = self._normalize_coin(coin)
            agg = coin_agg.setdefault(coin, {
                "n_trades": 0, "n_wins": 0,
                "wins": [], "losses": [],
                "total_pnl": 0.0, "last_ts": 0.0,
            })
            agg["n_trades"] += 1
            pnl = float(t.get("pnl") or t.get("pnl_usdt") or 0.0)
            pnl_pct = float(t.get("pnl_pct") or t.get("return_pct") or 0.0)
            agg["total_pnl"] += pnl
            ts = float(t.get("close_ts") or t.get("timestamp") or t.get("ts") or 0.0)
            if ts > agg["last_ts"]:
                agg["last_ts"] = ts
            if pnl > 0 or pnl_pct > 0:
                agg["n_wins"] += 1
                agg["wins"].append(abs(pnl_pct))
            elif pnl < 0 or pnl_pct < 0:
                agg["losses"].append(abs(pnl_pct))

        # 计算全局统计
        all_wins = []
        all_losses = []
        total_trades = 0
        total_wins = 0
        for agg in coin_agg.values():
            total_trades += agg["n_trades"]
            total_wins += agg["n_wins"]
            all_wins.extend(agg["wins"])
            all_losses.extend(agg["losses"])

        global_win_rate = (total_wins / total_trades) if total_trades > 0 else 0.0
        global_avg_win = (sum(all_wins) / len(all_wins)) if all_wins else 0.0
        global_avg_loss = (sum(all_losses) / len(all_losses)) if all_losses else 0.0
        global_w_l = (global_avg_win / global_avg_loss) if global_avg_loss > 0 else 0.0

        self._global_cache = {
            "win_rate": global_win_rate,
            "avg_win_pct": global_avg_win,
            "avg_loss_pct": global_avg_loss,
            "w_l_ratio": global_w_l,
            "n_trades": total_trades,
            "n_wins": total_wins,
        }

        # 构建 CoinPerformance + Bayesian Shrinkage
        self._perf_cache = {}
        for coin, agg in coin_agg.items():
            n = agg["n_trades"]
            nw = agg["n_wins"]
            wr = (nw / n) if n > 0 else 0.0
            avg_win = (sum(agg["wins"]) / len(agg["wins"])) if agg["wins"] else 0.0
            avg_loss = (sum(agg["losses"]) / len(agg["losses"])) if agg["losses"] else 0.0
            w_l = (avg_win / avg_loss) if avg_loss > 0 else 0.0

            # Bayesian Shrinkage
            shrunk_wr = self._shrink(wr, n, global_win_rate)
            shrunk_wl = self._shrink(w_l, n, global_w_l)

            self._perf_cache[coin] = CoinPerformance(
                coin=coin,
                n_trades=n,
                n_wins=nw,
                win_rate=wr,
                avg_win_pct=avg_win,
                avg_loss_pct=avg_loss,
                w_l_ratio=w_l,
                total_pnl=agg["total_pnl"],
                last_trade_ts=agg["last_ts"],
                shrunk_win_rate=shrunk_wr,
                shrunk_w_l_ratio=shrunk_wl,
            )

        self._last_load_ts = time.time()

        # 写磁盘缓存
        self._write_disk_cache()

    def _shrink(self, coin_val: float, n: int, global_val: float) -> float:
        """Bayesian Shrinkage: 小样本向全局均值收缩。

        θ' = (n·θ + α·θ₀) / (n + α)
        """
        if n >= self._threshold:
            return coin_val  # 大样本不收缩
        alpha = self._prior_strength
        return (n * coin_val + alpha * global_val) / (n + alpha)

    def _normalize_coin(self, coin: str) -> str:
        """归一化币种名。"""
        coin = coin.upper()
        for suffix in ("-USDT-SWAP", "-USDT", "/USDT", "USDT"):
            if coin.endswith(suffix):
                coin = coin[: -len(suffix)]
                break
        return coin

    def _set_empty(self) -> None:
        self._perf_cache = {}
        self._global_cache = {
            "win_rate": 0.0, "avg_win_pct": 0.0, "avg_loss_pct": 0.0,
            "w_l_ratio": 0.0, "n_trades": 0, "n_wins": 0,
        }
        self._last_load_ts = time.time()

    def _write_disk_cache(self) -> None:
        if not self._cache_file:
            return
        try:
            self._cache_file.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "by_coin": {k: v.to_dict() for k, v in self._perf_cache.items()},
                "global": self._global_cache,
                "cached_at": time.time(),
            }
            with open(self._cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception:
            pass  # 缓存写入失败不影响主流程
