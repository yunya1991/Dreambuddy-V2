"""
EvolutionDataAccessor — 自进化架构可视化的数据访问层

职责:
- 隔离 all_trades.jsonl / performance.json 的具体访问细节
- 处理 strategy_source 区分 evolution vs main_pool
- 处理时间窗口过滤
- 处理降级（evolution 无数据 / ReflectionEngine 未持久化）

对应 spec: docs/superpowers/specs/2026-09-05-evolution-arch-visualization-design.md 第6节
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


class EvolutionDataAccessor:
    """自进化架构可视化数据访问器"""

    def __init__(self, trades_file: str, perf_file: str):
        """
        Args:
            trades_file: all_trades.jsonl 路径
            perf_file: performance.json 路径
        """
        self.trades_file = Path(trades_file)
        self.perf_file = Path(perf_file)

    # ── 内部辅助 ──────────────────────────────────────────────────────────

    def _load_trades(self) -> list[dict]:
        """加载 all_trades.jsonl，返回 trade 记录列表"""
        if not self.trades_file.exists():
            return []
        trades = []
        with open(self.trades_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        trades.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return trades

    def _parse_exit_time(self, trade: dict) -> datetime | None:
        """解析 exit_time（ISO 8601 带时区），失败返回 None"""
        exit_time_str = trade.get("exit_time")
        if not exit_time_str:
            return None
        try:
            # 兼容带时区和不带时区的 ISO 格式
            dt = datetime.fromisoformat(exit_time_str.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            return None

    def _parse_entry_time(self, trade: dict) -> datetime | None:
        """解析 entry_time"""
        entry_time_str = trade.get("entry_time")
        if not entry_time_str:
            return None
        try:
            dt = datetime.fromisoformat(entry_time_str.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            return None

    def _filter_by_range(self, trades: list[dict], range_days: int | None) -> list[dict]:
        """按时间窗口过滤（基于 exit_time）"""
        if range_days is None:
            return trades
        cutoff = datetime.now(timezone.utc) - timedelta(days=range_days)
        result = []
        for t in trades:
            exit_dt = self._parse_exit_time(t)
            if exit_dt is not None and exit_dt >= cutoff:
                result.append(t)
        return result

    def _split_by_pool(self, trades: list[dict]) -> tuple[list[dict], list[dict]]:
        """按 strategy_source 区分 evolution vs main_pool
        evolution: strategy_source == "evolution"
        main_pool: 其他（含 None / 空字符串 / "bcrm" 等）
        """
        evolution = []
        main_pool = []
        for t in trades:
            if t.get("strategy_source") == "evolution":
                evolution.append(t)
            else:
                main_pool.append(t)
        return evolution, main_pool

    def _calc_pool_metrics(self, trades: list[dict], open_count: int = 0) -> dict:
        """计算单池指标"""
        if not trades:
            return {
                "total_pnl": None,
                "win_rate": None,
                "max_drawdown": None,
                "position_count": open_count,
                "running_days": 0,
                "closed_count": 0,
                "currency": "USDT",
            }
        pnls = [t.get("pnl", 0) for t in trades]
        total_pnl = sum(pnls)
        wins = sum(1 for p in pnls if p > 0)
        closed_count = len(trades)
        win_rate = wins / closed_count if closed_count > 0 else 0

        # 最大回撤（基于累计盈亏序列）
        cumulative = 0
        peak = 0
        max_dd = 0
        for p in pnls:
            cumulative += p
            if cumulative > peak:
                peak = cumulative
            dd = cumulative - peak
            if dd < max_dd:
                max_dd = dd
        # 归一化为百分比（基于总投入估算，简化处理）
        max_drawdown = max_dd / abs(total_pnl) if total_pnl != 0 else 0

        # 运行天数：从最早 entry_time 到现在
        entry_times = [self._parse_entry_time(t) for t in trades]
        entry_times = [et for et in entry_times if et is not None]
        if entry_times:
            earliest = min(entry_times)
            running_days = max(1, (datetime.now(timezone.utc) - earliest).days)
        else:
            running_days = 0

        return {
            "total_pnl": round(total_pnl, 6),
            "win_rate": round(win_rate, 4),
            "max_drawdown": round(max_drawdown, 4),
            "position_count": open_count,
            "running_days": running_days,
            "closed_count": closed_count,
            "currency": "USDT",
        }

    # ── 公开 API ──────────────────────────────────────────────────────────

    def get_evolution_overview(self, range_days: int | None = None) -> dict:
        """返回 evolution + main_pool 各 5 指标"""
        all_trades = self._load_trades()
        filtered = self._filter_by_range(all_trades, range_days)
        evo_trades, main_trades = self._split_by_pool(filtered)

        return {
            "range": f"{range_days}d" if range_days else "all",
            "last_update": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "evolution": self._calc_pool_metrics(evo_trades, open_count=0),
            "main_pool": self._calc_pool_metrics(main_trades, open_count=0),
        }

    def get_evolution_timeline(self, range_days: int | None = None) -> dict:
        """返回 cumulative + daily 双系列 + trade_points"""
        all_trades = self._load_trades()
        filtered = self._filter_by_range(all_trades, range_days)
        evo_trades, main_trades = self._split_by_pool(filtered)

        # 按日期聚合
        def _aggregate(trades):
            """返回 {date: {"pnl": sum, "trades": [...]}}"""
            daily_map = {}
            for t in trades:
                exit_dt = self._parse_exit_time(t)
                if exit_dt is None:
                    continue
                date_str = exit_dt.strftime("%Y-%m-%d")
                if date_str not in daily_map:
                    daily_map[date_str] = {"pnl": 0, "trades": []}
                daily_map[date_str]["pnl"] += t.get("pnl", 0)
                daily_map[date_str]["trades"].append({
                    "trade_id": t.get("trade_id"),
                    "date": date_str,
                    "pnl": t.get("pnl", 0),
                    "symbol": t.get("coin"),
                    "direction": t.get("direction"),
                })
            return daily_map

        evo_daily = _aggregate(evo_trades)
        main_daily = _aggregate(main_trades)

        # 合并所有日期并排序
        all_dates = sorted(set(list(evo_daily.keys()) + list(main_daily.keys())))

        # 构建序列
        evo_cum = []
        main_cum = []
        evo_daily_list = []
        main_daily_list = []
        evo_trade_points = []
        main_trade_points = []

        evo_running = 0
        main_running = 0
        for date_str in all_dates:
            evo_pnl = evo_daily.get(date_str, {}).get("pnl", 0)
            main_pnl = main_daily.get(date_str, {}).get("pnl", 0)

            evo_running += evo_pnl
            main_running += main_pnl

            evo_cum.append(round(evo_running, 6))
            main_cum.append(round(main_running, 6))
            evo_daily_list.append(round(evo_pnl, 6))
            main_daily_list.append(round(main_pnl, 6))

            # trade_points
            if date_str in evo_daily:
                evo_trade_points.extend(evo_daily[date_str]["trades"])
            if date_str in main_daily:
                main_trade_points.extend(main_daily[date_str]["trades"])

        return {
            "range": f"{range_days}d" if range_days else "all",
            "dates": all_dates,
            "cumulative": {
                "evolution": evo_cum,
                "main_pool": main_cum,
            },
            "daily": {
                "evolution": evo_daily_list,
                "main_pool": main_daily_list,
            },
            "trade_points": {
                "evolution": evo_trade_points,
                "main_pool": main_trade_points,
            },
        }

    def get_evolution_evidence(self, range_days: int | None = None) -> dict:
        """返回 ess_curve + reflection_count + cs_distribution + gmax_trajectory

        Phase 4 后数据来源:
        - ess_curve: FTCOrchestrator 中各轨道 FTC 的 ESS 均值（当前快照，单点日期）
        - reflection_count: all_trades.jsonl 中 evolution/main_pool 交易数（每次平仓=一次反思）
        - cs_distribution: trade_rec.confidence 字段的分位数分布
        - gmax_trajectory: FTCEvolutionBridge 当前 gmax 值（单点）
        """
        range_label = f"{range_days}d" if range_days else "all"
        all_trades = self._load_trades()
        if range_days is not None:
            all_trades = self._filter_by_range(all_trades, range_days)

        evo_trades = [t for t in all_trades if t.get("strategy_source") == "evolution"]
        main_trades = [t for t in all_trades if t.get("strategy_source") != "evolution"]

        # ── reflection_count: 每次平仓触发一次反思 ──
        reflection_by_date: dict[str, dict] = {}
        for t in all_trades:
            dt = self._parse_exit_time(t)
            if dt:
                day = dt.strftime("%Y-%m-%d")
                if day not in reflection_by_date:
                    reflection_by_date[day] = {"evolution": 0, "main_pool": 0}
                key = "evolution" if t.get("strategy_source") == "evolution" else "main_pool"
                reflection_by_date[day][key] += 1

        # ── cs_distribution: confidence 分位数 ──
        def _percentiles(values: list[float]) -> dict:
            if not values:
                return {"min": None, "p25": None, "median": None, "p75": None, "max": None, "samples": []}
            s = sorted(values)
            n = len(s)
            return {
                "min": round(s[0], 4),
                "p25": round(s[n // 4], 4),
                "median": round(s[n // 2], 4),
                "p75": round(s[(3 * n) // 4], 4),
                "max": round(s[-1], 4),
                "samples": [round(v, 4) for v in s[:50]],  # 最多50个样本
            }

        evo_cs = [float(t.get("confidence") or 0.0) for t in evo_trades]
        main_cs = [float(t.get("confidence") or 0.0) for t in main_trades]

        # ── ess_curve + gmax: 从 FTCOrchestrator 获取当前快照 ──
        ess_dates = []
        ess_evo_avg = []
        ess_main_avg = []
        gmax_dates = []
        gmax_vals = []
        try:
            import sys
            from pathlib import Path as _Path
            _evo_root = str(_Path(__file__).resolve().parents[2] / "23-四层闭环自进化交易架构")
            if _evo_root not in sys.path:
                sys.path.insert(0, _evo_root)

            from dreambuddy_evolution.adapters.ftc_orchestrator import FTCOrchestrator
            from dreambuddy_evolution.adapters.path_library import PathLibrary
            from dreambuddy_evolution.adapters.ftc_evolution_bridge import FTCEvolutionBridge

            orch = FTCOrchestrator(path_library=PathLibrary())
            orch.initialize_seeds()
            orch.run_backtest_all(symbol="BTC")

            all_ftcs = orch.get_all_ftcs()
            exploit_ess = [f.ess for f in all_ftcs if f.track == "exploit" and f.ess is not None]
            mixed_ess = [f.ess for f in all_ftcs if f.track == "mixed" and f.ess is not None]
            explore_ess = [f.ess for f in all_ftcs if f.track == "explore" and f.ess is not None]

            today = datetime.now().strftime("%Y-%m-%d")
            ess_dates = [today]
            # evolution 子池 = exploit + explore 轨道（实盘使用的）
            evo_pool_ess = exploit_ess + explore_ess
            ess_evo_avg = [round(sum(evo_pool_ess) / len(evo_pool_ess), 4)] if evo_pool_ess else [0.0]
            # main_pool 参考 = mixed 轨道（半仓）
            ess_main_avg = [round(sum(mixed_ess) / len(mixed_ess), 4)] if mixed_ess else [0.0]

            # gmax 当前值
            bridge = FTCEvolutionBridge(orchestrator=orch)
            gmax_dates = [today]
            gmax_vals = [round(bridge.gmax, 4)]
        except Exception:
            pass  # FTC 不可用时返回空数组

        return {
            "range": range_label,
            "degraded": False,
            "ess_curve": {
                "dates": ess_dates,
                "evolution_avg": ess_evo_avg,
                "main_pool_avg": ess_main_avg,
            },
            "reflection_count": {
                "evolution": len(evo_trades),
                "main_pool": len(main_trades),
                "by_date": {k: v["evolution"] + v["main_pool"] for k, v in reflection_by_date.items()},
            },
            "cs_distribution": {
                "evolution": _percentiles(evo_cs),
                "main_pool": _percentiles(main_cs),
            },
            "gmax_trajectory": {
                "dates": gmax_dates,
                "gmax_mult": gmax_vals,
                "cluster_weight_mult": [],
            },
        }

    def get_evolution_detail(self, detail_type: str, detail_id: str) -> dict | None:
        """返回单笔 trade 或单次 reflection 详情

        Args:
            detail_type: "trade" | "reflection"
            detail_id: trade_id 或 reflection_id
        Returns:
            dict 或 None（id 不存在）
        """
        if detail_type == "reflection":
            # MVP 降级：ReflectionEngine 未持久化
            return {
                "type": "reflection",
                "degraded": True,
                "message": "ReflectionEngine 持久化为 Phase 2 范围",
            }

        if detail_type == "trade":
            all_trades = self._load_trades()
            for t in all_trades:
                if t.get("trade_id") == detail_id:
                    return {
                        "type": "trade",
                        "trade_id": t.get("trade_id"),
                        "symbol": t.get("coin"),
                        "direction": t.get("direction"),
                        "source_tag": t.get("strategy_source"),
                        "entry_time": t.get("entry_time"),
                        "entry_price": t.get("entry_price"),
                        "exit_time": t.get("exit_time"),
                        "exit_price": t.get("exit_price"),
                        "pnl": t.get("pnl"),
                        "pnl_pct": t.get("pnl_pct"),
                        "exit_reason": t.get("exit_reason"),
                        "confidence": t.get("confidence"),
                        "hexagram": t.get("hexagram"),
                        "market_snapshot": t.get("market_snapshot"),
                    }
            return None  # id 不存在

        return None

    # ── FTC 金融思维链核心指标 ────────────────────────────────────────────

    def get_ftc_status(self) -> dict:
        """
        返回 FTC 金融思维链层的核心检测指标。

        包括:
        - ftc 总数 + 轨道分布（exploit/mixed/explore/discard）
        - ε 探索因子当前值
        - Top FTC 列表（id, ess, track, n_samples）
        - ESS 分布统计（mean/max/min）
        - 最近实盘触发的 FTC（从 all_trades.jsonl 的 market_snapshot.ftc_id 聚合）

        Returns:
            dict 结构，失败时返回 {"degraded": true, "error": ...}
        """
        try:
            import sys
            from pathlib import Path as _Path
            _evo_root = str(_Path(__file__).resolve().parents[2] / "23-四层闭环自进化交易架构")
            if _evo_root not in sys.path:
                sys.path.insert(0, _evo_root)

            from dreambuddy_evolution.adapters.ftc_orchestrator import FTCOrchestrator
            from dreambuddy_evolution.adapters.path_library import PathLibrary

            orch = FTCOrchestrator(path_library=PathLibrary())
            orch.initialize_seeds()
            orch.run_backtest_all(symbol="BTC")

            all_ftcs = orch.get_all_ftcs()
            track_summary = orch.get_track_summary()

            # Top 10 FTC 按 ESS 排序
            top_ftcs = sorted(
                [f for f in all_ftcs if f.ess is not None],
                key=lambda f: f.ess,
                reverse=True,
            )[:10]

            # ESS 分布统计
            ess_values = [f.ess for f in all_ftcs if f.ess is not None]
            ess_stats = {
                "count": len(ess_values),
                "mean": round(sum(ess_values) / len(ess_values), 4) if ess_values else 0.0,
                "max": round(max(ess_values), 4) if ess_values else 0.0,
                "min": round(min(ess_values), 4) if ess_values else 0.0,
            }

            # 最近实盘触发的 FTC（从平仓历史的 market_snapshot.ftc_id 聚合）
            recent_trades = self._load_trades()
            ftc_trade_counts: dict[str, int] = {}
            ftc_pnl_sum: dict[str, float] = {}
            for t in recent_trades[-200:]:  # 最近 200 笔
                snap = t.get("market_snapshot") or {}
                ftc_id = snap.get("ftc_id")
                if ftc_id:
                    ftc_trade_counts[ftc_id] = ftc_trade_counts.get(ftc_id, 0) + 1
                    ftc_pnl_sum[ftc_id] = ftc_pnl_sum.get(ftc_id, 0.0) + float(t.get("pnl") or 0.0)

            recent_ftc_activity = [
                {
                    "ftc_id": fid,
                    "trade_count": cnt,
                    "total_pnl": round(ftc_pnl_sum.get(fid, 0.0), 4),
                }
                for fid, cnt in sorted(ftc_trade_counts.items(), key=lambda x: x[1], reverse=True)
            ][:10]

            return {
                "total": len(all_ftcs),
                "track_summary": track_summary,
                "epsilon": round(orch.epsilon, 4),
                "epsilon_range": {"min": 0.2, "max": 0.6},
                "ess_stats": ess_stats,
                "top_ftcs": [
                    {
                        "ftc_id": f.ftc_id,
                        "ess": round(f.ess, 4) if f.ess is not None else None,
                        "track": f.track,
                        "n_samples": f.n_samples or 0,
                    }
                    for f in top_ftcs
                ],
                "recent_ftc_activity": recent_ftc_activity,
            }
        except Exception as e:
            return {"degraded": True, "error": str(e)}
