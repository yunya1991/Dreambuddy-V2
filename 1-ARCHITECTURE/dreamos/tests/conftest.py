"""Pytest 测试隔离配置。

背景 (2026-08-15 P1-3 教训): 测试与生产共用 cli/scheduler_data/orchestrator_v2_state.json,
测试运行把伪造亏损(-45 USDT × N)写入生产状态,污染 W/L、累计PnL、贝叶斯计数。
本 conftest 将状态文件重定向到 pytest tmp 目录,测试永不触碰生产数据。
"""
import pytest


@pytest.fixture(autouse=True)
def isolate_dreamos_state(tmp_path, monkeypatch):
    """每个测试独立的状态文件目录(autouse,全测试套件生效)。"""
    from dreamos.capabilities.trading import orchestrator_v2, v15_executor

    monkeypatch.setattr(
        orchestrator_v2, "STATE_FILE", tmp_path / "orchestrator_v2_state.json"
    )
    monkeypatch.setattr(
        orchestrator_v2, "LESSONS_FILE", tmp_path / "cognitive_lessons.json"
    )
    monkeypatch.setattr(
        v15_executor, "POSITIONS_FILE", tmp_path / "v15_positions.json"
    )
    yield
