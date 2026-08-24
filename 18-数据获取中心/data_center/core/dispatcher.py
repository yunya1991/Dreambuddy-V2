"""DataCenter — 统一对外入口，对齐 TECHNICAL_DESIGN.md §5.1。

DataCenter.fetch(category, source=..., ...) 路由到注册的 collector（SDK 轨）；
category="web" 走爬虫轨（M3 实现）。

M5 新增：通过 monitoring 参数注入 MonitoringBundle，实现调用统计、数据质量、告警三
件套的非侵入式埋点；monitoring 为 None 时启用默认 bundle。
"""
from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING, Optional

from dotenv import load_dotenv

from data_center.core.contract import DataRecord
from data_center.core.errors import SourceUnavailableError
from data_center.core.registry import Registry, default_registry

if TYPE_CHECKING:
    from data_center.monitoring import MonitoringBundle

# 默认 .env 路径：18-数据获取中心/config/.env（相对 dispatcher.py 上溯两级）
_DEFAULT_ENV = os.path.join(os.path.dirname(__file__), "..", "..", "config", ".env")


def _register_defaults(reg: Registry) -> None:
    """注册内置 collector（延迟 import 避免循环依赖）。"""
    from data_center.collectors.chain.ccxt_collector import CcxtCollector
    from data_center.collectors.chain.defillama_collector import DeFiLlamaCollector
    from data_center.collectors.chain.etherscan_collector import EtherscanCollector
    from data_center.collectors.finance.yfinance_collector import YFinanceCollector
    from data_center.collectors.macro.fred_collector import FredCollector
    from data_center.collectors.news.feedparser_collector import FeedparserCollector
    from data_center.collectors.news.gdelt_collector import GdeltCollector
    from data_center.collectors.news.rsshub_collector import RsshubCollector
    from data_center.collectors.news.tavily_collector import TavilyCollector

    reg.register("macro", "fred", FredCollector)
    reg.register("finance", "yfinance", YFinanceCollector)
    reg.register("chain", "ccxt", CcxtCollector)
    reg.register("chain", "etherscan", EtherscanCollector)
    reg.register("chain", "defillama", DeFiLlamaCollector)
    reg.register("news", "feedparser", FeedparserCollector)
    reg.register("news", "rsshub", RsshubCollector)
    reg.register("news", "tavily", TavilyCollector)
    reg.register("news", "gdelt", GdeltCollector)


class DataCenter:
    def __init__(
        self,
        config: dict | None = None,
        registry: Registry | None = None,
        env_path: str = _DEFAULT_ENV,
        monitoring: Optional["MonitoringBundle"] = None,
    ):
        # 加载 .env（存在才加载，override=True 让显式 env 仍可覆盖文件值）
        if env_path and os.path.exists(env_path):
            load_dotenv(env_path, override=True)
        self.config: dict = config or {}
        self.registry = registry if registry is not None else default_registry
        if registry is None:
            _register_defaults(self.registry)

        # M5: 监控三件套，默认启用（Lark 需显式配置）
        if monitoring is None:
            from data_center.monitoring import default_monitoring_bundle

            self.monitoring = default_monitoring_bundle()
        else:
            self.monitoring = monitoring

    # ------------------------------------------------------------------
    # 对外入口
    # ------------------------------------------------------------------
    def fetch(self, category: str, **params) -> list[DataRecord]:
        if category == "web":
            return self._fetch_monitored(category, "crawler", params, self._fetch_web)
        source = params.pop("source", None)
        if not source:
            raise SourceUnavailableError("fetch 需要 source 参数")
        cls = self.registry.get(category, source)

        def _collector_runner(inner_params: dict) -> list[DataRecord]:
            collector = cls(config=self.config)
            return collector.fetch(inner_params)

        return self._fetch_monitored(category, source, params, _collector_runner)

    def list_collectors(self) -> list[tuple[str, str]]:
        return self.registry.list()

    # ------------------------------------------------------------------
    # 爬虫轨
    # ------------------------------------------------------------------
    def _fetch_web(self, params: dict) -> list[DataRecord]:
        """爬虫轨：CrawlerRunner 读 sites.yaml → 分发 → DataRecord(category=web)。"""
        from data_center.crawler.runner import CrawlerRunner

        config_path = params.get("config")
        if not config_path:
            return []
        site_name = params.get("site")
        runner = CrawlerRunner(config_path=config_path)
        return runner.run(site_name)

    # ------------------------------------------------------------------
    # M5: 统一监控包装（before/after/error hooks）
    # ------------------------------------------------------------------
    def _fetch_monitored(
        self,
        category: str,
        source: str,
        params: dict,
        runner,
    ) -> list[DataRecord]:
        """在 runner 前后埋点：记录 metric + 质量检查 + 告警。"""
        bundle = self.monitoring
        start_ns = time.perf_counter_ns()
        try:
            result = runner(params)
        except Exception as exc:
            # —— 异常分支 ——
            duration_ms = (time.perf_counter_ns() - start_ns) / 1_000_000
            if bundle is not None:
                from data_center.monitoring.alerting import Alert, AlertLevel
                from data_center.monitoring.metrics import InvocationMetric

                metric = InvocationMetric.new_error(
                    source=source,
                    category=category,
                    duration_ms=duration_ms,
                    exc=exc,
                )
                bundle.metrics.record(metric)

                bundle.alerts.emit(Alert(
                    level=AlertLevel.ERROR,
                    title=f"采集异常: {source}/{category}",
                    message=(
                        f"{type(exc).__name__}: {exc}"
                        f" — duration_ms={round(duration_ms, 2)}"
                    ),
                    tags=["fetch_error", source, category, type(exc).__name__],
                ))
            raise

        # —— 正常分支 ——
        # H1 · Silver 中间件（Spec§E3）：EN_SILVER=true 时 result→清洗链→再回原链路
        # 默认 EN_SILVER=true（生产开启）；SILVER_FAIL_OPEN=true（fail-open兜底，秒级回滚）
        _en_silver = os.environ.get("EN_SILVER", "true").lower() not in {"0", "false", "off", "no"}
        if _en_silver and result:
            _fail_open = os.environ.get("SILVER_FAIL_OPEN", "true").lower() not in {"0", "false", "off", "no"}
            try:
                from data_cleaning.pipeline import DataCleaningPipeline, PipelineConfig
                _hours = int(os.environ.get("SILVER_FRESHNESS_HOURS", "48"))
                from datetime import timedelta as _td
                _pipe = DataCleaningPipeline(PipelineConfig(
                    enforce_hard_block=False,
                    fail_open=_fail_open,
                    freshness_threshold=_td(hours=_hours),
                ))
                _silver = _pipe.clean(result, source=source, category=category)
                # Gate passed → 用 Silver DF 还原 records + 写入 DAL；否则原 result
                if _silver.gate_passed:
                    from data_cleaning.adapters import cleaned_df_to_records as _to_recs
                    result = _to_recs(_silver.df, source=source, category=category,
                                       sub_category=result[0].sub_category if result else "")
                    # P1 打通：Silver → 19-DAL 写入（fail-open）
                    try:
                        from data_cleaning.dal_sink import DalSink
                        _sub = result[0].sub_category if result else ""
                        DalSink().write_silver(_silver, source=source,
                                               category=category, sub_category=_sub)
                    except Exception:  # noqa: BLE001
                        pass  # DAL 写入失败不影响主链路
            except Exception:  # noqa: BLE001
                if not _fail_open:
                    raise
                # fail-open: 保持原始 result 不变

        duration_ms = (time.perf_counter_ns() - start_ns) / 1_000_000
        if bundle is not None:
            from data_center.monitoring.alerting import Alert, AlertLevel
            from data_center.monitoring.metrics import InvocationMetric

            records_count = len(result)
            metric = InvocationMetric.new_ok(
                source=source,
                category=category,
                duration_ms=duration_ms,
                records_count=records_count,
            )
            bundle.metrics.record(metric)

            # 质量检查（数据契约 / 重复 / 新鲜度 / 空列表）
            # is_degraded = True → 空列表不触发 EMPTY_RESULT（允许级源）
            degraded_flag = self._is_source_degraded(source)
            issues = bundle.quality.check_all(
                result,
                source=source,
                category=category,
                is_degraded=degraded_flag,
            )
            for issue in issues:
                issue_level = (
                    AlertLevel.ERROR
                    if issue.code.value == "CONTRACT_INVALID"
                    else AlertLevel.WARNING
                )
                bundle.alerts.emit(Alert(
                    level=issue_level,
                    title=f"质量告警: {issue.code.value}",
                    message=issue.message,
                    tags=[
                        "quality",
                        issue.code.value,
                        source,
                        category,
                    ],
                ))

        return result

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------
    @staticmethod
    def _is_source_degraded(source: str) -> bool:
        """仅用于 EMPTY_RESULT allowlist 判断：glassnode / gdelt 等源通常可空。

        与 QualityChecker 的 allow_empty_degraded_sources 一致。
        """
        return source in {"glassnode", "gdelt"}
