"""Pytest 测试隔离配置。

背景 (2026-08-15 P1-3 教训): 测试与生产共用 cli/scheduler_data/orchestrator_v2_state.json,
测试运行把伪造亏损(-45 USDT × N)写入生产状态,污染 W/L、累计PnL、贝叶斯计数。
本 conftest 将状态文件重定向到 pytest tmp 目录,测试永不触碰生产数据。
"""
import pytest


@pytest.fixture(autouse=True)
def isolate_dreamos_state(tmp_path, monkeypatch):
    """每个测试独立的状态文件目录(autouse,全测试套件生效)。"""
    from dreamos.capabilities.trading import orchestrator_v2
    from dreamos.cli import auto_trader

    monkeypatch.setattr(
        orchestrator_v2, "STATE_FILE", tmp_path / "orchestrator_v2_state.json"
    )
    monkeypatch.setattr(
        orchestrator_v2, "LESSONS_FILE", tmp_path / "cognitive_lessons.json"
    )
    # V15Executor 已改造为 14-V15 适配器，不再使用 POSITIONS_FILE
    # 持仓状态统一由 14-V15 v15_state.json 管理
    # PROP-20260816: 对冲账本 + 动态排名层隔离
    from dreamos.capabilities.trading import hedge_executor, coin_selector

    monkeypatch.setattr(
        hedge_executor, "HEDGE_POSITIONS_FILE", tmp_path / "hedge_positions.json"
    )
    monkeypatch.setattr(
        coin_selector, "DYNAMIC_SCORES_FILE", tmp_path / "pool_dynamic_scores.json"
    )
    # PROP-20260816 P2: 持仓快照隔离(防止测试写入生产 scheduler_data)
    monkeypatch.setattr(
        auto_trader.AutoTrader, "SNAPSHOT_DIR", tmp_path
    )
    yield
