"""data-center CLI — Typer 命令行入口，对齐 TECHNICAL_DESIGN.md §5.3。

用法：
  data-center fetch macro --series FEDFUNDS --source fred
  data-center list collectors
  data-center crawl --config sites.yaml        # M3 实现
  data-center schedule --cron "0 * * * *" --task "..."
  data-center monitor status                   # M5：调用统计汇总
  data-center monitor health                   # M5：所有 collector 健康采样
  data-center monitor alerts --last 20         # M5：最近告警
"""
from __future__ import annotations

import json
import os
from typing import Optional

import typer

from data_center.core.dispatcher import DataCenter

app = typer.Typer(help="DataBuddy 数据获取中心 CLI", no_args_is_help=True)
monitor_app = typer.Typer(help="监控与健康检查（M5）", no_args_is_help=True)
app.add_typer(monitor_app, name="monitor")
# 进程内共享的 DataCenter（同一 CLI 会话内）
_DC_SINGLETON: Optional[DataCenter] = None


def _get_dc() -> DataCenter:
    """同一 CLI 进程内共享 DataCenter，确保 monitor status 可以看到 fetch 产生的 metric。"""
    global _DC_SINGLETON
    if _DC_SINGLETON is None:
        _DC_SINGLETON = DataCenter()
    return _DC_SINGLETON


@app.command()
def fetch(
    category: str = typer.Argument(..., help="数据域：macro/finance/chain/news/web"),
    series: Optional[str] = typer.Option(None, help="序列 ID（macro 用，如 FEDFUNDS）"),
    source: Optional[str] = typer.Option(None, help="数据源，如 fred/akshare/ccxt"),
    symbol: Optional[str] = typer.Option(None, help="交易对/标的（chain/finance 用）"),
    topic: Optional[str] = typer.Option(None, help="主题（news 用）"),
    config: Optional[str] = typer.Option(None, "--config", help="爬虫配置文件（web 用）"),
) -> None:
    """采集数据。"""
    dc = _get_dc()
    params: dict = {}
    for k, v in (
        ("series", series), ("source", source),
        ("symbol", symbol), ("topic", topic), ("config", config),
    ):
        if v is not None:
            params[k] = v
    recs = dc.fetch(category, **params)
    out = [
        {
            "source": r.source, "category": r.category, "sub_category": r.sub_category,
            "timestamp": r.timestamp, "metrics": r.metrics,
            "events": r.events, "timeseries": r.timeseries,
        }
        for r in recs
    ]
    typer.echo(json.dumps(out, ensure_ascii=False, default=str))


@app.command(name="list")
def list_(what: str = typer.Argument("collectors", help="列出对象，默认 collectors")) -> None:
    """列出已注册采集器等。"""
    if what != "collectors":
        typer.echo(f"未知 list 目标: {what}")
        raise typer.Exit(code=1)
    dc = _get_dc()
    for category, source in dc.list_collectors():
        typer.echo(f"{source}\t{category}")


@app.command()
def crawl(
    config: str = typer.Option(..., "--config", help="sites.yaml 路径"),
    site: Optional[str] = typer.Option(None, "--site", help="指定站点名，不指定则爬取全部 enabled 站点"),
    list_sites: bool = typer.Option(False, "--list-sites", help="仅列出配置中的站点名"),
) -> None:
    """爬虫轨：按 sites.yaml 配置爬取，输出 DataRecord JSON。"""
    from data_center.crawler.runner import CrawlerRunner

    runner = CrawlerRunner(config_path=config)
    if list_sites:
        for name in runner.list_sites():
            typer.echo(name)
        return
    # 爬虫走 web 分类 → 通过 DataCenter.fetch(category="web") 进入埋点链路
    dc = _get_dc()
    recs = dc.fetch("web", config=config, site=site)
    out = [
        {
            "source": r.source, "category": r.category, "sub_category": r.sub_category,
            "timestamp": r.timestamp, "metrics": r.metrics,
            "events": r.events, "timeseries": r.timeseries,
        }
        for r in recs
    ]
    typer.echo(json.dumps(out, ensure_ascii=False, default=str))


@app.command()
def schedule(
    cron: str = typer.Option(..., "--cron", help="cron 表达式"),
    task: str = typer.Option(..., "--task", help="任务内容"),
) -> None:
    """定时调度（后续阶段实现）。"""
    typer.echo(f"schedule: 未实现 cron={cron} task={task}")


# ---------------------------------------------------------------------------
# monitor 子命令（M5）
# ---------------------------------------------------------------------------
@monitor_app.command("status")
def monitor_status(window_sec: Optional[int] = typer.Option(None, "--window", help="时间窗口秒数，默认全部")) -> None:
    """打印 DataCenter 调用统计汇总表格（进程内共享）。"""
    from data_center.monitoring.alerting import AlertLevel

    dc = _get_dc()
    summary = dc.monitoring.metrics.summary(window_sec=window_sec)
    if not summary:
        typer.echo("（暂无调用统计，先运行 fetch 命令触发）")
        return

    header = f"{'SOURCE':<12} {'CATEGORY':<10} {'TOTAL':>5} {'OK':>4} {'ERR':>4} {'AVG(ms)':>8} {'RECORDS':>8}"
    typer.echo(header)
    typer.echo("-" * len(header))
    for (src, cat), v in sorted(summary.items()):
        typer.echo(
            f"{src:<12} {cat:<10} {v['total']:>5} "
            f"{v['ok_count']:>4} {v['error_count']:>4} "
            f"{v['avg_duration_ms']:>8.2f} {v['total_records']:>8}"
        )


@monitor_app.command("health")
def monitor_health() -> None:
    """跑一次所有内置 collector 健康采样（mock 友好，缺 Key 自动降级）。"""
    dc = _get_dc()
    all_ = dc.list_collectors()
    if not all_:
        typer.echo("（没有已注册的 collector）")
        return

    # 每个 collector 给一组合理的默认 params
    DEFAULT_PARAMS = {
        ("macro", "fred"): {"series": "FEDFUNDS"},
        ("finance", "yfinance"): {"symbol": "AAPL"},
        ("chain", "ccxt"): {"symbol": "BTC/USDT", "timeframe": "1h", "limit": 2},
        ("chain", "etherscan"): {"address": "0x0000000000000000000000000000000000000000"},
        ("chain", "defillama"): {"route": "chains"},
        ("news", "feedparser"): {"url": "https://hnrss.org/frontpage"},
        ("news", "rsshub"): {"route": "/"},
        ("news", "tavily"): {"query": "test"},
        ("news", "gdelt"): {"query": "test"},
    }

    typer.echo(f"{'CATEGORY/SOURCE':<26} {'AVAILABLE':>9} {'STATUS':<8} {'COUNT':>5} {'MSG'}")
    typer.echo("-" * 80)
    for category, source in all_:
        params = dict(DEFAULT_PARAMS.get((category, source), {}))
        params["source"] = source
        # is_available 检查（仅 collector 实例层面）
        available = "N/A"
        cls = dc.registry.get(category, source)
        try:
            inst = cls(config=dc.config)
            available = "YES" if inst.is_available() else "NO KEY"
        except Exception:
            available = "ERR"

        try:
            recs = dc.fetch(category, **params)
            status = "OK"
            count = len(recs)
            msg = ""
        except Exception as exc:
            status = "ERROR"
            count = 0
            msg = f"{type(exc).__name__}: {exc}"[:50]

        typer.echo(
            f"{category + '/' + source:<26} {available:>9} "
            f"{status:<8} {count:>5} {msg}"
        )


@monitor_app.command("alerts")
def monitor_alerts(
    last: int = typer.Option(20, "--last", "-n", help="读取最近 N 条"),
    alerts_file: Optional[str] = typer.Option(
        None, "--file", "-f", help="告警 NDJSON 文件路径，默认读环境变量 DATA_CENTER_ALERTS_FILE"
    ),
) -> None:
    """读取 FileAlertChannel 文件的最近 N 条告警。"""
    from data_center.monitoring.alerting import FileAlertChannel

    path = alerts_file or os.environ.get("DATA_CENTER_ALERTS_FILE")
    if not path:
        typer.echo("未指定 --file 且未设置 DATA_CENTER_ALERTS_FILE 环境变量。")
        typer.echo("提示：以 `DATA_CENTER_ALERTS_FILE=/tmp/alerts.ndjson data-center fetch ...` 启动将自动落文件。")
        raise typer.Exit(code=1)
    ch = FileAlertChannel(path)
    rows = ch.tail(last)
    if not rows:
        typer.echo("（暂无告警记录）")
        return
    for r in rows:
        ts = r.get("ts", "")
        lvl = r.get("level", "")
        title = r.get("title", "")
        msg = r.get("message", "")
        tags = " ".join(r.get("tags", []))
        typer.echo(f"{ts} [{lvl:<8}] {title} | {msg} | tags: {tags}")


# ---------------------------------------------------------------------------
# fivedomain 子命令（易经推理五计庙算数据采集）
# ---------------------------------------------------------------------------
@app.command(name="fivedomain")
def fivedomain(
    classes: str = typer.Option(
        "all", "--class", help="资产类：all | crypto_usdt | us_stock | precious_metal（多类用逗号分隔）"
    ),
    raw_json: bool = typer.Option(False, "--raw-json", help="直接打印 JSON（否则人类可读摘要）"),
) -> None:
    """一次性采集五维所需全部外部数据，按类输出 coin_data。喂给 FiveDomainFeatureComputer。"""
    import sys, os

    # 定位 11-易经推理系统/scripts/memory_l4，动态导入 FiveDomainFetcher
    _REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    _L4 = os.path.join(_REPO, "11-易经推理系统", "scripts", "memory_l4")
    if _L4 not in sys.path:
        sys.path.insert(0, _L4)

    try:
        from fivedomain_fetcher import FiveDomainFetcher, ASSET_CLASSES
    except Exception as e:  # pragma: no cover - 依赖缺失
        typer.echo(f"导入 FiveDomainFetcher 失败: {type(e).__name__}: {e}", err=True)
        raise typer.Exit(code=2)

    dc = _get_dc()
    fetcher = FiveDomainFetcher(data_center=dc)
    all_data = fetcher.fetch_coin_data()

    # 过滤选择的类
    if classes.strip().lower() == "all":
        chosen = list(ASSET_CLASSES)
    else:
        chosen = [c.strip() for c in classes.split(",") if c.strip() in ASSET_CLASSES]
        if not chosen:
            typer.echo(f"未知 --class 值：{classes}。可用：all / {', '.join(ASSET_CLASSES)}", err=True)
            raise typer.Exit(code=1)
    filtered = {c: all_data[c] for c in chosen}

    if raw_json:
        typer.echo(json.dumps(filtered, ensure_ascii=False, default=str, indent=2))
        return

    # 人类可读摘要
    typer.echo("=" * 72)
    typer.echo("  FiveDomainFetcher 采集摘要（喂给 FiveDomainFeatureComputer.coin_data）")
    typer.echo("=" * 72)
    for cls, coin in filtered.items():
        typer.echo(f"\n【{cls}】")
        # D 类道
        typer.echo("  ·道(D1~D10) 采集：")
        dao_keys = (
            "fedfunds_rate", "m2_yoy_pct", "fed_balance_sheet_trillion",
            "us_cpi_yoy_pct", "us_ppi_yoy_pct", "us_indpro_yoy_pct",
            "stablecoin_mcap_bln", "defi_tvl_bln", "gas_eth_gwei", "policy_sentiment_score",
        )
        for k in dao_keys:
            if k in coin:
                typer.echo(f"      - {k:<28s} = {coin[k]!r}")
        # T 类天
        typer.echo("  ·天(T1,T2,T4) 派生：")
        tian_keys = ("merrill_phase", "vix_close", "liquidity_score")
        for k in tian_keys:
            typer.echo(f"      - {k:<28s} = {coin.get(k)!r}")
        typer.echo(
            "  ·地(G1~G7)：cycle4y_t_rel / regime / spring_force_score / amplitude / ATR / FTD / MA200_dist "
            "→ 由本地行情派生（market_data_layer），不从 data_center 采集。"
        )
        typer.echo("  ·将/法：读 system_state（系统自省），不走外部采集。")
    typer.echo("")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
