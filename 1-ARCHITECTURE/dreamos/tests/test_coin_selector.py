"""CoinSelector 测试套件"""
import pytest
from pathlib import Path
import sys

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

from dreamos.capabilities.trading.coin_selector import CoinSelector


def test_coin_selector_initialization():
    """测试CoinSelector可正常初始化"""
    selector = CoinSelector()
    assert selector is not None
    assert hasattr(selector, "select")


def test_coin_selector_returns_pools():
    """测试select方法返回多空代币池结构"""
    selector = CoinSelector()
    result = selector.select(market_data={"symbols": ["BTC", "ETH"]})
    assert isinstance(result, dict)
    assert "long_pool" in result
    assert "short_pool" in result
    assert isinstance(result["long_pool"], list)
    assert isinstance(result["short_pool"], list)


def test_coin_selector_pool_format():
    """测试代币池中每个元素包含必要字段"""
    selector = CoinSelector()
    result = selector.select(market_data={"symbols": ["BTC"]})
    for pool_key in ("long_pool", "short_pool"):
        for item in result[pool_key]:
            assert "symbol" in item
            assert "score" in item
            assert "reasons" in item
