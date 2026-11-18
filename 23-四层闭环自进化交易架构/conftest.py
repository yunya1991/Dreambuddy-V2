"""23 域测试隔离：写盘态一律落 tmp，禁止污染 runtime/。

未注入 outbox 的 EntryLoop/Dispatcher 会回落到默认生产路径
（runtime/execution_outbox.db、runtime/chain_events-*.jsonl），
pytest 跑一遍就会把测试单（ord-open / FAKE_REJECT）写进真实监控数据。
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_evolution_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("EVOLUTION_OUTBOX_DB", str(tmp_path / "execution_outbox.db"))
    monkeypatch.setenv("EVOLUTION_CHAIN_EVENTS_DIR", str(tmp_path / "chain_events"))
