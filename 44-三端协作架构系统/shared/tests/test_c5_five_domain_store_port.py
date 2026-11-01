"""C5 第三批：five_domain_sqlite_reader 读路径 Store port 收编契约测试。

覆盖：
  - reader 源码不再出现 `sqlite3.connect(`（直连已集中到 _five_domain_store_port）；
  - 开关关闭（默认）与开关打开（FD_STORE_PORT=1）输出逐字段相等（行为零变化）；
  - port 路径 FAIL-OPEN（DB 缺失返回空 dict / 空批次）；
  - top10 同批次 id 区间语义（窗口外干扰行必须被排除）；
  - 只读约束：port.write 未开放；无模块级 sys.path.insert。
"""

import os
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "11-易经推理系统"))

from scripts.memory_l4 import _five_domain_store_port as port_mod  # noqa: E402
from scripts.memory_l4 import five_domain_sqlite_reader as reader_mod  # noqa: E402

READER_PATH = REPO_ROOT / "11-易经推理系统/scripts/memory_l4/five_domain_sqlite_reader.py"
PORT_PATH = REPO_ROOT / "11-易经推理系统/scripts/memory_l4/_five_domain_store_port.py"


def _mk_db(path: Path, rows) -> str:
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE records (id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, "
        "category TEXT, sub_category TEXT, metrics TEXT, raw TEXT, "
        "timeseries TEXT, timestamp INTEGER)"
    )
    for src, cat, sub, metrics, raw, ts in rows:
        conn.execute(
            "INSERT INTO records (source, category, sub_category, metrics, raw, timestamp) "
            "VALUES (?,?,?,?,?,?)",
            (src, cat, sub, metrics, raw, ts),
        )
    conn.commit()
    conn.close()
    return str(path)


def _seed(tmp_path: Path) -> str:
    p = tmp_path / "dc.db"
    rows = [
        ("fred", "macro", "FEDFUNDS", '{"value": 4.33}', "{}", 100),
        ("fred", "macro", "FEDFUNDS", '{"value": 4.10}', "{}", 200),
        ("fred", "macro", "CPIAUCSL", '{"value": 3.1}', "{}", 200),
        ("yfinance", "market", "^VIX", '{"price": 18.2}', "{}", 250),
        ("theblockbeats_dataview", "emotion", "signal", '{"overall": 0.6}', "{}", 300),
        (
            "theblockbeats_dataview",
            "onchain",
            "top10_inflow_di",
            '{"symbol": "BTC", "inflow_usd": 1200, "inflow_text": "1.2K", "rank": 1}',
            "{}",
            400,
        ),
        (
            "theblockbeats_dataview",
            "onchain",
            "top10_inflow_di",
            '{"symbol": "ETH", "inflow_usd": 800, "inflow_text": "800", "rank": 2}',
            "{}",
            401,
        ),
        # 窗口外干扰行：间隔 > 50 条（模拟上一批次）
        (
            "theblockbeats_dataview",
            "onchain",
            "top10_inflow_di",
            '{"symbol": "OLD", "inflow_usd": 5000, "inflow_text": "5K", "rank": 1}',
            "{}",
            460,
        ),
    ]
    return _mk_db(p, rows)


def _run_macro(db_path: str, flag: bool):
    old = os.environ.get("FD_STORE_PORT")
    if flag:
        os.environ["FD_STORE_PORT"] = "1"
    else:
        os.environ.pop("FD_STORE_PORT", None)
    try:
        return reader_mod.read_macro_from_sqlite(db_path)
    finally:
        if old is None:
            os.environ.pop("FD_STORE_PORT", None)
        else:
            os.environ["FD_STORE_PORT"] = old


# ── 直连已消除 ────────────────────────────────────────────────────────────
def test_reader_has_no_direct_sqlite_connect():
    src = READER_PATH.read_text(encoding="utf-8")
    assert "sqlite3.connect(" not in src
    assert "import sqlite3" not in src


# ── 行为零变化：两种模式输出逐字段相等 ────────────────────────────────────
def test_port_mode_equals_legacy_output(tmp_path):
    db = _seed(tmp_path)
    legacy = _run_macro(db, flag=False)
    ported = _run_macro(db, flag=True)
    assert legacy == ported
    assert legacy, "种子数据必须产出非空结果，否则等价断言无意义"


def test_legacy_is_default_when_switch_unset(tmp_path, monkeypatch):
    db = _seed(tmp_path)
    monkeypatch.delenv("FD_STORE_PORT", raising=False)
    # 默认 legacy：即使 port 助手整体故障也不影响结果
    monkeypatch.setattr(
        port_mod, "RecordsStorePort", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    assert _run_macro(db, flag=False)
    assert _run_macro(db, flag=True) == {}  # port 故障 FAIL-OPEN 返回部分 dict（无 rows）


# ── FAIL-OPEN ────────────────────────────────────────────────────────────
def test_missing_db_returns_empty_dict(tmp_path):
    assert _run_macro(str(tmp_path / "nope.db"), flag=False) == {}
    assert _run_macro(str(tmp_path / "nope.db"), flag=True) == {}


def test_port_health_and_unknown_table(tmp_path):
    port = port_mod.RecordsStorePort(_seed(tmp_path))
    assert port.health()["ok"] is True
    assert port.query("other", limit=1)["error_code"] == "unknown_table"
    assert port.query("records", filters={"source": "__none__"})["count"] == 0


# ── top10 同批次 id 区间语义 ──────────────────────────────────────────────
def test_top10_batch_window_filter(tmp_path):
    db = _seed(tmp_path)
    top, rows = port_mod.fetch_top10_inflow_batch(
        db, "theblockbeats_dataview", "top10_inflow_di", window=1
    )
    assert top is not None
    ids = [int(r["id"]) for r in rows]
    assert len(ids) == 2, f"窗口外干扰行必须被排除，实际 {ids}"
    assert max(ids) == int(top["id"])
    assert min(ids) == int(top["id"]) - 1


def test_top10_batch_default_window_keeps_all(tmp_path):
    top, rows = port_mod.fetch_top10_inflow_batch(
        _seed(tmp_path), "theblockbeats_dataview", "top10_inflow_di", window=50
    )
    assert top is not None
    assert len(rows) == 3


def test_top10_empty_source(tmp_path):
    top, rows = port_mod.fetch_top10_inflow_batch(
        _seed(tmp_path), "theblockbeats_dataview", "__absent__"
    )
    assert (top, rows) == (None, [])


# ── 只读红线 ─────────────────────────────────────────────────────────────
def test_write_not_open():
    try:
        port_mod.RecordsStorePort("/tmp/x.db").write("records", data={"id": 1})
    except NotImplementedError:
        return
    raise AssertionError("C5 第三批只读收编不得开放 write")


def test_no_module_level_sys_path_insert():
    for p in (READER_PATH, PORT_PATH):
        for line in p.read_text(encoding="utf-8").splitlines():
            assert not line.lstrip().startswith("sys.path.insert"), f"{p.name}: {line}"
