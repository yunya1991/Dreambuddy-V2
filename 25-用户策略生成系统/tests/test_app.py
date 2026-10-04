"""25-用户策略生成系统 Flask API 测试"""
import json
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
    assert data["module"] == "25-用户策略生成系统"
    assert "endpoints" in data


# ---------------------------------------------------------------------------
# 意图 → 策略设计
# ---------------------------------------------------------------------------

def test_gen_intent_ok(client):
    r = client.post("/api/v1/gen/intent",
                    data=json.dumps({"intent": "做多 BTC", "symbol": "BTC/USDT"}),
                    content_type="application/json")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert "trace_id" in data["result"]


def test_gen_intent_missing_intent(client):
    r = client.post("/api/v1/gen/intent",
                    data=json.dumps({}),
                    content_type="application/json")
    assert r.status_code == 400
    data = r.get_json()
    assert data["ok"] is False
    assert data["error"] == "missing_intent"


# ---------------------------------------------------------------------------
# 回测
# ---------------------------------------------------------------------------

def test_gen_backtest_ok(client):
    r = client.post("/api/v1/gen/backtest",
                    data=json.dumps({"strategy_id": "test_strat_001"}),
                    content_type="application/json")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert "metrics_summary" in data["result"]


def test_gen_backtest_missing_id(client):
    r = client.post("/api/v1/gen/backtest",
                    data=json.dumps({}),
                    content_type="application/json")
    assert r.status_code == 400
    assert r.get_json()["error"] == "missing_strategy_id"


# ---------------------------------------------------------------------------
# 基线对比
# ---------------------------------------------------------------------------

def test_gen_compare_user_wins(client):
    body = {
        "user_metrics": {
            "profit_factor": 1.5, "max_drawdown_pct": 8.0, "winrate": 55.0,
            "sharpe_ratio": 1.2, "trades": 100
        },
        "baseline_metrics": {
            "profit_factor": 1.3, "max_drawdown_pct": 10.0, "winrate": 50.0,
            "sharpe_ratio": 1.0, "trades": 100
        },
    }
    r = client.post("/api/v1/gen/compare",
                    data=json.dumps(body),
                    content_type="application/json")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert data["result"]["winner"] == "user"
    assert data["result"]["recommendation"] == "adopt_user"


def test_gen_compare_baseline_wins(client):
    body = {
        "user_metrics": {
            "profit_factor": 1.0, "max_drawdown_pct": 15.0, "winrate": 45.0,
            "sharpe_ratio": 0.5, "trades": 100
        },
        "baseline_metrics": {
            "profit_factor": 1.5, "max_drawdown_pct": 8.0, "winrate": 55.0,
            "sharpe_ratio": 1.2, "trades": 100
        },
    }
    r = client.post("/api/v1/gen/compare",
                    data=json.dumps(body),
                    content_type="application/json")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert data["result"]["winner"] == "baseline"


def test_gen_compare_missing_metrics(client):
    r = client.post("/api/v1/gen/compare",
                    data=json.dumps({"user_metrics": {}}),
                    content_type="application/json")
    assert r.status_code == 400
    assert r.get_json()["error"] == "missing_metrics"


def test_gen_compare_insufficient_trades(client):
    body = {
        "user_metrics": {"profit_factor": 1.5, "trades": 10},
        "baseline_metrics": {"profit_factor": 1.3, "trades": 100},
    }
    r = client.post("/api/v1/gen/compare",
                    data=json.dumps(body),
                    content_type="application/json")
    assert r.status_code == 200
    data = r.get_json()
    assert data["result"]["winner"] == "baseline"
    assert data["result"]["reason"] == "用户策略交易次数不足"


# ---------------------------------------------------------------------------
# 综合评分
# ---------------------------------------------------------------------------

def test_gen_score_ok(client):
    body = {
        "metrics": {
            "profit_factor": 1.5, "max_drawdown_pct": 8.0, "winrate": 55.0,
            "sharpe_ratio": 1.2, "trades": 100
        }
    }
    r = client.post("/api/v1/gen/score",
                    data=json.dumps(body),
                    content_type="application/json")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert isinstance(data["score"], float)
    assert 0.0 <= data["score"] <= 1.0


def test_gen_score_missing_metrics(client):
    r = client.post("/api/v1/gen/score",
                    data=json.dumps({}),
                    content_type="application/json")
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# 完整流水线
# ---------------------------------------------------------------------------

def test_gen_pipeline_ok(client):
    r = client.post("/api/v1/gen/pipeline",
                    data=json.dumps({"intent": "做多 BTC"}),
                    content_type="application/json")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True


def test_gen_pipeline_missing_intent(client):
    r = client.post("/api/v1/gen/pipeline",
                    data=json.dumps({}),
                    content_type="application/json")
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# 基线策略库
# ---------------------------------------------------------------------------

def test_baseline_list(client):
    r = client.get("/api/v1/baseline/list")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert "items" in data
    assert isinstance(data["items"], list)


def test_baseline_get_missing_id(client):
    r = client.get("/api/v1/baseline/get")
    assert r.status_code == 400


def test_baseline_get_not_found(client):
    r = client.get("/api/v1/baseline/get?strategy_id=nonexistent_001")
    assert r.status_code == 404


def test_baseline_metrics_missing_id(client):
    r = client.get("/api/v1/baseline/metrics")
    assert r.status_code == 400
