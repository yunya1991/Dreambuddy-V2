"""Etherscan collector 测试 — 迁移自 flow_collector 链上段。

etherscan-python 薄封装，覆盖 gas/balance/whales 三种 kind + 巨鲸地址表 + 无 Key 降级。
"""
from data_center.collectors.chain.etherscan_collector import (
    EtherscanCollector,
    WHALE_ADDRESSES,
)
from data_center.core.contract import DataRecord

ETH_MOD = "data_center.collectors.chain.etherscan_collector.Etherscan"
BINANCE_HOT = "0x28C6c06298d514Db089934071355E5743bf21d60"


def test_whale_addresses_migrated():
    # 对齐 flow_collector WHALE_ADDRESSES_V1 的三个交易所热钱包
    assert WHALE_ADDRESSES["binance_hot"] == BINANCE_HOT
    assert WHALE_ADDRESSES["coinbase_hot"].startswith("0x5754")
    assert WHALE_ADDRESSES["kraken_hot"].startswith("0x2910")


def test_no_key_returns_empty(monkeypatch):
    monkeypatch.delenv("ETHERSCAN_API_KEY", raising=False)
    c = EtherscanCollector()
    assert c.is_available() is False
    assert c.fetch({"kind": "gas"}) == []


def test_fetch_gas(mocker):
    mock_es = mocker.patch(ETH_MOD).return_value
    mock_es.get_gas_oracle.return_value = {
        "ProposeGasPrice": "12", "SafeGasPrice": "10", "FastGasPrice": "15",
    }
    c = EtherscanCollector(config={"api_key": "fake"})
    recs = c.fetch({"kind": "gas"})
    assert len(recs) == 1
    r = recs[0]
    assert isinstance(r, DataRecord)
    assert r.source == "etherscan"
    assert r.category == "chain"
    assert r.sub_category == "gas"
    assert r.metrics["propose_gas"] == 12.0
    assert r.metrics["fast_gas"] == 15.0


def test_fetch_balance(mocker):
    mock_es = mocker.patch(ETH_MOD).return_value
    mock_es.get_eth_balance.return_value = "3000000000000000000"  # 3 ETH (wei)
    c = EtherscanCollector(config={"api_key": "fake"})
    recs = c.fetch({"kind": "balance", "address": BINANCE_HOT})
    assert len(recs) == 1
    r = recs[0]
    assert r.metrics["balance_ether"] == 3.0
    assert r.metrics["address"] == BINANCE_HOT


def test_fetch_whales(mocker):
    mock_es = mocker.patch(ETH_MOD).return_value
    mock_es.get_eth_balance.return_value = "1000000000000000000"  # 1 ETH
    c = EtherscanCollector(config={"api_key": "fake"})
    recs = c.fetch({"kind": "whales"})
    assert len(recs) == len(WHALE_ADDRESSES)  # 每地址一条记录
    assert all(r.metrics["balance_ether"] == 1.0 for r in recs)
