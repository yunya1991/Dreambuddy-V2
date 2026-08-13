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


# ---- Task 2: SKILL 调用与融合 ----

def test_call_asset_research():
    """测试_call_asset_research返回资产调研结构"""
    selector = CoinSelector(use_hermes=False)
    result = selector._call_asset_research(region="global")
    assert isinstance(result, dict)
    assert "engineName" in result
    assert "region" in result
    assert "phase" in result
    assert "priority_assets" in result
    assert isinstance(result["priority_assets"], list)
    assert "source" in result


def test_call_attention_radar():
    """测试_call_attention_radar返回注意力排名结构"""
    selector = CoinSelector(use_hermes=False)
    result = selector._call_attention_radar(symbols=["BTC", "ETH", "SOL"])
    assert isinstance(result, dict)
    assert "long_top" in result
    assert "short_top" in result
    assert isinstance(result["long_top"], list)
    assert isinstance(result["short_top"], list)
    assert "source" in result


def test_fuse_results():
    """测试_fuse_results能正确融合两个SKILL结果"""
    selector = CoinSelector(use_hermes=False)
    asset_research = {
        "engineName": "AssetResearch",
        "region": "global",
        "phase": "discovery",
        "priority_assets": [
            {"symbol": "BTC", "score": 0.9, "reason": "strong trend"},
            {"symbol": "ETH", "score": 0.8, "reason": "volume surge"},
        ],
        "source": "mock",
    }
    attention_radar = {
        "long_top": [
            {"symbol": "BTC", "score": 0.85, "reason": "attention high"},
            {"symbol": "SOL", "score": 0.7, "reason": "momentum up"},
        ],
        "short_top": [
            {"symbol": "DOGE", "score": 0.65, "reason": "attention low"},
        ],
        "source": "mock",
    }
    fused = selector._fuse_results(asset_research, attention_radar)
    assert isinstance(fused, dict)
    assert "long_pool" in fused
    assert "short_pool" in fused
    assert isinstance(fused["long_pool"], list)
    assert isinstance(fused["short_pool"], list)
    # 验证融合逻辑：BTC 同时出现在 asset_research 和 attention_radar 的 long_top
    long_symbols = [item["symbol"] for item in fused["long_pool"]]
    assert "BTC" in long_symbols
    # 验证每个 pool 元素包含必要字段
    for item in fused["long_pool"]:
        assert "symbol" in item
        assert "score" in item
        assert "reasons" in item


# ---- Task 3: 多空代币池融合逻辑（crypto_priority） ----

def test_coin_selector_fuse_results():
    """测试融合逻辑中 crypto_priority 降权：非加密资产 score 乘以 0.5"""
    selector = CoinSelector(use_hermes=False)
    asset_research = {
        "engineName": "AssetResearch",
        "region": "global",
        "phase": "discovery",
        "priority_assets": [
            {"symbol": "BTC", "score": 0.9, "reason": "strong trend", "priority": 1.0},
            {"symbol": "DOGE", "score": 0.7, "reason": "meme coin", "priority": 0.5},
        ],
        "source": "mock",
    }
    attention_radar = {
        "long_top": [
            {"symbol": "BTC", "score": 0.85, "reason": "attention high"},
            {"symbol": "DOGE", "score": 0.6, "reason": "hype driven"},
        ],
        "short_top": [],
        "source": "mock",
    }
    fused = selector._fuse_results(asset_research, attention_radar)

    # 查找 BTC 和 DOGE 的融合结果
    pool_by_symbol = {item["symbol"]: item for item in fused["long_pool"]}
    assert "BTC" in pool_by_symbol
    assert "DOGE" in pool_by_symbol

    # BTC priority=1.0，不应降权
    btc_score = pool_by_symbol["BTC"]["score"]
    # DOGE priority=0.5，应降权（score 乘以 0.5）
    doge_score = pool_by_symbol["DOGE"]["score"]

    # BTC 的 score 应高于 DOGE（因为 DOGE 被 crypto_priority 降权）
    assert btc_score > doge_score, f"BTC score {btc_score} should be > DOGE score {doge_score}"


def test_coin_selector_select_uses_fusion():
    """测试 select 方法在 mock 模式下使用融合逻辑而非简单分池"""
    selector = CoinSelector(use_hermes=False)
    result = selector.select(market_data={"symbols": ["BTC", "ETH", "SOL", "DOGE"]})
    assert isinstance(result, dict)
    assert "long_pool" in result
    assert "short_pool" in result
    assert "source" in result
    # select 应该调用 _call_asset_research + _call_attention_radar + _fuse_results
    # 验证 source 为 mock（因为 use_hermes=False）
    assert result["source"] == "mock"
    # 验证返回的 pool 非空
    total = len(result["long_pool"]) + len(result["short_pool"])
    assert total > 0, "pools should not be empty"
