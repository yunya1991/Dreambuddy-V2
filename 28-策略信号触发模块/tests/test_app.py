"""28-策略信号触发模块 Flask API 测试"""
import json
import math
import os
import sys
from pathlib import Path

import pytest

# 确保 app 可导入
_MODULE_DIR = Path(__file__).resolve().parent.parent
if str(_MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(_MODULE_DIR))

from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# 健康检查
# ---------------------------------------------------------------------------

def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert data["module"] == "28-策略信号触发模块"
    assert "endpoints" in data


# ---------------------------------------------------------------------------
# 代币筛选主入口
# ---------------------------------------------------------------------------

def _make_btc_close():
    """生成模拟 BTC 收盘价序列。"""
    import random
    random.seed(42)
    base = 50000.0
    closes = {}
    ts = 1700000000000
    for i in range(50):
        base *= (1.0 + random.uniform(-0.01, 0.01))
        closes[ts + i * 3600_000] = round(base, 2)
    return closes


def _make_candidate(pair, corr_factor=1.0, beta_factor=1.0):
    """生成模拟候选币种。"""
    import random
    random.seed(hash(pair) & 0xFFFF)
    base = 100.0
    closes = {}
    ts = 1700000000000
    for i in range(50):
        base *= (1.0 + random.uniform(-0.01, 0.01) * corr_factor)
        closes[ts + i * 3600_000] = round(base, 2)
    return {"pair": pair, "close": closes}


def test_universe_screen_missing_candidates(client):
    r = client.post("/api/v1/universe/screen",
                    data=json.dumps({}),
                    content_type="application/json")
    assert r.status_code == 400
    assert r.get_json()["error"] == "missing_candidates"


def test_universe_screen_no_filter(client):
    """无过滤条件时所有候选通过。"""
    body = {
        "candidates": [
            _make_candidate("ETH/USDT"),
            _make_candidate("SOL/USDT"),
        ],
        "limit": 10,
    }
    r = client.post("/api/v1/universe/screen",
                    data=json.dumps(body),
                    content_type="application/json")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert data["stats"]["total"] == 2
    assert data["stats"]["passed"] == 2
    assert data["stats"]["rejected"] == 0


def test_universe_screen_with_beta_range(client):
    """beta 过滤：BTC 与自身相关性极高，应通过。"""
    btc_close = _make_btc_close()
    body = {
        "candidates": [
            {"pair": "BTC/USDT", "close": btc_close},
            _make_candidate("RANDOM/USDT", corr_factor=3.0),
        ],
        "beta_range": {"min": 0.0, "max": 100.0},
        "btc_close": btc_close,
        "limit": 10,
    }
    r = client.post("/api/v1/universe/screen",
                    data=json.dumps(body),
                    content_type="application/json")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert data["stats"]["passed"] >= 1


def test_universe_screen_with_corr_threshold(client):
    """相关性过滤：自身 BTC 应通过。"""
    btc_close = _make_btc_close()
    body = {
        "candidates": [
            {"pair": "BTC/USDT", "close": btc_close},
        ],
        "corr_threshold": 0.5,
        "btc_close": btc_close,
        "limit": 10,
    }
    r = client.post("/api/v1/universe/screen",
                    data=json.dumps(body),
                    content_type="application/json")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert data["stats"]["passed"] == 1
    assert data["passed"][0]["pair"] == "BTC/USDT"


# ---------------------------------------------------------------------------
# universe 纯函数 API
# ---------------------------------------------------------------------------

def test_universe_corr_pearson(client):
    xs = [1.0 + i * 0.1 for i in range(20)]
    ys = [2.0 + i * 0.2 for i in range(20)]
    body = {"xs": xs, "ys": ys, "method": "pearson"}
    r = client.post("/api/v1/universe/corr",
                    data=json.dumps(body),
                    content_type="application/json")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert data["corr"] is not None
    assert abs(data["corr"] - 1.0) < 0.01  # 完全线性相关


def test_universe_corr_insufficient(client):
    body = {"xs": [1.0, 2.0], "ys": [3.0, 4.0]}
    r = client.post("/api/v1/universe/corr",
                    data=json.dumps(body),
                    content_type="application/json")
    assert r.status_code == 400


def test_universe_beta_ok(client):
    import numpy as np
    # y = 2x + noise，beta 应接近 2
    rng = np.random.RandomState(42)
    x = rng.normal(0, 0.01, 100)
    y = 2.0 * x + rng.normal(0, 0.001, 100)
    body = {"x_ret": x.tolist(), "y_ret": y.tolist()}
    r = client.post("/api/v1/universe/beta",
                    data=json.dumps(body),
                    content_type="application/json")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert data["beta"] is not None
    assert abs(data["beta"] - 2.0) < 0.3


def test_universe_aliases_ok(client):
    r = client.get("/api/v1/universe/aliases?pair=BTC/USDT")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert "BTC/USDT" in data["aliases"]
    assert "BTCUSDT" in data["aliases"]


def test_universe_aliases_missing(client):
    r = client.get("/api/v1/universe/aliases")
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Freqtrade webhook
# ---------------------------------------------------------------------------

def test_webhook_entry_event(client):
    body = {
        "type": "entry",
        "pair": "BTC/USDT",
        "action": "buy",
        "price": 50000.0,
        "amount": 0.01,
        "strategy": "test_strategy",
        "tag": "tag_001",
    }
    r = client.post("/webhook/freqtrade",
                    data=json.dumps(body),
                    content_type="application/json")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert data["event_type"] == "entry"
    assert data["route"] == "strategy_signal_trigger"
    assert data["pair"] == "BTC/USDT"


def test_webhook_exit_event(client):
    body = {
        "type": "exit",
        "pair": "ETH/USDT",
        "action": "sell",
        "price": 3000.0,
        "amount": 1.0,
    }
    r = client.post("/webhook/freqtrade",
                    data=json.dumps(body),
                    content_type="application/json")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert data["event_type"] == "exit"


def test_webhook_status_event(client):
    body = {"type": "status", "pair": "BTC/USDT"}
    r = client.post("/webhook/freqtrade",
                    data=json.dumps(body),
                    content_type="application/json")
    assert r.status_code == 200
    data = r.get_json()
    assert data["event_type"] == "status"
    assert data["route"] == "heartbeat_record"


def test_webhook_empty_payload(client):
    """空 payload 应返回 400 empty_payload（not {} 为 True）。"""
    r = client.post("/webhook/freqtrade",
                    data=json.dumps({}),
                    content_type="application/json")
    assert r.status_code == 400
    data = r.get_json()
    assert data["ok"] is False
    assert data["error"] == "empty_payload"


def test_webhook_event_normalization(client):
    """测试事件类型归一化：buy → entry。"""
    body = {"type": "buy", "pair": "BTC/USDT", "action": "buy"}
    r = client.post("/webhook/freqtrade",
                    data=json.dumps(body),
                    content_type="application/json")
    assert r.status_code == 200
    data = r.get_json()
    assert data["event_type"] == "entry"  # 归一化


def test_webhook_query_events(client):
    """先发送事件再查询。"""
    # 发送一个 entry 事件
    body = {"type": "entry", "pair": "TEST/USDT", "action": "buy", "price": 1.0}
    client.post("/webhook/freqtrade",
                data=json.dumps(body),
                content_type="application/json")
    # 查询
    r = client.get("/api/v1/webhook/events?type=entry&limit=10")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert data["count"] >= 1
    assert data["events"][0]["type"] == "entry"


# ---------------------------------------------------------------------------
# 聚类
# ---------------------------------------------------------------------------

def test_universe_cluster_ok(client):
    import numpy as np
    rng = np.random.RandomState(42)
    candidates = []
    for i in range(10):
        ret = rng.normal(0, 0.01, 30).tolist()
        candidates.append({"pair": f"COIN{i}/USDT", "ret": ret})
    body = {"candidates": candidates, "k": 3}
    r = client.post("/api/v1/universe/cluster",
                    data=json.dumps(body),
                    content_type="application/json")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert len(data["labels"]) == 10
    assert data["k"] == 3


def test_universe_cluster_insufficient(client):
    body = {"candidates": [{"pair": "A", "ret": [0.01] * 5}], "k": 5}
    r = client.post("/api/v1/universe/cluster",
                    data=json.dumps(body),
                    content_type="application/json")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is False
