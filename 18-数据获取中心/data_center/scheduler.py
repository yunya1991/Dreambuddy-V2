"""scheduler — 持续采集调度器。

设计原则：
  - 独立进程或挂 data_server 后台线程，定时跑 9 个 collector
  - 频率分级：chain 5min / finance 15min / macro 1h / news 30min
  - 每次采集：DataCenter.fetch → 落库 records + metric + quality_issues + 异常告警
  - 不依赖 dispatcher 内存监控（避免进程重启清零），自行计算 metric/quality 落 SQLite

用法：
  from data_center import DataCenter
  from data_center.scheduler import CollectionScheduler, CollectionTask
  from data_center.storage.sink_sqlite import SqliteSink

  dc = DataCenter()
  sink = SqliteSink("data_center.db")
  sched = CollectionScheduler(dc=dc, sink=sink, quality=QualityChecker(),
                                tasks=CollectionScheduler.default_tasks())
  sched.start()  # 后台线程
  sched.stop()   # 退出
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from data_center.core.contract import DataRecord
from data_center.monitoring.alerting import Alert, AlertLevel, AlertRouter
from data_center.monitoring.metrics import InvocationMetric
from data_center.monitoring.quality import QualityChecker
from data_center.storage.sink_sqlite import SqliteSink


@dataclass
class CollectionTask:
    """单个采集任务配置。"""

    name: str
    category: str  # macro/finance/chain/news
    source: str  # fred/yfinance/ccxt/etherscan/defillama/gdelt/feedparser/rsshub/tavily
    params: dict  # fetch 参数（series/symbol/route/kind/query 等）
    interval_sec: int  # 采集间隔（秒）


class CollectionScheduler:
    """持续采集调度器：按 task.interval_sec 定时跑 collector，结果落 SqliteSink。"""

    def __init__(
        self,
        *,
        dc,
        sink: SqliteSink,
        quality: QualityChecker,
        tasks: list[CollectionTask],
        alerts_router: Optional[AlertRouter] = None,
    ) -> None:
        self.dc = dc
        self.sink = sink
        self.quality = quality
        self.tasks = tasks
        self.alerts_router = alerts_router
        self._thread: Optional[threading.Thread] = None
        self._stop_flag = threading.Event()
        self._last_run: dict[str, float] = {}  # task.name -> last ts

    # ------------------------------------------------------------------
    # 单次采集
    # ------------------------------------------------------------------
    def collect_once(self, task: CollectionTask) -> InvocationMetric:
        """执行单次采集：fetch → 落库 records + metric + quality + 异常告警。"""
        start_ns = time.perf_counter_ns()
        try:
            records = self.dc.fetch(task.category, source=task.source, **task.params)
            duration_ms = (time.perf_counter_ns() - start_ns) / 1_000_000
            metric = InvocationMetric.new_ok(
                source=task.source, category=task.category,
                duration_ms=duration_ms, records_count=len(records),
            )
            # records 落库
            if records:
                self.sink.write(records)
            # metric 落库
            self.sink.write_metric(metric)
            # quality 检查 + 落库
            issues = self.quality.check_all(
                records, source=task.source, category=task.category,
            )
            if issues:
                self.sink.write_quality(metric, issues)
            return metric
        except Exception as exc:
            duration_ms = (time.perf_counter_ns() - start_ns) / 1_000_000
            metric = InvocationMetric.new_error(
                source=task.source, category=task.category,
                duration_ms=duration_ms, exc=exc,
            )
            # metric 落库
            self.sink.write_metric(metric)
            # alert 落库 + 外部告警
            alert = Alert(
                level=AlertLevel.ERROR,
                title=f"{task.source} 采集失败 [{task.name}]",
                message=f"{type(exc).__name__}: {exc}",
                tags=[task.source, task.category, task.name],
            )
            self.sink.write_alert(alert)
            if self.alerts_router is not None:
                try:
                    self.alerts_router.emit(alert)
                except Exception:
                    pass
            return metric

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------
    def start(self) -> None:
        """启动后台采集线程。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_flag.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="dc-scheduler")
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """停止后台线程。"""
        self._stop_flag.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def _run_loop(self) -> None:
        """主循环：每秒检查各 task 是否到期。"""
        now = time.time()
        for task in self.tasks:
            self._last_run[task.name] = 0.0  # 初始 0，启动后立即跑一次
        while not self._stop_flag.is_set():
            now = time.time()
            for task in self.tasks:
                if now - self._last_run.get(task.name, 0.0) >= task.interval_sec:
                    try:
                        self.collect_once(task)
                    except Exception:
                        pass  # collect_once 内部已处理异常，这里防兜底
                    self._last_run[task.name] = time.time()
            self._stop_flag.wait(1.0)  # 1 秒 tick

    # ------------------------------------------------------------------
    # 默认任务清单（9 collector × 频率分级）
    # ------------------------------------------------------------------
    @staticmethod
    def default_tasks() -> list[CollectionTask]:
        """默认采集任务清单，频率分级：
          - macro/fred 6 系列：1h
          - finance/yfinance (^VIX)：15min
          - chain/ccxt/defillama/etherscan：5min
          - news/gdelt/feedparser/rsshub/tavily：30min
        """
        tasks: list[CollectionTask] = []
        # ── macro/fred 6 系列（1h）──
        for s in ("FEDFUNDS", "M2NS", "WALCL", "CPIAUCSL", "PPIACO", "INDPRO"):
            tasks.append(CollectionTask(
                name=f"fred_{s.lower()}",
                category="macro", source="fred",
                params={"series": s},
                interval_sec=3600,
            ))
        # ── finance/yfinance ^VIX（15min）──
        tasks.append(CollectionTask(
            name="yfinance_vix",
            category="finance", source="yfinance",
            params={"symbol": "^VIX"},
            interval_sec=900,
        ))
        # ── chain/ccxt BTC ticker（5min）──
        tasks.append(CollectionTask(
            name="ccxt_btc",
            category="chain", source="ccxt",
            params={"symbol": "BTC/USDT"},
            interval_sec=300,
        ))
        # ── chain/defillama TVL（5min）──
        tasks.append(CollectionTask(
            name="defillama_tvl",
            category="chain", source="defillama",
            params={"route": "chains"},
            interval_sec=300,
        ))
        # ── chain/etherscan gas（5min）──
        tasks.append(CollectionTask(
            name="etherscan_gas",
            category="chain", source="etherscan",
            params={"kind": "gas"},
            interval_sec=300,
        ))
        # ── news/gdelt（30min）──
        tasks.append(CollectionTask(
            name="gdelt_btc",
            category="news", source="gdelt",
            params={"query": "bitcoin crypto"},
            interval_sec=1800,
        ))
        # ── news/feedparser（30min）──
        tasks.append(CollectionTask(
            name="feedparser_coindesk",
            category="news", source="feedparser",
            params={"url": "https://www.coindesk.com/arc/outboundfeeds/rss/"},
            interval_sec=1800,
        ))
        # ── news/rsshub（30min）──
        tasks.append(CollectionTask(
            name="rsshub_wallstreetcn",
            category="news", source="rsshub",
            params={"route": "wallstreetcn/news/global"},
            interval_sec=1800,
        ))
        # ── news/tavily（30min，需 key）──
        tasks.append(CollectionTask(
            name="tavily_policy",
            category="news", source="tavily",
            params={"query": "Fed monetary policy", "max_results": 5},
            interval_sec=1800,
        ))
        return tasks
