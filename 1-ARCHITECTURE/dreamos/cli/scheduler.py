"""
Dream OS 定时调度器

支持:
    - cron 表达式配置定时任务
    - 多币种扫描调度
    - 任务状态管理
    - 执行历史记录
    - 邮件/通知提醒

用法:
    scheduler = DreamOSScheduler()
    scheduler.add_job('scan_btc', '*/5 * * * *', lambda: analyze('BTC'))
    scheduler.start()
"""

from __future__ import annotations

import time
import sys
import threading
import logging
import json
from datetime import datetime, timedelta
from typing import Dict, Any, Callable, Optional, List
from enum import Enum
from pathlib import Path
from collections import defaultdict

try:
    import croniter
    HAS_CRONITER = True
except ImportError:
    HAS_CRONITER = False


logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"


class ScheduledJob:
    def __init__(
        self,
        name: str,
        cron_expr: str,
        func: Callable,
        args: tuple = (),
        kwargs: Optional[Dict[str, Any]] = None,
        enabled: bool = True,
    ):
        self.name = name
        self.cron_expr = cron_expr
        self.func = func
        self.args = args
        self.kwargs = kwargs or {}
        self.enabled = enabled
        self.status = JobStatus.STOPPED
        self.last_run = None
        self.next_run = None
        self.run_count = 0
        self.error_count = 0
        self.last_error = None
        # job 级元数据（_save_jobs 持久化；动态赋值改为显式声明）
        self.symbols: List[str] = []
        self.dry_run: bool = True
        self.exchange: str = "hyperliquid"
        self.job_type: str = "scan"
        self._thread = None
        self._stop_event = threading.Event()

    def _calculate_next_run(self) -> Optional[datetime]:
        if not HAS_CRONITER:
            return None
        try:
            cron = croniter.croniter(self.cron_expr, datetime.now())
            return cron.get_next(datetime)
        except Exception:
            return None

    def _run_once(self):
        try:
            self.status = JobStatus.RUNNING
            self.func(*self.args, **self.kwargs)
            self.run_count += 1
            self.last_run = datetime.now()
            self.last_error = None
            logger.info(f"Job '{self.name}' completed successfully")
        except Exception as e:
            self.error_count += 1
            self.last_error = str(e)
            logger.error(f"Job '{self.name}' failed: {e}")
        finally:
            self.status = JobStatus.STOPPED
            self.next_run = self._calculate_next_run()

    def _scheduler_loop(self):
        while not self._stop_event.is_set():
            if not self.enabled:
                time.sleep(5)
                continue

            now = datetime.now()
            if self.next_run and now >= self.next_run:
                self._run_once()

            sleep_time = 1
            if self.next_run:
                diff = (self.next_run - now).total_seconds()
                sleep_time = max(1, min(diff, 60))

            time.sleep(sleep_time)

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self.next_run = self._calculate_next_run()
        self._thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self._thread.start()
        logger.info(f"Job '{self.name}' started with cron: {self.cron_expr}")

    def stop(self):
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self.status = JobStatus.STOPPED
        logger.info(f"Job '{self.name}' stopped")

    def pause(self):
        self.enabled = False
        self.status = JobStatus.PAUSED

    def resume(self):
        self.enabled = True
        self.status = JobStatus.RUNNING

    def run_now(self):
        threading.Thread(target=self._run_once, daemon=True).start()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "cron_expr": self.cron_expr,
            "enabled": self.enabled,
            "status": self.status,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "next_run": self.next_run.isoformat() if self.next_run else None,
            "run_count": self.run_count,
            "error_count": self.error_count,
            "last_error": self.last_error,
        }


class DreamOSScheduler:
    """Dream OS 定时调度器"""

    def __init__(self, data_dir: Optional[str] = None):
        self.jobs: Dict[str, ScheduledJob] = {}
        self._running = False
        self._stop_event = threading.Event()
        self._history: List[Dict[str, Any]] = []
        self._history_lock = threading.Lock()
        self.data_dir = Path(data_dir or "./scheduler_data")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._load_history()
        self._load_jobs()

    def add_job(
        self,
        name: str,
        cron_expr: str,
        func: Callable,
        args: tuple = (),
        kwargs: Optional[Dict[str, Any]] = None,
        enabled: bool = True,
        run_now: bool = False,
    ) -> ScheduledJob:
        if name in self.jobs:
            self.remove_job(name)

        job = ScheduledJob(name, cron_expr, func, args, kwargs, enabled)
        self.jobs[name] = job

        if enabled:
            job.start()
        if run_now:
            job.run_now()

        self._save_jobs()
        return job

    def remove_job(self, name: str):
        if name in self.jobs:
            self.jobs[name].stop()
            del self.jobs[name]
            self._save_jobs()

    def get_job(self, name: str) -> Optional[ScheduledJob]:
        return self.jobs.get(name)

    def list_jobs(self) -> List[Dict[str, Any]]:
        return [job.to_dict() for job in self.jobs.values()]

    def start(self):
        self._running = True
        logger.info("Dream OS Scheduler started")

    def stop(self):
        self._running = False
        self._stop_event.set()
        for job in self.jobs.values():
            job.stop()
        self._save_history()
        logger.info("Dream OS Scheduler stopped")

    def pause_all(self):
        for job in self.jobs.values():
            job.pause()

    def resume_all(self):
        for job in self.jobs.values():
            job.resume()

    def run_all_now(self):
        for job in self.jobs.values():
            job.run_now()

    def add_scan_job(
        self,
        name: str,
        cron_expr: str,
        symbols: List[str],
        scan_func: Callable[[str], Any],
        enabled: bool = True,
    ) -> ScheduledJob:
        def _scan_all():
            # P0.6 修复: 历史记录与扫描执行解耦
            # (8/15 ENOSPC 事故中 _record_history 抛异常→except 内再次抛异常→
            #  整个 scan job 中断,剩余币种全部跳过)
            for symbol in symbols:
                try:
                    result = scan_func(symbol)
                    action = "scan"
                except Exception as e:
                    result = {"error": str(e)}
                    action = "scan_error"
                try:
                    self._record_history(symbol, action, result)
                except Exception as e:
                    logger.warning(f"历史记录写入失败(不影响扫描) {symbol}: {e}")

        if name in self.jobs:
            self.remove_job(name)
        job = ScheduledJob(name, cron_expr, _scan_all, (), {}, enabled)
        job.symbols = symbols
        self.jobs[name] = job
        if enabled:
            job.start()
        self._save_jobs()
        return job

    def _record_history(self, symbol: str, action: str, result: Any):
        record = {
            "timestamp": datetime.now().isoformat(),
            "symbol": symbol,
            "action": action,
            "result": result,
        }
        with self._history_lock:
            self._history.append(record)
            if len(self._history) > 1000:
                self._history = self._history[-1000:]
        self._save_history()

    def _save_history(self):
        history_file = self.data_dir / "scheduler_history.json"
        with self._history_lock:
            with open(history_file, "w") as f:
                json.dump(self._history, f, indent=2, default=str)

    def _load_history(self):
        history_file = self.data_dir / "scheduler_history.json"
        if history_file.exists():
            try:
                with open(history_file, "r") as f:
                    self._history = json.load(f)
            except Exception:
                self._history = []

    def _save_jobs(self):
        jobs_file = self.data_dir / "scheduler_jobs.json"
        jobs_data = []
        for job in self.jobs.values():
            jobs_data.append({
                "name": job.name,
                "cron_expr": job.cron_expr,
                "enabled": job.enabled,
                "symbols": getattr(job, "symbols", []),
                "dry_run": getattr(job, "dry_run", True),
                "exchange": getattr(job, "exchange", "hyperliquid"),
                "job_type": getattr(job, "job_type", "scan"),
            })
        with open(jobs_file, "w") as f:
            json.dump(jobs_data, f, indent=2)

    def _load_jobs(self):
        jobs_file = self.data_dir / "scheduler_jobs.json"
        if jobs_file.exists():
            try:
                with open(jobs_file, "r") as f:
                    jobs_data = json.load(f)
                for job_data in jobs_data:
                    name = job_data["name"]
                    cron_expr = job_data["cron_expr"]
                    enabled = job_data.get("enabled", True)
                    job_type = job_data.get("job_type", "scan")
                    symbols = job_data.get("symbols", [])
                    # 读取 job 级别的 dry_run / exchange 配置(默认 dry_run=True 安全兜底)
                    dry_run = job_data.get("dry_run", True)
                    exchange = job_data.get("exchange", "hyperliquid")

                    if job_type == "exit_check":
                        # P0-2: 离场检查任务
                        def _exit_check(_dr=dry_run, _ex=exchange):
                            from dreamos.cli.auto_trader import AutoTrader
                            trader = AutoTrader(dry_run=_dr, exchange=_ex)
                            try:
                                result = trader.run_exit_check_all()
                                # P0.5-B2: 错误必须显式告警,不得静默为 "0 个持仓"
                                if isinstance(result, dict) and result.get("error"):
                                    logger.warning(f"离场检查失败 (dry_run={_dr}, exchange={_ex}): {result.get('error')}")
                                    return result
                                logger.info(f"离场检查完成: {result.get('checked', 0)} 个持仓, {result.get('exits', 0)} 个离场, tpsl更新={result.get('tpsl_updated', 0)}")
                                return result
                            except Exception as e:
                                logger.warning(f"离场检查失败 (dry_run={_dr}, exchange={_ex}): {e}")
                                return {"error": str(e)}

                        self.add_job(name, cron_expr, _exit_check, enabled=enabled)
                        if name in self.jobs:
                            self.jobs[name].dry_run = dry_run
                            self.jobs[name].exchange = exchange
                            self.jobs[name].job_type = "exit_check"
                            # add_job 已用默认值保存过一次,这里用正确值重新保存
                            self._save_jobs()
                    elif job_type == "backtest":
                        # 回测评估任务
                        bt_interval = job_data.get("interval", "1h")
                        bt_budget = job_data.get("budget", "lean")
                        def _backtest(_symbols=symbols, _interval=bt_interval, _budget=bt_budget):
                            import subprocess
                            try:
                                # 兜底: job 配置漏 symbols 时用默认币种，避免 join("") → 报告全 0
                                bt_symbols = [s for s in _symbols if s and s.strip()] if _symbols else []
                                if not bt_symbols:
                                    bt_symbols = ["BTC", "ETH", "SOL"]
                                    logger.warning("backtest job 未配置 symbols，回退默认 BTC,ETH,SOL")
                                # P0.5-B1: 跨平台修复 — 用当前解释器+相对仓库路径,不再硬编码 Mac 路径
                                _arch_dir = str(Path(__file__).resolve().parent.parent.parent)
                                cmd = [
                                    sys.executable, "-m",
                                    "dreamos.cli.dreamos_backtester",
                                    "--symbols", ",".join(bt_symbols),
                                    "--interval", _interval,
                                    "--budget", _budget,
                                ]
                                result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800, cwd=_arch_dir)
                                logger.info(f"回测评估完成: {result.stdout[-200:] if result.stdout else 'no output'}")
                                return {"exit_code": result.returncode}
                            except Exception as e:
                                logger.warning(f"回测评估失败: {e}")
                                return {"error": str(e)}

                        self.add_job(name, cron_expr, _backtest, enabled=enabled)
                        if name in self.jobs:
                            self.jobs[name].job_type = "backtest"
                            self._save_jobs()
                    elif job_type == "optimize":
                        # 编排优化任务
                        opt_interval = job_data.get("interval", "1h")
                        def _optimize(_symbols=symbols, _interval=opt_interval):
                            import subprocess
                            try:
                                # P0.5-B1: 跨平台修复 — 用当前解释器+相对仓库路径,不再硬编码 Mac 路径
                                _arch_dir = str(Path(__file__).resolve().parent.parent.parent)
                                cmd = [
                                    sys.executable, "-m",
                                    "dreamos.cli.dreamos_backtester",
                                    "--symbols", ",".join(_symbols),
                                    "--interval", _interval,
                                    "--optimize",
                                ]
                                result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600, cwd=_arch_dir)
                                logger.info(f"编排优化完成: {result.stdout[-200:] if result.stdout else 'no output'}")
                                return {"exit_code": result.returncode}
                            except Exception as e:
                                logger.warning(f"编排优化失败: {e}")
                                return {"error": str(e)}

                        self.add_job(name, cron_expr, _optimize, enabled=enabled)
                        if name in self.jobs:
                            self.jobs[name].job_type = "optimize"
                            self._save_jobs()
                    elif job_type == "orchestrate":
                        # P2: F层驱动 —— OrchestratorV2 周期编排
                        # 完整五层流水线: A选币 → B易经 → C执行 → D路由 → E认知审查
                        # 状态/账本从磁盘恢复(持久化),seed用小时时间桶保证每周期卦象不重复
                        def _orchestrate(_symbols=symbols, _dr=dry_run, _ex=exchange):
                            try:
                                from dreamos.capabilities.trading.orchestrator_v2 import OrchestratorV2
                                import time as _time
                                hour_seed = int(_time.time() // 3600)
                                orch = OrchestratorV2(use_hermes=False, seed=hour_seed)
                                # job级 dry_run 直接落到 executor（不依赖环境变量）
                                orch.executor.dry_run = bool(_dr)
                                # PROP-20260816 模块2: V15 纯多门禁（马丁无固定止损,空头方向风险无限）
                                orch.executor.long_only = True

                                # A层币池接线: job配置 > coin_pool.json(每周选币cron产出) > 默认池
                                # PROP-20260816 模块2/4: V15路径仅消费多池(按合并分top6);
                                # 对冲候选=多/空池合并分top1; regime透传给对冲激活门禁
                                target_symbols = list(_symbols or [])
                                pool_source = "job_config"
                                pool_regime = ""
                                hedge_long_cand = None
                                hedge_short_cand = None
                                if not target_symbols:
                                    try:
                                        pools = orch.coin_selector._load_persisted_pools()
                                        if pools:
                                            from dreamos.capabilities.trading import coin_selector as _cs
                                            pool_regime = pools.get("regime", "")
                                            long_merged = _cs.merge_dynamic_scores(pools.get("long_pool", []))
                                            short_merged = _cs.merge_dynamic_scores(pools.get("short_pool", []))
                                            ordered = []
                                            for item in long_merged:  # 纯多: 仅取多池
                                                s = (item or {}).get("symbol", "")
                                                if s and s not in ordered:
                                                    ordered.append(s)
                                            target_symbols = ordered[:6]
                                            pool_source = pools.get("source", "coin_pool.json")
                                            if long_merged:
                                                hedge_long_cand = long_merged[0]
                                            if short_merged:
                                                hedge_short_cand = short_merged[0]
                                    except Exception as e:
                                        logger.warning(f"F层编排: 币池加载失败({e}), 回退默认池")
                                if not target_symbols:
                                    target_symbols = ["BTC", "ETH", "SOL"]
                                    pool_source = "default"
                                logger.info(f"F层编排启动: {len(target_symbols)}币种 {target_symbols} | 来源={pool_source}")
                                results = []
                                # PROP-20260816 P1: B层指标注入(修复F-1数据饥饿)
                                from dreamos.cli.auto_trader import AutoTrader
                                from dreamos.capabilities.trading.market_enrichment import enrich_market_data
                                try:
                                    trader = AutoTrader(dry_run=True, exchange=_ex)
                                except Exception as e:
                                    trader = None
                                    logger.warning(f"F层编排: AutoTrader创建失败({e}), 本周期回退0价驱动")
                                for sym in target_symbols:
                                    md = {"symbol": sym, "entry_price": 0.0, "close_price": 0.0}
                                    if trader is not None:
                                        try:
                                            md = enrich_market_data(sym, md, trader._fetch_market_data)
                                            if md.get("ma20"):
                                                logger.info(
                                                    f"F层编排 {sym}: 指标注入完成 ma5/10/20="
                                                    f"{md.get('ma5')}/{md.get('ma10')}/{md.get('ma20')} "
                                                    f"momentum={md.get('momentum_direction')} vol={md.get('volatility')}"
                                                )
                                        except Exception as e:
                                            logger.warning(f"F层编排 {sym}: 指标注入失败(降级): {e}")
                                    cr = orch.run_cycle(md)
                                    results.append({
                                        "symbol": sym,
                                        "cycle_id": cr.get("cycle_id"),
                                        "status": cr.get("status"),
                                        "direction": cr.get("signal", {}).get("direction"),
                                        "confidence": cr.get("signal", {}).get("confidence"),
                                        "position_status": cr.get("execution", {}).get("status"),
                                    })

                                # PROP-20260816 模块1: 已评估币的 B层 conf 回写动态排名层
                                try:
                                    from dreamos.capabilities.trading import coin_selector as _cs_w
                                    for r in results:
                                        if r.get("confidence") is not None:
                                            _cs_w.record_dynamic_score(
                                                r.get("symbol", ""),
                                                float(r.get("confidence") or 0.0),
                                                r.get("direction") or "",
                                            )
                                except Exception as e:
                                    logger.warning(f"F层编排: 动态分回写失败({e})")

                                # PROP-20260816 模块3/4: 对冲路径 — 先巡检存量对离场,再评估新对入场
                                hedge_report = {}
                                try:
                                    from dreamos.capabilities.trading.hedge_executor import HedgeExecutor
                                    hedge = HedgeExecutor(dry_run=bool(_dr))

                                    def _hedge_px(sym):
                                        if trader is None:
                                            return 0.0
                                        try:
                                            md_h = enrich_market_data(
                                                sym,
                                                {"symbol": sym, "entry_price": 0.0, "close_price": 0.0},
                                                trader._fetch_market_data,
                                            )
                                            return float(md_h.get("close_price") or md_h.get("entry_price") or 0.0)
                                        except Exception:
                                            return 0.0

                                    # 1) 存量对离场巡检（合并PnL ≥+4%/≤-6% 双腿同平）
                                    open_pair = hedge.get_open_pair()
                                    if open_pair is not None:
                                        px_open = {
                                            open_pair.long_symbol: _hedge_px(open_pair.long_symbol),
                                            open_pair.short_symbol: _hedge_px(open_pair.short_symbol),
                                        }
                                        hedge_report["exits"] = hedge.manage_exits(px_open)
                                    # 2) 新对入场评估（仅有币池来源且无存量对时）
                                    if hedge_long_cand and hedge_short_cand and not hedge.has_open_pair():
                                        ls = hedge_long_cand.get("symbol", "")
                                        ss = hedge_short_cand.get("symbol", "")
                                        # 长腿信号: 复用本周期 B层结果（多池top1必在 target_symbols 内）
                                        long_sig = next(
                                            (
                                                {"direction": r.get("direction") or "",
                                                 "confidence": float(r.get("confidence") or 0.0)}
                                                for r in results if r.get("symbol") == ls
                                            ),
                                            {"direction": "", "confidence": 0.0},
                                        )
                                        # 短腿信号: 对空池 top1 跑一次 B层（long_only 门禁兜底,
                                        # 即使 B层误发 SHORT 也不会被 V15 执行）
                                        try:
                                            md_s = {"symbol": ss, "entry_price": 0.0, "close_price": 0.0}
                                            if trader is not None:
                                                md_s = enrich_market_data(ss, md_s, trader._fetch_market_data)
                                            cr_s = orch.run_cycle(md_s)
                                            short_sig = {
                                                "direction": cr_s.get("signal", {}).get("direction") or "",
                                                "confidence": float(cr_s.get("signal", {}).get("confidence") or 0.0),
                                            }
                                            try:
                                                from dreamos.capabilities.trading import coin_selector as _cs_s
                                                _cs_s.record_dynamic_score(ss, short_sig["confidence"], short_sig["direction"])
                                            except Exception:
                                                pass
                                        except Exception as e:
                                            logger.warning(f"F层编排: 对冲短腿B层评估失败({e})")
                                            short_sig = {"direction": "", "confidence": 0.0}
                                        px_en = {ls: _hedge_px(ls), ss: _hedge_px(ss)}
                                        hedge_report["entry"] = hedge.evaluate_entry(
                                            hedge_long_cand, hedge_short_cand,
                                            long_sig, short_sig, pool_regime, px_en,
                                        )
                                    if hedge_report:
                                        logger.info(f"F层对冲路径: {hedge_report}")
                                except Exception as e:
                                    logger.warning(f"F层编排: 对冲路径失败({e})")

                                st = orch.get_status()
                                summary = "; ".join(
                                    f"{r['symbol']}:{r['direction']}({float(r['confidence'] or 0):.2f})/{r['position_status']}"
                                    for r in results
                                )
                                logger.info(
                                    f"F层编排完成: {len(results)}周期 [{summary}] "
                                    f"| 累计 cycles={st['total_cycles']} pnl={st['total_pnl']}"
                                )
                                return {"cycles": results, "status_summary": st, "hedge": hedge_report}
                            except Exception as e:
                                logger.warning(f"F层编排失败: {e}")
                                return {"error": str(e)}

                        self.add_job(name, cron_expr, _orchestrate, enabled=enabled)
                        if name in self.jobs:
                            self.jobs[name].dry_run = dry_run
                            self.jobs[name].exchange = exchange
                            self.jobs[name].job_type = "orchestrate"
                            self.jobs[name].symbols = symbols  # 防止 _save_jobs 丢失显式配置
                            self._save_jobs()
                    else:
                        # 默认: 扫描交易任务
                        def _scan_single(symbol: str, _dr=dry_run, _ex=exchange):
                            from dreamos.cli.auto_trader import AutoTrader
                            trader = AutoTrader(dry_run=_dr, exchange=_ex)
                            try:
                                return trader.run_auto_trade(symbol)
                            except Exception as e:
                                logger.warning(f"调度扫描 {symbol} 失败 (dry_run={_dr}, exchange={_ex}): {e}")
                                return {"error": str(e)}

                        if symbols:
                            job = self.add_scan_job(name, cron_expr, symbols, _scan_single, enabled=enabled)
                            if job is not None:
                                job.dry_run = dry_run
                                job.exchange = exchange
                                # add_scan_job 已用默认值保存过一次,这里用正确值重新保存
                                self._save_jobs()
                        else:
                            self.add_job(name, cron_expr, lambda: None, enabled=enabled)
            except Exception as e:
                logger.warning(f"加载调度任务失败: {e}")

    def get_history(self, symbol: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        with self._history_lock:
            results = self._history.copy()
            if symbol:
                results = [r for r in results if r.get("symbol") == symbol]
            return results[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        stats = {
            "total_jobs": len(self.jobs),
            "running_jobs": sum(1 for j in self.jobs.values() if j.status == JobStatus.RUNNING),
            "paused_jobs": sum(1 for j in self.jobs.values() if j.status == JobStatus.PAUSED),
            "total_runs": sum(j.run_count for j in self.jobs.values()),
            "total_errors": sum(j.error_count for j in self.jobs.values()),
            "history_count": len(self._history),
        }
        return stats

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


PRESET_CRON = {
    "every_minute": "* * * * *",
    "every_5_minutes": "*/5 * * * *",
    "every_15_minutes": "*/15 * * * *",
    "every_hour": "0 * * * *",
    "every_4_hours": "0 */4 * * *",
    "daily_9am": "0 9 * * *",
    "daily_9pm": "0 21 * * *",
    "weekly_monday": "0 9 * * 1",
}

DEFAULT_SYMBOLS = ["BTC", "ETH", "SOL", "AVAX", "LINK", "ARB", "OP", "MATIC"]