# -*- coding: utf-8 -*-
"""W0 契约冻结：Ticket 存储 → 通用 StorePort 适配单测。

依据 PROPOSAL-P0-D3 §4.10 / §9.1：
  - latest-wins 读取
  - 写幂等（显式 key / 内容推导两种）
  - Principal 硬门禁（D1）
  - 未知表 / 坏输入 FAIL-OPEN，不抛错
  - 只代理不复制（不产生第二份权威状态，ADR-2）
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.ticket_store import JsonlTicketStore  # noqa: E402

from dreambuddy_l0.adapters.ticket import TABLE, TicketStoreAdapter  # noqa: E402
from dreambuddy_l0.ports.principal import PrincipalMissingError  # noqa: E402

_PRINCIPAL = {"role": "agent_admin", "subject": "test"}


def _adapter(tmp_path):
    return TicketStoreAdapter(JsonlTicketStore(str(tmp_path)))


def _lines(tmp_path):
    path = tmp_path / "34-前端应用训练系统" / "dsh_tickets.jsonl"
    if not path.exists():
        return 0
    return len([ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()])


def test_write_then_read_is_latest_wins(tmp_path):
    a = _adapter(tmp_path)
    assert a.write(TABLE, data={"ticket_id": "TK-R1", "state": "live"}, _principal=_PRINCIPAL)
    assert a.write(TABLE, data={"ticket_id": "TK-R1", "state": "ended"}, _principal=_PRINCIPAL)

    got = a.read(TABLE, key="TK-R1")
    assert got["row"]["state"] == "ended"
    assert _lines(tmp_path) == 2  # append-only，未覆盖旧行


def test_read_unknown_table_and_not_found(tmp_path):
    a = _adapter(tmp_path)
    assert a.read("other", key="TK-R1") == {"row": None, "error_code": "unknown_table"}
    assert a.read(TABLE, key="TK-NONE") == {"row": None, "error_code": "not_found"}


def test_write_rejects_unknown_table_and_bad_data(tmp_path):
    a = _adapter(tmp_path)
    assert a.write("other", data={"ticket_id": "TK-R1"}, _principal=_PRINCIPAL) is False
    assert a.write(TABLE, data={"state": "live"}, _principal=_PRINCIPAL) is False
    assert _lines(tmp_path) == 0


def test_explicit_idempotency_key_suppresses_replay(tmp_path):
    a = _adapter(tmp_path)
    rec = {"ticket_id": "TK-R1", "state": "live"}
    assert a.write(TABLE, data=rec, idempotency_key="tk-R1-live", _principal=_PRINCIPAL)
    assert a.write(TABLE, data=rec, idempotency_key="tk-R1-live", _principal=_PRINCIPAL)
    assert _lines(tmp_path) == 1


def test_content_derived_idempotency_ignores_volatile_fields(tmp_path):
    a = _adapter(tmp_path)
    rec = {"ticket_id": "TK-R1", "state": "live", "stored_at": 100.0}
    assert a.write(TABLE, data=rec, _principal=_PRINCIPAL)
    # stored_at 变化不应视为新内容
    rec2 = {"ticket_id": "TK-R1", "state": "live", "stored_at": 200.0}
    assert a.write(TABLE, data=rec2, _principal=_PRINCIPAL)
    assert _lines(tmp_path) == 1
    # 状态变化必须写入（ticket_id 单独做幂等键会吞掉更新）
    assert a.write(TABLE, data={"ticket_id": "TK-R1", "state": "ended"}, _principal=_PRINCIPAL)
    assert _lines(tmp_path) == 2


def test_write_requires_principal(tmp_path):
    a = _adapter(tmp_path)
    try:
        a.write(TABLE, data={"ticket_id": "TK-R1", "state": "live"})
    except PrincipalMissingError:
        pass
    else:  # pragma: no cover
        raise AssertionError("missing principal should raise PrincipalMissingError")
    assert _lines(tmp_path) == 0


def test_query_filters_latest_values(tmp_path):
    a = _adapter(tmp_path)
    a.write(TABLE, data={"ticket_id": "TK-R1", "state": "live"}, _principal=_PRINCIPAL)
    a.write(TABLE, data={"ticket_id": "TK-R2", "state": "ended"}, _principal=_PRINCIPAL)
    a.write(TABLE, data={"ticket_id": "TK-R2", "state": "live"}, _principal=_PRINCIPAL)

    rows = a.query(TABLE, filters={"state": "live"})
    assert {r["ticket_id"] for r in rows["rows"]} == {"TK-R1", "TK-R2"}
    assert a.query("other")["error_code"] == "unknown_table"


def test_health_reports_single_table(tmp_path):
    a = _adapter(tmp_path)
    assert a.health()["ok"] is False  # 尚未写入
    a.write(TABLE, data={"ticket_id": "TK-R1", "state": "live"}, _principal=_PRINCIPAL)
    h = a.health()
    assert h["ok"] is True and h["tables"] == 1 and h["dialect"] == "jsonl-ticket"
