"""classic-system MVP 后端 — Flask 测试

验证 classic_system_server.py 提供 3 个 MVP 端点：
1. GET /health → {ok: true, service: "classic-system-mvp", backtrader: bool}
2. POST /automation/backtest/run → 桥接 DreamOS C3 节点 + backtrader 增强
3. POST /evaluation/gate/check → 简化门禁检查
其他端点 → 501 Not Implemented

设计原则：
- 仅开发/测试环境使用，不替代 ml_trade_service.py 生产服务
- 端口 8092（与前端 classic-system-client.ts 契约一致）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# 确保能 import classic_system_server
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))


def test_health_endpoint():
    """GET /health 返回 200 + 健康状态结构"""
    from classic_system_server import app

    client = app.test_client()
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["service"] == "classic-system-mvp"
    # backtrader 字段为 bool（True/False，取决于 backtrader 是否安装）
    assert isinstance(data["backtrader"], bool)


def test_backtest_run_endpoint():
    """POST /automation/backtest/run 返回 200 + 回测结果结构

    MVP 阶段接受最小输入（无 signals/klines 也能返回降级结果），
    返回 {ok: true, result: {...}} 结构。
    """
    from classic_system_server import app

    client = app.test_client()
    # 最小 payload（MVP 不要求完整字段）
    payload = {
        "strategy_name": "test_strategy",
        "timerange": "20260101-20260928",
    }
    resp = client.post(
        "/automation/backtest/run",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    # 回测结果应包含核心字段（即使是降级的）
    assert "result" in data
    result = data["result"]
    assert "metrics_summary" in result
    metrics = result["metrics_summary"]
    # 核心指标字段都应存在（值可能为 0）
    for field in ("total_trades", "win_rate", "sharpe_ratio", "max_drawdown"):
        assert field in metrics


def test_unimplemented_endpoint_returns_501():
    """未实现的端点应返回 501 Not Implemented"""
    from classic_system_server import app

    client = app.test_client()
    # 任选一个未实现的端点
    resp = client.get("/strategy/registry")
    assert resp.status_code == 501
    data = resp.get_json()
    assert data["ok"] is False
    assert "not implemented" in (data.get("error") or "").lower() or \
           "501" in (data.get("error") or "")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
