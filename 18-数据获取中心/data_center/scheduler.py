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
        # ── news/theblockbeats_dataview（30min，Playwright 渲染 ~27s + 结构化解析）
        #    产出 26 条 DataRecord：道(M2/DXY/美债)、天(脉动指数+6个流动性信号)、
        #    将(Bitfinex多单+4个衍生品信号)、地(USDC/USDT溢价+Top10链上净流入)
        #    频率 30min 足以覆盖情绪/净流入/溢价的更新节奏；
        #    若需要更快可下调到 900s(15min)，但要考虑律动服务器响应慢。
        tasks.append(CollectionTask(
            name="theblockbeats_dataview",
            category="news", source="theblockbeats_dataview",
            params={},
            interval_sec=1800,
        ))
        # ── chain/panewslab route=all（4h，~17 次 HTTP，8 大板块 200+ metrics）
        #    panewslab 是易经战略层 D1~D10/T1/T4 proxy 的核心补充源：
        #    市场总览 / 周期判断 / ETF+机构 / 稳定币+RWA / 衍生品 / 交易所 /
        #    链上资金(treasury BTC+巨鲸+DeFi广度) / 美股+宏观 SP500/NASDAQ/VIX/10Y/DXY/DFF
        #    4h 更新频率足够覆盖日级战略决策（持仓/仓位），并避免 17 HTTP/次被限流。
        tasks.append(CollectionTask(
            name="panewslab_all",
            category="chain", source="panewslab",
            params={"route": "all"},
            interval_sec=14400,  # 4 小时
        ))
        # ── chain/stablecoin_transparency（Tether+USDC 官网真实供应量 + DeFiLlama 归档）
        #    用户要求"直接在官网抓取"，我们用官网__NEXT_DATA__+DeFiLlama官方透明度日档两级fallback。
        #    latest_snapshot 1h 更新 / top_n 4h（地维度稳定币双寡头份额观测）/ USDT&USDC 历史（1年初始化+周级刷新）
        tasks.append(CollectionTask(
            name="stablecoin_latest",
            category="chain", source="stablecoin_transparency",
            params={"route": "latest_snapshot"},
            interval_sec=3600,   # 1 小时
        ))
        tasks.append(CollectionTask(
            name="stablecoins_top10",
            category="chain", source="stablecoin_transparency",
            params={"route": "top_n", "n": 10},
            interval_sec=14400,  # 4 小时
        ))
        tasks.append(CollectionTask(
            name="stablecoin_hist_usdt_1y",
            category="chain", source="stablecoin_transparency",
            params={"route": "historical", "symbol": "USDT", "days": 365},
            interval_sec=604800,  # 7 天（周级刷新，初始化首跑会填充365天timeseries）
        ))
        tasks.append(CollectionTask(
            name="stablecoin_hist_usdc_1y",
            category="chain", source="stablecoin_transparency",
            params={"route": "historical", "symbol": "USDC", "days": 365},
            interval_sec=604800,
        ))
        # ── P0 扩窗 · 一次性初始化 backfill（≥60 天真五维回测窗）
        #    Panewslab/BlockBeats 仅抓当日快照，但 timeseries 携带 30/90 天趋势点；
        #    我们用更大 interval=24h(一次性) 的 backfill 任务先运行一次把 timeseries 宽度落到 Silver，
        #    stablecoin 历史同上拉满 365d，FRED/Macro 已按 series 自带全量历史。
        tasks.append(CollectionTask(
            name="panewslab_all_init_backfill",
            category="chain", source="panewslab",
            params={"route": "all"},
            interval_sec=86400,   # 24h 仅每日补一次，主要靠运行时落库的首条backfill拉到30/90天series
        ))
        tasks.append(CollectionTask(
            name="theblockbeats_dataview_init_backfill",
            category="news", source="theblockbeats_dataview",
            params={},
            interval_sec=86400,
        ))
        # ── news/odaily_newsflash 星球日报快讯（4h，与 panewslab route=all 对齐）
        #    Spec P0-2：政策维度主数据源，web-api 公开无反爬无鉴权，
        #    首屏20条+增量checkHasNew去重。4h 更新足够覆盖日级战略决策。
        tasks.append(CollectionTask(
            name="odaily_newsflash_latest",
            category="news", source="odaily_newsflash",
            params={"route": "latest"},
            interval_sec=14400,   # 4 小时
        ))
        # ── Phase A4：CoinFundamentalRanker 数据源（6h）──
        #    defillama protocols：全量 per-protocol TVL（Revenue Quality + TVL Growth 信号）
        tasks.append(CollectionTask(
            name="defillama_protocols",
            category="chain", source="defillama",
            params={"route": "protocols"},
            interval_sec=21600,  # 6h
        ))
        #    CoinGecko coin_info：核心币种 market_cap / supply（MC/Fees Mean Reversion 信号）
        for coin_id in ("bitcoin", "ethereum", "uniswap", "chainlink"):
            tasks.append(CollectionTask(
                name=f"coingecko_info_{coin_id}",
                category="coin", source="coingecko",
                params={"route": "coin_info", "coin_id": coin_id},
                interval_sec=21600,  # 6h
            ))
        #    yfinance stock_info：核心美股 PE / margins / ROE（Earnings Stability + PE Mean Reversion 信号）
        for symbol in ("NVDA", "AAPL", "MSFT"):
            tasks.append(CollectionTask(
                name=f"yfinance_stock_info_{symbol.lower()}",
                category="finance", source="yfinance",
                params={"route": "stock_info", "symbol": symbol},
                interval_sec=21600,  # 6h
            ))
        # ── 🆕 P0 数据源补全 ──────────────────────────────────────────
        #    覆盖 AGI 蓝图 L1 感知层核心缺口：情绪/资金流/衍生品/链上
        # ── chain/fear_greed（1h，alternative.me F&G 指数）
        #    每日更新1次但1h轮询确保及时获取，覆盖天维度情绪因子
        tasks.append(CollectionTask(
            name="fear_greed_latest",
            category="chain", source="fear_greed",
            params={"limit": 30},
            interval_sec=3600,
        ))
        # ── chain/mempool（5min，mempool.space BTC 链上基础数据）
        #    区块高度/Mempool状态/难度调整/矿池统计，覆盖地维度 D9 扩展
        tasks.append(CollectionTask(
            name="mempool_overview",
            category="chain", source="mempool",
            params={"kind": "overview"},
            interval_sec=300,
        ))
        # ── chain/bgeometrics（4h，BTC 链上深度指标）
        #    free tier 8次/小时 15次/天 → 每次取 top 3 (MVRV/SOPR/NUPL)
        #    覆盖 AGI L1 数据层 + BDSM E5/E6/E7 信号
        tasks.append(CollectionTask(
            name="bgeometrics_top3",
            category="chain", source="bgeometrics",
            params={"metrics": "all"},
            interval_sec=14400,  # 4h (free tier rate limit 友好)
        ))
        # ── chain/coinglass（5min，衍生品聚合数据）
        #    OI/Funding/清算/多空比，覆盖 AGI L1 感知层衍生品缺口
        #    stealthy mode 爬取，5min 适配高频衍生品数据
        tasks.append(CollectionTask(
            name="coinglass_oi",
            category="chain", source="coinglass",
            params={"pages": ["oi", "funding", "liquidations", "long_short"]},
            interval_sec=300,
        ))
        # ── finance/etf_flow（2h，farside ETF 每日净流入/流出）
        #    每日更新，2h 轮询确保美股收盘后及时获取
        #    覆盖 AGI Phase4.3 ETF 资金流信号 + 五维 D7
        #    stealthy mode 绕过 Cloudflare，频率不宜过高
        tasks.append(CollectionTask(
            name="etf_flow_daily",
            category="finance", source="etf_flow",
            params={},
            interval_sec=7200,  # 2h
        ))
        # ── 🆕 P1 数据源补全 ──────────────────────────────────────────
        #    补齐期权/机构持仓/稳定币深度/增强情绪/ETH链上
        # ── chain/deribit（15min，期权数据）
        #    Max Pain/DVOL/Put-Call Ratio，覆盖 AGI L1 感知层期权缺口
        tasks.append(CollectionTask(
            name="deribit_btc_options",
            category="chain", source="deribit",
            params={"currency": "BTC", "kind": "option"},
            interval_sec=900,  # 15min
        ))
        # ── finance/cftc_cot（24h，COT 持仓周报）
        #    机构/非商业持仓定位，每周二更新但每日轮询确保及时
        tasks.append(CollectionTask(
            name="cftc_cot_bitcoin",
            category="finance", source="cftc_cot",
            params={"market": "bitcoin"},
            interval_sec=86400,  # 24h
        ))
        # ── chain/defillama stablecoins（1h，稳定币总供应）
        #    覆盖五维 D7 稳定币市值 + AGI L1 流动性 proxy
        tasks.append(CollectionTask(
            name="defillama_stablecoins",
            category="chain", source="defillama",
            params={"route": "stablecoins"},
            interval_sec=3600,
        ))
        # ── chain/fear_greed_enhanced（1h，增强 F&G 含链上组件）
        #    与 alternative.me F&G 交叉验证
        tasks.append(CollectionTask(
            name="fear_greed_enhanced_latest",
            category="chain", source="fear_greed_enhanced",
            params={"action": "crypto"},
            interval_sec=3600,
        ))
        # ── chain/blockscout（5min，ETH 链上基础数据）
        #    区块号/总供应量/Gas，与 etherscan 互补
        tasks.append(CollectionTask(
            name="blockscout_overview",
            category="chain", source="blockscout",
            params={"kind": "overview"},
            interval_sec=300,
        ))
        # ── 🆕 P2 数据源补全 ──────────────────────────────────────────
        #    补齐零售情绪/排名交叉验证/新闻情绪/ETF备份/BTC链上备份
        # ── chain/google_trends（6h，搜索热度）
        #    "buy bitcoin"搜索热度，零售FOMO/恐慌指标（F&G组成因子10%）
        tasks.append(CollectionTask(
            name="google_trends_btc",
            category="chain", source="google_trends",
            params={"keyword": "buy bitcoin"},
            interval_sec=21600,  # 6h
        ))
        # ── chain/blockchain_info（5min，BTC链上基础数据备份）
        #    总流通量/难度/哈希率/24h交易数/市值，与mempool.space互补
        tasks.append(CollectionTask(
            name="blockchain_info_basics",
            category="chain", source="blockchain_info",
            params={},
            interval_sec=300,
        ))
        # ── coin/coinmarketcap（6h，币种排名+CMC F&G）
        #    与CoinGecko交叉验证排名，CMC F&G与alternative.me F&G交叉验证
        tasks.append(CollectionTask(
            name="cmc_listings",
            category="coin", source="coinmarketcap",
            params={"route": "listings", "limit": 20},
            interval_sec=21600,  # 6h
        ))
        # ── news/cryptopanic（30min，新闻+社区情绪投票）
        #    bullish/bearish投票，补充GDELT的per-coin新闻情绪
        tasks.append(CollectionTask(
            name="cryptopanic_btc",
            category="news", source="cryptopanic",
            params={"currencies": "BTC", "kind": "news"},
            interval_sec=1800,  # 30min
        ))
        # ── finance/sosovalue（1h，ETF可视化看板备份）
        #    与farside ETF flow交叉验证
        tasks.append(CollectionTask(
            name="sosovalue_etf",
            category="finance", source="sosovalue",
            params={},
            interval_sec=3600,
        ))
        return tasks
