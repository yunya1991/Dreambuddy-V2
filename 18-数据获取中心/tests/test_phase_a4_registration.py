"""Phase A4 注册测试 — TDD 先红后绿。

验证：
- DataCenter 注册了 CoinGeckoCollector（category=coin, source=coingecko）
- Scheduler default_tasks 包含 Phase A 新增采集任务：
  - defillama_protocols（6h）
  - coingecko_info_{coin_id}（6h）
  - yfinance_stock_info_{symbol}（6h）
"""
import pytest

from data_center.core.dispatcher import DataCenter
from data_center.scheduler import CollectionScheduler, CollectionTask


# ---------------------------------------------------------------------------
# Dispatcher 注册
# ---------------------------------------------------------------------------

def test_dispatcher_registers_coingecko():
    """DataCenter 默认 registry 应包含 ("coin", "coingecko")。"""
    dc = DataCenter()
    collectors = set(dc.list_collectors())
    assert ("coin", "coingecko") in collectors


def test_dispatcher_registers_protocol_category_for_defillama():
    """DeFiLlama 仍注册为 ("chain", "defillama")，protocols route 通过 params 路由。"""
    dc = DataCenter()
    collectors = set(dc.list_collectors())
    assert ("chain", "defillama") in collectors


# ---------------------------------------------------------------------------
# Scheduler 新任务
# ---------------------------------------------------------------------------

def test_scheduler_includes_defillama_protocols_task():
    """default_tasks 包含 defillama_protocols 任务（6h）。"""
    tasks = CollectionScheduler.default_tasks()
    names = [t.name for t in tasks]
    assert "defillama_protocols" in names
    task = next(t for t in tasks if t.name == "defillama_protocols")
    assert task.category == "chain"
    assert task.source == "defillama"
    assert task.params == {"route": "protocols"}
    assert task.interval_sec == 21600  # 6h


def test_scheduler_includes_coingecko_tasks():
    """default_tasks 包含 CoinGecko coin_info 任务（核心币种，6h）。"""
    tasks = CollectionScheduler.default_tasks()
    names = [t.name for t in tasks]
    # 核心币种
    expected_coins = ("bitcoin", "ethereum", "uniswap", "chainlink")
    for coin_id in expected_coins:
        task_name = f"coingecko_info_{coin_id}"
        assert task_name in names, f"缺少任务: {task_name}"
        task = next(t for t in tasks if t.name == task_name)
        assert task.category == "coin"
        assert task.source == "coingecko"
        assert task.params == {"route": "coin_info", "coin_id": coin_id}
        assert task.interval_sec == 21600  # 6h


def test_scheduler_includes_yfinance_stock_info_tasks():
    """default_tasks 包含 yfinance stock_info 任务（核心美股，6h）。"""
    tasks = CollectionScheduler.default_tasks()
    names = [t.name for t in tasks]
    expected_stocks = ("NVDA", "AAPL", "MSFT")
    for symbol in expected_stocks:
        task_name = f"yfinance_stock_info_{symbol.lower()}"
        assert task_name in names, f"缺少任务: {task_name}"
        task = next(t for t in tasks if t.name == task_name)
        assert task.category == "finance"
        assert task.source == "yfinance"
        assert task.params == {"route": "stock_info", "symbol": symbol}
        assert task.interval_sec == 21600  # 6h


def test_scheduler_new_tasks_count():
    """Phase A4 新增任务总数 = 1(defillama_protocols) + 4(coingecko) + 3(yfinance) = 8。"""
    tasks = CollectionScheduler.default_tasks()
    new_names = [
        "defillama_protocols",
        "coingecko_info_bitcoin",
        "coingecko_info_ethereum",
        "coingecko_info_uniswap",
        "coingecko_info_chainlink",
        "yfinance_stock_info_nvda",
        "yfinance_stock_info_aapl",
        "yfinance_stock_info_msft",
    ]
    names = [t.name for t in tasks]
    for n in new_names:
        assert n in names, f"缺少任务: {n}"
